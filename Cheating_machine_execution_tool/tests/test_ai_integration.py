from dataclasses import replace
import gc
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.ai_client import DiagnosticModelClient
from src.models.ai_diagnostics import ProviderProfile, DebugTriggerPolicy
from src.services.ai_diagnostic_service import AiDiagnosticService
from src.services.ai_debug_service import DiagnosticToolExecutor
from src.services.ai_store import DiagnosticStore, profile_fingerprint
from src.ui.ai_diagnostics_window import AiDiagnosticsWindow
from src.ui.ai_serial_bridge import AiSerialBridge
from test_ai_core import DIAGNOSTIC_MATERIAL, FakeCipher, FakeResponse, chat, call
from test_ai_debug import TARGET, Session


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DiagnosticStore(self.temp.name, FakeCipher())
        self.addCleanup(self.store.close)
        profile = self.store.save_profile(ProviderProfile(model="test"), "test-key")
        self.profile = replace(profile, capability="可自动诊断", tested_fingerprint=profile_fingerprint(profile))
        self.store.save_profile(self.profile)
        self.requests = []
        self.output = []
        def client_factory(profile, key, redactor):
            session = Mock()
            session.request.return_value = FakeResponse(chat("已观察事实：已有证据。原因假设：待核实。"))
            self.requests.append((profile, key, session))
            return DiagnosticModelClient(profile, key, redactor, session)
        def tool_factory(*args):
            tool = DiagnosticToolExecutor(*args)
            tool.pc_environment = lambda: "PC snapshot"
            return tool
        self.service = AiDiagnosticService(self.output.append, Mock(), lambda _t: "串口现场",
            lambda _t: False, self.store, client_factory, tool_factory)
        self.service.configure(self.profile, (TARGET,), DebugTriggerPolicy(channels=(1,)))
        self.addCleanup(self.stop_service)

    def stop_service(self):
        self.service.begin_close()
        self.service.event_thread.join(3)
        self.service.worker_thread.join(3)
        self.assertFalse(self.service.worker_thread.is_alive())

    def finish(self):
        self.service.events.join()
        self.service.jobs.join()

    def test_manual_job_freezes_provider_and_saves_report_without_model_key(self):
        identifier = self.service.submit("test-key 为什么失败？", 1, "question")
        self.service.configure(replace(self.profile, provider="MiniMax", model="other"), (TARGET,))
        self.finish()
        profile, key, session = self.requests[0]
        self.assertEqual(profile.provider, "DeepSeek")
        self.assertEqual(profile.model, "test")
        self.assertEqual(key, "test-key")
        report = self.store.reports()[0][2]
        self.assertNotIn("test-key", json.dumps(report))
        self.assertEqual(report["status"], "完成")
        self.assertNotIn("tools", session.request.call_args.kwargs["json"])

    def test_disabled_monitor_never_calls_model_but_serial_context_is_available(self):
        self.service.observe({"type": "diagnostic_start", "run_id": "r"})
        self.service.observe_serial("vlan101", Mock(port="COM1", direction="RX", text="串口故障现场"))
        self.service.observe({"type": "channel_result", "run_id": "r", "channel": 1, "ok": False})
        self.finish()
        self.assertEqual(self.requests, [])

    def test_monitor_triggers_third_attempt_and_not_credentials_or_duplicates(self):
        self.service.enable_monitor(True)
        self.service.observe({"type": "diagnostic_start", "run_id": "r"})
        for attempt in (1, 1, 2):
            self.service.observe({"type": "log", "run_id": "r", "channel": 1,
                "message": f"[WiFi测试] 通道1 第1轮 5G 第{attempt}/4次扫描失败：错误码=123"})
        self.finish()
        self.assertEqual(self.requests, [])
        self.service.observe({"type": "log", "run_id": "r", "channel": 1,
            "message": "[WiFi测试] 通道1 第1轮 5G 第3/4次扫描失败：错误码=123"})
        self.finish()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.store.reports()[0][2]["event"]["channel"], 1)

    def test_old_run_and_resume_does_not_reuse_retry_counts(self):
        self.service.enable_monitor(True)
        self.service.observe({"type": "diagnostic_start", "run_id": "r"})
        for attempt in (1, 2):
            self.service.observe({"type": "log", "run_id": "r", "channel": 1,
                "message": f"[WiFi测试] 通道1 第1轮 5G 第{attempt}/4次扫描失败：失败"})
        self.service.observe({"type": "channel_started", "run_id": "r", "channel": 1, "attempt": 1})
        self.service.observe({"type": "log", "run_id": "r", "channel": 1, "attempt": 1,
            "message": "[WiFi测试] 通道1 第1轮 5G 第1/4次扫描失败：失败"})
        self.service.observe({"type": "channel_result", "run_id": "old", "channel": 1, "ok": False})
        self.finish()
        self.assertEqual(self.requests, [])

    def test_new_batch_requires_rearming_monitor(self):
        self.service.enable_monitor(True)
        for run in ("r1", "r2"):
            self.service.observe({"type": "diagnostic_start", "run_id": run})
            self.service.observe({"type": "diagnostic_end", "run_id": run})
        self.finish()
        self.assertFalse(self.service.trigger.enabled)

    def test_missing_key_still_preserves_local_snapshot(self):
        changed = self.store.save_profile(replace(self.profile, base_url="https://another.example"))
        self.service.configure(changed, (TARGET,))
        self.service.submit("分析异常", 1)
        self.finish()
        self.assertEqual(self.requests, [])
        self.assertEqual(len(self.store.reports()), 1)

    def test_case_confirmation_preserves_device_credentials_and_filters_only_model_key(self):
        cause = "test-key 驱动异常 " + json.dumps(DIAGNOSTIC_MATERIAL, ensure_ascii=False)
        self.service.confirm_case("r", "WiFi失败", cause, "更新驱动", "复测通过", "Windows11")
        saved = self.store.cases("WiFi")[0]["cause"]
        self.assertNotIn("test-key", saved)
        self.assertIn(json.dumps(DIAGNOSTIC_MATERIAL, ensure_ascii=False), saved)
        knowledge = self.service._knowledge("WiFi")
        self.assertIn("test-password", knowledge)
        self.assertNotIn("test-key", knowledge)

    def test_split_serial_preserves_device_password_and_filters_model_key_after_joining(self):
        self.service.observe_serial("vlan101", Mock(port="COM1", direction="RX", text="password=split-"))
        self.service.observe_serial("vlan101", Mock(port="COM1", direction="RX", text="secret\nmodel=test-"))
        self.service.observe_serial("vlan101", Mock(port="COM1", direction="RX", text="key\nnext line\n"))
        context = self.service.trigger.context(1)
        self.assertIn("password=split-secret", context)
        self.assertNotIn("test-key", context)
        self.assertIn("next line", context)

    def test_operator_device_action_cancels_ai_and_waits_for_active_transport_cleanup(self):
        self.service.executors["test"] = Mock(transport=Mock())
        self.assertFalse(self.service.prepare_device_action())
        self.service.executors.clear()
        self.assertTrue(self.service.prepare_device_action())

    def test_snapshots_keep_real_addresses_mask_and_subnet_relationship(self):
        tool = DiagnosticToolExecutor(TARGET, threading.Event(), Mock(), self.store,
                                     self.service.redactor, Mock(), Mock())
        with patch("src.services.ai_debug_service.os.name", "posix"):
            result = json.loads(tool.pc_environment())
        self.assertTrue(result["configured_same_subnet"])
        self.assertEqual(result["configured_dut"], TARGET.host)
        self.assertEqual(result["configured_source"], TARGET.bind_ip)
        self.assertEqual(result["configured_subnet_mask"], TARGET.subnet_mask)

    def test_manual_material_survives_request_report_notifications_and_main_log(self):
        material = json.dumps(DIAGNOSTIC_MATERIAL, ensure_ascii=False)
        self.service.serial_read = lambda _t: material
        self.service.submit(material + " test-key", 1, "question")
        self.finish()
        session = self.requests[0][2]
        payload = session.request.call_args.kwargs["json"]
        content = json.loads(payload["messages"][1]["content"])
        self.assertIn(material, content["question"])
        self.assertEqual(content["snapshot"][1]["evidence"], material)
        report = self.store.reports()[0][2]
        self.assertIn(material, report["question"])
        self.assertEqual(json.loads(report["evidence"].split("\n", 1)[0])[1]["evidence"], material)
        self.assertNotIn("test-key", json.dumps(report))
        notifications = []
        while not self.service.updates.empty():
            notifications.append(self.service.updates.get_nowait())
        self.assertIn(material, next(p[1]["question"] for kind, p in notifications if kind == "report"))
        self.service.emit(material + " test-key")
        self.assertIn(material, self.output[-1])
        self.assertNotIn("test-key", "\n".join(self.output))
        self.assertTrue(any("真实诊断信息（含材料中的账号、密码）" in line and self.profile.base_url in line
                            for line in self.output))

    def test_automatic_monitor_sends_real_context_and_device_credentials(self):
        self.service.enable_monitor(True)
        self.service.observe({"type": "diagnostic_start", "run_id": "r"})
        material = json.dumps(DIAGNOSTIC_MATERIAL, ensure_ascii=False)
        self.service.observe({"type": "log", "run_id": "r", "channel": 1, "message": material})
        self.service.observe({"type": "channel_result", "run_id": "r", "channel": 1, "ok": False})
        self.finish()
        payload = self.requests[0][2].request.call_args.kwargs["json"]
        content = json.loads(payload["messages"][1]["content"])
        self.assertIn(material, content["recent_log"])
        self.assertIn(material, self.store.reports()[0][2]["evidence"])

    def test_temporary_report_fields_survive_model_error(self):
        self.service.client_factory = Mock(side_effect=ValueError("offline error"))
        self.service.submit("分析失败", 1)
        self.finish()
        self.assertEqual(self.store.reports()[0][2]["status"], "失败")

    def test_service_does_not_hold_tk_objects_for_worker_thread_collection(self):
        self.assertFalse(any(isinstance(value, tk.Misc) for value in self.service.__dict__.values()))


