import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.tftpd_automation import _build_prepare_tftpd_script


class TftpdAutomationTests(unittest.TestCase):
    def test_prepare_script_sets_current_directory_and_server_interface(self):
        script = _build_prepare_tftpd_script(
            Path(r"F:\tool\tftpd64.exe"),
            Path(r"F:\firmware"),
            "VLAN101",
            "192.168.1.101",
        )

        self.assertIn("$currentDirectory = 'F:\\firmware'", script)
        self.assertIn("$serverInterface = 'VLAN101'", script)
        self.assertIn("$serverIp = '192.168.1.101'", script)
        self.assertIn("Set-ControlTextByKeyboard $nativeFields[0] $currentDirectory", script)
        self.assertIn("Assert-DirectoryApplied $nativeFields[0] $currentDirectory", script)
        self.assertIn("Tftpd64 Current Directory 设置失败", script)
        self.assertIn("已设置 Tftpd64 Current Directory", script)
        self.assertIn("已设置 Tftpd64 Server interfaces", script)
        self.assertIn("[NativeWindow]::GetWindow($parentHandle, 5)", script)
        self.assertIn("[NativeWindow]::GetWindow($childHandle, 2)", script)
        self.assertNotIn("EnumChildWindows", script)
        self.assertNotIn("??", script)


if __name__ == "__main__":
    unittest.main()
