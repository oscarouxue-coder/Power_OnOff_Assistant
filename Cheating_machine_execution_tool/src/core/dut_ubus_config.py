"""DUT WAN、语音和 TR069 的 UBUS 协议切片。

协议路径参考 ``SdmcUbusLib``，但不导入其共享静态 Session；调用方必须为
每台 DUT 创建绑定对应 VLAN 源 IP 的 :class:`UbusHttpClient`。
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

from src.models.dut_config_models import DutTr069Settings, DutVoiceSettings, DutWanSettings

from .ubus_http_client import UBUS_SERVICE_BBFDM, UbusError, UbusHttpClient


VENDOR_PREFIX = "X_SDMC_"
WAN_COMMAND = f"Device.{VENDOR_PREFIX}CreateWAN()"
WAN_INTERFACE_PATH = "Device.IP.Interface."
MANAGEMENT_SERVER_PATH = "Device.ManagementServer."
MANUAL_INFORM_STAGE_PATH = f"Device.ManagementServer.{VENDOR_PREFIX}ManualInformStage"
INFORM_RESULT_PATH = f"Device.ManagementServer.{VENDOR_PREFIX}InformResult"
WEB_OPTIONAL = {"proto": "web"}

WAN_DEFAULT_INPUT: dict[str, Any] = {
    "Method": "Add",
    "Index": "",
    "Enable": 1,
    "Mode": "router",
    "ServiceType": "INTERNET",
    "IPoE": 0,
    "PPPoE": 0,
    "DHCPv6AddressAssignment": 0,
    "DHCPv6PrefixDelegation": 0,
    "DSLiteAddress": "",
    "DSLiteEnable": 0,
    "DSLiteType": "",
    "IPProtocol": "",
    "IPv4Address": "",
    "IPv4Gateway": "",
    "IPv4Netmask": "",
    "IPv4PrimaryDNS": "",
    "IPv4SecondDNS": "",
    "IPv4Type": "",
    "IPv6Address": "",
    "IPv6Gateway": "",
    "IPv6Prefix": "",
    "IPv6PrimaryDNS": "",
    "IPv6SecondDNS": "",
    "IPv6Type": "",
    "MTU": 1500,
    "MulticastVLANID": "",
    "Nat": 1,
    "Option60Vendor": "",
    "Option120Enable": 0,
    "Option121Enable": 0,
    "Password": "",
    "PortBind": 0,
    "SLAAC": 0,
    "TCPMSS": 0,
    "Username": "",
    "VLAN": "",
    "VLANPriority": 0,
}

INFORM_RESULT_MESSAGES = {
    "0_uploading": "上传中",
    "1_icwmpd_not_running": "CWMP 进程未运行",
    "2_empty_acs_url": "ACS URL 为空",
    "3_tr069_wan_error": "TR069 WAN 连接异常",
    "4_curl_connect_acs_fail": "连接 ACS 失败",
    "5_authentication_fail": "ACS 认证失败",
    "9_unknow_fail": "未知失败",
    "10_success": "成功",
}

LogCallback = Callable[[str], None]


def _emit(on_log: LogCallback | None, message: str) -> None:
    if on_log is not None:
        on_log(message)


def _require_rpc_ok(response: Any, action: str) -> Any:
    if not isinstance(response, list) or not response or response[0] != 0:
        raise UbusError(f"{action} 返回失败：{response}")
    return response


def _require_wan_ok(response: Any) -> Any:
    _require_rpc_ok(response, "WAN operate")
    try:
        result = response[1]["results"][0]["output"][0]["Result"]
    except (IndexError, KeyError, TypeError) as exc:
        raise UbusError(f"WAN operate 返回格式异常：{response}") from exc
    if str(result).upper() != "OK":
        raise UbusError(f"WAN 配置失败：Result={result}")
    return response


def _connection_index(value: str) -> int:
    match = re.match(r"\s*(\d+)", str(value))
    if match is None:
        raise ValueError("现有 WAN 连接名/索引必须以数字索引开头")
    return int(match.group(1))


def parse_port_bind(value: str) -> int:
    """把 ``1&&8&&256`` 或普通整数转换为端口位掩码。"""
    parts = [part.strip() for part in str(value).split("&&")]
    if not parts or any(not part for part in parts):
        raise ValueError("端口绑定格式无效")
    numbers = [int(part) for part in parts]
    if any(number < 0 for number in numbers):
        raise ValueError("端口绑定不能为负数")
    return sum(numbers)


def parse_wan_connection_names(response: Any) -> tuple[str, ...]:
    """从 ``Device.IP.Interface.`` 响应提取可操作的 WAN 连接名。"""
    _require_rpc_ok(response, "WAN connection query")
    payload = response[1] if len(response) > 1 and isinstance(response[1], dict) else {}
    interfaces = payload.get("Interface")
    if not isinstance(interfaces, list):
        ip_payload = payload.get("IP")
        interfaces = ip_payload.get("Interface") if isinstance(ip_payload, dict) else None
    if not isinstance(interfaces, list):
        raise UbusError(f"WAN connection query 返回格式异常：{response}")

    skip_names = {"LAN", "2_OTHER_B_VID_TRANSP"}
    names = {
        str(interface.get("Name", "")).strip()
        for interface in interfaces
        if isinstance(interface, dict)
    }
    filtered = [
        name
        for name in names
        if name and name not in skip_names and re.match(r"^\d+(?:_|$)", name)
    ]
    return tuple(sorted(filtered, key=lambda name: (int(name.split("_", 1)[0]), name)))


def query_wan_connection_names(
    client: UbusHttpClient,
    session_id: str,
    *,
    on_log: LogCallback | None = None,
) -> tuple[str, ...]:
    """读取单台 DUT 的现有 WAN 连接名，不执行任何写操作。"""
    _emit(on_log, f"TX UBUS bbfdm.get path={WAN_INTERFACE_PATH}")
    response = client.bbfdm_get(session_id, WAN_INTERFACE_PATH, WEB_OPTIONAL)
    names = parse_wan_connection_names(response)
    _emit(on_log, f"RX UBUS WAN 连接列表：{list(names)}")
    return names


def build_wan_input(settings: DutWanSettings) -> dict[str, Any]:
    """按 ``Device.X_SDMC_CreateWAN()`` 需要的完整输入构造 payload。"""
    operation = settings.operation.strip().lower()
    payload = dict(WAN_DEFAULT_INPUT)
    if operation == "delete":
        payload.update({"Method": "Delete", "Index": _connection_index(settings.connection_index)})
        return payload

    payload.update(
        {
            "Method": "add" if operation == "add" else "modify",
            "Mode": settings.mode.strip().lower(),
            "ServiceType": settings.service_type.strip().upper(),
            "VLAN": str(int(settings.vlan_id)),
            "VLANPriority": int(settings.vlan_priority),
            "PortBind": parse_port_bind(settings.port_bind),
            "MTU": int(settings.mtu),
            "Nat": 1 if settings.nat_enabled else 0,
        }
    )
    if operation == "modify":
        payload["Index"] = _connection_index(settings.connection_index)

    if payload["Mode"] == "bridge":
        return payload

    payload[settings.access_type.strip()] = "1"
    if settings.access_type == "PPPoE":
        payload["Username"] = settings.pppoe_username
        payload["Password"] = settings.pppoe_password

    protocol = settings.ip_protocol.strip()
    payload["IPProtocol"] = "IPv4AndIPv6" if protocol == "IPv4IPv6" else protocol
    if protocol in {"IPv4", "IPv4IPv6"}:
        payload["IPv4Type"] = settings.ipv4_type
        if settings.ipv4_type == "Static":
            payload.update(
                {
                    "IPv4Address": settings.ipv4_address,
                    "IPv4Netmask": settings.ipv4_netmask,
                    "IPv4Gateway": settings.ipv4_gateway,
                    "IPv4PrimaryDNS": settings.ipv4_primary_dns,
                    "IPv4SecondDNS": settings.ipv4_secondary_dns,
                }
            )
    if protocol in {"IPv6", "IPv4IPv6"}:
        if settings.ipv6_type == "Static":
            payload.update(
                {
                    "IPv6Type": "Static",
                    "IPv6Address": settings.ipv6_address,
                    "IPv6Prefix": settings.ipv6_prefix,
                    "IPv6Gateway": settings.ipv6_gateway,
                    "IPv6PrimaryDNS": settings.ipv6_primary_dns,
                    "IPv6SecondDNS": settings.ipv6_secondary_dns,
                }
            )
        else:
            payload["IPv6Type"] = "Dynamic"
            payload["DHCPv6PrefixDelegation"] = 1
            payload["DHCPv6AddressAssignment"] = 1 if settings.ipv6_type == "DHCPv6" else 0
            payload["SLAAC"] = 1 if settings.ipv6_type == "SLAAC" else 0
    return payload


def configure_wan(
    client: UbusHttpClient,
    session_id: str,
    settings: DutWanSettings,
    *,
    on_log: LogCallback | None = None,
) -> Any:
    payload = build_wan_input(settings)
    _emit(
        on_log,
        "TX UBUS bbfdm.operate "
        f"command={WAN_COMMAND}, input={json.dumps(payload, ensure_ascii=False, sort_keys=True)}",
    )
    response = client.bbfdm_operate(session_id, WAN_COMMAND, payload, WEB_OPTIONAL)
    _require_wan_ok(response)
    _emit(on_log, f"RX UBUS WAN Result=OK，Method={payload['Method']}，Index={payload['Index']}")
    return response


def _set_and_log(
    client: UbusHttpClient,
    session_id: str,
    path: str,
    values: dict[str, Any],
    on_log: LogCallback | None,
) -> Any:
    _emit(on_log, f"TX UBUS bbfdm.set path={path}, obj_path={values}")
    response = client.bbfdm_set(session_id, path, values, WEB_OPTIONAL)
    return _require_rpc_ok(response, f"bbfdm.set {path}")


def configure_voice(
    client: UbusHttpClient,
    session_id: str,
    settings: DutVoiceSettings,
    *,
    on_log: LogCallback | None = None,
) -> dict[str, Any]:
    profile_path = "Device.Services.VoiceService.1.VoIPProfile.1."
    network_path = "Device.Services.VoiceService.1.SIP.Network.1."
    sip_path = "Device.Services.VoiceService.1.SIP."
    client_path = f"Device.Services.VoiceService.1.SIP.Client.{int(settings.line_index)}."
    digit_map_path = "Device.Services.VoiceService.1.Interwork.1.Map.1."

    responses = {
        "profile": _set_and_log(
            client, session_id, profile_path, {"DTMFMethod": settings.dtmf_method}, on_log
        ),
        "network": _set_and_log(
            client,
            session_id,
            network_path,
            {
                "ProxyServer": settings.proxy_server,
                "ProxyServerPort": int(settings.proxy_port),
                "OutboundProxy": settings.outbound_proxy,
                "OutboundProxyPort": int(settings.outbound_proxy_port),
                "RegistrarServer": settings.registrar_server,
                "RegistrarServerPort": int(settings.registrar_server_port),
                "RegisterExpires": int(settings.register_expires),
            },
            on_log,
        ),
        "sip": _set_and_log(
            client,
            session_id,
            sip_path,
            {f"{VENDOR_PREFIX}SIPMode": settings.sip_mode},
            on_log,
        ),
        "account": _set_and_log(
            client,
            session_id,
            client_path,
            {
                "Enable": "1" if settings.account_enabled else "0",
                "AuthUserName": settings.auth_username,
                f"{VENDOR_PREFIX}AuthPassword": settings.auth_password,
                "RegisterURI": settings.display_name,
            },
            on_log,
        ),
    }
    codec_paths = [
        {
            "addr": (
                f"Device.Services.VoiceService.1.SIP.Client.{int(settings.line_index)}."
                f"{VENDOR_PREFIX}Codec.{index}.Codec"
            ),
            "value": codec,
        }
        for index, codec in enumerate(settings.codecs, 1)
    ]
    codec_payload = {"paths": codec_paths, "optional": WEB_OPTIONAL}
    _emit(on_log, f"TX UBUS bbfdm.set paths={codec_paths}")
    responses["codecs"] = _require_rpc_ok(
        client.call(session_id, UBUS_SERVICE_BBFDM, "set", codec_payload),
        "VoIP codec set",
    )
    if settings.digit_map:
        responses["digit_map"] = _set_and_log(
            client, session_id, digit_map_path, {"DigitMap": settings.digit_map}, on_log
        )
    _emit(on_log, f"TX UBUS bbfdm.get path={sip_path}")
    responses["readback"] = _require_rpc_ok(
        client.bbfdm_get(session_id, sip_path, WEB_OPTIONAL), "VoIP readback"
    )
    _emit(on_log, "成功：语音配置已下发并完成 SIP 路径回读")
    return responses


def _management_server_payload(settings: DutTr069Settings) -> dict[str, Any]:
    return {
        "PeriodicInformEnable": bool(settings.periodic_inform_enabled),
        "PeriodicInformInterval": int(settings.periodic_inform_interval),
        "URL": settings.acs_url,
        "Username": settings.acs_username,
        "Password": settings.acs_password,
        "HTTPConnectionRequestEnable": bool(settings.connection_request_enabled),
        "ConnectionRequestUsername": settings.connection_request_username,
        "ConnectionRequestPassword": settings.connection_request_password,
        f"{VENDOR_PREFIX}CertificateEnable": bool(settings.certificate_enabled),
    }


def _extract_management_server(response: Any) -> dict[str, Any]:
    _require_rpc_ok(response, "TR069 readback")
    if len(response) < 2 or not isinstance(response[1], dict):
        raise UbusError(f"TR069 回读格式异常：{response}")
    payload = response[1]
    nested = payload.get("ManagementServer")
    return nested if isinstance(nested, dict) else payload


def configure_tr069(
    client: UbusHttpClient,
    session_id: str,
    settings: DutTr069Settings,
    *,
    on_log: LogCallback | None = None,
    stop_requested: Callable[[], bool] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    inform_timeout: float = 60.0,
) -> dict[str, Any]:
    values = _management_server_payload(settings)
    response = _set_and_log(client, session_id, MANAGEMENT_SERVER_PATH, values, on_log)
    _emit(on_log, f"TX UBUS bbfdm.get path={MANAGEMENT_SERVER_PATH}")
    readback_response = client.bbfdm_get(session_id, MANAGEMENT_SERVER_PATH, WEB_OPTIONAL)
    readback = _extract_management_server(readback_response)
    mismatches = [key for key, value in values.items() if key in readback and readback[key] != value]
    if mismatches:
        raise UbusError(f"TR069 回读不一致：{', '.join(mismatches)}")
    result: dict[str, Any] = {"set": response, "readback": readback_response}
    _emit(on_log, "成功：TR069 参数已下发并完成 ManagementServer 回读")
    if not settings.manual_inform:
        _emit(on_log, "跳过：未勾选配置后手动 Inform")
        return result

    inform_payload = {"path": MANUAL_INFORM_STAGE_PATH, "value": "1_wait_inform", "optional": WEB_OPTIONAL}
    _emit(on_log, f"TX UBUS bbfdm.set path={MANUAL_INFORM_STAGE_PATH}, value=1_wait_inform")
    result["inform_trigger"] = _require_rpc_ok(
        client.call(session_id, UBUS_SERVICE_BBFDM, "set", inform_payload),
        "TR069 manual inform trigger",
    )
    deadline = time.monotonic() + max(1.0, float(inform_timeout))
    while time.monotonic() < deadline:
        if stop_requested is not None and stop_requested():
            raise InterruptedError("用户停止了 TR069 Inform 等待")
        stage_response = client.bbfdm_get(session_id, MANUAL_INFORM_STAGE_PATH, WEB_OPTIONAL)
        _require_rpc_ok(stage_response, "TR069 inform stage")
        stage_payload = stage_response[1] if len(stage_response) > 1 and isinstance(stage_response[1], dict) else {}
        stage = stage_payload.get(VENDOR_PREFIX + "ManualInformStage", stage_payload.get("ManualInformStage", ""))
        _emit(on_log, f"RX UBUS TR069 Inform 状态：{stage or '未知'}")
        if stage == "3_finish_inform":
            result_response = client.bbfdm_get(session_id, INFORM_RESULT_PATH, WEB_OPTIONAL)
            _require_rpc_ok(result_response, "TR069 inform result")
            result_payload = result_response[1] if len(result_response) > 1 and isinstance(result_response[1], dict) else {}
            code = result_payload.get(VENDOR_PREFIX + "InformResult", result_payload.get("InformResult", ""))
            message = INFORM_RESULT_MESSAGES.get(str(code), f"未知结果 {code}")
            if code != "10_success":
                raise UbusError(f"TR069 Inform 失败：{message}")
            _emit(on_log, "成功：TR069 手动 Inform 已完成")
            result["inform_result"] = result_response
            return result
        sleep_fn(1.0)
    raise UbusError(f"TR069 Inform 等待超时（{inform_timeout:g} 秒）")


__all__ = [
    "INFORM_RESULT_MESSAGES",
    "MANAGEMENT_SERVER_PATH",
    "WAN_COMMAND",
    "WAN_INTERFACE_PATH",
    "build_wan_input",
    "configure_tr069",
    "configure_voice",
    "configure_wan",
    "parse_wan_connection_names",
    "parse_port_bind",
    "query_wan_connection_names",
]
