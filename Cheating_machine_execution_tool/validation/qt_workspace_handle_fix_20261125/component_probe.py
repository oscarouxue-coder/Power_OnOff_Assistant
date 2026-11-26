"""Isolated own-process handle comparisons; no report, live device, or network."""
from contextlib import ExitStack
from pathlib import Path
import builtins
import ctypes
from ctypes import wintypes
import gc
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import weakref
from unittest.mock import patch

import psutil

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tests'), str(ROOT)]
MODE = sys.argv[1]
CYCLES = int(sys.argv[2])
if MODE not in ('empty', 'empty-deferred', 'window', 'adapter', 'service', 'resources') or not 1 <= CYCLES <= 40:
    raise ValueError('unknown control or invalid explicit repeat count')

SOURCE_FILES = (
    'src/ui/qt/main_window.py', 'src/ui/qt/workspace_controller.py', 'src/services/qt_workspace_adapter.py',
    'src/services/workspace_service.py', 'src/services/workspace_resources.py', 'src/services/host_resource_fence.py',
    'src/services/workspace_event_log.py', 'tests/qt_workbench_probe.py', 'tests/test_qt_workspace_adapter.py',
    'scripts/qt_test_guard.py', 'scripts/run_tests.py',
)


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


PROCESS = psutil.Process(os.getpid())
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32.GetCurrentProcess.argtypes = []
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
user32.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
user32.GetGuiResources.restype = wintypes.DWORD
CURRENT_PROCESS = kernel32.GetCurrentProcess()  # pseudo-handle, no handle enumeration


class FixtureFiles:
    """Only observed Python file objects in the synthetic root; no strong references."""
    def __init__(self, root):
        self.root = root
        self.refs = []
        self.untrackable = 0
        self.lock = threading.Lock()

    def track(self, path, stream):
        try:
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = Path.cwd() / candidate
            if self.root != candidate and self.root not in candidate.parents:
                return stream
        except (TypeError, ValueError, OSError):
            return stream
        with self.lock:
            try:
                self.refs.append(weakref.ref(stream))
            except TypeError:
                self.untrackable += 1
        return stream

    def sample(self):
        with self.lock:
            alive = [obj for ref in self.refs if (obj := ref()) is not None]
            return dict(fixture_python_files_observed=len(self.refs), fixture_python_files_alive=len(alive),
                        fixture_python_files_still_open=sum(not obj.closed for obj in alive),
                        fixture_python_files_untrackable=self.untrackable)


