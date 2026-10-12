"""无 GUI 执行旧工具 ``Start All`` 开关机测试业务。

旧 ``Auto_Power_On_Off_Tool.py`` 把业务编排、PyQt 控件和相对路径绑定在一起。
本适配层不 import / 实例化旧 ``UiCase``，而是在独立子进程中直接复用其
``PowerOnOffTelnet`` / ``PowerOnOffSsh``、串口和电源控制业务类，并把旧界面
``Logs`` 对应的三个 ``show_signal*`` 信号及旧结果文件中的每轮正常结论转发到
新工具主执行日志。
"""
from __future__ import annotations

import builtins
import configparser
import multiprocessing
import os
import queue
import re
import sys
import threading
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from line_check_assistant.legacy_ui_defaults_store import LegacyUiDefaultsStore


LEGACY_CONFIG_FILENAME = "config.ini"
LEGACY_TEST_PROJECT_FILENAME = "test_project_config.ini"
LEGACY_STOP_GRACE_SECONDS = 10.0
LEGACY_PROCESS_POLL_SECONDS = 0.2
LEGACY_RESULT_DRAIN_SECONDS = 1.0
LEGACY_LOG_DEDUP_SECONDS = 2.0
LEGACY_LOG_WHITESPACE_PATTERN = re.compile(r"\s+")
LEGACY_IPV4_PATTERN = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
LEGACY_NETWORK_CARD_PINGED_PATTERN = re.compile(
    r"^The network card with IP\s+(?P<source_ip>(?:\d{1,3}\.){3}\d{1,3})\s+"
    r"has been pinged$",
    re.IGNORECASE,
)
LEGACY_LOGIN_SUCCESS_PATTERN = re.compile(
    r"^(?P<source_ip>(?:\d{1,3}\.){3}\d{1,3})\s*登录成功$"
)
LEGACY_NORMAL_CYCLE_RESULT_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?:\s*"
    r"通道(?P<channel>\d+)下挂的设备在第(?P<cycle>\d+)次测试时正常$"
)
LEGACY_CYCLE_START_PATTERN = re.compile(
    r"^\*+\s*通道\s*【(?P<channel>\d+)】\s*开始第\s*(?P<cycle>\d+)\s*次测试\s*\*+$"
)
LEGACY_COMMAND_RESULT_FILENAME_PATTERN = re.compile(
    r"^device_(?P<device_number>\d+)_command_results_.+\.log$"
)
LEGACY_COMMAND_RETRY_PATTERN = re.compile(
    r"^通道\s*(?P<channel>\d+)\s*执行指令：\s*(?P<command>.+?)，"
    r"在第\s*(?P<attempt>\d+)\s*次时出现错误；准备第\s*"
    r"(?P<next_attempt>\d+)\s*/\s*(?P<total>\d+)\s*次验证$"
)
LEGACY_COMMAND_FAILURE_PATTERN = re.compile(
    r"^通道\s*(?P<channel>\d+)\s*尝试执行指令：\s*(?P<command>.+?)\s+"
    r"(?P<attempts>\d+)次进行验证，验证失败$"
)
LEGACY_COMMAND_RETRY_SUCCESS_PATTERN = re.compile(
    r"^通道\s*(?P<channel>\d+)\s*发送指令\s*(?P<command>.+?)\s*重试了\s*"
    r"(?P<retries>\d+)次之后，执行成功$"
)
LEGACY_KEY_RESULT_MARKERS = (
    "登录成功",
    "连接成功",
    "测试完成",
    "重试了",
    "扫描到了ssid",
    "网卡速率",
    "ping通",
    "pinged",
    "PING is OK",
    "wifi connected",
    "发送邮件成功",
)


@dataclass(frozen=True)
class LegacyPowerChannel:
    number: int
    network_card_ip: str


@dataclass(frozen=True)
class LegacyPowerTestRequest:
    tool_root: Path
    communication_method: str
    serial_port: str
    baud_rate: str
    selected_profile: str
    profile_filename: str
    startup_time: int
    interval_time: int
    number_of_tests: int
    wait_command_done: int
    telnet_enable: bool
    emails: str
    connect_wifi_enable: bool
    product_solution: str
    wifi_test_2g_enable: bool
    wifi_test_5g_enable: bool
    wifi_auth_mode: str
    wifi_cipher: str
    wifi_choose_wireless_card: bool
    wifi_wireless_card_name: str
    channels: tuple[LegacyPowerChannel, ...]
    ping_target_ip: str = ""


@dataclass(frozen=True)
class LegacyPowerTestResult:
    ok: bool
    detail: str


