from __future__ import annotations

import re
from typing import Iterable

from src.models.onu_registration_models import (
    DiscoveredOnu,
    OLT_FAMILY_C300,
    OnuDiscoveryScope,
    OnuProvisionRequest,
)


C300_ONU_TYPE = "SD-41"
C300_SERVICE_PORTS = (
    (1, 1, 200, "Internet"),
    (2, 2, 46, "TR069"),
    (3, 3, 335, "VOICE"),
    (4, 4, 600, "IPTV"),
    (5, 5, 171, "Internet2"),
    (6, 6, 172, "Internet3"),
)


class ZteC300OnuDriver:
    family = OLT_FAMILY_C300
    display_name = "中兴 C300"
    supports_write = True
    supports_offline_cleanup = True

    def build_discovery_command(self, _scope: OnuDiscoveryScope) -> str:
        return "show gpon onu uncfg"

    def parse_discovery(self, output: str) -> list[DiscoveredOnu]:
        onus: list[DiscoveredOnu] = []
        for raw_line in (output or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("-") or line.lower().startswith("onuindex"):
                continue
            match = re.match(
                r"^(gpon-onu_(?P<pon>\d+/\d+/\d+):(?P<id>\d+))\s+(\S+)\s+(\S+)\s*$",
                line,
                re.IGNORECASE,
            )
            if not match:
                continue
            onus.append(
                DiscoveredOnu(
                    family=self.family,
                    pon_interface=f"gpon-olt_{match.group('pon')}",
                    onu_interface=match.group(1),
                    suggested_onu_id=int(match.group("id")),
                    serial_number=match.group(4),
                    state=match.group(5),
                )
            )
        return onus

    def validate_request(self, request: OnuProvisionRequest) -> list[str]:
        errors: list[str] = []
        if request.family != self.family or request.onu.family != self.family:
            errors.append("所选 ONU 与 C300 驱动不匹配")
        if not re.fullmatch(r"gpon-onu_\d+/\d+/\d+:\d+", request.onu.onu_interface, re.I):
            errors.append("C300 ONU 接口格式无效")
        if not request.onu.serial_number.strip():
            errors.append("ONU SN 不能为空")
        return errors

    def build_precheck_commands(self, request: OnuProvisionRequest) -> list[str]:
        return ["terminal length 0", self.build_discovery_command(OnuDiscoveryScope()), "show gpon onu state"]

    def validate_precheck(self, request: OnuProvisionRequest, outputs: Iterable[str]) -> list[str]:
        values = list(outputs)
        discovered = self.parse_discovery(values[1] if len(values) > 1 else "")
        if not any(
            item.onu_interface.lower() == request.onu.onu_interface.lower()
            and item.serial_number.upper() == request.onu.serial_number.upper()
            for item in discovered
        ):
            return ["目标 ONU 已不在 C300 未注册列表中，可能已被其它会话处理或光路已变化"]
        registered_names = {
            item["interface"].lower() for item in self.parse_registered_states(values[2] if len(values) > 2 else "")
        }
        if request.onu.onu_interface.lower() in registered_names:
            return [f"ONU 接口 {request.onu.onu_interface} 已存在于注册状态表中"]
        return []

    def build_provision_commands(self, request: OnuProvisionRequest) -> list[str]:
        errors = self.validate_request(request)
        if errors:
            raise ValueError("；".join(errors))
        match = re.fullmatch(
            r"gpon-onu_(?P<pon>\d+/\d+/\d+):(?P<onu_id>\d+)",
            request.onu.onu_interface,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError("C300 ONU 接口格式无效")
        pon_path = match.group("pon")
        onu_id = match.group("onu_id")
        onu_interface = f"gpon-onu_{pon_path}:{onu_id}"
        onu_type = request.onu_type.strip() or C300_ONU_TYPE
        commands = [
            "configure terminal",
            f"interface gpon-olt_{pon_path}",
            f"onu {onu_id} type {onu_type} sn {request.onu.serial_number}",
            "exit",
            f"interface {onu_interface}",
            "sn-bind enable sn",
            "tcont 1 profile 1G",
        ]
        commands.extend(f"gemport {gemport} tcont 1" for gemport, _vport, _vlan, _service in C300_SERVICE_PORTS)
        commands.extend(
            f"service-port {gemport} vport {vport} user-vlan {vlan} vlan {vlan}"
            for gemport, vport, vlan, _service in C300_SERVICE_PORTS
        )
        commands.extend(["exit", f"pon-onu-mng {onu_interface}"])
        commands.extend(
            f"service {service} gemport {gemport} vlan {vlan}"
            for gemport, _vport, vlan, service in C300_SERVICE_PORTS
        )
        commands.extend(["mvlan 600", "exit", "end"])
        return commands

    def build_verify_commands(self, _request: OnuProvisionRequest) -> list[str]:
        return ["terminal length 0", "show gpon onu uncfg", "show gpon onu state"]

    def validate_verification(self, request: OnuProvisionRequest, outputs: Iterable[str]) -> list[str]:
        values = list(outputs)
        remaining = self.parse_discovery(values[1] if len(values) > 1 else "")
        if any(item.serial_number.upper() == request.onu.serial_number.upper() for item in remaining):
            return ["下发后目标 SN 仍在 C300 未注册列表中"]
        return []

    def parse_registered_states(self, output: str) -> list[dict[str, str | bool]]:
        states: list[dict[str, str | bool]] = []
        for raw_line in (output or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("-") or line.lower().startswith(("onuindex", "onu number")):
                continue
            match = re.match(
                r"^(?P<onu>\d+/\d+/\d+:\d+)\s+(?P<admin>\S+)\s+(?P<omcc>\S+)\s+(?P<phase>\S+)(?:\s+.+)?$",
                line,
            )
            if not match:
                continue
            values = match.groupdict()
            states.append(
                {
                    "interface": f"gpon-onu_{values['onu']}",
                    "pon": values["onu"].split(":", 1)[0],
                    "onu_id": values["onu"].split(":", 1)[1],
                    "reusable": values["admin"].lower() == "enable"
                    and (values["omcc"].lower() != "enable" or values["phase"].lower() != "working"),
                }
            )
        return states

    def build_cleanup_commands(self, request: OnuProvisionRequest, state_output: str) -> list[str]:
        target_pon = request.onu.onu_interface.split("_", 1)[-1].split(":", 1)[0]
        reusable = [item for item in self.parse_registered_states(state_output) if item["reusable"]]
        reusable.sort(key=lambda item: 0 if item["pon"] == target_pon else 1)
        if not reusable:
            return []
        commands = ["end", "configure terminal"]
        for item in reusable:
            commands.extend(
                [f"interface gpon-olt_{item['pon']}", f"no onu {item['onu_id']}", "exit"]
            )
        commands.append("end")
        return commands

