"""DUT 配置业务模型。"""
from __future__ import annotations

from dataclasses import dataclass


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


__all__ = ["DutTelnetEnableRequest", "DutTelnetEnableResult"]
