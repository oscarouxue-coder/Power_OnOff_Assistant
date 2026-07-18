import socket
import socketserver
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.telnet_transport import TelnetSession


def free_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class _FakeSampleServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _FakeSampleHandler(socketserver.BaseRequestHandler):
    """最简 仿 OpenWRT BusyBox telnetd: 读到 user 后发送 login:/Password:/提示符。"""

    def handle(self) -> None:  # pragma: no cover - 集成路径被覆盖
        try:
            self.request.sendall(b"login: ")
            data = self.request.recv(1024)
            self.request.sendall(b"Password: ")
            data = self.request.recv(1024)
            self.request.sendall(b"# ")
            self.request.recv(4096)
        except OSError:
            return


class TelnetSessionTests(unittest.TestCase):
    def test_constructor_rejects_ip_that_is_not_bindable(self):
        with patch("src.core.telnet_transport.ip_is_bindable_locally", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "Telnet 源 IP"):
                TelnetSession("192.168.29.115", "192.168.29.1")

    def test_constructor_with_loopback_succeeds_and_cursor_returns_zero(self):
        port = free_port()
        with _FakeSampleServer(("127.0.0.1", port), _FakeSampleHandler) as server:
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            try:
                session = TelnetSession("127.0.0.1", "127.0.0.1", device_port=port)
                try:
                    self.assertEqual(session.cursor(), 0)
                    self.assertIn(session.device_host, "127.0.0.1")
                finally:
                    session.close()
            finally:
                server.shutdown()
                server.server_close()

    def test_write_then_send_line_pushed_through_socket(self):
        port = free_port()
        captured = []

        class _CapturingHandler(socketserver.BaseRequestHandler):
            def handle(self):  # pragma: no cover - 端到端覆盖
                try:
                    self.request.settimeout(2.0)
                    while True:
                        chunk = self.request.recv(1024)
                        if not chunk:
                            break
                        captured.append(chunk)
                except (OSError, socket.timeout):
                    pass

        with _FakeSampleServer(("127.0.0.1", port), _CapturingHandler) as server:
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            try:
                session = TelnetSession("127.0.0.1", "127.0.0.1", device_port=port)
                try:
                    session.write(b"\r")
                    session.send_line("ppctl get foo")
                finally:
                    time.sleep(0.3)
                    session.close()
            finally:
                server.shutdown()
                server.server_close()

        all_bytes = b"".join(captured)
        self.assertIn(b"\r", all_bytes)
        self.assertIn(b"ppctl get foo\r", all_bytes)

    def test_wait_for_any_matches_marker_in_received_bytes(self):
        port = free_port()

        class _PromptingHandler(socketserver.BaseRequestHandler):
            def handle(self):  # pragma: no cover
                try:
                    self.request.sendall(b"Welcome\r\n# ")
                except OSError:
                    pass

        with _FakeSampleServer(("127.0.0.1", port), _PromptingHandler) as server:
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            try:
                session = TelnetSession("127.0.0.1", "127.0.0.1", device_port=port)
                try:
                    # 等待达 # 提示符
                    result = session.wait_for_any(("#", ">", "login:"), 3.0, session.cursor())
                    self.assertEqual(result, "#")
                finally:
                    session.close()
            finally:
                server.shutdown()
                server.server_close()

    def test_peek_since_displays_plaintext_known_secrets(self):
        # 操作员要求:所有下发/回显一律明文,不再按 known_secrets 脱敏。
        # ``known_secrets`` 形参保留以兼容既有调用方,但 _display 不再替换。
        port = free_port()

        class _EchoHandler(socketserver.BaseRequestHandler):
            def handle(self):  # pragma: no cover
                try:
                    self.request.sendall(b"super-secret-from-sample\n")
                except OSError:
                    pass

        with _FakeSampleServer(("127.0.0.1", port), _EchoHandler) as server:
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            try:
                session = TelnetSession(
                    "127.0.0.1",
                    "127.0.0.1",
                    device_port=port,
                    known_secrets=("super-secret-from-sample",),
                )
                try:
                    time.sleep(0.2)
                    snapshot = session.peek_since(0)
                    # 明文 secret 必须出现,"[敏感内容已隐藏]" placeholder 不应再出现
                    self.assertIn("super-secret-from-sample", snapshot)
                    self.assertNotIn("[敏感内容已隐藏]", snapshot)
                finally:
                    session.close()
            finally:
                server.shutdown()
                server.server_close()

    def test_close_is_idempotent(self):
        port = free_port()
        with _FakeSampleServer(("127.0.0.1", port), _FakeSampleHandler) as server:
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            try:
                session = TelnetSession("127.0.0.1", "127.0.0.1", device_port=port)
                session.close()
                # 第二次 close 不应报错
                session.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
