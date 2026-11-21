"""Observe the original Windows power worker when its Qt owner dies after the first power-on."""
import argparse
from contextlib import ExitStack
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

STAGES = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(STAGES/'archived_projects'), str(STAGES/'power_worker_replay')]
from check_archived_projects import Workspace
import replay
import psutil
from line_check_assistant.config_store import ChannelConfigStore
from src.services import legacy_power_test_service as legacy


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    temporary.replace(path)


def child(root, start, original, arguments):
    process = psutil.Process()
    write_json(root/'worker.json', dict(pid=process.pid, created=process.create_time(),
        parent=process.ppid(), spawn_owner=multiprocessing.parent_process().pid, clock=time.monotonic()))
    # Bounds only this disposable virtual worker if its original result pipe cannot drain.
    watchdog = threading.Timer(80, os._exit, (94,))
    watchdog.daemon = True
    watchdog.start()
    with ExitStack() as scope:
        scope.enter_context(patch.object(replay, 'POWER_PORT', 'COM7682'))
        if os.environ.get('DUTPILOT_TEST_LEGACY_CHILD') == '1':
            # Reproduce a worker launched by an earlier build, which only sets cwd.
            scope.enter_context(patch('src.services.power_worker_lifetime.publish_power_worker'))
        replay.record_child(root/'serial.json', start, False, None, original, arguments)


class Rack(replay.RecordingSpawn):
    def Process(self, *, target, args, name):
        assert target is legacy._legacy_start_all_worker and args[0].serial_port == 'COM7682'
        assert not args[0].connect_wifi_enable and len(args[0].channels) == 1
        return self.context.Process(target=child, name=name,
                                    args=(self.trace.parent, self.started_power, target, args))


def owner(root, direct):
    attempts = []
    replay.block_external_io(attempts)
    with ExitStack() as scope:
        scope.enter_context(patch('serial.Serial', side_effect=AssertionError('unexpected device access')))
        scope.enter_context(patch.object(replay, 'CHANNELS', (3,)))
        ui = Workspace(root)
        project = ui.command('create', root/'project', '进程中断模拟').project_id
        context = ui.adapter._service.projects.opened[project]
        nics = replay.configure(ui.adapter._service, context, False, 10, 'telnet')
        store = ChannelConfigStore(context.config_dir / 'network_card_ip.ini')
        store.save(store.load(), 'COM7682')
        ui.adapter._service.projects.save(context)
        rack = Rack(root/'serial.json', False, None)
        run = legacy.run_legacy_power_test
        if direct:
            request = legacy.prepare_legacy_power_test_request(context.saved_root/'Auto_power_on_off_tool',
                [legacy.LegacyPowerChannel(3, '192.0.2.3')])
            def exit_during_original_run():
                if rack.started_power.wait(30):
                    write_json(root/'owner.json', dict(pid=os.getpid(), project=project))
                    os._exit(47)
            threading.Thread(target=exit_during_original_run, daemon=True).start()
            run(request, lambda _: None, threading.Event(), process_context=rack)
            raise AssertionError('direct owner did not exit during original run')
        def record(request, *args, **options):
            return run(request, *args, process_context=rack, **options)
        scope.enter_context(patch.object(legacy, 'run_legacy_power_test', side_effect=record))
        scope.enter_context(patch('src.core.network_adapter.read_adapter_identities', return_value=nics))
        token = ui.command('prepare_execution', project, 'aging.start').payload.token
        ui.command('confirm_execution', project, token)
        assert rack.started_power.wait(30)
        ui.command('refresh')
        ui.wait(lambda: ui.rows[project].state == 'running')
        assert not attempts and ui.adapter._service.resources.owners
        write_json(root/'owner.json', dict(pid=os.getpid(), project=project, job=ui.rows[project].run_id))
        os._exit(47)


