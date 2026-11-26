"""Deterministic test configuration and an engine substitute; never physical I/O."""
from contextlib import contextmanager
from dataclasses import replace
from queue import Empty, Queue
import threading
from types import SimpleNamespace
from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
from src.models.network_adapter import AdapterIdentity
from src.services.pipeline_orchestrator import SubTaskResult


def block_live_model_transport(test):
    from unittest.mock import patch

    guard = patch('src.core.ai_client.DiagnosticModelClient._request',
                  side_effect=AssertionError('工作区专项禁止真实模型传输'))
    transport = guard.start()
    test.addCleanup(guard.stop)
    test.addCleanup(lambda: test.assertEqual(transport.call_count, 0, '存在未被模拟的模型请求'))


def continue_chat_intent(client, history, tools, stop):
    """Model fixture for an ordinary follow-up to an existing local conversation."""
    import json
    from src.models.ai_diagnostics import ModelReply
    from src.services.ai_session_router import ROUTE_INSTRUCTIONS

    assert history[0]['content'] == ROUTE_INSTRUCTIONS and not tools
    request = json.loads(history[1]['content'])
    current = request['current']
    decision = dict(intent='continue', scope=current['scope'], channel=current['channel'],
                    question=request['message'], clarification='')
    return ModelReply(json.dumps(decision), [], history)


def install_native_fixture_locks(test):
    """Separate simulated benches while retaining their actual host mutexes and lease keys."""
    import os
    from unittest.mock import patch
    from src.core.host_resource_lock import HostResourceLock

    bench = 'qt-native-fixture-' + str(os.getpid())
    original = HostResourceLock.__init__

    def initialize(lock, keys, namespace='physical-v1', *, reentrant=True):
        original(lock, keys, bench if namespace == 'physical-v1' else namespace, reentrant=reentrant)

    guard = patch.object(HostResourceLock, '__init__', initialize)
    guard.start()
    test.addCleanup(guard.stop)
    return bench


def configure_project(workspace, context, numbers=(1, 7), power_port='COM102'):
    (context.config_dir / 'config.ini').write_text('''[config]
test_project = test_project_config.ini
[ui_defaults]
communication_method = telnet
telnet_enable = 0
baud_rate = 19200
selected_profile = TEST_PROJECT
startup_time = 180
interval_time = 20
number_of_tests = 100
wait_command_done = 20
[Emails]
emails =
''', encoding='utf-8')
    (context.config_dir / 'test_project_config.ini').write_text('''[telnet]
request_url = http://192.168.1.1
telnet_default_on = 1
password = test-only
[connect_wifi]
enable = 0
''', encoding='utf-8')
    channels = [ChannelConfig('channel_' + str(n), vlan_name='VLAN' + str(100 + n),
        adapter_alias='VLAN' + str(100 + n), serial_port='COM' + str(n),
        network_card_ip='192.0.2.' + str(n), device_manage_ip='192.0.2.200') for n in numbers]
    ChannelConfigStore(context.config_dir / 'network_card_ip.ini').save(channels, power_port)
    workspace.projects.save(context)
    return tuple(AdapterIdentity(c.adapter_alias, 'fixture-guid-' + c.section, 'Up') for c in channels)


@contextmanager
def mock_power_interfaces(*projects):
    from unittest.mock import patch
    from uuid import NAMESPACE_DNS, uuid5

    interfaces, identities = [], []
    for project in projects:
        store = ChannelConfigStore(project.config_dir / 'network_card_ip.ini')
        for channel in store.load():
            if channel.enabled:
                alias = channel.adapter_alias
                guid = str(uuid5(NAMESPACE_DNS, alias))
                identities.append(AdapterIdentity(alias, guid, 'Up'))
                interfaces.append(dict(name=alias, guid=guid, up=True, index=len(interfaces) + 1,
                                       addresses=[(channel.network_card_ip, 24)]))
    with patch('src.core.network_adapter.read_adapter_identities', return_value=identities), \
            patch('src.services.physical_resource_guards.adapters_ipv4', return_value=interfaces):
        yield


def save_push_project_name(workspace, context, name='已保存试发项目'):
    from line_check_assistant.test_item_config_store import TestItemConfigStore
    store = TestItemConfigStore(context.config_dir / 'test_project_config.ini')
    original = store.load()
    store.save(replace(original, project_info=replace(original.project_info, project_name=name)))
    workspace.projects.save(context)


