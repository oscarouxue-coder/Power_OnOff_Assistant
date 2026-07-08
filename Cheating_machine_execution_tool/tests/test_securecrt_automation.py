import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.securecrt_automation import (
    SECURECRT_TFTP_COPY_UPGRADE_SCRIPT,
    SECURECRT_SCRIPT,
    _is_securecrt_main_window_title,
    _securecrt_command,
    _securecrt_runtime_dir,
    _wait_for_new_securecrt_window,
    _wait_for_securecrt_upgrade_started,
    build_tftp_copy_upgrade_target,
    build_serial_log_targets,
    launch_securecrt_tftp_copy_upgrade,
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
    @patch("line_check_assistant.securecrt_automation._wait_for_new_securecrt_window", return_value=True)
    @patch("line_check_assistant.securecrt_automation._securecrt_window_handles", return_value={101, 102})
    @patch("line_check_assistant.securecrt_automation.resolve_serial_log_directory")
    @patch("line_check_assistant.securecrt_automation.find_securecrt_executable")
    def test_launch_writes_manifest_and_uses_securecrt_script(self, find_securecrt, resolve_log_dir, existing_windows, wait_for_window, popen):
        find_securecrt.return_value = Path(r"C:\Program Files\VanDyke Software\Clients\SecureCRT.exe")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            temp_root = root / "ascii_temp"
            temp_root.mkdir()
            resolve_log_dir.return_value = root / "logs"

            with patch.dict(os.environ, {"TMP": str(temp_root), "TEMP": str(temp_root)}):
                result = launch_securecrt_serial_logs(root, ["vlan101", "vlan102"])

            self.assertTrue(result.success)
            self.assertEqual([target.port for target in result.targets], ["COM1", "COM2"])
            runtime_dir = temp_root / "LineCheckAssistant" / "securecrt_runtime"
            script_path = runtime_dir / "open_serial_logs.vbs"
            self.assertEqual(script_path.read_text(encoding="utf-8"), SECURECRT_SCRIPT)
            manifests = list(runtime_dir.glob("serial_targets_*.txt"))
            self.assertEqual(len(manifests), 1)
            manifest_lines = manifests[0].read_text(encoding="utf-16").splitlines()
            self.assertEqual(manifest_lines[0].split("\t")[:2], ["vlan101", "COM1"])
            popen.assert_called_once()
            command = popen.call_args.args[0]
            self.assertEqual(command[1], "/ARG")
            self.assertLess(command.index("/ARG"), command.index("/SCRIPT"))
            wait_for_window.assert_called_once_with(popen.return_value, {101, 102})

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
        self.assertIn('SetOption "Emulation", "ANSI"', SECURECRT_SCRIPT)
        self.assertIn('SetOption "Output Transformer Name", "Default"', SECURECRT_SCRIPT)
        self.assertIn('SetOption "Use Unicode Line Drawing", False', SECURECRT_SCRIPT)
        self.assertIn('SetOption "Enable Xterm-256color", False', SECURECRT_SCRIPT)
        self.assertIn('SetOption "Enable Xterm-Truecolor", False', SECURECRT_SCRIPT)
        self.assertIn('SetOption "DTR Flow Control", False', SECURECRT_SCRIPT)
        self.assertIn('SetOption "RTS Flow Control", False', SECURECRT_SCRIPT)
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

    def test_builds_tftp_copy_upgrade_target(self):
        target = build_tftp_copy_upgrade_target(
            "VLAN148",
            "192.168.1.148",
            Path("logs"),
            restore_factory=True,
            final_username="root",
            final_password="secret",
        )

        self.assertEqual(target.vlan, "vlan148")
        self.assertEqual(target.port, "COM48")
        self.assertEqual(target.tftp_command, "tftp 192.168.1.148:tclinux_allinone")
        self.assertEqual(target.transfer_method, "Tftp指令")
        self.assertTrue(target.restore_factory)
        self.assertEqual(target.final_username, "root")
        self.assertEqual(target.final_password, "secret")
        self.assertTrue(target.log_path.endswith(".log"))
        self.assertTrue(target.status_path.endswith(".status"))
        self.assertTrue(target.boot_enter_signal_path.endswith(".boot_enter.signal"))
        self.assertTrue(target.command_signal_path.endswith(".signal"))
        self.assertTrue(target.final_login_signal_path.endswith(".final_login.signal"))

    def test_builds_tftp_put_upgrade_target(self):
        target = build_tftp_copy_upgrade_target(
            "VLAN101",
            "192.168.1.101",
            Path("logs"),
            transfer_method="Tftp Put",
        )

        self.assertEqual(target.transfer_method, "Tftp Put")

    @patch("line_check_assistant.securecrt_automation._securecrt_process_id_for_window", return_value=27788)
    @patch("line_check_assistant.securecrt_automation._securecrt_window_handles", side_effect=[{101}, {101, 202}])
    @patch("line_check_assistant.securecrt_automation.subprocess.Popen")
    @patch("line_check_assistant.securecrt_automation._wait_for_securecrt_upgrade_started", return_value=True)
    @patch("line_check_assistant.securecrt_automation.find_securecrt_executable")
    def test_upgrade_launch_manifest_includes_transfer_method_and_new_window_pid(self, find_securecrt, _wait_started, popen, _window_handles, _process_id):
        find_securecrt.return_value = Path(r"C:\Program Files\VanDyke Software\Clients\SecureCRT.exe")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            temp_root = root / "ascii_temp"
            temp_root.mkdir()
            target = build_tftp_copy_upgrade_target(
                "VLAN101",
                "192.168.1.101",
                root,
                transfer_method="Tftp Put",
            )

            with patch.dict(os.environ, {"TMP": str(temp_root), "TEMP": str(temp_root)}):
                result = launch_securecrt_tftp_copy_upgrade(root, target)

            self.assertTrue(result.success)
            runtime_dir = temp_root / "LineCheckAssistant" / "securecrt_runtime"
            manifests = list(runtime_dir.glob("tftp_copy_upgrade_*.txt"))
            self.assertEqual(len(manifests), 1)
            fields = manifests[0].read_text(encoding="utf-16").split("\t")
            self.assertEqual(fields[11], "0")
            self.assertEqual(fields[18], "Tftp Put")
            self.assertEqual(result.securecrt_pids, (27788,))
            popen.assert_called_once()

    def test_upgrade_launch_accepts_status_file_when_existing_securecrt_window_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status_path = root / "upgrade.status"
            status_path.write_text("now\tSTART\n", encoding="utf-16")
            process = type("Process", (), {"poll": lambda self: None})()

            result = _wait_for_securecrt_upgrade_started(process, status_path, timeout_seconds=0.1)

        self.assertTrue(result)

    def test_securecrt_runtime_prefers_ascii_temp_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            temp_root = root / "ascii_temp"
            with patch.dict(os.environ, {"TMP": str(temp_root), "TEMP": str(temp_root)}):
                runtime_dir = _securecrt_runtime_dir(root / "中文项目")

        self.assertEqual(runtime_dir, temp_root / "LineCheckAssistant" / "securecrt_runtime")

    @patch("line_check_assistant.securecrt_automation._activate_window")
    @patch("line_check_assistant.securecrt_automation._find_securecrt_window", side_effect=[0, 123])
    def test_upgrade_wait_keeps_polling_after_launcher_process_exits(self, _find_window, _activate_window):
        with tempfile.TemporaryDirectory() as directory:
            status_path = Path(directory) / "missing.status"
            process = type("Process", (), {"poll": lambda self: 0})()

            result = _wait_for_securecrt_upgrade_started(process, status_path, timeout_seconds=0.6)

        self.assertTrue(result)
        _activate_window.assert_called_once_with(123)

    @patch("line_check_assistant.securecrt_automation._activate_window")
    @patch("line_check_assistant.securecrt_automation._securecrt_window_handles", side_effect=[{101}, {101, 202}])
    def test_window_wait_keeps_polling_after_launcher_process_exits(self, _window_handles, _activate_window):
        process = type("Process", (), {"poll": lambda self: 0})()

        result = _wait_for_new_securecrt_window(process, {101}, timeout_seconds=0.6)

        self.assertTrue(result)
        _activate_window.assert_called_once_with(202)

    def test_securecrt_command_keeps_arg_before_script_order(self):
        command = _securecrt_command(
            Path(r"C:\Program Files\VanDyke Software\Clients\SecureCRT.exe"),
            Path("manifest.txt"),
            Path("upgrade.vbs"),
        )

        self.assertEqual(command[1:], ["/ARG", "manifest.txt", "/SCRIPT", "upgrade.vbs"])

    def test_tftp_copy_upgrade_script_waits_for_boot_and_transfer_markers(self):
        self.assertIn('Function PressEnterUntilBootUserName', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('Sub SetLiveMonitorMode(tab)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('Sub SetScriptWaitMode(tab)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('Function WaitForFinalLoginSignalOrBootReset', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('tab.Screen.WaitForStrings("Boot", "Bood", 1)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('tab.Screen.Send "reset" & vbCr', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"POST_TFTP_BOOT_RESET_SENT"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        boot_wait_index = SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index('tab.Screen.WaitForStrings("Boot", "Bood", 1)')
        reset_sleep_index = SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index("crt.Sleep 1000", boot_wait_index)
        reset_send_index = SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index('tab.Screen.Send "reset" & vbCr', boot_wait_index)
        self.assertLess(reset_sleep_index, reset_send_index)
        self.assertIn(
            'WaitForStrings("UserName:", "Username:", "User Name:", 1)',
            SECURECRT_TFTP_COPY_UPGRADE_SCRIPT,
        )
        username_wait_index = SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index(
            'WaitForStrings("UserName:", "Username:", "User Name:", 1)'
        )
        retry_enter_index = SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index(
            'tab.Screen.Send vbCr',
            username_wait_index,
        )
        self.assertLess(username_wait_index, retry_enter_index)
        self.assertIn('bootEnterSignalPath = fields(13)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('commandSignalPath = fields(14)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('finalLoginSignalPath = fields(15)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('finalUsername = fields(16)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('finalPassword = fields(17)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('transferMethod = fields(18)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('Sub CloseUpgradeTab(tab, fso, statusPath)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('WriteStatus fso, statusPath, "SECURECRT_TAB_CLOSE_REQUESTED"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"BOOT_ENTER_SIGNAL_WAITING"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('WaitForFile(fso, bootEnterSignalPath, 1200)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('PressEnterUntilBootUserName(tab, 240)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertNotIn('WaitForString("1", 240)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"BOOT_ENTER_RETRY_STARTED"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"BOOT_USERNAME_PROMPT_FOUND"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        username_prompt_index = SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index('"BOOT_USERNAME_PROMPT_FOUND"')
        username_sleep_index = SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index("crt.Sleep 1000", username_prompt_index)
        username_send_index = SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index(
            "SendUserNameAndConfirmEcho(tab, username)",
            username_prompt_index,
        )
        self.assertLess(username_sleep_index, username_send_index)
        self.assertIn('username = "telecomadmin"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('password = "nE7jA%5m"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertNotIn('Sub ClearInputLine(tab)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertNotIn('tab.Screen.Send Chr(21)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertNotIn('tab.Screen.Send Chr(8)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertNotIn('tab.Screen.Send Chr(127)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('Function SendUserNameAndConfirmEcho(tab, value)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('tab.Screen.Send value', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('tab.Screen.WaitForString(value, 5)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('SendUserNameAndConfirmEcho(tab, username)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"BOOT_USERNAME_ECHO_MISSED"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('Sub SendPasswordAndEnter(tab, value)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('SendPasswordAndEnter tab, password', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertNotIn('SendTextSlow', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('Function LoginFinalSystemWithRetry', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('Function WaitForFinalShellReady', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('WaitForStrings("#", ">", "Login incorrect", "incorrect", 1)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertNotIn('WaitForStrings("#", ">", "Login incorrect", "incorrect", "login", "Login", 1)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('For finalLoginAttempt = 1 To 5', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('crt.Sleep 2000', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('loginTimeout = 900', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('loginTimeout = 2', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"FINAL_LOGIN_ATTEMPT_" & CStr(finalLoginAttempt)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"FINAL_LOGIN_RESULT_" & finalLoginResult', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"ERROR_FINAL_LOGIN_RETRY_EXHAUSTED"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('LoginFinalSystemWithRetry(tab, fso, statusPath, finalUsername, finalPassword)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('For loginAttempt = 1 To 3', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"BOOT_LOGIN_ATTEMPT_" & CStr(loginAttempt)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"BOOT_USERNAME_SENT"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn(
            'WaitForStrings("Passvord", "Passvord:", "Password", "Password:", "password", "password:", 30)',
            SECURECRT_TFTP_COPY_UPGRADE_SCRIPT,
        )
        self.assertIn('"BOOT_PASSWORD_PROMPT_FOUND"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"BOOT_PASSWORD_SENT"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('Function WaitForBootShellReady', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('WaitForStrings("Bood", "#", ">", "UserName:", "Username:", "User Name:", "Passvord:", "Password:", "password:", "Login incorrect", "incorrect", 1)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('WaitForBootShellReady = "READY"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('WaitForBootShellReady = "USERNAME"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('WaitForBootShellReady = "PASSWORD"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"BOOT_LOGIN_RESULT_" & loginResult', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('If Not bootLoginComplete Then', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"BOOT_SHELL_READY"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"BOOT_LOGIN_COMPLETE"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('WaitForFile(fso, commandSignalPath, 300)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('WaitForStrings("done", "write", 1)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('If transferMethod = "Tftp Put" Then', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"TFTP_PUT_COMPLETE_SIGNAL_FOUND"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"TFTP_COMPLETE"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        put_branch_index = SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index('If transferMethod = "Tftp Put" Then')
        command_send_index = SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index('tab.Screen.Send tftpCommand & vbCr', put_branch_index)
        else_index = SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index("Else", put_branch_index)
        self.assertLess(else_index, command_send_index)
        self.assertIn('"FINAL_LOGIN_MONITORING_STARTED"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertLess(
            SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index('SetLiveMonitorMode tab', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index('"TFTP_COMPLETE"')),
            SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index('WaitForFinalLoginSignalOrBootReset(tab, fso, finalLoginSignalPath, statusPath, 1200)'),
        )
        self.assertLess(
            SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index('WaitForFinalLoginSignalOrBootReset(tab, fso, finalLoginSignalPath, statusPath, 1200)'),
            SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index('SetScriptWaitMode tab', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index('WaitForFinalLoginSignalOrBootReset(tab, fso, finalLoginSignalPath, statusPath, 1200)')),
        )
        self.assertIn('WaitForFinalLoginSignalOrBootReset(tab, fso, finalLoginSignalPath, statusPath, 1200)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('If restoreFactory = "1" Then', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('Sub SendFactoryResetAndWait(tab, fso, statusPath, factoryResetCommand)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('tab.Screen.Send factoryResetCommand', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('tab.Screen.WaitForString(factoryResetCommand, 5)', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"RESTORE_FACTORY_ECHO_CONFIRMED"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('"RESTORE_FACTORY_ECHO_MISSED"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('tab.Screen.Send vbCr', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('crt.Sleep 8000', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertNotIn('factoryResetCommand & vbCr', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        restore_sent_index = SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index('"RESTORE_FACTORY_SENT"')
        restore_done_index = SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index('WriteStatus fso, statusPath, "DONE"')
        close_index = SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index('CloseUpgradeTab tab, fso, statusPath')
        self.assertLess(restore_sent_index, restore_done_index)
        self.assertLess(restore_done_index, close_index)
        self.assertLess(
            SECURECRT_TFTP_COPY_UPGRADE_SCRIPT.index('crt.Sleep 8000'),
            restore_done_index,
        )
        self.assertIn('SetOption "Emulation", "ANSI"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('SetOption "Output Transformer Name", "Default"', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('SetOption "Use Unicode Line Drawing", False', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('SetOption "Enable Xterm-256color", False', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('SetOption "Enable Xterm-Truecolor", False', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('SetOption "DTR Flow Control", False', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)
        self.assertIn('SetOption "RTS Flow Control", False', SECURECRT_TFTP_COPY_UPGRADE_SCRIPT)

    def test_securecrt_error_dialog_is_not_treated_as_main_window(self):
        self.assertFalse(_is_securecrt_main_window_title("SecureCRT"))
        self.assertTrue(_is_securecrt_main_window_title("not connected - SecureCRT"))

    @patch("line_check_assistant.securecrt_automation.subprocess.Popen")
    @patch("line_check_assistant.securecrt_automation._wait_for_new_securecrt_window", return_value=False)
    @patch("line_check_assistant.securecrt_automation._securecrt_window_handles", return_value={101})
    @patch("line_check_assistant.securecrt_automation.resolve_serial_log_directory")
    @patch("line_check_assistant.securecrt_automation.find_securecrt_executable")
    def test_launch_fails_when_securecrt_has_no_visible_window(self, find_securecrt, resolve_log_dir, _existing_windows, _wait_for_window, _popen):
        find_securecrt.return_value = Path(r"C:\Program Files\VanDyke Software\Clients\SecureCRT.exe")
        with tempfile.TemporaryDirectory() as directory:
            resolve_log_dir.return_value = Path(directory) / "logs"
            result = launch_securecrt_serial_logs(Path(directory), ["vlan101"])

        self.assertFalse(result.success)
        self.assertIn("未检测到本次新打开的 SecureCRT 主窗口", result.message)


if __name__ == "__main__":
    unittest.main()
