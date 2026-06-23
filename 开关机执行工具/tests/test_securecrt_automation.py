import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from line_check_assistant.securecrt_automation import (
    SECURECRT_SCRIPT,
    _is_securecrt_main_window_title,
    build_serial_log_targets,
    launch_securecrt_serial_logs,
    resolve_serial_log_directory,
    vlan_to_serial_port,
)


class SecureCRTSerialLogTests(unittest.TestCase):
    def test_maps_vlan_number_to_matching_com_port(self):
        self.assertEqual(vlan_to_serial_port("vlan101"), "COM1")
        self.assertEqual(vlan_to_serial_port("VLAN108"), "COM8")
        self.assertEqual(vlan_to_serial_port("vlan148"), "COM48")

    def test_builds_securecrt_log_template(self):
        targets = build_serial_log_targets(
            ["vlan101", "vlan108"],
            Path("logs"),
        )

        self.assertEqual(targets[0].log_path, str(Path("logs") / "%H-%M%D.log"))
        self.assertEqual(targets[1].port, "COM8")
        self.assertEqual(targets[1].baud, 115200)

    def test_log_directory_prefers_f_drive_and_falls_back_to_d_drive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary_path = root / "primary"
            fallback_path = root / "fallback"
            existing_drive = root / "existing-drive"
            existing_drive.mkdir()

            selected = resolve_serial_log_directory(primary_path, fallback_path, existing_drive)
            self.assertEqual(selected, primary_path)
            self.assertTrue(primary_path.is_dir())

            missing_drive = root / "missing-drive"
            selected = resolve_serial_log_directory(primary_path, fallback_path, missing_drive)
            self.assertEqual(selected, fallback_path)
            self.assertTrue(fallback_path.is_dir())

    @patch("line_check_assistant.securecrt_automation.subprocess.Popen")
    @patch("line_check_assistant.securecrt_automation._wait_for_visible_securecrt_window", return_value=True)
    @patch("line_check_assistant.securecrt_automation.resolve_serial_log_directory")
    @patch("line_check_assistant.securecrt_automation.find_securecrt_executable")
    def test_launch_writes_manifest_and_uses_securecrt_script(self, find_securecrt, resolve_log_dir, wait_for_window, popen):
        find_securecrt.return_value = Path(r"C:\Program Files\VanDyke Software\Clients\SecureCRT.exe")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resolve_log_dir.return_value = root / "logs"

            result = launch_securecrt_serial_logs(root, ["vlan101", "vlan102"])

            self.assertTrue(result.success)
            self.assertEqual([target.port for target in result.targets], ["COM1", "COM2"])
            script_path = root / "securecrt_runtime" / "open_serial_logs.vbs"
            self.assertEqual(script_path.read_text(encoding="utf-8"), SECURECRT_SCRIPT)
            manifests = list((root / "securecrt_runtime").glob("serial_targets_*.txt"))
            self.assertEqual(len(manifests), 1)
            manifest_lines = manifests[0].read_text(encoding="utf-16").splitlines()
            self.assertEqual(manifest_lines[0].split("\t")[:2], ["vlan101", "COM1"])
            popen.assert_called_once()
            command = popen.call_args.args[0]
            self.assertLess(command.index("/ARG"), command.index("/SCRIPT"))
            wait_for_window.assert_called_once_with()

    def test_securecrt_script_connects_tabs_and_enables_logging(self):
        self.assertIn('#$language = "VBScript"', SECURECRT_SCRIPT)
        self.assertIn('OpenSessionConfiguration("Default_Serial")', SECURECRT_SCRIPT)
        self.assertIn('sessionName = fields(0)', SECURECRT_SCRIPT)
        self.assertNotIn('__LineCheckAssistant_', SECURECRT_SCRIPT)
        self.assertIn('sessionConfig.SetOption "Com Port", fields(1)', SECURECRT_SCRIPT)
        self.assertIn("sessionConfig.Save sessionName", SECURECRT_SCRIPT)
        self.assertIn("ConnectInTab", SECURECRT_SCRIPT)
        self.assertIn('SetOption "Log Filename V2", fields(2)', SECURECRT_SCRIPT)
        self.assertIn('SetOption "Log Mode", 1', SECURECRT_SCRIPT)
        self.assertIn('SetOption "Start Log Upon Connect", True', SECURECRT_SCRIPT)
        self.assertIn('SetOption "New Log File At Midnight", True', SECURECRT_SCRIPT)
        self.assertIn(
            'SetOption "Custom Log Message Each Line", "[%Y-%M-%D %h:%m:%s] "',
            SECURECRT_SCRIPT,
        )
        self.assertIn('SetOption "Log Timestamp Each Line", False', SECURECRT_SCRIPT)
        self.assertLess(
            SECURECRT_SCRIPT.index('SetOption "Custom Log Message Each Line"'),
            SECURECRT_SCRIPT.index("ConnectInTab"),
        )
        self.assertNotIn("DeleteSession", SECURECRT_SCRIPT)
        self.assertNotIn("Python3", SECURECRT_SCRIPT)

    def test_securecrt_error_dialog_is_not_treated_as_main_window(self):
        self.assertFalse(_is_securecrt_main_window_title("SecureCRT"))
        self.assertTrue(_is_securecrt_main_window_title("not connected - SecureCRT"))

    @patch("line_check_assistant.securecrt_automation.subprocess.Popen")
    @patch("line_check_assistant.securecrt_automation._wait_for_visible_securecrt_window", return_value=False)
    @patch("line_check_assistant.securecrt_automation.resolve_serial_log_directory")
    @patch("line_check_assistant.securecrt_automation.find_securecrt_executable")
    def test_launch_fails_when_securecrt_has_no_visible_window(self, find_securecrt, resolve_log_dir, _wait_for_window, _popen):
        find_securecrt.return_value = Path(r"C:\Program Files\VanDyke Software\Clients\SecureCRT.exe")
        with tempfile.TemporaryDirectory() as directory:
            resolve_log_dir.return_value = Path(directory) / "logs"
            result = launch_securecrt_serial_logs(Path(directory), ["vlan101"])

        self.assertFalse(result.success)
        self.assertIn("未检测到可见主窗口", result.message)


if __name__ == "__main__":
    unittest.main()
