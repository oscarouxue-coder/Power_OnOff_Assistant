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
C600_BASEINFO_RE = re.compile(
    r"^(?P<interface>gpon_onu-\d+/\d+/\d+:\d+)\s+"
    r"(?P<type>\S+)\s+(?P<mode>\S+)\s+SN:(?P<sn>\S+)\s+(?P<state>\S+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
C600_ONU_INTERFACE_RE = re.compile(r"gpon_onu-\d+/\d+/\d+:\d+", re.IGNORECASE)
C600_EMPTY_ID_RE = re.compile(r"ONU data is null", re.IGNORECASE)
C600_EMPTY_SN_RE = re.compile(r"No related information to show", re.IGNORECASE)


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
        if 600 not in vlans:
            errors.append("C600 固定 MVLAN 600，业务映射必须包含 VLAN 600")
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
            self.build_discovery_command(scope),
            f"show gpon onu baseinfo {olt_interface} {request.onu_id}",
            f"show gpon onu by sn {request.onu.serial_number}",
        ]

    @staticmethod
    def precheck_allows_cli_error(command: str) -> bool:
        return command.startswith("show gpon onu baseinfo ") or command.startswith(
            "show gpon onu by sn "
        )

    def validate_precheck(self, request: OnuProvisionRequest, outputs: Iterable[str]) -> list[str]:
        values = list(outputs)
        errors: list[str] = []
        discovered = self.parse_discovery(values[0] if values else "")
        if request.onu.serial_number.upper() not in {
            item.serial_number.upper() for item in discovered
        }:
            errors.append("目标 SN 当前不在 C600 未注册 ONU 列表中，可能已被其它会话处理或光路已变化")

        baseinfo_output = clean_terminal_text(values[1] if len(values) > 1 else "")
        baseinfo = self.parse_baseinfo(baseinfo_output)
        if baseinfo:
            item = baseinfo[0]
            errors.append(
                f"ONU ID {request.onu_id} 已存在：type {item['type']} sn {item['serial_number']}"
            )
        elif not C600_EMPTY_ID_RE.search(baseinfo_output):
            errors.append("无法确认 C600 目标 ONU ID 是否空闲，baseinfo 返回格式不符合预期")

        sn_output = clean_terminal_text(values[2] if len(values) > 2 else "")
        registered_interfaces = self.parse_sn_lookup(sn_output)
        if registered_interfaces:
            errors.append(f"SN {request.onu.serial_number} 已注册在 {registered_interfaces[0]}")
        elif not C600_EMPTY_SN_RE.search(sn_output):
            errors.append("无法确认 C600 目标 SN 是否已注册，SN 查询返回格式不符合预期")
        return errors

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
        commands.extend(["mvlan 600", "exit", f"interface {vport_interface}"])
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
            f"show gpon remote-onu mvlan {onu_interface}",
        ]

    def validate_verification(self, request: OnuProvisionRequest, outputs: Iterable[str]) -> list[str]:
        values = list(outputs)
        errors: list[str] = []
        _olt_interface, onu_interface, _vport_interface = self._interfaces(request)

        collection = clean_terminal_text(values[0] if values else "")
        baseinfo = self.parse_baseinfo(collection)
        if not baseinfo:
            errors.append("C600 collection 未查询到 ONU 注册身份")
        else:
            item = baseinfo[0]
            if item["interface"].lower() != onu_interface.lower():
                errors.append(f"C600 ONU 接口不一致：{item['interface']}")
            if item["type"].upper() != request.onu_type.upper():
                errors.append(f"C600 ONU 型号不一致：{item['type']}")
            if item["serial_number"].upper() != request.onu.serial_number.upper():
                errors.append(f"C600 ONU SN 不一致：{item['serial_number']}")
            if item["mode"].lower() != "sn" or item["state"].lower() != "ready":
                errors.append(
                    f"C600 ONU 基本状态异常：mode={item['mode']} state={item['state']}"
                )

        expected_collection_patterns = [
            rf"^\s*tcont\s+{request.tcont_id}\s+profile\s+{re.escape(request.tcont_profile)}\s*$",
            rf"^\s*gemport\s+{request.gemport_id}\s+tcont\s+{request.tcont_id}\s*$",
            r"^\s*mvlan\s+600\s*$",
        ]
        if request.real_speed != "auto":
            expected_collection_patterns.append(
                rf"^\s*real-speed\s+{re.escape(request.real_speed)}\s*$"
            )
        if request.sn_bind_both:
            expected_collection_patterns.append(r"^\s*sn-bind\s+enable\s+both\s*$")
        for pattern in expected_collection_patterns:
            if not re.search(pattern, collection, re.I | re.M):
                errors.append(f"C600 collection 缺少配置：{pattern}")
        for item in request.services:
            service_pattern = (
                rf"^\s*service\s+{item.service_id}\s+gemport\s+{request.gemport_id}\s+"
                rf"vlan\s+{item.vlan}\s*$"
            )
            port_pattern = (
                rf"^\s*service-port\s+{item.service_id}\s+user-vlan\s+{item.vlan}\s+"
                rf"vlan\s+{item.vlan}\s*$"
            )
            if not re.search(service_pattern, collection, re.I | re.M):
                errors.append(f"C600 缺少 service {item.service_id}/VLAN {item.vlan}")
            if not re.search(port_pattern, collection, re.I | re.M):
                errors.append(f"C600 缺少 service-port {item.service_id}/VLAN {item.vlan}")

        runtime_ports = self.parse_service_port_statuses(values[1] if len(values) > 1 else "")
        for item in request.services:
            status = runtime_ports.get(item.service_id, "")
            if status != "OK/YES":
                errors.append(
                    f"C600 service-port {item.service_id} 运行状态异常：{status or '<缺失>'}"
                )

        detail = self.parse_detail_info(values[2] if len(values) > 2 else "")
        expected_detail = {
            "onu interface": onu_interface,
            "type": request.onu_type,
            "admin state": "enable",
            "phase state": "working",
            "config state": "success",
            "authentication mode": "sn",
            "serial number": request.onu.serial_number,
            "vport mode": "gemport",
            "onu status": "enable",
        }
        for key, expected in expected_detail.items():
            actual = detail.get(key, "")
            if actual.lower() != expected.lower():
                errors.append(
                    f"C600 detail-info {key} 不一致：期望 {expected}，实际 {actual or '<缺失>'}"
                )
        if request.sn_bind_both and "enable with both check" not in detail.get("sn bind", "").lower():
            errors.append(f"C600 SN Bind 状态异常：{detail.get('sn bind') or '<缺失>'}")

        mvlan_output = values[3] if len(values) > 3 else ""
        match = re.search(r"Multicast VLAN:\s*(\d+)", clean_terminal_text(mvlan_output), re.I)
        if not match or int(match.group(1)) != 600:
            errors.append("C600 组播 VLAN 600 验证失败")
        return errors

    def build_readiness_command(self, request: OnuProvisionRequest) -> str:
        olt_interface, _onu_interface, _vport_interface = self._interfaces(request)
        return f"show gpon onu state {olt_interface} {request.onu_id}"

    def readiness_state(self, request: OnuProvisionRequest, output: str) -> tuple[bool, str]:
        expected = self._interfaces(request)[1].split("-", 1)[1]
        for raw_line in clean_terminal_text(output or "").splitlines():
            match = re.match(
                r"^\s*(\d+/\d+/\d+:\d+)\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+.+)?$",
                raw_line,
                re.IGNORECASE,
            )
            if not match or match.group(1).lower() != expected.lower():
                continue
            admin, omcc, phase = match.group(2), match.group(3), match.group(4)
            ready = (
                admin.lower() == "enable"
                and omcc.lower() == "enable"
                and phase.lower() == "working"
            )
            return ready, f"admin={admin} omcc={omcc} phase={phase}"
        return False, "未查询到目标 ONU 状态"

    @staticmethod
    def parse_baseinfo(output: str) -> list[dict[str, str]]:
        return [
            {
                "interface": match.group("interface"),
                "type": match.group("type"),
                "mode": match.group("mode"),
                "serial_number": match.group("sn"),
                "state": match.group("state"),
            }
            for match in C600_BASEINFO_RE.finditer(clean_terminal_text(output or ""))
        ]

    @staticmethod
    def parse_sn_lookup(output: str) -> list[str]:
        return list(
            dict.fromkeys(C600_ONU_INTERFACE_RE.findall(clean_terminal_text(output or "")))
        )

    @staticmethod
    def parse_detail_info(output: str) -> dict[str, str]:
        details: dict[str, str] = {}
        for raw_line in clean_terminal_text(output or "").splitlines():
            match = re.match(r"^\s*([^:]+):\s*(.*?)\s*$", raw_line)
            if match:
                details[" ".join(match.group(1).lower().split())] = match.group(2)
        return details

    @staticmethod
    def parse_service_port_statuses(output: str) -> dict[int, str]:
        rows: dict[int, list[str]] = {}
        current_id: int | None = None
        for raw_line in clean_terminal_text(output or "").splitlines():
            row_match = re.match(r"^\s*(\d+)\s+\d+\s+\d+\s+--\s+", raw_line)
            if row_match:
                current_id = int(row_match.group(1))
                rows[current_id] = [raw_line]
            elif current_id is not None and not raw_line.strip().lower().startswith("sport total"):
                rows[current_id].append(raw_line)
        result: dict[int, str] = {}
        for service_id, lines in rows.items():
            normalized = " ".join(" ".join(lines).split())
            if re.search(r"\bOK\s+YES\b", normalized, re.I):
                result[service_id] = "OK/YES"
            elif re.search(r"\bFAIL\s+(?:YES|NO)\b", normalized, re.I):
                result[service_id] = "FAIL"
            else:
                result[service_id] = "UNKNOWN"
        return result

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
    # 发现结果中的Speed Mode是当前光模块能力，不代表该ONU型号支持real-speed命令。
    # 实机NP7287XGS会自动进入XGS-PON，但拒绝`real-speed xgspon`；发现后默认不下发，
    # 操作员仍可在配置页明确选择xgspon/xgpon/gpon作为型号专用覆盖。
    _ = speed_mode
    return "auto"
