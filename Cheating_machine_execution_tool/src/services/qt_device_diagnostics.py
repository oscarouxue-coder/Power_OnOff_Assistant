"""Project-local Qt diagnostic scope, tool selection and monitor policy."""
from dataclasses import asdict
from functools import partial
from time import monotonic
from uuid import uuid4

from line_check_assistant.config_store import ChannelConfigStore
from src.core.ai_network_probe import probe_connectivity
from src.core.serial_inventory import normalize_com_port
from src.models.ai_diagnostics import DebugTriggerPolicy
from src.models.ai_permissions import PERMISSION_LABELS
from src.models.capabilities import CapabilityAuthority, CapabilityError, CapabilitySpec, object_schema
from src.services.ai_batch_service import BatchSharedFailure
from src.models.serial_models import SerialSettings
from src.services.ai_debug_service import DiagnosticToolExecutor
from src.services.ai_monitor_service import AiMonitorService
from src.services.ai_store import profile_fingerprint
from src.services.project_diagnostic_transport import ProjectDiagnosticTransport


DIAGNOSTIC_TOOLS = frozenset(('ask_user', 'read_test_evidence', 'read_pc_environment',
    'read_network_state', 'read_serial_log', 'read_dut_state', 'probe_connectivity'))
FEATURES = ('power', 'telnet', 'wifi', 'ping')
CONFIGURE = 'diagnostics.qt.configure'


class QtDiagnosticMonitor(AiMonitorService):
    def start(self, job, stop, executor):
        identifier = super().start(job, stop, executor)
        try:
            state = self.collection_status(identifier)
            if not state['enabled']:
                raise ValueError(state['reason'])
            return identifier
        except BaseException:
            self.finish(identifier)
            raise

    def runtime(self, identifier):
        state = super().runtime(identifier)
        state.update(goal='读取指定通道异常的诊断证据并报告结果',
                     approval='仅开放预定义诊断查询，首次登录沿用本次监控权限')
        return state

    def tools(self):
        return [tool for tool in super().tools() if tool['name'] in DIAGNOSTIC_TOOLS]


