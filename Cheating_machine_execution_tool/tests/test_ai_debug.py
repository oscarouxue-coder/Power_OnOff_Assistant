from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.ai_debug_transport import DiagnosticTransport, DebugConnectionUnavailable
from src.core.serial_transport import PySerialSession, SerialSessionManager
from src.models.serial_models import SerialSettings
from src.models.ai_diagnostics import DiagnosticTarget
from src.services.ai_debug_service import DiagnosticToolExecutor, tool_schemas, READ_COMMANDS
from src.services.ai_store import DiagnosticStore
from src.utils.ai_redaction import DiagnosticRedactor
from src.ui.ai_serial_bridge import AiSerialBridge
from test_ai_core import FakeCipher


TARGET = DiagnosticTarget(1, "vlan101", "COM1", "192.168.1.101", "192.168.1.1", password="test-password")


class FastStop:
    def __init__(self):
        self.stopped = False

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, seconds):
        return self.stopped


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        self.now += 0.3
        return self.now


class Session:
    def __init__(self, history="root@OpenWrt:/#\n"):
        self.history = history
        self.writes = []
        self.error = None
        self.closed = False

    def cursor(self):
        return len(self.history)

    def peek_since(self, cursor):
        return self.history[cursor:]

    def send_line(self, text, sensitive=False):
        self.writes.append((text, sensitive))
        self.history += text + "\nquery output\nroot@OpenWrt:/#\n"

    def close(self):
        self.closed = True


class TransportTests(unittest.TestCase):
    def test_login_log_contains_actual_username_password_and_sent_commands(self):
        target = replace(TARGET, username="device-admin")
        session = Session("login:")
        def send(text, sensitive=False):
            session.writes.append((text, sensitive))
            session.history += text + "\n" + ("Password:" if len(session.writes) == 1 else "root@OpenWrt:/#\n")
        session.send_line = send
        output = []
        transport = DiagnosticTransport(target, FastStop(), output.append, Mock(),
            telnet_factory=Mock(return_value=session), clock=Clock())
        transport.open()
        self.assertEqual([text for text, _ in session.writes], [target.username, target.password])
        self.assertIn("[AI Debug] TX 登录用户名：" + target.username, output)
        self.assertIn("[AI Debug] TX 登录密码：" + target.password, output)
        transport.close()

    def test_telnet_preferred_locked_source_no_serial_open(self):
        session, serial = Session(), Mock()
        factory = Mock(return_value=session)
        transport = DiagnosticTransport(TARGET, FastStop(), Mock(), serial, telnet_factory=factory, clock=Clock())
        transport.open()
        self.assertEqual(transport.kind, "Telnet")
        self.assertEqual(factory.call_args.kwargs["bind_ip"], TARGET.bind_ip)
        serial.assert_not_called()
        self.assertEqual(session.writes, [])
        self.assertIn("query output", transport.command(READ_COMMANDS["system"]))
        transport.close()
        self.assertTrue(session.closed)

    def test_connection_failure_falls_back_to_existing_serial_without_closing_it(self):
        session, release = Session(), Mock()
        serial = Mock(return_value=(session, release, threading.Event()))
        transport = DiagnosticTransport(TARGET, FastStop(), Mock(), serial,
            telnet_factory=Mock(side_effect=OSError()), clock=Clock())
        transport.open()
        self.assertEqual(transport.kind, "串口")
        transport.close()
        release.assert_called_once()
        self.assertFalse(session.closed)

    def test_busy_dut_does_not_fallback_or_connect(self):
        serial, factory = Mock(), Mock()
        transport = DiagnosticTransport(TARGET, FastStop(), Mock(), serial, lambda _t: True, factory)
        with self.assertRaises(RuntimeError):
            transport.open()
        serial.assert_not_called()
        factory.assert_not_called()

    def test_boot_or_ambiguous_serial_prompt_never_gets_wakeup_or_commands(self):
        for text in ("U-Boot #", "=>", "Bootloader>", "#"):
            session, release = Session(text), Mock()
            transport = DiagnosticTransport(TARGET, FastStop(), Mock(), Mock(return_value=(session, release, threading.Event())),
                telnet_factory=Mock(side_effect=OSError()), clock=Clock())
            with self.subTest(text=text), self.assertRaises(DebugConnectionUnavailable):
                transport.open()
            self.assertEqual(session.writes, [])
            release.assert_called_once()

    def test_serial_window_cancel_stops_commands_but_keeps_monitor(self):
        cancel = threading.Event()
        session, release = Session(), Mock()
        transport = DiagnosticTransport(TARGET, FastStop(), Mock(), Mock(return_value=(session, release, cancel)),
            telnet_factory=Mock(side_effect=OSError()), clock=Clock())
        transport.open()
        cancel.set()
        with self.assertRaises(InterruptedError):
            transport.command("uname -a")
        transport.close()
        self.assertFalse(session.closed)

    def test_only_registered_reads_can_retry_on_serial_after_telnet_breaks(self):
        transport = Mock(kind="Telnet")
        transport.command.side_effect = [DebugConnectionUnavailable("lost"), "safe read"]
        executor = DiagnosticToolExecutor(TARGET, FastStop(), Mock(), Mock(), DiagnosticRedactor(), Mock(), Mock())
        executor.transport = transport
        result = executor.execute("read_dut_state", {"category": "system"})
        transport.fallback_serial.assert_called_once()
        self.assertIn("safe read", result["evidence"])


class ToolTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = DiagnosticStore(temp.name, FakeCipher())
        self.addCleanup(self.store.close)
        self.transport = Mock(kind="Telnet")
        self.executor = DiagnosticToolExecutor(TARGET, FastStop(), Mock(), self.store, DiagnosticRedactor(("model-auth-key",)), Mock(), Mock(return_value="passive"))
        self.executor.transport = self.transport

    def test_pc_snapshot_decodes_mixed_encodings_and_preserves_device_password(self):
        outputs = ["Windows IP 配置\r\n密码：test-password", "活动路由：在链路上", "系统上有 1 个接口：\r\n名称：VLAN101"]
        results = [Mock(stdout=text.encode(encoding), returncode=0)
                   for text, encoding in zip(outputs, ("gbk", "gbk", "utf-8"))]
        with patch("src.services.ai_debug_service.platform.platform", return_value="Windows"), \
             patch("ctypes.windll.kernel32.GetOEMCP", return_value=936), \
             patch("ctypes.windll.kernel32.GetACP", return_value=936), \
             patch("src.services.ai_debug_service.subprocess.run", side_effect=results) as run:
            snapshot = json.loads(self.executor.pc_environment())
        self.assertEqual(run.call_count, 3)
        self.assertIn("Windows IP 配置", snapshot["ipconfig /all"])
        self.assertEqual(snapshot["route print -4"], outputs[1])
        self.assertEqual(snapshot["netsh wlan show interfaces"], outputs[2])
        self.assertIn(TARGET.password, snapshot["ipconfig /all"])
        self.assertTrue(any("编码=utf-8" in c.args[0] for c in self.executor.emit.call_args_list))

    def test_pc_snapshot_truncates_characters_after_decode_and_logs_bad_bytes(self):
        # 第65536个字节位于中文字符中间，不能先按字节截断再解码。
        text = "a" * 65535 + "系统"
        results = [Mock(stdout=text.encode("utf-8"), returncode=0),
                   Mock(stdout=b"\x81", returncode=1), Mock(stdout=b"", returncode=0)]
        with patch("src.services.ai_debug_service.platform.platform", return_value="Windows"), \
             patch("ctypes.windll.kernel32.GetOEMCP", return_value=936), \
             patch("ctypes.windll.kernel32.GetACP", return_value=936), \
             patch("src.services.ai_debug_service.subprocess.run", side_effect=results):
            snapshot = json.loads(self.executor.pc_environment())
        self.assertEqual(snapshot["ipconfig /all"], "a" * 65535 + "系")
        messages = "\n".join(c.args[0] for c in self.executor.emit.call_args_list)
        self.assertIn("返回码=1", messages)
        self.assertIn("存在无法解码的字节", messages)

    def test_unknown_and_injected_commands_never_reach_transport(self):
        for name, arguments in (("reboot", {}), ("read_dut_state", {"category": "system;reboot"}),
            ("read_dut_state", {"category": "system", "command": "reboot"}),
            ("capture_packets", {"command": "reboot"}), ("read_serial_log", {"path": "C:/secret"})):
            with self.subTest(name=name):
                self.assertIn("error", self.executor.execute(name, arguments, True))
        self.transport.command.assert_not_called()

    def test_light_level_cannot_invoke_temporary_changes(self):
        for name in ("capture_packets", "follow_logs", "kernel_debug"):
            self.assertIn("error", self.executor.execute(name, {}, False))
        self.transport.command.assert_not_called()

    def test_passive_serial_log_does_not_connect_or_test_busy(self):
        result = self.executor.execute("read_serial_log", {})
        self.assertIn("passive", result["evidence"])
        self.transport.command.assert_not_called()

    def test_tool_call_budget_is_enforced(self):
        for _ in range(10):
            self.executor.execute("read_serial_log", {})
        self.assertIn("error", self.executor.execute("read_serial_log", {}))

    def test_debug_state_is_restored_on_cancellation(self):
        responses = iter(["4 4 1 7\nroot@OpenWrt:/#", "root@OpenWrt:/#", "root@OpenWrt:/#", "4 4 1 7\nroot@OpenWrt:/#"])
        self.transport.command.side_effect = lambda *args, **kwargs: next(responses)
        self.executor.stop.set()
        with self.assertRaises(InterruptedError):
            self.executor._temporary("kernel_debug")
        self.assertEqual(self.store.pending_recovery(), [])
        commands = [c.args[0] for c in self.transport.command.call_args_list]
        self.assertIn("dmesg -n 4", commands)
        self.assertNotIn("reboot", " ".join(commands))

    def test_disconnect_keeps_pending_recovery_without_reboot(self):
        self.transport.command.side_effect = ["4 4 1 7\n#", "#", OSError("disconnected")]
        self.executor.stop.set()
        with self.assertRaises(InterruptedError):
            self.executor._temporary("kernel_debug")
        self.assertEqual(len(self.store.pending_recovery()), 1)
        self.assertEqual(self.executor.recovery_state, "恢复待完成")

    def test_restore_only_task_unique_process_not_killall(self):
        self.transport.command.return_value = "__LCA_STOPPED\nroot@OpenWrt:/#"
        record = {"operation": "follow_logs", "path": "/tmp/lca_" + "a" * 32}
        self.executor._restore("r", record)
        command = self.transport.command.call_args.args[0]
        self.assertIn(record["path"], command)
        self.assertIn("/comm", command)
        self.assertIn("readlink /proc/$n/fd/1", command)
        self.assertNotIn("killall", command)
        self.assertEqual(self.store.pending_recovery(), [])

    def test_successful_packet_capture_is_local_only_and_remote_files_are_cleaned(self):
        import base64
        raw = bytes.fromhex("d4c3b2a1") + bytes(20)
        def output(command, **kwargs):
            if command == "command -v tcpdump":
                return "/usr/sbin/tcpdump\n#"
            if "__LCA_PID" in command:
                return "__LCA_PID:123\n#"
            if "__LCA_STOPPED" in command:
                return "__LCA_STOPPED\n#"
            if "__LCA_DATA_BEGIN" in command:
                return "__LCA_DATA_BEGIN\n" + base64.b64encode(raw).decode() + "\n__LCA_DATA_END\n#"
            if command.startswith("tcpdump -nn -r"):
                return "packet summary only\n#"
            return "#"
        self.transport.command.side_effect = output
        result = self.executor.execute("capture_packets", {}, True)
        files = list((self.store.directory / "captures").glob("*.pcap"))
        self.assertEqual(files[0].read_bytes(), raw)
        self.assertIn("packet summary only", result["evidence"])
        self.assertNotIn(base64.b64encode(raw).decode(), result["evidence"])
        self.assertEqual(self.store.pending_recovery(), [])
        commands = [c.args[0] for c in self.transport.command.call_args_list]
        self.assertTrue(any("-s 96 -c 256" in c for c in commands))
        self.assertTrue(any(c.startswith("rm -f /tmp/lca_") for c in commands))

    def test_process_that_does_not_stop_keeps_recovery_pending(self):
        self.transport.command.return_value = "__LCA_REMAINING\n__LCA_STOPPED\n#"
        record = {"operation": "follow_logs", "path": "/tmp/lca_" + "b" * 32}
        self.store.recovery("r", record)
        self.executor._restore("r", record)
        self.assertEqual(len(self.store.pending_recovery()), 1)
        self.assertEqual(self.executor.recovery_state, "恢复待完成")

    def test_malicious_recovery_record_does_not_execute(self):
        self.executor._restore("r", {"operation": "follow_logs", "path": "/tmp/x;reboot"})
        self.transport.command.assert_not_called()
        self.assertEqual(self.executor.recovery_state, "恢复待完成")

    def test_schemas_never_expose_command_or_target_parameter(self):
        for schema in tool_schemas(True):
            self.assertNotIn("command", schema["parameters"]["properties"])
            self.assertNotIn("host", schema["parameters"]["properties"])