class UiTests(unittest.TestCase):
    def setUp(self):
        gc.collect()
        self.temp = tempfile.TemporaryDirectory()
        self.store = DiagnosticStore(self.temp.name, FakeCipher())
        self.service = Mock()
        self.service.store = self.store
        self.service.profile = None
        self.service.trigger.policy = DebugTriggerPolicy()
        self.service.trigger.enabled = False
        self.service.updates = __import__("queue").Queue()
        self.root = tk.Tk()
        self.root.withdraw()
        self.dialog = AiDiagnosticsWindow(self.root, self.service, lambda: (TARGET,))
        self.dialog.open()

    def tearDown(self):
        if self.dialog._poll_id:
            self.root.after_cancel(self.dialog._poll_id)
        self.root.update_idletasks()
        if self.dialog.window is not None:
            self.dialog.window.destroy()
        self.root.destroy()
        self.store.close()
        self.temp.cleanup()
        self.dialog = self.service = self.root = None
        gc.collect()

    def test_vendor_and_model_are_separate_and_custom_model_is_editable(self):
        self.assertEqual(tuple(self.dialog.profile_choice["values"]), ())
        self.assertEqual(str(self.dialog.model_choice["state"]), "normal")
        self.dialog.vars["provider"].set("MiniMax")
        self.dialog._provider_changed()
        self.assertEqual(self.dialog.vars["protocol"].get(), "chat_completions")
        self.assertEqual(self.dialog.vars["base_url"].get(), "https://api.minimax.io/v1")
        self.dialog.vars["provider"].set("OpenAI")
        self.dialog._provider_changed()
        self.assertEqual(self.dialog.vars["protocol"].get(), "responses")

    def test_report_selection_formats_nested_evidence_without_changing_saved_report(self):
        evidence = [{"tool": "read_pc_environment", "evidence": json.dumps({
            "netsh wlan show interfaces": "系统上有 1 个接口：\r\n名称：VLAN101"}, ensure_ascii=False)}]
        payload = {"report": "已观察事实：正文正常", "evidence": json.dumps(evidence, ensure_ascii=False) + "\n串口现场"}
        self.store.save_report("readable", payload)
        self.dialog.reports_panel.open()
        shown = self.dialog.reports_panel.output.get("1.0", "end-1c")
        self.assertIn("已观察事实：正文正常\n\n本地证据：\n[1] read_pc_environment", shown)
        self.assertIn("系统上有 1 个接口：\r\n名称：VLAN101", shown)
        self.assertTrue(shown.endswith("\n串口现场"))
        self.assertEqual(self.store.reports()[0][2], payload)
        self.assertEqual(str(self.dialog.reports_panel.output["state"]), "disabled")

    def test_legacy_plain_report_evidence_remains_visible(self):
        self.store.save_report("legacy", {"report": "旧报告", "evidence": "绯荤粺涓婃湁\n原始日志"})
        self.dialog.reports_panel.open()
        self.assertTrue(self.dialog.reports_panel.output.get("1.0", "end-1c").endswith("绯荤粺涓婃湁\n原始日志"))

    def test_real_report_values_are_visible_and_old_aliases_remain_unchanged(self):
        material = json.dumps(DIAGNOSTIC_MATERIAL, ensure_ascii=False)
        self.store.save_report("real", {"report": material, "evidence": "历史占位符 <IP_1>"})
        self.dialog.reports_panel.open()
        shown = self.dialog.reports_panel.output.get("1.0", "end-1c")
        self.assertIn(material, shown)
        self.assertIn("历史占位符 <IP_1>", shown)

    def test_monitor_confirmation_names_real_material_and_recipient(self):
        self.service.profile = ProviderProfile()
        self.dialog.monitor_panel.enabled.set(True)
        with patch("src.ui.ai_monitor_window.messagebox.askyesno", return_value=False) as confirm:
            self.dialog.monitor_panel.changed()
        text = confirm.call_args.args[1]
        self.assertIn("真实诊断信息（含材料中的账号、密码）", text)
        self.assertIn(self.service.profile.provider, text)
        self.assertIn(self.service.profile.base_url, text)
        self.service.enable_monitor.assert_not_called()

    def test_profile_round_trip_preserves_each_provider_and_never_shows_key(self):
        self.dialog.vars["name"].set("DeepSeek账号")
        self.dialog.vars["model"].set("deepseek-test")
        self.dialog.vars["key"].set("test-secret")
        first = self.dialog._save()
        self.dialog._new_profile()
        self.dialog.vars["name"].set("MiniMax账号")
        self.dialog.vars["provider"].set("MiniMax")
        self.dialog._provider_changed()
        self.dialog.vars["model"].set("minimax-test")
        self.dialog.vars["key"].set("other-secret")
        second = self.dialog._save()
        self.dialog._reload_profiles(first.id)
        self.assertEqual(self.dialog.vars["model"].get(), "deepseek-test")
        self.assertEqual(self.dialog.vars["key"].get(), "")
        self.assertEqual(self.store.key(second), "other-secret")

    def test_native_checkbuttons_default_monitor_off_and_threshold_three(self):
        self.dialog.monitor_panel.open()
        widgets = []
        def visit(parent):
            for child in parent.winfo_children():
                widgets.append(child)
                visit(child)
        visit(self.dialog.window)
        self.assertGreaterEqual(sum(w.winfo_class() == "Checkbutton" for w in widgets), 6)
        self.assertFalse(any(w.winfo_class() == "TCheckbutton" for w in widgets))
        self.assertFalse(self.dialog.monitor_panel.enabled.get())
        self.assertEqual(self.dialog.monitor_panel.threshold.get(), "3")

    def test_background_matches_test_item_configuration_including_all_tabs_and_native_checks(self):
        self.dialog.monitor_panel.open()
        self.dialog.reports_panel.open()
        from line_check_assistant.app import COLOR_BG
        self.assertEqual(self.dialog.window.cget("background"), COLOR_BG)
        style = __import__("tkinter.ttk", fromlist=["Style"]).Style(self.root)
        def verify(parent):
            for child in parent.winfo_children():
                kind = child.winfo_class()
                if kind in ("TFrame", "TLabel", "TNotebook"):
                    self.assertEqual(style.lookup(child.cget("style"), "background"), COLOR_BG)
                elif kind == "Checkbutton":
                    self.assertEqual(child.cget("background"), COLOR_BG)
                    self.assertEqual(child.cget("activebackground"), COLOR_BG)
                verify(child)
        verify(self.dialog.window)

    def test_module_theme_preserves_global_styles_status_color_and_checkbox_semantics(self):
        from tkinter import ttk
        from src.ui.module_theme import apply_module_theme
        style = ttk.Style(self.root)
        style.configure("Alert.TLabel", foreground="red", background="white")
        window = tk.Toplevel(self.root)
        flag = tk.BooleanVar(window, value=True)
        label = ttk.Label(window, text="错误", style="Alert.TLabel")
        label.pack()
        check = tk.Checkbutton(window, text="选项", variable=flag)
        check.pack()
        try:
            apply_module_theme(window)
            self.assertEqual(style.lookup("Alert.TLabel", "background"), "white")
            self.assertEqual(style.lookup(label.cget("style"), "foreground"), "red")
            self.assertTrue(flag.get())
            check.invoke()
            self.assertFalse(flag.get())
        finally:
            window.destroy()

    def test_vendor_selection_restores_saved_model_and_keeps_separate_credentials(self):
        first = self.store.save_profile(ProviderProfile(provider="DeepSeek", model="deepseek-test"), "first")
        second = self.store.save_profile(ProviderProfile(provider="MiniMax", model="minimax-test", base_url="https://api.minimax.io/v1"), "second")
        self.dialog._reload_profiles(first.id)
        self.dialog.vars["provider"].set("MiniMax")
        self.dialog._provider_changed()
        self.assertEqual(self.dialog.profile.id, second.id)
        self.assertEqual(self.dialog.vars["model"].get(), "minimax-test")
        self.dialog.vars["provider"].set("DeepSeek")
        self.dialog._provider_changed()
        self.assertEqual(self.dialog.profile.id, first.id)
        self.assertEqual(self.store.key(first), "first")
        self.assertEqual(self.store.key(second), "second")

    def test_ai_window_remains_non_modal_and_hide_does_not_destroy(self):
        self.assertIsNone(self.dialog.window.grab_current())
        self.dialog.hide()
        self.assertTrue(self.dialog.window.winfo_exists())
        self.dialog.open()
        self.assertTrue(self.dialog.window.winfo_exists())

    def test_cancelled_ui_request_cannot_open_serial_later(self):
        bridge = AiSerialBridge(Mock(), Mock(), Mock())
        future = __import__("concurrent.futures", fromlist=["Future"]).Future()
        action = Mock()
        future.cancel()
        bridge.requests.put((future, action, None))
        bridge.poll()
        action.assert_not_called()


if __name__ == "__main__":
    unittest.main()
