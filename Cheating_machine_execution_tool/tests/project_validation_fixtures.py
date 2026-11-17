"""Automated regression fixtures: real orchestration over fake physical transports."""
from contextlib import ExitStack
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace
import threading
from unittest.mock import patch

from line_check_assistant.network_ops import CommandResult
from src.models.upgrade_stop import UpgradeStopped

active_fixture = ContextVar('validation_fixture', default=None)
KINDS = ('network', 'aging', 'power', 'serial', 'upgrade', 'parameters', 'onu', 'dut', 'ai')


class Gate:
    def __init__(self, timeout=15):
        self.entered = threading.Event()
        self.proceed = threading.Event()
        self.commands = []
        self.timeout = timeout

    def checkpoint(self, command, control, emit):
        if not self.entered.is_set():
            self.entered.set()
            if not self.proceed.wait(self.timeout):
                raise RuntimeError('模拟传输等待超时；未访问真实资源')
        if control.is_set():
            raise UpgradeStopped('模拟操作已在命令边界安全停止')
        self.commands.append(command)
        emit('[隔离模拟][命令] ' + command)


def transport(command):
    fixture = active_fixture.get()
    if fixture is None:
        raise AssertionError('模拟传输缺少明确的项目上下文')
    gate, control, emit = fixture
    gate.checkpoint(command, control, emit)


class FakeSerial:
    def write(self, frame):
        transport('SERIAL ' + frame.hex())
        return len(frame)

    def close(self):
        pass


class FakeSerialSession:
    def __init__(self, settings, log_path=None):
        self.settings, self.log_path = settings, log_path
        self.error, self.closed = None, False

    def open(self):
        transport('SERIAL OPEN ' + self.settings.port)
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_path.write_text('SIMULATED ' + self.settings.port, encoding='utf-8')

    def close(self):
        self.closed = True


class ValidationSandbox:
    """Fail closed for accidental network, process and real serial access."""
    def __enter__(self):
        self.stack = ExitStack()
        def denied(*args, **kwargs):
            raise AssertionError('自动化回归拒绝真实网络、串口、平台或系统命令')
        for name in ('socket.create_connection', 'socket.socket.connect', 'subprocess.Popen',
                     'serial.Serial', 'requests.sessions.Session.request'):
            self.stack.enter_context(patch(name, side_effect=denied))
        self.stack.enter_context(patch('src.core.serial_transport.PySerialSession', FakeSerialSession))
        ready = lambda *a, **kw: CommandResult(True, 'SIMULATED NETWORK READY')
        self.stack.enter_context(patch('line_check_assistant.network_ops.prepare_network_for_sample', ready))
        self.stack.enter_context(patch('line_check_assistant.page_upgrade.prepare_network_for_sample', ready))
        def ping(*args, **kwargs):
            transport('PING ' + str(args))
            return CommandResult(True, 'SIMULATED PING PASS')
        self.stack.enter_context(patch('line_check_assistant.network_ops.ping_host', ping))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)


def run_business(kind, index, context, manager, control, emit, gate):
    """Exercise the actual service/command lifecycle against explicit fake I/O."""
    token = active_fixture.set((gate, control, emit))
    emit('[隔离模拟] 开始 ' + kind + '；项目=' + context.identity.name)
    try:
        result = _business(kind, index, context, manager, control, emit)
        from src.services.project_status_service import result_state
        state = result_state(result)
        return dict(state=state, ok=state == 'succeeded', simulated=True, project_id=context.identity.project_id,
                    commands=list(gate.commands))
    except UpgradeStopped:
        return dict(state='stopped', ok=False, simulated=True, commands=list(gate.commands))
    finally:
        active_fixture.reset(token)


