"""出口选择、配置兼容及真实本机 HTTP/TLS 连接；不连接外部服务或设备。"""
from contextlib import ExitStack
from dataclasses import asdict, replace
from datetime import datetime, timedelta
import gc
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import queue
import select
import socket
import ssl
import tempfile
import threading
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from src.core.ai_client import DiagnosticModelClient, ModelServiceError
from src.core.ai_gateway_network import collect_gateway_network, _probe
from src.core.ai_source_ip import SourceIpAdapter, list_source_ips, normalize_source_ip, require_source_ip
from src.models.ai_diagnostics import ProviderProfile
from src.services.ai_store import DiagnosticStore, profile_fingerprint
from src.ui.ai_diagnostics_window import AiDiagnosticsWindow
from src.ui.ai_source_ip_dialog import SourceIpDialog
from src.utils.ai_redaction import DiagnosticRedactor
from test_ai_core import FakeCipher, FakeResponse, chat, call
from tk_test_windows import OffscreenTkWindows


CHOICES = [dict(name="办公网", ip="192.168.8.2", available=True),
           dict(name="断开网卡", ip="192.168.9.2", available=False)]


class SourceIpTests(unittest.TestCase):
    def test_enumeration_preserves_adapter_identity_and_unavailable_addresses(self):
        addresses = {"办公网": [SimpleNamespace(family=socket.AF_INET, address="192.168.8.2"),
                              SimpleNamespace(family=socket.AF_INET6, address="::1")],
                     "断开网卡": [SimpleNamespace(family=socket.AF_INET, address="192.168.9.2")]}
        with patch("src.core.ai_source_ip.psutil.net_if_addrs", return_value=addresses), patch(
                "src.core.ai_source_ip.psutil.net_if_stats", return_value={"办公网": SimpleNamespace(isup=True)}):
            self.assertEqual(list_source_ips(), CHOICES)

    def test_invalid_source_and_automatic_default(self):
        for value in ("::1", "hostname", "0.0.0.0", "224.1.1.1", "255.255.255.255", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_source_ip(value)
        self.assertEqual(normalize_source_ip(" 192.168.8.2 "), "192.168.8.2")
        with patch("src.core.ai_source_ip.list_source_ips") as query:
            self.assertEqual(require_source_ip(""), "")
            query.assert_not_called()

    def test_missing_down_or_query_failure_never_falls_back(self):
        with patch("src.core.ai_source_ip.list_source_ips", return_value=CHOICES):
            self.assertEqual(require_source_ip("192.168.8.2"), "192.168.8.2")
            for value in ("192.168.9.2", "192.168.10.2"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    require_source_ip(value)
        with patch("src.core.ai_source_ip.list_source_ips", side_effect=OSError("unavailable")):
            with self.assertRaises(OSError):
                require_source_ip("192.168.8.2")

    def test_direct_and_proxy_pools_bind_source_without_changing_session_proxy_policy(self):
        session = requests.Session()
        self.addCleanup(session.close)
        session.proxies = {"https": "http://user:password@localhost:8888"}
        client = DiagnosticModelClient(ProviderProfile(source_ip="127.0.0.1"), "key", DiagnosticRedactor(), session)
        self.assertTrue(session.trust_env)
        self.assertEqual(session.proxies["https"], "http://user:password@localhost:8888")
        for scheme in ("http://", "https://"):
            adapter = session.get_adapter(scheme)
            self.assertEqual(adapter.poolmanager.connection_pool_kw["source_address"], ("127.0.0.1", 0))
            proxy = adapter.proxy_manager_for(session.proxies["https"])
            self.assertEqual(proxy.connection_pool_kw["source_address"], ("127.0.0.1", 0))
        client.close()

    def test_unspecified_keeps_existing_adapters(self):
        session = requests.Session()
        adapters = dict(session.adapters)
        client = DiagnosticModelClient(ProviderProfile(), "key", DiagnosticRedactor(), session)
        self.assertEqual(dict(session.adapters), adapters)
        client.close()

    def test_preflight_failure_and_stop_prevent_request_and_network_probe(self):
        session = Mock()
        client = DiagnosticModelClient(ProviderProfile(source_ip="192.168.8.2"), "secret", DiagnosticRedactor(), session)
        with patch("src.core.ai_client.require_source_ip", side_effect=ValueError("出口不可用")), patch(
                "src.core.ai_client.collect_gateway_network") as probe:
            with self.assertRaisesRegex(ModelServiceError, "出口不可用"):
                client.models()
            session.request.assert_not_called()
            probe.assert_not_called()
        stop = threading.Event()
        stop.set()
        with patch("src.core.ai_client.require_source_ip") as preflight:
            with self.assertRaises(InterruptedError):
                client.models(stop)
            preflight.assert_not_called()

    def test_network_evidence_passes_source_to_gateway_and_proxy_without_mutation(self):
        proxy = dict(status="proxy", endpoint=dict(label="代理", host="localhost", port=8080))
        original = json.dumps(proxy)
        with patch("src.core.ai_gateway_network._probe", return_value=([], "")) as probe:
            detail = collect_gateway_network("https://example.com", proxy, source_ip="192.168.8.2")
        self.assertTrue(all(item["source_ip"] == "192.168.8.2" for item in probe.call_args.args[0]))
        self.assertEqual(json.dumps(proxy), original)
        self.assertIn("配置源IP=192.168.8.2", detail)
        self.assertIn("原失败HTTP请求实际接口/源IP=未知", detail)

    def test_transport_failure_reports_selected_source_once_without_replay(self):
        session = Mock()
        session.request.side_effect = requests.ConnectionError("secret")
        client = DiagnosticModelClient(ProviderProfile(source_ip="192.168.8.2"), "secret", DiagnosticRedactor(), session)
        with patch("src.core.ai_client.require_source_ip"), patch(
                "src.core.ai_client.collect_gateway_network", return_value="当前探测") as probe:
            with self.assertRaises(ModelServiceError):
                client.models()
        self.assertEqual(session.request.call_count, 1)
        self.assertEqual(probe.call_args.kwargs["source_ip"], "192.168.8.2")

    def test_connection_tool_roundtrip_rechecks_same_source_for_every_request(self):
        session = Mock()
        session.request.side_effect = [FakeResponse(chat()), FakeResponse(chat(None, [call()])), FakeResponse(chat())]
        client = DiagnosticModelClient(ProviderProfile(source_ip="192.168.8.2"), "secret", DiagnosticRedactor(), session)
        with patch("src.core.ai_client.require_source_ip") as check:
            self.assertEqual(client.test_connection()[0], "可自动诊断")
        self.assertEqual([item.args[0] for item in check.call_args_list], ["192.168.8.2"] * 3)
        self.assertEqual(session.request.call_count, 3)


class SourceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DiagnosticStore(self.temp.name, FakeCipher())
        self.addCleanup(self.store.close)

    def test_legacy_payload_and_fingerprint_remain_compatible(self):
        profile = self.store.save_profile(ProviderProfile(model="m"), "secret")
        old_hash = hashlib.sha256(repr((profile.id, profile.base_url, profile.protocol, profile.model,
                                      profile.timeout, profile.max_output, profile.credential_revision)).encode()).hexdigest()
        self.assertEqual(profile_fingerprint(profile), old_hash)
        legacy = asdict(replace(profile, capability="可自动诊断", tested_fingerprint=old_hash))
        del legacy["source_ip"]
        with self.store.db:
            self.store.db.execute("UPDATE profiles SET payload=? WHERE id=?", (json.dumps(legacy), profile.id))
        loaded = self.store.profiles()[0]
        self.assertEqual(loaded.source_ip, "")
        self.assertEqual(profile_fingerprint(loaded), loaded.tested_fingerprint)
        self.assertEqual(self.store.key(loaded), "secret")

    def test_source_roundtrip_isolation_invalidation_and_key_preservation(self):
        first = self.store.save_profile(ProviderProfile(model="m"), "secret")
        verified = self.store.save_profile(replace(first, capability="可自动诊断", tested_fingerprint=profile_fingerprint(first)))
        changed = self.store.save_profile(replace(verified, source_ip=" 192.168.8.2 "))
        self.assertEqual(changed.source_ip, "192.168.8.2")
        self.assertEqual(changed.capability, "未验证")
        self.assertEqual(changed.tested_fingerprint, "")
        self.assertNotEqual(profile_fingerprint(changed), profile_fingerprint(first))
        self.assertEqual(self.store.key(changed), "secret")
        second = self.store.save_profile(ProviderProfile(model="n"), "other-secret")
        self.assertEqual(second.source_ip, "")
        reopened = DiagnosticStore(self.temp.name, FakeCipher())
        try:
            self.assertEqual([p.source_ip for p in reopened.profiles()], ["192.168.8.2", ""])
        finally:
            reopened.close()
        restored = self.store.save_profile(replace(changed, source_ip=""))
        self.assertEqual(profile_fingerprint(restored), profile_fingerprint(first))
        self.assertEqual(restored.capability, "未验证")

    def test_invalid_ip_does_not_overwrite_saved_configuration(self):
        saved = self.store.save_profile(ProviderProfile(), "secret")
        with self.assertRaises(ValueError):
            self.store.save_profile(replace(saved, source_ip="proxy.example:8080"))
        self.assertEqual(self.store.profiles()[0], saved)


class SourceDialogTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.windows = self.stack.enter_context(OffscreenTkWindows())
        self.root = tk.Tk()
        self.addCleanup(self.cleanup_root)
        self.stack.enter_context(patch("src.ui.ai_source_ip_dialog.list_source_ips", return_value=CHOICES))
        self.stack.enter_context(patch("src.ui.ai_source_ip_dialog.require_source_ip", side_effect=lambda ip: ip))

    def cleanup_root(self):
        self.root.update_idletasks()
        self.windows.assert_offscreen()
        self.root.destroy()
        self.root = None
        gc.collect()

    def test_default_and_cancel_do_not_choose_or_save(self):
        dialog = SourceIpDialog(self.root)
        self.assertEqual(dialog.choice.current(), 0)
        self.assertEqual(dialog.choice["values"][0], "不指定（自动选择）")
        dialog.choice.current(1)
        dialog.cancel()
        self.assertIsNone(dialog.result)

    def test_choose_source_and_restore_automatic(self):
        for selected, expected in ((1, "192.168.8.2"), (0, "")):
            dialog = SourceIpDialog(self.root, "192.168.8.2")
            self.assertEqual(dialog.choice.current(), 1)
            dialog.choice.current(selected)
            dialog.accept()
            self.assertEqual(dialog.result, expected)

    def test_missing_and_down_source_are_retained_but_rejected(self):
        for value in ("192.168.10.2", "192.168.9.2"):
            dialog = SourceIpDialog(self.root, value)
            self.assertEqual(dialog.values[dialog.choice.current()]["ip"], value)
            dialog.accept()
            self.assertIsNone(dialog.result)
            self.assertIn("不可用", dialog.status.get())
            dialog.cancel()

    def test_refresh_failure_retains_current_setting_and_allows_automatic(self):
        dialog = SourceIpDialog(self.root, "192.168.8.2")
        with patch("src.ui.ai_source_ip_dialog.list_source_ips", side_effect=OSError("failure")):
            dialog.refresh()
        self.assertIn("枚举失败", dialog.status.get())
        self.assertEqual(dialog.values[dialog.choice.current()]["ip"], "192.168.8.2")
        dialog.choice.current(0)
        dialog.accept()
        self.assertEqual(dialog.result, "")

    def test_address_disappears_between_refresh_and_accept(self):
        dialog = SourceIpDialog(self.root, "192.168.8.2")
        with patch("src.ui.ai_source_ip_dialog.require_source_ip", side_effect=ValueError("地址已消失")):
            dialog.accept()
        self.assertIsNone(dialog.result)
        self.assertIn("地址已消失", dialog.status.get())
        dialog.cancel()

    def owner(self):
        service = Mock()
        service.updates = queue.Queue()
        owner = AiDiagnosticsWindow(self.root, service, lambda: ())
        owner.window = self.root
        frame = ttk.Frame(self.root)
        frame.pack(fill="both", expand=True)
        owner._connection_tab(frame)
        owner._fill_profile(ProviderProfile(model="m"))
        return owner

    def test_button_position_draft_cancel_copy_and_fill(self):
        owner = self.owner()
        siblings = owner.source_ip_button.master.winfo_children()
        self.assertEqual([w.cget("text") for w in siblings],
                         ["保存并选择", "刷新模型", "测试连接与工具能力", "指定出口 IP…"])
        with patch.object(SourceIpDialog, "show", return_value="192.168.8.2"):
            owner._source_ip()
        self.assertEqual(owner.vars["source_ip"].get(), "192.168.8.2")
        self.assertEqual(owner.profile.source_ip, "")
        owner.service.store.save_profile.assert_not_called()
        self.assertIn("192.168.8.2", owner.source_ip_button.cget("text"))
        with patch.object(SourceIpDialog, "show", return_value=None):
            owner._source_ip()
        self.assertEqual(owner.vars["source_ip"].get(), "192.168.8.2")
        owner._fill_profile(replace(owner.profile, source_ip="192.168.8.2"))
        owner._copy_profile()
        self.assertEqual(owner.profile.source_ip, "192.168.8.2")
        owner._new_profile()
        self.assertEqual(owner.vars["source_ip"].get(), "")

    def test_save_includes_source_and_preserves_blank_key(self):
        owner = self.owner()
        owner.service.store.save_profile.side_effect = lambda profile, key: profile
        owner._reload_profiles = Mock()
        owner.vars["source_ip"].set("192.168.8.2")
        profile = owner._save()
        self.assertEqual(profile.source_ip, "192.168.8.2")
        self.assertIsNone(owner.service.store.save_profile.call_args.args[1])

    def test_stale_test_cannot_overwrite_new_source(self):
        owner = self.owner()
        before = owner.profile
        owner.service.store.profiles.return_value = [replace(before, source_ip="192.168.8.2")]
        owner.events.put(("capability", (before, "可自动诊断", "OK")))
        owner._poll()
        owner.service.store.save_profile.assert_not_called()
        self.root.after_cancel(owner._poll_id)

    def test_test_completion_keeps_unsaved_source_draft(self):
        owner = self.owner()
        owner.vars["source_ip"].set("192.168.8.2")
        owner.service.store.profiles.return_value = [owner.profile]
        owner._reload_profiles = Mock()
        owner.events.put(("capability", (owner.profile, "可自动诊断", "OK")))
        owner._poll()
        owner._reload_profiles.assert_not_called()
        self.assertEqual(owner.vars["source_ip"].get(), "192.168.8.2")
        self.assertEqual(owner.service.store.save_profile.call_args.args[0].source_ip, "")
        self.root.after_cancel(owner._poll_id)

    def test_model_result_for_old_source_is_not_shown_for_new_draft(self):
        owner = self.owner()
        owner.vars["source_ip"].set("192.168.8.2")
        owner.events.put(("models", (owner.profile, [dict(id="old-model")])))
        owner._poll()
        self.assertEqual(owner.model_choice["values"], "")
        self.root.after_cancel(owner._poll_id)

    def test_minimum_window_buttons_fit_in_vista_and_clam(self):
        owner = self.owner()
        self.root.geometry("940x660")
        style = ttk.Style(self.root)
        for theme in ("vista", "clam"):
            if theme not in style.theme_names():
                continue
            style.theme_use(theme)
            for value in ("", "192.168.100.222"):
                owner.vars["source_ip"].set(value)
                self.root.update_idletasks()
                button = owner.source_ip_button
                self.assertLessEqual(button.winfo_x() + button.winfo_width(), button.master.winfo_width())
                dialog = SourceIpDialog(self.root, value)
                measured = []
                def close_mapped_dialog():
                    dialog.window.after_cancel(timeout)
                    dialog.window.update_idletasks()
                    measured.append(dialog.choice.winfo_width())
                    dialog.cancel()
                # Measure only after the real control maps and layout settles;
                # a wall-clock timer can destroy it before its first layout.
                dialog.choice.bind("<Map>", lambda _event: dialog.window.after_idle(close_mapped_dialog))
                timeout = dialog.window.after(5000, dialog.cancel)
                self.assertEqual(dialog.window.cget("background"), "#eef2f5")
                self.assertIsNone(dialog.show())
                self.assertEqual(len(measured), 1, "source choice did not map")
                self.assertGreaterEqual(measured[0], 400)


class LocalConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.records = []
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(datetime.utcnow() - timedelta(days=1))
                .not_valid_after(datetime.utcnow() + timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                               x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]), critical=False)
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
        cls.cert = str(Path(cls.temp.name) / "cert.pem")
        Path(cls.cert).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        private = Path(cls.temp.name) / "key.pem"
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()))
        records = cls.records
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def respond(self):
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                records.append((self.client_address[0], self.path, payload))
                body = ({"data": [{"id": "local-model"}]} if self.command == "GET" else
                        {"output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}]}
                        if "responses" in self.path else chat())
                content = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            do_GET = do_POST = respond

            def do_CONNECT(self):
                # 仅转发到本组测试已启动的 TLS 服务，不解析或连接外部目标。
                if self.path != "127.0.0.1:" + str(self.server.tls_port):
                    self.send_error(403)
                    return
                records.append((self.client_address[0], "CONNECT " + self.path, {}))
                with socket.create_connection(("127.0.0.1", self.server.tls_port), timeout=2) as upstream:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.flush()
                    while True:
                        readable, _, _ = select.select([self.connection, upstream], [], [], 2)
                        if not readable:
                            return
                        for stream in readable:
                            data = stream.recv(65536)
                            if not data:
                                return
                            (upstream if stream is self.connection else self.connection).sendall(data)

        cls.servers = []
        for tls in (False, True):
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            if tls:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(cls.cert, str(private))
                server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, kwargs=dict(poll_interval=.05), daemon=True)
            thread.start()
            cls.servers.append((server, thread))
        cls.servers[0][0].tls_port = cls.servers[1][0].server_port

    @classmethod
    def tearDownClass(cls):
        for server, thread in cls.servers:
            server.shutdown()
            server.server_close()
            thread.join(2)
        cls.temp.cleanup()

    def test_real_http_tls_models_and_both_protocol_streams_bind_local_source(self):
        for tls, (server, _) in enumerate(self.servers):
            base = ("https" if tls else "http") + "://127.0.0.1:" + str(server.server_port)
            for protocol in ("chat_completions", "responses"):
                with self.subTest(tls=tls, protocol=protocol), patch("src.core.ai_client.request_url",
                        side_effect=lambda _base, path: base + "/" + path):
                    session = requests.Session()
                    session.trust_env = False
                    session.verify = self.cert
                    client = DiagnosticModelClient(ProviderProfile(source_ip="127.0.0.1", protocol=protocol, model="local-model"),
                                                   "test-only-key", DiagnosticRedactor(), session)
                    try:
                        self.assertEqual(client.models(), ("local-model",))
                        self.assertEqual(client.complete_stream([], on_text=lambda _t: None).text, "OK")
                        self.assertEqual([record[0] for record in self.records[-2:]], ["127.0.0.1"] * 2)
                    finally:
                        client.close()

    def test_real_http_proxy_keeps_selected_source_and_absolute_request_target(self):
        server, _ = self.servers[0]
        session = requests.Session()
        session.trust_env = False
        session.proxies = {"http": "http://127.0.0.1:" + str(server.server_port)}
        client = DiagnosticModelClient(ProviderProfile(base_url="http://10.10.120.244:4000", source_ip="127.0.0.1"),
                                       "test-only-key", DiagnosticRedactor(), session)
        try:
            self.assertEqual(client.models(), ("local-model",))
            self.assertEqual(self.records[-1][:2], ("127.0.0.1", "http://10.10.120.244:4000/models"))
        finally:
            client.close()

    def test_real_https_connect_proxy_binds_source_and_retains_tls_verification(self):
        proxy, _ = self.servers[0]
        target, _ = self.servers[1]
        url = "https://127.0.0.1:" + str(target.server_port)
        session = requests.Session()
        session.trust_env = False
        session.verify = self.cert
        session.proxies = {"https": "http://127.0.0.1:" + str(proxy.server_port)}
        client = DiagnosticModelClient(ProviderProfile(base_url=url, source_ip="127.0.0.1"),
                                       "test-only-key", DiagnosticRedactor(), session)
        try:
            self.assertEqual(client.models(), ("local-model",))
            self.assertEqual(self.records[-2][:2], ("127.0.0.1", "CONNECT 127.0.0.1:" + str(target.server_port)))
            self.assertEqual(self.records[-1][0], "127.0.0.1")
            self.assertEqual(session.verify, self.cert)
        finally:
            client.close()

    @unittest.skipUnless(os.name == "nt", "Windows TCP取证")
    def test_real_windows_evidence_binds_selected_source_and_never_falls_back(self):
        server, _ = self.servers[0]
        for source, expected in (("127.0.0.1", "connected"), ("192.0.2.123", "tcp_failed")):
            with self.subTest(source=source):
                records, _ = _probe([dict(label="网关", host="127.0.0.1", port=server.server_port,
                                          source_ip=source)], threading.Event())
                tcp = next(item for item in records if item.get("kind") == "tcp")
                self.assertEqual(tcp["status"], expected)
                self.assertEqual(tcp["source"], source if expected == "connected" else "")
