"""Local selection for the original one-shot power on/off services."""
from dataclasses import dataclass

from line_check_assistant.network_ops import adapter_alias_from_display
from src.core.serial_inventory import normalize_com_port
from src.models.capabilities import CapabilityError, CapabilitySpec, object_schema
from src.models.channel_resource_options import POWER_SERIAL_OPTIONS
from src.services.power_on_service import turn_off_selected_channels, turn_on_selected_channels


CAPABILITY = 'power.qt_single'
POWER_ACTIONS = {'up': '上电', 'down': '下电'}


@dataclass(frozen=True)
class SinglePowerSelection:
    binding: str
    configured_port: str
    numbers: tuple
    detected_ports: tuple


@dataclass(frozen=True)
class SinglePowerTarget:
    port: str
    action: str
    binding: str


class QtSinglePower:
    def __init__(self, execution):
        self.execution = execution
        self.approval = None

    def register(self):
        self.execution.capabilities.registry.register(CapabilitySpec(CAPABILITY, '单次自动上/下电',
            '仅本机确认，使用原指定通道的电源服务，空电源口仅记录人工重启确认。',
            object_schema({'token': dict(type='string', minLength=32, maxLength=32)}, ['token']),
            self._execute, risk='dangerous', execution_mode='job', resource_requirements=('device-business', 'power'),
            sources=('gui',)))

    def selection(self, detected_ports):
        execution = self.execution
        execution._prepare_guard()
        binding = execution._binding()
        data = execution._snapshot()
        if execution._binding() != binding:
            raise CapabilityError('configuration_changed', '读取时配置已变化，请重新核对电源和通道')
        numbers = tuple(int(channel['section'].rsplit('_', 1)[1]) for channel in data['channels'] if channel['enabled'])
        if not numbers or len(set(numbers)) != len(numbers) or any(not 1 <= number <= 16 for number in numbers):
            raise CapabilityError('invalid_target', '请先勾选并保存有效通道，再执行单次上/下电')
        configured = normalize_com_port(data['power_serial_port'])
        return SinglePowerSelection(binding, configured, numbers, tuple(detected_ports))

    def preview(self, target, detected_ports):
        selected = self.selection(detected_ports)
        if selected.binding != target.binding:
            raise CapabilityError('configuration_changed', '项目或通道配置已变化，请重新打开单次上/下电')
        if target.action not in POWER_ACTIONS or target.port not in (*POWER_SERIAL_OPTIONS, selected.configured_port, *selected.detected_ports):
            raise CapabilityError('invalid_target', '电源动作或串口候选已变化，请重新选择')
        action = POWER_ACTIONS[target.action]
        targets = '、'.join(f'CH{number:02d}' for number in selected.numbers)
        summary = f'项目：{self.execution.context.identity.name}\n通道：{targets}\n操作：{action}\n'
        if target.port:
            verb = '开启' if target.action == 'up' else '关闭'
            summary += f'程控电源：{target.port}\n仅{verb}所列通道，按所列顺序执行，相邻命令间隔 1 秒。'
        else:
            summary += '程控电源：未选择\n请手动重启上述样机。确认后只记录人工操作，无串口指令。'
        return selected, summary

    def dispatch(self, confirmation, authority):
        self.approval = (confirmation, authority)
        try:
            return self.execution.capabilities.execute(CAPABILITY, {'token': confirmation.token}, authority)
        finally:
            self.approval = None

    def _execute(self, arguments, authority):
        if self.approval is None or self.approval[0].token != arguments['token'] or self.approval[1] != authority:
            raise CapabilityError('approval_required', '须从当前项目的单次上/下电界面确认')
        confirmation = self.approval[0]
        target = confirmation.power_target
        execution = self.execution
        numbers = confirmation.channel_ids
        data = execution._snapshot()
        aliases = {int(c['section'].rsplit('_', 1)[1]): adapter_alias_from_display(c['adapter_alias'] or c['vlan_name'])
                   for c in data['channels'] if c['enabled']}

        def recheck():
            execution._prepare_guard()
            if execution.workspace_close_requested() or execution._binding() != target.binding:
                raise CapabilityError('configuration_changed', '准入前项目已关闭或配置已变化，未执行单次上/下电')

        resources = ['device-business', *(f'channel:{number}' for number in numbers)]
        adapters = {}
        if target.port:
            named = tuple(number for number in numbers if aliases.get(number))
            if named:
                adapters = execution._verify_nics(named, target.binding)
            resources.extend('adapter:' + aliases[number].casefold() for number in named)
            resources.append('serial:' + target.port)
            configured = normalize_com_port(data['power_serial_port'])
            if configured and configured != target.port:
                resources.append('power:' + configured)

        def run(context):
            context.stop.checkpoint()
            if execution.workspace_close_requested():
                return dict(ok=False, state='stopped', message='工作区正在关闭，未执行单次上/下电')
            if not target.port:
                message = '操作员已确认手动重启，未向串口发送指令'
                context.event('power_manual', message)
                return dict(ok=True, state='succeeded', message=message, manual=True)
            context.event('power', f'调用原单次{POWER_ACTIONS[target.action]}服务：{target.port}，通道 {numbers}', dispatched=True)
            engine = turn_on_selected_channels if target.action == 'up' else turn_off_selected_channels
            result = engine(target.port, numbers, on_output=lambda line: context.event('power', line))
            context.event('power', result.message)
            return dict(ok=result.ok, state='succeeded' if result.ok else 'unknown', message=result.message)

        result = execution.capabilities.jobs.start(CAPABILITY, dict(channel_ids=list(numbers), port=target.port,
            action=target.action, target_binding=target.binding), authority, resources, run, recheck=recheck)
        return result, adapters
