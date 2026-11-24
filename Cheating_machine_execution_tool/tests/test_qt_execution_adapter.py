"""Original jobs/resources/config snapshots, with only physical engines replaced."""
from dataclasses import asdict, replace
from functools import partial
import json
from pathlib import Path
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch

from qt_execution_fakes import (
    ControlledPipeline, ControlledResumePipeline, configure_project, install_native_fixture_locks,
    mock_power_interfaces, save_push_project_name,
)
from test_power_supply import FakeSerial
from src.core.power_supply import channel_power_frame
from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.models.workbench_presentation import ChannelView, ProjectView
from src.services.qt_execution_adapter import QtExecutionAdapter
from src.services.qt_single_power import CAPABILITY as SINGLE_POWER, SinglePowerTarget
from src.services.qt_workspace_adapter import QtWorkspaceAdapter
from src.services.workspace_service import WorkspaceService


SOURCE = Path(__file__).resolve().parents[1]


class QtExecutionAdapterTests(unittest.TestCase):
    def setUp(self):
        install_native_fixture_locks(self)
        self.temporary = tempfile.TemporaryDirectory(prefix='qt-execution-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = WorkspaceService(SOURCE, directory=self.root / 'workspace')
        self.context = self.workspace.projects.create(self.root / 'project', '模拟上下电')
        self.workspace.status.attach(self.context)
        self.identities = configure_project(self.workspace, self.context)
        self.events = []
        self.adapter = QtExecutionAdapter(self.workspace, self.context, self.events.append)
        self.engine = ControlledPipeline()
        self.addCleanup(self.cleanup_runtime)
        self.nic = patch('src.core.network_adapter.read_adapter_identities', return_value=self.identities)
        self.nic.start()
        self.addCleanup(self.nic.stop)
        self.pipeline = patch('src.services.capability_device_services.PipelineOrchestrator', self.engine.factory)
        self.pipeline.start()
        self.addCleanup(self.pipeline.stop)
        serial = patch('serial.Serial', side_effect=AssertionError('physical serial forbidden'))
        serial.start()
        self.addCleanup(serial.stop)

    def cleanup_runtime(self):
        self.engine.finish.set()
        self.engine.release_stop.set()
        self.adapter.begin_close()
        self.wait_for(lambda: self.adapter.ready_to_close)
        self.adapter.close()
        for context in tuple(self.workspace.projects.opened.values()):
            self.workspace.projects.close(context)
        self.workspace.close()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.01)
        self.fail('expected controlled job state not observed')

    def start(self, operation='aging.start'):
        confirmation = self.adapter.prepare(operation)
        identifier = self.adapter.confirm(confirmation.token)
        self.assertTrue(self.engine.started.wait(3))
        return identifier

    def save_enabled_channels(self, numbers):
        from line_check_assistant.config_store import ChannelConfigStore
        store = ChannelConfigStore(self.context.config_dir / 'network_card_ip.ini')
        rows = [replace(c, enabled=int(c.section.split('_')[1]) in numbers) for c in store.load()]
        store.save(rows, store.load_power_serial_port())
        self.workspace.projects.save(self.context)

    def save_target_profile(self, kind='power_cycle'):
        from src.services.project_profile_store import write_project_profile
        plan = {'target_cycles': 100} if kind == 'power_cycle' else {'collectors': ['voice'], 'target_hours': 1}
        self.profile = write_project_profile(self.context.config_dir, dict(test_type=kind, type_config=plan,
            duts=[dict(label=f'DUT {n}', hardware_id=f'LAB-{n}', channel=n) for n in (1, 7)]))
        self.workspace.projects.save(self.context)

    def record_target_steps(self, channel, *, stop_before_verify=''):
        from src.services.project_preparation import preparation_for
        service = self.preparation = preparation_for(self.context)
        def target_steps():
            return next(d for d in service.snapshot()['duts'] if d['channel'] == channel)['steps']
        dut = next(d['dut_id'] for d in self.profile['duts'] if d['channel'] == channel)
        def read_step(key):
            return next(step for step in target_steps() if step['id'] == key)
        for step in target_steps():
            current = read_step(step['id'])
            if current['state'] == 'verified':
                continue
            if current['state'] != 'executed':
                service.record_manual(dut, step['id'], current['token'], '模拟执行依据', 'fixture')
            if step['id'] == stop_before_verify:
                return
            current = read_step(step['id'])
            service.verify(dut, step['id'], current['token'], current['attempt'], True, '模拟独立回读', 'fixture')

    def test_enabled_power_targets_match_confirmation_archive_and_engine(self):
        from line_check_assistant.config_store import ChannelConfigStore
        self.save_target_profile()
        self.save_enabled_channels({1})
        self.assertFalse((self.context.history / 'preparation.sqlite3').exists())
        preview = self.adapter.prepare('aging.start')
        self.assertEqual(preview.channel_ids, (1,))
        self.assertIn('CH01', preview.summary)
        self.assertNotIn('CH07', preview.summary)
        identifier = self.adapter.confirm(preview.token)
        self.assertTrue(self.engine.started.wait(3))
        context, _ = self.engine.calls[0]
        self.assertEqual([c.section for c in context.enabled_channels], ['channel_1'])
        store = ChannelConfigStore(context.legacy_tool_root / 'config/network_card_ip.ini')
        self.assertEqual([c.section for c in store.load() if c.enabled], ['channel_1'])
        status = self.adapter.capabilities.jobs.status(identifier, self.adapter.jobs[identifier]['authority'])
        self.assertEqual(status['request']['arguments']['channel_ids'], [1])
        self.assertIn('dut:hardware:lab-1', status['request']['resources'])
        self.assertNotIn('dut:hardware:lab-7', status['request']['resources'])

        self.engine.finish.set()
        self.wait_for(lambda: self.adapter.idle)
        self.save_enabled_channels({1, 7})
        self.record_target_steps(7)
        preview = self.adapter.prepare('aging.start')
        self.assertEqual(preview.channel_ids, (1, 7))
        identifier = self.adapter.confirm(preview.token)
        self.wait_for(lambda: self.adapter.idle)
        second, _ = self.engine.calls[1]
        self.assertEqual([c.section for c in second.enabled_channels], ['channel_1', 'channel_7'])
        status = self.adapter.capabilities.jobs.status(identifier, self.adapter.jobs[identifier]['authority'])
        self.assertEqual(status['request']['arguments']['channel_ids'], [1, 7])
        self.assertIn('dut:hardware:lab-7', status['request']['resources'])

    def test_enabled_power_targets_ignore_old_steps_and_reject_changed_confirmation(self):
        self.save_target_profile()
        self.save_enabled_channels(set())
        with self.assertRaisesRegex(CapabilityError, '未选择测试通道'):
            self.adapter.prepare('aging.start')
        self.save_enabled_channels({1})
        self.record_target_steps(1, stop_before_verify='firmware')
        preview = self.adapter.prepare('aging.start')
        self.save_enabled_channels({1, 7})
        with self.assertRaisesRegex(CapabilityError, '重新确认'):
            self.adapter.confirm(preview.token)
        self.assertEqual(self.adapter.prepare('aging.start').channel_ids, (1, 7))
        self.record_target_steps(1)
        self.preparation.invalidate(self.profile['duts'][0]['dut_id'], 'telnet', '模拟变更', 'fixture')
        self.assertEqual(self.adapter.prepare('aging.start').channel_ids, (1, 7))
        self.assertFalse(self.engine.calls)

    def test_typed_selection_rejects_missing_duplicate_identity_draft_and_wrong_cycle(self):
        from src.services.project_profile_store import write_project_profile
        self.save_target_profile()
        self.save_enabled_channels({1})
        original = self.profile['duts']
        wrong = dict(self.profile, duts=original[1:])
        write_project_profile(self.context.config_dir, wrong)
        with self.assertRaisesRegex(CapabilityError, '先保存项目配置'):
            self.adapter.prepare('aging.start')
        self.workspace.projects.save(self.context)
        with self.assertRaisesRegex(CapabilityError, 'CH01.*未映射'):
            self.adapter.prepare('aging.start')
        with self.assertRaisesRegex(ValueError, '重复'):
            write_project_profile(self.context.config_dir, dict(self.profile, duts=[original[0], dict(original[1], channel=1)]))
        duplicate = dict(self.profile, duts=[original[0], dict(original[1], hardware_id=original[0]['hardware_id'].lower())])
        write_project_profile(self.context.config_dir, duplicate)
        self.workspace.projects.save(self.context)
        with self.assertRaisesRegex(CapabilityError, 'CH01.*实物标识.*重复'):
            self.adapter.prepare('aging.start')
        wrong = dict(self.profile, duts=[dict(original[0], hardware_id=''), original[1]])
        write_project_profile(self.context.config_dir, wrong)
        self.workspace.projects.save(self.context)
        with self.assertRaisesRegex(CapabilityError, 'CH01.*实物标识'):
            self.adapter.prepare('aging.start')
        write_project_profile(self.context.config_dir, dict(self.profile, type_config={'target_cycles': 4}))
        self.workspace.projects.save(self.context)
        self.record_target_steps(1)
        with self.assertRaisesRegex(CapabilityError, '计划 4 轮与执行配置 100 轮'):
            self.adapter.prepare('aging.start')
        self.assertFalse(self.engine.calls)

    def test_saved_remap_invalidates_confirmation_and_keeps_physical_mapping_guards(self):
        from src.services.project_profile_store import write_project_profile
        self.save_target_profile()
        self.save_enabled_channels({1})
        self.record_target_steps(1)
        preview = self.adapter.prepare('aging.start')
        first, second = self.profile['duts']
        for changes, expected in (({'serial_port': 'COM99'}, '资源映射'),
                                  ({'network_adapter': 'fixture-other'}, '资源映射'),
                                  ({'vlan': 'VLAN111'}, '资源映射'),
                                  ({'power_channel': 'CH07'}, '供电')):
            with self.subTest(changes=changes):
                write_project_profile(self.context.config_dir,
                    dict(self.profile, duts=[dict(first, **changes), second]))
                self.workspace.projects.save(self.context)
                self.record_target_steps(1)
                with self.assertRaisesRegex(CapabilityError, 'CH01.*' + expected):
                    self.adapter.prepare('aging.start')
        with self.assertRaisesRegex(CapabilityError, '重新确认'):
            self.adapter.confirm(preview.token)
        self.assertFalse(self.engine.calls)

    def test_subset_permission_is_local_and_confirmed_run_rechecks_its_archive(self):
        from line_check_assistant.config_store import ChannelConfigStore
        from src.services.project_store import ProjectStore
        self.save_target_profile()
        self.save_enabled_channels({1})
        self.record_target_steps(1)
        self.adapter._ensure_runtime()
        with self.assertRaisesRegex(CapabilityError, '目标通道'):
            self.adapter.capabilities.execute('aging.start', {'channel_ids': [1]},
                CapabilityAuthority('fixture', 'fixture', 'model-op', (1,), mode='full_access', grant_id='fixture'))
        with self.assertRaisesRegex(CapabilityError, '目标通道'):
            self.adapter.prepare('pipeline.start', ['legacy_power_test'])
        preview = self.adapter.prepare('aging.start')
        original = ProjectStore.snapshot
        def change_archive(store, project):
            root = original(store, project)
            saved = ChannelConfigStore(root / 'Auto_power_on_off_tool/config/network_card_ip.ini')
            saved.save([replace(c, enabled=True) for c in saved.load()], saved.load_power_serial_port())
            return root
        with patch.object(ProjectStore, 'snapshot', change_archive):
            identifier = self.adapter.confirm(preview.token)
            self.wait_for(lambda: self.adapter.jobs_idle)
        result = self.adapter.capabilities.jobs.status(identifier, self.adapter.jobs[identifier]['authority'])
        self.assertEqual(result['state'], 'failed')
        self.assertFalse(result['result']['dispatched'])
        self.assertIn('启用通道', result['result']['error'])
        self.assertFalse(self.engine.calls)

    def test_typed_subset_retry_reuses_only_the_original_failed_target(self):
        self.save_target_profile()
        self.save_enabled_channels({7})
        self.record_target_steps(7)
        harness, _ = self.resume_pipeline()
        harness.finish.set()
        self.wait_for(lambda: self.adapter.idle)
        with self.assertRaises(CapabilityError):
            self.adapter.prepare('aging.resume', (1,))
        self.adapter.confirm(self.adapter.prepare('aging.resume', (7,)).token)
        self.assertTrue(harness.recovering.wait(3))
        self.assertEqual([c.number for c in harness.recovery_calls[0][0].channels], [7])

    def test_aging_uses_all_legacy_profile_duts_without_preparation(self):
        self.save_target_profile('service_aging')
        self.save_enabled_channels({1})
        self.record_target_steps(1)
        self.record_target_steps(7, stop_before_verify='wifi')
        preview = self.adapter.prepare('service_aging.start')
        self.assertEqual(preview.channel_ids, (1, 7))
        self.assertIn('DUT 7', preview.summary)
        self.assertFalse(self.engine.calls)

    def test_confirmation_is_one_use_and_original_jobs_own_execution(self):
        confirmation = self.adapter.prepare('aging.start')
        self.assertEqual(confirmation.channel_ids, (1, 7))
        self.assertIn('COM102', confirmation.summary)
        self.assertIsNone(self.adapter.capabilities)
        identifier = self.adapter.confirm(confirmation.token)
        self.assertTrue(self.engine.started.wait(3))
        with self.assertRaisesRegex(CapabilityError, '确认已失效'):
            self.adapter.confirm(confirmation.token)
        self.assertEqual(len(self.engine.calls), 1)
        context, tasks = self.engine.calls[0]
        self.assertEqual(tasks, frozenset({'legacy_power_test'}))
        self.assertEqual([c.section for c in context.channels], ['channel_1', 'channel_7'])
        self.assertNotEqual(context.legacy_tool_root.parent, self.context.working_root)
        self.assertTrue(str(context.legacy_tool_root).startswith(str(self.context.root / 'runs')))
        self.assertEqual((context.legacy_tool_root / 'config/config.ini').read_bytes(),
                         (self.context.config_dir / 'config.ini').read_bytes())
        self.assertIn(identifier, self.adapter.capabilities.jobs.controls)
        self.assertTrue(self.workspace.resources.owners)

    def test_power_log_open_uses_current_run_or_original_draft_root(self):
        draft = self.context.working_root / 'Auto_power_on_off_tool/test_results/device_7'
        draft.mkdir(parents=True, exist_ok=True)
        draft_power = draft / 'device_7_command_results_20261118090000.log'
        draft_power.write_bytes(b'original project result\r\n')
        (draft / 'device_7_wifi_20261118090000.log').touch()
        with patch('src.services.qt_power_logs.os.startfile') as shell_open:
            self.adapter.open_power_log(7, 'power')
            shell_open.assert_called_once_with(str(draft_power))
            with self.assertRaisesRegex(ValueError, '暂无本次 WiFi 日志'):
                self.adapter.open_power_log(7, 'wifi')
            with self.assertRaisesRegex(ValueError, '有效'):
                self.adapter.open_power_log(17, 'power')

            owner = self.start()
            self.assertEqual(owner, self.adapter.power_log_job)
            execution, _ = self.engine.calls[0]
            results = execution.legacy_tool_root / 'test_results/device_7'
            results.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, '暂无开关机运行日志'):
                self.adapter.open_power_log(7, 'power')
            new = results / 'device_7_command_results_20261120110000.log'
            new.write_bytes(b'current run result\n')
            (results / 'device_7_command_results_20261120100000.log').touch()
            (results / 'device_1_command_results_20261120120000.log').touch()
            self.adapter.open_power_log(7, 'power')
            self.assertEqual([call.args[0] for call in shell_open.call_args_list], [str(draft_power), str(new)])
            shell_open.side_effect = OSError('synthetic association unavailable')
            with self.assertRaisesRegex(ValueError, 'Windows 无法打开'):
                self.adapter.open_power_log(7, 'power')
        self.assertEqual(draft_power.read_bytes(), b'original project result\r\n')
        self.assertEqual(new.read_bytes(), b'current run result\n')
        self.assertEqual(self.events[-1].level, 'WARN')
        self.assertEqual((self.events[-1].run_id, self.events[-1].channel), (owner, 7))

    def test_config_changes_or_expiration_prevent_dispatch(self):
        for field in ('draft', 'saved', 'expiration'):
            with self.subTest(field=field):
                confirmation = self.adapter.prepare('aging.start')
                if field == 'expiration':
                    item, binding, _, parameters = self.adapter.pending
                    self.adapter.pending = (item, binding, time.monotonic() - 121, parameters)
                    with self.assertRaises(CapabilityError):
                        self.adapter.confirm(confirmation.token)
                else:
                    config = (self.context.config_dir if field == 'draft' else
                        self.context.saved_root / 'Auto_power_on_off_tool/config') / 'test_project_config.ini'
                    original = config.read_bytes()
                    config.write_bytes(original + b'\n# changed during confirmation\n')
                    with self.assertRaises(CapabilityError):
                        self.adapter.confirm(confirmation.token)
                    config.write_bytes(original)
                self.assertFalse(self.engine.calls)

    def test_unverified_nic_never_admits_a_job(self):
        confirmation = self.adapter.prepare('aging.start')
        with patch('src.core.network_adapter.read_adapter_identities', return_value=()):
            with self.assertRaisesRegex(CapabilityError, '目标网卡身份'):
                self.adapter.confirm(confirmation.token)
        self.assertIsNone(self.adapter.capabilities)
        self.assertFalse(self.workspace.resources.owners)

    def test_environment_check_uses_original_registered_operation(self):
        identifier = self.start('network.line_check')
        self.assertEqual(self.engine.calls[0][1], frozenset({'env_check'}))
        self.engine.finish.set()
        self.wait_for(lambda: self.adapter.idle)
        self.adapter.poll()
        self.assertEqual(self.adapter.jobs[identifier]['status']['state'], 'succeeded')

    def test_continuous_monitor_confirm_stop_and_history_use_the_selected_project_job(self):
        from src.services.project_profile_store import write_project_profile
        write_project_profile(self.context.config_dir, {
            'test_type': 'service_aging', 'type_config': {'target_hours': 168, 'collectors': ['voice']},
            'duts': [{'label': '语音样机', 'hardware_id': 'LAB-A', 'channel': 1}],
        })
        self.workspace.projects.save(self.context)
        self.assertFalse((self.context.history / 'preparation.sqlite3').exists())
        with self.assertRaisesRegex(CapabilityError, '持续供电'):
            self.adapter.prepare('aging.start')
        monitor = self.adapter.aging_monitor()
        preview = self.adapter.prepare('service_aging.start')
        self.assertIn('语音样机', preview.summary)
        changed = dict(monitor.service.prepare(), binding='changed')
        with patch.object(monitor.service, 'prepare', return_value=changed):
            with self.assertRaisesRegex(CapabilityError, '重新确认'):
                self.adapter.confirm(preview.token)
        self.assertFalse(self.workspace.resources.owners)
        preview = self.adapter.prepare('service_aging.start')
        identifier = self.adapter.confirm(preview.token)
        self.addCleanup(lambda: self.adapter.stop(identifier) if not self.adapter.jobs_idle else None)
        self.wait_for(lambda: monitor.service.snapshot().get('state') == 'running')
        view = monitor.service.snapshot()
        self.assertEqual(view['job_id'], identifier)
        row = next(row for row in view['rows'] if row['collector'] == 'voice')
        monitor.record(dict(job_id=identifier, dut_id=row['dut_id'], collector='voice', kind='daily',
                            outcome='healthy', evidence='模拟日检收据'))
        from src.services.workspace_event_log import associate_run
        daily = next(event for event in self.events if event.dut_id == row['dut_id'] and event.step == 'voice')
        archived = associate_run(daily, self.workspace.status.records)
        self.assertEqual((archived.job_id, archived.channel, archived.batch_id),
                         (identifier, 1, self.workspace.status.records[identifier]['run_id']))
        self.assertNotEqual(archived.job_id, archived.batch_id)
        self.adapter.stop(identifier)
        self.wait_for(lambda: self.adapter.jobs_idle)
        self.adapter.poll()
        self.assertEqual(monitor.service.snapshot()['state'], 'stopped')
        self.assertEqual(monitor.service.history_page(identifier, kind='daily')['rows'][0]['evidence'], '模拟日检收据')
        self.assertFalse(self.engine.calls)
        self.assertFalse(self.workspace.resources.owners)

    def test_field_collector_uses_the_confirmed_job_manifest_and_deduplicates_reports(self):
        from datetime import datetime, timezone
        from src.services.project_profile_store import write_project_profile
        write_project_profile(self.context.config_dir, {
            'test_type': 'service_aging',
            'type_config': {'collectors': ['iptv', 'voice'], 'feed_collectors': ['iptv']},
            'duts': [{'label': 'DUT A', 'hardware_id': 'rack-a'}],
        })
        self.workspace.projects.save(self.context)
        monitor = self.adapter.aging_monitor()
        monitor.service.interval = .25
        confirmation = self.adapter.prepare('service_aging.start')
        job = self.adapter.confirm(confirmation.token)
        self.addCleanup(lambda: self.adapter.stop(job) if not self.adapter.jobs_idle else None)
        plan_path = self.context.history / 'aging-input' / (job + '.plan.json')
        self.wait_for(plan_path.is_file)
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        self.assertEqual(plan['project_id'], self.context.identity.project_id)
        self.assertEqual(plan['job_id'], job)
        self.assertEqual(plan['feed_collectors'], ['iptv'])
        event = dict(project_id=plan['project_id'], job_id=job, dut_id=plan['duts'][0]['dut_id'],
                     event_id='rack-a-141', collector='iptv', observed_at=datetime.now(timezone.utc).isoformat(),
                     outcome='abnormal', detail='模拟机顶盒报告画面冻结')
        input_path = plan_path.with_suffix('').with_suffix('.jsonl')
        with input_path.open('a', encoding='utf-8') as stream:
            for record in (dict(event, job_id='other'), event, event):
                stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        self.wait_for(lambda: bool(monitor.service.history_page(job, kind='sample')['rows']))
        self.adapter.stop(job)
        self.wait_for(lambda: self.adapter.jobs_idle)
        view = monitor.service.snapshot(job)
        self.assertEqual(Path(view['feed_path']), input_path)
        samples = monitor.service.history_page(job, kind='sample')['rows']
        self.assertEqual([(s['source'], s['event_id'], s['evidence']) for s in samples],
                         [('jsonl', 'rack-a-141', event['detail'])])
        streams = {row['collector']: row for row in view['rows']}
        self.assertEqual((streams['iptv']['checks'], streams['iptv']['failures']), (1, 1))
        self.assertEqual((streams['voice']['checks'], streams['voice']['source']), (0, 'manual'))
        self.assertFalse(self.engine.calls)

    def test_single_power_reuses_original_frames_order_and_interval_with_temporary_port(self):
        from src.services.power_on_service import turn_off_selected_channels, turn_on_selected_channels
        saved = self.context.config_dir / 'test_project_config.ini'
        original = saved.read_bytes()
        for action, engine in (('up', turn_on_selected_channels), ('down', turn_off_selected_channels)):
            with self.subTest(action=action):
                fake = FakeSerial()
                calls, waits, resources_during_io = [], [], []

                def open_serial(**options):
                    calls.append(options['port'])
                    resources_during_io.extend(key for _, keys in self.workspace.resources.owners.values() for key in keys)
                    return fake

                selection = self.adapter.single_power.selection(('COM29',))
                self.assertEqual((selection.configured_port, selection.numbers), ('COM102', (1, 7)))
                confirmation = self.adapter.prepare(SINGLE_POWER,
                    SinglePowerTarget('COM29', action, selection.binding), detected_ports=('COM29',))
                self.assertIn('COM29', confirmation.summary)
                self.assertIn('CH01、CH07', confirmation.summary)
                with patch('src.services.qt_single_power.' + engine.__name__,
                           partial(engine, serial_factory=open_serial, sleep_fn=waits.append)):
                    identifier = self.adapter.confirm(confirmation.token)
                    self.wait_for(lambda: self.adapter.idle)
                self.adapter.poll()
                self.assertEqual(self.adapter.jobs[identifier]['status']['state'], 'succeeded')
                self.assertEqual(calls, ['COM29'])
                self.assertEqual(fake.writes, [channel_power_frame(channel, action == 'up') for channel in (1, 7)])
                self.assertEqual(waits, [1])
                self.assertTrue(fake.closed)
                self.assertIn('serial:com29', resources_during_io)
                self.assertIn('serial:com102', resources_during_io)
                self.assertFalse(self.workspace.resources.owners)
                self.assertEqual(saved.read_bytes(), original)
                self.assertFalse(self.engine.calls)

    def test_single_power_manual_acknowledgement_has_no_serial_or_nic_io(self):
        selection = self.adapter.single_power.selection(())
        confirmation = self.adapter.prepare(SINGLE_POWER, SinglePowerTarget('', 'up', selection.binding))
        self.assertIn('无串口指令', confirmation.summary)
        with patch('src.services.qt_single_power.turn_on_selected_channels', side_effect=AssertionError('manual cannot use power')), \
             patch('src.core.network_adapter.read_adapter_identities', side_effect=AssertionError('manual cannot read NIC')):
            identifier = self.adapter.confirm(confirmation.token)
            self.wait_for(lambda: self.adapter.idle)
        self.adapter.poll()
        status = self.adapter.jobs[identifier]['status']
        self.assertEqual(status['state'], 'succeeded')
        self.assertTrue(status['result']['manual'])
        self.assertFalse(self.workspace.resources.owners)

    def test_single_power_open_denial_fails_before_dispatch_and_releases_resources(self):
        from serial import SerialException
        from src.services.power_on_service import turn_off_selected_channels, turn_on_selected_channels

        def deny_open(**options):
            self.assertEqual(options['port'], 'COM106')
            raise SerialException("could not open port 'COM106': PermissionError(13, 'Access is denied')")

        for action, engine in (('up', turn_on_selected_channels), ('down', turn_off_selected_channels)):
            with self.subTest(action=action):
                selection = self.adapter.single_power.selection(())
                confirmation = self.adapter.prepare(SINGLE_POWER, SinglePowerTarget('COM106', action, selection.binding))
                with patch('src.services.qt_single_power.' + engine.__name__,
                           partial(engine, serial_factory=deny_open, sleep_fn=lambda _: None)):
                    identifier = self.adapter.confirm(confirmation.token)
                    self.wait_for(lambda: self.adapter.idle)
                self.adapter.poll()
                status = self.adapter.jobs[identifier]['status']
                self.assertEqual(status['state'], 'failed')
                self.assertFalse(status['result']['dispatched'])
                self.assertIn('Access is denied', status['result']['message'])
                self.assertIn('程控电源指令未下发', status['result']['message'])
                with self.workspace.status.lock:
                    self.assertEqual(self.workspace.status.records[identifier]['state'], 'failed')
                self.assertFalse(self.workspace.resources.owners)
                self.assertFalse(self.workspace.resources.unknown_for(self.context.identity.project_id))

    def test_single_power_first_write_exception_keeps_result_unknown(self):
        from src.services.power_on_service import turn_on_selected_channels

        class FailingSerial(FakeSerial):
            def write(self, data):
                self.writes.append(data)
                raise OSError('fixture first write failed')

        fake = FailingSerial()
        selection = self.adapter.single_power.selection(())
        confirmation = self.adapter.prepare(SINGLE_POWER, SinglePowerTarget('COM106', 'up', selection.binding))
        with patch('src.services.qt_single_power.turn_on_selected_channels',
                   partial(turn_on_selected_channels, serial_factory=lambda **_: fake, sleep_fn=lambda _: None)):
            identifier = self.adapter.confirm(confirmation.token)
            self.wait_for(lambda: self.adapter.idle)
        self.adapter.poll()
        status = self.adapter.jobs[identifier]['status']
        self.assertEqual(status['state'], 'unknown')
        self.assertTrue(status['result']['dispatched'])
        self.assertEqual(fake.writes, [channel_power_frame(1, True)])
        self.assertTrue(fake.closed)
        self.assertFalse(self.workspace.resources.unknown_for(self.context.identity.project_id))

    def test_single_power_partial_write_keeps_result_unknown_and_releases_closed_port(self):
        from src.services.power_on_service import turn_on_selected_channels

        class FailingSerial(FakeSerial):
            def write(self, data):
                if self.writes:
                    raise OSError('fixture second write failed')
                return super().write(data)

        fake = FailingSerial()
        selection = self.adapter.single_power.selection(())
        confirmation = self.adapter.prepare(SINGLE_POWER, SinglePowerTarget('COM106', 'up', selection.binding))
        with patch('src.services.qt_single_power.turn_on_selected_channels',
                   partial(turn_on_selected_channels, serial_factory=lambda **_: fake, sleep_fn=lambda _: None)):
            identifier = self.adapter.confirm(confirmation.token)
            self.wait_for(lambda: self.adapter.idle)
        self.adapter.poll()
        status = self.adapter.jobs[identifier]['status']
        self.assertEqual(status['state'], 'unknown')
        self.assertTrue(status['result']['dispatched'])
        self.assertFalse(self.workspace.resources.unknown_for(self.context.identity.project_id))
        self.assertEqual(fake.writes, [channel_power_frame(1, True)])
        self.assertTrue(fake.closed)
        self.assertIsNotNone(self.adapter.single_power.selection(()))
        self.assertEqual(len(fake.writes), 1)

    def test_single_power_rejects_unapproved_stale_and_busy_targets(self):
        context = self.context
        adapter = self.adapter
        adapter._ensure_runtime()
        selection = adapter.single_power.selection(())
        target = SinglePowerTarget('COM106', 'down', selection.binding)
        confirmation = adapter.prepare(SINGLE_POWER, target)
        authority = CapabilityAuthority('operator', adapter.session, confirmation.token, (1, 7), source='gui', approved=True)
        with self.assertRaisesRegex(CapabilityError, '界面确认'):
            adapter.capabilities.execute(SINGLE_POWER, {'token': confirmation.token}, authority)
        with self.assertRaisesRegex(CapabilityError, '当前来源'):
            adapter.capabilities.execute(SINGLE_POWER, {'token': confirmation.token}, replace(authority, source='local'))
        config = context.config_dir / 'test_project_config.ini'
        original = config.read_bytes()
        config.write_bytes(original + b'\n# fixture change\n')
        try:
            with self.assertRaisesRegex(CapabilityError, '已变化'):
                adapter.confirm(confirmation.token)
        finally:
            config.write_bytes(original)
        selection = adapter.single_power.selection(())
        with self.assertRaisesRegex(CapabilityError, '候选已变化'):
            adapter.prepare(SINGLE_POWER, SinglePowerTarget('COM29', 'down', selection.binding))
        confirmation = adapter.prepare(SINGLE_POWER, SinglePowerTarget('COM106', 'down', selection.binding))
        self.workspace.resources.acquire('other-owner', 'other-project', '另一个模拟项目', ('power:COM106',))
        try:
            with self.assertRaisesRegex(CapabilityError, '另一个模拟项目'):
                adapter.confirm(confirmation.token)
        finally:
            self.workspace.resources.release('other-owner')
        self.assertFalse(adapter.jobs)

    def test_stop_waits_for_engine_and_keeps_resources(self):
        identifier = self.start()
        result = self.adapter.stop(identifier)
        self.assertEqual(result['state'], 'stop_requested')
        self.assertTrue(self.engine.stop_observed.wait(3))
        self.assertFalse(self.adapter.idle)
        self.assertTrue(self.workspace.resources.owners)
        with self.assertRaisesRegex(RuntimeError, '安全收尾'):
            self.adapter.close()
        self.engine.release_stop.set()
        self.wait_for(lambda: self.adapter.idle)
        self.adapter.poll()
        self.assertEqual(self.adapter.jobs[identifier]['status']['state'], 'stopped')
        self.assertFalse(self.workspace.resources.owners)


    def test_unknown_result_allows_fresh_confirmation_without_retrying_old_job(self):
        self.engine.exception = OSError('fixture transport lost')
        with patch('src.services.power_worker_lifetime.power_worker_notice', return_value=''):
            identifier = self.start()
            self.engine.finish.set()
            self.wait_for(lambda: self.adapter.idle)
            self.adapter.poll()
            self.assertEqual(self.adapter.jobs[identifier]['status']['state'], 'unknown')
            self.assertFalse(self.workspace.resources.unknown_for(self.context.identity.project_id))
            confirmation = self.adapter.prepare('aging.start')
            self.assertEqual(len(self.engine.calls), 1)
            self.engine.exception = None
            fresh = self.adapter.confirm(confirmation.token)
            self.wait_for(lambda: self.adapter.idle)
            self.adapter.poll()
        self.assertNotEqual(identifier, fresh)
        self.assertEqual(len(self.engine.calls), 2)
        self.assertEqual(self.adapter.jobs[fresh]['status']['state'], 'succeeded')
        self.assertEqual(self.adapter.jobs[identifier]['status']['state'], 'unknown')
        self.assertEqual(self.workspace.status.snapshot(self.context).unknown_task_count, 0)

    def test_unknown_remote_job_reuses_same_request_and_requires_fresh_approval(self):
        self.adapter._ensure_runtime()
        service = self.adapter.capabilities
        self.assertNotIn('jobs.resolve_unknown', {row['capability_id'] for row in service.registry.list()})
        jobs = service.jobs
        requests = []
        args = dict(channel_ids=[1])
        keys = ('serial:qt-fixture-fresh-remote-request', 'channel:1')
        approved = CapabilityAuthority('fixture-member', 'fixture-chat', 'first-turn', (1,),
                                       source='feishu', approved=True)

        def run(context):
            requests.append(context.job_id)
            return dict(state='unknown', ok=False)

        first = jobs.start('fixture.write', args, approved, keys, run)
        self.wait_for(lambda: jobs.idle)
        repeated = jobs.start('fixture.write', args, approved, keys, run)
        self.assertEqual(repeated, dict(job_id=first['job_id'], state='unknown', reused=True))
        fresh = replace(approved, operation_id='new-turn', approved=False)
        with self.assertRaises(CapabilityError) as rejected:
            jobs.start('fixture.write', args, fresh, keys, run)
        self.assertEqual(rejected.exception.code, 'approval_required')
        second = jobs.start('fixture.write', args, replace(fresh, approved=True), keys, run)
        self.wait_for(lambda: jobs.idle)
        self.assertNotEqual(first['job_id'], second['job_id'])
        self.assertEqual(requests, [first['job_id'], second['job_id']])
        self.assertEqual(jobs.status(first['job_id'], approved)['state'], 'unknown')

    def test_other_project_cannot_acquire_same_physical_resources(self):
        self.start()
        context = self.workspace.projects.create(self.root / 'other', '另一个模拟项目')
        configure_project(self.workspace, context)
        other = QtExecutionAdapter(self.workspace, context, self.events.append)
        try:
            confirmation = other.prepare('aging.start')
            with self.assertRaises(CapabilityError):
                other.confirm(confirmation.token)
            self.assertTrue(other.idle)
        finally:
            other.close()
        self.assertEqual(len(self.engine.calls), 1)

    def test_selected_wifi_profile_reserves_host_before_a_power_job(self):
        from line_check_assistant.config_store import ChannelConfigStore
        from src.services.project_execution import project_resources
        from types import SimpleNamespace

        directory = self.context.config_dir
        default = (directory / 'test_project_config.ini').read_text(encoding='utf-8')
        (directory / 'wireless.ini').write_text(default.replace('enable = 0', 'enable = 1'), encoding='utf-8')
        main = directory / 'config.ini'
        main.write_text(main.read_text(encoding='utf-8').replace('test_project = test_project_config.ini',
            'Selected = wireless.ini').replace('selected_profile = TEST_PROJECT', 'selected_profile = SELECTED'),
            encoding='utf-8')
        self.workspace.projects.save(self.context)
        channels = ChannelConfigStore(directory / 'network_card_ip.ini').load()
        view = SimpleNamespace(channels=channels, power_serial_port='COM102', project_context=self.context)
        other = 'fixture-other-wifi'
        self.workspace.resources.acquire(other, 'another-project', '无线项目', ['wifi:host'])
        try:
            confirmation = self.adapter.prepare('aging.start')
            with self.assertRaisesRegex(CapabilityError, 'wifi:host'):
                self.adapter.confirm(confirmation.token)
            self.assertEqual(len(self.engine.calls), 0)
            self.assertEqual(set(self.workspace.resources.owners), {other})
            self.assertIn('wifi:host', project_resources(view, '_on_start'))
        finally:
            self.workspace.resources.release(other)
        job = self.start()
        self.assertIn('wifi:host', self.workspace.resources.owners[job][1])

    def test_snapshot_enabling_unreserved_wifi_stops_before_original_engine(self):
        from src.services.project_store import ProjectStore
        snapshot = ProjectStore.snapshot

        def enable_wifi_in_snapshot(store, context, *args, **kwargs):
            root = snapshot(store, context, *args, **kwargs)
            config = root / 'Auto_power_on_off_tool/config/test_project_config.ini'
            config.write_text(config.read_text(encoding='utf-8').replace('enable = 0', 'enable = 1'), encoding='utf-8')
            return root

        token = self.adapter.prepare('aging.start').token
        with patch.object(ProjectStore, 'snapshot', enable_wifi_in_snapshot):
            job = self.adapter.confirm(token)
            self.wait_for(lambda: self.adapter.idle)
        self.adapter.poll()
        row = self.adapter.jobs[job]['status']
        self.assertEqual(row['state'], 'failed')
        self.assertIn('无线资源已变化', str(row['result']))
        self.assertFalse(self.engine.calls)
        self.assertFalse(self.workspace.resources.owners)

    def test_disjoint_project_power_jobs_keep_separate_snapshots_stops_and_leases(self):
        from line_check_assistant.config_store import ChannelConfigStore
        from src.services.legacy_power_test_service import LegacyPowerTestResult

        other_context = self.workspace.projects.create(self.root / 'other', '独立模拟项目')
        configure_project(self.workspace, other_context, (3,))
        for context, power, host in ((self.context, 'COM9400', '192.0.2.200'),
                                     (other_context, 'COM9500', '192.0.2.201')):
            store = ChannelConfigStore(context.config_dir / 'network_card_ip.ini')
            channels = []
            for channel in store.load():
                number = int(channel.section.split('_')[-1])
                alias = f'VLAN{490 + number}'
                channels.append(replace(channel, adapter_alias=alias, vlan_name=alias, serial_port=f'COM{9600+number}',
                                        device_manage_ip=host))
            store.save(channels, power)
            self.workspace.projects.save(context)
        self.workspace.status.attach(other_context)
        other_events = []
        other = QtExecutionAdapter(self.workspace, other_context, other_events.append)
        started = {port: Event() for port in ('COM9400', 'COM9500')}
        finish, observed = Event(), Event()
        requests = {}

        def run(request, emit, stop, **callbacks):
            port = request.serial_port
            requests[port] = request
            callbacks['on_channel_progress'](request.channels[0].number, 3, 100, port)
            started[port].set()
            while not finish.wait(.02):
                if stop.is_set():
                    if port == 'COM9400':
                        observed.set()
                    return LegacyPowerTestResult(False, '用户已停止执行开关机测试')
            return LegacyPowerTestResult(True, '模拟正常完成')

        self.pipeline.stop()
        try:
            with mock_power_interfaces(self.context, other_context), \
                    patch('src.services.legacy_power_test_service.run_legacy_power_test', side_effect=run):
                first = self.adapter.confirm(self.adapter.prepare('aging.start').token)
                self.assertTrue(started['COM9400'].wait(3))
                second = other.confirm(other.prepare('aging.start').token)
                self.assertTrue(started['COM9500'].wait(3))
                self.assertNotEqual(first, second)
                for context, port, numbers in ((self.context, 'COM9400', (1, 7)), (other_context, 'COM9500', (3,))):
                    self.assertIn(context.root / 'runs', requests[port].tool_root.parents)
                    self.assertEqual(tuple(channel.number for channel in requests[port].channels), numbers)
                self.adapter.stop(first)
                self.assertTrue(observed.wait(3))
                self.wait_for(lambda: self.adapter.idle)
                self.adapter.poll()
                other.poll()
                self.assertEqual(self.adapter.jobs[first]['status']['state'], 'stopped')
                self.assertFalse(other.idle)
                owners = {owner_project for owner_project, _ in self.workspace.resources.owners.values()}
                self.assertEqual(owners, {other_context.identity.project_id})
                finish.set()
                self.wait_for(lambda: other.idle)
                other.poll()
                self.assertEqual(other.jobs[second]['status']['state'], 'succeeded')
                self.assertTrue(all(row.project_id == other_context.identity.project_id for row in other_events))
                self.assertFalse(self.workspace.resources.owners)
        finally:
            finish.set()
            self.wait_for(lambda: self.adapter.idle and other.idle)
            other.close()

    def test_power_failure_after_stop_request_preserves_original_failure(self):
        from src.services.legacy_power_test_service import LegacyPowerTestResult
        self.pipeline.stop()
        for detail in ('通道1业务检测失败', '用户停止，旧业务子进程已终止'):
            entered = Event()
            def fail(request, emit, stop, **callbacks):
                entered.set()
                self.assertTrue(stop.wait(3))
                return LegacyPowerTestResult(False, detail)
            with self.subTest(detail=detail), mock_power_interfaces(self.context), \
                    patch('src.services.legacy_power_test_service.run_legacy_power_test', side_effect=fail):
                identifier = self.adapter.confirm(self.adapter.prepare('aging.start').token)
                self.assertTrue(entered.wait(3))
                self.adapter.stop(identifier)
                self.wait_for(lambda: self.adapter.idle)
                self.adapter.poll()
                status = self.adapter.jobs[identifier]['status']
                self.assertEqual(status['state'], 'failed')
                self.assertIn(detail, status['result']['error'])

    def test_original_orchestrator_receives_original_request_and_callbacks(self):
        from src.services.legacy_power_test_service import LegacyPowerTestResult
        self.pipeline.stop()
        captured = []
        def run(request, emit, stop, **callbacks):
            captured.append(request)
            callbacks['on_progress'](68, 100)
            callbacks['on_channel_progress'](7, 68, 100, '原通道阶段')
            callbacks['on_channel_status'](7, 'failed', '原判据结果')
            return LegacyPowerTestResult(False, 'fixture original verdict')
        with mock_power_interfaces(self.context), \
                patch('src.services.legacy_power_test_service.run_legacy_power_test', side_effect=run):
            confirmation = self.adapter.prepare('aging.start')
            identifier = self.adapter.confirm(confirmation.token)
            self.wait_for(lambda: self.adapter.idle)
        self.adapter.poll()
        self.assertEqual(len(captured), 1)
        request = captured[0]
        self.assertEqual((request.startup_time, request.interval_time, request.number_of_tests), (180, 20, 100))
        self.assertEqual(tuple(c.number for c in request.channels), (1, 7))
        self.assertEqual(self.adapter.jobs[identifier]['status']['state'], 'failed')
        self.assertEqual(self.adapter.jobs[identifier]['progress'], (68, 100))
        self.assertEqual(self.adapter.jobs[identifier]['channels'][7]['status'], 'failed')

    def test_all_sixteen_channels_reach_original_worker_and_keep_individual_results(self):
        from src.services import legacy_power_test_service as legacy
        from test_legacy_power_test_service import _CompletedProcess, _FakeProcessContext

        numbers = tuple(range(1, 17))
        configure_project(self.workspace, self.context, numbers)
        expected = legacy.prepare_legacy_power_test_request(self.context.saved_root / 'Auto_power_on_off_tool',
            [legacy.LegacyPowerChannel(n, f'192.0.2.{n}') for n in numbers])
        requests = []

        class SimulatedWorker(_CompletedProcess):
            def start(self):
                request, messages, _, _, run_id, *_ = self.args
                requests.append((request, run_id))
                for number in reversed(numbers):
                    messages.put(dict(type='channel_result', channel=number, run_id=run_id, ok=number != 16))
                messages.put(dict(type='channel_result', channel=16, run_id='previous-run', ok=True))
                messages.put(dict(type='result', run_id=run_id, ok=False, detail='模拟第16通道失败'))
                self._alive = False

        context = _FakeProcessContext()
        self.pipeline.stop()
        with mock_power_interfaces(self.context), \
                patch.object(legacy, 'multiprocessing') as multiprocessing, \
                patch.object(context, 'Process', side_effect=SimulatedWorker) as factory:
            multiprocessing.get_context.return_value = context
            confirmation = self.adapter.prepare('aging.start')
            self.assertEqual(confirmation.channel_ids, numbers)
            identifier = self.adapter.confirm(confirmation.token)
            self.wait_for(lambda: self.adapter.idle)
        self.adapter.poll()
        multiprocessing.get_context.assert_called_once_with('spawn')
        self.assertIs(factory.call_args.kwargs['target'], legacy._legacy_start_all_worker)
        (request, diagnostic_run), = requests
        self.assertNotEqual(diagnostic_run, 'manual')
        self.assertEqual(self.adapter.ai_evidence.run_id, diagnostic_run)
        channel_evidence = self.adapter.ai_evidence.snapshot(diagnostic_run, 16)
        self.assertTrue(any(row['source'] == 'channel_result' for row in channel_evidence))
        self.assertTrue(all(row['channel'] == 16 for row in channel_evidence))
        self.assertIn(self.context.root / 'runs', request.tool_root.parents)
        self.assertEqual(replace(request, tool_root=expected.tool_root), expected)
        view = self.resume_view(numbers)
        self.assertEqual((view.run_id, view.state), (identifier, 'failed'))
        self.assertEqual([(c.number, c.state, c.cycle, c.total) for c in view.channels],
                         [(n, 'success', 100, 100) for n in numbers[:-1]] + [(16, 'failed', 0, 100)])
        self.assertFalse(self.workspace.resources.owners)

    def test_running_targets_keep_saved_snapshot_after_external_draft_edit(self):
        from line_check_assistant.config_store import ChannelConfigStore
        self.start()
        run_config = self.adapter.configuration_dir
        self.assertNotEqual(run_config, self.context.config_dir)
        original = (run_config / 'network_card_ip.ini').read_bytes()
        draft = self.context.config_dir / 'network_card_ip.ini'
        store = ChannelConfigStore(draft)
        channels = store.load()
        channels[0] = replace(channels[0], serial_port='COM999')
        store.save(channels, 'COM999')
        self.assertEqual(self.adapter.configuration_dir, run_config)
        self.assertEqual((run_config / 'network_card_ip.ini').read_bytes(), original)
        self.assertEqual(ChannelConfigStore(run_config / 'network_card_ip.ini').load()[0].serial_port, 'COM1')

    def test_cancelled_confirmation_is_logged_and_cannot_be_reused(self):
        confirmation = self.adapter.prepare('aging.start')
        self.adapter.discard_confirmation(confirmation.token)
        self.assertIsNone(self.adapter.pending)
        with self.assertRaises(CapabilityError):
            self.adapter.confirm(confirmation.token)
        self.assertTrue(any('跳过执行' in e.message for e in self.events))
        self.assertFalse(self.engine.calls)

    def test_pipeline_prestarts_confirmed_serial_targets_and_preserves_nonfatal_failure(self):
        from qt_serial_fakes import SerialHarness
        from src.services.legacy_power_test_service import LegacyPowerTestResult
        self.pipeline.stop()
        serial = SerialHarness().start()
        self.addCleanup(serial.stop)
        tasks = ('env_check', 'serial_terminal', 'legacy_power_test')
        statuses = self.adapter.pipeline_status()
        self.assertEqual(set(statuses), set(tasks))
        self.assertFalse(serial.sessions)
        confirmation = self.adapter.prepare('pipeline.start', tasks)
        self.assertIn('串口日志 → 环境线路检查 → 执行开关机测试', confirmation.summary)
        self.assertIn('仅断电已勾选通道', confirmation.summary)
        self.assertEqual(confirmation.channel_ids, (1, 7))
        self.assertFalse(serial.sessions)
        entered = []
        original = self.adapter.manager.acquire_monitor

        def monitor(owner, settings, path):
            entered.append(settings.port)
            if settings.port == 'COM1':
                raise OSError('fixture port failed to open')
            return original(owner, settings, path)

        def environment(orchestrator):
            self.assertEqual(entered, ['COM1', 'COM7'])
            entered.append('environment')

        def aging(request, *args, **kwargs):
            self.assertEqual(entered[-1], 'environment')
            entered.append('aging')
            return LegacyPowerTestResult(True, '模拟完成')

        with mock_power_interfaces(self.context), patch.object(self.adapter.manager, 'acquire_monitor', side_effect=monitor), \
                patch('src.services.pipeline_orchestrator.PipelineOrchestrator._run_env_check', new=environment), \
                patch('src.services.legacy_power_test_service.run_legacy_power_test', side_effect=aging):
            run = self.adapter.confirm(confirmation.token)
            self.wait_for(lambda: not self.adapter.pipeline_serial.requests.empty())
            self.assertEqual(entered, [])
            self.adapter.poll()
            self.wait_for(lambda: self.adapter.idle)
        self.adapter.poll()
        self.assertEqual(entered, ['COM1', 'COM7', 'environment', 'aging'])
        self.assertEqual(self.adapter.pipeline_serial.last_run, run)
        status = self.adapter.jobs[run]['status']
        self.assertEqual(status['capability_id'], 'pipeline.start')
        self.assertEqual([(item['code'], item['ok']) for item in status['result']['items']],
                         [('serial_terminal', False), ('env_check', True), ('legacy_power_test', True)])
        self.assertTrue(any('2. 串口日志' in event.message for event in self.events))
        self.assertTrue(self.adapter.terminal.tabs['vlan107']['path'].endswith('.log'))
        self.assertIs(self.adapter.terminal.tabs['vlan107']['session'], serial.sessions['COM7'])

    def test_pipeline_environment_failure_prevents_aging(self):
        self.pipeline.stop()
        with patch('src.services.pipeline_orchestrator.PipelineOrchestrator._run_env_check',
                   side_effect=RuntimeError('fixture environment failure')), \
                patch('src.services.legacy_power_test_service.run_legacy_power_test') as aging:
            confirmation = self.adapter.prepare('pipeline.start', ('env_check', 'legacy_power_test'))
            run = self.adapter.confirm(confirmation.token)
            self.wait_for(lambda: self.adapter.idle)
        aging.assert_not_called()
        self.adapter.poll()
        self.assertEqual(self.adapter.jobs[run]['status']['state'], 'failed')

    def test_pipeline_prestart_cannot_open_serial_after_stop_before_owner_claims_it(self):
        self.pipeline.stop()
        confirmation = self.adapter.prepare('pipeline.start', ('serial_terminal', 'env_check'))
        with patch.object(self.adapter.terminal, 'open_pipeline') as open_serial, \
                patch('src.services.pipeline_orchestrator.PipelineOrchestrator._run_env_check') as environment:
            run = self.adapter.confirm(confirmation.token)
            self.wait_for(lambda: not self.adapter.pipeline_serial.requests.empty())
            self.adapter.stop(run)
            self.wait_for(lambda: self.adapter.idle)
            self.adapter.poll()
        open_serial.assert_not_called()
        environment.assert_not_called()
        self.assertEqual(self.adapter.jobs[run]['status']['state'], 'stopped')

    def test_pipeline_requires_explicit_choices_and_rejects_changed_serial_destination(self):
        for tasks in ((), ('sample_upgrade',), ('serial_terminal', 'serial_terminal')):
            with self.assertRaises(CapabilityError):
                self.adapter.prepare('pipeline.start', tasks)
        confirmation = self.adapter.prepare('pipeline.start', ('serial_terminal',))
        self.adapter.terminal.log_dir = self.root / 'changed'
        with self.assertRaisesRegex(CapabilityError, '日志目录已变化'):
            self.adapter.confirm(confirmation.token)
        self.assertFalse(self.adapter.jobs)

    def pretest_payload(self):
        from line_check_assistant.test_item_config_store import TelnetSettings
        draft = self.adapter.configuration_command('open', {})
        return dict(token=draft.token, revision=draft.revision,
            telnet=asdict(TelnetSettings(password='fixture-private-password', timeout=3)),
            order=dict(command_fail_retry_interval_time=100, items=[
                dict(command='fixture draft command', retry_times=19,
                     expected_segments=[dict(text='MATCHED', negate=False)])]))

    def resume_pipeline(self, *, acknowledge_live=False, numbers=(1, 7)):
        if numbers != (1, 7):
            self.identities = configure_project(self.workspace, self.context, numbers=numbers)
            readers = patch('src.core.network_adapter.read_adapter_identities', return_value=self.identities)
            readers.start()
            self.addCleanup(readers.stop)
        harness = ControlledResumePipeline(acknowledge_live=acknowledge_live)
        pipeline = patch('src.services.capability_device_services.PipelineOrchestrator', harness.factory)
        runner = patch('src.services.legacy_power_test_service.run_legacy_power_test', harness.run_after_exit)
        pipeline.start()
        runner.start()
        self.addCleanup(pipeline.stop)
        self.addCleanup(runner.stop)
        self.addCleanup(harness.release_recovery.set)
        self.addCleanup(harness.finish.set)
        parent = self.adapter.confirm(self.adapter.prepare('aging.start').token)
        self.assertTrue(harness.started.wait(3))
        return harness, parent

    def resume_view(self, numbers=(1, 7)):
        view = ProjectView(self.context.identity.project_id, '模拟上下电', '自动开关机', '', '', '', '', '', None, '',
            channels=tuple(ChannelView(number, 'unknown') for number in numbers))
        return self.adapter.present(view)

    def test_channel_stage_and_completed_count_follow_the_same_run_and_channel(self):
        self.start()
        context, _ = self.engine.calls[0]
        context.app._set_power_test_channel_progress(7, 68, 100, '等待重试')
        context.app._set_power_test_channel_state(7, 'retry', '连接超时')
        view = self.resume_view((1, 7, 8))
        self.assertEqual(view.progress_text, '已完成 68 / 100 轮')
        first, retry, absent = view.channels
        self.assertEqual((first.stage, first.cycle), ('fixture stage', 68))
        self.assertEqual((retry.stage, retry.cycle, retry.total, retry.detail),
                         ('等待重试', 68, 100, '连接超时'))
        self.assertEqual((absent.stage, absent.cycle, absent.total), ('', None, None))
        self.adapter.stop(view.run_id)
        self.engine.release_stop.set()
        self.wait_for(lambda: self.adapter.idle)
        stopped = self.resume_view().channels[1]
        self.assertEqual((stopped.state, stopped.cycle, stopped.stage), ('stopped', 68, '等待重试'))

    def test_late_previous_batch_events_preserve_current_run_channel_and_history(self):
        previous = self.start()
        previous_projection = self.engine.calls[0][0].app
        self.engine.finish.set()
        self.wait_for(lambda: self.adapter.idle)
        self.engine.finish.clear()
        self.engine.started.clear()
        current = self.start()
        self.assertNotEqual(previous, current)
        current_projection = self.engine.calls[1][0].app
        current_projection._set_power_test_progress(12, 100)
        current_projection._set_power_test_channel_progress(7, 12, 100, 'current cycle')
        current_projection._record_power_test_channel_history(7, 12, 'running', 'current history')
        before = self.resume_view((7,))
        cursor = dict(before.power_history_events)[7]
        self.assertGreater(cursor, 0)
        leases = dict(self.workspace.resources.owners)
        self.assertTrue(leases)

        # Deliver the previous worker's callbacks after the new run is on screen.
        previous_projection._set_power_test_progress(99, 100)
        previous_projection._set_power_test_channel_progress(7, 99, 100, 'previous cycle')
        previous_projection._set_power_test_channel_state(7, 'failed', 'previous failure')
        previous_projection._record_power_test_channel_history(7, 99, 'failed', 'previous history')
        after = self.resume_view((7,))
        channel, = after.channels
        self.assertEqual((after.run_id, after.state, after.progress, after.attention_count),
                         (current, 'running', 12, 0))
        self.assertEqual((channel.state, channel.cycle, channel.total, channel.stage),
                         ('running', 12, 100, 'current cycle'))
        self.assertEqual((after.power_history_job, dict(after.power_history_events)[7]), (current, cursor))
        self.assertEqual(self.workspace.resources.owners, leases)
        history_logs = [(row.run_id, row.channel) for row in self.events
                        if 'current history' in row.message or 'previous history' in row.message]
        self.assertEqual(history_logs, [(current, 7), (previous, 7)])
        jobs = self.adapter.capabilities.jobs
        old_record = jobs.status(previous, self.adapter.jobs[previous]['authority'])
        self.assertEqual(old_record['state'], 'succeeded')
        self.assertTrue(any('previous history' in event['message'] for event in old_record['events']))

    def test_qt_resume_live_uses_original_queue_only_once(self):
        harness, parent = self.resume_pipeline(acknowledge_live=True)
        self.assertEqual([row.number for row in self.resume_view().channels if row.can_resume], [7])
        prepared = self.adapter.prepare('aging.resume', (7,))
        self.assertIn('CH07', prepared.summary)
        self.assertIn('第 4/100 轮', prepared.summary)
        self.assertEqual(self.adapter.confirm(prepared.token), parent)
        self.wait_for(lambda: len(harness.live_commands) == 1 and not harness.session.is_recovering)
        command = harness.live_commands[0]
        self.assertEqual((command['channel'], command['completed'], command['attempt']), (7, 3, 1))
        with self.assertRaisesRegex(CapabilityError, '确认已失效'):
            self.adapter.confirm(prepared.token)
        self.assertFalse(self.adapter.idle)
        self.assertEqual(set(self.adapter.jobs), {parent})
        self.assertEqual(self.resume_view().channels[0].cycle, 100)
        self.assertFalse(harness.recovery_calls)

    def test_qt_resume_keeps_parent_lease_when_queued_command_falls_back_on_process_exit(self):
        harness, parent = self.resume_pipeline()
        self.adapter.confirm(self.adapter.prepare('aging.resume', (7,)).token)
        self.wait_for(lambda: not harness.commands.empty())
        harness.finish.set()
        self.assertTrue(harness.process_done.wait(3))
        self.assertTrue(harness.recovering.wait(3))
        self.assertFalse(self.adapter.idle)
        self.assertIn(parent, self.workspace.resources.owners)
        self.assertTrue(self.resume_view().can_stop)
        request, options = harness.recovery_calls[0]
        self.assertEqual([item.number for item in request.channels], [7])
        self.assertEqual(options['initial_completed'], {7: 3})
        self.assertFalse(options['initialize_power'])
        self.adapter.stop(parent)
        self.assertTrue(harness.observed_stop.wait(3))
        self.assertIn(parent, self.workspace.resources.owners)
        harness.release_recovery.set()
        self.wait_for(lambda: self.adapter.idle)
        self.adapter.poll()
        self.assertNotIn(parent, self.workspace.resources.owners)
        self.assertEqual(self.adapter.jobs[parent]['status']['state'], 'failed')
        self.assertIn('续跑已停止', self.resume_view().resume_detail)

    def test_qt_resume_after_run_keeps_original_verdict_and_reopens_progress_observation(self):
        harness, parent = self.resume_pipeline()
        harness.finish.set()
        self.wait_for(lambda: self.adapter.idle)
        original = self.resume_view()
        self.assertEqual(original.state, 'failed')
        self.assertTrue(self.adapter.jobs[parent]['drained'])
        prepared = self.adapter.prepare('aging.resume', (7,))
        recovery = self.adapter.confirm(prepared.token)
        self.assertNotEqual(recovery, parent)
        self.assertTrue(harness.recovering.wait(3))
        during = self.resume_view()
        self.assertEqual((during.run_id, during.active_task_count, during.can_stop), (recovery, 1, True))
        self.assertIn(recovery, self.workspace.resources.owners)
        self.assertNotIn(parent, self.workspace.resources.owners)
        harness.release_recovery.set()
        self.wait_for(lambda: self.adapter.idle)
        finished = self.resume_view()
        self.assertEqual((finished.state, finished.run_id, finished.active_task_count), ('failed', parent, 0))
        self.assertEqual([(row.number, row.state, row.cycle) for row in finished.channels],
            [(1, 'success', 100), (7, 'success', 100)])
        self.assertIn('续跑完成', finished.resume_detail)
        self.assertEqual(self.adapter.jobs[recovery]['status']['state'], 'succeeded')
        self.assertEqual(self.adapter.jobs[parent]['status']['result']['items'][0]['detail'], '模拟原批次异常结论')
        self.assertEqual(harness.calls, [frozenset({'legacy_power_test'})])

    def test_qt_resume_rejects_phase_and_nic_changes_and_foreign_source(self):
        harness, parent = self.resume_pipeline()
        prepared = self.adapter.prepare('aging.resume', (7,))
        with self.assertRaisesRegex(CapabilityError, '当前来源'):
            self.adapter.capabilities.execute('aging.qt_resume.confirm', {'token': prepared.token},
                CapabilityAuthority('remote', 'r', 'op', (7,), source='feishu', approved=True))
        harness.finish.set()
        self.wait_for(lambda: self.adapter.idle)
        with self.assertRaisesRegex(CapabilityError, '运行阶段已变化'):
            self.adapter.confirm(prepared.token)
        prepared = self.adapter.prepare('aging.resume', (7,))
        different = tuple(replace(row, interface_guid='changed') for row in self.identities)
        with patch('src.core.network_adapter.read_adapter_identities', return_value=different), \
             self.assertRaisesRegex(CapabilityError, '网卡身份与原批次不同'):
            self.adapter.confirm(prepared.token)
        prepared = self.adapter.prepare('aging.resume', (7,))
        self.adapter.discard_confirmation(prepared.token)
        with self.assertRaisesRegex(CapabilityError, '确认已失效'):
            self.adapter.confirm(prepared.token)
        prepared = self.adapter.prepare('aging.resume', (7,))
        config = self.context.config_dir / 'config.ini'
        config.write_bytes(config.read_bytes() + b'\n# changed after preview\n')
        with self.assertRaises(CapabilityError):
            self.adapter.confirm(prepared.token)
        self.assertEqual(tuple(self.adapter.jobs), (parent,))
        self.assertFalse(harness.recovery_calls)
        self.assertTrue(harness.commands.empty())

    def start_resume_series(self):
        harness, parent = self.resume_pipeline(numbers=(1, 7, 9, 11))
        harness.finish.set()
        self.wait_for(lambda: self.adapter.idle)
        harness.recovery_gates = {number: Event() for number in (7, 9, 11)}
        job = self.adapter.confirm(self.adapter.prepare('aging.resume', (7,)).token)
        self.assertTrue(harness.recovering.wait(3))
        for channel in (11, 9):
            prepared = self.adapter.prepare('aging.resume', (channel,))
            self.assertIn('加入等待队列', prepared.summary)
            self.assertEqual(self.adapter.confirm(prepared.token), job)
        return harness, parent, job

    def test_qt_postrun_resume_queue_is_fifo_and_reacquires_only_next_channel(self):
        harness, parent, first = self.start_resume_series()
        with self.assertRaisesRegex(CapabilityError, '已在等待续跑'):
            self.adapter.prepare('aging.resume', (11,))
        self.assertIn('排队 CH11、CH09', self.resume_view((1, 7, 9, 11)).resume_detail)
        self.assertEqual(len(harness.recovery_calls), 1)
        self.assertEqual(set(self.workspace.resources.owners), {first})
        harness.failed_recoveries.add(7)
        harness.recovery_gates[7].set()
        self.wait_for(lambda: self.adapter.jobs_idle)
        self.assertFalse(self.adapter.idle)
        with self.assertRaisesRegex(CapabilityError, '请等待'):
            self.adapter.prepare('aging.start')
        with self.assertRaisesRegex(CapabilityError, '等待续跑'):
            self.adapter.configuration_command('open', {})
        statuses = self.adapter.capabilities.jobs.status

        def stale_status(identifier, authority, after):
            result = statuses(identifier, authority, after)
            return dict(result, state='running') if identifier == first else result

        with patch.object(self.adapter.capabilities.jobs, 'status', side_effect=stale_status):
            self.adapter.poll()
        self.assertFalse(self.adapter.idle)
        self.assertEqual(len(harness.recovery_calls), 1)
        self.adapter.poll()
        self.wait_for(lambda: len(harness.recovery_calls) == 2)
        second = self.adapter.resume.recovery_job
        self.assertEqual(set(self.workspace.resources.owners), {second})
        self.assertEqual(self.adapter.jobs[first]['status']['state'], 'failed')
        harness.recovery_gates[11].set()
        self.wait_for(lambda: self.adapter.jobs_idle)
        self.adapter.poll()
        self.wait_for(lambda: len(harness.recovery_calls) == 3)
        third = self.adapter.resume.recovery_job
        self.assertEqual(set(self.workspace.resources.owners), {third})
        self.assertEqual([req.channels[0].number for req, _ in harness.recovery_calls], [7, 11, 9])
        self.assertTrue(all(not options['initialize_power'] for _, options in harness.recovery_calls))
        self.assertEqual([options['initial_completed'] for _, options in harness.recovery_calls], [{7: 3}, {11: 3}, {9: 3}])
        harness.recovery_gates[9].set()
        self.wait_for(lambda: self.adapter.idle)
        view = self.resume_view((1, 7, 9, 11))
        self.assertEqual((view.state, view.run_id, view.active_task_count), ('failed', parent, 0))
        self.assertIn('CH09 · 续跑完成', view.resume_detail)
        self.assertEqual([channel.cycle for channel in view.channels], [100, 3, 100, 100])

    def test_qt_postrun_queue_stop_from_previous_visible_job_cancels_waiting(self):
        harness, _, first = self.start_resume_series()
        harness.recovery_gates[7].set()
        self.wait_for(lambda: self.adapter.jobs_idle)
        self.adapter.poll()
        self.wait_for(lambda: len(harness.recovery_calls) == 2)
        second = self.adapter.resume.recovery_job
        self.assertEqual(self.adapter.stop(first)['job_id'], second)
        self.assertTrue(harness.observed_stop.wait(3))
        self.assertFalse(self.adapter.resume.has_waiting)
        self.assertIn(second, self.workspace.resources.owners)
        harness.recovery_gates[11].set()
        self.wait_for(lambda: self.adapter.idle)
        self.adapter.poll()
        self.assertEqual(self.adapter.jobs[second]['status']['state'], 'stopped')
        self.assertEqual([req.channels[0].number for req, _ in harness.recovery_calls], [7, 11])
        self.assertTrue(any('取消等待中的 CH09' in entry.message for entry in self.events))

    def test_qt_postrun_queue_revalidates_each_target_and_discards_on_close(self):
        harness, _, _ = self.start_resume_series()
        changed = tuple(replace(row, interface_guid='replaced') if row.alias == 'VLAN111' else row for row in self.identities)
        with patch('src.core.network_adapter.read_adapter_identities', return_value=changed):
            harness.recovery_gates[7].set()
            self.wait_for(lambda: self.adapter.jobs_idle)
            self.adapter.poll()
            self.wait_for(lambda: len(harness.recovery_calls) == 2)
        self.assertEqual([req.channels[0].number for req, _ in harness.recovery_calls], [7, 9])
        self.assertTrue(any('CH11 未启动' in entry.message and '网卡身份' in entry.message for entry in self.events))
        self.adapter.confirm(self.adapter.prepare('aging.resume', (11,)).token)
        self.adapter.begin_close()
        self.assertFalse(self.adapter.ready_to_close)
        self.assertFalse(self.adapter.resume.has_waiting)
        self.assertTrue(harness.observed_stop.wait(3))
        harness.recovery_gates[9].set()
        self.wait_for(lambda: self.adapter.ready_to_close)
        self.adapter.poll()
        self.assertEqual(len(harness.recovery_calls), 2)

    def test_qt_postrun_queue_rejects_configuration_changed_during_wait(self):
        harness, _, _ = self.start_resume_series()
        config = self.context.config_dir / 'config.ini'
        config.write_bytes(config.read_bytes() + b'\n# changed while requests waited\n')
        harness.recovery_gates[7].set()
        self.wait_for(lambda: self.adapter.jobs_idle)
        self.adapter.poll()
        self.assertTrue(self.adapter.idle)
        self.assertEqual(len(harness.recovery_calls), 1)
        for channel in (11, 9):
            self.assertTrue(any(f'CH{channel:02d} 未启动' in entry.message for entry in self.events))

    def test_qt_postrun_queue_discards_waiting_when_first_result_is_unknown(self):
        harness, _, first = self.start_resume_series()
        harness.recovery_gates[7].set()
        self.wait_for(lambda: self.adapter.jobs_idle)
        statuses = self.adapter.capabilities.jobs.status

        def unknown_status(identifier, authority, after):
            result = statuses(identifier, authority, after)
            return dict(result, state='unknown') if identifier == first else result

        with patch.object(self.adapter.capabilities.jobs, 'status', side_effect=unknown_status):
            view = self.resume_view((1, 7, 9, 11))
        self.assertIn('续跑结果未知', view.resume_detail)
        self.assertFalse(self.adapter.resume.has_waiting)
        self.assertEqual(len(harness.recovery_calls), 1)
        self.assertTrue(any('取消等待中的 CH11、CH09' in entry.message for entry in self.events))

    def test_qt_postrun_queue_does_not_dispatch_on_refresh_after_workspace_exit_request(self):
        harness, _, _ = self.start_resume_series()
        closing = Event()
        self.adapter.workspace_close_requested = closing.is_set
        closing.set()
        harness.recovery_gates[7].set()
        self.wait_for(lambda: self.adapter.jobs_idle)
        self.adapter.poll()
        self.assertTrue(self.adapter.idle)
        self.assertFalse(self.adapter.resume.has_waiting)
        self.assertEqual(len(harness.recovery_calls), 1)
        self.assertTrue(any('工作区正在关闭，取消等待中的 CH11、CH09' in entry.message for entry in self.events))

    def push_payload(self, url):
        save_push_project_name(self.workspace, self.context)
        draft = self.adapter.configuration_command('open', {})
        push = dict(draft.values['push'], dingtalk_flag='0', webhook=url,
            secret='push-private-signature-fixture', at_all='1')
        return dict(token=draft.token, revision=draft.revision, values=push)

    def test_push_trial_uses_original_adapters_frozen_draft_and_saved_project_name(self):
        from webhook_fakes import DINGTALK, FEISHU, response
        payload = self.push_payload(DINGTALK)
        project_config = self.context.config_dir / 'test_project_config.ini'
        push_config = self.context.config_dir / 'config.ini'
        original = (project_config.read_bytes(), push_config.read_bytes())
        for url, platform, field, reply in ((DINGTALK, 'dingtalk', 'text', {'errcode': 0}),
                (FEISHU, 'feishu', 'content', {'code': 0})):
            with self.subTest(platform=platform):
                payload['values']['webhook'] = url
                opener = response(reply)
                other = 'dingtalk' if platform == 'feishu' else 'feishu'
                with patch(f'src.core.{other}_robot.build_opener', side_effect=AssertionError('wrong platform')) as wrong, \
                     patch(f'src.core.{platform}_robot.build_opener', return_value=opener):
                    confirmation = self.adapter.configuration_command('push_preview', payload)
                    self.assertIn('已保存试发项目', confirmation['summary'])
                    self.assertIn('@所有人：开启', confirmation['summary'])
                    self.assertNotIn('demo-token', confirmation['summary'])
                    self.assertNotIn('push-private-signature-fixture', confirmation['summary'])
                    opener.open.assert_not_called()
                    payload['values']['webhook'] = 'invalid mutated value'
                    decision = dict(token=payload['token'], confirmation=confirmation['confirmation'])
                    self.adapter.configuration_command('push_execute', decision)
                    self.wait_for(lambda: self.adapter.ready_to_close)
                    with self.assertRaisesRegex(CapabilityError, '确认已失效'):
                        self.adapter.configuration_command('push_execute', decision)
                opener.open.assert_called_once()
                wrong.assert_not_called()
                request = opener.open.call_args.args[0]
                body = json.loads(request.data)
                self.assertIn('项目：已保存试发项目', str(body[field]))
                self.assertTrue(body['at']['isAtAll'] if platform == 'dingtalk' else '<at user_id="all">' in body[field]['text'])
                self.assertEqual(opener.open.call_args.kwargs['timeout'], 10)
                self.assertEqual(self.adapter.push_trial.snapshot().state, 'accepted')
        self.assertEqual((project_config.read_bytes(), push_config.read_bytes()), original)
        self.assertFalse(self.adapter.jobs)
        self.assertFalse(self.workspace.resources.owners)
        self.assertNotIn('demo-token', str(self.events))
        self.assertNotIn('push-private-signature-fixture', str(self.events))

    def test_push_trial_decline_source_and_conflicting_saved_configuration_prevent_dispatch(self):
        from webhook_fakes import FEISHU
        payload = self.push_payload(FEISHU)
        with patch('src.services.qt_push_trial.send_test_message') as send:
            prepared = self.adapter.configuration_command('push_preview', payload)
            decision = dict(token=payload['token'], confirmation=prepared['confirmation'])
            self.adapter.configuration_command('push_cancel', decision)
            with self.assertRaisesRegex(CapabilityError, '确认已失效'):
                self.adapter.configuration_command('push_execute', decision)
            with self.assertRaisesRegex(CapabilityError, '当前来源'):
                self.adapter.capabilities.execute('notifications.editor.preview', payload,
                    CapabilityAuthority('remote-fixture', 'session', 'request', (), source='feishu'))
            with self.assertRaisesRegex(CapabilityError, 'Webhook'):
                self.adapter.configuration_command('push_preview', dict(payload, values=dict(payload['values'], webhook='bad')))
            prepared = self.adapter.configuration_command('push_preview', payload)
            path = self.adapter.push_trial.project_path
            path.write_bytes(path.read_bytes() + b'\n# saved file changed\n')
            with self.assertRaisesRegex(CapabilityError, '配置已变化'):
                self.adapter.configuration_command('push_execute', dict(decision, confirmation=prepared['confirmation']))
            send.assert_not_called()

    def test_push_trial_unknown_response_waits_for_close_without_fencing_dut(self):
        from threading import Event
        from webhook_fakes import FEISHU
        payload = self.push_payload(FEISHU)
        entered, release = Event(), Event()
        self.addCleanup(release.set)

        def send(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError('fixture not released')
            raise RuntimeError('网络超时，发送结果未知 push-private-signature-fixture')

        with patch('src.services.qt_push_trial.send_test_message', side_effect=send) as sender:
            prompt = self.adapter.configuration_command('push_preview', payload)
            self.adapter.configuration_command('push_execute', dict(token=payload['token'], confirmation=prompt['confirmation']))
            self.assertTrue(entered.wait(3))
            self.assertTrue(self.adapter.idle)
            self.assertFalse(self.adapter.ready_to_close)
            with self.assertRaisesRegex(CapabilityError, '正在发送'):
                self.adapter.configuration_command('close', dict(token=payload['token']))
            with self.assertRaisesRegex(CapabilityError, '仍在进行'):
                self.adapter.configuration_command('push_preview', payload)
            release.set()
            self.wait_for(lambda: self.adapter.ready_to_close)
            sender.assert_called_once()
        outcome = self.adapter.push_trial.snapshot()
        self.assertEqual(outcome.state, 'unknown')
        self.assertIn('发送结果未知', outcome.message)
        self.assertNotIn('push-private-signature-fixture', outcome.message)
        self.assertFalse(self.workspace.resources.unknown_for(self.context.identity.project_id))

    def version_payload(self, channel=7, prompt='>'):
        draft = self.adapter.configuration_command('open', {})
        telnet = dict(draft.values['telnet'], login_success_flag=prompt,
            login_after_input_str='fixture shell', password='version-private-fixture', port=2323)
        return dict(token=draft.token, revision=draft.revision, channel=channel, telnet=telnet)

    def test_version_uses_original_query_on_one_frozen_draft_target(self):
        from test_device_project_info_service import _FakeTelnetSession
        from src.services.device_project_info_service import DEVICEINFO_COMMAND, PROC_VERSION_COMMAND
        payload = self.version_payload()
        config = self.context.config_dir / 'test_project_config.ini'
        original = config.read_bytes()
        fake = _FakeTelnetSession([
            "option software_version 'S7'\noption inner_sw_version 'T7'\n",
            'Linux version #1 SMP Mon Jun 8 10:16:25 UTC 2026\n',
        ])
        with patch('src.services.device_project_info_service.TelnetSession', return_value=fake) as telnet:
            prompt = self.adapter.configuration_command('version_preview', payload)
            self.assertIn('CH07', prompt['summary'])
            self.assertIn('fixture shell', prompt['summary'])
            self.assertNotIn('version-private-fixture', prompt['summary'])
            telnet.assert_not_called()
            payload['telnet']['login_after_input_str'] = 'changed after preview'
            payload['channel'] = 1
            approved = dict(token=payload['token'], confirmation=prompt['confirmation'])
            view = self.adapter.configuration_command('version_execute', approved)
            self.wait_for(lambda: self.adapter.idle)
            with self.assertRaisesRegex(CapabilityError, '确认已失效'):
                self.adapter.configuration_command('version_execute', approved)
        self.adapter.poll()
        self.assertTrue(fake.closed)
        self.assertEqual(fake.sent_lines[-3:], ['fixture shell', DEVICEINFO_COMMAND, PROC_VERSION_COMMAND])
        self.assertEqual(telnet.call_args.kwargs['bind_ip'], '192.0.2.7')
        self.assertEqual(telnet.call_args.kwargs['device_port'], 2323)
        self.assertEqual(fake.sent_lines[1], 'version-private-fixture')
        result = self.adapter.version_query.snapshot()
        self.assertEqual((result.state, result.active, result.channel), ('succeeded', False, 7))
        self.assertEqual(result.values, ('S7', 'T7', 'Mon Jun 8 10:16:25 UTC 2026'))
        job = self.adapter.jobs[view.job_id]['status']
        self.assertEqual(job['capability_id'], 'device.version')
        self.assertNotIn('version-private-fixture', str(job['request']))
        self.assertNotIn('version-private-fixture', str(self.events))
        self.assertEqual(config.read_bytes(), original)

    def test_version_confirmation_decline_scope_and_external_config_changes_prevent_dispatch(self):
        payload = self.version_payload()
        preview = lambda: self.adapter.configuration_command('version_preview', payload)
        prompt = preview()
        approved = dict(token=payload['token'], confirmation=prompt['confirmation'])
        self.adapter.configuration_command('version_cancel', approved)
        with self.assertRaisesRegex(CapabilityError, '确认已失效'):
            self.adapter.configuration_command('version_execute', approved)
        with self.assertRaises(CapabilityError):
            self.adapter.capabilities.execute('version.editor.preview', payload,
                CapabilityAuthority('remote-fixture', 'session', 'request', (7,), source='feishu'))
        with self.assertRaisesRegex(CapabilityError, '未启用'):
            self.adapter.configuration_command('version_preview', dict(payload, channel=6))
        prompt = preview()
        config = self.context.config_dir / 'test_project_config.ini'
        config.write_bytes(config.read_bytes() + b'\n# configuration changed before approval\n')
        with self.assertRaises(CapabilityError):
            self.adapter.configuration_command('version_execute', dict(approved, confirmation=prompt['confirmation']))
        self.assertFalse(self.adapter.jobs)

    def test_version_no_login_after_confirmation_for_hash_and_waits_for_read_cleanup(self):
        from threading import Event
        payload = self.version_payload(prompt='#')
        payload['telnet']['port'] = 0
        prompt = self.adapter.configuration_command('version_preview', payload)
        self.assertEqual(prompt['summary'], '')
        entered, release = Event(), Event()
        self.addCleanup(release.set)

        def query(request, emit):
            entered.set()
            if not release.wait(5):
                raise AssertionError('fixture was not released')
            raise RuntimeError('fixture failure version-private-fixture')

        with patch('src.services.qt_version_query.query_device_project_info', side_effect=query):
            self.adapter.configuration_command('version_execute', dict(token=payload['token'], confirmation=prompt['confirmation']))
            self.assertTrue(entered.wait(3))
            self.assertTrue(self.adapter.version_query.snapshot().active)
            with self.assertRaisesRegex(CapabilityError, '仍在收尾'):
                self.adapter.configuration_command('close', dict(token=payload['token']))
            self.assertTrue(self.workspace.resources.owners)
            release.set()
            self.wait_for(lambda: self.adapter.idle)
        self.adapter.poll()
        view = self.adapter.version_query.snapshot()
        self.assertEqual((view.state, view.values, view.error), ('failed', (), 'fixture failure ***'))
        self.assertFalse(self.workspace.resources.owners)
        self.adapter.configuration_command('close', dict(token=payload['token']))
        self.adapter.configuration_command('open', {})
        self.assertIsNone(self.adapter.version_query.snapshot())

    def test_pretest_executes_frozen_unsaved_draft_once_per_selected_channel_with_original_runner(self):
        from types import SimpleNamespace
        from test_test_item_pretest import Session
        payload = self.pretest_payload()
        config = self.context.config_dir / 'test_project_config.ini'
        original = config.read_bytes()
        sessions = [Session({'fixture draft command': 'MATCHED\n#'}), Session({'fixture draft command': 'wrong\n#'})]
        with patch('src.services.test_item_pretest_service.TelnetSession', side_effect=sessions) as telnet, \
                patch('src.services.test_item_pretest_service.prepare_network_for_sample', return_value=SimpleNamespace(ok=True)) as net:
            prompt = self.adapter.configuration_command('pretest_preview', payload)
            self.assertIn('channel_1', prompt['summary'])
            self.assertIn('channel_7', prompt['summary'])
            self.assertNotIn('fixture-private-password', prompt['summary'])
            self.assertFalse(telnet.called)
            pending = self.adapter.pretest.pending.request
            self.assertEqual(pending.order.items[0].retry_times, 1)
            self.assertEqual(pending.order.command_fail_retry_interval_time, 0)
            payload['order']['items'][0]['command'] = 'different command after confirmation'
            run = self.adapter.configuration_command('pretest_execute',
                dict(token=payload['token'], confirmation=prompt['confirmation']))
            self.wait_for(lambda: self.adapter.idle)
        self.adapter.poll()
        self.assertEqual([session.sent[-1] for session in sessions], ['fixture draft command'] * 2)
        self.assertTrue(all(session.sent.count('fixture draft command') == 1 and session._closed for session in sessions))
        self.assertEqual(net.call_count, 2)
        self.assertEqual([call.kwargs['bind_ip'] for call in telnet.call_args_list],
                         [channel.network_card_ip for channel in pending.channels])
        result = self.adapter.jobs[run]['status']['result']['result']
        self.assertEqual((result['executed'], result['passed'], result['failed']), (2, 1, 1))
        view = self.resume_view()
        self.assertEqual((view.run_id, view.success_count, view.failure_count, view.count_unit),
                         (run, 1, 1, '条命令'))
        self.assertTrue(any(entry.level == 'SUCCESS' and '匹配通过' in entry.message for entry in self.events))
        self.assertTrue(any(entry.level == 'ERROR' and '期望不匹配' in entry.message for entry in self.events))
        self.assertEqual(config.read_bytes(), original)
        self.assertNotIn('fixture-private-password', str(self.adapter.jobs[run]['status']['request']))

    def test_pretest_decline_and_stale_configuration_prevent_dispatch_and_gate_remote_source(self):
        payload = self.pretest_payload()
        token = payload['token']
        draft = self.adapter.configuration_command('pretest_preview', payload)
        self.adapter.configuration_command('pretest_cancel', dict(token=token))
        approval = dict(token=token, confirmation=draft['confirmation'])
        with self.assertRaisesRegex(CapabilityError, '确认已失效'):
            self.adapter.configuration_command('pretest_execute', approval)
        draft = self.adapter.configuration_command('pretest_preview', payload)
        approval['confirmation'] = draft['confirmation']
        remote = CapabilityAuthority('remote', 'session', 'operation', (), source='feishu', approved=True)
        with self.assertRaisesRegex(CapabilityError, '来源'):
            self.adapter.capabilities.execute('pretest.editor.execute', approval, remote)
        config = self.context.config_dir / 'test_project_config.ini'
        config.write_bytes(config.read_bytes() + b'\n# changed\n')
        with self.assertRaises(CapabilityError):
            self.adapter.configuration_command('pretest_execute', approval)
        self.assertFalse(self.adapter.jobs)

    def test_pretest_stop_waits_for_original_worker_before_closing_editor(self):
        import threading
        from src.models.test_item_pretest_models import PretestResult
        payload = self.pretest_payload()
        token = dict(token=payload['token'])
        entered, stopping, release = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def runner(request, cancel, emit):
            entered.set()
            if cancel.wait(4):
                stopping.set()
            release.wait(4)
            emit('模拟日志已收尾', 'warning')
            return PretestResult(2, 1, unchecked=1, cancelled=cancel.is_set())

        with patch('src.services.qt_pretest.run_pretest', side_effect=runner):
            draft = self.adapter.configuration_command('pretest_preview', payload)
            run = self.adapter.configuration_command('pretest_execute', dict(token, confirmation=draft['confirmation']))
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.adapter.configuration_command('pretest_stop', token)['state'], 'stop_requested')
            self.assertTrue(stopping.wait(2))
            self.assertFalse(self.adapter.idle)
            with self.assertRaisesRegex(CapabilityError, '仍在收尾'):
                self.adapter.configuration_command('close', token)
            release.set()
            self.wait_for(lambda: self.adapter.idle)
        self.adapter.poll()
        self.assertEqual(self.adapter.jobs[run]['status']['state'], 'stopped')
        self.assertIn('未执行 1', self.adapter.pretest.snapshot()[3])
        self.adapter.configuration_command('close', token)
        self.assertFalse(self.adapter.configuration.opened)

    def test_pretest_unchecked_outcome_is_never_reported_as_test_success(self):
        from src.models.test_item_pretest_models import PretestResult
        payload = self.pretest_payload()
        with patch('src.services.qt_pretest.run_pretest', return_value=PretestResult(2, 2, unchecked=2)):
            draft = self.adapter.configuration_command('pretest_preview', payload)
            run = self.adapter.configuration_command('pretest_execute',
                dict(token=payload['token'], confirmation=draft['confirmation']))
            self.wait_for(lambda: self.adapter.idle)
        self.adapter.poll()
        result = self.adapter.jobs[run]['status']['result']
        self.assertFalse(result['ok'])
        self.assertEqual(result['outcome'], 'unchecked')
        self.assertEqual(self.adapter.pretest.snapshot()[1:3], ('unchecked', False))
        view = self.resume_view()
        self.assertEqual((view.run_id, view.state, view.success_count, view.failure_count, view.count_unit),
                         (run, 'unchecked', 0, 0, '条命令'))
        item = self.adapter.jobs[run]
        with patch.object(self.adapter, 'poll'):
            for incomplete in ('old text', {'result': 'old text'}, {'result': {'passed': 2}}):
                with patch.dict(item['status'], result=incomplete):
                    old = self.resume_view()
                    self.assertEqual((old.success_count, old.failure_count, old.count_unit), (None, None, ''))
            later = dict(item, status=dict(item['status'], capability_id='aging.start', state='succeeded', result={}))
            with patch.dict(self.adapter.jobs, {'later-job': later}), patch.object(self.adapter, 'latest', 'later-job'):
                following = self.resume_view()
                self.assertEqual((following.run_id, following.state), ('later-job', 'completed'))
                self.assertEqual((following.success_count, following.failure_count), (None, None))

    def test_single_channel_completion_uses_actual_terminal_state(self):
        configure_project(self.workspace, self.context, (1,))
        identifier = self.start()
        self.assertEqual([c.section for c in self.engine.calls[0][0].channels], ['channel_1'])
        self.engine.finish.set()
        self.wait_for(lambda: self.adapter.idle)
        self.adapter.poll()
        self.assertEqual(self.adapter.jobs[identifier]['status']['state'], 'succeeded')
        self.assertNotIn(identifier, self.adapter.capabilities.jobs.controls)
        self.assertFalse(self.workspace.resources.owners)
