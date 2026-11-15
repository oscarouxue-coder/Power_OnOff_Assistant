"""嵌入接入表单的离线Tk验证；不连接平台、模型或设备。"""
from contextlib import ExitStack
import gc
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

from line_check_assistant.app import LineCheckAssistant
from src.ui.dingtalk_setup_window import DingTalkSetupWindow
from src.ui.feishu_setup_window import FeishuSetupWindow
from tk_test_windows import OffscreenTkWindows


class RemoteManagementTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.windows = self.stack.enter_context(OffscreenTkWindows())
        self.root = tk.Tk()
        self.addCleanup(self.cleanup_root)
        self.root.geometry("880x560")
        self.root._log = Mock()
        self.root._sync_ai_message_push = Mock()
        self.notifications = Mock(busy=False, last_result="尚未发送")
        self.root._feishu_notification_service = Mock(return_value=self.notifications)
        self.root.ai_assistant = Mock(remote=None, feishu_remote=None)
        self.stores, self.constructors = {}, {}
        configs = {
            "dingtalk": dict(isolated=False, enabled=False, client_id="", client_secret="",
                             robot_code="", webhook="", secret="", group_name=""),
            "feishu": dict(isolated=False, enabled=False, app_id="", app_secret="",
                           group_enabled=False, p2p_enabled=False, push_enabled=False, group_name=""),
        }
        for platform, store_name, constructor in (
            ("dingtalk", "RemoteConfigStore", DingTalkSetupWindow),
            ("feishu", "FeishuConfigStore", FeishuSetupWindow),
        ):
            store = Mock()
            store.load.return_value = configs[platform]
            store.configure.return_value = dict(configs[platform], webhook="new-hook", secret="new-secret")
            self.stores[platform] = store
            self.stack.enter_context(patch(f"src.services.{platform}_remote_store.{store_name}", return_value=store))
            self.constructors[platform] = self.stack.enter_context(patch(
                f"src.ui.{platform}_setup_window.{constructor.__name__}", wraps=constructor))
        self.stack.enter_context(patch("line_check_assistant.app.MessagePushConfigService")).return_value.load.return_value = {
            "webhook": "saved-push-hook", "secret": "saved-push-secret"}
        self.messages = self.stack.enter_context(patch("src.ui.dingtalk_setup_window.messagebox"))
        self.stack.enter_context(patch("src.ui.feishu_setup_window.messagebox", self.messages))
        self.management = LineCheckAssistant._build_ai_remote_management(self.root, self.root)

    def cleanup_root(self):
        self.windows.assert_offscreen()
        self.root.update_idletasks()
        self.root.destroy()
        self.management = self.root = None
        gc.collect()

    def runtime(self, platform, **changes):
        config = dict(self.stores[platform].load.return_value, **changes)
        runtime = Mock(config=config, transport=None, sessions=(), conversation=Mock(running={}))
        runtime.snapshot.return_value = dict(enabled=config["enabled"], candidate=None, binding=True, status="等待绑定")
        setattr(self.root.ai_assistant, "remote" if platform == "dingtalk" else "feishu_remote", runtime)
        return runtime

    def test_lazy_embedded_reuse_keeps_input_and_one_timer_per_platform(self):
        self.assertFalse(self.management.panels)
        self.assertEqual([self.management.book.tab(t, "text") for t in self.management.book.tabs()], ["钉钉", "飞书"])
        self.management.activate()
        for platform, field in (("dingtalk", "client_id"), ("feishu", "app_id")):
            panel = self.management.panels[platform]
            self.assertIsInstance(panel.window, tk.Frame)
            self.assertIs(panel.dialog_parent, self.root)
            panel.variables[field].set("unsaved-input")
            timer = panel.after_id
            loads = self.stores[platform].load.call_count
            for _ in range(3):
                self.management.select_platform(platform)
                self.management.activate()
            self.assertIs(self.management.panels[platform], panel)
            self.assertEqual(panel.variables[field].get(), "unsaved-input")
            self.assertEqual(panel.after_id, timer)
            self.assertEqual(self.stores[platform].load.call_count, loads)
            self.constructors[platform].assert_called_once()
        self.assertFalse(any(isinstance(w, tk.Toplevel) for w in self.root.winfo_children()))
        self.assertEqual(self.management.panels["dingtalk"].variables["webhook"].get(), "saved-push-hook")
        self.assertEqual(self.management.panels["dingtalk"].variables["client_secret"].get(), "")
        self.assertEqual(self.management.panels["feishu"].variables["app_secret"].get(), "")

    def test_tab_switch_pauses_without_cancel_hide_cancels_only_pending_binding(self):
        ding, feishu = self.runtime("dingtalk"), self.runtime("feishu", p2p_enabled=True, enabled=True, push_enabled=True)
        self.management.activate()
        for panel in self.management.panels.values():
            panel.code = "PENDING"
        self.management.suspend()
        for panel in self.management.panels.values():
            self.assertIsNone(panel.after_id)
            self.assertEqual(panel.code, "PENDING")
        ding.enable.assert_not_called()
        feishu.cancel_binding.assert_not_called()
        self.management.activate()
        self.management.suspend(cancel_binding=True)
        ding.enable.assert_called_once_with(False)
        feishu.cancel_binding.assert_called_once_with()
        feishu.enable.assert_not_called()
        feishu.set_push_enabled.assert_not_called()
        for panel in self.management.panels.values():
            self.assertEqual(panel.code, "")
            self.assertIsNone(panel.after_id)
        self.management.activate()
        for panel in self.management.panels.values():
            self.assertIsNotNone(panel.after_id)

    def test_hiding_active_platform_without_pending_binding_keeps_services(self):
        ding = self.runtime("dingtalk", enabled=True)
        feishu = self.runtime("feishu", enabled=True, group_enabled=True, push_enabled=True)
        self.management.activate()
        self.management.suspend(cancel_binding=True)
        ding.enable.assert_not_called()
        feishu.enable.assert_not_called()
        feishu.cancel_binding.assert_not_called()
        feishu.set_push_enabled.assert_not_called()

    def test_failed_binding_cleanup_still_pauses_both_platforms_without_disclosure(self):
        ding, feishu = self.runtime("dingtalk"), self.runtime("feishu")
        ding.enable.side_effect = RuntimeError("private-token")
        self.management.activate()
        for panel in self.management.panels.values():
            panel.code = "PENDING"
        self.management.suspend(cancel_binding=True)
        feishu.cancel_binding.assert_called_once()
        self.assertTrue(all(p.after_id is None for p in self.management.panels.values()))
        self.assertNotIn("private-token", str(self.root._log.call_args_list))

    def test_destroy_host_removes_timers_and_new_host_can_load_forms(self):
        self.management.activate()
        panels = tuple(self.management.panels.values())
        timers = [p.after_id for p in panels]
        self.management.frame.destroy()
        afters = self.root.tk.call("after", "info")
        for timer, panel in zip(timers, panels):
            self.assertNotIn(timer, afters)
            self.assertIsNone(panel.after_id)
            panel.resume()
            self.assertIsNone(panel.after_id)
        self.management = LineCheckAssistant._build_ai_remote_management(self.root, self.root)
        self.management.activate()
        for constructor in self.constructors.values():
            self.assertEqual(constructor.call_count, 2)

    def test_platform_load_failure_is_isolated_and_retryable(self):
        self.stores["dingtalk"].load.side_effect = ValueError("private-secret")
        self.management.activate()
        self.assertNotIn("dingtalk", self.management.panels)
        self.assertIn("feishu", self.management.panels)
        feishu = self.management.panels["feishu"]
        self.assertNotIn("private-secret", str(self.management.errors))
        self.assertNotIn("private-secret", str(self.root._log.call_args_list))
        self.messages.showerror.assert_not_called()
        self.stores["dingtalk"].load.side_effect = None
        self.management.activate()
        self.assertIn("dingtalk", self.management.panels)
        self.assertIs(self.management.panels["feishu"], feishu)
        self.assertFalse(self.management.errors)

    def test_embedded_save_keeps_notification_sync_and_dialog_parent(self):
        self.management.activate()
        ding = self.management.panels["dingtalk"]
        ding.variables["client_id"].set("new-client")
        ding.variables["client_secret"].set("new-secret")
        ding.save()
        self.root._sync_ai_message_push.assert_called_once_with(self.stores["dingtalk"].configure.return_value)
        self.assertEqual(ding.variables["client_secret"].get(), "")
        self.assertIs(self.messages.showinfo.call_args.kwargs["parent"], self.root)
        self.assertIn("重启", ding.status.get())
        feishu = self.management.panels["feishu"]
        feishu.variables["app_secret"].set("app-secret")
        feishu.save()
        self.stores["feishu"].configure.assert_called_once()
        self.assertEqual(feishu.variables["app_secret"].get(), "")
        self.notifications.enqueue.assert_not_called()

    def test_embedded_enable_cancellation_keeps_switches_off_and_uses_ai_parent(self):
        ding, feishu = self.runtime("dingtalk"), self.runtime("feishu")
        self.management.activate()
        self.messages.askyesno.return_value = False
        panel = self.management.panels["dingtalk"]
        panel.enabled.set(True)
        panel.toggle()
        self.assertFalse(panel.enabled.get())
        ding.enable.assert_not_called()
        panel = self.management.panels["feishu"]
        for kind in ("group", "p2p"):
            panel.switches[kind].set(True)
            panel.toggle(kind)
            self.assertFalse(panel.switches[kind].get())
        feishu.enable.assert_not_called()
        for call in self.messages.askyesno.call_args_list:
            self.assertIs(call.kwargs["parent"], self.root)
            self.assertEqual(call.kwargs["default"], "no")

    def test_embedded_feishu_context_menu_works_from_input(self):
        self.management.activate()
        self.management.select_platform("feishu")
        self.root.update()
        panel = self.management.panels["feishu"]
        entry = next(w for w in panel.window.winfo_children() if isinstance(w, ttk.Entry))
        with patch.object(panel.menu, "tk_popup") as popup:
            entry.event_generate("<Button-3>", rootx=20, rooty=30)
            self.root.update()
            popup.assert_called_once_with(20, 30)

    def test_native_controls_and_minimum_layout_under_vista_clam(self):
        self.management.activate()
        for theme in ("vista", "clam"):
            ttk.Style(self.root).theme_use(theme)
            self.management.activate()
            for platform in self.management.panels:
                self.management.select_platform(platform)
                self.root.update()
                panel = self.management.panels[platform]
                self.assertEqual(panel.window.cget("background"), "#eef2f5")
                checks = [w for w in panel.window.winfo_children() if isinstance(w, tk.Checkbutton)]
                self.assertEqual(len(checks), 1 if platform == "dingtalk" else 3)
                def verify(widget):
                    for child in widget.winfo_children():
                        if child.winfo_class() in ("TButton", "Checkbutton", "TEntry"):
                            self.assertTrue(child.winfo_viewable())
                            self.assertLessEqual(child.winfo_rootx() + child.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width())
                            self.assertLessEqual(child.winfo_rooty() + child.winfo_height(), self.root.winfo_rooty() + self.root.winfo_height())
                        verify(child)
                verify(panel.window)


if __name__ == "__main__":
    unittest.main()
