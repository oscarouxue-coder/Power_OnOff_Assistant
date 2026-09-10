"""单次预备测试；不读写配置，也不进入正式测试的重试流程。"""
from __future__ import annotations

import copy
import ipaddress
import threading
import time
from typing import Callable

from line_check_assistant.network_ops import prepare_network_for_sample
from src.core.fuzzy_match_runner import match_expected
from src.core.telnet_transport import TelnetSession
from src.models.test_item_pretest_models import PretestRequest, PretestResult
from src.services.test_item_execution_service import _join_expected, _login

Output = Callable[[str, str], None]


class PretestCancelled(Exception):
    pass


def prepare_pretest_request(channels, order, telnet) -> PretestRequest:
    """冻结页面和通道快照；整批校验在任何网络操作之前完成。"""
    request = copy.deepcopy(PretestRequest(tuple(channels), order, telnet))
    if not request.channels:
        raise ValueError("请先在主界面勾选要执行预备测试的通道。")
    if not request.order.items:
        raise ValueError("当前测试项页没有有效命令。")
    for index, item in enumerate(request.order.items, 1):
        if not item.command.strip() or "\n" in item.command or "\r" in item.command:
            raise ValueError(f"第 {index} 条命令为空或包含换行，请修正后执行。")
    for channel in request.channels:
        if not channel.enabled or not channel.adapter_alias.strip():
            raise ValueError(f"{channel.section} 未启用或未配置网卡。")
        try:
            source = ipaddress.IPv4Address(channel.network_card_ip)
            target = ipaddress.IPv4Address(channel.device_manage_ip)
            ipaddress.IPv4Network(f"{source}/{channel.subnet_mask}", strict=False)
            if source == target or source.is_unspecified or target.is_unspecified:
                raise ValueError("源地址与目标地址不能相同或为空地址")
        except ValueError as exc:
            raise ValueError(f"{channel.section} 的源 IP、样机 IP 或掩码无效：{exc}") from exc
    if not 1 <= int(telnet.port) <= 65535 or int(telnet.timeout) <= 0:
        raise ValueError("Telnet 端口或超时无效。")
    if not all(str(value).strip() for value in (
        telnet.input_user_flag, telnet.input_password_flag, telnet.login_success_flag
    )):
        raise ValueError("请填写 Telnet 用户名、密码及登录成功提示符。")
    return request


class _CancellableSession:
    """复用现有登录过程，在等提示符和下发边界响应停止。"""
    def __init__(self, session, cancel):
        self.session, self.cancel = session, cancel

    def check(self):
        if self.cancel.is_set():
            raise PretestCancelled()
        error = getattr(self.session, "error", None)
        if error or getattr(self.session, "_closed", False):
            raise ConnectionError(f"Telnet 连接中断：{error or '远端关闭连接'}")

    def cursor(self):
        self.check()
        return self.session.cursor()

    def write(self, data, sensitive=False):
        self.check()
        self.session.write(data, sensitive=sensitive)

    def send_line(self, text, sensitive=False):
        self.check()
        self.session.send_line(text, sensitive=sensitive)

    def wait_for_any(self, markers, timeout_seconds, cursor):
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            self.check()
            found = self.session.wait_for_any(
                markers, min(0.2, max(0, deadline - time.monotonic())), cursor
            )
            if found is not None:
                self.check()
                return found
        return None


def _read_response(session, cursor, cancel, emit, timeout):
    deadline = time.monotonic() + timeout
    last_cursor, last_data_at = cursor, None
    try:
        while time.monotonic() < deadline:
            session.check()
            current = session.cursor()
            if current > last_cursor:
                last_cursor, last_data_at = current, time.monotonic()
            if last_data_at is not None and time.monotonic() - last_data_at >= 1.0:
                return session.session.peek_since(cursor)
            cancel.wait(0.1)
        raise TimeoutError("等待命令稳定回显超时")
    finally:
        output = session.session.peek_since(cursor)
        for line in output.splitlines():
            emit(f"回显 | {line}", "")
        if not output:
            emit("回显 | （未收到内容）", "")


