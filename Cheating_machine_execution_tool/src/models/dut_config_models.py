"""DUT 配置业务模型。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DutTelnetEnableRequest:
    """对单台 DUT 通过 UBUS 开启 Telnet 所需的完整连接信息。"""

    channel: str
    vlan: str
    adapter_alias: str
    bind_ip: str
    device_host: str
    subnet_mask: str
    username: str
    password: str
    ubus_port: int = 80


@dataclass(frozen=True)
class DutTelnetEnableResult:
    """单台 DUT 的最终执行结果。"""

    request: DutTelnetEnableRequest
    ok: bool
    stage: str
    message: str
    action: str = ""


@dataclass(frozen=True)
class DutTelnetStatus:
    """DUT当前Telnet访问控制规则与TCP 23状态。"""

    access_control_enabled: bool = False
    rule_present: bool = False
    rule_enabled: bool = False
    source_interfaces: tuple[str, ...] = ()
    tcp_port_open: bool = False
    probe_message: str = ""


@dataclass(frozen=True)
class DutWanSettings:
    """一批 DUT 共用的 WAN 操作参数。"""

    operation: str = "add"  # add / modify / delete
    connection_index: str = ""
    mode: str = "router"  # router / bridge
    service_type: str = "INTERNET"
    vlan_id: str = ""
    multicast_vlan_id: str = ""
    vlan_priority: str = "0"
    port_bind: str = "0"
    mtu: str = "1500"
    nat_enabled: bool = True
    access_type: str = "IPoE"  # IPoE / PPPoE
    ip_protocol: str = "IPv4"  # IPv4 / IPv6 / IPv4IPv6
    ipv4_type: str = "Dynamic"  # Dynamic / Static
    ipv4_address: str = ""
    ipv4_netmask: str = ""
    ipv4_gateway: str = ""
    ipv4_primary_dns: str = ""
    ipv4_secondary_dns: str = ""
    ipv6_type: str = "SLAAC"  # SLAAC / DHCPv6 / Static
    ipv6_address: str = ""
    ipv6_prefix: str = ""
    ipv6_gateway: str = ""
    ipv6_primary_dns: str = ""
    ipv6_secondary_dns: str = ""
    pppoe_username: str = ""
    pppoe_password: str = ""


@dataclass(frozen=True)
class DutWanConnectionInfo:
    """从 DUT 只读查询得到、可回填 WAN 表单的现有连接快照。"""

    name: str
    index: str = ""
    mode: str = ""
    service_type: str = ""
    vlan_id: str = ""
    multicast_vlan_id: str = ""
    vlan_priority: str = ""
    port_bind: str = ""
    mtu: str = ""
    nat_enabled: bool | None = None
    access_type: str = ""
    ip_protocol: str = ""
    ipv4_type: str = ""
    ipv4_address: str = ""
    ipv4_netmask: str = ""
    ipv4_gateway: str = ""
    ipv4_primary_dns: str = ""
    ipv4_secondary_dns: str = ""
    ipv6_type: str = ""
    ipv6_address: str = ""
    ipv6_prefix: str = ""
    ipv6_gateway: str = ""
    ipv6_primary_dns: str = ""
    ipv6_secondary_dns: str = ""
    pppoe_username: str = ""
    pppoe_password: str = ""


@dataclass(frozen=True)
class DutWanQueryResult:
    """单台 DUT 的现有 WAN 名称与配置快照查询结果。"""

    request: DutTelnetEnableRequest
    ok: bool
    stage: str
    message: str
    connection_names: tuple[str, ...] = ()
    connections: tuple[DutWanConnectionInfo, ...] = ()


@dataclass(frozen=True)
class DutVoiceSettings:
    """一批 DUT 共用的 SIP/VoIP 参数。"""

    line_index: str = "1"
    account_enabled: bool = True
    display_name: str = ""
    auth_username: str = ""
    auth_password: str = ""
    proxy_server: str = ""
    proxy_port: str = "5060"
    outbound_proxy: str = ""
    outbound_proxy_port: str = "5060"
    registrar_server: str = ""
    registrar_server_port: str = "5060"
    dtmf_method: str = "RFC2833"
    register_expires: str = "3600"
    sip_mode: str = "SIP"
    digit_map: str = "x."
    codecs: tuple[str, ...] = (
        "G.711 U-law",
        "G.711 A-law",
        "G.729",
        "G.722",
        "G.723",
    )


@dataclass(frozen=True)
class DutTr069Settings:
    """一批 DUT 共用的 TR069/CWMP 参数。"""

    acs_url: str = ""
    acs_username: str = ""
    acs_password: str = ""
    periodic_inform_enabled: bool = True
    periodic_inform_interval: str = "86400"
    connection_request_enabled: bool = True
    connection_request_username: str = ""
    connection_request_password: str = ""
    certificate_enabled: bool = False
    manual_inform: bool = False


@dataclass(frozen=True)
class DutAdvancedConfigRequest:
    """WAN/语音/TR069 共用的单台连接信息和功能参数。"""

    channel: str
    vlan: str
    adapter_alias: str
    bind_ip: str
    device_host: str
    subnet_mask: str
    username: str
    password: str
    feature: str
    settings: DutWanSettings | DutVoiceSettings | DutTr069Settings
    ubus_port: int = 80


@dataclass(frozen=True)
class DutAdvancedConfigResult:
    """WAN/语音/TR069 单台最终执行结果。"""

    request: DutAdvancedConfigRequest
    ok: bool
    stage: str
    message: str
    details: Any = None


@dataclass(frozen=True)
class DutAdvancedQueryResult:
    """语音/TR069单台只读状态查询结果。"""

    request: DutTelnetEnableRequest
    feature: str
    ok: bool
    stage: str
    message: str
    settings: DutTelnetStatus | DutVoiceSettings | DutTr069Settings | None = None


__all__ = [
    "DutAdvancedConfigRequest",
    "DutAdvancedConfigResult",
    "DutAdvancedQueryResult",
    "DutTelnetEnableRequest",
    "DutTelnetEnableResult",
    "DutTelnetStatus",
    "DutTr069Settings",
    "DutVoiceSettings",
    "DutWanConnectionInfo",
    "DutWanQueryResult",
    "DutWanSettings",
]
