from pathlib import Path
import json
import sqlite3
from threading import Barrier, Event, Lock, get_ident
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.models.project import ProjectContext, ProjectIdentity
from src.models.qt_log_history import HistoryEventFilter, HistoryMaterialBatchTarget, HistoryMaterialTarget
from src.services.capability_jobs import CapabilityJobs
from src.services.qt_log_history import EVENTS_PER_PAGE, JOBS_PER_PAGE, MAX_MESSAGE_CHARS, read_channel_history, read_log_history
from src.services.qt_power_logs import (history_result_files, open_history_result_file, summarize_history_materials,
                                       summarize_history_materials_batch)
from src.services.project_status_service import ProjectStatusService


class MaterialReadOverlapProbe:
    """Synthetic file handles remain open across two real bounded read calls."""

    def __init__(self, paths, together, on_overlap=None):
        self.paths, self.together = frozenset(paths), frozenset(together)
        self.entered, self.read_done = Barrier(2, action=on_overlap), Barrier(2)
        self.lock = Lock()
        self.active = self.peak = 0
        self.threads = set()
        self.opened, self.closed, self.read_paths = [], [], []

    def patch_open(self):
        owner, original = self, Path.open

        def opened(path, *args, **kwargs):
            stream = original(path, *args, **kwargs)
            if path not in owner.paths or (args[0] if args else kwargs.get('mode')) != 'rb':
                return stream
            with owner.lock:
                owner.opened.append(path)

            class Tracked:
                first_read = True

                def __getattr__(self, name):
                    return getattr(stream, name)

                def __enter__(self):
                    stream.__enter__()
                    return self

                def __exit__(self, *exc):
                    try:
                        return stream.__exit__(*exc)
                    finally:
                        with owner.lock:
                            owner.closed.append((path, stream.closed))

                def read(self, *read_args):
                    paired = self.first_read and path in owner.together
                    self.first_read = False
                    with owner.lock:
                        owner.active += 1
                        owner.peak = max(owner.peak, owner.active)
                        owner.threads.add(get_ident())
                        owner.read_paths.append(path)
                    try:
                        if paired:
                            owner.entered.wait(10)
                        data = stream.read(*read_args)
                        if paired:
                            owner.read_done.wait(10)
                        return data
                    finally:
                        with owner.lock:
                            owner.active -= 1

            return Tracked()

        return patch.object(Path, 'open', new=opened)

    def evidence(self):
        with self.lock:
            return dict(peak=self.peak, workers=len(self.threads), active=self.active,
                        opened=len(self.opened), closed=len(self.closed),
                        all_closed=len(self.opened) == len(self.closed) and all(closed for _, closed in self.closed))


class QtLogHistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.project = ProjectContext(root / '工程 A #历史', ProjectIdentity('project-a', '验证 A', 'fixture'), root)
        self.other = ProjectContext(root / '工程 B', ProjectIdentity('project-b', '验证 B', 'fixture'), root)

    def open_jobs(self, context):
        jobs = CapabilityJobs(context.history / 'ai/business', SimpleNamespace())
        self.addCleanup(jobs.close)
        return jobs

    @staticmethod
    def insert_job(jobs, identifier, order):
        with jobs.db:
            jobs.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (identifier, identifier, '', 'private-principal', '', 'aging.start', 'succeeded', '',
                 order, order, '{"credential":"fixture-private"}', 'null'))

    def material_fixture(self, context, job='saved-batch', run_id='2' * 32, channels=(7, 8)):
        jobs = self.open_jobs(context)
        self.insert_job(jobs, job, 1)
        with jobs.db:
            jobs.db.execute('UPDATE jobs SET payload=? WHERE id=?',
                            (json.dumps({'arguments': {'channel_ids': list(channels)}}), job))
        run = context.root / 'runs' / run_id
        directory = run / 'Auto_power_on_off_tool/test_results/device_7'
        directory.mkdir(parents=True)
        record = dict(owner=job, project_id=context.identity.project_id, run_id=run_id, operation='aging.start')
        manifest = run / 'run.json'
        manifest.write_text(json.dumps(record), encoding='utf-8')
        power = directory / 'device_7_command_results_20261120220100.log'
        wifi = directory / 'device_7_wifi_20261120220100.log'
        power.write_text('通道 7 ping 通\n通道 8 ping 通\nfixture-secret-never-copy\n', encoding='utf-8')
        wifi.write_text('2026-11-20 22:01:01.123456 [ERROR] [WiFi] 通道7 第2轮 fixture-secret-never-copy\n'
                        '2026-11-20 22:01:02.123456 [INFO] [WiFi] 通道8 第3轮 foreign-channel\n', encoding='utf-8')
        target = HistoryMaterialTarget(context.identity.project_id, job, run_id, 7, power.name, wifi.name)
        return target, dict(record, _path=manifest), power, wifi, jobs.directory / 'capability_jobs.sqlite3'

    def material_batch_fixture(self):
        from dataclasses import replace
        first, record, power, wifi, database = self.material_fixture(self.project, channels=(7, 8, 9))
        folder = power.parent.parent
        eight = folder / 'device_8/device_8_wifi_20261120220100.log'
        nine_power = folder / 'device_9/device_9_command_results_20261120220100.log'
        nine_wifi = folder / 'device_9/device_9_wifi_20261120220100.log'
        eight.parent.mkdir()
        nine_power.parent.mkdir()
        eight.write_text('2026-11-20 22:02:01.123456 [INFO] [WiFi] 通道8 第4轮 fixture\n', encoding='utf-8')
        nine_power.write_text('通道 9 ping 通\n', encoding='utf-8')
        nine_wifi.write_text('2026-11-20 22:03:01.123456 [WARN] [WiFi] 通道9 第5轮 fixture\n', encoding='utf-8')
        second = replace(first, channel=8, power_name='', wifi_name=eight.name)
        third = replace(first, channel=9, power_name=nine_power.name, wifi_name=nine_wifi.name)
        return (HistoryMaterialBatchTarget(first.project_id, first.job_id, first.run_id, (first, second, third)),
                record, (power, wifi, eight, nine_power, nine_wifi, database, record['_path']))

    def test_saved_material_report_exact_scope_round_trip_without_source_reread(self):
        from src.services.qt_archived_logs import _read_page
        from src.services.qt_power_logs import material_report_snapshot, save_material_report, read_material_reports
        target, record, paths = self.material_batch_fixture()
        record.update(state='succeeded', updated_at=1795040123)
        original = {path: path.read_bytes() for path in paths}
        def read(path, *args):
            if path == paths[4]:
                raise PermissionError('fixture')
            return _read_page(path, *args)
        with patch('src.services.qt_archived_logs._read_page', side_effect=read):
            summary = summarize_history_materials_batch(self.project, record, target, Event())
        snapshot = material_report_snapshot(self.project, record, summary)
        self.assertIn('缺失 1 份', snapshot.text)
        self.assertIn('无法读取 1 份', snapshot.text)
        self.assertNotIn('fixture-secret-never-copy', snapshot.text)
        saved = save_material_report(self.project, record, snapshot, Event())
        with patch('src.services.qt_archived_logs._read_page', side_effect=AssertionError('must not reread')):
            reopened = read_material_reports(self.project, record, target.job_id, Event())
        self.assertEqual(reopened.reports, (saved,))
        self.assertEqual(reopened.invalid_count, 0)
        self.assertEqual(saved.channels, (7, 8, 9))
        self.assertEqual(saved.historical_state, 'succeeded')
        self.assertTrue(saved.historical_at and saved.generated_at and saved.saved_at)
        self.assertEqual(original, {path: path.read_bytes() for path in paths})
        with self.assertRaises(ValueError):
            save_material_report(self.project, record, snapshot, Event())
        with self.assertRaises(ValueError):
            read_material_reports(self.other, record, target.job_id, Event())
        wrong = dict(record, owner='another-job', run_id='3' * 32)
        self.assertFalse(read_material_reports(self.project, wrong, 'another-job', Event()).reports)

    def test_saved_material_report_cancel_failure_and_corrupt_record_are_independent(self):
        from src.services.qt_power_logs import material_report_snapshot, save_material_report, read_material_reports
        target, record, *_ = self.material_fixture(self.project)
        record.update(state='succeeded', updated_at=1795040123)
        summary = summarize_history_materials(self.project, record, target, Event())
        snapshot = material_report_snapshot(self.project, record, summary)
        cancel = Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            save_material_report(self.project, record, snapshot, cancel)
        with patch('src.services.qt_power_logs.atomic_json', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                save_material_report(self.project, record, snapshot, Event())
        self.assertFalse(read_material_reports(self.project, record, target.job_id, Event()).reports)
        saved = save_material_report(self.project, record, snapshot, Event())
        directory = next((self.project.history / 'material_reports').iterdir())
        broken = directory / ('a' * 32 + '.json')
        broken.write_text('invalid synthetic record', encoding='utf-8')
        page = read_material_reports(self.project, record, target.job_id, Event())
        self.assertEqual(page.reports, (saved,))
        self.assertEqual(page.invalid_count, 1)
        with self.assertRaises(InterruptedError):
            read_material_reports(self.project, record, target.job_id, cancel)

    def test_material_batch_reports_three_channels_independently_and_keeps_valid_results(self):
        from src.services.qt_archived_logs import _read_page
        target, record, paths = self.material_batch_fixture()
        originals = {p: p.read_bytes() for p in paths}
        overlap = MaterialReadOverlapProbe(paths[:5], (paths[0], paths[2]))

        def read(path, *args):
            if path == paths[4]:
                raise PermissionError('fixture')
            return _read_page(path, *args)

        with overlap.patch_open(), patch('src.services.qt_archived_logs._read_page', side_effect=read):
            self.material_fixture(self.other)
            summary = summarize_history_materials_batch(self.project, record, target, Event())
        self.assertTrue(summary.matches(target))
        self.assertEqual((summary.completed_count, summary.failed_count, summary.cancelled_count), (3, 0, 0))
        rows = [row.summary for row in summary.entries]
        self.assertEqual([(r.read_count, r.missing_count, r.failed_count) for r in rows], [(2, 0, 0), (1, 1, 0), (1, 0, 1)])
        self.assertIn('第2轮，记录等级 ERROR', rows[0].text)
        self.assertIn('第4轮，记录等级 INFO', rows[1].text)
        self.assertIn(paths[3].name + '@0:1', rows[2].text)
        self.assertNotIn(paths[2].name, rows[0].text)
        self.assertNotIn(paths[0].name, rows[1].text)
        self.assertNotIn(paths[4].name + '@', rows[2].text)
        self.assertIn('其中资料缺失或读取失败 2 个', summary.text)
        self.assertIn('故障原因及当前设备状态未知', summary.text)
        self.assertEqual(originals, {p: p.read_bytes() for p in paths})
        self.assertEqual(overlap.evidence(), dict(peak=2, workers=2, active=0, opened=4, closed=4, all_closed=True))
        self.assertCountEqual(overlap.read_paths, paths[:4])
        self.assertEqual([row.target.channel for row in summary.entries], [7, 8, 9])
        print('MATERIAL_PARALLEL_SERVICE_EVIDENCE: ' + json.dumps(overlap.evidence()))

    def test_material_batch_rejects_mixed_and_duplicate_scope_before_any_source_read(self):
        from dataclasses import replace
        target, record, _ = self.material_batch_fixture()
        first, second, third = target.channels
        cases = (replace(target, channels=(first, replace(second, project_id='project-b'))),
                 replace(target, channels=(first, replace(second, run_id='8' * 32))),
                 replace(target, channels=(first, replace(second, job_id='other-job'))),
                 replace(target, channels=(first, first)),
                 replace(target, channels=(first, replace(second, wifi_name='../not-a-source.log'))),
                 replace(target, channels=(first, replace(second, channel=10, wifi_name='device_10_wifi_20261120.log'))))
        with patch('src.services.qt_archived_logs._read_page', side_effect=AssertionError('unexpected source read')):
            for selected in cases:
                with self.subTest(selected=selected), self.assertRaises(ValueError):
                    summarize_history_materials_batch(self.project, record, selected, Event())

    def test_material_batch_cancel_preserves_completed_channel_and_marks_rest_without_read(self):
        target, record, _ = self.material_batch_fixture()
        stop = Event()
        first_done = Event()
        calls = []

        def read(context, saved, row, cancel):
            calls.append(row.channel)
            if row.channel == 7:
                result = summarize_history_materials(context, saved, row, cancel)
                first_done.set()
                return result
            if row.channel == 8:
                if not first_done.wait(10):
                    raise AssertionError('first channel did not complete')
                stop.set()
            return summarize_history_materials(context, saved, row, cancel)

        with patch('src.services.qt_power_logs.summarize_history_materials', side_effect=read):
            result = summarize_history_materials_batch(self.project, record, target, stop)
            self.assertCountEqual(calls, [7, 8])
            self.assertEqual([r.state for r in result.entries], ['completed', 'cancelled', 'cancelled'])
            self.assertIsNotNone(result.entries[0].summary)
            self.assertIsNone(result.entries[1].summary)
            self.assertIn('已取消 2 个', result.text)
            self.assertIn('CH09 · 已取消', result.text)
            calls.clear()
            cancelled = summarize_history_materials_batch(self.project, record, target, stop)
            self.assertEqual(calls, [])
            self.assertEqual(cancelled.cancelled_count, 3)

    def test_material_batch_cancel_while_two_real_fixture_reads_overlap_closes_both(self):
        import threading
        target, record, paths = self.material_batch_fixture()
        originals = {p: p.read_bytes() for p in paths}
        stop = Event()
        overlap = MaterialReadOverlapProbe(paths[:5], (paths[0], paths[2]), on_overlap=stop.set)
        with overlap.patch_open():
            result = summarize_history_materials_batch(self.project, record, target, stop)
        self.assertEqual([row.state for row in result.entries], ['cancelled', 'cancelled', 'cancelled'])
        self.assertTrue(all(row.summary is None for row in result.entries))
        self.assertCountEqual(overlap.read_paths, (paths[0], paths[2]))
        self.assertEqual(overlap.evidence(), dict(peak=2, workers=2, active=0, opened=2, closed=2, all_closed=True))
        self.assertFalse(any(thread.name.startswith('qt-local-material') for thread in threading.enumerate()))
        self.assertEqual(originals, {p: p.read_bytes() for p in paths})
        print('MATERIAL_PARALLEL_CANCEL_EVIDENCE: ' + json.dumps(overlap.evidence()))

    def test_material_batch_whole_channel_failure_does_not_erase_other_channel_results(self):
        from dataclasses import replace
        target, record, _ = self.material_batch_fixture()

        def read(context, saved, row, cancel):
            if row.channel == 8:
                raise ValueError('fixture failed')
            return summarize_history_materials(context, saved, row, cancel)

        with patch('src.services.qt_power_logs.summarize_history_materials', side_effect=read):
            result = summarize_history_materials_batch(self.project, record, target, Event())
        self.assertEqual([r.state for r in result.entries], ['completed', 'failed', 'completed'])
        self.assertIn('CH08 · 无法核对', result.text)
        self.assertIn('第5轮，记录等级 WARN', result.entries[2].summary.text)
        self.assertFalse(replace(result, entries=(result.entries[1], *result.entries[1:])).matches(target))

    def test_material_summary_reads_two_saved_sources_with_exact_scope_and_citations(self):
        target, record, power, wifi, database = self.material_fixture(self.project)
        self.material_fixture(self.other)
        before = {p: p.read_bytes() for p in (power, wifi, database, record['_path'])}
        with patch('src.services.qt_power_logs._launch', side_effect=AssertionError('unexpected launch')):
            summary = summarize_history_materials(self.project, record, target, Event())
        self.assertEqual((summary.read_count, summary.missing_count, summary.failed_count), (2, 0, 0))
        self.assertEqual(summary.target, target)
        self.assertIn(power.name + '@0:1', summary.text)
        self.assertIn(wifi.name + '@0:1', summary.text)
        self.assertIn('2026-11-20 22:01:01.123456', summary.text)
        self.assertIn('第2轮，记录等级 ERROR', summary.text)
        self.assertIn('时间未知', summary.text)
        self.assertIn('故障原因及当前设备状态未知', summary.text)
        for marker in ('fixture-secret-never-copy', 'foreign-channel', '第3轮', '通道 8'):
            self.assertNotIn(marker, summary.text)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_material_summary_rejects_wrong_project_batch_channel_or_filename_before_read(self):
        from dataclasses import replace
        target, record, _, _, _ = self.material_fixture(self.project)
        self.material_fixture(self.other)
        with patch('src.services.qt_archived_logs._read_page', side_effect=AssertionError('unexpected read')):
            for context, selected in ((self.other, target), (self.project, replace(target, run_id='3' * 32)),
                                      (self.project, replace(target, channel=8)),
                                      (self.project, replace(target, wifi_name='../other.log'))):
                with self.subTest(selected=selected), self.assertRaises(ValueError):
                    summarize_history_materials(context, record, selected, Event())

    def test_material_summary_separates_missing_unreadable_and_keeps_other_result(self):
        from dataclasses import replace
        from src.services.qt_archived_logs import _read_page
        target, record, power, wifi, _ = self.material_fixture(self.project)
        missing = summarize_history_materials(self.project, record, replace(target, wifi_name=''), Event())
        self.assertEqual((missing.read_count, missing.missing_count, missing.failed_count), (1, 1, 0))
        self.assertIn('缺少已列出的留存文件', missing.text)

        def read(path, *args):
            if path == power:
                raise PermissionError('fixture private path')
            return _read_page(path, *args)

        with patch('src.services.qt_archived_logs._read_page', side_effect=read):
            partial = summarize_history_materials(self.project, record, target, Event())
        self.assertEqual((partial.read_count, partial.missing_count, partial.failed_count), (1, 0, 1))
        self.assertIn('无法读取', partial.text)
        self.assertIn(wifi.name + '@0:1', partial.text)
        self.assertNotIn('fixture private path', partial.text)

    def test_material_summary_is_bounded_and_stops_before_next_source(self):
        from src.services.qt_archived_logs import _read_page
        target, record, power, _, _ = self.material_fixture(self.project)
        power.write_text('通道 7 ping 通\n' * 200 + '通道 7 ping 通', encoding='utf-8')
        summary = summarize_history_materials(self.project, record, target, Event())
        self.assertIn('已读取 120 行', summary.text)
        self.assertIn('有更早内容未读取', summary.text)
        self.assertEqual(summary.text.count('引用 ' + power.name), 6)
        self.assertIn('明确标记 119 条', summary.text)
        stop = Event()

        def read(path, *args):
            stop.set()
            return _read_page(path, *args)

        with patch('src.services.qt_archived_logs._read_page', side_effect=read) as reader:
            with self.assertRaises(InterruptedError):
                summarize_history_materials(self.project, record, target, stop)
            reader.assert_called_once()
        with patch('src.services.qt_archived_logs._read_page', side_effect=AssertionError('unexpected read')):
            with self.assertRaises(InterruptedError):
                summarize_history_materials(self.project, record, target, stop)

    def test_material_summary_refuses_wal_and_oversized_binding_without_source_reads(self):
        from dataclasses import replace
        target, record, _, _, _ = self.material_fixture(self.project)
        database = self.other.history / 'ai/business/capability_jobs.sqlite3'
        database.parent.mkdir(parents=True)
        header = bytearray(100)
        header[18:20] = b'\x02\x02'
        database.write_bytes(header)
        foreign = replace(target, project_id=self.other.identity.project_id)
        with patch('src.services.qt_power_logs.sqlite3.connect', side_effect=AssertionError('unexpected SQLite open')):
            with self.assertRaisesRegex(ValueError, 'WAL'):
                summarize_history_materials(self.other, dict(record, project_id=foreign.project_id), foreign, Event())
        self.assertEqual(database.read_bytes(), bytes(header))
        self.assertEqual(tuple(database.parent.iterdir()), (database,))

        with record['_path'].open('ab') as stream:
            stream.write(b' ' * (256 * 1024))
        with patch('src.services.qt_archived_logs._read_page', side_effect=AssertionError('unexpected read')):
            with self.assertRaisesRegex(ValueError, '运行快照'):
                summarize_history_materials(self.project, record, target, Event())

    def test_jobs_and_events_page_by_project_and_task_without_repeating_inserted_rows(self):
        jobs = self.open_jobs(self.project)
        other = self.open_jobs(self.other)
        for number in range(JOBS_PER_PAGE + 2):
            self.insert_job(jobs, f'fixture-{number:03d}', number)
        target = 'fixture-000'
        self.insert_job(other, target, 0)
        other.event(target, 'aging', '{"channel":1,"text":"other-project"}')
        for index in range(EVENTS_PER_PAGE + 5):
            jobs.event(target, 'aging', f'{{"channel":1,"index":{index}}}')
        jobs.event('fixture-001', 'history', '{"channel":1,"text":"other-task"}')
        log_database = jobs.directory / 'capability_jobs.sqlite3'
        original = log_database.read_bytes()
        job_page = read_log_history(self.project, None)
        self.assertEqual(len(job_page.entries), JOBS_PER_PAGE)
        self.assertNotIn('fixture-private', repr(job_page))
        self.assertNotIn('private-principal', repr(job_page))
        oldest_jobs = read_log_history(self.project, job_page.next_cursor)
        self.assertEqual([entry.job_id for entry in oldest_jobs.entries], ['fixture-001', target])
        first = read_log_history(self.project, None, target)
        self.assertEqual(len(first.entries), EVENTS_PER_PAGE)
        self.assertTrue(all(row.project_id == 'project-a' and row.run_id == target and row.channel == 1 for row in first.entries))
        self.assertIn('"index":5', first.entries[0].message)
        self.assertIn('"index":64', first.entries[-1].message)
        self.assertEqual(log_database.read_bytes(), original)
        jobs.event(target, 'aging', '{"channel":7,"text":"late"}')
        older = read_log_history(self.project, first.next_cursor, target)
        self.assertEqual(len(older.entries), 5)
        self.assertIsNone(older.next_cursor)
        self.assertNotIn('late', repr(older))
        self.assertNotIn('other-task', repr(first))
        self.assertNotIn('other-project', repr(first))
        self.assertIn('other-project', read_log_history(self.other, None, target).entries[0].message)
        with self.assertRaisesRegex(ValueError, '不属于'):
            read_log_history(self.other, None, 'fixture-001')

    def test_full_job_filter_pages_matches_and_shows_original_long_record_excerpt(self):
        jobs = self.open_jobs(self.project)
        for job in ('selected', 'other'):
            self.insert_job(jobs, job, 1)
        # More recent nonmatches must not push the oldest matches out of the search.
        for index in range(EVENTS_PER_PAGE + 2):
            jobs.event('selected', 'aging', json.dumps(dict(channel='channel_07', text=f'Straße%_{index}'),
                                                       ensure_ascii=False))
        text = 'ß' * (MAX_MESSAGE_CHARS + 500) + ' — STraße%_tail'
        jobs.event('selected', 'history', json.dumps(dict(text=text, channel=7), ensure_ascii=False))
        for _ in range(EVENTS_PER_PAGE + 1):
            jobs.event('selected', 'failed', 'Straße%_')
        jobs.event('other', 'aging', '{"channel":7,"text":"STRASSE%_other"}')
        filters = HistoryEventFilter('strasse%_', 'INFO', 7)
        page = read_log_history(self.project, None, 'selected', filters)
        self.assertEqual(len(page.entries), EVENTS_PER_PAGE)
        self.assertIn('STraße%_tail', page.entries[-1].message)
        self.assertIn('命中位置节选', page.entries[-1].message)
        self.assertLess(len(page.entries[-1].message), MAX_MESSAGE_CHARS + 100)
        self.assertTrue(all(row.channel == 7 and row.level == 'INFO' for row in page.entries))
        jobs.event('selected', 'aging', '{"channel":7,"text":"STRASSE%_later"}')
        older = read_log_history(self.project, page.next_cursor, 'selected', filters)
        self.assertEqual(len(older.entries), 3)
        self.assertIsNone(older.next_cursor)
        self.assertIn('Straße%_0', older.entries[0].message)
        self.assertNotIn('other', repr(page.entries))
        self.assertNotIn('later', repr(older.entries))
        self.assertFalse(read_log_history(self.project, None, 'selected',
                                          HistoryEventFilter('strasse%_', 'ERROR', 7)).entries)

    def test_cancelled_history_read_skips_missing_database_and_closes_new_connection(self):
        cancelled = Event()
        cancelled.set()
        with patch('src.services.qt_log_history.job_database_path') as path:
            with self.assertRaisesRegex(ValueError, '已取消任务历史读取'):
                read_log_history(self.project, None, closing_event=cancelled)
            path.assert_not_called()
        self.assertFalse(self.project.history.exists())

        self.open_jobs(self.project)
        connect = sqlite3.connect
        connections = []

        def cancel_on_connect(*args, **kwargs):
            connections.append(connect(*args, **kwargs))
            cancelled.set()
            return connections[-1]

        for job in (None, 'selected'):
            cancelled.clear()
            with patch('src.services.qt_log_history.sqlite3.connect', side_effect=cancel_on_connect):
                with self.assertRaisesRegex(ValueError, '已取消任务历史读取'):
                    read_log_history(self.project, None, job, closing_event=cancelled)
            with self.assertRaises(sqlite3.ProgrammingError):
                connections[-1].execute('SELECT 1')

    def test_short_job_query_honors_cancel_and_long_event_scan_interrupts_sqlite(self):
        jobs = self.open_jobs(self.project)
        self.insert_job(jobs, 'selected', 1)
        with jobs.db:
            jobs.db.executemany('INSERT INTO job_events(job_id,created,stage,message) VALUES(?,?,?,?)',
                                (('selected', n, 'running', '中间记录') for n in range(600)))
        connect = sqlite3.connect
        cancelled = Event()
        for job, query in ((None, 'FROM jobs'), ('selected', 'FROM job_events')):
            cancelled.clear()

            def cancel_in_query(*args, **kwargs):
                connection = connect(*args, **kwargs)
                connection.set_trace_callback(lambda sql: cancelled.set() if query in sql else None)
                return connection

            with patch('src.services.qt_log_history.sqlite3.connect', side_effect=cancel_in_query):
                with self.assertRaisesRegex(ValueError, '已取消任务历史读取') as failure:
                    read_log_history(self.project, None, job, HistoryEventFilter(keyword='无匹配'),
                                     closing_event=cancelled)
            if job is not None:
                self.assertIsInstance(failure.exception.__cause__, sqlite3.OperationalError)
                self.assertIn('interrupted', str(failure.exception.__cause__))
        self.assertEqual(read_log_history(self.project, None).entries[0].job_id, 'selected')

    def test_legacy_runs_page_equal_timestamps_without_jobs_or_other_projects(self):
        from src.services.qt_log_history import read_legacy_runs

        ledger = ProjectStatusService()
        project_id = 'a' * 32
        other = 'b' * 32

        def record(index, owner, project, state='succeeded', **changes):
            ledger.records[owner] = dict(project_id=project, owner=owner, run_id=f'{index:032x}',
                operation='_on_start', state=state, created_at=1700000000, updated_at=1700000300,
                revision='12345678', **changes)

        for index in range(JOBS_PER_PAGE + 2):
            record(index, f'gui:{project_id}:{index:032x}', project_id)
        record(510, 'capability-job', project_id)
        record(511, f'gui:{other}:{511:032x}', other)
        record(512, f'gui:{other}:{512:032x}', project_id)
        first = read_legacy_runs(ledger, project_id)
        self.assertEqual([row.run_id for row in first.entries],
                         [f'{n:032x}' for n in range(JOBS_PER_PAGE + 1, 1, -1)])
        self.assertIsNotNone(first.next_cursor)
        record(513, f'gui:{project_id}:{513:032x}', project_id)
        second = read_legacy_runs(ledger, project_id, first.next_cursor)
        self.assertEqual([row.run_id for row in second.entries], [f'{1:032x}', f'{0:032x}'])
        self.assertIsNone(second.next_cursor)
        self.assertEqual([row.run_id for row in read_legacy_runs(ledger, other).entries], [f'{511:032x}'])

    def test_legacy_runs_distinguish_pending_and_reviewed_unknown_without_mutating_ledger(self):
        from copy import deepcopy
        from src.services.qt_log_history import read_legacy_runs

        ledger = ProjectStatusService()
        project_id = 'a' * 32
        for number, (state, reviewed) in enumerate((('prepared', False), ('unknown', False), ('unknown', True))):
            key = f'gui:{project_id}:{number:032x}'
            ledger.records[key] = dict(owner=key, project_id=project_id, run_id=f'{number:032x}', state=state,
                operation='_on_start', reconciled=reviewed, created_at=1700000000 + number,
                updated_at=1700000300, revision='12345678')
        original = deepcopy(ledger.records)
        page = read_legacy_runs(ledger, project_id)
        states = {entry.run_id: entry.state for entry in page.entries}
        self.assertNotEqual(states[f'{0:032x}'], '运行中')
        self.assertNotEqual(states[f'{1:032x}'], states[f'{2:032x}'])
        self.assertIn('已核实', states[f'{2:032x}'])
        self.assertEqual(ledger.records, original)

    def test_missing_database_and_large_or_unstructured_records(self):
        empty = read_log_history(self.project, None)
        self.assertEqual(empty.entries, ())
        self.assertFalse(self.project.root.exists())
        jobs = self.open_jobs(self.project)
        self.insert_job(jobs, 'existing', 1)
        jobs.event('existing', 'history', '{"channel":true}')
        jobs.event('existing', 'failed', 'CH01 ' + '长' * (MAX_MESSAGE_CHARS + 10))
        view = read_log_history(self.project, None, 'existing').entries
        self.assertEqual([row.channel for row in view], [None, None])
        self.assertEqual(view[1].level, 'ERROR')
        self.assertIn('原数据库保留原文', view[1].message)
        self.assertLess(view[1].message.count('长'), MAX_MESSAGE_CHARS + 10)
        with self.assertRaisesRegex(ValueError, '边界无效'):
            read_log_history(self.project, 0, 'existing')

    def test_channel_retry_history_pages_original_rounds_and_filters_before_limiting(self):
        jobs = self.open_jobs(self.project)
        other = self.open_jobs(self.other)
        self.insert_job(jobs, 'chosen', 1)
        self.insert_job(jobs, 'other-batch', 2)
        self.insert_job(other, 'chosen', 1)

        def record(store, job, channel, cycle, status, detail, stage='history'):
            store.event(job, stage, json.dumps(dict(channel=channel, cycle=cycle, status=status, detail=detail)))

        for cycle in range(1, EVENTS_PER_PAGE + 3):
            record(jobs, 'chosen', 7, cycle, 'retry', f'第{cycle}次失败原因')
            record(jobs, 'chosen', 1, cycle, 'failed', '其它通道')
        jobs.event('chosen', 'history', '{invalid json')
        record(jobs, 'chosen', True, 10, 'retry', '无效通道')
        record(jobs, 'chosen', 7, 20, 'failed', '普通进度忽略', stage='aging')
        record(jobs, 'other-batch', 7, 50, 'failed', '其它批次')
        record(other, 'chosen', 7, 30, 'failed', '其它项目')
        database = jobs.directory / 'capability_jobs.sqlite3'
        original = database.read_bytes()
        page = read_channel_history(self.project, 'chosen', 7, None)
        self.assertEqual([row.cycle for row in page.entries], list(range(3, EVENTS_PER_PAGE + 3)))
        self.assertEqual((page.entries[0].status, page.entries[0].detail), ('retry', '第3次失败原因'))
        self.assertEqual(database.read_bytes(), original)
        record(jobs, 'chosen', 7, 70, 'success', '恢复后成功')
        older = read_channel_history(self.project, 'chosen', 7, page.next_cursor)
        self.assertEqual([row.cycle for row in older.entries], [1, 2])
        self.assertIsNone(older.next_cursor)
        self.assertEqual(read_channel_history(self.project, 'chosen', 8, None).entries, ())
        self.assertEqual(read_channel_history(self.other, 'chosen', 7, None).entries[0].detail, '其它项目')
        with self.assertRaisesRegex(ValueError, '不属于'):
            read_channel_history(self.other, 'other-batch', 7, None)

    def test_power_results_revalidate_the_saved_run_and_original_channels(self):
        jobs = self.open_jobs(self.project)
        self.insert_job(jobs, 'original-older', 1)
        self.insert_job(jobs, 'unrelated-newer', 2)
        payload = json.dumps({'arguments': {'channel_ids': [7], 'tasks': ['legacy_power_test']}})
        with jobs.db:
            jobs.db.execute('UPDATE jobs SET payload=?,capability=? WHERE id=?',
                            (payload, 'pipeline.start', 'original-older'))
        run_id = '0' * 32
        root = self.project.root / 'runs' / run_id
        directory = root / 'Auto_power_on_off_tool/test_results/device_7'
        directory.mkdir(parents=True)
        manifest = root / 'run.json'
        record = dict(owner='original-older', project_id='project-a', run_id=run_id, operation='pipeline.start')
        manifest.write_text(json.dumps(record), encoding='utf-8')
        link = dict(record, _path=manifest)
        power = directory / 'device_7_command_results_20261120220100.log'
        wifi = directory / 'device_7_wifi_20261120220100_resume1.log'
        power.write_bytes(b'original-result\r\n')
        wifi.write_bytes(b'original-wifi\r\n')
        (directory / 'device_7_wifi_not_a_log.txt').touch()
        other_channel = directory.with_name('device_1') / 'device_1_wifi_20261120220300.log'
        other_channel.parent.mkdir()
        other_channel.touch()
        wrong_run = self.project.root / 'runs' / ('1' * 32) / directory.relative_to(root) / power.name
        wrong_run.parent.mkdir(parents=True)
        wrong_run.touch()

        entries = history_result_files(self.project, 'original-older', link)
        self.assertEqual({file.path for file in entries}, {power, wifi})
        self.assertTrue(all(file.label.startswith('CH07 · ') for file in entries))
        with patch('src.services.qt_power_logs.os.startfile') as shell_open:
            self.assertEqual(open_history_result_file(self.project, 'original-older', link, wifi), 7)
            for forged in (other_channel, wrong_run):
                with self.assertRaisesRegex(ValueError, '选定批次及通道'):
                    open_history_result_file(self.project, 'original-older', link, forged)
            with self.assertRaisesRegex(ValueError, '历史库'):
                open_history_result_file(self.other, 'original-older', link, power)
            manifest.write_text(json.dumps(dict(record, owner='unrelated-newer')), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '身份不符'):
                open_history_result_file(self.project, 'original-older', link, power)
            shell_open.assert_called_once_with(str(wifi))
        self.assertEqual(power.read_bytes(), b'original-result\r\n')
        self.assertEqual(wifi.read_bytes(), b'original-wifi\r\n')

        with jobs.db:
            jobs.db.execute('UPDATE jobs SET payload=? WHERE id=?',
                (json.dumps({'arguments': {'channel_ids': [7], 'tasks': ['env_check']}}), 'original-older'))
        with self.assertRaisesRegex(ValueError, '开关机子任务'):
            history_result_files(self.project, 'original-older', link)
