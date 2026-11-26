"""Actual application loop and close, isolated synthetic workspace/instance."""
from contextlib import ExitStack
from pathlib import Path
import json
import os
import queue
import sys
import tempfile
import threading
import time
import unittest
import weakref
from unittest.mock import Mock, patch

import psutil

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tests'), str(ROOT)]


def run():
    started = time.monotonic()
    rows = []
    with tempfile.TemporaryDirectory(prefix='workspace-actual-loop-') as temporary, ExitStack() as scope:
        fixture = Path(temporary).resolve()
        local, roaming = fixture / 'local', fixture / 'roaming'
        local.mkdir()
        roaming.mkdir()
        scope.enter_context(patch.dict(os.environ, LOCALAPPDATA=str(local), APPDATA=str(roaming),
                                       TEMP=str(fixture), TMP=str(fixture), TMPDIR=str(fixture)))
        previous = tempfile.tempdir
        tempfile.tempdir = str(fixture)
        scope.callback(setattr, tempfile, 'tempdir', previous)
        guards = {endpoint: scope.enter_context(patch(endpoint, side_effect=AssertionError('live I/O forbidden')))
                  for endpoint in (
                      'requests.sessions.Session.request', 'serial.Serial', 'socket.create_connection',
                      'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyname_ex', 'socket.gethostbyaddr',
                      'socket.socket.connect', 'socket.socket.connect_ex', 'socket.socket.send', 'socket.socket.sendall',
                      'socket.socket.sendto', 'socket.socket.bind', 'socket.socket.listen', 'socket.socket.accept',
                      'subprocess.Popen', 'os.startfile')}
        scope.enter_context(patch('src.core.network_adapter.read_adapter_identities', return_value=()))
        scope.enter_context(patch('src.core.serial_inventory.list_serial_port_names', return_value=[]))
        scope.enter_context(patch('src.services.remote_instance_management.selected_gateway_slot', return_value=None))
        from PySide6.QtCore import QCoreApplication, QEvent
        from qt_test_guard import QtTestScope
        from src.ui.qt.application import run_workspace
        from src.ui.qt.workspace_controller import WorkspaceController
        from qt_execution_fakes import block_live_model_transport, install_native_fixture_locks
        import run_tests
        process = psutil.Process(os.getpid())

        class ActualLoop(unittest.TestCase):
            def test_application_return_destroys_widget_before_releasing_instance(self):
                block_live_model_transport(self)
                install_native_fixture_locks(self)
                with QtTestScope() as native:
                    app = native.app
                    app.setQuitOnLastWindowClosed(True)
                    try:
                        for index in range(1, 4):
                            refs, states = {}, []
                            fake = Mock()
                            fake.start.return_value = True
                            fake.requests = queue.Queue()
                            fake.closing_requested = threading.Event()

                            def create(window, source_root, **unused):
                                controller = WorkspaceController(window, source_root,
                                    directory=fixture / ('workspace-' + str(index)), start_configured_gateway=False)
                                refs.update(window=weakref.ref(window), controller=weakref.ref(controller),
                                            adapter=weakref.ref(controller.adapter))
                                owner = weakref.ref(controller)

                                def close_when_ready():
                                    obj = owner()
                                    if obj is not None and obj.ready:
                                        obj.timer.timeout.disconnect(close_when_ready)
                                        obj.window.close()

                                controller.timer.timeout.connect(close_when_ready)
                                return controller

                            def released(*args, **kwargs):
                                from shiboken6 import isValid
                                obj = refs['controller']()
                                states.append(dict(window_destroyed=not isValid(refs['window']()),
                                                   controller_destroyed=not isValid(obj),
                                                   terminal_refs_released=obj._workspace_refs_released,
                                                   worker_closed=obj.adapter.closed.is_set() and
                                                       not obj.adapter.thread.is_alive()))

                            fake.close.side_effect = released
                            with ExitStack() as patches:
                                patches.enter_context(patch('src.core.workspace_instance.WorkspaceInstance', return_value=fake))
                                patches.enter_context(patch('src.ui.qt.application._create_application', return_value=app))
                                # A Mock's call history would itself strongly retain the window.
                                patches.enter_context(patch('src.ui.qt.workspace_controller.WorkspaceController', new=create))
                                self.assertEqual(run_workspace(), 0)
                            self.assertEqual(states, [dict(window_destroyed=True, controller_destroyed=True,
                                                           terminal_refs_released=True, worker_closed=True)])
                            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                            app.processEvents()
                            row = dict(cycle=index, state=states[0], handles=process.num_handles(),
                                       python_threads=threading.active_count(),
                                       weakrefs={name: int(value() is not None) for name, value in refs.items()})
                            rows.append(row)
                            self.assertEqual(row['weakrefs'], dict(window=0, controller=0, adapter=0))
                    finally:
                        app.setQuitOnLastWindowClosed(False)

        globals()['ActualLoop'] = ActualLoop
        code = run_tests.main(['-v', '__main__.ActualLoop.test_application_return_destroys_widget_before_releasing_instance'])
        counts = {name: guard.call_count for name, guard in guards.items()}
        evidence = dict(rows=rows, denied=counts, elapsed_seconds=round(time.monotonic() - started, 3), result=code)
        (OUT / 'application-loop.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        return code or int(any(counts.values()))


if __name__ == '__main__':
    sys.exit(run())
