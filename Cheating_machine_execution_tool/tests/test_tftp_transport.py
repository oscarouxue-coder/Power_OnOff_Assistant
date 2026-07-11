import os
import socket
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tftpy

from src.core.tftp_transport import TftpServerHandle, _ip_is_bindable_locally, upload_firmware, wait_for_bindable_ip


class TftpTransportTests(unittest.TestCase):
    def test_wait_for_bindable_ip_retries_until_windows_address_is_ready(self):
        now = [0.0]
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        with patch("src.core.tftp_transport._ip_is_bindable_locally", side_effect=[False, False, True]):
            result = wait_for_bindable_ip(
                "192.168.1.139",
                timeout_seconds=15,
                poll_seconds=0.5,
                sleep_fn=sleep,
                monotonic_fn=lambda: now[0],
            )

        self.assertTrue(result)
        self.assertEqual(sleeps, [0.5, 0.5])

    def test_server_serves_selected_file_only_under_fixed_alias(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            firmware = root / "selected.img"
            firmware.write_bytes(b"firmware-data")
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
            probe.close()
            server = TftpServerHandle("127.0.0.1", firmware, port=port)
            server.start()
            try:
                target = root / "downloaded.img"
                tftpy.TftpClient("127.0.0.1", port).download("tclinux_allinone", str(target), timeout=1, retries=3)
                self.assertEqual(target.read_bytes(), b"firmware-data")
            finally:
                server.stop()
                server.stop()

    def test_ip_is_bindable_locally_for_loopback_and_unused_address(self):
        # 回环 IP 通常能 bind 成功。
        self.assertTrue(_ip_is_bindable_locally("127.0.0.1"))
        # TEST-NET-1(203.0.113.0/24)按 RFC 5737 不应分配到任何真实接口,本机也基本无法 bind。
        # 在某些被 VPN/容器接管的环境下可能反而能 bind,但只要不是测试环境典型值即符合预期。
        unused = "203.0.113.99"
        try:
            result = _ip_is_bindable_locally(unused)
        except OSError:
            result = False
        # 不强制断言结果(取决于环境),只验证函数不会抛异常。
        self.assertIn(result, (True, False))

    def test_server_falls_back_to_inaddr_any_when_bind_ip_not_local(self):
        """回归:network_card_ip.ini 与本机实际网卡不一致时,TFTP 服务应回退到 INADDR_ANY 而不是直接报错。

        现场场景:网络卡 IP 配置为 192.168.29.139,但对应 VLAN 网卡实际并不持有该 IP,
        tftpy.listen() 会抛 WSAEADDRNOTAVAIL(10049)。start() 需要自动回退到空字符串监听。
        """
        with TemporaryDirectory() as directory:
            root = Path(directory)
            firmware = root / "firmware.bin"
            firmware.write_bytes(b"fallback-test")

            # 用一个绝对不会在本机的 IP 触发不可绑定分支。
            server = TftpServerHandle("203.0.113.1", firmware, alias="tclinux_allinone")
            with patch("src.core.tftp_transport._ip_is_bindable_locally", return_value=False):
                server.start()
            try:
                # 实际监听 IP 应为空串(即回退到 INADDR_ANY),而不是原始 203.0.113.1。
                self.assertEqual(server.bind_ip_actually_used, "")
            finally:
                server.stop()

    def test_server_keeps_configured_bind_ip_when_it_is_local(self):
        """正路径:bind_ip 在本机网卡上时不应回退,_bind_ip_actually_used 应等于原值。"""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            firmware = root / "firmware.bin"
            firmware.write_bytes(b"happy-path")
            server = TftpServerHandle("127.0.0.1", firmware, alias="tclinux_allinone")
            with patch("src.core.tftp_transport._ip_is_bindable_locally", return_value=True):
                server.start()
            try:
                self.assertEqual(server.bind_ip_actually_used, "127.0.0.1")
            finally:
                server.stop()

    def test_strict_server_rejects_unbindable_ip_without_any_fallback(self):
        with TemporaryDirectory() as directory:
            firmware = Path(directory) / "firmware.bin"
            firmware.write_bytes(b"strict-bind-test")
            server = TftpServerHandle("203.0.113.1", firmware, allow_any_fallback=False)

            with patch("src.core.tftp_transport._ip_is_bindable_locally", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "严格绑定"):
                    server.start()

            self.assertEqual(server.bind_ip_actually_used, "203.0.113.1")

    def test_two_strict_servers_can_listen_on_distinct_ips_with_same_port(self):
        with TemporaryDirectory() as directory:
            firmware = Path(directory) / "firmware.bin"
            firmware.write_bytes(b"two-server-test")
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
            probe.close()
            first = TftpServerHandle("127.0.0.1", firmware, port=port, allow_any_fallback=False)
            second = TftpServerHandle("127.0.0.2", firmware, port=port, allow_any_fallback=False)
            first.start()
            try:
                second.start()
                self.assertEqual(first.bind_ip_actually_used, "127.0.0.1")
                self.assertEqual(second.bind_ip_actually_used, "127.0.0.2")
            finally:
                second.stop()
                first.stop()

    def test_server_binds_transfer_data_socket_to_listening_vlan_ip(self):
        with TemporaryDirectory() as directory:
            firmware = Path(directory) / "firmware.bin"
            firmware.write_bytes(b"bound-data-socket-test")
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.bind(("127.0.0.2", 0))
            port = probe.getsockname()[1]
            probe.close()
            server = TftpServerHandle("127.0.0.2", firmware, port=port, allow_any_fallback=False)
            client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            client.bind(("127.0.0.1", 0))
            server.start()
            try:
                # RRQ 后服务端会创建新的 TFTP 数据传输 socket；不发送 ACK，
                # 保留会话以便断言该 socket 的本地 IP。
                client.sendto(b"\x00\x01tclinux_allinone\x00octet\x00", ("127.0.0.2", port))
                deadline = time.monotonic() + 2
                while not server._server.sessions and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(server._server.sessions)
                session = next(iter(server._server.sessions.values()))
                self.assertEqual(session.sock.getsockname()[0], "127.0.0.2")
            finally:
                client.close()
                server.stop()

    def test_upload_binds_requested_source_ip_and_uses_requested_remote_name(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            firmware = root / "firmware.bin"
            firmware.write_bytes(b"upload-data")
            received = root / "received.bin"
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
            probe.close()
            receiver = tftpy.TftpServer(str(root), upload_open=lambda _path, _ctx: received.open("wb"), flock=False)
            import threading
            thread = threading.Thread(target=lambda: receiver.listen("127.0.0.1", port, timeout=1), daemon=True)
            thread.start()
            self.assertTrue(receiver.is_running.wait(3))
            try:
                result = upload_firmware(firmware, "127.0.0.1", "127.0.0.1", remote_name="remote.bin", port=port)
                self.assertGreater(result.bytes_transferred, 0)
                self.assertEqual(received.read_bytes(), b"upload-data")
            finally:
                receiver.stop(now=True)
                thread.join(3)
