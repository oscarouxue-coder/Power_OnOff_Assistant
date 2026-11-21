"""Stop the original child while a synthetic driver write refuses to return."""
import argparse
import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'power_worker_replay'))
import replay
from src.services import legacy_power_test_service as legacy
from src.services.workspace_service import WorkspaceService


def check(directory):
    workspace = WorkspaceService(replay.ROOT, directory=directory / 'workspace')
    project = workspace.projects.create(directory / 'project', 'Blocked write fixture')
    logs = []
    stop = threading.Event()
    try:
        replay.configure(workspace, project, False, 1, 'telnet')
        request = legacy.prepare_legacy_power_test_request(project.saved_root / 'Auto_power_on_off_tool', [
            legacy.LegacyPowerChannel(n, f'192.0.2.{n}') for n in replay.CHANNELS])
        trace = directory / 'entered-write.json'
        spawn = replay.RecordingSpawn(trace, False, 'blocked')
        stop_times = []

        def stop_at_driver():
            if spawn.started_power.wait(20):
                stop_times.append(time.monotonic())
            stop.set()

        watcher = threading.Thread(target=stop_at_driver)
        watcher.start()
        result = legacy.run_legacy_power_test(request, logs.append, stop, process_context=spawn)
        watcher.join(21)
        assert len(stop_times) == 1 and not watcher.is_alive()
        assert not result.ok and '子进程已终止' in result.detail, result
        elapsed = time.monotonic() - stop_times[0]
        assert elapsed >= legacy.LEGACY_STOP_GRACE_SECONDS - 0.1
        data = json.loads(trace.read_text(encoding='utf-8'))
        assert not data['blocked'] and data['pid'] not in {p.pid for p in multiprocessing.active_children()}
        assert len([e for e in data['events'] if e['event'] == 'frame']) == 2
        assert any('未在停止宽限期内退出' in line for line in logs)
        return dict(result=result.detail, ok=result.ok, grace_seconds=legacy.LEGACY_STOP_GRACE_SECONDS,
                    stop_to_return_seconds=round(elapsed, 3), child_exited=True, trace_at_blocked_write=data)
    finally:
        workspace.projects.close(project)
        workspace.close()


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', required=True, type=Path)
    args = cli.parse_args()
    blocked = []
    replay.block_external_io(blocked)
    with tempfile.TemporaryDirectory(prefix='dutpilot-blocked-port-') as temp, \
            patch('serial.Serial', side_effect=AssertionError('parent must not open a port')):
        receipt = check(Path(temp))
    assert not blocked
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print('POWER_WORKER_BLOCKED_WRITE_GRACEFUL_DEADLINE_VERIFIED')
