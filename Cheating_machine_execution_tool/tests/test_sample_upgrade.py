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

    @patch("line_check_assistant.sample_upgrade.prepare_tftpd_server")
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
            prepare_tftpd.return_value = CommandResult(True, "tftpd ok")
            sleep = Mock()
            request = SingleTftpCopyUpgradeRequest(
                vlan="vlan101",
                server_interface="VLAN101",
                tftp_server_ip="192.168.1.101",
                firmware_path=firmware,
                power_serial_port="COM106",
            )

            result = run_single_tftp_copy_upgrade(root, root / "Auto_Power_On_Off_Tool(2).exe", request, sleep_fn=sleep)

            self.assertTrue(result.ok)
            self.assertTrue((root / "vlan101.boot_enter.signal").is_file())
            self.assertTrue((root / "vlan101.signal").is_file())
            self.assertTrue((root / "vlan101.final_login.signal").is_file())
            self.assertEqual(automate_power_on.call_count, 2)
            prepare_tftpd.assert_called_once()
            self.assertEqual(prepare_tftpd.call_args.args[2], "VLAN101")
            self.assertEqual(prepare_tftpd.call_args.args[3], "192.168.1.101")
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


if __name__ == "__main__":
    unittest.main()
