"""按测试项配置锁源登录 Telnet，再读取样机版本信息。"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable

from line_check_assistant.test_item_config_store import ProjectInfoSettings, TelnetSettings
from src.core.telnet_transport import TelnetSession
from src.services.telnet_post_login_service import run_telnet_post_login


Output = Callable[[str], None]

DEVICEINFO_COMMAND = "cat /etc/config/deviceinfo"
PROC_VERSION_COMMAND = "cat /proc/version"
COMMAND_TIMEOUT_SECONDS = 10.0
COMMAND_STABLE_SECONDS = 0.3
LOGIN_INTER_STEP_SLEEP_SECONDS = 0.3

_OPTION_PATTERN = re.compile(
    r"^\s*option\s+(?P<key>[A-Za-z0-9_]+)\s+(?P<value>.+?)\s*$",
    re.MULTILINE,
)
_COMPILE_TIME_PATTERN = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+\d{4}\b"
)


@dataclass(frozen=True)
class DeviceProjectInfoQueryRequest:
    """一次版本查询需要的锁源连接和登录参数。"""

    bind_ip: str
    device_host: str
    telnet: TelnetSettings


@dataclass(frozen=True)
class DeviceProjectInfo:
    software_version: str
    internal_software_version: str
    onu_compile_time: str


def project_info_mismatches(
    expected: ProjectInfoSettings, actual: DeviceProjectInfo
) -> tuple[str, ...]:
    """返回样机版本与项目基准值不一致的字段详情，比较前去除首尾空白。"""
    fields = (
        ("软件版本", expected.software_version, actual.software_version),
        (
            "内部软件版本",
            expected.internal_software_version,
            actual.internal_software_version,
        ),
        ("ONU 软件编译时间", expected.onu_compile_time, actual.onu_compile_time),
    )
    return tuple(
        f"{label}：期望 {expected_value.strip()}，实际 {actual_value.strip()}"
        for label, expected_value, actual_value in fields
        if expected_value.strip() != actual_value.strip()
    )


def _option_value(deviceinfo_output: str, key: str) -> str:
    for match in _OPTION_PATTERN.finditer(deviceinfo_output):
        if match.group("key") != key:
            continue
        value = match.group("value").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            return value
    raise RuntimeError(f"未在 /etc/config/deviceinfo 中找到 option {key}")


def _compile_time(proc_version_output: str) -> str:
    match = _COMPILE_TIME_PATTERN.search(proc_version_output)
    if match is None:
        raise RuntimeError("未在 /proc/version 中识别出 ONU 软件编译时间")
    return match.group(0)


def _login(session: TelnetSession, telnet: TelnetSettings, emit: Output) -> None:
    """按测试项配置的现有 Telnet 提示符完成登录。"""
    if not (telnet.input_user_flag or "").strip():
        raise RuntimeError("Telnet 用户名提示符为空，无法查询样机版本")
    if not (telnet.input_password_flag or "").strip():
        raise RuntimeError("Telnet 密码提示符为空，无法查询样机版本")
    if not (telnet.login_success_flag or "").strip():
        raise RuntimeError("Telnet 登录成功提示符为空，无法查询样机版本")

    cursor = session.cursor()
    session.write(b"\r", sensitive=False)
    if session.wait_for_any([telnet.input_user_flag], 15.0, cursor) is None:
        raise RuntimeError(f"登录超时：未收到用户名提示符 '{telnet.input_user_flag}'")
    cursor = session.cursor()
    session.send_line(telnet.user, sensitive=False)
    time.sleep(LOGIN_INTER_STEP_SLEEP_SECONDS)
    if session.wait_for_any([telnet.input_password_flag], 10.0, cursor) is None:
        raise RuntimeError(f"登录超时：未收到密码提示符 '{telnet.input_password_flag}'")
    cursor = session.cursor()
    session.send_line(telnet.password, sensitive=False)
    time.sleep(LOGIN_INTER_STEP_SLEEP_SECONDS)
    if session.wait_for_any([telnet.login_success_flag], 20.0, cursor) is None:
        raise RuntimeError(f"登录超时：未收到登录成功提示符 '{telnet.login_success_flag}'")
    emit("[项目信息] Telnet 登录成功。")
    run_telnet_post_login(
        session, telnet, lambda line: emit(f"[项目信息] {line}"), time.sleep
    )


def _run_read_only_command(
    session: TelnetSession, command: str, emit: Output
) -> str:
    cursor = session.cursor()
    session.send_line(command, sensitive=False)
    emit(f"[项目信息] 下发只读命令：{command}")
    deadline = time.monotonic() + COMMAND_TIMEOUT_SECONDS
    last_cursor = cursor
    last_data_at: float | None = None
    while time.monotonic() < deadline:
        current_cursor = session.cursor()
        if current_cursor > last_cursor:
            last_cursor = current_cursor
            last_data_at = time.monotonic()
        if last_data_at is not None and time.monotonic() - last_data_at >= COMMAND_STABLE_SECONDS:
            return session.peek_since(cursor)
        time.sleep(0.1)
    raise RuntimeError(f"命令执行超时：{command}（未收到稳定输出）")


def query_device_project_info(
    request: DeviceProjectInfoQueryRequest, emit: Output = lambda _line: None
) -> DeviceProjectInfo:
    """连接指定样机并读取两个 deviceinfo 字段及 /proc/version 编译时间。"""
    telnet = request.telnet
    emit(
        f"[项目信息] 连接样机 {request.device_host}:{int(telnet.port or 23)}，"
        f"锁定 PC 源 IP {request.bind_ip}。"
    )
    session = TelnetSession(
        bind_ip=request.bind_ip,
        device_host=request.device_host,
        device_port=int(telnet.port or 23),
        known_secrets=(telnet.password,),
    )
    try:
        _login(session, telnet, emit)
        deviceinfo_output = _run_read_only_command(
            session, DEVICEINFO_COMMAND, emit
        )
        proc_version_output = _run_read_only_command(
            session, PROC_VERSION_COMMAND, emit
        )
        result = DeviceProjectInfo(
            software_version=_option_value(deviceinfo_output, "software_version"),
            internal_software_version=_option_value(
                deviceinfo_output, "inner_sw_version"
            ),
            onu_compile_time=_compile_time(proc_version_output),
        )
        emit(
            "[项目信息] 查询成功："
            f"软件版本 {result.software_version}，"
            f"内部软件版本 {result.internal_software_version}，"
            f"ONU 软件编译时间 {result.onu_compile_time}。"
        )
        return result
    finally:
        session.close()


__all__ = [
    "DEVICEINFO_COMMAND",
    "PROC_VERSION_COMMAND",
    "DeviceProjectInfo",
    "DeviceProjectInfoQueryRequest",
    "project_info_mismatches",
    "query_device_project_info",
]
