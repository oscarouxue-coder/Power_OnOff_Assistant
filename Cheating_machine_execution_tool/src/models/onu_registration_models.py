from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
from typing import Optional, Sequence


OLT_FAMILY_C300 = "C300"
OLT_FAMILY_C600 = "C600"
OLT_FAMILIES = (OLT_FAMILY_C300, OLT_FAMILY_C600)


@dataclass(frozen=True)
class OltConnection:
    host: str
    source_ip: str
    username: str
    password: str
    port: int = 23
    timeout: float = 10.0

    def validate(self) -> list[str]:
        errors: list[str] = []
        try:
            ipaddress.ip_address((self.host or "").strip())
        except ValueError:
            errors.append("OLT IP 必须是有效地址")
        try:
            ipaddress.ip_address((self.source_ip or "").strip())
        except ValueError:
            errors.append("源 IP 必须是有效地址，ONU 注册不允许使用系统默认网卡")
        if not 1 <= self.port <= 65535:
            errors.append("Telnet 端口必须在 1-65535 之间")
        if not (self.username or "").strip():
            errors.append("OLT 用户名不能为空")
        if not self.password:
            errors.append("OLT 密码不能为空")
        if not 2 <= self.timeout <= 120:
            errors.append("超时时间必须在 2-120 秒之间")
        return errors


@dataclass(frozen=True)
class OnuDiscoveryScope:
    shelf: int = 1
    slot: int = 1
    pon: int = 1

    def validate(self) -> list[str]:
        errors: list[str] = []
        for label, value in (("机框", self.shelf), ("槽位", self.slot), ("PON 口", self.pon)):
            if not 1 <= value <= 64:
                errors.append(f"{label}必须在 1-64 之间")
        return errors


@dataclass(frozen=True)
class OnuServiceMapping:
    service_id: int
    vlan: int


@dataclass(frozen=True)
class DiscoveredOnu:
    family: str
    pon_interface: str
    serial_number: str
    onu_interface: str = ""
    suggested_onu_id: Optional[int] = None
    model: str = ""
    speed_mode: str = ""
    state: str = ""

    @property
    def display_text(self) -> str:
        interface = self.onu_interface or self.pon_interface
        details = [interface]
        if self.model:
            details.append(f"型号:{self.model}")
        details.append(f"SN:{self.serial_number}")
        if self.speed_mode:
            details.append(f"速率:{self.speed_mode}")
        if self.state:
            details.append(f"状态:{self.state}")
        return "  ".join(details)


@dataclass(frozen=True)
class C300CleanupCandidate:
    onu_interface: str
    pon_interface: str
    onu_id: int
    state: str
    serial_number: str = ""
    onu_type: str = ""

    @property
    def display_text(self) -> str:
        details = [self.onu_interface]
        if self.onu_type:
            details.append(f"型号:{self.onu_type}")
        if self.serial_number:
            details.append(f"SN:{self.serial_number}")
        details.append(f"状态:{self.state}")
        return "  ".join(details)


@dataclass(frozen=True)
class RegisteredOnu:
    """目标 PON 口下已注册、且可被操作员显式选择删除的离线 / 非 working ONU。"""

    family: str
    pon_interface: str
    onu_interface: str
    onu_id: int
    state: str
    serial_number: str = ""
    onu_type: str = ""

    @property
    def display_text(self) -> str:
        details = [self.onu_interface]
        if self.onu_type:
            details.append(f"型号:{self.onu_type}")
        if self.serial_number:
            details.append(f"SN:{self.serial_number}")
        details.append(f"状态:{self.state}")
        return "  ".join(details)


@dataclass(frozen=True)
class OnuProvisionRequest:
    family: str
    onu: DiscoveredOnu
    onu_id: Optional[int] = None
    onu_type: str = ""
    real_speed: str = "auto"
    tcont_id: int = 1
    tcont_profile: str = ""
    gemport_id: int = 1
    vport_id: int = 1
    sn_bind_both: bool = True
    services: Sequence[OnuServiceMapping] = field(default_factory=tuple)


@dataclass(frozen=True)
class OnuOperationResult:
    ok: bool
    message: str
    output: str = ""
    onus: tuple[DiscoveredOnu, ...] = ()
    cleanup_candidates: tuple[C300CleanupCandidate, ...] = ()
    registered_onus: tuple[RegisteredOnu, ...] = ()
    commands: tuple[str, ...] = ()
