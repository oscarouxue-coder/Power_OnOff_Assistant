"""Versioned project profiles use the same immutable revisions as device configuration."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import UUID

from src.models.project import PROJECT_FILE
from src.models.project_profile import normalize_project_profile
from src.services.project_profile_store import (
    PROFILE_FILE, project_profile_digest, read_project_profile, write_project_profile,
)
from src.services.project_store import configuration_digest, ProjectStore


class ProjectProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = ProjectStore(Path(__file__).resolve().parents[1])
        self.addCleanup(lambda: [self.store.close(c) for c in list(self.store.opened.values())])

    def test_typed_create_versions_the_imported_inputs_and_restores_unsaved_edits(self):
        inputs = dict(test_type='power_cycle', model='D1', software_version='S1', requirements='启动检查',
                      type_config={'target_cycles': 500}, optional_steps=['parameters'],
                      duts=[dict(label='设备一', channel=1, hardware_id='H1', target_firmware='F1',
                                 serial_port='COM1', network_adapter='Ethernet 1', vlan='vlan101', power_channel='A-1'),
                            dict(label='设备二')])
        target = self.root / 'A'
        target.mkdir()
        context = self.store.create(target, '项目一', profile=inputs)
        original = read_project_profile(context.config_dir)
        self.assertFalse(self.store.dirty(context))
        self.assertEqual(len(set(UUID(row['dut_id']) for row in original['duts'])), 2)
        self.assertEqual(read_project_profile(context.saved_root / 'Auto_power_on_off_tool/config'), original)
        self.assertEqual(original['type_config']['target_cycles'], 500)
        before_revision = context.saved_root
        original_run = self.store.snapshot(context) / 'Auto_power_on_off_tool/config'
        original_digest = project_profile_digest(original)
        draft = write_project_profile(context.config_dir, dict(original, model='D2'), expected_profile_digest=original_digest)
        self.assertTrue(self.store.dirty(context))
        self.store.close(context)
        context = self.store.open(target)
        self.assertEqual(read_project_profile(context.config_dir), draft)
        self.assertEqual(read_project_profile(original_run), original)
        self.assertEqual(read_project_profile(self.store.snapshot(context) / 'Auto_power_on_off_tool/config'), original)
        (context.history / 'preparation.sqlite3').write_bytes(b'source project evidence')
        duplicate = self.store.duplicate(context, self.root / '副本')
        self.assertNotEqual(context.identity.project_id, duplicate.identity.project_id)
        self.assertEqual(read_project_profile(duplicate.config_dir), original)
        self.assertFalse((duplicate.history / 'preparation.sqlite3').exists())
        self.store.discard(context)
        self.assertEqual(read_project_profile(context.config_dir), original)
        write_project_profile(context.config_dir, draft)
        self.store.save(context)
        self.assertEqual(read_project_profile(context.saved_root / 'Auto_power_on_off_tool/config'), draft)
        self.assertEqual(read_project_profile(before_revision / 'Auto_power_on_off_tool/config'), original)
        self.assertEqual(read_project_profile(original_run), original)
        self.assertFalse(self.store.dirty(context))

    def test_reading_legacy_profile_and_cancelling_an_edit_do_not_type_the_project(self):
        context = self.store.create(self.root / '旧工程', '旧工程')
        previous = configuration_digest(context.config_dir)
        self.assertIsNone(read_project_profile(context.config_dir))
        self.assertEqual(configuration_digest(context.config_dir), previous)
        self.assertFalse(self.store.dirty(context))
        saved = write_project_profile(context.config_dir, {'test_type': 'service_aging'}, expected_profile_digest='')
        self.assertEqual(saved['type_config'], {'target_hours': None, 'collectors': []})
        self.store.discard(context)
        self.assertFalse((context.config_dir / PROFILE_FILE).exists())

    def test_stale_editors_cannot_overwrite_the_winning_profile(self):
        context = self.store.create(self.root / '老化', '老化', profile={'test_type': 'service_aging'})
        first = read_project_profile(context.config_dir)
        original_digest = project_profile_digest(first)
        def edit(model):
            try:
                write_project_profile(context.config_dir, dict(first, model=model), expected_profile_digest=original_digest)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(edit, ('M1', 'M2'))), [False, True])
        current = read_project_profile(context.config_dir)
        with patch('src.services.project_profile_store.atomic_json', side_effect=OSError('模拟无法写入')):
            with self.assertRaises(OSError):
                write_project_profile(context.config_dir, dict(current, model='覆盖'))
        self.assertEqual(read_project_profile(context.config_dir), current)

    def test_field_feed_sources_require_selected_supported_businesses_and_preserve_old_profile_shape(self):
        old = {'target_hours': 168, 'collectors': ['iptv', 'voice', 'lan_ping']}
        def normalize(config):
            return normalize_project_profile({'test_type': 'service_aging', 'type_config': config})
        self.assertEqual(normalize(old)['type_config'], old)
        self.assertEqual(normalize(dict(old, feed_collectors=[])), normalize(old))
        for feeds in (['lan_ping'], ['cpu_memory'], ['tr069'], ['other'], 'voice', None):
            with self.subTest(feeds=feeds), self.assertRaises(ValueError):
                normalize(dict(old, feed_collectors=feeds))
        profile = normalize(dict(old, feed_collectors=['voice', 'iptv', 'voice']))
        self.assertEqual(profile['type_config']['feed_collectors'], ['iptv', 'voice'])
        context = self.store.create(self.root / '老化现场', '老化现场', profile=profile)
        run = self.store.snapshot(context)
        self.assertEqual(read_project_profile(run / 'Auto_power_on_off_tool/config'), profile)
        with self.assertRaises(ValueError):
            normalize_project_profile({'test_type': 'power_cycle', 'type_config': {'feed_collectors': []}})

    def test_dut_presence_is_optional_and_requires_its_own_field_feed(self):
        def profile(config):
            return normalize_project_profile({'test_type': 'service_aging', 'type_config': config})
        self.assertEqual(profile({'collectors': ['lan_ping']})['type_config'],
                         {'target_hours': None, 'collectors': ['lan_ping']})
        for config in ({'collectors': ['dut_presence']},
                       {'collectors': ['dut_presence', 'voice'], 'feed_collectors': ['voice']},
                       {'collectors': [], 'feed_collectors': ['dut_presence']}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                profile(config)
        config = dict(target_hours=168, collectors=['lan_ping', 'dut_presence'], feed_collectors=['dut_presence'])
        self.assertEqual(profile(config)['type_config'], config)

    def test_invalid_or_failed_typed_creation_leaves_original_directory_retryable(self):
        target = self.root / '新项目'
        target.mkdir()
        with self.assertRaises(ValueError):
            self.store.create(target, '不支持类型', profile={'test_type': 'other'})
        with patch('src.services.project_store.atomic_json', side_effect=OSError('模拟版本保存失败')):
            with self.assertRaises(OSError):
                self.store.create(target, '失败', profile={'test_type': 'power_cycle'})
        self.assertEqual(list(target.iterdir()), [])
        self.assertFalse(self.store.opened)
        context = self.store.create(target, '重试', profile={'test_type': 'power_cycle'})
        self.assertTrue((context.root / PROJECT_FILE).is_file())

    def test_validates_physical_slots_and_explicit_plan_fields(self):
        base = dict(test_type='service_aging', type_config=dict(target_hours=168, collectors=['iptv', 'easymesh']))
        accepted = normalize_project_profile(dict(base, duts=[{'label': '同型号'}, {'label': '同型号'}]))
        self.assertEqual(accepted['type_config']['target_hours'], 168)
        self.assertIsNone(accepted['duts'][0]['channel'])
        self.assertEqual(accepted, normalize_project_profile(accepted, assign_ids=False))
        for edits in (
            dict(schema_version=2), dict(type_config={'target_cycles': 5}), dict(optional_steps=['invalid']),
            dict(duts=[{'label': 'A', 'channel': 17}]), dict(duts=[{'label': 'A', 'password': 'unexpected'}]),
            dict(duts=[{'label': 'A', 'channel': 1}, {'label': 'B', 'channel': 1}]),
            dict(duts=[accepted['duts'][0], accepted['duts'][0]]),
        ):
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                normalize_project_profile(dict(base, **edits))

    def test_manifest_publish_failure_retracts_only_the_new_project_entries(self):
        target = self.root / '目标'
        target.mkdir()
        original = Path.rename
        def fail_publish(path, destination):
            if Path(destination) == target / PROJECT_FILE:
                (target / '现场临时文件.txt').write_text('保留', encoding='utf-8')
                raise OSError('模拟发布失败')
            return original(path, destination)
        with patch.object(Path, 'rename', fail_publish), self.assertRaises(OSError):
            self.store.create(target, '发布失败', profile={'test_type': 'power_cycle'})
        self.assertEqual([p.name for p in target.iterdir()], ['现场临时文件.txt'])
        self.assertFalse(self.store.opened)
        self.assertFalse(self.store.leases)

    def test_corrupt_profile_is_not_silently_reset(self):
        path = self.root / PROFILE_FILE
        path.write_bytes(b'{')
        with self.assertRaisesRegex(ValueError, '项目档案无效'):
            write_project_profile(self.root, {'test_type': 'power_cycle'})
        self.assertEqual(path.read_bytes(), b'{')
