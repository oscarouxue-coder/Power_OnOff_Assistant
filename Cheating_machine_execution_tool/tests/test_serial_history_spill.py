"""Bounded serial RX with a real reader thread and a queue-backed fake driver."""
import gc
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
import weakref

from qt_serial_fakes import QueueSerial
from src.core.serial_transport import PySerialSession, SerialCloseError
from src.core.transport_observation import HistoryRegistry
from src.models.serial_models import SerialSettings


class SerialHistorySpillTests(unittest.TestCase):
    def session(self, log=None):
        driver = QueueSerial()
        session = PySerialSession(SerialSettings('SIM-SPILL-' + self._testMethodName), log,
                                  serial_factory=lambda **options: driver)
        session.open()
        return session, driver

    def await_cursor(self, session, expected):
        with session._condition:
            self.assertTrue(session._condition.wait_for(lambda: session.cursor() >= expected or session.error, 5))
        self.assertIsNone(session.error)
        self.assertEqual(session.cursor(), expected)

    def test_no_log_old_cursors_survive_eviction_close_and_storage_dies_with_last_session(self):
        session, driver = self.session()
        raw = (b'a' * (session.READ_CHUNK - 1) + '中'.encode() + b'EtHeR\xff' + b'k' * (session.HISTORY_LIMIT + 17))
        try:
            driver.input.put(raw)
            self.await_cursor(session, len(raw))
            self.assertLessEqual(len(session._history), session.HISTORY_LIMIT)
            self.assertGreater(session._history_offset, 0)
            self.assertEqual(session.peek_since(0), raw.decode('utf-8', errors='replace'))
            self.assertEqual(session.peek_since(-17), 'k' * 17)
            self.assertEqual(session.peek_since(len(raw) + 1), '')
            self.assertTrue(session.wait_for_all(('中', 'ether'), 0, 0))
            self.assertEqual(session.wait_for_any(('eThEr', 'k'), 0, 0), 'ether')
            self.assertEqual(session.wait_for_any(('k', 'ether'), 0, 0), 'k')
            self.assertFalse(session.wait_for_all(('ether',), 0, -100))
        finally:
            session.close()
        self.assertEqual(session.cursor(), len(raw))
        self.assertEqual(b''.join(session.iter_rx_history()), raw)
        self.assertEqual(session.peek_since(0), raw.decode('utf-8', errors='replace'))
        self.assertFalse(session.wait_for_all(('k',), 0, 0))
        self.assertIsNone(session.wait_for_any(('k',), 0, 0))
        handle = session._history_file
        reference = weakref.ref(session)
        del session
        gc.collect()
        self.assertIsNone(reference())
        self.assertTrue(handle.closed)
        self.assertFalse(driver.writes)

    def test_incremental_live_wait_finds_split_markers_after_initial_disk_scan(self):
        session, driver = self.session()
        try:
            start = b'DoNe' + b'.' * session.HISTORY_LIMIT + b'Wr'
            driver.input.put(start)
            self.await_cursor(session, len(start))
            result = []
            waiter = threading.Thread(target=lambda: result.append(session.wait_for_all(('write', 'done'), 3, 0)))
            waiter.start()
            driver.input.put(b'It')
            driver.input.put(b'E')
            waiter.join(4)
            self.assertEqual(result, [True])
            self.assertFalse(session.wait_for_all(('done', 'write'), 0, 1))
        finally:
            session.close()

    def test_long_line_spill_keeps_one_timestamp_crlf_order_and_close_tail(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'serial.log'
            session, driver = self.session(path)
            long_line = '设备' * (session.LOG_LINE_LIMIT + 11)
            raw = long_line.encode()
            try:
                for _ in range(3):
                    driver.input.put(raw)
                driver.input.put(b'\r')
                self.await_cursor(session, 3 * len(raw) + 1)
                with session._log_lock:
                    self.assertLessEqual(len(session._rx_log_line_buffer), session.LOG_LINE_LIMIT)
                    self.assertIsNotNone(session._rx_line_file)
                self.assertNotIn(' RX ', path.read_text(encoding='utf-8'))
                driver.input.put(b'\n\nlast')
                self.await_cursor(session, 3 * len(raw) + 7)
            finally:
                session.close()
            lines = [text.split(' RX ', 1)[1] for text in path.read_text(encoding='utf-8').splitlines() if ' RX ' in text]
            self.assertEqual(lines, [3 * long_line, '', 'last'])
            self.assertIsNone(session._rx_line_file)

    def test_spill_write_failure_is_reported_and_prevents_an_unverified_marker_or_command(self):
        session, driver = self.session()
        errors = []
        session.subscribe(lambda event: errors.append(event.text) if event.direction == 'ERROR' else None)
        try:
            driver.input.put(b'z' * session.HISTORY_LIMIT)
            self.await_cursor(session, session.HISTORY_LIMIT)
            with patch('src.core.serial_transport.tempfile.TemporaryFile', side_effect=OSError('simulated full volume')):
                driver.input.put(b'write')
                session._reader.join(5)
            self.assertFalse(session._reader.is_alive())
            self.assertIn('临时原始历史写入失败', str(session.error))
            self.assertTrue(any('simulated full volume' in e for e in errors))
            with self.assertRaisesRegex(RuntimeError, '临时原始历史'):
                session.wait_for_any(('write',), 0, 0)
            with self.assertRaisesRegex(RuntimeError, '临时原始历史'):
                session.write(b'no command')
            self.assertFalse(driver.writes)
            sample = HistoryRegistry.inspect(session, {})
            self.assertEqual(sample['received_bytes'], session.HISTORY_LIMIT + len(b'write'))
        finally:
            session.close()

    def test_log_spill_error_notifies_and_leaves_existing_close_fence(self):
        with TemporaryDirectory() as temp:
            session, driver = self.session(Path(temp) / 'out.log')
            events = []
            session.subscribe(lambda event: events.append(event.direction))
            try:
                with patch('src.core.serial_transport.tempfile.TemporaryFile', side_effect=OSError('simulated log spill failure')):
                    driver.input.put(b'x' * (session.LOG_LINE_LIMIT + 1))
                    session._reader.join(5)
                self.assertFalse(session._reader.is_alive())
                self.assertIn('ERROR', events)
                sample = HistoryRegistry.inspect(session, {})
                self.assertIn('simulated log spill failure', sample['write_error'])
                self.assertEqual(sample['received_bytes'], session.LOG_LINE_LIMIT + 1)
                with self.assertRaisesRegex(SerialCloseError, 'simulated log spill failure'):
                    session.close()
                self.assertTrue(driver.closed)
                self.assertIsNone(session._log_handle)
                self.assertFalse(driver.writes)
            finally:
                # The production manager fences an unconfirmed shutdown. Release the fixture lock.
                if session._host_resource_lock:
                    session._host_resource_lock.close()

    def test_1_2_4_8_mib_keep_a_constant_resident_window_and_complete_raw_history(self):
        session, driver = self.session()
        block = b'12345678' * 8192
        expected = hashlib.sha256()
        try:
            for count in range(1, 129):
                driver.input.put(block)
                expected.update(block)
                if count in (16, 32, 64, 128):
                    size = len(block) * count
                    self.await_cursor(session, size)
                    with session._condition:
                        sample = HistoryRegistry.inspect(session, {})
                    self.assertEqual(sample['received_bytes'], size)
                    self.assertLessEqual(sample['history_high_water_bytes'], session.HISTORY_LIMIT)
                    self.assertEqual(sample['history_bytes'] + sample['history_spilled_bytes'], size)
                    actual = hashlib.sha256()
                    for part in session.iter_rx_history():
                        self.assertLessEqual(len(part), session.READ_CHUNK)
                        actual.update(part)
                    self.assertEqual(actual.digest(), expected.digest())
            self.assertFalse(driver.writes)
        finally:
            session.close()
