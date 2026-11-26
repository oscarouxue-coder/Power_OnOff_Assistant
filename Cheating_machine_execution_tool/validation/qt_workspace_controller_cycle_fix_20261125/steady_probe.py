"""Same-workspace contrast for the process-handle trend of repeat_probe.py."""
from contextlib import ExitStack
from pathlib import Path
import json
import os
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repeat_probe import OUT, sample, file_hashes

CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 60
if not 1 <= CYCLES <= 100:
    raise ValueError('explicit repeat count must be 1..100')


def run():
    from qt_test_guard import active_guard
    if active_guard() is None:
        raise RuntimeError('Verified native Qt desktop is required')
    started = time.monotonic()
    hashes = file_hashes()
    rows = []
    evidence = {}
    guards = {}
    code = None
    with ExitStack() as scope:
        for endpoint in (
            'requests.sessions.Session.request', 'serial.Serial', 'socket.create_connection',
            'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyname_ex', 'socket.gethostbyaddr',
            'socket.socket.connect', 'socket.socket.connect_ex', 'socket.socket.send',
            'socket.socket.sendall', 'socket.socket.sendto', 'socket.socket.bind', 'socket.socket.listen',
            'socket.socket.accept', 'subprocess.Popen', 'os.startfile',
        ):
            guards[endpoint] = scope.enter_context(patch(endpoint, side_effect=AssertionError('live I/O forbidden')))

        from PySide6.QtCore import QTimer, Qt
        from PySide6.QtTest import QTest
        from qt_workbench_probe import QtProjectWorkspaceTests
        from test_qt_log_history import MaterialReadOverlapProbe, QtLogHistoryTests
        from src.services.capability_jobs import CapabilityJobs
        from src.services.qt_archived_logs import _read_page
        import run_tests

        class SteadyCase(QtProjectWorkspaceTests):
            def setUp(self):
                self.addCleanup(self.record_closed)
                super().setUp()

            def record_closed(self):
                adapter = self.controller.adapter
                evidence['after_workspace_close'] = sample()
                evidence['workspace_closed'] = adapter.closed.is_set() and not adapter.thread.is_alive()
                evidence['terminal_owner_refs_released'] = self.controller._workspace_refs_released
                evidence['remaining_material_workers'] = [t.name for t in threading.enumerate()
                                                          if t.name.startswith('qt-local-material')]
                self.assertTrue(evidence['workspace_closed'])
                self.assertTrue(evidence['terminal_owner_refs_released'])
                self.assertFalse(evidence['remaining_material_workers'])

            def test_steady(self):
                self.controller.submit('create', self.root / 'steady-report-project', '合成重复报告项目')
                self.wait_for(lambda: len(self.window.projects) == 1)
                project = self.window.selected_project
                workspace = self.controller.adapter._service
                context = workspace.projects.opened[project]
                jobs = CapabilityJobs(context.history / 'ai/business', SimpleNamespace())
                job = 'fixture-steady-batch'
                try:
                    QtLogHistoryTests.insert_job(jobs, job, 1795040100)
                    with jobs.db:
                        jobs.db.execute('UPDATE jobs SET payload=? WHERE id=?',
                                        (json.dumps({'arguments': {'channel_ids': [7, 8, 9]}}), job))
                finally:
                    jobs.close()
                run = workspace.projects.snapshot(context)
                workspace.status.begin(context, job, run, 'aging.start')
                workspace.status.update(job, 'succeeded')
                paths = {}
                for channel in (7, 8, 9):
                    directory = run / f'Auto_power_on_off_tool/test_results/device_{channel}'
                    directory.mkdir(parents=True)
                    wifi = directory / f'device_{channel}_wifi_20261120221001.log'
                    wifi.write_text(f'2026-11-20 22:10:01.123456 [INFO] [WiFi] 通道{channel} 第1轮 fixture\n', encoding='utf-8')
                    paths[channel] = [wifi]
                    if channel != 8:
                        power = directory / f'device_{channel}_command_results_20261120221001.log'
                        power.write_text(f'通道 {channel} ping 通\n', encoding='utf-8')
                        paths[channel].append(power)
                all_paths = tuple(path for group in paths.values() for path in group)
                paired_paths = (paths[7][1], paths[8][0])
                pinned = (*all_paths, run / 'run.json', jobs.directory / 'capability_jobs.sqlite3')
                originals = {p: p.read_bytes() for p in pinned}

                self.controller.history_action.trigger()
                history = self.controller.log_history
                self.wait_for(lambda: project in history.windows and history.windows[project].result_files_action.isEnabled())
                dialog = history.windows[project]
                self.assertEqual(dialog.jobs.currentData(), job)
                dialog.result_files_action.trigger()
                self.wait_for(lambda: dialog.result_files_dialog is not None)
                files = dialog.result_files_dialog
                for index, channel in enumerate((7, 8, 9)):
                    item = next(files.files.item(i) for i in range(files.files.count())
                                if files.files.item(i).data(Qt.ItemDataRole.UserRole) == paths[channel][0])
                    files.files.scrollToItem(item)
                    QTest.mouseClick(files.files.viewport(), Qt.MouseButton.LeftButton,
                                     Qt.KeyboardModifier.ControlModifier if index else Qt.KeyboardModifier.NoModifier,
                                     files.files.visualItemRect(item).center())
                self.assertEqual([r.channel for r in files.summary_target().channels], [7, 8, 9])
                evidence['before_repeats'] = sample()
                ticks = []
                pending_ticks = [0]
                callback_errors = []
                timer = QTimer()
                timer.setInterval(10)

                def heartbeat():
                    try:
                        ticks.append(time.monotonic())
                        if files.summary_pending:
                            pending_ticks[0] += 1
                    except Exception as error:
                        callback_errors.append(type(error).__name__)

                timer.timeout.connect(heartbeat)
                timer.start()
                self.addCleanup(timer.stop)

                def unreadable(path, *args):
                    if path == paths[9][0]:
                        raise PermissionError('fixture')
                    return _read_page(path, *args)

                for number in range(1, CYCLES + 1):
                    begin = time.monotonic()
                    first_tick = len(ticks)
                    first_pending = pending_ticks[0]
                    normal = MaterialReadOverlapProbe(all_paths, paired_paths)
                    with normal.patch_open(), patch('src.services.qt_archived_logs._read_page', side_effect=unreadable):
                        files.summary_action.trigger()
                        self.wait_for(lambda: files.summary.isVisible() and not files.summary_pending)
                    text = files.summary.toPlainText()
                    self.assertIn('已完成核对 3 个', text)
                    self.assertIn('其中资料缺失或读取失败 2 个', text)
                    self.assertIn(paths[7][0].name + '@0:1', text)
                    self.assertNotIn(paths[9][0].name + '@', text)
                    self.assertEqual(normal.evidence(), dict(peak=2, workers=2, active=0, opened=4, closed=4, all_closed=True))

                    entered, release = threading.Event(), threading.Event()

                    def hold_pair():
                        entered.set()
                        if not release.wait(10):
                            raise AssertionError('fixture overlap release missing')

                    cancelled = MaterialReadOverlapProbe(all_paths, paired_paths, on_overlap=hold_pair)
                    try:
                        with cancelled.patch_open():
                            files.summary_action.trigger()
                            self.wait_for(entered.is_set)
                            count_at_entry = pending_ticks[0]
                            self.wait_for(lambda: pending_ticks[0] > count_at_entry)
                            files.summary_cancel.click()
                            self.assertTrue(files.summary_pending)
                            release.set()
                            self.wait_for(lambda: files.summary.isVisible() and not files.summary_pending)
                    finally:
                        release.set()
                    text = files.summary.toPlainText()
                    self.assertIn('已完成核对 0 个', text)
                    self.assertIn('已取消 3 个', text)
                    self.assertNotIn('@0:1', text)
                    self.assertCountEqual(cancelled.read_paths, paired_paths)
                    self.assertEqual(cancelled.evidence(), dict(peak=2, workers=2, active=0, opened=2, closed=2, all_closed=True))
                    self.assertFalse(history.summary_requests)
                    self.wait_for(lambda: not self.controller.adapter._history_reads)
                    self.assertFalse(any(t.name.startswith('qt-local-material') for t in threading.enumerate()))
                    self.assertNotIn(project, self.controller.adapter._executions)
                    self.assertFalse(callback_errors)
                    period = ticks[max(0, first_tick - 1):]
                    gaps = [b - a for a, b in zip(period, period[1:])]
                    row = dict(cycle=number, elapsed_seconds=round(time.monotonic() - begin, 3),
                               after=sample(), completed_reports=1, cancelled_reports=1,
                               completed_channels=3, cancelled_channels=3,
                               normal=normal.evidence(), cancelled=cancelled.evidence(),
                               qt_ticks=len(ticks) - first_tick, pending_ticks=pending_ticks[0] - first_pending,
                               max_timer_gap_ms=round(max(gaps, default=0.0) * 1000, 3),
                               remaining_workers=0)
                    rows.append(row)
                    (OUT / 'steady-metrics.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
                    print('STEADY_CYCLE: ' + json.dumps(row), flush=True)
                timer.stop()
                self.assertEqual(originals, {p: p.read_bytes() for p in pinned})
                evidence['original_history_unchanged'] = True
                evidence['before_workspace_close'] = sample()
                evidence['qt_callback_errors'] = callback_errors
                files.close()
                dialog.close()
                self.window.close()
                self.wait_for(lambda: not self.window.isVisible() and
                              self.controller.adapter.closed.is_set() and
                              not self.controller.adapter.thread.is_alive())

        globals()['SteadyCase'] = SteadyCase
        try:
            code = run_tests.main(['-v', '__main__.SteadyCase.test_steady'])
            if len(rows) != CYCLES or any(guard.call_count for guard in guards.values()):
                code = 1
        finally:
            final_hashes = file_hashes()
            evidence.update(cycles_requested=CYCLES, cycles_recorded=len(rows), result_code=code,
                            elapsed_seconds=round(time.monotonic() - started, 3),
                            changed_source_files=[p for p in hashes if hashes[p] != final_hashes[p]],
                            source_hashes_before=hashes, source_hashes_after=final_hashes,
                            denied_call_counts={name: guard.call_count for name, guard in guards.items()})
            (OUT / 'steady-summary.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
            print('STEADY_SUMMARY: ' + json.dumps(evidence, ensure_ascii=False), flush=True)
    return code if code is not None else 1


if __name__ == '__main__':
    sys.exit(run())
