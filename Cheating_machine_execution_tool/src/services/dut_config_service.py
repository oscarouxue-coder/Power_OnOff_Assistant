"""DUT 配置流程：准备网络、通过 UBUS 开启 Telnet，并验证 TCP 23 端口。"""
from __future__ import annotations

import ipaddress
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Callable, Iterable

from line_check_assistant.network_ops import prepare_network_for_sample
from src.core.bind_socket import wait_for_bindable_ip
from src.core.telnet_transport import probe_telnet_port
from src.core.ubus_enable_telnet import EnableTelnetResult, enable_telnet_via_ubus
from src.core.ubus_http_client import UbusHttpClient
from src.models.dut_config_models import DutTelnetEnableRequest, DutTelnetEnableResult


DEFAULT_DUT_PARALLEL_COUNT = 1
MAX_DUT_PARALLEL_COUNT = 8
UBUS_ENABLE_MAX_RETRIES = 3
UBUS_ENABLE_RETRY_DELAY_SECONDS = 2.0
BIND_READY_TIMEOUT_SECONDS = 15.0
TELNET_PROBE_ATTEMPTS = 3
TELNET_PROBE_TIMEOUT_SECONDS = 5.0
TELNET_PROBE_RETRY_DELAY_SECONDS = 1.0

OutputCallback = Callable[[str], None]
ItemCompleteCallback = Callable[[DutTelnetEnableResult], None]


class _DutConfigCancelled(RuntimeError):
    """内部取消信号；转换为操作员可见的 stopped 结果。"""


def clamp_dut_parallel_count(value: int | str | None) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_DUT_PARALLEL_COUNT
    return max(1, min(parsed, MAX_DUT_PARALLEL_COUNT))


def validate_dut_telnet_request(request: DutTelnetEnableRequest) -> tuple[str, ...]:
    """返回配置错误；空元组表示请求可执行。"""
    errors: list[str] = []
    label = request.channel or request.vlan or "未命名通道"
    if not request.vlan.strip():
        errors.append("通道未配置 VLAN")
    if not request.adapter_alias.strip():
        errors.append(f"{label} 未配置 VLAN 网卡")
    if not request.bind_ip.strip():
        errors.append(f"{label} 未配置 PC 静态 IP")
    if not request.device_host.strip():
        errors.append(f"{label} 未配置样机管理 IP")
    for field_label, value in (("PC 静态 IP", request.bind_ip), ("样机管理 IP", request.device_host)):
        if value.strip():
            try:
                ipaddress.ip_address(value.strip())
            except ValueError:
                errors.append(f"{label} {field_label} 格式无效：{value}")
    if request.bind_ip.strip() and request.bind_ip.strip() == request.device_host.strip():
        errors.append(f"{label} 的 PC 静态 IP 与样机管理 IP 相同")
    if not request.username.strip():
        errors.append("UBUS 登录账号为空")
    if not request.password:
        errors.append("UBUS 登录密码为空")
    try:
        ubus_port = int(request.ubus_port)
    except (TypeError, ValueError):
        errors.append(f"{label} UBUS 端口格式无效：{request.ubus_port}")
    else:
        if not 1 <= ubus_port <= 65535:
            errors.append(f"{label} UBUS 端口超出范围：{request.ubus_port}")
    return tuple(errors)


