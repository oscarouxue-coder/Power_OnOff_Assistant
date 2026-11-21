"""No serial/network/device operations: real process locks and temporary identity stores."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

from src.core.host_resource_lock import HostResourceLock, HostResourceBusy, physical_key
from src.services.remote_instance_identity import RemoteInstanceIdentity


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def identity(self, **kwargs):
        value = RemoteInstanceIdentity(self.root / "app", storage_root=self.root / "data", **kwargs)
        self.addCleanup(value.close)
        return value

    def test_restart_preserves_permanent_id_and_changes_run(self):
        first = self.identity(slot=1)
        permanent, boot = first.instance_id, first.run_id
        first.close()
        second = self.identity(slot=1)
        self.assertEqual(permanent, second.instance_id)
        self.assertNotEqual(boot, second.run_id)

    def test_same_directory_multiple_slots_are_independent(self):
        first, second = self.identity(), self.identity()
        self.assertEqual((1, 2), (first.slot, second.slot))
        self.assertNotEqual(first.instance_id, second.instance_id)
        self.assertNotEqual(first.directory, second.directory)

    def test_explicit_busy_slot_and_copied_identity_are_rejected(self):
        first = self.identity(slot=1)
        with self.assertRaises(HostResourceBusy):
            self.identity(slot=1)
        first.close()
        with self.assertRaises(ValueError):
            RemoteInstanceIdentity(self.root / "copy", storage_root=self.root / "data", slot=1)

    def test_normalization_unifies_power_and_serial_bus(self):
        self.assertEqual(physical_key("serial:COM001"), physical_key("power:com1"))
        self.assertEqual(physical_key("adapter:VLAN101"), physical_key("adapter:vlan101"))

    def test_same_install_path_on_distinct_local_stores_gets_distinct_identity(self):
        first = self.identity(slot=1)
        second = RemoteInstanceIdentity(self.root / "app", storage_root=self.root / "other-machine-user-data", slot=1)
        try:
            self.assertNotEqual(first.instance_id, second.instance_id)
        finally:
            second.close()

    def test_cross_process_contention_and_release(self):
        key = "serial:fake-" + uuid.uuid4().hex
        lock = HostResourceLock([key]).acquire()
        self.addCleanup(lock.close)
        script = ("import sys; from src.core.host_resource_lock import HostResourceLock; "
                  "lock=HostResourceLock([sys.argv[1]]); lock.acquire(); lock.close()")
        result = subprocess.run([sys.executable, "-X", "utf8", "-c", script, key], capture_output=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn(b"HostResourceBusy", result.stderr)
        lock.close()
        result = subprocess.run([sys.executable, "-c", script, key], capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_partial_acquisition_rolls_back(self):
        key = "serial:" + uuid.uuid4().hex
        # A genuinely different process must hold the lock; local nested locks are valid.
        script = ("import sys; from src.core.host_resource_lock import HostResourceLock; "
                  "lock=HostResourceLock([sys.argv[1]]).acquire(); print('ready',flush=True); input()")
        process = subprocess.Popen([sys.executable, "-c", script, key], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual("ready", process.stdout.readline().strip())
            guard = HostResourceLock(["adapter:" + key, key])
            with self.assertRaises(HostResourceBusy):
                guard.acquire()
            self.assertEqual([], guard.acquired)
        finally:
            process.communicate("\n", timeout=5)

    def test_child_gui_power_and_adapter_operations_are_rejected_before_io(self):
        key = "COM987654"
        guard = HostResourceLock(["power:" + key, "adapter:synthetic-adapter"]).acquire()
        self.addCleanup(guard.close)
        script = '''
from unittest.mock import Mock, patch
from src.core.power_supply import ProgrammablePowerSupply, PowerSupplyError
from line_check_assistant.network_ops import enable_adapter
factory = Mock(side_effect=AssertionError('must not access serial'))
try:
    ProgrammablePowerSupply('COM987654', serial_factory=factory).open()
    raise AssertionError('power lock not enforced')
except PowerSupplyError:
    factory.assert_not_called()
with patch('line_check_assistant.network_ops.subprocess.run', side_effect=AssertionError('must not touch adapter')):
    assert not enable_adapter('synthetic-adapter').ok
print('NO_DEVICE_IO')
'''
        result = subprocess.run([sys.executable, "-X", "utf8", "-c", script], capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(b"NO_DEVICE_IO", result.stdout)
