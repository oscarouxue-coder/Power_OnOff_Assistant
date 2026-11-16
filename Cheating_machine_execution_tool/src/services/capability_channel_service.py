"""Versioned channel transactions. File/model logic is independent of Tk widgets."""
from dataclasses import asdict, replace
from copy import deepcopy
import hashlib
import ipaddress
from pathlib import Path
import re
import uuid

from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore, DEFAULT_SUBNET_MASK
from line_check_assistant.network_ops import adapter_alias_from_display, static_ip_for_vlan
from line_check_assistant.paths import resolve_config_dir
from src.models.capabilities import CapabilitySpec, CapabilityError, fingerprint, object_schema
from src.services.capability_device_services import CHANNEL_PROPERTIES
from src.services.adapter_rename_service import validate_adapter_name, AdapterRenameService, synchronize_channel_adapter_names


class ChannelCapabilities:
    def __init__(self, service, tool_root, commit_callback=None):
        self.service, self.commit_callback = service, commit_callback
        self.rename_service = AdapterRenameService()
        self.store = ChannelConfigStore(resolve_config_dir(Path(tool_root)) / 'network_card_ip.ini')
        revision = dict(type='string', minLength=64, maxLength=64)
        service.registry.register(CapabilitySpec('channels.candidates', '读取本地通道候选与配置版本',
            '只读本项目全部候选及配置revision，候选不构成设备执行授权。新增选择/绑定须本地审阅，不改变当前会话范围。',
            object_schema(), self.read, sources=('local', 'gui')))
        service.registry.register(CapabilitySpec('channels.configure', '提交明确通道绑定配置',
            '复用原通道存储及IP派生。当前通道修改受现有范围约束；新绑定/全局管理IP/电源需本地审核，提交前复核GUI和文件版本。',
            object_schema(dict(CHANNEL_PROPERTIES, revision=revision, values=object_schema({
                'enabled': dict(type='boolean'), 'vlan_name': dict(type='string', maxLength=200),
                'serial_port': dict(type='string', maxLength=32)}),
                device_ip=dict(type='string', maxLength=64), power_serial_port=dict(type='string', maxLength=32)),
                ('channel_ids', 'revision', 'values')), self.configure, risk='modify', sources=('local', 'gui'),
            resource_scope=lambda a: self.prepare(a)['scope'], resource_requirements=('device-business', 'configuration')))
        service.registry.register(CapabilitySpec('channels.select', '设置本地通道勾选集合',
            '本地负责人审阅明确勾选集合后提交，空集合表示清除；不会授予当前AI会话新增DUT访问权限。',
            object_schema({'selected_channel_ids': dict(type='array', maxItems=16, uniqueItems=True,
                items=dict(type='integer', minimum=1, maximum=16)), 'revision': revision}, ('selected_channel_ids', 'revision')),
            self.select, risk='modify', sources=('local', 'gui'), resource_scope=lambda a: self.prepare(a, selecting=True)['scope'],
            resource_requirements=('device-business', 'configuration')))
        service.registry.register(CapabilitySpec('network.rename', '按网卡真实身份重命名并同步通道引用',
            '异步复用原重命名及GUID回读服务。目标GUID和新配置先经本地审核；不确定结果不重发、不自动改回名称。',
            object_schema({'channel_ids': dict(CHANNEL_PROPERTIES['channel_ids'], maxItems=1), 'revision': revision,
                'new_name': dict(type='string', minLength=1, maxLength=200)}, ('channel_ids', 'revision', 'new_name')),
            self.rename, risk='dangerous', execution_mode='job', sources=('local', 'gui'),
            resource_scope=lambda a: self.prepare_rename(a)['scope'], resource_requirements=('device-business', 'adapter', 'configuration')))

    def _file_hash(self):
        return hashlib.sha256(self.store.config_path.read_bytes()).hexdigest() if self.store.config_path.exists() else ''

    def state(self, snapshot=None):
        snapshot = snapshot if snapshot is not None else self.service.snapshot()
        return dict(channels=[dict(c) for c in snapshot['channels']], power_serial_port=snapshot.get('power_serial_port', ''),
                    device_ip=snapshot.get('device_ip', ''), file_sha256=self._file_hash())

    def read(self, arguments, authority):
        state = self.state()
        return dict(channels=state['channels'], power_serial_port=state['power_serial_port'],
                    device_ip=state['device_ip'], revision=fingerprint(state), device_authority_changed=False)

    def prepare_rename(self, arguments):
        before = self.state()
        if fingerprint(before) != arguments['revision']:
            raise CapabilityError('channel_configuration_changed', '通道配置已变化，未准备重命名')
        reason = self.rename_service.availability()
        if reason:
            raise CapabilityError('rename_unavailable', reason)
        section = 'channel_' + str(arguments['channel_ids'][0])
        channels = [ChannelConfig(**c) for c in before['channels']]
        channel = next((c for c in channels if c.section == section), None)
        if channel is None:
            raise CapabilityError('invalid_target', '目标通道不存在')
        old = adapter_alias_from_display(channel.adapter_alias or channel.vlan_name)
        new = validate_adapter_name(arguments['new_name'])
        adapters = self.rename_service.reader()
        matches = [a for a in adapters if a.alias.casefold() == old.casefold()]
        if len(matches) != 1 or not matches[0].interface_guid:
            raise CapabilityError('adapter_identity_required', '原网卡不存在、身份为空或不唯一')
        unchanged = old == new
        if not unchanged and any(a.alias.casefold() == new.casefold() for a in adapters):
            raise CapabilityError('adapter_name_exists', '新网卡名称已经存在，未修改')
        synchronize_channel_adapter_names(channels, section, old, new)
        after = dict(channels=[asdict(c) for c in channels], power_serial_port=before['power_serial_port'], device_ip=before['device_ip'])
        guid = matches[0].interface_guid
        scope = None if unchanged else dict(id='adapter-rename:' + fingerprint([guid, old, new, after]),
            interface_guid=guid, old_name=old, new_name=new, desired_configuration=deepcopy(after),
            purpose='重命名此物理网卡并同步项目引用；不改变当前AI会话的设备授权')
        before['adapter_options'] = [a.display_name for a in adapters]
        return dict(before=before, after=after, scope=scope, guid=guid, old=old, new=new,
                    unchanged=unchanged, revision=arguments['revision'])

    def rename(self, arguments, authority):
        prepared = self.prepare_rename(arguments)
        self.service.scopes.require(authority, prepared['scope'])
        if prepared['unchanged']:
            return dict(ok=True, state='skipped', effective_name=prepared['old'], dispatched=False)
        if self.commit_callback is None:
            raise CapabilityError('configuration_host_unavailable', '缺少可写主机配置适配，未重命名')
        def recheck():
            current = self.prepare_rename(arguments)
            if current['guid'] != prepared['guid'] or current['scope'] != prepared['scope']:
                raise CapabilityError('adapter_identity_changed', '准入前网卡身份或配置已变化，未重命名')
        def run(context):
            context.stop.checkpoint()
            def output(message):
                context.event('rename', message, dispatched='实际命令：' in message)
            result = self.rename_service.rename(prepared['old'], prepared['new'], output, expected_interface_guid=prepared['guid'])
            if not result.ok:
                return dict(ok=False, state='unknown' if result.uncertain else 'failed', message=result.message)
            prepared['after']['adapter_options'] = [a.display_name for a in result.adapters]
            try:
                commit = self.commit_callback(prepared)
                if isinstance(commit, dict) and commit.get('state') == 'saved_refresh_failed':
                    raise RuntimeError('配置保存后显示/资格刷新未完成')
            except Exception as exc:
                context.event('unknown', '网卡改名已由GUID回读确认，配置同步未完成，不自动改回或再次重命名')
                return dict(ok=False, state='unknown', adapter_renamed=True, error=str(exc),
                    interface_guid=prepared['guid'], old_name=prepared['old'], new_name=prepared['new'])
            return dict(ok=True, adapter_renamed=True, configuration_saved=True, interface_guid=prepared['guid'],
                        old_name=prepared['old'], new_name=prepared['new'])
        return self.service.jobs.start('network.rename', dict(arguments, interface_guid=prepared['guid'], old_name=prepared['old']), authority,
            ('device-business', 'channel:' + str(arguments['channel_ids'][0]),
             'adapter:' + prepared['old'].casefold(), 'adapter:' + prepared['new'].casefold(), 'configuration'),
            run, recheck=recheck)

    @staticmethod
    def _port(value):
        value = value.strip().upper()
        if value and not re.fullmatch(r'COM[1-9]\d*', value):
            raise CapabilityError('invalid_parameters', '串口必须为空或明确的COM编号')
        return value

    def prepare(self, arguments, selecting=False):
        before = self.state()
        if fingerprint(before) != arguments['revision']:
            raise CapabilityError('channel_configuration_changed', '界面或磁盘通道配置已变化，请读取当前版本后重新合并')
        channels = [ChannelConfig(**item) for item in before['channels']]
        indexed = {int(c.section.rsplit('_', 1)[1]): c for c in channels}
        requested = arguments['selected_channel_ids'] if selecting else arguments['channel_ids']
        if any(number not in indexed for number in requested):
            raise CapabilityError('invalid_target', '通道候选不存在，未修改任何配置')
        if selecting:
            channels = [replace(c, enabled=int(c.section.rsplit('_', 1)[1]) in requested) for c in channels]
        else:
            values = dict(arguments['values'])
            if 'serial_port' in values:
                values['serial_port'] = self._port(values['serial_port'])
            if 'vlan_name' in values:
                alias = validate_adapter_name(adapter_alias_from_display(values['vlan_name'])) if values['vlan_name'].strip() else ''
                values.update(vlan_name=alias, adapter_alias=alias)
            channels = [replace(c, **values) if int(c.section.rsplit('_', 1)[1]) in requested else c for c in channels]
        device_ip = arguments.get('device_ip', before['device_ip']).strip()
        if device_ip:
            ipaddress.IPv4Address(device_ip)
        power = self._port(arguments.get('power_serial_port', before['power_serial_port']))
        # The existing GUI has one management IP and derives each VLAN source IP.
        for channel in channels:
            channel.device_manage_ip = device_ip
            channel.subnet_mask = DEFAULT_SUBNET_MASK
            try:
                channel.network_card_ip = static_ip_for_vlan(channel.vlan_name or channel.adapter_alias, device_ip) if channel.vlan_name and device_ip else ''
            except ValueError:
                channel.network_card_ip = ''
            if channel.enabled and power and channel.serial_port.upper() == power:
                raise CapabilityError('port_conflict', '样机串口与程控电源COM冲突，未保存')
        after = dict(channels=[asdict(c) for c in channels], power_serial_port=power, device_ip=device_ip)
        unchanged = all(after[k] == before[k] for k in after)
        disable_only = not selecting and arguments['values'] == {'enabled': False} and not any(
            key in arguments for key in ('device_ip', 'power_serial_port'))
        scope = None if unchanged or disable_only else dict(id='channel-configuration:' + fingerprint(after),
            desired_configuration=after, purpose='仅保存此配置/勾选集合，不授权AI访问新增设备；原会话设备范围保持')
        return dict(before=before, after=after, revision=arguments['revision'], scope=scope, unchanged=unchanged)

    def configure(self, arguments, authority):
        return self._apply(arguments, authority)

    def select(self, arguments, authority):
        return self._apply(arguments, authority, selecting=True)

    def _apply(self, arguments, authority, selecting=False):
        owner = 'configuration:' + uuid.uuid4().hex
        with self.service.resources.lease(owner, ('device-business', 'configuration')):
            prepared = self.prepare(arguments, selecting)
            self.service.scopes.require(authority, prepared['scope'])
            if not prepared['unchanged']:
                if self.commit_callback is None:
                    raise CapabilityError('configuration_host_unavailable', '主机尚未接入可写通道数据适配，未保存配置')
                try:
                    result = self.commit_callback(prepared)
                except CapabilityError:
                    raise
                except Exception as exc:
                    raise CapabilityError('channel_commit_failed', '主机提交未完成，请核对状态后再重试：' + str(exc)) from exc
                if isinstance(result, dict) and result.get('state') == 'saved_refresh_failed':
                    return dict(ok=False, saved=True, changed=True, state='unknown',
                        error='配置已保存，但主界面或目标资格刷新失败；保留资源保护，须本地核对并重启', device_authority_changed=False)
            self.service.emit('[通道配置] 已提交审核后的配置/选择集合；当前AI会话未增加设备授权')
            return dict(ok=True, changed=not prepared['unchanged'], device_authority_changed=False,
                        notice='绑定变化会使旧目标资格失效；新增目标仍须经可信入口明确选择')

    def commit(self, prepared, current_snapshot, reflect):
        """Host data adapter calls this atomically on its owning thread; reflect only renders data."""
        with self.store.transaction():
            return self._commit(prepared, current_snapshot, reflect)

    def _commit(self, prepared, current_snapshot, reflect):
        if fingerprint(self.state(current_snapshot)) != prepared['revision']:
            raise CapabilityError('channel_configuration_changed', '实际提交前通道数据/文件再次变化，未覆盖')
        before, after = prepared['before'], prepared['after']
        temporary = self.store.config_path.with_name(self.store.config_path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            # Reuse the GUI store serializer. Publish only the selected rows, exactly
            # as the original _persist_config, with an atomic file replacement.
            ChannelConfigStore(temporary).save([ChannelConfig(**c) for c in after['channels'] if c['enabled']], after['power_serial_port'])
            try:
                reflect(after)
                if self._file_hash() != before['file_sha256']:
                    raise CapabilityError('channel_configuration_changed', '提交期间配置被其它写入方修改，本次未覆盖')
                temporary.replace(self.store.config_path)
            except Exception as exc:
                try:
                    reflect(before)
                except Exception as rollback:
                    raise CapabilityError('channel_view_rollback_failed', '通道视图恢复未完成，须本地核对后重启') from rollback
                raise CapabilityError('channel_commit_failed', '通道配置提交失败，本次未覆盖磁盘配置并已恢复界面：' + str(exc)) from exc
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                self.service.emit('[通道配置] 临时配置清理失败，请在本地核对；不改变提交结果')
        return dict(ok=True)
