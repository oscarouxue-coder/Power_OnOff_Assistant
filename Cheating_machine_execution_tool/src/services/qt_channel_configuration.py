"""Local Qt channel editing over original prepare/commit and selected-only INI.

The validation projection is data only. It never acquires device access and
cannot execute registered actions; the real capability service owns admission.
"""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import threading
import time
from types import SimpleNamespace
import uuid

from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
from src.models.capabilities import CapabilityError, CapabilitySpec, fingerprint, object_schema
from src.models.project_review import ReviewRequired
from src.models.qt_configuration import ConfigurationDraft
from src.models.project_profile import normalize_project_profile
from src.services.project_profile_store import PROFILE_FILE, read_project_profile, write_project_profile
from src.services.capability_channel_service import ChannelCapabilities
from src.services.capability_registry import CapabilityRegistry
from src.services.project_store import configuration_digest
from src.services.qt_configuration_service import QtConfigurationService


DUT_CHANNEL_DETAILS = (('label', '样机名称'), ('target_firmware', '目标固件'),
                       ('adb_serial', 'ADB 设备标识'), ('other_devices', '其他设备'))


def channel_slots(channels):
    """Same 16 disabled missing slots as the original _ensure_channel_slots."""
    by_id = {c.section: c for c in channels}
    for number in range(1, 17):
        by_id.setdefault('channel_' + str(number), ChannelConfig('channel_' + str(number), enabled=False))
    return sorted(by_id.values(), key=lambda c: int(c.section.rsplit('_', 1)[1]))


def channel_environment(directory=None):
    if directory is None:
        return dict(channels=[asdict(c) for c in channel_slots([])], power_serial_port='', device_ip='')
    store = ChannelConfigStore(directory / 'network_card_ip.ini')
    slots = channel_slots(store.load())
    return dict(channels=[asdict(c) for c in slots], power_serial_port=store.load_power_serial_port(),
                device_ip=next((c.device_manage_ip for c in slots if c.device_manage_ip), ''))


def prepare_channel_environment(before, arguments, working_root, *, preserve=False):
    rows = arguments['rows']
    numbers = [r['number'] for r in rows]
    if (len(numbers) != 16 or any(type(n) is not int for n in numbers)
            or set(numbers) != set(range(1, 17)) or any(type(r['enabled']) is not bool for r in rows)):
        raise CapabilityError('invalid_target', '须提交完整且不重复的16个通道槽位')
    indexed = {int(c['section'].rsplit('_', 1)[1]): c for c in before['channels']}
    if set(indexed) != set(range(1, 17)):
        raise CapabilityError('invalid_target', '原通道编号不在1至16完整范围内，请先核对原项目')
    proposed = deepcopy(before)
    projection = SimpleNamespace(snapshot=lambda: deepcopy(proposed), registry=CapabilityRegistry())
    validator = ChannelCapabilities(projection, working_root)
    try:
        for row in rows:
            prepared = validator.prepare(dict(channel_ids=[row['number']], revision=fingerprint(validator.state()),
                values={k: row[k] for k in ('enabled', 'vlan_name', 'serial_port')},
                device_ip=arguments['device_ip'], power_serial_port=arguments['power_serial_port']))
            proposed.update(prepared['after'])
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        message = '通道校验失败，请检查管理IPv4、COM编号、VLAN名称及样机/电源串口冲突；未保存'
        if isinstance(error, ReviewRequired):
            raise ReviewRequired('invalid_parameters', message, **asdict(error.review)) from None
        raise CapabilityError('invalid_parameters', message) from None
    if preserve:
        same_management_ip = proposed['device_ip'] == before['device_ip']
        for channel in proposed['channels']:
            old = indexed[int(channel['section'].rsplit('_', 1)[1])]
            if channel['vlan_name'] == old['vlan_name']:
                channel['adapter_alias'] = old['adapter_alias']
                if old['enabled'] and same_management_ip:
                    for key in ('device_manage_ip', 'network_card_ip', 'subnet_mask'):
                        channel[key] = old[key]
    return {key: proposed[key] for key in ('channels', 'power_serial_port', 'device_ip')}