def _business(kind, index, context, manager, control, emit):
    # Reuse repository protocol-response fixtures, never any test methods.
    port = 'COM' + str(98000 + index)
    alias, ip = 'simulated' + str(index), '192.0.2.' + str(index + 1)
    if kind == 'network':
        from line_check_assistant.network_ops import run_line_check
        return run_line_check(alias, ip, '255.255.255.0', '192.0.2.254')
    if kind == 'aging':
        import uuid
        from test_legacy_power_test_service import _write_config_tree, _FakeProcessContext
        from src.services.legacy_power_test_service import (LegacyPowerChannel,
            prepare_legacy_power_test_request, run_legacy_power_test)
        fixture_root = context.root / 'history' / 'validation-aging' / uuid.uuid4().hex
        fixture_root.mkdir(parents=True, exist_ok=True)
        request = prepare_legacy_power_test_request(_write_config_tree(fixture_root, serial_port=port),
                    (LegacyPowerChannel(1, '192.168.1.101'),))
        class ProcessContext(_FakeProcessContext):
            def Process(self, **kwargs):
                process = super().Process(**kwargs)
                original = process.start
                def start():
                    transport('LEGACY CHILD START channel_1')
                    original()
                process.start = start
                return process
        return run_legacy_power_test(request, emit, control, process_context=ProcessContext())
    if kind == 'power':
        from src.services.power_on_service import turn_on_selected_channels
        return turn_on_selected_channels(port, [1], serial_factory=lambda *a, **kw: FakeSerial(),
                                         sleep_fn=lambda seconds: None, on_output=emit)
    if kind == 'serial':
        from src.models.serial_models import SerialSettings
        path = context.root / 'logs' / 'validation_serial.txt'
        manager.acquire_monitor('validation', SerialSettings(port), path)
        manager.release('validation', port)
        return dict(ok=True)
    if kind == 'parameters':
        from test_sample_parameter_service import FakeSession, FakeManager, values
        from src.models import SampleParameterWriteRequest
        from src.services.sample_parameter_service import run_single_sample_parameter_write
        class Session(FakeSession):
            def send_line(self, text, sensitive=False):
                transport(text)
                return super().send_line(text, sensitive)
        request = SampleParameterWriteRequest('vlan101', port, 'fake', 'fake', values())
        return run_single_sample_parameter_write(request, FakeManager(Session()), emit,
                    cancel_event=control, sleep_fn=lambda seconds: None)
    if kind == 'upgrade':
        from test_page_upgrade import FakeUbusClient
        from line_check_assistant.page_upgrade import PageUpgradeRequest, run_single_page_upgrade
        class Client(FakeUbusClient):
            def upload_file(self, *args):
                transport('UPLOAD SIMULATED FIRMWARE')
                return super().upload_file(*args)
        firmware = context.root / 'inputs' / 'validation.bin'
        firmware.parent.mkdir(exist_ok=True)
        firmware.write_bytes(b'SIMULATED FIRMWARE')
        request = PageUpgradeRequest('vlan101', ip, '192.0.2.254', 'fake', 'fake', firmware, alias)
        return run_single_page_upgrade(request, emit, sleep_fn=lambda seconds: None,
                                       client_factory=Client, stop_control=control)
    if kind == 'onu':
        from test_onu_registration_service import FakeSession
        from src.models.onu_registration_models import OltConnection
        from src.services.onu_registration_service import OnuRegistrationService
        class Session(FakeSession):
            def execute(self, command, **kwargs):
                transport(command)
                return super().execute(command, **kwargs)
        session = Session({'show onu-type': 'ONU type name: OSCAR_XGS\nPON type: gpon\nSpeed mode: XGS-PON\nZXAN#'})
        connection = OltConnection(host='198.51.100.' + str(index + 1), source_ip=ip, username='fake', password='fake')
        return OnuRegistrationService(logger=emit, session_type=session).query_templates('C600', connection, 'onu_type', control)
    if kind == 'dut':
        from src.models import DutTelnetEnableRequest
        from src.services.dut_wan_query_service import run_single_dut_wan_query
        class Client:
            def login(self, *args):
                transport('UBUS LOGIN')
                return 'simulated-session'
            def logout(self, *args):
                pass
            def close(self):
                pass
        request = DutTelnetEnableRequest(channel='channel_1', vlan='vlan101', adapter_alias=alias,
            bind_ip=ip, device_host='192.0.2.254', subnet_mask='255.255.255.0', username='fake', password='fake')
        return run_single_dut_wan_query(request, stop_event=control, on_output=emit,
            network_prepare_fn=lambda *a, **kw: CommandResult(True, 'SIMULATED'), bind_waiter=lambda *a, **kw: True,
            client_factory=lambda *a, **kw: Client(), query_fn=lambda *a, **kw: ('SIMULATED_WAN',), sleep_fn=lambda seconds: None)
    if kind == 'ai':
        from test_ai_core import FakeResponse, chat
        from src.core.ai_client import DiagnosticModelClient
        from src.models.ai_diagnostics import ProviderProfile
        from src.utils.ai_redaction import DiagnosticRedactor
        class Session:
            def request(self, *args, **kwargs):
                transport('MODEL COMPLETION ' + context.identity.project_id)
                return FakeResponse(chat('SIMULATED ' + context.identity.project_id))
            def close(self):
                pass
        client = DiagnosticModelClient(ProviderProfile(model='simulated', base_url='https://validation.invalid'),
                                       'fake-key', DiagnosticRedactor(), Session(), emit)
        try:
            reply = client.complete([dict(role='user', content='simulate')], stop=control)
            return dict(ok=context.identity.project_id in reply.text)
        finally:
            client.close()
    raise ValueError('未知模拟业务：' + kind)


