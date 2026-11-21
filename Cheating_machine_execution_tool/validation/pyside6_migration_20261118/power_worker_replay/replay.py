"""Compare the two entry points using real Windows spawn and a recording serial port."""
import argparse
from contextlib import ExitStack, redirect_stdout
from dataclasses import replace
import json
import multiprocessing
import os
from pathlib import Path
import platform
import sys
import tempfile
import threading
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
CHANNELS = (3, 9)
POWER_PORT = 'COM239'


def block_external_io(record):
    # Python 3.9 queries Windows version through "ver" at first use. Cache it
    # before entering the fixture; every external command during a run is forbidden.
    platform.uname()
    def guard(event, args):
        if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto', 'os.system', 'subprocess.Popen'}:
            record.append(event)
            raise RuntimeError('Unexpected external I/O in the fixture: ' + event)
    sys.addaudithook(guard)


def record_child(trace_file, first_on, ping_failure, serial_failure, target, args):
    """Install boundary doubles before loading the original worker or legacy modules."""
    request = args[0]
    assert request.serial_port == POWER_PORT and not request.connect_wifi_enable
    started = time.monotonic()
    events, blocked = [], []
    lock = threading.Lock()

    def record(kind, **data):
        with lock:
            events.append(dict(event=kind, seconds=round(time.monotonic() - started, 4), **data))

    class VirtualPort:
        def __init__(self, port, baudrate, timeout):
            assert port == POWER_PORT and baudrate == 19200
            self.port = port
            self.is_open = True
            record('serial_open', port=port, baudrate=baudrate)

        def isOpen(self):
            return self.is_open

        def write(self, data):
            assert self.is_open
            if serial_failure and data[2] == 0xa0 and data[4] == CHANNELS[0]:
                record('serial_write_error', hex=bytes(data).hex(), mode=serial_failure)
                if serial_failure == 'blocked':
                    # A forced process termination cannot run Python finalizers.
                    Path(trace_file).write_text(json.dumps(dict(pid=os.getpid(), events=events, blocked=blocked)),
                                                encoding='utf-8')
                    first_on.set()
                    threading.Event().wait(60)
                    raise AssertionError('the parent did not enforce the original stop deadline')
                if serial_failure == 'partial':
                    return len(data) - 1
                raise OSError('[WinError 31] synthetic power serial write failure')
            record('frame', hex=bytes(data).hex())
            if bytes(data)[2] == 0xa0:
                first_on.set()
            return len(data)

        def close(self):
            if self.is_open:
                record('serial_close')
                self.is_open = False

    def profile(frame, event, arg):
        if event != 'call' or not frame.f_code.co_filename.endswith('powe_on_off_telnet.py'):
            return
        if frame.f_code.co_name == 'sleep_time':
            record('configured_wait', channel=frame.f_locals['power_num'], duration=frame.f_locals['times'])
        elif frame.f_code.co_name == 'run_case':
            record('channel_start', channel=frame.f_locals['power_num'])

    def fail_ping(*, dest_addr, timeout, src_addr):
        assert dest_addr == '192.0.2.200' and timeout == 5
        assert src_addr in {f'192.0.2.{number}' for number in CHANNELS}
        record('simulated_ping_error', source=src_addr)
        raise OSError('synthetic adapter failure')

    block_external_io(blocked)
    try:
        with ExitStack() as stack, open(os.devnull, 'w') as quiet:
            stack.enter_context(redirect_stdout(quiet))
            stack.enter_context(patch('serial.Serial', VirtualPort))
            wifi = stack.enter_context(patch('pywifi.PyWiFi'))
            wifi.return_value.interfaces.return_value = []
            mail = stack.enter_context(patch('smtplib.SMTP_SSL'))
            if ping_failure:
                stack.enter_context(patch('ping3.ping', side_effect=fail_ping))
            threading.setprofile(profile)
            try:
                target(*args)
            finally:
                threading.setprofile(None)
            record('mail_transport_calls', count=mail.call_count)
    finally:
        Path(trace_file).write_text(json.dumps(dict(pid=os.getpid(), events=events, blocked=blocked),
                                               indent=2), encoding='utf-8')


class RecordingSpawn:
    def __init__(self, trace, ping_failure, serial_failure):
        self.context = multiprocessing.get_context('spawn')
        self.trace = trace
        self.ping_failure = ping_failure
        self.serial_failure = serial_failure
        self.started_power = self.context.Event()
        self.request = None
        self.Queue = self.context.Queue
        self.Event = self.context.Event

    def Process(self, *, target, args, name):
        from src.services.legacy_power_test_service import _legacy_start_all_worker
        assert target is _legacy_start_all_worker
        self.request = args[0]
        return self.context.Process(target=record_child,
            args=(self.trace, self.started_power, self.ping_failure, self.serial_failure, target, args), name=name)


