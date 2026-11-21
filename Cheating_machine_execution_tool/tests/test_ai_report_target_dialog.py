"""旧报告按需选择：独立真实Tk及临时数据库，不连接设备或模型。"""
from dataclasses import asdict, replace
import gc
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

import test_ai_workspace as workspace
from test_ai_debug import TARGET
from src.ui.ai_report_target_dialog import AiReportTargetDialog
from src.ui.module_theme import MODULE_BACKGROUND


class TargetDialogTests(unittest.TestCase):
    def setUp(self):
        from tk_test_windows import install_offscreen_windows
        install_offscreen_windows(self)
        gc.collect()
        self.root = tk.Tk()
        self.root.geometry("800x500")
        self.root.update()
        self.addCleanup(self.root.destroy)

    def dialog(self, targets=(TARGET,)):
        return AiReportTargetDialog(self.root, targets, MODULE_BACKGROUND)

    def test_modal_defaults_no_selection_cancel_focus_and_releases_grab(self):
        dialog = self.dialog()
        observed = []
        def inspect_and_cancel():
            observed.append((dialog.window.grab_current(), dialog.tree.selection(),
                             str(dialog.choose_button.cget("state")),
                             str(dialog.cancel_button.cget("default"))))
            dialog.cancel_button.invoke()
        self.root.after(80, inspect_and_cancel)
        self.assertIsNone(dialog.show())
        self.assertEqual(observed, [(dialog.window, (), "disabled", "active")])
        self.assertIsNone(self.root.grab_current())
        self.assertTrue(self.root.winfo_exists())

    def test_explicit_selection_returns_exact_target_and_full_fields(self):
        target = replace(TARGET, host="long-host-name-for-current-device.example.test", port="COM116")
        dialog = self.dialog((TARGET, target))
        self.assertEqual(tuple(dialog.tree.item("1", "values")),
                         (str(target.channel), target.vlan, target.port, target.host))
        # 未选择时即使直接调用，也不能默认认定第一台设备。
        dialog.choose()
        self.assertTrue(dialog.window.winfo_exists())
        dialog.tree.selection_set("1")
        dialog.selection_changed()
        self.assertNotIn("disabled", dialog.choose_button.state())
        self.root.after(60, dialog.choose_button.invoke)
        self.assertIs(dialog.show(), target)
        self.assertIsNone(self.root.grab_current())

    def test_escape_and_titlebar_close_cancel_after_selection(self):
        for action in ("escape", "close"):
            with self.subTest(action=action):
                dialog = self.dialog()
                dialog.tree.selection_set("0")
                def cancel():
                    if action == "escape":
                        dialog.window.event_generate("<Escape>")
                    else:
                        dialog.window.tk.call(dialog.window.protocol("WM_DELETE_WINDOW"))
                self.root.after(80, cancel)
                self.assertIsNone(dialog.show())
                self.assertIsNone(self.root.grab_current())

    def test_vista_clam_minimum_layout_background_and_scrollbars(self):
        style = ttk.Style(self.root)
        for theme in ("vista", "clam"):
            if theme not in style.theme_names():
                continue
            with self.subTest(theme=theme):
                style.theme_use(theme)
                targets = tuple(replace(TARGET, port="COM" + str(i)) for i in range(40))
                dialog = self.dialog(targets)
                dialog.window.geometry("620x260")
                dialog.window.deiconify()
                self.root.update()
                self.assertEqual(dialog.window.cget("background"), MODULE_BACKGROUND)
                for control in (dialog.tree, dialog.choose_button, dialog.cancel_button):
                    self.assertTrue(control.winfo_viewable())
                    self.assertLessEqual(control.winfo_rootx() + control.winfo_width(),
                                         dialog.window.winfo_rootx() + dialog.window.winfo_width())
                    self.assertLessEqual(control.winfo_rooty() + control.winfo_height(),
                                         dialog.window.winfo_rooty() + dialog.window.winfo_height())
                dialog.tree.yview_moveto(1)
                self.root.update()
                self.assertGreater(dialog.tree.yview()[0], 0)
                dialog.cancel()


