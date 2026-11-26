"""Independent synthetic P0 repeat probe; use the existing native test guard."""
from contextlib import ExitStack
from pathlib import Path
import hashlib
import json
import os
import sys
import threading
import time
from unittest.mock import patch

import psutil


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tests'), str(ROOT)]
CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 30
if not 1 <= CYCLES <= 60:
    raise ValueError('explicit repeat count must be 1..60')
RUN_LABEL = sys.argv[2] if len(sys.argv) > 2 else 'repeat'
if not RUN_LABEL or not all(c in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in RUN_LABEL):
    raise ValueError('invalid evidence label')
METRICS_FILE = f'cycle-metrics-{RUN_LABEL}.json'
SUMMARY_FILE = f'repeat-summary-{RUN_LABEL}.json'

SOURCE_FILES = (
    'src/services/qt_power_logs.py', 'src/services/qt_archived_logs.py', 'src/services/qt_log_history.py',
    'src/services/qt_workspace_adapter.py', 'src/ui/qt/log_history_dialog.py', 'src/models/qt_log_history.py',
    'tests/test_qt_log_history.py', 'tests/qt_workbench_probe.py', 'scripts/run_tests.py', 'scripts/run_gui_child.py',
)


def file_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


PROCESS = psutil.Process(os.getpid())


def sample():
    return dict(rss_bytes=PROCESS.memory_info().rss, process_handles=PROCESS.num_handles(),
                python_threads=threading.active_count())


