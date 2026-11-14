"""报告删除：临时SQLite、离线service和真实Tk，不访问用户数据或设备。"""
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.services.ai_diagnostic_service import AiDiagnosticService
from src.services.ai_store import DiagnosticStore
from src.utils.ai_redaction import DiagnosticRedactor
from test_ai_core import FakeCipher
import test_ai_workspace as workspace


class ReportDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DiagnosticStore(self.temp.name, FakeCipher())
        self.addCleanup(self.store.close)
        self.logs = []
        # 无worker，直接控制生产生命周期登记，覆盖队列/运行/清理边界。
        self.service = AiDiagnosticService.__new__(AiDiagnosticService)
        self.service.store = self.store
        self.service.lock = threading.RLock()
        self.service.stops = set()
        self.service.executors = {}
        self.service.redactor = DiagnosticRedactor()
        self.service.emit_sink = self.logs.append
        for identifier in ("r1", "r2"):
            self.store.save_report(identifier, {"report": identifier, "channel": 1})

    def test_single_delete_persists_after_reopen(self):
        self.assertEqual(self.service.delete_reports(["r1"]), 1)
        other = DiagnosticStore(self.temp.name, FakeCipher())
        try:
            self.assertEqual([row[0] for row in other.reports()], ["r2"])
            with self.assertRaisesRegex(ValueError, "不存在"):
                other.report("r1")
        finally:
            other.close()

    def test_bulk_deduplicates_skips_missing_and_logs_counts(self):
        self.assertEqual(self.service.delete_reports(["r1", "r2", "r1", "missing"]), 2)
        self.assertEqual(self.store.reports(), [])
        self.assertIn("请求删除 3 份", self.logs[0])
        self.assertIn("删除成功 2 份，跳过已不存在 1 份", self.logs[-1])

    def test_unlimited_query_and_delete_over_hundred(self):
        for i in range(120):
            self.store.save_report("old" + str(i), {"report": str(i)})
        self.assertEqual(len(self.store.reports()), 100)
        self.assertEqual(len(self.store.reports(limit=0)), 0)
        ids = [row[0] for row in self.store.reports(limit=None)]
        self.assertEqual(len(ids), 122)
        self.assertEqual(self.service.delete_reports(ids), 122)
        self.assertEqual(self.store.reports(limit=None), [])

    def test_queue_running_or_cleanup_rejects_whole_batch(self):
        for stage in ("queued", "running", "cleaning"):
            with self.subTest(stage=stage):
                stop = threading.Event()
                if stage == "cleaning":
                    stop.set()
                self.service.stops = {("r1", 1, stop)}
                self.service.executors = {"r1": Mock()} if stage != "queued" else {}
                with self.assertRaisesRegex(ValueError, "本次全部未删除"):
                    self.service.delete_reports(["r2", "r1"])
                self.assertEqual(len(self.store.reports()), 2)
                self.assertIn("删除失败", self.logs[-1])
        self.service.stops.clear()
        self.service.executors.clear()
        self.assertEqual(self.service.delete_reports(["r1", "r2"]), 2)

    def test_executor_alone_still_blocks_and_unrelated_job_does_not(self):
        self.service.executors = {"r1": Mock()}
        with self.assertRaises(ValueError):
            self.service.delete_reports(["r1"])
        self.assertEqual(self.service.delete_reports(["r2"]), 1)

    def test_transaction_rolls_back_partial_delete(self):
        self.store.db.execute("CREATE TRIGGER reject_report BEFORE DELETE ON reports "
                              "WHEN OLD.id='r2' BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
        self.store.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.delete_reports(["r1", "r2"])
        self.assertEqual({r[0] for r in self.store.reports()}, {"r1", "r2"})
        self.assertIn("删除失败，本次全部未删除", self.logs[-1])

    def test_preserves_all_other_tables_and_external_files(self):
        self.store.confirm_case("r1", "标题", "原因", "处理", "复测", "范围")
        self.store.create_chat({"id": "s1", "created": "2026-11-14", "source_report_id": "r1"})
        self.store.append_chat("s1", {"role": "user", "text": "问题"})
        self.store.append_chat("s1", [{"role": "user", "content": "协议"}], group=True)
        self.store.add_chat_evidence("s1", {"source": "历史报告", "text": "已留存报告", "run_id": "manual"})
        self.store.set_setting("fixture", {"value": "保留"})
        self.store.recovery("recovery", {"report_id": "r1"})
        names = [r[0] for r in self.store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                 if r[0] != "reports"]
        before = {name: list(self.store.db.execute("SELECT * FROM " + name)) for name in names}
        log = Path(self.temp.name) / "original.log"
        log.write_bytes(b"original evidence")
        self.service.delete_reports(["r1", "r2"])
        self.assertEqual(before, {name: list(self.store.db.execute("SELECT * FROM " + name)) for name in names})
        self.assertEqual(log.read_bytes(), b"original evidence")
        self.assertEqual(self.store.cases()[0]["report_id"], "r1")

    def test_empty_and_invalid_input_does_not_delete(self):
        self.assertEqual(self.service.delete_reports([]), 0)
        self.assertEqual(self.store.delete_reports([]), 0)
        with self.assertRaises(ValueError):
            self.store.delete_reports(["r1", ""])
        for limit in (-1, True, "100"):
            with self.assertRaises(ValueError):
                self.store.reports(limit=limit)
        self.assertEqual(len(self.store.reports()), 2)

    def test_service_holds_lifecycle_lock_through_store_delete(self):
        original = self.store.delete_reports
        def delete(ids):
            result = []
            def competing_submit():
                acquired = self.service.lock.acquire(blocking=False)
                result.append(acquired)
                if acquired:
                    self.service.lock.release()
            thread = threading.Thread(target=competing_submit)
            thread.start()
            thread.join(2)
            self.assertEqual(result, [False])
            return original(ids)
        with patch.object(self.store, "delete_reports", side_effect=delete):
            self.assertEqual(self.service.delete_reports(["r1"]), 1)


class ReportManagerTests(unittest.TestCase):
    setUp = workspace.WorkspaceTests.setUp
    close_ui = workspace.WorkspaceTests.close_ui
    stop_services = workspace.WorkspaceTests.stop_services
    report = workspace.WorkspaceTests.report

    def manager(self):
        self.report()
        panel = self.dialog.reports_panel
        panel.open()
        panel.selected = "r1"
        panel.reload()
        panel.delete_button.invoke()
        return panel, panel.manager

    def test_button_position_preselection_reopen_and_no_requests(self):
        panel, manager = self.manager()
        buttons = panel.case_button.master.pack_slaves()
        self.assertEqual(buttons.index(panel.delete_button), buttons.index(panel.case_button) + 1)
        self.assertEqual(buttons, [panel.continue_button, panel.case_button, panel.delete_button])
        self.assertEqual(manager.tree.selection(), ("r1",))
        panel.manage_reports()
        self.assertIs(panel.manager, manager)
        self.assertIsNone(manager.window.grab_current())
        self.assertEqual(self.requests, [])

    def test_cancel_defaults_no_and_preserves_selection(self):
        panel, manager = self.manager()
        with patch("src.ui.ai_report_manager.messagebox.askyesno", return_value=False) as ask:
            manager.delete_selected()
        self.assertEqual(ask.call_args.kwargs["default"], "no")
        self.assertEqual(manager.tree.selection(), ("r1",))
        self.assertEqual(panel.selected, "r1")
        self.assertEqual(len(self.store.reports()), 1)

    def test_delete_other_keeps_reading_scroll_and_selection(self):
        panel, manager = self.manager()
        self.report("r2")
        panel.output.yview("45.0")
        panel.output.tag_add("sel", "46.0", "47.0")
        top = panel.output.index("@0,0")
        selection = panel.output.tag_ranges("sel")
        manager.refresh()
        manager.tree.selection_set("r2")
        with patch("src.ui.ai_report_manager.messagebox.askyesno", return_value=True):
            manager.delete_selected()
        self.assertEqual(panel.selected, "r1")
        self.assertEqual(panel.output.index("@0,0"), top)
        self.assertEqual(panel.output.tag_ranges("sel"), selection)

    def test_current_delete_switches_and_empty_disables_operations(self):
        panel, manager = self.manager()
        self.report("r2")
        manager.refresh()
        with patch("src.ui.ai_report_manager.messagebox.askyesno", return_value=True):
            manager.delete_selected()
            self.assertEqual(panel.selected, "r2")
            manager.clear_all()
        self.assertEqual(panel.selected, "")
        self.assertEqual(panel.output.get("1.0", "end-1c"), "暂无诊断报告。")
        for button in (panel.continue_button, panel.case_button, panel.delete_button,
                       manager.delete_button, manager.clear_button):
            self.assertIn("disabled", button.state())
        self.assertEqual(self.dialog.report_status.get(), "")

    def test_clear_all_over_hundred_preserves_report_created_during_confirmation(self):
        panel, manager = self.manager()
        for i in range(105):
            self.report("old" + str(i), report="旧报告")
        manager.refresh()
        self.assertEqual(len(manager.rows), 106)
        manager.select_all()
        self.assertEqual(len(manager.tree.selection()), 106)
        manager.deselect()
        self.assertEqual(manager.tree.selection(), ())
        def confirm(*args, **kwargs):
            self.report("new", report="确认期间新增")
            return True
        with patch("src.ui.ai_report_manager.messagebox.askyesno", side_effect=confirm):
            manager.clear_all()
        self.assertEqual(set(manager.rows), {"new"})
        self.assertEqual(panel.selected, "new")
        self.assertIn("已删除 106 份", manager.status.get())

    def test_failure_keeps_selection_and_report_body(self):
        panel, manager = self.manager()
        before = panel.output.get("1.0", "end-1c")
        with patch("src.ui.ai_report_manager.messagebox.askyesno", return_value=True), \
                patch.object(self.diag, "delete_reports", side_effect=RuntimeError("fixture")), \
                patch("src.ui.ai_report_manager.messagebox.showerror") as error:
            manager.delete_selected()
        error.assert_called_once()
        self.assertEqual(manager.tree.selection(), ("r1",))
        self.assertEqual(panel.output.get("1.0", "end-1c"), before)
        self.assertIn("删除失败", manager.status.get())
        self.assertNotIn("disabled", manager.delete_button.state())

    def test_busy_status_and_batch_rejection_then_retry(self):
        panel, manager = self.manager()
        stop = threading.Event()
        self.diag.stops.add(("r1", 1, stop))
        self.addCleanup(self.diag.stops.clear)
        manager.refresh()
        self.assertIn("不可删除", manager.tree.item("r1", "values")[-1])
        with patch("src.ui.ai_report_manager.messagebox.askyesno", return_value=True), \
                patch("src.ui.ai_report_manager.messagebox.showerror") as error:
            manager.delete_selected()
            error.assert_called_once()
            self.assertEqual(manager.tree.selection(), ("r1",))
            self.diag.stops.clear()
            manager.delete_selected()
        self.assertEqual(self.store.reports(), [])

    def test_deleted_report_queued_notification_is_ignored(self):
        panel, manager = self.manager()
        self.diag.notify("report", ("r1", {}))
        with patch("src.ui.ai_report_manager.messagebox.askyesno", return_value=True):
            manager.clear_all()
        self.root.after_cancel(self.dialog._poll_id)
        self.dialog._poll()
        self.assertEqual(self.dialog.report_status.get(), "")
        self.assertEqual(panel.ids, [])

    def test_handoff_material_and_case_revision_survive_report_delete(self):
        panel, manager = self.manager()
        identifier = self.dialog.continue_report("r1")
        evidence = self.store.chat_evidence(identifier)
        case_id = self.store.confirm_case("r1", "标题", "原因", "处理", "复测", "范围")
        self.diag.delete_reports(["r1"])
        self.assertEqual(self.store.chat(identifier)["source_report_id"], "r1")
        self.assertEqual(self.store.chat_evidence(identifier), evidence)
        self.assertTrue(any("故障报告" in row["text"] for row in evidence))
        self.store.confirm_case("r1", "修订标题", "原因", "处理", "复测", "范围", case_id=case_id)
        self.assertEqual(self.store.cases()[0]["title"], "修订标题")

    def test_vista_clam_minimum_layout(self):
        from tkinter import ttk
        panel, manager = self.manager()
        style = ttk.Style(self.root)
        for theme in ("vista", "clam"):
            if theme not in style.theme_names():
                continue
            with self.subTest(theme=theme):
                style.theme_use(theme)
                panel.window.geometry("760x480")
                manager.window.geometry("760x420")
                panel.window.deiconify()
                manager.window.deiconify()
                self.root.update()
                for button in (panel.case_button, panel.delete_button,
                               manager.delete_button, manager.clear_button):
                    self.assertTrue(button.winfo_ismapped())
                    self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                         button.winfo_toplevel().winfo_rootx() + button.winfo_toplevel().winfo_width())


if __name__ == "__main__":
    unittest.main()
