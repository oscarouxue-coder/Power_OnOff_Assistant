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

from src.models.dut_config_models import (
    DutTr069Settings,
    DutVoiceSettings,
    DutWanConnectionInfo,
    DutWanSettings,
)

from .ubus_http_client import UBUS_SERVICE_BBFDM, UbusError, UbusHttpClient


VENDOR_PREFIX = "X_SDMC_"
WAN_COMMAND = f"Device.{VENDOR_PREFIX}CreateWAN()"
WAN_INTERFACE_PATH = "Device.IP.Interface."
WAN_QUERY_PATHS = (
    "Device.WiFi.SSID.",
    "Device.Ethernet.",
    WAN_INTERFACE_PATH,
    "Device.PPP.",
    "Device.Bridging.Bridge.",
    "Device.DHCPv4.",
    "Device.DHCPv6.",
    "Device.DNS.Client.Server.",
    "Device.NAT.",
)
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


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = _as_text(value).lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return None


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _payload_from_response(response: Any) -> dict[str, Any]:
    _require_rpc_ok(response, "WAN connection query")
    payload = response[1] if len(response) > 1 and isinstance(response[1], dict) else {}
    return payload


def _interface_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    interfaces = payload.get("Interface")
    if not isinstance(interfaces, list):
        ip_payload = payload.get("IP")
        interfaces = ip_payload.get("Interface") if isinstance(ip_payload, dict) else None
    if not isinstance(interfaces, list):
        raise UbusError(f"WAN connection query 返回格式异常：{payload}")
    return [item for item in interfaces if isinstance(item, dict)]


def _nested_list(payload: dict[str, Any], parent: str, child: str) -> list[dict[str, Any]]:
    container = payload.get(parent)
    values = container.get(child) if isinstance(container, dict) else None
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _named_wan_interfaces(payload: dict[str, Any]) -> list[dict[str, Any]]:
    skip_names = {"LAN", "2_OTHER_B_VID_TRANSP"}
    return [
        interface
        for interface in _interface_list(payload)
        if (_as_text(interface.get("Name")) not in skip_names)
        and re.match(r"^\d+(?:_|$)", _as_text(interface.get("Name")))
    ]


def _name_parts(name: str) -> tuple[str, str, str, str]:
    match = re.match(r"^(\d+)_(.+)_([RB])_VID_([^_]+)$", name, re.IGNORECASE)
    if match is None:
        index = re.match(r"^(\d+)", name)
        return (index.group(1) if index else "", "", "", "")
    return match.group(1), match.group(2).upper(), match.group(3).upper(), match.group(4)


def _instance_matches(item: dict[str, Any], instance: str) -> bool:
    return _as_text(_first(item, f"{VENDOR_PREFIX}Instance", "Instance")) == instance


def _find_vlan_termination(
    payload: dict[str, Any], lower_layers: str
) -> dict[str, Any] | None:
    vlan_path = lower_layers
    if lower_layers.startswith("Device.PPP.Interface."):
        ppp_instance = lower_layers.rsplit(".", 1)[-1]
        ppp = next(
            (item for item in _nested_list(payload, "PPP", "Interface") if _instance_matches(item, ppp_instance)),
            None,
        )
        vlan_path = _as_text(ppp.get("LowerLayers")) if ppp else ""
    match = re.search(r"Device\.Ethernet\.VLANTermination\.(\d+)", vlan_path)
    if match is None:
        return None
    instance = match.group(1)
    return next(
        (
            item
            for item in _nested_list(payload, "Ethernet", "VLANTermination")
            if _instance_matches(item, instance)
        ),
        None,
    )


