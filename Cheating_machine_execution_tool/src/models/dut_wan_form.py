"""Unchanged WAN presentation rules shared by Tk and Qt; no GUI imports."""
from __future__ import annotations
from collections.abc import Iterable
from dataclasses import dataclass
from src.models.dut_config_models import DutWanConnectionInfo

WAN_ROUTER_SERVICE_TYPES = (
    "INTERNET",
    "TR069",
    "VOICE",
    "TR069_VOICE",
    "TR069_INTERNET",
    "VOICE_INTERNET",
    "TR069_VOICE_INTERNET",
    "IPTV",
    "OTHER",
)

WAN_BRIDGE_SERVICE_TYPES = ("IPTV", "INTERNET", "OTHER")

WAN_LAN_PORTS = tuple(range(1, 9))

WAN_LAN_PORT_MASK = sum(1 << (port - 1) for port in WAN_LAN_PORTS)

def _port_bind_mask_value(value: str) -> int:
    """把查询值或旧组合文本转换为非负位掩码；无效值按 0 处理。"""
    try:
        parts = [part.strip() for part in str(value).split("&&")]
        if not parts or any(not part for part in parts):
            return 0
        mask = sum(int(part) for part in parts)
        return mask if mask >= 0 else 0
    except (TypeError, ValueError):
        return 0

def wan_lan_ports_from_port_bind(value: str) -> tuple[int, ...]:
    """把 ``PortBind`` 位掩码转换为界面应勾选的 LAN1–LAN8。"""
    mask = _port_bind_mask_value(value)
    return tuple(port for port in WAN_LAN_PORTS if mask & (1 << (port - 1)))

def wan_port_bind_from_lan_ports(
    ports: Iterable[int], *, preserved_mask: int = 0
) -> str:
    """把已勾选 LAN 口转换为 UBUS 位掩码，并保留不在界面展示的旧绑定。"""
    mask = max(0, int(preserved_mask))
    for port in ports:
        if port in WAN_LAN_PORTS:
            mask |= 1 << (port - 1)
    return str(mask)

@dataclass(frozen=True)
class WanFormRules:
    """WAN 当前选择对应的可见字段；不包含任何 UBUS 业务执行。"""

    show_index: bool
    show_config: bool
    show_router: bool
    show_pppoe_credentials: bool
    show_multicast_vlan: bool
    show_ipv4_selector: bool
    show_ipv4_static: bool
    show_ipv6_selector: bool
    show_ipv6_static: bool
    mtu_default: str

def normalize_wan_address_modes(
    access_type: str,
    ip_protocol: str,
    ipv4_type: str,
    ipv6_type: str,
    *,
    changed: str = "",
) -> tuple[str, str]:
    """把地址方式收敛到 WAN 协议封装实际支持的组合。"""
    if access_type == "PPPoE":
        return "DHCP", ipv6_type if ipv6_type in {"SLAAC", "DHCPv6"} else "SLAAC"
    if ip_protocol != "IPv4+IPv6（双栈）":
        return ipv4_type, ipv6_type
    if changed == "ipv4_type":
        return ("静态", "静态") if ipv4_type == "静态" else ("DHCP", "SLAAC" if ipv6_type == "静态" else ipv6_type)
    if changed == "ipv6_type":
        return ("静态", "静态") if ipv6_type == "静态" else ("DHCP" if ipv4_type == "静态" else ipv4_type, ipv6_type)
    if "静态" in {ipv4_type, ipv6_type}:
        return "静态", "静态"
    return "DHCP", ipv6_type

def resolve_wan_form_rules(
    operation: str,
    mode: str,
    access_type: str,
    ip_protocol: str,
    ipv4_type: str,
    ipv6_type: str,
    service_type: str = "",
) -> WanFormRules:
    """返回 WAN 表单显隐规则，供 Tk 界面和无界面测试共同使用。"""
    show_config = operation != "删除"
    show_router = show_config and mode == "路由"
    show_ipv4 = show_router and ip_protocol in {"IPv4", "IPv4+IPv6（双栈）"}
    show_ipv6 = show_router and ip_protocol in {"IPv6", "IPv4+IPv6（双栈）"}
    return WanFormRules(
        show_index=operation in {"修改", "删除"},
        show_config=show_config,
        show_router=show_router,
        show_pppoe_credentials=show_router and access_type == "PPPoE",
        show_multicast_vlan=show_config and service_type.strip().upper() == "IPTV",
        show_ipv4_selector=show_ipv4,
        show_ipv4_static=show_ipv4 and ipv4_type == "静态",
        show_ipv6_selector=show_ipv6,
        show_ipv6_static=show_ipv6 and ipv6_type == "静态",
        mtu_default="1492" if access_type == "PPPoE" else "1500",
    )

def wan_connection_form_values(info: DutWanConnectionInfo) -> dict[str, str | bool | None]:
    """把业务模型值转换为 WAN 表单使用的中文枚举和值。"""
    protocol = {
        "IPv4AndIPv6": "IPv4+IPv6（双栈）",
        "IPv4/IPv6": "IPv4+IPv6（双栈）",
        "IPv4IPv6": "IPv4+IPv6（双栈）",
    }.get(info.ip_protocol, info.ip_protocol)
    return {
        "mode": "桥接" if info.mode.lower() == "bridge" else "路由" if info.mode else "",
        "service_type": info.service_type.replace("-", "_").upper(),
        "vlan_id": info.vlan_id,
        "multicast_vlan_id": info.multicast_vlan_id,
        "vlan_priority": info.vlan_priority,
        "port_bind": info.port_bind,
        "mtu": info.mtu,
        "nat_enabled": info.nat_enabled,
        "access_type": info.access_type,
        "ip_protocol": protocol,
        "ipv4_type": "静态" if info.ipv4_type.lower() == "static" else "DHCP" if info.ipv4_type else "",
        "ipv4_address": info.ipv4_address,
        "ipv4_netmask": info.ipv4_netmask,
        "ipv4_gateway": info.ipv4_gateway,
        "ipv4_primary_dns": info.ipv4_primary_dns,
        "ipv4_secondary_dns": info.ipv4_secondary_dns,
        "ipv6_type": "静态" if info.ipv6_type.lower() == "static" else info.ipv6_type,
        "ipv6_address": info.ipv6_address,
        "ipv6_prefix": info.ipv6_prefix,
        "ipv6_gateway": info.ipv6_gateway,
        "ipv6_primary_dns": info.ipv6_primary_dns,
        "ipv6_secondary_dns": info.ipv6_secondary_dns,
        "pppoe_username": info.pppoe_username,
        "pppoe_password": info.pppoe_password,
    }
