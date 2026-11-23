"""Bind the local six-tab editor draft to one original pretest job."""
from dataclasses import asdict, dataclass, replace
import time
import uuid

from line_check_assistant.config_store import ChannelConfig
from line_check_assistant.test_item_config_store import ExpectedSegment, OrderConfig, OrderItem, TelnetSettings
from src.models.capabilities import CapabilityError, CapabilitySpec, object_schema
from src.models.test_item_pretest_models import PretestRequest
from src.services.capability_configuration_service import configuration_schema
from src.services.project_status_service import result_state
from src.services.telnet_post_login_service import describe_telnet_post_login
from src.services.test_item_pretest_service import prepare_pretest_request, run_pretest


@dataclass(frozen=True)
class PretestConfirmation:
    token: str
    editor: str
    binding: str
    created: float
    request: PretestRequest


class QtPretest:
    def __init__(self, execution):
        self.execution = execution
        self.capabilities = execution.capabilities
        self.pending = None
        self.latest = ''
        text = dict(type='string', minLength=32, maxLength=32)
        session = dict(token=text)
        for name, handler, fields, risk in (
            ('preview', self.preview, dict(session, revision=dict(type='string', minLength=64, maxLength=64),
                telnet=configuration_schema('telnet'), order=configuration_schema('order')), 'read'),
            ('execute', self.execute, dict(session, confirmation=text), 'dangerous'),
            ('cancel', self.cancel, session, 'read'),
            ('stop', self.stop, session, 'modify'),
        ):
            self.capabilities.registry.register(CapabilitySpec('pretest.editor.' + name, '本机预备测试',
                '本机确认后使用编辑器当前快照执行原单次预备测试', object_schema(fields, tuple(fields)),
                handler, sources=('gui',), risk=risk, execution_mode='job' if name == 'execute' else 'sync',
                cancellation='cooperative' if name == 'execute' else 'none',
                resource_requirements=('device-business', 'channel', 'adapter') if name == 'execute' else ()))

    def _check(self, token):
        if not token or self.execution.configuration.token != token:
            raise CapabilityError('editor_expired', '测试项配置窗口已失效')

    def _prepare_guard(self, token):
        self._check(token)
        self.execution._prepare_guard(own_configuration=token)
        if self.execution.other_jobs_active():
            raise CapabilityError('resource_busy', '其它项目正在执行设备任务，请等待安全收尾')

    def preview(self, arguments, authority):
        token = arguments['token']
        self.pending = None
        self._prepare_guard(token)
        if arguments['revision'] != self.execution.configuration._revision():
            raise CapabilityError('configuration_changed', '项目配置已变化，请重新加载后核对草稿')
        binding = self.execution._binding()
        data = self.execution._snapshot()
        channels = [ChannelConfig(**row) for row in data['channels'] if row['enabled']]
        telnet = TelnetSettings(**arguments['telnet'])
        order = OrderConfig(0, [OrderItem(command=item.get('command', '').strip(), retry_times=1,
            expected_segments=[ExpectedSegment(**segment) for segment in item.get('expected_segments', ())])
            for item in arguments['order'].get('items', ())])
        try:
            request = prepare_pretest_request(channels, order, telnet)
        except ValueError as error:
            raise CapabilityError('configuration_incomplete', str(error)) from None
        if self.execution._binding() != binding:
            raise CapabilityError('configuration_changed', '预检期间项目配置已变化')
        confirmation = uuid.uuid4().hex
        self.pending = PretestConfirmation(confirmation, token, binding, time.monotonic(), request)
        targets = '\n'.join(f'{channel.section} / {channel.vlan_name or channel.adapter_alias}'
            f' · {channel.network_card_ip} → {channel.device_manage_ip}:{telnet.port}' for channel in request.channels)
        summary = '\n'.join((self.execution.context.identity.name,
            f'按当前窗口顺序执行 {len(order.items)} 条测试命令，每通道每条一次。',
            targets, describe_telnet_post_login(telnet),
            '将准备网卡并登录样机，命令可能改变设备状态。当前草稿不会自动保存。是否执行？'))
        self.execution._log('[Qt预备测试] 已校验草稿及通道，等待本机确认')
        return dict(confirmation=confirmation, summary=summary)

    def execute(self, arguments, authority):
        pending, self.pending = self.pending, None
        token = arguments['token']
        self._prepare_guard(token)
        if (not pending or pending.token != arguments['confirmation'] or pending.editor != token
                or time.monotonic() - pending.created > 120):
            raise CapabilityError('confirmation_expired', '预备测试确认已失效，请重新核对')
        request = pending.request
        numbers = tuple(int(channel.section.rsplit('_', 1)[1]) for channel in request.channels)
        self.execution._verify_nics(numbers, pending.binding)
        operator = replace(authority, operation_id=pending.token, channels=numbers)

        def run(context, snapshot, channels):
            context.stop.checkpoint()
            context.event('pretest', '使用已确认的编辑器草稿调用原预备测试，每条一次', dispatched=True)
            result = run_pretest(request, context.stop.event,
                lambda text, tag: context.event('pretest.' + tag if tag else 'pretest', text))
            outcome = result_state(result)
            state = 'stopped' if context.stop.is_set() else 'skipped' if outcome == 'unchecked' else outcome
            return dict(ok=state == 'succeeded', state=state, outcome=outcome, result=asdict(result))

        self.execution._admission_binding = pending.binding
        try:
            started = self.capabilities.devices._job('pretest.start', {'channel_ids': list(numbers)}, operator, run,
                recorded_extra={'source': 'editor_draft', 'command_count': len(request.order.items)},
                precheck=lambda: self._check(token))
        finally:
            self.execution._admission_binding = None
        identifier = started['job_id']
        self.execution.jobs[identifier] = dict(authority=operator, after=0, status=None, channels={}, progress=None,
            title='预备测试', result_view='查看测试项配置和项目日志')
        self.latest = self.execution.latest = identifier
        self.execution.parameters = ()
        self.execution._log('[Qt预备测试] 本机确认后提交原任务', job_id=identifier)
        return identifier

    def cancel(self, arguments, authority):
        self._check(arguments['token'])
        self.pending = None
        self.execution._log('[Qt预备测试] 操作员取消，未启动任务', 'WARN')

    def stop(self, arguments, authority):
        self._check(arguments['token'])
        if self.latest and self.latest == self.execution.latest:
            return self.execution.stop(self.latest)
        return {}

    def snapshot(self):
        identifier = self.latest
        if not identifier or identifier != self.execution.latest:
            return '', '', False, ''
        status = self.execution.jobs[identifier]['status'] or {}
        result = status.get('result')
        if not isinstance(result, dict):
            result = {}
        state = status.get('state', 'queued')
        counts = result.get('result')
        keys = ('total', 'executed', 'passed', 'failed', 'unchecked', 'device_errors')
        if isinstance(counts, dict) and all(type(counts.get(key)) is int and counts[key] >= 0 for key in keys):
            message = (f"共 {counts['total']} 条，已下发 {counts['executed']}，成功 {counts['passed']}，"
                       f"失败 {counts['failed']}，未校验 {counts['unchecked']}，"
                       f"未执行 {counts['total'] - counts['executed']}，设备异常 {counts['device_errors']}。")
        else:
            message = result.get('error', '')
        active = not self.execution.idle
        if state == 'skipped' and result.get('outcome') == 'unchecked':
            state = 'unchecked'
        return identifier, state, active, message
