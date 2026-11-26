"""Temp-directory workspace logging, with injected delays and independently failing sinks."""
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from src.models.workbench_presentation import LogView
from src.services.workspace_event_log import WorkspaceEventWriter, read_workspace_events


class WorkspaceEventLogTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.reports = []

    def writer(self, **settings):
        writer = WorkspaceEventWriter(lambda *args: self.reports.append(args), **settings)
        writer.start(self.root)
        self.addCleanup(writer.close)
        return writer

    @staticmethod
    def entry(message, project='p1'):
        return LogView('12:34:56', 'WARN', project, '同名工程', message, 'local-job', 2,
                       dut_id='DUT共用名', step='lan_ping', job_id='local-job', batch_id='actual-run')

    def test_daily_rollover_restart_filters_original_text_and_stable_keyset_paging(self):
        stamp = [datetime(2026, 11, 21, 23, 59, 59)]
        writer = self.writer(clock=lambda: stamp[0])
        for text in ('原文一\n第二行', '原文二'):
            self.assertTrue(writer.offer(self.entry(text)))
        writer.offer(self.entry('其他项目', 'p2'))
        stamp[0] = datetime(2026, 11, 22, 0, 0, 1)
        writer.offer(self.entry('跨日'))
        writer.close()
        filters = dict(project_id='p1', dut_id='DUT共用名', channel=2, level='WARN', step='lan_ping',
                       job_id='local-job', run_id='actual-run')
        top = read_workspace_events(self.root, limit=1, **filters)
        self.assertEqual([r['message'] for r in top], ['跨日'])
        writer = self.writer(clock=lambda: stamp[0])
        writer.offer(self.entry('重启后'))
        writer.close()
        older = read_workspace_events(self.root, before=top[0]['cursor'], **filters)
        self.assertEqual([r['message'] for r in older], ['原文二', '原文一\n第二行'])
        self.assertEqual(len(read_workspace_events(self.root, **filters)), 4)
        self.assertEqual(len(read_workspace_events(self.root, project_id='p2')), 1)
        self.assertEqual(read_workspace_events(self.root, run_id='local-job'), ())
        self.assertIn('12:34:56 [p1] 原文一\n第二行\n', (self.root/'workspace.log').read_text(encoding='utf-8'))

    def test_blocked_disk_keeps_admission_bounded_and_close_waits_for_both_archives(self):
        writer = self.writer(max_events=2, max_chars=12, reserve_events=1, reserve_chars=20)
        write = writer._write_text
        entered, release, closed = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def slow(batch):
            entered.set()
            release.wait(5)
            write(batch)

        with patch.object(writer, '_write_text', side_effect=slow):
            writer.offer(self.entry('first'))
            self.assertTrue(entered.wait(2))
            self.assertTrue(writer.offer(self.entry('second')))
            self.assertTrue(writer.offer(self.entry('third')))
            producer_done = threading.Event()
            producer = threading.Thread(target=lambda: (writer.offer(self.entry('fourth')), producer_done.set()))
            producer.start()
            self.assertFalse(producer_done.wait(.05))
            self.assertTrue(writer.offer(self.entry('stop'), control=True))
            self.assertFalse(writer.offer(self.entry('reserve full'), control=True))
            pending, age = writer.pending_snapshot()
            self.assertEqual(pending, 4)
            self.assertGreater(age, 0)
            self.assertFalse(writer.flush(0))
            release.set()
            producer.join(3)
            self.assertTrue(producer_done.is_set())
            self.assertTrue(writer.flush())
            entered.clear()
            release.clear()
            writer.offer(self.entry('final'))
            self.assertTrue(entered.wait(2))
            closer = threading.Thread(target=lambda: (writer.close(), closed.set()))
            closer.start()
            self.assertFalse(closed.wait(.05))
            self.assertFalse(writer.release_closed_callbacks())
            self.assertTrue(callable(writer.report))
            release.set()
            closer.join(3)
            self.assertTrue(closed.is_set())
        rows = read_workspace_events(self.root)
        self.assertEqual([row['message'] for row in rows if row['project_id']],
                         ['final', 'fourth', 'stop', 'third', 'second', 'first'])
        self.assertTrue(any('1 条原始记录未进入归档' in row['message'] for row in rows))
        self.assertEqual(sum(report[3] for report in self.reports), 1)
        self.assertFalse(writer.offer(self.entry('late')))
        self.assertEqual(writer.pending_snapshot(), (0, 0.))
        self.assertIsNone(writer.report)
        self.assertTrue(writer.release_closed_callbacks())
        writer.close()

    def test_unconfirmed_final_archive_does_not_release_callback_ownership(self):
        writer = self.writer()
        with patch.object(writer, '_write_text', side_effect=OSError('synthetic write failure')), \
                patch('src.services.workspace_event_log._write_events', side_effect=OSError('synthetic archive failure')):
            self.assertTrue(writer.offer(self.entry('final')))
            writer.close()
        self.assertFalse(writer.release_closed_callbacks())
        self.assertTrue(callable(writer.report))
        self.assertTrue(self.reports[-1][1])

    def test_one_sink_failure_preserves_original_and_two_sink_failure_reports_on_recovery(self):
        writer = self.writer()
        with patch.object(writer, '_write_text', side_effect=PermissionError):
            writer.offer(self.entry('主文本不可写'))
            self.assertTrue(writer.flush())
            with patch('src.services.workspace_event_log._write_events', side_effect=OSError):
                writer.offer(self.entry('两端不可写'))
                self.assertTrue(writer.flush())
        writer.offer(self.entry('恢复'))
        self.assertTrue(writer.flush())
        with patch('src.services.workspace_event_log._write_events', side_effect=OSError):
            writer.offer(self.entry('结构档不可写'))
            self.assertTrue(writer.flush())
        writer.close()
        messages = [r['message'] for r in read_workspace_events(self.root)]
        self.assertIn('主文本不可写', messages)
        self.assertIn('此前 1 条工作区记录的两份日志都未确认写入', messages)
        self.assertNotIn('两端不可写', messages)
        self.assertTrue(any('PermissionError' in msg for msg in messages))
        text = (self.root/'workspace.log').read_text(encoding='utf-8')
        self.assertIn('结构档不可写', text)
        self.assertIn('结构化归档 OSError', text)

    def test_empty_and_invalid_queries_never_create_files(self):
        self.assertEqual(read_workspace_events(self.root), ())
        for kwargs in (dict(before=['../tmp', 2]), dict(limit=121), dict(before=('2026-11-21', False))):
            with self.assertRaises(ValueError):
                read_workspace_events(self.root, **kwargs)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_process_exit_during_uncommitted_archive_transaction_preserves_committed_prefix(self):
        writer = self.writer()
        writer.offer(self.entry('已提交'))
        writer.close()
        path, = (self.root / 'workspace-events').glob('*.sqlite3')
        child = subprocess.run([sys.executable, '-c', (
            'import os, sqlite3, sys\n'
            'db=sqlite3.connect(sys.argv[1])\n'
            'db.execute("BEGIN IMMEDIATE")\n'
            'db.execute("UPDATE events SET message=?", ("interrupted",))\n'
            'os._exit(13)\n'), str(path)], timeout=8)
        self.assertEqual(child.returncode, 13)
        writer = self.writer()
        writer.offer(self.entry('重启后提交'))
        writer.close()
        self.assertEqual([r['message'] for r in read_workspace_events(self.root)], ['重启后提交', '已提交'])
