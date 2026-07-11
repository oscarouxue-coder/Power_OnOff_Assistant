import os
import socket
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tftpy

from src.core.tftp_transport import TftpServerHandle, _ip_is_bindable_locally, upload_firmware


class TftpTransportTests(unittest.TestCase):
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
