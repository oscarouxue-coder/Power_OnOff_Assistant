"""预备测试使用模拟会话，不访问网卡或设备。"""
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from line_check_assistant.app import LineCheckAssistant
from line_check_assistant.config_store import ChannelConfig
from line_check_assistant.test_item_config_store import ExpectedSegment, OrderConfig, OrderItem, TelnetSettings
from src.services import test_item_pretest_service as service
from src.ui.test_item_pretest_controls import PretestControls


class ClockEvent:
    def __init__(self):
        self.now = 0
        self.stopped = False

    def wait(self, seconds):
        self.now += seconds
        return self.stopped

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True


class Session:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.history = ""
        self.sent = []
        self.error = None
        self._closed = False

    def cursor(self):
        return len(self.history)

    def peek_since(self, cursor):
        return self.history[cursor:]

    def send_line(self, text, sensitive=False):
        self.sent.append(text)
        self.history += self.responses.get(text, "OK\n#")

    def write(self, data, sensitive=False):
        pass

    def wait_for_any(self, markers, timeout, cursor):
        return markers[0]

    def close(self):
        self._closed = True


def channel(number=1):
    return ChannelConfig(f"channel_{number}", vlan_name=f"vlan{100 + number}",
                         adapter_alias=f"VLAN{number}", network_card_ip=f"192.168.1.{100 + number}",
                         device_manage_ip="192.168.1.1")


def request(items=None, channels=None):
    return service.prepare_pretest_request(
        channels or [channel()],
        OrderConfig(999, items or [OrderItem("first", [ExpectedSegment("OK")], 99)]),
        TelnetSettings(password="test-password", timeout=3),
    )