def configure(workspace, project, ping_failure, startup, protocol):
    from configparser import ConfigParser
    from line_check_assistant.config_store import ChannelConfigStore
    from qt_execution_fakes import configure_project
    identities = configure_project(workspace, project, CHANNELS)
    for file, changes in (
            ('config.ini', {'ui_defaults': dict(startup_time=startup, interval_time=2, number_of_tests=2,
                                                communication_method=protocol),
                            'other_config': dict(commands_execute_times=1, telnet_enable_fail_retry_times=1,
                                                 telnet_enable_fail_retry_interval=1)}),
            ('test_project_config.ini', {'telnet': dict(only_power_off_on=int(not ping_failure), port=23, user='fixture',
                                                       request_url='http://192.0.2.200'),
                                         'ssh': dict(port=22, user='fixture', password='fixture', request_url='192.0.2.200'),
                                         'order': {}})):
        parser = ConfigParser(interpolation=None)
        path = project.config_dir / file
        parser.read(path, encoding='utf-8')
        for section, values in changes.items():
            if not parser.has_section(section):
                parser.add_section(section)
            for key, value in values.items():
                parser.set(section, key, str(value))
        with path.open('w', encoding='utf-8') as output:
            parser.write(output)
    channels = ChannelConfigStore(project.config_dir / 'network_card_ip.ini')
    channels.save(channels.load(), POWER_PORT)
    workspace.projects.save(project)
    return identities


