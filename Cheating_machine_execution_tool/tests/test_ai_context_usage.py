"""上下文用量：临时会话/假模型协议与独立Tk；不出网、不连接设备。"""
from dataclasses import replace
import gc
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.models.ai_diagnostics import ProviderProfile
from src.services.ai_context_budget import ContextCapacity
from src.services.ai_context_usage import request_usage, reply_usage, failed_usage
from src.services.ai_conversation_service import AiConversationService
from src.services.ai_store import DiagnosticStore, profile_fingerprint
from src.ui.ai_context_status import AiContextStatus
from src.ui.ai_diagnostics_window import AiDiagnosticsWindow
from src.ui.module_theme import apply_module_theme
import test_ai_conversation as conversation_tests
from test_ai_core import FakeCipher, FakeResponse, chat, call
from test_ai_debug import TARGET


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


class UsageMathTests(unittest.TestCase):
    def setUp(self):
        self.profile = ProviderProfile(model="fixture")
        self.capacity = ContextCapacity(1000000, "手动填写")
        self.request = request_usage(self.profile, self.capacity, 12000, 2)

    def test_both_protocols_use_input_plus_output_without_summing_billing_metadata(self):
        for protocol, usage in (("chat_completions", {"prompt_tokens": 3000, "completion_tokens": 400,
                                                    "total_tokens": 999999, "prompt_cache_hit_tokens": 2500}),
                                ("responses", {"input_tokens": 3000, "output_tokens": 400,
                                               "output_tokens_details": {"reasoning_tokens": 250}})):
            with self.subTest(protocol=protocol):
                result = reply_usage(self.request, usage, protocol, [{"content": "回复"}], dumps)
                self.assertEqual((result["input_tokens"], result["output_tokens"], result["total_tokens"]), (3000, 400, 3400))
                self.assertEqual(result["source"], "api")
                self.assertNotIn("previous_valid", result)

    def test_missing_or_malformed_usage_estimates_both_sides_including_tool_arguments(self):
        output = [{"role": "assistant", "content": "中文回复", "reasoning_content": "思考",
                   "tool_calls": [call("read_network_state", '{"category":"wifi"}')]}]
        for protocol, incoming, outgoing in (("chat_completions", "prompt_tokens", "completion_tokens"),
                                              ("responses", "input_tokens", "output_tokens")):
            for usage in (None, [], "invalid", {}, {incoming: 4}, {incoming: True, outgoing: 1},
                          {incoming: -1, outgoing: 1}, {incoming: 4.0, outgoing: 1}, {incoming: 4, outgoing: "1"}):
                with self.subTest(protocol=protocol, usage=usage):
                    result = reply_usage(self.request, usage, protocol, output, dumps)
                    self.assertEqual(result["source"], "estimate")
                    self.assertEqual(result["input_tokens"], 12000)
                    self.assertEqual(result["output_tokens"], len(dumps(output).encode("utf-8")))

    def test_zero_usage_is_valid_and_reserves_are_not_used_tokens(self):
        result = reply_usage(self.request, {"input_tokens": 0, "output_tokens": 0}, "responses", [], dumps)
        self.assertEqual(result["total_tokens"], 0)
        self.assertEqual(result["source"], "api")
        self.assertEqual(self.request["total_tokens"], 12000)
        self.assertEqual(self.request["identity"]["max_output"], self.profile.max_output)

    def test_failed_retries_keep_one_previous_completed_snapshot(self):
        completed = reply_usage(self.request, {"input_tokens": 3000, "output_tokens": 100}, "responses", [], dumps)
        latest = completed
        for _ in range(5):
            latest = request_usage(self.profile, self.capacity, 8000, 2, latest)
        self.assertNotIn("previous_valid", latest["previous_valid"])
        for state in ("failed", "cancelled"):
            result = failed_usage(latest, state)
            self.assertEqual(result["total_tokens"], 3100)
            self.assertEqual(result["updated"], completed["updated"])
            self.assertEqual(result["state"], state)
        self.assertEqual(failed_usage(None, "failed")["state"], "failed")


