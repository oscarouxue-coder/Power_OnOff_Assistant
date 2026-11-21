"""Per-channel power acknowledgements with deterministic serial and timing boundaries."""
import importlib
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class PowerCommandReceiptTests(unittest.TestCase):
    def setUp(self):
        legacy = Path(__file__).resolve().parents[1] / 'Auto_power_on_off_tool'
        with patch.object(sys, 'path', [str(legacy), *sys.path]):
            self.module = importlib.import_module('common.power_on_off')
        self.power = self.module.PowerOnOff(Mock())
        self.power.stop_event = threading.Event()
        self.power.set_interval(0)
        self.port = Mock()

    def start_consumer(self):
        consumer = threading.Thread(target=self.power.consumer, daemon=True)
        consumer.start()

        def stop_consumer():
            self.power.stop_event.set()
            consumer.join(4)
            self.assertFalse(consumer.is_alive())

        self.addCleanup(stop_consumer)

    def test_receipt_after_write_and_stop_discards_next_channel(self):
        writing, allow_write = threading.Event(), threading.Event()
        settling, allow_settle = threading.Event(), threading.Event()

        def write(_payload):
            writing.set()
            self.assertTrue(allow_write.wait(3))

        def sleep(duration):
            if duration == 3:
                settling.set()
                self.assertTrue(allow_settle.wait(3))

        self.port.write.side_effect = write
        with patch.object(self.module, 'time', SimpleNamespace(sleep=sleep)), ThreadPoolExecutor(2) as pool:
            self.start_consumer()
            try:
                first = pool.submit(self.power.producer, (self.power.power_on, self.port, 3))
                self.assertTrue(writing.wait(3))
                self.assertFalse(first.done())
                self.assertEqual(self.power.switch_status_list[2], 0)
                allow_write.set()
                self.assertTrue(settling.wait(3))
                first.result(3)
                self.assertEqual(self.power.switch_status_list[2], 1)
                queued = threading.Event()
                put = self.power.PowerTaskQueue.put

                def enqueue(command):
                    put(command)
                    queued.set()

                with patch.object(self.power.PowerTaskQueue, 'put', enqueue):
                    second = pool.submit(self.power.producer, (self.power.power_on, self.port, 9))
                    self.assertTrue(queued.wait(3))
                    self.power.stop_event.set()
                    with self.assertRaises(self.module.PowerCommandCancelled):
                        second.result(3)
            finally:
                self.power.stop_event.set()
                allow_write.set()
                allow_settle.set()
        self.port.write.assert_called_once_with(bytes.fromhex('5501a00003a2'))

    def test_partial_write_latches_failure_without_repower_or_cached_success(self):
        serial_port = self.module.Serial.__new__(self.module.Serial)
        serial_port.ser = self.port
        self.port.write.return_value = 5
        self.start_consumer()
        with ThreadPoolExecutor(2) as pool:
            failed = pool.submit(self.power.producer, (self.power.power_on, serial_port, 3))
            with self.assertRaisesRegex(self.module.PowerCommandError, '5/6'):
                failed.result(3)
            next_channel = pool.submit(self.power.producer, (self.power.power_on, serial_port, 9))
            with self.assertRaisesRegex(self.module.PowerCommandError, '5/6'):
                next_channel.result(3)
        self.assertEqual(self.power.switch_status_list, [0] * 16)
        self.port.write.assert_called_once()
