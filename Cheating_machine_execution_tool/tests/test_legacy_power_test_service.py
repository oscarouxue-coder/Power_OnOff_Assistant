from __future__ import annotations

import inspect
import os
import queue
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.services.legacy_power_test_service as service_module
from src.services.legacy_power_test_service import (
    LegacyPowerChannel,
    LegacyPowerTestRequest,
    prepare_legacy_power_test_request,
    run_legacy_power_test,
)


def _write_config_tree(root: Path, *, serial_port: str = "COM105") -> Path:
    config_dir = root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "config.ini").write_text(
        """[config]
test_project = test_project_config.ini

[ui_defaults]
communication_method = telnet
telnet_enable = 0
baud_rate = 19200
selected_profile = TEST_PROJECT
startup_time = 180
interval_time = 20
number_of_tests = 500
wait_command_done = 20

[Emails]
emails = ""
""",
        encoding="utf-8",
    )
    (config_dir / "network_card_ip.ini").write_text(
        f"""[power_supply]
serial_port = {serial_port}

[channel_5]
enabled = 1
network_card_ip = 192.168.1.105
""",
        encoding="utf-8",
    )
    (config_dir / "test_project_config.ini").write_text(
        """[telnet]
telnet_default_on = 1
password = secret

[connect_wifi]
enable = 1
product_solution = openwrt
""",
        encoding="utf-8",
    )
    return root


class _FakeEvent:
    def __init__(self) -> None:
        self._set = False

    def is_set(self) -> bool:
        return self._set

    def set(self) -> None:
        self._set = True


class _CompletedProcess:
    def __init__(self, *, args, **_kwargs) -> None:
        self.args = args
        self.exitcode = 0
        self._alive = True

    def start(self) -> None:
        message_queue = self.args[1]
        message_queue.put({"type": "log", "level": "warning", "message": "旧Logs内容"})
        message_queue.put(
            {
                "type": "log",
                "level": "info",
                "message": "selected_scheme_path: ./config/test_project_config.ini",
                "source": "logger",
            }
        )
        message_queue.put(
            {
                "type": "log",
                "level": "info",
                "message": "192.168.1.105登录成功",
                "source": "logger",
            }
        )
        message_queue.put(
            {
                "type": "log",
                "level": "info",
                "message": "2026-08-08 15:37:41.904434: 通道9下挂的设备在第1次测试时正常",
                "source": "result_file",
            }
        )
        for source in ("logger", "signal"):
            message_queue.put(
                {
                    "type": "log",
                    "level": "error",
                    "message": "通道 5 登录telnet失败",
                    "source": source,
                }
            )
        message_queue.put({"type": "result", "ok": True, "detail": "1 个通道全部完成"})
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout=None) -> None:
        return


class _FakeProcessContext:
    def Queue(self):
        return queue.Queue()

    def Event(self):
        return _FakeEvent()

    def Process(self, **kwargs):
        return _CompletedProcess(**kwargs)


