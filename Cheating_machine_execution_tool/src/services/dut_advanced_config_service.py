"""DUT WAN、语音和 TR069 的单台与批量业务编排。"""
from __future__ import annotations

import ipaddress
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

from line_check_assistant.network_ops import prepare_network_for_sample
from src.core.bind_socket import wait_for_bindable_ip
from src.core.dut_ubus_config import configure_tr069, configure_voice, configure_wan, parse_port_bind
from src.core.ubus_http_client import UbusHttpClient
from src.models.dut_config_models import (
    DutAdvancedConfigRequest,
    DutAdvancedConfigResult,
    DutTr069Settings,
    DutVoiceSettings,
    DutWanSettings,
)

from .dut_config_service import BIND_READY_TIMEOUT_SECONDS, clamp_dut_parallel_count


UBUS_LOGIN_MAX_RETRIES = 3
UBUS_LOGIN_RETRY_DELAY_SECONDS = 2.0
VOICE_CODEC_OPTIONS = {
    "G.711 U-law",
    "G.711 A-law",
    "G.729",
    "G.722",
    "G.723",
    "G.726 - 16",
    "G.726 - 24",
    "G.726 - 32",
    "G.726 - 40",
}
VOICE_SIP_MODE_OPTIONS = ("SIP", "IMSSIP", "UDP", "TCP", "TLS")

OutputCallback = Callable[[str], None]
ItemCompleteCallback = Callable[[DutAdvancedConfigResult], None]


class _DutAdvancedConfigCancelled(RuntimeError):
    pass


def _validate_common(request: DutAdvancedConfigRequest) -> list[str]:
    errors: list[str] = []
    label = request.channel or request.vlan or "未命名通道"
    if not request.vlan.strip():
        errors.append("通道未配置 VLAN")
    if not request.adapter_alias.strip():
        errors.append(f"{label} 未配置 VLAN 网卡")
    for field_label, value in (("PC 静态 IP", request.bind_ip), ("样机管理 IP", request.device_host)):
        if not value.strip():
            errors.append(f"{label} 未配置 {field_label}")
            continue
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
        port = int(request.ubus_port)
    except (TypeError, ValueError):
        errors.append(f"{label} UBUS 端口格式无效：{request.ubus_port}")
    else:
        if not 1 <= port <= 65535:
            errors.append(f"{label} UBUS 端口超出范围：{request.ubus_port}")
    return errors


def _validate_ip(errors: list[str], label: str, value: str, version: int, *, required: bool = True) -> None:
    if not value.strip():
        if required:
            errors.append(f"{label}为空")
        return
    try:
        parsed = ipaddress.ip_address(value.strip())
        if parsed.version != version:
            raise ValueError
    except ValueError:
        errors.append(f"{label}格式无效：{value}")


