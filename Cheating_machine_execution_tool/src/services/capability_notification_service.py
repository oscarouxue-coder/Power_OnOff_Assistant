"""Reviewed notification destination and original push configuration/test service."""
from pathlib import Path
import threading
import uuid

from line_check_assistant.paths import resolve_config_dir
from src.models.capabilities import CapabilitySpec, CapabilityError, fingerprint, object_schema
from src.services.message_push_config_service import MessagePushConfigService, send_test_message
from src.core.webhook_target import detect_platform, SAFE_ENDPOINTS


class NotificationCapabilities:
    def __init__(self, service, tool_root):
        self.service = service
        directory = resolve_config_dir(Path(tool_root))
        self.store = MessagePushConfigService(directory / 'config.ini')
        self.project_path = directory / 'test_project_config.ini'
        self.lock = threading.RLock()
        service.registry.register(CapabilitySpec('notifications.read', '查询通知配置', '返回开关、平台及版本，不输出Webhook令牌和密钥。',
            object_schema(), self.read, sources=('local', 'gui')))
        properties = {'revision': dict(type='string', minLength=64, maxLength=64), 'values': object_schema({
            'enabled': dict(type='boolean'), 'at_all': dict(type='boolean'),
            'webhook': dict(type='string', maxLength=4096), 'secret': dict(type='string', maxLength=4096)})}
        service.registry.register(CapabilitySpec('notifications.patch', '保存通知配置', '共用原配置服务合并保存；目的地/广播范围须本地审阅，已授权同范围不重复确认。打开的配置编辑器不被覆盖。',
            object_schema(properties, ('revision', 'values')), self.patch, risk='modify', sources=('local', 'gui'),
            resource_requirements=('device-business', 'configuration'), resource_scope=lambda a: self.scope(a, patch=True)))
        service.registry.register(CapabilitySpec('notifications.test', '向已审核目的地试发', '异步调用原测试消息服务，只发固定测试正文，不接受任意收件人/正文；接口接受后仍须群内核对。',
            object_schema({'revision': properties['revision']}, ('revision',)), self.test, risk='dangerous',
            sources=('local', 'gui'), execution_mode='job', resource_scope=self.scope))

    def _values(self, arguments, patch=False):
        current = self.store.load()
        if fingerprint(current) != arguments['revision']:
            raise CapabilityError('notification_changed', '通知配置已变化，未覆盖配置或试发')
        values = dict(current)
        if patch:
            for key, value in arguments['values'].items():
                destination = 'dingtalk_flag' if key == 'enabled' else key
                values[destination] = ('1' if value else '0') if key in ('enabled', 'at_all') else value
        values = self.store.validate(values)
        disabling = patch and arguments['values'] == {'enabled': False}
        if values['webhook'] and not disabling:
            detect_platform(values['webhook'])
        elif values['dingtalk_flag'] == '1':
            raise CapabilityError('notification_target_required', '启用通知前须配置明确目的地')
        return current, values

    def scope(self, arguments, patch=False):
        _, values = self._values(arguments, patch)
        if patch and arguments['values'] == {'enabled': False}:
            return None
        if not values['webhook']:
            if patch:
                return None
            raise CapabilityError('notification_target_required', '没有可试发的通知目的地')
        platform = detect_platform(values['webhook'])
        destination = fingerprint({k: values[k] for k in ('webhook', 'secret', 'at_all')})
        return dict(id='notification:' + destination, destination_revision=destination,
            platform=platform, endpoint=SAFE_ENDPOINTS[platform], at_all=values['at_all'] == '1',
            purpose='保存该目的地及固定测试消息；不授权任意正文或其它群')

    def read(self, arguments, authority):
        with self.lock:
            values = self.store.load()
            try:
                platform = detect_platform(values['webhook']) if values['webhook'] else None
            except ValueError:
                platform = 'invalid'
            return dict(enabled=values['dingtalk_flag'] == '1', at_all=values['at_all'] == '1',
                configured=bool(values['webhook']), platform=platform, destination_valid=platform not in (None, 'invalid'),
                revision=fingerprint(values), secrets_omitted=True)

    def patch(self, arguments, authority):
        with self.service.resources.lease('configuration:' + uuid.uuid4().hex, ('device-business', 'configuration')), self.lock:
            if self.service.snapshot().get('configuration_editor_open'):
                raise CapabilityError('editor_open', '消息推送编辑器仍有草稿上下文，未覆盖')
            _, values = self._values(arguments, patch=True)
            self.store.save(values)
            self.service.emit('[消息推送] 已通过原配置服务保存审核范围，凭据省略；未试发')
            return self.read({}, authority)

    def test(self, arguments, authority):
        with self.lock:
            _, values = self._values(arguments)
            destination = self.scope(arguments)
        def recheck():
            self._values(arguments)
            if self.scope(arguments) != destination:
                raise CapabilityError('notification_changed', '试发准入前目的地或广播范围变化，未下发')
        def run(context):
            context.stop.checkpoint()
            context.event('sending', '向本地审核目的地下发原固定测试消息，凭据省略', dispatched=True)
            # The original HTTP service owns its timeout; do not cancel a submitted
            # request halfway or retry an uncertain POST.
            platform = send_test_message(values, self.project_path, log=lambda message: context.event('sending', message))
            return dict(ok=True, accepted=True, platform=platform, delivery='仍须在目标群核对收到', retried=False)
        return self.service.jobs.start('notifications.test', dict(configuration_revision=arguments['revision'],
            destination_revision=destination['destination_revision']), authority, (destination['id'],), run, recheck=recheck)