class UsageConversationTests(unittest.TestCase):
    setUp = conversation_tests.ConversationTests.setUp
    stop_services = conversation_tests.ConversationTests.stop_services
    send = conversation_tests.ConversationTests.send

    def test_request_estimate_is_published_before_response_and_capacity_is_not_a_chat_message(self):
        observed = []
        class Observe(FakeResponse):
            def iter_content(inner, size):
                observed.append(self.store.chat(self.id)["context_usage"])
                yield from super().iter_content(size)
        self.responses.append(Observe(chat("完成")))
        # usage是模型响应的顶层字段。
        self.responses[0].data["usage"] = {"prompt_tokens": 12, "completion_tokens": 3}
        self.send()
        request = observed[0]
        self.assertEqual(request["state"], "requesting")
        self.assertEqual(request["total_tokens"], len(dumps(self.requests[0]).encode("utf-8")))
        self.assertIsNone(request["output_tokens"])
        self.assertEqual(self.store.chat(self.id)["context_usage"]["total_tokens"], 15)
        self.assertFalse(any(m["role"] == "system" and m["text"].startswith("上下文容量：")
                             for m in self.store.chat_items(self.id)))

    def test_both_protocols_tool_results_refresh_then_save_latest_response_not_sum(self):
        for protocol in ("chat_completions", "responses"):
            with self.subTest(protocol=protocol):
                changed = self.store.save_profile(replace(self.profile, protocol=protocol))
                self.profile = replace(changed, capability="可自动诊断", tested_fingerprint=profile_fingerprint(changed))
                self.store.save_profile(self.profile)
                self.id = self.service.create_session(TARGET, self.profile)
                if protocol == "responses":
                    first = {"output": [{"type": "function_call", "call_id": "e1", "name": "read_test_evidence",
                                         "arguments": '{"query":""}'}], "usage": {"input_tokens": 100, "output_tokens": 10}}
                    second = {"output": [{"type": "message", "role": "assistant", "content": [
                        {"type": "output_text", "text": "完成"}]}], "usage": {"input_tokens": 150, "output_tokens": 5}}
                else:
                    first = chat("", [call("read_test_evidence", '{"query":""}')])
                    first["usage"] = {"prompt_tokens": 100, "completion_tokens": 10}
                    second = chat("完成")
                    second["usage"] = {"prompt_tokens": 150, "completion_tokens": 5}
                self.responses.extend([first, second])
                with patch.object(self.service, "_save_usage", wraps=self.service._save_usage) as save:
                    self.send()
                snapshots = [c.args[1] for c in save.call_args_list]
                self.assertEqual([s["state"] for s in snapshots], ["requesting", "completed", "requesting", "completed"])
                self.assertGreater(snapshots[2]["input_tokens"], snapshots[0]["input_tokens"])
                self.assertEqual(self.store.chat(self.id)["context_usage"]["total_tokens"], 155)

    def test_retry_reestimates_trimmed_request_and_failure_keeps_completed_usage(self):
        first = chat("已完成")
        first["usage"] = {"prompt_tokens": 500, "completion_tokens": 20}
        self.responses.append(first)
        self.send()
        for _ in range(6):
            self.store.append_chat(self.id, [{"role": "user", "content": "旧材料" * 100}], group=True)
        error = FakeResponse({"error": {"code": "context_length_exceeded"}}, 400)
        self.responses.extend([error, ValueError("offline")])
        with patch.object(self.service, "_save_usage", wraps=self.service._save_usage) as save:
            self.send("再次检查")
        estimates = [c.args[1]["input_tokens"] for c in save.call_args_list if c.args[1].get("state") == "requesting"]
        self.assertEqual(len(estimates), 2)
        self.assertLess(estimates[1], estimates[0])
        saved = self.store.chat(self.id)["context_usage"]
        self.assertEqual(saved["total_tokens"], 520)
        self.assertEqual(saved["state"], "failed")

    def test_cancel_keeps_completed_usage_and_restart_recovers_it_without_recomputing(self):
        response = chat("完成")
        response["usage"] = {"prompt_tokens": 400, "completion_tokens": 20}
        self.responses.append(response)
        self.send()
        self.diag.operation_lock.acquire()
        try:
            self.service.send(self.id, "排队")
            self.service.stop(self.id)
        finally:
            self.diag.operation_lock.release()
        self.service.jobs.join()
        self.assertEqual(self.store.chat(self.id)["context_usage"]["state"], "cancelled")
        self.service.begin_close()
        self.service.worker.join(4)
        self.service = AiConversationService(self.diag, self.context)
        self.diag.conversation = self.service
        self.assertEqual(self.service.context_status(self.id)["snapshot"]["total_tokens"], 420)
        self.assertEqual(len(self.requests), 1)
        reopened = DiagnosticStore(self.temp.name, FakeCipher())
        try:
            self.assertEqual(reopened.chat(self.id)["context_usage"]["total_tokens"], 420)
        finally:
            reopened.close()

    def test_capacity_output_model_changes_expire_usage_but_new_request_replaces_it(self):
        self.send()
        self.assertFalse(self.service.context_status(self.id)["stale"])
        for profile in (replace(self.profile, context_tokens=1000000), replace(self.profile, max_output=8192),
                        replace(self.profile, model="changed")):
            with self.subTest(profile=profile):
                self.store.save_profile(profile)
                self.assertTrue(self.service.context_status(self.id)["stale"])
        self.store.save_profile(self.profile)
        self.store.cache_model_contexts(self.profile, [{"id": self.profile.model, "context_tokens": 1000000}])
        self.assertTrue(self.service.context_status(self.id)["stale"])
        self.send()
        self.assertFalse(self.service.context_status(self.id)["stale"])

    def test_restart_marks_interrupted_request_cancelled_and_recovers_previous_result(self):
        response = chat("完成")
        response["usage"] = {"prompt_tokens": 100, "completion_tokens": 20}
        self.responses.append(response)
        self.send()
        previous = self.store.chat(self.id)["context_usage"]
        incomplete = request_usage(self.profile, ContextCapacity(), 16000, 0, previous)
        self.store.update_chat(self.id, status="处理中", context_usage=incomplete)
        self.service.begin_close()
        self.service.worker.join(4)
        self.service = AiConversationService(self.diag, self.context)
        self.diag.conversation = self.service
        self.assertEqual(self.store.chat(self.id)["status"], "上次中断，可继续")
        recovered = self.service.context_status(self.id)["snapshot"]
        self.assertEqual(recovered["state"], "cancelled")
        self.assertEqual(recovered["total_tokens"], 120)
        self.assertEqual(len(self.requests), 1)

    def test_old_session_unknown_capacity_and_budget_failure_do_not_invent_actual_usage(self):
        initial = self.service.context_status(self.id)
        self.assertEqual(initial["snapshot"], {})
        self.assertEqual(initial["capacity"], 0)
        self.store.save_profile(replace(self.profile, context_tokens=5000))
        self.send("大问题" * 1000)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.service.context_status(self.id)["snapshot"]["state"], "failed")

    def test_real_dialog_minimum_layout_and_session_switch(self):
        gc.collect()
        root = tk.Tk()
        root.withdraw()
        dialog = AiDiagnosticsWindow(root, self.diag, lambda: (TARGET,), conversation=self.service)
        try:
            self.store.cache_model_contexts(self.profile, [{"id": self.profile.model, "context_tokens": 1048576}])
            response = chat("完成")
            response["usage"] = {"prompt_tokens": 200, "completion_tokens": 10}
            self.responses.append(response)
            self.send()
            dialog.open()
            panel = dialog.chat_panel
            dialog.window.geometry("940x660")
            for theme in ("vista", "clam"):
                with self.subTest(theme=theme):
                    ttk.Style(root).theme_use(theme)
                    dialog._apply_theme()
                    panel.refresh()
                    root.update()
                    widget = panel.context_status
                    self.assertEqual(widget.status_text.get(),
                                     "上下文容量：1,048,576 Token ｜ 当前上下文用量：210（0.02%）")
                    self.assertGreater(float(widget.progress.cget("value")), 0)
                    for child in (widget, widget.progress, panel.send_button, panel.input):
                        self.assertTrue(child.winfo_ismapped(),
                                        f"{child}: geometry={child.winfo_geometry()}, window={dialog.window.winfo_geometry()}")
                        self.assertLessEqual(child.winfo_rooty() + child.winfo_height(),
                                             dialog.window.winfo_rooty() + dialog.window.winfo_height())
                    self.assertGreater(panel.output.winfo_height(), 80)
            old = self.id
            other = self.service.create_session(TARGET, self.profile)
            panel.refresh()
            panel.sessions.current(panel.ids.index(other))
            panel.choose()
            self.assertIn("待下一次请求", panel.context_status.status_text.get())
            panel.sessions.current(panel.ids.index(old))
            panel.choose()
            self.assertIn("当前上下文用量：210", panel.context_status.status_text.get())
        finally:
            if dialog._poll_id:
                root.after_cancel(dialog._poll_id)
            dialog.window.destroy()
            root.destroy()
            del dialog, root
            gc.collect()


