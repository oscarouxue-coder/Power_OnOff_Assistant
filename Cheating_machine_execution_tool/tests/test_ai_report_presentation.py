"""诊断报告排版：离线报告与真实Tk，不访问用户数据库、模型或设备。"""
import unittest
from unittest.mock import patch
from tkinter import ttk

import test_ai_workspace as workspace


class ReportPresentationTests(unittest.TestCase):
    setUp = workspace.WorkspaceTests.setUp
    close_ui = workspace.WorkspaceTests.close_ui
    stop_services = workspace.WorkspaceTests.stop_services
    report = workspace.WorkspaceTests.report

    def show(self, **changes):
        original = self.report(**changes)
        panel = self.dialog.reports_panel
        panel.open()
        self.root.update()
        return panel, original

    def test_markdown_sections_and_code_are_display_only(self):
        report = ("# **已观察事实**\n- **重点**：`ping 192.168.1.1`\n"
                  "1. 核对出口\n> 待核实\n```text\n  原因假设\n\t**原文**\n```\n"
                  "本地恢复状态：恢复失败，待人工处理")
        panel, original = self.show(report=report)
        output = panel.output
        shown = output.get("1.0", "end-1c")
        self.assertTrue(shown.startswith("诊断分析\n已观察事实\n• 重点：ping 192.168.1.1"))
        self.assertIn("1. 核对出口\n│ 待核实", shown)
        self.assertIn("  原因假设\n\t**原文**\n", shown)
        self.assertIn("本地恢复状态：恢复失败，待人工处理", shown)
        for tag in ("report_analysis", "report_evidence", "md_h1", "md_bold", "md_inline_code", "md_code"):
            self.assertTrue(output.tag_ranges(tag), tag)
        code = output.search("原因假设", "1.0")
        self.assertNotIn("md_h2", output.tag_names(code))
        self.assertEqual(self.store.report("r1"), original)
        self.assertEqual(str(output["state"]), "disabled")
        self.assertEqual(output.tag_names()[-1], "sel")
        self.assertEqual(self.requests, [])

    def test_plain_chapter_titles_and_failure_text_remain_complete(self):
        report = ("已观察事实：\n链路掉线\n证据引用\n日志1\n原因假设\n待核实\n"
                  "建议检查步骤\n核对线缆\n缺失信息\n待补充\n临时操作恢复状态\n"
                  "恢复失败\n本地恢复状态：未确认")
        panel, original = self.show(report=report, status="失败")
        output = panel.output
        self.assertIn(report, output.get("1.0", "end-1c"))
        for heading in ("已观察事实", "证据引用", "原因假设", "建议检查步骤", "缺失信息", "临时操作恢复状态"):
            index = output.search(heading, "2.0")
            self.assertIn("md_h2", output.tag_names(index))
        self.assertEqual(self.store.report("r1"), original)

    def test_evidence_copy_preserves_literal_markers_paths_and_whitespace(self):
        evidence = ("## 证据原文\n**不可改写** `命令`\n- 原因假设\n"
                    "C:\\日志\\_原文\\#1.log\r\n  缩进\t字段\n\n```\n<IP_1>\n")
        panel, original = self.show(report="分析", evidence=evidence)
        output = panel.output
        start = output.search("## 证据原文", "1.0")
        self.assertEqual(output.get(start, "end-1c"), evidence)
        for tag in ("md_h1", "md_h2", "md_bold", "md_inline_code", "md_code"):
            for begin, end in zip(output.tag_ranges(tag)[::2], output.tag_ranges(tag)[1::2]):
                self.assertTrue(output.compare(end, "<=", start), tag)
        output.tag_add("sel", start, "end-1c")
        output.event_generate("<<Copy>>")
        self.root.update()
        self.assertEqual(self.root.clipboard_get(), evidence)
        self.assertEqual(self.store.report("r1"), original)

    def test_refresh_keeps_reading_without_rebuild_and_switch_resets_top(self):
        panel, _ = self.show(report="## 分析\n" + "持续故障\n" * 160)
        panel.output.yview_moveto(.35)
        panel.output.tag_add("sel", "35.0", "35.3")
        self.root.update()
        top = panel.output.index("@0,0")
        selection = panel.output.get("sel.first", "sel.last")
        self.report("new", report="新报告")
        with patch.object(panel.output, "delete", wraps=panel.output.delete) as delete:
            panel.reload()
            delete.assert_not_called()
        self.assertEqual(panel.selected, "r1")
        self.assertEqual(panel.output.index("@0,0"), top)
        self.assertEqual(panel.output.get("sel.first", "sel.last"), selection)
        self.report(report="## 分析\n" + "持续故障\n" * 180)
        panel.reload()
        self.root.update()
        self.assertEqual(panel.output.index("@0,0"), top)
        self.assertEqual(panel.output.get("sel.first", "sel.last"), selection)
        panel.choice.current(panel.ids.index("new"))
        panel.choose()
        self.root.update()
        self.assertEqual(panel.output.yview()[0], 0.0)
        self.assertEqual(panel.output.tag_ranges("sel"), ())
        self.assertEqual(self.requests, [])

    def test_empty_history_and_empty_report_keep_operations_consistent(self):
        panel = self.dialog.reports_panel
        panel.open()
        self.assertEqual(panel.output.get("1.0", "end-1c"), "暂无诊断报告。")
        for button in (panel.continue_button, panel.case_button, panel.delete_button):
            self.assertIn("disabled", button.state())
        self.report(report="", evidence="")
        panel.reload()
        self.assertIn("诊断分析\n", panel.output.get("1.0", "end-1c"))
        self.assertTrue(panel.output.get("1.0", "end-1c").endswith("本地证据：\n"))
        for button in (panel.continue_button, panel.case_button, panel.delete_button):
            self.assertNotIn("disabled", button.state())

    def test_vista_clam_default_and_minimum_layout_wraps_without_altering_text(self):
        line = "长诊断内容保持自动折行和原始字符" * 24
        panel, _ = self.show(report=line, evidence=line)
        style = ttk.Style(self.root)
        for theme in ("vista", "clam"):
            self.assertIn(theme, style.theme_names())
            style.theme_use(theme)
            for size in ("920x620", "760x480"):
                with self.subTest(theme=theme, size=size):
                    panel.window.geometry(size)
                    self.root.update()
                    for widget in (panel.choice, panel.continue_button, panel.case_button, panel.delete_button, panel.output):
                        self.assertTrue(widget.winfo_ismapped())
                        self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                             panel.window.winfo_rootx() + panel.window.winfo_width())
                        self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                             panel.window.winfo_rooty() + panel.window.winfo_height())
                    self.assertGreater(panel.output.count("2.0", "3.0", "displaylines")[0], 1)
                    self.assertEqual(panel.output.get("2.0", "2.end"), line)
                    self.assertEqual(panel.output.cget("background"), "#ffffff")
                    self.assertEqual(panel.window.cget("background"), "#eef2f5")


if __name__ == "__main__":
    unittest.main()
