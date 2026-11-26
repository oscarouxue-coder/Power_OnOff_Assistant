"""Bounded timing observation of the unchanged synthetic Qt regression."""
from contextlib import ExitStack
from pathlib import Path
import json
import os
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tests'), str(ROOT)]
mode = sys.argv[1]
assert mode in ('natural', 'held')


def run():
    events = []
    started = time.perf_counter_ns()
    lock = threading.Lock()
    observed_assertion = threading.Event()
    target = {}
    seen = set()

    def record(label, *, once=False, **fields):
        with lock:
            if once and label in seen:
                return
            seen.add(label)
            events.append(dict(ms=round((time.perf_counter_ns() - started) / 1e6, 3),
                               label=label, thread='gui' if threading.current_thread() is threading.main_thread() else 'worker',
                               **fields))

    def owner_state():
        resources = target.get('resources')
        return bool(resources and target.get('id') in resources.owners)

    with tempfile.TemporaryDirectory(prefix='p0-timing-synthetic-') as temporary, ExitStack() as scope:
        root = Path(temporary).resolve()
        local, roaming = root / 'local', root / 'roaming'
        local.mkdir()
        roaming.mkdir()
        scope.enter_context(patch.dict(os.environ, LOCALAPPDATA=str(local), APPDATA=str(roaming),
                                       TEMP=str(root), TMP=str(root), TMPDIR=str(root)))
        previous = tempfile.tempdir
        tempfile.tempdir = str(root)
        scope.callback(setattr, tempfile, 'tempdir', previous)
        guards = {key: scope.enter_context(patch(key, side_effect=AssertionError('live I/O forbidden')))
                  for key in (
                      'requests.sessions.Session.request', 'serial.Serial', 'socket.create_connection',
                      'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyname_ex', 'socket.gethostbyaddr',
                      'socket.socket.connect', 'socket.socket.connect_ex', 'socket.socket.send', 'socket.socket.sendall',
                      'socket.socket.sendto', 'socket.socket.bind', 'socket.socket.listen', 'socket.socket.accept',
                      'subprocess.Popen', 'os.startfile')}
        scope.enter_context(patch('src.core.network_adapter.read_adapter_identities', return_value=()))
        scope.enter_context(patch('src.core.serial_inventory.list_serial_port_names', return_value=[]))
        scope.enter_context(patch('src.services.remote_instance_management.selected_gateway_slot', return_value=None))
        from qt_workbench_probe import QtProjectWorkspaceTests
        from src.services.capability_jobs import CapabilityJobs
        from src.services.project_status_service import ProjectStatusService
        from src.services.workspace_resources import WorkspaceResources
        from src.services.qt_workspace_adapter import QtWorkspaceAdapter
        from src.ui.qt.main_window import MainWindow
        import run_tests

        original_config = QtProjectWorkspaceTests._configured_execution
        original_run = CapabilityJobs._run
        original_complete = ProjectStatusService.complete
        original_status = CapabilityJobs.status
        original_release = WorkspaceResources.release
        original_publish = QtWorkspaceAdapter._publish
        original_set = MainWindow.set_projects
        original_assert = QtProjectWorkspaceTests.assertFalse

        def config(case, *args, **kwargs):
            value = original_config(case, *args, **kwargs)
            target['resources'] = case.controller.adapter._service.resources
            return value

        def job_run(jobs, identifier, capability, runner, control):
            target['id'] = identifier
            record('job_worker_enter')
            try:
                return original_run(jobs, identifier, capability, runner, control)
            finally:
                record('job_worker_return', owner_held=owner_state())

        def complete(status, owner, result=None, state=None):
            if owner == target.get('id'):
                record('project_status_terminal_enter', state=state, owner_held=owner_state())
            value = original_complete(status, owner, result, state)
            if owner == target.get('id'):
                record('project_status_terminal_return', state=state, owner_held=owner_state())
            return value

        def job_status(jobs, identifier, authority, after_event=0):
            result = original_status(jobs, identifier, authority, after_event)
            if identifier == target.get('id') and result['state'] == 'succeeded':
                record('terminal_job_read', once=True, owner_held=owner_state())
            return result

        def release(resources, owner, *args, **kwargs):
            matched = resources is target.get('resources') and owner == target.get('id')
            if matched:
                record('resource_release_enter', owner_held=owner_state())
                if mode == 'held':
                    # Diagnostic scheduling contrast, never change release order or
                    # the original test assertion. Maximum bounded wait; synthetic only.
                    signal = observed_assertion.wait(2.0)
                    record('synthetic_hold_finished', assertion_observed=signal)
            result = original_release(resources, owner, *args, **kwargs)
            if matched:
                record('resource_release_return', owner_held=owner_state())
            return result

        def publish(adapter):
            result = original_publish(adapter)
            for row in adapter._snapshot:
                if row.run_id == target.get('id') and row.state == 'completed':
                    record('terminal_snapshot_published', once=True, owner_held=owner_state(),
                           can_start=row.can_start, active_tasks=row.active_task_count)
            return result

        def set_projects(window, projects):
            result = original_set(window, projects)
            for row in window.projects:
                if row.run_id == target.get('id') and row.state == 'completed':
                    record('terminal_ui_observed', once=True, owner_held=owner_state(),
                           can_start=row.can_start, active_tasks=row.active_task_count)
                    if row.can_start:
                        record('terminal_ui_can_start', once=True, owner_held=owner_state())
            return result

        def check(case, expr, *args, **kwargs):
            resources = target.get('resources')
            match = resources is not None and expr is resources.owners
            if match:
                record('original_resource_assertion', owner_held=owner_state(), owners_empty=not bool(expr))
            try:
                return original_assert(case, expr, *args, **kwargs)
            finally:
                if match:
                    observed_assertion.set()

        for owner, name, value in (
            (QtProjectWorkspaceTests, '_configured_execution', config),
            (CapabilityJobs, '_run', job_run),
            (ProjectStatusService, 'complete', complete),
            (CapabilityJobs, 'status', job_status),
            (WorkspaceResources, 'release', release),
            (QtWorkspaceAdapter, '_publish', publish),
            (MainWindow, 'set_projects', set_projects),
            (QtProjectWorkspaceTests, 'assertFalse', check),
        ):
            scope.enter_context(patch.object(owner, name, new=value))
        code = run_tests.main(['-v', 'qt_workbench_probe.QtProjectWorkspaceTests.'
                               'test_qt_saved_material_error_and_cancel_leave_active_fake_power_job_unchanged'])
        counts = {key: guard.call_count for key, guard in guards.items()}
        result = dict(mode=mode, events=events, code=code, denied_calls=counts,
                      elapsed_seconds=round((time.perf_counter_ns()-started)/1e9, 3))
        (OUT / ('timing-' + mode + '.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
        print('TIMING_RESULT: ' + json.dumps(result), flush=True)
        # Preserve the original verdict, including a diagnostic assertion failure.
        return code or int(any(counts.values()))


if __name__ == '__main__':
    sys.exit(run())
