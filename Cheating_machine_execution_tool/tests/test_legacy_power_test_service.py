from __future__ import annotations

import inspect
import os
import queue
import sys
import tempfile
import unittest
from dataclasses import replace
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


class _HistoryCompletedProcess:
    def __init__(self, *, args, **_kwargs) -> None:
        self.args = args
        self.exitcode = 0
        self._alive = True

    def start(self) -> None:
        message_queue = self.args[1]
        message_queue.put({"type": "log", "level": "info", "message": "*******\u901a\u9053 \u30105\u3011 \u5f00\u59cb\u7b2c 2 \u6b21\u6d4b\u8bd5*******", "source": "signal"})
        message_queue.put({"type": "log", "level": "warning", "message": "\u901a\u9053 5 \u6267\u884c\u6307\u4ee4\uff1a/userfs/bin/ponmgr gpon get info\uff0c\u5728\u7b2c 1 \u6b21\u65f6\u51fa\u73b0\u9519\u8bef\uff1b\u51c6\u5907\u7b2c 2/3 \u6b21\u9a8c\u8bc1", "source": "signal"})
        message_queue.put({"type": "log", "level": "info", "message": "\u901a\u9053 5 \u53d1\u9001\u6307\u4ee4 /userfs/bin/ponmgr gpon get info \u91cd\u8bd5\u4e86 1\u6b21\u4e4b\u540e\uff0c\u6267\u884c\u6210\u529f", "source": "signal"})
        message_queue.put({"type": "log", "level": "error", "message": "\u901a\u9053 5 \u5c1d\u8bd5\u6267\u884c\u6307\u4ee4\uff1a/userfs/bin/ponmgr gpon get info 3\u6b21\u8fdb\u884c\u9a8c\u8bc1\uff0c\u9a8c\u8bc1\u5931\u8d25", "source": "signal"})
        message_queue.put({"type": "result", "ok": False, "detail": "\u901a\u9053 5 \u9a8c\u8bc1\u5931\u8d25"})
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout=None) -> None:
        return


class _HistoryProcessContext(_FakeProcessContext):
    def Process(self, **kwargs):
        return _HistoryCompletedProcess(**kwargs)


