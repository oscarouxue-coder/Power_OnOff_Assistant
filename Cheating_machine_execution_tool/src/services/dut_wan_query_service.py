"""DUT 现有 WAN 连接查询：网络准备、锁源 UBUS 登录和批量共同项汇总。"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

from line_check_assistant.network_ops import prepare_network_for_sample
from src.core.bind_socket import wait_for_bindable_ip
from src.core.dut_ubus_config import query_wan_connections
from src.core.ubus_http_client import UbusHttpClient
from src.models.dut_config_models import (
    DutTelnetEnableRequest,
    DutWanConnectionInfo,
    DutWanQueryResult,
)

from .dut_config_service import (
    BIND_READY_TIMEOUT_SECONDS,
    DEFAULT_DUT_PARALLEL_COUNT,
    clamp_dut_parallel_count,
    validate_dut_telnet_request,
)


WAN_QUERY_LOGIN_MAX_RETRIES = 3
WAN_QUERY_LOGIN_RETRY_DELAY_SECONDS = 2.0

OutputCallback = Callable[[str], None]
ItemCompleteCallback = Callable[[DutWanQueryResult], None]


class _DutWanQueryCancelled(RuntimeError):
    pass


def run_single_dut_wan_query(
    request: DutTelnetEnableRequest,
    *,
    stop_event: threading.Event | None = None,
    on_output: OutputCallback | None = None,
    network_prepare_fn: Callable = prepare_network_for_sample,
    bind_waiter: Callable[[str, float], bool] = wait_for_bindable_ip,
    client_factory: Callable[..., UbusHttpClient] = UbusHttpClient,
    query_fn: Callable = query_wan_connections,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> DutWanQueryResult:
    """查询单台 DUT；所有异常收敛为结果，且每次 client 都会关闭。"""
    label = request.channel or request.vlan or request.device_host or "DUT"

    def emit(message: str) -> None:
        if on_output is not None:
            on_output(f"[DUT配置][WAN查询][{label}] {message}")

    def ensure_not_stopped() -> None:
        if stop_event is not None and stop_event.is_set():
            raise _DutWanQueryCancelled("用户已请求停止")

    def pause(seconds: float) -> None:
        ensure_not_stopped()
        if stop_event is not None and sleep_fn is time.sleep:
            if stop_event.wait(max(0.0, float(seconds))):
                raise _DutWanQueryCancelled("用户已请求停止")
        else:
            sleep_fn(seconds)
        ensure_not_stopped()

    errors = validate_dut_telnet_request(request)
    if errors:
        message = "；".join(errors)
        emit(f"预检失败：{message}")
        return DutWanQueryResult(request, False, "preflight", message)

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
            return DutWanQueryResult(request, False, "network", network_result.message)

        ensure_not_stopped()
        emit(f"等待源 IP 可绑定：{request.bind_ip}，超时 {BIND_READY_TIMEOUT_SECONDS:g} 秒")
        if not bind_waiter(request.bind_ip, BIND_READY_TIMEOUT_SECONDS):
            message = f"网络准备后源 IP 仍不可绑定：{request.bind_ip}"
            emit(f"失败：{message}")
            return DutWanQueryResult(request, False, "bind", message)

        last_error: Exception | None = None
        for attempt in range(1, WAN_QUERY_LOGIN_MAX_RETRIES + 2):
            session_id = ""
            ensure_not_stopped()
            if attempt > 1:
                emit(
                    f"UBUS 登录第 {attempt - 1}/{WAN_QUERY_LOGIN_MAX_RETRIES} 次重试，"
                    f"等待 {WAN_QUERY_LOGIN_RETRY_DELAY_SECONDS:g} 秒"
                )
                pause(WAN_QUERY_LOGIN_RETRY_DELAY_SECONDS)
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
                queried = tuple(query_fn(client, session_id, on_log=emit))
                connections = tuple(
                    item for item in queried if isinstance(item, DutWanConnectionInfo)
                )
                names = (
                    tuple(item.name for item in connections)
                    if len(connections) == len(queried)
                    else tuple(str(item) for item in queried)
                )
                message = f"查询成功，发现 {len(names)} 个现有 WAN"
                emit(f"成功：{message}：{list(names)}")
                return DutWanQueryResult(
                    request,
                    True,
                    "completed",
                    message,
                    connection_names=names,
                    connections=connections,
                )
            except _DutWanQueryCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - 查询登录按既有策略重试
                last_error = exc
                emit(f"UBUS 查询现有 WAN 失败：{exc}")
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

        message = f"UBUS 查询现有 WAN 重试耗尽：{last_error}"
        if last_error is not None and "access denied" in str(last_error).lower():
            message += "；请退出样机 Web 管理页面后重试"
        emit(f"失败：{message}")
        return DutWanQueryResult(request, False, "query", message)
    except _DutWanQueryCancelled:
        message = "用户已停止，未继续查询本台 DUT"
        emit(f"跳过：{message}")
        return DutWanQueryResult(request, False, "stopped", message)
    except Exception as exc:  # noqa: BLE001 - 单台异常不能破坏批次
        message = f"WAN 查询异常：{exc}"
        emit(f"失败：{message}")
        return DutWanQueryResult(request, False, "exception", message)
    finally:
        if client is not None:
            client.close()


def common_wan_connection_names(
    results: Iterable[DutWanQueryResult],
) -> tuple[str, ...]:
    """仅当所有目标查询成功时，返回名称完全一致的共同 WAN。"""
    items = list(results)
    if not items or any(not result.ok for result in items):
        return ()
    common = set(items[0].connection_names)
    for result in items[1:]:
        common.intersection_update(result.connection_names)
    return tuple(sorted(common, key=lambda name: (int(name.split("_", 1)[0]), name)))


def common_wan_connection_details(
    results: Iterable[DutWanQueryResult],
) -> dict[str, DutWanConnectionInfo]:
    """返回所有目标详情完全一致的共同 WAN，避免批量界面展示任一台的特例值。"""
    items = list(results)
    common_names = common_wan_connection_names(items)
    if not common_names:
        return {}
    per_target = [{item.name: item for item in result.connections} for result in items]
    details: dict[str, DutWanConnectionInfo] = {}
    for name in common_names:
        snapshots = [mapping.get(name) for mapping in per_target]
        if all(snapshot is not None for snapshot in snapshots) and len(set(snapshots)) == 1:
            details[name] = snapshots[0]  # type: ignore[assignment]
    return details


def run_dut_wan_query_batch(
    requests: Iterable[DutTelnetEnableRequest],
    *,
    max_workers: int = DEFAULT_DUT_PARALLEL_COUNT,
    stop_event: threading.Event | None = None,
    on_output: OutputCallback | None = None,
    on_item_complete: ItemCompleteCallback | None = None,
    single_runner: Callable[..., DutWanQueryResult] = run_single_dut_wan_query,
) -> list[DutWanQueryResult]:
    """并行查询；停止后不再提交尚未开始的 DUT。"""
    items = list(requests)
    if not items:
        return []
    cancel = stop_event or threading.Event()
    workers = min(clamp_dut_parallel_count(max_workers), len(items))
    results_by_index: dict[int, DutWanQueryResult] = {}
    next_index = 0

    def report(result: DutWanQueryResult) -> None:
        if on_item_complete is not None:
            on_item_complete(result)

    def stopped_result(request: DutTelnetEnableRequest) -> DutWanQueryResult:
        return DutWanQueryResult(
            request, False, "stopped", "用户已停止，未启动本台 WAN 查询"
        )

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dut-wan-query") as executor:
        futures: dict[Future, int] = {}
        while next_index < len(items) and len(futures) < workers and not cancel.is_set():
            futures[
                executor.submit(
                    single_runner,
                    items[next_index],
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
                    result = DutWanQueryResult(
                        items[index], False, "exception", f"WAN 查询异常：{exc}"
                    )
                results_by_index[index] = result
                report(result)
                if next_index < len(items) and not cancel.is_set():
                    futures[
                        executor.submit(
                            single_runner,
                            items[next_index],
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
    "common_wan_connection_details",
    "common_wan_connection_names",
    "run_dut_wan_query_batch",
    "run_single_dut_wan_query",
]