class UsageWidgetTests(unittest.TestCase):
    def test_compact_status_wraps_and_preserves_unknown_estimate_and_failure_states(self):
        gc.collect()
        root = tk.Tk()
        try:
            frame = AiContextStatus(root)
            frame.pack(fill="x")
            completed = {"state": "completed", "basis": "reply", "source": "api",
                         "input_tokens": 5700, "output_tokens": 49, "total_tokens": 5749,
                         "updated": "2026-11-12T12:29:44"}
            for theme in ("vista", "clam"):
                with self.subTest(theme=theme):
                    ttk.Style(root).theme_use(theme)
                    apply_module_theme(root)
                    root.geometry("900x240")
                    frame.show({"capacity": 1048576, "source": "模型接口（缓存）",
                                "max_output": 4096, "snapshot": completed})
                    root.update()
                    self.assertEqual(frame.status_text.get(),
                                     "上下文容量：1,048,576 Token ｜ 当前上下文用量：5,749（0.55%）")
                    labels = [child for child in frame.winfo_children() if isinstance(child, ttk.Label)]
                    self.assertEqual(labels, [frame.status_label])
                    self.assertAlmostEqual(float(frame.progress.cget("value")), 5749 / 1048576 * 100)
                    normal_height = frame.status_label.winfo_height()
                    root.geometry("320x240")
                    root.update()
                    self.assertGreater(frame.status_label.winfo_height(), normal_height)
                    self.assertLessEqual(frame.status_label.winfo_width(), frame.winfo_width())
                    self.assertTrue(frame.progress.winfo_ismapped())
            sample = {"state": "completed", "basis": "reply", "source": "estimate",
                      "input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
            frame.show({"capacity": 0, "max_output": 4096, "snapshot": sample})
            self.assertEqual(frame.status_text.get(), "上下文容量：未知 ｜ 当前上下文用量：约 120")
            frame.show({"capacity": 100, "source": "手动填写", "max_output": 4096, "snapshot": sample})
            self.assertEqual(frame.status_text.get(), "上下文容量：100 Token ｜ 当前上下文用量：约 120（120.00%）")
            self.assertEqual(float(frame.progress.cget("value")), 100)
            requesting = dict(sample, state="requesting", basis="input", output_tokens=None, total_tokens=100)
            frame.show({"capacity": 1000, "snapshot": requesting})
            self.assertEqual(frame.status_text.get(),
                             "上下文容量：1,000 Token ｜ 预计输入：约 100 Token（10.00%）；请求中")
            for state, message in (("failed", "本轮失败"), ("cancelled", "本轮已取消")):
                with self.subTest(state=state):
                    frame.show({"capacity": 1048576, "snapshot": dict(completed, state=state)})
                    self.assertIn("当前上下文用量：5,749（0.55%）", frame.status_text.get())
                    self.assertIn(message + "，保留已有用量", frame.status_text.get())
            frame.show({"capacity": 100, "snapshot": sample, "stale": True})
            self.assertIn("已过期", frame.status_text.get())
            self.assertNotIn("%", frame.status_text.get())
            self.assertEqual(float(frame.progress.cget("value")), 0)
            frame.show({"capacity": 1048576, "snapshot": {}})
            self.assertEqual(frame.status_text.get(), "上下文容量：1,048,576 Token ｜ 待下一次请求更新")
            frame.show()
            self.assertEqual(frame.status_text.get(), "上下文容量：选择会话后显示 ｜ 待下一次请求更新")
        finally:
            root.destroy()
            gc.collect()


if __name__ == "__main__":
    unittest.main()
