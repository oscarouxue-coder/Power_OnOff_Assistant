"""GUI-only configuration transactions over original stores; no device I/O."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import tempfile
import uuid

from line_check_assistant.legacy_ui_defaults_store import LegacyUiDefaultsStore
from line_check_assistant.test_item_config_store import (TestItemConfigStore, TestProjectConfig,
    TelnetSettings, OrderConfig, OrderItem, ExpectedSegment, ConnectWifiSettings, ProjectInfoSettings)
from src.models.capabilities import CapabilityError, CapabilitySpec, object_schema
from src.models.qt_configuration import ConfigurationDraft
from src.models.wifi_test_models import WifiTestOptions
from src.services.capability_configuration_service import configuration_schema, load_default_order
from src.services.message_push_config_service import MessagePushConfigService
from src.services.project_store import configuration_digest
from src.services.qt_editor_recovery import QtEditorRecovery
from src.services.wifi_connection_service import validate_wifi_options


FILES = ('test_project_config.ini', 'config.ini')


def push_values_schema():
    keys = ('dingtalk_flag', 'webhook', 'secret', 'at_all')
    return object_schema({key: dict(type='string', maxLength=16384) for key in keys}, keys)


def editor_values_schema():
    properties = {key: configuration_schema(key) for key in ('telnet', 'order', 'connect_wifi', 'project_info')}
    # Runtime keys can include original extensions. Original store validates the
    # required keys; hidden/unknown fields remain in the local editor snapshot.
    properties['runtime'] = dict(type='object', properties={}, additionalProperties=True)
    properties['push'] = push_values_schema()
    return object_schema(properties, tuple(properties))


class QtConfigurationService:
    def __init__(self, workspace, context, capabilities, *, other_editor_open=lambda: False):
        self.workspace, self.context, self.capabilities = workspace, context, capabilities
        self.other_editor_open = other_editor_open
        self.token = ''
        self.recovery = QtEditorRecovery(context)
        add = capabilities.registry.register
        token = dict(type='string', minLength=32, maxLength=32)
        editor_revision = dict(type='string', minLength=64, maxLength=64)
        for suffix, handler, schema, risk in (
            ('open', self.open, object_schema(), 'read'),
            ('reload', self.reload, object_schema({'token': token, 'discard_recovery': dict(type='boolean')}, ('token',)), 'read'),
            ('close', self.close_editor, object_schema({'token': token, 'discard_revision': editor_revision}, ('token',)), 'read'),
            ('checkpoint', self.checkpoint, object_schema({'token': token, 'revision': editor_revision,
                'values': dict(type='object', additionalProperties=True)}, ('token', 'revision', 'values')), 'read'),
            ('defaults', self.defaults, object_schema({'token': token}, ('token',)), 'read'),
            ('wifi_interfaces', self.wifi_interfaces, object_schema({'token': token}, ('token',)), 'read'),
            ('save', self.save, object_schema({'token': token, 'revision': editor_revision,
                'values': editor_values_schema()}, ('token', 'revision', 'values')), 'modify'),
        ):
            add(CapabilitySpec('configuration.editor.' + suffix, '本机配置编辑器 ' + suffix,
                '仅供真实本机GUI编辑，私有值不进入AI或远程接口；复用原配置存储，不执行设备或发送消息。',
                schema, handler, risk=risk, sources=('gui',), resource_requirements=('configuration',)))

    @property
    def opened(self):
        return bool(self.token)

    def _guard(self, token=None):
        if token is not None and (not self.token or token != self.token):
            raise CapabilityError('editor_expired', '配置编辑上下文已失效，请关闭后重新打开')
        if self.other_editor_open():
            raise CapabilityError('editor_open', '请先保存或关闭本项目通道配置窗口')
        if not self.capabilities.jobs.idle or self.capabilities.jobs.closing:
            raise CapabilityError('resource_busy', '本项目任务正在执行或收尾，配置编辑未放行')
        self.workspace.projects._validate_paths(self.context)

    def _revision(self):
        manifest = self.context.root / 'project.linecheck.json'
        return hashlib.sha256((self.context.identity.revision + configuration_digest(self.context.config_dir)
            + hashlib.sha256(manifest.read_bytes()).hexdigest()).encode()).hexdigest()

    @staticmethod
    def _has_recovery_fields(raw, values):
        if raw.keys() != values.keys():
            return False
        for domain, fields in values.items():
            recovered = raw[domain]
            if not isinstance(recovered, dict) or recovered.keys() != fields.keys():
                return False
            if domain == 'order':
                items = recovered['items']
                if not isinstance(items, list) or not isinstance(recovered['command_fail_retry_interval_time'], str):
                    return False
                for item in items:
                    if (not isinstance(item, dict) or item.keys() != {'command', 'retry_times', 'expected_segments'}
                            or not isinstance(item['command'], str) or not isinstance(item['retry_times'], str)
                            or not isinstance(item['expected_segments'], list)):
                        return False
                    if any(not isinstance(segment, dict) or segment.keys() != {'text', 'negate'}
                           or not isinstance(segment['text'], str) or type(segment['negate']) is not bool
                           for segment in item['expected_segments']):
                        return False
            elif any(type(recovered[key]) is not (str if domain == 'telnet' and key in ('port', 'timeout')
                     else type(value)) for key, value in fields.items()):
                return False
        return True

    def _load(self, *, recover=False):
        config_dir = self.context.config_dir
        before = self._revision()
        config = TestItemConfigStore(config_dir / FILES[0]).load()
        values = asdict(config)
        values['runtime'] = LegacyUiDefaultsStore(config_dir / FILES[1]).load()
        values['push'] = MessagePushConfigService(config_dir / FILES[1]).load()
        if before != self._revision():
            raise CapabilityError('configuration_changed', '读取期间配置已变化，请重新加载')
        recovered, warning = self.recovery.read(before) if recover else (None, '')
        if recovered is not None and not self._has_recovery_fields(recovered, values):
            recovered, warning = None, 'Qt 恢复草稿字段无效，原文件保留'
        return ConfigurationDraft(self.context.identity.project_id, self.context.identity.name,
            self.token, before, values, tuple(name for name in FILES if not (config_dir / name).is_file()),
            recovered, warning, self.recovery.legacy_path.exists())

    def open(self, arguments, authority):
        self._guard()
        if self.opened:
            raise CapabilityError('editor_open', '该项目已有配置编辑窗口')
        self.token = uuid.uuid4().hex
        try:
            draft = self._load(recover=True)
        except Exception:
            self.token = ''
            raise CapabilityError('configuration_unreadable', '配置加载失败，请检查ini格式与访问权限') from None
        self.capabilities.emit('[Qt配置] 已加载六标签配置，尚未保存或执行')
        return draft

    def reload(self, arguments, authority):
        self._guard(arguments['token'])
        try:
            draft = self._load()
            if arguments.get('discard_recovery'):
                self.recovery.discard()
                self.capabilities.emit('[Qt配置] 已按本机确认清除恢复草稿')
            return draft
        except Exception:
            raise CapabilityError('configuration_unreadable', '重新加载失败，原界面草稿保留，请核对配置文件') from None

    def close_editor(self, arguments, authority):
        if self.token and arguments['token'] == self.token:
            if arguments.get('discard_revision'):
                self._clear_saved_recovery(arguments['discard_revision'])
            self.token = ''
            self.capabilities.emit('[Qt配置] 编辑上下文已关闭，未保存的界面值不写入配置')
        return None

    def checkpoint(self, arguments, authority):
        if not self.token or arguments['token'] != self.token:
            raise CapabilityError('editor_expired', '配置编辑上下文已失效')
        try:
            self.workspace.projects._validate_paths(self.context)
            if arguments['revision'] != self._revision():
                raise CapabilityError('configuration_changed', '配置已变化，未覆盖恢复草稿')
            self.recovery.write(arguments['revision'], arguments['values'])
        except CapabilityError:
            raise
        except Exception:
            raise CapabilityError('recovery_write_failed', '恢复草稿未写入，现有文件保留；可确认重新加载后重试') from None

    def _clear_saved_recovery(self, revision):
        try:
            self.recovery.discard_saved_revision(revision)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            self.capabilities.emit('[Qt配置] 清理恢复草稿未完成，原文件保留')

    def defaults(self, arguments, authority):
        self._guard(arguments['token'])
        try:
            path = self.context.config_dir / 'test_project_config.default.ini'
            before = hashlib.sha256(path.read_bytes()).digest()
            order = load_default_order(path)
            if hashlib.sha256(path.read_bytes()).digest() != before:
                raise ValueError('default changed')
        except Exception:
            raise CapabilityError('default_unreadable', '默认测试项模板读取失败，当前草稿保留') from None
        self.capabilities.emit('[Qt配置] 已读取原默认命令模板，等待本机保存；全局重试间隔保留')
        return deepcopy(asdict(order)['items'])

    def wifi_interfaces(self, arguments, authority):
        self._guard(arguments['token'])
        from src.core.wifi_interfaces import list_wifi_interface_names
        try:
            names = list(list_wifi_interface_names())
        except Exception:
            raise CapabilityError('wifi_inventory_unavailable', '无线网卡读取失败，请检查网卡及驱动；未改变当前配置') from None
        self.capabilities.emit('[Qt配置] 已读取无线网卡列表；未连接、断开或修改网络')
        return names

    @staticmethod
    def _capture(values, config_dir):
        telnet = TelnetSettings(**values['telnet'])
        telnet.telnet_need_enter_password_flag = 0
        order_values = values['order']
        order = OrderConfig(order_values['command_fail_retry_interval_time'], [OrderItem(
            command=item['command'], retry_times=item['retry_times'],
            expected_segments=[ExpectedSegment(**s) for s in item['expected_segments']]) for item in order_values['items']])
        wifi = ConnectWifiSettings(**values['connect_wifi'])
        info = ProjectInfoSettings(**values['project_info'])
        if order.command_fail_retry_interval_time < 0 or any(item.retry_times < 1 for item in order.items):
            raise CapabilityError('invalid_parameters', '重试次数至少为1，全局重试间隔不能为负数')
        # Same validation as the existing WiFi editor; never scan or connect.
        validate_wifi_options(WifiTestOptions(wifi.connection_test_mode, wifi.security_source,
            bool(wifi.wireless_ping_enable), wifi.wireless_ping_target), bool(wifi.enable), wifi.product_solution)
        runtime = dict(values['runtime'])
        runtime['telnet_enable'] = '0' if bool(telnet.telnet_default_on) else '1'
        runtime = LegacyUiDefaultsStore(config_dir / FILES[1]).validate(runtime)
        push = MessagePushConfigService.validate(values['push'])
        return TestProjectConfig(telnet, order, wifi, info), runtime, push

    @staticmethod
    def _replace(path, data):
        temporary = path.with_name(path.name + '.qt-' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def save(self, arguments, authority):
        self._guard(arguments['token'])
        if arguments['revision'] != self._revision():
            raise CapabilityError('configuration_changed', '磁盘配置或项目版本已改变，未覆盖；请先重新加载并核对')
        if self.workspace.resources.unknown_for(self.context.identity.project_id):
            raise CapabilityError('configuration_unknown', '项目有未核实操作，请先由本机操作员核实')
        config_dir = self.context.config_dir
        try:
            config, runtime, push = self._capture(arguments['values'], config_dir)
        except Exception:
            raise CapabilityError('invalid_parameters', '配置校验失败，请检查整数、运行参数、WiFi选项及推送字段；未写入文件') from None
        owner = 'gui:qt-configuration:' + uuid.uuid4().hex
        uncertain = False
        self.capabilities.resources.acquire(owner, ('device-business', 'configuration'))
        try:
            # Original serializers work on an isolated copy first. No secrets
            # or temporary credentials enter the log or a business job payload.
            with tempfile.TemporaryDirectory(prefix='.qt-config-', dir=str(self.context.root)) as temporary:
                staging = Path(temporary).resolve()
                staging.relative_to(self.context.root.resolve())
                self.workspace.projects._copy_config(config_dir, staging)
                TestItemConfigStore(staging / FILES[0]).save(config)
                LegacyUiDefaultsStore(staging / FILES[1]).save(runtime)
                MessagePushConfigService(staging / FILES[1]).save(push)
                written = {name: (staging / name).read_bytes() for name in FILES}
                if self._revision() != arguments['revision']:
                    raise CapabilityError('configuration_changed', '保存准备期间配置变化，未覆盖，请重新加载')
                previous = {name: (config_dir / name).read_bytes() if (config_dir / name).exists() else None for name in FILES}
                try:
                    for name in FILES:
                        self._replace(config_dir / name, written[name])
                    self.workspace.projects.save(self.context)
                except Exception:
                    for name, data in previous.items():
                        try:
                            if data is None:
                                (config_dir / name).unlink(missing_ok=True)
                            else:
                                self._replace(config_dir / name, data)
                        except Exception:
                            uncertain = True
                    if uncertain:
                        raise CapabilityError('configuration_rollback_failed', '配置恢复未完成，已保留未知保护；请本机核实文件与项目版本') from None
                    raise CapabilityError('configuration_save_failed', '配置保存未完成，已恢复原草稿；请核对存储权限后重试') from None
            self._clear_saved_recovery(arguments['revision'])
            self.capabilities.emit('[Qt配置] 六标签配置已保存并提交项目版本；未执行设备命令或发送消息')
            return self._load()
        except CapabilityError:
            raise
        except Exception:
            raise CapabilityError('configuration_save_failed', '配置保存未完成，请核对ini格式、目录及写入权限；不输出配置内容') from None
        finally:
            self.capabilities.resources.release(owner, uncertain=uncertain)
