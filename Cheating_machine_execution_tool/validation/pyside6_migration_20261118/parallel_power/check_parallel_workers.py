"""Run two original Windows power workers through the Qt workspace command queue."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'power_worker_replay'))
import replay
from line_check_assistant.config_store import ChannelConfigStore
from src.models.network_adapter import AdapterIdentity
from src.services import legacy_power_test_service as legacy
from src.services.qt_workspace_adapter import QtWorkspaceAdapter


def virtual_child(port, trace, first_on, target, args):
    assert port in ('COM7231', 'COM7232') and args[0].serial_port == port
    with patch.object(replay, 'POWER_PORT', port):
        replay.record_child(trace, first_on, False, None, target, args)


class RecordingRack(replay.RecordingSpawn):
    def Process(self, *, target, args, name):
        assert target is legacy._legacy_start_all_worker and self.request is None
        self.request = args[0]
        return self.context.Process(target=virtual_child, name=name,
            args=(self.request.serial_port, self.trace, self.started_power, target, args))


def check(root, full_banks):
    workspace = QtWorkspaceAdapter(replay.ROOT, directory=root / 'workspace')
    results = {}
    projects = {}

    def wait(predicate, timeout=15):
        deadline = time.monotonic() + timeout
        refresh = time.monotonic()
        while time.monotonic() < deadline:
            rows, _, messages = workspace.take_updates()
            projects.clear()
            projects.update((row.project_id, row) for row in rows)
            results.update((r.identifier, r) for r in messages)
            if predicate():
                return
            if projects and time.monotonic() >= refresh:
                # The native workbench requests progress snapshots on its UI timer.
                workspace.submit('refresh')
                refresh = time.monotonic() + .25
            time.sleep(.05)
        raise AssertionError('workspace timeout: ' + repr([(p.name, p.state) for p in projects.values()]))

    def command(operation, *args, expect_error=False):
        identifier = workspace.submit(operation, *args)
        wait(lambda: identifier in results)
        result = results[identifier]
        assert bool(result.error) == expect_error, result
        return result

    original = legacy.run_legacy_power_test
    racks = {port: RecordingRack(root / (port + '.json'), False, None) for port in ('COM7231', 'COM7232')}

    def route(request, *args, **kwargs):
        return original(request, *args, process_context=racks[request.serial_port], **kwargs)

    try:
        wait(lambda: any(r.operation == 'ready' for r in results.values()))
        nics = []
        ids = []
        for bank, (channel, port) in enumerate(((3, 'COM7231'), (9, 'COM7232'))):
            identifier = command('create', root / str(channel), f'独立模拟电源 {bank + 1}').project_id
            ids.append(identifier)
            service = workspace._service
            project = service.projects.opened[identifier]
            selected = tuple(range(1, 17)) if full_banks else (channel,)
            with patch.object(replay, 'CHANNELS', selected):
                replay.configure(service, project, False, 1 if full_banks else 10, 'telnet')
            store = ChannelConfigStore(project.config_dir / 'network_card_ip.ini')
            bindings = []
            for c in store.load():
                number = int(c.section.rsplit('_', 1)[1])
                alias = 'VLAN' + str(700 + 20 * bank + number)
                bindings.append(replace(c, adapter_alias=alias, vlan_name=alias, serial_port=f'COM{7240+20*bank+number}'))
                nics.append(AdapterIdentity(alias, 'fixture-parallel-worker-' + alias, 'Up'))
            store.save(bindings, port)
            service.projects.save(project)
        first, second = ids
        with patch.object(legacy, 'run_legacy_power_test', side_effect=route), \
                patch('src.core.network_adapter.read_adapter_identities', return_value=nics):
            for identifier, rack in zip(ids, racks.values()):
                token = command('prepare_execution', identifier, 'aging.start').payload.token
                command('confirm_execution', identifier, token)
                wait(rack.started_power.is_set, 80)
            wait(lambda: all(projects[k].state == 'running' for k in ids))
            jobs = {key: projects[key].run_id for key in ids}
            assert jobs[first] != jobs[second]
            coordinator = workspace._service.resources
            with coordinator.lock:
                assert {v[0] for v in coordinator.owners.values()} == set(ids)
            command('stop_execution', second, jobs[first], expect_error=True)
            if full_banks:
                wait(lambda: all(projects[k].state == 'completed' for k in ids), 180)
            else:
                command('stop_execution', first, jobs[first])
                wait(lambda: projects[first].state == 'stopped')
                with coordinator.lock:
                    assert {v[0] for v in coordinator.owners.values()} == {second}
                assert projects[second].state == 'running'
                wait(lambda: projects[second].state == 'completed', 60)
        traces = {}
        for identifier, (port, rack) in zip(ids, racks.items()):
            assert (workspace._service.projects.opened[identifier].root / 'runs') in rack.request.tool_root.parents
            trace = json.loads(rack.trace.read_text(encoding='utf-8'))
            assert not trace['blocked']
            events = trace['events']
            assert [e['event'] for e in events if e['event'] in ('serial_open','serial_close')] == ['serial_open','serial_close']
            frames = [e['hex'] for e in events if e['event'] == 'frame']
            numbers = [c.number for c in rack.request.channels]
            assert set(numbers) == (set(range(1, 17)) if full_banks else {3 if identifier == first else 9})
            expected_count = 0
            for number in numbers:
                cycle = (False, True) if not full_banks and identifier == first else (False, True, False, True)
                expected = [legacy.channel_power_frame(number, on).hex() for on in cycle]
                assert [f for f in frames if bytes.fromhex(f)[4] == number] == expected
                expected_count += len(expected)
            assert len(frames) == expected_count
            traces[port] = dict(project=identifier, job=jobs[identifier], state=projects[identifier].state, **trace)
        assert len({row['pid'] for row in traces.values()} | {os.getpid()}) == 3
        assert not workspace._service.resources.owners
        return traces
    finally:
        workspace.begin_close({key:'discard' for key in projects})
        assert workspace.wait_closed(25)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--full-banks', action='store_true', help='finish two full 16-channel projects on separate virtual supplies')
    args = parser.parse_args()
    blocked = []
    replay.block_external_io(blocked)
    with tempfile.TemporaryDirectory(prefix='dutpilot-parallel-power-') as tmp, \
            patch('serial.Serial', side_effect=AssertionError('parent may not open a physical COM port')):
        data = check(Path(tmp), args.full_banks)
    assert not blocked, blocked
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2), encoding='utf-8')
    print('TWO_PROJECT_POWER_CHILDREN_VERIFIED')