Output = Callable[[str], None]
ProgressOutput = Callable[[int, int], None]
ChannelProgressOutput = Callable[[int, int, int, str], None]
ChannelStatusOutput = Callable[[int, str, str], None]
ChannelHistoryOutput = Callable[[int, int, str, str], None]


def _format_power_frame(payload) -> str:
    return " ".join(f"{byte:02X}" for byte in bytes(payload))


def _should_forward_legacy_log(level: str, text: str, source: str) -> bool:
    """保留操作员信号和关键结果，过滤旧 logger 的高频底层 INFO。"""
    normalized_level = level.strip().lower()
    if normalized_level in {"warning", "error"}:
        return True
    if source == "signal":
        return True
    if source != "logger":
        return True
    compact_text = LEGACY_LOG_WHITESPACE_PATTERN.sub(" ", text).strip()
    return len(compact_text) <= 300 and any(
        marker.lower() in compact_text.lower() for marker in LEGACY_KEY_RESULT_MARKERS
    )


def _legacy_log_dedup_key(level: str, text: str) -> tuple[str, str]:
    return (
        level.strip().lower(),
        LEGACY_LOG_WHITESPACE_PATTERN.sub(" ", text).strip(),
    )


def _overall_completed_cycle(
    completed_by_channel: dict[int, int],
    result_line: str,
    total_cycles: int,
) -> int | None:
    """记录单通道正常完成轮次，返回所有已选通道都完成的最小轮次。"""
    normalized_line = result_line.strip()
    match = LEGACY_NORMAL_CYCLE_RESULT_PATTERN.fullmatch(normalized_line)
    if match is not None:
        completed_cycle = int(match.group("cycle"))
    else:
        match = LEGACY_CYCLE_START_PATTERN.fullmatch(normalized_line)
        if match is None:
            return None
        # 新一轮已开始，说明上一轮已经完成；兼容 only_power_off_on 不写正常结果行的路径。
        completed_cycle = int(match.group("cycle")) - 1
    channel = int(match.group("channel"))
    if channel not in completed_by_channel:
        return None
    cycle = max(0, min(completed_cycle, total_cycles))
    completed_by_channel[channel] = max(completed_by_channel[channel], cycle)
    return min(completed_by_channel.values()) if completed_by_channel else 0


def _legacy_channel_progress_from_log(
    result_line: str,
    total_cycles: int,
) -> tuple[int, int, str] | None:
    """从旧日志提取单通道完成轮次与当前阶段，供主界面独立概览使用。"""
    normalized_line = result_line.strip()
    match = LEGACY_NORMAL_CYCLE_RESULT_PATTERN.fullmatch(normalized_line)
    if match is not None:
        cycle = max(0, min(int(match.group("cycle")), total_cycles))
        return int(match.group("channel")), cycle, f"第{cycle}轮完成"
    match = LEGACY_CYCLE_START_PATTERN.fullmatch(normalized_line)
    if match is None:
        return None
    current_cycle = int(match.group("cycle"))
    completed_cycle = max(0, min(current_cycle - 1, total_cycles))
    return int(match.group("channel")), completed_cycle, f"第{current_cycle}轮执行中"


def _extract_ipv4(value: str) -> str:
    match = LEGACY_IPV4_PATTERN.search(value)
    return match.group(0) if match is not None else ""


def _format_legacy_operator_log(text: str, ping_target_ip: str) -> str:
    """把旧工具英文关键结果转换为新工具的操作员日志。"""
    compact_text = LEGACY_LOG_WHITESPACE_PATTERN.sub(" ", text).strip()
    match = LEGACY_NETWORK_CARD_PINGED_PATTERN.fullmatch(compact_text)
    if match is None:
        return text
    source_ip = match.group("source_ip")
    if ping_target_ip:
        return f"Ping 成功：源网卡 {source_ip} → 目标样机 {ping_target_ip}"
    return f"Ping 成功：源网卡 {source_ip} 已连通目标样机"