def validate_wan_settings(settings: DutWanSettings) -> tuple[str, ...]:
    errors: list[str] = []
    operation = settings.operation.strip().lower()
    if operation not in {"add", "modify", "delete"}:
        errors.append(f"WAN 操作无效：{settings.operation}")
    if operation in {"modify", "delete"}:
        value = settings.connection_index.strip()
        if not value or not value.split("_", 1)[0].isdigit():
            errors.append("修改/删除必须填写以数字开头的现有 WAN 连接名或索引")
    if operation == "delete":
        return tuple(errors)
    if settings.mode not in {"router", "bridge"}:
        errors.append(f"WAN 模式无效：{settings.mode}")
    allowed_services = {
        "TR069", "VOICE", "INTERNET", "TR069_VOICE", "TR069_INTERNET",
        "VOICE_INTERNET", "TR069_VOICE_INTERNET", "OTHER", "IPTV",
    }
    if settings.service_type not in allowed_services:
        errors.append(f"WAN 业务类型无效：{settings.service_type}")
    if settings.mode == "bridge" and settings.service_type not in {"IPTV", "INTERNET", "OTHER"}:
        errors.append("桥接 WAN 的业务类型仅支持 IPTV、INTERNET 或 OTHER")
    try:
        vlan_id = int(settings.vlan_id)
        if not 1 <= vlan_id <= 4094:
            raise ValueError
    except ValueError:
        errors.append(f"业务 VLAN ID 必须为 1–4094：{settings.vlan_id}")
    multicast_vlan_id = settings.multicast_vlan_id.strip()
    if settings.service_type == "IPTV" and multicast_vlan_id:
        try:
            multicast_vlan = int(multicast_vlan_id)
            if not 1 <= multicast_vlan <= 4094:
                raise ValueError
        except ValueError:
            errors.append(f"组播 VLAN ID 必须为 1–4094：{settings.multicast_vlan_id}")
    try:
        priority = int(settings.vlan_priority)
        if not 0 <= priority <= 7:
            raise ValueError
    except ValueError:
        errors.append(f"VLAN 优先级必须为 0–7：{settings.vlan_priority}")
    try:
        mtu = int(settings.mtu)
        if not 576 <= mtu <= 2000:
            raise ValueError
    except ValueError:
        errors.append(f"MTU 必须为 576–2000：{settings.mtu}")
    try:
        parse_port_bind(settings.port_bind)
    except (TypeError, ValueError) as exc:
        errors.append(f"端口绑定无效：{exc}")
    if settings.mode == "bridge":
        return tuple(errors)
    if settings.access_type not in {"IPoE", "PPPoE"}:
        errors.append(f"接入方式无效：{settings.access_type}")
    if settings.ip_protocol not in {"IPv4", "IPv6", "IPv4IPv6"}:
        errors.append(f"IP 协议无效：{settings.ip_protocol}")
    if settings.access_type == "PPPoE":
        if not settings.pppoe_username:
            errors.append("PPPoE 账号为空")
        if not settings.pppoe_password:
            errors.append("PPPoE 密码为空")
        if settings.ip_protocol in {"IPv6", "IPv4IPv6"} and settings.ipv6_type == "Static":
            errors.append("PPPoE 不支持静态 IPv6；请改用 SLAAC、DHCPv6 或 IPoE")
    if settings.ip_protocol == "IPv4IPv6":
        address_pair = (settings.ipv4_type, settings.ipv6_type)
        allowed_pairs = (
            {("Dynamic", "SLAAC"), ("Dynamic", "DHCPv6")}
            if settings.access_type == "PPPoE"
            else {("Dynamic", "SLAAC"), ("Dynamic", "DHCPv6"), ("Static", "Static")}
        )
        if address_pair not in allowed_pairs:
            errors.append(
                f"{settings.access_type} 双栈地址方式组合不受支持："
                f"IPv4={settings.ipv4_type}，IPv6={settings.ipv6_type}"
            )
    if settings.ip_protocol in {"IPv4", "IPv4IPv6"}:
        if settings.ipv4_type not in {"Dynamic", "Static"}:
            errors.append(f"IPv4 地址方式无效：{settings.ipv4_type}")
        if settings.ipv4_type == "Static":
            if settings.access_type == "PPPoE":
                errors.append("PPPoE 不支持静态 IPv4；请改用动态 IPv4 或 IPoE")
            _validate_ip(errors, "IPv4 地址", settings.ipv4_address, 4)
            _validate_ip(errors, "IPv4 网关", settings.ipv4_gateway, 4)
            _validate_ip(errors, "IPv4 主 DNS", settings.ipv4_primary_dns, 4)
            _validate_ip(errors, "IPv4 备 DNS", settings.ipv4_secondary_dns, 4, required=False)
            try:
                ipaddress.IPv4Network(f"0.0.0.0/{settings.ipv4_netmask}")
            except ValueError:
                errors.append(f"IPv4 子网掩码格式无效：{settings.ipv4_netmask}")
    if settings.ip_protocol in {"IPv6", "IPv4IPv6"}:
        if settings.ipv6_type not in {"SLAAC", "DHCPv6", "Static"}:
            errors.append(f"IPv6 地址方式无效：{settings.ipv6_type}")
        if settings.ipv6_type == "Static":
            _validate_ip(errors, "IPv6 地址", settings.ipv6_address, 6)
            _validate_ip(errors, "IPv6 网关", settings.ipv6_gateway, 6)
            _validate_ip(errors, "IPv6 主 DNS", settings.ipv6_primary_dns, 6)
            _validate_ip(errors, "IPv6 备 DNS", settings.ipv6_secondary_dns, 6, required=False)
            try:
                ipaddress.IPv6Network(settings.ipv6_prefix.strip(), strict=False)
            except ValueError:
                errors.append(f"IPv6 前缀格式无效：{settings.ipv6_prefix}")
    return tuple(errors)