def _find_bridge_vlan(payload: dict[str, Any], lower_layers: str) -> dict[str, Any] | None:
    match = re.match(r"Device\.Ethernet\.Link\.(\d+)", lower_layers)
    if match is None:
        return None
    link = next(
        (
            item
            for item in _nested_list(payload, "Ethernet", "Link")
            if _instance_matches(item, match.group(1))
        ),
        None,
    )
    bridge_path = _as_text(link.get("LowerLayers")) if link else ""
    bridge_match = re.match(r"Device\.Bridging\.Bridge\.(\d+)", bridge_path)
    if bridge_match is None:
        return None
    bridges = payload.get("Bridge")
    if not isinstance(bridges, list):
        bridging = payload.get("Bridging")
        bridges = bridging.get("Bridge") if isinstance(bridging, dict) else None
    bridge = next(
        (
            item
            for item in bridges or []
            if isinstance(item, dict) and _instance_matches(item, bridge_match.group(1))
        ),
        None,
    )
    vlans = bridge.get("VLAN") if bridge else None
    return next((item for item in vlans or [] if isinstance(item, dict)), None)


def _port_bind_mask(value: Any) -> str:
    text = _as_text(value)
    if not text:
        return "0"
    if text.isdigit():
        return text
    mask = 0
    matched = False
    for path in (part.strip() for part in text.split(",")):
        lan_match = re.fullmatch(r"Device\.Ethernet\.Interface\.(\d+)", path)
        if lan_match:
            port = int(lan_match.group(1))
            if 1 <= port <= 8:
                mask |= 1 << (port - 1)
                matched = True
            continue
        wifi_match = re.fullmatch(r"Device\.WiFi\.SSID\.(\d+)", path)
        if wifi_match:
            wifi_flags = {1: 256, 2: 512, 5: 2048, 6: 4096}
            flag = wifi_flags.get(int(wifi_match.group(1)))
            if flag is not None:
                mask |= flag
                matched = True
    return str(mask) if matched else "0"


def _dns_for_interface(payload: dict[str, Any], interface_path: str) -> tuple[list[str], list[str]]:
    ipv4: list[str] = []
    ipv6: list[str] = []
    servers = _nested_list(payload, "DNS", "Client")
    if servers:
        nested = servers[0].get("Server")
        servers = [item for item in nested if isinstance(item, dict)] if isinstance(nested, list) else []
    if not servers:
        direct = payload.get("Server")
        servers = [item for item in direct if isinstance(item, dict)] if isinstance(direct, list) else []
    for item in servers:
        if _as_text(item.get("Interface")) != interface_path:
            continue
        address = _as_text(_first(item, "DNSServer", "IPAddress"))
        if address:
            (ipv6 if ":" in address else ipv4).append(address)
    return ipv4, ipv6


