from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import Mock

from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.models.app_update import AppUpdateCheckResult, ReleaseAsset, UpdateCheckStatus
from src.services.capability_service import CapabilityService
from line_check_assistant.test_item_config_store import TestItemConfigStore, TestProjectConfig


class ApplicationCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.snapshot = dict(channels=[dict(section='channel_1', vlan_name='vlan116', adapter_alias='vlan116',
            serial_port='COM16', network_card_ip='192.168.1.116', device_manage_ip='192.168.1.1', enabled=True)],
            upgrade_settings={}, configuration_editor_open=False)
        self.manager = Mock()
        self.runtime = CapabilityService(self.root / 'runtime', self.manager, lambda: self.snapshot, tool_root=self.root)
        self.auth = CapabilityAuthority('local', 'session', 'request', (1,), mode='full_access', grant_id='grant')
        self.store = self.runtime.configuration.store
        config = TestProjectConfig()
        config.telnet.password = 'synthetic-secret'
        self.store.save(config)

    def tearDown(self):
        self.runtime.jobs.begin_close()
        self.wait()
        self.runtime.observations.close_all()
        self.runtime.jobs.close()
        self.temp.cleanup()

    def wait(self):
        deadline = time.monotonic() + 3
        while not self.runtime.jobs.idle and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertTrue(self.runtime.jobs.idle)

    def patch(self, domain, values, **extra):
        before = self.runtime.execute('configuration.read', dict(domain=domain), self.auth)
        return self.runtime.execute('configuration.' + domain + '.patch', dict(revision=before['revision'], values=values, **extra), self.auth)

    def test_configuration_uses_same_gui_store_and_preserves_omitted_secret(self):
        before = self.runtime.execute('configuration.read', dict(domain='telnet'), self.auth)
        self.assertNotIn('synthetic-secret', str(before))
        self.patch('telnet', {'login_after_input_str': '', 'only_power_off_on': 1})
        actual = TestItemConfigStore(self.store.config_path).load()
        self.assertEqual('', actual.telnet.login_after_input_str)
        self.assertEqual('synthetic-secret', actual.telnet.password)
        self.assertEqual(0, actual.telnet.telnet_need_enter_password_flag)

    def test_configuration_rejects_stale_revision_and_open_editor(self):
        before = self.runtime.configuration.read(dict(domain='project_info'), self.auth)
        self.patch('project_info', {'project_name': 'other writer'})
        with self.assertRaises(CapabilityError):
            self.runtime.execute('configuration.project_info.patch', dict(revision=before['revision'], values={'project_name': 'stale'}), self.auth)
        self.snapshot['configuration_editor_open'] = True
        with self.assertRaises(CapabilityError) as error:
            self.patch('project_info', {'project_name': 'overwrite draft'})
        self.assertEqual('editor_open', error.exception.code)
        self.assertEqual('other writer', self.store.load().project_info.project_name)

    def test_configuration_order_remains_data_until_explicit_test_execution(self):
        self.patch('order', dict(command_fail_retry_interval_time=17, items=[dict(command='echo synthetic', retry_times=2,
            expected_segments=[dict(text='synthetic', negate=False)])]))
        actual = self.store.load()
        self.assertEqual(17, actual.order.command_fail_retry_interval_time)
        self.assertEqual('echo synthetic', actual.order.items[0].command)
        self.manager.acquire_control.assert_not_called()
        with self.assertRaises(CapabilityError):
            self.patch('telnet', dict(telnet_need_enter_password_flag=1))

    def test_remote_identity_cannot_modify_global_test_configuration(self):
        with self.assertRaises(CapabilityError):
            self.runtime.execute('configuration.read', dict(domain='telnet'), replace(self.auth, source='feishu'))

    def test_passive_monitor_never_claims_device_business_and_closes_only_own(self):
        self.runtime.resources.acquire('aging', ('device-business',))
        try:
            self.runtime.execute('serial.monitor.open', dict(channel_ids=[1]), self.auth)
            self.manager.acquire_control.assert_not_called()
            call = self.manager.acquire_monitor.call_args
            self.assertEqual('COM16', call[0][1].port)
            self.runtime.execute('serial.monitor.close', dict(channel_ids=[1]), replace(self.auth, principal='another-user'))
            self.manager.release.assert_not_called()
            self.runtime.execute('serial.monitor.close', dict(channel_ids=[1]), self.auth)
            self.manager.release.assert_called_once_with(call[0][0], 'COM16', wait=False)
        finally:
            self.runtime.resources.release('aging')

    def test_wifi_log_uses_current_attempt_and_never_previous_directory_file(self):
        old = self.root / 'Auto_power_on_off_tool/test_results/device_1/device_1_wifi_99999999.log'
        old.parent.mkdir(parents=True)
        old.write_text('old attempt', encoding='utf-8')
        value = self.runtime.execute('logs.wifi', dict(channel_ids=[1]), self.auth)
        self.assertEqual('missing', value['items'][0]['state'])
        current = self.root / 'current.log'
        current.write_text('current attempt', encoding='utf-8')
        self.snapshot['current_wifi_logs'] = {'1': str(current)}
        self.assertEqual('current attempt', self.runtime.execute('logs.wifi', dict(channel_ids=[1]), self.auth)['items'][0]['content'])

    def test_update_download_uses_original_verified_result_without_model_supplied_url(self):
        directory = self.root / 'line_check_assistant/packaging_assets'
        directory.mkdir(parents=True)
        (directory / 'VERSION_INFO.txt').write_text('版本：V1.2.10', encoding='utf-8')
        self.runtime.updates.updater = Mock()
        update = AppUpdateCheckResult(UpdateCheckStatus.UPDATE_AVAILABLE, '1.2.10', '1.2.11', '', '',
            'https://example.invalid/release', ReleaseAsset('LineCheckAssistant_portable.zip', 'https://example.invalid/package.zip', 100), 'a' * 64)
        self.runtime.updates.updater.check_for_update.return_value = update
        self.runtime.updates.updater.download_update.side_effect = lambda update, path, *a, **kw: path
        checked = self.runtime.execute('updates.check', {}, self.auth)
        self.wait()
        result = self.runtime.execute('updates.download', dict(check_job_id=checked['job_id']), replace(self.auth, operation_id='download'))
        self.wait()
        actual = self.runtime.jobs.status(result['job_id'], self.auth)
        self.assertEqual('succeeded', actual['state'])
        self.assertFalse(actual['result']['executed'])
        self.assertEqual(Path(actual['result']['path']).name, 'DUTPilot_portable.zip')
        self.assertTrue(Path(actual['result']['path']).is_relative_to(self.runtime.files.workspace))
        with self.assertRaises(CapabilityError):
            self.runtime.execute('updates.download', dict(check_job_id=checked['job_id'], url='https://arbitrary.invalid'), self.auth)

    def test_job_submission_admission_does_not_block_gui_database_read(self):
        pending, release = threading.Event(), threading.Event()
        def recheck():
            pending.set()
            self.assertTrue(release.wait(2))
        result, errors = [], []
        def submit():
            try:
                result.append(self.runtime.jobs.start('fake', dict(channel_ids=[1]), self.auth, (),
                    lambda context: dict(ok=True), recheck=recheck))
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=submit)
        thread.start()
        try:
            self.assertTrue(pending.wait(2))
            # This is the same mutex used by the main-thread management refresh.
            self.assertTrue(self.runtime.jobs.lock.acquire(timeout=.2))
            self.runtime.jobs.lock.release()
        finally:
            release.set()
            thread.join(3)
        self.assertEqual([], errors)
        self.wait()
        with self.assertRaises(CapabilityError):
            self.runtime.jobs.status(result[0]['job_id'], replace(self.auth, channels=()))

    def test_phase_rollback_disables_modules_without_removing_old_gui_engines(self):
        runtime = CapabilityService(self.root / 'rollback', self.manager, lambda: self.snapshot,
            tool_root=self.root, enabled_modules=())
        try:
            self.assertIsNone(runtime.devices)
            self.assertEqual('firmware.upgrade', runtime.registry.get('firmware.upgrade').capability_id)
            for identifier in ('power.on', 'parameters.write', 'onu.register', 'configuration.telnet.patch', 'updates.check'):
                with self.subTest(identifier=identifier), self.assertRaises(CapabilityError):
                    runtime.execute(identifier, dict(channel_ids=[1]), self.auth)
            with self.assertRaises(CapabilityError):
                runtime.extensions.approve({}, '', 'local')
        finally:
            runtime.jobs.close()

    def test_notifications_require_local_destination_review_preserve_secrets_and_merge_original_store(self):
        from src.services.message_push_config_service import MessagePushConfigService
        initial = self.runtime.execute('notifications.read', {}, self.auth)
        arguments = dict(revision=initial['revision'], values=dict(enabled=True,
            webhook='https://oapi.dingtalk.com/robot/send?access_token=synthetic-token', secret='synthetic-signing-key', at_all=False))
        with self.assertRaises(CapabilityError) as caught:
            self.runtime.execute('notifications.patch', arguments, self.auth)
        self.assertEqual('local_scope_approval_required', caught.exception.code)
        scope = self.runtime.notifications.scope(arguments, patch=True)
        self.assertNotIn('synthetic-token', str(scope))
        self.runtime.scopes.grant(self.auth.principal, scope, 'real-local-reviewer')
        saved = self.runtime.execute('notifications.patch', arguments, self.auth)
        self.assertNotIn('synthetic-signing-key', str(saved))
        self.assertTrue(MessagePushConfigService(self.runtime.notifications.store.config_path).load()['dingtalk_flag'] == '1')
        disabled = self.runtime.execute('notifications.patch', dict(revision=saved['revision'], values=dict(enabled=False)), self.auth)
        self.assertFalse(disabled['enabled'])
        self.assertEqual('synthetic-signing-key', self.runtime.notifications.store.load()['secret'])
        with self.assertRaises(CapabilityError):
            self.runtime.execute('notifications.patch', dict(revision=saved['revision'], values=dict(enabled=True)), self.auth)

    def test_notification_trial_uses_fake_original_sender_once_and_distinguishes_acceptance_from_delivery(self):
        from unittest.mock import patch
        self.runtime.notifications.store.save(dict(dingtalk_flag='0', webhook='https://oapi.dingtalk.com/robot/send?access_token=synthetic-token',
            secret='synthetic-secret', at_all='0'))
        status = self.runtime.execute('notifications.read', {}, self.auth)
        arguments = dict(revision=status['revision'])
        self.runtime.scopes.grant(self.auth.principal, self.runtime.notifications.scope(arguments), 'real-local-reviewer')
        with patch('src.services.capability_notification_service.send_test_message', return_value='钉钉') as send:
            first = self.runtime.execute('notifications.test', arguments, self.auth)
            self.wait()
            second = self.runtime.execute('notifications.test', arguments, self.auth)
            self.assertEqual(first['job_id'], second['job_id'])
            send.assert_called_once()
            result = self.runtime.jobs.status(first['job_id'], self.auth)
            self.assertTrue(result['result']['accepted'])
            self.assertIn('核对', result['result']['delivery'])
            self.assertNotIn('synthetic-secret', str(result))
        with self.assertRaises(CapabilityError):
            self.runtime.execute('notifications.test', arguments, replace(self.auth, source='feishu'))

    def test_notification_editor_and_broadcast_change_do_not_reuse_old_authorization(self):
        self.runtime.notifications.store.save(dict(webhook='https://oapi.dingtalk.com/robot/send?access_token=synthetic-token'))
        status = self.runtime.execute('notifications.read', {}, self.auth)
        arguments = dict(revision=status['revision'], values=dict(enabled=True))
        scope = self.runtime.notifications.scope(arguments, patch=True)
        self.runtime.scopes.grant(self.auth.principal, scope, 'real-local-reviewer')
        self.snapshot['configuration_editor_open'] = True
        with self.assertRaises(CapabilityError) as caught:
            self.runtime.execute('notifications.patch', arguments, self.auth)
        self.assertEqual('editor_open', caught.exception.code)
        self.snapshot['configuration_editor_open'] = False
        with self.assertRaises(CapabilityError) as caught:
            self.runtime.execute('notifications.patch', dict(arguments, values=dict(enabled=True, at_all=True)), self.auth)
        self.assertEqual('local_scope_approval_required', caught.exception.code)

    def test_invalid_legacy_notification_target_can_be_disabled_without_sending_or_granting_scope(self):
        self.runtime.notifications.store.save(dict(dingtalk_flag='1', webhook='invalid old field', secret='saved-secret'))
        value = self.runtime.execute('notifications.read', {}, self.auth)
        self.assertFalse(value['destination_valid'])
        updated = self.runtime.execute('notifications.patch', dict(revision=value['revision'], values=dict(enabled=False)), self.auth)
        self.assertFalse(updated['enabled'])
        self.assertEqual('saved-secret', self.runtime.notifications.store.load()['secret'])

    def test_default_order_draft_matches_shared_gui_loader_and_preserves_retry_until_explicit_save(self):
        from dataclasses import asdict
        from line_check_assistant.test_item_config_store import OrderConfig, OrderItem
        from src.services.capability_configuration_service import load_default_order
        default_path = self.runtime.configuration.directory / 'test_project_config.default.ini'
        template = TestProjectConfig(order=OrderConfig(command_fail_retry_interval_time=99, items=[OrderItem(command='echo default', retry_times=2)]))
        TestItemConfigStore(default_path).save(template)
        current = self.store.load()
        current.order.command_fail_retry_interval_time = 17
        current.order.items = [OrderItem(command='echo user draft')]
        self.store.save(current)
        before = self.store.config_path.read_bytes()
        result = self.runtime.execute('configuration.defaults.prepare', {}, self.auth)
        self.assertFalse(result['saved'])
        self.assertEqual(before, self.store.config_path.read_bytes())
        self.assertEqual(asdict(load_default_order(default_path))['items'], result['arguments']['values']['items'])
        self.runtime.execute(result['capability_id'], result['arguments'], self.auth)
        self.assertEqual('echo default', self.store.load().order.items[0].command)
        self.assertEqual(17, self.store.load().order.command_fail_retry_interval_time)

    def test_resource_refresh_uses_current_enumeration_while_aging_keeps_ownership(self):
        self.runtime.host.serial_provider = Mock(return_value=['COM16', 'COM102'])
        self.runtime.host.adapter_provider = Mock(return_value=['VLAN116'])
        self.runtime.resources.acquire('aging', ('device-business',))
        try:
            result = self.runtime.execute('resources.refresh', {}, self.auth)
            self.assertEqual(['COM16', 'COM102'], result['serial_ports'])
            self.assertEqual(['VLAN116'], result['adapters'])
            self.assertFalse(result['selection_changed'])
            self.assertTrue(self.runtime.resources.busy)
            self.manager.acquire_control.assert_not_called()
            self.manager.acquire_monitor.assert_not_called()
        finally:
            self.runtime.resources.release('aging')