def _legacy_channel_status_from_log(text: str) -> tuple[int, str, str] | None:
    """从旧业务明确的重试/失败信号提取主界面通道状态。"""
    compact_text = LEGACY_LOG_WHITESPACE_PATTERN.sub(" ", text).strip()
    retry_match = LEGACY_COMMAND_RETRY_PATTERN.fullmatch(compact_text)
    if retry_match is not None:
        return (
            int(retry_match.group("channel")),
            "retry",
            (
                f"执行指令：{retry_match.group('command')}，在第"
                f"{retry_match.group('attempt')}次时出现错误；准备第"
                f"{retry_match.group('next_attempt')}/{retry_match.group('total')}次验证"
            ),
        )
    failure_match = LEGACY_COMMAND_FAILURE_PATTERN.fullmatch(compact_text)
    if failure_match is not None:
        return (
            int(failure_match.group("channel")),
            "failed",
            (
                f"执行指令：{failure_match.group('command')} "
                f"{failure_match.group('attempts')}次验证失败"
            ),
        )
    retry_success_match = LEGACY_COMMAND_RETRY_SUCCESS_PATTERN.fullmatch(compact_text)
    if retry_success_match is not None:
        return (
            int(retry_success_match.group("channel")),
            "success",
            (
                f"执行指令：{retry_success_match.group('command')} 重试"
                f"{retry_success_match.group('retries')}次后验证成功"
            ),
        )
    return None


def prepare_legacy_power_test_request(
    tool_root: Path,
    channels: Iterable[LegacyPowerChannel],
) -> LegacyPowerTestRequest:
    """读取旧工具现用配置并形成无 GUI ``Start All`` 请求。"""
    resolved_root = Path(tool_root).resolve()
    config_dir = resolved_root / "config"
    config_path = config_dir / LEGACY_CONFIG_FILENAME
    defaults = LegacyUiDefaultsStore(config_path).load()
    defaults = LegacyUiDefaultsStore(config_path).validate(defaults)

    selected_channels = tuple(channels)
    if not selected_channels:
        raise ValueError("执行开关机测试至少需要一个已勾选通道")
    invalid_channels = [str(item.number) for item in selected_channels if not 1 <= item.number <= 16]
    if invalid_channels:
        raise ValueError(f"旧工具仅支持电源通道 1～16：{', '.join(invalid_channels)}")
    missing_ips = [str(item.number) for item in selected_channels if not item.network_card_ip.strip()]
    if missing_ips:
        raise ValueError(f"以下通道缺少 PC 静态 IP：{', '.join(missing_ips)}")
    parser = configparser.RawConfigParser()
    parser.optionxform = str
    parser.read(config_path, encoding="utf-8")
    if not parser.has_section("config"):
        raise ValueError(f"配置文件缺少 [config]：{config_path}")
    profile_filename = ""
    for profile_name, filename in parser.items("config"):
        if profile_name.strip().lower() == defaults["selected_profile"].strip().lower():
            profile_filename = filename.strip()
            break
    if not profile_filename:
        raise ValueError(
            f"[ui_defaults] selected_profile 未出现在 [config]：{defaults['selected_profile']}"
        )
    profile_path = config_dir / profile_filename
    if not profile_path.is_file():
        raise FileNotFoundError(f"旧工具测试方案不存在：{profile_path}")

    profile_parser = configparser.RawConfigParser()
    profile_parser.read(profile_path, encoding="utf-8")
    power_parser = configparser.RawConfigParser()
    power_parser.read(config_dir / "network_card_ip.ini", encoding="utf-8")
    serial_port = power_parser.get("power_supply", "serial_port", fallback="").strip().upper()
    if not serial_port:
        raise ValueError("执行开关机测试需要配置程控电源 COM 口")
    telnet_default_on = profile_parser.get(
        "telnet", "telnet_default_on", fallback="1"
    ).strip()
    if telnet_default_on not in {"0", "1"}:
        raise ValueError("[telnet] telnet_default_on 只能是 0 或 1")
    connect_wifi_enable = profile_parser.getboolean(
        "connect_wifi", "enable", fallback=False
    )
    product_solution = profile_parser.get(
        "connect_wifi", "product_solution", fallback=""
    ).strip().lower()
    wifi_test_2g_enable = profile_parser.getboolean(
        "connect_wifi", "test_2g_enable", fallback=True
    )
    wifi_test_5g_enable = profile_parser.getboolean(
        "connect_wifi", "test_5g_enable", fallback=True
    )
    wifi_auth_mode = profile_parser.get(
        "connect_wifi", "auth_mode", fallback="WPA2-PSK"
    ).strip() or "WPA2-PSK"
    wifi_cipher = profile_parser.get(
        "connect_wifi", "cipher", fallback="AES"
    ).strip() or "AES"
    wifi_choose_wireless_card = profile_parser.getboolean(
        "connect_wifi", "choose_wireless_card", fallback=False
    )
    wifi_wireless_card_name = profile_parser.get(
        "connect_wifi", "wireless_card_name", fallback=""
    ).strip()
    if connect_wifi_enable and wifi_choose_wireless_card and not wifi_wireless_card_name:
        raise ValueError("WiFi 连接测试已勾选指定无线网卡，但无线网卡名称为空")
    request_url = profile_parser.get(
        defaults["communication_method"], "request_url", fallback=""
    ).strip()
    ping_target_ip = _extract_ipv4(request_url)
    emails = parser.get("Emails", "emails", fallback="").strip().replace('"', "")

    return LegacyPowerTestRequest(
        tool_root=resolved_root,
        communication_method=defaults["communication_method"],
        serial_port=serial_port,
        baud_rate=defaults["baud_rate"],
        selected_profile=defaults["selected_profile"],
        profile_filename=profile_filename,
        startup_time=int(defaults["startup_time"]),
        interval_time=int(defaults["interval_time"]),
        number_of_tests=int(defaults["number_of_tests"]),
        wait_command_done=int(defaults["wait_command_done"]),
        telnet_enable=telnet_default_on == "0",
        emails=emails,
        connect_wifi_enable=connect_wifi_enable,
        product_solution=product_solution,
        wifi_test_2g_enable=wifi_test_2g_enable,
        wifi_test_5g_enable=wifi_test_5g_enable,
        wifi_auth_mode=wifi_auth_mode,
        wifi_cipher=wifi_cipher,
        wifi_choose_wireless_card=wifi_choose_wireless_card,
        wifi_wireless_card_name=wifi_wireless_card_name,
        channels=selected_channels,
        ping_target_ip=ping_target_ip,
    )