def _address_details(
    interface: dict[str, Any], payload: dict[str, Any], interface_path: str
) -> dict[str, str]:
    ipv4_enabled = _as_bool(_first(interface, "IPv4Enable")) is True
    ipv6_enabled = _as_bool(_first(interface, "IPv6Enable")) is True
    protocol = "IPv4IPv6" if ipv4_enabled and ipv6_enabled else "IPv4" if ipv4_enabled else "IPv6" if ipv6_enabled else ""
    direct_protocol = _as_text(_first(interface, "IPProtocol"))
    if direct_protocol:
        protocol = "IPv4IPv6" if direct_protocol in {"IPv4AndIPv6", "IPv4/IPv6"} else direct_protocol

    ipv4_dns, ipv6_dns = _dns_for_interface(payload, interface_path)
    ipv4_addresses = interface.get("IPv4Address")
    ipv4_list = [item for item in ipv4_addresses if isinstance(item, dict)] if isinstance(ipv4_addresses, list) else []
    static_v4 = next(
        (
            item
            for item in ipv4_list
            if _as_text(_first(item, "AddressingType", "Origin")).lower() == "static"
        ),
        None,
    )
    direct_v4_type = _as_text(_first(interface, "IPv4Type"))
    ipv4_type = direct_v4_type or ("Static" if static_v4 else "Dynamic" if ipv4_enabled else "")
    ipv4_item = static_v4 or (ipv4_list[0] if ipv4_list else {})

    ipv6_addresses = interface.get("IPv6Address")
    ipv6_list = [item for item in ipv6_addresses if isinstance(item, dict)] if isinstance(ipv6_addresses, list) else []
    static_v6 = next(
        (item for item in ipv6_list if _as_text(_first(item, "AddressingType", "Origin")).lower() == "static"),
        None,
    )
    direct_v6_type = _as_text(_first(interface, "IPv6Type"))
    ipv6_type = direct_v6_type or ("Static" if static_v6 else "Dynamic" if ipv6_enabled else "")
    if ipv6_type == "Dynamic":
        dhcpv6 = next(
            (
                item
                for item in _nested_list(payload, "DHCPv6", "Client")
                if _as_text(item.get("Interface")) == interface_path
            ),
            None,
        )
        if dhcpv6:
            request_address = _as_bool(dhcpv6.get("RequestAddresses")) is True
            accept_ra = _as_bool(dhcpv6.get(f"{VENDOR_PREFIX}AcceptRAPrefixes")) is True
            ipv6_type = "DHCPv6" if request_address and not accept_ra else "SLAAC" if accept_ra else "DHCPv6"
        else:
            ipv6_type = "SLAAC"
    ipv6_item = static_v6 or (ipv6_list[0] if ipv6_list else {})
    prefixes = interface.get("IPv6Prefix")
    prefix_list = [item for item in prefixes if isinstance(item, dict)] if isinstance(prefixes, list) else []
    static_prefix = next(
        (item for item in prefix_list if _as_text(_first(item, "Origin", "AddressingType")).lower() == "static"),
        prefix_list[0] if prefix_list else {},
    )
    return {
        "ip_protocol": protocol,
        "ipv4_type": ipv4_type,
        "ipv4_address": _as_text(_first(ipv4_item, "IPAddress", "Address")),
        "ipv4_netmask": _as_text(_first(ipv4_item, "SubnetMask", "Netmask")),
        "ipv4_gateway": _as_text(_first(ipv4_item, f"{VENDOR_PREFIX}DefaultGateway", "Gateway")),
        "ipv4_primary_dns": ipv4_dns[0] if ipv4_dns else _as_text(_first(interface, "IPv4PrimaryDNS")),
        "ipv4_secondary_dns": ipv4_dns[1] if len(ipv4_dns) > 1 else _as_text(_first(interface, "IPv4SecondDNS")),
        "ipv6_type": ipv6_type,
        "ipv6_address": _as_text(_first(ipv6_item, "IPAddress", "Address")),
        "ipv6_prefix": _as_text(_first(static_prefix, "Prefix")),
        "ipv6_gateway": _as_text(_first(ipv6_item, f"{VENDOR_PREFIX}DefaultGateway", "Gateway")),
        "ipv6_primary_dns": ipv6_dns[0] if ipv6_dns else _as_text(_first(interface, "IPv6PrimaryDNS")),
        "ipv6_secondary_dns": ipv6_dns[1] if len(ipv6_dns) > 1 else _as_text(_first(interface, "IPv6SecondDNS")),
    }


