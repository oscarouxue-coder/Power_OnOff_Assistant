"""No hardware, external service or executable templates are used."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from src.models.capabilities import CapabilityAuthority, CapabilityError, CapabilitySpec, object_schema
from src.services.capability_service import CapabilityService
from src.ui.capability_management import CapabilityManagement


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.runtime = CapabilityService(Path(self.temp.name), Mock(), lambda: dict(channels=[]))
        self.authority = CapabilityAuthority('user', 'session', 'operation', (1,), mode='full_access', grant_id='grant')
        self.calls = []
        self.runtime.registry.register(CapabilitySpec('fake.action', 'fake', 'fake', object_schema({
            'channel_ids': dict(type='array', items=dict(type='integer')), 'value': dict(type='string')}, ('channel_ids',)),
            lambda a, auth: self.calls.append(a) or dict(ok=True), risk='modify'))
        self.manifest = dict(id='fake_template', name='Fake', version='1', description='Mock only',
            target_capability='fake.action', input_schema=object_schema({'channels': dict(type='array', items=dict(type='integer'))}, ('channels',)),
            arguments={'value': 'fixed'}, bindings={'channel_ids': 'channels'}, allowed_channels=[1], max_executions=1)

    def tearDown(self):
        self.runtime.jobs.close()
        self.temp.cleanup()

    def approve(self):
        review = self.runtime.extensions.review(self.manifest)
        self.runtime.extensions.approve(self.manifest, review['reviewed_sha256'], 'real-local-reviewer')

    def test_review_is_not_registration_and_ai_has_no_approval_capability(self):
        self.runtime.extensions.review(self.manifest)
        with self.assertRaises(CapabilityError):
            self.runtime.execute('extension.fake_template', {'channels': [1]}, self.authority)
        with self.assertRaises(CapabilityError):
            self.runtime.execute('extensions.approve', self.manifest, self.authority)
        self.assertEqual([], self.calls)

    def test_exact_review_fixed_arguments_scope_and_execution_limit(self):
        review = self.runtime.extensions.review(self.manifest)
        altered = deepcopy(self.manifest)
        altered['arguments']['value'] = 'changed'
        with self.assertRaises(CapabilityError):
            self.runtime.extensions.approve(altered, review['reviewed_sha256'], 'local')
        self.approve()
        with self.assertRaises(CapabilityError):
            self.runtime.execute('extension.fake_template', {'channels': [2]}, replace(self.authority, channels=(1, 2)))
        self.runtime.execute('extension.fake_template', {'channels': [1]}, self.authority)
        self.assertEqual([dict(channel_ids=[1], value='fixed')], self.calls)
        self.approve()  # Reviewing the same version cannot reset consumed authorization.
        with self.assertRaises(CapabilityError) as caught:
            self.runtime.execute('extension.fake_template', {'channels': [1]}, self.authority)
        self.assertEqual('template_limit', caught.exception.code)

    def test_changed_target_schema_requires_review_and_revoke_is_immediate(self):
        self.approve()
        self.runtime.extensions.set_enabled('fake_template', False, 'local')
        with self.assertRaises(CapabilityError):
            self.runtime.execute('extension.fake_template', {'channels': [1]}, self.authority)
        self.runtime.extensions.set_enabled('fake_template', True, 'local')
        target = self.runtime.registry.get('fake.action')
        target.input_schema['description'] = 'changed contract'
        with self.assertRaises(CapabilityError) as caught:
            self.runtime.execute('extension.fake_template', {'channels': [1]}, self.authority)
        self.assertEqual('template_changed', caught.exception.code)

    def test_unsupported_schema_cannot_silently_drop_constraints(self):
        for schema in ({'type': 'object', 'patternProperties': {}},
                       object_schema({'field': {'type': 'string', 'pattern': '^safe$'}}),
                       object_schema({'field': {'type': 'array'}})):
            with self.subTest(schema=schema), self.assertRaises(CapabilityError):
                self.runtime.extensions.review(dict(self.manifest, input_schema=schema))

    def test_local_management_hides_reopens_and_disposes_polling(self):
        from tk_test_windows import install_offscreen_windows
        install_offscreen_windows(self)
        root = tk.Tk()
        root.withdraw()
        panel = SimpleNamespace(service=SimpleNamespace(capabilities=SimpleNamespace(service=self.runtime)), owner=SimpleNamespace(window=root))
        manager = CapabilityManagement(panel)
        try:
            manager.open()
            window = manager.window
            root.update_idletasks()
            self.assertIsNotNone(manager.poll_id)
            manager.hide()
            self.assertIsNone(manager.poll_id)
            self.assertEqual('withdrawn', window.state())
            manager.open()
            self.assertIs(window, manager.window)
            self.assertIsNotNone(manager.poll_id)
            manager.close()
            self.assertIsNone(manager.window)
            self.assertIsNone(manager.poll_id)
        finally:
            manager.close()
            root.destroy()

    def test_controlled_host_tools_do_not_interpret_shell(self):
        with patch('src.services.controlled_host_service.list_serial_port_names', return_value=['COM16']):
            self.assertEqual(['COM16'], self.runtime.execute('host.serial_ports', {}, self.authority)['ports'])
        with self.assertRaises(CapabilityError):
            self.runtime.execute('host.environment', {'command': 'arbitrary code'}, self.authority)
