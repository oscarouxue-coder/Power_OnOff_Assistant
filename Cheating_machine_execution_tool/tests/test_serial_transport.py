import os
import sys
import time
import threading
import queue
import unittest
from io import StringIO
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
    def test_async_close_waits_for_inflight_callback_and_reserves_port(self):
        entered, release = threading.Event(), threading.Event()
        class Driver(FakeSerial):
            def __init__(self):
                super().__init__()
                self.input = queue.SimpleQueue()
            @property
            def in_waiting(self):
                return 0
            def read(self, _size):
                try:
                    return self.input.get(timeout=.02)
                except queue.Empty:
                    return b''
            def cancel_read(self):
                self.input.put(b'')
        driver = Driver()
        original = PySerialSession
        manager = SerialSessionManager()
        with TemporaryDirectory() as directory, mock.patch('src.core.serial_transport.PySerialSession',
                side_effect=lambda settings, log_path=None: original(settings, log_path, lambda **kwargs: driver)):
            session = manager.acquire_monitor('monitor', SerialSettings('SIM42'), Path(directory)/'log.txt')
            def callback(event):
                if event.direction == 'RX':
                    entered.set()
                    release.wait(3)
            session.subscribe(callback)
            driver.input.put(b'tail without newline')
            try:
                self.assertTrue(entered.wait(1))
                start = time.monotonic()
                ticket = manager.release('monitor', 'SIM42', wait=False)
                self.assertLess(time.monotonic()-start, .1)
                self.assertFalse(ticket.done.is_set())
                self.assertIsNotNone(session._log_handle)
                with self.assertRaisesRegex(RuntimeError, '正在关闭'):
                    manager.acquire_monitor('new', SerialSettings('SIM42'))
            finally:
                release.set()
            self.assertTrue(ticket.done.wait(2))
            self.assertEqual(ticket.error, '')
            self.assertIsNone(session._log_handle)
            self.assertFalse(session._reader.is_alive())
            saved = (Path(directory)/'log.txt').read_text(encoding='utf-8')
            self.assertIn('RX tail without newline\n', saved)
            self.assertIn('STATE 串口已关闭', saved)
            manager.shutdown_all()

    def test_close_thread_failure_keeps_control_and_bulk_shutdown_can_retry(self):
        from qt_serial_fakes import SerialHarness

        ports = ('COM7955', 'COM7956', 'COM7957')
        start = threading.Thread.start
        coordinator = mock.Mock()
        manager = SerialSessionManager(resource_coordinator=coordinator, project_id='fixture')
        harness = SerialHarness()
        with mock.patch('src.core.serial_transport.PySerialSession', side_effect=harness.factory):
            for port in ports:
                manager.acquire_control('original', SerialSettings(port))

        def refuse_second(worker):
            if worker.name == 'serial-close-' + ports[1]:
                raise RuntimeError('synthetic close thread unavailable')
            start(worker)

        try:
            with mock.patch.object(threading.Thread, 'start', refuse_second):
                with self.assertRaisesRegex(RuntimeError, 'thread unavailable'):
                    manager.shutdown_all(wait=False)
            for port in ports[1:]:
                state = manager.diagnostic_state(port)
                self.assertTrue(state['opened_in_program'])
                self.assertFalse(state['closing_in_program'])
                self.assertEqual(state['control_owner'], 'original')
                self.assertIs(manager.existing_session(SerialSettings(port)), harness.sessions[port])
                self.assertFalse(manager.manual_writable(port))
                self.assertFalse(harness.drivers[port].closed)
            # Exercise the same driver even if Thread.start delivers a late exception.
            def started_then_raised(worker):
                start(worker)
                raise RuntimeError('thread already started')
            with mock.patch.object(threading.Thread, 'start', started_then_raised):
                ticket = manager.release('original', ports[1], wait=False)
            self.assertTrue(ticket.done.wait(2))
            self.assertEqual(ticket.error, '')
            self.assertTrue(all(t.done.is_set() and not t.error for t in manager.shutdown_all(wait=True)))
            self.assertTrue(all(harness.drivers[port].closed and not harness.drivers[port].writes for port in ports))
            self.assertCountEqual(coordinator.release.call_args_list,
                [mock.call(manager._workspace_owner(port), uncertain=False) for port in ports])
        finally:
            # Also works against a failed implementation with an unstarted close ticket.
            for session in harness.sessions.values():
                session.close()

    def test_workspace_release_failure_completes_ticket_and_preserves_port_fence(self):
        from qt_serial_fakes import SerialHarness

        coordinator = mock.Mock()
        coordinator.release.side_effect = OSError('synthetic resource database unavailable')
        manager = SerialSessionManager(resource_coordinator=coordinator, project_id='fixture')
        harness = SerialHarness()
        settings = SerialSettings('COM7958')
        with mock.patch('src.core.serial_transport.PySerialSession', side_effect=harness.factory):
            manager.acquire_monitor('monitor', settings)
            ticket = manager.release('monitor', settings.port, wait=False)
            self.assertTrue(ticket.done.wait(2))
            self.assertIn('synthetic resource database unavailable', ticket.error)
            self.assertTrue(harness.drivers[settings.port].closed)
            self.assertFalse(harness.drivers[settings.port].writes)
            self.assertEqual(manager.shutdown_all(wait=True), (ticket,))
            with self.assertRaisesRegex(RuntimeError, '正在关闭'):
                manager.acquire_monitor('retry', settings)

    def test_open_failure_releases_driver_log_and_port_before_retry(self):
        from qt_serial_fakes import SerialHarness
        from src.core.host_resource_lock import HostResourceLock

        for fault in ('log', 'reader', 'started_reader'):
            harness = SerialHarness()
            with self.subTest(fault=fault), TemporaryDirectory() as directory, \
                    mock.patch('src.core.serial_transport.PySerialSession', side_effect=harness.factory):
                manager = SerialSessionManager()
                self.addCleanup(manager.shutdown_all)
                settings = SerialSettings('COM7941')
                log = Path(directory) / 'serial.log'
                if fault == 'log':
                    log.mkdir()
                    with self.assertRaises(OSError):
                        manager.acquire_monitor('gui', settings, log)
                    log.rmdir()
                else:
                    start = threading.Thread.start

                    def fail_start(thread):
                        if fault == 'started_reader':
                            start(thread)
                        raise RuntimeError('fixture-start')

                    with mock.patch.object(threading.Thread, 'start', fail_start):
                        with self.assertRaisesRegex(RuntimeError, 'fixture-start'):
                            manager.acquire_monitor('gui', settings, log)

                first = harness.sessions[settings.port]
                self.assertTrue(harness.drivers[settings.port].closed)
                self.assertIsNone(first._log_handle)
                self.assertFalse(first._reader is not None and first._reader.is_alive())
                self.assertFalse(manager.diagnostic_state(settings.port)['closing_in_program'])
                with HostResourceLock(['serial:' + settings.port], reentrant=False):
                    pass
                harness.drivers.pop(settings.port)
                retry = manager.acquire_monitor('gui', settings, log)
                self.assertIsNot(first, retry)
                manager.release('gui', settings.port)
                self.assertTrue(harness.drivers[settings.port].closed)

    def test_driver_close_error_fences_normal_release_and_failed_start_rollback(self):
        from qt_serial_fakes import QueueSerial
        from src.core.host_resource_lock import HostResourceBusy, HostResourceLock

        for rollback in (False, True):
            with self.subTest(rollback=rollback), TemporaryDirectory() as directory:
                coordinator = mock.Mock()
                manager = SerialSessionManager(resource_coordinator=coordinator, project_id='fixture')
                port = 'COM7942'
                driver = QueueSerial()
                log = Path(directory) / 'closed.log'
                session = PySerialSession(SerialSettings(port), log, serial_factory=lambda **kwargs: driver)
                events = []
                session.subscribe(events.append)
                try:
                    with mock.patch('src.core.serial_transport.PySerialSession', return_value=session), \
                            mock.patch.object(driver, 'close', side_effect=OSError('fixture-close')):
                        if rollback:
                            with mock.patch.object(threading.Thread, 'start', side_effect=RuntimeError('fixture-start')):
                                with self.assertRaisesRegex(RuntimeError, 'fixture-close'):
                                    manager.acquire_monitor('gui', session.settings, log)
                        else:
                            manager.acquire_monitor('gui', session.settings, log)
                            ticket = manager.release('gui', port, wait=False)
                            self.assertTrue(ticket.done.wait(3))
                            self.assertIn('fixture-close', ticket.error)
                        with self.assertRaisesRegex(RuntimeError, 'fixture-close'):
                            session.close()
                        with self.assertRaisesRegex(RuntimeError, '正在关闭'):
                            manager.acquire_control('upgrade', session.settings)
                        self.assertTrue(manager.diagnostic_state(port)['closing_in_program'])
                        with self.assertRaises(HostResourceBusy):
                            HostResourceLock(['serial:' + port], reentrant=False).acquire()
                        coordinator.release.assert_called_once_with(manager._workspace_owner(port), uncertain=True)
                        self.assertFalse(any(event.text == '串口已关闭' for event in events))
                        self.assertTrue(any(event.direction == 'ERROR' and 'fixture-close' in event.text for event in events))
                        self.assertIsNone(session._log_handle)
                        self.assertFalse(driver.writes)
                finally:
                    driver.close()
                    if session._host_resource_lock:
                        session._host_resource_lock.close()

    def test_log_file_prefixes_every_serial_line_and_joins_split_rx_chunks(self):
        session = PySerialSession(SerialSettings("COM1"), serial_factory=lambda **_k: FakeSerial(**_k))
        session._log_handle = StringIO()

        with mock.patch(
            "src.core.serial_transport.time.strftime",
            return_value="2026-08-08_19:12:10",
        ):
            session._emit("RX", b"", "第一行\r\n第二")
            session._emit("RX", b"", "行\n第三行\r")
            session._emit("RX", b"", "\n末尾残留")
            session._flush_pending_rx_log_line()
            session._emit("TX", b"", "发送一\r\n发送二")
            session._emit("STATE", b"", "串口已关闭")

        self.assertEqual(
            session._log_handle.getvalue(),
            "2026-08-08_19:12:10 RX 第一行\n"
            "2026-08-08_19:12:10 RX 第二行\n"
            "2026-08-08_19:12:10 RX 第三行\n"
            "2026-08-08_19:12:10 RX 末尾残留\n"
            "2026-08-08_19:12:10 TX 发送一\n"
            "2026-08-08_19:12:10 TX 发送二\n"
            "2026-08-08_19:12:10 STATE 串口已关闭\n",
        )

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
