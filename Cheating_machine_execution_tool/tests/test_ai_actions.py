"""完整工具离线回归：临时文件/数据库和本机无害子进程，不连接真实DUT/云端。"""
from dataclasses import asdict, replace
import gc
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.ai_local_executor import run_local_command, read_local_file, write_preview, write_local_file
from src.core.ai_serial_diagnostics import read_serial_status
from src.models.ai_actions import ActionAssessment, normalize_action, action_fingerprint, action_tool_schemas
from src.models.ai_diagnostics import ProviderProfile
from src.services.ai_action_service import AiActionService
from src.services.ai_store import DiagnosticStore, profile_fingerprint
from src.services.ai_debug_service import DiagnosticToolExecutor, tool_schemas
from src.ui.ai_action_approval import AiActionApproval
from src.ui.ai_serial_bridge import AiSerialBridge
from src.ui.serial_terminal import SerialTerminalWindow
from src.core.ai_debug_transport import DiagnosticTransport, DebugConnectionUnavailable
from src.core.serial_transport import SerialSessionManager
from src.utils.ai_redaction import DiagnosticRedactor
from test_ai_core import FakeCipher, chat, call
from test_ai_debug import TARGET
import test_ai_conversation as conversation_fixture


class ActionModelsTests(unittest.TestCase):
    def test_only_complete_conversation_exposes_commands(self):
        from src.services.ai_conversation_service import conversation_tools
        names = {s["name"] for s in conversation_tools(True, True)}
        self.assertTrue({s["name"] for s in action_tool_schemas()} <= names)
        self.assertNotIn("run_local_command", {s["name"] for s in tool_schemas(True)})
        self.assertNotIn("run_dut_command", {s["name"] for s in conversation_tools(False, True)})
        self.assertEqual(conversation_tools(True, False), [])

    def test_target_injection_invalid_timeout_and_parameters_are_rejected(self):
        for params in ({"command": "id", "host": "other"}, {"command": "id", "timeout_seconds": True},
                       {"command": "id", "timeout_seconds": 1801}, {"command": "\x00"}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                normalize_action("run_dut_command", params)
        self.assertEqual(normalize_action("run_local_command", {"command": "Get-Date"})["timeout_seconds"], 60)
        self.assertEqual(normalize_action("run_dut_command", {"command": "id", "timeout_seconds": 1800})["timeout_seconds"], 1800)

    def test_review_is_strict_and_does_not_extract_json_from_instructions(self):
        self.assertEqual(ActionAssessment.parse('{"risk":"ordinary","reason":"读取版本"}').risk, "ordinary")
        for value in ('safe', '```json\n{"risk":"ordinary","reason":"ok"}\n```',
                      '{"risk":"ordinary","reason":"ok","approved":true}', '{"risk":"ordinary","reason":""}'):
            with self.assertRaises(ValueError):
                ActionAssessment.parse(value)


class ActionServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.temp = temporary.name
        self.addCleanup(temporary.cleanup)
        self.store = DiagnosticStore(self.temp, FakeCipher())
        self.addCleanup(self.store.close)
        self.profile = ProviderProfile(model="offline")
        self.store.create_chat({"id": "chat", "created": "2026-11-12", "run_id": "run", "target": asdict(TARGET),
                                "profile": asdict(self.profile), "status": "处理中"})
        self.stop = threading.Event()
        self.eligible = True
        self.owner = SimpleNamespace(store=self.store, redactor=DiagnosticRedactor(("model-secret",)),
            emit=Mock(), notify=Mock(), message=Mock(), running={"chat": self.stop},
            diagnostic=SimpleNamespace(busy=Mock(return_value=False)),
            collection_status=lambda _: {"enabled": self.eligible, "reason": "目标或模型已变化"},
            _profile=lambda _: self.profile)
        self.service = AiActionService(self.owner)
        self.executor = Mock(transport=None)
        self.executor.execute.return_value = {"evidence": "fixed query"}
        self.review = Mock(return_value=ActionAssessment("ordinary", "可判断的查询"))
        self.result = []

    def execute(self, name="run_local_command", params=None):
        return self.service.execute("chat", name, {"command": "Get-Date"} if params is None else params, TARGET,
                                    self.stop, self.executor, self.review)

    def wait(self, condition, timeout=3):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            value = condition()
            if value:
                return value
            time.sleep(.01)
        self.fail("后台操作未到达期望状态")

    def start_pending(self, name="run_local_command", params=None):
        def run():
            try:
                self.result.append(self.execute(name, params))
            except Exception as exc:
                self.result.append(exc)
        thread = threading.Thread(target=run)
        thread.start()
        def cleanup():
            self.stop.set()
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.addCleanup(cleanup)
        action = self.wait(lambda: next((a for a in self.store.actions("chat") if a["state"] == "waiting_approval"), None))
        return thread, action

    def decide(self, action, approved=True):
        self.service.decide("chat", action["id"], action["fingerprint"], approved)

    @patch("src.services.ai_action_service.run_local_command")
    def test_ordinary_command_automatically_executes_once_with_real_params(self, run):
        run.return_value = {"status": "completed", "exit_code": 0, "process_cleanup_confirmed": True, "stdout": "real output"}
        result = self.execute()
        self.assertEqual(result["action_state"], "succeeded")
        self.review.assert_called_once()
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["command"], "Get-Date")
        self.assertEqual(self.store.actions("chat")[0]["result"]["stdout"], "real output")

    @patch("src.services.ai_action_service.run_local_command")
    def test_ui_eligibility_check_never_holds_confirmation_lock(self, run):
        def eligible(_):
            self.assertFalse(self.service.lock._is_owned(), "等待Tk的检查不能持有确认锁")
            return {"enabled": True}
        self.owner.collection_status = eligible
        run.return_value = {"status": "completed", "exit_code": 0, "process_cleanup_confirmed": True}
        self.assertEqual(self.execute()["action_state"], "succeeded")
        self.review.return_value = ActionAssessment("unknown", "等待批准")
        thread, action = self.start_pending()
        self.decide(action, False)
        thread.join(3)

    @patch("src.services.ai_action_service.run_local_command")
    def test_dangerous_waits_approval_then_executes_once_and_rejects_duplicate(self, run):
        run.return_value = {"status": "completed", "exit_code": 0, "process_cleanup_confirmed": True}
        thread, action = self.start_pending(params={"command": "Restart-Computer"})
        run.assert_not_called()
        self.decide(action)
        with self.assertRaises(ValueError):
            self.decide(action)
        thread.join(3)
        self.assertFalse(thread.is_alive())
        run.assert_called_once()
        self.assertEqual(self.result[0]["action_state"], "succeeded")

    @patch("src.services.ai_action_service.run_local_command")
    def test_rejected_operation_is_never_dispatched(self, run):
        self.review.return_value = ActionAssessment("unknown", "不明脚本")
        thread, action = self.start_pending()
        self.decide(action, False)
        thread.join(3)
        run.assert_not_called()
        self.assertFalse(self.result[0]["dispatched"])
        self.assertEqual(self.store.action(action["id"])["state"], "rejected")

    @patch("src.services.ai_action_service.run_local_command")
    def test_review_failure_requires_manual_confirmation(self, run):
        self.review.side_effect = ValueError("接口异常 model-secret")
        thread, action = self.start_pending()
        self.assertEqual(action["assessment"]["risk"], "unknown")
        self.assertNotIn("model-secret", self.store.action(action["id"])["assessment"]["reason"])
        self.decide(action, False)
        thread.join(3)
        run.assert_not_called()

    @patch("src.services.ai_action_service.run_local_command")
    def test_blocked_operation_has_no_approval_path(self, run):
        self.review.return_value = ActionAssessment("blocked", "绕过串口占用保护")
        self.assertEqual(self.execute()["action_state"], "blocked")
        run.assert_not_called()
        self.assertIsNone(self.service.pending("chat"))

    @patch("src.services.ai_action_service.run_local_command")
    def test_stop_invalidates_pending_permission(self, run):
        self.review.return_value = ActionAssessment("unknown", "待确认")
        thread, action = self.start_pending()
        self.stop.set()
        self.service.invalidate("chat", "停止本轮")
        thread.join(3)
        run.assert_not_called()
        self.assertEqual(self.store.action(action["id"])["state"], "cancelled")
        with self.assertRaises(ValueError):
            self.decide(action)

    @patch("src.services.ai_action_service.run_local_command")
    def test_changed_target_or_model_revokes_pending_operation(self, run):
        self.review.return_value = ActionAssessment("unknown", "待确认")
        thread, action = self.start_pending()
        self.eligible = False
        thread.join(3)
        self.assertFalse(thread.is_alive())
        run.assert_not_called()
        self.assertEqual(self.store.action(action["id"])["state"], "cancelled")

    @patch("src.services.ai_action_service.run_local_command")
    def test_modified_saved_parameters_cannot_use_old_approval(self, run):
        self.review.return_value = ActionAssessment("unknown", "待确认")
        thread, action = self.start_pending()
        self.store.change_action(action["id"], ("waiting_approval",), "waiting_approval", params={"command": "changed"})
        with self.assertRaisesRegex(ValueError, "变化"):
            self.decide(action)
        thread.join(3)
        run.assert_not_called()

    def test_first_device_login_needs_approval_and_reused_connection_does_not(self):
        thread, action = self.start_pending("read_dut_state", {"category": "system"})
        self.executor.execute.assert_not_called()
        self.assertIn("登录", action["assessment"]["reason"])
        self.decide(action)
        thread.join(3)
        self.executor.execute.assert_called_once_with("read_dut_state", {"category": "system"}, deep=True)
        self.executor.transport = Mock()
        self.execute("read_dut_state", {"category": "system"})
        self.assertEqual(self.executor.execute.call_count, 2)
        self.assertEqual(len(self.store.actions("chat")), 1)

    def test_custom_command_disconnect_never_falls_back_or_repeats(self):
        connection = self.executor.transport = Mock(kind="Telnet")
        connection.command.side_effect = RuntimeError("连接中断")
        self.executor._connection.return_value = connection
        result = self.execute("run_dut_command", {"command": "cat /proc/version"})
        self.assertEqual(result["action_state"], "unknown")
        self.assertTrue(result["dispatched"])
        self.assertIn("待核实", result["notice"])
        connection.command.assert_called_once()
        connection.fallback_serial.assert_not_called()

    def test_uncertain_command_retry_requires_new_approval(self):
        connection = self.executor.transport = Mock(kind="Telnet")
        connection.command.side_effect = RuntimeError("连接中断")
        self.executor._connection.return_value = connection
        self.execute("run_dut_command", {"command": "cat /proc/version"})
        thread, action = self.start_pending("run_dut_command", {"command": "cat /proc/version"})
        self.assertIn("重试", action["assessment"]["reason"])
        self.decide(action, False)
        thread.join(3)
        connection.command.assert_called_once()

    def test_device_busy_does_not_even_open_connection(self):
        self.owner.diagnostic.busy.return_value = True
        with self.assertRaisesRegex(ValueError, "抢占"):
            self.execute("run_dut_command", {"command": "id"})
        self.executor._connection.assert_not_called()

    def test_file_version_changed_before_approval_is_not_overwritten(self):
        path = Path(self.temp) / "file.txt"
        path.write_text("before", encoding="utf-8")
        self.review.return_value = ActionAssessment("dangerous", "覆盖配置")
        thread, action = self.start_pending("write_local_file", {"path": str(path), "content": "after"})
        self.assertIn("before", action["preview"]["diff"])
        path.write_text("operator edit", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "文件版本"):
            self.decide(action)
        thread.join(3)
        self.assertEqual(path.read_text(encoding="utf-8"), "operator edit")

    def test_read_and_write_files_filter_keys_and_record_actual_results(self):
        path = Path(self.temp) / "file.txt"
        result = self.execute("write_local_file", {"path": str(path), "content": "中文内容"})
        self.assertEqual(result["action_state"], "succeeded")
        path.write_text("密码=real-password key=model-secret", encoding="utf-8")
        result = self.execute("read_local_file", {"path": str(path)})
        self.assertIn("real-password", result["text"])
        self.assertNotIn("model-secret", result["text"])
        with self.assertRaisesRegex(ValueError, "API密钥"):
            self.execute("write_local_file", {"path": str(path), "content": "model-secret"})

    def test_restart_invalidates_pending_and_marks_started_operation_uncertain(self):
        for state in ("waiting_approval", "approved", "executing"):
            action = self.service._prepare("chat", "run_local_command", {"command": "Get-Date"})
            self.store.change_action(action["id"], ("reviewing",), state)
        AiActionService(self.owner)
        self.assertEqual([a["state"] for a in self.store.actions("chat")], ["cancelled", "cancelled", "unknown"])

    def test_action_records_deleted_atomically_with_conversation(self):
        self.service._prepare("chat", "run_local_command", {"command": "Get-Date"})
        self.store.delete_chats(["chat"])
        self.assertEqual(self.store.actions("chat"), [])

    @patch("src.services.ai_action_service.read_serial_status")
    def test_serial_status_queries_do_not_acquire_or_open_serial(self, status):
        status.return_value = {"external_owner": "未知"}
        self.assertEqual(self.execute("read_serial_status", {}), {"external_owner": "未知"})
        self.executor._connection.assert_not_called()


