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
import types
import unittest
import weakref
from unittest.mock import patch

import psutil

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tests'), str(ROOT)]
MODE = sys.argv[1]
CYCLES = int(sys.argv[2])
if MODE not in ('fixture', 'formal', 'backrefs', 'callback', 'resource-detach',
                'window', 'timer-bound', 'timer-closure') or not 1 <= CYCLES <= 40:
    raise ValueError('unknown control or invalid explicit repeat count')

SOURCE_FILES = (
    'src/ui/qt/main_window.py', 'src/ui/qt/workspace_controller.py', 'src/services/qt_workspace_adapter.py',
    'src/services/workspace_service.py', 'src/services/workspace_resources.py', 'src/services/host_resource_fence.py',
    'src/services/workspace_event_log.py', 'tests/qt_workbench_probe.py', 'tests/test_qt_workspace_adapter.py',
    'scripts/qt_test_guard.py', 'scripts/run_tests.py',
    'src/ui/qt/app_update_dialog.py', 'src/services/qt_app_update.py',
    'src/ui/qt/log_history_dialog.py', 'src/ui/qt/ai_chat_controller.py',
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

        from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer
        from PySide6.QtWidgets import QWidget, QApplication
        import shiboken6
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

        def objects(case):
            controller = case.controller
            adapter = controller.adapter
            owned = dict(window=case.window, controller=controller, adapter=adapter,
                         workspace_service=adapter._service, workspace_resources=adapter._service.resources,
                         log_writer=adapter._log_writer, history_executor=adapter._history_reader,
                         gateway_executor=adapter._gateway_worker, timer=controller.timer,
                         update_worker=controller.app_update.worker, update_executor=controller.app_update.worker._worker)
            # Inspect identity edges only between known synthetic objects. Do not emit values.
            for name, child in vars(controller).items():
                if type(child).__module__.startswith('src.ui.qt') and not isinstance(child, QObject):
                    if vars(child).get('workspace') is controller:
                        owned['child:' + name] = child
            return owned

        def inspect_closed(case, intervention):
            owned = objects(case)
            ctrl = owned['controller']
            adapter = owned['adapter']
            writer = owned['log_writer']
            update = owned['update_worker']
            assert adapter.closed.is_set() and not adapter.thread.is_alive()
            assert writer.report is None and writer.associate is None
            assert adapter._service._closed
            assert not update.pending_work
            assert not shiboken6.isValid(owned['window'])
            assert not shiboken6.isValid(ctrl)
            edges = []
            for owner, value in owned.items():
                for attr, item in vars(value).items():
                    for target, candidate in owned.items():
                        if item is candidate:
                            edges.append([owner, attr, target, 'direct'])
                        elif isinstance(item, types.MethodType) and item.__self__ is candidate:
                            edges.append([owner, attr, target, 'bound'])
            by_dict = {id(vars(value)): name for name, value in owned.items()}
            referrers = {}
            for target in ('controller', 'window', 'adapter'):
                counts = {}
                for referrer in gc.get_referrers(owned[target]):
                    kind = by_dict.get(id(referrer)) or type(referrer).__name__
                    counts[kind] = counts.get(kind, 0) + 1
                referrers[target] = counts
            graph = dict(edges=edges, referrers_by_type=referrers,
                         invalid_qobjects=[name for name, item in owned.items()
                                           if isinstance(item, QObject) and not shiboken6.isValid(item)],
                         update_executor_shutdown=update._worker._shutdown,
                         plain_backrefs=[name for name in owned if name.startswith('child:')])
            # The following independent ablations are diagnostic-only, on dead
            # isolated fixture objects after the actual close and DeferredDelete.
            # They are NOT proposed production changes or live UI interactions.
            if intervention == 'backrefs':
                for name, child in owned.items():
                    if name.startswith('child:'):
                        child.workspace = None
            elif intervention == 'callback':
                update._write_log = None
            elif intervention == 'resource-detach':
                ctrl.adapter = None
                update._write_log = None
            return {name: weakref.ref(value) for name, value in owned.items()}, graph

        class TimerOwner:
            def __init__(self, timer):
                self.timer = timer
            def tick(self):
                pass

        def timer_fixture(closure):
            with QtTestScope() as scope:
                window = QWidget()
                timer = QTimer(window)
                owner = TimerOwner(timer)
                if closure:
                    timer.timeout.connect(lambda target=owner: target.tick())
                else:
                    timer.timeout.connect(owner.tick)
                timer.start(20)
                window.show()
                pump(.05)
                live = measure()
                timer.stop()
                window.close()
            assert not shiboken6.isValid(window) and not shiboken6.isValid(timer)
            return {name: weakref.ref(value) for name, value in
                    (('window', window), ('timer', timer), ('owner', owner))}, live

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
                    graph = None
                    formal = None
                    if MODE in ('fixture', 'formal', 'backrefs', 'callback', 'resource-detach'):
                        case = QtProjectWorkspaceTests('test_qt_multi_channel_saved_material_summary_preserves_independent_and_cancelled_results')
                        try:
                            case.setUp()  # initialization only; never call the report test
                            self.assertFalse(case.window.projects)
                            live = measure()
                            if MODE != 'fixture':
                                case.window.close()
                                case.wait_for(lambda: not case.window.isVisible() and
                                    case.controller.adapter.closed.is_set() and
                                    not case.controller.adapter.thread.is_alive())
                                formal = dict(timer_active=case.controller.timer.isActive(),
                                              update_pending=case.controller.app_update.worker.pending_work,
                                              update_executor_shutdown=case.controller.app_update.worker._worker._shutdown,
                                              coordinator_cleared=case.window._close_coordinator is None)
                        finally:
                            self.assertTrue(case.doCleanups())
                        worker_closed = case.controller.adapter.closed.is_set() and not case.controller.adapter.thread.is_alive()
                        immediate = measure()
                        refs, graph = inspect_closed(case, MODE)
                        lifetime_refs.append(refs)
                        del refs
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
                        lifetime_refs.append({'window': weakref.ref(window)})
                        del window, qt_scope
                    else:
                        refs, live = timer_fixture(MODE == 'timer-closure')
                        lifetime_refs.append(refs)
                        del refs
                        immediate = measure()
                    self.assertTrue(worker_closed)
                    pump(.05)
                    after_pump = measure()
                    gc_count = None  # no per-cycle explicit GC
                    after_gc = None
                    pump(.25)
                    after_wait = measure()
                    row = dict(cycle=number, before=before, live=live, immediate=immediate,
                               after_pump=after_pump, after_gc=after_gc, after_wait=after_wait,
                                gc_collected=gc_count, worker_closed=worker_closed,
                                closed_graph=graph, formal_close=formal)
                    rows.append(row)
                    (OUT / f'metrics-{MODE}.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
                    print('HANDLE_CONTROL_CYCLE: ' + json.dumps(row), flush=True)

                pump(2.0)
                final['after_two_seconds'] = measure()
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
