import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.paths import resolve_config_dir, resolve_old_tool_path


class PathsTests(unittest.TestCase):
    def test_resolve_config_dir_uses_moved_old_tool_source_directory(self):
        root = Path("C:/line-check")

        self.assertEqual(
            resolve_config_dir(root),
            root / "Auto_power_on_off_tool" / "config",
        )

    def test_resolve_old_tool_path_prefers_new_plain_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plain = root / "Auto_Power_On_Off_Tool.exe"
            legacy = root / "Auto_Power_On_Off_Tool(2).exe"
            plain.write_text("", encoding="utf-8")
            legacy.write_text("", encoding="utf-8")

            self.assertEqual(resolve_old_tool_path(root), plain)

    def test_resolve_old_tool_path_accepts_legacy_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "Auto_Power_On_Off_Tool(2).exe"
            legacy.write_text("", encoding="utf-8")

            self.assertEqual(resolve_old_tool_path(root), legacy)

    def test_resolve_old_tool_path_uses_default_plain_name_when_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            self.assertEqual(resolve_old_tool_path(root), root / "Auto_Power_On_Off_Tool.exe")


if __name__ == "__main__":
    unittest.main()
