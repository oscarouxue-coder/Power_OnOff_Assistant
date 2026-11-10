"""离线协议/凭据/案例回归，禁止访问云端或真实设备。"""
import dataclasses
import gc
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.ai_client import DiagnosticModelClient, ModelServiceError
from src.core.ai_credentials import WindowsCredentialCipher
from src.models.ai_diagnostics import ProviderProfile
from src.services.ai_store import DiagnosticStore, canonical_url, profile_fingerprint
from src.utils.ai_redaction import DiagnosticRedactor


class FakeCipher:
    def encrypt(self, value, binding):
        return (binding + "\x00" + value[::-1]).encode()

    def decrypt(self, value, binding):
        prefix, text = value.decode().split("\x00", 1)
        if prefix != binding:
            raise ValueError("binding mismatch")
        return text[::-1]


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status_code, self.closed = data, status, False

    def iter_content(self, _size):
        yield json.dumps(self.data).encode()

    def close(self):
        self.closed = True


def chat(text="OK", calls=None, **extra):
    return {"choices": [{"message": {"role": "assistant", "content": text,
              **({"tool_calls": calls} if calls is not None else {}), **extra}}]}


def call(name="connection_test", args="{}"):
    return {"id": "call-1", "type": "function", "function": {"name": name, "arguments": args}}


