import threading
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from line_check_assistant.network_ops import CommandResult
from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings, SampleUpgradeSettingsStore
from src.models.boot_entry import BOOT_ENTRY_LOGIN, BOOT_ENTRY_SDMC
from src.models.serial_models import FullPackageUpgradeRequest
from src.services.sdmc_boot_entry import enter_sdmc_boot
from src.services.serial_upgrade_service import run_single_full_package_upgrade


class TimedSession:
    def __init__(self, response="", response_at=0.4):
        self.now = 0.0
        self.response = response
        self.response_at = response_at
        self.writes = []
        self.cursors = []

    def cursor(self):
        return 42

    def write(self, data):
        self.writes.append((round(self.now, 6), data))

    def wait_for_any(self, markers, timeout, cursor):
        self.cursors.append(cursor)
        self.now += timeout
        if self.now >= self.response_at:
            return next((m for m in markers if m in self.response.lower()), None)
        return None


class SdmcBootEntryTests(unittest.TestCase):
    def run_entry(self, session, timeout=3, cancel=None):
        messages = []
        result = enter_sdmc_boot(session, cancel or threading.Event(), messages.append,
                                 timeout_seconds=timeout, clock=lambda: session.now)
        return result, messages

    def test_success_markers_stop_without_credentials(self):
        for marker in ("=>", "ECNT>", "U-Boot>", "#", ">"):
            with self.subTest(marker=marker):
                session = TimedSession(marker)
                result, messages = self.run_entry(session)
                self.assertTrue(result.ok)
                self.assertEqual(session.writes, [(0.0, b"sdmc\r")])
                self.assertTrue(all(c == 42 for c in session.cursors))
                self.assertIn("TX sdmc [回车]", messages)
                self.assertIn("命中提示符", messages[-1])

    def test_repeat_every_second_and_timeout_on_login_prompts(self):
        session = TimedSession("UserName: Password: Passvord: done write")
        result, messages = self.run_entry(session)
        self.assertFalse(result.ok)
        self.assertEqual(session.writes, [(0.0, b"sdmc\r"), (1.0, b"sdmc\r"), (2.0, b"sdmc\r")])
        self.assertIn("超时", messages[-1])

    def test_prompt_before_next_send_does_not_send_again(self):
        session = TimedSession("=>", response_at=1.0)
        result, _ = self.run_entry(session)
        self.assertTrue(result.ok)
        self.assertEqual(len(session.writes), 1)

    def test_cancel_prevents_send(self):
        cancel = threading.Event()
        cancel.set()
        session = TimedSession()
        result, messages = self.run_entry(session, cancel=cancel)
        self.assertFalse(result.ok)
        self.assertEqual(session.writes, [])
        self.assertIn("取消", messages[-1])

    def test_serial_failure_is_logged(self):
        session = TimedSession()
        session.write = Mock(side_effect=RuntimeError("closed"))
        result, messages = self.run_entry(session)
        self.assertFalse(result.ok)
        self.assertIn("closed", messages[-1])

    def test_setting_roundtrip_and_legacy_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.ini"
            store = SampleUpgradeSettingsStore(path)
            self.assertEqual(store.load().boot_entry_method, BOOT_ENTRY_LOGIN)
            store.save(SampleUpgradeSettings(boot_entry_method=BOOT_ENTRY_SDMC))
            self.assertEqual(store.load().boot_entry_method, BOOT_ENTRY_SDMC)
            path.write_text("[sample_upgrade]\nboot_entry_method=unknown\n", encoding="utf-8")
            self.assertEqual(store.load().boot_entry_method, BOOT_ENTRY_LOGIN)

    def run_flow(self, transfer, success=True, restore=False):
        prefix = "src.services.serial_upgrade_service."
        with ExitStack() as stack:
            folder = stack.enter_context(tempfile.TemporaryDirectory())
            stack.enter_context(patch(prefix + "DEFAULT_LOG_DIR", Path(folder)))
            controller = stack.enter_context(patch(prefix + "SerialUpgradeController")).return_value
            controller._cancel = threading.Event()
            controller.monitor_post_tftp.return_value = True
            controller.send_tftp_command_and_wait.return_value = CommandResult(True, "done write")
            controller.login_final_system.return_value = CommandResult(True, "shell")
            power = stack.enter_context(patch(prefix + "_power_cycle_current_channel", return_value=CommandResult(True, "power")))
            def enter(*args):
                self.assertTrue(power.called)
                self.assertEqual(power.call_args.kwargs["off_delay_seconds"], 1)
                self.assertEqual(power.call_args.kwargs["on_delay_seconds"], 1)
                return CommandResult(success, "SDMC result")
            sdmc = stack.enter_context(patch(prefix + "enter_sdmc_boot", side_effect=enter))
            network = stack.enter_context(patch(prefix + "prepare_tftp_network", return_value=CommandResult(True, "network")))
            server = stack.enter_context(patch(prefix + "TftpServerHandle")).return_value
            upload = stack.enter_context(patch(prefix + "upload_firmware"))
            manager = Mock()
            request = FullPackageUpgradeRequest("vlan112", "VLAN112", "192.168.1.112", Path("fw.bin"),
                "COM102", "final-user", "final-pass", restore_factory=restore,
                transfer_method=transfer, power_channel=4, boot_entry_method=BOOT_ENTRY_SDMC)
            result = run_single_full_package_upgrade(request, manager, sleep_fn=lambda _: None)
            self.assertEqual(result.ok, success)
            sdmc.assert_called_once()
            controller.wait_for_boot_login.assert_not_called()
            controller.wait_for_tftp_put_boot_username.assert_not_called()
            controller.login_tftp_put_boot_after_username.assert_not_called()
            manager.release.assert_called_once()
            if success:
                network.assert_called_once()
                if transfer == "Tftp Put":
                    upload.assert_called_once()
                else:
                    server.start.assert_called_once()
                    server.stop.assert_called_once()
                    controller.send_tftp_command_and_wait.assert_called_once()
                if restore:
                    controller.login_final_system.assert_called_once_with("final-user", "final-pass")
                    controller.restore_factory_if_enabled.assert_called_once()
                else:
                    controller.login_final_system.assert_not_called()
            else:
                network.assert_not_called()
                upload.assert_not_called()
                server.start.assert_not_called()
                controller.login_final_system.assert_not_called()

    def test_both_transfers_use_sdmc_after_power_and_skip_boot_credentials(self):
        for transfer in ("Tftp指令", "Tftp Put"):
            with self.subTest(transfer=transfer):
                self.run_flow(transfer)

    def test_sdmc_failure_blocks_both_transfers(self):
        for transfer in ("Tftp指令", "Tftp Put"):
            with self.subTest(transfer=transfer):
                self.run_flow(transfer, success=False)

    def test_factory_reset_still_requires_final_login_for_both_transfers(self):
        for transfer in ("Tftp指令", "Tftp Put"):
            with self.subTest(transfer=transfer):
                self.run_flow(transfer, restore=True)

    def test_unattended_confirmation_includes_selected_boot_method(self):
        from types import SimpleNamespace
        from line_check_assistant.pipeline_window import PipelineWindow
        settings = SampleUpgradeSettings(boot_entry_method=BOOT_ENTRY_SDMC)
        context = SimpleNamespace(sample_upgrade_settings=settings)
        note = PipelineWindow._unattended_confirmation_note(context, {"sample_upgrade"}, True)
        self.assertIn("进入 Boot 方式：SDMC 指令进入", note)
        settings.upgrade_mode = "页面升级"
        note = PipelineWindow._unattended_confirmation_note(context, {"sample_upgrade"}, True)
        self.assertNotIn("进入 Boot 方式", note)