def validate_voice_settings(settings: DutVoiceSettings) -> tuple[str, ...]:
    errors: list[str] = []
    if settings.sip_mode not in VOICE_SIP_MODE_OPTIONS:
        errors.append(
            f"SIP 模式无效：{settings.sip_mode}；仅支持 {'、'.join(VOICE_SIP_MODE_OPTIONS)}"
        )
    try:
        line_index = int(settings.line_index)
        if not 1 <= line_index <= 8:
            raise ValueError
    except ValueError:
        errors.append(f"语音线路索引必须为 1–8：{settings.line_index}")
    if settings.account_enabled:
        if not settings.display_name:
            errors.append("SIP 显示名称为空")
        if not settings.auth_username:
            errors.append("SIP 认证账号为空")
        if not settings.auth_password:
            errors.append("SIP 认证密码为空")
    if not settings.proxy_server:
        errors.append("SIP 代理服务器为空")
    if not settings.registrar_server:
        errors.append("SIP 注册服务器为空")
    for label, value in (
        ("代理服务器端口", settings.proxy_port),
        ("出站代理端口", settings.outbound_proxy_port),
        ("注册服务器端口", settings.registrar_server_port),
    ):
        try:
            port = int(value)
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            errors.append(f"{label}必须为 1–65535：{value}")
    try:
        if int(settings.register_expires) <= 0:
            raise ValueError
    except ValueError:
        errors.append(f"注册有效期必须为正整数：{settings.register_expires}")
    if len(settings.codecs) != 5 or any(codec not in VOICE_CODEC_OPTIONS for codec in settings.codecs):
        errors.append("语音编码必须选择 5 个受支持的编码")
    return tuple(errors)


