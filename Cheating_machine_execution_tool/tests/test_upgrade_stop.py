"""Safe stop boundaries use simulated IO only; no real DUT or power commands."""
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from line_check_assistant.app import LineCheckAssistant
from line_check_assistant.network_ops import CommandResult
from line_check_assistant.page_upgrade import PageUpgradeRequest, run_single_page_upgrade, run_page_upgrade_batch
from line_check_assistant.pipeline_window import PipelineWindow
from src.core.gateway_proxy import GatewayProxy
from src.core.gateway_browser import GatewayBrowser
from src.models import FullPackageUpgradeRequest
from src.models.upgrade_stop import UpgradeStopped, UpgradeStoppedResult
from src.services.serial_upgrade_service import (
    SerialUpgradeController, UpgradePowerCycleCoordinator,
    FullPackageUpgradeItemResult, run_single_full_package_upgrade,
    run_parallel_tftp_command_upgrades, run_parallel_tftp_put_upgrades,
)
from src.services.upgrade_stop_service import (
    UpgradeRun, UpgradeStopControl, StopAwareSerialSession, stopped_result, summarize_results,
)
from src.services.web_gateway_upgrade_service import start_gateway_upgrade, run_parallel_web_gateway_upgrades
from src.services.pipeline_orchestrator import PipelineOrchestrator


class UpgradeStopTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.firmware = Path(self.folder.name, "firmware.bin")
        self.firmware.write_bytes(b"simulated firmware")
        self.control = UpgradeStopControl()

    def request(self, transfer="Tftp Put", vlan="vlan101", restore=True):
        return FullPackageUpgradeRequest(
            vlan, vlan.upper(), "192.168.1." + vlan[4:], self.firmware,
            "COM106", "root", "test", transfer_method=transfer,
            restore_factory=restore, serial_port="COM" + vlan[4:], power_channel=1,
            web_source_ip="192.168.1." + vlan[4:], web_device_ip="192.168.1.1",
        )

    def page_request(self):
        return PageUpgradeRequest("vlan101", "192.168.1.101", "192.168.1.1", "root", "test", self.firmware, restore_factory=True)

    def test_protection_is_thread_local_not_batch_wide(self):
        self.control.request_stop()
        errors = []
        with self.control.protect():
            self.control.checkpoint()
            def other_worker():
                try:
                    self.control.checkpoint()
                except UpgradeStopped:
                    errors.append("stopped")
            worker = threading.Thread(target=other_worker)
            worker.start()
            worker.join(1)
        self.assertEqual(errors, ["stopped"])
        with self.assertRaises(UpgradeStopped):
            self.control.checkpoint()

    def test_long_wait_wakes_on_stop(self):
        entered = threading.Event()
        stopped = threading.Event()
        def wait():
            entered.set()
            try:
                self.control.sleep(120)
            except UpgradeStopped:
                stopped.set()
        worker = threading.Thread(target=wait, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(1))
        self.control.request_stop()
        self.assertTrue(stopped.wait(1))
        worker.join(1)

    def test_serial_wait_stops_without_next_write(self):
        session = Mock()
        session.wait_for_any.side_effect = lambda *args: self.control.request_stop()
        guarded = StopAwareSerialSession(session, self.control)
        with self.assertRaises(UpgradeStopped):
            guarded.wait_for_any(("login",), 900, 0)
        with self.assertRaises(UpgradeStopped):
            guarded.send_line("reset")
        session.send_line.assert_not_called()

    def test_controller_cleanup_does_not_stop_other_devices(self):
        controller = SerialUpgradeController(Mock(), stop_control=self.control)
        controller.cancel()
        self.assertFalse(self.control.is_set())

    def test_tftp_command_finishes_current_attempt_but_never_retries(self):
        for outcome in ((True, False), (False, True), (False, False)):
            with self.subTest(outcome=outcome):
                control = UpgradeStopControl()
                session = Mock()
                controller = SerialUpgradeController(session, sleep_fn=Mock(), stop_control=control)
                def transfer(*args):
                    control.request_stop()
                    control.checkpoint()  # protected current attempt
                    return outcome
                controller._wait_for_tftp_completion_or_arp_failure = Mock(side_effect=transfer)
                with self.assertRaises(UpgradeStopped):
                    controller.send_tftp_command_and_wait("tftp 192.168.1.101:tclinux_allinone")
                session.send_line.assert_called_once()

    def test_stop_during_boot_observation_never_sends_reset(self):
        session = Mock()
        session.wait_for_any.side_effect = lambda *args: self.control.request_stop() or "boot"
        controller = SerialUpgradeController(session, stop_control=self.control)
        with self.assertRaises(UpgradeStopped):
            controller.monitor_post_tftp()
        session.send_line.assert_not_called()

    def test_factory_command_is_not_started_after_stop(self):
        session = Mock()
        controller = SerialUpgradeController(session, stop_control=self.control)
        self.control.request_stop()
        with self.assertRaises(UpgradeStopped):
            controller.restore_factory_if_enabled(True)
        session.write.assert_not_called()

    def test_admitted_factory_command_finishes_enter_before_stopping(self):
        session = Mock()
        controller = SerialUpgradeController(session, stop_control=self.control, sleep_fn=lambda seconds: self.control.request_stop())
        with self.assertRaises(UpgradeStopped):
            controller.restore_factory_if_enabled(True)
        self.assertEqual([call.args[0] for call in session.write.call_args_list], [b"firstboot -y;reboot", b"\r"])

    def test_admitted_power_action_completes_pair(self):
        actions = []
        supply = Mock()
        def pair(*args, **kwargs):
            actions.append("off")
            self.control.request_stop()
            actions.append("on")
        supply.power_on_channels.side_effect = pair
        with UpgradePowerCycleCoordinator(supply_factory=lambda *args, **kwargs: supply) as coordinator:
            result = coordinator.power_on_channel("COM106", 1, wait_seconds=0, stop_control=self.control)
        self.assertTrue(result.ok)
        self.assertEqual(actions, ["off", "on"])
        supply.close.assert_called_once()

    def test_stop_before_shared_power_action_does_not_open_port(self):
        factory = Mock()
        self.control.request_stop()
        with UpgradePowerCycleCoordinator(supply_factory=factory) as coordinator:
            with self.assertRaises(UpgradeStopped):
                coordinator.power_on_channel("COM106", 1, wait_seconds=0, stop_control=self.control)
        factory.assert_not_called()

    def test_tftp_put_stop_after_upload_skips_observation_repower_and_factory(self):
        prefix = "src.services.serial_upgrade_service."
        with ExitStack() as stack:
            stack.enter_context(patch(prefix + "DEFAULT_LOG_DIR", Path(self.folder.name)))
            controller = stack.enter_context(patch(prefix + "SerialUpgradeController")).return_value
            controller.wait_for_tftp_put_boot_username.return_value = CommandResult(True, "ready")
            controller.login_tftp_put_boot_after_username.return_value = CommandResult(True, "ready")
            power = stack.enter_context(patch(prefix + "_power_cycle_current_channel", return_value=CommandResult(True, "power")))
            stack.enter_context(patch(prefix + "prepare_tftp_network", return_value=CommandResult(True, "network")))
            upload = stack.enter_context(patch(prefix + "upload_firmware", side_effect=lambda *args, **kwargs: self.control.request_stop()))
            manager = Mock()
            result = run_single_full_package_upgrade(self.request(), manager, stop_control=self.control)
        self.assertIsInstance(result, UpgradeStoppedResult)
        upload.assert_called_once()
        self.assertEqual(power.call_count, 1)
        controller.monitor_post_tftp.assert_not_called()
        controller.login_final_system.assert_not_called()
        controller.restore_factory_if_enabled.assert_not_called()
        manager.release.assert_called_once()

    def test_parallel_all_transfers_skip_queued_targets(self):
        runners = (("Tftp指令", run_parallel_tftp_command_upgrades), ("Tftp Put", run_parallel_tftp_put_upgrades), ("web打开网关", run_parallel_web_gateway_upgrades))
        for transfer, runner in runners:
            with self.subTest(transfer=transfer):
                control = UpgradeStopControl()
                requests = [self.request(transfer, f"vlan{n}") for n in (101, 102, 103)]
                def first(request, *args, **kwargs):
                    control.request_stop()
                    return stopped_result(request.vlan)
                with patch("src.services.serial_upgrade_service.run_single_full_package_upgrade", side_effect=first) as single, patch("src.services.web_gateway_upgrade_service.find_gateway_browser"):
                    results = runner(requests, Mock(), max_workers=1, stop_control=control)
                self.assertEqual(single.call_count, 1)
                self.assertEqual([item.request for item in results], requests)
                self.assertEqual([item.result.skipped for item in results], [False, True, True])

    def test_page_stop_after_upload_does_not_trigger_upgrade(self):
        client = Mock()
        client.login.return_value = True
        client.upload_file.side_effect = lambda *args: self.control.request_stop() or (200, "ok")
        result = run_single_page_upgrade(self.page_request(), client_factory=lambda ip: client, stop_control=self.control)
        self.assertIsInstance(result, UpgradeStoppedResult)
        client.trigger_upgrade.assert_not_called()
        client.trigger_factory_reset.assert_not_called()
        client.logout.assert_called_once()
        client.session.close.assert_called_once()

    def test_page_stop_after_trigger_preserves_read_only_status_then_exits(self):
        client = Mock()
        client.login.return_value = True
        client.upload_file.return_value = (200, "ok")
        client.trigger_upgrade.side_effect = lambda **kwargs: self.control.request_stop() or "bbfdm.operate"
        client.query_upgrade_status.return_value = 9
        result = run_single_page_upgrade(self.page_request(), client_factory=lambda ip: client, stop_control=self.control)
        self.assertIsInstance(result, UpgradeStoppedResult)
        client.query_upgrade_status.assert_called_once()
        self.assertEqual(client.login.call_count, 1)
        client.trigger_factory_reset.assert_not_called()

    def test_page_batch_already_stopped_never_creates_client(self):
        self.control.request_stop()
        with patch("line_check_assistant.page_upgrade.requests.Session") as client:
            results = run_page_upgrade_batch([self.page_request()] * 3, max_workers=1, stop_control=self.control)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(item.result.skipped for item in results))
        client.assert_not_called()

    def test_page_stop_while_waiting_for_reboot_skips_login_and_factory(self):
        client = Mock()
        client.login.return_value = True
        client.upload_file.return_value = (200, "ok")
        client.query_upgrade_status.return_value = 9
        result = run_single_page_upgrade(
            self.page_request(), client_factory=lambda ip: client,
            stop_control=self.control, sleep_fn=lambda seconds: self.control.request_stop(),
        )
        self.assertIsInstance(result, UpgradeStoppedResult)
        self.assertIn("设备最终结果待确认", result.message)
        self.assertEqual(client.login.call_count, 1)
        client.trigger_factory_reset.assert_not_called()

    def test_page_stop_during_status_poll_still_observes_terminal_status(self):
        client = Mock()
        client.login.return_value = True
        client.upload_file.return_value = (200, "ok")
        client.query_upgrade_status.side_effect = [None, 9]
        result = run_single_page_upgrade(
            self.page_request(), client_factory=lambda ip: client,
            stop_control=self.control, sleep_fn=lambda seconds: self.control.request_stop(),
        )
        self.assertIsInstance(result, UpgradeStoppedResult)
        self.assertEqual(client.query_upgrade_status.call_count, 2)
        client.trigger_factory_reset.assert_not_called()

    def test_page_status_timeout_after_stop_is_not_reported_success(self):
        client = Mock()
        client.login.return_value = True
        client.upload_file.return_value = (200, "ok")
        client.trigger_upgrade.side_effect = lambda **kwargs: self.control.request_stop() or "triggered"
        result = run_single_page_upgrade(
            self.page_request(), client_factory=lambda ip: client,
            stop_control=self.control, status_timeout_seconds=0,
        )
        self.assertIsInstance(result, UpgradeStoppedResult)
        self.assertFalse(result.ok)
        self.assertIn("设备最终结果待确认", result.message)

    def test_web_stop_before_submit_does_not_click_or_start_upload(self):
        browser = GatewayBrowser("127.0.0.1", 1, "127.0.0.2", Mock())
        browser.stop_control = self.control
        browser.cdp = Mock()
        self.control.request_stop()
        with self.assertRaises(UpgradeStopped):
            browser.submit_firmware(self.firmware)
        self.assertFalse(browser.submitted)
        browser.cdp.evaluate.assert_not_called()

    def test_proxy_upload_failure_releases_drain_waiter(self):
        proxy = GatewayProxy("127.0.0.1", 1, "127.0.0.2", Mock())
        proxy.expect_upload()
        client = Mock()
        client.recv.return_value = b"POST http://127.0.0.2/upgrade HTTP/1.1\r\nContent-Length: 1\r\n\r\nx"
        with patch.object(proxy, "_connect", side_effect=OSError("simulated connection failure")):
            proxy._handle(client)
        self.assertTrue(proxy.upload_seen)
        self.assertEqual(proxy.upload_active, 0)
        self.assertTrue(proxy.wait_for_upload_completion(timeout=0))

    def test_web_stop_after_click_drains_upload_before_browser_close(self):
        prefix = "src.services.web_gateway_upgrade_service."
        events = []
        browser = Mock(submitted=False, submitted_at=None)
        def submit(path):
            events.append("submit")
            browser.submitted = True
            browser.submitted_at = time.monotonic() - 31
            self.control.request_stop()
        browser.submit_firmware.side_effect = submit
        browser.wait_for_upload_completion.side_effect = lambda: events.append("drain")
        browser.close.side_effect = lambda: events.append("close")
        with patch(prefix + "prepare_network_for_sample", return_value=CommandResult(True, "network")), patch(prefix + "wait_for_bindable_ip", return_value=True), patch(prefix + "selected_interface_index", return_value=7), patch(prefix + "GatewayBrowser", return_value=browser):
            with self.assertRaises(UpgradeStopped):
                start_gateway_upgrade(self.request("web打开网关"), Mock(), lambda seconds: events.append(seconds), stop_control=self.control)
        self.assertEqual(events[:3], ["submit", 30, "drain"])
        self.assertEqual(events[-1], "close")
        self.assertLess(events.index("drain"), events.index("close"))
        self.assertEqual(events.count("drain"), 1)
        self.assertEqual(events.count(30), 1)

    def test_web_proxy_drain_does_not_close_active_upload(self):
        proxy = GatewayProxy("127.0.0.1", 1, "127.0.0.2", Mock())
        proxy.expect_upload()
        proxy.upload_seen = True
        proxy.upload_active = 1
        finished = threading.Event()
        thread = threading.Thread(target=lambda: (proxy.wait_for_upload_completion(timeout=0), finished.set()), daemon=True)
        thread.start()
        self.assertFalse(finished.wait(0.05))
        self.assertFalse(proxy.stop_event.is_set())
        with proxy.upload_condition:
            proxy.upload_active = 0
            proxy.upload_condition.notify_all()
        self.assertTrue(finished.wait(1))
        thread.join(1)

    def test_web_proxy_unobserved_upload_times_out_as_unknown(self):
        proxy = GatewayProxy("127.0.0.1", 1, "127.0.0.2", Mock())
        proxy.expect_upload()
        self.assertFalse(proxy.wait_for_upload_completion(timeout=0))
        self.assertIn("设备结果待确认", proxy.log.call_args.args[0])

    def ui(self, run=None):
        run = run or UpgradeRun()
        run.thread = Mock(is_alive=Mock(return_value=False))
        app = SimpleNamespace(
            _sample_upgrade_run=run, sample_upgrade_running=True,
            upgrade_start_button=Mock(), upgrade_stop_button=Mock(),
            upgrade_status_var=Mock(), upgrade_progress_var=Mock(get=Mock(return_value=40)),
            _log=Mock(), _set_upgrade_status=Mock(), after=Mock(),
            pipeline_window=Mock(), serial_terminal=Mock(),
            _pipeline_subtask_events={},
        )
        return app, run

    def test_ui_stop_is_idempotent_and_links_only_owned_pipeline(self):
        for owned in (False, True):
            app, run = self.ui(UpgradeRun(pipeline_owned=owned))
            LineCheckAssistant._stop_sample_upgrade(app)
            LineCheckAssistant._stop_sample_upgrade(app)
            self.assertTrue(run.control.is_set())
            app._log.assert_called_once()
            self.assertEqual(app.pipeline_window.request_stop.call_count, int(owned))
            app.upgrade_stop_button.configure.assert_called_with(state="disabled")
            app.upgrade_start_button.configure.assert_called_with(state="disabled")

    def test_pipeline_stop_does_not_cancel_independent_upgrade(self):
        app, run = self.ui()
        LineCheckAssistant._stop_sample_upgrade(app, from_pipeline=True)
        self.assertFalse(run.control.is_set())

    def test_ui_close_reopen_buttons_reflect_existing_batch(self):
        app, run = self.ui()
        app.upgrade_start_button = Mock()
        app.upgrade_stop_button = Mock()
        LineCheckAssistant._refresh_upgrade_buttons(app)
        app.upgrade_stop_button.configure.assert_called_with(state="normal")
        LineCheckAssistant._stop_sample_upgrade(app)
        app.upgrade_stop_button = Mock()
        LineCheckAssistant._refresh_upgrade_buttons(app)
        app.upgrade_stop_button.configure.assert_called_with(state="disabled")

    def test_ui_completion_waits_for_worker_resource_release(self):
        app, run = self.ui()
        run.control.request_stop()
        run.thread.is_alive.return_value = True
        with patch.object(LineCheckAssistant, "_report_sample_upgrade_completion") as report:
            LineCheckAssistant._complete_page_upgrade(app, [], run=run)
            self.assertTrue(app.sample_upgrade_running)
            report.assert_not_called()
            run.thread.is_alive.return_value = False
            app.after.call_args.args[1]()
            self.assertFalse(app.sample_upgrade_running)
            self.assertTrue(run.finished)
            self.assertEqual(report.call_args.args[1], "样机升级已停止")
        app.serial_terminal.finish_upgrade_logs.assert_called_once()

    def test_ui_normal_deferred_completion_still_signals_pipeline(self):
        app, run = self.ui()
        run.thread.is_alive.return_value = True
        results = [FullPackageUpgradeItemResult(self.request(), CommandResult(True, "ok"))]
        with patch.object(LineCheckAssistant, "_report_sample_upgrade_completion"), patch("line_check_assistant.app._finish_pipeline_subtask_if_waiting") as finish:
            LineCheckAssistant._complete_page_upgrade(app, results, run=run)
            run.thread.is_alive.return_value = False
            app.after.call_args.args[1]()
            self.assertTrue(finish.call_args.args[2])

    def test_ui_old_batch_completion_cannot_clear_new_batch(self):
        app, run = self.ui()
        old = UpgradeRun()
        self.assertTrue(LineCheckAssistant._finish_upgrade_run(app, old, []))
        self.assertTrue(app.sample_upgrade_running)
        app.upgrade_start_button.configure.assert_not_called()

    def test_ui_old_batch_progress_is_discarded(self):
        app, run = self.ui()
        old = UpgradeRun()
        callback = Mock()
        old.ui_queue.put(callback)
        LineCheckAssistant._drain_upgrade_ui(app, old)
        callback.assert_not_called()

    def test_ui_start_guard_and_restart_get_fresh_stop_token(self):
        app, run = self.ui()
        worker = Mock()
        with patch("line_check_assistant.app.threading.Thread") as thread:
            self.assertFalse(LineCheckAssistant._launch_upgrade_run(app, worker, ([],)))
            thread.assert_not_called()
            run.control.request_stop()
            with patch.object(LineCheckAssistant, "_report_sample_upgrade_completion"):
                LineCheckAssistant._finish_upgrade_run(app, run, [])
            self.assertTrue(LineCheckAssistant._launch_upgrade_run(app, worker, ([],)))
            self.assertIsNot(app._sample_upgrade_run, run)
            self.assertFalse(app._sample_upgrade_run.control.is_set())
            self.assertTrue(app.sample_upgrade_running)

    def test_ui_worker_exception_restores_controls_and_reports_error(self):
        app, run = self.ui()
        with patch.object(LineCheckAssistant, "_report_sample_upgrade_completion") as report:
            LineCheckAssistant._finish_upgrade_run(app, run, [], "simulated failure")
        self.assertFalse(app.sample_upgrade_running)
        self.assertTrue(run.finished)
        self.assertEqual(report.call_args.args[1], "样机升级失败")
        app.upgrade_start_button.configure.assert_called_with(state="normal")

    def test_pipeline_upgrade_stop_skips_following_tasks(self):
        ctx = SimpleNamespace(stop_event=threading.Event())
        orchestrator = PipelineOrchestrator(ctx, Mock())
        orchestrator._run_subtask = Mock(side_effect=UpgradeStopped("stopped at safe boundary"))
        results = orchestrator.run({"sample_upgrade", "sample_parameter_write"})
        orchestrator._run_subtask.assert_called_once_with("sample_upgrade")
        self.assertTrue(ctx.stop_event.is_set())
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)

    def test_pipeline_stop_forwards_to_upgrade(self):
        app, run = self.ui(UpgradeRun(pipeline_owned=True))
        app._stop_sample_upgrade = lambda **kwargs: LineCheckAssistant._stop_sample_upgrade(app, **kwargs)
        window = SimpleNamespace(app=app, _orchestrator=Mock(), _running_thread=Mock(), _update_main_power_test_status=Mock(), _emit_to_main_log=Mock())
        self.assertTrue(PipelineWindow.request_stop(window))
        self.assertTrue(run.control.is_set())
        window._orchestrator.request_stop.assert_called_once()

    def test_stop_summary_distinguishes_failure_and_skipped(self):
        results = [SimpleNamespace(result=result) for result in (CommandResult(True, "ok"), CommandResult(False, "bad"), stopped_result("a"), stopped_result("b", skipped=True))]
        self.assertEqual(summarize_results(results), "成功 1 台，失败 1 台，已停止 1 台，跳过 1 台")


if __name__ == "__main__":
    unittest.main()