def run():
    from qt_test_guard import active_guard
    if active_guard() is None:
        raise RuntimeError('Verified native Qt desktop is required')

    started = time.monotonic()
    baseline_hashes = file_hashes()
    baseline_memory = sample()
    rows = []
    guards = {}
    result_code = None

    with ExitStack() as scope:
        # The probe itself launches no network, physical serial, external program,
        # or model transport. Never relax these guards to pass a repeat.
        for endpoint in (
            'requests.sessions.Session.request', 'serial.Serial', 'socket.create_connection',
            'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyname_ex', 'socket.gethostbyaddr',
            'socket.socket.connect', 'socket.socket.connect_ex', 'socket.socket.send', 'socket.socket.sendall',
            'socket.socket.sendto', 'socket.socket.bind', 'socket.socket.listen', 'socket.socket.accept',
            'subprocess.Popen', 'os.startfile',
        ):
            guards[endpoint] = scope.enter_context(patch(endpoint, side_effect=AssertionError('live I/O forbidden')))

        from PySide6.QtCore import QTimer
        from qt_workbench_probe import QtProjectWorkspaceTests
        from test_qt_log_history import MaterialReadOverlapProbe, QtLogHistoryTests
        from src.models.qt_log_history import HistoryMaterialBatchSummary
        from src.services.qt_power_logs import summarize_history_materials_batch
        from src.ui.qt.log_history_dialog import HistoryResultFilesDialog, LogHistoryController
        import run_tests

        class RepeatCycle(QtProjectWorkspaceTests):
            def setUp(self):
                self.started = time.monotonic()
                self.before = sample()
                self.verified = False
                self.ticks = []
                self.pending_ticks = 0
                self.callback_errors = []
                self.views = []
                self.invalidated = 0
                self.service_cancel = None
                # Registered first: measure after every original cleanup has run.
                self.addCleanup(self.record_after_cleanup)
                super().setUp()
                self.timer = QTimer()
                self.timer.setInterval(10)
                self.timer.timeout.connect(self.heartbeat)
                self.timer.start()
                self.addCleanup(self.timer.stop)

            def heartbeat(self):
                self.ticks.append(time.monotonic())
                try:
                    for dialog in self.controller.log_history.windows.values():
                        files = dialog.result_files_dialog
                        if files is not None and files.summary_pending:
                            self.pending_ticks += 1
                except Exception as error:
                    self.callback_errors.append(type(error).__name__)

            def exercise(self):
                original_show = HistoryResultFilesDialog.show_summary
                original_cancel = LogHistoryController._cancel_summary

                def observe_show(dialog, identifier, summary):
                    if isinstance(summary, HistoryMaterialBatchSummary):
                        self.views.append(dict(request_id=identifier, selected=len(summary.target.channels),
                                               completed=summary.completed_count, failed=summary.failed_count,
                                               cancelled=summary.cancelled_count))
                    return original_show(dialog, identifier, summary)

                def observe_invalidate(controller, files, reason, *, display=True):
                    if any(request[1] is files for request in controller.summary_requests.values()):
                        self.invalidated += 1
                    return original_cancel(controller, files, reason, display=display)

                with patch.object(HistoryResultFilesDialog, 'show_summary', new=observe_show), \
                     patch.object(LogHistoryController, '_cancel_summary', new=observe_invalidate):
                    self.test_qt_multi_channel_saved_material_summary_preserves_independent_and_cancelled_results()
                self.timer.stop()
                self.assertEqual([(r['selected'], r['completed'], r['failed'], r['cancelled']) for r in self.views],
                                 [(3, 3, 0, 0), (3, 1, 0, 2), (2, 2, 0, 0)])
                self.assertEqual(self.invalidated, 3)
                self.assertGreater(self.pending_ticks, 0)
                self.assertFalse(self.callback_errors)
                self.assertFalse(self.controller.log_history.summary_requests)

                # Repeat cancellation while both real synthetic reads are held open.
                fixture = QtLogHistoryTests('test_material_batch_cancel_while_two_real_fixture_reads_overlap_closes_both')
                fixture.setUp()
                try:
                    target, record, paths = fixture.material_batch_fixture()
                    originals = {p: p.read_bytes() for p in paths}
                    stop = threading.Event()
                    probe = MaterialReadOverlapProbe(paths[:5], (paths[0], paths[2]), on_overlap=stop.set)
                    with probe.patch_open():
                        result = summarize_history_materials_batch(fixture.project, record, target, stop)
                    self.assertEqual([row.state for row in result.entries], ['cancelled'] * 3)
                    self.assertCountEqual(probe.read_paths, (paths[0], paths[2]))
                    self.assertEqual(probe.evidence(), dict(peak=2, workers=2, active=0, opened=2, closed=2, all_closed=True))
                    self.assertEqual(originals, {p: p.read_bytes() for p in paths})
                    self.service_cancel = dict(channels_cancelled=result.cancelled_count, **probe.evidence())
                finally:
                    fixture.doCleanups()
                self.assertFalse(any(t.name.startswith('qt-local-material') for t in threading.enumerate()))
                self.verified = True

            def record_after_cleanup(self):
                adapter = getattr(getattr(self, 'controller', None), 'adapter', None)
                closed = bool(adapter is not None and adapter.closed.is_set() and not adapter.thread.is_alive())
                workers = [t.name for t in threading.enumerate() if t.name.startswith('qt-local-material')]
                gaps = [b - a for a, b in zip(self.ticks, self.ticks[1:])]
                row = dict(cycle=self._testMethodName, elapsed_seconds=round(time.monotonic() - self.started, 3),
                           verified=self.verified, before=self.before, after=sample(),
                           qt_ticks=len(self.ticks), pending_ticks=self.pending_ticks,
                           max_timer_gap_ms=round(max(gaps, default=0.0) * 1000, 3),
                           callback_errors=self.callback_errors, displayed_reports=self.views,
                           invalidated_requests=self.invalidated, service_overlap_cancel=self.service_cancel,
                           history_worker_closed=closed, remaining_material_workers=workers)
                rows.append(row)
                # Persist each completed sample so interrupted runs retain evidence.
                (OUT / METRICS_FILE).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
                print('REPEAT_CYCLE: ' + json.dumps(row, ensure_ascii=False), flush=True)
                self.assertTrue(closed)
                self.assertFalse(workers)
                self.assertTrue(self.verified)

        # Explicit named repetitions; do not discover other suite tests.
        names = []
        for number in range(1, CYCLES + 1):
            name = f'test_cycle_{number:03d}'
            setattr(RepeatCycle, name, RepeatCycle.exercise)
            names.append('__main__.RepeatCycle.' + name)
        globals()['RepeatCycle'] = RepeatCycle
        try:
            result_code = run_tests.main(['-v', *names])
            if len(rows) != CYCLES or any(guard.call_count for guard in guards.values()):
                result_code = 1
        finally:
            final_hashes = file_hashes()
            evidence = dict(cycles_requested=CYCLES, cycles_recorded=len(rows),
                            elapsed_seconds=round(time.monotonic() - started, 3),
                            result_code=result_code, baseline_memory=baseline_memory, final_memory=sample(),
                            changed_source_files=[p for p in SOURCE_FILES if baseline_hashes[p] != final_hashes[p]],
                            source_hashes_before=baseline_hashes, source_hashes_after=final_hashes,
                            denied_call_counts={name: guard.call_count for name, guard in guards.items()},
                            metrics=METRICS_FILE)
            (OUT / SUMMARY_FILE).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
            print('REPEAT_SUMMARY: ' + json.dumps(evidence, ensure_ascii=False), flush=True)
    return result_code if result_code is not None else 1


if __name__ == '__main__':
    sys.exit(run())