def run_pretest(request: PretestRequest, cancel: threading.Event, emit: Output) -> PretestResult:
    request = prepare_pretest_request(request.channels, request.order, request.telnet)
    result = PretestResult(len(request.channels) * len(request.order.items))
    emit(f"[预备测试] 开始：{len(request.channels)} 个通道，每条命令仅执行一次，不重试。", "")

    def sleep(seconds):
        if cancel.wait(seconds):
            raise PretestCancelled()

    for channel in request.channels:
        if cancel.is_set():
            break
        prefix = f"[预备测试][{channel.section}/{channel.vlan_name or channel.adapter_alias}]"

        def channel_emit(text, tag=""):
            emit(f"{prefix} {text}", tag)

        raw = None
        try:
            channel_emit(f"准备网络：{channel.network_card_ip} → {channel.device_manage_ip}:{request.telnet.port}")
            net = prepare_network_for_sample(
                channel.adapter_alias, channel.network_card_ip, channel.subnet_mask,
                on_output=lambda line: channel_emit(line), sleep_fn=sleep,
                settle_seconds=2.0, reuse_if_ready=True,
            )
            if not net.ok:
                raise RuntimeError(f"网络准备失败：{net.message}")
            sleep(0)
            channel_emit("连接并登录 Telnet")
            raw = TelnetSession(
                bind_ip=channel.network_card_ip, device_host=channel.device_manage_ip,
                device_port=int(request.telnet.port), connect_timeout=float(request.telnet.timeout),
            )
            session = _CancellableSession(raw, cancel)
            _login(session, request.telnet, lambda line: channel_emit(line), sleep)
            session.check()
            for index, item in enumerate(request.order.items, 1):
                session.check()
                label = f"[{index}/{len(request.order.items)}]"
                expected = _join_expected(item.expected_segments)
                channel_emit(f"{label} 期望：{expected or '（未配置结果校验）'}")
                cursor = session.cursor()
                session.send_line(item.command, sensitive=False)
                result.executed += 1
                channel_emit(f"{label} 下发命令：{item.command}")
                try:
                    output = _read_response(session, cursor, cancel, channel_emit, float(request.telnet.timeout))
                except TimeoutError as exc:
                    result.failed += 1
                    channel_emit(f"{label} 失败：{exc}；不重试，继续下一条。", "error")
                    continue
                except PretestCancelled:
                    result.unchecked += 1
                    channel_emit(f"{label} 已下发但停止等待，结果未校验。", "warning")
                    raise
                except Exception:
                    result.failed += 1
                    raise
                if not expected:
                    result.unchecked += 1
                    channel_emit(f"{label} 已执行，未配置结果校验。", "warning")
                elif match_expected(output, expected):
                    result.passed += 1
                    channel_emit(f"{label} 成功：期望匹配通过。", "success")
                else:
                    result.failed += 1
                    channel_emit(f"{label} 失败：期望不匹配；不重试，继续下一条。", "error")
        except PretestCancelled:
            break
        except Exception as exc:
            result.device_errors += 1
            channel_emit(f"设备执行失败：{exc}；终止当前设备，跳过其剩余命令。", "error")
        finally:
            if raw is not None:
                try:
                    raw.close()
                except Exception as exc:
                    result.device_errors += 1
                    channel_emit(f"关闭连接失败：{exc}", "error")
    result.cancelled = cancel.is_set()
    tag = "error" if result.failed or result.device_errors else (
        "warning" if result.cancelled or result.unchecked or result.skipped else "success"
    )
    emit(
        f"[预备测试] {'已停止' if result.cancelled else '执行结束'}：共 {result.total} 条，"
        f"已下发 {result.executed}，成功 {result.passed}，失败 {result.failed}，"
        f"未校验 {result.unchecked}，未执行 {result.skipped}，设备异常 {result.device_errors}。", tag,
    )
    return result