def run_single_dut_telnet_enable(
    request: DutTelnetEnableRequest,
    *,
    stop_event: threading.Event | None = None,
    on_output: OutputCallback | None = None,
    network_prepare_fn: Callable = prepare_network_for_sample,
    bind_waiter: Callable[[str, float], bool] = wait_for_bindable_ip,
    client_factory: Callable[..., UbusHttpClient] = UbusHttpClient,
    enable_telnet_fn: Callable[..., EnableTelnetResult] = enable_telnet_via_ubus,
    probe_fn: Callable[..., None] = probe_telnet_port,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> DutTelnetEnableResult:
    """执行单台 DUT；所有异常收敛为结果，确保批量内其它 DUT 可继续。"""
    label = request.channel or request.vlan or request.device_host or "DUT"

    def emit(message: str) -> None:
        if on_output is not None:
            on_output(f"[DUT配置][{label}] {message}")

    def ensure_not_stopped() -> None:
        if stop_event is not None and stop_event.is_set():
            raise _DutConfigCancelled("用户已请求停止")

    def pause(seconds: float) -> None:
        ensure_not_stopped()
        if stop_event is not None and sleep_fn is time.sleep:
            if stop_event.wait(max(0.0, float(seconds))):
                raise _DutConfigCancelled("用户已请求停止")
        else:
            sleep_fn(seconds)
        ensure_not_stopped()

    errors = validate_dut_telnet_request(request)
    if errors:
        message = "；".join(errors)
        emit(f"预检失败：{message}")
        return DutTelnetEnableResult(request, False, "preflight", message)

    try:
        ensure_not_stopped()
        emit(
            f"开始准备网络：网卡={request.adapter_alias}，"
            f"PC={request.bind_ip}/{request.subnet_mask or '255.255.255.0'}，"
            f"DUT={request.device_host}"
        )
        network_result = network_prepare_fn(
            request.adapter_alias,
            request.bind_ip,
            request.subnet_mask or "255.255.255.0",
            on_output=emit,
            sleep_fn=pause,
            reuse_if_ready=True,
        )
        if not network_result.ok:
            emit(f"网络准备失败：{network_result.message}")
            return DutTelnetEnableResult(request, False, "network", network_result.message)

        ensure_not_stopped()
        emit(f"等待源 IP 可绑定：{request.bind_ip}，超时 {BIND_READY_TIMEOUT_SECONDS:g} 秒")
        if not bind_waiter(request.bind_ip, BIND_READY_TIMEOUT_SECONDS):
            message = f"网络准备后源 IP 仍不可绑定：{request.bind_ip}"
            emit(f"失败：{message}")
            return DutTelnetEnableResult(request, False, "bind", message)

        enable_result: EnableTelnetResult | None = None
        last_error: Exception | None = None
        for attempt in range(1, UBUS_ENABLE_MAX_RETRIES + 2):
            ensure_not_stopped()
            if attempt > 1:
                retry_index = attempt - 1
                emit(
                    f"UBUS 开启 Telnet 第 {retry_index}/{UBUS_ENABLE_MAX_RETRIES} 次重试，"
                    f"等待 {UBUS_ENABLE_RETRY_DELAY_SECONDS:g} 秒"
                )
                pause(UBUS_ENABLE_RETRY_DELAY_SECONDS)
            emit(
                f"准备 UBUS 登录：{request.bind_ip} -> "
                f"{request.device_host}:{request.ubus_port}"
            )
            client = client_factory(request.bind_ip, request.device_host, ubus_port=request.ubus_port)
            try:
                enable_result = enable_telnet_fn(
                    client,
                    request.username,
                    request.password,
                    on_log=lambda event: emit(f"UBUS: {event.message}"),
                    sleep_fn=pause,
                )
                last_error = None
                break
            except _DutConfigCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - 单台错误需记录并按策略重试
                last_error = exc
                emit(f"UBUS 开启 Telnet 失败：{exc}")
            finally:
                client.close()

        if enable_result is None:
            message = f"UBUS 开启 Telnet 重试耗尽：{last_error}"
            if last_error is not None and "access denied" in str(last_error).lower():
                message += "；请退出样机 Web 管理页面后重试"
            emit(f"失败：{message}")
            return DutTelnetEnableResult(request, False, "ubus", message)

        for attempt in range(1, TELNET_PROBE_ATTEMPTS + 1):
            ensure_not_stopped()
            emit(
                f"TX TCP Telnet 端口验证 {attempt}/{TELNET_PROBE_ATTEMPTS}："
                f"{request.bind_ip} -> {request.device_host}:23"
            )
            try:
                probe_fn(
                    request.bind_ip,
                    request.device_host,
                    device_port=23,
                    timeout=TELNET_PROBE_TIMEOUT_SECONDS,
                )
                message = (
                    f"Telnet 已开启并验证可用：{request.bind_ip} -> "
                    f"{request.device_host}:23（{enable_result.message}）"
                )
                emit(f"成功：{message}")
                return DutTelnetEnableResult(
                    request,
                    True,
                    "completed",
                    message,
                    action=enable_result.action,
                )
            except Exception as exc:  # noqa: BLE001 - 端口启动可能有短暂延迟
                if attempt >= TELNET_PROBE_ATTEMPTS:
                    message = f"UBUS 已成功，但 Telnet 23 端口验证失败：{exc}"
                    emit(f"失败：{message}")
                    return DutTelnetEnableResult(
                        request,
                        False,
                        "telnet_probe",
                        message,
                        action=enable_result.action,
                    )
                emit(f"Telnet 端口尚未就绪：{exc}，等待 {TELNET_PROBE_RETRY_DELAY_SECONDS:g} 秒后重试")
                pause(TELNET_PROBE_RETRY_DELAY_SECONDS)
    except _DutConfigCancelled:
        message = "用户已停止，未继续执行本台后续步骤"
        emit(f"跳过：{message}")
        return DutTelnetEnableResult(request, False, "stopped", message)
    except Exception as exc:  # noqa: BLE001 - 防止单台异常破坏整个批次
        message = f"DUT 配置异常：{exc}"
        emit(f"失败：{message}")
        return DutTelnetEnableResult(request, False, "exception", message)

    return DutTelnetEnableResult(request, False, "exception", "DUT 配置未产生结果")


def run_dut_telnet_enable_batch(
    requests: Iterable[DutTelnetEnableRequest],
    *,
    max_workers: int = DEFAULT_DUT_PARALLEL_COUNT,
    stop_event: threading.Event | None = None,
    on_output: OutputCallback | None = None,
    on_item_complete: ItemCompleteCallback | None = None,
    single_runner: Callable[..., DutTelnetEnableResult] = run_single_dut_telnet_enable,
) -> list[DutTelnetEnableResult]:
    """动态提交批量任务；停止后不再向线程池提交尚未开始的 DUT。"""
    items = list(requests)
    if not items:
        return []
    cancel = stop_event or threading.Event()
    workers = min(clamp_dut_parallel_count(max_workers), len(items))
    results_by_index: dict[int, DutTelnetEnableResult] = {}
    next_index = 0

    def stopped_result(request: DutTelnetEnableRequest) -> DutTelnetEnableResult:
        return DutTelnetEnableResult(
            request,
            False,
            "stopped",
            "用户已停止，未启动本台 DUT 配置",
        )

    def report(result: DutTelnetEnableResult) -> None:
        if on_item_complete is not None:
            on_item_complete(result)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dut-telnet") as executor:
        futures: dict[Future, int] = {}
        while next_index < len(items) and len(futures) < workers and not cancel.is_set():
            futures[executor.submit(
                single_runner,
                items[next_index],
                stop_event=cancel,
                on_output=on_output,
            )] = next_index
            next_index += 1

        while futures:
            completed, _pending = wait(tuple(futures), return_when=FIRST_COMPLETED)
            for future in completed:
                index = futures.pop(future)
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001 - 自定义 runner 也不能破坏批次
                    result = DutTelnetEnableResult(
                        items[index], False, "exception", f"DUT 配置异常：{exc}"
                    )
                results_by_index[index] = result
                report(result)
                if next_index < len(items) and not cancel.is_set():
                    futures[executor.submit(
                        single_runner,
                        items[next_index],
                        stop_event=cancel,
                        on_output=on_output,
                    )] = next_index
                    next_index += 1

    while next_index < len(items):
        result = stopped_result(items[next_index])
        results_by_index[next_index] = result
        report(result)
        next_index += 1

    return [results_by_index[index] for index in range(len(items))]


__all__ = [
    "DEFAULT_DUT_PARALLEL_COUNT",
    "MAX_DUT_PARALLEL_COUNT",
    "clamp_dut_parallel_count",
    "run_dut_telnet_enable_batch",
    "run_single_dut_telnet_enable",
    "validate_dut_telnet_request",
]