def run_legacy_power_test(
    request: LegacyPowerTestRequest,
    emit: Output,
    stop_event: threading.Event,
    *,
    process_context=None,
    on_progress: ProgressOutput | None = None,
    on_channel_progress: ChannelProgressOutput | None = None,
    on_channel_status: ChannelStatusOutput | None = None,
    on_channel_history: ChannelHistoryOutput | None = None,
) -> LegacyPowerTestResult:
    """在独立无 GUI 子进程运行旧 ``Start All``，同步等待最终结果。"""
    context = process_context or multiprocessing.get_context("spawn")
    message_queue = context.Queue()
    child_stop_event = context.Event()
    process = context.Process(
        target=_legacy_start_all_worker,
        args=(request, message_queue, child_stop_event),
        name="legacy-start-all-headless",
    )
    emit(
        "[执行开关机测试] 启动旧 Start All 无GUI业务："
        f"通信={request.communication_method}，COM={request.serial_port}，"
        f"通道={[item.number for item in request.channels]}，循环={request.number_of_tests}次"
    )
    if request.connect_wifi_enable:
        wifi_card = (
            request.wifi_wireless_card_name
            if request.wifi_choose_wireless_card
            else "自动选择首张可用无线网卡"
        )
        emit(
            "[执行开关机测试] WiFi连接配置：主控=启用，"
            f"2.4G={'启用' if request.wifi_test_2g_enable else '关闭'}，"
            f"5G={'启用' if request.wifi_test_5g_enable else '关闭'}，"
            f"方案={request.product_solution}，认证={request.wifi_auth_mode}，"
            f"加密={request.wifi_cipher}，网卡={wifi_card}"
        )
    else:
        emit("[执行开关机测试] WiFi连接配置：主控=关闭，本次跳过 WiFi 连接测试。")
    completed_by_channel = {item.number: 0 for item in request.channels}
    last_reported_cycle = 0
    if on_progress is not None:
        on_progress(0, request.number_of_tests)
    process.start()
    if on_channel_progress is not None:
        for channel in request.channels:
            on_channel_progress(channel.number, 0, request.number_of_tests, "等待第1轮")

    final_result: LegacyPowerTestResult | None = None
    stop_deadline: float | None = None
    exit_drain_deadline: float | None = None
    recent_log_times: dict[tuple[str, str], float] = {}
    last_forwarded_log_key: tuple[str, str] | None = None
    forwarded_login_success_ips: set[str] = set()
    channel_details: dict[int, str] = {}
    emit(
        "[执行开关机测试] 已启用精简日志：保留每轮开始/正常结论、关键结果、"
        "警告/错误、程控电源指令和最终结论。"
    )
    while process.is_alive() or final_result is None:
        if stop_event.is_set() and not child_stop_event.is_set():
            emit("[执行开关机测试] 收到停止请求，正在通知旧业务停止所有通道。")
            child_stop_event.set()
            stop_deadline = time.monotonic() + LEGACY_STOP_GRACE_SECONDS
        if stop_deadline is not None and process.is_alive() and time.monotonic() >= stop_deadline:
            emit("[执行开关机测试] 旧业务未在停止宽限期内退出，终止本次无GUI专用子进程。")
            process.terminate()
            process.join(timeout=2)
            return LegacyPowerTestResult(False, "用户停止，旧业务子进程已终止")

        try:
            message = message_queue.get(timeout=LEGACY_PROCESS_POLL_SECONDS)
        except queue.Empty:
            if not process.is_alive():
                if exit_drain_deadline is None:
                    exit_drain_deadline = time.monotonic() + LEGACY_RESULT_DRAIN_SECONDS
                elif time.monotonic() >= exit_drain_deadline:
                    break
            continue

        message_type = message.get("type")
        if message_type == "log":
            level = str(message.get("level", "info")).upper()
            raw_text = str(message.get("message", ""))
            source = str(message.get("source", "signal")).lower()
            channel_status = _legacy_channel_status_from_log(raw_text)
            if channel_status is not None:
                channel_number, status, detail = channel_status
                channel_details[channel_number] = detail
                # 重试过程和最终失败必须在主日志精简/去重之前单独上报；
                # "重试后成功"也属于本次重试历史的一部分，不能因状态恢复而丢失。
                if on_channel_history is not None and (
                    status in {"retry", "failed"}
                    or (status == "success" and "重试" in detail)
                ):
                    completed_cycle = completed_by_channel.get(channel_number, 0)
                    current_cycle = min(
                        max(completed_cycle + 1, 1), request.number_of_tests
                    )
                    on_channel_history(channel_number, current_cycle, status, detail)
                if on_channel_status is not None:
                    on_channel_status(channel_number, status, detail)
            channel_progress = _legacy_channel_progress_from_log(
                raw_text,
                request.number_of_tests,
            )
            if channel_progress is not None:
                channel_number, completed_cycle, stage = channel_progress
                if channel_number in completed_by_channel:
                    completed_by_channel[channel_number] = max(
                        completed_by_channel[channel_number],
                        completed_cycle,
                    )
                    if on_channel_progress is not None:
                        on_channel_progress(
                            channel_number,
                            completed_by_channel[channel_number],
                            request.number_of_tests,
                            stage,
                        )
            completed_cycle = _overall_completed_cycle(
                completed_by_channel,
                raw_text,
                request.number_of_tests,
            )
            if (
                on_progress is not None
                and completed_cycle is not None
                and completed_cycle > last_reported_cycle
            ):
                last_reported_cycle = completed_cycle
                on_progress(completed_cycle, request.number_of_tests)
            if not _should_forward_legacy_log(level, raw_text, source):
                continue
            text = _format_legacy_operator_log(raw_text, request.ping_target_ip)
            login_match = LEGACY_LOGIN_SUCCESS_PATTERN.fullmatch(
                LEGACY_LOG_WHITESPACE_PATTERN.sub(" ", text).strip()
            )
            if login_match is not None:
                source_ip = login_match.group("source_ip")
                if source_ip in forwarded_login_success_ips:
                    continue
                forwarded_login_success_ips.add(source_ip)
            dedup_key = _legacy_log_dedup_key(level, text)
            if dedup_key == last_forwarded_log_key:
                continue
            now = time.monotonic()
            if now - recent_log_times.get(dedup_key, float("-inf")) < LEGACY_LOG_DEDUP_SECONDS:
                continue
            recent_log_times[dedup_key] = now
            if len(recent_log_times) > 128:
                recent_log_times = {
                    key: seen_at
                    for key, seen_at in recent_log_times.items()
                    if now - seen_at < LEGACY_LOG_DEDUP_SECONDS
                }
            emit(f"[旧工具Logs][{level}] {text}")
            last_forwarded_log_key = dedup_key
        elif message_type == "channel_result":
            channel_number = int(message.get("channel", 0))
            ok = bool(message.get("ok"))
            if not 1 <= channel_number <= 16:
                continue
            if ok:
                status, detail = "success", "所有测试项验证成功"
                if on_channel_progress is not None:
                    on_channel_progress(
                        channel_number,
                        request.number_of_tests,
                        request.number_of_tests,
                        detail,
                    )
            else:
                status = "failed"
                detail = channel_details.get(
                    channel_number,
                    "测试失败，详细信息请查看执行日志",
                )
            if on_channel_status is not None:
                on_channel_status(channel_number, status, detail)
        elif message_type == "stage":
            emit(f"[执行开关机测试] {message.get('message', '')}")
            last_forwarded_log_key = None
        elif message_type == "result":
            final_result = LegacyPowerTestResult(
                bool(message.get("ok")),
                str(message.get("detail", "")),
            )

    process.join(timeout=2)
    if final_result is None:
        detail = f"旧业务子进程异常退出，exitcode={process.exitcode}"
        emit(f"[执行开关机测试] 失败：{detail}")
        return LegacyPowerTestResult(False, detail)
    if final_result.ok and on_progress is not None and last_reported_cycle < request.number_of_tests:
        on_progress(request.number_of_tests, request.number_of_tests)
    emit(
        f"[执行开关机测试] {'成功' if final_result.ok else '失败'}：{final_result.detail}"
    )
    return final_result


