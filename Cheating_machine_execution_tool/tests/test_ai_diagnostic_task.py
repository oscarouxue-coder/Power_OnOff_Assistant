"""连续诊断离线回归：临时数据库、受控模型与只读工具，不连接真实设备。"""
import json
import threading
import time
import unittest
from unittest.mock import Mock, patch

import test_ai_conversation as fixtures
import test_ai_workspace as workspace_fixtures
from test_ai_core import FakeResponse, chat, call
from src.core.ai_client import DiagnosticModelClient, ModelServiceError
from src.services.ai_diagnostic_task import DiagnosticTask
from src.utils.ai_redaction import DiagnosticRedactor
from src.models.ai_diagnostics import ProviderProfile
from src.services.ai_conversation_service import AiConversationService


def tool(name, params, identifier="step"):
    value = call(name, json.dumps(params, ensure_ascii=False))
    value["id"] = identifier
    return chat("", [value])


class TaskUnitTests(unittest.TestCase):
    def test_plan_requires_existing_evidence_and_keeps_observations_separate(self):
        task = DiagnosticTask("定位故障")
        params = {"steps": [{"text": "检查网卡", "status": "completed"}],
                  "findings": [{"evidence_id": "e1", "observation": "网卡当前未连接，故障时状态未知"}]}
        with self.assertRaises(ValueError):
            task.update_plan(params, set())
        task.update_plan(params, {"e1"})
        self.assertEqual(task.snapshot()["findings"], params["findings"])

    def test_budgets_duplicate_checks_and_supplement_invalidation(self):
        clock = Mock(return_value=0)
        task = DiagnosticTask("检查", clock=clock)
        task.record("read_pc_environment", {}, {"error": "接口查询失败"}, "e1")
        for _ in range(2):
            self.assertEqual(task.cached("read_pc_environment", {})["evidence_id"], "e1")
        self.assertIn("没有新进展", task.limit_reason())
        task.supplement("网卡已重新连接，请核对")
        self.assertEqual(task.take_inputs(), ["网卡已重新连接，请核对"])
        self.assertIsNone(task.cached("read_pc_environment", {}))
        clock.return_value = 601
        self.assertIn("10分钟", task.limit_reason())
        task.calls = 48
        self.assertIn("48次", task.limit_reason())
        task.rounds = 24
        self.assertIn("24轮", task.limit_reason())

    def test_different_queries_with_no_new_evidence_also_stop(self):
        task = DiagnosticTask("检查")
        for index in range(3):
            task.record("read_test_evidence", {"query": str(index)}, {"matched": 0, "history": []}, str(index))
        self.assertIn("没有新进展", task.limit_reason())


