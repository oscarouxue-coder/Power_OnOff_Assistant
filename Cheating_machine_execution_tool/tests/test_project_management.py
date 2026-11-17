"""Temporary projects and Fake resources only; no DUT or platform I/O."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.models.project import PROJECT_FILE
from src.models.capabilities import CapabilityError
from src.services.project_store import ProjectStore
from src.services.workspace_resources import WorkspaceResources


SOURCE = Path(__file__).resolve().parents[1]


class ProjectManagementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='多项目 test ')
        self.root = Path(self.temporary.name)
        self.store = ProjectStore(SOURCE)
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(self.close_projects)

    def close_projects(self):
        for context in tuple(self.store.opened.values()):
            self.store.close(context)

    def create(self, name='项目 A'):
        return self.store.create(self.root / name, name)

    def test_new_project_uses_sanitized_defaults_not_local_bindings(self):
        context = self.create()
        from line_check_assistant.config_store import ChannelConfigStore
        store = ChannelConfigStore(context.config_dir / 'network_card_ip.ini')
        self.assertEqual(store.load_power_serial_port(), '')
        self.assertFalse(any(c.serial_port or c.network_card_ip for c in store.load()))
        self.assertFalse(self.store.dirty(context))

    def test_four_projects_same_filename_save_and_snapshot_are_isolated(self):
        contexts = [self.create('项目 ' + str(n)) for n in range(4)]
        snapshots = []
        for n, context in enumerate(contexts):
            path = context.config_dir / 'test_project_config.ini'
            path.write_text('[project_info]\nproject_name = 项目 %s\n' % n, encoding='utf-8')
            self.store.save(context)
            snapshots.append(self.store.snapshot(context))
        for n, (context, snapshot) in enumerate(zip(contexts, snapshots)):
            (context.config_dir / 'test_project_config.ini').write_text('changed', encoding='utf-8')
            self.assertIn('项目 %s' % n, (snapshot / 'Auto_power_on_off_tool/config/test_project_config.ini').read_text(encoding='utf-8'))
            self.assertTrue(self.store.dirty(context))

    def test_failed_manifest_commit_keeps_old_revision_and_draft(self):
        context = self.create()
        old = context.identity
        (context.config_dir / 'config.ini').write_text('[changed]\nvalue=草稿\n', encoding='utf-8')
        with patch('src.services.project_store.atomic_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.store.save(context)
        self.assertEqual(context.identity, old)
        self.assertEqual(json.loads((context.root / PROJECT_FILE).read_text(encoding='utf-8'))['revision'], old.revision)
        self.assertTrue(self.store.dirty(context))

    def test_discard_restores_committed_configuration(self):
        context = self.create()
        before = (context.config_dir / 'config.ini').read_bytes()
        (context.config_dir / 'config.ini').write_text('draft', encoding='utf-8')
        self.store.discard(context)
        self.assertEqual((context.config_dir / 'config.ini').read_bytes(), before)
        self.assertFalse(self.store.dirty(context))

    def test_duplicate_has_new_identity_and_no_active_history(self):
        context = self.create()
        context.history.joinpath('original.txt').write_text('history')
        copy = self.store.duplicate(context, self.root / 'copy')
        self.assertNotEqual(copy.identity.project_id, context.identity.project_id)
        self.assertFalse(copy.history.joinpath('original.txt').exists())

    def test_directory_move_preserves_identity_and_history_path(self):
        context = self.create()
        identity = context.identity.project_id
        self.store.close(context)
        moved = self.root / '搬动目录'
        context.root.rename(moved)
        reopened = self.store.open(moved)
        from src.services.ai_project_store import project_directory
        self.assertEqual(reopened.identity.project_id, identity)
        self.assertEqual(project_directory(reopened.working_root), moved.resolve() / 'history/ai')

    def test_duplicate_open_and_second_writer_are_rejected(self):
        context = self.create()
        other = ProjectStore(SOURCE)
        with self.assertRaises(RuntimeError):
            other.open(context.root)
        self.assertIs(self.store.open(context.root / PROJECT_FILE), context)

    def test_unknown_format_and_missing_saved_configuration_fail_closed(self):
        context = self.create()
        self.store.close(context)
        path = context.root / PROJECT_FILE
        value = asdict(context.identity)
        value['format_version'] = 999
        path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '格式版本'):
            self.store.open(context.root)

    def test_import_keeps_source_configuration_bytes(self):
        incoming = self.root / '旧目录/config'
        incoming.mkdir(parents=True)
        path = incoming / 'test_project_config.ini'
        path.write_text('[project_info]\nproject_name=旧项目\n[telnet]\npassword=simulated\n', encoding='utf-8')
        before = path.read_bytes()
        context = self.store.create(self.root / 'imported', '导入项目', import_directory=incoming.parent)
        self.assertEqual(path.read_bytes(), before)
        self.assertIn('password = simulated', (context.config_dir / path.name).read_text(encoding='utf-8'))

    def test_import_and_duplicate_copy_parameter_inputs_and_survive_relocation(self):
        from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettingsStore
        incoming = self.root / 'old/config'
        incoming.mkdir(parents=True)
        (incoming / 'test_project_config.ini').write_text('[project_info]\nproject_name=old\n', encoding='utf-8')
        (incoming.parent / 'table.csv').write_text('simulated,data\n', encoding='utf-8')
        (incoming / 'sample_upgrade_settings.ini').write_text('[sample_upgrade]\nparameter_table_path=table.csv\n', encoding='utf-8')
        context = self.store.create(self.root / 'imported', 'I', import_directory=incoming)
        copied = SampleUpgradeSettingsStore(context.config_dir / 'sample_upgrade_settings.ini').load().parameter_table_path
        self.assertEqual(Path(copied).read_text(), 'simulated,data\n')
        duplicate = self.store.duplicate(context, self.root / 'duplicate')
        self.store.close(duplicate)
        moved = self.root / 'moved'
        duplicate.root.rename(moved)
        reopened = self.store.open(moved)
        path = SampleUpgradeSettingsStore(reopened.config_dir / 'sample_upgrade_settings.ini').load().parameter_table_path
        self.assertTrue(Path(path).is_relative_to(reopened.root))
        self.assertEqual(Path(path).read_text(), 'simulated,data\n')


class WorkspaceResourcesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.resources = WorkspaceResources(self.temporary.name)
        self.addCleanup(self.resources.close)

    def test_power_and_serial_cannot_be_owned_by_different_projects(self):
        self.resources.acquire('a1', 'a', '项目 A', ['power:COM010'])
        with self.assertRaisesRegex(CapabilityError, '项目 A'):
            self.resources.acquire('b1', 'b', '项目 B', ['serial:COM10'])
        self.resources.release('a1')
        self.resources.acquire('b1', 'b', '项目 B', ['serial:COM10'])
        self.resources.release('b1')

    def test_same_project_nested_engine_keeps_other_projects_excluded(self):
        self.resources.acquire('a1', 'a', 'A', ['serial:COM11'])
        self.resources.acquire('a2', 'a', 'A', ['serial:COM11'])
        self.resources.release('a1')
        with self.assertRaises(CapabilityError):
            self.resources.acquire('b1', 'b', 'B', ['serial:COM11'])
        self.resources.release('a2')

    def test_unknown_result_blocks_reuse_until_original_task_is_reviewed(self):
        self.resources.acquire('a1', 'a', 'A', ['adapter:vlan101'])
        self.resources.release('a1', uncertain=True)
        with self.assertRaises(CapabilityError):
            self.resources.acquire('b1', 'b', 'B', ['adapter:vlan101'])
        self.resources.resolve('a1')
        self.resources.acquire('b1', 'b', 'B', ['adapter:vlan101'])
        self.resources.release('b1')

    def test_adapter_alias_and_guid_are_the_same_resource(self):
        self.resources.register_adapter('vlan101', '{guid-1}')
        self.resources.acquire('a1', 'a', 'A', ['adapter:vlan101'])
        with self.assertRaises(CapabilityError):
            self.resources.acquire('b1', 'b', 'B', ['adapter:{GUID-1}'])
        self.resources.release('a1')

    def test_late_identity_discovery_adds_guid_to_existing_reservation(self):
        self.resources.acquire('a1', 'a', 'A', ['adapter:vlan101'])
        self.resources.register_adapter('vlan101', '{guid-1}')
        self.resources.register_adapter('renamed101', '{guid-1}')
        with self.assertRaises(CapabilityError):
            self.resources.acquire('b1', 'b', 'B', ['adapter:renamed101'])
        self.resources.release('a1')

    def test_legacy_ai_diagnostic_transport_uses_the_same_project_resource_guard(self):
        from types import SimpleNamespace
        from src.core.ai_debug_transport import DiagnosticTransport, DebugSessionInvalid
        from src.services.project_diagnostic_transport import ProjectDiagnosticTransport
        import threading
        target = SimpleNamespace(vlan='simulated101')
        context = lambda key: SimpleNamespace(identity=SimpleNamespace(project_id=key, name=key))
        a = ProjectDiagnosticTransport(target, threading.Event(), lambda text: None, None,
                                       resources=self.resources, project_context=context('a'))
        b = ProjectDiagnosticTransport(target, threading.Event(), lambda text: None, None,
                                       resources=self.resources, project_context=context('b'))
        with patch.object(DiagnosticTransport, 'open') as open_transport:
            try:
                a.open()
                with self.assertRaises(CapabilityError):
                    b.open()
                self.assertEqual(open_transport.call_count, 1)
                with self.assertRaises(DebugSessionInvalid):
                    a._invalidate('simulated uncertain dispatch', dispatched=True)
                with self.assertRaises(CapabilityError):
                    b.open()
                self.resources.resolve(a.project_owner)
                b.open()
            finally:
                a.close()
                b.close()

    def test_diagnostic_pending_cleanup_retains_resource_until_local_review(self):
        from types import SimpleNamespace
        from src.core.ai_debug_transport import DiagnosticTransport
        from src.services.project_diagnostic_transport import ProjectDiagnosticTransport
        import threading
        target = SimpleNamespace(vlan='simulated102', channel='1', host='simulated-device', port=23)
        pending = [('record', dict(channel='1', host='simulated-device', port=23))]
        store = SimpleNamespace(pending_recovery=lambda: pending)
        context = SimpleNamespace(identity=SimpleNamespace(project_id='a', name='A'))
        transport = ProjectDiagnosticTransport(target, threading.Event(), lambda text: None, None,
                    resources=self.resources, project_context=context, recovery_store=store)
        with patch.object(DiagnosticTransport, 'open'):
            transport.open()
            transport.close()
        self.assertTrue(transport.project_uncertain)
        self.assertIn(transport.project_owner, dict(self.resources.unknown_gui()))
        with self.assertRaises(CapabilityError):
            self.resources.acquire('b', 'b', 'B', ['adapter:simulated102'])
        self.resources.resolve(transport.project_owner)
        self.resources.acquire('b', 'b', 'B', ['adapter:simulated102'])
        self.resources.release('b')

    def test_releasing_an_adapter_does_not_keep_it_fenced_by_an_unrelated_serial_monitor(self):
        self.resources.acquire('serial-a', 'a', 'A', ['serial:COM987654'])
        self.resources.acquire('adapter-a', 'a', 'A', ['adapter:simulated101'])
        self.resources.release('adapter-a')
        self.resources.acquire('adapter-b', 'b', 'B', ['adapter:simulated101'])
        self.resources.release('adapter-b')
        self.resources.release('serial-a')

    def test_reviewed_unknown_adapter_is_released_while_other_known_resources_stay_owned(self):
        self.resources.acquire('serial-a', 'a', 'A', ['serial:COM987655'])
        self.resources.acquire('adapter-a', 'a', 'A', ['adapter:simulated102'])
        self.resources.release('adapter-a', uncertain=True)
        with self.assertRaises(CapabilityError):
            self.resources.acquire('adapter-b', 'b', 'B', ['adapter:simulated102'])
        self.resources.resolve('adapter-a')
        self.resources.acquire('adapter-b', 'b', 'B', ['adapter:simulated102'])
        with self.assertRaises(CapabilityError):
            self.resources.acquire('serial-b', 'b', 'B', ['serial:COM987655'])
        self.resources.release('adapter-b')
        self.resources.release('serial-a')


class ProjectModelStoreTests(unittest.TestCase):
    def test_shared_accounts_keep_project_selection_and_history_separate(self):
        from src.services.ai_store import DiagnosticStore
        from src.services.project_ai_store import ProjectDiagnosticStore
        from src.models.ai_diagnostics import ProviderProfile
        class Cipher:
            def encrypt(self, value, binding):
                return value.encode()
            def decrypt(self, value, binding):
                return value.decode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = DiagnosticStore(root / 'models', cipher=Cipher())
            a = ProjectDiagnosticStore(root / 'a', models, cipher=Cipher())
            b = ProjectDiagnosticStore(root / 'b', models, cipher=Cipher())
            try:
                profile = a.save_profile(ProviderProfile(model='fake'), 'simulated-key')
                self.assertEqual(b.profiles(), a.profiles())
                self.assertEqual(b.key(profile), 'simulated-key')
                a.set_setting('selected_profile', profile.id)
                a.set_setting('project_note', 'A')
                self.assertEqual(b.setting('selected_profile', ''), '')
                self.assertIsNone(b.setting('project_note'))
            finally:
                a.close()
                b.close()
                models.close()

    def test_conflicting_import_remaps_selected_account_and_removes_project_credentials(self):
        from src.services.ai_store import DiagnosticStore
        from src.services.project_ai_store import ProjectDiagnosticStore
        from src.models.ai_diagnostics import ProviderProfile
        class Cipher:
            def encrypt(self, value, binding):
                return value.encode()
            def decrypt(self, value, binding):
                return value.decode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = DiagnosticStore(root / 'models', cipher=Cipher())
            legacy = DiagnosticStore(root / 'legacy', cipher=Cipher())
            target = ProjectDiagnosticStore(root / 'project', models, cipher=Cipher())
            try:
                models.save_profile(ProviderProfile(id='same', model='existing'), 'first-key')
                legacy.save_profile(ProviderProfile(id='same', model='imported'), 'second-key')
                legacy.set_setting('selected_profile', 'same')
                target.import_profiles(legacy)
                selected = target.setting('selected_profile')
                self.assertNotEqual(selected, 'same')
                self.assertEqual(next(p for p in target.profiles() if p.id == selected).model, 'imported')
                self.assertEqual(target.db.execute('SELECT count(*) FROM profiles').fetchone()[0], 0)
                target.import_profiles(legacy)
                self.assertEqual(len(models.profiles()), 2)
            finally:
                target.close()
                legacy.close()
                models.close()


if __name__ == '__main__':
    unittest.main()