class PretestServiceTests(unittest.TestCase):
    def run_request(self, req, sessions=None, event=None, on_emit=None):
        sessions = sessions or [Session()]
        event = event or ClockEvent()
        logs = []

        def emit(text, tag):
            logs.append((text, tag))
            if on_emit:
                on_emit(text, tag)

        with patch.object(service, "TelnetSession", side_effect=sessions) as factory, \
             patch.object(service, "prepare_network_for_sample", return_value=SimpleNamespace(ok=True)) as network, \
             patch.object(service.time, "monotonic", side_effect=lambda: event.now):
            result = service.run_pretest(req, event, emit)
        return result, logs, factory, network

    def test_once_only_failure_continues_and_retry_settings_unchanged(self):
        req = request([OrderItem("first", [ExpectedSegment("missing")], 99),
                       OrderItem("second", [ExpectedSegment("OK")], 99)])
        session = Session()
        result, logs, _, _ = self.run_request(req, [session])
        self.assertEqual(session.sent, ["root", "test-password", "first", "second"])
        self.assertEqual((result.passed, result.failed, result.executed), (1, 1, 2))
        self.assertEqual(req.order.items[0].retry_times, 99)
        self.assertEqual(req.order.command_fail_retry_interval_time, 999)
        self.assertTrue(any("期望不匹配" in text and tag == "error" for text, tag in logs))
        self.assertTrue(any("期望匹配通过" in text and tag == "success" for text, tag in logs))
        self.assertTrue(any("回显 | OK" in text for text, _ in logs))
        self.assertTrue(session._closed)

    def test_no_expected_is_unchecked_not_passed(self):
        result, logs, _, _ = self.run_request(request([OrderItem("first")]))
        self.assertEqual((result.passed, result.unchecked), (0, 1))
        self.assertEqual(logs[-1][1], "warning")

    def test_negation_and_multiple_segments_are_preserved(self):
        result, _, _, _ = self.run_request(request([
            OrderItem("first", [ExpectedSegment("OK"), ExpectedSegment("ERROR", True)])
        ]))
        self.assertEqual(result.passed, 1)

    def test_channels_are_sequential_and_bound_to_snapshot(self):
        req = request(channels=[channel(2), channel(1)])
        result, _, factory, network = self.run_request(req, [Session(), Session()])
        self.assertEqual(result.passed, 2)
        self.assertEqual([c.kwargs["bind_ip"] for c in factory.call_args_list],
                         ["192.168.1.102", "192.168.1.101"])
        self.assertTrue(all(c.kwargs["reuse_if_ready"] for c in network.call_args_list))

    def test_all_targets_validated_before_any_network_operation(self):
        req = request(channels=[channel(), channel(2)])
        req.channels[1].network_card_ip = "invalid"
        with patch.object(service, "prepare_network_for_sample") as network:
            with self.assertRaises(ValueError):
                service.run_pretest(req, ClockEvent(), Mock())
        network.assert_not_called()

    def test_input_snapshot_does_not_change_when_page_changes(self):
        items = [OrderItem("first", [ExpectedSegment("OK")], 8)]
        channels = [channel()]
        req = request(items, channels)
        items[0].command = "changed"
        channels[0].device_manage_ip = "192.168.1.2"
        self.assertEqual(req.order.items[0].command, "first")
        self.assertEqual(req.channels[0].device_manage_ip, "192.168.1.1")

    def test_empty_targets_commands_and_invalid_port_rejected(self):
        for channels, order, telnet in [
            ([], OrderConfig(items=[OrderItem("a")]), TelnetSettings()),
            ([channel()], OrderConfig(), TelnetSettings()),
            ([channel()], OrderConfig(items=[OrderItem("", [ExpectedSegment("x")])]), TelnetSettings()),
            ([channel()], OrderConfig(items=[OrderItem("a")]), TelnetSettings(port=0)),
        ]:
            with self.subTest(channels=channels, order=order, telnet=telnet):
                with self.assertRaises(ValueError):
                    service.prepare_pretest_request(channels, order, telnet)

    def test_login_failure_closes_session_and_continues_next_device(self):
        first, second = Session(), Session()
        with patch.object(service, "_login", side_effect=[RuntimeError("登录失败"), None]):
            result, logs, _, _ = self.run_request(request(channels=[channel(), channel(2)]), [first, second])
        self.assertEqual(first.sent, [])
        self.assertEqual(second.sent, ["first"])
        self.assertEqual((result.device_errors, result.skipped), (1, 1))
        self.assertTrue(first._closed)
        self.assertEqual(logs[-1][1], "error")

    def test_stop_after_first_result_sends_no_later_command_or_device(self):
        event = ClockEvent()
        session = Session()
        result, _, factory, _ = self.run_request(
            request([OrderItem("first", [ExpectedSegment("OK")]), OrderItem("second")], [channel(), channel(2)]),
            [session], event,
            lambda text, tag: event.set() if "期望匹配通过" in text else None,
        )
        self.assertTrue(result.cancelled)
        self.assertEqual(result.skipped, 3)
        self.assertNotIn("second", session.sent)
        self.assertEqual(factory.call_count, 1)

    def test_stop_during_response_retains_output_and_closes(self):
        event = ClockEvent()
        result, logs, _, _ = self.run_request(request(), event=event,
            on_emit=lambda text, tag: event.set() if "下发命令" in text else None)
        self.assertEqual((result.executed, result.unchecked, result.passed), (1, 1, 0))
        self.assertTrue(result.cancelled)
        self.assertTrue(any("回显 | OK" in text for text, _ in logs))

    def test_disconnect_during_response_is_failure_and_stops_device(self):
        session = Session()
        result, logs, _, _ = self.run_request(request([OrderItem("first"), OrderItem("second")]), [session],
            on_emit=lambda text, tag: setattr(session, "_closed", True) if "下发命令" in text else None)
        self.assertEqual((result.failed, result.skipped, result.device_errors), (1, 1, 1))
        self.assertNotIn("second", session.sent)
        self.assertTrue(any("连接中断" in text for text, _ in logs))

    def test_silent_response_times_out_once_then_continues(self):
        session = Session({"first": ""})
        result, _, _, _ = self.run_request(request([OrderItem("first"), OrderItem("second")]), [session])
        self.assertEqual(session.sent.count("first"), 1)
        self.assertEqual((result.failed, result.unchecked), (1, 1))

    def test_cancel_during_login_prevents_command(self):
        event, session = ClockEvent(), Session()
        session.wait_for_any = lambda *args: (event.set() or "ogin:")
        result, _, _, _ = self.run_request(request(), [session], event)
        self.assertEqual(result.executed, 0)
        self.assertTrue(result.cancelled)
        self.assertTrue(session._closed)


