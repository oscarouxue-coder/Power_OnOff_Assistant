"""监控独立三档授权；临时SQLite、离线模型和Mock危险操作。"""
from dataclasses import replace
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_ai_integration as integration
import test_ai_workspace as workspace
from test_ai_core import FakeResponse, chat, call
from test_ai_debug import TARGET
from src.core.ai_client import DiagnosticModelClient
from src.models.ai_actions import ActionAssessment, action_fingerprint
from src.models.ai_diagnostics import DiagnosticJob, DebugTriggerPolicy, MonitorStatus
from src.models.ai_permissions import ASK, AUTO, FULL, PERMISSION_LABELS
from src.services.ai_monitor_service import AiMonitorService
from src.services.ai_store import profile_fingerprint
from src.services.ai_trigger_service import DiagnosticTrigger
from src.ui.ai_monitor_status import monitor_presentation


class MonitorActionTests(unittest.TestCase):
    setUp = integration.ServiceTests.setUp
    stop_service = integration.ServiceTests.stop_service
    finish = integration.ServiceTests.finish

    def arm(self, mode=AUTO, targets=(TARGET,)):
        self.service.run_id, self.service.run_active = "run", True
        self.monitor = self.service.monitor
        self.monitor.apply(self.profile, targets, DebugTriggerPolicy(channels=tuple(t.channel for t in targets)),
                           mode, True, confirmed=mode == FULL)
        self.monitor.review = Mock(return_value=ActionAssessment("ordinary", "本次目标的只读检查"))

    def start(self, target=TARGET):
        self.stop = threading.Event()
        self.job = DiagnosticJob(uuid.uuid4().hex, self.profile, target, "诊断并修复", "run")
        self.store.save_report(self.job.id, {"status": "处理中"})
        self.executor = Mock(transport=None, recovery_state="无临时修改", used=2)
        self.executor.execute.return_value = {"evidence": "查询结果"}
        self.executor._connection.return_value.command.return_value = "shell output"
        self.identifier = self.monitor.start(self.job, self.stop, self.executor)
        self.addCleanup(self.cleanup_context, self.identifier)

    def cleanup_context(self, identifier):
        self.stop.set()
        self.monitor.finish(identifier)

    def execute(self, name="run_local_command", params=None):
        return self.monitor.execute(self.identifier, name, params if params is not None else {"command": "Get-Date"},
                                    self.stop, self.executor)

    def pending_thread(self, name="run_local_command", params=None):
        output = []
        def execute():
            try:
                output.append(self.execute(name, params))
            except InterruptedError:
                output.append("cancelled")
        thread = threading.Thread(target=execute)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(self.stop.set)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            pending = self.monitor.pending()
            if pending is not None:
                return thread, output, pending
            time.sleep(.01)
        self.fail("未进入待批准状态")

    def decide(self, pending, approved=True):
        self.monitor.actions.decide(self.identifier, pending["id"], pending["fingerprint"], approved)

    @patch("src.services.ai_action_service.run_local_command")
    def test_auto_ordinary_reviews_and_never_creates_chat(self, run):
        self.arm()
        self.start()
        run.return_value = {"status": "completed", "exit_code": 0, "process_cleanup_confirmed": True}
        result = self.execute()
        self.assertEqual(result["action_state"], "succeeded")
        self.monitor.review.assert_called_once()
        action = self.store.actions(self.identifier)[0]
        self.assertEqual(action["source"], "monitor")
        self.assertEqual(action["report_id"], self.job.id)
        self.assertEqual(action_fingerprint(action), action["fingerprint"])
        self.assertEqual(self.store.chats(), [])
        self.assertEqual(self.store.setting("chat_permission_mode", ASK), ASK)

    @patch("src.services.ai_action_service.run_local_command")
    def test_ask_waits_for_button_and_approval_dispatches_once(self, run):
        self.arm(ASK)
        self.start()
        run.return_value = {"status": "completed", "exit_code": 0, "process_cleanup_confirmed": True}
        thread, output, pending = self.pending_thread()
        run.assert_not_called()
        self.assertEqual(self.service.monitor_status().waiting_approval, 1)
        self.assertIn("待批准", monitor_presentation(MonitorStatus(True, running=1, waiting_approval=1))[0])
        self.decide(pending)
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(output[0]["action_state"], "succeeded")
        run.assert_called_once()
        with self.assertRaises(ValueError):
            self.decide(pending)

    @patch("src.services.ai_action_service.run_local_command")
    def test_review_failure_waits_and_rejection_never_dispatches(self, run):
        self.arm()
        self.start()
        self.monitor.review.side_effect = RuntimeError("offline")
        thread, output, pending = self.pending_thread()
        self.assertEqual(pending["assessment"]["risk"], "unknown")
        self.assertEqual(pending["review_status"], "failed")
        self.decide(pending, False)
        thread.join(3)
        run.assert_not_called()
        self.assertEqual(output[0]["status"], "rejected_or_cancelled")

    @patch("src.services.ai_action_service.run_local_command")
    def test_full_dangerous_skips_review_with_monitor_grant(self, run):
        self.arm(FULL)
        self.start()
        run.return_value = {"status": "completed", "exit_code": 0, "process_cleanup_confirmed": True}
        self.assertEqual(self.execute(params={"command": "Restart-Computer"})["action_state"], "succeeded")
        self.monitor.review.assert_not_called()
        action = self.store.actions(self.identifier)[0]
        self.assertEqual(action["authorization_source"], "monitor_grant")
        self.assertEqual(action["authorization_id"], self.monitor.grant["id"])
        self.assertEqual(action["review_status"], "skipped_full_access")
        run.assert_called_once()

    def test_first_login_in_auto_needs_approval_full_does_not(self):
        self.arm()
        self.start()
        thread, output, pending = self.pending_thread("read_dut_state", {"category": "system"})
        self.executor.execute.assert_not_called()
        self.decide(pending)
        thread.join(3)
        self.executor.execute.assert_called_once()
        self.monitor.finish(self.identifier)
        self.arm(FULL)
        self.start()
        self.execute("read_dut_state", {"category": "system"})
        self.executor.execute.assert_called_once()
        self.monitor.review.assert_not_called()

    def test_ask_temporary_change_waits_on_existing_connection(self):
        self.arm(ASK)
        self.start()
        self.executor.transport = Mock()
        thread, _, pending = self.pending_thread("kernel_debug", {})
        self.executor.execute.assert_not_called()
        self.decide(pending, False)
        thread.join(3)

    def test_stop_wakes_approval_and_revokes_full_preference_retained(self):
        self.arm(ASK)
        self.start()
        thread, output, pending = self.pending_thread()
        self.service.enable_monitor(False)
        thread.join(3)
        self.assertTrue(output == ["cancelled"] or output[0].get("status") == "rejected_or_cancelled")
        self.assertEqual(self.store.action(pending["id"])["state"], "cancelled")
        self.monitor.finish(self.identifier)
        self.arm(FULL)
        self.start()
        self.service.enable_monitor(False)
        self.assertIsNone(self.monitor.grant)
        self.assertEqual(self.monitor.mode, AUTO)
        self.assertEqual(self.store.setting("monitor_permission_mode"), FULL)

    @patch("src.services.ai_action_service.run_local_command")
    def test_full_unknown_retry_across_jobs_still_needs_approval(self, run):
        self.arm(FULL)
        self.start()
        run.return_value = {"status": "timeout", "exit_code": None, "process_cleanup_confirmed": True}
        self.assertEqual(self.execute()["action_state"], "unknown")
        old_identifier = self.identifier
        self.monitor.finish(self.identifier)
        self.start()
        self.assertEqual(self.identifier, old_identifier)
        thread, _, pending = self.pending_thread()
        self.assertIn("重试须重新批准", pending["assessment"]["reason"])
        self.assertEqual(run.call_count, 1)
        self.decide(pending, False)
        thread.join(3)
        self.assertEqual(run.call_count, 1)

    @patch("src.services.ai_action_service.run_local_command")
    def test_busy_blocks_generic_modification_even_with_full_access(self, run):
        self.arm(FULL)
        self.start()
        self.service.shared_busy = lambda _: True
        self.assertEqual(self.execute()["status"], "skipped")
        run.assert_not_called()
        with self.assertRaises(ValueError):
            self.execute("run_dut_command", {"command": "id", "host": "other"})

    def test_readonly_file_direct_and_write_version_guard_survives(self):
        self.arm(ASK)
        self.start()
        path = Path(self.temp.name) / "file.txt"
        path.write_text("before", encoding="utf-8")
        self.assertEqual(self.execute("read_local_file", {"path": str(path)})["text"], "before")
        self.monitor.review.assert_not_called()
        thread, _, pending = self.pending_thread("write_local_file", {"path": str(path), "content": "after"})
        path.write_text("external", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.decide(pending)
        thread.join(3)
        self.assertEqual(path.read_text(encoding="utf-8"), "external")

    @patch("src.services.ai_action_service.run_local_command")
    def test_resource_change_during_review_prevents_dispatch(self, run):
        self.arm()
        self.start()
        def review(*_args):
            self.service.shared_busy = lambda _: True
            return ActionAssessment("ordinary", "查询")
        self.monitor.review.side_effect = review
        result = self.execute()
        self.assertFalse(result["dispatched"])
        self.assertIn("占用", result["error"])
        run.assert_not_called()

    def test_busy_apply_and_invalid_full_leave_settings_unchanged(self):
        self.arm()
        self.start()
        before = self.store.setting("trigger_policy")
        with self.assertRaises(ValueError):
            self.monitor.apply(self.profile, (TARGET,), DebugTriggerPolicy(channels=(1,), threshold=7), FULL, True, True)
        self.assertEqual(self.store.setting("trigger_policy"), before)
        self.assertEqual(self.monitor.mode, AUTO)
        self.monitor.finish(self.identifier)
        with self.assertRaises(ValueError):
            self.monitor.apply(self.profile, (TARGET,), DebugTriggerPolicy(channels=(1,)), FULL, True)
        self.assertEqual(self.monitor.mode, AUTO)

    def test_target_model_and_batch_changes_revoke(self):
        for change in ("target", "model", "batch"):
            with self.subTest(change=change):
                self.arm(FULL)
                self.start()
                if change == "target":
                    self.service.configure(self.profile, (replace(TARGET, host="192.168.1.2"),))
                elif change == "model":
                    self.store.save_profile(replace(self.profile, model="changed"))
                    self.assertFalse(self.monitor.status(self.identifier)["enabled"])
                    self.store.save_profile(self.profile)
                else:
                    self.service.run_id = "new-run"
                    self.assertFalse(self.monitor.status(self.identifier)["enabled"])
                self.assertIsNone(self.monitor.grant)
                self.assertEqual(self.monitor.mode, AUTO)
                self.monitor.finish(self.identifier)

    def test_restart_cancels_approved_and_marks_executing_unknown(self):
        self.arm(FULL)
        self.start()
        action = self.monitor.actions._prepare(self.identifier, "run_local_command", {"command": "Get-Date"})
        self.store.change_action(action["id"], ("reviewing",), "executing")
        restored = AiMonitorService(self.service)
        self.assertEqual(restored.mode, AUTO)
        self.assertIsNone(restored.grant)
        self.assertEqual(self.store.action(action["id"])["state"], "unknown")
        self.assertEqual(self.store.chats(), [])

    def test_multi_channel_scopes_are_separate_and_stale_fingerprint_rejected(self):
        other = replace(TARGET, channel=2, vlan="VLAN102", port="COM2")
        self.arm(ASK, (TARGET, other))
        self.start()
        first = self.identifier
        thread, _, pending = self.pending_thread()
        with self.assertRaises(ValueError):
            self.monitor.actions.decide(first, pending["id"], "old", True)
        self.decide(pending, False)
        thread.join(3)
        self.monitor.finish(first)
        self.start(other)
        self.assertNotEqual(self.identifier, first)
        self.assertEqual(self.store.actions(self.identifier), [])

    def test_network_probe_uses_target_batch_settings(self):
        self.arm()
        self.start()
        context = Mock()
        context.target_settings.return_value = {"wifi_wireless_card_name": "wifi"}
        self.service.conversation = Mock(context=context)
        self.addCleanup(setattr, self.service, "conversation", None)
        with patch("src.services.ai_monitor_service.probe_connectivity", return_value={"ok": True}) as probe:
            self.execute("probe_connectivity", {"path": "wireless"})
        context.target_settings.assert_called_once_with("run", 1)
        self.assertEqual(probe.call_args.args[1], {"wifi_wireless_card_name": "wifi"})

    def test_independent_review_uses_verified_model_and_no_tools(self):
        self.arm()
        self.start()
        session = Mock()
        session.request.return_value = FakeResponse(chat('{"risk":"ordinary","reason":"本次只读查询"}'))
        self.service.client_factory = lambda profile, key, redactor: DiagnosticModelClient(profile, key, redactor, session)
        action = self.monitor.actions._prepare(self.identifier, "run_local_command", {"command": "Get-Date"})
        assessment = AiMonitorService.review(self.monitor, self.identifier, action, self.stop)
        self.assertEqual(assessment.risk, "ordinary")
        payload = session.request.call_args.kwargs["json"]
        self.assertNotIn("tools", payload)
        self.assertIn("独立的操作风险审查员", payload["messages"][0]["content"])
        self.assertIn("诊断本次目标通道", payload["messages"][1]["content"])

    def test_legacy_deep_disabled_no_longer_limits_monitor_tools(self):
        from src.models.ai_diagnostics import DiagnosticEvent
        trigger = DiagnosticTrigger(DebugTriggerPolicy(channels=(1,), deep_enabled=False))
        trigger.enabled = True
        trigger.start("run")
        decision = trigger.observe(DiagnosticEvent("run", 1, "test", "failed", "failed"))
        self.assertEqual(decision.level, "deep")
        names = {tool["name"] for tool in self.service.monitor.tools()}
        self.assertTrue({"run_local_command", "write_local_file", "run_dut_command", "kernel_debug"} <= names)
        self.assertNotIn("ask_user", names)


class MonitorProtocolTests(unittest.TestCase):
    setUp = integration.ServiceTests.setUp
    stop_service = integration.ServiceTests.stop_service
    finish = integration.ServiceTests.finish

    def test_pre_batch_full_binds_first_run_and_new_batch_revokes(self):
        self.service.monitor.apply(self.profile, (TARGET,), DebugTriggerPolicy(channels=(1,)), FULL, True, True)
        grant = self.service.monitor.grant["id"]
        self.assertIsNone(self.service.monitor.bound_run)
        self.service.observe({"type": "diagnostic_start", "run_id": "first"})
        self.finish()
        self.assertEqual(self.service.monitor.bound_run, "first")
        report_id = self.service.submit("诊断", 1, automatic=True)
        self.finish()
        self.assertEqual(self.store.report(report_id)["permission_mode"], FULL)
        self.assertEqual(self.service.monitor.grant["id"], grant)
        self.service.observe({"type": "diagnostic_end", "run_id": "first"})
        self.service.observe({"type": "diagnostic_start", "run_id": "second"})
        self.finish()
        self.assertFalse(self.service.trigger.enabled)
        self.assertEqual(self.service.monitor.mode, AUTO)
        self.assertIsNone(self.service.monitor.grant)

    @patch("src.services.ai_action_service.run_local_command")
    def test_background_pending_cancel_does_not_dispatch_or_touch_chat(self, run):
        self.service.run_id, self.service.run_active = "run", True
        self.service.monitor.apply(self.profile, (TARGET,), DebugTriggerPolicy(channels=(1,)), ASK, True)
        self.service.monitor.review = Mock(return_value=ActionAssessment("ordinary", "查询"))
        session = Mock()
        session.request.return_value = FakeResponse(chat("", [call("run_local_command", '{"command":"Get-Date"}')]))
        self.service.client_factory = lambda profile, key, redactor: DiagnosticModelClient(profile, key, redactor, session)
        report_id = self.service.submit("本次异常", 1, automatic=True)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and self.service.monitor_status().waiting_approval == 0:
            time.sleep(.01)
        self.assertEqual(self.service.monitor_status().waiting_approval, 1)
        pending = self.service.monitor.pending()
        self.service.enable_monitor(False)
        self.finish()
        run.assert_not_called()
        self.assertEqual(self.store.action(pending["id"])["state"], "cancelled")
        self.assertEqual(self.store.report(report_id)["status"], "已取消")
        self.assertEqual(self.service.monitor_status().waiting_approval, 0)
        self.assertEqual(self.store.chats(), [])

    @patch("src.services.ai_action_service.run_local_command")
    def test_full_monitor_tool_execution_both_protocols_and_report(self, run):
        for protocol in ("chat_completions", "responses"):
            with self.subTest(protocol=protocol):
                profile = self.store.save_profile(replace(self.profile, protocol=protocol))
                self.profile = replace(profile, capability="可自动诊断", tested_fingerprint=profile_fingerprint(profile))
                self.store.save_profile(self.profile)
                self.service.run_id, self.service.run_active = "run-" + protocol, True
                self.service.monitor.apply(self.profile, (TARGET,), DebugTriggerPolicy(channels=(1,), deep_enabled=False), FULL, True, True)
                session = Mock()
                if protocol == "responses":
                    responses = [
                        {"output": [{"type": "function_call", "call_id": "op", "name": "run_local_command", "arguments": '{"command":"Get-Date"}'}]},
                        {"output": [{"type": "message", "content": [{"type": "output_text", "text": "已执行查询，修复和恢复仍待验证"}]}]},
                    ]
                else:
                    responses = [chat("", [call("run_local_command", '{"command":"Get-Date"}')]), chat("已执行查询，修复和恢复仍待验证")]
                session.request.side_effect = [FakeResponse(value) for value in responses]
                self.service.client_factory = lambda profile, key, redactor: DiagnosticModelClient(profile, key, redactor, session)
                run.reset_mock()
                run.return_value = {"status": "completed", "exit_code": 0, "process_cleanup_confirmed": True}
                report_id = self.service.submit("本次网络异常", 1, automatic=True)
                self.finish()
                run.assert_called_once()
                self.assertEqual(session.request.call_count, 2)
                request = session.request.call_args_list[0].kwargs["json"]
                text = json.dumps(request, ensure_ascii=False)
                self.assertIn('permission_mode', text)
                self.assertIn('full_access', text)
                self.assertIn('run_local_command', text)
                report = self.store.report(report_id)
                self.assertEqual(report["status"], "完成")
                self.assertEqual(report["permission_mode"], FULL)
                self.assertIn("待验证", report["report"])
                self.assertEqual(self.store.chats(), [])
                self.assertEqual(self.service.monitor_status().waiting_approval, 0)


class MonitorUiTests(unittest.TestCase):
    setUp = workspace.WorkspaceTests.setUp
    close_ui = workspace.WorkspaceTests.close_ui
    stop_services = workspace.WorkspaceTests.stop_services

    def test_dropdown_replaces_checkbox_and_permission_is_independent(self):
        panel = self.dialog.monitor_panel
        panel.open()
        self.assertEqual(tuple(panel.permission_choice["values"]), tuple(PERMISSION_LABELS.values()))
        self.assertEqual(panel.permission.get(), "帮我批准")
        panel.permission.set("请求批准")
        panel._permission_selected()
        panel.update_status()
        self.assertEqual(panel.permission.get(), "请求批准")
        panel.enabled.set(True)
        with patch("src.ui.ai_monitor_window.messagebox.askyesno", return_value=True):
            panel.changed()
        self.assertEqual(self.diag.monitor.mode, ASK)
        self.assertNotEqual(self.store.setting("chat_permission_mode"), ASK)

    def test_full_cancel_keeps_active_mode_and_confirmation_contains_scope(self):
        panel = self.dialog.monitor_panel
        panel.open()
        panel.permission.set("完全访问")
        panel.enabled.set(True)
        with patch("src.ui.ai_monitor_window.messagebox.askyesno", return_value=False) as confirm:
            panel.changed()
        self.assertEqual(self.diag.monitor.mode, AUTO)
        self.assertEqual(panel.permission.get(), "帮我批准")
        text = confirm.call_args.args[1]
        for expected in ("通道1", "恢复出厂", "供电控制", "独立模型风险审查", "真实诊断信息"):
            self.assertIn(expected, text)
        self.assertEqual(confirm.call_args.kwargs["default"], "no")
        self.assertFalse(self.diag.trigger.enabled)

    def test_pending_disables_dropdown_without_new_fixed_button(self):
        panel = self.dialog.monitor_panel
        panel.open()
        panel.update_status(MonitorStatus(True, True, running=1, waiting_approval=1))
        self.assertEqual(str(panel.permission_choice["state"]), "disabled")
        self.assertIn("点击此处", panel.status.get())
        self.assertEqual(str(panel.status_label.cget("cursor")), "hand2")
        self.assertIsNone(panel.approval.button)
        panel.update_status(MonitorStatus())
        self.assertEqual(str(panel.permission_choice["state"]), "readonly")

    def test_pending_click_opens_nonmodal_detail_and_rejection_is_specific(self):
        self.diag.run_id, self.diag.run_active = "run1", True
        self.diag.monitor.apply(self.profile, (TARGET,), DebugTriggerPolicy(channels=(1,)), ASK, True)
        job = DiagnosticJob(uuid.uuid4().hex, self.profile, TARGET, "诊断异常", "run1")
        self.store.save_report(job.id, {"status": "处理中"})
        stop = threading.Event()
        identifier = self.diag.monitor.start(job, stop, Mock())
        self.addCleanup(self.diag.monitor.finish, identifier)
        action = self.diag.monitor.actions._prepare(identifier, "run_local_command", {"command": "Get-Date"})
        self.store.change_action(action["id"], ("reviewing",), "waiting_approval",
                                 assessment={"risk": "ordinary", "reason": "查询"})
        panel = self.dialog.monitor_panel
        panel.open_pending()
        self.root.update_idletasks()
        self.assertTrue(panel.approval.window.winfo_exists())
        self.assertIsNone(panel.approval.window.grab_current())
        self.assertIn("Get-Date", panel.approval.detail.get("1.0", "end-1c"))
        panel.approval.reject_button.invoke()
        self.assertIsNone(panel.approval.window)
        self.assertEqual(self.store.action(action["id"])["state"], "rejected")

    def test_deleted_model_revokes_idle_full_monitor(self):
        panel = self.dialog.monitor_panel
        panel.open()
        panel.permission.set("完全访问")
        panel.enabled.set(True)
        with patch("src.ui.ai_monitor_window.messagebox.askyesno", return_value=True):
            panel.changed()
        self.assertEqual(self.diag.monitor.mode, FULL)
        with patch("src.ui.ai_diagnostics_window.messagebox.askyesno", return_value=True):
            self.dialog._delete_profile()
        self.assertFalse(self.diag.trigger.enabled)
        self.assertEqual(self.diag.monitor.mode, AUTO)
        self.assertIsNone(self.diag.monitor.grant)


if __name__ == "__main__":
    unittest.main()