class DiagnosticTaskTests(unittest.TestCase):
    setUp = fixtures.ConversationTests.setUp
    stop_services = fixtures.ConversationTests.stop_services

    def run_task(self, text="定位Ping失败"):
        self.service.send(self.id, text, diagnosis_only=True)
        self.service.jobs.join()
        return self.store.chat(self.id)

    def test_more_than_five_rounds_and_ten_calls_without_protocol_loss(self):
        for index in range(12):
            self.service.add_evidence(self.id, "fixture", "sample" + str(index) + "unique 当前只读记录")
            self.responses.append(tool("read_test_evidence", {"query": "sample" + str(index) + "unique"}, str(index)))
        self.responses.append(chat("证据不足，建议核对物理接线；未修复。"))
        result = self.run_task()
        self.assertEqual(result["status"], "可继续")
        self.assertEqual(result["diagnostic_task"]["calls"], 12)
        self.assertEqual(result["diagnostic_task"]["rounds"], 13)
        groups = self.store.chat_items(self.id, group=True)
        self.assertEqual(sum(m.get("role") == "tool" for m in groups[0]), 12)
        self.assertLess(sum(m.get("role") == "tool" for m in self.requests[-1]["messages"]), 12)

    def test_diagnosis_hides_and_blocks_modifications_even_with_full_access(self):
        self.service.permissions.select(self.id, "full_access", confirmed=True)
        self.responses.extend([tool("run_local_command", {"command": "reboot"}), chat("未执行修复")])
        self.run_task()
        names = {t["function"]["name"] for t in self.requests[0]["tools"]}
        for name in ("run_local_command", "run_dut_command", "write_local_file", "capture_packets", "kernel_debug", "follow_logs"):
            self.assertNotIn(name, names)
        self.assertFalse(self.store.actions(self.id))
        with self.assertRaisesRegex(ValueError, "连续诊断"):
            self.service.actions.execute(self.id, "run_dut_command", {"command": "reboot"}, None,
                                         threading.Event(), Mock(), Mock())

    def test_duplicate_failure_is_not_executed_again_and_task_concludes(self):
        self.responses.extend([tool("read_pc_environment", {}) for _ in range(3)] + [chat("无法取证，建议人工检查")])
        with patch.object(self.service, "_collect", side_effect=RuntimeError("查询失败")) as collect:
            result = self.run_task()
        self.assertEqual(collect.call_count, 1)
        self.assertIn("没有新进展", result["diagnostic_task"]["reason"])
        self.assertNotIn("tools", self.requests[-1])

    def test_memory_plan_and_quoted_evidence_survive_next_request(self):
        evidence_id = self.service.add_evidence(self.id, "fixture", "网卡管理状态Enabled，当前未接网线")
        self.responses.extend([tool("update_diagnostic_plan", {
            "steps": [{"text": "检查网卡", "status": "completed"}, {"text": "核对接线", "status": "pending"}],
            "findings": [{"evidence_id": evidence_id, "observation": "当前链路未连接，不能据此证明网卡禁用"}]}), chat("建议检查接线")])
        self.run_task()
        self.responses.append(chat("继续核对"))
        self.run_task("已换网线")
        info = json.loads(self.requests[-1]["messages"][-1]["content"])
        self.assertEqual(info["diagnostic_task"]["findings"][0]["evidence_id"], evidence_id)
        self.assertIn("已换网线", info["diagnostic_task"]["corrections"])

    def test_inflight_supplement_skips_unstarted_checks_and_is_used_next_round(self):
        entered, release = threading.Event(), threading.Event()
        original = self.diag.client_factory
        def factory(*args):
            client = original(*args)
            complete = client.complete_stream
            def blocked(*args, **kwargs):
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("offline release timeout")
                return complete(*args, **kwargs)
            client.complete_stream = blocked
            return client
        self.diag.client_factory = factory
        self.responses.extend([tool("read_pc_environment", {}), chat("按补充核对接线")])
        try:
            self.service.send(self.id, "检查", diagnosis_only=True)
            self.assertTrue(entered.wait(5))
            self.service.send(self.id, "网卡是启用的，先看接线", diagnosis_only=True)
        finally:
            release.set()
        self.service.jobs.join()
        group = self.store.chat_items(self.id, group=True)[0]
        self.assertTrue(any(m.get("role") == "user" and m.get("content") == "网卡是启用的，先看接线" for m in group))
        self.assertIn("收到用户补充", json.dumps(group, ensure_ascii=False))
        self.assertFalse(self.service.tasks)

    def supplement_receipts(self, session=None):
        with self.store.lock:
            return self.store.db.execute('SELECT turn_id,supplement_id,state,request_id FROM chat_supplement_receipts '
                'WHERE session_id=? ORDER BY message_id', (session or self.id,)).fetchall()

    def hold_first_response(self):
        entered, release = threading.Event(), threading.Event()
        original = self.diag.client_factory
        def factory(*args):
            client = original(*args)
            request = client.session.request.side_effect
            def blocked(method, *args, **kwargs):
                response = request(method, *args, **kwargs)
                if method == 'POST' and len(self.requests) == 1:
                    entered.set()
                    if not release.wait(5):
                        raise AssertionError('fake barrier timeout')
                return response
            client.session.request.side_effect = blocked
            return client
        self.diag.client_factory = factory
        return entered, release

    def test_supplement_receipts_distinguish_duplicates_and_sessions_without_wire_metadata(self):
        entered, release = self.hold_first_response()
        other = self.service.create_session(None, self.profile, scope='pc', diagnosis_only=True)
        self.responses.extend([chat('first'), chat('second'), chat('other')])
        try:
            self.service.send(self.id, 'question', diagnosis_only=True)
            self.assertTrue(entered.wait(5))
            self.service.send(self.id, 'duplicate fixture', diagnosis_only=True)
            self.service.send(self.id, 'duplicate fixture', diagnosis_only=True)
            self.assertEqual([r[2] for r in self.supplement_receipts()], ['received', 'received'])
            self.service.send(other, 'other question', diagnosis_only=True)
            self.service.send(other, 'other supplement', diagnosis_only=True)
        finally:
            release.set()
        self.service.jobs.join()
        a, b = self.supplement_receipts(), self.supplement_receipts(other)
        self.assertEqual(len(a), 2)
        self.assertEqual(len({r[1] for r in a}), 2)
        self.assertEqual(len({r[0] for r in a}), 1)
        self.assertEqual([r[2] for r in a], ['confirmed', 'confirmed'])
        self.assertEqual(a[0][3], a[1][3])
        self.assertTrue(a[0][3])
        self.assertEqual(b[0][2], 'confirmed')
        self.assertNotEqual(a[0][0], b[0][0])
        self.assertNotEqual(a[0][3], b[0][3])
        self.assertEqual(len(self.requests), 3)
        counts = lambda text: [sum(m.get('content') == text for m in p['messages']) for p in self.requests]
        self.assertEqual(counts('duplicate fixture'), [0, 2, 0])
        self.assertEqual(counts('other supplement'), [0, 0, 1])
        for identity in (a[0][1], a[1][1], a[0][0], a[0][3], b[0][1]):
            self.assertNotIn(identity, json.dumps(self.requests))
        for identity in (a[0][1], a[1][1], a[0][0], b[0][1]):
            self.assertNotIn(identity, json.dumps(self.store.chat_items(self.id)))
        self.assertIn(a[0][3], [m.get('reply_id') for m in self.store.chat_items(self.id)])
        from src.services.ai_store import DiagnosticStore
        reopened = DiagnosticStore(self.store.directory, self.store.cipher)
        try:
            self.assertEqual(reopened.db.execute('SELECT turn_id,supplement_id,state,request_id FROM '
                'chat_supplement_receipts WHERE session_id=? ORDER BY message_id', (self.id,)).fetchall(), a)
            self.assertEqual(reopened.update_supplement_receipts(self.id, a[0][0], [a[0][1]], 'confirmed', 'late'), ())
        finally:
            reopened.close()

    def test_supplement_cancel_before_transport_leaves_no_dispatch_receipt(self):
        entered, release = threading.Event(), threading.Event()
        first, first_release = self.hold_first_response()
        original = self.diag.client_factory
        def factory(*args):
            client = original(*args)
            request = client._request
            def blocked(method, *args, **kwargs):
                if method == 'POST' and len(self.requests) == 1:
                    entered.set()
                    if not release.wait(5):
                        raise AssertionError('fake dispatch barrier timeout')
                return request(method, *args, **kwargs)
            client._request = blocked
            return client
        self.diag.client_factory = factory
        self.responses.append(chat('first'))
        try:
            self.service.send(self.id, 'question', diagnosis_only=True)
            self.assertTrue(first.wait(5))
            self.service.send(self.id, 'supplement before cancellation', diagnosis_only=True)
            first_release.set()
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.supplement_receipts()[0][2], 'received')
            self.service.stop(self.id)
        finally:
            first_release.set()
            release.set()
        self.service.jobs.join()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.supplement_receipts()[0][2:], ('cancelled', None))

    def test_supplement_cancel_after_confirmed_transport_keeps_receipt(self):
        first, first_release = self.hold_first_response()
        entered, release = threading.Event(), threading.Event()
        class HeldResponse(FakeResponse):
            def iter_content(inner, size):
                entered.set()
                if not release.wait(5):
                    raise AssertionError('fake response barrier timeout')
                yield from super().iter_content(size)
        self.responses.extend([chat('first'), HeldResponse(chat('second'))])
        try:
            self.service.send(self.id, 'question', diagnosis_only=True)
            self.assertTrue(first.wait(5))
            self.service.send(self.id, 'supplement after dispatch', diagnosis_only=True)
            first_release.set()
            self.assertTrue(entered.wait(5))
            before = self.supplement_receipts()
            self.assertEqual(before[0][2], 'confirmed')
            self.service.stop(self.id)
        finally:
            first_release.set()
            release.set()
        self.service.jobs.join()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.supplement_receipts(), before)

    def test_supplement_compaction_cannot_match_an_identical_untracked_message(self):
        task = DiagnosticTask('fixture')
        identity = task.supplement('duplicate')
        current = [{'role': 'user', 'content': 'initial'}]
        self.service._task_checkpoint(self.id, task, current)
        current.extend([{'role': 'assistant', 'content': 'old'}, {'role': 'user', 'content': 'duplicate'}])
        task.boundaries = [1, 2, 3]
        compacted = task.compact(current)
        self.assertTrue(any(m.get('content') == 'duplicate' for m in compacted))
        self.assertNotIn(id(current[1]), {id(m) for m in compacted})
        client = Mock()
        complete = Mock(return_value='unchanged')
        self.assertEqual(self.service._complete_with_supplement_receipts(self.id, task, threading.Event(),
            'request', client, compacted, complete), 'unchanged')
        complete.assert_called_once_with()
        self.assertIn(identity, task.pending_supplements)
        self.assertFalse(task.unconfirmed_supplements)

    def test_supplement_transport_observer_preserves_payload_for_both_protocols(self):
        from dataclasses import replace
        for protocol in ('chat_completions', 'responses'):
            with self.subTest(protocol=protocol):
                profile = replace(self.profile, protocol=protocol)
                session = Mock()
                response = chat('reply') if protocol == 'chat_completions' else {'output': [
                    {'type': 'message', 'content': [{'type': 'output_text', 'text': 'reply'}]}]}
                session.request.return_value = FakeResponse(response)
                client = DiagnosticModelClient(profile, 'fixture', DiagnosticRedactor(), session=session)
                history = [{'role': 'user', 'content': 'same'}, {'role': 'user', 'content': 'same'}]
                expected = client.request_payload(history, ())
                confirm = Mock()
                with client.observe_supplement_dispatch(history, {1: 'second-id'}, confirm):
                    client.complete(history)
                self.assertEqual(session.request.call_args.kwargs['json'], expected)
                confirm.assert_called_once_with(('second-id',))
                confirm.reset_mock()
                request = client._request
                def altered(method, path, payload, *args):
                    payload['input' if protocol == 'responses' else 'messages'][1] = {'role': 'user', 'content': 'different'}
                    return request(method, path, payload, *args)
                session.request.return_value = FakeResponse(response)
                with patch.object(client, '_request', side_effect=altered):
                    with client.observe_supplement_dispatch(history, {1: 'second-id'}, confirm):
                        client.complete(history)
                confirm.assert_not_called()
                self.assertEqual(session.request.call_count, 2)
                client.close()

    def test_supplement_transport_exception_without_response_is_unconfirmed(self):
        entered, release = self.hold_first_response()
        self.responses.extend([chat('first'), RuntimeError('fixture transport exception')])
        try:
            self.service.send(self.id, 'question', diagnosis_only=True)
            self.assertTrue(entered.wait(5))
            self.service.send(self.id, 'unconfirmed fixture', diagnosis_only=True)
        finally:
            release.set()
        self.service.jobs.join()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.supplement_receipts()[0][2:], ('unconfirmed', None))

    def test_supplement_restart_and_delete_preserve_exact_local_rows(self):
        payload = dict(role='user', text='fixture', kind='text', diagnostic_supplement=True)
        self.store.append_chat(self.id, payload, supplement_receipt=('turn-a', 'supplement-a'))
        other = self.service.create_session(None, self.profile, scope='pc', diagnosis_only=True)
        self.store.append_chat(other, payload, supplement_receipt=('turn-b', 'supplement-b'))
        self.assertEqual(self.store.update_supplement_receipts(other, 'turn-a', ['supplement-a'], 'confirmed', 'wrong'), ())
        self.store.interrupt_supplement_receipts(self.id)
        self.assertEqual(self.supplement_receipts()[0][2:], ('unconfirmed', None))
        self.assertEqual(self.supplement_receipts(other)[0][2:], ('received', None))
        self.assertEqual(self.store.update_supplement_receipts(self.id, 'turn-a', ['supplement-a'], 'confirmed', 'late'), ())
        self.service.delete_sessions([self.id])
        self.assertFalse(self.supplement_receipts())
        self.assertEqual(self.supplement_receipts(other)[0][2:], ('received', None))

    def test_supplement_budget_failure_and_terminal_cleanup_do_not_claim_dispatch(self):
        from src.services.ai_context_budget import ContextCapacity
        entered, release = self.hold_first_response()
        self.responses.append(chat('first'))
        with patch('src.services.ai_conversation_service.context_capacity', return_value=ContextCapacity(32768, 'fixture')):
            try:
                self.service.send(self.id, 'question', diagnosis_only=True)
                self.assertTrue(entered.wait(5))
                self.service.send(self.id, 'x' * 32000, diagnosis_only=True)
            finally:
                release.set()
            self.service.jobs.join()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.supplement_receipts()[0][2:], ('not_dispatched', None))
        self.assertEqual(self.store.chat(self.id)['status'], '失败，可继续')

    def test_stop_keeps_supplement_and_never_resumes_automatically(self):
        entered, release = threading.Event(), threading.Event()
        def collect(*args):
            entered.set()
            release.wait(5)
            return {"evidence": "已取得的只读信息"}
        self.responses.append(tool("read_pc_environment", {}))
        try:
            with patch.object(self.service, "_collect", side_effect=collect):
                self.service.send(self.id, "检查", diagnosis_only=True)
                self.assertTrue(entered.wait(5))
                self.service.send(self.id, "保留我的补充", diagnosis_only=True)
                self.service.stop(self.id)
                release.set()
                self.service.jobs.join()
        finally:
            release.set()
        result = self.store.chat(self.id)
        self.assertEqual(result["status"], "已停止")
        self.assertIn("保留我的补充", result["diagnostic_task"]["corrections"])
        self.assertEqual(self.supplement_receipts()[0][2:], ('cancelled', None))
        self.assertFalse(self.service.tasks)
        self.assertFalse(self.service.drafts)

    def test_budget_requests_final_advice_without_additional_tools(self):
        self.responses.extend([tool("read_test_evidence", {"query": str(i)}, str(i)) for i in range(2)] + [chat("预算内证据不足，请核对接线")])
        with patch.object(DiagnosticTask, "max_rounds", 2):
            result = self.run_task()
        self.assertEqual(len(self.requests), 3)
        self.assertNotIn("tools", self.requests[-1])
        self.assertTrue(result["diagnostic_task"]["reason"])

    def test_ask_user_waits_then_preserves_plan_when_answered(self):
        self.responses.append(tool("ask_user", {"question": "LOS灯是否亮？", "reason": "需要现场状态"}))
        result = self.run_task()
        self.assertEqual(result["status"], "等待你回复")
        self.assertEqual(len(self.requests), 1)
        self.responses.append(chat("LOS灯熄灭仍不能证明业务正常，建议核对业务连接"))
        self.service.answer_question(self.id, "LOS灯熄灭")
        self.service.jobs.join()
        info = json.loads(self.requests[-1]["messages"][-1]["content"])
        self.assertEqual(info["answering_question"]["id"], result["pending"]["id"])
        self.assertTrue(self.store.chat(self.id)["diagnosis_only"])

    def test_empty_final_response_does_not_claim_diagnostic_advice(self):
        self.responses.append(chat(""))
        result = self.run_task()
        self.assertEqual(result["status"], "失败，可继续")
        self.assertTrue(any("模型未返回诊断结论" in m["text"] for m in self.store.chat_items(self.id)))
        self.assertFalse(any("本次诊断已给出建议" in m["text"] for m in self.store.chat_items(self.id)))

    def test_restart_marks_task_interrupted_and_does_not_replay_queries(self):
        self.service.shutdown.set()
        self.service.worker.join(4)
        self.store.update_chat(self.id, status="处理中", diagnosis_only=True,
                               diagnostic_task={"goal": "检查", "state": "处理中", "steps": []})
        self.service = AiConversationService(self.diag, self.context)
        self.diag.conversation = self.service
        self.assertEqual(self.store.chat(self.id)["diagnostic_task"]["state"], "上次中断，可继续")
        self.assertFalse(self.service.tasks)
        self.assertTrue(self.service.jobs.empty())
        self.assertFalse(self.requests)

    def test_pc_scope_uses_only_pc_tools_and_preserves_other_permissions(self):
        self.id = self.service.create_session(None, self.profile, scope="pc")
        before = self.service.permissions.status(self.id)["mode"]
        self.responses.append(chat("请核对本机DNS配置，尚未实施修改"))
        self.run_task("检查本机网络")
        names = {t["function"]["name"] for t in self.requests[-1]["tools"]}
        self.assertIn("read_pc_environment", names)
        self.assertNotIn("read_dut_state", names)
        self.assertNotIn("run_local_command", names)
        self.assertEqual(self.service.permissions.status(self.id)["mode"], before)

    def test_time_budget_cancels_unapproved_login_without_connecting(self):
        self.service.permissions.select(self.id, "ask")
        self.responses.extend([tool("read_dut_state", {"category": "network"}), chat("登录未批准，建议现场核对")])
        self.service.send(self.id, "检查设备", diagnosis_only=True)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if any(a["state"] == "waiting_approval" for a in self.store.actions(self.id)):
                break
            time.sleep(.01)
        self.assertTrue(any(a["state"] == "waiting_approval" for a in self.store.actions(self.id)))
        with self.service.lock:
            task = self.service.tasks[self.id]
            task.clock = lambda: task.started + 601
        self.service.jobs.join()
        self.assertTrue(all(a["state"] == "cancelled" for a in self.store.actions(self.id)))
        self.assertIn("10分钟", self.store.chat(self.id)["diagnostic_task"]["reason"])
        self.assertNotIn("tools", self.requests[-1])
        self.assertFalse(any("TX" in line for line in self.logs))


