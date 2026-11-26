"""Replay original power-engine events in a private project, without hardware."""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.models.capabilities import CapabilityError
from src.services.power_run_overview import PowerRunOverview, matching_power_overview, power_attention_records
from src.models.workbench_presentation import ChannelView, ProjectView
from src.services.project_power_plan import check_project_power_plan
from src.services.project_profile_store import read_project_profile, write_project_profile
from src.services.project_status_service import ProjectStatusService
from src.services.project_store import ProjectStore
from src.services.qt_log_history import job_database_path


class PowerRunOverviewTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = ProjectStore(Path(__file__).resolve().parents[1])
        self.addCleanup(lambda: [self.store.close(c) for c in list(self.store.opened.values())])
        self.context = self.store.create(Path(temp.name) / 'project', '项目', profile={
            'test_type': 'power_cycle', 'type_config': {'target_cycles': 3},
            'duts': [dict(label=f'DUT {n}', hardware_id=f'LAB-{n}', channel=n, serial_port=f'COM{n}', vlan=f'vlan{100+n}',
                          network_adapter=f'vlan{100+n}', power_channel=f'CH{n:02d}') for n in (1, 2)]})
        self.profile = read_project_profile(self.context.config_dir)
        self.ledger = ProjectStatusService(lambda line: None)
        database = job_database_path(self.context)
        database.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(database)
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE jobs(id TEXT PRIMARY KEY, capability TEXT, payload TEXT, state TEXT, stage TEXT, updated REAL, result TEXT);
            CREATE TABLE job_events(id INTEGER PRIMARY KEY, job_id TEXT, created REAL, stage TEXT, message TEXT);
        """)

    def create_job(self, job='power', operation='pipeline.start', tasks=('env_check', 'legacy_power_test'),
                   channels=(1,), state='failed'):
        root = self.store.snapshot(self.context)
        self.ledger.begin(self.context, job, root, operation)
        self.ledger.update(job, state)
        with self.db:
            self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)', (job, operation,
                json.dumps({'arguments': {'tasks': tasks, 'channel_ids': channels}}), state, state, 40, 'null'))
        return self.ledger.records[job]

    def event(self, at, stage='aging', *, job='power', channel=1, **fields):
        with self.db:
            self.db.execute('INSERT INTO job_events(job_id,created,stage,message) VALUES(?,?,?,?)',
                            (job, at, stage, json.dumps(dict(fields, channel=channel))))

    def attention_project(self, record, overview=None, **changes):
        card = ProjectView(self.context.identity.project_id, '项目', '挂测', '—', 'failed',
                           '失败', '—', '', None, '', 1, run_id=record['run_id'],
                           project_type='power_cycle', channels=(ChannelView(1, 'unknown'),),
                           test_overview=overview)
        return replace(card, **changes)

    def test_task_attention_reads_exact_failure_receipt_and_events_without_channel_failure(self):
        record = self.create_job()
        other = self.create_job('other')
        with self.db:
            self.db.execute('UPDATE jobs SET result=? WHERE id=?',
                            (json.dumps({'error': '子任务 legacy_power_test 失败:电源初始化失败'}), 'power'))
            self.db.execute('UPDATE jobs SET result=? WHERE id=?',
                            (json.dumps({'error': '其他任务的错误'}), 'other'))
            self.db.execute('INSERT INTO job_events(job_id,created,stage,message) VALUES(?,?,?,?)',
                            ('power', 32, 'pipeline', '实际初始化回执：串口打开失败'))
            self.db.execute('INSERT INTO job_events(job_id,created,stage,message) VALUES(?,?,?,?)',
                            ('other', 33, 'pipeline', '其他任务事件'))
        current = self.attention_project(record)
        before = self.db.execute('SELECT * FROM jobs').fetchall()
        entry, = power_attention_records(current, self.context, record)
        self.assertEqual(entry.label, '任务')
        self.assertIn('电源初始化失败', entry.reason)
        self.assertIn('执行开关机测试', entry.stage)
        self.assertIn('串口打开失败', entry.related_events[0])
        self.assertTrue(entry.time)
        self.assertEqual(before, self.db.execute('SELECT * FROM jobs').fetchall())
        wrong, = power_attention_records(current, self.context, other)
        self.assertNotIn('其他任务', wrong.reason)
        self.assertFalse(wrong.related_events)
        self.assertEqual(power_attention_records(replace(current, state='running'), self.context, record), ())
        with self.db:
            self.db.execute('UPDATE jobs SET result=? WHERE id=?', (json.dumps({'items': [
                {'code': 'env_check', 'ok': False, 'detail': '模拟线路检查失败'},
                {'code': 'serial_terminal', 'ok': True}]}), 'power'))
        failed_subtask, = power_attention_records(current, self.context, record)
        self.assertIn('模拟线路检查失败', failed_subtask.reason)
        self.assertIn('环境线路检查', failed_subtask.event)

    def test_current_channel_failure_and_recovery_are_independent_of_historical_count(self):
        record = self.create_job()
        with self.db:
            self.db.execute('UPDATE jobs SET result=? WHERE id=?',
                (json.dumps({'error': '子任务 legacy_power_test 失败:失败通道：[1]'}), 'power'))
        view = PowerRunOverview()
        self.event(10, completed=0, stage='aging', detail='第1轮执行中')
        self.event(11, stage='history', cycle=1, status='failed', detail='PON 注册超时')
        self.event(12, status='failed', detail='测试失败，详细信息请查看执行日志')
        def current():
            overview = view.snapshot(self.context, record, self.profile)
            return power_attention_records(self.attention_project(record, overview), self.context, record)
        entry, = current()
        self.assertEqual((entry.channel, entry.cycle, entry.reason), (1, 1, 'PON 注册超时'))
        self.assertTrue(entry.time)
        self.assertIn('PON 注册超时', '\n'.join(entry.related_events))
        self.event(13, stage='history', cycle=1, status='resume', detail='续跑开始')
        self.event(14, status='running', detail='第1轮执行中')
        resume = self.create_job('resume', operation='aging.resume', state='running')
        active = self.attention_project(record, view.snapshot(self.context, record, self.profile),
            run_id=resume['owner'], power_history_job=record['owner'], resume_detail='CH01 · 续跑中',
            channels=(ChannelView(1, 'failed', detail='旧失败'),))
        self.assertEqual(power_attention_records(active, self.context, resume), ())
        long_reason = 'WiFi 验证失败：' + '原始错误细节' * 1600
        self.event(15, stage='history', cycle=1, status='failed', detail=long_reason)
        self.assertEqual(power_attention_records(replace(active,
            test_overview=view.snapshot(self.context, record, self.profile)), self.context, resume), ())
        self.event(15.5, status='failed', detail='测试失败，详细信息请查看执行日志')
        entry, = current()
        self.assertEqual(entry.reason, long_reason)
        self.event(16, stage='history', cycle=1, status='resume', detail='再次续跑')
        self.event(17, status='success', detail='所有测试项验证成功')
        self.assertEqual(current(), ())
        self.assertEqual(view.snapshot(self.context, record, self.profile)['rows'][0]['failure'], 1)

    def test_missing_or_invalid_task_receipt_keeps_an_explicit_unknown_reason(self):
        record = self.create_job()
        current = self.attention_project(record)
        with self.db:
            self.db.execute('UPDATE jobs SET result=? WHERE id=?', ('invalid json', 'power'))
        entry, = power_attention_records(current, self.context, record)
        self.assertIn('无法读取', entry.reason)
        self.assertFalse(entry.reason_recorded)
        with self.db:
            self.db.execute('UPDATE jobs SET result=? WHERE id=?', (json.dumps({'error': '已保留失败回执'}), 'power'))
            self.db.execute('DROP TABLE job_events')
        entry, = power_attention_records(current, self.context, record)
        self.assertEqual(entry.reason, '已保留失败回执')
        self.assertIn('暂无法读取', entry.related_events[0])
        with self.db:
            self.db.execute('DELETE FROM jobs WHERE id=?', ('power',))
        entry, = power_attention_records(current, self.context, record)
        self.assertIn('未找到匹配', entry.reason)

    def test_terminal_project_card_recovers_only_the_selected_batch_receipts_and_duration(self):
        from src.models.workbench_presentation import ProjectView
        from src.services.qt_workspace_adapter import QtWorkspaceAdapter
        adapter = SimpleNamespace(_power_overviews={})
        card = ProjectView(self.context.identity.project_id, '项目', '挂测', '—', 'failed',
                           '失败', '—', '尚无实时轮次数据', None, '', 0)
        record = self.create_job(channels=(1, 2))
        record.update(started_at=10, finished_at=3671)
        show = lambda latest: QtWorkspaceAdapter._typed_project(adapter, card, self.context, [record], latest)
        self.event(12, completed=2)
        first = show(record)
        self.assertEqual((first.progress, first.elapsed), (None, '01:01:01'))
        self.event(15, channel=2, completed=1)
        restored = show(record)
        self.assertEqual(restored.progress, 33)
        self.assertIn('1 / 3', restored.progress_text)
        self.assertIsNone(show(dict(owner='another')).progress)
        for run_id in (record['owner'], record['run_id']):
            with self.subTest(run_id=run_id):
                self.assertIs(matching_power_overview(replace(restored, run_id=run_id)), restored.test_overview)
        other = replace(restored, run_id='another', power_history_job=record['owner'])
        self.assertFalse(matching_power_overview(other))
        resumed = replace(other, resume_detail='CH01 · 续跑中')
        self.assertIs(matching_power_overview(resumed), restored.test_overview)
        record.pop('started_at')
        self.assertEqual(show(record).elapsed, '—')

    def test_reopen_recovers_latest_power_pipeline_from_original_request_and_run_archive(self):
        direct = self.create_job('direct', 'aging.start', tasks=(), channels=(2,))
        power = self.create_job()
        other = self.create_job('other', tasks=('env_check', 'sample_upgrade'))
        service = self.create_job('service', 'service_aging.start', tasks=())
        self.create_job('invalid', channels=(True,))
        self.event(1, job='other', completed=75)
        self.event(2, channel=2, completed=95)
        self.event(3, channel=True, completed=90)
        self.event(4, completed=2, stage='aging', detail='第2轮完成')
        new_profile = dict(self.profile, type_config={'target_cycles': 77},
                           duts=[dict(dut, label='新标签') for dut in self.profile['duts']])
        write_project_profile(self.context.config_dir, new_profile)
        self.store.save(self.context)
        location = self.context.root
        self.store.close(self.context)
        self.context = self.store.open(location)
        reopened = ProjectStatusService(lambda line: None)
        reopened.attach(self.context)
        view = PowerRunOverview()
        foreign = dict(power, project_id='another-project')
        records = [foreign] + [reopened.records[k] for k in ('invalid', 'other', 'service', 'power', 'direct')]
        chosen = view.latest_record(self.context, records)
        self.assertEqual(chosen['owner'], 'power')
        data = view.snapshot(self.context, chosen, new_profile)
        self.assertEqual((data['target'], data['job_id']), (3, 'power'))
        self.assertEqual([(r['channel'], r['label'], r['dut_id'], r['completed']) for r in data['rows']],
                         [(1, 'DUT 1', self.profile['duts'][0]['dut_id'], 2)])
        self.assertIsNone(data['rows'][0]['duration'])
        self.assertEqual(view.latest_record(self.context, [other, service, foreign]), {})
        self.assertEqual(view.latest_record(self.context, [direct])['owner'], 'direct')

    def test_completed_failed_attempt_and_later_resume_use_their_own_evidence(self):
        record = self.create_job()
        view = PowerRunOverview()
        def current():
            return view.snapshot(self.context, record, self.profile)['rows'][0]
        self.assertIsNone(current()['completed'])
        self.event(10, detail='第1轮执行中')
        self.event(11, status='retry', detail='连接失败准备重试')
        self.event(11, 'history', cycle=1, status='retry')
        self.event(12, 'history', cycle=1, status='retry')
        self.event(15, 'history', cycle=1, status='failed', detail='PON 注册超时')
        self.event(16, 'history', cycle=1, status='failed', detail='重复回执')
        row = current()
        self.assertEqual((row['failure'], row['success'], row['retries'], row['duration']), (1, 0, 2, 5.0))
        self.event(25, 'history', cycle=1, status='resume')
        self.assertIsNone(current()['duration'])
        self.event(28, detail='第1轮执行中')
        self.event(29, status='running', detail='第1轮执行中')
        self.event(35, status='success', detail='第1轮测试正常')
        self.event(36, completed=1, detail='第1轮完成')
        row = current()
        self.assertEqual((row['cycle'], row['completed'], row['duration']), (1, 1, 7.0))
        self.assertEqual((row['success'], row['failure'], row['retries']), (1, 1, 2))
        self.assertEqual((row['last_failure'], row['failure_reason']), (1, 'PON 注册超时'))
        self.assertEqual(current(), row)
        self.assertEqual(PowerRunOverview().snapshot(self.context, record, self.profile)['rows'][0], row)

    def test_bounded_replay_keeps_cursor_and_never_uses_current_profile_for_missing_archive(self):
        record = self.create_job(state='succeeded')
        with self.db:
            self.db.executemany('INSERT INTO job_events(job_id,created,stage,message) VALUES(?,?,?,?)',
                                [('power', 1, 'pipeline', '日志')] * 512)
        self.event(10, detail='第2轮测试正常', completed=2)
        view = PowerRunOverview()
        self.assertIsNone(view.snapshot(self.context, record, self.profile)['rows'][0]['completed'])
        self.assertEqual(view.snapshot(self.context, record, self.profile)['rows'][0]['success'], 1)
        self.assertIsNone(view.snapshot(self.context, record, self.profile)['rows'][0]['duration'])
        for invalid in (dict(record, run_id='../foreign'), dict(record, _path=self.context.root / 'run.json')):
            with self.subTest(invalid=invalid):
                self.assertEqual(PowerRunOverview().snapshot(self.context, invalid, self.profile), {})
        blank = PowerRunOverview().snapshot(self.context, {}, self.profile)
        self.assertEqual([r['channel'] for r in blank['rows']], [1, 2])
        self.assertTrue(all(r['success'] is None for r in blank['rows']))

    def test_typed_plan_requires_exact_enabled_channels_goal_and_frozen_configuration(self):
        channels = [SimpleNamespace(section=f'channel_{n:02d}', enabled=True, vlan_name=f'vlan{100+n}',
                    adapter_alias=f'vlan{100+n} [DUT]', serial_port='', network_card_ip=f'192.0.2.{n}')
                    for n in (1, 2)]
        archive = self.store.snapshot(self.context)
        with patch('src.services.project_preparation.preparation_for') as preparation:
            check_project_power_plan(self.context, channels, cycles=3, config_root=archive)
            preparation.assert_not_called()
            for selection, cycles, message in ((channels[:1], 3, '目标通道'), (channels + channels[:1], 3, '重复'),
                                              (channels, 4, '计划'), (channels, True, '计划')):
                with self.subTest(message=message), self.assertRaisesRegex(CapabilityError, message):
                    check_project_power_plan(self.context, selection, cycles=cycles)
            channels[1].enabled = False
            with self.assertRaisesRegex(CapabilityError, '未启用'):
                check_project_power_plan(self.context, channels, cycles=3)
            channels[1].enabled = True
            channels[1].serial_port = 'COM37'
            with self.assertRaisesRegex(CapabilityError, '资源映射'):
                check_project_power_plan(self.context, channels, cycles=3)
            changed = dict(self.profile, type_config={'target_cycles': 4})
            write_project_profile(self.context.config_dir, changed)
            with self.assertRaisesRegex(CapabilityError, '先保存'):
                check_project_power_plan(self.context, channels, cycles=4)
            self.store.save(self.context)
            with self.assertRaisesRegex(CapabilityError, '运行快照'):
                check_project_power_plan(self.context, channels, cycles=4, config_root=archive)