def run_case(mode, temp, *, short_wait=False, serial_failure=None, protocol='telnet', execution_timeout=95):
    from src.core.power_supply import channel_power_frame
    from src.services import legacy_power_test_service as legacy
    from src.services.qt_execution_adapter import QtExecutionAdapter
    from src.services.workspace_service import WorkspaceService
    root = temp / mode
    workspace = WorkspaceService(ROOT, directory=root / 'ws')
    project = workspace.projects.create(root / 'project', 'Power replay')
    workspace.status.attach(project)
    ping_failure = mode.endswith('_ping_error')
    startup = 1 if short_wait else 10
    identities = configure(workspace, project, ping_failure, startup, protocol)
    tool_root = project.saved_root / 'Auto_power_on_off_tool'
    expected = legacy.prepare_legacy_power_test_request(tool_root, [
        legacy.LegacyPowerChannel(number, f'192.0.2.{number}') for number in CHANNELS])
    assert (expected.number_of_tests, expected.startup_time, expected.interval_time) == (2, startup, 2)
    assert expected.communication_method == protocol
    logs = []
    trace_file = root / 'serial.json'
    spawn = RecordingSpawn(trace_file, ping_failure, serial_failure)
    adapter = None
    try:
        if mode.startswith('direct'):
            verdict = legacy.run_legacy_power_test(expected, logs.append, threading.Event(), process_context=spawn)
            if not serial_failure:
                assert verdict.ok == (not ping_failure), verdict.detail
            if ping_failure:
                assert '失败通道：[3, 9]' in verdict.detail, verdict.detail
            state = 'succeeded' if verdict.ok else 'failed'
            detail = verdict.detail
            results_root = tool_root
        else:
            adapter = QtExecutionAdapter(workspace, project, logs.append)
            with patch.object(legacy, 'multiprocessing', Mock(get_context=Mock(return_value=spawn))), \
                    patch('src.core.network_adapter.read_adapter_identities', return_value=identities):
                confirmation = adapter.prepare('aging.start')
                assert confirmation.channel_ids == CHANNELS
                job = adapter.confirm(confirmation.token)
                if mode == 'qt_stop':
                    assert spawn.started_power.wait(25), 'first power-on frame never arrived'
                    assert workspace.resources.owners, 'lease was released before the stop request'
                    adapter.stop(job)
                deadline = time.monotonic() + execution_timeout
                while not adapter.idle and time.monotonic() < deadline:
                    time.sleep(.05)
                assert adapter.idle, 'execution did not finish'
                adapter.poll()
            row = adapter.jobs[job]
            state = row['status']['state']
            detail = str(row['status']['result'])
            expected_state = 'stopped' if mode == 'qt_stop' else 'succeeded'
            if ping_failure:
                expected_state = 'failed'
            if not serial_failure:
                assert state == expected_state, (state, [entry.message for entry in logs[-10:]])
            if ping_failure:
                assert '失败通道：[3, 9]' in str(row['status']['result'])
                assert all(row['channels'][number]['status'] == 'failed' for number in CHANNELS)
            if mode == 'qt_stop':
                assert row['status']['result']['ok'] is False
                assert '用户已停止执行开关机测试' in str(row['status']['result'])
            assert not workspace.resources.owners
            results_root = project.root / 'runs'
            assert results_root in spawn.request.tool_root.parents
        assert replace(spawn.request, tool_root=expected.tool_root) == expected
        trace = json.loads(trace_file.read_text(encoding='utf-8'))
        assert trace['pid'] != os.getpid() and not trace['blocked']
        events = trace['events']
        assert [e['event'] for e in events if e['event'] in ('serial_open', 'serial_close')] == ['serial_open', 'serial_close']
        frames = [e['hex'] for e in events if e['event'] == 'frame']
        if serial_failure:
            rejected_frame = channel_power_frame(CHANNELS[0], True).hex()
            assert any(e['event'] == 'serial_write_error' and e['hex'] == rejected_frame for e in events)
            assert rejected_frame not in frames
            assert len([e for e in events if e['event'] == 'serial_write_error']) == 1
            if state == 'failed':
                assert '失败通道：[3, 9]' in detail, detail
                assert frames == [channel_power_frame(n, False).hex() for n in CHANNELS]
            return dict(entry=mode, original_reported_state=state, rejected_power_on=rejected_frame,
                        protocol=protocol, failure_mode=serial_failure,
                        accepted_frames=len(frames), failure_reported=state == 'failed', **trace)
        assert sorted(e['channel'] for e in events if e['event']=='channel_start') == list(CHANNELS)
        assert frames[:len(CHANNELS)] == [channel_power_frame(n,False).hex() for n in CHANNELS]
        if short_wait:
            written = {}
            expected_sequence = ['off', 'on', 'off', 'on']
            for number in CHANNELS:
                off, on = (channel_power_frame(number, value).hex() for value in (False, True))
                written[number] = ['on' if f == on else 'off' for f in frames if f in (off, on)]
            complete = all(sequence == expected_sequence for sequence in written.values())
            return dict(entry=mode, original_reported_state=state, complete_serial_sequences=complete,
                        expected_per_channel=expected_sequence, observed_per_channel=written, **trace)
        if ping_failure:
            assert len(frames) == 2 * len(CHANNELS)
            for number in CHANNELS:
                assert channel_power_frame(number, True).hex() in frames
                assert sum(e['event'] == 'simulated_ping_error' and e['source'] == f'192.0.2.{number}'
                           for e in events) == 31
                files = list(results_root.rglob(f'device_{number}_command_results_*.log'))
                assert len(files) == 1
                assert f'通道 {number} 发送 ping error 信号'.encode() in files[0].read_bytes()
            return dict(entry=mode, state=state, failed_channels=list(CHANNELS), **trace)
        if mode == 'qt_stop':
            assert channel_power_frame(CHANNELS[0], True).hex() in frames
            for number in CHANNELS:
                off, on = (channel_power_frame(number, value).hex() for value in (False, True))
                assert [value for value in frames if value in (off, on)] in ([off], [off, on])
            return dict(entry=mode, state=state, retained_business_ok=False, **trace)
        assert len(frames) == 4 * len(CHANNELS), frames
        for number in CHANNELS:
            expected_frames = [channel_power_frame(number, on).hex() for on in (False, True, False, True)]
            assert [value for value in frames if value in expected_frames] == expected_frames, (number, frames)
            waits = [e['duration'] for e in events if e['event']=='configured_wait' and e['channel']==number]
            assert waits == [10, 2, 10], (number, waits)
            files = list(results_root.rglob(f'device_{number}_command_results_*.log'))
            assert len(files) == 1, files
            raw = files[0].read_bytes()
            for cycle in (1, 2):
                assert f'only power off on {cycle} times'.encode() in raw
        return dict(entry=mode, state=state, completed_cycles_per_channel=2, **trace)
    finally:
        if adapter is not None:
            adapter.begin_close()
            deadline = time.monotonic() + 30
            while not adapter.ready_to_close and time.monotonic() < deadline:
                time.sleep(.05)
            adapter.close()
        workspace.projects.close(project)
        workspace.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    scenario = parser.add_mutually_exclusive_group()
    scenario.add_argument('--short-wait', action='store_true', help='Audit queue completion at a one-second startup wait')
    scenario.add_argument('--serial-failure', action='store_true', help='Reject channel 3 power-on at the virtual port')
    scenario.add_argument('--partial-write', action='store_true', help='Return a short write at the virtual port')
    parser.add_argument('--ssh', action='store_true', help='Run the SSH worker up to the injected serial failure')
    args = parser.parse_args()
    failure = 'partial' if args.partial_write else 'exception' if args.serial_failure else None
    if args.ssh and not failure:
        parser.error('--ssh requires --serial-failure or --partial-write')
    blocked = []
    block_external_io(blocked)
    with tempfile.TemporaryDirectory(prefix='dutpilot-real-worker-') as folder, \
            patch('serial.Serial', side_effect=AssertionError('parent cannot open serial')):
        modes = ('direct', 'qt', 'qt_stop', 'direct_ping_error', 'qt_ping_error')
        if args.short_wait or failure:
            modes = ('direct', 'qt')
        results = [run_case(mode, Path(folder), short_wait=args.short_wait, serial_failure=failure,
                            protocol='ssh' if args.ssh else 'telnet')
                   for mode in modes]
    assert not blocked, blocked
    args.output.write_text(json.dumps(dict(parent=os.getpid(), cases=results), indent=2), encoding='utf-8')
    if args.short_wait and not all(case['complete_serial_sequences'] for case in results):
        print('POWER_WORKER_SERIAL_SEQUENCE_INCOMPLETE')
        return 1
    if failure and not all(case['failure_reported'] for case in results):
        print('POWER_WORKER_WRITE_FAILURE_NOT_PROPAGATED')
        return 1
    print('POWER_WORKER_REPLAY_OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
