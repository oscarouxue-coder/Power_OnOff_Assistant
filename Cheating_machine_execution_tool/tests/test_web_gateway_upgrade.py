import os
import socket
import tempfile
import threading
import unittest
from contextlib import ExitStack
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.request import ProxyHandler, Request, build_opener

from line_check_assistant.network_ops import CommandResult
from src.core.gateway_browser import GatewayBrowser, browser_command
from src.core.gateway_proxy import GatewayProxy
from src.models import FullPackageUpgradeRequest
from src.models.boot_entry import BOOT_ENTRY_LOGIN, BOOT_ENTRY_SDMC
from src.services.serial_upgrade_service import run_single_full_package_upgrade
from src.services.web_gateway_upgrade_service import (
    start_gateway_upgrade, validate_web_target, selected_interface_index,
    run_parallel_web_gateway_upgrades,
)


def request_for(**changes):
    request = FullPackageUpgradeRequest(
        "vlan112", "VLAN112", "", Path("firmware.bin"), "COM102", "root", "secret",
        transfer_method="web打开网关", power_channel=4, serial_port="COM12",
        web_device_ip="192.168.7.1", web_source_ip="192.168.7.112",
    )
    return replace(request, **changes)


class WebGatewayTests(unittest.TestCase):
    def test_proxy_distinguishes_idle_preconnect_and_gateway_connect_timeout(self):
        log = Mock()
        proxy = GatewayProxy("192.168.1.148", 71, "192.168.1.1", log)
        client = Mock()
        client.recv.side_effect = TimeoutError("idle")
        proxy._handle(client)
        log.assert_not_called()
        client.sendall.assert_not_called()
        client.recv.side_effect = None
        client.recv.return_value = b"GET http://192.168.1.1/ HTTP/1.1\r\nHost: 192.168.1.1\r\n\r\n"
        with patch.object(proxy, "_connect", side_effect=TimeoutError("timed out")):
            proxy._handle(client)
        self.assertIn("连接样机 192.168.1.1:80", log.call_args.args[0])
        self.assertIn("ifIndex 71", log.call_args.args[0])

    def test_cdp_timeout_names_the_failed_method(self):
        from src.core.gateway_cdp import DevToolsClient
        client = DevToolsClient.__new__(DevToolsClient)
        client.sequence = 0
        client.connection = Mock()
        client._send = Mock()
        client._receive = Mock(side_effect=socket.timeout("timed out"))
        with self.assertRaisesRegex(TimeoutError, "Page.navigate"):
            client.call("Page.navigate", timeout=30)

    def test_readiness_retries_only_get_before_opening_browser(self):
        proxy = GatewayProxy("192.168.1.148", 71, "192.168.1.1", Mock())
        now = [0.0]
        with patch.object(proxy, "_probe_upgrade_page", side_effect=[TimeoutError("link down"), RuntimeError("starting"), None]) as probe:
            proxy.wait_for_gateway(timeout=5, clock=lambda: now[0], sleep_fn=lambda seconds: now.__setitem__(0, now[0] + seconds))
            self.assertEqual(probe.call_count, 3)
            self.assertEqual(now[0], 2)

    def test_readiness_timeout_keeps_egress_diagnostics(self):
        proxy = GatewayProxy("192.168.1.148", 71, "192.168.1.1", Mock())
        now = [0.0]
        with patch.object(proxy, "_probe_upgrade_page", side_effect=TimeoutError("TCP connect timeout")):
            with self.assertRaisesRegex(TimeoutError, "192.168.1.148 / ifIndex 71"):
                proxy.wait_for_gateway(timeout=2, clock=lambda: now[0], sleep_fn=lambda seconds: now.__setitem__(0, now[0] + seconds))
        self.assertEqual(now[0], 2)

    def test_browser_does_not_start_until_gateway_is_ready(self):
        browser = GatewayBrowser("192.168.1.148", 71, "192.168.1.1", Mock())
        with patch("src.core.gateway_browser.find_gateway_browser", return_value="edge"), \
                patch.object(browser.proxy, "wait_for_gateway", side_effect=TimeoutError("not ready")), \
                patch("src.core.gateway_browser.subprocess.Popen") as launch:
            with self.assertRaisesRegex(TimeoutError, "not ready"):
                browser.start()
            launch.assert_not_called()

    def test_validate_target_uses_configured_subnet_not_fixed_tftp_network(self):
        validate_web_target("192.168.7.112", "192.168.7.1", "255.255.255.0")
        for source, target in (("", "192.168.1.1"), ("192.168.1.2", "192.168.7.1"),
                               ("192.168.1.1", "192.168.1.1"), ("192.168.1.2", "http://192.168.1.1")):
            with self.subTest(source=source, target=target), self.assertRaises(ValueError):
                validate_web_target(source, target, "255.255.255.0")

    @patch("src.services.web_gateway_upgrade_service.subprocess.run")
    def test_interface_query_uses_exact_alias_and_ip_without_shell_interpolation(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout="112", stderr="")
        self.assertEqual(selected_interface_index("VLAN112", "192.168.7.112"), 112)
        self.assertEqual(run.call_args.kwargs["env"]["LINE_CHECK_WEB_ALIAS"], "VLAN112")
        run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="wrong source")
        with self.assertRaisesRegex(RuntimeError, "wrong source"):
            selected_interface_index("VLAN112", "192.168.7.112")

    def test_proxy_binds_source_and_windows_interface_before_connect(self):
        with patch("src.core.gateway_proxy.socket.socket") as factory, patch("src.core.gateway_proxy.os.name", "nt"):
            sock = factory.return_value
            events = []
            sock.bind.side_effect = lambda arg: events.append(("bind", arg))
            sock.setsockopt.side_effect = lambda *args: events.append(("interface", args[-1]))
            sock.connect.side_effect = lambda arg: events.append(("connect", arg))
            GatewayProxy("192.168.7.112", 112, "192.168.7.1", Mock())._connect()
            self.assertEqual(events, [("bind", ("192.168.7.112", 0)),
                                      ("interface", socket.htonl(112)), ("connect", ("192.168.7.1", 80))])
            sock.setsockopt.side_effect = OSError("interface failure")
            sock.connect.reset_mock()
            with self.assertRaises(OSError):
                GatewayProxy("192.168.7.112", 112, "192.168.7.1", Mock())._connect()
            sock.connect.assert_not_called()

    def test_proxy_rejects_other_target_without_upstream_connection(self):
        proxy = GatewayProxy("127.0.0.1", 0, "127.0.0.1", Mock())
        port = proxy.start()
        try:
            with patch.object(proxy, "_connect") as connect, socket.create_connection(("127.0.0.1", port)) as client:
                client.sendall(b"GET http://192.168.1.1/ HTTP/1.1\r\nHost: 192.168.1.1\r\n\r\n")
                self.assertIn(b"403 Forbidden", client.recv(4096))
                connect.assert_not_called()
        finally:
            proxy.close()

    def test_browser_command_isolated_profile_and_no_proxy_bypass(self):
        args = browser_command("edge", "temporary-profile", 12345)
        self.assertIn("--user-data-dir=temporary-profile", args)
        self.assertIn("--proxy-server=http://127.0.0.1:12345", args)
        self.assertIn("--proxy-bypass-list=<-loopback>", args)
        self.assertIn("--disable-quic", args)
        self.assertNotIn("--headless=new", args)

    def test_start_submits_once_then_waits_exactly_30_seconds(self):
        prefix = "src.services.web_gateway_upgrade_service."
        with ExitStack() as stack:
            prepare = stack.enter_context(patch(prefix + "prepare_network_for_sample", return_value=CommandResult(True, "ready")))
            stack.enter_context(patch(prefix + "wait_for_bindable_ip", return_value=True))
            stack.enter_context(patch(prefix + "selected_interface_index", return_value=112))
            browser = stack.enter_context(patch(prefix + "GatewayBrowser")).return_value
            events = []
            browser.start.side_effect = lambda: events.append("open")
            browser.submit_firmware.side_effect = lambda path: events.append("click")
            result = start_gateway_upgrade(request_for(), Mock(), lambda seconds: events.append(seconds))
            self.assertIs(result, browser)
            self.assertEqual(events, ["open", "click", 30])
            self.assertEqual(prepare.call_args.args[:3], ("VLAN112", "192.168.7.112", "255.255.255.0"))
            browser.close.assert_not_called()  # Kept alive through serial postprocessing.
            browser.submit_firmware.side_effect = RuntimeError("missing button")
            sleep = Mock()
            with self.assertRaisesRegex(RuntimeError, "missing button"):
                start_gateway_upgrade(request_for(), Mock(), sleep)
            sleep.assert_not_called()
            browser.close.assert_called_once()

    def test_web_both_boot_methods_and_all_postprocessing_branches(self):
        prefix = "src.services.serial_upgrade_service."
        for boot in (BOOT_ENTRY_LOGIN, BOOT_ENTRY_SDMC):
            for reset in (True, False):
                for restore in (True, False):
                    with self.subTest(boot=boot, reset=reset, restore=restore), ExitStack() as stack:
                        folder = stack.enter_context(tempfile.TemporaryDirectory())
                        stack.enter_context(patch(prefix + "DEFAULT_LOG_DIR", Path(folder)))
                        controller = stack.enter_context(patch(prefix + "SerialUpgradeController")).return_value
                        controller.wait_for_tftp_put_boot_username.return_value = CommandResult(True, "username")
                        controller.login_tftp_put_boot_after_username.return_value = CommandResult(True, "boot")
                        controller.login_final_system.return_value = CommandResult(True, "shell")
                        controller.monitor_post_tftp.return_value = reset
                        sdmc = stack.enter_context(patch(prefix + "enter_sdmc_boot", return_value=CommandResult(True, "boot")))
                        power = stack.enter_context(patch(prefix + "_power_cycle_current_channel", return_value=CommandResult(True, "power")))
                        web = stack.enter_context(patch(prefix + "start_gateway_upgrade"))
                        browser = web.return_value
                        events = []
                        web.side_effect = lambda *args: events.append("web-wait-30-complete") or browser
                        controller.monitor_post_tftp.side_effect = lambda: events.append("observe-90") or reset
                        tftp = stack.enter_context(patch(prefix + "upload_firmware"))
                        tftp_network = stack.enter_context(patch(prefix + "prepare_tftp_network"))
                        manager = Mock()
                        result = run_single_full_package_upgrade(
                            request_for(boot_entry_method=boot, restore_factory=restore), manager,
                            sleep_fn=lambda seconds: events.append(seconds),
                        )
                        self.assertTrue(result.ok, result.message)
                        self.assertEqual(events[:2], ["web-wait-30-complete", "observe-90"])
                        self.assertEqual(events[-1], 120 if restore else 3)
                        self.assertEqual(power.call_count, 1 if reset else 2)
                        self.assertEqual(power.call_args_list[0].kwargs["on_delay_seconds"], 1)
                        if not reset:
                            self.assertNotIn("on_delay_seconds", power.call_args.kwargs)
                        self.assertEqual(sdmc.call_count, int(boot == BOOT_ENTRY_SDMC))
                        self.assertEqual(controller.login_tftp_put_boot_after_username.call_count, int(boot == BOOT_ENTRY_LOGIN))
                        self.assertEqual(controller.login_final_system.call_count, int(restore))
                        tftp.assert_not_called()
                        tftp_network.assert_not_called()
                        browser.close.assert_called_once()
                        manager.release.assert_called_once()

    def test_web_submit_failure_never_reboots_or_resets_factory(self):
        prefix = "src.services.serial_upgrade_service."
        with ExitStack() as stack:
            folder = stack.enter_context(tempfile.TemporaryDirectory())
            stack.enter_context(patch(prefix + "DEFAULT_LOG_DIR", Path(folder)))
            controller = stack.enter_context(patch(prefix + "SerialUpgradeController")).return_value
            stack.enter_context(patch(prefix + "enter_sdmc_boot", return_value=CommandResult(True, "boot")))
            power = stack.enter_context(patch(prefix + "_power_cycle_current_channel", return_value=CommandResult(True, "power")))
            stack.enter_context(patch(prefix + "start_gateway_upgrade", side_effect=RuntimeError("submit failure")))
            manager = Mock()
            result = run_single_full_package_upgrade(request_for(boot_entry_method=BOOT_ENTRY_SDMC), manager)
            self.assertFalse(result.ok)
            power.assert_called_once()
            controller.monitor_post_tftp.assert_not_called()
            controller.restore_factory_if_enabled.assert_not_called()
            manager.release.assert_called_once()

    def test_parallel_web_keeps_order_and_other_channel_after_failure(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            path = Path(folder, "fw.bin")
            path.write_bytes(b"test")
            one = request_for(firmware_path=path)
            two = replace(one, vlan="vlan113", server_interface="VLAN113", serial_port="COM13", web_source_ip="192.168.7.113")
            stack.enter_context(patch("src.services.web_gateway_upgrade_service.find_gateway_browser", return_value="edge"))
            worker = stack.enter_context(patch("src.services.serial_upgrade_service.run_single_full_package_upgrade"))
            worker.side_effect = lambda req, *args, **kwargs: CommandResult(req.vlan == "vlan113", req.vlan)
            results = run_parallel_web_gateway_upgrades([one, two], Mock(), max_workers=2)
            self.assertEqual([item.request for item in results], [one, two])
            self.assertEqual([item.result.ok for item in results], [False, True])

    def test_invalid_batch_blocks_all_power_and_browser_work(self):
        with patch("src.services.serial_upgrade_service.run_single_full_package_upgrade") as run:
            with self.assertRaises(ValueError):
                run_parallel_web_gateway_upgrades([request_for(web_device_ip="bad")], Mock())
            run.assert_not_called()

    def test_main_ui_snapshots_web_target_file_boot_and_uses_web_worker(self):
        from line_check_assistant.app import LineCheckAssistant
        from line_check_assistant.config_store import ChannelConfig
        channel = ChannelConfig(section="channel_1", enabled=True, vlan_name="VLAN112",
                                serial_port="COM12", network_card_ip="192.168.7.112")
        context = SimpleNamespace(
            upgrade_firmware_var=Mock(get=Mock(return_value="firmware.bin")),
            upgrade_username_var=Mock(get=Mock(return_value="root")),
            upgrade_password_var=Mock(get=Mock(return_value="secret")),
            upgrade_restore_factory_var=Mock(get=Mock(return_value=False)),
            upgrade_transfer_var=Mock(get=Mock(return_value="web打开网关")),
            upgrade_boot_entry_var=Mock(get=Mock(return_value=BOOT_ENTRY_SDMC)),
            upgrade_parallel_count_var=Mock(get=Mock(return_value=2)),
            device_ip_var=Mock(get=Mock(return_value="192.168.7.1")),
            upgrade_window=Mock(), _selected_tftp_copy_upgrade_channels=Mock(return_value=[channel]),
            _full_package_tftp_server_ip_for_channel=Mock(side_effect=AssertionError("must not use TFTP IP")),
            _selected_power_serial_port=Mock(return_value="COM102"),
            _parallel_web_gateway_upgrade_worker=Mock(), _set_upgrade_status=Mock(), _log=Mock(),
        )
        with patch("line_check_assistant.app.Path.is_file", return_value=True), \
                patch("line_check_assistant.app.messagebox.askyesno", return_value=True) as confirm, \
                patch("line_check_assistant.app.threading.Thread") as thread:
            self.assertTrue(LineCheckAssistant._start_full_package_upgrade(context))
            request = thread.call_args.kwargs["args"][0][0][1]
            self.assertIs(thread.call_args.kwargs["target"], context._parallel_web_gateway_upgrade_worker)
            self.assertEqual(request.web_device_ip, "192.168.7.1")
            self.assertEqual(request.web_source_ip, "192.168.7.112")
            self.assertEqual(request.serial_port, "COM12")
            self.assertEqual(request.boot_entry_method, BOOT_ENTRY_SDMC)
            text = confirm.call_args.args[1]
            self.assertIn("192.168.7.1", text)
            self.assertIn("firmware.bin", text)
            self.assertIn("30秒", text)
            self.assertNotIn("固定为 192.168.1.1", text)
            context.device_ip_var.get.return_value = "10.0.0.1"
            self.assertEqual(request.web_device_ip, "192.168.7.1")

    def test_unattended_confirmation_shows_web_destination_and_wait(self):
        from line_check_assistant.pipeline_window import PipelineWindow
        from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings
        context = SimpleNamespace(
            sample_upgrade_settings=SampleUpgradeSettings(transfer_method="web打开网关"),
            app=SimpleNamespace(device_ip_var=Mock(get=Mock(return_value="192.168.7.1"))),
        )
        note = PipelineWindow._unattended_confirmation_note(context, {"sample_upgrade"}, True)
        self.assertIn("http://192.168.7.1/", note)
        self.assertIn("固定等待30秒", note)

    def test_duplicate_source_or_vlan_rejects_whole_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "fw.bin")
            path.write_bytes(b"test")
            one = request_for(firmware_path=path)
            with patch("src.services.serial_upgrade_service.run_single_full_package_upgrade") as run:
                with self.assertRaisesRegex(ValueError, "重复"):
                    run_parallel_web_gateway_upgrades([one, one], Mock())
                run.assert_not_called()


