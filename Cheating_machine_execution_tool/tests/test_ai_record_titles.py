"""列表名称专项：临时数据库/离线真实Tk，不访问模型、设备或用户数据。"""
import copy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.services.ai_record_titles import AiRecordTitles
from src.services.ai_store import DiagnosticStore
from src.ui.ai_record_presentation import RecordTitleDialog, record_detail, record_labels
from test_ai_core import FakeCipher
import test_ai_workspace as workspace


class RecordTitleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DiagnosticStore(self.temp.name, FakeCipher())
        self.addCleanup(self.store.close)
        self.logs = []
        self.titles = AiRecordTitles(self.store, self.logs.append)
        self.chat = dict(id="s1", created="2026-11-14T02:24:54+08:00", title="通道1排障",
                         target={"channel": 1}, profile={"provider": "fixture", "model": "fixture"},
                         status="可继续")
        self.store.create_chat(self.chat)

    def entry(self):
        return self.titles.chat_entries(self.store.chats())[0]

    def test_legacy_first_user_question_and_empty_session_without_writes(self):
        self.assertEqual(self.entry()["title"], "新会话")
        self.store.append_chat("s1", {"role": "system", "text": "已创建会话"})
        self.store.append_chat("s1", {"role": "assistant", "text": "系统主动询问"})
        self.store.append_chat("s1", {"role": "user", "text": "  分析 `重启`\n\t日志  "})
        self.store.append_chat("s1", {"role": "user", "text": "后续问题"})
        before = (self.store.chat("s1"), self.store.chat_items("s1"))
        self.assertEqual(self.entry()["title"], "分析 重启 日志")
        self.assertEqual(before, (self.store.chat("s1"), self.store.chat_items("s1")))
        self.assertEqual(self.store.record_titles("chat"), {})

    def test_existing_custom_title_is_preserved(self):
        self.store.update_chat("s1", title="现场问题")
        self.store.append_chat("s1", {"role": "user", "text": "另一个主题"})
        self.assertEqual(self.entry()["title"], "现场问题")

    def test_report_event_question_fallback_cycle_and_backticks(self):
        for payload, expected in (({"event": {"detail": "`Telnet`\n连接超时", "cycle": 12}}, "Telnet 连接超时"),
                                  ({"question": "分析启动中断", "event": {"detail": " \n` `"}}, "分析启动中断"),
                                  ({}, "诊断报告")):
            self.store.save_report("r1", payload)
            entry = self.titles.report_entries(self.store.reports())[0]
            self.assertEqual(entry["title"], expected)
            if (payload.get("event") or {}).get("cycle"):
                self.assertIn("·第12轮", record_labels([entry])[0])

    def test_report_handoff_prefers_report_name_and_deleted_source_falls_back(self):
        self.store.save_report("r1", {"question": "WiFi未获取IP"})
        self.store.update_chat("s1", source_report_id="r1")
        self.store.append_chat("s1", {"role": "user", "text": "请继续"})
        self.assertEqual(self.entry()["title"], "WiFi未获取IP")
        self.titles.rename("report", "r1", "现场无线故障")
        self.assertEqual(self.entry()["title"], "现场无线故障")
        self.store.delete_reports(["r1"])
        self.assertEqual(self.entry()["title"], "请继续")

    def test_rename_persists_independent_of_session_payload_and_later_messages(self):
        before = copy.deepcopy(self.chat)
        self.titles.rename("chat", "s1", " 通道1排障 ")
        self.store.append_chat("s1", {"role": "user", "text": "新问题不能覆盖人工名"})
        other = DiagnosticStore(self.temp.name, FakeCipher())
        try:
            self.assertEqual(AiRecordTitles(other, self.logs.append).chat_entries(other.chats())[0]["title"], "通道1排障")
            self.assertEqual(other.chat("s1"), before)
        finally:
            other.close()
        self.assertIn("重命名成功", self.logs[-1])

    def test_background_report_save_does_not_overwrite_manual_title_or_created_order(self):
        self.store.save_report("r1", {"question": "原问题", "report": "旧内容"})
        before = self.store.reports()[0]
        self.titles.rename("report", "r1", "人工标题")
        self.assertEqual(self.store.reports()[0], before)
        self.store.save_report("r1", {"question": "后台问题", "report": "生成完成"})
        self.assertEqual(self.titles.report_entries(self.store.reports())[0]["title"], "人工标题")

    def test_invalid_names_missing_record_and_invalid_kind_do_not_save(self):
        for value in ("", " \n\t", "x" * 81, "``"):
            with self.assertRaises(ValueError):
                self.titles.rename("chat", "s1", value)
        for kind, identifier in (("chat", "missing"), ("report", "missing"), ("unknown", "s1")):
            with self.assertRaises(ValueError):
                self.titles.rename(kind, identifier, "有效名称")
        self.assertEqual(self.store.record_titles("chat"), {})
        self.assertTrue(all("重命名失败" in log for log in self.logs))

    def test_rename_accepts_80_characters_and_removes_backticks(self):
        self.titles.rename("chat", "s1", "x" * 80)
        self.assertEqual(len(self.entry()["title"]), 80)
        self.titles.rename("chat", "s1", "`查看`  \n日志")
        self.assertEqual(self.entry()["title"], "查看 日志")

    def test_delete_only_cleans_corresponding_display_metadata(self):
        self.store.save_report("r1", {"report": "材料"})
        self.titles.rename("report", "r1", "报告标题")
        self.titles.rename("chat", "s1", "会话标题")
        self.store.delete_chats(["s1"])
        self.assertEqual(self.store.record_titles("chat"), {})
        self.assertEqual(self.store.record_titles("report"), {"r1": "报告标题"})
        self.store.delete_reports(["r1"])
        self.assertEqual(self.store.record_titles("report"), {})

    def test_long_multiline_same_labels_are_distinct_and_full_detail_is_available(self):
        original = self.entry()
        original["title"] = "主题" * 30
        entries = [dict(original, id=identifier) for identifier in ("abcdefgh1", "abcdefgh2")]
        labels = record_labels(entries)
        self.assertNotEqual(*labels)
        self.assertIn("…", labels[0])
        self.assertNotIn("fixture", labels[0])
        detail = record_detail(entries[0])
        self.assertIn(original["title"], detail)
        self.assertIn("2026-11-14 02:24:54", detail)
        self.assertIn("fixture / fixture", detail)
        self.assertIn("abcdefgh1", detail)

    def test_report_delete_failure_rolls_back_names_together_with_reports(self):
        for identifier in ("r1", "r2"):
            self.store.save_report(identifier, {"report": identifier})
            self.titles.rename("report", identifier, "名称" + identifier)
        self.store.db.execute("CREATE TRIGGER reject_second BEFORE DELETE ON reports "
                              "WHEN OLD.id='r2' BEGIN SELECT RAISE(ABORT, 'fixture'); END")
        self.store.db.commit()
        with self.assertRaises(Exception):
            self.store.delete_reports(["r1", "r2"])
        self.assertEqual(len(self.store.reports()), 2)
        self.assertEqual(self.store.record_titles("report"), {"r1": "名称r1", "r2": "名称r2"})


