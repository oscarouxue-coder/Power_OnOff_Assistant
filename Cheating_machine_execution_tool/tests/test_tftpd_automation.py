import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.tftpd_automation import _build_prepare_tftpd_script
from line_check_assistant.upgrade_cleanup import _build_close_upgrade_tools_script


class TftpdAutomationTests(unittest.TestCase):
    def test_prepare_script_sets_current_directory_and_tftp_server_tab_only(self):
        script = _build_prepare_tftpd_script(
            Path(r"F:\tool\tftpd64.exe"),
            Path(r"F:\firmware"),
            "VLAN101",
            "192.168.1.101",
        )

        self.assertIn("$currentDirectory = 'F:\\firmware'", script)
        self.assertIn("Stop-Process -Id $existingProcess.Id -Force", script)
        self.assertIn("Start-Process -FilePath $toolPath -WorkingDirectory $currentDirectory", script)
        self.assertIn("Set-ControlTextRobust $nativeFields[0] $currentDirectory", script)
        self.assertIn("Set-ControlTextByAutomation $control $value", script)
        self.assertIn("Set-ControlTextByNativeApi $control $value", script)
        self.assertIn("Set-ControlTextByKeyboard $control $value", script)
        self.assertIn("Assert-DirectoryApplied $nativeFields[0] $currentDirectory", script)
        self.assertIn("Tftpd64 Current Directory 设置失败", script)
        self.assertIn("已设置 Tftpd64 Current Directory", script)
        self.assertIn('$tab.Current.Name -eq "Tftp Server"', script)
        self.assertIn("已切换到 Tftp Server", script)
        self.assertNotIn("Server interfaces", script)
        self.assertNotIn("Find-ServerInterfaceComboItem", script)
        self.assertNotIn("Select-ComboBoxItem", script)
        self.assertIn("[NativeWindow]::GetWindow($parentHandle, 5)", script)
        self.assertIn("[NativeWindow]::GetWindow($childHandle, 2)", script)
        self.assertNotIn("EnumChildWindows", script)
        self.assertNotIn("??", script)

    def test_cleanup_script_closes_project_tftpd_and_securecrt(self):
        script = _build_close_upgrade_tools_script(Path(r"F:\tool\tftpd64.exe"))

        self.assertIn("$tftpdPath = 'F:\\tool\\tftpd64.exe'", script)
        self.assertIn("try { $_.Path -eq $tftpdPath }", script)
        self.assertIn('$_.ProcessName -ieq "SecureCRT"', script)
        self.assertIn('Stop-ProcessGracefully $process "Tftpd64"', script)
        self.assertIn('Stop-ProcessGracefully $process "SecureCRT"', script)
        self.assertIn("CloseMainWindow()", script)
        self.assertIn("Stop-Process -Id $process.Id -Force", script)


if __name__ == "__main__":
    unittest.main()
