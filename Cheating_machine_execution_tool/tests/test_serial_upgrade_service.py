import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.serial_upgrade_service import SerialUpgradeController


class FakeSession:
    def __init__(self, any_results=(), all_result=True):
        self.any_results = list(any_results)
        self.all_result = all_result
        self.writes = []

    def cursor(self):
        return 0

    def write(self, data, sensitive=False):
        self.writes.append((data, sensitive))

    def send_line(self, text, sensitive=False):
        self.writes.append((text.encode("utf-8") + b"\r", sensitive))

    def wait_for_any(self, _markers, _timeout, _cursor):
        return self.any_results.pop(0) if self.any_results else None

    def wait_for_all(self, _markers, _timeout, _cursor):
        return self.all_result


class SerialUpgradeControllerTests(unittest.TestCase):
    def test_tftp_command_requires_done_and_write_stage_result(self):
        session = FakeSession(all_result=True)
        controller = SerialUpgradeController(session, sleep_fn=lambda _seconds: None)

        result = controller.send_tftp_command_and_wait("tftp 192.168.1.101:tclinux_allinone")

        self.assertTrue(result.ok)
        self.assertEqual(session.writes[0][0], b"tftp 192.168.1.101:tclinux_allinone\r")

    def test_boot_login_and_factory_reset_preserve_send_timing_order(self):
        event = threading.Event()
        event.set()
        session = FakeSession(any_results=["username:", "username:", "password:", "#"])
        sleeps = []
        controller = SerialUpgradeController(session, sleep_fn=sleeps.append)

        result = controller.wait_for_boot_login(event, timeout_seconds=1)
        controller.restore_factory_if_enabled(True)

        self.assertTrue(result.ok)
        values = [item[0] for item in session.writes]
        self.assertIn(b"firstboot -y;reboot", values)
        factory_index = values.index(b"firstboot -y;reboot")
        self.assertEqual(values[factory_index + 1], b"\r")
        self.assertEqual(sleeps[-2:], [1, 8])

    def test_post_tftp_boot_marker_sends_reset_once(self):
        session = FakeSession(any_results=["boot"])
        controller = SerialUpgradeController(session, sleep_fn=lambda _seconds: None)

        self.assertTrue(controller.monitor_post_tftp(seconds=1))
        self.assertEqual(session.writes, [(b"reset\r", False)])