def parse_wan_connections(response: Any) -> tuple[DutWanConnectionInfo, ...]:
    """把 WAN 多路径只读响应解析为可直接回填界面的配置快照。"""
    payload = _payload_from_response(response)
    connections: list[DutWanConnectionInfo] = []
    for interface in _named_wan_interfaces(payload):
        name = _as_text(interface.get("Name"))
        name_index, name_service, name_mode, name_vlan = _name_parts(name)
        index = _as_text(_first(interface, f"{VENDOR_PREFIX}Instance", "Instance")) or name_index
        interface_path = f"Device.IP.Interface.{index}"
        lower_layers = _as_text(interface.get("LowerLayers"))
        mode = "bridge" if lower_layers.startswith("Device.Ethernet.Link.") or name_mode == "B" else "router"
        access_type = "" if mode == "bridge" else "PPPoE" if lower_layers.startswith("Device.PPP.Interface.") else "IPoE"
        vlan_term = _find_vlan_termination(payload, lower_layers)
        bridge_vlan = _find_bridge_vlan(payload, lower_layers) if mode == "bridge" else None
        vlan_id = _as_text(_first(interface, "VLAN", "VLANID", f"{VENDOR_PREFIX}VLANID"))
        vlan_priority = _as_text(_first(interface, "VLANPriority", f"{VENDOR_PREFIX}VLANPriority"))
        if vlan_term:
            vlan_id = _as_text(_first(vlan_term, "VLANID", "VLAN")) or vlan_id
            vlan_priority = _as_text(_first(vlan_term, "VLANPriority", f"{VENDOR_PREFIX}VLANPriority")) or vlan_priority
        elif bridge_vlan:
            vlan_id = _as_text(_first(bridge_vlan, "VLANID", "VLAN")) or vlan_id
            vlan_priority = _as_text(_first(bridge_vlan, f"{VENDOR_PREFIX}VLANPriority", "VLANPriority")) or vlan_priority
        if not vlan_id and name_vlan.upper() != "TRANSP":
            vlan_id = name_vlan

        ppp: dict[str, Any] = {}
        if lower_layers.startswith("Device.PPP.Interface."):
            ppp_instance = lower_layers.rsplit(".", 1)[-1]
            ppp = next(
                (item for item in _nested_list(payload, "PPP", "Interface") if _instance_matches(item, ppp_instance)),
                {},
            )
        nat_settings = _nested_list(payload, "NAT", "InterfaceSetting")
        nat_item = next(
            (
                item
                for item in nat_settings
                if _instance_matches(item, index)
                or _as_text(item.get("Interface")) in {interface_path, name}
            ),
            None,
        )
        nat_enabled = _as_bool(nat_item.get("Enable")) if nat_item else _as_bool(_first(interface, "Nat", f"{VENDOR_PREFIX}Nat"))
        address = _address_details(interface, payload, interface_path)
        mtu = _as_text(_first(interface, "MaxMTUSize", "MTU"))
        if not mtu and mode == "router":
            mtu = "1492" if access_type == "PPPoE" else "1500"
        connections.append(
            DutWanConnectionInfo(
                name=name,
                index=index,
                mode=mode,
                service_type=_as_text(_first(interface, f"{VENDOR_PREFIX}ServiceType", "ServiceType")).upper() or name_service,
                vlan_id=vlan_id,
                vlan_priority=vlan_priority or "0",
                port_bind=_port_bind_mask(_first(interface, f"{VENDOR_PREFIX}PortBind", "PortBind")),
                mtu=mtu,
                nat_enabled=nat_enabled,
                access_type=access_type,
                pppoe_username=_as_text(ppp.get("Username")),
                pppoe_password=_as_text(_first(ppp, f"{VENDOR_PREFIX}Password", "Password")),
                **address,
            )
        )
    unique = {item.name: item for item in connections}
    return tuple(sorted(unique.values(), key=lambda item: (int(item.index or "0"), item.name)))


def query_wan_connections(
    client: UbusHttpClient,
    session_id: str,
    *,
    on_log: LogCallback | None = None,
) -> tuple[DutWanConnectionInfo, ...]:
    """一次只读多路径查询获得现有 WAN 名称及完整配置。"""
    _emit(on_log, f"TX UBUS bbfdm.get paths={list(WAN_QUERY_PATHS)}")
    response = client.call(
        session_id,
        UBUS_SERVICE_BBFDM,
        "get",
        {"paths": list(WAN_QUERY_PATHS), "optional": WEB_OPTIONAL},
    )
    connections = parse_wan_connections(response)
    summaries = [
        f"{item.name}(业务={item.service_type or '-'}, VLAN={item.vlan_id or '-'}, "
        f"模式={item.mode or '-'}, 接入={item.access_type or '-'})"
        for item in connections
    ]
    _emit(on_log, f"RX UBUS WAN 完整信息：{summaries}")
    return connections


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
    "query_wan_connections",
    "parse_wan_connections",
]
