import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.network_ops import CommandResult
from line_check_assistant.sample_upgrade import (
    SingleTftpCopyUpgradeRequest,
    run_single_tftp_copy_upgrade,
    wait_for_upgrade_status,
)


class SampleUpgradeTests(unittest.TestCase):
    def test_wait_for_upgrade_status_reads_utf16_status_file(self):
        with tempfile.TemporaryDirectory() as directory:
            status_path = Path(directory) / "upgrade.status"
            status_path.write_text("now\tSTART\nnow\tTFTP_COMPLETE\n", encoding="utf-16")

            result = wait_for_upgrade_status(str(status_path), "TFTP_COMPLETE", 1, sleep_fn=Mock())

        self.assertTrue(result.ok)

    def test_wait_for_upgrade_status_hides_internal_securecrt_statuses(self):
        with tempfile.TemporaryDirectory() as directory:
            status_path = Path(directory) / "upgrade.status"
            status_path.write_text(
                "now\tSTART\n"
                "now\tSERIAL_CONNECTED\n"
                "now\tBOOT_LOGIN_ATTEMPT_1\n"
                "now\tPOST_TFTP_BOOT_RESET_SENT\n"
                "now\tDONE\n",
                encoding="utf-16",
            )
            output = Mock()

            result = wait_for_upgrade_status(str(status_path), "DONE", 1, on_output=output, sleep_fn=Mock())

        self.assertTrue(result.ok)
        output.assert_called_once_with("SecureCRT 状态：POST_TFTP_BOOT_RESET_SENT")

    def test_wait_for_upgrade_status_still_shows_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            status_path = Path(directory) / "upgrade.status"
            status_path.write_text("now\tERROR_FINAL_LOGIN_TIMEOUT\n", encoding="utf-16")
            output = Mock()

            result = wait_for_upgrade_status(str(status_path), "DONE", 1, on_output=output, sleep_fn=Mock())

        self.assertFalse(result.ok)
        output.assert_called_once_with("SecureCRT 状态：ERROR_FINAL_LOGIN_TIMEOUT")

    @patch("line_check_assistant.sample_upgrade.prepare_tftpd_server")
    @patch("line_check_assistant.sample_upgrade._has_status", return_value=False)
    @patch("line_check_assistant.sample_upgrade.set_static_ip")
    @patch("line_check_assistant.sample_upgrade.enable_adapter")
    @patch("line_check_assistant.sample_upgrade.automate_power_on")
    @patch("line_check_assistant.sample_upgrade.wait_for_upgrade_status")
    @patch("line_check_assistant.sample_upgrade.launch_securecrt_tftp_copy_upgrade")
    @patch("line_check_assistant.sample_upgrade.build_tftp_copy_upgrade_target")
    @patch("line_check_assistant.sample_upgrade.resolve_serial_log_directory")
    def test_single_tftp_copy_upgrade_orchestrates_one_sample(
        self,
        resolve_log_dir,
        build_target,
        launch_securecrt,
        wait_status,
        automate_power_on,
        enable_adapter,
        set_static_ip,
        has_status,
        prepare_tftpd,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            firmware = root / "tclinux_allinone"
            firmware.write_text("firmware", encoding="utf-8")
            target = SimpleNamespace(
                vlan="vlan101",
                log_path=str(root / "vlan101.log"),
                status_path=str(root / "vlan101.status"),
                boot_enter_signal_path=str(root / "vlan101.boot_enter.signal"),
                command_signal_path=str(root / "vlan101.signal"),
                final_login_signal_path=str(root / "vlan101.final_login.signal"),
                tftp_command="tftp 192.168.1.101:tclinux_allinone",
            )
            resolve_log_dir.return_value = root
            build_target.return_value = target
            launch_securecrt.return_value = SimpleNamespace(success=True, message="securecrt ok")
            wait_status.return_value = CommandResult(True, "status ok")
            automate_power_on.return_value = CommandResult(True, "power ok")
            calls = []
            enable_adapter.side_effect = lambda *_args: calls.append("enable") or CommandResult(True, "enabled")
            set_static_ip.side_effect = lambda *_args: calls.append("set_ip") or CommandResult(True, "set ip")
            prepare_tftpd.side_effect = lambda *_args, **_kwargs: calls.append("tftpd") or CommandResult(True, "tftpd ok")
            sleep = Mock()
            request = SingleTftpCopyUpgradeRequest(
                vlan="vlan101",
                server_interface="VLAN101",
                tftp_server_ip="192.168.1.101",
                firmware_path=firmware,
                power_serial_port="COM106",
                final_username="root",
                final_password="secret",
            )

            result = run_single_tftp_copy_upgrade(root, root / "Auto_Power_On_Off_Tool(2).exe", request, sleep_fn=sleep)

            self.assertTrue(result.ok)
            self.assertEqual(build_target.call_args.kwargs["final_username"], "root")
            self.assertEqual(build_target.call_args.kwargs["final_password"], "secret")
            self.assertTrue((root / "vlan101.boot_enter.signal").is_file())
            self.assertTrue((root / "vlan101.signal").is_file())
            self.assertTrue((root / "vlan101.final_login.signal").is_file())
            self.assertEqual(automate_power_on.call_count, 2)
            enable_adapter.assert_called_once_with("VLAN101")
            set_static_ip.assert_called_once_with("VLAN101", "192.168.1.101", "255.255.255.0")
            prepare_tftpd.assert_called_once()
            self.assertEqual(prepare_tftpd.call_args.args[2], "VLAN101")
            self.assertEqual(prepare_tftpd.call_args.args[3], "192.168.1.101")
            self.assertEqual(calls, ["enable", "set_ip", "tftpd"])
            has_status.assert_called_once_with(root / "vlan101.status", "POST_TFTP_BOOT_RESET_SENT")
            sleep.assert_any_call(90)
            sleep.assert_any_call(120)
            wait_status.assert_any_call(
                str(root / "vlan101.status"),
                "BOOT_LOGIN_COMPLETE",
                600,
                on_output=ANY,
                sleep_fn=sleep,
            )
            wait_status.assert_any_call(
                str(root / "vlan101.status"),
                "TFTP_COMPLETE",
                2400,
                on_output=ANY,
                sleep_fn=sleep,
            )
            wait_status.assert_any_call(
                str(root / "vlan101.status"),
                "DONE",
                1200,
                on_output=ANY,
                sleep_fn=sleep,
            )

    @patch("line_check_assistant.sample_upgrade.prepare_tftpd_server")
    @patch("line_check_assistant.sample_upgrade._has_status", return_value=True)
    @patch("line_check_assistant.sample_upgrade.set_static_ip")
    @patch("line_check_assistant.sample_upgrade.enable_adapter")
    @patch("line_check_assistant.sample_upgrade.automate_power_on")
    @patch("line_check_assistant.sample_upgrade.wait_for_upgrade_status")
    @patch("line_check_assistant.sample_upgrade.launch_securecrt_tftp_copy_upgrade")
    @patch("line_check_assistant.sample_upgrade.build_tftp_copy_upgrade_target")
    @patch("line_check_assistant.sample_upgrade.resolve_serial_log_directory")
    def test_single_tftp_copy_upgrade_skips_repower_after_boot_reset(
        self,
        resolve_log_dir,
        build_target,
        launch_securecrt,
        wait_status,
        automate_power_on,
        enable_adapter,
        set_static_ip,
        has_status,
        prepare_tftpd,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            firmware = root / "tclinux_allinone"
            firmware.write_text("firmware", encoding="utf-8")
            target = SimpleNamespace(
                vlan="vlan101",
                log_path=str(root / "vlan101.log"),
                status_path=str(root / "vlan101.status"),
                boot_enter_signal_path=str(root / "vlan101.boot_enter.signal"),
                command_signal_path=str(root / "vlan101.signal"),
                final_login_signal_path=str(root / "vlan101.final_login.signal"),
                tftp_command="tftp 192.168.1.101:tclinux_allinone",
            )
            resolve_log_dir.return_value = root
            build_target.return_value = target
            launch_securecrt.return_value = SimpleNamespace(success=True, message="securecrt ok")
            wait_status.return_value = CommandResult(True, "status ok")
            automate_power_on.return_value = CommandResult(True, "power ok")
            enable_adapter.return_value = CommandResult(True, "enabled")
            set_static_ip.return_value = CommandResult(True, "set ip")
            prepare_tftpd.return_value = CommandResult(True, "tftpd ok")
            sleep = Mock()
            request = SingleTftpCopyUpgradeRequest(
                vlan="vlan101",
                server_interface="VLAN101",
                tftp_server_ip="192.168.1.101",
                firmware_path=firmware,
                power_serial_port="COM106",
                final_username="root",
                final_password="secret",
            )

            result = run_single_tftp_copy_upgrade(root, root / "Auto_Power_On_Off_Tool(2).exe", request, sleep_fn=sleep)

            self.assertTrue(result.ok)
            self.assertEqual(build_target.call_args.kwargs["final_username"], "root")
            self.assertEqual(build_target.call_args.kwargs["final_password"], "secret")
            self.assertEqual(automate_power_on.call_count, 1)
            has_status.assert_called_once_with(root / "vlan101.status", "POST_TFTP_BOOT_RESET_SENT")
            self.assertTrue((root / "vlan101.final_login.signal").is_file())
            sleep.assert_any_call(90)
            sleep.assert_any_call(120)


if __name__ == "__main__":
    unittest.main()