class PretestUiTests(unittest.TestCase):
    def controls(self):
        with patch("src.ui.test_item_pretest_controls.ttk") as ttk:
            ttk.Button.side_effect = lambda *args, **kwargs: Mock()
            return PretestControls(Mock(), capture_request=Mock(return_value=request()), log=Mock())

    @patch("src.ui.test_item_pretest_controls.messagebox.askyesno", return_value=False)
    def test_declined_confirmation_never_starts_worker(self, confirm):
        controls = self.controls()
        with patch("src.ui.test_item_pretest_controls.threading.Thread") as thread:
            controls.start()
        thread.assert_not_called()
        self.assertFalse(controls.running)
        self.assertIn("192.168.1.101", confirm.call_args.args[1])

    @patch("src.ui.test_item_pretest_controls.messagebox.askyesno", return_value=True)
    def test_double_start_blocked_and_events_drained_before_finish(self, _confirm):
        controls = self.controls()
        with patch("src.ui.test_item_pretest_controls.threading.Thread") as thread:
            controls.start()
            controls.start()
        self.assertEqual(thread.call_count, 1)
        controls.events.put(("success result", "success"))
        controls.events.put(None)
        controls._poll()
        controls.log.assert_called_with("success result", "success")
        self.assertFalse(controls.running)
        controls.start_button.configure.assert_called_with(state="normal")

    @patch("src.ui.test_item_pretest_controls.messagebox.showinfo")
    def test_close_requests_stop_and_waits_for_log_drain(self, _info):
        controls = self.controls()
        controls.running = True
        self.assertFalse(controls.can_close())
        self.assertTrue(controls.cancel.is_set())
        controls.events.put(None)
        controls._poll()
        self.assertTrue(controls.can_close())

    def test_worker_failure_always_queues_completion(self):
        controls = self.controls()
        with patch("src.ui.test_item_pretest_controls.run_pretest", side_effect=RuntimeError("oops")):
            controls._worker(request())
        self.assertEqual(controls.events.get()[1], "error")
        self.assertIsNone(controls.events.get())

    def test_explicit_color_and_file_log_are_consistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = SimpleNamespace(log_path=Path(tmp) / "main.log", log_text=Mock(),
                                      _log_tag_for=Mock(return_value="error"))
            LineCheckAssistant._log(context, "匹配成功：期望文字含失败", tag="success")
            context.log_text.insert.assert_any_call("end", "匹配成功：期望文字含失败\n", "success")
            context._log_tag_for.assert_not_called()
            LineCheckAssistant._log(context, "失败：未匹配", tag="error")
            context.log_text.insert.assert_any_call("end", "失败：未匹配\n", "error")
            saved = context.log_path.read_text(encoding="utf-8")
            self.assertIn("匹配成功：期望文字含失败", saved)
            self.assertIn("失败：未匹配", saved)

    def test_main_capture_uses_checked_channels_and_current_page(self):
        context = SimpleNamespace(_capture_current_channel=Mock(), _selected_channels=Mock(return_value=[channel(2)]))
        order = OrderConfig(items=[OrderItem("unsaved")])
        captured = LineCheckAssistant._capture_pretest_request(context, order, TelnetSettings())
        self.assertEqual(captured.channels[0].section, "channel_2")
        self.assertEqual(captured.order.items[0].command, "unsaved")
        context._capture_current_channel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
