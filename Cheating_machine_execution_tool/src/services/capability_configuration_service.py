"""Versioned edits through the same stores consumed by the GUI and engines.

Configuration is saved only while idle and with its editor closed. Values are
merged, so passwords and fields the caller did not supply are preserved.
"""
from dataclasses import asdict, replace
from pathlib import Path
import threading
import uuid

from line_check_assistant.paths import resolve_config_dir
from line_check_assistant.test_item_config_store import (TestItemConfigStore, TestProjectConfig,
    TelnetSettings, OrderConfig, OrderItem, ExpectedSegment, ConnectWifiSettings, ProjectInfoSettings)
from line_check_assistant.legacy_ui_defaults_store import LegacyUiDefaultsStore, REQUIRED_OPTIONS
from src.models.capabilities import CapabilitySpec, CapabilityError, object_schema, fingerprint
from src.services.capability_device_services import settings_schema


MODELS = {'telnet': TelnetSettings, 'order': OrderConfig, 'connect_wifi': ConnectWifiSettings, 'project_info': ProjectInfoSettings}


def load_default_order(path):
    """Use the same store operation as the frozen GUI draft loader."""
    return TestItemConfigStore(Path(path)).load().order


def configuration_schema(domain):
    if domain == 'runtime':
        return object_schema({key: dict(type='string', maxLength=2000) for key in REQUIRED_OPTIONS})
    schema = settings_schema(MODELS[domain])
    if domain == 'order':
        item = settings_schema(OrderItem)
        item['properties']['expected_segments'] = dict(type='array', maxItems=100,
            items=settings_schema(ExpectedSegment))
        schema['properties']['items'] = dict(type='array', maxItems=500, items=item)
    if domain == 'telnet':
        schema['properties']['telnet_need_enter_password_flag'] = dict(type='integer', enum=[0])
        schema['properties']['port'].update(minimum=1, maximum=65535)
        schema['properties']['timeout'].update(minimum=1, maximum=600)
    return schema


class ConfigurationCapabilities:
    def __init__(self, service, tool_root):
        self.service = service
        self.directory = resolve_config_dir(Path(tool_root))
        self.store = TestItemConfigStore(self.directory / 'test_project_config.ini')
        self.legacy = LegacyUiDefaultsStore(self.directory / 'config.ini')
        self.lock = threading.RLock()
        service.registry.register(CapabilitySpec('configuration.read', '读取测试配置', '返回当前配置及修改令牌；密码不返回，未提供的值会保留。',
            object_schema({'domain': dict(type='string', enum=list(MODELS) + ['runtime'])}, ('domain',)),
            self.read, sources=('local', 'gui')))
        service.registry.register(CapabilitySpec('configuration.defaults.prepare', '准备默认测试项草稿',
            '与GUI恢复默认共用模板读取，返回未保存的order.items草稿及保存参数；保留当前全局重试间隔，未自动保存或执行。',
            object_schema(), self.prepare_defaults, sources=('local', 'gui')))
        for domain in list(MODELS) + ['runtime']:
            service.registry.register(CapabilitySpec('configuration.' + domain + '.patch', '修改配置 ' + domain,
                '共用原配置存储；需当前revision、界面编辑器关闭且无业务运行。只修改明确提供字段，不执行配置命令。',
                object_schema({'revision': dict(type='string', minLength=64, maxLength=64), 'values': configuration_schema(domain)}, ('revision', 'values')),
                lambda a, auth, d=domain: self.patch(d, a, auth), risk='modify', sources=('local', 'gui'),
                resource_requirements=('device-business', 'configuration')))

    def _revision(self):
        return fingerprint([p.read_bytes().hex() if p.is_file() else '' for p in
            (self.store.config_path, self.legacy.config_path)])

    def prepare_defaults(self, arguments, authority):
        path = self.directory / 'test_project_config.default.ini'
        with self.lock:
            before = self.service.files.information(path)['sha256']
            order = load_default_order(path)
            if self.service.files.information(path)['sha256'] != before:
                raise CapabilityError('default_template_changed', '读取默认模板期间内容已变化，未生成草稿')
            draft = {'items': asdict(order)['items']}
            revision = self._revision()
        self.service.emit('[测试项配置] 已从原默认模板准备命令草稿；保留当前全局重试间隔，等待保存')
        return dict(saved=False, template_sha256=before, capability_id='configuration.order.patch',
                    arguments=dict(revision=revision, values=draft), count=len(order.items))

    def read(self, arguments, authority):
        domain = arguments['domain']
        with self.lock:
            values = self.legacy.load() if domain == 'runtime' else asdict(getattr(self.store.load(), domain))
            # A read must not disclose stored credentials back to the model/remote transcript.
            values.pop('password', None)
            return dict(domain=domain, values=values, revision=self._revision(), secrets_omitted=True)

    def patch(self, domain, arguments, authority):
        owner = 'configuration:' + uuid.uuid4().hex
        with self.service.resources.lease(owner, ('device-business', 'configuration')), self.lock:
            snapshot = self.service.snapshot()
            if snapshot.get('configuration_editor_open'):
                raise CapabilityError('editor_open', '测试项配置窗口仍有编辑上下文，请先保存或关闭，未覆盖界面草稿')
            if self._revision() != arguments['revision']:
                raise CapabilityError('configuration_changed', '配置已改变，请读取当前值后重新合并')
            values = arguments['values']
            if domain == 'runtime':
                merged = dict(self.legacy.load(), **values)
                self.legacy.save(merged)
            else:
                config = self.store.load()
                merged = dict(asdict(getattr(config, domain)), **values)
                if domain == 'order':
                    if merged['command_fail_retry_interval_time'] < 0:
                        raise CapabilityError('invalid_parameters', '全局重试间隔不能为负数')
                    merged['items'] = [OrderItem(command=item['command'], retry_times=item.get('retry_times', 5),
                        expected_segments=[ExpectedSegment(**segment) for segment in item.get('expected_segments', [])]) for item in merged['items']]
                    if any(not item.command.strip() or item.retry_times < 1 for item in merged['items']):
                        raise CapabilityError('invalid_parameters', '测试命令不能为空且重试次数至少为1')
                if domain == 'telnet':
                    merged['telnet_need_enter_password_flag'] = 0
                config = replace(config, **{domain: MODELS[domain](**merged)})
                self.store.save(config)
            self.service.emit('[配置保存] ' + domain + '；共用配置存储写入成功，未执行设备命令')
            return self.read(dict(domain=domain), authority)
