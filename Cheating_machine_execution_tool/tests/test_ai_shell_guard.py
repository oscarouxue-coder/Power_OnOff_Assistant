"""A2: boot/relogin/EOF regressions with data-only fake sessions."""
import threading
from dataclasses import replace
import unittest
from unittest.mock import Mock

from test_ai_debug import TARGET, Session, Clock, FastStop
from src.core.ai_debug_transport import DiagnosticTransport, DebugConnectionUnavailable, DebugSessionInvalid
from src.services.ai_debug_service import DiagnosticToolExecutor
from src.utils.ai_redaction import DiagnosticRedactor


class ShellGuardTests(unittest.TestCase):
    def connect(self, serial=False):
        self.session = Session()
        self.release = Mock()
        self.acquire = Mock(return_value=(self.session, self.release, threading.Event()))
        self.transport = DiagnosticTransport(TARGET, FastStop(), Mock(), self.acquire,
            telnet_factory=Mock(side_effect=OSError()) if serial else Mock(return_value=self.session), clock=Clock())
        self.transport.open()
        self.addCleanup(self.transport.close)
        return self.transport

    def test_boot_after_serial_login_prevents_first_command(self):
        transport = self.connect(serial=True)
        self.session.history += "U-Boot 2020.01\n=>"
        with self.assertRaises(DebugConnectionUnavailable):
            transport.command("cat /proc/uptime")
        self.assertEqual(self.session.writes, [])
        self.release.assert_called_once()
        self.assertFalse(self.session.closed)

    def test_relogin_and_closed_connection_prevent_command(self):
        for state in ("login", "closed", "error"):
            with self.subTest(state=state):
                transport = self.connect()
                if state == "login": self.session.history += "\nlogin:"
                elif state == "closed": self.session.closed = True
                else: self.session.error = OSError("simulated disconnect")
                with self.assertRaises(DebugConnectionUnavailable):
                    transport.command("uname -a")
                self.assertEqual(self.session.writes, [])

    def test_cleanup_does_not_bypass_boot_or_busy_guard(self):
        for state in ("boot", "busy"):
            with self.subTest(state=state):
                transport = self.connect()
                if state == "boot": self.session.history += "\n=>"
                else: transport.busy = lambda _: True
                with self.assertRaises((RuntimeError, DebugConnectionUnavailable)):
                    transport.command("dmesg -n 4", cleanup=True)
                self.assertEqual(self.session.writes, [])

    def test_unknown_prompt_never_sends_wakeup(self):
        transport = self.connect(serial=True)
        self.session.history += "\nstarting services..."
        with self.assertRaises(DebugConnectionUnavailable): transport.command("id")
        self.assertEqual(self.session.writes, [])

    def test_historical_boot_text_in_completed_output_is_not_reboot(self):
        transport = self.connect()
        def send(text, sensitive=False):
            self.session.writes.append((text, sensitive))
            self.session.history += text + "\n[0.0] Linux version 5.4\nU-Boot old history\nroot@OpenWrt:/#\n"
        self.session.send_line = send
        transport.command("dmesg")
        transport.command("uname -a")
        self.assertEqual(len(self.session.writes), 2)

    def test_post_dispatch_timeout_is_not_replayed(self):
        transport = self.connect()
        def send(text, sensitive=False):
            self.session.writes.append((text, sensitive))
            self.session.history += text + "\nwaiting"
        self.session.send_line = send
        with self.assertRaises(DebugConnectionUnavailable): transport.command("id", timeout=.4)
        with self.assertRaises(DebugConnectionUnavailable): transport.command("id")
        self.assertEqual(len(self.session.writes), 1)

    def test_normal_queries_and_cancelled_cleanup_keep_compatibility(self):
        transport = self.connect()
        transport.command("uname -a")
        transport.stop.set()
        transport.command("dmesg -n 4", cleanup=True)
        self.assertEqual(len(self.session.writes), 2)

    def test_invalid_session_does_not_trigger_fixed_read_serial_fallback(self):
        transport = self.connect()
        self.session.history += "\n=>"
        executor = DiagnosticToolExecutor(TARGET, transport.stop, Mock(), Mock(), DiagnosticRedactor(), self.acquire, Mock(), lambda _: False)
        executor.transport = transport
        result = executor.execute("read_dut_state", {"category": "network"})
        self.assertTrue(result["session_invalid"])
        self.assertFalse(result["dispatched"])
        self.acquire.assert_not_called()
        self.assertEqual(self.session.writes, [])

    def test_send_failure_marks_unknown_and_blocks_next_attempt(self):
        transport = self.connect()
        self.session.send_line = Mock(side_effect=OSError("simulated partial send"))
        with self.assertRaises(DebugSessionInvalid) as caught: transport.command("id")
        self.assertTrue(caught.exception.dispatched)
        with self.assertRaises(DebugSessionInvalid): transport.command("id")
        self.session.send_line.assert_called_once()

    def test_boot_during_response_invalidates_session(self):
        transport = self.connect(serial=True)
        def send(text, sensitive=False):
            self.session.writes.append((text, sensitive))
            self.session.history += "\nU-Boot 2020.01\n=>"
        self.session.send_line = send
        with self.assertRaises(DebugSessionInvalid) as caught: transport.command("id")
        self.assertTrue(caught.exception.dispatched)
        with self.assertRaises(DebugSessionInvalid): transport.command("id")
        self.assertEqual(len(self.session.writes), 1)

    def test_already_logged_in_no_auth_target_with_empty_login_markers(self):
        transport = self.connect()
        transport.target = replace(TARGET, user_prompt="", password_prompt="", no_auth=True)
        transport.command("id")
        self.assertEqual(len(self.session.writes), 1)

    def test_unannotated_transport_error_blocks_remaining_queries_this_round(self):
        executor = DiagnosticToolExecutor(TARGET, FastStop(), Mock(), Mock(), DiagnosticRedactor(), Mock(), Mock())
        transport = Mock(kind="Telnet")
        transport.command.side_effect = DebugConnectionUnavailable("unknown transport result")
        executor.transport = transport
        executor.transport_factory = Mock()
        first = executor.execute("read_dut_state", {"category": "network"})
        second = executor.execute("read_dut_state", {"category": "system"})
        self.assertTrue(first["dispatched"])
        self.assertFalse(second["dispatched"])
        transport.command.assert_called_once()
        transport.fallback_serial.assert_not_called()
        executor.transport_factory.assert_not_called()

    def test_login_preflight_veto_does_not_log_credentials_as_sent(self):
        transport = self.connect()
        transport.emit = Mock()
        with self.assertRaises(DebugSessionInvalid): transport._send_login("synthetic-password", "Password:", "密码")
        self.assertEqual(self.session.writes, [])
        self.assertFalse(any("TX 登录" in str(call) for call in transport.emit.call_args_list))


if __name__ == "__main__": unittest.main()
