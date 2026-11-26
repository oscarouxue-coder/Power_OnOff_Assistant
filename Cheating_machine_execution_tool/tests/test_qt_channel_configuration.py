"""Original channel prepare/commit, selected-only files and temporary projects."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, PropertyMock

from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.services.qt_workspace_adapter import QtWorkspaceAdapter


SOURCE = Path(__file__).resolve().parents[1]


class QtChannelConfigurationTests(unittest.TestCase):
    def setUp(self):
        from qt_execution_fakes import install_native_fixture_locks
        install_native_fixture_locks(self)
        self.temporary = tempfile.TemporaryDirectory(prefix='qt-channel-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.adapter = QtWorkspaceAdapter(SOURCE, directory=self.root / 'workspace')
        self.addCleanup(self.cleanup_worker)
        self.results, self.logs = {}, []
        self.wait_for(lambda: (0, 'ready') in self.results)
        self.identifier = self.command('create', self.root / 'project', '通道配置项目').project_id
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
        self.fail('channel command did not finish')

    def command(self, operation, *args, expected_error=False):
        request = self.adapter.submit(operation, *args)
        self.wait_for(lambda: (request, operation) in self.results)
        result = self.results[request, operation]
        self.assertEqual(bool(result.error), expected_error, result.error)
        return result

    def open(self):
        return self.command('channels_editor_open', self.identifier).payload

    def arguments(self, draft):
        return dict(token=draft.token, revision=draft.revision, device_ip='192.168.2.1', power_serial_port='COM102',
            rows=[dict(number=int(c['section'].rsplit('_', 1)[1]), enabled=False,
                vlan_name=c['vlan_name'], serial_port=c['serial_port']) for c in draft.values['channels']])

    def preview(self, draft, arguments=None, expected_error=False):
        return self.command('channels_editor_preview', self.identifier, arguments or self.arguments(draft), expected_error=expected_error)

    def commit(self, draft, preview, expected_error=False):
        return self.command('channels_editor_save', self.identifier,
            dict(token=draft.token, confirmation=preview.payload['confirmation']), expected_error=expected_error)

    def test_open_has_16_disabled_slots_but_does_not_persist_or_start_devices(self):
        path = self.context.config_dir / 'network_card_ip.ini'
        original = path.read_bytes()
        with patch('serial.Serial', side_effect=AssertionError('physical serial forbidden')):
            draft = self.open()
        self.assertEqual(len(draft.values['channels']), 16)
        self.assertEqual(path.read_bytes(), original)
        self.assertNotIn('values=', repr(draft))
        self.assertFalse(self.adapter._executions[self.identifier].jobs)

    def test_selected_only_save_matches_original_serializer_and_derives_ips(self):
        draft = self.open()
        args = self.arguments(draft)
        args['rows'][0].update(enabled=True, vlan_name='VLAN116', serial_port='com16')
        args['rows'][6].update(enabled=True, vlan_name='VLAN117', serial_port='COM17')
        before_revision = self.context.identity.revision
        preview = self.preview(draft, args)
        original = (self.context.config_dir / 'network_card_ip.ini').read_bytes()
        self.assertIn('192.168.2.116', preview.payload['summary'])
        self.assertEqual((self.context.config_dir / 'network_card_ip.ini').read_bytes(), original)
        result = self.commit(draft, preview)
        store = ChannelConfigStore(self.context.config_dir / 'network_card_ip.ini')
        channels = store.load()
        self.assertEqual([c.section for c in channels], ['channel_1', 'channel_7'])
        self.assertEqual([c.network_card_ip for c in channels], ['192.168.2.116', '192.168.2.117'])
        self.assertEqual(channels[0].serial_port, 'COM16')
        self.assertNotEqual(before_revision, self.context.identity.revision)
        self.assertFalse(self.adapter._service.projects.dirty(self.context))
        expected = ChannelConfigStore(self.root / 'expected.ini')
        expected.save([ChannelConfig(**c) for c in result.payload.values['channels'] if c['enabled']], 'COM102')
        self.assertEqual(expected.config_path.read_bytes(), store.config_path.read_bytes())
        self.assertEqual(len(result.payload.values['channels']), 16)

    def test_unselected_bindings_remain_in_session_but_not_old_format_file(self):
        draft = self.open()
        args = self.arguments(draft)
        args['rows'][0].update(enabled=True, vlan_name='VLAN116', serial_port='COM16')
        args['rows'][1].update(enabled=False, vlan_name='VLAN118', serial_port='COM18')
        result = self.commit(draft, self.preview(draft, args)).payload
        self.assertEqual(result.values['channels'][1]['serial_port'], 'COM18')
        self.assertEqual([c.section for c in ChannelConfigStore(self.context.config_dir / 'network_card_ip.ini').load()], ['channel_1'])
        self.command('channels_editor_close', self.identifier, dict(token=draft.token))
        reopened = self.open()
        self.assertEqual(reopened.values['channels'][1]['serial_port'], 'COM18')

    def test_clear_selection_and_empty_power_stay_empty_without_fallback(self):
        draft = self.open()
        args = self.arguments(draft)
        args['power_serial_port'] = ''
        self.commit(draft, self.preview(draft, args))
        store = ChannelConfigStore(self.context.config_dir / 'network_card_ip.ini')
        self.assertEqual(store.load(), [])
        self.assertEqual(store.load_power_serial_port(), '')

    def test_invalid_and_duplicate_targets_are_rejected_without_writing(self):
        draft = self.open()
        path = self.context.config_dir / 'network_card_ip.ini'
        before = path.read_bytes()
        for kind in ('ip', 'port', 'conflict', 'duplicate'):
            args = self.arguments(draft)
            args['rows'][0].update(enabled=True, vlan_name='VLAN116', serial_port='COM16')
            if kind == 'ip':
                args['device_ip'] = 'not-an-ip'
            elif kind == 'port':
                args['rows'][0]['serial_port'] = 'invalid-port'
            elif kind == 'conflict':
                args['power_serial_port'] = 'COM16'
            else:
                args['rows'][1]['number'] = 1
            self.preview(draft, args, expected_error=True)
            self.assertEqual(path.read_bytes(), before)

    def test_cancel_and_expired_confirmation_never_write(self):
        draft = self.open()
        path = self.context.config_dir / 'network_card_ip.ini'
        before = path.read_bytes()
        preview = self.preview(draft)
        self.command('channels_editor_cancel', self.identifier, dict(token=draft.token))
        self.commit(draft, preview, expected_error=True)
        preview = self.preview(draft)
        self.adapter._executions[self.identifier].channel_editor.pending['created'] = time.monotonic() - 121
        self.commit(draft, preview, expected_error=True)
        self.assertEqual(path.read_bytes(), before)

    def test_concurrent_change_after_preview_is_not_overwritten(self):
        draft = self.open()
        preview = self.preview(draft)
        path = self.context.config_dir / 'network_card_ip.ini'
        changed = path.read_bytes() + b'\n# concurrent fixture\n'
        path.write_bytes(changed)
        self.commit(draft, preview, expected_error=True)
        self.assertEqual(path.read_bytes(), changed)

    def test_editors_and_task_admission_are_mutually_exclusive(self):
        draft = self.open()
        self.command('configuration_open', self.identifier, expected_error=True)
        self.command('prepare_execution', self.identifier, 'aging.start', expected_error=True)
        self.command('close', self.identifier, expected_error=True)
        runtime = self.adapter._executions[self.identifier]
        with patch.object(type(runtime.capabilities.jobs), 'idle', new_callable=PropertyMock, return_value=False):
            self.preview(draft, expected_error=True)

    def test_gui_only_configuration_does_not_expand_device_authority(self):
        draft = self.open()
        runtime = self.adapter._executions[self.identifier]
        for source in ('local', 'dingtalk', 'feishu'):
            authority = CapabilityAuthority('fixture', 'session', 'operation', (1,), source=source, approved=True)
            with self.assertRaises(CapabilityError) as error:
                runtime.capabilities.execute('channels.editor.reload', dict(token=draft.token), authority)
            self.assertEqual(error.exception.code, 'source_forbidden')
            self.assertEqual(authority.channels, (1,))

    def test_project_commit_failure_restores_network_file_and_cache(self):
        draft = self.open()
        path = self.context.config_dir / 'network_card_ip.ini'
        before, revision = path.read_bytes(), self.context.identity.revision
        args = self.arguments(draft)
        args['rows'][0].update(enabled=True, vlan_name='VLAN116', serial_port='COM16')
        preview = self.preview(draft, args)
        with patch.object(self.adapter._service.projects, 'save', side_effect=OSError('fixture failure')):
            self.commit(draft, preview, expected_error=True)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.context.identity.revision, revision)
        self.assertFalse(self.adapter._service.resources.unknown_for(self.identifier))

    def test_wizard_and_environment_save_share_one_revision_and_reject_stale_edits(self):
        from src.services.project_profile_store import PROFILE_FILE, read_project_profile

        profile = dict(test_type='power_cycle', duts=[])
        view = self.command('wizard_profile_get', self.identifier).payload
        rows = [dict(number=n, enabled=n in (1, 2, 7), vlan_name=f'VLAN{117-n}', serial_port=f'COM{17-n}')
                for n in range(1, 17)]
        request = dict(revision=view['environment_revision'], assignments={},
                       channels=dict(rows=rows, device_ip='192.168.1.1', power_serial_port='COM102'))
        original = self.context.identity.revision
        self.command('wizard_profile_save', self.identifier, profile, view['token'], request, True)
        self.assertNotEqual(self.context.identity.revision, original)
        saved = self.context.saved_root / 'Auto_power_on_off_tool/config'
        duts = read_project_profile(saved)['duts']
        ids = {dut['channel']: dut['dut_id'] for dut in duts}
        self.assertEqual(set(ids), {1, 2, 7})
        self.assertFalse(any(dut['hardware_id'] for dut in duts))
        self.command('wizard_profile_save', self.identifier, profile, view['token'], request, True, expected_error=True)
        draft = self.open()
        args = self.arguments(draft)
        for index in (0, 6):
            args['rows'][index]['enabled'] = True
        preview = self.preview(draft, args)
        paths = [self.context.config_dir / name for name in (PROFILE_FILE, 'network_card_ip.ini')]
        original_files = [path.read_bytes() for path in paths]
        with patch.object(self.adapter._service.projects, 'save', side_effect=OSError('fixture failure')):
            self.commit(draft, preview, expected_error=True)
        self.assertEqual([path.read_bytes() for path in paths], original_files)
        self.commit(draft, self.preview(draft, args))
        view = self.command('wizard_profile_get', self.identifier).payload
        self.assertEqual({dut['channel']: dut['dut_id'] for dut in view['profile']['duts']}, ids)
        self.assertEqual([row['section'] for row in view['environment']['channels'] if row['enabled']],
                         ['channel_1', 'channel_7'])

    def test_resource_refresh_is_read_only_and_failure_retains_last_success(self):
        from src.models.network_adapter import AdapterIdentity
        draft = self.open()
        path = self.context.config_dir / 'network_card_ip.ini'
        before = path.read_bytes()
        revision = self.context.identity.revision
        def refresh():
            return self.command('channels_editor_resources', self.identifier, dict(token=draft.token)).payload

        with patch('src.core.network_adapter.read_adapter_identities') as adapters, \
             patch('src.core.serial_inventory.list_serial_port_names') as serial_ports, \
             patch('serial.Serial', side_effect=AssertionError('must not open serial')):
            adapters.return_value = (AdapterIdentity('VLAN116', 'fixture-guid'),)
            serial_ports.return_value = ['COM101', 'COM1600']
            self.assertEqual(refresh(), dict(adapters=['VLAN116'], ports=['COM101', 'COM1600'], errors=[]))
            serial_ports.side_effect = OSError('fixture serial failure')
            adapters.return_value = (AdapterIdentity('VLAN117', 'fixture-new-guid'),)
            partial = refresh()
            self.assertEqual(partial['adapters'], ['VLAN117'])
            self.assertEqual(partial['ports'], ['COM101', 'COM1600'])
            self.assertIn('串口枚举失败', partial['errors'][0])
            serial_ports.side_effect = None
            serial_ports.return_value = []
            adapters.side_effect = OSError('fixture adapter failure')
            partial = refresh()
            self.assertEqual(partial['adapters'], ['VLAN117'])
            self.assertEqual(partial['ports'], [])
            self.assertIn('网卡枚举失败', partial['errors'][0])
            adapters.side_effect = None
            adapters.return_value = ()
            self.assertEqual(refresh(), dict(adapters=[], ports=[], errors=[]))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.context.identity.revision, revision)
        self.assertFalse(self.adapter._executions[self.identifier].jobs)

    def test_failed_commit_does_not_undo_another_writer(self):
        draft = self.open()
        preview = self.preview(draft)
        service = self.adapter._executions[self.identifier].channel_editor
        changed = service.path.read_bytes() + b'\n# other writer before publish\n'
        def reject(*args):
            service.path.write_bytes(changed)
            raise CapabilityError('channel_configuration_changed', 'fixture changed')
        with patch.object(service.channels, 'commit', side_effect=reject):
            self.commit(draft, preview, expected_error=True)
        self.assertEqual(service.path.read_bytes(), changed)

    def test_failed_restore_keeps_unknown_fence(self):
        from src.services.qt_configuration_service import QtConfigurationService
        draft = self.open()
        preview = self.preview(draft)
        with patch.object(self.adapter._service.projects, 'save', side_effect=OSError('fixture commit failure')), \
             patch.object(QtConfigurationService, '_replace', side_effect=OSError('fixture restore failure')):
            self.commit(draft, preview, expected_error=True)
        self.assertTrue(self.adapter._service.resources.unknown_for(self.identifier))

    def test_store_lock_failure_releases_configuration_admission(self):
        draft = self.open()
        preview = self.preview(draft)
        service = self.adapter._executions[self.identifier].channel_editor
        before = service.path.read_bytes()
        with patch.object(service.channels.store, 'transaction', side_effect=OSError('fixture lock failed')):
            self.commit(draft, preview, expected_error=True)
        self.assertEqual(service.path.read_bytes(), before)
        self.assertFalse(service.capabilities.resources.busy)
        self.assertFalse(self.adapter._service.resources.owners)

    def test_factory_fields_survive_binding_change(self):
        channel = ChannelConfig('channel_1', vlan_name='VLAN116', serial_port='COM16', device_manage_ip='192.168.1.1',
            factory_device_host='192.168.29.1', factory_bind_ip='192.168.29.116')
        ChannelConfigStore(self.context.config_dir / 'network_card_ip.ini').save([channel], 'COM102')
        self.adapter._service.projects.save(self.context)
        draft = self.open()
        args = self.arguments(draft)
        args['rows'][0].update(enabled=True, vlan_name='VLAN119', serial_port='COM19')
        self.commit(draft, self.preview(draft, args))
        current = ChannelConfigStore(self.context.config_dir / 'network_card_ip.ini').load()[0]
        self.assertEqual(current.factory_bind_ip, '192.168.29.116')
        self.assertEqual(current.factory_device_host, '192.168.29.1')

    def test_save_confirmation_cannot_be_replayed(self):
        draft = self.open()
        preview = self.preview(draft)
        self.commit(draft, preview)
        revision = self.context.identity.revision
        self.commit(draft, preview, expected_error=True)
        self.assertEqual(self.context.identity.revision, revision)
