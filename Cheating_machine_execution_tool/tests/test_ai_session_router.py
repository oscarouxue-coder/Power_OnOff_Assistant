"""对话路由专项：临时数据库、隔离模型与设备，无真实命令下发。"""
from collections import deque
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_ai_conversation as fixture
from test_ai_core import chat, call
from test_ai_debug import TARGET
from src.models.ai_session_scope import target_label
from src.services.ai_conversation_service import conversation_tools
from src.services.ai_pc_conversation import PcConversationExecutor
from src.services.ai_store import profile_fingerprint
from src.ui.ai_diagnostics_window import AiDiagnosticsWindow


class RouterTests(unittest.TestCase):
    setUp = fixture.ConversationTests.setUp
    stop_services = fixture.ConversationTests.stop_services

    def decision(self, scope="device", channel=1, intent="continue", question="问题", clarification=""):
        self.route_replies = deque([chat(json.dumps(dict(scope=scope, channel=channel, intent=intent,
            question=question, clarification=clarification), ensure_ascii=False))])

    def route(self, text, **kwargs):
        result = self.service.router.send(text, self.diag.profile, **kwargs)
        self.service.jobs.join()
        return result["identifier"]

    def test_switch_reuses_latest_matching_target_and_preserves_history(self):
        second = replace(TARGET, channel=2, port="COM102")
        self.diag.configure(self.profile, (TARGET, second))
        first = self.route("通道1 检查断网")
        other = self.route("通道2 检查串口")
        self.assertNotEqual(first, other)
        self.assertEqual(first, self.route("切回通道1"))
        self.assertEqual(asdict(TARGET), self.store.chat(first)["target"])
        self.assertTrue(self.store.chat_items(other))

    def test_natural_language_com_port_resolves_and_preserves_user_text(self):
        self.diag.configure(self.profile, (TARGET, replace(TARGET, channel=2, port="COM102")))
        self.decision(channel=2, intent="switch", question="模型改写不能成为执行目标")
        identifier = self.route("改查COM102对应的设备，核对故障")
        items = self.store.chat_items(identifier)
        self.assertIn("改查COM102对应的设备，核对故障", [m["text"] for m in items if m["role"] == "user"])
        self.assertEqual(self.store.chat(identifier)["target"]["channel"], 2)

    def test_explicit_new_creates_separate_session(self):
        self.service.router.select(self.id)
        other = self.route("新会话", fresh=True)
        self.assertNotEqual(self.id, other)
        self.assertEqual(self.store.chat(other)["target"], asdict(TARGET))

    def test_general_question_with_no_targets_uses_no_tools_or_dut_executor(self):
        self.diag.configure(self.profile, ())
        self.decision("general", None, "continue", "你是谁")
        factory = Mock(side_effect=AssertionError("不得创建设备执行器"))
        self.diag.tool_factory = factory
        identifier = self.route("你是谁")
        self.assertIsNone(self.store.chat(identifier)["target"])
        self.assertEqual(self.store.chat(identifier)["scope"], "general")
        self.assertNotIn("tools", self.requests[-1])
        factory.assert_not_called()

    def test_pc_session_is_independent_and_tools_exclude_device(self):
        self.diag.configure(self.profile, ())
        self.decision("pc", None, "switch", "检查电脑网络")
        identifier = self.route("只查本机电脑网络")
        names = {t["function"]["name"] for t in self.requests[-1]["tools"]}
        self.assertIn("read_pc_environment", names)
        self.assertIn("run_local_command", names)
        self.assertNotIn("run_dut_command", names)
        self.assertNotIn("read_serial_status", names)
        self.assertNotIn("probe_connectivity", names)
        self.assertTrue(self.service.collection_status(identifier)["enabled"])
        self.assertEqual(target_label(self.store.chat(identifier)), "本机电脑")

    def test_pc_device_call_rejected_in_execution_service(self):
        identifier = self.service.create_session(None, self.profile, scope="pc")
        with self.assertRaisesRegex(ValueError, "范围"):
            self.service.actions.execute(identifier, "run_dut_command", {"command": "reboot"},
                None, threading.Event(), Mock(), Mock())

    def test_pc_busy_prevents_local_generic_operation(self):
        identifier = self.service.create_session(None, self.profile, scope="pc")
        self.diag.busy = lambda _: True
        with self.assertRaisesRegex(ValueError, "共享资源"):
            self.service.actions.execute(identifier, "run_local_command", {"command": "example"},
                None, threading.Event(), Mock(), Mock())

    def test_pc_snapshot_has_no_fake_device_identity(self):
        executor = PcConversationExecutor(threading.Event(), self.logs.append)
        with patch("src.services.ai_pc_conversation.read_network_state", return_value={"observed": True}):
            result = executor.execute("read_pc_environment", {})
        self.assertNotIn("channel", result)
        self.assertNotIn("configured_dut", result)
        self.assertIn("route", result)

    def test_ambiguous_target_asks_without_collecting(self):
        self.diag.configure(self.profile, (TARGET, replace(TARGET, channel=2)))
        self.decision(channel=None, intent="clarify", question="", clarification="该管理IP对应通道1、2，请明确通道。")
        identifier = self.route("检查192.168.1.1")
        self.assertEqual(self.store.chat(identifier)["scope"], "general")
        self.assertIn("明确通道", self.store.chat_items(identifier)[-1]["text"])
        self.assertEqual(len(self.requests), 1)

    def test_clarification_carries_only_user_description_to_device(self):
        self.decision(channel=None, intent="clarify", question="", clarification="哪个通道？")
        general = self.route("WAN偶尔断开")
        identifier = self.route("通道1 继续检查")
        self.assertNotEqual(identifier, general)
        evidence = self.store.chat_evidence(identifier)
        self.assertTrue(any(e["source"] == "用户目标澄清对话" and "WAN" in e["text"] for e in evidence))

    def test_mention_of_other_channel_keeps_current(self):
        self.diag.configure(self.profile, (TARGET, replace(TARGET, channel=2)))
        self.decision(channel=1, intent="continue")
        self.assertEqual(self.id, self.route("通道2正常，只继续查当前设备", selected=self.id))

    def test_bare_target_answer_resumes_original_problem_once(self):
        self.decision(channel=None, intent="clarify", question="", clarification="哪个通道？")
        general = self.route("WAN偶尔断开")
        identifier = self.route("通道1")
        users = [m["text"] for m in self.store.chat_items(identifier) if m["role"] == "user"]
        self.assertEqual(len(users), 1)
        self.assertIn("WAN偶尔断开", users[0])
        self.assertIsNone(self.store.chat(general).get("routing_pending"))

    def test_implicit_remote_followup_after_target_change_gets_current_snapshot(self):
        source = dict(kind="dingtalk", sender="a")
        first = self.route("通道1 检查", source=source)
        changed = replace(TARGET, port="COM999")
        self.diag.configure(self.profile, (changed,))
        self.decision(channel=1, intent="continue")
        second = self.route("继续排查", source=source)
        self.assertNotEqual(first, second)
        self.assertEqual(self.store.chat(second)["target"], asdict(changed))

    def test_unknown_channel_never_falls_back_to_first(self):
        identifier = self.route("通道99 检查")
        self.assertEqual(self.store.chat(identifier)["scope"], "general")
        self.assertFalse(self.store.chat(identifier)["target"])

    def test_changed_configuration_during_resolution_does_not_create_or_send(self):
        original = self.service.router._resolve
        def resolve(*args):
            result = original(*args)
            self.diag.configure(self.profile, (replace(TARGET, port="COM999"),))
            return result
        before = len(self.store.chats())
        with patch.object(self.service.router, "_resolve", side_effect=resolve):
            with self.assertRaisesRegex(ValueError, "识别期间"):
                self.route("通道1 检查")
        self.assertEqual(len(self.store.chats()), before)
        self.assertFalse(self.service.running)

    def test_disabled_entry_cancels_before_session_creation(self):
        with self.assertRaises(InterruptedError):
            self.route("通道1 检查", guard=lambda: False)
        self.assertFalse(self.service.running)

    def test_invalid_model_route_never_sends_old_target(self):
        self.route_replies = deque([chat("不是JSON")])
        with self.assertRaises(ValueError):
            self.route("改查另一台", selected=self.id)
        self.assertFalse(self.service.running)
        self.assertFalse(any(m["role"] == "user" for m in self.store.chat_items(self.id)))

    def test_model_cannot_execute_tools_during_route(self):
        self.route_replies = deque([chat("", [call("run_local_command", '{"command":"forbidden"}')])])
        with self.assertRaisesRegex(ValueError, "不允许调用工具"):
            self.route("切换目标", selected=self.id)
        self.assertFalse(self.service.running)

    def test_source_identity_never_reuses_other_members_or_platforms(self):
        ids = []
        for source in (dict(kind="local"), dict(kind="dingtalk", sender="a"),
                       dict(kind="feishu", sender="a", chat_type="group"),
                       dict(kind="feishu", sender="a", chat_type="p2p"),
                       dict(kind="feishu", sender="b", chat_type="group")):
            ids.append(self.route("通道1 检查", source=source))
        self.assertEqual(len(set(ids)), 5)

    def test_queued_switch_does_not_stop_previous_session(self):
        self.diag.configure(self.profile, (TARGET, replace(TARGET, channel=2)))
        old_stop = threading.Event()
        self.service.running[self.id] = old_stop
        self.addCleanup(lambda: self.service.running.pop(self.id, None))
        with self.diag.operation_lock:
            result = self.service.router.send("通道2 检查", self.profile, selected=self.id)
            self.assertFalse(old_stop.is_set())
            self.assertEqual(self.store.chat(result["identifier"])["status"], "排队中")
        self.service.jobs.join()

    def test_selected_historical_session_stays_material_only(self):
        self.store.update_chat(self.id, run_id="old")
        self.decision(channel=1, intent="continue")
        self.assertEqual(self.route("分析旧报告", selected=self.id), self.id)
        self.assertFalse(self.service.authorized(self.id))
        self.assertEqual(self.store.chat(self.id)["run_id"], "old")

    def test_router_shutdown_cancels_and_idle_tracks_recognition(self):
        stop = threading.Event()
        self.service.router.active[("test",)] = stop
        self.assertFalse(self.service.idle)
        self.service.router.cancel()
        self.assertTrue(stop.is_set())
        self.service.router.active.clear()

    def test_scope_participates_in_authorization_binding(self):
        identifier = self.service.create_session(None, self.profile, scope="pc")
        first = self.service.permissions._binding(self.store.chat(identifier))
        self.store.update_chat(identifier, scope="general")
        self.assertNotEqual(first, self.service.permissions._binding(self.store.chat(identifier)))

    def test_scope_tools_work_for_both_protocols(self):
        for protocol in ("chat_completions", "responses"):
            profile = replace(self.profile, protocol=protocol)
            profile = replace(profile, tested_fingerprint=profile_fingerprint(profile))
            self.store.save_profile(profile)
            self.diag.configure(profile, ())
            # 工具范围定义与协议编码无关；两协议均通过真实client发送。
            identifier = self.service.create_session(None, profile, scope="general")
            if protocol == "responses":
                self.responses.append({"output": [{"type": "message", "role": "assistant", "content": [
                    {"type": "output_text", "text": "普通问答回复"}]}]})
            self.service.send(identifier, "普通问答")
            self.service.jobs.join()
            self.assertEqual(self.store.chat(identifier)["status"], "可继续")
            self.assertEqual(conversation_tools(True, True, "general"), [])

    def test_first_send_refresh_does_not_invalidate_route_or_keep_sent_draft(self):
        root = tk.Tk()
        root.withdraw()
        dialog = AiDiagnosticsWindow(root, self.diag, lambda: (TARGET,), conversation=self.service)
        entered, release = threading.Event(), threading.Event()
        original = self.service.send
        def paused(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("测试同步超时")
            original(*args, **kwargs)
        try:
            dialog.open()
            panel = dialog.chat_panel
            self.assertFalse(panel.selected)
            with patch.object(self.service, "send", side_effect=paused):
                panel.input.insert("1.0", "通道1 检查断网")
                panel.send()
                deadline = time.monotonic() + 2
                while not entered.is_set() and time.monotonic() < deadline:
                    root.update()
                    time.sleep(.005)
                self.assertTrue(entered.wait(2))
                generation = panel.route_generation
                panel.poll()
                self.assertEqual(panel.route_generation, generation)
                release.set()
                fixture.wait_panel(panel, self.service)
            self.assertEqual(panel.selected, self.id)
            self.assertEqual(panel.input.get("1.0", "end-1c"), "")
        finally:
            release.set()
            if dialog._poll_id:
                root.after_cancel(dialog._poll_id)
            dialog.window.destroy()
            root.destroy()

    def test_route_json_protocol_supports_responses(self):
        from src.core.ai_client import DiagnosticModelClient
        from src.utils.ai_redaction import DiagnosticRedactor
        profile = replace(self.profile, protocol="responses")
        profile = replace(profile, tested_fingerprint=profile_fingerprint(profile))
        self.store.save_profile(profile)
        self.diag.configure(profile, (TARGET,))
        http = Mock()
        reply = dict(scope="pc", channel=None, intent="switch", question="", clarification="")
        from test_ai_core import FakeResponse
        http.request.return_value = FakeResponse({"output": [{"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": json.dumps(reply)}]}]})
        self.diag.client_factory = lambda p, k, r: DiagnosticModelClient(p, k, r, http)
        identifier = self.route("切到本机电脑")
        self.assertEqual(self.store.chat(identifier)["scope"], "pc")
        request = http.request.call_args.kwargs["json"]
        self.assertIn("input", request)
        self.assertNotIn("tools", request)