class _HeadlessSignal:
    def __init__(self) -> None:
        self._callbacks: list[Callable[..., None]] = []

    def __getitem__(self, _signature):
        return self

    def connect(self, callback: Callable[..., None]) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in tuple(self._callbacks):
            callback(*args)


class _HeadlessSignalDescriptor:
    def __init__(self) -> None:
        self._storage_name = ""

    def __set_name__(self, _owner, name: str) -> None:
        self._storage_name = f"__headless_signal_{name}"

    def __get__(self, instance, _owner):
        if instance is None:
            return self
        signal = instance.__dict__.get(self._storage_name)
        if signal is None:
            signal = _HeadlessSignal()
            instance.__dict__[self._storage_name] = signal
        return signal


class _HeadlessQThread:
    def __init__(self, *_args, **_kwargs) -> None:
        pass


def _install_headless_legacy_stubs(request: LegacyPowerTestRequest):
    """替代旧业务只用于信号/配置的 PyQt 类，确保不创建任何 GUI。"""
    qt_package = types.ModuleType("PyQt5")
    qt_package.__path__ = []  # type: ignore[attr-defined]
    qt_core = types.ModuleType("PyQt5.QtCore")
    qt_core.QThread = _HeadlessQThread
    qt_core.pyqtSignal = lambda *_args, **_kwargs: _HeadlessSignalDescriptor()
    sys.modules["PyQt5"] = qt_package
    sys.modules["PyQt5.QtCore"] = qt_core

    class HeadlessOnuConfig:
        connect_wifi_enable_status = int(request.connect_wifi_enable)
        choose_test_2g_flag = int(request.wifi_test_2g_enable)
        choose_test_5g_flag = int(request.wifi_test_5g_enable)
        connect_wifi_auth_mode = request.wifi_auth_mode
        connect_wifi_ciper = request.wifi_cipher
        Onu_solution_type = request.product_solution
        choose_wireless_card_flag = int(request.wifi_choose_wireless_card)
        choose_wireless_card_name = request.wifi_wireless_card_name
        iface_names: list[str] = []

    onu_module = types.ModuleType("test_case.Onu_config")
    onu_module.OnuCongfig = HeadlessOnuConfig
    sys.modules["test_case.Onu_config"] = onu_module
    return HeadlessOnuConfig


