"""Channel writes use temporary INI files and data-only/Fake GUI adapters."""
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import Mock, patch

from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings
from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.services.capability_service import CapabilityService
from src.ui.capability_ui_bridge import CapabilityUiBridge


class Value:
    def __init__(self, value): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class ChannelCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.snapshot = dict(channels=[asdict(ChannelConfig('channel_' + str(n), vlan_name='VLAN' + str(115 + n),
            adapter_alias='VLAN' + str(115 + n), serial_port='COM' + str(15 + n), network_card_ip='192.168.1.' + str(115 + n),
            device_manage_ip='192.168.1.1', factory_bind_ip='192.168.29.' + str(115 + n), enabled=n == 1)) for n in (1, 2)],
            power_serial_port='COM102', device_ip='192.168.1.1', upgrade_settings={})
        self.auth = CapabilityAuthority('local', 'session', 'operation', (1,), mode='full_access', grant_id='grant')
        self.manager = Mock()
        self.runtime = CapabilityService(self.root / 'runtime', self.manager, lambda: self.snapshot, tool_root=self.root)
        self.channels = self.runtime.channel_configuration
        self.channels.store.save([ChannelConfig(**self.snapshot['channels'][0])], 'COM102')
        self.channels.commit_callback = lambda prepared: self.channels.commit(prepared, self.snapshot, self.reflect)

    def tearDown(self):
        self.runtime.jobs.close()
        self.temp.cleanup()

    def reflect(self, state):
        self.snapshot.update({key: state[key] for key in ('channels', 'power_serial_port', 'device_ip')})

    def arguments(self, **extra):
        return dict(revision=self.channels.read({}, self.auth)['revision'], **extra)

    def approve(self, arguments, selecting=False):
        scope = self.channels.prepare(arguments, selecting)['scope']
        if scope:
            self.runtime.scopes.grant(self.auth.principal, scope, 'real-local-reviewer')

    def test_binding_transaction_matches_gui_serializer_and_keeps_factory_values(self):
        arguments = self.arguments(channel_ids=[1], values=dict(vlan_name='VLAN118', serial_port='COM18'),
            device_ip='192.168.2.1', power_serial_port='COM103')
        with self.assertRaises(CapabilityError) as caught:
            self.runtime.execute('channels.configure', arguments, self.auth)
        self.assertEqual('local_scope_approval_required', caught.exception.code)
        self.approve(arguments)
        result = self.runtime.execute('channels.configure', arguments, self.auth)
        self.assertFalse(result['device_authority_changed'])
        current = self.channels.store.load()[0]
        self.assertEqual(('VLAN118', 'COM18', '192.168.2.118'), (current.vlan_name, current.serial_port, current.network_card_ip))
        self.assertEqual('192.168.29.116', current.factory_bind_ip)
        expected = ChannelConfigStore(self.root / 'expected.ini')
        expected.save([ChannelConfig(**c) for c in self.snapshot['channels'] if c['enabled']], 'COM103')
        self.assertEqual(expected.config_path.read_bytes(), self.channels.store.config_path.read_bytes())
        self.manager.acquire_control.assert_not_called()

    def test_selection_requires_owner_review_and_never_expands_callers_device_authority(self):
        arguments = self.arguments(selected_channel_ids=[2])
        with self.assertRaises(CapabilityError):
            self.runtime.execute('channels.select', arguments, self.auth)
        self.approve(arguments, selecting=True)
        self.runtime.execute('channels.select', arguments, self.auth)
        self.assertEqual(['channel_2'], [c.section for c in self.channels.store.load()])
        self.assertEqual((1,), self.auth.channels)
        with self.assertRaises(CapabilityError):
            self.runtime.execute('power.on', dict(channel_ids=[2]), self.auth)
        repeated = self.runtime.execute('channels.select', self.arguments(selected_channel_ids=[2]), self.auth)
        self.assertFalse(repeated['changed'])

    def test_new_gui_change_before_actual_commit_is_preserved_without_disk_overwrite(self):
        arguments = self.arguments(channel_ids=[1], values=dict(serial_port='COM18'))
        self.approve(arguments)
        original = self.channels.store.config_path.read_bytes()
        def commit(prepared):
            self.snapshot['channels'][0]['serial_port'] = 'COM19'
            return self.channels.commit(prepared, self.snapshot, self.reflect)
        self.channels.commit_callback = commit
        with self.assertRaises(CapabilityError) as caught:
            self.runtime.execute('channels.configure', arguments, self.auth)
        self.assertEqual('channel_configuration_changed', caught.exception.code)
        self.assertEqual('COM19', self.snapshot['channels'][0]['serial_port'])
        self.assertEqual(original, self.channels.store.config_path.read_bytes())

    def test_atomic_publish_failure_rolls_back_view_and_keeps_ini(self):
        arguments = self.arguments(channel_ids=[1], values=dict(serial_port='COM18'))
        self.approve(arguments)
        original = self.channels.store.config_path.read_bytes()
        replace_path = Path.replace
        def fail_publish(path, target):
            if Path(target) == self.channels.store.config_path:
                raise PermissionError('fake publish denied')
            return replace_path(path, target)
        with patch.object(Path, 'replace', autospec=True, side_effect=fail_publish), self.assertRaises(CapabilityError):
            self.runtime.execute('channels.configure', arguments, self.auth)
        self.assertEqual('COM16', self.snapshot['channels'][0]['serial_port'])
        self.assertEqual(original, self.channels.store.config_path.read_bytes())
        self.assertEqual([], list(self.channels.store.config_path.parent.glob('*.tmp')))

    def fake_app(self):
        return SimpleNamespace(channels=[ChannelConfig(**c) for c in self.snapshot['channels']],
            power_serial_var=Value('COM102'), device_ip_var=Value('192.168.1.1'), _capture_current_channel=Mock(),
            _current_sample_upgrade_settings=lambda: SampleUpgradeSettings(), _selected_power_serial_port=lambda: 'COM102',
            _serial_log_directory=lambda: self.root / 'serial', _app_closing=False, _log=Mock(),
            _rebuild_channel_config_rows=Mock(), _refresh_channel_list_item=Mock(), _load_current_channel=Mock(),
            _refresh_upgrade_targets=Mock())

    def test_failed_view_rollback_keeps_gui_resource_protection(self):
        arguments = self.arguments(channel_ids=[1], values=dict(serial_port='COM18'))
        prepared = self.channels.prepare(arguments)
        app = self.fake_app()
        app._rebuild_channel_config_rows.side_effect = RuntimeError('fake render failure')
        bridge = CapabilityUiBridge(app)
        bridge.channel_configuration = self.channels
        try:
            with self.assertRaises(CapabilityError):
                bridge._commit_channels(SimpleNamespace(args=(prepared,), admit=lambda: True))
            self.assertIn('configuration-unknown', app._capability_reservations)
            self.assertEqual('COM16', self.channels.store.load()[0].serial_port)
        finally:
            bridge.close()

    def test_worker_commits_data_via_main_thread_adapter_without_gui_callback_execution(self):
        arguments = self.arguments(channel_ids=[1], values=dict(serial_port='COM18'))
        self.approve(arguments)
        app = self.fake_app()
        owner_thread = threading.get_ident()
        app._rebuild_channel_config_rows.side_effect = lambda: self.assertEqual(owner_thread, threading.get_ident())
        app._ai_target_busy = lambda target: bool(app._capability_reservations)
        bridge = CapabilityUiBridge(app)
        bridge.channel_configuration = self.channels
        self.runtime.snapshot = bridge.client.snapshot
        self.runtime.resources.admissible = bridge.client.admissible
        self.runtime.resources.released = bridge.client.released
        self.channels.commit_callback = bridge.client.commit_channels
        outcomes, errors = [], []
        def worker():
            try:
                outcomes.append(self.runtime.execute('channels.configure', arguments, self.auth))
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=worker)
        thread.start()
        deadline = time.monotonic() + 4
        while thread.is_alive() and time.monotonic() < deadline:
            bridge.poll()
            time.sleep(.002)
        thread.join(.1)
        try:
            self.assertFalse(thread.is_alive())
            self.assertEqual([], errors)
            self.assertTrue(outcomes[0]['ok'])
            self.assertEqual('COM18', app.channels[0].serial_port)
            self.assertEqual('COM18', self.channels.store.load()[0].serial_port)
            self.assertEqual(set(), app._capability_reservations)
        finally:
            bridge.close()

    def prepare_rename(self):
        from src.services.adapter_rename_service import AdapterRenameService
        self.adapters = [SimpleNamespace(alias='VLAN116', interface_guid='synthetic-guid', display_name='VLAN116')]
        def rename(old, new):
            self.assertEqual('VLAN116', old)
            self.adapters = [SimpleNamespace(alias=new, interface_guid='synthetic-guid', display_name=new)]
        self.rename_adapter = Mock(side_effect=rename)
        self.channels.rename_service = AdapterRenameService(reader=lambda: self.adapters,
            renamer=self.rename_adapter, availability=lambda: '')
        arguments = self.arguments(channel_ids=[1], new_name='VLAN118')
        scope = self.channels.prepare_rename(arguments)['scope']
        self.runtime.scopes.grant(self.auth.principal, scope, 'real-local-reviewer')
        return arguments

    def wait_job(self, identifier):
        deadline = time.monotonic() + 3
        while not self.runtime.jobs.idle and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertTrue(self.runtime.jobs.idle)
        return self.runtime.jobs.status(identifier, self.auth)

    def test_adapter_rename_reuses_guid_readback_and_shared_configuration_commit(self):
        arguments = self.prepare_rename()
        job = self.runtime.execute('network.rename', arguments, self.auth)
        result = self.wait_job(job['job_id'])
        self.assertEqual('succeeded', result['state'])
        self.assertTrue(result['result']['configuration_saved'])
        self.rename_adapter.assert_called_once_with('VLAN116', 'VLAN118')
        self.assertEqual('VLAN118', self.channels.store.load()[0].vlan_name)
        self.assertEqual('192.168.1.118', self.snapshot['channels'][0]['network_card_ip'])
        self.manager.acquire_control.assert_not_called()

    def test_adapter_identity_swap_at_dispatch_never_renames_a_different_device(self):
        arguments = self.prepare_rename()
        calls = [0]
        def reader():
            calls[0] += 1
            if calls[0] >= 4:
                return [SimpleNamespace(alias='VLAN116', interface_guid='other-guid', display_name='VLAN116')]
            return self.adapters
        self.channels.rename_service.reader = reader
        job = self.runtime.execute('network.rename', arguments, self.auth)
        result = self.wait_job(job['job_id'])
        self.assertEqual('failed', result['state'])
        self.rename_adapter.assert_not_called()
        self.assertEqual('VLAN116', self.channels.store.load()[0].vlan_name)

    def test_adapter_renamed_but_config_failed_is_unknown_without_automatic_rename_back(self):
        arguments = self.prepare_rename()
        self.channels.commit_callback = Mock(side_effect=PermissionError('synthetic config failure'))
        job = self.runtime.execute('network.rename', arguments, self.auth)
        result = self.wait_job(job['job_id'])
        self.assertEqual('unknown', result['state'])
        self.assertTrue(result['result']['adapter_renamed'])
        self.rename_adapter.assert_called_once()
        with self.assertRaises(CapabilityError) as caught:
            self.runtime.execute('power.on', dict(channel_ids=[1]), self.auth)
        self.assertEqual('previous_result_unknown', caught.exception.code)
