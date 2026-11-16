"""Permanent options use temp stores and a data-only host; no device/network calls."""
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import gc
import threading
import time
import unittest
import weakref
from unittest.mock import Mock, patch

from line_check_assistant.app import LineCheckAssistant
from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings, SampleUpgradeSettingsStore
from line_check_assistant.onu_registration_store import OnuRegistrationConfig, OnuRegistrationStore
from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.services.capability_service import CapabilityService
from src.ui.capability_ui_bridge import CapabilityUiBridge
from test_capability_channels import Value


class StringValue(Value):
    def get(self):
        return str(self.value)


class SettingsCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.snapshot = dict(channels=[], upgrade_settings=asdict(SampleUpgradeSettings(password='upgrade-secret',
            parameter_initial_password='parameter-secret')), device_ip='192.168.1.1')
        self.onu = asdict(OnuRegistrationConfig(c300_username='user300', c300_password='secret300',
            c600_username='user600', c600_password='secret600', username='user300', password='secret300'))
        self.auth = CapabilityAuthority('local', 'session', 'operation', (), mode='full_access', grant_id='grant')
        self.runtime = CapabilityService(self.root / 'runtime', Mock(), lambda: self.snapshot, tool_root=self.root,
            onu_configuration=lambda: self.onu)
        self.settings = self.runtime.settings
        for domain, values in (('upgrade', self.snapshot['upgrade_settings']), ('onu', self.onu)):
            self.settings.stores[domain].save(self.settings.models[domain](**values))
        self.settings.commit_callback = lambda p: self.settings.commit(p, self.snapshot, self.onu, self.reflect)

    def tearDown(self):
        self.runtime.jobs.close()
        self.temp.cleanup()

    def reflect(self, domain, values):
        if domain == 'upgrade':
            self.snapshot['upgrade_settings'] = values
        else:
            self.onu = values

    def args(self, domain, **values):
        return dict(revision=self.runtime.execute('settings.read', dict(domain=domain), self.auth)['revision'], values=values)

    def test_upgrade_merge_preserves_independent_options_and_matches_gui_serializer(self):
        args = self.args('upgrade', parallel_count=3, transfer_method='Tftp指令', parameter_exit_aging=True)
        read = self.runtime.execute('settings.read', dict(domain='upgrade'), self.auth)
        self.assertNotIn('password', read['values'])
        self.assertNotIn('parameter_initial_password', read['values'])
        self.assertTrue(self.runtime.execute('firmware.settings.patch', args, self.auth)['saved'])
        actual = self.settings.stores['upgrade'].load()
        self.assertEqual(('upgrade-secret', 'parameter-secret', 3, True),
            (actual.password, actual.parameter_initial_password, actual.parallel_count, actual.parameter_exit_aging))
        expected = SampleUpgradeSettingsStore(self.root / 'expected.ini')
        expected.save(actual)
        self.assertEqual(expected.config_path.read_bytes(), self.settings.stores['upgrade'].config_path.read_bytes())
        self.runtime.manager.acquire_control.assert_not_called()

    def test_open_editor_or_pending_autosave_and_stale_revision_never_override(self):
        for key in ('upgrade_editor_open', 'upgrade_autosave_pending'):
            with self.subTest(key=key):
                self.snapshot[key] = True
                with self.assertRaises(CapabilityError) as caught:
                    self.runtime.execute('firmware.settings.patch', self.args('upgrade', parallel_count=2), self.auth)
                self.assertEqual('editor_open', caught.exception.code)
                self.snapshot[key] = False
        args = self.args('upgrade', parallel_count=3)
        self.snapshot['upgrade_settings']['parallel_count'] = 4
        with self.assertRaises(CapabilityError) as caught:
            self.runtime.execute('firmware.settings.patch', args, self.auth)
        self.assertEqual('settings_changed', caught.exception.code)
        self.assertEqual(4, self.snapshot['upgrade_settings']['parallel_count'])

    def test_onu_new_profile_requires_review_and_does_not_authorize_hardware(self):
        args = self.args('onu', olt_family='C600', c600_pon=6, c600_olt_ip='172.18.18.153')
        with self.assertRaises(CapabilityError) as caught:
            self.runtime.execute('onu.settings.patch', args, self.auth)
        self.assertEqual('local_scope_approval_required', caught.exception.code)
        scope = self.settings.prepare('onu', args)['scope']
        self.assertNotIn('secret600', str(scope))
        self.runtime.scopes.grant(self.auth.principal, scope, 'local-reviewer')
        self.runtime.execute('onu.settings.patch', args, self.auth)
        actual = self.settings.stores['onu'].load()
        self.assertEqual(('C600', '172.18.18.153', 'user600', 'secret600', 'secret300', False),
            (actual.olt_family, actual.olt_ip, actual.username, actual.password, actual.c300_password, actual.c300_allow_offline_cleanup))
        with self.assertRaises(CapabilityError) as caught:
            self.runtime.execute('onu.connection', dict(family='C600'), self.auth)
        self.assertEqual('local_scope_approval_required', caught.exception.code)

    def test_new_credentials_invalidate_previous_execution_scope_without_exposing_secrets(self):
        scope = self.runtime.onu.scope(dict(family='C300'), 'connection')
        self.runtime.scopes.grant(self.auth.principal, scope, 'local-reviewer')
        args = self.args('onu', c300_password='changed-secret')
        self.runtime.scopes.grant(self.auth.principal, self.settings.prepare('onu', args)['scope'], 'local-reviewer')
        self.runtime.execute('onu.settings.patch', args, self.auth)
        self.assertFalse(self.runtime.scopes.allowed(self.auth.principal, self.runtime.onu.scope(dict(family='C300'), 'connection')))
        read = self.runtime.execute('settings.read', dict(domain='onu'), self.auth)
        self.assertNotIn('changed-secret', str(read))
        self.assertNotIn('secret600', str(read))

    def test_unsafe_flags_unknown_enums_and_remote_control_plane_are_rejected(self):
        for domain, values in (('onu', dict(c300_allow_offline_cleanup=True)),
                ('upgrade', dict(parallel_count=9)), ('upgrade', dict(boot_entry_method='shell'))):
            identifier = 'onu.settings.patch' if domain == 'onu' else 'firmware.settings.patch'
            with self.assertRaises(CapabilityError):
                self.runtime.execute(identifier, self.args(domain, **values), self.auth)
        with self.assertRaises(CapabilityError) as caught:
            self.runtime.execute('settings.read', dict(domain='upgrade'), replace(self.auth, source='dingtalk'))
        self.assertEqual('source_forbidden', caught.exception.code)

    def test_ui_change_between_prepare_and_commit_and_publish_failure_preserve_original(self):
        args = self.args('upgrade', parallel_count=3)
        original = self.settings.stores['upgrade'].config_path.read_bytes()
        def changed(p):
            self.snapshot['upgrade_autosave_pending'] = True
            return self.settings.commit(p, self.snapshot, self.onu, self.reflect)
        self.settings.commit_callback = changed
        with self.assertRaises(CapabilityError):
            self.runtime.execute('firmware.settings.patch', args, self.auth)
        self.snapshot['upgrade_autosave_pending'] = False
        self.settings.commit_callback = lambda p: self.settings.commit(p, self.snapshot, self.onu, self.reflect)
        args = self.args('upgrade', parallel_count=3)
        original_replace = Path.replace
        def fail(path, destination):
            if Path(destination) == self.settings.stores['upgrade'].config_path:
                raise PermissionError('fake publish failure')
            return original_replace(path, destination)
        with patch.object(Path, 'replace', autospec=True, side_effect=fail), self.assertRaises(CapabilityError):
            self.runtime.execute('firmware.settings.patch', args, self.auth)
        self.assertEqual(2, self.snapshot['upgrade_settings']['parallel_count'])
        self.assertEqual(original, self.settings.stores['upgrade'].config_path.read_bytes())
        self.assertEqual([], list(self.settings.stores['upgrade'].config_path.parent.glob('*.tmp')))

    def fake_app(self):
        app = SimpleNamespace(after_cancel=Mock(), sample_upgrade_save_after_id=None, onu_save_after_id=None)
        upgrade_names = dict(upgrade_mode='upgrade_mode', transfer_method='upgrade_transfer', boot_entry_method='upgrade_boot_entry',
            parallel_count='upgrade_parallel_count', restore_factory='upgrade_restore_factory', username='upgrade_username',
            password='upgrade_password', firmware_path='upgrade_firmware')
        for key, value in self.snapshot['upgrade_settings'].items():
            setattr(app, upgrade_names.get(key, key) + '_var', Value(value))
        for key, value in self.onu.items():
            setattr(app, 'onu_family_var' if key == 'olt_family' else 'onu_' + key + '_var',
                    StringValue(value) if type(value) is int else Value(value))
        app.onu_registration_config = OnuRegistrationConfig(**self.onu)
        app.onu_connection_profiles = {family: {key: self.onu[family.lower() + '_' + key]
            for key in ('olt_ip', 'source_ip', 'username', 'password')} for family in ('C300', 'C600')}
        app._remember_onu_connection_profile = lambda family: LineCheckAssistant._remember_onu_connection_profile(app, family)
        return app

    @staticmethod
    def release_tcl_fixture(app, interpreter):
        # Tcl commands own Python callback closures. Remove them on the owner
        # thread before a later business worker can trigger cyclic GC.
        import tkinter as tk
        for variable in list(vars(app).values()):
            if isinstance(variable, tk.Variable):
                for modes, command in variable.trace_info():
                    variable.trace_remove(modes, command)
        for identifier in interpreter.tk.call('after', 'info'):
            interpreter.after_cancel(identifier)
        vars(app).clear()

    def clean_tcl_on_owner_thread(self, app, interpreter):
        reference = weakref.ref(interpreter)
        self.addCleanup(lambda: self.assertIsNone(reference(), 'Tcl fixture retained after owner-thread cleanup'))
        self.addCleanup(gc.collect)
        self.addCleanup(self.release_tcl_fixture, app, interpreter)

    def test_data_renderer_matches_actual_gui_collectors_in_both_domains(self):
        app = self.fake_app()
        bridge = CapabilityUiBridge(app)
        upgrade = dict(self.snapshot['upgrade_settings'], parallel_count=5, parameter_exit_aging=True)
        bridge._reflect_settings('upgrade', upgrade)
        self.assertEqual(upgrade, asdict(LineCheckAssistant._current_sample_upgrade_settings(app)))
        onu = dict(self.onu, olt_family='C600', olt_ip=self.onu['c600_olt_ip'], source_ip=self.onu['c600_source_ip'],
                   username='user600', password='secret600', c600_pon=6)
        bridge._reflect_settings('onu', onu)
        self.assertEqual(onu, asdict(LineCheckAssistant._current_onu_registration_config(app)))
        bridge.close()

    def test_autosave_is_cancelled_even_when_a_data_assignment_fails(self):
        app = self.fake_app()
        bridge = CapabilityUiBridge(app)
        def fail(value):
            app.sample_upgrade_save_after_id = 'scheduled-by-trace'
            raise RuntimeError('fake render failure')
        app.upgrade_transfer_var.set = fail
        with self.assertRaises(RuntimeError):
            bridge._reflect_settings('upgrade', self.snapshot['upgrade_settings'])
        app.after_cancel.assert_called_once_with('scheduled-by-trace')
        self.assertIsNone(app.sample_upgrade_save_after_id)
        bridge.close()

    def test_worker_commit_is_rendered_on_owner_thread_without_opening_a_window(self):
        app = self.fake_app()
        app.channels = []
        app.device_ip_var = Value('192.168.1.1')
        app._capture_current_channel = Mock()
        app._current_sample_upgrade_settings = lambda: LineCheckAssistant._current_sample_upgrade_settings(app)
        app._selected_power_serial_port = lambda: ''
        app._serial_log_directory = lambda: self.root / 'serial'
        app._log = Mock()
        bridge = CapabilityUiBridge(app)
        bridge.settings_configuration = self.settings
        self.settings.commit_callback = bridge.client.commit_settings
        args = self.args('upgrade', parallel_count=6)
        output, threads = [], []
        original = bridge._reflect_settings
        def render(*values):
            threads.append(threading.get_ident())
            return original(*values)
        bridge._reflect_settings = render
        def execute():
            try:
                output.append(self.runtime.execute('firmware.settings.patch', args, self.auth))
            except Exception as exc:
                output.append(exc)
        worker = threading.Thread(target=execute)
        worker.start()
        deadline = time.monotonic() + 3
        while worker.is_alive() and time.monotonic() < deadline:
            bridge.poll()
            time.sleep(.001)
        worker.join(.1)
        self.assertFalse(worker.is_alive())
        self.assertTrue(output and isinstance(output[0], dict), repr(output))
        self.assertEqual([threading.get_ident()], threads)
        self.assertEqual(6, self.settings.stores['upgrade'].load().parallel_count)
        self.assertEqual(6, app.upgrade_parallel_count_var.get())
        bridge.close()

    def test_actual_tcl_autosave_traces_are_drained_without_replaying_a_save(self):
        import tkinter as tk
        interpreter = tk.Tcl()
        errors = []
        interpreter.report_callback_exception = lambda *args: errors.append(args)
        app = self.fake_app()
        self.clean_tcl_on_owner_thread(app, interpreter)
        app.after, app.after_cancel = interpreter.after, interpreter.after_cancel
        for name, value in list(vars(app).items()):
            if name.endswith('_var'):
                cls = tk.BooleanVar if type(value.get()) is bool else tk.StringVar
                setattr(app, name, cls(interpreter, value=value.get()))
        saved = Mock()
        def save():
            saved()
        app._save_sample_upgrade_settings = save
        app._schedule_sample_upgrade_save = lambda: LineCheckAssistant._schedule_sample_upgrade_save(app)
        # Use the frozen GUI's actual trace registration, including both windows' shared values.
        LineCheckAssistant._bind_sample_upgrade_autosave(app)
        bridge = CapabilityUiBridge(app)
        traces = app.upgrade_mode_var.trace_info()
        bridge._reflect_settings('upgrade', dict(self.snapshot['upgrade_settings'], parallel_count=3))
        self.assertIsNone(app.sample_upgrade_save_after_id)
        self.assertEqual('', interpreter.tk.call('after', 'info'))
        saved.assert_not_called()
        self.assertEqual([], errors)
        self.assertEqual(traces, app.upgrade_mode_var.trace_info())
        # Normal GUI changes retain the original callbacks after the data commit.
        app.upgrade_mode_var.set('页面升级')
        self.assertIsNotNone(app.sample_upgrade_save_after_id)
        interpreter.after_cancel(app.sample_upgrade_save_after_id)
        bridge.close()

    def test_onu_editor_traces_are_not_called_but_exact_callbacks_remain_installed(self):
        import tkinter as tk
        interpreter = tk.Tcl()
        app = self.fake_app()
        self.clean_tcl_on_owner_thread(app, interpreter)
        for name, value in list(vars(app).items()):
            if name.endswith('_var'):
                cls = tk.BooleanVar if type(value.get()) is bool else tk.StringVar
                setattr(app, name, cls(interpreter, value=value.get()))
        callbacks = Mock()
        app.onu_family_var.trace_add('write', lambda *args: callbacks('family'))
        app.onu_c600_pon_var.trace_add('write', lambda *args: callbacks('pon'))
        bridge = CapabilityUiBridge(app)
        bridge._reflect_settings('onu', dict(self.onu, c600_pon=6))
        callbacks.assert_not_called()
        self.assertFalse(app.onu_preview_ready)
        app.onu_c600_pon_var.set('7')
        callbacks.assert_called_once_with('pon')
        bridge.close()
