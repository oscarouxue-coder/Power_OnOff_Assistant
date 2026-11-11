"""会话删除：临时SQLite、真实Tk控件，无云端、真实用户数据或设备操作。"""
from dataclasses import asdict, replace
import gc
from pathlib import Path
import queue
import sqlite3
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.models.ai_diagnostics import ProviderProfile
from src.services.ai_conversation_service import AiConversationService
from src.services.ai_action_service import AiActionService
from src.services.ai_evidence_context import AiEvidenceContext
from src.services.ai_store import DiagnosticStore, profile_fingerprint
from src.ui.ai_chat_panel import AiChatPanel
from src.utils.ai_redaction import DiagnosticRedactor
from test_ai_core import FakeCipher
from test_ai_debug import TARGET


class DeletionFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DiagnosticStore(self.temp.name, FakeCipher())
        self.addCleanup(self.store.close)
        self.profile = self.store.save_profile(ProviderProfile(model="fixture"), "model-secret")
        self.profile = replace(self.profile, capability="可自动诊断", tested_fingerprint=profile_fingerprint(self.profile))
        self.store.save_profile(self.profile)
        # 不启动worker；直接控制与生产相同的队列/清理存活标志。
        self.service = AiConversationService.__new__(AiConversationService)
        self.service.store = self.store
        self.service.redactor = DiagnosticRedactor()
        self.service.redactor.add_secrets(("model-secret",))
        self.service.diagnostic = Mock()
        self.service.lock = threading.RLock()
        self.service.running = {}
        self.service.executors = {}
        self.service.diagnostic.targets = {TARGET.channel: TARGET}
        self.service.target_current = lambda target: target == TARGET
        self.service.shutdown = threading.Event()
        self.service.updates = queue.Queue()
        self.service.context = AiEvidenceContext()
        self.service.actions = AiActionService(self.service)
        self.add_session("s1")
        self.add_session("s2")

    def add_session(self, identifier):
        self.store.create_chat({"id": identifier, "created": "2026-11-12T12:30:00+08:00",
            "title": "排障" + identifier, "status": "等待你回复", "run_id": "manual",
            "target": asdict(TARGET), "profile": asdict(self.profile), "pending": {"question": "现场？"}})
        self.store.append_chat(identifier, {"role": "user", "text": "故障" + identifier,
                                            "kind": "text", "created": "2026-11-12T12:30:00+08:00"})
        self.store.append_chat(identifier, [{"role": "user", "content": "原始协议组"}], group=True)
        self.store.add_chat_evidence(identifier, {"source": "fixture", "text": "证据" + identifier,
                                                 "run_id": "manual"})

    def snapshot(self):
        return {name: list(self.store.db.execute("SELECT * FROM " + name)) for name in
                ("chat_sessions", "chat_messages", "chat_groups", "chat_evidence")}


