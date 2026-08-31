from __future__ import annotations

import inspect
import os
import queue
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
request_url = http://192.168.1.1
telnet_default_on = 1
password = secret

[connect_wifi]
enable = 1
product_solution = openwrt
test_2g_enable = 0
test_5g_enable = 1
auth_mode = WPA3-PSK
cipher = TKIP+AES
choose_wireless_card = 1
wireless_card_name = Wi-Fi 2
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
                "message": "192.168.1.106登录成功",
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
                "message": "192.168.1.106登录成功",
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
                "message": "The network card with IP 192.168.1.105 has been pinged",
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
        message_queue.put(
            {
                "type": "log",
                "level": "info",
                "message": "2026-08-08 15:37:42.904434: 通道5下挂的设备在第1次测试时正常",
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
        self.assertFalse(request.wifi_test_2g_enable)
        self.assertTrue(request.wifi_test_5g_enable)
        self.assertEqual(request.wifi_auth_mode, "WPA3-PSK")
        self.assertEqual(request.wifi_cipher, "TKIP+AES")
        self.assertTrue(request.wifi_choose_wireless_card)
        self.assertEqual(request.wifi_wireless_card_name, "Wi-Fi 2")
        self.assertEqual(request.channels[0].number, 5)
        self.assertEqual(request.ping_target_ip, "192.168.1.1")

    def test_prepare_request_rejects_empty_power_com(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = _write_config_tree(Path(temp_dir), serial_port="")

            with self.assertRaisesRegex(ValueError, "程控电源 COM"):
                prepare_legacy_power_test_request(
                    root,
                    (LegacyPowerChannel(5, "192.168.1.105"),),
                )

    def test_prepare_request_rejects_selected_wifi_card_without_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = _write_config_tree(Path(temp_dir))
            profile_path = root / "config" / "test_project_config.ini"
            profile_path.write_text(
                profile_path.read_text(encoding="utf-8").replace(
                    "wireless_card_name = Wi-Fi 2",
                    "wireless_card_name =",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "无线网卡名称为空"):
                prepare_legacy_power_test_request(
                    root,
                    (LegacyPowerChannel(5, "192.168.1.105"),),
                )

    def test_headless_onu_config_uses_all_wifi_profile_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            request = prepare_legacy_power_test_request(
                _write_config_tree(Path(temp_dir)),
                (LegacyPowerChannel(5, "192.168.1.105"),),
            )

        with patch.dict(sys.modules, {}, clear=False):
            onu_config = service_module._install_headless_legacy_stubs(request)
            self.assertEqual(onu_config.connect_wifi_enable_status, 1)
            self.assertEqual(onu_config.choose_test_2g_flag, 0)
            self.assertEqual(onu_config.choose_test_5g_flag, 1)
            self.assertEqual(onu_config.connect_wifi_auth_mode, "WPA3-PSK")
            self.assertEqual(onu_config.connect_wifi_ciper, "TKIP+AES")
            self.assertEqual(onu_config.Onu_solution_type, "openwrt")
            self.assertEqual(onu_config.choose_wireless_card_flag, 1)
            self.assertEqual(onu_config.choose_wireless_card_name, "Wi-Fi 2")

    def test_cycle_progress_uses_slowest_selected_channel(self) -> None:
        completed_by_channel = {5: 0, 6: 0}

        self.assertEqual(
            service_module._overall_completed_cycle(
                completed_by_channel,
                "2026-08-08 20:00:00: 通道5下挂的设备在第3次测试时正常",
                500,
            ),
            0,
        )
        self.assertEqual(
            service_module._overall_completed_cycle(
                completed_by_channel,
                "2026-08-08 20:00:01: 通道6下挂的设备在第2次测试时正常",
                500,
            ),
            2,
        )
        self.assertEqual(
            service_module._overall_completed_cycle(
                completed_by_channel,
                "2026-08-08 20:00:02: 通道5下挂的设备在第9次测试时正常",
                500,
            ),
            2,
        )
        self.assertEqual(
            service_module._overall_completed_cycle(
                completed_by_channel,
                "2026-08-08 20:00:03: 通道6下挂的设备在第9次测试时正常",
                500,
            ),
            9,
        )

    def test_cycle_progress_ignores_unselected_channel_and_clamps_total(self) -> None:
        completed_by_channel = {5: 0}

        self.assertIsNone(
            service_module._overall_completed_cycle(
                completed_by_channel,
                "2026-08-08 20:00:00: 通道9下挂的设备在第1次测试时正常",
                10,
            )
        )
        self.assertEqual(
            service_module._overall_completed_cycle(
                completed_by_channel,
                "2026-08-08 20:00:01: 通道5下挂的设备在第12次测试时正常",
                10,
            ),
            10,
        )

    def test_cycle_start_confirms_previous_cycle_for_power_only_mode(self) -> None:
        completed_by_channel = {9: 0}

        self.assertEqual(
            service_module._overall_completed_cycle(
                completed_by_channel,
                "*******通道 【9】 开始第1次测试*******",
                500,
            ),
            0,
        )
        self.assertEqual(
            service_module._overall_completed_cycle(
                completed_by_channel,
                "*******通道 【9】 开始第 4 次测试*******",
                500,
            ),
            3,
        )

    def test_log_filter_keeps_operator_signals_and_key_results(self) -> None:
        self.assertTrue(
            service_module._should_forward_legacy_log(
                "info",
                "*******通道 【9】 开始第2次测试*******",
                "signal",
            )
        )

    def test_channel_progress_parser_keeps_independent_round_and_stage(self) -> None:
        self.assertEqual(
            service_module._legacy_channel_progress_from_log(
                "*******通道 【7】 开始第 4 次测试*******",
                20,
            ),
            (7, 3, "第4轮执行中"),
        )
        self.assertEqual(
            service_module._legacy_channel_progress_from_log(
                "2026-08-08 15:37:41.904434: 通道7下挂的设备在第4次测试时正常",
                20,
            ),
            (7, 4, "第4轮完成"),
        )

    def test_command_retry_failure_and_retry_success_logs_report_channel_states(self) -> None:
        retry = service_module._legacy_channel_status_from_log(
            "通道 7 执行指令：/userfs/bin/ponmgr gpon get info，在第1次时出现错误；准备第2/3次验证"
        )
        retry_success = service_module._legacy_channel_status_from_log(
            "通道 7 发送指令 /userfs/bin/ponmgr gpon get info 重试了 1次之后，执行成功"
        )
        failure = service_module._legacy_channel_status_from_log(
            "通道 7 尝试执行指令：/userfs/bin/ponmgr gpon get info 3次进行验证，验证失败"
        )

        self.assertEqual(retry[0:2], (7, "retry"))
        self.assertIn("第1次", retry[2])
        self.assertEqual(retry_success[0:2], (7, "success"))
        self.assertIn("重试1次后验证成功", retry_success[2])
        self.assertEqual(failure[0:2], (7, "failed"))
        self.assertIn("3次验证失败", failure[2])
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
            wifi_test_2g_enable=True,
            wifi_test_5g_enable=True,
            wifi_auth_mode="WPA2-PSK",
            wifi_cipher="AES",
            wifi_choose_wireless_card=False,
            wifi_wireless_card_name="",
            channels=(LegacyPowerChannel(5, "192.168.1.105"),),
            ping_target_ip="192.168.1.1",
        )
        emitted = []
        progress = []
        channel_progress = []

        original_dedup_seconds = service_module.LEGACY_LOG_DEDUP_SECONDS
        service_module.LEGACY_LOG_DEDUP_SECONDS = 0.0
        try:
            result = run_legacy_power_test(
                request,
                emitted.append,
                _FakeEvent(),
                process_context=_FakeProcessContext(),
                on_progress=lambda completed, total: progress.append((completed, total)),
                on_channel_progress=lambda channel, completed, total, stage: channel_progress.append(
                    (channel, completed, total, stage)
                ),
            )
        finally:
            service_module.LEGACY_LOG_DEDUP_SECONDS = original_dedup_seconds

        self.assertTrue(result.ok)
        self.assertIn("[旧工具Logs][WARNING] 旧Logs内容", emitted)
        self.assertEqual(
            sum("[旧工具Logs][INFO] 192.168.1.105登录成功" == line for line in emitted),
            1,
        )
        self.assertEqual(
            sum("[旧工具Logs][INFO] 192.168.1.106登录成功" == line for line in emitted),
            1,
        )
        self.assertIn(
            "[旧工具Logs][INFO] Ping 成功：源网卡 192.168.1.105 → "
            "目标样机 192.168.1.1",
            emitted,
        )
        self.assertFalse(any("has been pinged" in line for line in emitted))
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
        self.assertIn(
            "[执行开关机测试] WiFi连接配置：主控=关闭，本次跳过 WiFi 连接测试。",
            emitted,
        )
        self.assertIn("成功：1 个通道全部完成", emitted[-1])
        self.assertEqual(progress, [(0, 1), (1, 1)])
        self.assertEqual(
            channel_progress,
            [(5, 0, 1, "等待第1轮"), (5, 1, 1, "第1轮完成")],
        )

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
