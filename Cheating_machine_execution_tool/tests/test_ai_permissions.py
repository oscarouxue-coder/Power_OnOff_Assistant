"""三档权限离线回归；危险命令全部Mock，不访问真实模型或DUT。"""
from dataclasses import asdict, replace
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.models.ai_permissions import ASK, AUTO, FULL, normalize_permission
from src.models.ai_actions import ActionAssessment
from src.services.ai_permission_service import AiPermissionService
import test_ai_actions as action_fixture
import test_ai_conversation as conversation_fixture
import test_ai_chat_presentation as presentation_fixture
from test_ai_core import chat, call


class PermissionActionsTests(unittest.TestCase):
    execute = action_fixture.ActionServiceTests.execute
    wait = action_fixture.ActionServiceTests.wait
    start_pending = action_fixture.ActionServiceTests.start_pending
    decide = action_fixture.ActionServiceTests.decide

    def setUp(self):
        action_fixture.ActionServiceTests.setUp(self)
        self.owner.lock = threading.RLock()
        self.owner.executors = {}
        self.owner.shutdown = threading.Event()
        self.owner.permissions = AiPermissionService(self.owner)
        self.owner.permissions.initialize("chat", new=True)

    def select(self, mode):
        running = self.owner.running.pop("chat")
        try:
            self.owner.permissions.select("chat", mode, confirmed=mode == FULL)
        finally:
            self.owner.running["chat"] = running

    @patch("src.services.ai_action_service.run_local_command")
    def test_ask_ordinary_waits_for_specific_approval(self, run):
        self.select(ASK)
        run.return_value = {"status": "completed", "exit_code": 0, "process_cleanup_confirmed": True}
        thread, action = self.start_pending()
        run.assert_not_called()
        self.assertEqual(action["permission_mode"], ASK)
        self.decide(action)
        thread.join(3)
        run.assert_called_once()

    def test_ask_temporary_change_waits_even_on_existing_connection(self):
        self.select(ASK)
        self.executor.transport = Mock()
        thread, action = self.start_pending("kernel_debug", {})
        self.executor.execute.assert_not_called()
        self.decide(action, False)
        thread.join(3)

    def test_ask_file_write_rejection_preserves_file(self):
        self.select(ASK)
        path = Path(self.temp) / "fixture.txt"
        path.write_text("before", encoding="utf-8")
        thread, action = self.start_pending("write_local_file", {"path": str(path), "content": "after"})
        self.decide(action, False)
        thread.join(3)
        self.assertEqual(path.read_text(encoding="utf-8"), "before")

    def test_readonly_remains_direct_in_all_modes(self):
        path = Path(self.temp) / "fixture.txt"
        path.write_text("only evidence", encoding="utf-8")
        for mode in (ASK, AUTO, FULL):
            self.select(mode)
            self.assertEqual(self.execute("read_local_file", {"path": str(path)})["text"], "only evidence")
            self.executor.transport = Mock()
            self.execute("read_dut_state", {"category": "system"})
        self.review.assert_not_called()
        self.assertEqual(self.store.actions("chat"), [])

    @patch("src.services.ai_action_service.run_local_command")
    def test_full_dangerous_command_skips_review_and_logs_grant(self, run):
        self.select(FULL)
        run.return_value = {"status": "completed", "exit_code": 0, "process_cleanup_confirmed": True}
        self.review.side_effect = AssertionError("不得调用独立审查")
        result = self.execute(params={"command": "Restart-Computer"})
        self.assertEqual(result["action_state"], "succeeded")
        run.assert_called_once()
        self.review.assert_not_called()
        action = self.store.actions("chat")[0]
        self.assertEqual(action["review_status"], "skipped_full_access")
        self.assertEqual(action["authorization_source"], "session_grant")
        self.assertTrue(action["authorization_id"])
        self.assertIsNone(action["assessment"])
        self.assertIn("已跳过独立审查", str(self.owner.emit.call_args_list))

    def test_full_first_login_is_automatic(self):
        self.select(FULL)
        self.execute("read_dut_state", {"category": "system"})
        self.executor.execute.assert_called_once()
        self.review.assert_not_called()
        self.assertIsNone(self.service.pending("chat"))

    @patch("src.services.ai_action_service.run_local_command")
    def test_revoked_full_grant_cannot_dispatch_prepared_action(self, run):
        self.select(FULL)
        prepare = self.service._prepare
        def revoke(*args):
            action = prepare(*args)
            self.owner.permissions.revoke("chat", "目标授权撤销")
            return action
        with patch.object(self.service, "_prepare", side_effect=revoke):
            with self.assertRaises(InterruptedError):
                self.execute(params={"command": "Restart-Computer"})
        run.assert_not_called()

    def test_full_write_preserves_version_guard(self):
        self.select(FULL)
        path = Path(self.temp) / "fixture.txt"
        path.write_text("before", encoding="utf-8")
        from src.core.ai_local_executor import write_local_file
        def changed(**kwargs):
            path.write_text("operator edit", encoding="utf-8")
            return write_local_file(**kwargs)
        with patch("src.services.ai_action_service.write_local_file", side_effect=changed):
            result = self.execute("write_local_file", {"path": str(path), "content": "after"})
        self.assertIn("已变化", result["error"])
        self.assertEqual(path.read_text(encoding="utf-8"), "operator edit")
        self.review.assert_not_called()

    def test_full_busy_and_secret_guards(self):
        self.select(FULL)
        self.owner.diagnostic.busy.return_value = True
        with self.assertRaisesRegex(ValueError, "抢占"):
            self.execute("run_dut_command", {"command": "reboot"})
        with self.assertRaisesRegex(ValueError, "API密钥"):
            self.execute(params={"command": "echo model-secret"})
        self.executor._connection.assert_not_called()

    def test_full_unknown_result_retry_still_requires_approval(self):
        self.select(FULL)
        connection = self.executor.transport = Mock(kind="Telnet")
        connection.command.side_effect = RuntimeError("连接中断")
        self.executor._connection.return_value = connection
        self.assertEqual(self.execute("run_dut_command", {"command": "reboot"})["action_state"], "unknown")
        thread, action = self.start_pending("run_dut_command", {"command": "reboot"})
        self.decide(action, False)
        thread.join(3)
        connection.command.assert_called_once()

    def test_stop_revokes_grant_but_keeps_preference(self):
        self.select(FULL)
        self.service.invalidate("chat", "停止本轮")
        self.assertEqual(self.owner.permissions.status("chat")["mode"], AUTO)
        self.assertEqual(self.store.setting("chat_permission_mode"), FULL)
        self.assertEqual(self.owner.permissions.grants, {})
        restarted = AiPermissionService(self.owner)
        restarted.initialize("chat")
        self.assertEqual(restarted.status("chat")["mode"], AUTO)
        self.assertIn("重新选择并确认", self.owner.message.call_args.args[2])

    def test_busy_confirmation_and_invalid_mode_rejected(self):
        for mode, confirmed in ((FULL, False), (ASK, False), ("unknown", True)):
            with self.assertRaises(ValueError):
                self.owner.permissions.select("chat", mode, confirmed)
        self.assertEqual(self.owner.permissions.status("chat")["mode"], AUTO)

    def test_grant_binding_and_runtime_eligibility_revoke(self):
        for key, value in (("target", {"channel": 2}), ("profile", {"model": "other"}), ("run_id", "new")):
            self.select(FULL)
            original = self.store.chat("chat")[key]
            self.store.update_chat("chat", **{key: value})
            self.assertEqual(self.owner.permissions.status("chat")["mode"], AUTO)
            self.store.update_chat("chat", **{key: original})
        self.select(FULL)
        self.eligible = False
        self.assertEqual(self.owner.permissions.status("chat")["mode"], AUTO)

    def test_restart_does_not_restore_full_grant(self):
        self.select(FULL)
        restarted = AiPermissionService(self.owner)
        restarted.initialize("chat")
        self.assertEqual(restarted.status("chat")["mode"], AUTO)
        self.assertEqual(restarted.grants, {})
        self.assertEqual(self.store.setting("chat_permission_mode"), FULL)
        self.assertEqual(normalize_permission({"invalid": True}), AUTO)


