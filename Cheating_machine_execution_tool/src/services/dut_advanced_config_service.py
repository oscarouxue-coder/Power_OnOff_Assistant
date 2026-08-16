"""DUT WAN、语音、TR069 和 WiFi 的单台与批量业务编排。"""
from __future__ import annotations

import ipaddress
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from collections.abc import Callable, Iterable
from dataclasses import replace
from urllib.parse import urlsplit

from line_check_assistant.network_ops import prepare_network_for_sample
from src.core.bind_socket import wait_for_bindable_ip
from src.core.dut_ubus_config import configure_tr069, configure_voice, configure_wan, parse_port_bind
from src.core.dut_wifi_config import (
    WIFI_APPLY_SETTLE_SECONDS,
    apply_wifi_config,
    configure_wifi,
    verify_wifi_config,
)
from src.core.ubus_http_client import UbusHttpClient
from src.models.dut_config_models import (
    DutAdvancedConfigRequest,
    DutAdvancedConfigResult,
    DutTr069Settings,
    DutVoiceSettings,
    DutWanSettings,
    DutWifiSettings,
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
VOICE_DTMF_OPTIONS = ("RFC2833", "InBand", "SIPINFO")
VOICE_SIP_MODE_OPTIONS = ("SIP", "IMSSIP", "UDP", "TCP", "TLS")
WIFI_SECURITY_MODE_OPTIONS = (
    "None",
    "WPA2-Personal",
    "WPA3-Personal",
    "WPA3-Personal-Transition",
    "WPA-WPA2-Personal",
)
WIFI_BANDWIDTH_OPTIONS = {
    "2.4G": ("20MHz", "40MHz", "20/40MHz"),
    "5G": ("20MHz", "40MHz", "80MHz", "160MHz"),
}
WIFI_MODE_OPTIONS = {
    "2.4G": ("b", "b,g", "b,g,n", "b,g,n,ax"),
    "5G": ("a", "a,n", "a,n,ac", "a,n,ac,ax"),
}

OutputCallback = Callable[[str], None]
ItemCompleteCallback = Callable[[DutAdvancedConfigResult], None]


class _DutAdvancedConfigCancelled(RuntimeError):
    pass


def build_dut_wifi_settings_sequence(
    settings: DutWifiSettings,
    target_count: int,
    *,
    increment_enabled: bool,
) -> tuple[DutWifiSettings, ...]:
    """按固定目标顺序生成逐台WiFi参数，递增时保留SSID数字尾缀宽度。"""
    if target_count < 0:
        raise ValueError(f"目标数量不能为负数：{target_count}")
    if target_count == 0:
        return ()
    if not increment_enabled:
        return tuple(settings for _index in range(target_count))

    match = re.fullmatch(r"(.*?)(\d+)", settings.ssid)
    if match is None:
        raise ValueError(
            "已勾选“SSID递增”，WiFi名称必须以数字结尾，例如 Test_2G_01。"
        )
    prefix, suffix = match.groups()
    start_number = int(suffix)
    suffix_width = len(suffix)
    sequence: list[DutWifiSettings] = []
    for offset in range(target_count):
        ssid = f"{prefix}{str(start_number + offset).zfill(suffix_width)}"
        if len(ssid.encode("utf-8")) > 32:
            raise ValueError(
                f"SSID递增生成的名称“{ssid}”按UTF-8编码后超过32字节。"
            )
        sequence.append(replace(settings, ssid=ssid))
    return tuple(sequence)


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
    supported_sip_modes = settings.supported_sip_modes or VOICE_SIP_MODE_OPTIONS
    if settings.sip_mode not in supported_sip_modes:
        errors.append(
            f"SIP 模式无效：{settings.sip_mode}；仅支持 {'、'.join(supported_sip_modes)}"
        )
    supported_dtmf_methods = settings.supported_dtmf_methods or VOICE_DTMF_OPTIONS
    if settings.dtmf_method not in supported_dtmf_methods:
        errors.append(
            f"DTMF 模式无效：{settings.dtmf_method}；仅支持 {'、'.join(supported_dtmf_methods)}"
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
    supported_codecs = settings.supported_codecs or tuple(sorted(VOICE_CODEC_OPTIONS))
    if len(settings.codecs) != 5 or any(codec not in supported_codecs for codec in settings.codecs):
        errors.append("语音编码必须选择 5 个受支持的编码")
    return tuple(errors)


def validate_tr069_settings(settings: DutTr069Settings) -> tuple[str, ...]:
    errors: list[str] = []
    supported = set(settings.supported_fields)
    if not supported or "acs_url" in supported:
        parsed = urlsplit(settings.acs_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"ACS URL 必须是完整的 http/https 地址：{settings.acs_url}")
    if not supported or "periodic_inform_interval" in supported:
        try:
            if int(settings.periodic_inform_interval) <= 0:
                raise ValueError
        except ValueError:
            errors.append(f"周期 Inform 间隔必须为正整数：{settings.periodic_inform_interval}")
    if supported and settings.manual_inform and "manual_inform" not in supported:
        errors.append("当前DUT不支持配置后手动 Inform")
    return tuple(errors)


def _validate_wifi_radio(
    *,
    band: str,
    channel: str,
    channel_bandwidth: str,
    operating_mode: str,
    transmit_power: str,
    supported_channels: tuple[str, ...],
    supported_bandwidths: tuple[str, ...],
    supported_modes: tuple[str, ...],
    supported_transmit_powers: tuple[str, ...],
) -> list[str]:
    errors: list[str] = []
    normalized_channel = channel.strip().lower()
    normalized_supported_channels = tuple(
        value.lower() for value in supported_channels
    )
    if normalized_supported_channels and normalized_channel not in normalized_supported_channels:
        errors.append(f"{band} WiFi 信道不在DUT支持列表：{channel}")
    elif not normalized_supported_channels and normalized_channel != "auto":
        try:
            channel_number = int(normalized_channel)
        except ValueError:
            errors.append(f"{band} WiFi 信道无效：{channel}")
        else:
            if band == "2.4G" and not 1 <= channel_number <= 14:
                errors.append(f"2.4G WiFi 信道必须为 auto 或 1–14：{channel}")
            if band == "5G" and channel_number not in {
                36, 40, 44, 48, 52, 56, 60, 64,
                100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140,
                144, 149, 153, 157, 161, 165,
            }:
                errors.append(f"5G WiFi 信道不受支持：{channel}")
    bandwidths = supported_bandwidths or WIFI_BANDWIDTH_OPTIONS[band]
    if channel_bandwidth not in bandwidths:
        errors.append(f"{band} WiFi 信道带宽无效：{channel_bandwidth}")
    modes = supported_modes or WIFI_MODE_OPTIONS[band]
    if operating_mode not in modes:
        errors.append(f"{band} WiFi 协议类型无效：{operating_mode}")
    if supported_transmit_powers and transmit_power not in supported_transmit_powers:
        errors.append(
            f"{band} WiFi 发射功率不在DUT支持列表：{transmit_power}"
        )
    return errors


def validate_wifi_settings(settings: DutWifiSettings) -> tuple[str, ...]:
    """校验首版 WiFi 页面支持且能由参考 UBUS 模型稳定表达的组合。"""
    errors: list[str] = []
    if settings.band not in {"2.4G", "5G"}:
        return (f"WiFi 频段无效：{settings.band}",)
    try:
        ssid_index = int(settings.ssid_index)
        if not 1 <= ssid_index <= 8:
            raise ValueError
    except (TypeError, ValueError):
        errors.append(f"SSID 索引必须为 1–8：{settings.ssid_index}")
    if not settings.ssid:
        errors.append("WiFi 名称为空")
    elif len(settings.ssid.encode("utf-8")) > 32:
        errors.append("WiFi 名称按 UTF-8 编码后不能超过 32 字节")
    security_modes = settings.supported_security_modes or WIFI_SECURITY_MODE_OPTIONS
    if settings.security_mode not in security_modes:
        errors.append(f"WiFi 认证/加密模式无效：{settings.security_mode}")
    elif settings.security_mode != "None":
        password = settings.password
        is_hex_key = len(password) == 64 and all(char in "0123456789abcdefABCDEF" for char in password)
        if not (8 <= len(password) <= 63 or is_hex_key):
            errors.append("WiFi 密码必须为 8–63 个字符，或 64 位十六进制密钥")

    errors.extend(
        _validate_wifi_radio(
            band=settings.band,
            channel=settings.channel,
            channel_bandwidth=settings.channel_bandwidth,
            operating_mode=settings.operating_mode,
            transmit_power=settings.transmit_power,
            supported_channels=settings.supported_channels,
            supported_bandwidths=settings.supported_bandwidths,
            supported_modes=settings.supported_modes,
            supported_transmit_powers=settings.supported_transmit_powers,
        )
    )
    if settings.dual_band_enabled:
        expected_peer_band = "5G" if settings.band == "2.4G" else "2.4G"
        if settings.peer_radio is None:
            errors.append(f"双频合一缺少{expected_peer_band}射频参数")
        else:
            peer = settings.peer_radio
            if peer.band != expected_peer_band:
                errors.append(
                    f"双频合一另一频段应为{expected_peer_band}，实际为{peer.band}"
                )
            if peer.transmit_power != settings.transmit_power:
                errors.append(
                    "双频合一的发射功率是公共参数，两个Radio必须使用同一值"
                )
            errors.extend(
                _validate_wifi_radio(
                    band=expected_peer_band,
                    channel=peer.channel,
                    channel_bandwidth=peer.channel_bandwidth,
                    operating_mode=peer.operating_mode,
                    transmit_power=settings.transmit_power,
                    supported_channels=peer.supported_channels,
                    supported_bandwidths=peer.supported_bandwidths,
                    supported_modes=peer.supported_modes,
                    supported_transmit_powers=peer.supported_transmit_powers,
                )
            )
    try:
        transmit_power = int(settings.transmit_power)
        if not 1 <= transmit_power <= 100:
            raise ValueError
    except ValueError:
        errors.append(f"WiFi 发射功率必须为 1–100：{settings.transmit_power}")
    try:
        max_associations = int(settings.max_associations)
        if not 0 <= max_associations <= 32:
            raise ValueError
    except ValueError:
        errors.append(f"WiFi 最大接入数必须为 0–32：{settings.max_associations}")
    return tuple(errors)


def validate_dut_advanced_request(request: DutAdvancedConfigRequest) -> tuple[str, ...]:
    errors = _validate_common(request)
    if request.feature == "wan" and isinstance(request.settings, DutWanSettings):
        errors.extend(validate_wan_settings(request.settings))
    elif request.feature == "voice" and isinstance(request.settings, DutVoiceSettings):
        errors.extend(validate_voice_settings(request.settings))
    elif request.feature == "tr069" and isinstance(request.settings, DutTr069Settings):
        errors.extend(validate_tr069_settings(request.settings))
    elif request.feature in {"wifi_2g", "wifi_5g"} and isinstance(
        request.settings, DutWifiSettings
    ):
        expected_band = "2.4G" if request.feature == "wifi_2g" else "5G"
        if request.settings.band != expected_band:
            errors.append(
                f"{request.feature} 与 WiFi 频段 {request.settings.band} 不匹配"
            )
        errors.extend(validate_wifi_settings(request.settings))
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
    wifi_fn: Callable = configure_wifi,
    wifi_apply_fn: Callable = apply_wifi_config,
    wifi_verify_fn: Callable = verify_wifi_config,
    wifi_phase: str = "configure",
    sleep_fn: Callable[[float], None] = time.sleep,
) -> DutAdvancedConfigResult:
    label = request.channel or request.vlan or request.device_host or "DUT"
    feature_label = {
        "wan": "WAN配置", "voice": "语音配置", "tr069": "TR069配置",
        "wifi_2g": "2.4G WiFi配置", "wifi_5g": "5G WiFi配置",
    }.get(
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
        elif request.feature == "tr069":
            details = tr069_fn(
                client,
                session_id,
                request.settings,
                on_log=emit,
                stop_requested=lambda: bool(stop_event and stop_event.is_set()),
                sleep_fn=pause,
            )
            success_message = "TR069 配置成功"
        elif wifi_phase == "apply":
            details = wifi_apply_fn(
                client,
                session_id,
                request.settings,
                on_log=emit,
                sleep_fn=pause,
            )
            success_message = (
                f"{request.settings.band} WiFi 参数已下发，等待批次统一稳定后回读"
            )
        elif wifi_phase == "verify":
            details = wifi_verify_fn(
                client,
                session_id,
                request.settings,
                on_log=emit,
                sleep_fn=pause,
            )
            success_message = f"{request.settings.band} WiFi 回读校验成功"
        elif wifi_phase == "configure":
            details = wifi_fn(
                client,
                session_id,
                request.settings,
                on_log=emit,
                sleep_fn=pause,
            )
            success_message = f"{request.settings.band} WiFi 配置成功"
        else:
            raise ValueError(f"WiFi执行阶段无效：{wifi_phase}")
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
    shared_wifi_settle: bool = False,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> list[DutAdvancedConfigResult]:
    items = list(requests)
    if not items:
        return []
    cancel = stop_event or threading.Event()
    workers = min(clamp_dut_parallel_count(max_workers), len(items))
    def report(result: DutAdvancedConfigResult) -> None:
        if on_item_complete is not None:
            on_item_complete(result)

    def stopped_result(request: DutAdvancedConfigRequest) -> DutAdvancedConfigResult:
        return DutAdvancedConfigResult(request, False, "stopped", "用户已停止，未启动本台 DUT 配置")

    def run_phase(
        indexes: list[int],
        *,
        runner_kwargs: dict[str, object] | None = None,
        report_immediately: bool,
    ) -> dict[int, DutAdvancedConfigResult]:
        phase_results: dict[int, DutAdvancedConfigResult] = {}
        next_position = 0
        kwargs = runner_kwargs or {}
        phase_workers = min(workers, len(indexes)) if indexes else 1
        with ThreadPoolExecutor(
            max_workers=phase_workers,
            thread_name_prefix=f"dut-{items[0].feature}",
        ) as executor:
            futures: dict[Future, int] = {}
            while (
                next_position < len(indexes)
                and len(futures) < phase_workers
                and not cancel.is_set()
            ):
                index = indexes[next_position]
                futures[
                    executor.submit(
                        single_runner,
                        items[index],
                        stop_event=cancel,
                        on_output=on_output,
                        **kwargs,
                    )
                ] = index
                next_position += 1
            while futures:
                completed, _pending = wait(
                    tuple(futures), return_when=FIRST_COMPLETED
                )
                for future in completed:
                    index = futures.pop(future)
                    try:
                        result = future.result()
                    except Exception as exc:  # noqa: BLE001
                        result = DutAdvancedConfigResult(
                            items[index],
                            False,
                            "exception",
                            f"DUT 配置异常：{exc}",
                        )
                    phase_results[index] = result
                    if report_immediately:
                        report(result)
                    if next_position < len(indexes) and not cancel.is_set():
                        next_index = indexes[next_position]
                        futures[
                            executor.submit(
                                single_runner,
                                items[next_index],
                                stop_event=cancel,
                                on_output=on_output,
                                **kwargs,
                            )
                        ] = next_index
                        next_position += 1
        while next_position < len(indexes):
            index = indexes[next_position]
            result = stopped_result(items[index])
            phase_results[index] = result
            if report_immediately:
                report(result)
            next_position += 1
        return phase_results

    use_shared_wifi_settle = (
        shared_wifi_settle
        and len(items) > 1
        and all(item.feature in {"wifi_2g", "wifi_5g"} for item in items)
    )
    all_indexes = list(range(len(items)))
    if not use_shared_wifi_settle:
        results_by_index = run_phase(
            all_indexes,
            report_immediately=True,
        )
        return [results_by_index[index] for index in all_indexes]

    apply_results = run_phase(
        all_indexes,
        runner_kwargs={"wifi_phase": "apply"},
        report_immediately=False,
    )
    applied_indexes = [
        index for index in all_indexes if apply_results[index].ok
    ]
    if not applied_indexes:
        final_results = [apply_results[index] for index in all_indexes]
        for result in final_results:
            report(result)
        return final_results

    def unverified_result(index: int, message: str) -> DutAdvancedConfigResult:
        return DutAdvancedConfigResult(
            items[index],
            False,
            "stopped",
            message,
        )

    if cancel.is_set():
        for index in applied_indexes:
            apply_results[index] = unverified_result(
                index,
                "WiFi参数已下发，但用户停止后未执行统一等待和回读校验",
            )
        final_results = [apply_results[index] for index in all_indexes]
        for result in final_results:
            report(result)
        return final_results

    last_index = applied_indexes[-1]
    last_request = items[last_index]
    last_label = (
        last_request.channel
        or last_request.vlan
        or last_request.device_host
        or "DUT"
    )
    feature_label = (
        "2.4G WiFi配置" if last_request.feature == "wifi_2g" else "5G WiFi配置"
    )
    if on_output is not None:
        on_output(
            f"[DUT配置][{feature_label}][{last_label}] "
            f"等待 WiFi 参数生效并稳定：{WIFI_APPLY_SETTLE_SECONDS:g} 秒"
            "（SSID递增批次统一等待，仅最后一台执行）"
        )
    try:
        if sleep_fn is time.sleep:
            stopped_during_wait = cancel.wait(WIFI_APPLY_SETTLE_SECONDS)
        else:
            sleep_fn(WIFI_APPLY_SETTLE_SECONDS)
            stopped_during_wait = cancel.is_set()
    except Exception as exc:  # noqa: BLE001 - 批次等待异常必须形成逐台结果
        for index in applied_indexes:
            apply_results[index] = DutAdvancedConfigResult(
                items[index],
                False,
                "exception",
                f"WiFi统一稳定等待异常：{exc}",
            )
        final_results = [apply_results[index] for index in all_indexes]
        for result in final_results:
            report(result)
        return final_results

    if stopped_during_wait:
        for index in applied_indexes:
            apply_results[index] = unverified_result(
                index,
                "WiFi参数已下发，但用户在统一稳定等待期间停止，未完成回读校验",
            )
        final_results = [apply_results[index] for index in all_indexes]
        for result in final_results:
            report(result)
        return final_results

    if on_output is not None:
        on_output(
            f"[DUT配置][{feature_label}][{last_label}] "
            "SSID递增批次统一等待完成，开始逐台回读校验"
        )
    verify_results = run_phase(
        applied_indexes,
        runner_kwargs={"wifi_phase": "verify"},
        report_immediately=False,
    )
    final_by_index = dict(apply_results)
    final_by_index.update(verify_results)
    final_results = [final_by_index[index] for index in all_indexes]
    for result in final_results:
        report(result)
    return final_results


__all__ = [
    "UBUS_LOGIN_MAX_RETRIES",
    "VOICE_CODEC_OPTIONS",
    "VOICE_DTMF_OPTIONS",
    "WIFI_BANDWIDTH_OPTIONS",
    "WIFI_MODE_OPTIONS",
    "WIFI_SECURITY_MODE_OPTIONS",
    "build_dut_wifi_settings_sequence",
    "run_dut_advanced_config_batch",
    "run_single_dut_advanced_config",
    "validate_dut_advanced_request",
    "validate_tr069_settings",
    "validate_voice_settings",
    "validate_wan_settings",
    "validate_wifi_settings",
]
