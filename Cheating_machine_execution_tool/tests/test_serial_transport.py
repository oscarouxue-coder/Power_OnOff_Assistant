import os
import sys
import time
import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.serial_transport import PySerialSession, SerialSessionManager, vlan_to_serial_port
from src.models import SerialSettings


class FakeSerial:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chunks = [b"do", b"ne and wri", b"te"]
        self.writes = []
        self.closed = False

    @property
    def in_waiting(self):
        return len(self.chunks[0]) if self.chunks else 0

    def read(self, _size):
        return self.chunks.pop(0) if self.chunks else b""

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        return None

    def cancel_read(self):
        return None

    def close(self):
        self.closed = True


class SerialTransportTests(unittest.TestCase):
    def test_vlan_mapping_and_default_settings(self):
        self.assertEqual(vlan_to_serial_port("VLAN148"), "COM48")
        self.assertEqual(SerialSettings("COM1").baudrate, 115200)
        self.assertFalse(SerialSettings("COM1").rtscts)

    def test_single_reader_matches_marker_across_chunks_and_close_is_idempotent(self):
        created = []

        def factory(**kwargs):
            item = FakeSerial(**kwargs)
            created.append(item)
            return item

        with TemporaryDirectory() as directory:
            session = PySerialSession(SerialSettings("COM1"), Path(directory) / "serial.log", factory)
            session.open()
            self.assertTrue(session.wait_for_all(("done", "write"), 2, 0))
            session.send_line("reset")
            session.close()
            session.close()
        self.assertEqual(created[0].kwargs["baudrate"], 115200)
        self.assertEqual(created[0].kwargs["bytesize"], 8)
        self.assertEqual(created[0].writes, [b"reset\r"])
        self.assertTrue(created[0].closed)

    def test_manager_locks_manual_writer_while_upgrade_controls_port(self):
        manager = SerialSessionManager()
        fake = FakeSerial()
        original = PySerialSession.__init__

        def init_with_fake(self, settings, log_path=None):
            original(self, settings, log_path, serial_factory=lambda **_kwargs: fake)

        with mock.patch.object(PySerialSession, "__init__", init_with_fake):
            manager.acquire_monitor("terminal", SerialSettings("COM1"))
            manager.acquire_control("upgrade", SerialSettings("COM1"))
            self.assertFalse(manager.manual_writable("COM1"))
            manager.release("upgrade", "COM1")
            self.assertTrue(manager.manual_writable("COM1"))
            manager.shutdown_all()

    def test_peek_since_returns_decoded_text_from_cursor(self):
        """peek_since 返回从指定游标到当前的全部解码文本,不消费历史。

        用于诊断乱码(UTF-8 替换符),不应影响 wait_for_any 的游标。
        """
        session = PySerialSession(SerialSettings("COM1"), serial_factory=lambda **_k: FakeSerial(**_k))
        # 不调用 open() 避免 reader 线程污染 history;直接注入数据
        session._history.extend(b"UserName:\x80\x81\xc0")
        snapshot = session.peek_since(0)
        # 无效字节会被 decode(errors="replace") 替换为 U+FFFD
        self.assertIn("UserName:", snapshot)
        self.assertIn("�", snapshot)
        # peek_since 不影响游标
        cursor_before = session.cursor()
        session.peek_since(0)
        self.assertEqual(session.cursor(), cursor_before)
        # 起点游标为 9,只看到乱码部分
        tail = session.peek_since(9)
        self.assertNotIn("UserName:", tail)
        self.assertIn("�", tail)
