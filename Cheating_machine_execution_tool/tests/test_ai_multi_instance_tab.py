"""Mapped offscreen Tk forms, temporary configuration and no external connections."""
from contextlib import ExitStack
import gc
import os
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
from types import SimpleNamespace
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

from src.models.capabilities import CapabilitySpec, object_schema
from src.services.capability_registry import CapabilityRegistry
from src.services.remote_gateway_host import RemoteGatewayHost
from src.services.remote_instance_management import RemoteInstanceManagement
from src.services.remote_gateway_runtime import RemoteGatewayRuntime
from src.ui.ai_multi_instance_tab import MultiInstanceTab
from src.ui.ai_assistant_controller import AiAssistantController
from test_ai_core import FakeCipher
from tk_test_windows import OffscreenTkWindows


class MultiInstanceTabTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        temporary = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.dict(os.environ, LOCALAPPDATA=str(temporary), LINECHECK_GATEWAY_SLOT=""))
        self.windows = self.stack.enter_context(OffscreenTkWindows())
        self.root = tk.Tk()
        self.root.geometry("1080x720")
        self.registry = CapabilityRegistry()
        self.registry.register(CapabilitySpec("firmware.upgrade", "升级", "fake", object_schema(), lambda a, auth: None))
        self.registry.register(CapabilitySpec("power.on", "上电", "fake", object_schema(), lambda a, auth: None))
        self.logs = []
        self.host = RemoteGatewayHost(temporary / "gateway", cipher=FakeCipher())
        self.service = RemoteInstanceManagement(temporary / "program", registry=lambda: self.registry,
            cipher=FakeCipher(), host=self.host, emit=self.logs.append)
        self.panel = MultiInstanceTab(self.root, self.service)
        self.addCleanup(self.cleanup)
        self.panel.activate()
        self.wait_idle()

    def cleanup(self):
        self.panel.dispose()
        self.service.begin_close()
        self.service.close_thread.join(5)
        self.windows.assert_offscreen()
        self.root.update_idletasks()
        self.root.destroy()
        self.panel = self.root = None
        gc.collect()

    def wait_idle(self):
        deadline = time.monotonic() + 4
        while self.panel.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.root.update()
        self.assertFalse(self.panel.busy)

    def widgets(self, root):
        for child in root.winfo_children():
            yield child
            yield from self.widgets(child)

    def test_native_checkboxes_theme_and_no_connection_on_open(self):
        self.assertEqual([self.panel.book.tab(t, "text") for t in self.panel.book.tabs()], ["本机实例", "统一网关"])
        checks = [w for w in self.widgets(self.panel.frame) if isinstance(w, tk.Checkbutton)]
        self.assertEqual(len(checks), 20)
        self.assertFalse(any(isinstance(w, ttk.Checkbutton) for w in self.widgets(self.panel.frame)))
        self.assertTrue(all(w.cget("background") == "#eef2f5" for w in checks))
        self.assertTrue(all(not v.get() for v in self.panel.channels.values()))
        self.assertIsNone(self.host.server)
        self.assertEqual(self.panel.capabilities.curselection(), ())

    def test_activate_suspend_preserves_drafts_one_timer_and_service(self):
        self.panel.variables["name"].set("未保存的名字")
        self.panel.gateway_vars["host"].set("10.8.0.2")
        timer = self.panel.after_id
        self.panel.activate()
        self.assertEqual(self.panel.after_id, timer)
        with patch.object(self.host, "stop") as stop:
            self.panel.suspend()
            self.assertIsNone(self.panel.after_id)
            self.panel.activate()
            self.assertEqual(self.panel.variables["name"].get(), "未保存的名字")
            self.assertEqual(self.panel.gateway_vars["host"].get(), "10.8.0.2")
            stop.assert_not_called()

    def test_late_slot_read_does_not_overwrite_new_input(self):
        ready, release = threading.Event(), threading.Event()
        original = self.service.slot
        def slow(number):
            ready.set()
            release.wait(3)
            return original(number)
        with patch.object(self.service, "slot", side_effect=slow):
            self.panel._load_slot()
            self.assertTrue(ready.wait(1))
            self.panel.variables["url"].set("ws://127.0.0.1:19000")
            release.set()
            self.wait_idle()
        self.assertEqual(self.panel.variables["url"].get(), "ws://127.0.0.1:19000")

    def test_pending_operation_completed_while_hidden_drains_after_reopen(self):
        ready, release = threading.Event(), threading.Event()
        def work():
            ready.set()
            release.wait(3)
            return "saved"
        done = Mock()
        self.panel._submit(work, done)
        self.assertTrue(ready.wait(1))
        self.panel.suspend()
        release.set()
        self.panel.activate()
        self.wait_idle()
        done.assert_called_once_with("saved")

    def test_duplicate_clicks_only_submit_once_and_error_does_not_disclose(self):
        ready, release = threading.Event(), threading.Event()
        calls = []
        def work():
            calls.append(True)
            ready.set()
            release.wait(3)
            raise RuntimeError("private-platform-secret")
        self.panel._submit(work)
        self.assertTrue(ready.wait(1))
        self.panel._submit(work)
        release.set()
        self.wait_idle()
        self.assertEqual(len(calls), 1)
        self.assertNotIn("private-platform-secret", self.panel.result.get())
        self.assertNotIn("private-platform-secret", "\n".join(self.logs))

    def test_instance_confirmation_cancellation_and_captured_scope(self):
        self.panel.variables["mode"].set("统一网关接入")
        self.panel.variables["url"].set("ws://127.0.0.1:18761")
        self.panel.channels[1].set(True)
        self.panel.capabilities.selection_set(0)
        with patch("src.ui.ai_multi_instance_tab.messagebox.askyesno", return_value=False), patch.object(self.service, "save_instance") as save:
            self.panel._save_instance()
            save.assert_not_called()
        with patch("src.ui.ai_multi_instance_tab.messagebox.askyesno", return_value=True), patch.object(self.service, "save_instance") as save:
            self.panel._save_instance()
            self.wait_idle()
            save.assert_called_once_with("gateway", 1, "ws://127.0.0.1:18761", False, [1], ["firmware.upgrade"])

    def test_pairing_code_expiry_and_dispose_clear_only_ui(self):
        self.panel._show_code("temporary-pair-code")
        self.panel.code_expires = time.monotonic() - 1
        self.panel.suspend()
        self.panel.activate()
        self.assertEqual(self.panel.pairing_code.get(), "")
        self.panel.variables["code"].set("typed-pair-code")
        with patch.object(self.service, "begin_close") as close:
            self.panel.dispose()
            self.assertEqual(self.panel.variables["code"].get(), "")
            self.assertIsNone(self.panel.after_id)
            close.assert_not_called()

    def test_gui_loopback_save_start_pair_scope_and_next_boot(self):
        from test_remote_instance_management import free_port, SCOPES
        self.panel.gateway_vars["port"].set(str(free_port()))
        self.panel.scopes = SCOPES
        self.panel._save_gateway()
        self.wait_idle()
        self.panel._start_gateway()
        self.wait_idle()
        self.assertIsNotNone(self.host.server)
        self.panel._create_code()
        self.wait_idle()
        self.assertTrue(self.panel.pairing_code.get())
        self.panel.variables["name"].set("界面回环实例")
        self.panel.variables["url"].set("ws://127.0.0.1:" + str(self.host.server.port))
        self.panel.variables["code"].set(self.panel.pairing_code.get())
        self.panel._pair()
        self.wait_idle()
        self.assertEqual(self.panel.variables["code"].get(), "")
        self.assertIn("fake-chat", self.panel.scope_summary.get())
        self.panel.variables["mode"].set("统一网关接入")
        self.panel.channels[1].set(True)
        self.panel.capabilities.selection_set(0)
        with patch("src.ui.ai_multi_instance_tab.messagebox.askyesno", return_value=True):
            self.panel._save_instance()
            self.wait_idle()
        runtime = RemoteGatewayRuntime(self.service.app_dir, 1, cipher=FakeCipher())
        try:
            self.assertEqual(runtime.config["channel_ids"], [1])
            self.assertEqual(runtime.config["capability_ids"], ["firmware.upgrade"])
            self.assertTrue(runtime.config["enabled"])
        finally:
            runtime.close()

    def test_late_pair_success_preserves_new_code_draft(self):
        self.panel.variables["code"].set("new-code")
        revision = self.panel.revision - 1
        self.panel._pair_done({}, revision, "old-code")
        self.assertEqual(self.panel.variables["code"].get(), "new-code")

    def test_slot_is_frozen_during_operation_and_unread_slot_cannot_save_scope(self):
        ready, release = threading.Event(), threading.Event()
        def work():
            ready.set()
            release.wait(3)
        self.panel._submit(work)
        self.assertTrue(ready.wait(1))
        self.assertEqual(str(self.panel.slot_choice.cget("state")), "disabled")
        release.set()
        self.wait_idle()
        self.assertEqual(str(self.panel.slot_choice.cget("state")), "readonly")
        self.panel.variables["slot"].set("2")
        self.panel.variables["mode"].set("统一网关接入")
        with patch.object(self.service, "save_instance") as save:
            self.panel._save_instance()
            save.assert_not_called()
        self.assertIn("重新读取所选槽位", self.panel.result.get())

    def test_invalid_gateway_startup_keeps_editor_and_never_starts_direct_mode(self):
        terminal = SimpleNamespace(ai_debug_cancel=None, diagnostic_observer=None)
        args = (self.root, terminal, Mock(), lambda: (), lambda target: False, lambda: "", self.logs.append, None)
        with patch("src.services.remote_instance_management.selected_gateway_slot", return_value=1), \
                patch("src.services.remote_gateway_runtime.RemoteGatewayRuntime", side_effect=ValueError("unpaired")), \
                patch("src.services.dingtalk_remote_service.DingTalkRemoteService") as direct:
            controller = AiAssistantController(*args, app_dir=self.service.app_dir, project_config_path=self.service.app_dir / "project.ini")
        try:
            self.assertTrue(controller.gateway_startup_error)
            self.assertIsNone(controller.remote)
            self.assertIsNone(controller.feishu_remote)
            direct.assert_not_called()
            controller.dialog.open()
            controller.dialog.book.select(controller.dialog.multi_tab)
            self.root.update()
            self.assertIsNotNone(controller.dialog.multi_panel)
            self.assertEqual(controller.instance_management.status()["current_mode"], "error")
        finally:
            deadline = time.monotonic() + 5
            while not controller.prepare_app_close() and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
            self.assertTrue(controller.closed)

    def test_gateway_forms_and_bottom_actions_fit_minimum_window(self):
        self.panel.scope_summary.set("long-member-scope\n" * 200)
        for size in ("1060x710", "920x590"):
            self.root.geometry(size)
            for page in (self.panel.instance_page, self.panel.gateway_page):
                self.panel.book.select(page)
                self.root.update_idletasks()
                self.root.update()
                for widget in self.widgets(page):
                    if isinstance(widget, ttk.Button):
                        self.assertTrue(widget.winfo_ismapped(), (size, widget.cget("text")))
                        self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), page.winfo_rooty() + page.winfo_height(), (size, widget.cget("text")))


if __name__ == "__main__":
    unittest.main()