class QtDeviceDiagnostics:
    def __init__(self, execution, store):
        self.execution = execution
        self.store = store
        self.pending = None
        self.registered = False
        self.targets = ()
        self.profile = None
        self.run_id = None
        self.tool_factory = partial(DiagnosticToolExecutor, transport_factory=partial(
            ProjectDiagnosticTransport, resources=execution.workspace.resources,
            project_context=execution.context, recovery_store=store))

    def bind(self, chat):
        self.chat = chat
        chat.diagnostic.probe_connectivity = self.probe
        chat.diagnostic.target_current = chat.conversation.target_current
        chat.conversation.batch.host_busy = self.host_busy

    def _binding(self):
        return self.chat._profile(), self.chat.handoff.configured_targets(), self.chat.conversation.context.run_id

    def active(self, target):
        return (target in self.targets and self.profile == self.chat._profile()
                and self.run_id == self.chat.conversation.context.run_id
                and self.chat.conversation.target_current(target))

    def host_busy(self):
        e = self.execution
        return (e.closed or e.closing or e.workspace_close_requested() or e.workspace.maintenance.active
                or e.editor_open or not e.idle or e.other_jobs_active())

    def busy(self, target):
        e = self.execution
        if (e.closed or e.closing or e.workspace_close_requested() or e.workspace.maintenance.active
                or e.editor_open or target is None or e.other_jobs_active()):
            return True
        keys = ['adapter:' + target.vlan, 'serial:' + target.port]
        if e.workspace.resources.busy_for(e.context.identity.project_id, keys):
            return True
        if e.manager:
            state = e.manager.diagnostic_state(target.port)
            if state['control_owner'].startswith('qt-diagnostic:') and self.power_port_conflict(target):
                return True
            if state['closing_in_program'] or (state['control_owner'] and not state['control_owner'].startswith('qt-diagnostic:')):
                return True
        if not e.idle:
            session = e.resume.log_session(e.power_log_job)
            if not session or not e.has_only_power_tasks() or session.run_id != self.chat.diagnostic.run_id:
                return True
            with session.lock:
                if target.channel not in session.ready or target.channel in session.active_started:
                    return True
        # Monitoring may be armed before a new run. Its own bound run is
        # revalidated by AiMonitorService for each tool.
        monitor = self.chat.diagnostic
        monitored = (monitor.trigger.enabled and monitor.run_active and target in self.targets
                     and target.channel in monitor.trigger.policy.channels and self.profile == self.chat._profile()
                     and self.chat.conversation.target_current(target))
        return not (monitored or self.active(target))

    def shared_busy(self, target):
        e = self.execution
        return not e.idle or self.busy(target) or e.workspace.resources.busy_for(e.context.identity.project_id, ('wifi:host',))

    def probe(self, target, settings, path, stop, emit, busy):
        e = self.execution
        if busy(target) or stop.is_set():
            raise ValueError('目标或共享资源正在使用，跳过 Ping')
        adapter = settings.get('wifi_wireless_card_name') if path == 'wireless' else target.vlan
        keys = ['adapter:' + adapter.casefold()] if adapter else []
        if path == 'wireless':
            keys.append('wifi:host')
        owner = 'qt-diagnostic-ping:' + uuid4().hex
        try:
            e.workspace.resources.acquire(owner, e.context.identity.project_id, e.context.identity.name, keys)
        except CapabilityError as error:
            if path == 'wireless':
                raise BatchSharedFailure('共享无线资源不可用：' + str(error)) from error
            raise
        try:
            return probe_connectivity(target, settings, path, stop, emit, busy)
        finally:
            e.workspace.resources.release(owner)

    def power_port_conflict(self, target):
        store = ChannelConfigStore(self.execution.context.config_dir / 'network_card_ip.ini')
        return normalize_com_port(target.port) == normalize_com_port(store.load_power_serial_port())

    def acquire_serial(self, target, stop):
        port = normalize_com_port(target.port)
        if not port or self.power_port_conflict(target):
            raise ValueError('目标串口无效或与程控电源串口冲突')
        if self.busy(target) or stop.is_set():
            raise ValueError('目标或串口已变化、被占用或已取消')
        owner = 'qt-diagnostic:' + uuid4().hex
        manager = self.execution.manager
        session = manager.acquire_control(owner, SerialSettings(port))
        def release():
            manager.release(owner, port, wait=True)
        try:
            invalid = self.busy(target) or stop.is_set()
        except BaseException:
            release()
            raise
        if invalid:
            release()
            raise ValueError('取得串口后目标已失效，本次跳过')
        return session, release, stop

    def view(self):
        profile, targets, run = self._binding()
        token = uuid4().hex
        self.pending = (token, monotonic() + 300, profile, targets, run)
        d = self.chat.diagnostic
        policy = self.store.setting('trigger_policy', {}) or asdict(d.trigger.policy)
        return dict(token=token, model=profile.model if profile else '', provider=profile.base_url if profile else '',
            targets=[(t.channel, f'通道 {t.channel} · {t.vlan} · {t.port} · {t.bind_ip} → {t.host}:{t.telnet_port}') for t in targets],
            policy=policy, active=[t.channel for t in targets if self.active(t)],
            permission=d.monitor.mode, status=asdict(d.monitor_status()))

    def disable(self):
        self.pending = None
        self.targets = ()
        self.profile = None
        self.chat.diagnostic.enable_monitor(False)
        if self.execution.terminal is not None:
            self.execution.terminal.set_diagnostic_receiver(None)
        conversation = self.chat.conversation
        with conversation.lock:
            running = tuple(conversation.running)
        for identifier in running:
            session = self.store.chat(identifier)
            if conversation.local_mode(session) in ('channel', 'batch'):
                conversation.stop(identifier)
        self.chat.diagnostic.emit('[Ai助手] 已关闭本项目主动诊断和异常监控')

    @staticmethod
    def _serial_observer(receiver, targets):
        ports = {(t.vlan.casefold(), t.port.upper()): t for t in targets}
        def receive(vlan, event):
            with receiver.lock:
                target = ports.get((vlan.casefold(), event.port.upper()))
                if (target and receiver.trigger.enabled and target.channel in receiver.trigger.policy.channels
                        and receiver.targets.get(target.channel) == target):
                    receiver(vlan, event)
        return receive

    def confirm(self, token, channels, features, threshold, cooldown, keywords, codes, monitor, permission):
        registry = self.execution.instance_registry()
        if not self.registered:
            words = dict(type='array', items=dict(type='string', minLength=1, maxLength=256), maxItems=64)
            fields = dict(token=dict(type='string', minLength=32, maxLength=32),
                channel_ids=dict(type='array', items=dict(type='integer', minimum=1, maximum=16),
                                 minItems=1, maxItems=16, uniqueItems=True),
                features=dict(type='array', items=dict(type='string', enum=list(FEATURES)), uniqueItems=True),
                threshold=dict(type='integer', minimum=1, maximum=20), cooldown=dict(type='integer', minimum=1, maximum=3600),
                keywords=words, codes=words, monitor=dict(type='boolean'),
                permission=dict(type='string', enum=list(PERMISSION_LABELS)))
            registry.register(CapabilitySpec(CONFIGURE, '确认项目诊断通道', '应用本机确认的诊断范围与监控策略',
                object_schema(fields, fields), self._apply, risk='modify', sources=('gui',)))
            self.registered = True
        args = dict(token=token, channel_ids=list(channels), features=list(features), threshold=threshold,
                    cooldown=cooldown, keywords=list(keywords), codes=list(codes), monitor=monitor, permission=permission)
        operator = CapabilityAuthority('local-operator:' + self.execution.context.identity.project_id,
            self.execution.session, uuid4().hex, tuple(channels), source='gui', approved=True)
        self.execution.capabilities.execute(CONFIGURE, args, operator)

    def _apply(self, args, authority):
        token, channels, features = args['token'], args['channel_ids'], args['features']
        threshold, cooldown = args['threshold'], args['cooldown']
        keywords, codes, monitor, permission = args['keywords'], args['codes'], args['monitor'], args['permission']
        pending, self.pending = self.pending, None
        if not pending or token != pending[0] or monotonic() > pending[1] or self._binding() != pending[2:]:
            raise ValueError('确认期间项目通道、模型或批次已变化，请重新打开设置')
        profile, targets, run = pending[2:]
        if not profile or profile.capability != '可自动诊断' or profile.tested_fingerprint != profile_fingerprint(profile):
            raise ValueError('请先选择已通过工具验证的模型')
        if not set(channels) <= {t.channel for t in targets} or (monitor and not features):
            raise ValueError('请核对诊断通道、监控条件、阈值和冷却时间')
        policy = DebugTriggerPolicy(tuple(channels), tuple(features), threshold, cooldown, tuple(keywords), tuple(codes))
        d = self.chat.diagnostic
        with d.lock:
            d.monitor.apply(profile, targets, policy, permission, monitor, confirmed=True)
            self.targets = tuple(t for t in targets if t.channel in channels)
            self.profile, self.run_id = profile, run
            d.serial_receiver.pending.clear()
            self.execution.terminal.set_diagnostic_receiver(self._serial_observer(d.serial_receiver, self.targets) if monitor else None)
        d.emit('[Ai助手] 本机主动诊断已确认，通道 ' + '、'.join(str(c) for c in channels))