@unittest.skipUnless(os.name == "nt", "Windows PowerShell/Job Object专项")
class LocalExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def run_command(self, command, timeout=10, stop=None):
        return run_local_command(command, self.temporary.name, timeout, stop or threading.Event(), Mock())

    def test_chinese_stdout_stderr_working_directory_and_exit_code(self):
        result = self.run_command("Write-Output '中文输出'; [Console]::Error.WriteLine('错误输出'); (Get-Location).Path; exit 7")
        self.assertEqual(result["exit_code"], 7)
        self.assertIn("中文输出", result["stdout"])
        self.assertIn("错误输出", result["stderr"])
        self.assertIn(self.temporary.name, result["stdout"])
        self.assertTrue(result["process_cleanup_confirmed"])

    def test_stop_before_launch_does_not_execute(self):
        stop = threading.Event()
        stop.set()
        with patch("src.core.ai_local_executor.subprocess.Popen") as launch, self.assertRaises(InterruptedError):
            self.run_command("Get-Date", stop=stop)
        launch.assert_not_called()

    def test_timeout_kills_descendant_before_it_can_write_marker(self):
        marker = Path(self.temporary.name) / "child-marker"
        # 静态命令经参数传递；只写临时目录，不修改电脑设置。
        marker_literal = str(marker).replace("'", "''")
        script = "Start-Sleep -Seconds 4; [IO.File]::WriteAllText('" + marker_literal + "','unexpected')"
        import base64
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        result = self.run_command("Start-Process powershell.exe -WindowStyle Hidden -ArgumentList '-NoProfile','-EncodedCommand','" + encoded + "'; Start-Sleep -Seconds 10", timeout=1)
        self.assertEqual(result["status"], "timed_out")
        self.assertTrue(result["process_cleanup_confirmed"])
        time.sleep(4.2)
        self.assertFalse(marker.exists())

    def test_stop_during_execution_cleans_job(self):
        stop = threading.Event()
        timer = threading.Timer(.7, stop.set)
        timer.start()
        try:
            result = self.run_command("Start-Sleep -Seconds 20", stop=stop)
            self.assertEqual(result["status"], "cancelled")
            self.assertTrue(result["process_cleanup_confirmed"])
        finally:
            timer.cancel()

    def test_output_is_bounded_and_truncation_is_reported(self):
        result = self.run_command("[Console]::Write(('x' * 1100000))")
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["stdout"]), 1024 * 1024)


class ActionConversationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = conversation_fixture.ConversationTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_independent_risk_review_and_execution_continue_both_protocols(self):
        f = self.fixture
        for protocol in ("chat_completions", "responses"):
            profile = f.store.save_profile(replace(f.profile, protocol=protocol))
            f.profile = replace(profile, capability="可自动诊断", tested_fingerprint=profile_fingerprint(profile))
            f.store.save_profile(f.profile)
            f.id = f.service.create_session(TARGET, f.profile)
            review = '{"risk":"ordinary","reason":"只读查询时间"}'
            if protocol == "responses":
                f.responses.extend([
                    {"output": [{"type": "function_call", "call_id": "full-1", "name": "run_local_command", "arguments": '{"command":"Get-Date"}'}]},
                    {"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": review}]}], "usage": {"input_tokens": 40, "output_tokens": 9}},
                    {"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "结果已获得"}]}]},
                ])
            else:
                f.responses.extend([chat("", [call("run_local_command", '{"command":"Get-Date"}')]), chat(review), chat("结果已获得")])
            with patch("src.services.ai_action_service.run_local_command", return_value={
                    "status": "completed", "exit_code": 0, "process_cleanup_confirmed": True, "stdout": "实际时间"}) as run:
                self.assertEqual(f.send("查询本机时间")["status"], "可继续")
                run.assert_called_once()
            requests = f.requests[-3:]
            review_payload = requests[1]
            field = "input" if protocol == "responses" else "messages"
            self.assertIn("独立的操作风险审查员", review_payload[field][0]["content"])
            self.assertNotIn("tools", review_payload)
            self.assertIn("实际时间", json.dumps(requests[2], ensure_ascii=False))
            self.assertEqual(f.store.actions(f.id)[0]["state"], "succeeded")
            self.assertTrue(any("独立风险审查请求" in line for line in f.logs))

    def test_stop_while_waiting_approval_completes_protocol_and_does_not_execute(self):
        f = self.fixture
        f.responses.extend([chat("", [call("run_dut_command", '{"command":"reboot"}')]),
                            chat('{"risk":"dangerous","reason":"会重启样机"}')])
        with patch.object(DiagnosticToolExecutor, "_connection") as connection:
            f.service.send(f.id, "重启当前样机")
            end = time.monotonic() + 3
            while time.monotonic() < end and not f.service.actions.pending(f.id):
                time.sleep(.01)
            self.assertIsNotNone(f.service.actions.pending(f.id))
            f.service.stop(f.id)
            f.service.jobs.join()
            connection.assert_not_called()
        self.assertEqual(f.store.chat(f.id)["status"], "已停止")
        self.assertEqual(f.store.actions(f.id)[0]["state"], "cancelled")
        group = f.store.chat_items(f.id, group=True)[-1]
        self.assertTrue(any(m.get("role") == "tool" for m in group))

    def test_review_usage_uses_same_budget_and_keys_are_not_sent_in_material(self):
        f = self.fixture
        f.responses.append(chat('{"risk":"ordinary","reason":"查询"}'))
        f.service.message(f.id, "user", "读取版本")
        assessment = f.service._review_action(f.id, {"command": "echo model-secret"}, f.profile, "model-secret", threading.Event())
        self.assertEqual(assessment.risk, "ordinary")
        self.assertEqual(f.store.chat(f.id)["context_usage"]["request_kind"], "risk_review")
        self.assertNotIn("model-secret", json.dumps(f.requests[-1], ensure_ascii=False))
        self.assertEqual(f.store.chat(f.id)["context_usage"]["state"], "completed")

    def test_new_batch_cancels_pending_action_and_old_approval_is_rejected(self):
        f = self.fixture
        f.responses.extend([chat("", [call("run_dut_command", '{"command":"reboot"}')]),
                            chat('{"risk":"dangerous","reason":"重启"}')])
        with patch.object(DiagnosticToolExecutor, "_connection") as connection:
            f.service.send(f.id, "重启当前样机")
            end = time.monotonic() + 3
            action = None
            while time.monotonic() < end:
                action = f.service.actions.pending(f.id)
                if action:
                    break
                time.sleep(.01)
            self.assertIsNotNone(action)
            f.context.observe({"type": "diagnostic_start", "run_id": "new-run"})
            f.service.on_run("new-run")
            f.service.jobs.join()
            with self.assertRaises(ValueError):
                f.service.actions.decide(f.id, action["id"], action["fingerprint"], True)
            connection.assert_not_called()
        self.assertEqual(f.store.action(action["id"])["state"], "cancelled")

    def test_restarted_service_cancels_saved_approval_without_running_it(self):
        from src.services.ai_conversation_service import AiConversationService
        f = self.fixture
        f.service.begin_close()
        f.service.worker.join(3)
        action = f.service.actions._prepare(f.id, "run_dut_command", {"command": "reboot"})
        f.store.change_action(action["id"], ("reviewing",), "waiting_approval")
        f.store.update_chat(f.id, status="等待操作员批准")
        with patch.object(DiagnosticToolExecutor, "execute") as execute:
            f.service = AiConversationService(f.diag, f.context)
            f.diag.conversation = f.service
            execute.assert_not_called()
        self.assertEqual(f.store.action(action["id"])["state"], "cancelled")
        self.assertEqual(f.store.chat(f.id)["status"], "上次中断，可继续")
        self.assertIsNone(f.service.actions.pending(f.id))


