"""「全流程执行 → 测试项配置」子任务的执行 service。

背景：
- 主界面「检查并执行测试」按钮触发的全流程管道中,第 6 个子任务「测试项配置」按
  ``Auto_power_on_off_tool/config/test_project_config.ini`` 的 ``[order]`` 段下发命令
  并匹配读回结果。
- 本模块负责：单台样机 → 准备网络 → TelnetSession 登录 → 顺序执行 ``[order]`` 每条命令
  → per-command ``retry_times`` 次重试（间隔来自 ``config.ini [other_config]``）
  → 写 per-channel 结果文件 → 返回汇总。
- 不包含：程控电源上下电（由子任务 1 负责）、test_number 循环（本轮 v1 不实现）、
  WiFi 验证（本轮 v1 不实现）、多通道并行（本轮 v1 串行,与「写样机参数」默认并行 1 一致）。

关键设计：
- 复用 ``src/core/telnet_transport.py:TelnetSession`` 的协议（cursor / send_line / wait_for_any /
  peek_since），与「写样机参数」telnet 路径同款绑定源 IP。
- 复用 ``line_check_assistant/network_ops.py:prepare_network_for_sample`` 启用网卡 + 切静态 IP。
- 复用 ``src/core/fuzzy_match_runner.py:match_expected`` per-segment 匹配
  （移植自老工具 ``common/fuzzy_match.py``，per-segment ``!A&&B`` 语义,AGENTS 硬规则不改老工具）。
- 结果文件路径：``Cheating_machine_execution_tool/test_results/device_{section}_command_results_{YYYYMMDD_HHMMSS}.log``,
  落盘每条命令的「TX / 读回 / fuzzy 匹配结果 / 阶段」时间戳行,与老工具 ``powe_on_off_telnet.py:241`` 同款约定。

不变量（AGENTS §1.3 / §1.4）：
- ``TelnetSession`` 按 VLAN ``bind_ip`` 锁源（``source_address=(bind_ip, 0)``）,不绑直接抛错。
- ``0.0.0.0`` 不出现在 telnet / tftp 路径。
- 升级 / 重启 / 恢复出厂 / 批量写参 / 测试项执行 均保留主执行日志 + 关键阶段记录。
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from line_check_assistant.config_store import ChannelConfig
from line_check_assistant.network_ops import (
    prepare_network_for_sample,
)
from line_check_assistant.test_item_config_store import (
    ExpectedSegment,
    OrderConfig,
    OrderItem,
    TelnetSettings,
)
from src.core.fuzzy_match_runner import match_expected as _match_expected
from src.core.telnet_transport import TelnetSession


# 单条命令读回的「稳定时间」：连续 stable_seconds 秒无新数据即认为命令回显完成。
READ_STABLE_SECONDS = 1.0
# 单条命令读回总超时（覆盖典型命令回显 + 多次重试间隔）。
READ_MAX_SECONDS = 8.0
# 登录阶段：等待 input_user_flag / input_password_flag / login_success_flag 的超时（秒）。
LOGIN_USER_PROMPT_TIMEOUT_SECONDS = 15.0
LOGIN_PASSWORD_PROMPT_TIMEOUT_SECONDS = 10.0
LOGIN_SUCCESS_TIMEOUT_SECONDS = 20.0
# 登录阶段各步之间的固定 sleep，给样机回显缓冲（与老工具 telnet_client.py:155 同款）。
LOGIN_INTER_STEP_SLEEP_SECONDS = 0.5

# per-channel 结果文件存放目录（用户决策：与老工具 test_results/ 分离）。
TEST_RESULTS_DIRNAME = "test_results"
TEST_RESULTS_DIR = Path(__file__).resolve().parents[2] / TEST_RESULTS_DIRNAME

Output = Callable[[str], None]


@dataclass(frozen=True)
class TestItemRunRequest:
    channel: ChannelConfig
    order: OrderConfig
    telnet: TelnetSettings
    # 重试间隔（秒）:来自 config.ini [other_config],缺省 60。
    retry_interval_seconds: int
    # per-channel 结果文件路径（由 caller 预生成,避免多线程时间戳竞争）。
    log_path: Path
    # 选填:自定义睡眠函数（测试时 mock 用,避免真睡）。
    sleep_fn: Callable[[float], None] = time.sleep
    # 选填:自定义时间源（测试时 mock 用）。
    monotonic_fn: Callable[[], float] = time.monotonic


@dataclass(frozen=True)
class TestItemRunResult:
    channel_section: str
    total: int
    passed: int
    failed: int
    log_path: Path


def _join_expected(segments: Iterable[ExpectedSegment]) -> str:
    """与 ``test_item_config_store._join_expected`` 同款,内联避免跨包 import。"""
    parts: List[str] = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        parts.append(f"!{text}" if seg.negate else text)
    return "&&".join(parts)


def _read_until_stable(
    session: TelnetSession,
    cursor: int,
    *,
    stable_seconds: float = READ_STABLE_SECONDS,
    max_seconds: float = READ_MAX_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> str:
    """从 ``cursor`` 起读取 session,直到「连续 stable_seconds 秒无新数据」或「总耗时超 max_seconds」。

    返回:从 cursor 到当前的「新增」回显文本（不含 cursor 之前的字节）。
    """
    deadline = monotonic_fn() + max_seconds
    last_data_at = monotonic_fn()
    while monotonic_fn() < deadline:
        new_cursor = session.cursor()
        if new_cursor > cursor:
            last_data_at = monotonic_fn()
        if monotonic_fn() - last_data_at >= stable_seconds:
            break
        sleep_fn(0.1)
    return session.peek_since(cursor)


def _login(
    session: TelnetSession,
    telnet: TelnetSettings,
    emit: Output,
    sleep_fn: Callable[[float], None],
) -> None:
    """按 ``TelnetSettings`` 字段完成 telnet 登录。

    时序:先发 ``\\r`` 触发样机重发 banner → 等 input_user_flag → 发 user →
    等 input_password_flag → 发 password → 等 login_success_flag。
    任一阶段超时抛 ``RuntimeError``,由 worker 标记「登录失败」并停止该台。

    与 ``sample_parameter_service._login`` 同款约定:登录首步先发 ``\\r`` 触发 prompt,
    避免 cursor 落在 banner 中段后 wait_for_any 看不到历史 prompt。
    """
    # 触发样机重发 banner(若已发,则此 CR 无副作用,只是再按一次回车)
    cursor = session.cursor()
    session.write(b"\r", sensitive=False)
    flag = session.wait_for_any(
        [telnet.input_user_flag],
        timeout_seconds=LOGIN_USER_PROMPT_TIMEOUT_SECONDS,
        cursor=cursor,
    )
    if flag is None:
        raise RuntimeError(
            f"登录超时：未收到用户名提示符 '{telnet.input_user_flag}' "
            f"({LOGIN_USER_PROMPT_TIMEOUT_SECONDS}s 内)"
        )
    # cursor 在 send_line 之前取(老工具 / sample_parameter_service._login 同款约定):
    # wait_for_any 搜索 [cursor, end) 的新数据,send_line 后样机的 prompt
    # 响应正好落在该区间;若在 send_line 之后取 cursor,cursor 已在 end,无新数据可看。
    cursor = session.cursor()
    session.send_line(telnet.user, sensitive=False)
    sleep_fn(LOGIN_INTER_STEP_SLEEP_SECONDS)
    flag = session.wait_for_any(
        [telnet.input_password_flag],
        timeout_seconds=LOGIN_PASSWORD_PROMPT_TIMEOUT_SECONDS,
        cursor=cursor,
    )
    if flag is None:
        raise RuntimeError(
            f"登录超时：未收到密码提示符 '{telnet.input_password_flag}' "
            f"({LOGIN_PASSWORD_PROMPT_TIMEOUT_SECONDS}s 内)"
        )
    cursor = session.cursor()
    session.send_line(telnet.password, sensitive=False)
    sleep_fn(LOGIN_INTER_STEP_SLEEP_SECONDS)
    flag = session.wait_for_any(
        [telnet.login_success_flag],
        timeout_seconds=LOGIN_SUCCESS_TIMEOUT_SECONDS,
        cursor=cursor,
    )
    if flag is None:
        raise RuntimeError(
            f"登录超时：未收到登录成功标志 '{telnet.login_success_flag}' "
            f"({LOGIN_SUCCESS_TIMEOUT_SECONDS}s 内)"
        )
    emit(f"telnet 登录成功（flag={flag}）")


def _run_one_command(
    session: TelnetSession,
    item: OrderItem,
    expected_str: str,
    retry_times: int,
    retry_interval_seconds: int,
    index: int,
    total: int,
    emit: Output,
    log_handle,
    sleep_fn: Callable[[float], None],
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> bool:
    """单条命令:发送 → 读回 → fuzzy 匹配 → 失败重试。

    返回:True=匹配成功,False=全部重试后仍失败。
    """
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
    log_handle.write(
        f"[{timestamp}] === [{index}/{total}] 命令: {item.command} | 期望: {expected_str or '(无)'} "
        f"| 重试 {retry_times} 次 ===\n"
    )
    log_handle.flush()
    if expected_str:
        emit(f"[{index}/{total}] {item.command} | 期望: {expected_str}")
    else:
        emit(f"[{index}/{total}] {item.command} | 期望: (无)")

    actual_attempts = max(1, int(retry_times))
    for attempt in range(1, actual_attempts + 1):
        cursor = session.cursor()
        session.send_line(item.command, sensitive=False)
        result = _read_until_stable(
            session,
            cursor,
            sleep_fn=sleep_fn,
            monotonic_fn=monotonic_fn,
        )
        if not expected_str:
            # 无期望 → 默认通过,主日志明确输出
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
            log_handle.write(f"[{ts}] 尝试 {attempt}/{actual_attempts}: 无期望,默认通过\n")
            log_handle.flush()
            emit(f"  ✓ 尝试 {attempt}/{actual_attempts} 无期望,默认通过")
            return True
        matched = _match_expected(result, expected_str)
        if matched:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
            log_handle.write(
                f"[{ts}] 尝试 {attempt}/{actual_attempts}: MATCH OK 期望: '{expected_str}'\n"
            )
            log_handle.flush()
            emit(f"  ✓ 尝试 {attempt}/{actual_attempts} 匹配成功")
            return True
        # 失败
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
        log_handle.write(
            f"[{ts}] 尝试 {attempt}/{actual_attempts}: MATCH FAIL 期望: '{expected_str}'\n"
        )
        log_handle.flush()
        if attempt < actual_attempts:
            emit(
                f"  ✗ 尝试 {attempt}/{actual_attempts} 匹配失败，{retry_interval_seconds}s 后重试"
            )
            sleep_fn(float(retry_interval_seconds))
        else:
            emit(f"  ✗ 尝试 {attempt}/{actual_attempts} 匹配失败（已用尽 {actual_attempts} 次）")
    return False


def _build_log_path(channel: ChannelConfig, monotonic_fn: Callable[[], float] = time.monotonic) -> Path:
    """按 channel.section + 时间戳生成 per-channel 结果文件路径。

    文件名格式:``device_{section}_command_results_{YYYYMMDD_HHMMSS}.log``,
    与老工具 ``powe_on_off_telnet.py:241`` ``create_command_exec_result_file`` 同款约定。
    """
    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(monotonic_fn()))
    return TEST_RESULTS_DIR / channel.section / f"device_{channel.section}_command_results_{ts}.log"


def run_test_item_execution(
    req: TestItemRunRequest,
    emit: Output,
) -> TestItemRunResult:
    """单台样机的测试项执行主流程。

    流程:
      1. ``prepare_network_for_sample`` 启用网卡 + 切静态 IP。
      2. ``TelnetSession(bind_ip, device_host, port)`` 按 VLAN bind_ip 锁源。
      3. ``_login`` 按 ``TelnetSettings`` 字段登录。
      4. 顺序执行 ``req.order.items``:每条 ``_run_one_command`` →
         send_line → 读回 → fuzzy 匹配 → 失败 retry_times 次。
      5. ``finally`` 关闭 session,无论成败。
      6. 返回 ``TestItemRunResult`` (不抛,失败条目在 result.failed 中反映)。

    Raises:
        RuntimeError: 网络准备失败 / Telnet 连接失败 / 登录失败。
            (由编排器统一 stop pipeline 并报「子任务失败」。)
    """
    channel = req.channel
    emit(f"=== 开始测试项执行 {channel.section} ({channel.vlan_name or channel.adapter_alias}) ===")
    if not channel.enabled:
        raise RuntimeError(f"通道未启用: {channel.section}")

    bind_ip = (channel.network_card_ip or "").strip()
    device_host = (channel.device_manage_ip or "").strip()
    if not bind_ip:
        raise RuntimeError(f"{channel.section} 未配置 PC 静态 IP（network_card_ip）")
    if not device_host:
        raise RuntimeError(f"{channel.section} 未配置样机管理 IP（device_manage_ip）")

    # 1. 网络准备
    emit(f"准备网络 {channel.vlan_name or channel.adapter_alias}（{bind_ip}）")
    net_result = prepare_network_for_sample(
        channel.adapter_alias,
        bind_ip,
        channel.subnet_mask or "255.255.255.0",
        on_output=lambda line: emit(f"  {line}"),
        sleep_fn=req.sleep_fn,
        settle_seconds=2.0,
    )
    if not net_result.ok:
        raise RuntimeError(f"网络准备失败: {net_result.message}")
    emit(f"网络已就绪: {net_result.message}")

    # 2. 准备结果文件目录 + 打开句柄
    req.log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = req.log_path.open("a", encoding="utf-8", errors="replace")
    try:
        ts0 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
        log_handle.write(
            f"[{ts0}] === 通道 {channel.section} ({channel.vlan_name or channel.adapter_alias}) 开始测试 ===\n"
        )
        log_handle.flush()

        # 3. 打开 telnet session(自带 log_handle,会把 RX/TX/STATE 写进同一文件)
        try:
            session = TelnetSession(
                bind_ip=bind_ip,
                device_host=device_host,
                device_port=int(req.telnet.port or 23),
                log_path=req.log_path,
                connect_timeout=15.0,
            )
        except Exception as exc:
            raise RuntimeError(f"Telnet 连接失败 {device_host}:23 源 IP {bind_ip}: {exc}") from exc
        try:
            # 4. 登录
            _login(session, req.telnet, emit, req.sleep_fn)

            # 5. 顺序执行 [order] 命令
            total = len(req.order.items)
            passed = 0
            failed = 0
            if total == 0:
                emit("  [order] 段无命令,跳过执行")
            for index, item in enumerate(req.order.items, start=1):
                expected_str = _join_expected(item.expected_segments)
                ok = _run_one_command(
                    session=session,
                    item=item,
                    expected_str=expected_str,
                    retry_times=int(item.retry_times or 1),
                    retry_interval_seconds=int(req.retry_interval_seconds or 0),
                    index=index,
                    total=total,
                    emit=emit,
                    log_handle=log_handle,
                    sleep_fn=req.sleep_fn,
                    monotonic_fn=req.monotonic_fn,
                )
                if ok:
                    passed += 1
                else:
                    failed += 1

            ts1 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
            log_handle.write(
                f"[{ts1}] === 通道 {channel.section} 全部完成: {passed}/{total} 匹配 ===\n"
            )
            log_handle.flush()
            emit(f"=== 测试项执行 {channel.section} 完成: {passed}/{total} 匹配 ===")
            return TestItemRunResult(
                channel_section=channel.section,
                total=total,
                passed=passed,
                failed=failed,
                log_path=req.log_path,
            )
        finally:
            try:
                session.close()
            except Exception:
                pass
    finally:
        try:
            log_handle.close()
        except Exception:
            pass


def build_log_path(channel: ChannelConfig) -> Path:
    """公开 helper: 为给定通道生成时间戳结果文件路径(便于编排器预生成,避免并发竞争)。"""
    return _build_log_path(channel)


__all__ = [
    "LOGIN_INTER_STEP_SLEEP_SECONDS",
    "LOGIN_PASSWORD_PROMPT_TIMEOUT_SECONDS",
    "LOGIN_SUCCESS_TIMEOUT_SECONDS",
    "LOGIN_USER_PROMPT_TIMEOUT_SECONDS",
    "READ_MAX_SECONDS",
    "READ_STABLE_SECONDS",
    "TEST_RESULTS_DIR",
    "TestItemRunRequest",
    "TestItemRunResult",
    "build_log_path",
    "run_test_item_execution",
]
