"""上下文预算与自动容量的离线回归；使用临时数据库和假HTTPS响应。"""
from dataclasses import asdict, replace
import gc
import json
from pathlib import Path
import sys
import tempfile
import threading
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.ai_client import ContextLengthError, DiagnosticModelClient, ModelServiceError
from src.models.ai_diagnostics import ProviderProfile
from src.services.ai_context_budget import (ContextCapacity, ContextBudgetError, ConversationBudget,
                                            context_capacity, refresh_model_context)
from src.services.ai_store import DiagnosticStore, profile_fingerprint
from src.ui.ai_diagnostics_window import AiDiagnosticsWindow
from src.utils.ai_redaction import DiagnosticRedactor
import test_ai_conversation as conversation_tests
from test_ai_core import FakeCipher, FakeResponse, chat, call
from test_ai_debug import TARGET


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


def group(text="历史"):
    return [{"role": "user", "content": text}, {"role": "assistant", "content": "答复"}]


class ContextBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DiagnosticStore(self.temp.name, FakeCipher())
        self.addCleanup(self.store.close)
        self.profile = ProviderProfile(model="m")
        self.client = DiagnosticModelClient(self.profile, "test-key", DiagnosticRedactor(), Mock())
        self.addCleanup(self.client.close)

    def budget(self, groups=(), current=None, tokens=0, output=4096):
        return ConversationBudget(groups, [{"role": "system", "content": "系统"}],
                                  current if current is not None else group("当前"),
                                  ContextCapacity(tokens), output, dumps)

    def test_unknown_keeps_latest_50_whole_groups(self):
        groups = [group(str(i)) for i in range(51)]
        budget = self.budget(groups)
        self.assertEqual(budget.groups, groups[1:])
        self.assertEqual(budget.skipped, 1)

    def test_character_boundary_counts_serialized_protocol(self):
        item = group("")
        padding = 100000 - len(dumps(item))
        item = group("x" * padding)
        self.assertEqual(len(dumps(item)), 100000)
        self.assertEqual(len(self.budget([item]).groups), 1)
        self.assertEqual(self.budget([group("x" * (padding + 1))]).groups, [])
        self.assertEqual(self.budget([group("old"), item]).groups, [item])

    def test_known_capacity_has_no_round_or_character_cap(self):
        groups = [group("x" * 2100) for _ in range(60)]
        budget = self.budget(groups, tokens=1000000)
        budget.fit(self.client, [])
        self.assertEqual(budget.groups, groups)
        self.assertGreater(sum(len(dumps(g)) for g in budget.groups), 100000)

    def test_budget_covers_output_margin_tools_prefix_and_current(self):
        current = group("当前问题")
        budget = self.budget([group("旧" * 1000)], current, tokens=6000)
        history, estimated = budget.fit(self.client, [])
        self.assertEqual(budget.skipped, 1)
        self.assertEqual(current, group("当前问题"))
        self.assertLessEqual(estimated + 4096 + 300, 6000)
        huge_tool = [{"name": "t", "description": "x" * 8000, "parameters": {}}]
        with self.assertRaisesRegex(ContextBudgetError, "当前问题及本轮工具链未截断"):
            budget.fit(self.client, huge_tool)
        self.assertEqual(history[0]["role"], "system")

    def test_utf8_estimate_for_chinese_and_english_and_both_protocols(self):
        for protocol in ("chat_completions", "responses"):
            self.client.profile = replace(self.profile, protocol=protocol)
            for text in ("中英文mixed", "English only"):
                budget = self.budget(current=group(text), tokens=100000)
                history, estimated = budget.fit(self.client, [])
                self.assertEqual(estimated, len(dumps(self.client.request_payload(history)).encode("utf-8")))

    def test_manual_priority_cache_isolation_and_restart(self):
        self.store.cache_model_contexts(self.profile, [{"id": "m", "context_tokens": 128000}])
        self.assertEqual(context_capacity(self.store, self.profile).tokens, 128000)
        self.assertEqual(context_capacity(self.store, replace(self.profile, context_tokens=32000)).tokens, 32000)
        for other in (replace(self.profile, model="other"), replace(self.profile, base_url="https://other.example/v1")):
            self.assertEqual(context_capacity(self.store, other).tokens, 0)
        self.store.cache_model_contexts(self.profile, [{"id": "m", "context_tokens": 0}])
        reopened = DiagnosticStore(self.temp.name, FakeCipher())
        try:
            self.assertEqual(context_capacity(reopened, self.profile).tokens, 128000)
        finally:
            reopened.close()

    def test_old_profile_and_context_only_change_keep_fingerprint(self):
        profile = self.store.save_profile(self.profile, "test-key")
        verified = replace(profile, capability="可自动诊断", tested_fingerprint=profile_fingerprint(profile))
        self.store.save_profile(verified)
        changed = self.store.save_profile(replace(verified, context_tokens=64000))
        self.assertEqual(changed.capability, "可自动诊断")
        self.assertEqual(profile_fingerprint(changed), profile_fingerprint(profile))
        old = asdict(changed)
        del old["context_tokens"]
        with self.store.lock, self.store.db:
            self.store.db.execute("UPDATE profiles SET payload=? WHERE id=?", (dumps(old), profile.id))
        self.assertEqual(self.store.profiles()[0].context_tokens, 0)
        for invalid in (-1, "1000", True):
            with self.assertRaises(ValueError):
                self.store.save_profile(replace(profile, context_tokens=invalid))

    def test_model_metadata_fields_and_id_only_compatibility(self):
        self.client.session.request.return_value = FakeResponse({"data": [
            {"id": "m", "context_window": 128000}, {"id": "bare"},
            {"id": "other", "context_length": 64000}, {"id": "bad", "context_window": True}]})
        models = refresh_model_context(self.store, self.client)
        self.assertEqual(tuple(m["id"] for m in models), ("m", "bare", "other", "bad"))
        self.assertEqual(context_capacity(self.store, self.profile).tokens, 128000)
        self.assertEqual(self.store.model_context(replace(self.profile, model="bad")), 0)
        self.client.session.request.return_value = FakeResponse({}, 404)
        with self.assertRaises(ModelServiceError):
            refresh_model_context(self.store, self.client)
        self.assertEqual(self.store.model_context(self.profile), 128000)

    def test_context_error_classification_never_exposes_server_text(self):
        for protocol in ("chat_completions", "responses"):
            self.client.profile = replace(self.profile, protocol=protocol)
            for error in ({"code": "context_length_exceeded", "message": "test-key"},
                          {"message": "maximum context length exceeded test-key"}):
                self.client.session.request.return_value = FakeResponse({"error": error}, 400)
                with self.assertRaises(ContextLengthError) as caught:
                    self.client.complete([])
                self.assertNotIn("test-key", str(caught.exception))
        for status, error in ((400, {"message": "invalid parameter test-key"}),
                              (429, {"code": "context_length_exceeded"})):
            self.client.session.request.return_value = FakeResponse({"error": error}, status)
            with self.assertRaises(ModelServiceError) as caught:
                self.client.complete([])
            self.assertNotIsInstance(caught.exception, ContextLengthError)

    def test_current_tool_chain_is_never_split_and_history_halves(self):
        current = group("当前") + [{"role": "tool", "tool_call_id": "t", "content": "结果"}]
        budget = self.budget([group(str(i)) for i in range(5)], current)
        self.assertTrue(budget.halve_history())
        self.assertEqual(len(budget.groups), 2)
        self.assertEqual(budget.history()[-3:], current)