class LegacyPowerTestServiceTests(unittest.TestCase):
    def _run_status_messages(self, messages):
        class StatusProcess(_HistoryCompletedProcess):
            def start(self):
                for message in messages:
                    self.args[1].put(message)
                self.args[1].put(dict(type="result", ok=False, detail="保留业务最终失败结论"))
                self._alive = False

        class StatusContext(_FakeProcessContext):
            def Process(self, **kwargs):
                return StatusProcess(**kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            request = replace(prepare_legacy_power_test_request(
                _write_config_tree(Path(temp_dir)),
                (LegacyPowerChannel(2, "192.168.1.102"), LegacyPowerChannel(7, "192.168.1.107")),
            ), number_of_tests=5)
        statuses, history, progress, emitted = [], [], [], []
        result = run_legacy_power_test(
            request, emitted.append, _FakeEvent(), process_context=StatusContext(),
            on_channel_status=lambda *event: statuses.append(event),
            on_channel_history=lambda *event: history.append(event),
            on_channel_progress=lambda *event: progress.append(event),
        )
        return result, statuses, history, progress, emitted

    def test_normal_cycle_and_start_logs_report_explicit_channel_states(self):
        self.assertEqual(service_module._legacy_channel_status_from_log(
            "2026-10-12 21:22:30.204141: 通道2下挂的设备在第3次测试时正常"
        ), (2, "success", "第3轮测试正常"))
        self.assertEqual(service_module._legacy_channel_status_from_log(
            "*******通道 【2】 开始第 4 次测试*******"
        ), (2, "running", "第4轮执行中"))
        for text in (
            "通道2下挂的设备在第3次测试时正常",
            "2026-10-12 21:22:30: 通道2下挂的设备在第3次测试时失败",
            "2026-10-12 21:22:30: 通道2下挂的设备在第3次测试时正常，尚未确认",
            "192.168.1.102登录成功",
        ):
            with self.subTest(text=text):
                self.assertIsNone(service_module._legacy_channel_status_from_log(text))

    def test_normal_cycle_restores_only_selected_channel_and_keeps_failure_history(self):
        normal = "2026-10-12 21:22:30.204141: 通道2下挂的设备在第3次测试时正常"
        result, statuses, history, progress, emitted = self._run_status_messages([
            dict(type="log", message="*******通道 【2】 开始第3次测试*******"),
            dict(type="log", message="通道 2 尝试执行指令：echo check 3次进行验证，验证失败"),
            dict(type="log", message="通道 7 尝试执行指令：echo other 3次进行验证，验证失败"),
            dict(type="log", message=normal, source="result_file"),
            dict(type="log", message=normal.replace("通道2", "通道9"), source="result_file"),
        ])
        self.assertFalse(result.ok)
        self.assertEqual(statuses, [
            (2, "running", "第3轮执行中"),
            (2, "failed", "执行指令：echo check 3次验证失败"),
            (7, "failed", "执行指令：echo other 3次验证失败"),
            (2, "success", "第3轮测试正常"),
        ])
        self.assertEqual(history, [
            (2, 3, "failed", "执行指令：echo check 3次验证失败"),
            (7, 1, "failed", "执行指令：echo other 3次验证失败"),
        ])
        self.assertEqual(progress[-1], (2, 3, 5, "第3轮完成"))
        self.assertIn(f"[旧工具Logs][INFO] {normal}", emitted)

    def test_duplicate_or_previous_cycle_normal_logs_do_not_clear_new_failure(self):
        normal = "2026-10-12 21:22:30.204141: 通道2下挂的设备在第3次测试时正常"
        _, statuses, history, progress, _ = self._run_status_messages([
            dict(type="log", message=normal, source="result_file"),
            dict(type="log", message="*******通道 【2】 开始第4次测试*******"),
            dict(type="log", message="通道 2 尝试执行指令：echo check 3次进行验证，验证失败"),
            dict(type="log", message=normal, source="result_file"),
            dict(type="log", message=normal.replace("第3次", "第2次"), source="result_file"),
            dict(type="log", message=normal.replace("第3次", "第6次"), source="result_file"),
        ])
        self.assertEqual(statuses, [
            (2, "success", "第3轮测试正常"),
            (2, "running", "第4轮执行中"),
            (2, "failed", "执行指令：echo check 3次验证失败"),
        ])
        self.assertEqual(history, [(2, 4, "failed", "执行指令：echo check 3次验证失败")])

    def test_final_channel_failure_overrides_normal_and_rejects_late_success(self):
        normal = "2026-10-12 21:22:30: 通道2下挂的设备在第3次测试时正常"
        result, statuses, _, _, _ = self._run_status_messages([
            dict(type="log", message=normal, source="result_file"),
            dict(type="channel_result", channel=2, ok=False),
            dict(type="log", message=normal.replace("第3次", "第4次"), source="result_file"),
        ])
        self.assertFalse(result.ok)
        self.assertEqual(statuses, [
            (2, "success", "第3轮测试正常"),
            (2, "failed", "测试失败，详细信息请查看执行日志"),
        ])

    def test_duplicate_or_old_cycle_start_does_not_clear_current_retry(self):
        start = "*******通道 【2】 开始第4次测试*******"
        _, statuses, _, _, _ = self._run_status_messages([
            dict(type="log", message=start),
            dict(type="log", message="通道 2 执行指令：echo check，在第1次时出现错误；准备第2/3次验证"),
            dict(type="log", message=start),
            dict(type="log", message=start.replace("第4次", "第3次")),
        ])
        self.assertEqual(statuses, [
            (2, "running", "第4轮执行中"),
            (2, "retry", "执行指令：echo check，在第1次时出现错误；准备第2/3次验证"),
        ])

    def test_whitespace_normal_log_uses_same_progress_and_stale_guard(self):
        normal = "2026-10-12  21:22:30.204141:   通道2下挂的设备在第3次测试时正常"
        _, statuses, _, progress, _ = self._run_status_messages([
            dict(type="log", message=normal, source="result_file"),
            dict(type="log", message="通道 2 尝试执行指令：echo check 3次进行验证，验证失败"),
            dict(type="log", message=normal, source="result_file"),
        ])
        self.assertEqual(statuses, [
            (2, "success", "第3轮测试正常"),
            (2, "failed", "执行指令：echo check 3次验证失败"),
        ])
        self.assertEqual(progress[-1], (2, 3, 5, "第3轮完成"))

    def test_history_extracts_telnet_connection_retry(self) -> None:
        for text in (
            "通道 2 第 1 次连接telnet 失败，等待10s再连接一次；",
            "通道2 第1次连接 TELNET 失败，等待 10 s 再连接一次",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    service_module._legacy_channel_history_error_from_log(text),
                    (2, "retry", text),
                )
                self.assertIsNone(service_module._legacy_channel_status_from_log(text))

    def test_history_extracts_full_command_exception(self) -> None:
        text = (
            "bbfdmd -c get Device.ManagementServer.X_SDMC_AcsLineStatus在通道2:"
            "执行错误时发生异常:[WinError 10054] 远程主机强迫关闭了一个现有的连接。"
        )
        self.assertEqual(
            service_module._legacy_channel_history_error_from_log(text),
            (2, "failed", text),
        )
        self.assertIsNone(service_module._legacy_channel_status_from_log(text))

    def test_history_extracts_ping_error(self) -> None:
        text = "通道 1 发送 ping error 信号"
        self.assertEqual(
            service_module._legacy_channel_history_error_from_log(text),
            (1, "failed", text),
        )
        self.assertIsNone(service_module._legacy_channel_status_from_log(text))

    def test_history_error_parser_ignores_normal_and_unattributed_logs(self) -> None:
        for text in (
            "192.168.1.102登录成功",
            "通道 2 连接telnet 成功",
            "通道 2 发送 ping success 信号",
            "执行错误时发生异常:[WinError 10054]",
            "通道 2 执行指令：echo ok，在第1次时出现错误；准备第2/3次验证",
        ):
            with self.subTest(text=text):
                self.assertIsNone(service_module._legacy_channel_history_error_from_log(text))

    def test_parent_records_extra_errors_before_dedup_with_channel_cycles(self) -> None:
        retry = "通道 2 第 1 次连接telnet 失败，等待10s再连接一次；"
        exception = (
            "bbfdmd -c get Device.ManagementServer.X_SDMC_AcsLineStatus在通道2:"
            "执行错误时发生异常:[WinError 10054] 远程主机强迫关闭了一个现有的连接。"
        )
        ping = "通道 1 发送 ping error 信号"

        class ErrorProcess(_HistoryCompletedProcess):
            def start(self):
                message_queue = self.args[1]
                for level, text, source in (
                    ("info", "*******通道 【2】 开始第3次测试*******", "signal"),
                    ("info", "*******通道 【1】 开始第2次测试*******", "signal"),
                    ("error", retry, "signal"),
                    ("error", exception, "logger"),
                    ("error", ping, "logger"),
                    ("error", ping, "signal"),
                    ("error", "通道 9 发送 ping error 信号", "logger"),
                ):
                    message_queue.put(dict(type="log", level=level, message=text, source=source))
                message_queue.put(dict(type="result", ok=True, detail="全部完成"))
                self._alive = False

        class ErrorContext(_FakeProcessContext):
            def Process(self, **kwargs):
                return ErrorProcess(**kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            request = prepare_legacy_power_test_request(
                _write_config_tree(Path(temp_dir)),
                (LegacyPowerChannel(1, "192.168.1.101"), LegacyPowerChannel(2, "192.168.1.102")),
            )
        history, emitted, statuses = [], [], []
        result = run_legacy_power_test(
            request, emitted.append, _FakeEvent(), process_context=ErrorContext(),
            on_channel_history=lambda *event: history.append(event),
            on_channel_status=lambda *event: statuses.append(event),
        )
        self.assertTrue(result.ok)
        self.assertEqual(history, [
            (2, 3, "retry", retry),
            (2, 3, "failed", exception),
            (1, 2, "failed", ping),
            (1, 2, "failed", ping),
        ])
        self.assertEqual(statuses, [
            (2, "running", "第3轮执行中"),
            (1, "running", "第2轮执行中"),
        ])
        for text in (retry, exception, ping):
            self.assertEqual(emitted.count(f"[旧工具Logs][ERROR] {text}"), 1)

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

    def test_parent_reports_complete_per_channel_retry_and_failure_history(self) -> None:
        request = LegacyPowerTestRequest(
            tool_root=Path("legacy"),
            communication_method="telnet",
            serial_port="COM105",
            baud_rate="19200",
            selected_profile="TEST_PROJECT",
            profile_filename="test_project_config.ini",
            startup_time=180,
            interval_time=20,
            number_of_tests=3,
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
        history = []

        result = run_legacy_power_test(
            request,
            lambda _line: None,
            _FakeEvent(),
            process_context=_HistoryProcessContext(),
            on_channel_history=lambda channel, cycle, status, detail: history.append(
                (channel, cycle, status, detail)
            ),
        )

        self.assertFalse(result.ok)
        self.assertEqual(
            [item[:3] for item in history],
            [(5, 2, "retry"), (5, 2, "success"), (5, 2, "failed")],
        )
        self.assertIn("\u51c6\u5907\u7b2c2/3\u6b21\u9a8c\u8bc1", history[0][3])
        self.assertIn("\u91cd\u8bd51\u6b21\u540e\u9a8c\u8bc1\u6210\u529f", history[1][3])
        self.assertIn("3\u6b21\u9a8c\u8bc1\u5931\u8d25", history[2][3])

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