@unittest.skipUnless(os.environ.get("LINECHECK_WEB_BROWSER_TEST") == "1", "显式启用本机无头浏览器模拟网页验收")
class LocalBrowserIntegrationTests(unittest.TestCase):
    def test_headerless_boot_page_opens_in_real_browser_readonly(self):
        import socketserver
        requests = []

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                request = self.request.recv(4096)
                requests.append(request)
                self.request.sendall(b'<!DOCTYPE HTML><html><head><title>Software update</title></head>'
                                     b'<body><form method="post"><input type="file" name="firmware">'
                                     b'<input type="submit" value="Update software"></form></body></html>')

        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        browser = GatewayBrowser("127.0.0.1", 0, "127.0.0.1", Mock(),
                                 target_port=server.server_address[1], headless=True)
        try:
            browser.start()
            self.assertEqual(browser.cdp.evaluate("document.title"), "Software update")
            self.assertEqual(browser.cdp.evaluate('document.querySelectorAll("input[type=file]").length'), 1)
            self.assertTrue(all(request.startswith(b"GET ") for request in requests))
        finally:
            browser.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_real_browser_selects_file_and_submits_once_without_page_change(self):
        received, source_addresses = [], []
        submitted = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                source_addresses.append(self.client_address[0])
                data = (b'<h1>Software update</h1><form action="/update" method="post" enctype="multipart/form-data">'
                        b'<input type="file" name="firmware"><input type="submit" value="Update software"></form>')
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                received.append(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(204)  # Browser page intentionally remains unchanged.
                self.end_headers()
                submitted.set()

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        browser = GatewayBrowser("127.0.0.1", 0, "127.0.0.1", print,
                                 target_port=server.server_port, headless=True)
        try:
            with tempfile.TemporaryDirectory() as folder, ExitStack() as cleanup:
                cleanup.callback(browser.close)
                firmware = Path(folder, "firmware test.bin")
                data = b"firmware-test-" * 100000
                firmware.write_bytes(data)
                browser.start()
                browser.submit_firmware(firmware)
                self.assertTrue(submitted.wait(10), "POST未到达本机模拟网页")
                self.assertEqual(len(received), 1)
                self.assertIn(data, received[0])
                self.assertIn(b'filename="firmware test.bin"', received[0])
                self.assertEqual(set(source_addresses), {"127.0.0.1"})
                with self.assertRaisesRegex(RuntimeError, "禁止重复提交"):
                    browser.submit_firmware(firmware)
        finally:
            browser.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
