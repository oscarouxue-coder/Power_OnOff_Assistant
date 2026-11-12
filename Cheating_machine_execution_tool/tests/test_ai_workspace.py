"""统一工作台、报告接手与监控隔离；临时数据库和离线模型。"""
from dataclasses import asdict, replace
import gc
import json
import tkinter as tk
import unittest
from unittest.mock import patch

import test_ai_conversation as conversation_fixtures
from test_ai_debug import TARGET
from src.ui.ai_diagnostics_window import AiDiagnosticsWindow


class WorkspaceTests(unittest.TestCase):
    stop_services = conversation_fixtures.ConversationTests.stop_services

    def setUp(self):
        conversation_fixtures.ConversationTests.setUp(self)
        gc.collect()
        self.root = tk.Tk()
        self.root.withdraw()
        self.targets = (TARGET, replace(TARGET, channel=2, vlan="VLAN102", port="COM2"))
        self.dialog = AiDiagnosticsWindow(self.root, self.diag, lambda: self.targets, conversation=self.service)
        self.dialog.open()
        self.addCleanup(self.close_ui)

    def close_ui(self):
        if self.dialog._poll_id:
            self.root.after_cancel(self.dialog._poll_id)
        self.root.update_idletasks()
        self.dialog.window.destroy()
        self.root.destroy()
        self.dialog = self.root = None
        gc.collect()

    def report(self, identifier="r1", target=TARGET, **changes):
        payload = dict(run_id="run1", channel=target.channel, target=asdict(target),
                       provider="offline", status="完成", report="故障报告\n" * 180, evidence="故障时证据")
        payload.update(changes)
        self.store.save_report(identifier, payload)
        return payload

    def test_workspace_is_only_manual_entry_and_auxiliary_windows_are_lazy(self):
        self.assertEqual([self.dialog.book.tab(t, "text") for t in self.dialog.book.tabs()],
                         ["排障工作台", "模型接入", "已确认案例"])
        self.assertIsNone(self.dialog.monitor_panel.window)
        self.assertIsNone(self.dialog.reports_panel.window)
        self.assertFalse(hasattr(self.dialog, "question"))
        self.assertFalse(hasattr(self.dialog, "_submit"))
        self.assertFalse(hasattr(self.dialog.chat_panel, "from_report"))

    def test_windows_reopen_non_modal_and_close_does_not_cancel_tasks(self):
        with patch.object(self.diag, "cancel") as cancel, patch.object(self.service, "stop") as stop:
            for panel in (self.dialog.monitor_panel, self.dialog.reports_panel):
                panel.open()
                window = panel.window
                self.assertIsNone(window.grab_current())
                window.tk.call(window.protocol("WM_DELETE_WINDOW"))
                self.assertEqual(window.state(), "withdrawn")
                panel.open()
                self.assertIs(panel.window, window)
            cancel.assert_not_called()
            stop.assert_not_called()
        self.assertEqual(self.requests, [])

    def test_new_report_does_not_switch_chat_or_create_session_or_request(self):
        panel = self.dialog.chat_panel
        selected = panel.selected
        before = len(self.store.chats())
        self.report()
        self.diag.notify("report", ("r1", {}))
        self.root.after_cancel(self.dialog._poll_id)
        self.dialog._poll()
        self.root.update()
        self.assertEqual(panel.selected, selected)
        self.assertEqual(len(self.store.chats()), before)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.dialog.report_status.get(), "报告有更新")
        self.assertIsNone(self.dialog.reports_panel.window)

    def test_cross_channel_report_handoff_uses_snapshot_and_waits_for_send(self):
        target = self.targets[1]
        original = self.report(target=target)
        identifier = self.dialog.continue_report("r1")
        session = self.store.chat(identifier)
        self.assertEqual(session["target"], asdict(target))
        self.assertEqual(session["source_report_id"], "r1")
        self.assertEqual(session["run_id"], "run1")
        self.assertEqual(self.dialog.chat_panel.target_choice.current(), 1)
        self.assertEqual(self.dialog.book.select(), str(self.dialog.workspace))
        self.assertTrue(self.service.authorized(identifier))
        self.assertIn("故障时证据", self.store.chat_evidence(identifier)[-1]["text"])
        self.assertEqual(self.store.report("r1"), original)
        self.assertEqual(self.requests, [])
        self.assertTrue(self.service.jobs.empty())

    def test_old_batch_and_changed_target_do_not_gain_collection(self):
        for changes in ({"run_id": "old-run"}, {"target": replace(TARGET, port="COM99")}):
            with self.subTest(changes=changes):
                self.report(**changes)
                identifier = self.dialog.continue_report("r1")
                self.assertFalse(self.service.authorized(identifier))
                self.assertEqual(self.requests, [])

    def test_local_report_snapshot_keeps_original_target_without_model_call(self):
        self.diag.configure(replace(self.profile, model=""), (TARGET,))
        report_id = self.diag.submit("离线触发快照", TARGET.channel)
        self.diag.configure(self.profile, (replace(TARGET, port="COM99"),))
        self.assertEqual(self.store.report(report_id)["target"], asdict(TARGET))
        self.assertEqual(self.requests, [])

    def test_handoff_then_send_keeps_report_and_full_conversation_tools(self):
        self.report(target=self.targets[1])
        identifier = self.dialog.continue_report("r1")
        self.dialog.chat_panel.input.insert("1.0", "继续分析该报告")
        self.dialog.chat_panel.send()
        self.service.jobs.join()
        self.assertEqual(self.dialog.chat_panel.selected, identifier)
        self.assertIn("故障时证据", json.dumps(self.requests[-1], ensure_ascii=False))
        names = {t["function"]["name"] for t in self.requests[-1]["tools"]}
        self.assertIn("run_local_command", names)
        self.assertEqual(self.store.chat(identifier)["target"], asdict(self.targets[1]))

    def test_old_batch_stays_material_only_after_sending_in_workspace(self):
        self.report(run_id="old-run")
        identifier = self.dialog.continue_report("r1")
        self.dialog.chat_panel.input.insert("1.0", "分析故障时材料")
        self.dialog.chat_panel.send()
        self.service.jobs.join()
        self.assertEqual(self.dialog.chat_panel.selected, identifier)
        names = {t["function"]["name"] for t in self.requests[-1]["tools"]}
        self.assertNotIn("run_local_command", names)
        self.assertNotIn("run_device_command", names)
        self.assertFalse(self.service.authorized(identifier))

    def test_legacy_ui_confirmation_cancellation_and_explicit_handoff(self):
        self.report()
        payload = self.store.report("r1")
        payload.pop("target")
        self.store.save_report("r1", payload)
        panel = self.dialog.reports_panel
        panel.open()
        with patch.object(self.dialog, "_error") as error:
            panel.continue_chat()
            error.assert_called_once()
        panel.legacy_target.current(0)
        before = len(self.store.chats())
        with patch("src.ui.ai_reports_window.messagebox.askyesno", return_value=False):
            panel.continue_chat()
        self.assertEqual(len(self.store.chats()), before)
        with patch("src.ui.ai_reports_window.messagebox.askyesno", return_value=True):
            panel.continue_chat()
        self.assertEqual(len(self.store.chats()), before + 1)
        self.assertEqual(self.requests, [])

    def test_legacy_report_requires_explicit_target_confirmation_and_same_channel(self):
        self.report()
        payload = self.store.report("r1")
        payload.pop("target")
        self.store.save_report("r1", payload)
        for target, confirmed in ((None, False), (TARGET, False), (self.targets[1], True)):
            with self.subTest(target=target, confirmed=confirmed), self.assertRaises(ValueError):
                self.service.create_session_from_report("r1", self.profile, target, confirmed)
        identifier = self.service.create_session_from_report("r1", self.profile, TARGET, True)
        self.assertEqual(self.store.chat(identifier)["run_id"], "run1")
        self.assertEqual(self.requests, [])

    def test_legacy_no_batch_is_historical_and_stale_target_is_rejected(self):
        self.report(run_id="")
        payload = self.store.report("r1")
        payload.pop("target")
        self.store.save_report("r1", payload)
        with self.assertRaises(ValueError):
            self.service.create_session_from_report("r1", self.profile, replace(TARGET, port="COM99"), True)
        identifier = self.service.create_session_from_report("r1", self.profile, TARGET, True)
        self.assertFalse(self.service.authorized(identifier))
        self.assertEqual(self.store.chat(identifier)["run_id"], "historical:r1")

    def test_invalid_or_missing_report_does_not_create_session(self):
        before = len(self.store.chats())
        self.report(channel=99)
        with self.assertRaises(ValueError):
            self.service.create_session_from_report("r1", self.profile)
        with self.assertRaises(ValueError):
            self.service.create_session_from_report("missing", self.profile)
        self.assertEqual(len(self.store.chats()), before)

    def test_report_refresh_preserves_selection_scroll_and_text_selection(self):
        self.report()
        panel = self.dialog.reports_panel
        panel.open()
        self.root.update()
        panel.output.yview_moveto(.35)
        panel.output.tag_add("sel", "3.0", "3.3")
        self.root.update()
        top = panel.output.index("@0,0")
        selected = panel.output.get("sel.first", "sel.last")
        self.report("new", target=self.targets[1])
        panel.reload()
        self.root.update()
        self.assertEqual(panel.selected, "r1")
        self.assertEqual(panel.output.index("@0,0"), top)
        self.assertEqual(panel.output.get("sel.first", "sel.last"), selected)
        self.report(report="故障报告\n" * 200)
        panel.reload()
        self.root.update()
        self.assertEqual(panel.output.index("@0,0"), top)
        self.assertEqual(panel.output.get("sel.first", "sel.last"), selected)

    def test_report_selection_remains_when_outside_recent_hundred(self):
        self.report()
        panel = self.dialog.reports_panel
        panel.open()
        for i in range(101):
            self.report("new" + str(i))
        with self.store.lock:
            self.store.db.execute("UPDATE reports SET created='2000-01-01' WHERE id='r1'")
            self.store.db.commit()
        panel.reload()
        self.assertEqual(panel.selected, "r1")
        self.assertIn("r1", panel.ids)

    def test_case_source_survives_report_change_and_existing_case_revision(self):
        self.report()
        self.report("r2")
        self.dialog.case_from_report("r1")
        panel = self.dialog.reports_panel
        panel.open()
        panel.selected = "r2"
        panel.render()
        for key, value in self.dialog.case_fields.items():
            value.set(key)
        with patch("src.ui.ai_diagnostics_window.messagebox.askyesno", return_value=True):
            self.dialog._confirm_case()
        case = self.store.cases()[0]
        self.assertEqual(case["report_id"], "r1")
        self.dialog.case_list.selection_set(str(case["id"]))
        self.dialog._choose_case()
        panel.selected = "r2"
        with patch("src.ui.ai_diagnostics_window.messagebox.askyesno", return_value=True):
            self.dialog._confirm_case()
        self.assertEqual(self.store.cases()[0]["report_id"], "r1")
        self.dialog._new_case()
        self.assertEqual(self.dialog.case_report_id, "")

    def test_monitor_scope_is_independent_and_stops_do_not_cross(self):
        monitor = self.dialog.monitor_panel
        monitor.channels.set("2")
        monitor.enabled.set(True)
        with patch("src.ui.ai_monitor_window.messagebox.askyesno", return_value=True):
            monitor.changed()
        self.assertEqual(self.diag.trigger.policy.channels, (2,))
        self.assertTrue(self.diag.trigger.enabled)
        self.assertEqual(self.dialog.chat_panel.target_choice.current(), 0)
        with patch.object(self.service, "cancel_all") as cancel_all, patch.object(self.diag, "cancel") as cancel:
            monitor.enabled.set(False)
            monitor.changed()
            cancel.assert_called_once()
            cancel_all.assert_not_called()
        with patch.object(self.diag, "cancel") as cancel:
            self.dialog.chat_panel.stop()
            cancel.assert_not_called()

    def test_monitor_apply_and_cancel_preserve_active_policy_and_validation(self):
        monitor = self.dialog.monitor_panel
        monitor.enabled.set(True)
        with patch("src.ui.ai_monitor_window.messagebox.askyesno", return_value=True):
            monitor.changed()
        previous = self.diag.trigger.policy
        monitor.channels.set("2")
        with patch("src.ui.ai_monitor_window.messagebox.askyesno", return_value=False):
            monitor.apply()
        self.assertTrue(self.diag.trigger.enabled)
        self.assertTrue(monitor.enabled.get())
        self.assertEqual(self.diag.trigger.policy, previous)
        monitor.channels.set("99")
        with patch.object(self.dialog, "_error") as error:
            monitor.apply()
            error.assert_called_once()
        self.assertEqual(self.diag.trigger.policy, previous)
        self.assertTrue(monitor.enabled.get())

    def test_minimum_layout_and_auxiliary_themes(self):
        from tkinter import ttk
        for theme in ("vista", "clam"):
            with self.subTest(theme=theme):
                style = ttk.Style(self.root)
                style.theme_use(theme)
                self.dialog._apply_theme()
                self.dialog.window.geometry("940x660")
                self.dialog.window.deiconify()
                self.dialog.book.select(self.dialog.workspace)
                self.root.update()
                panel = self.dialog.chat_panel
                for widget in (panel.input, panel.send_button, panel.context_status):
                    self.assertTrue(widget.winfo_viewable())
                    self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                         self.dialog.window.winfo_rooty() + self.dialog.window.winfo_height())
                self.assertGreater(panel.output.winfo_height(), 80)
                self.dialog.monitor_panel.open()
                self.dialog.reports_panel.open()
                for auxiliary in (self.dialog.monitor_panel, self.dialog.reports_panel):
                    # 以各自最小尺寸核对所有操作控件未被底部裁切。
                    size = auxiliary.window.minsize()
                    auxiliary.window.geometry(f"{size[0]}x{size[1]}")
                    self.root.update()
                    self.assertIsNone(auxiliary.window.grab_current())
                    self.assertEqual(auxiliary.window.cget("background"), self.dialog.background_color)
                    def verify(parent):
                        for child in parent.winfo_children():
                            if child.winfo_class() in ("TButton", "Checkbutton", "TEntry", "TCombobox", "TSpinbox"):
                                self.assertTrue(child.winfo_viewable())
                                self.assertLessEqual(child.winfo_rooty() + child.winfo_height(),
                                                     auxiliary.window.winfo_rooty() + auxiliary.window.winfo_height())
                                self.assertLessEqual(child.winfo_rootx() + child.winfo_width(),
                                                     auxiliary.window.winfo_rootx() + auxiliary.window.winfo_width())
                            verify(child)
                    verify(auxiliary.window)
                self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