class RecordTitleUiTests(unittest.TestCase):
    setUp = workspace.WorkspaceTests.setUp
    close_ui = workspace.WorkspaceTests.close_ui
    stop_services = workspace.WorkspaceTests.stop_services
    report = workspace.WorkspaceTests.report

    def new_chat(self):
        identifier = self.service.create_session(self.targets[0], self.profile)
        self.dialog.chat_panel.selected = identifier
        self.dialog.chat_panel.refresh()
        return identifier, self.dialog.chat_panel

    def rename(self, actions, value):
        with patch("src.ui.ai_record_presentation.RecordTitleDialog", return_value=SimpleNamespace(result=value)):
            actions.rename()

    def test_chat_rename_keeps_draft_selection_scroll_and_updates_open_manager(self):
        identifier, panel = self.new_chat()
        self.service.message(identifier, "user", "排查WiFi\n" * 160)
        panel.refresh()
        panel.input.insert("1.0", "未发送草稿")
        panel.output.yview_moveto(.35)
        panel.output.tag_add("sel", "30.0", "30.3")
        self.root.update()
        top, selected = panel.output.index("@0,0"), tuple(panel.output.tag_ranges("sel"))
        panel.manage_sessions()
        with patch.object(panel.output, "delete", wraps=panel.output.delete) as delete:
            self.rename(panel.record_actions, "无线连接故障")
            delete.assert_not_called()
        self.assertEqual(panel.selected, identifier)
        self.assertEqual(panel.input.get("1.0", "end-1c"), "未发送草稿")
        self.assertEqual(panel.output.index("@0,0"), top)
        self.assertEqual(tuple(panel.output.tag_ranges("sel")), selected)
        self.assertTrue(panel.sessions.get().startswith("无线连接故障 |"))
        self.assertEqual(panel.session_manager.tree.set(identifier, "title"), "无线连接故障")
        self.assertEqual(self.requests, [])

    def test_report_rename_keeps_body_position_and_updates_manager_and_chat(self):
        self.report(question="Telnet连接失败")
        panel = self.dialog.reports_panel
        panel.open()
        identifier = self.dialog.continue_report("r1")
        panel.manage_reports()
        panel.output.yview_moveto(.35)
        panel.output.tag_add("sel", "35.0", "35.3")
        self.root.update()
        top, selected = panel.output.index("@0,0"), tuple(panel.output.tag_ranges("sel"))
        before = self.store.report("r1")
        with patch.object(panel.output, "delete", wraps=panel.output.delete) as delete:
            self.rename(panel.record_actions, "现场Telnet故障")
            delete.assert_not_called()
        self.assertEqual(panel.selected, "r1")
        self.assertEqual(panel.output.index("@0,0"), top)
        self.assertEqual(tuple(panel.output.tag_ranges("sel")), selected)
        self.assertEqual(panel.manager.tree.set("r1", "title"), "现场Telnet故障")
        self.assertEqual(self.dialog.chat_panel.selected, identifier)
        self.assertTrue(self.dialog.chat_panel.sessions.get().startswith("现场Telnet故障 |"))
        self.assertEqual(self.store.report("r1"), before)
        self.assertEqual(self.requests, [])

    def test_cancel_does_not_save_or_refresh(self):
        identifier, panel = self.new_chat()
        with patch.object(panel.record_actions, "changed") as changed:
            self.rename(panel.record_actions, None)
        changed.assert_not_called()
        self.assertEqual(self.store.record_titles("chat"), {})
        self.assertIn("已取消重命名", self.logs[-1])

    def test_modal_refresh_does_not_change_rename_destination(self):
        self.report("r1", question="原报告")
        self.report("r2", question="另一份报告")
        panel = self.dialog.reports_panel
        panel.open()
        panel.selected = "r1"
        panel.reload()
        def dialog(*_args):
            panel.selected = "r2"
            panel.reload()
            return SimpleNamespace(result="只改原报告")
        with patch("src.ui.ai_record_presentation.RecordTitleDialog", side_effect=dialog):
            panel.record_actions.rename()
        self.assertEqual(self.store.record_titles("report"), {"r1": "只改原报告"})
        self.assertEqual(panel.selected, "r2")

    def test_deleted_record_during_modal_dialog_reports_error_without_recreation(self):
        self.report()
        panel = self.dialog.reports_panel
        panel.open()
        def dialog(*_args):
            self.store.delete_reports(["r1"])
            return SimpleNamespace(result="失效记录")
        with patch("src.ui.ai_record_presentation.RecordTitleDialog", side_effect=dialog), \
                patch("src.ui.ai_record_presentation.messagebox.showerror") as error:
            panel.record_actions.rename()
        error.assert_called_once()
        self.assertEqual(self.store.record_titles("report"), {})
        self.assertEqual(self.store.reports(), [])

    def test_management_single_selection_and_renaming_sync(self):
        self.report("r1", question="一个问题")
        self.report("r2", question="另一个问题")
        panel = self.dialog.reports_panel
        panel.open()
        panel.manage_reports()
        manager = panel.manager
        manager.select_all()
        self.assertIsNone(manager.record_actions.current())
        manager.deselect()
        self.assertIsNone(manager.record_actions.current())
        manager.tree.selection_set("r1")
        self.rename(manager.record_actions, "管理窗口命名")
        self.assertEqual(manager.tree.selection(), ("r1",))
        self.assertEqual(panel.record_entries["r1"]["title"], "管理窗口命名")
        self.assertEqual(manager.tree.set("r1", "title"), "管理窗口命名")

    def test_tooltip_and_destroy_cancel_pending_jobs(self):
        identifier, panel = self.new_chat()
        self.root.update()
        actions = panel.record_actions
        actions.schedule(None)
        self.assertIsNotNone(actions.job)
        actions.widget.after_cancel(actions.job)
        actions.job = None
        actions.show_detail(identifier)
        self.assertIsNotNone(actions.popup)
        text = actions.popup.winfo_children()[0].cget("text")
        self.assertIn(identifier, text)
        actions.hide()
        self.assertIsNone(actions.popup)
        actions.schedule(None)
        panel.sessions.destroy()
        self.assertIsNone(actions.job)

    def test_real_rename_dialog_theme_initial_value_and_cancel_in_vista_clam(self):
        from tkinter import ttk
        for theme in ("vista", "clam"):
            ttk.Style(self.root).theme_use(theme)
            seen = []
            def cancel_dialog():
                for window in self.root.winfo_children():
                    if isinstance(window, RecordTitleDialog):
                        seen.append((window.entry.get(), window.cget("background")))
                        window.cancel()
            self.root.after(100, cancel_dialog)
            dialog = RecordTitleDialog(self.root, "原主题", "#eef2f5")
            self.assertEqual(seen, [("原主题", "#eef2f5")])
            self.assertIsNone(dialog.result)

    def test_real_rename_dialog_save_normalizes_name(self):
        def save_dialog():
            for window in self.root.winfo_children():
                if isinstance(window, RecordTitleDialog):
                    window.entry.delete(0, "end")
                    window.entry.insert(0, " `现场问题` ")
                    window.ok()
        self.root.after(100, save_dialog)
        dialog = RecordTitleDialog(self.root, "原主题", "#eef2f5")
        self.assertEqual(dialog.result, "现场问题")

    def test_default_and_minimum_layout_in_vista_clam(self):
        from tkinter import ttk
        _, chat = self.new_chat()
        self.report(question="很长的诊断主题" * 20)
        report = self.dialog.reports_panel
        report.open()
        chat.manage_sessions()
        report.manage_reports()
        for theme in ("vista", "clam"):
            ttk.Style(self.root).theme_use(theme)
            for size in ("920x620", "760x480"):
                with self.subTest(theme=theme, size=size):
                    report.window.geometry(size)
                    self.root.update()
                    for widget in (report.choice, report.output, report.continue_button, report.delete_button):
                        self.assertTrue(widget.winfo_ismapped())
                        self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                             report.window.winfo_rootx() + report.window.winfo_width())
            for manager in (chat.session_manager, report.manager):
                for size in ("940x520", "760x420"):
                    manager.window.geometry(size)
                    self.root.update()
                    for widget in (manager.tree, manager.delete_button, manager.clear_button):
                        self.assertTrue(widget.winfo_ismapped())
                        self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                             manager.window.winfo_rootx() + manager.window.winfo_width())
                        self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                             manager.window.winfo_rooty() + manager.window.winfo_height())
                    self.assertEqual(manager.window.cget("background"), "#eef2f5")


if __name__ == "__main__":
    unittest.main()
