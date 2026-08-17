from dataclasses import dataclass, field
import ipaddress
import re
from typing import List


SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SN_RE = re.compile(r"^[A-Za-z0-9_-]{4,32}$")


@dataclass(frozen=True)
class ServiceMapping:
    service_id: int
    vlan: int


@dataclass(frozen=True)
class OltConnection:
    host: str
    port: int
    username: str
    password: str
    source_ip: str = ""
    timeout: float = 10.0

    def validate(self) -> List[str]:
        errors: List[str] = []
        try:
            ipaddress.ip_address(self.host)
        except ValueError:
            errors.append("OLT 地址必须是有效的 IPv4/IPv6 地址")
        if self.source_ip:
            try:
                ipaddress.ip_address(self.source_ip)
            except ValueError:
                errors.append("源地址必须是有效的 IPv4/IPv6 地址")
        if not 1 <= self.port <= 65535:
            errors.append("Telnet 端口必须在 1-65535 之间")
        if not self.username.strip():
            errors.append("用户名不能为空")
        if not self.password:
            errors.append("密码不能为空")
        if not 2 <= self.timeout <= 120:
            errors.append("超时时间必须在 2-120 秒之间")
        return errors


@dataclass(frozen=True)
class OnuProvisionConfig:
    shelf: int
    slot: int
    pon: int
    onu_id: int
    onu_type: str
    serial_number: str
    real_speed: str = "xgspon"
    tcont_id: int = 1
    tcont_profile: str = "CXP-55"
    gemport_id: int = 1
    vport_id: int = 1
    sn_bind_both: bool = True
    services: List[ServiceMapping] = field(default_factory=list)

    @property
    def olt_interface(self) -> str:
        return f"gpon_olt-{self.shelf}/{self.slot}/{self.pon}"

    @property
    def onu_interface(self) -> str:
        return f"gpon_onu-{self.shelf}/{self.slot}/{self.pon}:{self.onu_id}"

    @property
    def vport_interface(self) -> str:
        return f"vport-{self.shelf}/{self.slot}/{self.pon}.{self.onu_id}:{self.vport_id}"

    def validate(self) -> List[str]:
        errors: List[str] = []
        for label, value, upper in (
            ("机框", self.shelf, 64),
            ("槽位", self.slot, 64),
            ("PON 口", self.pon, 64),
            ("ONU ID", self.onu_id, 1024),
            ("T-CONT ID", self.tcont_id, 255),
            ("GEM Port ID", self.gemport_id, 4095),
            ("VPort ID", self.vport_id, 4095),
        ):
            if not 1 <= value <= upper:
                errors.append(f"{label}必须在 1-{upper} 之间")
        if not SAFE_NAME_RE.fullmatch(self.onu_type):
            errors.append("ONU 型号只能包含字母、数字、点、下划线和连字符")
        if not SN_RE.fullmatch(self.serial_number):
            errors.append("SN 必须为 4-32 位 ASCII 字母、数字、下划线或连字符")
        if self.real_speed not in {"xgspon", "xgpon", "gpon", "auto"}:
            errors.append("实际速率必须是 xgspon、xgpon、gpon 或 auto")
        if not SAFE_NAME_RE.fullmatch(self.tcont_profile):
            errors.append("T-CONT 模板名称格式无效")
        if not self.services:
            errors.append("至少需要一条业务 VLAN 映射")
        service_ids = [item.service_id for item in self.services]
        if len(service_ids) != len(set(service_ids)):
            errors.append("Service ID 不能重复")
        vlans = [item.vlan for item in self.services]
        if len(vlans) != len(set(vlans)):
            errors.append("VLAN 不能重复")
        for item in self.services:
            if not 1 <= item.service_id <= 4095:
                errors.append(f"Service ID {item.service_id} 超出 1-4095")
            if not 1 <= item.vlan <= 4094:
                errors.append(f"VLAN {item.vlan} 超出 1-4094")
        return errors


@dataclass(frozen=True)
class UnconfiguredOnu:
    olt_interface: str
    model: str
    serial_number: str
    speed_mode: str

    @property
    def location(self):
        match = re.fullmatch(r"gpon_olt-(\d+)/(\d+)/(\d+)", self.olt_interface)
        if not match:
            raise ValueError(f"无法解析 PON 接口：{self.olt_interface}")
        return tuple(int(value) for value in match.groups())
