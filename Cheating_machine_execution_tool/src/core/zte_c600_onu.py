from __future__ import annotations

import re
from typing import Iterable

from src.core.zte_olt_telnet import clean_terminal_text
from src.models.onu_registration_models import (
    DiscoveredOnu,
    OLT_FAMILY_C600,
    OnuDiscoveryScope,
    OnuProvisionRequest,
)


SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SN_RE = re.compile(r"^[A-Za-z0-9_-]{4,32}$")
UNCONFIGURED_RE = re.compile(
    r"^(gpon_olt-\d+/\d+/\d+)\s+(\S+)\s+(\S+)\s+(.+?)\s*$",
    re.IGNORECASE,
)
REGISTERED_RE = re.compile(
    r"^\s*onu\s+(\d+)\s+type\s+(\S+)\s+sn\s+(\S+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


class ZteC600OnuDriver:
    family = OLT_FAMILY_C600
    display_name = "中兴 C600"
    supports_write = False
    supports_offline_cleanup = False

    def build_discovery_command(self, scope: OnuDiscoveryScope) -> str:
        errors = scope.validate()
        if errors:
            raise ValueError("；".join(errors))
        return (
            f"show pon onu uncfg gpon_olt-{scope.shelf}/{scope.slot}/{scope.pon} "
            "sn model speed-mode"
        )

    def parse_discovery(self, output: str) -> list[DiscoveredOnu]:
        result: list[DiscoveredOnu] = []
        for line in clean_terminal_text(output or "").splitlines():
            match = UNCONFIGURED_RE.match(line.strip())
            if not match:
                continue
            interface, model, serial_number, speed_mode = match.groups()
            if model.lower() == "model" or serial_number.lower() == "sn":
                continue
            result.append(
                DiscoveredOnu(
                    family=self.family,
                    pon_interface=interface,
                    model=model,
                    serial_number=serial_number,
                    speed_mode=speed_mode.strip(),
                )
            )
        return result

    def validate_request(self, request: OnuProvisionRequest) -> list[str]:
        errors: list[str] = []
        if request.family != self.family or request.onu.family != self.family:
            errors.append("所选 ONU 与 C600 驱动不匹配")
        if not re.fullmatch(r"gpon_olt-\d+/\d+/\d+", request.onu.pon_interface, re.I):
            errors.append("C600 PON 接口格式无效")
        if request.onu_id is None or not 1 <= request.onu_id <= 1024:
            errors.append("ONU ID 必须在 1-1024 之间")
        if not SAFE_NAME_RE.fullmatch(request.onu_type or ""):
            errors.append("ONU 型号只能包含字母、数字、点、下划线和连字符")
        if not SN_RE.fullmatch(request.onu.serial_number or ""):
            errors.append("SN 必须为 4-32 位 ASCII 字母、数字、下划线或连字符")
        if request.real_speed not in {"xgspon", "xgpon", "gpon", "auto"}:
            errors.append("实际速率必须是 xgspon、xgpon、gpon 或 auto")
        for label, value, upper in (
            ("T-CONT ID", request.tcont_id, 255),
            ("GEM Port ID", request.gemport_id, 4095),
            ("VPort ID", request.vport_id, 4095),
        ):
            if not 1 <= value <= upper:
                errors.append(f"{label}必须在 1-{upper} 之间")
        if not SAFE_NAME_RE.fullmatch(request.tcont_profile or ""):
            errors.append("T-CONT 模板名称格式无效")
        if not request.services:
            errors.append("至少需要一条 ServiceID/VLAN 映射")
        service_ids = [item.service_id for item in request.services]
        vlans = [item.vlan for item in request.services]
        if len(service_ids) != len(set(service_ids)):
            errors.append("Service ID 不能重复")
        if len(vlans) != len(set(vlans)):
            errors.append("VLAN 不能重复")
        for item in request.services:
            if not 1 <= item.service_id <= 4095:
                errors.append(f"Service ID {item.service_id} 超出 1-4095")
            if not 1 <= item.vlan <= 4094:
                errors.append(f"VLAN {item.vlan} 超出 1-4094")
        return errors

    def _interfaces(self, request: OnuProvisionRequest) -> tuple[str, str, str]:
        location = request.onu.pon_interface.split("-", 1)[1]
        onu_interface = f"gpon_onu-{location}:{request.onu_id}"
        vport_interface = f"vport-{location}.{request.onu_id}:{request.vport_id}"
        return request.onu.pon_interface, onu_interface, vport_interface

    def build_precheck_commands(self, request: OnuProvisionRequest) -> list[str]:
        olt_interface, _onu_interface, _vport_interface = self._interfaces(request)
        scope = self._scope_from_interface(olt_interface)
        return [
            f"show running-config-interface {olt_interface}",
            self.build_discovery_command(scope),
        ]

    def validate_precheck(self, request: OnuProvisionRequest, outputs: Iterable[str]) -> list[str]:
        values = list(outputs)
        registered = [
            (int(onu_id), onu_type, serial_number)
            for onu_id, onu_type, serial_number in REGISTERED_RE.findall(
                clean_terminal_text(values[0] if values else "")
            )
        ]
        for onu_id, onu_type, serial_number in registered:
            if onu_id == request.onu_id:
                return [f"ONU ID {onu_id} 已存在：type {onu_type} sn {serial_number}"]
            if serial_number.upper() == request.onu.serial_number.upper():
                return [f"SN {serial_number} 已注册在 ONU ID {onu_id}"]
        discovered = self.parse_discovery(values[1] if len(values) > 1 else "")
        if request.onu.serial_number.upper() not in {
            item.serial_number.upper() for item in discovered
        }:
            return ["目标 SN 当前不在 C600 未注册 ONU 列表中，可能已被其它会话处理或光路已变化"]
        return []

    def build_provision_commands(self, request: OnuProvisionRequest) -> list[str]:
        errors = self.validate_request(request)
        if errors:
            raise ValueError("；".join(errors))
        olt_interface, onu_interface, vport_interface = self._interfaces(request)
        commands = [
            "configure terminal",
            f"interface {olt_interface}",
            f"onu {request.onu_id} type {request.onu_type} sn {request.onu.serial_number}",
            "exit",
            f"interface {onu_interface}",
        ]
        if request.real_speed != "auto":
            commands.append(f"real-speed {request.real_speed}")
        commands.append(f"tcont {request.tcont_id} profile {request.tcont_profile}")
        if request.sn_bind_both:
            commands.append("sn-bind enable both")
        commands.extend(
            [
                f"gemport {request.gemport_id} tcont {request.tcont_id}",
                "exit",
                f"pon-onu-mng {onu_interface}",
            ]
        )
        commands.extend(
            f"service {item.service_id} gemport {request.gemport_id} vlan {item.vlan}"
            for item in request.services
        )
        commands.extend(["exit", f"interface {vport_interface}"])
        commands.extend(
            f"service-port {item.service_id} user-vlan {item.vlan} vlan {item.vlan}"
            for item in request.services
        )
        commands.extend(["exit", "end"])
        return commands

    def build_verify_commands(self, request: OnuProvisionRequest) -> list[str]:
        _olt_interface, onu_interface, _vport_interface = self._interfaces(request)
        return [
            f"show collection pon-onu {onu_interface} config",
            f"show service-port interface {onu_interface}",
            f"show gpon onu detail-info {onu_interface}",
        ]

    def validate_verification(self, _request: OnuProvisionRequest, _outputs: Iterable[str]) -> list[str]:
        return []

    @staticmethod
    def _scope_from_interface(interface: str) -> OnuDiscoveryScope:
        match = re.fullmatch(r"gpon_olt-(\d+)/(\d+)/(\d+)", interface, re.I)
        if not match:
            raise ValueError(f"C600 PON 接口格式无效：{interface}")
        return OnuDiscoveryScope(*(int(value) for value in match.groups()))


def parse_service_mappings(text: str):
    from src.models.onu_registration_models import OnuServiceMapping

    mappings: list[OnuServiceMapping] = []
    for line_number, raw_line in enumerate((text or "").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"(\d+)\s*[,=:]\s*(\d+)", line)
        if not match:
            raise ValueError(f"业务映射第 {line_number} 行格式错误，应为 ServiceID,VLAN")
        mappings.append(OnuServiceMapping(int(match.group(1)), int(match.group(2))))
    return mappings


def speed_mode_to_cli(speed_mode: str) -> str:
    normalized = (speed_mode or "").strip().upper().replace("_", "-")
    return {"XGS-PON": "xgspon", "XG-PON": "xgpon", "GPON": "gpon"}.get(normalized, "auto")