class TaskUiTests(unittest.TestCase):
    setUp = workspace_fixtures.WorkspaceTests.setUp
    close_ui = workspace_fixtures.WorkspaceTests.close_ui
    stop_services = fixtures.ConversationTests.stop_services

    def test_new_session_is_first_and_creates_blank_without_stopping_old_work(self):
        panel = self.dialog.chat_panel
        panel.selected = self.id
        self.service.router.select(self.id)
        self.service.message(self.id, "user", "旧会话的问题")
        self.service.add_evidence(self.id, "旧材料", "旧会话证据")
        self.store.update_chat(self.id, diagnostic_task=dict(goal="旧排查"), source_report_id="old-report")
        before = self.store.chat(self.id)
        panel.input.insert("1.0", "未发送的草稿")
        panel.task_control.changed(True)
        old_stop = threading.Event()
        self.service.running[self.id] = old_stop
        try:
            menu = panel.task_control.menu
            self.assertEqual(menu.entrycget(0, "label"), "新会话")
            self.assertEqual(menu.type(1), "separator")
            self.assertEqual(menu.entrycget(2, "label"), "切换为常规对话（沿用操作权限）")
            with patch.object(self.service, "stop") as stop, patch.object(self.service.router, "cancel_source") as cancel, \
                    patch.object(panel.input, "focus_set", wraps=panel.input.focus_set) as focus:
                menu.invoke(0)
                stop.assert_not_called()
                cancel.assert_not_called()
                focus.assert_called_once()
            identifier = panel.selected
            self.assertNotEqual(identifier, self.id)
            session = self.store.chat(identifier)
            self.assertEqual(session["scope"], "general")
            self.assertIsNone(session["target"])
            self.assertEqual(session["profile"]["id"], self.profile.id)
            self.assertEqual(session["source_report_id"], "")
            self.assertNotIn("diagnostic_task", session)
            self.assertEqual(self.store.chat_evidence(identifier), [])
            self.assertFalse(any(m["role"] in ("user", "assistant") for m in self.store.chat_items(identifier)))
            self.assertEqual(self.store.chat(self.id), before)
            self.assertIs(self.service.running[self.id], old_stop)
            self.assertFalse(old_stop.is_set())
            self.assertEqual(self.service.router.current(), identifier)
            self.assertEqual(panel.input.get("1.0", "end-1c"), "未发送的草稿")
            self.assertNotIn("旧会话的问题", panel.output.get("1.0", "end"))
            self.assertTrue(panel.task_control.enabled)
            self.service.message(self.id, "assistant", "旧任务后台返回的结果")
            panel.poll()
            self.assertEqual(panel.selected, identifier)
            self.assertNotIn("旧任务后台返回的结果", panel.output.get("1.0", "end"))
            self.assertEqual(panel.input.get("1.0", "end-1c"), "未发送的草稿")
            self.assertEqual(self.requests, [])
            self.assertTrue(any("空白新会话" in line and "已创建" in line for line in self.logs))
        finally:
            self.service.running.pop(self.id, None)

    def test_new_session_menu_disables_during_routing_and_callback_guards_it(self):
        panel = self.dialog.chat_panel
        panel.selected = self.id
        panel.input.insert("1.0", "草稿")
        panel.routing = True
        count = len(self.store.chats())
        generation = panel.route_generation
        menu = panel.task_control.menu
        with patch.object(menu, "tk_popup") as popup, patch.object(menu, "grab_release"):
            self.assertEqual(panel.task_control.popup(Mock(num=3, x_root=10, y_root=20)), "break")
            popup.assert_called_once_with(10, 20)
            self.assertEqual(menu.entrycget(0, "state"), "disabled")
            menu.invoke(0)
            self.assertIsNone(panel.task_control.new_session())
            self.assertEqual(len(self.store.chats()), count)
            self.assertEqual(panel.selected, self.id)
            self.assertEqual(panel.route_generation, generation)
            self.assertEqual(panel.input.get("1.0", "end-1c"), "草稿")
            panel.routing = False
            panel.task_control.popup(Mock(num=None))
            self.assertEqual(menu.entrycget(0, "state"), "normal")
        self.assertTrue(panel.send_button.bind("<Button-3>"))
        self.assertTrue(panel.send_button.bind("<Alt-Down>"))
        self.assertEqual(self.requests, [])

    def test_new_session_failure_preserves_selection_and_draft(self):
        panel = self.dialog.chat_panel
        panel.selected = self.id
        self.service.router.select(self.id)
        panel.render()
        panel.input.insert("1.0", "保留输入")
        count = len(self.store.chats())
        generation = panel.route_generation
        for profile, error in ((None, None), (self.profile, RuntimeError("模拟存储失败"))):
            with self.subTest(profile=profile), patch.object(self.dialog, "_error") as shown:
                self.dialog.service.profile = profile
                if error is None:
                    self.assertIsNone(panel.task_control.new_session())
                else:
                    with patch.object(self.service, "create_session", side_effect=error):
                        self.assertIsNone(panel.task_control.new_session())
                shown.assert_called_once()
                self.assertEqual(panel.selected, self.id)
                self.assertEqual(self.service.router.current(), self.id)
                self.assertEqual(panel.route_generation, generation)
                self.assertEqual(len(self.store.chats()), count)
                self.assertEqual(panel.input.get("1.0", "end-1c"), "保留输入")
        self.assertTrue(any("创建空白新会话失败" in line for line in self.logs))
        self.assertEqual(self.requests, [])

    def test_new_session_first_send_stays_in_new_general_session(self):
        panel = self.dialog.chat_panel
        self.service.message(self.id, "user", "旧会话专有故障")
        panel.task_control.new_session()
        identifier = panel.selected
        panel.input.insert("1.0", "你是谁")
        panel.send()
        fixtures.wait_panel(panel, self.service)
        self.assertEqual(panel.selected, identifier)
        self.assertEqual([m["text"] for m in self.store.chat_items(identifier) if m["role"] == "user"], ["你是谁"])
        self.assertNotIn("旧会话专有故障", json.dumps(self.requests, ensure_ascii=False))
        self.assertEqual(self.store.chat(identifier)["scope"], "general")

    def test_new_session_rejects_unsaved_profile_and_shutdown_without_creating(self):
        from dataclasses import replace
        count = len(self.store.chats())
        with self.assertRaisesRegex(ValueError, "模型配置已变化"):
            self.service.create_blank_session(replace(self.profile, model="unsaved"))
        self.service.shutdown.set()
        try:
            with self.assertRaisesRegex(RuntimeError, "正在退出"):
                self.service.create_blank_session(self.profile)
        finally:
            self.service.shutdown.clear()
        self.assertEqual(len(self.store.chats()), count)
        self.assertEqual(self.requests, [])

    def test_menu_sends_diagnostic_task_and_progress_is_on_demand(self):
        panel = self.dialog.chat_panel
        panel.selected = self.id
        panel.task_control.changed(True)
        panel.input.insert("1.0", "检查故障")
        self.responses.append(chat("证据不足，建议核对接线"))
        panel.send()
        fixtures.wait_panel(panel, self.service)
        self.assertTrue(self.store.chat(self.id)["diagnosis_only"])
        self.assertEqual(panel.send_button.cget("text"), "发送连续诊断 ▾")
        panel.task_control.show_progress()
        self.assertIn("检查故障", panel.task_control.output.get("1.0", "end"))
        self.assertEqual(panel.task_control.output.cget("state"), "disabled")
        self.assertEqual(panel.task_control.window.cget("background"), "#eef2f5")
        window = panel.task_control.window
        panel.task_control.show_progress()
        self.assertIs(panel.task_control.window, window)
        self.assertIs(self.store.setting("continuous_diagnosis"), True)
        panel.task_control.changed(False)
        self.assertEqual(panel.send_button.cget("text"), "发送 / 回答问题 ▾")

    def test_stream_preview_is_not_persisted_and_final_text_replaces_it(self):
        panel = self.dialog.chat_panel
        panel.selected = self.id
        self.service._draft(self.id, "正在逐步分析")
        panel.render()
        self.assertIn("正在逐步分析", panel.output.get("1.0", "end"))
        self.assertFalse(any(m["text"] == "正在逐步分析" for m in self.store.chat_items(self.id)))
        with self.service.lock:
            self.service.drafts.pop(self.id)
        self.service.message(self.id, "assistant", "正在逐步分析，结论尚未确认")
        panel.render()
        self.assertEqual(panel.output.get("1.0", "end").count("正在逐步分析"), 1)

    def test_task_progress_does_not_pollute_main_log_summary(self):
        from src.ui.main_log_filter import format_main_log_message
        for message in ("[AI对话] 会话1234abcd工具完成：update_diagnostic_plan",
                        '[AI对话] 会话1234abcd连续诊断计划更新：[{"text":"检查网卡","status":"in_progress"}]',
                        "[AI对话] 会话1234abcd已采用2条诊断补充，原始记录保留"):
            self.assertIsNone(format_main_log_message(message))
        self.assertIsNotNone(format_main_log_message("[AI对话] 会话1234abcd连续诊断收束：连续三次检查没有新进展；不再新增取证"))


