import queue
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from line_check_assistant.app import LineCheckAssistant
from src.ui.project_name_badge import ProjectNameBadge, fit_project_name


class SavedProjectNameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test_project_config.ini"
        self.context = SimpleNamespace(project_name_badge=Mock(), log_queue=queue.Queue())
        patcher = patch("line_check_assistant.app.TEST_ITEM_CONFIG_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def refresh(self):
        LineCheckAssistant._refresh_saved_project_name(self.context)

    def test_reads_project_info_without_prefix_or_writes(self):
        self.path.write_text("[project_info]\nproject_name = 项目A 中文\n", encoding="utf-8")
        before = self.path.read_bytes()
        self.refresh()
        self.context.project_name_badge.set_name.assert_called_once_with("项目A 中文")
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_file_and_empty_name(self):
        self.refresh()
        self.context.project_name_badge.set_name.assert_called_with("")
        self.assertFalse(self.path.exists())
        for content in ("[project_info]\nproject_name =   \n", "[other]\nname = old\n"):
            self.path.write_text(content, encoding="utf-8")
            self.refresh()
            self.context.project_name_badge.set_name.assert_called_with("")

    def test_parse_or_access_failure_does_not_escape_or_log_config(self):
        self.path.write_text("private malformed config", encoding="utf-8")
        self.refresh()
        self.context.project_name_badge.set_name.assert_called_with("", failed=True)
        self.assertNotIn("private", self.context.log_queue.get_nowait())
        with patch("line_check_assistant.app.TestItemConfigStore.load", side_effect=PermissionError("private")):
            self.refresh()
        self.assertNotIn("private", self.context.log_queue.get_nowait())


class ProjectNameBadgeTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.badge = ProjectNameBadge(self.root, font_family="Microsoft YaHei UI",
                                      background="#eaf3ff", foreground="#174b80")
        self.badge.pack()
        self.root.update_idletasks()

    def test_name_and_placeholders_have_no_prefix(self):
        self.badge.set_name("项目A")
        self.assertEqual(self.badge.label.cget("text"), "项目A")
        self.badge.set_name("   ")
        self.assertEqual(self.badge.full_text, "未设置")
        self.badge.set_name("", failed=True)
        self.assertEqual(self.badge.full_text, "读取失败")

    def test_long_name_fits_and_tooltip_keeps_full_value(self):
        name = "中文项目ABC" * 20
        self.badge.set_name(name)
        self.assertTrue(self.badge.label.cget("text").endswith("…"))
        self.assertLessEqual(self.badge.name_font.measure(self.badge.label.cget("text")), 156)
        self.badge._show_tooltip()
        self.assertEqual(self.badge.tooltip.winfo_children()[0].cget("text"), name)
        self.badge.set_name("新项目")
        self.assertIsNone(self.badge.tooltip)

    def test_destroy_cancels_pending_tooltip(self):
        self.badge._schedule_tooltip()
        job = self.badge.tooltip_job
        self.badge.destroy()
        self.assertNotIn(job, self.root.tk.call("after", "info"))

    def test_pixel_fit_preserves_short_names_and_handles_tiny_width(self):
        self.assertEqual(fit_project_name("名称", len, 2), "名称")
        self.assertEqual(fit_project_name("长项目名称", len, 3), "长项…")
        self.assertEqual(fit_project_name("名称", len, 0), "")
