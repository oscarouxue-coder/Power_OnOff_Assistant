"""正式测试初始化隔离验证；仅使用模拟串口和业务类，不连接设备。"""
import queue
import sys
import tempfile
import threading
import types
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_legacy_power_test_service import _write_config_tree
from src.services import legacy_power_test_service as legacy


class ImmediateEvent(threading.Event):
    def __init__(self):
        super().__init__()
        self.waits = []

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return self.is_set()


class SelectedPowerInitializationTests(unittest.TestCase):
    def run_worker(self, numbers, communication="telnet", *, initialize_power=True,
                   stop_after=None, fail_at=None, initially_stopped=False, wifi_cancel=False):
        event = ImmediateEvent()
        if initially_stopped:
            event.set()
        timeline, frames, workers = [], [], []
        messages = queue.Queue()

        class Serial:
            def __init__(self, *args, **kwargs):
                pass

            def is_open(self):
                return True

            def write(self, frame):
                frame = bytes(frame)
                timeline.append(("write", frame))
                if fail_at == len(frames) + 1:
                    raise OSError("simulated serial failure")
                frames.append(frame)
                if stop_after == len(frames):
                    event.set()

            def serial_close(self):
                timeline.append(("close",))

        class Worker:
            def __init__(self, serial, logger, *args, initialize_power=True):
                workers.append(self)
                self.initialize_power = initialize_power
                self.dingtalk = SimpleNamespace(log=None)
                self.power_control = SimpleNamespace(
                    switch_status_list=[0] * 16, power_off=Mock(),
                    stopthreadevent=0, consumer=lambda: timeline.append(("consumer",)),
                )
                if initialize_power:
                    serial.write(bytes.fromhex("55 00 AD 00 00 AD"))

            def run_case(self, ip, channel, *args, **kwargs):
                timeline.append(("run", channel))
                if wifi_cancel:
                    assert isinstance(self.wifi_scheduler, legacy.PowerTestWifiScheduler)
                    event.set()
                    return None
                return True

        modules = {}
        for name, attr, value in (
            ("common.serilal_client", "Serial", Serial),
            ("test_case.powe_on_off_telnet", "PowerOnOffTelnet", Worker),
            ("test_case.power_on_off_ssh", "PowerOnOffSsh", Worker),
        ):
            module = types.ModuleType(name)
            setattr(module, attr, value)
            modules[name] = module
        with tempfile.TemporaryDirectory() as temporary:
            request = replace(legacy.prepare_legacy_power_test_request(
                _write_config_tree(Path(temporary)),
                tuple(legacy.LegacyPowerChannel(n, f"192.168.1.{100 + n}") for n in numbers),
            ), communication_method=communication, connect_wifi_enable=False)
            with patch.dict(sys.modules, modules), patch.object(sys, "path", list(sys.path)), \
                    patch.object(legacy.os, "chdir"), \
                    patch.object(legacy, "_install_headless_legacy_stubs"), \
                    patch.object(legacy, "_connect_legacy_log_signals"), \
                    patch.object(legacy, "_install_legacy_result_log_forwarder", return_value=lambda: None):
                legacy._legacy_start_all_worker(request, messages, event, initialize_power=initialize_power)
        output = list(messages.queue)
        self.assertNotIn(bytes.fromhex("55 00 AD 00 00 AD"), frames)
        self.assertFalse(workers[0].initialize_power)
        workers[0].power_control.power_off.assert_not_called()
        self.assertEqual(workers[0].power_control.switch_status_list, [0] * 16)
        self.assertEqual(timeline[-1], ("close",))
        return frames, timeline, output, event

    def test_telnet_and_ssh_send_only_selected_frames_before_starting_threads(self):
        # 独立协议期望覆盖非连续通道、首尾通道及调用顺序。
        expected = {
            1: bytes.fromhex("55 01 A1 00 01 A1"),
            5: bytes.fromhex("55 01 A1 00 05 A5"),
            6: bytes.fromhex("55 01 A1 00 06 A6"),
            16: bytes.fromhex("55 01 A1 00 10 B0"),
        }
        for communication in ("telnet", "ssh"):
            for numbers in ((5,), (5, 6), (16, 1)):
                with self.subTest(communication=communication, numbers=numbers):
                    frames, timeline, messages, event = self.run_worker(numbers, communication)
                    self.assertEqual(frames, [expected[n] for n in numbers])
                    self.assertEqual(timeline[:len(numbers)], [("write", frame) for frame in frames])
                    self.assertCountEqual([item[1] for item in timeline if item[0] == "run"], numbers)
                    self.assertEqual(event.waits.count(0.5), len(numbers))
                    self.assertTrue(messages[-1]["ok"])
                    text = "\n".join(item.get("message", "") for item in messages)
                    self.assertIn(f"初始化仅断电已勾选通道：{list(numbers)}", text)
                    for frame in frames:
                        self.assertIn("下发程控电源指令：" + frame.hex(" ").upper(), text)
                    self.assertIn("未回读电源状态", text)
                    self.assertIn("全部下发完成", text)

    def test_wifi_cancel_has_separate_result_and_ready_messages(self):
        _, _, messages, _ = self.run_worker((5,), wifi_cancel=True)
        for kind in ('channel_result', 'channel_ready'):
            message = next(item for item in messages if item['type'] == kind)
            self.assertTrue(message['cancelled'])
            self.assertFalse(message['ok'])
        self.assertIn('用户已停止', messages[-1]['detail'])

    def test_duplicate_selected_channels_are_initialized_once_in_request_order(self):
        frames, _, _, event = self.run_worker((6, 5, 6))
        self.assertEqual(frames, [bytes.fromhex("55 01 A1 00 06 A6"),
                                  bytes.fromhex("55 01 A1 00 05 A5")])
        self.assertEqual(event.waits.count(0.5), 2)

    def test_stop_during_initialization_prevents_remaining_frames_and_all_threads(self):
        for count in (1, 2):
            with self.subTest(stop_after=count):
                frames, timeline, messages, _ = self.run_worker((5, 6), stop_after=count)
                self.assertEqual(len(frames), count)
                self.assertFalse(any(item[0] in ("run", "consumer") for item in timeline))
                self.assertFalse(messages[-1]["ok"])
                self.assertIn("已停止初始化断电", messages[-1]["detail"])

    def test_stop_before_initialization_sends_no_frames_and_starts_no_threads(self):
        frames, timeline, messages, _ = self.run_worker((5, 6), initially_stopped=True)
        self.assertEqual(frames, [])
        self.assertEqual(timeline, [("close",)])
        self.assertFalse(messages[-1]["ok"])

    def test_serial_failure_stops_initialization_and_reports_channel_without_repower(self):
        for fail_at in (1, 2):
            with self.subTest(fail_at=fail_at):
                frames, timeline, messages, _ = self.run_worker((5, 6, 16), fail_at=fail_at)
                self.assertEqual(len(frames), fail_at - 1)
                self.assertEqual(sum(item[0] == "write" for item in timeline), fail_at)
                self.assertFalse(any(item[0] in ("run", "consumer") for item in timeline))
                self.assertFalse(messages[-1]["ok"])
                self.assertIn(f"通道 {4 + fail_at} 断电指令下发失败", messages[-1]["detail"])
                self.assertIn("simulated serial failure", messages[-1]["detail"])

    def test_resume_skips_initialization_for_telnet_and_ssh(self):
        for communication in ("telnet", "ssh"):
            with self.subTest(communication=communication):
                frames, timeline, messages, event = self.run_worker(
                    (5,), communication, initialize_power=False,
                )
                self.assertEqual(frames, [])
                self.assertIn(("run", 5), timeline)
                self.assertNotIn(0.5, event.waits)
                self.assertTrue(messages[-1]["ok"])
                self.assertTrue(any("跳过初始化断电" in item.get("message", "") for item in messages))


if __name__ == "__main__":
    unittest.main()