class _ForwardingLegacyLogger:
    """旧业务 logger 适配；已知敏感值先脱敏再转发。"""

    def __init__(self, message_queue, secrets: Sequence[str]) -> None:
        self.message_queue = message_queue
        self.secrets = tuple(secret for secret in secrets if secret)

    def _write(self, level: str, message) -> None:
        text = str(message)
        for secret in self.secrets:
            text = text.replace(secret, "***")
        self.message_queue.put(
            {
                "type": "log",
                "level": level,
                "message": text,
                "source": "logger",
            }
        )

    def info(self, message, *_args, **_kwargs) -> None:
        self._write("info", message)

    def warning(self, message, *_args, **_kwargs) -> None:
        self._write("warning", message)

    def error(self, message, *_args, **_kwargs) -> None:
        self._write("error", message)

    def debug(self, message, *_args, **_kwargs) -> None:
        return


class _ForwardingLegacyResultFile:
    """保留旧结果文件写入，并转发完整的单轮正常结果行。"""

    def __init__(self, opened_file, message_queue) -> None:
        self._opened_file = opened_file
        self._message_queue = message_queue
        self._text_buffer = ""

    def write(self, data):
        written = self._opened_file.write(data)
        if isinstance(data, (bytes, bytearray, memoryview)):
            payload = bytes(data)
            if isinstance(written, int):
                payload = payload[:written]
            self._capture(payload.decode("utf-8", errors="replace"))
        return written

    def _capture(self, text: str) -> None:
        self._text_buffer += text
        while "\n" in self._text_buffer:
            line, self._text_buffer = self._text_buffer.split("\n", 1)
            self._forward_if_normal_cycle_result(line.rstrip("\r"))

    def _forward_if_normal_cycle_result(self, line: str) -> None:
        if LEGACY_NORMAL_CYCLE_RESULT_PATTERN.fullmatch(line):
            self._message_queue.put(
                {
                    "type": "log",
                    "level": "info",
                    "message": line,
                    "source": "result_file",
                }
            )

    def __enter__(self):
        self._opened_file.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._text_buffer:
            self._forward_if_normal_cycle_result(self._text_buffer.rstrip("\r"))
            self._text_buffer = ""
        return self._opened_file.__exit__(exc_type, exc_value, traceback)

    def __getattr__(self, name: str):
        return getattr(self._opened_file, name)