def observe(root, direct):
    command = [sys.executable, '-X', 'utf8', __file__, '--owner', str(root)]
    proc = subprocess.Popen(command + (['--direct'] if direct else []),
                            stdout=subprocess.DEVNULL)
    assert proc.wait(65) == 47, 'simulated owner did not exit at the first power-on'
    confirmed_exit = time.monotonic()
    meta = json.loads((root/'worker.json').read_text(encoding='utf-8'))
    previous = json.loads((root/'owner.json').read_text(encoding='utf-8'))
    # The venv's Windows launcher can sit between Python and its OS parent.
    assert meta['spawn_owner'] == previous['pid']
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x00100000, False, meta['pid'])
    assert handle and psutil.Process(meta['pid']).create_time() == meta['created']
    blocked = []
    replay.block_external_io(blocked)
    try:
        if not direct:
            assert kernel.WaitForSingleObject(handle, 0) == 258
            checks = verify_reopened_workspace(root, previous, alive=True)
            assert kernel.WaitForSingleObject(handle, 0) == 258
        assert kernel.WaitForSingleObject(handle, 85000) == 0, 'virtual worker did not exit'
        if not direct:
            finished = verify_reopened_workspace(root, previous, alive=False)
    finally:
        kernel.CloseHandle(handle)
    trace = json.loads((root/'serial.json').read_text(encoding='utf-8'))
    assert not blocked and not trace['blocked']
    # record_child starts its relative clock after the child's metadata timestamp.
    # Any write past this lower bound necessarily occurred after confirmed owner exit.
    offset = confirmed_exit - meta['clock']
    later = [e for e in trace['events'] if e['event'] == 'frame' and e['seconds'] > offset + .2]
    assert [e['hex'] for e in later] == ['5501a10003a3', '5501a00003a2'], later
    result = dict(owner_exit=47, worker_pid=meta['pid'], entry='original' if direct else 'qt',
                  owner_exit_seconds_from_worker=round(offset, 3), frames_after_confirmed_exit=later,
                  trace=trace, physical_serial_opens=0)
    if not direct:
        result.update(reopened_project_state='unknown', new_start_rejected=True,
                      while_alive=checks, after_exit=finished, legacy_child=os.environ.get('DUTPILOT_TEST_LEGACY_CHILD') == '1')
    return result


def verify_reopened_workspace(root, previous, *, alive):
    with patch('serial.Serial', side_effect=AssertionError('reopen should not control power')) as serial:
        ui = Workspace(root)
        try:
            pid = ui.command('open', root/'project').project_id
            ui.wait(lambda: pid in ui.rows)
            assert pid == previous['project'] and ui.rows[pid].state == 'unknown' and not ui.rows[pid].can_start
            assert previous['job'] in ui.adapter._service.resources.unknown_for(pid)
            query = ui.adapter.submit('prepare_execution', pid, 'aging.start')
            ui.wait(lambda: query in ui.results)
            assert ui.results[query].error
            query = ui.adapter.submit('job_review_prepare', pid, previous['job'])
            ui.wait(lambda: query in ui.results)
            review = ui.results[query]
            notice = ui.rows[pid].state_text
            if alive:
                assert '仍在运行' in notice, notice
                assert '仍在运行' in review.error, review.error
                assert previous['job'] in ui.adapter._service.resources.unknown_for(pid)
                jobs = ui.adapter._executions[pid].capabilities.jobs
                from src.models.capabilities import CapabilityAuthority, CapabilityError
                row = jobs._row(previous['job'])
                channels = tuple(row['request']['arguments'].get('channel_ids', ()))
                authority = CapabilityAuthority(row['principal'], 'local-operator', 'local-control', channels,
                    source='gui', mode='full_access', grant_id='local-control', approved=True)
                try:
                    jobs.resolve_unknown(previous['job'], authority, 'failed', '模拟：进程仍活时尝试核实')
                except CapabilityError as error:
                    assert '仍在运行' in str(error), str(error)
                else:
                    raise AssertionError('the underlying service removed a live worker guard')
                assert jobs._row(previous['job'])['state'] == 'unknown'
                assert previous['job'] in ui.adapter._service.resources.unknown_for(pid)
                result = dict(display=notice, review_blocked=True, service_blocked=True, protected=True)
            else:
                assert not review.error and '仍在运行' not in notice, review.error
                assert previous['job'] in ui.adapter._service.resources.unknown_for(pid)
                reply = ui.command('job_review_commit', pid, review.payload.token, 'failed',
                                   '模拟：已核对原进程退出，操作端异常退出，未获得完整结果')
                assert reply.payload == 'failed'
                assert previous['job'] not in ui.adapter._service.resources.unknown_for(pid)
                result = dict(protected_before_confirmation=True, explicit_outcome=reply.payload,
                              protection_released_after_confirmation=True)
        finally:
            ui.close()
        serial.assert_not_called()
    return result


if __name__ == '__main__':
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument('--owner', type=Path)
    args.add_argument('--direct', action='store_true', help='compare the original executor entry without Qt job admission')
    args.add_argument('--old-worker', action='store_true', help='simulate a pre-marker worker')
    args.add_argument('--output', type=Path)
    options = args.parse_args()
    if options.owner:
        try:
            owner(options.owner, options.direct)
        except BaseException:
            import traceback
            traceback.print_exc()
            sys.stderr.flush()
            os._exit(48)
    else:
        assert options.output
        if options.old_worker:
            os.environ['DUTPILOT_TEST_LEGACY_CHILD'] = '1'
        with tempfile.TemporaryDirectory(prefix='dutpilot-owner-loss-') as temp:
            root = Path(temp).resolve()
            os.environ.update(LOCALAPPDATA=str(root/'local'), APPDATA=str(root/'roaming'), PROGRAMDATA=str(root/'machine'))
            result = observe(root, options.direct)
        options.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print('OWNER_LOSS_OBSERVED', len(result['frames_after_confirmed_exit']))
