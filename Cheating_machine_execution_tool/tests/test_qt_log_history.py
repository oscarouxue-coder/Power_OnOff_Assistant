from pathlib import Path
import json
import sqlite3
from threading import Event
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.models.project import ProjectContext, ProjectIdentity
from src.models.qt_log_history import HistoryEventFilter
from src.services.capability_jobs import CapabilityJobs
from src.services.qt_log_history import EVENTS_PER_PAGE, JOBS_PER_PAGE, MAX_MESSAGE_CHARS, read_channel_history, read_log_history
from src.services.qt_power_logs import history_result_files, open_history_result_file
from src.services.project_status_service import ProjectStatusService


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
