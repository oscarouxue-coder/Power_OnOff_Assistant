"""多样机离线回归：模型、Ping和设备均隔离，不操作真实网络。"""
from collections import deque
from dataclasses import asdict, replace
import json
import gc
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_ai_conversation as fixture
from test_ai_core import chat, call
from test_ai_debug import TARGET
from src.models.ai_batch import BatchStage, observed_status
from src.models.ai_actions import ActionAssessment
from src.models.ai_session_scope import target_label
from src.services.ai_conversation_service import conversation_tools


def stage(instruction="只读检查", select="all", scope="device", read_only=True, probe="none"):
    return asdict(BatchStage(scope, select, instruction, read_only, probe))


class BatchTests(unittest.TestCase):
    stop_services = fixture.ConversationTests.stop_services

    def setUp(self):
        fixture.ConversationTests.setUp(self)
        self.targets = (TARGET, replace(TARGET, channel=2, port="COM102", bind_ip="192.168.1.22"),
                        replace(TARGET, channel=7, port="COM107", bind_ip="192.168.1.27"))
        self.diag.configure(self.profile, self.targets)
        self.seen = []

    def decision(self, channels=(1, 2, 7), **extra):
        result = dict(intent="switch", scope="batch", channel=None, channels=list(channels),
                      question="检查", clarification="", selection="all")
        result.update(extra)
        self.route_replies = deque([chat(json.dumps(result, ensure_ascii=False))])

    def ping(self, target, settings, path, stop, emit, busy):
        self.seen.append((target.channel, target.bind_ip, path))
        return dict(path=path, result=dict(target_ip=target.host, sent=4, times_ms=[1.2]))

    def route(self, text="3台样机是否都能ping通", **kwargs):
        self.decision()
        result = self.service.router.send(text, self.profile, **kwargs)
        self.service.jobs.join()
        return result["identifier"]

    def test_three_same_ip_targets_ping_with_separate_sources_and_one_parent(self):
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            identifier = self.route()
        session = self.store.chat(identifier)
        self.assertEqual(session["scope"], "batch")
        self.assertEqual([r["status"] for r in session["batch"]["rows"]], ["reachable"] * 3)
        self.assertEqual([c for c, _, _ in self.seen], [1, 2, 7])
        self.assertEqual([ip for _, ip, _ in self.seen], [t.bind_ip for t in self.targets])
        self.assertEqual(len(session["batch_children"]), 3)
        text = "\n".join(m["text"] for m in self.store.chat_items(identifier))
        self.assertIn("【通道7】", text)
        self.assertIn("| 1 | 通道2 | Ping可达 |", text)
        self.assertEqual(conversation_tools(True, True, "batch"), [])
        self.assertIn("7", target_label(session))

    def test_clarification_then_one_by_one_preserves_original_request(self):
        self.route_replies = deque([chat(json.dumps(dict(intent="clarify", scope="device", channel=None,
            question="", clarification="哪个通道？"), ensure_ascii=False))])
        general = self.service.router.send("3台样机是否都能ping通", self.profile)["identifier"]
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            identifier = self.service.router.send("逐台检查", self.profile)["identifier"]
            self.service.jobs.join()
        self.assertIn("ping", self.store.chat(identifier)["batch"]["original"])
        self.assertIsNone(self.store.chat(general)["routing_pending"])
        self.assertEqual(len(self.seen), 3)

    def test_unreachable_continues_and_rechecks_only_failure(self):
        def probe(*args):
            value = self.ping(*args)
            if args[0].channel == 2:
                value["result"]["times_ms"] = []
            return value
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=probe):
            identifier = self.route()
        self.assertEqual([r["status"] for r in self.store.chat(identifier)["batch"]["rows"]],
                         ["reachable", "unreachable", "reachable"])
        self.seen.clear()
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            result = self.service.router.send("只重查失败的", self.profile)
            self.service.jobs.join()
        self.assertEqual(identifier, result["identifier"])
        self.assertEqual([x[0] for x in self.seen], [2])
        with self.assertRaisesRegex(ValueError, "没有符合条件"):
            self.service.router.send("继续剩余", self.profile)

    def test_independent_probe_error_does_not_mark_success_or_stop_next(self):
        def probe(*args):
            if args[0].channel == 2:
                raise ValueError("无法唯一确认目标出口接口")
            return self.ping(*args)
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=probe):
            identifier = self.route()
        self.assertEqual([r["status"] for r in self.store.chat(identifier)["batch"]["rows"]],
                         ["reachable", "failed", "reachable"])

    def test_count_mismatch_and_invalid_channel_dispatch_nothing(self):
        for channels, text in (((1, 99), "都ping一下"), ((1, 1), "都ping一下")):
            self.decision(channels)
            with self.assertRaises(ValueError):
                self.service.router.send(text, self.profile)
        self.assertFalse(self.service.running)
        self.assertFalse(any(s.get("batch_children") for s in self.store.chats()))

    def test_count_mismatch_asks_and_explicit_answer_resumes_original(self):
        self.decision()
        result = self.service.router.send("2台样机ping一下", self.profile)
        self.assertFalse(result["submitted"])
        self.assertFalse(self.service.running)
        self.assertIn("数量", result["notice"])
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            result = self.service.router.send("通道1、2、7", self.profile)
            self.service.jobs.join()
        self.assertTrue(result["submitted"])
        self.assertEqual(len(self.seen), 3)

    def test_model_cannot_dispatch_tools_in_plan(self):
        self.responses.append(chat("", [call("run_local_command", '{"command":"forbidden"}')]))
        identifier = self.route("逐台检查样机状态")
        self.assertEqual(self.store.chat(identifier)["status"], "失败，可继续")
        self.assertFalse(self.store.chat(identifier)["batch_children"])

    def test_stages_check_all_before_failed_only_diagnosis(self):
        self.responses.append(chat(json.dumps(dict(stages=[stage(probe="wired"), stage(select="failed")]))))
        def probe(*args):
            value = self.ping(*args)
            value["result"]["times_ms"] = [] if args[0].channel == 2 else [1]
            return value
        def run(child, *_args):
            self.seen.append(("diagnose", self.store.chat(child)["target"]["channel"]))
            self.service.batch.record_tool(child, "read_pc_environment", {"observed": True})
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=probe), \
             patch.object(self.service, "_run", side_effect=run):
            identifier = self.route("先检查3台ping，不通的再排查")
        self.assertEqual([s[0] for s in self.seen], [1, 2, 7, "diagnose"])
        self.assertEqual(self.seen[-1], ("diagnose", 2))
        self.assertEqual(self.store.chat(identifier)["batch"]["rows"][4]["status"], "completed")

    def test_stop_cancels_remaining_and_continue_uses_only_remaining(self):
        parent = []
        def probe(*args):
            value = self.ping(*args)
            if len(self.seen) == 1:
                self.service.stop(parent[0])
            return value
        self.decision()
        with self.diag.operation_lock:
            parent.append(self.service.router.send("3台样机都ping一下", self.profile)["identifier"])
            with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=probe):
                self.diag.operation_lock.release()
                try:
                    self.service.jobs.join()
                finally:
                    self.diag.operation_lock.acquire()
        self.assertEqual([r["status"] for r in self.store.chat(parent[0])["batch"]["rows"]],
                         ["reachable", "stopped", "stopped"])
        self.seen.clear()
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            self.service.router.send("继续剩下两台", self.profile)
            self.service.jobs.join()
        self.assertEqual([s[0] for s in self.seen], [2, 7], self.logs[-12:])

    def test_changed_config_between_targets_stops_remaining(self):
        def probe(*args):
            value = self.ping(*args)
            self.diag.targets[2] = replace(self.targets[1], port="COM999")
            return value
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=probe):
            identifier = self.route()
        self.assertEqual(len(self.seen), 1)
        self.assertEqual(self.store.chat(identifier)["batch"]["rows"][1]["status"], "pending")
        self.assertEqual(self.store.chat(identifier)["status"], "失败，可继续")

    def test_read_only_stage_filters_mutation_and_execution_guard_blocks_it(self):
        self.responses.extend([chat(json.dumps(dict(stages=[stage()]))),
                               chat("", [call("run_dut_command", '{"command":"reboot"}')]), chat("未执行修改")])
        identifier = self.route("检查3台样机状态")
        child = self.store.chat(identifier)["batch_children"]["1"]
        requests = [r for r in self.requests if r.get("tools")]
        self.assertTrue(requests)
        self.assertNotIn("run_dut_command", [t["function"]["name"] for t in requests[0]["tools"]])
        with self.assertRaisesRegex(ValueError, "只读"):
            self.service.actions.execute(child, "run_dut_command", {"command": "reboot"}, TARGET,
                                         threading.Event(), Mock(), Mock())

    def test_shared_pc_step_runs_once_and_cleanup_failure_pauses(self):
        self.responses.append(chat(json.dumps(dict(stages=[stage(scope="pc", read_only=False), stage()]))))
        seen = []
        def run(child, *_args):
            seen.append(self.store.chat(child)["scope"])
            self.service.batch.record_tool(child, "read_pc_environment", {"observed": True})
            self.store.update_chat(child, batch_cleanup_unconfirmed=True)
        with patch.object(self.service, "_run", side_effect=run):
            identifier = self.route("检查3台，必要时按要求修改本机网络再检查")
        self.assertEqual(seen, ["pc"])
        self.assertIn("已暂停", self.store.chat(identifier)["status"])
        self.assertEqual([r["status"] for r in self.store.chat(identifier)["batch"]["rows"]],
                         ["completed", "pending", "pending", "pending"])
        with self.assertRaisesRegex(ValueError, "清理未确认"):
            self.service.router.send("继续剩余", self.profile)
        self.assertFalse(self.service.router.send("已确认清理完成", self.profile)["submitted"])

    def test_full_access_runs_each_requested_device_operation_once(self):
        self.store.set_setting("chat_permission_mode", "full_access")
        self.responses.append(chat(json.dumps(dict(stages=[stage("按用户要求执行重启", read_only=False)]))))
        self.responses.extend([response for _ in self.targets for response in (
            chat("", [call("run_dut_command", '{"command":"reboot"}')]), chat("已下发，需核对重启结果"))])
        connections = []
        def factory(target, *_args):
            connection = Mock(kind="mock")
            connection.command.return_value = "accepted"
            executor = Mock(recovery_state="无临时修改", transport=None)
            executor._connection.return_value = connection
            connections.append((target.channel, connection))
            return executor
        self.diag.tool_factory = factory
        identifier = self.route("按通道顺序重启3台样机")
        self.assertEqual([c for c, _ in connections], [1, 2, 7])
        self.assertTrue(all(c.command.call_count == 1 for _, c in connections))
        self.assertEqual(len(self.service.batch.actions(identifier)), 3)
        self.assertTrue(all(a["state"] == "succeeded" for a in self.service.batch.actions(identifier)))

    def test_parent_approval_targets_child_and_stop_cancels_whole_batch(self):
        self.store.set_setting("chat_permission_mode", "ask")
        self.responses.extend([chat(json.dumps(dict(stages=[stage("用户要求重启", read_only=False)]))),
                               chat("", [call("run_dut_command", '{"command":"reboot"}')])])
        executor = Mock(recovery_state="无临时修改", transport=None)
        self.diag.tool_factory = Mock(return_value=executor)
        self.decision()
        with patch.object(self.service, "_review_action", return_value=ActionAssessment("dangerous", "用户要求重启")):
            identifier = self.service.router.send("重启3台样机", self.profile)["identifier"]
            deadline = time.monotonic() + 4
            action = None
            while time.monotonic() < deadline:
                action = self.service.actions.pending(identifier)
                if action:
                    break
                time.sleep(.01)
            self.assertIsNotNone(action)
            self.assertNotEqual(action["session_id"], identifier)
            self.assertEqual(action["target"]["channel"], 1)
            from src.services.dingtalk_remote_service import DingTalkRemoteService
            from src.services.feishu_remote_service import FeishuRemoteService
            for platform in (DingTalkRemoteService, FeishuRemoteService):
                remote = SimpleNamespace(lock=threading.RLock(), tokens={}, store=self.store,
                    conversation=self.service, local_only_approvals=set(), identity=lambda _m: ("owner",),
                    reply=Mock(return_value=True), clock=lambda: 0)
                platform._publish_approval(remote, identifier, Mock())
                self.assertEqual(len(remote.tokens), 1)
                self.assertEqual(next(iter(remote.tokens.values()))["session"], action["session_id"])
                self.assertEqual(remote.reply.call_args[0][-1], 1)
                platform._forget_tokens(remote, identifier)
                self.assertFalse(remote.tokens)
            self.service.stop(identifier)
            self.service.jobs.join()
        executor._connection.assert_not_called()
        self.assertEqual(self.store.chat(identifier)["status"], "已停止")
        self.assertTrue(all(r["status"] == "stopped" for r in self.store.chat(identifier)["batch"]["rows"]))
        with self.assertRaises(ValueError):
            self.service.actions.decide(action["session_id"], action["id"], action["fingerprint"], True)

    def test_multiple_human_questions_require_target_and_preserve_others(self):
        self.responses.append(chat(json.dumps(dict(stages=[stage()]))))
        self.responses.extend(chat("", [call("ask_user", json.dumps(dict(question="指示灯状态？", reason="需要人工观察")))]) for _ in self.targets)
        identifier = self.route("检查3台样机指示灯异常")
        with self.assertRaisesRegex(ValueError, "明确通道"):
            self.service.batch.submit(identifier, "绿灯")
        self.responses.append(chat("已记录通道2的人工观察"))
        result = self.service.router.send("通道2 绿灯", self.profile)
        self.service.jobs.join()
        self.assertEqual(result["identifier"], identifier)
        children = self.store.chat(identifier)["batch_children"]
        self.assertIsNone(self.store.chat(children["2"])["pending"])
        self.assertTrue(self.store.chat(children["1"])["pending"])
        self.assertTrue(self.store.chat(children["7"])["pending"])
        self.assertEqual(self.store.chat(identifier)["status"], "等待你回复")

    def test_historical_parent_analysis_has_no_tools(self):
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            identifier = self.route()
        self.store.update_chat(identifier, run_id="historical")
        self.decision(intent="continue")
        result = self.service.router.send("分析旧结果", self.profile, selected=identifier)
        self.service.jobs.join()
        self.assertEqual(result["identifier"], identifier)
        self.assertNotIn("tools", self.requests[-1])
        self.assertEqual(len(self.seen), 3)

    def test_shared_wireless_busy_pauses_without_ping(self):
        self.service.shared_busy = lambda _t: True
        probe = Mock(side_effect=AssertionError("busy must not probe"))
        with patch("src.services.ai_conversation_service.probe_connectivity", probe):
            identifier = self.route("3台样机无线ping是否正常")
        probe.assert_not_called()
        self.assertIn("已暂停", self.store.chat(identifier)["status"])

    def test_batch_parent_has_no_generic_action_executor(self):
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            identifier = self.route()
        with self.assertRaisesRegex(ValueError, "范围"):
            self.service.actions.execute(identifier, "run_local_command", {"command": "reboot"}, None,
                                         threading.Event(), Mock(), Mock())

    def test_child_authorization_invalidated_by_parent_grant_change(self):
        self.store.set_setting("chat_permission_mode", "full_access")
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            identifier = self.route()
        child = self.store.chat(identifier)["batch_children"]["1"]
        self.assertTrue(self.service.collection_status(child)["enabled"])
        self.service.permissions.revoke(identifier, "test invalidation")
        self.assertFalse(self.service.collection_status(child)["enabled"])

    def test_raw_evidence_available_on_parent_with_channel_identity(self):
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            identifier = self.route()
        evidence = self.store.chat_evidence(identifier)
        self.assertEqual({e["channel"] for e in evidence}, {1, 2, 7})
        self.assertTrue(all("通道" in e["source"] for e in evidence))

    def test_plain_inspection_cannot_gain_mutation_tools_from_bad_planner(self):
        self.responses.append(chat(json.dumps(dict(stages=[stage(read_only=False)]))))
        identifier = self.route("检查3台样机状态")
        children = self.store.chat(identifier)["batch_children"].values()
        self.assertTrue(all(self.store.chat(c)["batch_read_only"] for c in children))

    def test_explicit_channel_list_has_no_first_channel_fallback(self):
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            result = self.service.router.send("通道1、2、7 都ping一下", self.profile)
            self.service.jobs.join()
        self.assertEqual(self.store.chat(result["identifier"])["scope"], "batch")
        self.assertEqual([s[0] for s in self.seen], [1, 2, 7])

    def test_resume_does_not_replay_completed_stage(self):
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            identifier = self.route()
        batch = dict(original="修改3台配置后再检查", stages=[stage("修改配置", read_only=False), stage("核对配置")],
                     rows=[dict(stage=i, channel=c, status="completed" if i == 0 else "stopped")
                           for i in range(2) for c in (1, 2, 7)])
        self.store.update_chat(identifier, batch=batch, batch_progress={str(c): "stopped" for c in (1, 2, 7)})
        seen = []
        def run(child, *_args):
            seen.append(self.store.chat(child)["batch_stage"]["instruction"])
            self.service.batch.record_tool(child, "read_pc_environment", {"actual": True})
        with patch.object(self.service, "_run", side_effect=run):
            self.service.router.send("继续剩余", self.profile)
            self.service.jobs.join()
        self.assertEqual(seen, ["核对配置"] * 3)

    def test_workbench_shows_parent_and_channel_evidence_without_child_entries(self):
        import tkinter as tk
        from tk_test_windows import install_offscreen_windows
        from src.ui.ai_diagnostics_window import AiDiagnosticsWindow
        from src.ui.ai_session_manager import AiSessionManager
        install_offscreen_windows(self)
        self.addCleanup(gc.collect)
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            identifier = self.route()
        root = tk.Tk()
        root.withdraw()
        dialog = AiDiagnosticsWindow(root, self.diag, lambda: self.targets, conversation=self.service)
        try:
            dialog.open()
            panel = dialog.chat_panel
            panel.selected = identifier
            panel.refresh()
            self.assertIn(identifier, panel.ids)
            children = set(self.store.chat(identifier)["batch_children"].values())
            self.assertFalse(children.intersection(panel.ids))
            self.assertIn("批量", panel.current_target.cget("text"))
            manager = AiSessionManager(dialog.window, self.service, identifier, panel.refresh, dialog.background_color)
            try:
                self.assertFalse(children.intersection(manager.rows))
            finally:
                manager.window.destroy()
        finally:
            if dialog._poll_id:
                root.after_cancel(dialog._poll_id)
            dialog.window.destroy()
            root.destroy()

    def test_service_restart_does_not_replay_saved_batch(self):
        from src.services.ai_conversation_service import AiConversationService
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            identifier = self.route()
        self.service.begin_close()
        self.service.worker.join(4)
        self.store.update_chat(identifier, status="处理中", batch_request={"original": "reboot", "channels": [1, 2, 7]})
        count = len(self.requests)
        restarted = AiConversationService(self.diag, self.context)
        try:
            self.assertTrue(restarted.jobs.empty())
            self.assertFalse(restarted.running)
            self.assertIsNone(self.store.chat(identifier)["batch_request"])
            self.assertEqual(len(self.requests), count)
            self.assertEqual(self.store.chat(identifier)["status"], "上次中断，可继续")
        finally:
            restarted.begin_close()
            restarted.worker.join(4)

    def test_cross_device_summary_uses_current_tool_results_without_tools(self):
        self.responses.extend([chat(json.dumps(dict(stages=[stage("读取版本并比较")]))), chat("通道2版本不同，需结合基准核实。")])
        def run(child, *_args):
            channel = self.store.chat(child)["target"]["channel"]
            self.service.batch.record_tool(child, "read_dut_state", dict(version="different" if channel == 2 else "same"))
        with patch.object(self.service, "_run", side_effect=run):
            identifier = self.route("比较3台样机版本差异")
        request = self.requests[-1]
        self.assertNotIn("tools", request)
        payload = request["messages"][-1]["content"]
        self.assertIn("different", payload)
        self.assertIn("same", payload)
        self.assertIn('"channel": 7', payload)
        self.assertIn("版本不同", self.store.chat_items(identifier)[-1]["text"])

    def test_unknown_result_excluded_from_retry_failures(self):
        self.assertEqual(observed_status([], [dict(state="unknown")]), "unknown")
        self.assertEqual(observed_status([]), "skipped")
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            identifier = self.route()
        self.store.update_chat(identifier, batch_progress={"1": "unknown", "2": "reachable", "7": "reachable"})
        with self.assertRaisesRegex(ValueError, "没有符合条件"):
            self.service.router.send("只重查失败的", self.profile)

    def test_sources_do_not_share_parent_or_children(self):
        ids = []
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            for source in (dict(kind="local"), dict(kind="dingtalk", sender="a"),
                           dict(kind="feishu", sender="a", chat_type="p2p")):
                ids.append(self.route(source=source))
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(len({c for p in ids for c in self.store.chat(p)["batch_children"].values()}), 9)

    def test_batch_permission_binding_contains_all_targets(self):
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            identifier = self.route()
        session = self.store.chat(identifier)
        self.assertIn('"batch_targets"', self.service.permissions._binding(session))
        self.service.permissions.select(identifier, "ask")
        self.seen.clear()
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            self.service.send(identifier, "3台都ping一下")
            self.service.jobs.join()
        self.assertTrue(all(self.store.chat(c)["permission_mode"] == "ask"
                            for c in self.store.chat(identifier)["batch_children"].values()))

    def test_delete_parent_removes_children(self):
        with patch("src.services.ai_conversation_service.probe_connectivity", side_effect=self.ping):
            identifier = self.route()
        children = list(self.store.chat(identifier)["batch_children"].values())
        self.service.delete_sessions([identifier])
        for child in [identifier] + children:
            with self.assertRaises(ValueError):
                self.store.chat(child)


class BatchModelTests(unittest.TestCase):
    def test_strict_stage_validation(self):
        for invalid in (dict(stage(), read_only="yes"), dict(stage(), scope="other"), dict(stage(), probe="shell")):
            with self.assertRaises(ValueError):
                BatchStage.parse(invalid)

    def test_actual_ping_dataclass_shape_is_used(self):
        self.assertEqual(observed_status([("probe_connectivity", {"result": {"sent": 4, "times_ms": []}})]), "unreachable")
        self.assertEqual(observed_status([("probe_connectivity", {"result": {"sent": 4, "times_ms": [1]}})]), "reachable")


if __name__ == "__main__":
    unittest.main()