class ControlledPipeline:
    """Records the real orchestration request; waits for test-controlled finish."""
    def __init__(self):
        self.started = threading.Event()
        self.finish = threading.Event()
        self.stop_observed = threading.Event()
        self.release_stop = threading.Event()
        self.calls = []
        self.failure = False
        self.exception = None

    def factory(self, context, emit):
        owner = self

        class Engine:
            def run(self, tasks):
                owner.calls.append((context, frozenset(tasks)))
                projection = context.app
                projection._set_power_test_progress(68, 100)
                for channel in context.enabled_channels:
                    number = int(channel.section.rsplit('_', 1)[1])
                    projection._set_power_test_channel_state(number, 'running', 'fixture stage')
                    projection._set_power_test_channel_progress(number, 68, 100, 'fixture stage')
                owner.started.set()
                while not owner.finish.wait(.01):
                    if context.stop_event.is_set():
                        owner.stop_observed.set()
                        owner.release_stop.wait(5)
                        return [SubTaskResult(next(iter(tasks)), False, detail='safe stop confirmed')]
                if owner.exception is not None:
                    raise owner.exception
                for channel in context.enabled_channels:
                    number = int(channel.section.rsplit('_', 1)[1])
                    projection._set_power_test_channel_state(number, 'failed' if owner.failure else 'success', 'fixture result')
                return [SubTaskResult(next(iter(tasks)), not owner.failure)]

        return Engine()


class ControlledResumePipeline:
    """Expose an original resume session while replacing the device process."""
    def __init__(self, *, acknowledge_live=False):
        self.acknowledge_live = acknowledge_live
        self.commands = Queue()
        self.started = threading.Event()
        self.finish = threading.Event()
        self.process_done = threading.Event()
        self.recovering = threading.Event()
        self.release_recovery = threading.Event()
        self.observed_stop = threading.Event()
        self.live_commands = []
        self.recovery_calls = []
        self.recovery_gates = {}
        self.failed_recoveries = set()
        self.calls = []

    def factory(self, context, emit):
        def run(tasks):
            from src.services.legacy_power_test_service import LegacyPowerChannel, prepare_legacy_power_test_request
            from src.services.power_test_resume_service import PowerTestResumeSession

            self.calls.append(frozenset(tasks))
            projection = context.app
            numbers = [int(c.section.rsplit('_', 1)[1]) for c in context.enabled_channels]
            request = prepare_legacy_power_test_request(context.legacy_tool_root,
                tuple(LegacyPowerChannel(n, c.network_card_ip) for n, c in zip(numbers, context.enabled_channels)))
            session = PowerTestResumeSession(request, context.enabled_channels, context.stop_event, emit,
                on_progress=projection._set_power_test_progress,
                on_channel_progress=projection._set_power_test_channel_progress,
                on_channel_status=projection._set_power_test_channel_state,
                on_channel_history=projection._record_power_test_channel_history)
            self.session = projection.power_test_resume_session = session
            with session.process_lock:
                session.attach(self.commands)
                for number in numbers:
                    if number == 1:
                        self._record(number, 100, 'success')
                    else:
                        self._record(number, 3, 'failed')
                self.started.set()
                while not self.finish.wait(.01) and not context.stop_event.is_set():
                    if not self.acknowledge_live:
                        continue
                    try:
                        command = self.commands.get_nowait()
                    except Empty:
                        continue
                    self.live_commands.append(command)
                    session.observe(dict(type='channel_started', channel=command['channel']))
                    self._record(command['channel'], 100, 'success')
                session.detach()
                session.original_done = True
            self.process_done.set()
            return [SubTaskResult('legacy_power_test', False, detail='模拟原批次异常结论')]
        return SimpleNamespace(run=run)

    def _record(self, number, completed, state):
        session = self.session
        session.progress(number, completed)
        session.observe(dict(type='channel_ready', channel=number, ok=state == 'success'))
        session.callbacks['on_channel_progress'](number, completed, 100, '模拟进度')
        session.callbacks['on_channel_status'](number, state, '模拟状态')
        session.callbacks['on_progress'](min(session.completed.values()), 100)

    def run_after_exit(self, request, emit, stop, **options):
        self.recovery_calls.append((request, options))
        self.recovering.set()
        number = request.channels[0].number
        gate = self.recovery_gates.get(number, self.release_recovery)
        while not gate.wait(.01) and not self.release_recovery.is_set():
            if stop.is_set():
                self.observed_stop.set()
        ok = not stop.is_set() and number not in self.failed_recoveries
        if ok:
            self._record(number, 100, 'success')
        return SimpleNamespace(ok=ok)
