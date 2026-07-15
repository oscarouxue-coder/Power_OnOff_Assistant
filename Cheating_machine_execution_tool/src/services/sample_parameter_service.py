from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable, Optional

from src.config import DEFAULT_LOG_DIR
from src.core import SerialSessionManager
from src.core.parameter_session import ParameterSession
from src.models import (
    STANDARD_PARAMETER_DEFINITIONS,
    ParameterTablePreflight,
    SampleParameterItemResult,
    SampleParameterRecord,
    SampleParameterTarget,
    SampleParameterWriteRequest,
    SerialSettings,
)


FACTORY_USERNAME = "root"
FACTORY_PASSWORD = "t*hEQ#BHu7z%3n"
FACTORY_REBOOT_WAIT_SECONDS = 100
PARAMETER_MAX_PARALLEL = 8
PARAMETER_WRITE_RETRIES = 3
_MAC_PATTERN = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")
_DANGEROUS_VALUE_CHARS = frozenset({'\r', '\n', '"'})

Output = Callable[[str], None]
SessionReady = Callable[[str, object, Path], None]
# 切到 telnet 路径时，run_*_sample_parameter_write 接受一个工厂方法返回已登录的 ParameterSession；
# 保留 None 以兼容既有的串口路径与旧单元测试。
# 用 Optional[...] 因为 Python 3.9 不支持在 typing 别名上用 PEP 604 "|"。
TelnetSessionFactory = Optional[Callable[["SampleParameterWriteRequest"], ParameterSession]]


def preflight_parameter_targets(
    records: Iterable[SampleParameterRecord],
    channel_ports: Iterable[tuple[str, str]],
) -> ParameterTablePreflight:
    errors: list[str] = []
    warnings: list[str] = []
    channels: dict[str, tuple[str, str]] = {}
    ports: dict[str, str] = {}
    for vlan, port in channel_ports:
        clean_vlan, clean_port = vlan.strip(), port.strip().upper()
        key = clean_vlan.casefold()
        if not clean_vlan:
            errors.append("存在未配置 VLAN 的已勾选通道。")
            continue
        if key in channels:
            errors.append(f"已勾选通道存在重复 VLAN：{clean_vlan}。")
            continue
        if not clean_port:
            errors.append(f"无法从 VLAN {clean_vlan} 映射串口，请检查 VLAN 命名。")
            continue
        if clean_port in ports:
            errors.append(f"VLAN {clean_vlan} 与 {ports[clean_port]} 使用同一串口 {clean_port}。")
            continue
        channels[key] = (clean_vlan, clean_port)
        ports[clean_port] = clean_vlan
    records_by_vlan: dict[str, SampleParameterRecord] = {}
    for record in records:
        clean_vlan = record.vlan.strip()
        key = clean_vlan.casefold()
        if not clean_vlan:
            errors.append(f"参数表第 {record.source_row} 行 VLAN 为空。")
            continue
        if key in records_by_vlan:
            errors.append(f"参数表 VLAN 重复：{clean_vlan}（第 {record.source_row} 行）。")
            continue
        records_by_vlan[key] = record
    targets: list[SampleParameterTarget] = []
    for key, (vlan, port) in channels.items():
        record = records_by_vlan.get(key)
        if record is None:
            errors.append(f"参数表缺少已勾选通道 {vlan} 的记录。")
            continue
        errors.extend(_record_errors(vlan, record))
        targets.append(SampleParameterTarget(vlan=vlan, serial_port=port, record=record))
    for key, record in records_by_vlan.items():
        if key not in channels:
            warnings.append(f"参数表第 {record.source_row} 行 VLAN {record.vlan} 未勾选，本次跳过。")
    if not channels:
        errors.append("请先在主界面勾选至少一个通道并配置 VLAN。")
    return ParameterTablePreflight(tuple(targets), tuple(errors), tuple(warnings))