def validate_tr069_settings(settings: DutTr069Settings) -> tuple[str, ...]:
    errors: list[str] = []
    parsed = urlsplit(settings.acs_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        errors.append(f"ACS URL 必须是完整的 http/https 地址：{settings.acs_url}")
    try:
        if int(settings.periodic_inform_interval) <= 0:
            raise ValueError
    except ValueError:
        errors.append(f"周期 Inform 间隔必须为正整数：{settings.periodic_inform_interval}")
    return tuple(errors)


def validate_dut_advanced_request(request: DutAdvancedConfigRequest) -> tuple[str, ...]:
    errors = _validate_common(request)
    if request.feature == "wan" and isinstance(request.settings, DutWanSettings):
        errors.extend(validate_wan_settings(request.settings))
    elif request.feature == "voice" and isinstance(request.settings, DutVoiceSettings):
        errors.extend(validate_voice_settings(request.settings))
    elif request.feature == "tr069" and isinstance(request.settings, DutTr069Settings):
        errors.extend(validate_tr069_settings(request.settings))
    else:
        errors.append(f"DUT 配置功能与参数类型不匹配：{request.feature}")
    return tuple(errors)


def run_single_dut_advanced_config(
    request: DutAdvancedConfigRequest,
    *,
    stop_event: threading.Event | None = None,
    on_output: OutputCallback | None = None,
    network_prepare_fn: Callable = prepare_network_for_sample,
    bind_waiter: Callable[[str, float], bool] = wait_for_bindable_ip,
    client_factory: Callable[..., UbusHttpClient] = UbusHttpClient,
    wan_fn: Callable = configure_wan,
    voice_fn: Callable = configure_voice,
    tr069_fn: Callable = configure_tr069,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> DutAdvancedConfigResult:
    label = request.channel or request.vlan or request.device_host or "DUT"
    feature_label = {"wan": "WAN配置", "voice": "语音配置", "tr069": "TR069配置"}.get(
        request.feature, request.feature
    )

    def emit(message: str) -> None:
        if on_output is not None:
            on_output(f"[DUT配置][{feature_label}][{label}] {message}")

    def ensure_not_stopped() -> None:
        if stop_event is not None and stop_event.is_set():
            raise _DutAdvancedConfigCancelled("用户已请求停止")

    def pause(seconds: float) -> None:
        ensure_not_stopped()
        if stop_event is not None and sleep_fn is time.sleep:
            if stop_event.wait(max(0.0, float(seconds))):
                raise _DutAdvancedConfigCancelled("用户已请求停止")
        else:
            sleep_fn(seconds)
        ensure_not_stopped()

    errors = validate_dut_advanced_request(request)
    if errors:
        message = "；".join(errors)
        emit(f"预检失败：{message}")
        return DutAdvancedConfigResult(request, False, "preflight", message)

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
            return DutAdvancedConfigResult(request, False, "network", network_result.message)
        ensure_not_stopped()
        emit(f"等待源 IP 可绑定：{request.bind_ip}，超时 {BIND_READY_TIMEOUT_SECONDS:g} 秒")
        if not bind_waiter(request.bind_ip, BIND_READY_TIMEOUT_SECONDS):
            message = f"网络准备后源 IP 仍不可绑定：{request.bind_ip}"
            emit(f"失败：{message}")
            return DutAdvancedConfigResult(request, False, "bind", message)

        session_id = ""
        last_error: Exception | None = None
        for attempt in range(1, UBUS_LOGIN_MAX_RETRIES + 2):
            ensure_not_stopped()
            if attempt > 1:
                emit(
                    f"UBUS 登录第 {attempt - 1}/{UBUS_LOGIN_MAX_RETRIES} 次重试，"
                    f"等待 {UBUS_LOGIN_RETRY_DELAY_SECONDS:g} 秒"
                )
                pause(UBUS_LOGIN_RETRY_DELAY_SECONDS)
            client = client_factory(request.bind_ip, request.device_host, ubus_port=request.ubus_port)
            emit(
                f"TX UBUS session.login：{request.bind_ip} -> {request.device_host}:"
                f"{request.ubus_port}，username={request.username}，password={request.password}"
            )
            try:
                session_id = client.login(request.username, request.password)
                last_error = None
                emit("UBUS 登录成功")
                break
            except Exception as exc:  # noqa: BLE001 - 登录按策略重试
                last_error = exc
                emit(f"UBUS 登录失败：{exc}")
                client.close()
                client = None
        if client is None or not session_id:
            message = f"UBUS 登录重试耗尽：{last_error}"
            if last_error is not None and "access denied" in str(last_error).lower():
                message += "；请退出样机 Web 管理页面后重试"
            emit(f"失败：{message}")
            return DutAdvancedConfigResult(request, False, "login", message)

        ensure_not_stopped()
        if request.feature == "wan":
            details = wan_fn(client, session_id, request.settings, on_log=emit)
            success_message = "WAN 操作成功"
        elif request.feature == "voice":
            details = voice_fn(client, session_id, request.settings, on_log=emit)
            success_message = "语音配置成功"
        else:
            details = tr069_fn(
                client,
                session_id,
                request.settings,
                on_log=emit,
                stop_requested=lambda: bool(stop_event and stop_event.is_set()),
                sleep_fn=pause,
            )
            success_message = "TR069 配置成功"
        ensure_not_stopped()
        emit(f"成功：{success_message}")
        return DutAdvancedConfigResult(request, True, "completed", success_message, details)
    except (_DutAdvancedConfigCancelled, InterruptedError):
        message = "用户已停止，未继续执行本台后续步骤"
        emit(f"跳过：{message}")
        return DutAdvancedConfigResult(request, False, "stopped", message)
    except Exception as exc:  # noqa: BLE001 - 单台错误不能破坏批次
        message = f"{feature_label}异常：{exc}"
        emit(f"失败：{message}")
        return DutAdvancedConfigResult(request, False, "ubus", message)
    finally:
        if client is not None:
            client.close()


def run_dut_advanced_config_batch(
    requests: Iterable[DutAdvancedConfigRequest],
    *,
    max_workers: int = 1,
    stop_event: threading.Event | None = None,
    on_output: OutputCallback | None = None,
    on_item_complete: ItemCompleteCallback | None = None,
    single_runner: Callable[..., DutAdvancedConfigResult] = run_single_dut_advanced_config,
) -> list[DutAdvancedConfigResult]:
    items = list(requests)
    if not items:
        return []
    cancel = stop_event or threading.Event()
    workers = min(clamp_dut_parallel_count(max_workers), len(items))
    results_by_index: dict[int, DutAdvancedConfigResult] = {}
    next_index = 0

    def report(result: DutAdvancedConfigResult) -> None:
        if on_item_complete is not None:
            on_item_complete(result)

    def stopped_result(request: DutAdvancedConfigRequest) -> DutAdvancedConfigResult:
        return DutAdvancedConfigResult(request, False, "stopped", "用户已停止，未启动本台 DUT 配置")

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"dut-{items[0].feature}") as executor:
        futures: dict[Future, int] = {}
        while next_index < len(items) and len(futures) < workers and not cancel.is_set():
            futures[executor.submit(single_runner, items[next_index], stop_event=cancel, on_output=on_output)] = next_index
            next_index += 1
        while futures:
            completed, _pending = wait(tuple(futures), return_when=FIRST_COMPLETED)
            for future in completed:
                index = futures.pop(future)
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    result = DutAdvancedConfigResult(items[index], False, "exception", f"DUT 配置异常：{exc}")
                results_by_index[index] = result
                report(result)
                if next_index < len(items) and not cancel.is_set():
                    futures[executor.submit(single_runner, items[next_index], stop_event=cancel, on_output=on_output)] = next_index
                    next_index += 1
    while next_index < len(items):
        result = stopped_result(items[next_index])
        results_by_index[next_index] = result
        report(result)
        next_index += 1
    return [results_by_index[index] for index in range(len(items))]


__all__ = [
    "UBUS_LOGIN_MAX_RETRIES",
    "VOICE_CODEC_OPTIONS",
    "run_dut_advanced_config_batch",
    "run_single_dut_advanced_config",
    "validate_dut_advanced_request",
    "validate_tr069_settings",
    "validate_voice_settings",
    "validate_wan_settings",
]