class SessionDeletionTests(DeletionFixture, unittest.TestCase):
    def test_single_delete_removes_children_preserves_other_session_and_reopen(self):
        before = (self.store.chat("s2"), self.store.chat_items("s2"),
                  self.store.chat_items("s2", group=True), self.store.chat_evidence("s2"))
        self.assertEqual(self.service.delete_sessions(["s1"]), 1)
        with self.assertRaisesRegex(ValueError, "不存在"):
            self.store.chat("s1")
        self.assertEqual(self.store.chat_items("s1"), [])
        self.assertEqual(self.store.chat_items("s1", group=True), [])
        self.assertEqual(self.store.chat_evidence("s1"), [])
        self.assertEqual(before, (self.store.chat("s2"), self.store.chat_items("s2"),
                                 self.store.chat_items("s2", group=True), self.store.chat_evidence("s2")))
        reopened = DiagnosticStore(self.temp.name, FakeCipher())
        try:
            self.assertEqual([s["id"] for s in reopened.chats()], ["s2"])
            for table in ("chat_messages", "chat_groups", "chat_evidence"):
                self.assertEqual(reopened.db.execute("SELECT COUNT(*) FROM " + table +
                                 " WHERE session_id='s1'").fetchone()[0], 0)
        finally:
            reopened.close()

    def test_multi_delete_deduplicates_disables_collection_and_notifies(self):
        self.assertTrue(self.service.authorized("s1"))
        self.assertEqual(self.service.delete_sessions(["s1", "s2", "s1"]), 2)
        self.assertFalse(self.service.authorized("s1"))
        self.assertFalse(self.service.authorized("s2"))
        self.assertTrue(all(not rows for rows in self.snapshot().values()))
        self.assertEqual([self.service.updates.get_nowait() for _ in range(2)], ["s1", "s2"])
        self.assertIn("成功删除2个会话", self.service.diagnostic.emit.call_args.args[0])

    def test_delete_preserves_reports_cases_profile_recovery_shared_evidence_and_files(self):
        self.store.save_report("r1", {"report": "报告"})
        self.store.confirm_case("r1", "标题", "原因", "方案", "验证", "范围")
        self.store.recovery("recovery1", {"target": asdict(TARGET)})
        self.store.set_setting("fixture", {"enabled": True})
        self.service.context.observe({"type": "log", "channel": TARGET.channel, "message": "共享事件"})
        context_before = self.service.context.snapshot("manual", TARGET.channel)
        files = [Path(self.temp.name) / name for name in ("source.log", "import.txt", "capture.pcap")]
        for path in files:
            path.write_bytes(b"original data")
        names = ("profiles", "settings", "reports", "cases", "case_revisions", "recovery")
        before = {name: list(self.store.db.execute("SELECT * FROM " + name)) for name in names}
        self.service.delete_sessions(["s1", "s2"])
        self.assertEqual(before, {name: list(self.store.db.execute("SELECT * FROM " + name)) for name in names})
        self.assertEqual(self.store.key(self.profile), "model-secret")
        self.assertEqual(context_before, self.service.context.snapshot("manual", TARGET.channel))
        self.assertTrue(all(path.read_bytes() == b"original data" for path in files))

    def test_sql_error_rolls_back_all_four_tables_and_keeps_collection_eligibility(self):
        before = self.snapshot()
        self.store.db.execute("CREATE TRIGGER fail_delete BEFORE DELETE ON chat_sessions "
                              "WHEN OLD.id='s1' BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
        self.store.db.commit()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "fixture failure"):
            self.service.delete_sessions(["s2", "s1"])
        self.assertEqual(before, self.snapshot())
        self.assertTrue(self.service.authorized("s1"))
        self.assertTrue(self.service.authorized("s2"))
        self.assertTrue(self.service.updates.empty())
        self.assertFalse(self.store.db.in_transaction)

    def test_missing_id_rejects_entire_batch_at_both_layers(self):
        before = self.snapshot()
        for delete in (self.service.delete_sessions, self.store.delete_chats):
            with self.assertRaisesRegex(ValueError, "不存在"):
                delete(["s1", "missing"])
            self.assertEqual(before, self.snapshot())

    def test_running_queued_or_stopping_blocks_entire_batch_without_stopping(self):
        before = self.snapshot()
        for stopping in (False, True):
            stop = threading.Event()
            if stopping:
                stop.set()
            self.service.running["s1"] = stop
            with self.assertRaisesRegex(ValueError, "全部会话均未删除"):
                self.service.delete_sessions(["s2", "s1"])
            self.assertEqual(stop.is_set(), stopping)
            self.assertEqual(before, self.snapshot())
            self.assertTrue(self.service.authorized("s1"))

    def test_executor_cleanup_alone_blocks_until_removed(self):
        self.service.executors["s1"] = Mock()
        with self.assertRaisesRegex(ValueError, "后台清理结束"):
            self.service.delete_sessions(["s1", "s2"])
        self.service.executors.pop("s1").close.assert_not_called()
        self.assertEqual(self.service.delete_sessions(["s1", "s2"]), 2)

    def test_unselected_busy_session_is_unaffected(self):
        stop = self.service.running["s2"] = threading.Event()
        self.assertEqual(self.service.delete_sessions(["s1"]), 1)
        self.assertFalse(stop.is_set())
        self.assertEqual(self.store.chat("s2")["status"], "等待你回复")

    def test_empty_selection_is_noop_and_shutdown_rejects(self):
        before = self.snapshot()
        self.assertEqual(self.service.delete_sessions([]), 0)
        self.assertEqual(self.store.delete_chats([]), 0)
        self.service.shutdown.set()
        with self.assertRaisesRegex(ValueError, "正在退出"):
            self.service.delete_sessions(["s1"])
        self.assertEqual(before, self.snapshot())