class SerialDiagnosticsTests(unittest.TestCase):
    def test_full_conversation_read_failure_requires_new_login_instead_of_silent_fallback(self):
        transport = Mock(kind="Telnet")
        transport.command.side_effect = DebugConnectionUnavailable("等待超时")
        executor = DiagnosticToolExecutor(TARGET, threading.Event(), Mock(), Mock(), DiagnosticRedactor(), Mock(), Mock())
        executor.transport = transport
        executor.allow_read_fallback = False
        result = executor.execute("read_dut_state", {"category": "system"})
        self.assertIn("确认新连接", result["error"])
        self.assertIsNone(executor.transport)
        transport.fallback_serial.assert_not_called()
        transport.close.assert_called_once()

    def test_bridge_preserves_original_open_error_without_modal_popup(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = Mock()
            manager.acquire_monitor.side_effect = PermissionError("COM3 Access is denied (WinError 5)")
            terminal = SerialTerminalWindow(Mock(), manager, Path(temporary), Path(temporary) / "settings.json")
            terminal.show = Mock()
            terminal.tabs["vlan101"] = {"session": None, "port": "COM3"}
            bridge = AiSerialBridge(terminal, manager, lambda _: False)
            self.addCleanup(bridge.close)
            with patch("src.ui.serial_terminal.messagebox.showerror") as popup:
                with self.assertRaisesRegex(PermissionError, "WinError 5"):
                    bridge.acquire(replace(TARGET, port="COM3"), threading.Event())
                popup.assert_not_called()
            self.assertIn("Access is denied", terminal.last_open_errors["COM3"])

    def test_both_telnet_and_serial_connection_errors_reach_caller(self):
        telnet = Mock(side_effect=TimeoutError("Telnet connection timed out"))
        acquire = Mock(side_effect=PermissionError("COM3 WinError 5"))
        transport = DiagnosticTransport(TARGET, threading.Event(), Mock(), acquire, telnet_factory=telnet)
        with self.assertRaises(DebugConnectionUnavailable) as caught:
            transport.open()
        self.assertIn("Telnet connection timed out", str(caught.exception))
        self.assertIn("COM3 WinError 5", str(caught.exception))
        acquire.assert_called_once()

    def test_internal_snapshot_is_readonly_and_keeps_ownership(self):
        manager = SerialSessionManager()
        manager._owners["COM3"].add("monitor")
        manager._controllers["COM3"] = "upgrade"
        with patch("src.core.serial_transport.PySerialSession") as session:
            result = manager.diagnostic_state("com3")
            self.assertEqual(result["control_owner"], "upgrade")
            self.assertEqual(result["monitor_owners"], ["monitor"])
            self.assertFalse(result["opened_in_program"])
            session.assert_not_called()
        self.assertEqual(manager.control_owner("COM3"), "upgrade")

    @unittest.skipUnless(os.name == "nt", "Windows PnP查询")
    def test_pnp_problem_code_driver_and_missing_port_do_not_infer_external_owner(self):
        pnp = [{"name": "USB Serial Port (COM3)", "problem_code": 10, "driver_version": "1.2.3", "status": "Error"}]
        with patch("serial.tools.list_ports.comports", return_value=[]), patch(
                "src.core.ai_serial_diagnostics.run_local_command", return_value={"status": "completed",
                "exit_code": 0, "truncated": False, "stdout": json.dumps(pnp)}) as query:
            result = read_serial_status(replace(TARGET, port="COM3"), threading.Event(), Mock(), {"control_owner": "upgrade"})
        self.assertFalse(result["enumerated"])
        self.assertEqual(result["pnp"][0]["problem_code"], 10)
        self.assertEqual(result["pnp"][0]["driver_version"], "1.2.3")
        self.assertEqual(result["external_owner"], "未知")
        self.assertIn("Get-CimInstance", query.call_args.args[0])


class ApprovalUiTests(ActionServiceTests):
    # 仅复用fixture，不继承其测试：下面的load_tests在模块底部限制发现。
    def test_approval_window_themes_minimum_layout_session_switch_and_cancel(self):
        root = tk.Tk()
        root.geometry("940x660")
        root.update()
        self.addCleanup(lambda: (root.destroy(), gc.collect()))
        self.review.return_value = ActionAssessment("dangerous", "操作影响需要核对")
        thread, action = self.start_pending()
        for theme in ("vista", "clam"):
            ttk.Style(root).theme_use(theme)
            panel = AiActionApproval(root, SimpleNamespace(actions=self.service), "#eef2f5")
            panel.pack(fill="x")
            panel.show("chat")
            panel.open()
            root.update()
            panel.window.geometry("680x420")
            root.update()
            self.assertEqual(panel.window.cget("background"), "#eef2f5")
            self.assertIn("Get-Date", panel.detail.get("1.0", "end"))
            self.assertTrue(panel.approve_button.winfo_ismapped())
            self.assertLess(panel.reject_button.winfo_rooty() + panel.reject_button.winfo_height(),
                            panel.window.winfo_rooty() + panel.window.winfo_height())
            self.assertIsNone(panel.window.grab_current())
            panel.show("")
            self.assertIsNone(panel.window)
            panel.destroy()
        self.decide(action, False)
        thread.join(3)


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for cls in (ActionModelsTests, ActionServiceTests, LocalExecutorTests, ActionConversationTests, SerialDiagnosticsTests):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    suite.addTest(ApprovalUiTests("test_approval_window_themes_minimum_layout_session_switch_and_cancel"))
    return suite


if __name__ == "__main__":
    unittest.main()