class PermissionConversationTests(unittest.TestCase):
    setUp = conversation_fixture.ConversationTests.setUp
    stop_services = conversation_fixture.ConversationTests.stop_services
    send = conversation_fixture.ConversationTests.send

    def test_preference_and_sessions_are_separate(self):
        self.service.permissions.select(self.id, ASK)
        second = self.service.create_session(self.diag.targets[1], self.profile)
        self.assertEqual(self.service.permissions.status(second)["mode"], ASK)
        self.service.permissions.select(second, FULL, confirmed=True)
        self.assertEqual(self.service.permissions.status(self.id)["mode"], ASK)
        third = self.service.create_session(self.diag.targets[1], self.profile)
        self.assertEqual(self.service.permissions.status(third)["mode"], AUTO)
        self.assertIn("重新选择并确认", self.store.chat_items(third)[-1]["text"])

    def test_full_runtime_and_no_review_in_both_protocols(self):
        for protocol in ("chat_completions", "responses"):
            changed = self.store.save_profile(replace(self.profile, protocol=protocol))
            from src.services.ai_store import profile_fingerprint
            self.profile = replace(changed, capability="可自动诊断", tested_fingerprint=profile_fingerprint(changed))
            self.store.save_profile(self.profile)
            self.id = self.service.create_session(self.diag.targets[1], self.profile)
            self.service.permissions.select(self.id, FULL, confirmed=True)
            if protocol == "responses":
                self.responses.extend([
                    {"output": [{"type": "function_call", "call_id": "full-1", "name": "run_local_command", "arguments": '{"command":"Restart-Computer"}'}]},
                    {"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "结果已获得"}]}]},
                ])
            else:
                self.responses.extend([chat("", [call("run_local_command", '{"command":"Restart-Computer"}')]), chat("结果已获得")])
            count = len(self.requests)
            with patch("src.services.ai_action_service.run_local_command", return_value={
                    "status": "completed", "exit_code": 0, "process_cleanup_confirmed": True}) as run:
                self.assertEqual(self.send("重启系统")["status"], "可继续")
                run.assert_called_once()
            self.assertEqual(len(self.requests) - count, 2)
            field = "messages" if protocol == "chat_completions" else "input"
            instructions = self.requests[-1][field][0]["content"]
            self.assertIn('"permission_mode": "full_access"', instructions)
            self.assertIn('"full_access": true', instructions)
            self.assertFalse(any("独立风险审查请求" in log for log in self.logs))

    def test_new_batch_and_stop_revoke_full_access(self):
        self.service.permissions.select(self.id, FULL, confirmed=True)
        self.service.stop(self.id)
        self.assertEqual(self.service.permissions.status(self.id)["mode"], AUTO)
        self.service.permissions.select(self.id, FULL, confirmed=True)
        self.service.on_run("run2")
        self.assertEqual(self.service.permissions.grants, {})

    def test_delete_forgets_grant_without_changing_other_session(self):
        self.service.permissions.select(self.id, FULL, confirmed=True)
        second = self.service.create_session(self.diag.targets[1], self.profile)
        self.service.delete_sessions([self.id])
        self.assertEqual(self.service.permissions.grants, {})
        self.assertEqual(self.service.permissions.status(second)["mode"], AUTO)


class PermissionControlTests(unittest.TestCase):
    setUp = presentation_fixture.ChatPresentationTests.setUp
    tearDown = presentation_fixture.ChatPresentationTests.tearDown

    def test_full_confirmation_cancel_and_confirm(self):
        from test_ai_debug import TARGET
        self.session["target"] = asdict(TARGET)
        control = self.panel.permission_control
        control.choice.set("完全访问")
        with patch("src.ui.ai_permission_control.messagebox.askyesno", return_value=False) as confirm:
            control.select()
        self.service.permissions.select.assert_not_called()
        self.assertEqual(control.choice.get(), "帮我批准")
        self.assertIn("恢复出厂", confirm.call_args.args[1])
        self.assertEqual(confirm.call_args.kwargs["default"], "no")
        control.choice.set("完全访问")
        with patch("src.ui.ai_permission_control.messagebox.askyesno", return_value=True):
            control.select()
        self.service.permissions.select.assert_called_once_with("s1", FULL, confirmed=True)

    def test_running_cleanup_and_empty_session_disable_switching(self):
        control = self.panel.permission_control
        for mapping in (self.service.running, self.service.executors):
            mapping["s1"] = Mock()
            control.show("s1")
            self.assertIn("disabled", control.choice.state())
            mapping.clear()
        control.show("s1")
        self.assertIn("readonly", control.choice.state())
        control.show("")
        self.assertIn("disabled", control.choice.state())

    def test_session_modes_display_without_changing_preference(self):
        control = self.panel.permission_control
        for mode, label in ((ASK, "请求批准"), (AUTO, "帮我批准"), (FULL, "完全访问")):
            self.service.permissions.status.return_value = {"mode": mode}
            control.show("s1")
            self.assertEqual(control.choice.get(), label)
        self.service.permissions.select.assert_not_called()
