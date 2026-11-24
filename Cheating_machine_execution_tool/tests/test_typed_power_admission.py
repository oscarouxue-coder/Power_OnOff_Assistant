"""Exercise typed power admission and single-DUT recovery using real local job storage."""
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from qt_execution_fakes import configure_project, install_native_fixture_locks
from line_check_assistant.config_store import ChannelConfigStore
from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.services.capability_service import CapabilityService
from src.services.pipeline_orchestrator import SubTaskResult
from src.services.project_profile_store import (
    PROFILE_FILE, project_profile_digest, read_project_profile, write_project_profile,
)
from src.services.project_store import ProjectStore
from src.services.workspace_service import WorkspaceService


class TypedPowerAdmissionTests(unittest.TestCase):
    def setUp(self):
        install_native_fixture_locks(self)
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.workspace = WorkspaceService(Path(__file__).resolve().parents[1], directory=root / 'workspace')
        self.addCleanup(self.workspace.close)
        self.context = self.workspace.projects.create(root / 'project', '两个 DUT', profile={
            'test_type': 'power_cycle', 'type_config': {'target_cycles': 100},
            'duts': [dict(channel=n, label=f'DUT {n}', hardware_id=f'fixture-{n}', adb_serial=f'Fixture-A{n}')
                     for n in (1, 7)]})
        self.addCleanup(self.workspace.projects.close, self.context)
        configure_project(self.workspace, self.context)
        self.profile = read_project_profile(self.context.config_dir)
        store = ChannelConfigStore(self.context.config_dir / 'network_card_ip.ini')
        self.snapshot = dict(channels=[asdict(c) for c in store.load()], upgrade_settings={},
                             power_serial_port=store.load_power_serial_port())
        self.service = CapabilityService(self.context.history / 'ai/business', Mock(), lambda: self.snapshot,
            tool_root=self.context.working_root, enabled_modules={'devices'}, project_context=self.context)
        self.addCleanup(self.close_service)
        self.authority = CapabilityAuthority('local-user', 'session', 'original', (1, 7),
                                             mode='full_access', grant_id='grant')
        self.session = SimpleNamespace(request=SimpleNamespace(connect_wifi_enable=False), is_recovering=False,
            can_resume=lambda number: number == 7, submit=Mock(return_value=True), failed=set())
        def engine(ctx, emit):
            ctx.app.power_test_resume_session = self.session
            return SimpleNamespace(run=lambda tasks: [SubTaskResult('legacy_power_test', False)])
        self.service.devices.pipeline_factory = Mock(side_effect=engine)

    def close_service(self):
        self.service.jobs.begin_close()
        self.wait_jobs()
        self.service.jobs.close()

    def wait_jobs(self):
        deadline = time.monotonic() + 5
        while not self.service.jobs.idle and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(self.service.jobs.idle)

    def parent(self):
        job = self.service.execute('aging.start', {'channel_ids': [1, 7]}, self.authority)
        self.wait_jobs()
        status = self.service.jobs.status(job['job_id'], self.authority)
        self.assertEqual(status['state'], 'failed')
        return status

    def resume(self, parent):
        return self.service.execute('aging.resume', dict(channel_ids=[7], parent_job_id=parent['job_id']),
                                    replace(self.authority, operation_id=uuid4().hex))

    def test_resume_leases_only_the_same_failed_dut_and_reuses_parent_session(self):
        parent = self.parent()
        digest = project_profile_digest(self.profile)
        self.assertEqual(parent['request']['arguments']['project_profile_digest'], digest)
        result = self.resume(parent)
        self.wait_jobs()
        status = self.service.jobs.status(result['job_id'], self.authority)
        self.assertEqual(status['state'], 'succeeded', status['result'])
        self.assertEqual(status['request']['arguments']['project_profile_digest'], digest)
        self.assertEqual({key for key in status['request']['resources'] if key.startswith('dut:')},
                         {'dut:hardware:fixture-7', 'dut:record:' + self.profile['duts'][1]['dut_id']})
        self.assertIn('dut:hardware:fixture-1', parent['request']['resources'])
        from src.models.project_profile import adb_resource_key
        self.assertEqual({k for k in parent['request']['resources'] if k.startswith('adb:')},
                         {adb_resource_key('Fixture-A1'), adb_resource_key('Fixture-A7')})
        self.assertEqual({k for k in status['request']['resources'] if k.startswith('adb:')},
                         {adb_resource_key('Fixture-A7')})
        self.session.submit.assert_called_once_with(7)

    def test_resource_grant_and_worker_both_recheck_the_approved_profile(self):
        updated = dict(self.profile, duts=[dict(dut, hardware_id='replaced') for dut in self.profile['duts']])
        def change_at_lease(owner, keys):
            self.assertIn('dut:hardware:fixture-7', keys)
            write_project_profile(self.context.config_dir, updated)
            self.workspace.projects.save(self.context)
            return True
        self.service.resources.admissible = change_at_lease
        with self.assertRaisesRegex(CapabilityError, '对应的项目档案发生变化'):
            self.service.execute('aging.start', {'channel_ids': [1, 7]}, self.authority)
        self.assertFalse(self.service.resources.busy)
        self.service.resources.admissible = lambda owner, keys: True
        take_snapshot = ProjectStore.snapshot
        def changed_archive(store, context):
            path = take_snapshot(store, context)
            write_project_profile(path / 'Auto_power_on_off_tool/config', self.profile)
            return path
        with patch.object(ProjectStore, 'snapshot', changed_archive):
            result = self.parent()
        self.assertFalse(result['result']['dispatched'])
        self.assertIn('运行快照', result['result']['error'])
        self.service.devices.pipeline_factory.assert_not_called()

    def test_resume_rejects_changed_parent_configuration_and_removed_type(self):
        parent = self.parent()
        projection = self.service.devices.latest_aging[2]
        original = projection.context.configuration_root / 'Auto_power_on_off_tool/config/config.ini'
        previous = original.read_bytes()
        original.write_bytes(previous + b'\n# replaced\n')
        with self.assertRaisesRegex(CapabilityError, '原批次运行快照'):
            self.resume(parent)
        original.write_bytes(previous)
        current = self.context.config_dir / 'config.ini'
        current.write_bytes(previous + b'\n# other saved settings\n')
        self.workspace.projects.save(self.context)
        with self.assertRaisesRegex(CapabilityError, '当前执行配置与原批次'):
            self.resume(parent)
        (self.context.config_dir / PROFILE_FILE).unlink()
        self.workspace.projects.save(self.context)
        with self.assertRaisesRegex(CapabilityError, '续跑 DUT 档案'):
            self.resume(parent)
        self.session.submit.assert_not_called()

    def test_resume_rechecks_parent_session_after_acquiring_resources(self):
        parent = self.parent()
        def replace_at_lease(owner, keys):
            self.service.devices.latest_aging = None
            return True
        self.service.resources.admissible = replace_at_lease
        with self.assertRaisesRegex(CapabilityError, '原批次已变化'):
            self.resume(parent)
        self.session.submit.assert_not_called()
        self.assertFalse(self.service.resources.busy)

    def test_unknown_dut_blocks_new_operation_even_with_no_channel_or_interface_overlap(self):
        jobs = self.service.jobs
        def request(key, state):
            return jobs.start('fixture', {'label': uuid4().hex},
                replace(self.authority, operation_id=uuid4().hex), [key],
                lambda ctx: dict(ok=state == 'succeeded', state=state))
        for key in ('dut:record:fixture', 'dut:hardware:fixture'):
            with self.subTest(key=key):
                request(key, 'unknown')
                self.wait_jobs()
                with self.assertRaisesRegex(CapabilityError, '结果未知'):
                    request(key, 'succeeded')
        unrelated = request('dut:hardware:other', 'succeeded')
        self.wait_jobs()
        self.assertEqual(jobs.status(unrelated['job_id'], self.authority)['state'], 'succeeded')