DIAGNOSTIC_MATERIAL = {
    "ip": "192.168.1.101", "mask": "255.255.255.0", "gateway": "192.168.1.1",
    "dns": "192.168.1.1", "mac": "aa:bb:cc:dd:ee:ff", "ssid": "office room",
    "device": {"username": "root", "password": "test-password", "api_key": "dut-token"},
    "logs": ['SSID="office room" password=wifi-pass Bearer device-token sk-device-token',
             "option key 'wifi-pass'", "https://example.com/webhook?access_token=abc"],
}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DiagnosticStore(self.temp.name, FakeCipher())
        self.addCleanup(self.store.close)

    def test_profiles_and_credentials_are_isolated_and_recovered(self):
        first = self.store.save_profile(ProviderProfile(model="m", name="A"), "first-secret")
        second = self.store.save_profile(ProviderProfile(model="n", provider="MiniMax", name="B"), "second-secret")
        self.assertEqual(self.store.key(first), "first-secret")
        self.assertEqual(self.store.key(second), "second-secret")
        self.assertEqual([p.name for p in self.store.profiles()], ["A", "B"])
        raw = (Path(self.temp.name) / "diagnostics.sqlite3").read_bytes()
        self.assertNotIn(b"first-secret", raw)

    def test_endpoint_change_invalidates_key_and_verified_capability(self):
        profile = self.store.save_profile(ProviderProfile(model="m"), "secret")
        verified = dataclasses.replace(profile, capability="可自动诊断", tested_fingerprint=profile_fingerprint(profile))
        self.store.save_profile(verified)
        self.assertEqual(self.store.profiles()[0].capability, "可自动诊断")
        changed = self.store.save_profile(dataclasses.replace(verified, base_url="https://other.example/v1"))
        self.assertEqual(changed.capability, "未验证")
        with self.assertRaises(ValueError):
            self.store.key(changed)

    def test_key_and_model_changes_invalidate_capability_and_stale_test(self):
        profile = self.store.save_profile(ProviderProfile(model="m"), "secret")
        verified = dataclasses.replace(profile, capability="可自动诊断", tested_fingerprint=profile_fingerprint(profile))
        self.store.save_profile(verified)
        newer = self.store.save_profile(verified, "new-secret")
        self.assertNotEqual(profile_fingerprint(profile), profile_fingerprint(newer))
        self.assertEqual(newer.capability, "未验证")
        self.assertEqual(self.store.save_profile(dataclasses.replace(newer, model="another")).capability, "未验证")

    def test_missing_model_allowed_for_refresh_and_no_key_in_settings(self):
        saved = self.store.save_profile(ProviderProfile(), "secret")
        self.assertEqual(saved.model, "")
        self.store.set_setting("selected_profile", saved.id)
        self.assertEqual(self.store.setting("selected_profile"), saved.id)

    def test_only_confirmed_active_cases_are_retrieved_and_can_be_revised_deleted(self):
        self.store.save_report("r", {"report": "猜测WiFi断线"})
        self.assertEqual(self.store.cases("WiFi"), [])
        case = self.store.confirm_case("r", "WiFi断线", "驱动异常", "更新驱动", "双频复测通过", "Win11")
        self.assertEqual(self.store.cases("WiFi")[0]["id"], case)
        self.store.confirm_case("r", "WiFi断线", "服务异常", "启动服务", "复测通过", "Win11", case)
        self.assertEqual(self.store.cases("WiFi")[0]["cause"], "服务异常")
        self.store.update_case_state(case)
        self.assertEqual(self.store.cases("WiFi"), [])
        self.store.update_case_state(case)
        self.store.update_case_state(case, delete=True)
        self.assertEqual(self.store.cases(include_inactive=True), [])

    def test_incomplete_case_is_not_confirmed(self):
        with self.assertRaises(ValueError):
            self.store.confirm_case("r", "问题", "", "处理", "结果", "范围")

    def test_recovery_record_persists_until_restored(self):
        self.store.recovery("r", {"channel": 1})
        self.assertEqual(self.store.pending_recovery(), [("r", {"channel": 1})])
        self.store.recovery("r", {"channel": 1}, "restored")
        self.assertEqual(self.store.pending_recovery(), [])

    def test_canonical_url_rejects_credentials_queries_and_plain_http(self):
        for value in ("http://example.com", "https://a:b@example.com", "https://example.com?api_key=x", "https://example.com#x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_url(value)
        self.assertEqual(canonical_url("https://EXAMPLE.com/v1/"), "https://example.com/v1")


class RedactionTests(unittest.TestCase):
    def test_diagnostic_fields_and_nested_credentials_keep_real_values(self):
        redactor = DiagnosticRedactor(("model-auth-key",))
        raw = {**DIAGNOSTIC_MATERIAL, "max_tokens": 4096, "max_output_tokens": 4096, "tools": []}
        self.assertEqual(redactor.object(raw), raw)
        self.assertEqual(json.loads(redactor.dumps(raw)), raw)

    def test_ip_and_subnet_mask_are_never_replaced_by_aliases(self):
        redactor = DiagnosticRedactor()
        text = "192.168.1.1 192.168.1.2 255.255.255.0 192.168.1.1"
        self.assertEqual(redactor.text(text), text)

    def test_only_registered_model_keys_are_removed_from_values_and_keys(self):
        redactor = DiagnosticRedactor(("model-auth-key",))
        redactor.add_secrets(("second-model-key", None))
        raw = {"model-auth-key": ["Bearer model-auth-key", {"password": "second-model-key"}],
               "api_key": "dut-token", "secret": "sk-device-token"}
        text = redactor.dumps(raw)
        self.assertNotIn("model-auth-key", text)
        self.assertNotIn("second-model-key", text)
        self.assertIn("dut-token", text)
        self.assertIn("sk-device-token", text)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_real_dpapi_round_trip_and_binding(self):
        cipher = WindowsCredentialCipher()
        blob = cipher.encrypt("test-only-secret", "profile|https://example.com")
        self.assertNotIn(b"test-only-secret", blob)
        self.assertEqual(cipher.decrypt(blob, "profile|https://example.com"), "test-only-secret")
        with self.assertRaises(RuntimeError):
            cipher.decrypt(blob, "other-profile")


class ClientTests(unittest.TestCase):
    def client(self, responses, provider="DeepSeek", protocol="chat_completions"):
        session = Mock()
        session.request.side_effect = [FakeResponse(data, code) if isinstance(code, int) else code for data, code in responses]
        client = DiagnosticModelClient(ProviderProfile(provider=provider, protocol=protocol, model="test-model"),
                                       "test-key", DiagnosticRedactor(), session)
        return client, session

    def test_real_material_and_auth_only_key_across_both_protocol_tool_round_trips(self):
        for protocol in ("chat_completions", "responses"):
            with self.subTest(protocol=protocol):
                if protocol == "responses":
                    first = {"output": [{"type": "function_call", "name": "read_serial_log",
                                         "call_id": "call-1", "arguments": "{}"}]}
                    final = {"output": [{"type": "message", "content": [
                        {"type": "output_text", "text": json.dumps(DIAGNOSTIC_MATERIAL) + " test-key"}]}]}
                else:
                    first = chat(None, [call("read_serial_log")])
                    final = chat(json.dumps(DIAGNOSTIC_MATERIAL) + " test-key")
                client, session = self.client([(first, 200), (final, 200)], protocol=protocol)
                history = [{"role": "user", "content": client.redactor.dumps(DIAGNOSTIC_MATERIAL) + " test-key"}]
                reply = client.complete(history)
                tool = client.tool_result(reply.calls[0], {**DIAGNOSTIC_MATERIAL, "model_key": "test-key"})
                result = client.complete(reply.history + [tool])
                for request in session.request.call_args_list:
                    self.assertEqual(request.kwargs["headers"]["Authorization"], "Bearer test-key")
                    payload = request.kwargs["json"]
                    self.assertNotIn("test-key", json.dumps(payload))
                    messages = payload["input" if protocol == "responses" else "messages"]
                    content = messages[0]["content"].split(" <模型API密钥已隐藏>")[0]
                    self.assertEqual(json.loads(content), DIAGNOSTIC_MATERIAL)
                evidence = json.loads(tool["output" if protocol == "responses" else "content"])
                self.assertEqual({k: v for k, v in evidence.items() if k != "model_key"}, DIAGNOSTIC_MATERIAL)
                self.assertNotIn("test-key", result.text)
                self.assertEqual(json.loads(result.text.split(" <模型API密钥已隐藏>")[0]), DIAGNOSTIC_MATERIAL)

    def test_deepseek_and_minimax_tool_history_preserved(self):
        for provider in ("DeepSeek", "MiniMax"):
            with self.subTest(provider=provider):
                client, session = self.client([(chat(None, [call()], reasoning_content="protocol-thought"), 200), (chat("done"), 200)], provider)
                reply = client.complete([{"role": "user", "content": "test-key"}], [{"name": "connection_test", "parameters": {"type": "object", "properties": {}}}])
                self.assertEqual(reply.history[-1]["reasoning_content"], "protocol-thought")
                client.complete(reply.history + [client.tool_result(reply.calls[0], {"ok": True})])
                payload = session.request.call_args.kwargs["json"]
                self.assertEqual(payload["messages"][-2]["tool_calls"][0]["id"], "call-1")
                self.assertEqual(payload["messages"][-1]["tool_call_id"], "call-1")
                self.assertIn("max_completion_tokens" if provider == "MiniMax" else "max_tokens", payload)
                self.assertNotIn("test-key", json.dumps(payload))

    def test_responses_preserves_reasoning_and_function_call_ids(self):
        response = {"output": [{"type": "reasoning", "id": "rs1", "summary": []},
            {"type": "function_call", "name": "read_serial_log", "call_id": "c1", "arguments": "{}"}]}
        client, session = self.client([(response, 200)], "OpenAI", "responses")
        reply = client.complete([{"role": "user", "content": "x"}], [{"name": "read_serial_log", "parameters": {"type": "object", "properties": {}}}])
        self.assertEqual(reply.history[-2]["type"], "reasoning")
        self.assertEqual(client.tool_result(reply.calls[0], {})["call_id"], "c1")
        self.assertFalse(session.request.call_args.kwargs["json"]["store"])

    def test_connection_check_requires_tool_call_and_result_round_trip(self):
        client, _ = self.client([(chat(), 200), (chat(None, [call()]), 200), (chat(), 200)])
        self.assertEqual(client.test_connection()[0], "可自动诊断")

    def test_plain_text_fake_tool_is_never_executed(self):
        client, _ = self.client([(chat(), 200), (chat('connection_test({})'), 200)])
        self.assertEqual(client.test_connection()[0], "可问答")

    def test_tool_incompatibility_downgrades_question_only(self):
        client, _ = self.client([(chat(), 200), ({"error": "unsupported"}, 400)])
        self.assertEqual(client.test_connection()[0], "可问答")

    def test_http_errors_do_not_expose_raw_service_response_or_key(self):
        for code in (401, 403, 404, 429, 500, 302):
            client, session = self.client([({"error": "test-key"}, code)])
            with self.subTest(code=code), self.assertRaises(ModelServiceError) as caught:
                client.complete([])
            self.assertNotIn("test-key", str(caught.exception))
            self.assertFalse(session.request.call_args.kwargs["allow_redirects"])

    def test_cancelled_request_does_not_contact_service(self):
        client, session = self.client([])
        stop = threading.Event()
        stop.set()
        with self.assertRaises(InterruptedError):
            client.complete([], stop=stop)
        session.request.assert_not_called()

    def test_model_list_unsupported_reports_error_without_overwriting_model(self):
        client, _ = self.client([({}, 404)])
        with self.assertRaises(ModelServiceError):
            client.models()
        self.assertEqual(client.profile.model, "test-model")


if __name__ == "__main__":
    unittest.main()
