"""ADB targets are project-declared resource identities. No bridge or DUT is contacted."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from uuid import uuid4

from src.core.host_resource_lock import physical_key
from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.models.project_profile import adb_resource_key, adb_serial_from_key, dut_resource_keys, normalize_project_profile
from src.services.capability_jobs import CapabilityJobs
from src.services.project_profile_store import project_profile_digest
from src.services.resource_lease_service import ResourceLeaseService
from src.services.workspace_resources import WorkspaceResources


SOURCE = Path(__file__).resolve().parents[1]


class AdbResourceLeaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.serial = 'Adb-' + uuid4().hex
        self.key = adb_resource_key(self.serial)
        self.other = adb_resource_key(self.serial.lower())

    def child(self, *args):
        child = subprocess.run([sys.executable,'tests/fixtures/adb_resource_probe.py',*args], cwd=str(SOURCE), capture_output=True,
                               text=True, timeout=10)
        self.assertEqual(child.returncode,0,child.stderr)
        return child.stdout.strip()

    def test_case_sensitive_lossless_keys_and_old_digests(self):
        fixture = dict(test_type='power_cycle',duts=[dict(dut_id=str(uuid4()),label='D1',channel=1)])
        original = normalize_project_profile(fixture)
        self.assertNotIn('adb_serial',original['duts'][0])
        self.assertFalse(any(k.startswith('adb:') for k in dut_resource_keys(original['duts'])))
        fixture['duts'][0]['adb_serial'] = ''
        self.assertEqual(project_profile_digest(fixture),project_profile_digest(original))
        for serial in ('ABC','abc','adb:414243','[fe80::C%3]:5555','测试机 A'):
            with self.subTest(serial=serial):
                fixture['duts'][0]['adb_serial'] = serial
                profile = normalize_project_profile(fixture)
                key = adb_resource_key(serial)
                self.assertEqual(physical_key(physical_key(key)),key)
                self.assertEqual(adb_serial_from_key(key),serial)
                self.assertIn(key,dut_resource_keys(profile['duts'],[1]))
                self.assertNotIn(key,dut_resource_keys(profile['duts'],[2]))
        self.assertNotEqual(self.key,self.other)
        for key in ('adb:', 'adb:FF', 'adb:ff', 'adb:410a42', 'serial:4142'):
            self.assertIsNone(adb_serial_from_key(key))
        for value in (None,17,'A\nB','A\x00B'):
            fixture['duts'][0]['adb_serial'] = value
            with self.assertRaises(ValueError):
                normalize_project_profile(fixture)

    def test_same_project_declaration_in_two_projects_and_independent_host_process(self):
        coordinator = WorkspaceResources(self.root)
        self.addCleanup(coordinator.close)
        first = ResourceLeaseService(coordinator=coordinator,project_id='A',project_name='A')
        second = ResourceLeaseService(coordinator=coordinator,project_id='B',project_name='B')
        first.acquire('job-A',[self.key])
        self.addCleanup(first.release,'job-A')
        with self.assertRaises(CapabilityError) as busy:
            second.acquire('job-B',[self.key])
        self.assertEqual(busy.exception.code,'resource_busy')
        second.acquire('job-B',[self.other])
        second.release('job-B')
        self.assertEqual(self.child('probe',self.key,self.other).splitlines(),['resource_busy','acquired'])
        first.release('job-A')
        self.assertEqual(self.child('probe',self.key),'acquired')

    def test_abrupt_process_exit_preserves_only_original_adb_fence_until_review(self):
        self.child('crash',str(self.root),self.key)
        resources = WorkspaceResources(self.root)
        self.addCleanup(resources.close)
        self.assertIn('lost',resources.unknown_for('A'))
        with self.assertRaises(CapabilityError) as denied:
            resources.acquire('next','B','B',[self.key])
        self.assertEqual(denied.exception.code,'host_result_unknown')
        resources.acquire('other','B','B',[self.other])
        resources.release('other')
        resources.resolve('lost')
        resources.acquire('next','B','B',[self.key])
        resources.release('next')

    def test_unknown_job_on_adb_only_blocks_same_declared_identity(self):
        jobs = CapabilityJobs(self.root,ResourceLeaseService())
        self.addCleanup(jobs.close)
        auth = CapabilityAuthority('operator','session','first',(),source='gui',approved=True)
        def wait():
            deadline = time.monotonic()+5
            while not jobs.idle and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertTrue(jobs.idle)
        def unknown(job):
            job.event('test','fake dispatch',dispatched=True)
            raise RuntimeError('fake lost reply')
        receipt = jobs.start('fixture.start',{},auth,[self.key],unknown)
        wait()
        self.assertEqual(jobs.status(receipt['job_id'],auth)['state'],'unknown')
        with self.assertRaises(CapabilityError) as denied:
            jobs.start('fixture.start',{},replace(auth,operation_id='second'),[self.key],lambda job:None)
        self.assertEqual(denied.exception.code,'previous_result_unknown')
        jobs.start('fixture.start',{},replace(auth,operation_id='distinct'),[self.other],lambda job:{'ok':True})
        wait()