class TargetHandoffTests(unittest.TestCase):
    setUp = workspace.WorkspaceTests.setUp
    close_ui = workspace.WorkspaceTests.close_ui
    stop_services = workspace.WorkspaceTests.stop_services
    report = workspace.WorkspaceTests.report

    def legacy_panel(self):
        self.report()
        payload = self.store.report("r1")
        payload.pop("target")
        self.store.save_report("r1", payload)
        panel = self.dialog.reports_panel
        panel.open()
        return panel

    def test_new_report_uses_snapshot_without_selector_or_confirmation(self):
        self.report()
        panel = self.dialog.reports_panel
        panel.open()
        with patch("src.ui.ai_reports_window.AiReportTargetDialog") as chooser, \
                patch("src.ui.ai_reports_window.messagebox.askyesno") as confirm:
            panel.continue_chat()
        chooser.assert_not_called()
        confirm.assert_not_called()
        self.assertFalse(hasattr(panel, "legacy_target"))
        session = self.store.chat(self.dialog.chat_panel.selected)
        self.assertEqual(session["target"], asdict(TARGET))
        self.assertEqual(self.requests, [])
        self.assertTrue(self.service.jobs.empty())

    def test_selector_uses_fresh_same_channel_targets_only(self):
        panel = self.legacy_panel()
        fresh = replace(TARGET, port="COM119", host="192.168.19.1")
        self.targets = (self.targets[1], fresh)
        before = len(self.store.chats())
        with patch("src.ui.ai_reports_window.AiReportTargetDialog") as chooser, \
                patch("src.ui.ai_reports_window.messagebox.askyesno") as confirm:
            chooser.return_value.show.return_value = None
            panel.continue_chat()
        self.assertEqual(chooser.call_args.args[1], (fresh,))
        confirm.assert_not_called()
        self.assertEqual(len(self.store.chats()), before)
        self.assertTrue(any("已取消选择设备" in log for log in self.logs))
        self.assertEqual(self.requests, [])

    def test_missing_current_target_shows_error_and_keeps_report(self):
        panel = self.legacy_panel()
        self.targets = (self.targets[1],)
        before = len(self.store.chats())
        text = panel.output.get("1.0", "end-1c")
        with patch("src.ui.ai_reports_window.AiReportTargetDialog") as chooser, \
                patch.object(self.dialog, "_error") as error:
            panel.continue_chat()
        chooser.assert_not_called()
        self.assertIn("当前无可关联的同通道设备", str(error.call_args.args[0]))
        self.assertEqual(panel.output.get("1.0", "end-1c"), text)
        self.assertEqual(len(self.store.chats()), before)
        self.assertTrue(any("继续排查未完成" in log for log in self.logs))
        self.assertEqual(self.requests, [])

    def test_report_source_pinned_during_selection_and_confirmation(self):
        panel = self.legacy_panel()
        original = self.store.report("r1")
        def select():
            self.report("r2", target=self.targets[1])
            panel.selected = "r2"
            panel.reload()
            return TARGET
        def confirm(*args, **kwargs):
            panel.selected = "r2"
            panel.reload()
            return True
        with patch("src.ui.ai_reports_window.AiReportTargetDialog") as chooser, \
                patch("src.ui.ai_reports_window.messagebox.askyesno", side_effect=confirm):
            chooser.return_value.show.side_effect = select
            panel.continue_chat()
        session = self.store.chat(self.dialog.chat_panel.selected)
        self.assertEqual(session["source_report_id"], "r1")
        self.assertEqual(session["target"], asdict(TARGET))
        self.assertEqual(self.store.report("r1"), original)
        self.assertEqual(self.requests, [])
        self.assertTrue(self.service.jobs.empty())

    def test_changed_target_or_deleted_report_during_selection_is_rejected(self):
        for change in ("target", "report"):
            with self.subTest(change=change):
                panel = self.legacy_panel()
                self.targets = (TARGET, self.targets[1])
                before = len(self.store.chats())
                def select():
                    if change == "target":
                        self.targets = (replace(TARGET, port="COM99"), self.targets[1])
                    else:
                        self.diag.delete_reports(["r1"])
                    return TARGET
                with patch("src.ui.ai_reports_window.AiReportTargetDialog") as chooser, \
                        patch("src.ui.ai_reports_window.messagebox.askyesno", return_value=True), \
                        patch.object(self.dialog, "_error") as error:
                    chooser.return_value.show.side_effect = select
                    panel.continue_chat()
                error.assert_called_once()
                self.assertEqual(len(self.store.chats()), before)
                self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