def profile_with_environment(profile, environment, assignments=None, *, before=None):
    assignments = assignments or {}
    duts = [dict(dut) for dut in profile.get('duts', ())]
    enabled = {int(row['section'].rsplit('_', 1)[1]) for row in environment['channels'] if row['enabled']}
    by_channel = {dut['channel']: dut for dut in duts if dut.get('channel') is not None}
    for dut in duts:
        if dut.get('channel') is not None or dut.get('dut_id') not in assignments:
            continue
        number = assignments[dut['dut_id']]
        if number == 0:
            continue
        if type(number) is not int or number not in enabled:
            raise ReviewRequired('invalid_target', '请为旧 DUT 选择已启用的通道，或移出本批',
                                 'channels', 'assignments', reference=dut['dut_id'])
        previous = by_channel.get(number)
        if previous is not None:
            raise ReviewRequired('invalid_target', f'CH{number:02d} 已绑定其他 DUT，请选择另一通道',
                                 'channels', 'assignments', reference=dut['dut_id'], channels=(number,))
        dut['channel'] = number
        by_channel[number] = dut
    if (profile.get('test_type') == 'service_aging' and not profile.get('environment_channels')
            and any(dut.get('channel') is None and dut.get('dut_id') not in assignments for dut in duts)):
        raise ValueError('请在环境配置中处理未绑定通道的旧 DUT')
    for number in sorted(enabled - by_channel.keys()):
        duts.append(dict(channel=number, label=f'CH{number:02d}'))
    if before is not None:
        keys = ('enabled', 'vlan_name', 'adapter_alias', 'serial_port', 'network_card_ip',
                'device_manage_ip', 'subnet_mask', 'factory_bind_ip', 'factory_device_host')
        original = {row['section']: row for row in before['channels']}
        proposed = {row['section']: row for row in environment['channels']}
        changed_power = (profile['test_type'] == 'power_cycle'
                         and before['power_serial_port'] != environment['power_serial_port'])
        for dut in duts:
            section = f"channel_{dut.get('channel')}"
            if section not in original:
                continue
            old, new = original[section], proposed[section]
            if (old['enabled'] or new['enabled']) and (changed_power or any(old[k] != new[k] for k in keys)):
                dut['mapping_generation'] = uuid.uuid4().hex
    return normalize_project_profile(dict(profile, duts=duts, environment_channels=True))


