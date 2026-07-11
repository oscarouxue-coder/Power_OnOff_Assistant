import os
import socket
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tftpy

from src.core.tftp_transport import TftpServerHandle, upload_firmware


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
