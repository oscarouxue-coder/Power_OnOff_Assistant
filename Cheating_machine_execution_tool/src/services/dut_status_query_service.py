"""DUT Telnet、语音、TR069与WiFi当前状态的只读批量查询流程。"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Union

from line_check_assistant.network_ops import prepare_network_for_sample
from src.core.bind_socket import wait_for_bindable_ip
from src.core.dut_ubus_config import query_tr069_status, query_voice_status
from src.core.dut_wifi_config import query_wifi_status
from src.core.ubus_enable_telnet import query_telnet_status
from src.core.ubus_http_client import UbusHttpClient
from src.models.dut_config_models import (
    DutAdvancedQueryResult,
    DutTelnetEnableRequest,
    DutTelnetStatus,
    DutTr069Settings,
    DutVoiceSettings,
    DutWifiSettings,
)

from .dut_config_service import (
    BIND_READY_TIMEOUT_SECONDS,
    DEFAULT_DUT_PARALLEL_COUNT,
    clamp_dut_parallel_count,
    validate_dut_telnet_request,
)


STATUS_QUERY_LOGIN_MAX_RETRIES = 3
STATUS_QUERY_LOGIN_RETRY_DELAY_SECONDS = 2.0

OutputCallback = Callable[[str], None]
ItemCompleteCallback = Callable[[DutAdvancedQueryResult], None]
StatusSettings = Union[DutTelnetStatus, DutVoiceSettings, DutTr069Settings, DutWifiSettings]


class _DutStatusQueryCancelled(RuntimeError):
    pass


def _validate_query(feature: str, line_index: str, ssid_index: str) -> tuple[str, ...]:
    if feature not in {"telnet", "voice", "tr069", "wifi_2g", "wifi_5g"}:
        return (f"不支持的DUT状态查询类型：{feature}",)
    if feature == "voice":
        try:
            value = int(line_index)
            if not 1 <= value <= 8:
                raise ValueError
        except (TypeError, ValueError):
            return (f"语音线路索引必须为 1–8：{line_index}",)
    if feature in {"wifi_2g", "wifi_5g"}:
        try:
            value = int(ssid_index)
            if not 1 <= value <= 8:
                raise ValueError
        except (TypeError, ValueError):
            return (f"WiFi SSID 索引必须为 1–8：{ssid_index}",)
    return ()


def run_single_dut_status_query(
    request: DutTelnetEnableRequest,
    feature: str,
    *,
    line_index: str = "1",
    ssid_index: str = "1",
    stop_event: threading.Event | None = None,
    on_output: OutputCallback | None = None,
    network_prepare_fn: Callable = prepare_network_for_sample,
    bind_waiter: Callable[[str, float], bool] = wait_for_bindable_ip,
    client_factory: Callable[..., UbusHttpClient] = UbusHttpClient,
    query_fn: Callable | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> DutAdvancedQueryResult:
    """查询单台DUT状态；异常收敛为结果，每次登录都释放设备session。"""
    label = request.channel or request.vlan or request.device_host or "DUT"
    feature_label = {
        "telnet": "Telnet查询", "voice": "语音查询", "tr069": "TR069查询",
        "wifi_2g": "2.4G WiFi查询", "wifi_5g": "5G WiFi查询",
    }.get(feature, feature)

    def emit(message: str) -> None:
        if on_output is not None:
            on_output(f"[DUT配置][{feature_label}][{label}] {message}")

    def ensure_not_stopped() -> None:
        if stop_event is not None and stop_event.is_set():
            raise _DutStatusQueryCancelled("用户已请求停止")

    def pause(seconds: float) -> None:
        ensure_not_stopped()
        if stop_event is not None and sleep_fn is time.sleep:
            if stop_event.wait(max(0.0, float(seconds))):
                raise _DutStatusQueryCancelled("用户已请求停止")
        else:
            sleep_fn(seconds)
        ensure_not_stopped()

    errors = (
        *validate_dut_telnet_request(request),
        *_validate_query(feature, line_index, ssid_index),
    )
    if errors:
        message = "；".join(errors)
        emit(f"预检失败：{message}")
        return DutAdvancedQueryResult(request, feature, False, "preflight", message)

    client: UbusHttpClient | None = None
    try:
        ensure_not_stopped()
        emit(
            f"开始准备网络：网卡={request.adapter_alias}，PC={request.bind_ip}/"
            f"{request.subnet_mask or '255.255.255.0'}，DUT={request.device_host}"
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
            return DutAdvancedQueryResult(
                request, feature, False, "network", network_result.message
            )

        ensure_not_stopped()
        emit(f"等待源 IP 可绑定：{request.bind_ip}，超时 {BIND_READY_TIMEOUT_SECONDS:g} 秒")
        if not bind_waiter(request.bind_ip, BIND_READY_TIMEOUT_SECONDS):
            message = f"网络准备后源 IP 仍不可绑定：{request.bind_ip}"
            emit(f"失败：{message}")
            return DutAdvancedQueryResult(request, feature, False, "bind", message)

        last_error: Exception | None = None
        for attempt in range(1, STATUS_QUERY_LOGIN_MAX_RETRIES + 2):
            session_id = ""
            ensure_not_stopped()
            if attempt > 1:
                emit(
                    f"UBUS 登录第 {attempt - 1}/{STATUS_QUERY_LOGIN_MAX_RETRIES} 次重试，"
                    f"等待 {STATUS_QUERY_LOGIN_RETRY_DELAY_SECONDS:g} 秒"
                )
                pause(STATUS_QUERY_LOGIN_RETRY_DELAY_SECONDS)
            client = client_factory(
                request.bind_ip, request.device_host, ubus_port=request.ubus_port
            )
            emit(
                f"TX UBUS session.login：{request.bind_ip} -> {request.device_host}:"
                f"{request.ubus_port}，username={request.username}，password={request.password}"
            )
            try:
                session_id = client.login(request.username, request.password)
                emit("UBUS 登录成功")
                if query_fn is not None:
                    if feature == "voice":
                        settings = query_fn(client, session_id, line_index, on_log=emit)
                    elif feature in {"wifi_2g", "wifi_5g"}:
                        band = "2.4G" if feature == "wifi_2g" else "5G"
                        settings = query_fn(
                            client, session_id, band, ssid_index, on_log=emit
                        )
                    else:
                        settings = query_fn(client, session_id, on_log=emit)
                elif feature == "telnet":
                    settings = query_telnet_status(
                        client,
                        session_id,
                        request.bind_ip,
                        request.device_host,
                        on_log=emit,
                    )
                elif feature == "voice":
                    settings = query_voice_status(
                        client, session_id, line_index, on_log=emit
                    )
                elif feature == "tr069":
                    settings = query_tr069_status(client, session_id, on_log=emit)
                else:
                    band = "2.4G" if feature == "wifi_2g" else "5G"
                    settings = query_wifi_status(
                        client,
                        session_id,
                        band,
                        ssid_index,
                        on_log=emit,
                        sleep_fn=pause,
                    )
                expected_type = {
                    "telnet": DutTelnetStatus,
                    "voice": DutVoiceSettings,
                    "tr069": DutTr069Settings,
                    "wifi_2g": DutWifiSettings,
                    "wifi_5g": DutWifiSettings,
                }[feature]
                if not isinstance(settings, expected_type):
                    raise TypeError(f"{feature_label}返回了不匹配的状态类型")
                message = f"{feature_label}成功"
                emit(f"成功：{message}")
                return DutAdvancedQueryResult(
                    request, feature, True, "completed", message, settings
                )
            except _DutStatusQueryCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - 登录和查询按既有策略整体重试
                last_error = exc
                emit(f"UBUS {feature_label}失败：{exc}")
            finally:
                if session_id:
                    emit(
                        "TX UBUS bbfdm.unauthenticated_operate "
                        "command=Device.X_SDMC_Login.logout()"
                    )
                    try:
                        client.logout(session_id)
                        emit("UBUS 会话已注销")
                    except Exception as exc:  # noqa: BLE001 - 注销失败不覆盖查询结果
                        emit(f"UBUS 会话注销失败（已继续关闭连接）：{exc}")
                client.close()
                client = None

        message = f"UBUS {feature_label}重试耗尽：{last_error}"
        if last_error is not None and "access denied" in str(last_error).lower():
            message += "；请退出样机 Web 管理页面后重试"
        emit(f"失败：{message}")
        return DutAdvancedQueryResult(request, feature, False, "query", message)
    except _DutStatusQueryCancelled:
        message = "用户已停止，未继续查询本台 DUT"
        emit(f"跳过：{message}")
        return DutAdvancedQueryResult(request, feature, False, "stopped", message)
    except Exception as exc:  # noqa: BLE001 - 单台异常不能破坏批次
        message = f"{feature_label}异常：{exc}"
        emit(f"失败：{message}")
        return DutAdvancedQueryResult(request, feature, False, "exception", message)
    finally:
        if client is not None:
            client.close()


def common_dut_status_settings(
    results: Iterable[DutAdvancedQueryResult],
) -> StatusSettings | None:
    """仅当所有目标成功且状态完全一致时返回可安全回填的配置。"""
    items = list(results)
    if not items or any(not item.ok or item.settings is None for item in items):
        return None
    first = items[0].settings
    return first if all(item.settings == first for item in items[1:]) else None


def run_dut_status_query_batch(
    requests: Iterable[DutTelnetEnableRequest],
    feature: str,
    *,
    line_index: str = "1",
    ssid_index: str = "1",
    max_workers: int = DEFAULT_DUT_PARALLEL_COUNT,
    stop_event: threading.Event | None = None,
    on_output: OutputCallback | None = None,
    on_item_complete: ItemCompleteCallback | None = None,
    single_runner: Callable[..., DutAdvancedQueryResult] = run_single_dut_status_query,
) -> list[DutAdvancedQueryResult]:
    """并行只读查询；停止后不再提交尚未开始的DUT。"""
    items = list(requests)
    if not items:
        return []
    cancel = stop_event or threading.Event()
    workers = min(clamp_dut_parallel_count(max_workers), len(items))
    results_by_index: dict[int, DutAdvancedQueryResult] = {}
    next_index = 0

    def report(result: DutAdvancedQueryResult) -> None:
        if on_item_complete is not None:
            on_item_complete(result)

    def stopped_result(request: DutTelnetEnableRequest) -> DutAdvancedQueryResult:
        return DutAdvancedQueryResult(
            request, feature, False, "stopped", f"用户已停止，未启动本台{feature}状态查询"
        )

    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix=f"dut-{feature}-query"
    ) as executor:
        futures: dict[Future, int] = {}
        while next_index < len(items) and len(futures) < workers and not cancel.is_set():
            futures[
                executor.submit(
                    single_runner,
                    items[next_index],
                    feature,
                    line_index=line_index,
                    ssid_index=ssid_index,
                    stop_event=cancel,
                    on_output=on_output,
                )
            ] = next_index
            next_index += 1
        while futures:
            completed, _pending = wait(tuple(futures), return_when=FIRST_COMPLETED)
            for future in completed:
                index = futures.pop(future)
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    result = DutAdvancedQueryResult(
                        items[index], feature, False, "exception", f"DUT状态查询异常：{exc}"
                    )
                results_by_index[index] = result
                report(result)
                if next_index < len(items) and not cancel.is_set():
                    futures[
                        executor.submit(
                            single_runner,
                            items[next_index],
                            feature,
                            line_index=line_index,
                            ssid_index=ssid_index,
                            stop_event=cancel,
                            on_output=on_output,
                        )
                    ] = next_index
                    next_index += 1
    while next_index < len(items):
        result = stopped_result(items[next_index])
        results_by_index[next_index] = result
        report(result)
        next_index += 1
    return [results_by_index[index] for index in range(len(items))]


__all__ = [
    "STATUS_QUERY_LOGIN_MAX_RETRIES",
    "common_dut_status_settings",
    "run_dut_status_query_batch",
    "run_single_dut_status_query",
]
