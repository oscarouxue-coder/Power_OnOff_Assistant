"""Temporary projects, original stores, no GUI/network/serial/message sends."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, PropertyMock

from line_check_assistant.legacy_ui_defaults_store import LegacyUiDefaultsStore
from line_check_assistant.test_item_config_store import TestItemConfigStore
from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.services.message_push_config_service import MessagePushConfigService
from src.services.qt_workspace_adapter import QtWorkspaceAdapter


SOURCE = Path(__file__).resolve().parents[1]


class QtConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='qt-config-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.adapter = QtWorkspaceAdapter(SOURCE, directory=self.root / 'workspace')
        self.addCleanup(self.cleanup_worker)
        self.results, self.logs = {}, []
        self.wait_for(lambda: (0, 'ready') in self.results)
        self.identifier = self.command('create', self.root / 'project', '配置项目').project_id
        self.context = self.adapter._service.projects.opened[self.identifier]

    def cleanup_worker(self):
        self.adapter.begin_close({p.project_id: 'discard' for p in self.adapter.take_updates()[0]})
        self.assertTrue(self.adapter.wait_closed(6))

    def wait_for(self, predicate):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            projects, logs, results = self.adapter.take_updates()
            self.logs.extend(logs)
            self.results.update({(r.identifier, r.operation): r for r in results})
            if predicate():
                return
            time.sleep(.01)
        self.fail('configuration command did not finish')

    def command(self, operation, *args, expected_error=False):
        request = self.adapter.submit(operation, *args)
        self.wait_for(lambda: (request, operation) in self.results)
        result = self.results[request, operation]
        self.assertEqual(bool(result.error), expected_error, result.error)
        return result

    def open(self):
        return self.command('configuration_open', self.identifier).payload

    def save(self, draft, values=None, expected_error=False):
        return self.command('configuration_save', self.identifier,
            dict(token=draft.token, revision=draft.revision, values=deepcopy(values or draft.values)), expected_error=expected_error)

    def bytes(self):
        return {path.name: path.read_bytes() for path in self.context.config_dir.iterdir() if path.is_file()}

    def test_open_cancel_and_gui_only_capabilities_never_expose_or_write_secrets(self):
        before = self.bytes()
        draft = self.open()
        self.assertEqual(set(draft.values), {'telnet', 'order', 'connect_wifi', 'project_info', 'runtime', 'push'})
        runtime = self.adapter._executions[self.identifier]
        for source in ('local', 'dingtalk', 'feishu'):
            authority = CapabilityAuthority('synthetic', 'session', 'operation', (), source=source, approved=True)
            with self.assertRaises(CapabilityError) as error:
                runtime.capabilities.execute('configuration.editor.reload', dict(token=draft.token), authority)
            self.assertEqual(error.exception.code, 'source_forbidden')
        self.command('configuration_close', self.identifier, dict(token=draft.token))
        self.assertEqual(self.bytes(), before)
        self.assertNotIn('values=', repr(draft))

    def test_six_domains_save_through_original_stores_and_commit_project_revision(self):
        draft = self.open()
        old_revision = self.context.identity.revision
        values = deepcopy(draft.values)
        values['telnet'].update(password='private-fixture-password%', user='fixture-user', telnet_default_on=0,
            telnet_no_user_password_flag=1, only_power_off_on=1, login_after_input_str='')
        values['order'] = dict(command_fail_retry_interval_time=0, items=[dict(command='echo fixture', retry_times=3,
            expected_segments=[dict(text='first', negate=False), dict(text='second', negate=True)])])
        values['connect_wifi'].update(enable=0, test_2g_enable=0, wireless_card_name='retained disabled card',
            wireless_ping_enable=0, wireless_ping_target='retained.invalid', auth_mode='WPA3-PSK')
        values['project_info']['software_version'] = 'fixture-version'
        values['runtime']['number_of_tests'] = '37'
        values['push'].update(webhook='https://example.invalid/?token=private-fixture-token', secret='private-fixture-secret', dingtalk_flag='0')
        with patch('src.services.message_push_config_service.send_test_message', side_effect=AssertionError('must not send')), \
             patch('serial.Serial', side_effect=AssertionError('must not open serial')):
            result = self.save(draft, values)
        current = result.payload
        self.assertNotEqual(current.revision, draft.revision)
        self.assertNotEqual(self.context.identity.revision, old_revision)
        self.assertEqual(TestItemConfigStore(self.context.config_dir / 'test_project_config.ini').load().telnet.password,
            'private-fixture-password%')
        self.assertEqual(current.values['order'], values['order'])
        self.assertEqual(current.values['runtime']['number_of_tests'], '37')
        self.assertEqual(current.values['runtime']['telnet_enable'], '1')
        self.assertEqual(current.values['connect_wifi']['wireless_card_name'], 'retained disabled card')
        self.assertEqual(current.values['push'], values['push'])
        self.assertFalse(self.adapter._service.projects.dirty(self.context))
        log_text = '\n'.join(entry.message for entry in self.logs)
        self.assertNotIn('private-fixture', log_text)
        self.assertNotIn('private-fixture', repr(result))

    def test_encrypted_recovery_survives_workspace_restart_and_explicit_save_clears_it(self):
        draft = self.open()
        before = self.bytes()
        project_id = self.identifier
        legacy = self.context.root / 'ui/editor_recovery.json'
        legacy.parent.mkdir(exist_ok=True)
        legacy.write_bytes(b'{"legacy_fixture": true}')
        raw = deepcopy(draft.values)
        raw['telnet'].update(port='partially typed', timeout='', password='private-recovery-fixture')
        raw['order'] = dict(command_fail_retry_interval_time='   ', items=[
            dict(command=' whitespace ', retry_times='-', expected_segments=[dict(text='', negate=True)])])
        checkpoint_args = dict(token=draft.token, revision=draft.revision, values=raw)
        self.command('configuration_checkpoint', project_id, checkpoint_args)
        runtime = self.adapter._executions[project_id]
        authority = CapabilityAuthority('synthetic', 'session', 'operation', (), source='local', approved=True)
        with self.assertRaises(CapabilityError) as denied:
            runtime.capabilities.execute('configuration.editor.checkpoint', checkpoint_args, authority)
        self.assertEqual(denied.exception.code, 'source_forbidden')
        recovery = legacy.with_name('qt_editor_recovery.json')
        self.assertNotIn(b'private-recovery-fixture', recovery.read_bytes())
        self.assertEqual(self.bytes(), before)
        context_root = self.context.root
        self.cleanup_worker()
        self.results.clear()
        self.adapter = QtWorkspaceAdapter(SOURCE, directory=self.root / 'workspace')
        self.wait_for(lambda: (0, 'ready') in self.results)
        self.assertEqual(self.command('open', context_root).project_id, project_id)
        self.context = self.adapter._service.projects.opened[project_id]
        restored = self.open()
        self.assertEqual(restored.recovered_values, raw)
        self.assertTrue(restored.legacy_recovery)
        self.assertNotIn('private-recovery-fixture', repr(restored))
        self.assertFalse(any('private-recovery-fixture' in entry.message for entry in self.logs))
        self.assertEqual(self.bytes(), before)
        self.save(restored)
        self.assertFalse(recovery.exists())
        self.assertEqual(legacy.read_bytes(), b'{"legacy_fixture": true}')

    def test_stale_recovery_is_preserved_until_explicit_reload(self):
        draft = self.open()
        raw = deepcopy(draft.values)
        raw['telnet'].update(port='23', timeout='10')
        raw['order'] = dict(command_fail_retry_interval_time='60', items=[])
        self.command('configuration_checkpoint', self.identifier, dict(token=draft.token, revision=draft.revision, values=raw))
        recovery = self.context.root / 'ui/qt_editor_recovery.json'
        saved = recovery.read_bytes()
        config = self.context.config_dir / 'config.ini'
        config.write_bytes(config.read_bytes() + b'\n# revision changed in fixture\n')
        self.command('configuration_close', self.identifier, dict(token=draft.token))
        reopened = self.open()
        self.assertIn('旧配置', reopened.recovery_warning)
        self.assertIsNone(reopened.recovered_values)
        self.command('configuration_checkpoint', self.identifier,
            dict(token=reopened.token, revision=reopened.revision, values=raw), expected_error=True)
        self.assertEqual(recovery.read_bytes(), saved)
        self.command('configuration_reload', self.identifier, dict(token=reopened.token, discard_recovery=True))
        self.assertFalse(recovery.exists())

    def test_external_change_blocks_save_and_reload_returns_new_revision(self):
        draft = self.open()
        path = self.context.config_dir / 'config.ini'
        changed = path.read_bytes() + b'\n# external fixture edit\n'
        path.write_bytes(changed)
        self.save(draft, expected_error=True)
        self.assertEqual(path.read_bytes(), changed)
        reloaded = self.command('configuration_reload', self.identifier, dict(token=draft.token)).payload
        self.assertNotEqual(reloaded.revision, draft.revision)
        self.assertEqual(reloaded.token, draft.token)

    def test_invalid_runtime_and_wifi_are_rejected_without_partial_write_or_secret_error(self):
        draft = self.open()
        before = self.bytes()
        for invalid in ('runtime', 'wifi'):
            values = deepcopy(draft.values)
            if invalid == 'runtime':
                values['runtime']['number_of_tests'] = 'private-fixture-not-a-number'
            else:
                values['connect_wifi'].update(enable=1, product_solution='bcm')
            result = self.save(draft, values, expected_error=True)
            self.assertNotIn('private-fixture', result.error)
            self.assertEqual(self.bytes(), before)

    def test_editor_lease_blocks_start_and_project_mutation(self):
        self.open()
        self.command('prepare_execution', self.identifier, 'aging.start', expected_error=True)
        self.command('save', self.identifier, expected_error=True)
        self.command('rename', self.identifier, 'should not rename', expected_error=True)
        self.command('close', self.identifier, expected_error=True)
        self.assertIn(self.identifier, self.adapter._service.projects.opened)

    def test_running_task_guard_is_checked_again_at_save(self):
        draft = self.open()
        runtime = self.adapter._executions[self.identifier]
        before = self.bytes()
        with patch.object(type(runtime.capabilities.jobs), 'idle', new_callable=PropertyMock, return_value=False):
            self.save(draft, expected_error=True)
        self.assertEqual(self.bytes(), before)

    def test_staging_failure_leaves_original_files_and_revision_untouched(self):
        draft = self.open()
        before, revision = self.bytes(), self.context.identity.revision
        with patch.object(MessagePushConfigService, 'save', side_effect=OSError('private-fixture-error')):
            result = self.save(draft, expected_error=True)
        self.assertEqual(self.bytes(), before)
        self.assertEqual(self.context.identity.revision, revision)
        self.assertNotIn('private-fixture', result.error)

    def test_project_commit_failure_restores_original_draft_bytes(self):
        draft = self.open()
        before, revision = self.bytes(), self.context.identity.revision
        values = deepcopy(draft.values)
        values['runtime']['number_of_tests'] = '79'
        with patch.object(self.adapter._service.projects, 'save', side_effect=OSError('fixture commit failure')):
            self.save(draft, values, expected_error=True)
        self.assertEqual(self.bytes(), before)
        self.assertEqual(self.context.identity.revision, revision)
        self.assertFalse(self.adapter._service.resources.unknown_for(self.identifier))

    def test_failed_rollback_keeps_unknown_protection(self):
        draft = self.open()
        service = self.adapter._executions[self.identifier].configuration
        original = service._replace
        calls = []
        def fail_after_first(path, value):
            calls.append(path)
            if len(calls) > 1:
                raise OSError('fixture rollback failure')
            original(path, value)
        with patch.object(service, '_replace', side_effect=fail_after_first):
            self.save(draft, expected_error=True)
        self.assertTrue(self.adapter._service.resources.unknown_for(self.identifier))

    def test_default_commands_are_only_a_draft_and_keep_global_retry_interval(self):
        draft = self.open()
        before = self.bytes()
        items = self.command('configuration_defaults', self.identifier, dict(token=draft.token)).payload
        self.assertIsInstance(items, list)
        self.assertEqual(self.bytes(), before)
        self.assertEqual(draft.values['order']['command_fail_retry_interval_time'],
            TestItemConfigStore(self.context.config_dir / 'test_project_config.ini').load().order.command_fail_retry_interval_time)

    def test_missing_project_ini_uses_original_defaults_without_creating_on_open(self):
        path = self.context.config_dir / 'test_project_config.ini'
        path.unlink()
        draft = self.open()
        self.assertIn('test_project_config.ini', draft.missing_files)
        self.assertEqual(draft.values['telnet']['port'], 23)
        self.assertFalse(path.exists())

    def test_missing_default_template_is_an_error_and_does_not_clear_commands(self):
        draft = self.open()
        path = self.context.config_dir / 'test_project_config.default.ini'
        if path.exists():
            path.unlink()
        before = self.bytes()
        self.command('configuration_defaults', self.identifier, dict(token=draft.token), expected_error=True)
        self.assertEqual(self.bytes(), before)

    def test_serialized_files_match_the_original_save_sequence(self):
        from src.services.qt_configuration_service import QtConfigurationService
        draft = self.open()
        values = deepcopy(draft.values)
        values['runtime']['number_of_tests'] = '71'
        values['order']['command_fail_retry_interval_time'] = 0
        values['telnet']['password'] = 'private-fixture-percent%'
        expected = self.root / 'expected'
        self.adapter._service.projects._copy_config(self.context.config_dir, expected)
        config, runtime, push = QtConfigurationService._capture(values, expected)
        TestItemConfigStore(expected / 'test_project_config.ini').save(config)
        LegacyUiDefaultsStore(expected / 'config.ini').save(runtime)
        MessagePushConfigService(expected / 'config.ini').save(push)
        self.save(draft, values)
        for name in ('test_project_config.ini', 'config.ini'):
            self.assertEqual((self.context.config_dir / name).read_bytes(), (expected / name).read_bytes())

    def test_wireless_card_refresh_only_reads_original_inventory(self):
        draft = self.open()
        before = self.bytes()
        with patch('src.core.wifi_interfaces.list_wifi_interface_names', return_value=['Fixture Wi-Fi', 'Fixture Wi-Fi 2']) as query:
            names = self.command('configuration_wifi_interfaces', self.identifier, dict(token=draft.token)).payload
        query.assert_called_once_with()
        self.assertEqual(names, ['Fixture Wi-Fi', 'Fixture Wi-Fi 2'])
        self.assertEqual(self.bytes(), before)
