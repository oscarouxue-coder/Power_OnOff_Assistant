from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class ParameterDefinition:
    label: str
    column: str
    command: str
    sensitive: bool = False
    legacy_columns: tuple[str, ...] = ()


STANDARD_PARAMETER_DEFINITIONS: tuple[ParameterDefinition, ...] = (
    ParameterDefinition("SN", "SN", "ppctl set SERIAL_NUMBER="),
    ParameterDefinition("XPON SN", "GPON SN", "ppctl set XPON_SN="),
    ParameterDefinition("MAC", "MAC", "ppctl set LAN_BASE_MAC_ADDRESS="),
    ParameterDefinition("2.4主SSID", "2.4G SSID", "ppctl set WIFI_SSID_24G1="),
    ParameterDefinition("2.4主SSID密码", "2.4G WiFi Password", "ppctl set WIFI_KEY_24G1=", True, ("WiFi Password",)),
    ParameterDefinition("5G主SSID", "5G SSID", "ppctl set WIFI_SSID_5G1="),
    ParameterDefinition("5G主SSID密码", "5G WiFi Password", "ppctl set WIFI_KEY_5G1=", True, ("WiFi Password",)),
    ParameterDefinition("2.4G国家码", "2.4G Country Code", "ppctl set WIFI_CCODE_24G=", False, ("Country code",)),
    ParameterDefinition("5G国家码", "5G Country Code", "ppctl set WIFI_CCODE_5G=", False, ("Country code",)),
    ParameterDefinition("产品名", "Product Class", "ppctl set PRODUCT_CLASS="),
    ParameterDefinition("super用户账号", "Superuser Name", "ppctl set SUPER_USERNAME="),
    ParameterDefinition("super用户密码", "Superuser Password", "ppctl set SUPER_PASSWORD=", True),
    ParameterDefinition("普通用户账号", "User Name", "ppctl set USER_USERNAME="),
    ParameterDefinition("普通用户密码", "User Password", "ppctl set USER_PASSWORD=", True, ("Password",)),
    ParameterDefinition("IP地址", "IP", "ppctl set LAN_IP_ADDRESS="),
)

PARAMETER_COLUMNS: tuple[str, ...] = tuple(item.column for item in STANDARD_PARAMETER_DEFINITIONS)
VLAN_COLUMN = "VLAN"


@dataclass(frozen=True)
class SampleParameterRecord:
    vlan: str
    values: Mapping[str, str]
    source_row: int = 0


@dataclass(frozen=True)
class SampleParameterTarget:
    vlan: str
    serial_port: str
    record: SampleParameterRecord


@dataclass(frozen=True)
class SampleParameterWriteRequest:
    vlan: str
    serial_port: str
    initial_username: str
    initial_password: str
    values: Mapping[str, str]
    # telnet + UBUS 启用前置字段。串口路径下填空,ubus_port 默认 80。
    bind_ip: str = ""
    device_host: str = ""
    ubus_port: int = 80
    # 工厂模式第二次登录所需的网络切换字段(样机进入工厂模式重启后管理 IP 切到另一网段);
    # telnet 路径下必备。串口路径可填空,service 层不消费。
    factory_bind_ip: str = ""
    factory_device_host: str = ""


@dataclass(frozen=True)
class SampleParameterItemResult:
    request: SampleParameterWriteRequest
    ok: bool
    message: str
    written_count: int = 0
    failed_labels: tuple[str, ...] = ()
    cancelled: bool = False


@dataclass(frozen=True)
class ParameterTablePreflight:
    targets: tuple[SampleParameterTarget, ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.targets)


@dataclass(frozen=True)
class ParameterGenerationTemplate:
    sn_prefix: str
    xpon_prefix: str
    ssid_24_prefix: str
    ssid_5_prefix: str
    suffix_length: int
    fixed_values: Mapping[str, str] = field(default_factory=dict)