class LegacyPowerTestServiceTests(unittest.TestCase):
    def test_power_frame_is_rendered_in_execution_log_format(self) -> None:
        self.assertEqual(
            service_module._format_power_frame(bytes((0x55, 0x00, 0xAD, 0x00, 0x00, 0xAD))),
            "55 00 AD 00 00 AD",
        )

    def test_prepare_request_loads_old_start_all_settings_without_gui(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = _write_config_tree(Path(temp_dir))

            request = prepare_legacy_power_test_request(
                root,
                (LegacyPowerChannel(5, "192.168.1.105"),),
            )

        self.assertEqual(request.communication_method, "telnet")
        self.assertEqual(request.serial_port, "COM105")
        self.assertEqual(request.profile_filename, "test_project_config.ini")
        self.assertEqual(request.number_of_tests, 500)
        self.assertTrue(request.connect_wifi_enable)
        self.assertEqual(request.channels[0].number, 5)

    def test_prepare_request_rejects_empty_power_com(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = _write_config_tree(Path(temp_dir), serial_port="")

            with self.assertRaisesRegex(ValueError, "程控电源 COM"):
                prepare_legacy_power_test_request(
                    root,
                    (LegacyPowerChannel(5, "192.168.1.105"),),
                )

    def test_log_filter_keeps_operator_signals_and_key_results(self) -> None:
        self.assertTrue(
            service_module._should_forward_legacy_log(
                "info",
                "*******通道 【9】 开始第2次测试*******",
                "signal",
            )
        )
        self.assertTrue(
            service_module._should_forward_legacy_log(
                "info",
                "192.168.1.109登录成功",
                "logger",
            )
        )
        self.assertFalse(
            service_module._should_forward_legacy_log(
                "info",
                "selected_scheme_path: ./config/test_project_config.ini",
                "logger",
            )
        )
        self.assertTrue(
            service_module._should_forward_legacy_log(
                "error",
                "任意底层异常",
                "logger",
            )
        )

    def test_parent_forwards_legacy_logs_and_waits_for_result(self) -> None:
        request = LegacyPowerTestRequest(
            tool_root=Path("legacy"),
            communication_method="telnet",
            serial_port="COM105",
            baud_rate="19200",
            selected_profile="TEST_PROJECT",
            profile_filename="test_project_config.ini",
            startup_time=180,
            interval_time=20,
            number_of_tests=1,
            wait_command_done=20,
            telnet_enable=False,
            emails="",
            connect_wifi_enable=False,
            product_solution="openwrt",
            channels=(LegacyPowerChannel(5, "192.168.1.105"),),
        )
        emitted = []

        result = run_legacy_power_test(
            request,
            emitted.append,
            _FakeEvent(),
            process_context=_FakeProcessContext(),
        )

        self.assertTrue(result.ok)
        self.assertIn("[旧工具Logs][WARNING] 旧Logs内容", emitted)
        self.assertIn("[旧工具Logs][INFO] 192.168.1.105登录成功", emitted)
        self.assertIn(
            "[旧工具Logs][INFO] 2026-08-08 15:37:41.904434: "
            "通道9下挂的设备在第1次测试时正常",
            emitted,
        )
        self.assertFalse(any("selected_scheme_path" in line for line in emitted))
        self.assertEqual(
            sum("[旧工具Logs][ERROR] 通道 5 登录telnet失败" in line for line in emitted),
            1,
        )
        self.assertTrue(any("已启用精简日志" in line for line in emitted))
        self.assertIn("成功：1 个通道全部完成", emitted[-1])

    def test_result_file_success_line_is_forwarded_without_changing_file(self) -> None:
        expected_line = "2026-08-08 15:37:41.904434: 通道9下挂的设备在第1次测试时正常"
        expected_bytes = (expected_line + "\n").encode("utf-8")
        message_queue = queue.Queue()

        with tempfile.TemporaryDirectory() as temp_dir:
            results_dir = Path(temp_dir) / "test_results" / "device_9"
            results_dir.mkdir(parents=True)
            result_path = results_dir / "device_9_command_results_20260808.log"
            restore = service_module._install_legacy_result_log_forwarder(message_queue)
            try:
                with open(result_path, "wb", buffering=0) as result_file:
                    midpoint = len(expected_bytes) // 2
                    result_file.write(expected_bytes[:midpoint])
                    result_file.write(expected_bytes[midpoint:])
            finally:
                restore()

            self.assertEqual(result_path.read_bytes(), expected_bytes)

        self.assertEqual(
            message_queue.get_nowait(),
            {
                "type": "log",
                "level": "info",
                "message": expected_line,
                "source": "result_file",
            },
        )
        with self.assertRaises(queue.Empty):
            message_queue.get_nowait()

    def test_result_file_forwarder_ignores_unrelated_binary_files(self) -> None:
        message_queue = queue.Queue()

        with tempfile.TemporaryDirectory() as temp_dir:
            unrelated_path = Path(temp_dir) / "unrelated.log"
            restore = service_module._install_legacy_result_log_forwarder(message_queue)
            try:
                unrelated_path.write_bytes(
                    "2026-08-08 15:37:41.904434: 通道9下挂的设备在第1次测试时正常\n".encode(
                        "utf-8"
                    )
                )
            finally:
                restore()

        with self.assertRaises(queue.Empty):
            message_queue.get_nowait()

    def test_service_does_not_import_or_construct_old_gui_entry(self) -> None:
        source = inspect.getsource(service_module)
        self.assertNotIn("import Auto_Power_On_Off_Tool", source)
        self.assertNotIn("UiCase(", source)
        self.assertNotIn("QMainWindow", source)


if __name__ == "__main__":
    unittest.main()
