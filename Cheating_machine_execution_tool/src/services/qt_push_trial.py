"""Keep a one-shot local notification trial separate from DUT results."""
from configparser import RawConfigParser
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import time
import uuid

from src.core.webhook_target import PLATFORM_NAMES, SAFE_ENDPOINTS, detect_platform
from src.models.capabilities import CapabilityError, CapabilitySpec, object_schema
from src.models.qt_configuration import PushTrialView
from src.services.message_push_config_service import MessagePushConfigService, load_push_project_name, send_test_message
from src.services.qt_configuration_service import push_values_schema


@dataclass(frozen=True)
class PushTrialRequest:
    identifier: str
    editor: str
    revision: str
    binding: str
    created: float
    project_name: str
    values: dict = field(repr=False)


class QtPushTrial:
    def __init__(self, execution):
        self.execution = execution
        self.pending = None
        self.thread = None
        self.result = None
        self.editor = ''
        self.identifier = ''
        token = dict(type='string', minLength=32, maxLength=32)
        session = dict(token=token)
        decision = dict(session, confirmation=token)
        for action, handler, fields, risk in (
            ('preview', self.preview, dict(session, revision=dict(type='string', minLength=64, maxLength=64),
                values=push_values_schema()), 'read'),
            ('execute', self.execute, decision, 'dangerous'),
            ('cancel', self.cancel, decision, 'read'),
        ):
            execution.capabilities.registry.register(CapabilitySpec('notifications.editor.' + action, '本机试发测试消息',
                '使用当前窗口草稿及已保存项目名，明确确认后调用原固定测试消息服务',
                object_schema(fields, tuple(fields)), handler, sources=('gui',), risk=risk))

    @property
    def active(self):
        return self.thread is not None and self.thread.is_alive()

    @property
    def project_path(self):
        return self.execution.context.saved_root / 'Auto_power_on_off_tool/config/test_project_config.ini'

    def _guard(self, token):
        if self.active or self.execution.closing or self.execution.workspace.maintenance.active:
            raise CapabilityError('resource_busy', '消息试发或工作区维护仍在进行，请等待')
        self.execution.configuration._guard(token)

    def preview(self, arguments, authority):
        token, revision = arguments['token'], arguments['revision']
        self._guard(token)
        self.pending = None
        binding = self.execution._binding()
        if revision != self.execution.configuration._revision():
            raise CapabilityError('configuration_changed', '项目配置已变化，请重新加载后核对草稿')
        try:
            values = MessagePushConfigService.validate(arguments['values'])
            project_name = load_push_project_name(self.project_path)
            platform = detect_platform(values['webhook'])
        except ValueError as error:
            raise CapabilityError('notification_invalid', str(error)) from None
        if binding != self.execution._binding() or revision != self.execution.configuration._revision():
            raise CapabilityError('configuration_changed', '预检期间项目配置已变化，请重新加载')
        confirmation = uuid.uuid4().hex
        self.pending = PushTrialRequest(confirmation, token, revision, binding, time.monotonic(), project_name, values)
        summary = '\n'.join((f'消息项目名：{project_name}', f'目标平台：{PLATFORM_NAMES[platform]}',
            f'目的地：当前 Webhook（{SAFE_ENDPOINTS[platform]}）',
            '@所有人：' + ('开启' if values['at_all'] == '1' else '关闭'),
            '发送一条固定测试消息。是否继续？'))
        self.execution._log('[Qt消息推送] 已核对试发平台、已保存项目名和广播选项，等待本机确认')
        return dict(confirmation=confirmation, summary=summary)

    def _take(self, arguments):
        token = arguments['token']
        self._guard(token)
        pending = self.pending
        if not pending or pending.editor != token or pending.identifier != arguments['confirmation']:
            raise CapabilityError('confirmation_expired', '消息试发确认已失效，请重新核对')
        self.pending = None
        return pending

    def execute(self, arguments, authority):
        pending = self._take(arguments)
        if time.monotonic() - pending.created > 120:
            raise CapabilityError('confirmation_expired', '消息试发确认已过期，请重新核对')
        if pending.binding != self.execution._binding() or pending.revision != self.execution.configuration._revision():
            raise CapabilityError('configuration_changed', '确认期间项目配置已变化，未发送消息')
        result = Future()
        thread = Thread(target=self._send, args=(pending, self.project_path, result), name='qt-push-trial', daemon=True)
        try:
            thread.start()
        except RuntimeError:
            raise CapabilityError('notification_worker_unavailable', '无法启动发送线程，请重试') from None
        self.thread, self.result = thread, result
        self.editor, self.identifier = pending.editor, pending.identifier
        return self.snapshot()

    def _send(self, request, path, result):
        def record(message, level='INFO'):
            for secret in (request.values['webhook'].strip(), request.values['secret'].strip()):
                if secret:
                    message = message.replace(secret, '[已隐藏]')
            self.execution._log(message, level, job_id=request.identifier)
            return message

        state = 'failed'
        invoked_sender = False
        try:
            record('[Qt消息推送] 本机已确认，读取已保存项目名后单次试发')
            if (load_push_project_name(path) != request.project_name or
                    request.binding != self.execution._binding()):
                raise ValueError('发送前项目配置已变化，未发送消息')
            # The original service reads an INI. Pass only the confirmed name,
            # without copying unrelated credentials into a temporary file.
            config = RawConfigParser()
            config['project_info'] = {'project_name': request.project_name}
            with TemporaryDirectory(prefix='dutpilot-push-trial-') as temporary:
                snapshot = Path(temporary) / path.name
                with snapshot.open('w', encoding='utf-8') as stream:
                    config.write(stream)
                invoked_sender = True
                platform = send_test_message(request.values, snapshot, log=record)
        except (ValueError, RuntimeError) as error:
            message = str(error)
            if '结果未知' in message:
                state = 'unknown'
            message = record('[Qt消息推送] ' + message, 'WARN' if state == 'unknown' else 'ERROR')
        except Exception:
            if invoked_sender:
                state = 'unknown'
                message = record('[Qt消息推送] 发送结果未知，请先检查群消息', 'WARN')
            else:
                message = record('[Qt消息推送] 无法读取已确认的项目配置，未发送消息', 'ERROR')
        else:
            state = 'accepted'
            message = record(f'[Qt消息推送] {platform}已接受，请在目标群核对测试消息', 'SUCCESS')
        result.set_result(PushTrialView(request.identifier, state, message.removeprefix('[Qt消息推送] ')))

    def cancel(self, arguments, authority):
        self._take(arguments)
        self.execution._log('[Qt消息推送] 操作员取消，未发送消息')

    def snapshot(self):
        if self.result is None or self.editor != self.execution.configuration.token:
            return None
        if self.active:
            return PushTrialView(self.identifier, 'sending', '正在发送测试消息…')
        if not self.result.done():
            return PushTrialView(self.identifier, 'unknown', '发送线程未返回结果，请先检查群消息')
        return self.result.result()