class SessionManagerTests(DeletionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        gc.collect()
        self.root = tk.Tk()
        self.root.geometry("1040x760")
        self.owner = Mock(window=self.root, targets=(TARGET,), background_color="#eef2f5")
        frame = ttk.Frame(self.root)
        frame.pack(fill="both", expand=True)
        self.panel = AiChatPanel(frame, self.owner, self.service)
        self.panel.refresh_targets()
        self.root.update_idletasks()
        self.panel.manage_sessions()
        self.manager = self.panel.session_manager
        self.root.update_idletasks()

    def tearDown(self):
        self.root.destroy()
        del self.panel, self.owner, self.manager, self.root
        gc.collect()

    def test_initial_selection_columns_time_theme_and_reopen_single_window(self):
        self.assertEqual(self.manager.tree.selection(), (self.panel.selected,))
        self.assertEqual(str(self.manager.tree.cget("selectmode")), "extended")
        self.assertEqual(len(self.manager.tree.cget("columns")), 5)
        self.assertEqual(self.manager.tree.item("s1", "values")[0], "2026-11-12 12:30:00")
        self.assertEqual(self.manager.window.cget("background"), "#eef2f5")
        self.panel.manage_sessions()
        self.assertIs(self.panel.session_manager, self.manager)

    def test_select_all_deselect_and_refresh_preserve_selection(self):
        self.manager.select_all()
        self.assertEqual(set(self.manager.tree.selection()), {"s1", "s2"})
        self.manager.refresh()
        self.assertEqual(set(self.manager.tree.selection()), {"s1", "s2"})
        self.manager.deselect()
        self.assertIn("disabled", self.manager.delete_button.state())
        self.assertNotIn("disabled", self.manager.clear_button.state())

    def test_cancel_defaults_no_and_does_not_delete_or_clear_draft(self):
        self.panel.input.insert("1.0", "未发送内容")
        before = self.snapshot()
        with patch("src.ui.ai_session_manager.messagebox.askyesno", return_value=False) as ask:
            self.manager.clear_all()
        self.assertEqual(ask.call_args.kwargs["default"], "no")
        self.assertIn("2 个会话", ask.call_args.args[1])
        self.assertIn("无法撤销", ask.call_args.args[1])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.panel.input.get("1.0", "end-1c"), "未发送内容")

    def test_delete_other_session_keeps_current_draft_and_reading_selection(self):
        self.panel.input.insert("1.0", "保留输入")
        self.panel.output.tag_add("sel", "2.0", "2.3")
        selection = self.panel.output.get("sel.first", "sel.last")
        self.manager.tree.selection_set("s1")
        with patch("src.ui.ai_session_manager.messagebox.askyesno", return_value=True):
            self.manager.delete_selected()
        self.assertEqual(self.panel.selected, "s2")
        self.assertEqual(self.panel.input.get("1.0", "end-1c"), "保留输入")
        self.assertEqual(self.panel.output.get("sel.first", "sel.last"), selection)
        self.assertEqual(self.manager.tree.get_children(), ("s2",))

    def test_delete_current_switches_target_and_clears_input(self):
        other_target = replace(TARGET, channel=TARGET.channel + 1)
        self.store.update_chat("s1", target=asdict(other_target))
        self.owner.targets = (TARGET, other_target)
        self.panel.refresh_targets()
        self.panel.input.insert("1.0", "旧会话输入")
        with patch("src.ui.ai_session_manager.messagebox.askyesno", return_value=True):
            self.manager.delete_selected()
        self.assertEqual(self.panel.selected, "s1")
        self.assertEqual(self.panel.input.get("1.0", "end-1c"), "")
        self.assertEqual(self.panel.target_choice.current(), 1)
        self.assertIn("故障s1", self.panel.output.get("1.0", "end-1c"))
        self.assertNotIn("故障s2", self.panel.output.get("1.0", "end-1c"))

    def test_clear_all_empty_state_and_late_notifications_are_safe(self):
        self.panel.input.insert("1.0", "旧会话输入")
        with patch("src.ui.ai_session_manager.messagebox.askyesno", return_value=True):
            self.manager.clear_all()
        self.panel.poll()
        self.panel.refresh()
        self.assertEqual(self.panel.selected, "")
        self.assertEqual(self.panel.sessions.get(), "")
        self.assertEqual(self.panel.output.get("1.0", "end-1c"), "")
        self.assertEqual(self.panel.input.get("1.0", "end-1c"), "")
        self.assertIn("新建会话", self.panel.status.get())
        self.assertIn("disabled", self.manager.delete_button.state())
        self.assertIn("disabled", self.manager.clear_button.state())
        self.assertNotIn("disabled", self.panel.send_button.state())

    def test_clear_all_freezes_ids_even_if_new_session_appears_during_confirm(self):
        def confirm(*args, **kwargs):
            self.add_session("s3")
            self.manager.refresh()
            return True
        with patch("src.ui.ai_session_manager.messagebox.askyesno", side_effect=confirm):
            self.manager.clear_all()
        self.assertEqual([s["id"] for s in self.store.chats()], ["s3"])
        self.assertEqual(self.panel.selected, "s3")

    def test_busy_error_preserves_entire_selection_and_draft(self):
        self.service.running["s1"] = threading.Event()
        self.manager.refresh()
        self.manager.select_all()
        self.panel.input.insert("1.0", "保留输入")
        before = self.snapshot()
        self.assertIn("不可删除", self.manager.tree.item("s1", "values")[-1])
        with patch("src.ui.ai_session_manager.messagebox.askyesno", return_value=True), \
                patch("src.ui.ai_session_manager.messagebox.showerror") as error:
            self.manager.delete_selected()
        self.assertIn("停止本轮排查", error.call_args.args[1])
        self.assertEqual(set(self.manager.tree.selection()), {"s1", "s2"})
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.panel.input.get("1.0", "end-1c"), "保留输入")

    def test_minimum_window_keeps_buttons_inside_client_area(self):
        for theme in ("vista", "clam"):
            with self.subTest(theme=theme):
                ttk.Style(self.root).theme_use(theme)
                self.manager.window.geometry("760x420")
                self.root.update()  # 完成原生窗口映射/尺寸事件后再检查实际客户区。
                for button in self.manager.delete_button.master.winfo_children():
                    self.assertGreater(button.winfo_width(), 1)
                    self.assertGreaterEqual(button.winfo_rootx(), self.manager.window.winfo_rootx())
                    self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                         self.manager.window.winfo_rootx() + self.manager.window.winfo_width())
                    self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                         self.manager.window.winfo_rooty() + self.manager.window.winfo_height())


if __name__ == "__main__":
    unittest.main()