def _is_legacy_command_result_file(file, mode: str) -> bool:
    if "b" not in mode or not ({"w", "a"} & set(mode)):
        return False
    try:
        path = Path(file)
    except TypeError:
        return False
    filename_match = LEGACY_COMMAND_RESULT_FILENAME_PATTERN.fullmatch(path.name)
    if filename_match is None:
        return False
    device_number = filename_match.group("device_number")
    return (
        path.parent.name == f"device_{device_number}"
        and path.parent.parent.name == "test_results"
    )


def _install_legacy_result_log_forwarder(message_queue):
    """在当前旧业务子进程内安装窄范围结果文件转发器。"""
    original_open = builtins.open

    def forwarding_open(file, mode="r", *args, **kwargs):
        opened_file = original_open(file, mode, *args, **kwargs)
        if _is_legacy_command_result_file(file, str(mode)):
            return _ForwardingLegacyResultFile(opened_file, message_queue)
        return opened_file

    builtins.open = forwarding_open

    def restore() -> None:
        if builtins.open is forwarding_open:
            builtins.open = original_open

    return restore


def _read_profile_secrets(tool_root: Path, profile_filename: str) -> tuple[str, ...]:
    parser = configparser.RawConfigParser()
    parser.read(tool_root / "config" / profile_filename, encoding="utf-8")
    return tuple(
        parser.get(section, option, fallback="")
        for section, option in (("telnet", "password"), ("ssh", "password"))
    )


def _connect_legacy_log_signals(worker, message_queue) -> None:
    for signal_name, level in (
        ("show_signal", "info"),
        ("show_signal_warning", "warning"),
        ("show_signal_error", "error"),
    ):
        signal = getattr(worker, signal_name, None)
        if signal is None:
            continue
        signal[str].connect(
            lambda text, log_level=level: message_queue.put(
                {
                    "type": "log",
                    "level": log_level,
                    "message": str(text),
                    "source": "signal",
                }
            )
        )


