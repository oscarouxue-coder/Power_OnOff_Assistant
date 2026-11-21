"""Qt DUT admission and original batches, without real network or hardware."""
from dataclasses import replace
from pathlib import Path
import json
import tempfile
import time
import unittest
from unittest.mock import patch

from qt_execution_fakes import configure_project
from qt_dut_fakes import DutHarness
from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.services.qt_execution_adapter import QtExecutionAdapter
from src.services.workspace_service import WorkspaceService


SOURCE = Path(__file__).resolve().parents[1]


class QtDutConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='qt-dut-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.workspace = WorkspaceService(SOURCE, directory=root / 'workspace')
        self.context = self.workspace.projects.create(root / 'project', 'DUT mock project')
        self.workspace.status.attach(self.context)
        self.identities = configure_project(self.workspace, self.context)
        self.logs = []
        self.execution = QtExecutionAdapter(self.workspace, self.context, self.logs.append)
        self.fake = DutHarness()
        self.addCleanup(self.cleanup_runtime)
        for target, effect in (
            ('src.services.qt_dut_configuration.run_dut_telnet_enable_batch', self.fake.enable_batch),
            ('src.services.qt_dut_configuration.run_dut_status_query_batch', self.fake.query_batch),
            ('src.core.network_adapter.read_adapter_identities', lambda: self.identities),
            ('serial.Serial', AssertionError('physical serial forbidden')),
            ('socket.create_connection', AssertionError('physical network forbidden')),
        ):
            handle = patch(target, side_effect=effect)
            handle.start()
            self.addCleanup(handle.stop)
        self.snapshot = self.execution.dut_command('show', {})
        self.token = self.snapshot['token']

    def cleanup_runtime(self):
        self.fake.release.set()
        self.execution.begin_close()
        self.wait(lambda: self.execution.idle)
        self.execution.close()
        for project in tuple(self.workspace.projects.opened.values()):
            self.workspace.projects.close(project)
        self.workspace.close()

    def wait(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.01)
        self.fail('original DUT job did not reach expected state')

    def preview(self, action='enable', ids=None, parallel=1):
        return self.execution.dut_command('preview', dict(token=self.token, action=action,
            channel_ids=ids or [1, 7], username='fixture-user', password='fixture-private-password', parallel_count=parallel))

    def start(self, action='enable', ids=None, parallel=1):
        preview = self.preview(action, ids, parallel)
        self.execution.dut_command('execute', dict(token=self.token, confirmation=preview['confirmation']))
        return self.execution.dut.latest

    def finish(self):
        self.wait(lambda: self.execution.idle)
        self.execution.poll()
        return self.execution.dut_command('poll', dict(token=self.token))

    def test_show_has_real_targets_and_never_connects_or_modifies_configuration(self):
        before = self.execution._binding()
        self.assertEqual([t['number'] for t in self.snapshot['targets']], [1, 7])
        self.assertFalse(self.fake.calls)
        self.assertFalse(self.fake.network_calls)
        self.assertEqual(self.execution._binding(), before)
        self.assertEqual(self.execution.dut_command('show', {})['token'], self.token)

    def test_original_services_receive_selected_requests_parallelism_and_safe_logs(self):
        before = self.execution._binding()
        identifier = self.start(ids=[7], parallel=3)
        status = self.finish()
        self.assertEqual(status['state'], 'succeeded')
        self.assertEqual(self.fake.workers, [3])
        self.assertEqual([r.channel for r in self.fake.calls], ['通道 7'])
        self.assertEqual(self.fake.calls[0].password, 'fixture-private-password')
        self.assertTrue(self.fake.network_calls[0][1]['reuse_if_ready'])
        self.assertEqual(status['rows'][0]['number'], 7)
        job = self.execution.capabilities.jobs.status(identifier, self.execution.jobs[identifier]['authority'])
        self.assertNotIn('fixture-private-password', json.dumps(job, ensure_ascii=False))
        self.assertNotIn('fixture-private-password', '\n'.join(v.message for v in self.logs))
        self.assertEqual(self.execution._binding(), before)
        self.assertIn('DUT', self.execution.present(self._project()).test_type)

    def _project(self):
        from src.models.workbench_presentation import ProjectView
        return ProjectView(self.context.identity.project_id, 'p', 'type', '', 'idle', '空闲', '', '', None, '')

    def test_current_status_preserves_unknowns_and_actual_service_result(self):
        self.start('query')
        state = self.finish()
        self.assertEqual(state['state'], 'succeeded')
        self.assertEqual(len(state['rows']), 2)
        self.assertTrue(all(row['settings']['tcp_port_open'] for row in state['rows']))
        self.assertEqual(self.fake.workers, [1])

    def test_cancel_expiry_config_change_and_replay_never_dispatch(self):
        confirmation = self.preview()
        self.execution.dut_command('cancel', dict(token=self.token))
        with self.assertRaises(CapabilityError):
            self.execution.dut_command('execute', dict(token=self.token, confirmation=confirmation['confirmation']))
        for kind in ('expiry', 'configuration'):
            confirmation = self.preview()
            original = self.execution.dut.pending
            if kind == 'expiry':
                self.execution.dut.pending = (*original[:2], time.monotonic() - 121, *original[3:])
            else:
                path = self.context.config_dir / 'config.ini'
                data = path.read_bytes()
                path.write_bytes(data + b'\n# changed\n')
            with self.assertRaises(CapabilityError):
                self.execution.dut_command('execute', dict(token=self.token, confirmation=confirmation['confirmation']))
            if kind == 'configuration':
                path.write_bytes(data)
        self.assertFalse(self.fake.calls)

    def test_unverified_nic_blocks_original_job_and_confirmation_is_consumed(self):
        confirmation = self.preview()
        with patch('src.core.network_adapter.read_adapter_identities', return_value=()):
            with self.assertRaisesRegex(CapabilityError, '网卡身份'):
                self.execution.dut_command('execute', dict(token=self.token, confirmation=confirmation['confirmation']))
        self.assertFalse(self.fake.calls)
        self.assertIsNone(self.execution.dut.pending)

    def test_stop_keeps_resource_ownership_until_original_worker_returns(self):
        self.fake.release.clear()
        identifier = self.start()
        self.assertTrue(self.fake.started.wait(3))
        self.execution.dut_command('stop', dict(token=self.token))
        self.assertTrue(self.fake.stop_seen.wait(3))
        self.assertFalse(self.execution.idle)
        self.assertTrue(self.workspace.resources.owners)
        with self.assertRaises(RuntimeError):
            self.execution.close()
        self.fake.release.set()
        self.assertEqual(self.finish()['state'], 'stopped')
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(len(self.execution.dut.rows), 2)

    def test_window_close_and_reopen_preserve_live_job_and_reject_old_token(self):
        self.fake.release.clear()
        identifier = self.start()
        self.assertTrue(self.fake.started.wait(3))
        self.execution.dut_command('detach', dict(token=self.token))
        self.assertFalse(self.execution.jobs[identifier]['authority'] is None)
        self.assertFalse(self.execution.capabilities.jobs.controls[identifier].is_set())
        with self.assertRaises(CapabilityError):
            self.execution.dut_command('poll', dict(token=self.token))
        self.snapshot = self.execution.dut_command('show', {})
        self.token = self.snapshot['token']
        self.assertEqual(self.snapshot['job_id'], identifier)
        self.fake.release.set()
        self.assertEqual(self.finish()['state'], 'succeeded')

    def test_gui_only_capabilities_do_not_grant_remote_or_ai_authority(self):
        auth = CapabilityAuthority('fixture', 's', 'o', (1, 7), source='gui', approved=True)
        for source in ('local', 'dingtalk', 'feishu'):
            with self.assertRaisesRegex(CapabilityError, '来源'):
                self.execution.capabilities.validate('dut.editor.poll', dict(token=self.token), replace(auth, source=source))
        self.assertEqual(self.execution.capabilities.registry.get('dut.editor.execute').risk, 'dangerous')

    def test_original_network_failure_has_no_retry_replay_and_unknown_write_outcome(self):
        self.fake.failure = True
        self.start()
        status = self.finish()
        self.assertEqual(status['state'], 'unknown')
        self.assertTrue(all(not row['ok'] for row in status['rows']))
        self.assertEqual(len(self.fake.calls), 2)
        with self.assertRaises(CapabilityError):
            self.preview()
        self.assertEqual(len(self.fake.calls), 2)

    def test_editors_and_unsaved_project_block_dut_admission(self):
        draft = self.execution.configuration_command('open', {})
        with self.assertRaisesRegex(CapabilityError, '编辑器'):
            self.preview()
        self.execution.configuration_command('close', dict(token=draft.token))
        path = self.context.config_dir / 'config.ini'
        data = path.read_bytes()
        path.write_bytes(data + b'\n# draft\n')
        with self.assertRaisesRegex(CapabilityError, '保存'):
            self.preview()
        path.write_bytes(data)

    def test_empty_disabled_duplicate_and_invalid_requests_never_dispatch(self):
        for channels in ([], [2], [1, 1]):
            with self.assertRaises(CapabilityError):
                self.execution.dut_command('preview', dict(token=self.token, action='enable',
                    channel_ids=channels, username='x', password='x', parallel_count=1))
        self.assertFalse(self.fake.calls)

    def test_job_request_and_targets_stay_bound_to_original_configuration(self):
        self.fake.release.clear()
        self.start('query', ids=[1])
        self.assertTrue(self.fake.started.wait(3))
        before = self.execution.dut_command('poll', dict(token=self.token))['targets']
        path = self.context.config_dir / 'network_card_ip.ini'
        data = path.read_bytes()
        path.write_bytes(data.replace(b'192.0.2.200', b'192.0.2.201'))
        self.assertEqual(self.execution.dut_command('poll', dict(token=self.token))['targets'], before)
        path.write_bytes(data)
        self.fake.release.set()
        self.finish()

    def test_later_power_job_is_not_reported_as_a_live_dut_batch(self):
        from qt_execution_fakes import ControlledPipeline
        self.start('query')
        self.finish()
        engine = ControlledPipeline()
        self.addCleanup(engine.finish.set)
        self.addCleanup(engine.release_stop.set)
        self.execution.capabilities.devices.pipeline_factory = engine.factory
        preview = self.execution.prepare('aging.start')
        self.execution.confirm(preview.token)
        self.assertTrue(engine.started.wait(3))
        snapshot = self.execution.dut_command('poll', dict(token=self.token))
        self.assertFalse(snapshot['active'])
        self.assertFalse(snapshot['can_execute'])
        self.assertFalse(self.execution.idle)
        engine.finish.set()
        self.wait(lambda: self.execution.idle)

    def test_show_loads_parameter_credentials_from_original_project_settings_file(self):
        from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings, SampleUpgradeSettingsStore

        path = self.context.config_dir / 'sample_upgrade_settings.ini'
        network = self.context.config_dir / 'network_card_ip.ini'
        store = SampleUpgradeSettingsStore(path)
        store.save(SampleUpgradeSettings(username='fixture-upgrade-user',
            parameter_initial_username='fixture-parameter-user',
            parameter_initial_password='fixture-parameter-private'))
        self.workspace.projects.save(self.context)
        original = path.read_bytes()
        original_network = network.read_bytes()
        result = self.execution.dut_command('show', {})
        self.assertEqual(result['username'], 'fixture-parameter-user')
        self.assertEqual(result['password'], 'fixture-parameter-private')
        self.assertEqual(network.read_bytes(), original_network)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(self.fake.calls)
        self.assertNotIn('fixture-parameter-private', '\n'.join(entry.message for entry in self.logs))

    def test_draft_credentials_survive_window_reopen_without_persisting(self):
        before = self.execution._binding()
        self.execution.dut_command('detach', dict(token=self.token, username='edited-user',
            password='edited-private-draft', parallel_count=4))
        snapshot = self.execution.dut_command('show', {})
        self.token = snapshot['token']
        self.assertEqual(snapshot['password'], 'edited-private-draft')
        self.assertEqual(snapshot['parallel_count'], 4)
        self.assertEqual(self.execution._binding(), before)
        self.assertFalse(self.fake.calls)

    def test_batch_exception_is_redacted_without_retry_or_false_success(self):
        with patch('src.services.qt_dut_configuration.run_dut_telnet_enable_batch',
                side_effect=RuntimeError('fixture-private-password failure')) as batch:
            identifier = self.start()
            status = self.finish()
        self.assertEqual(status['state'], 'unknown')
        self.assertEqual(batch.call_count, 1)
        self.assertNotIn('fixture-private-password', status['error'])
        result = self.execution.capabilities.jobs.status(identifier, self.execution.jobs[identifier]['authority'])
        self.assertNotIn('fixture-private-password', json.dumps(result))

    def test_confirmation_is_one_use_even_after_successful_execution(self):
        preview = self.preview()
        args = dict(token=self.token, confirmation=preview['confirmation'])
        self.execution.dut_command('execute', args)
        self.finish()
        with self.assertRaisesRegex(CapabilityError, '确认已失效'):
            self.execution.dut_command('execute', args)
        self.assertEqual(len(self.fake.calls), 2)

    def test_resource_denial_preserves_previous_result_without_dispatch(self):
        self.start('query')
        previous = self.finish()
        preview = self.preview()
        resources = self.execution.capabilities.resources
        resources.acquire('fixture-competing-job', ('device-business',))
        try:
            with self.assertRaises(CapabilityError):
                self.execution.dut_command('execute', dict(token=self.token, confirmation=preview['confirmation']))
        finally:
            resources.release('fixture-competing-job')
        current = self.execution.dut_command('poll', dict(token=self.token))
        self.assertEqual(current['rows'], previous['rows'])
        self.assertEqual(current['job_id'], previous['job_id'])
        self.assertEqual(len(self.fake.calls), 2)