class QtChannelConfiguration:
    def __init__(self, workspace, context, capabilities, other_editor_open, adapter_rename=None):
        self.workspace, self.context, self.capabilities = workspace, context, capabilities
        self.other_editor_open = other_editor_open
        self.token = ''
        self.pending = None
        self.adapter_rename = adapter_rename
        self.rename_review = None
        self.lock = threading.RLock()
        self.cache = None
        self.cache_hash = None
        self.channels = capabilities.channel_configuration
        self.path = self.channels.store.config_path
        token = dict(type='string', minLength=32, maxLength=32)
        row = object_schema({'number': dict(type='integer', minimum=1, maximum=16),
            'enabled': dict(type='boolean'), 'vlan_name': dict(type='string', maxLength=200),
            'serial_port': dict(type='string', maxLength=32)}, ('number', 'enabled', 'vlan_name', 'serial_port'))
        assignment = object_schema({'dut_id': dict(type='string', minLength=36, maxLength=36),
            'number': dict(type='integer', minimum=0, maximum=16)}, ('dut_id', 'number'))
        details = object_schema(dict(number=dict(type='integer', minimum=1, maximum=16),
            **{key: dict(type='string') for key, _ in DUT_CHANNEL_DETAILS}), ('number',))
        preview = object_schema({'token': token, 'revision': dict(type='string', minLength=64, maxLength=64),
            'rows': dict(type='array', minItems=16, maxItems=16, items=row),
            'device_ip': dict(type='string', maxLength=64), 'power_serial_port': dict(type='string', maxLength=32),
            'assignments': dict(type='array', items=assignment),
            'dut_details': dict(type='array', maxItems=16, items=details)},
            ('token', 'revision', 'rows', 'device_ip', 'power_serial_port'))
        for suffix, handler, schema, risk in (
            ('open', self.open, object_schema(), 'read'),
            ('reload', self.reload, object_schema({'token': token}, ('token',)), 'read'),
            ('close', self.close_editor, object_schema({'token': token}, ('token',)), 'read'),
            ('resources', self.resources, object_schema({'token': token}, ('token',)), 'read'),
            ('preview', self.preview, preview, 'read'),
            ('cancel', self.cancel_preview, object_schema({'token': token}, ('token',)), 'read'),
            ('save', self.save, object_schema({'token': token, 'confirmation': token}, ('token', 'confirmation')), 'modify'),
        ):
            capabilities.registry.register(CapabilitySpec('channels.editor.' + suffix, '本机通道编辑 ' + suffix,
                '仅供本机GUI审阅绑定，复用原通道校验/存储；不会操作网卡、串口或电源，不授予AI新增设备权限。',
                schema, handler, risk=risk, sources=('gui',), resource_requirements=('configuration',)))
        if adapter_rename is not None:
            rename_fields = dict(token=token, revision=dict(type='string', minLength=64, maxLength=64),
                number=dict(type='integer', minimum=1, maximum=16),
                old_name=dict(type='string', minLength=1, maxLength=200),
                new_name=dict(type='string', minLength=1, maxLength=200))
            for suffix, handler, schema, risk in (
                ('rename_preview', self.rename_preview, object_schema(rename_fields, tuple(rename_fields)), 'read'),
                ('rename_confirm', self.rename_confirm, object_schema({'token': token, 'confirmation': token},
                    ('token', 'confirmation')), 'dangerous'),
                ('rename_cancel', self.rename_cancel, object_schema({'token': token}, ('token',)), 'read'),
            ):
                capabilities.registry.register(CapabilitySpec('channels.editor.' + suffix, '本机网卡改名 ' + suffix,
                    '仅供本机操作员审阅网卡 GUID 与受影响通道。沿用单次 Windows 改名及同一 GUID 回读。',
                    schema, handler, risk=risk, sources=('gui',), resource_requirements=('adapter', 'configuration')))

    @property
    def opened(self):
        return bool(self.token)

    def _file_hash(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path.is_file() else ''

    def snapshot(self):
        with self.lock:
            digest = self._file_hash()
            if self.cache is None or self.cache_hash != digest:
                store = ChannelConfigStore(self.path)
                channels = channel_slots(store.load())
                self.cache = dict(channels=[asdict(c) for c in channels], power_serial_port=store.load_power_serial_port(),
                    device_ip=next((c.device_manage_ip for c in channels if c.device_manage_ip), ''))
                self.cache_hash = digest
            return deepcopy(self.cache)

    def _revision(self):
        return fingerprint([self.context.identity.revision, configuration_digest(self.context.config_dir), self.snapshot(),
            hashlib.sha256((self.context.root / 'project.linecheck.json').read_bytes()).hexdigest()])

    def _guard(self, token=None):
        if token is not None and (not self.token or token != self.token):
            raise CapabilityError('editor_expired', '通道编辑上下文已失效，请重新打开')
        if self.other_editor_open():
            raise ReviewRequired('editor_open', '请先保存或关闭本项目测试配置窗口', 'editor', 'close')
        if not self.capabilities.jobs.idle or self.capabilities.jobs.closing:
            raise CapabilityError('resource_busy', '任务正在执行或收尾，通道配置未放行')
        self.workspace.projects._validate_paths(self.context)

    def _load(self):
        before = self._revision()
        values = self.snapshot()
        profile = read_project_profile(self.context.config_dir)
        if profile:
            values['service_aging'] = profile['test_type'] == 'service_aging'
            values['dut_details'] = {dut['channel']: {key: dut.get(key, '') for key, _ in DUT_CHANNEL_DETAILS}
                                     for dut in profile['duts'] if dut['channel'] is not None}
            if values['service_aging'] and not profile.get('environment_channels'):
                values['unbound_duts'] = [{'dut_id': dut['dut_id'], 'label': dut['label']}
                                         for dut in profile['duts'] if dut['channel'] is None]
        if self._revision() != before:
            raise CapabilityError('configuration_changed', '读取期间配置变化，请重新加载')
        return ConfigurationDraft(self.context.identity.project_id, self.context.identity.name, self.token, before, values)

    def open(self, arguments, authority):
        self._guard()
        if self.opened:
            raise CapabilityError('editor_open', '该项目已有通道编辑窗口')
        self.token = uuid.uuid4().hex
        try:
            draft = self._load()
        except Exception:
            self.token = ''
            raise CapabilityError('configuration_unreadable', '通道配置读取失败，请检查文件格式和权限') from None
        self.capabilities.emit('[Qt通道] 已载入16个配置槽位，尚未保存；勾选不等于任务运行')
        return draft

    def reload(self, arguments, authority):
        self._guard(arguments['token'])
        self.pending = None
        self.rename_review = None
        return self._load()

    def close_editor(self, arguments, authority):
        if self.token == arguments['token']:
            self.token = ''
            self.pending = None
            self.rename_review = None
            self.capabilities.emit('[Qt通道] 已关闭编辑窗口，未保存的界面修改不写盘')

    def resources(self, arguments, authority):
        # The workspace joins this guarded request to its host-wide reader.
        self._guard(arguments['token'])

    def preview(self, arguments, authority):
        self._guard(arguments['token'])
        self.pending = None
        self.rename_review = None
        if self._revision() != arguments['revision']:
            raise ReviewRequired('configuration_changed', '项目或磁盘配置已变化，请重新加载后核对', 'channels', 'reload')
        before = self.channels.state()
        profile = read_project_profile(self.context.config_dir)
        aging = bool(profile and profile['test_type'] == 'service_aging')
        edits = dict(arguments, power_serial_port='') if aging else arguments
        after = prepare_channel_environment(before, edits, self.context.working_root, preserve=bool(profile))
        if aging:
            after['power_serial_port'] = before['power_serial_port']
        elif self.workspace.projects.power_resources is not None:
            self.workspace.resources.check_power_selection(self.context.identity.project_id, after['power_serial_port'],
                (int(row['section'].rsplit('_', 1)[1]) for row in after['channels'] if row['enabled']))
        assignment_rows = arguments.get('assignments', ())
        assignments = {row['dut_id']: row['number'] for row in assignment_rows}
        unbound = set()
        if aging and not profile.get('environment_channels'):
            unbound = {dut['dut_id'] for dut in profile['duts'] if dut['channel'] is None}
        if len(assignments) != len(assignment_rows) or set(assignments) != unbound:
            raise ReviewRequired('invalid_target', '请逐台处理未绑定通道的旧 DUT，选择已启用的通道或移出本批', 'channels', 'assignments')
        updated_profile = profile_with_environment(profile, after, assignments, before=before) if profile else None
        details = arguments.get('dut_details', ())
        if details:
            enabled = {int(row['section'].rsplit('_', 1)[1]) for row in after['channels'] if row['enabled']}
            by_channel = {row['number']: row for row in details}
            if not updated_profile or len(by_channel) != len(details) or not by_channel.keys() <= enabled:
                raise CapabilityError('invalid_target', '只能修改本项目已启用通道的 DUT 信息')
            for dut in updated_profile['duts']:
                number = dut['channel']
                if number in by_channel:
                    changes = by_channel[number]
                    dut.update({key: changes[key].strip() for key, _ in DUT_CHANNEL_DETAILS if key in changes})
                    dut['label'] = dut['label'] or f'CH{number:02d}'
            updated_profile = normalize_project_profile(updated_profile)
        confirmation = uuid.uuid4().hex
        self.pending = dict(confirmation=confirmation, revision=arguments['revision'], created=time.monotonic(),
            profile=updated_profile, prepared=dict(before=before, after=after, revision=fingerprint(before)))
        selected = [c for c in after['channels'] if c['enabled']]
        summary = (self.context.identity.name + '\n管理IP：' + (after['device_ip'] or '未配置') +
            '\n电源COM：' + (after['power_serial_port'] or '不使用程控电源') + '\n已选通道：' +
            ('、'.join(c['section'].replace('channel_', 'CH') for c in selected) or '无（清除选择）') + '\n' +
            '\n'.join(c['section'].replace('channel_', 'CH') + ' · ' + (c['vlan_name'] or '未配置VLAN') + ' / ' +
                (c['serial_port'] or '按原VLAN映射') + ' / ' + (c['network_card_ip'] or '源IP待配置') for c in selected))
        if assignments:
            summary += '\n旧 DUT 处理：\n' + '\n'.join(
                dut['label'] + ' → ' + (f"CH{assignments[dut['dut_id']]:02d}" if assignments[dut['dut_id']]
                                         else '移出本批（保留历史）')
                for dut in profile['duts'] if dut['dut_id'] in assignments)
        if details:
            summary += '\nDUT 信息修改：\n' + '\n'.join(
                f"CH{row['number']:02d} · " + ' / '.join(
                    title + ' ' + (row[key] or '（清空）') for key, title in DUT_CHANNEL_DETAILS if key in row)
                for row in details)
        summary += '\n保存本项目当前草稿并提交版本；只写已选通道，不改网络或上下电。是否继续？'
        self.capabilities.emit('[Qt通道] 原校验已生成保存预览，等待本机确认')
        return dict(confirmation=confirmation, summary=summary)

    def cancel_preview(self, arguments, authority):
        self._guard(arguments['token'])
        self.pending = None
        self.capabilities.emit('[Qt通道] 本机取消保存，未写入文件')

    def rename_preview(self, arguments, authority):
        self._guard(arguments['token'])
        self.pending = None
        self.rename_review = None
        self.rename_review, confirmation = self.adapter_rename.prepare(self, arguments)
        return confirmation

    def rename_cancel(self, arguments, authority):
        self._guard(arguments['token'])
        self.rename_review = None
        self.capabilities.emit('[网卡重命名] 操作员取消，原网卡名称和通道配置保留')

    def rename_confirm(self, arguments, authority):
        self._guard(arguments['token'])
        review, self.rename_review = self.rename_review, None
        if not review or review['confirmation'] != arguments['confirmation'] or time.monotonic() - review['created'] > 120:
            raise CapabilityError('confirmation_expired', '网卡改名确认失效，请重新审阅')
        return self.adapter_rename.apply(self, review)

    def save(self, arguments, authority):
        self._guard(arguments['token'])
        pending, self.pending = self.pending, None
        if not pending or pending['confirmation'] != arguments['confirmation'] or time.monotonic() - pending['created'] > 120:
            raise CapabilityError('confirmation_expired', '通道保存确认已失效，请重新预览')
        if self._revision() != pending['revision']:
            raise ReviewRequired('configuration_changed', '确认后配置变化，未覆盖，请重新加载', 'channels', 'reload')
        self.workspace.guard_project_workers(self.context)
        owner = 'gui:qt-channel:' + uuid.uuid4().hex
        uncertain = False
        self.capabilities.resources.acquire(owner, ('device-business', 'configuration'))
        try:
            with self.lock, self.channels.store.transaction():
                if self._revision() != pending['revision']:
                    raise CapabilityError('configuration_changed', '实际提交前配置变化，未覆盖')
                previous = self.path.read_bytes() if self.path.exists() else None
                profile_path = self.context.config_dir / PROFILE_FILE
                previous_profile = profile_path.read_bytes() if pending['profile'] else None
                profile_published = False
                old_cache, old_hash = deepcopy(self.cache), self.cache_hash
                old_revision = self.context.identity.revision
                published = False
                written_hash = None
                try:
                    self.channels.commit(pending['prepared'], self.capabilities.snapshot(), self._reflect)
                    published = True
                    written_hash = self.cache_hash = self._file_hash()
                    if pending['profile']:
                        write_project_profile(self.context.config_dir, pending['profile'])
                        profile_published = True
                    self.workspace.projects.save(self.context, require_power_registration=True)
                except Exception as error:
                    revision_changed = self.context.identity.revision != old_revision
                    uncertain = revision_changed or getattr(error, 'code', '') == 'channel_view_rollback_failed'
                    if published and not revision_changed:
                        try:
                            if self._file_hash() != written_hash:
                                raise RuntimeError('another writer changed configuration')
                            if previous is None:
                                self.path.unlink(missing_ok=True)
                            else:
                                QtConfigurationService._replace(self.path, previous)
                        except Exception:
                            uncertain = True
                    if profile_published and not revision_changed:
                        try:
                            if read_project_profile(self.context.config_dir) != pending['profile']:
                                raise RuntimeError('another writer changed project profile')
                            QtConfigurationService._replace(profile_path, previous_profile)
                        except Exception:
                            uncertain = True
                    self.cache, self.cache_hash = old_cache, old_hash
                    # Never undo another writer if original commit rejected a
                    # concurrent change before it published our own file.
                    try:
                        if self._file_hash() != old_hash:
                            self.cache = None
                    except OSError:
                        self.cache = None
                        uncertain = True
                    if isinstance(error, ReviewRequired) and not uncertain:
                        raise
                    raise CapabilityError('channel_save_unknown' if uncertain else 'channel_save_failed',
                        f'通道恢复未完成，请检查 {self.path.name}、{profile_path.name} 和项目版本 {old_revision[:12]}' if uncertain else
                        '通道提交失败，未覆盖其它写入或已恢复原草稿；请重新加载并核对') from None
        finally:
            self.capabilities.resources.release(owner, uncertain=uncertain)
        self.capabilities.emit('[Qt通道] 已按原规则保存已选通道并提交项目版本，未执行设备操作')
        return self._load()

    def _reflect(self, value):
        self.cache = deepcopy({key: value[key] for key in ('channels', 'power_serial_port', 'device_ip')})
