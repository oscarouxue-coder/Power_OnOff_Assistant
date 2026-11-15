"""Read-only sampling and existing log limitations; no physical IO devices."""
import gc
import io
import json
import queue
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import weakref

from src.core.transport_observation import HistoryRegistry
from src.core.serial_transport import PySerialSession
from src.models.serial_models import SerialSettings
from src.services.transport_history_monitor import TransportHistoryMonitor


class HistoryMonitorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.registry = HistoryRegistry()

    def session(self):
        session = PySerialSession(SerialSettings("SIM_ONLY"))
        self.registry.register(session, "serial", "SIM_ONLY")
        return session

    def test_reads_lengths_without_consuming_or_rewriting_history(self):
        session = self.session()
        session._history.extend(b"raw\xff\r\n")
        session._rx_log_line_buffer = "pending"
        before = bytes(session._history)
        row = self.registry.collect()["sessions"][0]
        self.assertEqual(row["history_bytes"], 6)
        self.assertEqual(row["received_bytes"], 6)
        self.assertEqual(row["pending_rx_chars"], 7)
        self.assertIsNone(row["history_limit_bytes"])
        self.assertIsNone(row["last_flush_confirmed"])
        self.assertEqual(bytes(session._history), before)

    def test_busy_history_lock_is_skipped_instead_of_blocking(self):
        session = self.session()
        ready, release = threading.Event(), threading.Event()
        def worker():
            with session._condition:
                ready.set()
                release.wait(3)
        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(ready.wait(1))
            start = time.monotonic()
            self.assertEqual(self.registry.collect()["sessions"][0]["sample_status"], "busy")
            self.assertLess(time.monotonic()-start, .2)
        finally:
            release.set(); thread.join(3)

    def test_registry_does_not_retain_retired_sessions(self):
        session = self.session()
        session._history.extend(b"retained on disk only")
        reference = weakref.ref(session)
        self.registry.retire(session)
        final = self.registry.collect()["sessions"]
        self.assertTrue(final[0]["final"])
        del session
        gc.collect()
        self.assertIsNone(reference())
        self.assertEqual(self.registry.collect()["sessions"], [])

    def test_transport_close_observation_performs_no_filesystem_io(self):
        session = self.session()
        session.log_path = self.directory / "offline-volume.log"
        with patch.object(Path, "stat", side_effect=AssertionError("IO on transport close")), patch("src.core.transport_observation.shutil.disk_usage", side_effect=AssertionError("disk probe on transport close")):
            self.registry.retire(session)

    def test_file_size_and_partial_line_are_not_claimed_as_byte_fidelity(self):
        session = self.session()
        path = self.directory / "capture.log"
        path.write_text("timestamp RX payload\n", encoding="utf-8")
        session.log_path = path
        session._log_handle = io.StringIO()
        session._rx_log_line_buffer = "not flushed"
        row = self.registry.collect()["sessions"][0]
        self.assertEqual(row["log_file_bytes"], path.stat().st_size)
        self.assertGreater(row["log_disk_free_bytes"], 0)
        self.assertEqual(row["pending_rx_chars"], 11)
        self.assertEqual(row["write_status"], "open_unverified")

    def test_reader_failure_and_file_stat_failure_are_visible(self):
        session = self.session()
        session.log_path = self.directory / "missing.log"
        session._reader = Mock()
        session._reader.is_alive.return_value = False
        row = self.registry.collect()["sessions"][0]
        self.assertEqual(row["write_status"], "reader_stopped_unexpectedly")
        self.assertIsNotNone(row["write_error"])

    def test_growth_and_closed_totals_do_not_double_count(self):
        monitor = TransportHistoryMonitor(self.directory, Mock(), registry=self.registry)
        session = self.session()
        session._history.extend(b"abcd")
        monitor.sample()
        time.sleep(.02)  # Windows monotonic clock can have a coarse tick.
        session._history.extend(b"efgh")
        row = monitor.sample()["sessions"][0]
        self.assertGreater(row["history_bytes_per_second"], 0)
        session._closed = True
        self.registry.retire(session)
        self.assertEqual(monitor.sample()["closed_received_bytes"]["serial:SIM_ONLY"], 8)
        self.assertEqual(monitor.sample()["closed_received_bytes"]["serial:SIM_ONLY"], 8)

    def test_background_monitor_stops_with_final_sample(self):
        monitor = TransportHistoryMonitor(self.directory, Mock(), interval=.02, registry=self.registry)
        monitor.start()
        limit = time.monotonic()+2
        while not monitor.path.exists() and time.monotonic() < limit: time.sleep(.01)
        monitor.begin_close(); monitor.thread.join(3)
        self.assertTrue(monitor.idle)
        rows = [json.loads(line) for line in monitor.path.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(rows[-1]["final_sample"])

    def test_monitor_write_failure_is_reported_and_does_not_escape(self):
        messages = []
        monitor = TransportHistoryMonitor(self.directory, messages.append, registry=self.registry)
        monitor.stop.set()
        with patch.object(Path, "open", side_effect=OSError("simulated monitor disk error")):
            monitor._loop()
        self.assertTrue(any("OSError" in m for m in messages))

    def test_monitor_thread_start_failure_does_not_abort_application(self):
        messages = []
        monitor = TransportHistoryMonitor(self.directory, messages.append, registry=self.registry)
        with patch.object(threading.Thread, "start", side_effect=RuntimeError("simulated thread limit")):
            monitor.start()
        self.assertTrue(monitor.idle)
        self.assertTrue(any("RuntimeError" in message for message in messages))

    def test_main_close_waits_for_monitor_without_joining_on_ui_thread(self):
        from line_check_assistant.app import LineCheckAssistant
        messages, persisted = queue.Queue(), []
        monitor = TransportHistoryMonitor(self.directory, messages.put, interval=60, registry=self.registry)
        monitor.start()
        app = SimpleNamespace(transport_history_monitor=monitor, after=Mock(), destroy=Mock(),
                              onu_save_after_id=None, sample_upgrade_save_after_id=None,
                              _save_onu_registration_config=Mock(), _save_sample_upgrade_settings=Mock(), log_queue=messages)
        def drain():
            while not messages.empty(): persisted.append(messages.get_nowait())
        app._drain_log_queue = drain
        app._on_app_close = lambda: LineCheckAssistant._on_app_close(app)
        app._on_app_close()
        if not monitor.idle: app.destroy.assert_not_called()
        monitor.thread.join(3)
        self.assertTrue(monitor.idle)
        if not app.destroy.called: app._on_app_close()
        app.destroy.assert_called_once()
        self.assertTrue(any("已停止采样" in message for message in persisted))
        self.assertTrue(json.loads(monitor.path.read_text(encoding="utf-8").splitlines()[-1])["final_sample"])


if __name__ == "__main__": unittest.main()