class ValidationJobs:
    """Four independent production Job managers sharing the real resource coordinator."""
    def __init__(self, workspace_service, contexts, managers):
        from src.services.capability_jobs import CapabilityJobs
        from src.services.resource_lease_service import ResourceLeaseService
        self.service, self.contexts, self.managers = workspace_service, contexts, managers
        self.jobs, self.rounds, self.logs = [], [], [[] for _ in contexts]
        self.closed = False
        self.injected = None
        for index, context in enumerate(contexts):
            leases = ResourceLeaseService(coordinator=workspace_service.resources,
                        project_id=context.identity.project_id, project_name=context.identity.name)
            jobs = CapabilityJobs(context.history / 'validation-jobs', leases, self.emitter(index),
                                  project_context=context, status_service=workspace_service.status)
            self.jobs.append(jobs)

    def emitter(self, index):
        context = self.contexts[index]
        def emit(text):
            value = '[模拟项目 ' + context.identity.project_id + '] ' + str(text)
            self.logs[index].append(value)
            path = context.root / 'logs' / 'validation.log'
            path.parent.mkdir(exist_ok=True)
            with path.open('a', encoding='utf-8') as stream:
                stream.write(value + '\n')
        return emit

    def start(self, kind, timeout=15):
        import uuid
        from src.models.capabilities import CapabilityAuthority
        gates, submissions = [], []
        for index, (context, jobs, manager) in enumerate(zip(self.contexts, self.jobs, self.managers)):
            gate = Gate(timeout)
            authority = CapabilityAuthority('validation-local', context.identity.project_id, uuid.uuid4().hex,
                                            (1,), mode='full_access', grant_id='isolated-validation')
            keys = ['adapter:simulated' + str(index), 'channel:1']
            if kind in ('serial', 'parameters'):
                keys.append('serial:COM' + str(98000 + index))
            if kind in ('aging', 'power'):
                keys.append('power:COM' + str(98000 + index))
            if kind == 'onu':
                keys.append('olt:198.51.100.' + str(index + 1))
            def runner(job, i=index, project=context, sessions=manager, entry=gate):
                from src.models.project_task import task_path
                config = job.configuration_root / 'Auto_power_on_off_tool/config/test_project_config.ini'
                before = config.read_bytes()
                assert task_path(project.config_dir / 'test_project_config.ini') == config
                result = run_business(kind, i, project, sessions, job.stop, self.emitter(i), entry)
                assert config.read_bytes() == before, '运行配置快照被修改'
                return result
            submission = jobs.start('validation.' + kind, dict(channel_ids=[1]), authority, keys, runner)
            gates.append(gate)
            submissions.append((jobs, submission['job_id'], authority))
        self.rounds.append((gates, submissions))
        return gates, submissions

    def inject(self, unknown=False):
        import uuid
        from src.models.capabilities import CapabilityAuthority
        authority = CapabilityAuthority('validation-local', self.contexts[0].identity.project_id, uuid.uuid4().hex,
                                        (1,), mode='full_access', grant_id='isolated-validation')
        def runner(job):
            job.event('simulated_failure', 'SIMULATED fault injection; no real commands', dispatched=unknown)
            raise RuntimeError('SIMULATED unknown' if unknown else 'SIMULATED failure')
        submission = self.jobs[0].start('validation.fault', dict(channel_ids=[1]), authority,
                                       ['adapter:simulated0'], runner)
        self.injected = (submission['job_id'], authority)
        return submission

    def reconcile_injected(self):
        if self.injected is not None:
            identifier, authority = self.injected
            return self.jobs[0].resolve_unknown(identifier, authority, 'not_executed',
                        'SIMULATED target only; no real device commands; local operator reviewed fixture')

    def release(self):
        for gates, _ in self.rounds:
            for gate in gates:
                gate.proceed.set()

    def close(self):
        if self.closed:
            return
        import time
        for jobs in self.jobs:
            jobs.begin_close()
        self.release()
        deadline = time.monotonic() + 5
        while any(not jobs.idle for jobs in self.jobs) and time.monotonic() < deadline:
            time.sleep(.01)
        for jobs in self.jobs:
            jobs.close()
        self.closed = True


