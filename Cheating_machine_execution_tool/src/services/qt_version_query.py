"""Run the original version query with one local editor's Telnet draft."""
from dataclasses import asdict, dataclass, field, replace
import ipaddress
import time
import uuid

from line_check_assistant.test_item_config_store import TelnetSettings
from src.models.capabilities import CapabilityError, CapabilitySpec, object_schema
from src.models.qt_configuration import VersionQueryView
from src.services.capability_configuration_service import configuration_schema
from src.services.capability_jobs import TERMINAL
from src.services.device_project_info_service import (
    DEVICEINFO_COMMAND, PROC_VERSION_COMMAND, DeviceProjectInfoQueryRequest, query_device_project_info,
)
from src.services.telnet_post_login_service import describe_telnet_post_login


@dataclass(frozen=True)
class VersionQueryRequest:
    confirmation: str
    editor: str
    binding: str
    revision: str
    channel: int
    created: float
    request: DeviceProjectInfoQueryRequest = field(repr=False)


class QtVersionQuery:
    def __init__(self, execution):
        self.execution = execution
        self.capabilities = execution.capabilities
        self.pending = None
        self.latest = ''
        self.editor = ''
        self.channel = 0
        token = dict(type='string', minLength=32, maxLength=32)
        session = dict(token=token)
        telnet = configuration_schema('telnet')
        # This query uses the original fixed read timeouts and port-zero fallback.
        telnet['properties']['port']['minimum'] = 0
        telnet['properties']['timeout'] = dict(type='integer')
        for action, handler, fields, risk in (
            ('preview', self.preview, dict(session, revision=dict(type='string', minLength=64, maxLength=64),
                channel=dict(type='integer', minimum=1, maximum=16), telnet=telnet), 'read'),
            ('execute', self.execute, dict(session, confirmation=token), 'dangerous'),
            ('cancel', self.cancel, dict(session, confirmation=token), 'read'),
        ):
            self.capabilities.registry.register(CapabilitySpec('version.editor.' + action, '本机查询当前样机版本',
                '绑定配置编辑器和一个通道，使用本机 Telnet 草稿调用原版本查询',
                object_schema(fields, tuple(fields)), handler, sources=('gui',), risk=risk,
                execution_mode='job' if action == 'execute' else 'sync',
                resource_requirements=('device-business', 'channel', 'adapter') if action == 'execute' else ()))

    def _check_editor(self, token):
        if token != self.execution.configuration.token:
            raise CapabilityError('editor_expired', '配置窗口已失效，请重新打开')

    def _ready(self, token):
        self._check_editor(token)
        self.execution._prepare_guard(own_configuration=token)
        if self.execution.other_jobs_active():
            raise CapabilityError('resource_busy', '其它项目正在执行设备任务，请等待收尾')

    def preview(self, arguments, authority):
        token, revision = arguments['token'], arguments['revision']
        self._ready(token)
        self.pending = None
        if revision != self.execution.configuration._revision():
            raise CapabilityError('configuration_changed', '项目配置已变化，请重新加载后核对草稿')
        binding = self.execution._binding()
        number = arguments['channel']
        operator = replace(authority, channels=(number,))
        _, (channel,) = self.capabilities.devices.selected({'channel_ids': [number]}, operator)
        bind_ip, host = channel.network_card_ip.strip(), channel.device_manage_ip.strip()
        try:
            local = ipaddress.IPv4Address(bind_ip)
            remote = ipaddress.IPv4Address(host)
            if local == remote or local.is_unspecified or remote.is_unspecified:
                raise ValueError('invalid endpoint')
        except ValueError:
            raise CapabilityError('invalid_target', '当前通道的 PC 静态 IP 或样机管理 IP 无效') from None
        telnet = TelnetSettings(**arguments['telnet'])
        if not all(flag.strip() for flag in (telnet.input_user_flag, telnet.input_password_flag, telnet.login_success_flag)):
            raise CapabilityError('configuration_incomplete', '请补齐 Telnet 用户名、密码和登录成功提示符')
        if binding != self.execution._binding() or revision != self.execution.configuration._revision():
            raise CapabilityError('configuration_changed', '预检期间项目配置已变化，请重新加载')
        confirmation = uuid.uuid4().hex
        request = DeviceProjectInfoQueryRequest(bind_ip, host, telnet)
        self.pending = VersionQueryRequest(confirmation, token, binding, revision, number, time.monotonic(), request)
        self.execution._log(f'[Qt项目信息] 已核对当前草稿和 CH{number:02d}')
        summary = ''
        if telnet.login_success_flag == '>':
            summary = '\n'.join((self.execution.context.identity.name,
                f'CH{number:02d} · {channel.vlan_name or channel.adapter_alias} · {bind_ip} → {host}:{telnet.port or 23}',
                describe_telnet_post_login(telnet), f'后续只读命令：{DEVICEINFO_COMMAND}、{PROC_VERSION_COMMAND}',
                '是否继续查询？'))
        return dict(confirmation=confirmation, summary=summary)

    def _take(self, arguments):
        token = arguments['token']
        self._check_editor(token)
        pending = self.pending
        if not pending or pending.editor != token or pending.confirmation != arguments['confirmation']:
            raise CapabilityError('confirmation_expired', '版本查询确认已失效，请重新查询')
        self.pending = None
        return pending

    def execute(self, arguments, authority):
        pending = self._take(arguments)
        self._ready(pending.editor)
        if time.monotonic() - pending.created > 120:
            raise CapabilityError('confirmation_expired', '版本查询确认已过期，请重新查询')

        def recheck():
            self._check_editor(pending.editor)
            if pending.revision != self.execution.configuration._revision():
                raise CapabilityError('configuration_changed', '查询前配置变化，请重新加载')

        numbers = (pending.channel,)
        recheck()
        self.execution._verify_nics(numbers, pending.binding)
        operator = replace(authority, channels=numbers, operation_id=pending.confirmation)
        request = pending.request
        password = request.telnet.password

        def safe_message(text):
            return text.replace(password, '***') if password else text

        def run(context, snapshot, channels):
            context.stop.checkpoint()
            context.event('version', '使用已核对的当前 Telnet 草稿调用原版本查询', dispatched=True)
            try:
                result = query_device_project_info(request, emit=lambda line: context.event('version', safe_message(line)))
            except Exception as error:
                message = safe_message(str(error) or '样机版本查询失败')
                context.event('version', '查询失败：' + message)
                return dict(ok=False, state='failed', error=message)
            context.event('version', '查询成功，已读取三项样机版本信息')
            return dict(ok=True, state='succeeded', result=asdict(result))

        self.execution._admission_binding = pending.binding
        try:
            started = self.capabilities.devices._job('device.version', {'channel_ids': list(numbers)}, operator, run,
                recorded_extra={'source': 'editor_draft'}, precheck=recheck)
        finally:
            self.execution._admission_binding = None
        identifier = started['job_id']
        self.execution.jobs[identifier] = dict(authority=operator, after=0, status=None, channels={}, progress=None,
            title='样机版本查询', result_view='查看项目信息和项目日志', stop_available=False)
        self.latest = self.execution.latest = identifier
        self.editor, self.channel = pending.editor, pending.channel
        self.execution.parameters = ()
        self.execution._log('[Qt项目信息] 已提交版本查询', job_id=identifier)
        return self.snapshot()

    def cancel(self, arguments, authority):
        self._take(arguments)
        self.execution._log('[Qt项目信息] 已取消登录后命令确认，未查询')

    def snapshot(self):
        if not self.latest or self.editor != self.execution.configuration.token:
            return None
        status = self.execution.jobs[self.latest]['status'] or {}
        result = status.get('result') or {}
        state = status.get('state', 'queued')
        active = state not in TERMINAL or (self.latest == self.execution.latest and not self.execution.idle)
        values = result.get('result')
        fields = ('software_version', 'internal_software_version', 'onu_compile_time')
        return VersionQueryView(self.latest, state, active, self.channel,
            tuple(values[key] for key in fields) if values else (), result.get('error', ''))