def _legacy_start_all_worker(request, message_queue, stop_event) -> None:
    """子进程入口；必须保持模块顶层，供 Windows spawn / PyInstaller 调用。"""
    serial_client = None
    legacy_worker = None
    restore_result_log_open = None
    try:
        tool_root = Path(request.tool_root).resolve()
        os.chdir(tool_root)
        sys.path.insert(0, str(tool_root))
        onu_config_class = _install_headless_legacy_stubs(request)
        if request.connect_wifi_enable:
            import pywifi

            onu_config_class.iface_names = [
                interface.name() for interface in pywifi.PyWiFi().interfaces()
            ]
            if not onu_config_class.iface_names:
                raise RuntimeError("已启用 WiFi 连接测试，但当前电脑没有可用无线网卡")
            if (
                request.wifi_choose_wireless_card
                and request.wifi_wireless_card_name not in onu_config_class.iface_names
            ):
                raise RuntimeError(
                    "指定的无线网卡不存在或未启用："
                    f"{request.wifi_wireless_card_name}；当前可用："
                    f"{', '.join(onu_config_class.iface_names)}"
                )

        from common.serilal_client import Serial
        if request.communication_method == "telnet":
            from test_case.powe_on_off_telnet import PowerOnOffTelnet as WorkerClass
        else:
            from test_case.power_on_off_ssh import PowerOnOffSsh as WorkerClass

        secrets = _read_profile_secrets(tool_root, request.profile_filename)
        logger = _ForwardingLegacyLogger(message_queue, secrets)
        message_queue.put(
            {
                "type": "stage",
                "message": (
                    f"打开程控电源串口 {request.serial_port}/{request.baud_rate}；"
                    "旧 Start All 初始化将下发全通道断电帧 55 00 AD 00 00 AD。"
                ),
            }
        )
        serial_client = Serial(request.serial_port, request.baud_rate, logger, timeout=5)
        serial_client.is_open()
        original_serial_write = serial_client.write

        def write_with_execution_log(payload):
            frame = bytes(payload)
            message_queue.put(
                {
                    "type": "stage",
                    "message": "下发程控电源指令：" + _format_power_frame(frame),
                }
            )
            return original_serial_write(payload)

        serial_client.write = write_with_execution_log

        common_args = (
            serial_client,
            logger,
            request.startup_time,
            request.interval_time,
            request.wait_command_done,
            request.number_of_tests,
            request.profile_filename,
            request.emails,
        )
        if request.communication_method == "telnet":
            legacy_worker = WorkerClass(
                *common_args,
                int(request.telnet_enable),
                request.selected_profile,
            )
        else:
            legacy_worker = WorkerClass(
                *common_args,
                request.selected_profile,
            )
        legacy_worker.dingtalk.log = logger.info
        _connect_legacy_log_signals(legacy_worker, message_queue)
        restore_result_log_open = _install_legacy_result_log_forwarder(message_queue)

        selected = {item.number for item in request.channels}
        for channel_number in range(1, 17):
            setattr(
                legacy_worker,
                f"channel_{channel_number}_flag",
                1 if channel_number in selected else 0,
            )
        legacy_worker.power_control.stopthreadevent = 0
        power_consumer = threading.Thread(
            target=legacy_worker.power_control.consumer,
            name="legacy-power-command-consumer",
            daemon=True,
        )
        power_consumer.start()

        channel_results: dict[int, bool] = {}
        channel_threads: list[threading.Thread] = []

        def run_channel(channel: LegacyPowerChannel) -> None:
            try:
                if request.communication_method == "telnet":
                    result = legacy_worker.run_case(
                        channel.network_card_ip,
                        channel.number,
                        stop_event,
                    )
                else:
                    result = legacy_worker.run_case(
                        channel.network_card_ip,
                        channel.number,
                        1,
                    )
                channel_results[channel.number] = bool(result)
                message_queue.put(
                    {"type": "channel_result", "channel": channel.number, "ok": bool(result)}
                )
            except Exception as exc:  # noqa: BLE001 - 子进程必须回传旧业务异常
                channel_results[channel.number] = False
                message_queue.put(
                    {
                        "type": "log",
                        "level": "error",
                        "message": f"通道 {channel.number} 无GUI执行异常：{exc}",
                    }
                )
                message_queue.put(
                    {"type": "channel_result", "channel": channel.number, "ok": False}
                )

        message_queue.put(
            {
                "type": "stage",
                "message": f"开始启动已勾选通道：{sorted(selected)}",
            }
        )
        for channel in request.channels:
            if stop_event.is_set():
                break
            thread = threading.Thread(
                target=run_channel,
                args=(channel,),
                name=f"legacy-channel-{channel.number}",
            )
            thread.start()
            channel_threads.append(thread)
            if stop_event.wait(1.0):
                break

        stop_forwarded = False
        while any(thread.is_alive() for thread in channel_threads):
            if stop_event.is_set() and not stop_forwarded:
                stop_forwarded = True
                request_stop = getattr(legacy_worker, "request_stop", None)
                if callable(request_stop):
                    request_stop()
                for channel_number in range(1, 17):
                    setattr(legacy_worker, f"channel_{channel_number}_flag", 0)
            for thread in channel_threads:
                thread.join(timeout=0.2)

        if stop_event.is_set():
            message_queue.put(
                {"type": "result", "ok": False, "detail": "用户已停止执行开关机测试"}
            )
            return
        failed = sorted(
            channel.number
            for channel in request.channels
            if not channel_results.get(channel.number, False)
        )
        if failed:
            message_queue.put(
                {
                    "type": "result",
                    "ok": False,
                    "detail": f"失败通道：{failed}",
                }
            )
        else:
            message_queue.put(
                {
                    "type": "result",
                    "ok": True,
                    "detail": f"{len(request.channels)} 个通道全部完成",
                }
            )
    except Exception as exc:  # noqa: BLE001 - 保证初始化错误可见
        message_queue.put(
            {"type": "log", "level": "error", "message": f"旧 Start All 初始化失败：{exc}"}
        )
        message_queue.put({"type": "result", "ok": False, "detail": str(exc)})
    finally:
        if restore_result_log_open is not None:
            restore_result_log_open()
        if legacy_worker is not None:
            try:
                legacy_worker.power_control.stopthreadevent = 1
            except Exception:
                pass
        if serial_client is not None:
            try:
                serial_client.serial_close()
            except Exception:
                pass


__all__ = [
    "LegacyPowerChannel",
    "LegacyPowerTestRequest",
    "LegacyPowerTestResult",
    "prepare_legacy_power_test_request",
    "run_legacy_power_test",
]