def run_parallel_sample_parameter_writes(
    requests: Iterable[SampleParameterWriteRequest],
    session_manager: SerialSessionManager,
    parallel_count: int = 2,
    on_output: Output | None = None,
    on_session_ready: SessionReady | None = None,
    cancel_event: threading.Event | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> list[SampleParameterItemResult]:
    items = list(requests)
    if not items:
        return []
    workers = max(1, min(int(parallel_count), PARAMETER_MAX_PARALLEL, len(items)))
    cancel = cancel_event or threading.Event()
    indexed_results: dict[int, SampleParameterItemResult] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sample-parameter") as executor:
        futures = {
            executor.submit(
                run_single_sample_parameter_write,
                request,
                session_manager,
                on_output,
                on_session_ready,
                cancel,
                sleep_fn,
            ): index
            for index, request in enumerate(items)
        }
        for future in as_completed(futures):
            index = futures[future]
            request = items[index]
            try:
                indexed_results[index] = future.result()
            except Exception as exc:
                indexed_results[index] = SampleParameterItemResult(request, False, f"{request.vlan} 写参流程异常：{exc}")
    return [indexed_results[index] for index in range(len(items))]


def run_single_sample_parameter_write(
    request: SampleParameterWriteRequest,
    session_manager: SerialSessionManager,
    on_output: Output | None = None,
    on_session_ready: SessionReady | None = None,
    cancel_event: threading.Event | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    telnet_session_factory: TelnetSessionFactory = None,
) -> SampleParameterItemResult:
    """按样机写一次批量参数。

    传输层选择：
    - `telnet_session_factory=None`：走既有串口路径（保持 8 项单元测试不变）。
    - `telnet_session_factory!=None`：切片 5 由工厂提供一个已登录的 ParameterSession,
      service 层对其执行相同写入流程；session 生命周期由工厂自身管理(外层 finally 不再 release)。

    切片 1 阶段 telnet_session_factory 形参已就绪但默认走串口路径，
    即"新增抽象，零行为变更"。
    """
    emit = on_output or (lambda _message: None)
    cancel = cancel_event or threading.Event()
    owner = f"sample-parameter:{request.vlan.casefold()}"
    if telnet_session_factory is not None:
        session = telnet_session_factory(request)
        emit(f"{request.vlan} 写参：使用 Telnet 会话（绑定源 IP {getattr(request, 'bind_ip', '')}）。")
        if on_session_ready:
            on_session_ready(request.vlan, session, DEFAULT_LOG_DIR / f"sample_parameter_{request.vlan}.log")
        return run_parameter_write_pipeline(request, session, cancel, sleep_fn, emit)
    if cancel.is_set():
        return SampleParameterItemResult(request, False, f"{request.vlan} 写参已取消。", cancelled=True)
    log_path = DEFAULT_LOG_DIR / f"sample_parameter_{request.vlan}_{request.serial_port}.log"
    session = session_manager.acquire_control(owner, SerialSettings(port=request.serial_port), log_path)
    if on_session_ready:
        on_session_ready(request.vlan, session, log_path)
    emit(f"{request.vlan} 写参：串口 {request.serial_port} 已打开。")
    try:
        return run_parameter_write_pipeline(request, session, cancel, sleep_fn, emit)
    finally:
        # 串口路径专属: 始终释放 session。
        session_manager.release(owner, request.serial_port)


def run_parameter_write_pipeline(
    request: SampleParameterWriteRequest,
    session: ParameterSession,
    cancel: threading.Event,
    sleep_fn: Callable[[float], None],
    emit: Output,
) -> SampleParameterItemResult:
    """对已打开的 ParameterSession 执行一次写样机参数的完整流水线。

    流水线:
        首次登录 → ppctl clear → FACTORY_MODE=1 → firstboot -yr
        → 等 100 秒 → 工厂模式二次登录 → 15 项 ppctl set/get
        → FACTORY_MODE=0 + firstboot -yr（在 finally 中执行）

    不关心 session 是 PySerial 还是 Telnet；会话生命周期由调用方管理。
    """
    entered_factory = False
    try:
        if cancel.is_set():
            return SampleParameterItemResult(request, False, f"{request.vlan} 写参已取消。", cancelled=True)
        if not _login(session, request.initial_username, request.initial_password, cancel, sleep_fn):
            return SampleParameterItemResult(request, False, f"{request.vlan} 写参失败：首次登录失败。")
        if cancel.is_set():
            return SampleParameterItemResult(request, False, f"{request.vlan} 写参已取消。", cancelled=True)
        _send_stage(session, "ppctl clear", False, emit, request.vlan)
        _send_stage(session, "ppctl set FACTORY_MODE=1", False, emit, request.vlan)
        entered_factory = True
        _send_stage(session, "firstboot -yr", False, emit, request.vlan)
        emit(f"{request.vlan} 写参：已触发进入工厂模式重启，等待 {FACTORY_REBOOT_WAIT_SECONDS} 秒。")
        if not _wait_cancellable(FACTORY_REBOOT_WAIT_SECONDS, cancel, sleep_fn):
            return SampleParameterItemResult(request, False, f"{request.vlan} 写参已取消，准备执行工厂模式清理。", cancelled=True)
        if not _login(session, FACTORY_USERNAME, FACTORY_PASSWORD, cancel, sleep_fn):
            return SampleParameterItemResult(request, False, f"{request.vlan} 写参失败：工厂模式二次登录失败。")
        written = 0
        failed_labels: list[str] = []
        for definition in STANDARD_PARAMETER_DEFINITIONS:
            if cancel.is_set():
                return SampleParameterItemResult(
                    request, False,
                    f"{request.vlan} 写参已取消，准备执行工厂模式清理。",
                    written, tuple(failed_labels), True,
                )
            value = str(request.values.get(definition.column, ""))
            if _write_and_verify(session, request.vlan, definition.label, definition.command, value, definition.sensitive, cancel, emit, sleep_fn):
                written += 1
            else:
                failed_labels.append(definition.label)
        if failed_labels:
            return SampleParameterItemResult(
                request,
                False,
                f"{request.vlan} 写参完成但 {len(failed_labels)} 项校验失败：{'、'.join(failed_labels)}。",
                written,
                tuple(failed_labels),
            )
        return SampleParameterItemResult(request, True, f"{request.vlan} 写参完成，{written} 项均已读回校验。", written)
    except Exception as exc:
        return SampleParameterItemResult(request, False, f"{request.vlan} 写参异常：{exc}", 0, (), cancel.is_set())
    finally:
        if entered_factory:
            try:
                _send_stage(session, "ppctl set FACTORY_MODE=0", False, emit, request.vlan)
                _send_stage(session, "firstboot -yr", False, emit, request.vlan)
                emit(f"{request.vlan} 写参：已下发退出工厂模式与重启命令。")
            except Exception as exc:
                emit(f"{request.vlan} 写参：退出工厂模式清理失败：{exc}")
                emit(f"{request.vlan} 写参：请人工确认设备已退出工厂模式。")


def _record_errors(vlan: str, record: SampleParameterRecord) -> list[str]:
    errors: list[str] = []
    mac = str(record.values.get("MAC", "")).strip()
    if not _MAC_PATTERN.fullmatch(mac):
        errors.append(f"{vlan} 的 MAC 格式错误，应为 XX:XX:XX:XX:XX:XX。")
    for definition in STANDARD_PARAMETER_DEFINITIONS:
        value = str(record.values.get(definition.column, ""))
        if not value.strip():
            errors.append(f"{vlan} 缺少必填参数：{definition.column}。")
        elif any(char in value for char in _DANGEROUS_VALUE_CHARS):
            errors.append(f"{vlan} 参数 {definition.column} 含不允许的引号或换行。")
    return errors


def _login(session, username: str, password: str, cancel: threading.Event, sleep_fn: Callable[[float], None]) -> bool:
    if not username or not password:
        return False
    for _attempt in range(3):
        if cancel.is_set():
            return False
        cursor = session.cursor()
        session.write(b"\r")
        prompt = session.wait_for_any(("#", ">", "login:", "username:"), 8, cursor)
        if prompt in ("#", ">"):
            return True
        username_cursor = session.cursor()
        session.send_line(username, sensitive=True)
        password_prompt = session.wait_for_any(("password:", "passvord:"), 8, username_cursor)
        if password_prompt not in ("password:", "passvord:"):
            continue
        result_cursor = session.cursor()
        session.send_line(password, sensitive=True)
        result = session.wait_for_any(("#", ">", "incorrect", "failed"), 15, result_cursor)
        if result in ("#", ">"):
            return True
        _wait_cancellable(1, cancel, sleep_fn)
    return False


def _write_and_verify(session, vlan: str, label: str, command_prefix: str, value: str, sensitive: bool, cancel: threading.Event, emit: Output, sleep_fn: Callable[[float], None]) -> bool:
    variable = command_prefix.rstrip("=").rsplit(" ", 1)[-1]
    read_command = f"ppctl get {variable}"
    expected = _normalize_mac(value) if label == "MAC" else value
    for attempt in range(1, PARAMETER_WRITE_RETRIES + 1):
        if cancel.is_set():
            return False
        command = f'{command_prefix}"{value}"'
        emit(f"{vlan} TX {command_prefix}{'[敏感内容已隐藏]' if sensitive else repr(value)}（{label}，第 {attempt}/{PARAMETER_WRITE_RETRIES} 次）")
        session.send_line(command, sensitive=sensitive)
        if not _wait_cancellable(1, cancel, sleep_fn):
            return False
        cursor = session.cursor()
        emit(f"{vlan} TX {read_command}（读取 {label}）")
        session.send_line(read_command)
        marker = session.wait_for_any((f"{variable}=", f"{variable} =", f"{variable}:"), 4, cursor)
        if marker is None:
            emit(f"{vlan} {label} 第 {attempt}/{PARAMETER_WRITE_RETRIES} 次读回无响应。")
            continue
        actual = _extract_readback(session.peek_since(cursor), variable)
        actual_for_compare = _normalize_mac(actual) if label == "MAC" else actual
        if actual_for_compare == expected:
            emit(f"{vlan} {label} 写入并读回校验成功（第 {attempt} 次）。")
            return True
        emit(f"{vlan} {label} 第 {attempt}/{PARAMETER_WRITE_RETRIES} 次读回不一致。")
    return False


def _extract_readback(output: str, variable: str) -> str:
    pattern = re.compile(rf"^{re.escape(variable)}\s*(?:=|:)\s*(.*)$", re.IGNORECASE)
    for line in output.splitlines():
        match = pattern.match(line.strip())
        if match:
            return match.group(1).strip().strip('"')
    return ""


def _normalize_mac(value: str) -> str:
    compact = "".join(char for char in value.upper() if char.isalnum())
    if len(compact) == 12:
        return ":".join(compact[index:index + 2] for index in range(0, 12, 2))
    return value.strip()


def _send_stage(session, command: str, sensitive: bool, emit: Output, vlan: str) -> None:
    emit(f"{vlan} TX {command}")
    session.send_line(command, sensitive=sensitive)


def _wait_cancellable(seconds: float, cancel: threading.Event, sleep_fn: Callable[[float], None]) -> bool:
    remaining = float(seconds)
    while remaining > 0:
        if cancel.is_set():
            return False
        interval = min(1.0, remaining)
        sleep_fn(interval)
        remaining -= interval
    return not cancel.is_set()