class ContextConversationTests(unittest.TestCase):
    setUp = conversation_tests.ConversationTests.setUp
    stop_services = conversation_tests.ConversationTests.stop_services
    send = conversation_tests.ConversationTests.send

    def seed(self, count=8, text="较早问题"):
        for i in range(count):
            self.store.append_chat(self.id, group(text + str(i)), group=True)

    def test_automatic_discovery_and_metadata_reuse(self):
        self.model_data = [{"id": "offline", "context_window": 1000000}]
        self.seed(60)
        self.send("继续")
        self.assertEqual(self.store.model_context(self.profile), 1000000)
        self.assertEqual(len([m for m in self.requests[-1]["messages"] if m.get("role") == "user"]), 61)
        self.assertTrue(any("来源=模型接口" in line for line in self.logs))
        self.model_data = [{"id": "offline", "context_window": 2000000}]
        self.send("再次继续")
        self.assertEqual(self.store.model_context(self.profile), 1000000)

    def test_existing_session_uses_changed_capacity_without_losing_authorization(self):
        self.seed(60)
        self.store.save_profile(replace(self.profile, context_tokens=1000000))
        self.assertEqual(self.send()["status"], "可继续")
        self.assertTrue(self.service.authorized(self.id))
        self.assertEqual(len([m for m in self.requests[-1]["messages"] if m.get("role") == "user"]), 61)

    def test_server_retry_halves_history_and_preserves_original_groups(self):
        self.seed()
        error = FakeResponse({"error": {"code": "context_length_exceeded", "message": "model-secret"}}, 400)
        self.responses.extend([error, error, chat("成功")])
        self.assertEqual(self.send()["status"], "可继续")
        self.assertEqual(len(self.requests), 3)
        self.assertEqual([len(r["messages"]) for r in self.requests], [18, 10, 6])
        self.assertEqual(len(self.store.chat_items(self.id, group=True)), 9)
        self.assertFalse(any("model-secret" in line for line in self.logs))

    def test_retry_exhaustion_has_three_requests_and_retains_current(self):
        self.seed()
        self.responses.extend([FakeResponse({"error": {"code": "context_length_exceeded"}}, 400) for _ in range(3)])
        self.assertEqual(self.send("保留问题")["status"], "失败，可继续")
        self.assertEqual(len(self.requests), 3)
        self.assertIn("保留问题", dumps(self.store.chat_items(self.id, group=True)[-1]))

    def test_two_retry_limit_is_shared_across_all_interactions(self):
        self.seed(16)
        error = FakeResponse({"error": {"code": "context_length_exceeded"}}, 400)
        tool_reply = chat("", [call("read_test_evidence", '{"query":"现场"}')])
        self.responses.extend([error, tool_reply, error, tool_reply, error])
        with patch.object(self.service, "search", return_value={"text": "材料"}) as search:
            self.assertEqual(self.send()["status"], "失败，可继续")
            self.assertEqual(search.call_count, 2)
        self.assertEqual(len(self.requests), 5)

    def test_context_retry_after_tool_does_not_reexecute_it(self):
        self.seed()
        self.responses.extend([chat("", [call("read_test_evidence", '{"query":"较早"}')]),
            FakeResponse({"error": {"code": "context_length_exceeded"}}, 400), chat("已完成")])
        with patch.object(self.service, "search", wraps=self.service.search) as search:
            self.assertEqual(self.send()["status"], "可继续")
            self.assertEqual(search.call_count, 1)
        final = self.requests[-1]["messages"]
        self.assertEqual(len([m for m in final if m.get("role") == "tool"]), 1)
        saved = self.store.chat_items(self.id, group=True)[-1]
        self.assertEqual(len([m for m in saved if m.get("role") == "tool"]), 1)
        self.assertTrue(any(m.get("tool_calls") for m in saved))

    def test_responses_protocol_context_retry_preserves_call_ids(self):
        changed = self.store.save_profile(replace(self.profile, protocol="responses"))
        changed = replace(changed, capability="可自动诊断", tested_fingerprint=profile_fingerprint(changed))
        self.store.save_profile(changed)
        self.id = self.service.create_session(TARGET, changed)
        self.seed()
        self.responses.extend([{"output": [{"type": "function_call", "call_id": "c1",
                                            "name": "read_test_evidence", "arguments": '{"query":"较早"}'}]},
            FakeResponse({"error": {"code": "context_length_exceeded"}}, 400),
            {"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "OK"}]}]}])
        with patch.object(self.service, "search", wraps=self.service.search) as search:
            self.assertEqual(self.send()["status"], "可继续")
            self.assertEqual(search.call_count, 1)
        self.assertTrue(any(m.get("type") == "function_call_output" and m["call_id"] == "c1"
                            for m in self.requests[-1]["input"]))

    def test_budget_failure_preserves_full_question_without_posting(self):
        self.store.save_profile(replace(self.profile, context_tokens=5000))
        question = "当前问题" * 1000
        self.assertEqual(self.send(question)["status"], "失败，可继续")
        self.assertEqual(self.requests, [])
        self.assertIn(question, dumps(self.store.chat_items(self.id, group=True)[-1]))
        self.assertTrue(any("上下文预算不足" in line for line in self.logs))

    def test_budget_rechecked_after_tool_growth_preserves_result(self):
        self.store.save_profile(replace(self.profile, context_tokens=30000))
        self.responses.append(chat("", [call("read_test_evidence", '{"query":"现场"}')]))
        with patch.object(self.service, "search", return_value={"text": "现场" * 10000}) as search:
            self.assertEqual(self.send()["status"], "失败，可继续")
            self.assertEqual(search.call_count, 1)
        self.assertEqual(len(self.requests), 1)
        saved = self.store.chat_items(self.id, group=True)[-1]
        self.assertTrue(any(m.get("role") == "tool" and "现场" in m["content"] for m in saved))
        self.assertTrue(any("上下文预算不足" in line for line in self.logs))

    def test_non_context_service_error_does_not_retry(self):
        self.seed()
        self.responses.append(FakeResponse({"error": {"message": "invalid argument"}}, 400))
        self.assertEqual(self.send()["status"], "失败，可继续")
        self.assertEqual(len(self.requests), 1)

    def test_cancel_between_context_retries_stops_requesting(self):
        self.seed()
        original = self.diag.client_factory
        def factory(*args):
            client = original(*args)
            def complete(*_args):
                self.service.stop(self.id)
                raise ContextLengthError("context")
            client.complete = Mock(side_effect=complete)
            self.test_client = client
            return client
        self.diag.client_factory = factory
        self.assertEqual(self.send()["status"], "已停止")
        self.assertEqual(self.test_client.complete.call_count, 1)

    def test_unknown_context_shows_fallback_and_single_message_limit_unchanged(self):
        self.send()
        self.assertTrue(any("50轮 / 100000字符" in line for line in self.logs))
        with self.assertRaisesRegex(ValueError, "32768"):
            self.service.send(self.id, "x" * 32769)

    def test_tk_context_field_source_save_and_reload_in_both_themes(self):
        gc.collect()
        root = tk.Tk()
        root.withdraw()
        dialog = AiDiagnosticsWindow(root, self.diag, lambda: (TARGET,), conversation=self.service)
        try:
            dialog.open()
            connection = dialog.model_choice.master.master
            connection.master.select(connection)
            for theme in ("vista", "clam"):
                if theme in tk.ttk.Style(root).theme_names():
                    tk.ttk.Style(root).theme_use(theme)
                dialog.window.geometry("940x660")
                connection.master.select(connection)
                root.update()
                root.update_idletasks()
                for widget in connection.winfo_children():
                    self.assertLessEqual(widget.winfo_y() + widget.winfo_height(), connection.winfo_height())
                for widget in dialog.model_choice.master.winfo_children():
                    self.assertLessEqual(widget.winfo_x() + widget.winfo_width(), dialog.model_choice.master.winfo_width())
                self.assertIn("50轮 / 100000字符", dialog.context_status.get())
                dialog.vars["context_tokens"].set("128000")
                saved = dialog._save()
                self.assertEqual(saved.context_tokens, 128000)
                self.assertIn("手动填写", dialog.context_status.get())
                dialog._reload_profiles(saved.id)
                self.assertEqual(dialog.vars["context_tokens"].get(), "128000")
                dialog.vars["context_tokens"].set("")
                self.assertEqual(dialog._save().context_tokens, 0)
                self.store.cache_model_contexts(self.profile, [{"id": "offline", "context_tokens": 256000}])
                dialog._update_context_status()
                self.assertIn("256000", dialog.context_status.get())
                self.assertIn("模型接口", dialog.context_status.get())
                # 下一主题从未知容量开始。
                self.store.set_setting(self.store._model_context_key(self.profile.base_url, self.profile.model), 0)
                dialog._update_context_status()
            with patch.object(dialog, "_error") as error:
                dialog.vars["context_tokens"].set("0")
                self.assertIsNone(dialog._save())
                error.assert_called_once()
        finally:
            if dialog._poll_id:
                root.after_cancel(dialog._poll_id)
            dialog.window.destroy()
            root.destroy()
            gc.collect()


if __name__ == "__main__":
    unittest.main()
