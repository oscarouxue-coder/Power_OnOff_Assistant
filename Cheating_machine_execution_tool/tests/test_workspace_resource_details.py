"""Real temporary lease/fence records and holder identities. No physical I/O."""
from functools import partial
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from src.core.host_resource_lock import HostResourceLock
from src.models.capabilities import CapabilityError
from src.models.qt_device_inventory import DeviceLeaseView, ResourceLeaseEntry
from src.services.qt_workspace_adapter import QtWorkspaceAdapter
from src.services.workspace_resources import WorkspaceResources


class WorkspaceResourceDetailsTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        simulated_lock = partial(HostResourceLock, namespace='fixture-' + uuid4().hex)
        replacement = patch('src.services.workspace_resources.HostResourceLock', simulated_lock)
        replacement.start()
        self.addCleanup(replacement.stop)
        self.directory = Path(temp.name)
        self.resources = self.open_resources()

    def open_resources(self):
        resources = WorkspaceResources(self.directory)
        self.addCleanup(resources.close)
        return resources

    def test_real_c300_c600_targets_share_the_exact_olt_including_ipv6(self):
        resources = self.resources
        for host, target in (('192.0.2.61', 'gpon-olt_1/2/1'), ('192.0.2.62', 'gpon_olt-1/1/5'),
                             ('2001:db8::16', 'gpon_olt-1/1/5'), ('2001:db8::17', 'OLT')):
            pon, olt = 'pon:' + host + ':' + target, 'olt:' + host
            self.assertEqual(resources.keys([pon, olt]), (olt, pon.lower()))
            resources.acquire('pon-job', 'a', '项目 A', [pon])
            with self.assertRaisesRegex(CapabilityError, '项目 A'):
                resources.acquire('other', 'b', '项目 B', [olt])
            rows = resources.lease_entries()
            self.assertEqual({r.resource_key for r in rows}, {olt, pon.lower()})
            self.assertTrue(all(r.owner_id == 'pon-job' and r.state == 'held' for r in rows))
            resources.release('pon-job')
        self.assertEqual(resources.keys(['pon:192.0.2.63/1/2/3']),
                         ('olt:192.0.2.63', 'pon:192.0.2.63/1/2/3'))
        self.assertEqual(resources.keys(['pon:2001:db8::16/1/2/3']),
                         ('olt:2001:db8::16', 'pon:2001:db8::16/1/2/3'))

    def test_separate_holders_unknown_fences_and_reconciliation_do_not_change_other_owners(self):
        resources = self.resources
        resources.register_adapter('模拟VLAN', 'guid-1')
        resources.acquire('power-job', 'a', '同名项目', ['power:COM007', 'dut:hardware:SN01', 'channel:7'])
        resources.acquire('gui:monitor', 'a', '同名项目', ['serial:com7', 'adapter:模拟VLAN', 'wifi:host'])
        resources.acquire('scan-job', 'b', '同名项目', ['tftp:192.0.2.1:69'])
        rows = resources.lease_entries()
        self.assertEqual({r.resource_key for r in rows}, {
            'serial:com7', 'dut:hardware:sn01', 'adapter:模拟vlan', 'adapter:guid-1', 'wifi:host', 'tftp:192.0.2.1:69'})
        self.assertEqual([r.owner_id for r in rows if r.resource_key == 'serial:com7'], ['gui:monitor', 'power-job'])
        self.assertEqual({r.project_id for r in rows}, {'a', 'b'})
        resources.release('power-job', uncertain=True)
        rows = resources.lease_entries()
        self.assertIn(ResourceLeaseEntry('serial:com7', 'a', '同名项目', 'gui:monitor', 'held'), rows)
        self.assertIn(ResourceLeaseEntry('serial:com7', 'a', '同名项目', 'power-job', 'unresolved'), rows)
        self.assertEqual({r.resource_key for r in rows if r.state == 'unresolved'},
                         {'serial:com7', 'dut:hardware:sn01'})
        resources.resolve('power-job')
        self.assertTrue(all(r.state == 'held' for r in resources.lease_entries()))
        self.assertFalse(any(r.resource_key.startswith('dut:') for r in resources.lease_entries()))
        resources.release('gui:monitor')
        resources.release('scan-job')
        self.assertEqual(resources.lease_entries(), ())

    def test_old_or_foreign_process_owner_is_unverified_in_this_instance_until_reviewed(self):
        self.resources.acquire('job-A', 'a', '项目 A', ['dut:record:fixture'])
        other = self.open_resources()
        self.assertEqual(other.lease_entries(), (
            ResourceLeaseEntry('dut:record:fixture', 'a', '项目 A', 'job-A', 'unresolved'),))
        self.assertEqual(self.resources.lease_entries()[0].state, 'held')
        self.resources.release('job-A', uncertain=True)
        self.assertEqual(other.lease_entries()[0].state, 'unresolved')
        other.resolve('job-A')
        self.assertEqual(other.lease_entries(), ())
        self.assertEqual(self.resources.lease_entries(), ())

    def test_legacy_keys_and_orphaned_fences_are_visible_without_inventing_an_owner(self):
        resources = self.resources
        resources.acquire('original', 'a', '旧项目', ['dut:hardware:sn01'])
        resources.release('original', uncertain=True)
        with resources.fence.db as db:
            db.execute('UPDATE workspace_owners SET keys=NULL WHERE owner=?', ('original',))
            db.execute('INSERT INTO fence VALUES(?,?,?)', ('wifi:unknown', 'pre-migration-owner', 'unknown'))
        self.assertEqual(resources.lease_entries(), (
            ResourceLeaseEntry('dut:hardware:sn01', 'a', '旧项目', '', 'unresolved'),
            ResourceLeaseEntry('wifi:unknown', '', '', '', 'unresolved')))
        self.assertEqual(resources.fence.db.execute('SELECT COUNT(*) FROM fence').fetchone()[0], 2)

    def test_qt_rows_cover_all_keys_and_busy_fence_reader_retains_actual_sample_time(self):
        resources = self.resources
        resources.acquire('job', 'a', '项目', ['power:COM011', 'adapter:fixture', 'dut:hardware:device'])
        adapter = QtWorkspaceAdapter.__new__(QtWorkspaceAdapter)
        adapter._service = SimpleNamespace(resources=resources)
        adapter._resource_sample, adapter._device_leases = None, DeviceLeaseView()
        adapter.lock = RLock()
        adapter._sample_resources(5.0)
        before = adapter._device_leases
        self.assertEqual({r.resource_key for r in before.entries}, {'serial:com11', 'adapter:fixture','dut:hardware:device'})
        self.assertEqual(dict(before.owners), {'serial:com11': ('项目',), 'adapter:fixture': ('项目',)})
        with sqlite3.connect(str(self.directory / 'resource_fence.sqlite3'), timeout=0) as blocker:
            blocker.execute('BEGIN EXCLUSIVE')
            adapter._sample_resources(10.0)
            self.assertIs(adapter._device_leases, before)
            self.assertEqual(adapter._resource_sample.sampled_at, 5.0)
        resources.release('job', uncertain=True)
        adapter._sample_resources(12.0)
        self.assertTrue(all(row.state == 'unresolved' for row in adapter._device_leases.entries))
        self.assertFalse(adapter._device_leases.owners)
        self.assertEqual(adapter._resource_sample.serial, 0)
