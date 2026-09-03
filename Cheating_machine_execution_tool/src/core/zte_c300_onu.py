from __future__ import annotations

import re
from typing import Iterable

from src.models.onu_registration_models import (
    C300CleanupCandidate,
    DiscoveredOnu,
    OLT_FAMILY_C300,
    OnuDiscoveryScope,
    OnuProvisionRequest,
    OnuTemplate,
    RegisteredOnu,
)


C300_ONU_TYPE = "SD-41"
C300_INFERRED_PON_TYPE = "GPON（根据接口推断）"
C300_SERVICE_PORTS = (
    (1, 1, 200, "Internet"),
    (2, 2, 46, "TR069"),
    (3, 3, 335, "VOICE"),
    (4, 4, 600, "IPTV"),
    (5, 5, 171, "Internet2"),
    (6, 6, 172, "Internet3"),
)
C300_SERVICE_NAMES = ("Internet", "TR069", "VOICE", "IPTV", "Internet2", "Internet3")
NO_ONU_DATA_RE = re.compile(
    r"ONU data is null|No related information to show",
    re.IGNORECASE,
)
BASEINFO_RE = re.compile(
    r"^(?P<interface>gpon-onu_\d+/\d+/\d+:\d+)\s+"
    r"(?P<type>\S+)\s+(?P<mode>\S+)\s+SN:(?P<sn>\S+)\s+(?P<state>\S+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
ONU_INTERFACE_RE = re.compile(r"gpon-onu_\d+/\d+/\d+:\d+", re.IGNORECASE)
C300_SN_RE = re.compile(r"^[A-Za-z0-9]{4}[0-9A-Fa-f]{8}$")
ONU_TYPE_BLOCK_RE = re.compile(
    r"ONU type name:\s*(?P<name>\S+)(?P<body>.*?)(?=ONU type name:|\Z)",
    re.IGNORECASE | re.DOTALL,
)
PON_TYPE_RE = re.compile(r"^\s*PON type:\s*(?P<value>\S+)", re.IGNORECASE | re.MULTILINE)
TCONT_PROFILE_BLOCK_RE = re.compile(
    r"Profile name\s*:\s*(?P<name>\S+)(?P<body>.*?)(?=Profile name\s*:|\Z)",
    re.IGNORECASE | re.DOTALL,
)
TCONT_RATE_RE = re.compile(
    r"^\s*\d+\s+(?P<fbw>\d+)\s+(?P<abw>\d+)\s+(?P<mbw>\d+)",
    re.MULTILINE,
)


def _c300_rate_label(rate_kbps: int) -> str:
    if rate_kbps >= 1_000_000:
        return "1G"
    if rate_kbps >= 1_000:
        return f"{rate_kbps // 1000}M"
    return f"{rate_kbps}K" if rate_kbps else ""


class ZteC300OnuDriver:
    family = OLT_FAMILY_C300
    display_name = "中兴 C300"
    supports_write = True
    supports_offline_cleanup = True

    def build_discovery_command(self, _scope: OnuDiscoveryScope) -> str:
        return "show gpon onu uncfg"

    @staticmethod
    def build_template_query_command(kind: str) -> str:
        if kind == "onu_type":
            return "show onu-type"
        if kind == "dba":
            return "show gpon profile tcont"
        raise ValueError(f"不支持的 C300 模板查询类型：{kind}")

    @staticmethod
    def parse_templates(kind: str, output: str) -> list[OnuTemplate]:
        if kind == "onu_type":
            templates = []
            for match in ONU_TYPE_BLOCK_RE.finditer(output or ""):
                pon_match = PON_TYPE_RE.search(match.group("body"))
                pon_type = pon_match.group("value").upper() if pon_match else ""
                templates.append(OnuTemplate(match.group("name"), kind, pon_type=pon_type))
            return templates
        if kind == "dba":
            templates = []
            for match in TCONT_PROFILE_BLOCK_RE.finditer(output or ""):
                rate_match = TCONT_RATE_RE.search(match.group("body"))
                rate_kbps = (
                    max(int(rate_match.group(name)) for name in ("fbw", "abw", "mbw"))
                    if rate_match else 0
                )
                templates.append(
                    OnuTemplate(
                        match.group("name"),
                        kind,
                        rate_label=_c300_rate_label(rate_kbps),
                        max_rate_kbps=rate_kbps,
                    )
                )
            return templates
        raise ValueError(f"不支持的 C300 模板解析类型：{kind}")

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
                    registration_type=f"{C300_ONU_TYPE}（配置模板）",
                    pon_type=C300_INFERRED_PON_TYPE,
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
        if not C300_SN_RE.fullmatch(request.onu.serial_number.strip()):
            errors.append("C300 ONU SN 必须为4位厂商标识加8位十六进制字符")
        if request.onu_id is not None and request.onu_id < 1:
            errors.append("C300 ONU ID 必须为正整数")
        if request.tcont_id < 1:
            errors.append("C300 T-CONT 必须为正整数")
        if not (request.tcont_profile or "1G").strip():
            errors.append("C300 DBA 模板不能为空")
        try:
            self._service_ports(request)
        except ValueError as exc:
            errors.append(str(exc))
        return errors

    @staticmethod
    def _target_parts(request: OnuProvisionRequest) -> tuple[str, int, str, str]:
        match = re.fullmatch(
            r"gpon-onu_(?P<pon>\d+/\d+/\d+):(?P<onu_id>\d+)",
            request.onu.onu_interface,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError("C300 ONU 接口格式无效")
        pon_path = match.group("pon")
        onu_id = request.onu_id if request.onu_id is not None else int(match.group("onu_id"))
        return pon_path, onu_id, f"gpon-olt_{pon_path}", f"gpon-onu_{pon_path}:{onu_id}"

    @staticmethod
    def _service_ports(request: OnuProvisionRequest) -> tuple[tuple[int, int, int, str], ...]:
        if not request.services:
            return C300_SERVICE_PORTS
        if len(request.services) != len(C300_SERVICE_NAMES):
            raise ValueError("C300 必须保留六项标准业务映射")
        service_ids = [item.service_id for item in request.services]
        vlans = [item.vlan for item in request.services]
        if any(item < 1 for item in service_ids):
            raise ValueError("C300 Service ID 必须为正整数")
        if len(set(service_ids)) != len(service_ids):
            raise ValueError("C300 Service ID 不能重复")
        if any(not 1 <= item <= 4094 for item in vlans):
            raise ValueError("C300 VLAN 必须在 1-4094 之间")
        if len(set(vlans)) != len(vlans):
            raise ValueError("C300 VLAN 不能重复")
        if 600 not in vlans:
            raise ValueError("C300 标准业务必须保留组播 VLAN 600")
        return tuple(
            (item.service_id, item.service_id, item.vlan, C300_SERVICE_NAMES[index])
            for index, item in enumerate(request.services)
        )

    def build_precheck_commands(self, request: OnuProvisionRequest) -> list[str]:
        _pon_path, onu_id, olt_interface, _onu_interface = self._target_parts(request)
        return [
            "terminal length 0",
            "show gpon onu uncfg",
            f"show gpon onu baseinfo {olt_interface} {onu_id}",
            f"show gpon onu by sn {request.onu.serial_number}",
        ]

    def validate_precheck(self, request: OnuProvisionRequest, outputs: Iterable[str]) -> list[str]:
        values = list(outputs)
        _pon_path, onu_id, _olt_interface, _onu_interface = self._target_parts(request)
        discovered = self.parse_discovery(values[1] if len(values) > 1 else "")
        errors: list[str] = []
        baseinfo_output = values[2] if len(values) > 2 else ""
        baseinfo = self.parse_baseinfo(baseinfo_output)
        if baseinfo:
            item = baseinfo[0]
            errors.append(
                f"ONU ID {onu_id} 已存在："
                f"{item['interface']} type {item['type']} sn {item['serial_number']}"
            )
        elif not NO_ONU_DATA_RE.search(baseinfo_output):
            errors.append("无法确认 C300 目标 ONU ID 是否空闲，baseinfo 返回格式不符合预期")

        sn_output = values[3] if len(values) > 3 else ""
        registered_interfaces = self.parse_sn_lookup(sn_output)
        if registered_interfaces:
            errors.append(
                f"SN {request.onu.serial_number} 已注册在 {registered_interfaces[0]}"
            )
        elif not NO_ONU_DATA_RE.search(sn_output):
            errors.append("无法确认 C300 目标 SN 是否已注册，SN 查询返回格式不符合预期")

        if not any(
            item.pon_interface.lower() == request.onu.pon_interface.lower()
            and item.serial_number.upper() == request.onu.serial_number.upper()
            for item in discovered
        ):
            errors.append("目标 ONU 已不在 C300 未注册列表中，可能已被其它会话处理或光路已变化")
        return errors

    def build_provision_commands(self, request: OnuProvisionRequest) -> list[str]:
        errors = self.validate_request(request)
        if errors:
            raise ValueError("；".join(errors))
        pon_path, onu_id, _olt_interface, onu_interface = self._target_parts(request)
        onu_type = request.onu_type.strip() or C300_ONU_TYPE
        tcont_id = request.tcont_id
        tcont_profile = request.tcont_profile.strip() or "1G"
        service_ports = self._service_ports(request)
        commands = [
            "configure terminal",
            f"interface gpon-olt_{pon_path}",
            f"onu {onu_id} type {onu_type} sn {request.onu.serial_number}",
            "exit",
            f"interface {onu_interface}",
            "sn-bind enable sn",
            f"tcont {tcont_id} profile {tcont_profile}",
        ]
        commands.extend(f"gemport {gemport} tcont {tcont_id}" for gemport, _vport, _vlan, _service in service_ports)
        commands.extend(
            f"service-port {gemport} vport {vport} user-vlan {vlan} vlan {vlan}"
            for gemport, vport, vlan, _service in service_ports
        )
        commands.extend(["exit", f"pon-onu-mng {onu_interface}"])
        commands.extend(
            f"service {service} gemport {gemport} vlan {vlan}"
            for gemport, _vport, vlan, service in service_ports
        )
        commands.extend(["mvlan 600", "exit", "end"])
        return commands

    def build_verify_commands(self, request: OnuProvisionRequest) -> list[str]:
        _pon_path, onu_id, olt_interface, onu_interface = self._target_parts(request)
        return [
            "terminal length 0",
            f"show gpon onu baseinfo {olt_interface} {onu_id}",
            f"show gpon onu state {olt_interface} {onu_id}",
            f"show gpon onu detail-info {onu_interface}",
            f"show gpon onu tcont {olt_interface} {onu_id}",
            f"show gpon onu gemport {olt_interface} {onu_id}",
            f"show gpon onu vport {olt_interface} {onu_id}",
            f"show service-port interface {onu_interface}",
            f"show gpon remote-onu service {onu_interface}",
            f"show gpon remote-onu mvlan {onu_interface}",
        ]

    def validate_verification(self, request: OnuProvisionRequest, outputs: Iterable[str]) -> list[str]:
        values = list(outputs)
        errors: list[str] = []
        _pon_path, onu_id, _olt_interface, onu_interface = self._target_parts(request)
        expected_type = request.onu_type.strip() or C300_ONU_TYPE
        expected_services = {
            gemport: (vport, vlan, service)
            for gemport, vport, vlan, service in self._service_ports(request)
        }

        baseinfo = self.parse_baseinfo(values[1] if len(values) > 1 else "")
        if not baseinfo:
            errors.append("下发后未查询到 C300 ONU 注册记录")
        else:
            item = baseinfo[0]
            if item["interface"].lower() != onu_interface.lower():
                errors.append(f"下发后 ONU 接口不一致：{item['interface']}")
            if item["type"].upper() != expected_type.upper():
                errors.append(f"下发后 ONU 型号不一致：{item['type']}")
            if item["serial_number"].upper() != request.onu.serial_number.upper():
                errors.append(f"下发后 ONU SN 不一致：{item['serial_number']}")
            if item["mode"].lower() != "sn" or item["state"].lower() != "ready":
                errors.append(
                    f"下发后 ONU 基本状态异常：mode={item['mode']} state={item['state']}"
                )

        states = self.parse_registered_states(values[2] if len(values) > 2 else "")
        target_state = next(
            (item for item in states if item["interface"].lower() == onu_interface.lower()),
            None,
        )
        if not target_state:
            errors.append("下发后未查询到 C300 ONU 运行状态")
        elif not (
            target_state["admin"].lower() == "enable"
            and target_state["omcc"].lower() == "enable"
            and target_state["phase"].lower() == "working"
        ):
            errors.append(
                "下发后 ONU 未进入 working："
                f"admin={target_state['admin']} omcc={target_state['omcc']} "
                f"phase={target_state['phase']}"
            )

        detail = self.parse_detail_info(values[3] if len(values) > 3 else "")
        expected_detail = {
            "onu interface": onu_interface,
            "type": expected_type,
            "state": "ready",
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
                errors.append(f"ONU detail-info {key} 不一致：期望 {expected}，实际 {actual or '<缺失>'}")
        sn_bind = detail.get("sn bind", "")
        if "enable" not in sn_bind.lower() or "sn check" not in sn_bind.lower():
            errors.append(f"ONU SN Bind 状态异常：{sn_bind or '<缺失>'}")

        tcont_output = values[4] if len(values) > 4 else ""
        tcont_match = re.search(r"^T-CONT:\s+(\d+)\s*$", tcont_output, re.I | re.M)
        profile_match = re.search(r"^\s*Profile name:\s+(\S+)\s*$", tcont_output, re.I | re.M)
        expected_tcont = request.tcont_id
        expected_profile = request.tcont_profile.strip() or "1G"
        if not tcont_match or int(tcont_match.group(1)) != expected_tcont:
            errors.append(f"T-CONT {expected_tcont} 验证失败")
        if not profile_match or profile_match.group(1).upper() != expected_profile.upper():
            errors.append(f"T-CONT 模板 {expected_profile} 验证失败")

        gemports = self.parse_gemports(values[5] if len(values) > 5 else "")
        for gemport in expected_services:
            item = gemports.get(gemport)
            if not item:
                errors.append(f"缺少 GEM Port {gemport}")
            elif item["tcont"] != expected_tcont or item["status"].lower() != "active":
                errors.append(
                    f"GEM Port {gemport} 状态异常：T-CONT={item['tcont']} status={item['status']}"
                )

        vports = self.parse_vports(values[6] if len(values) > 6 else "")
        for gemport, (vport, _vlan, _service) in expected_services.items():
            item = vports.get(vport)
            if not item:
                errors.append(f"缺少 VPort {vport}")
            elif item["gemport"] != gemport or item["map_type"] != "1:1":
                errors.append(
                    f"VPort {vport} 映射异常：GEM={item['gemport']} map={item['map_type']}"
                )

        service_ports = self.parse_service_ports(values[7] if len(values) > 7 else "")
        for gemport, (vport, vlan, _service) in expected_services.items():
            item = service_ports.get(gemport)
            if not item:
                errors.append(f"缺少 service-port {gemport}")
            elif (
                item["vport"] != vport
                or item["begin_vlan"] != vlan
                or item["end_vlan"] != vlan
                or item["vlan"] != vlan
                or item["status"].upper() != "OK"
                or item["enable"].upper() != "YES"
            ):
                errors.append(f"service-port {gemport} 业务或状态不一致")

        remote_services = self.parse_remote_services(values[8] if len(values) > 8 else "")
        for gemport, (_vport, vlan, service) in expected_services.items():
            item = remote_services.get(service.lower())
            if not item:
                errors.append(f"缺少远端业务 {service}")
            elif item["gemport"] != gemport or item["vlan"] != vlan:
                errors.append(f"远端业务 {service} 的 GEM/VLAN 不一致")

        mvlan_match = re.search(
            r"Multicast VLAN:\s*(\d+)", values[9] if len(values) > 9 else "", re.I
        )
        if not mvlan_match or int(mvlan_match.group(1)) != 600:
            errors.append("组播 VLAN 600 验证失败")
        return errors

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
            for match in BASEINFO_RE.finditer(output or "")
        ]

    @staticmethod
    def parse_sn_lookup(output: str) -> list[str]:
        return list(dict.fromkeys(ONU_INTERFACE_RE.findall(output or "")))

    @staticmethod
    def parse_detail_info(output: str) -> dict[str, str]:
        details: dict[str, str] = {}
        for raw_line in (output or "").splitlines():
            match = re.match(r"^\s*([^:]+):\s*(.*?)\s*$", raw_line)
            if match:
                details[" ".join(match.group(1).lower().split())] = match.group(2)
        return details

    @staticmethod
    def parse_gemports(output: str) -> dict[int, dict[str, str | int]]:
        result: dict[int, dict[str, str | int]] = {}
        for block in re.split(r"(?=^OLT:\s+)", output or "", flags=re.MULTILINE):
            gem = re.search(r"^GEM port:\s+(\d+)\s*$", block, re.I | re.M)
            tcont = re.search(r"^T-CONT:\s+(\d+)\s*$", block, re.I | re.M)
            status = re.search(r"^Status:\s+(\S+)\s*$", block, re.I | re.M)
            if gem and tcont and status:
                result[int(gem.group(1))] = {
                    "tcont": int(tcont.group(1)),
                    "status": status.group(1),
                }
        return result

    @staticmethod
    def parse_vports(output: str) -> dict[int, dict[str, str | int]]:
        result: dict[int, dict[str, str | int]] = {}
        for block in re.split(r"(?=^ONU interface:\s+)", output or "", flags=re.MULTILINE):
            vport = re.search(r"^Vport:\s+(\d+)\s*$", block, re.I | re.M)
            map_type = re.search(r"^Map type:\s+(\S+)\s*$", block, re.I | re.M)
            gemport = re.search(r"^\s*GEM port:\s+(\d+)\s*$", block, re.I | re.M)
            if vport and map_type and gemport:
                result[int(vport.group(1))] = {
                    "map_type": map_type.group(1),
                    "gemport": int(gemport.group(1)),
                }
        return result

    @staticmethod
    def parse_service_ports(output: str) -> dict[int, dict[str, str | int]]:
        result: dict[int, dict[str, str | int]] = {}
        lines = (output or "").splitlines()
        for index, line in enumerate(lines):
            if not re.match(r"^\s*\d+\s+\d+\s+\d+\s+\d+\s+", line):
                continue
            numbers = [int(value) for value in re.findall(r"\b\d+\b", line)]
            if len(numbers) < 5:
                continue
            continuation = lines[index + 1] if index + 1 < len(lines) else ""
            status = re.search(r"\b(OK|FAIL)\s+(YES|NO)\s*$", continuation, re.I)
            sport, vport, begin_vlan, end_vlan, vlan = numbers[:5]
            result[sport] = {
                "vport": vport,
                "begin_vlan": begin_vlan,
                "end_vlan": end_vlan,
                "vlan": vlan,
                "status": status.group(1) if status else "",
                "enable": status.group(2) if status else "",
            }
        return result

    @staticmethod
    def parse_remote_services(output: str) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for raw_line in (output or "").splitlines():
            match = re.match(
                r"^\s*(\S+)\s+(\d+)\s+--\s+--\s+(\d+)\s*$",
                raw_line,
                re.IGNORECASE,
            )
            if match and match.group(1).lower() != "service":
                result[match.group(1).lower()] = {
                    "gemport": int(match.group(2)),
                    "vlan": int(match.group(3)),
                }
        return result

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
                    "admin": values["admin"],
                    "omcc": values["omcc"],
                    "phase": values["phase"],
                    "reusable": values["admin"].lower() == "enable"
                    and (values["omcc"].lower() != "enable" or values["phase"].lower() != "working"),
                }
            )
        return states

    def build_readiness_command(self, request: OnuProvisionRequest) -> str:
        _pon_path, onu_id, olt_interface, _onu_interface = self._target_parts(request)
        return f"show gpon onu state {olt_interface} {onu_id}"

    def readiness_state(self, request: OnuProvisionRequest, output: str) -> tuple[bool, str]:
        _pon_path, _onu_id, _olt_interface, onu_interface = self._target_parts(request)
        target = next(
            (
                item
                for item in self.parse_registered_states(output)
                if item["interface"].lower() == onu_interface.lower()
            ),
            None,
        )
        if not target:
            return False, "未查询到目标 ONU 状态"
        ready = (
            target["admin"].lower() == "enable"
            and target["omcc"].lower() == "enable"
            and target["phase"].lower() == "working"
        )
        return ready, (
            f"admin={target['admin']} omcc={target['omcc']} phase={target['phase']}"
        )

    def cleanup_candidates(
        self,
        request: OnuProvisionRequest,
        state_output: str,
    ) -> list[C300CleanupCandidate]:
        target_pon = request.onu.onu_interface.split("_", 1)[-1].split(":", 1)[0]
        candidates: list[C300CleanupCandidate] = []
        for item in self.parse_registered_states(state_output):
            if item["pon"] != target_pon or not item["reusable"]:
                continue
            candidates.append(
                C300CleanupCandidate(
                    onu_interface=str(item["interface"]),
                    pon_interface=f"gpon-olt_{item['pon']}",
                    onu_id=int(str(item["onu_id"])),
                    state=str(item["phase"]),
                )
            )
        return candidates

    @staticmethod
    def with_cleanup_identity(
        candidate: C300CleanupCandidate,
        baseinfo_output: str,
    ) -> C300CleanupCandidate:
        baseinfo = ZteC300OnuDriver.parse_baseinfo(baseinfo_output)
        if not baseinfo:
            return candidate
        item = baseinfo[0]
        return C300CleanupCandidate(
            onu_interface=candidate.onu_interface,
            pon_interface=candidate.pon_interface,
            onu_id=candidate.onu_id,
            state=candidate.state,
            serial_number=item["serial_number"],
            onu_type=item["type"],
        )

    def build_cleanup_commands(
        self,
        request: OnuProvisionRequest,
        state_output: str,
        selected_onu_interface: str,
    ) -> list[str]:
        selected = selected_onu_interface.strip().lower()
        candidate = next(
            (
                item
                for item in self.cleanup_candidates(request, state_output)
                if item.onu_interface.lower() == selected
            ),
            None,
        )
        if not candidate:
            return []
        return [
            "end",
            "configure terminal",
            f"interface {candidate.pon_interface}",
            f"no onu {candidate.onu_id}",
            "exit",
            "end",
        ]

    # ---- 已注册 ONU 管理（查询目标 PON 已注册 ONU → 显式删除离线 / 非 working ONU） ----

    @staticmethod
    def build_registered_query_command(pon_interface: str) -> str:
        """查询目标 PON 口下已注册 ONU 的运行状态。

        C300 仅确认支持全局 `show gpon onu state`（不带参数），不支持按 PON
        过滤的 `show gpon onu state <pon>`；解析时再按目标 PON 过滤。
        """
        return "show gpon onu state"

    def parse_registered_candidates(
        self,
        pon_interface: str,
        state_output: str,
    ) -> list[RegisteredOnu]:
        """从 state 输出中提取目标 PON 下全部已注册 ONU（不区分在线 / 离线状态）。"""
        target_pon = pon_interface.rsplit("_", 1)[-1]
        candidates: list[RegisteredOnu] = []
        for item in self.parse_registered_states(state_output):
            if item["pon"] != target_pon:
                continue
            candidates.append(
                RegisteredOnu(
                    family=self.family,
                    pon_interface=pon_interface,
                    onu_interface=item["interface"],
                    onu_id=int(item["onu_id"]),
                    state=item["phase"],
                )
            )
        return candidates

    @staticmethod
    def build_delete_identity_command(candidate: RegisteredOnu) -> str:
        """删除前身份复核：读取该 ONU 的接口、型号与 SN。"""
        return f"show gpon onu baseinfo {candidate.pon_interface} {candidate.onu_id}"

    @staticmethod
    def build_delete_commands(candidate: RegisteredOnu) -> list[str]:
        """在目标 PON 口下删除指定 ONU，仅生成这一台的 `no onu`。"""
        return [
            "configure terminal",
            f"interface {candidate.pon_interface}",
            f"no onu {candidate.onu_id}",
            "exit",
            "end",
        ]

    @staticmethod
    def deleted_if_baseinfo_empty(baseinfo_output: str) -> bool:
        """删除后回读：baseinfo 返回空记录视为该 ONU 已释放。"""
        return bool(NO_ONU_DATA_RE.search(baseinfo_output or ""))