def run():
    from qt_test_guard import active_guard
    if active_guard() is None:
        raise RuntimeError('Verified native Qt desktop is mandatory')
    started = time.monotonic()
    source_before = hashes()
    rows, final = [], {}
    lifetime_refs = []
    guards = {}
    code = None
    with tempfile.TemporaryDirectory(prefix='p0-handle-audit-') as temporary, ExitStack() as scope:
        fixture_root = Path(temporary).resolve()
        local = fixture_root / 'local'
        roaming = fixture_root / 'roaming'
        local.mkdir()
        roaming.mkdir()
        scope.enter_context(patch.dict(os.environ, LOCALAPPDATA=str(local), APPDATA=str(roaming),
                                       TEMP=str(fixture_root), TMP=str(fixture_root), TMPDIR=str(fixture_root)))
        previous_tempdir = tempfile.tempdir
        tempfile.tempdir = str(fixture_root)
        scope.callback(setattr, tempfile, 'tempdir', previous_tempdir)
        for endpoint in (
            'requests.sessions.Session.request', 'serial.Serial', 'socket.create_connection',
            'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyname_ex', 'socket.gethostbyaddr',
            'socket.socket.connect', 'socket.socket.connect_ex', 'socket.socket.send', 'socket.socket.sendall',
            'socket.socket.sendto', 'socket.socket.bind', 'socket.socket.listen', 'socket.socket.accept',
            'subprocess.Popen', 'os.startfile',
        ):
            guards[endpoint] = scope.enter_context(patch(endpoint, side_effect=AssertionError('live I/O forbidden')))
        scope.enter_context(patch('src.core.network_adapter.read_adapter_identities', return_value=()))
        scope.enter_context(patch('src.core.serial_inventory.list_serial_port_names', return_value=[]))
        scope.enter_context(patch('src.services.remote_instance_management.selected_gateway_slot', return_value=None))

        tracker = FixtureFiles(fixture_root)
        original_path_open, original_builtin_open = Path.open, builtins.open

        def path_open(path, *args, **kwargs):
            return tracker.track(path, original_path_open(path, *args, **kwargs))

        def builtin_open(path, *args, **kwargs):
            return tracker.track(path, original_builtin_open(path, *args, **kwargs))

        scope.enter_context(patch.object(Path, 'open', new=path_open))
        scope.enter_context(patch.object(builtins, 'open', new=builtin_open))

        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QWidget, QApplication
        from qt_test_guard import QtTestScope
        from qt_workbench_probe import QtProjectWorkspaceTests
        from test_qt_workspace_adapter import QtWorkspaceAdapterTests
        from src.ui.qt.main_window import MainWindow
        from src.ui.qt.theme import apply_theme
        from src.services.workspace_service import WorkspaceService
        from src.services.workspace_resources import WorkspaceResources
        import run_tests

        def pump(seconds):
            app = QApplication.instance()
            until = time.monotonic() + seconds
            while True:
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                app.processEvents()
                remaining = until - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(.01, remaining))

        def measure():
            app = QApplication.instance()
            result = dict(t_seconds=round(time.monotonic() - started, 3),
                          rss_bytes=PROCESS.memory_info().rss, process_handles=PROCESS.num_handles(),
                          process_threads=PROCESS.num_threads(), python_threads=threading.active_count(),
                          gdi_objects=int(user32.GetGuiResources(CURRENT_PROCESS, 0)),
                          user_objects=int(user32.GetGuiResources(CURRENT_PROCESS, 1)),
                          qt_top_levels=len(app.topLevelWidgets()) if app is not None else 0)
            result.update(tracker.sample())
            if lifetime_refs:
                result['component_refs_alive'] = {name: sum(group[name]() is not None for group in lifetime_refs)
                                                  for name in lifetime_refs[0]}
            return result

        def own_component_refs(case):
            adapter = case.controller.adapter
            return {name: weakref.ref(value) for name, value in (
                ('test_case', case), ('window', case.window), ('controller', case.controller),
                ('adapter', adapter), ('workspace_service', adapter._service),
                ('workspace_resources', adapter._service.resources), ('log_writer', adapter._log_writer),
                ('history_executor', adapter._history_reader), ('gateway_executor', adapter._gateway_worker))}

        class AuditCase(unittest.TestCase):
            def test_control(self):
                # A single constant warm-up widget gives all controls the same
                # native QApplication. No per-cycle report/widget for adapter,
                # service, or resource-only controls.
                with QtTestScope() as warm:
                    dummy = QWidget()
                    dummy.show()
                    pump(.05)
                    dummy.close()
                del dummy, warm
                gc.collect()
                pump(.25)
                final['baseline'] = measure()

                for number in range(1, CYCLES + 1):
                    before = measure()
                    worker_closed = True
                    if MODE in ('empty', 'empty-deferred'):
                        case = QtProjectWorkspaceTests('test_qt_multi_channel_saved_material_summary_preserves_independent_and_cancelled_results')
                        try:
                            case.setUp()  # initialization only; never call the report test
                            self.assertFalse(case.window.projects)
                            if MODE == 'empty-deferred':
                                lifetime_refs.append(own_component_refs(case))
                            live = measure()
                        finally:
                            self.assertTrue(case.doCleanups())
                        worker_closed = case.controller.adapter.closed.is_set() and not case.controller.adapter.thread.is_alive()
                        immediate = measure()
                        del case
                    elif MODE == 'window':
                        with QtTestScope() as qt_scope:
                            window = MainWindow(demo=False)
                            apply_theme(qt_scope.app)
                            window.resize(1366, 768)
                            window.show()
                            pump(.05)
                            live = measure()
                            window.close()
                        immediate = measure()
                        del window, qt_scope
                    elif MODE == 'adapter':
                        case = QtWorkspaceAdapterTests('test_old_running_and_queued_history_never_starts_hardware')
                        try:
                            case.setUp()  # no project, device, model or report operation
                            self.assertFalse(case.projects)
                            lifetime_refs.append({name: weakref.ref(obj) for name, obj in
                                (('adapter', case.adapter), ('service', case.adapter._service),
                                 ('writer', case.adapter._log_writer))})
                            live = measure()
                        finally:
                            self.assertTrue(case.doCleanups())
                        worker_closed = case.adapter.closed.is_set() and not case.adapter.thread.is_alive()
                        immediate = measure()
                        del case
                    else:
                        with tempfile.TemporaryDirectory(prefix='component-') as component:
                            if MODE == 'service':
                                instance = WorkspaceService(ROOT, directory=Path(component))
                                lifetime_refs.append({'service': weakref.ref(instance)})
                            else:
                                instance = WorkspaceResources(Path(component))
                            try:
                                live = measure()
                            finally:
                                instance.close()
                            immediate = measure()
                            del instance
                    self.assertTrue(worker_closed)
                    pump(.05)
                    after_pump = measure()
                    if MODE in ('empty-deferred', 'adapter', 'service'):
                        gc_count = None  # retain normal automatic GC policy; explicit GC only at final control
                        after_gc = None
                    else:
                        gc_count = gc.collect()
                        pump(.05)
                        after_gc = measure()
                    pump(.25)
                    after_wait = measure()
                    row = dict(cycle=number, before=before, live=live, immediate=immediate,
                               after_pump=after_pump, after_gc=after_gc, after_wait=after_wait,
                               gc_collected=gc_count, worker_closed=worker_closed)
                    rows.append(row)
                    (OUT / f'metrics-{MODE}.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
                    print('HANDLE_CONTROL_CYCLE: ' + json.dumps(row), flush=True)

                pump(2.0)
                final['after_two_seconds'] = measure()
                if MODE in ('empty-deferred', 'adapter', 'service'):
                    pump(5.0)
                    final['before_final_gc'] = measure()
                final['final_gc_collected'] = gc.collect()
                pump(5.0)
                final['after_extra_five_seconds'] = measure()

        globals()['AuditCase'] = AuditCase
        try:
            code = run_tests.main(['-v', '__main__.AuditCase.test_control'])
            if len(rows) != CYCLES or any(guard.call_count for guard in guards.values()):
                code = 1
        finally:
            source_after = hashes()
            final.update(mode=MODE, requested=CYCLES, recorded=len(rows), result_code=code,
                         elapsed_seconds=round(time.monotonic() - started, 3),
                         changed_source_files=[name for name in source_before if source_before[name] != source_after[name]],
                         source_hashes_before=source_before, source_hashes_after=source_after,
                         denied_calls={name: guard.call_count for name, guard in guards.items()})
            (OUT / f'summary-{MODE}.json').write_text(json.dumps(final, indent=2), encoding='utf-8')
            print('HANDLE_CONTROL_SUMMARY: ' + json.dumps(final), flush=True)
    return code if code is not None else 1


if __name__ == '__main__':
    sys.exit(run())
