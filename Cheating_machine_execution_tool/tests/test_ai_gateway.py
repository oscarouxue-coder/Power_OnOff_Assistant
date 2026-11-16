"""公司网关离线回归；真实网络仅使用本机回环TCP，不读取真实密钥。"""
import dataclasses
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.ai_client import DiagnosticModelClient, ModelServiceError, request_url
from src.core.ai_gateway_network import _probe, collect_gateway_network, proxy_snapshot, transport_error
from src.models.ai_diagnostics import ProviderProfile
from src.services.ai_store import DiagnosticStore, canonical_url, profile_fingerprint
from src.utils.ai_redaction import DiagnosticRedactor
from test_ai_core import FakeCipher, FakeResponse, chat, call


GATEWAY = "http://10.10.120.244:4000"


class GatewayAddressTests(unittest.TestCase):
    def test_only_exact_authorized_http_origin_is_allowed(self):
        for suffix in ("", "/", "/v1", "/chat/completions", "/v1/chat/completions/"):
            with self.subTest(suffix=suffix):
                self.assertEqual(canonical_url(GATEWAY + suffix), (GATEWAY + suffix).rstrip("/"))
        for value in ("http://10.10.120.245:4000", "http://10.10.120.244:4001",
                      "http://10.10.120.244", "http://10.10.120.244:04000",
                      "http://10.10.120.244.evil:4000", "http://10.10.120.244:4000@evil",
                      "http://user@10.10.120.244:4000", GATEWAY + "?key=secret",
                      GATEWAY + "#secret", "http://localhost:4000", "http://example.com"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_url(value)
        self.assertEqual(canonical_url("https://EXAMPLE.com/prefix/v1/"), "https://example.com/prefix/v1")

    def test_path_matrix_and_model_list_preserve_explicit_prefix(self):
        for origin in (GATEWAY, "https://example.com/prefix"):
            for prefix in ("", "/v1"):
                for suffix in ("", "/", "/chat/completions", "/chat/completions/"):
                    base = origin + prefix + suffix
                    with self.subTest(base=base):
                        self.assertEqual(request_url(base, "chat/completions"), origin + prefix + "/chat/completions")
                        self.assertEqual(request_url(base, "models"), origin + prefix + "/models")
        self.assertEqual(request_url("https://api.openai.com/v1/", "responses"),
                         "https://api.openai.com/v1/responses")

    def test_http_profile_round_trip_key_binding_and_capability_invalidation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DiagnosticStore(directory, FakeCipher())
            profile = store.save_profile(ProviderProfile(provider="MiniMax", base_url=GATEWAY,
                                        model="3rd-MiniMax-M3"), "test-only-key")
            verified = dataclasses.replace(profile, capability="可自动诊断", tested_fingerprint=profile_fingerprint(profile))
            store.save_profile(verified)
            store.close()
            store = DiagnosticStore(directory, FakeCipher())
            try:
                self.assertEqual(store.profiles()[0], verified)
                self.assertEqual(store.key(verified), "test-only-key")
                changed_model = store.save_profile(dataclasses.replace(verified, model="3rd-MiniMax-M3.1-Flash-Preview"))
                self.assertEqual(changed_model.capability, "未验证")
                self.assertEqual(store.key(changed_model), "test-only-key")
                changed_url = store.save_profile(dataclasses.replace(changed_model, base_url=GATEWAY + "/v1"))
                self.assertEqual(changed_url.tested_fingerprint, "")
                with self.assertRaises(ValueError):
                    store.key(changed_url)
            finally:
                store.close()


class GatewayClientTests(unittest.TestCase):
    def client(self, responses=(), model="3rd-MiniMax-M3"):
        session = Mock()
        session.request.side_effect = list(responses)
        logs = []
        client = DiagnosticModelClient(ProviderProfile(provider="MiniMax", base_url=GATEWAY,
            model=model), "test-only-key", DiagnosticRedactor(), session, logs.append)
        return client, session, logs

    def test_company_tool_round_trip_auth_and_logging(self):
        client, session, logs = self.client([FakeResponse(chat()), FakeResponse(chat(None, [call()])), FakeResponse(chat())])
        self.assertEqual(client.test_connection()[0], "可自动诊断")
        self.assertEqual(session.request.call_count, 3)
        for item in session.request.call_args_list:
            self.assertEqual(item.args[:2], ("POST", GATEWAY + "/chat/completions"))
            self.assertEqual(item.kwargs["headers"]["Authorization"], "Bearer test-only-key")
            self.assertFalse(item.kwargs["allow_redirects"])
            self.assertNotIn("source_address", item.kwargs)
            self.assertNotIn("proxies", item.kwargs)
        self.assertIn("TX POST " + GATEWAY, "\n".join(logs))
        self.assertIn("成功", "\n".join(logs))
        self.assertNotIn("test-only-key", "\n".join(logs))

    def test_failed_tool_does_not_grant_diagnostic_capability(self):
        client, _, _ = self.client([FakeResponse(chat()), FakeResponse({"error": "test-only-key"}, 400)])
        self.assertEqual(client.test_connection()[0], "可问答")

    def test_manual_model_ids_are_sent_verbatim_without_switching(self):
        for model in ("3rd-MiniMax-M3", "3rd-MiniMax-M3.1-Flash-Preview"):
            with self.subTest(model=model):
                client, session, _ = self.client([FakeResponse(chat())], model=model)
                client.complete([])
                payload = session.request.call_args.kwargs["json"]
                self.assertEqual(payload["model"], model)
                self.assertIn("max_completion_tokens", payload)

    def test_company_full_endpoint_stream_keeps_complete_text(self):
        client, session, _ = self.client()
        client.profile = dataclasses.replace(client.profile, base_url=GATEWAY + "/v1/chat/completions/")
        response = Mock(status_code=200)
        response.iter_content.return_value = iter([b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\n',
                                                    b'data: [DONE]\n\n'])
        session.request.side_effect = [response]
        preview = []
        reply = client.complete_stream([], on_text=preview.append)
        self.assertEqual(reply.text, "OK")
        self.assertEqual(preview[-1], "OK")
        self.assertEqual(session.request.call_args.args[1], GATEWAY + "/v1/chat/completions")
        self.assertTrue(session.request.call_args.kwargs["json"]["stream"])
        response.close.assert_called_once()

    def test_http_errors_do_not_probe_network_or_retry_paths(self):
        for code in (401, 403, 404, 429, 302):
            client, session, logs = self.client([FakeResponse({"error": "test-only-key"}, code)])
            with self.subTest(code=code), patch("src.core.ai_client.collect_gateway_network") as probe:
                with self.assertRaises(ModelServiceError) as caught:
                    client.complete([])
                probe.assert_not_called()
                self.assertEqual(session.request.call_count, 1)
                self.assertIn(GATEWAY + "/chat/completions", str(caught.exception))
                self.assertNotIn("test-only-key", str(caught.exception) + "\n".join(logs))

    def test_network_failures_diagnose_without_replay_and_hide_raw_error(self):
        for error in (requests.ConnectTimeout("Bearer test-only-key"), requests.ReadTimeout("test-only-key"),
                      requests.exceptions.ProxyError("http://proxy-user:proxy-password@proxy"),
                      requests.exceptions.SSLError("test-only-key"), requests.ConnectionError("test-only-key")):
            client, session, logs = self.client([error])
            with self.subTest(error=type(error).__name__), patch("src.core.ai_client.collect_gateway_network", return_value="当前探测") as probe:
                with self.assertRaises(ModelServiceError) as caught:
                    client.complete([])
                self.assertEqual(session.request.call_count, 1)
                probe.assert_called_once()
                text = str(caught.exception) + "\n".join(logs)
                self.assertIn(type(error).__name__, text)
                self.assertIn("当前探测", text)
                self.assertNotIn("test-only-key", text)
                self.assertNotIn("proxy-password", text)

    def test_cancelled_transport_error_skips_probe(self):
        stop = threading.Event()
        client, session, _ = self.client()
        def fail(*_args, **_kwargs):
            stop.set()
            raise requests.ConnectionError("private")
        session.request.side_effect = fail
        with patch("src.core.ai_client.collect_gateway_network") as probe:
            with self.assertRaises(InterruptedError):
                client.complete([], stop=stop)
            probe.assert_not_called()


class NetworkEvidenceTests(unittest.TestCase):
    def test_proxy_snapshot_preserves_session_and_omits_authentication(self):
        session = requests.Session()
        session.trust_env = False
        session.proxies = {"http": "http://proxy-user:proxy-password@proxy.example:8080"}
        self.addCleanup(session.close)
        original = dict(session.proxies)
        result = proxy_snapshot(session, GATEWAY)
        self.assertEqual(result["status"], "proxy")
        self.assertEqual(result["endpoint"], {"label": "代理", "host": "proxy.example", "port": 8080})
        self.assertNotIn("proxy-password", json.dumps(result))
        self.assertEqual(session.proxies, original)
        self.assertFalse(session.trust_env)

    def test_environment_proxy_no_proxy_and_disabled_environment(self):
        session = requests.Session()
        self.addCleanup(session.close)
        with patch.dict(os.environ, {"HTTP_PROXY": "http://user:password@proxy.example:8888",
                                     "NO_PROXY": "10.10.120.244"}, clear=True):
            self.assertEqual(proxy_snapshot(session, GATEWAY)["status"], "direct")
            self.assertTrue(proxy_snapshot(session, GATEWAY)["no_proxy_bypass"])
            with patch.dict(os.environ, {"NO_PROXY": "elsewhere"}):
                self.assertEqual(proxy_snapshot(session, GATEWAY)["status"], "proxy")
                self.assertFalse(proxy_snapshot(session, GATEWAY)["no_proxy_bypass"])
                session.trust_env = False
                self.assertEqual(proxy_snapshot(session, GATEWAY)["status"], "direct")

    def test_error_classification_uses_nested_codes_and_never_raw_message(self):
        error = requests.ConnectionError(socket.gaierror(11001, "private-secret"))
        self.assertIn("DNS", transport_error(error))
        self.assertIn("11001", transport_error(error))
        self.assertNotIn("private-secret", transport_error(error))
        self.assertIn("代理", transport_error(requests.exceptions.ProxyError("private-secret")))
        self.assertIn("TLS", transport_error(requests.exceptions.SSLError("private-secret")))

    def test_no_proxy_does_not_claim_bypass_when_session_proxy_still_applies(self):
        session = requests.Session()
        session.proxies = {"http": "http://proxy.example:8080"}
        self.addCleanup(session.close)
        with patch.dict(os.environ, {"NO_PROXY": "10.10.120.244"}, clear=True):
            result = proxy_snapshot(session, GATEWAY)
        self.assertEqual(result["status"], "proxy")
        self.assertFalse(result["no_proxy_bypass"])

    def test_actual_tcp_interface_is_distinct_from_inferred_route(self):
        records = [dict(kind="tcp", label="网关", ips=["10.10.120.244"], status="connected", source="10.10.112.18", peer="10.10.120.244"),
                   dict(kind="interface", label="网关", source="10.10.112.18", matches=[dict(name="办公网", index=7)]),
                   dict(kind="route", label="网关", status="ok", interface="另一网卡", index=8, source="10.10.112.19")]
        with patch("src.core.ai_gateway_network._probe", return_value=(records, "")) as probe:
            text = collect_gateway_network(GATEWAY, {"status": "direct"})
        self.assertEqual(probe.call_args.args[0], [{"label": "网关", "host": "10.10.120.244", "port": 4000}])
        self.assertIn("原失败HTTP请求实际接口/源IP=未知", text)
        self.assertIn("对应接口=办公网/7", text)
        self.assertIn("接口=另一网卡/8", text)
        self.assertIn("路由推断", text)
        self.assertIn("端口可连接", text)

    def test_proxy_and_gateway_are_probed_as_separate_endpoints(self):
        with patch("src.core.ai_gateway_network._probe", return_value=([], "")) as probe:
            text = collect_gateway_network(GATEWAY, {"status": "proxy", "endpoint": dict(label="代理", host="proxy.example", port=8080)})
        self.assertEqual(len(probe.call_args.args[0]), 2)
        self.assertIn("命中代理 proxy.example:8080", text)

    def test_probe_failure_does_not_hide_original_error_or_leak_stderr(self):
        with patch("src.core.ai_gateway_network._probe", side_effect=RuntimeError("test-secret")):
            text = collect_gateway_network(GATEWAY, {"status": "unknown"})
        self.assertIn("网络诊断失败：RuntimeError", text)
        self.assertNotIn("test-secret", text)
        self.assertIn("未知", text)

    def test_stop_skips_diagnostics(self):
        stop = threading.Event()
        stop.set()
        with patch("src.core.ai_gateway_network.subprocess.Popen") as popen:
            with self.assertRaises(InterruptedError):
                collect_gateway_network(GATEWAY, {"status": "direct"}, stop)
            popen.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows只读探测")
    def test_probe_deadline_keeps_partial_evidence_and_kills_process(self):
        process = Mock()
        process.__enter__ = Mock(return_value=process)
        process.__exit__ = Mock(return_value=False)
        process.poll.return_value = 0
        process.communicate.side_effect = [subprocess.TimeoutExpired("powershell", .2),
            (b'AIGW:{"kind":"tcp","status":"tcp_timeout"}\n', b"private stderr")]
        with patch("src.core.ai_gateway_network.subprocess.Popen", return_value=process), patch(
                "src.core.ai_gateway_network.time.monotonic", side_effect=[0, 0, 9]):
            records, note = _probe([dict(label="网关", host="127.0.0.1", port=1)], None)
        self.assertEqual(records[0]["status"], "tcp_timeout")
        self.assertIn("8秒", note)
        process.kill.assert_called_once()

    @unittest.skipUnless(os.name == "nt", "Windows只读探测")
    def test_subprocess_uses_fixed_script_and_stdin_for_target(self):
        process = Mock()
        process.__enter__ = Mock(return_value=process)
        process.__exit__ = Mock(return_value=False)
        process.poll.return_value = 0
        process.returncode = 0
        process.communicate.return_value = (b'AIGW:{"kind":"tcp","label":"gateway","status":"dns_failed"}\n', b"private stderr")
        host = "private-host';Write-Output injected;#"
        with patch("src.core.ai_gateway_network.subprocess.Popen", return_value=process) as popen:
            records, _ = _probe([dict(label="gateway", host=host, port=1)], None)
        self.assertNotIn(host, " ".join(popen.call_args.args[0]))
        data = json.loads(process.communicate.call_args.kwargs["input"])
        self.assertEqual(data[0]["host"], host)
        self.assertEqual(records[0]["status"], "dns_failed")

    @unittest.skipUnless(os.name == "nt", "Windows只读探测")
    def test_cancelled_running_probe_cleans_up_process(self):
        process = Mock()
        process.__enter__ = Mock(return_value=process)
        process.__exit__ = Mock(return_value=False)
        process.poll.return_value = None
        stop = Mock()
        stop.is_set.side_effect = [False, True]
        with patch("src.core.ai_gateway_network.subprocess.Popen", return_value=process):
            with self.assertRaises(InterruptedError):
                _probe([dict(label="网关", host="127.0.0.1", port=1)], stop)
        process.kill.assert_called_once()
        process.communicate.assert_called_once()

    @unittest.skipUnless(os.name == "nt", "仅本机回环TCP；不访问公司网关")
    def test_real_powershell_loopback_success_and_closed_port(self):
        with socket.socket() as listening, socket.socket() as refused:
            listening.bind(("127.0.0.1", 0))
            listening.listen(1)
            refused.bind(("127.0.0.1", 0))
            records, _ = _probe([dict(label="网关", host="127.0.0.1", port=listening.getsockname()[1]),
                                 dict(label="代理", host="127.0.0.1", port=refused.getsockname()[1])], None)
        tcp = {r["label"]: r for r in records if r.get("kind") == "tcp"}
        self.assertEqual(tcp["网关"]["status"], "connected")
        self.assertEqual(tcp["网关"]["source"], "127.0.0.1")
        # Windows对未监听端口可能先静默丢弃SYN；不能把探测时限内未回复伪装成拒绝。
        self.assertIn(tcp["代理"]["status"], ("tcp_failed", "tcp_timeout"))
        if tcp["代理"]["status"] == "tcp_failed":
            self.assertTrue(tcp["代理"]["code"])


if __name__ == "__main__":
    unittest.main()
