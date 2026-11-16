"""Versioned permanent options; host renders data, original stores own serialization."""
from dataclasses import asdict
from pathlib import Path
import hashlib
import ipaddress
import uuid

from line_check_assistant.config_store import ChannelConfigStore
from line_check_assistant.paths import resolve_config_dir
from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings, SampleUpgradeSettingsStore
from line_check_assistant.onu_registration_store import OnuRegistrationConfig, OnuRegistrationStore
from src.models.boot_entry import BOOT_ENTRY_OPTIONS
from src.models.capabilities import CapabilitySpec, CapabilityError, object_schema, fingerprint
from src.services.capability_device_services import settings_schema
from src.services.web_gateway_upgrade_service import TRANSFER_WEB_GATEWAY


class SettingsCapabilities:
    def __init__(self, service, tool_root, commit_callback=None, onu_configuration=None):
        self.service, self.commit_callback = service, commit_callback
        directory = resolve_config_dir(Path(tool_root))
        self.stores = {'upgrade': SampleUpgradeSettingsStore(directory / 'sample_upgrade_settings.ini'),
                       'onu': OnuRegistrationStore(directory / 'onu_registration.ini')}
        self.models = {'upgrade': SampleUpgradeSettings, 'onu': OnuRegistrationConfig}
        self.onu_configuration = onu_configuration or (lambda: asdict(self.stores['onu'].load()))
        service.registry.register(CapabilitySpec('settings.read', '读取永久升级/ONU选项',
            '返回当前界面和文件共同版本，省略密码；打开编辑器或未完成自动保存时不覆盖草稿。',
            object_schema({'domain': dict(type='string', enum=['upgrade', 'onu'])}, ('domain',)),
            self.read, sources=('local', 'gui')))
        for domain, identifier in (('upgrade', 'firmware.settings.patch'), ('onu', 'onu.settings.patch')):
            schema = settings_schema(self.models[domain])
            properties = schema['properties']
            if domain == 'upgrade':
                properties['upgrade_mode']['enum'] = ['全包升级', '页面升级']
                properties['transfer_method']['enum'] = ['Tftp指令', 'Tftp Put', TRANSFER_WEB_GATEWAY]
                properties['boot_entry_method']['enum'] = list(BOOT_ENTRY_OPTIONS)
                properties['power_operation']['enum'] = ['up', 'down']
                for key in ('parallel_count', 'parameter_parallel_count'):
                    properties[key].update(minimum=1, maximum=8)
            else:
                # Active aliases are derived from the selected profile, not independent credentials.
                for key in ('olt_ip', 'source_ip', 'username', 'password', 'c300_allow_offline_cleanup'):
                    properties.pop(key)
                properties['olt_family']['enum'] = ['C300', 'C600']
                for key, value in properties.items():
                    if value['type'] == 'integer':
                        value.update(minimum=0 if key.endswith(('_shelf', '_slot', '_pon')) else 1, maximum=4094)
            service.registry.register(CapabilitySpec(identifier, '保存永久选项 ' + domain,
                '只保存原配置、不操作设备。需当前revision及编辑器关闭；新OLT连接/PON范围须本地审阅，业务执行仍独立校验范围。',
                object_schema({'revision': dict(type='string', minLength=64, maxLength=64), 'values': schema}, ('revision', 'values')),
                lambda a, auth, d=domain: self.patch(d, a, auth), risk='modify', sources=('local', 'gui'),
                resource_scope=lambda a, d=domain: self.prepare(d, a)['scope'],
                resource_requirements=('device-business', 'configuration')))

    def digest(self, domain):
        path = self.stores[domain].config_path
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ''

    def state(self, domain, snapshot=None, onu_values=None):
        snapshot = self.service.snapshot() if snapshot is None else snapshot
        values = (snapshot.get('upgrade_settings', {}) if domain == 'upgrade' else
                  self.onu_configuration() if onu_values is None else onu_values)
        return dict(values=asdict(self.models[domain](**values)), file_sha256=self.digest(domain),
                    editor_open=bool(snapshot.get(domain + '_editor_open')),
                    autosave_pending=bool(snapshot.get(domain + '_autosave_pending')))

    def read(self, arguments, authority):
        state = self.state(arguments['domain'])
        values = {key: value for key, value in state['values'].items() if 'password' not in key}
        return dict(domain=arguments['domain'], values=values, revision=fingerprint(state),
                    editor_open=state['editor_open'], autosave_pending=state['autosave_pending'], secrets_omitted=True)

    def prepare(self, domain, arguments):
        before = self.state(domain)
        if fingerprint(before) != arguments['revision']:
            raise CapabilityError('settings_changed', '界面或永久配置已变化，未覆盖')
        if before['editor_open'] or before['autosave_pending']:
            raise CapabilityError('editor_open', '相关窗口或自动保存仍有编辑上下文，请先关闭并等待保存完成')
        after = dict(before['values'], **arguments['values'])
        scope = None
        if domain == 'onu':
            prefix = after['olt_family'].lower() + '_'
            for key in ('olt_ip', 'source_ip', 'username', 'password'):
                after[key] = after[prefix + key]
            after['c300_allow_offline_cleanup'] = False
            for family in ('c300_', 'c600_'):
                for key in ('olt_ip', 'source_ip'):
                    ipaddress.IPv4Address(after[family + key])
            binding_keys = ('olt_family',) + tuple(family + name for family in ('c300_', 'c600_') for name in
                ('olt_ip', 'source_ip', 'username', 'password', 'shelf', 'slot', 'pon'))
            if any(after[k] != before['values'][k] for k in binding_keys):
                scope = dict(id='onu-settings:' + fingerprint(after), configuration_revision=fingerprint(after),
                    family=after['olt_family'], host=after['olt_ip'], source_ip=after['source_ip'],
                    pon=[after[prefix + k] for k in ('shelf', 'slot', 'pon')],
                    changed_fields=sorted(arguments['values']), purpose='仅保存此连接/PON配置，不授予OLT执行或write权限')
        return dict(domain=domain, before=before, after=after, revision=arguments['revision'], scope=scope)

    def patch(self, domain, arguments, authority):
        with self.service.resources.lease('settings:' + uuid.uuid4().hex, ('device-business', 'configuration')):
            prepared = self.prepare(domain, arguments)
            self.service.scopes.require(authority, prepared['scope'])
            if self.commit_callback is None:
                raise CapabilityError('configuration_host_unavailable', '永久选项尚无可写主机数据适配，未保存')
            self.commit_callback(prepared)
            self.service.emit('[永久选项] ' + domain + '已通过原store保存并同步数据；未下发设备命令')
            return dict(ok=True, saved=True, domain=domain, executed_device_operation=False)

    def commit(self, prepared, snapshot, onu_values, reflect):
        """Called by the host on its owning thread; never holds locks across RPC."""
        domain = prepared['domain']
        store = self.stores[domain]
        with ChannelConfigStore(store.config_path).transaction():
            if fingerprint(self.state(domain, snapshot, onu_values)) != prepared['revision']:
                raise CapabilityError('settings_changed', '实际提交前选项或自动保存状态变化，未覆盖')
            temporary = store.config_path.with_name(store.config_path.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                staged = type(store)(temporary)
                staged.save(self.models[domain](**prepared['after']))
                canonical = asdict(staged.load())
                try:
                    reflect(domain, canonical)
                    if self.digest(domain) != prepared['before']['file_sha256']:
                        raise CapabilityError('settings_changed', '提交期间配置被其它写入方改变，未覆盖')
                    temporary.replace(store.config_path)
                except Exception as exc:
                    try:
                        reflect(domain, prepared['before']['values'])
                    except Exception as rollback:
                        raise CapabilityError('settings_rollback_failed', '选项视图恢复失败，须本地核对后重启') from rollback
                    raise CapabilityError('settings_commit_failed', '永久选项提交失败，已恢复视图且未覆盖配置：' + str(exc)) from exc
                return dict(saved=True)
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