class StreamTests(unittest.TestCase):
    def client(self, events, protocol="chat_completions", terminated=True):
        data = b"".join(b"data: " + json.dumps(e, ensure_ascii=False).encode() + b"\r\n\r\n" for e in events)
        if terminated:
            data += b"data: [DONE]\n\n"
        response = Mock(status_code=200)
        response.iter_content.side_effect = lambda _size: (data[i:i+3] for i in range(0, len(data), 3))
        session = Mock()
        session.request.return_value = response
        redactor = DiagnosticRedactor(("secret-token",))
        client = DiagnosticModelClient(ProviderProfile(model="offline", protocol=protocol), "secret-token", redactor, session)
        self.addCleanup(client.close)
        return client, response

    def test_chat_stream_assembles_fragmented_tools_and_reasoning(self):
        events = [
            {"choices": [{"delta": {"content": "正在检查中文", "reasoning_content": "private-reasoning"}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "type": "function", "function": {"name": "read_", "arguments": "{"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "pc_environment", "arguments": "}"}}]}, "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 4}}]
        client, response = self.client(events)
        preview = []
        reply = client.complete_stream([], [], on_text=preview.append)
        self.assertEqual(preview[-1], "正在检查中文")
        self.assertEqual(reply.calls, [{"id": "c1", "name": "read_pc_environment", "arguments": "{}"}])
        self.assertEqual(reply.history[-1]["reasoning_content"], "private-reasoning")
        self.assertEqual(reply.usage["prompt_tokens"], 10)
        response.close.assert_called_once()

    def test_responses_stream_uses_completed_canonical_output(self):
        final = {"status": "completed", "output": [{"type": "reasoning", "id": "r1", "summary": []},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "检查结束"}]},
            {"type": "function_call", "call_id": "c1", "name": "read_pc_environment", "arguments": "{}"}], "usage": {"input_tokens": 9}}
        client, _ = self.client([{"type": "response.output_text.delta", "delta": "检查"},
                                 {"type": "response.completed", "response": final}], "responses")
        reply = client.complete_stream([], [], on_text=Mock())
        self.assertEqual(reply.history, final["output"])
        self.assertEqual(reply.calls[0]["id"], "c1")

    def test_truncated_stream_never_returns_executable_calls(self):
        client, response = self.client([{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "read_pc_environment", "arguments": "{"}}]}}]}], terminated=False)
        with self.assertRaises(ModelServiceError):
            client.complete_stream([], [], on_text=Mock())
        response.close.assert_called_once()

    def test_split_model_key_never_appears_in_previews(self):
        client, _ = self.client([{"choices": [{"delta": {"content": part}}]} for part in ("密钥：sec", "ret-", "token", "；完成")])
        preview = []
        reply = client.complete_stream([], [], on_text=preview.append)
        for value in preview:
            self.assertNotIn("sec", value)
        self.assertIn("模型API密钥已隐藏", reply.text)

    def test_json_only_provider_is_accepted_without_resubmitting(self):
        client, response = self.client([])
        response.iter_content.side_effect = lambda _: [json.dumps(chat("普通响应")).encode()]
        reply = client.complete_stream([], [], on_text=Mock())
        self.assertEqual(reply.text, "普通响应")
        client.session.request.assert_called_once()

    def test_stop_closes_stream_without_finalizing_tools(self):
        client, response = self.client([])
        stop = threading.Event()
        def chunks(_):
            stop.set()
            yield b"data: {}\n\n"
        response.iter_content.side_effect = chunks
        with self.assertRaises(InterruptedError):
            client.complete_stream([], [], stop, Mock())
        response.close.assert_called_once()
