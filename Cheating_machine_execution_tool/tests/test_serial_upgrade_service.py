import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from line_check_assistant.network_ops import CommandResult
from src.models import FullPackageUpgradeRequest
from src.services.serial_upgrade_service import TRANSFER_TFTP_PUT, SerialUpgradeController, run_single_full_package_upgrade


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


class FakeSessionManager:
    def __init__(self, session):
        self.session = session
        self.released = []

    def acquire_control(self, _owner, _settings, _log_path):
        return self.session

    def release(self, owner, port):
        self.released.append((owner, port))


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

    @patch.object(SerialUpgradeController, "monitor_post_tftp", return_value=False)
    @patch("src.services.serial_upgrade_service.upload_firmware")
    @patch("src.services.serial_upgrade_service.prepare_tftp_network", return_value=CommandResult(True, "network ready"))
    @patch("src.services.serial_upgrade_service.power_on_selected_channels")
    def test_full_package_upgrade_uses_direct_power_channel_for_initial_and_repower(
        self,
        direct_power,
        _prepare_network,
        _upload_firmware,
        _monitor_post_tftp,
    ):
        session = FakeSession(any_results=["#", "login", "password", "#"])
        manager = FakeSessionManager(session)
        request = FullPackageUpgradeRequest(
            vlan="vlan102",
            server_interface="VLAN102",
            tftp_server_ip="192.168.1.102",
            firmware_path=Path(r"F:\firmware\tclinux_allinone"),
            power_serial_port="COM106",
            final_username="root",
            final_password="secret",
            transfer_method=TRANSFER_TFTP_PUT,
            power_channel=2,
        )

        def fake_power(*_args, **kwargs):
            callback = kwargs.get("on_channel_powered")
            if callback:
                callback(2)
            return CommandResult(True, "power ready")

        direct_power.side_effect = fake_power

        result = run_single_full_package_upgrade(request, manager, sleep_fn=lambda _seconds: None)

        self.assertTrue(result.ok)
        self.assertEqual(direct_power.call_count, 2)
        self.assertEqual(direct_power.call_args_list[0].args[:2], ("COM106", [2]))
        self.assertEqual(direct_power.call_args_list[1].args[:2], ("COM106", [2]))
        self.assertIn("on_channel_powered", direct_power.call_args_list[0].kwargs)
        self.assertEqual(len(manager.released), 1)
