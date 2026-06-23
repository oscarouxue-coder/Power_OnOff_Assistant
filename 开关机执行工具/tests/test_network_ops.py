import unittest
from unittest.mock import patch
import sys 
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.network_ops import CommandResult, enable_adapter, ping_host, run_line_check, static_ip_for_vlan


class StaticIpForVlanTests(unittest.TestCase):
    def test_uses_device_network_and_vlan_suffix(self):
        self.assertEqual(static_ip_for_vlan("VLAN108", "192.168.1.1"), "192.168.1.108")

    def test_accepts_adapter_display_name(self):
        self.assertEqual(static_ip_for_vlan("vlan24 [Up]", "10.20.30.254"), "10.20.30.24")

    def test_rejects_invalid_host_number(self):
        with self.assertRaisesRegex(ValueError, "1-254"):
            static_ip_for_vlan("VLAN300", "192.168.1.1")

    def test_rejects_invalid_device_ip(self):
        with self.assertRaisesRegex(ValueError, "样机管理 IP"):
            static_ip_for_vlan("VLAN108", "192.168.1")


class PingHostTests(unittest.TestCase):
    @patch("line_check_assistant.network_ops.subprocess.run")
    def test_binds_ping_to_channel_static_ip(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = "Reply from 192.168.1.1: bytes=32 time<1ms TTL=64"
        run.return_value.stderr = ""

        result = ping_host("192.168.1.1", "192.168.1.108")

        self.assertTrue(result.ok)
        command = run.call_args.args[0]
        self.assertEqual(
            command,
            ["ping", "-S", "192.168.1.108", "-n", "2", "-w", "1000", "192.168.1.1"],
        )

    def test_rejects_missing_source_ip(self):
        result = ping_host("192.168.1.1", "")
        self.assertFalse(result.ok)
        self.assertIn("PC 静态 IP", result.message)

    @patch("line_check_assistant.network_ops.time.sleep")
    @patch("line_check_assistant.network_ops.subprocess.run")
    def test_retries_same_bound_source_until_ping_succeeds(self, run, sleep):
        failed = unittest.mock.Mock(returncode=1, stdout="Request timed out.", stderr="")
        passed = unittest.mock.Mock(
            returncode=0,
            stdout="Reply from 192.168.1.1: bytes=32 time<1ms TTL=64",
            stderr="",
        )
        run.side_effect = [failed, passed]

        result = ping_host("192.168.1.1", "192.168.1.107")

        self.assertTrue(result.ok)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][1:3], ["-S", "192.168.1.107"])
        self.assertEqual(run.call_args_list[1].args[0][1:3], ["-S", "192.168.1.107"])
        self.assertIn("$ ping -S 192.168.1.107", result.output)
        sleep.assert_called_once_with(2.0)


class EnableAdapterTests(unittest.TestCase):
    @patch("line_check_assistant.network_ops.subprocess.run")
    def test_enables_selected_vlan_adapter(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = ""
        run.return_value.stderr = ""

        result = enable_adapter("VLAN107 [Disabled]")

        self.assertTrue(result.ok)
        self.assertEqual(
            run.call_args.args[0],
            ["netsh", "interface", "set", "interface", "name=VLAN107", "admin=enabled"],
        )

    @patch("line_check_assistant.network_ops.ping_host")
    @patch("line_check_assistant.network_ops.set_static_ip")
    @patch("line_check_assistant.network_ops.enable_adapter")
    def test_line_check_enables_adapter_before_setting_ip_and_ping(self, enable, set_ip, ping):
        calls = []
        enable.side_effect = lambda _alias: calls.append("enable") or CommandResult(True, "enabled")
        set_ip.side_effect = lambda *_args: calls.append("set_ip") or CommandResult(True, "set")
        ping.side_effect = lambda *_args: calls.append("ping") or CommandResult(True, "ping ok")

        result = run_line_check(
            "VLAN107",
            "192.168.1.107",
            "255.255.255.0",
            "192.168.1.1",
            settle_seconds=0,
        )

        self.assertTrue(result.ok)
        self.assertEqual(calls, ["enable", "set_ip", "ping"])


if __name__ == "__main__":
    unittest.main()