class SerialSharingTests(unittest.TestCase):
    def setUp(self):
        self.manager = SerialSessionManager()
        self.session = PySerialSession(SerialSettings("COM1"))
        self.session._serial = Mock()
        self.manager._sessions["COM1"] = self.session
        self.manager._owners["COM1"].add("monitor")

    def test_existing_control_shares_connection_and_releases_only_ai_owner(self):
        session = self.manager.acquire_existing_control("ai-debug:test", SerialSettings("COM1"))
        self.assertIs(session, self.session)
        self.assertFalse(self.manager.manual_writable("COM1"))
        self.manager.release("ai-debug:test", "COM1")
        self.assertTrue(self.manager.manual_writable("COM1"))
        self.assertIs(self.manager.existing_session(SerialSettings("COM1")), session)
        self.assertFalse(session._closed)

    def test_existing_config_mismatch_or_upgrade_lock_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.manager.existing_session(SerialSettings("COM1", baudrate=9600))
        self.manager.acquire_control("upgrade", SerialSettings("COM1"))
        with self.assertRaises(RuntimeError):
            self.manager.acquire_existing_control("ai-debug:test", SerialSettings("COM1"))

    def test_multiple_subscribers_receive_identical_rx_even_with_control_owner(self):
        received, other = [], []
        self.session.subscribe(received.append)
        self.session.subscribe(other.append)
        self.manager.acquire_control("upgrade", SerialSettings("COM1"))
        self.session._emit("RX", b"x", "x")
        self.assertEqual(received[0], other[0])

    def test_passive_bridge_read_works_while_upgrade_has_control(self):
        self.session._history.extend(b"passive output")
        self.manager.acquire_control("upgrade", SerialSettings("COM1"))
        bridge = AiSerialBridge(Mock(), self.manager, Mock(return_value=True))
        self.assertIn("passive output", bridge.read(TARGET))


if __name__ == "__main__":
    unittest.main()
