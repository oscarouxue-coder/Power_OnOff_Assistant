from __future__ import annotations

from dataclasses import dataclass, replace
import re
import unicodedata

from src.core.zte_c300_onu import C300_SERVICE_NAMES, ZteC300OnuDriver
from src.core.zte_c600_onu import C600_FIXED_BUSINESS_LAYERS, ZteC600OnuDriver
from src.models.onu_registration_models import (
    OLT_FAMILY_C300,
    OLT_FAMILY_C600,
    OnuCommandPlan,
    OnuProvisionRequest,
    OnuServiceMapping,
)


SAFE_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")


class OnuCommandEditError(ValueError):
    """An edit error located in the operator's original text."""

    def __init__(self, request: OnuProvisionRequest, line_number: int, reason: str) -> None:
        self.line_number = line_number
        onu_id = request.onu_id if request.onu_id is not None else request.onu.suggested_onu_id
        if onu_id is None:
            interface_id = re.search(r":([0-9]+)$", request.onu.onu_interface)
            onu_id = interface_id.group(1) if interface_id else "未指定"
        self.target_name = (
            f"SN {request.onu.serial_number} / {request.onu.pon_interface} / "
            f"ONU ID {onu_id}"
        )
        self.reason = reason
        super().__init__(f"{self.target_name}，第 {line_number} 行：{reason}")


@dataclass(frozen=True)
class _CommandLine:
    number: int
    command: str

    @property
    def normalized(self) -> str:
        return " ".join(self.command.split())


class OnuCommandEditService:
    """Parse only commands reproducible by the existing family driver."""

    def build_default(self, base_request: OnuProvisionRequest) -> OnuCommandPlan:
        driver = self._driver(base_request)
        try:
            commands = driver.build_provision_commands(base_request)
        except ValueError as exc:
            raise OnuCommandEditError(base_request, 1, str(exc)) from exc
        return self.prepare(base_request, "\n".join(commands))

    def prepare(self, base_request: OnuProvisionRequest, text: str) -> OnuCommandPlan:
        driver = self._driver(base_request)
        lines = self._read_lines(base_request, text)
        try:
            original = driver.build_provision_commands(base_request)
        except ValueError as exc:
            raise OnuCommandEditError(base_request, 1, str(exc)) from exc
        identity_line, identity = self._single(
            base_request, lines, "onu ", r"onu ([0-9]+) type (\S+) sn (\S+)", "ONU 注册命令"
        )
        original_identity = next(command for command in original if command.startswith("onu "))
        original_match = re.fullmatch(r"onu ([0-9]+) type (\S+) sn (\S+)", original_identity)
        if original_match is None:
            raise OnuCommandEditError(base_request, identity_line.number, "原始 ONU 注册命令格式无效")
        if identity.group(1) != original_match.group(1) or identity.group(3) != original_match.group(3):
            raise OnuCommandEditError(base_request, identity_line.number, "目标 SN 和 ONU ID 固定，不允许修改")
        if not SAFE_NAME_RE.fullmatch(identity.group(2)):
            raise OnuCommandEditError(base_request, identity_line.number, "ONU 类型模板名称只能包含字母、数字、点、下划线和连字符")
        if base_request.family == OLT_FAMILY_C300:
            request = self._parse_c300(base_request, lines, identity.group(2))
        else:
            request = self._parse_c600(base_request, lines, identity.group(2))
        errors = driver.validate_request(request)
        if errors:
            service_line = next((line for line in lines if line.normalized.startswith("service ")), identity_line)
            raise OnuCommandEditError(base_request, service_line.number, "；".join(errors))
        expected = driver.build_provision_commands(request)
        for index in range(max(len(lines), len(expected))):
            if index >= len(lines):
                raise OnuCommandEditError(base_request, lines[-1].number, f"命令不完整，缺少：{expected[index]}")
            if index >= len(expected):
                raise OnuCommandEditError(base_request, lines[index].number, "存在多余或不支持的命令")
            if lines[index].normalized != " ".join(expected[index].split()):
                raise OnuCommandEditError(
                    base_request,
                    lines[index].number,
                    f"命令、顺序或上下文不符合生成规则；期望：{expected[index]}",
                )
        normalized_original = tuple(" ".join(command.split()) for command in original)
        commands = tuple(line.command for line in lines)
        edited = tuple(line.normalized for line in lines) != normalized_original
        return OnuCommandPlan(request, commands, edited)

    @staticmethod
    def _driver(request: OnuProvisionRequest):
        if request.family == OLT_FAMILY_C300:
            return ZteC300OnuDriver()
        if request.family == OLT_FAMILY_C600:
            return ZteC600OnuDriver()
        raise OnuCommandEditError(request, 1, f"不支持的 OLT 型号：{request.family}")

    @staticmethod
    def _read_lines(request: OnuProvisionRequest, text: str) -> list[_CommandLine]:
        if not isinstance(text, str):
            raise OnuCommandEditError(request, 1, "待下发命令必须是文本")
        result = []
        # Split only real line endings: other control characters must not silently
        # become new commands, and TAB must not reach a CLI with completion enabled.
        for number, raw_line in enumerate(re.split(r"\r\n|\r|\n", text), 1):
            if any(unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} for char in raw_line):
                raise OnuCommandEditError(request, number, "命令中不允许控制字符（包括制表符）")
            command = raw_line.strip()
            if not command or command.startswith("#"):
                continue
            if any(char.isspace() and ord(char) > 127 for char in raw_line):
                raise OnuCommandEditError(request, number, "有效命令只允许 ASCII 空格，不允许不间断空格或全角空格")
            normalized = " ".join(command.split())
            if normalized.split()[0].lower() in {"write", "no", "reboot", "reload", "reset", "delete"}:
                raise OnuCommandEditError(request, number, "编辑区域不允许保存、删除或重启命令")
            result.append(_CommandLine(number, command))
        if not result:
            raise OnuCommandEditError(request, 1, "待下发命令不能为空")
        return result

    @staticmethod
    def _single(request, lines, prefix, pattern, label):
        candidates = [line for line in lines if line.normalized.startswith(prefix)]
        if not candidates:
            raise OnuCommandEditError(request, lines[-1].number, f"缺少{label}")
        if len(candidates) > 1:
            raise OnuCommandEditError(request, candidates[1].number, f"{label}重复")
        match = re.fullmatch(pattern, candidates[0].normalized)
        if not match:
            raise OnuCommandEditError(request, candidates[0].number, f"{label}格式无效")
        return candidates[0], match

    def _parse_c300(self, base, lines, onu_type):
        tcont_line, tcont = self._single(
            base, lines, "tcont ", r"tcont ([0-9]+) profile (\S+)", "单个 T-CONT/DBA 命令"
        )
        if not SAFE_NAME_RE.fullmatch(tcont.group(2)):
            raise OnuCommandEditError(base, tcont_line.number, "DBA 模板名称只能包含字母、数字、点、下划线和连字符")
        services = {}
        for line in lines:
            if not line.normalized.startswith("service "):
                continue
            match = re.fullmatch(r"service (\S+) gemport ([0-9]+) vlan ([0-9]+)", line.normalized)
            if match is None or match.group(1) not in C300_SERVICE_NAMES:
                raise OnuCommandEditError(base, line.number, "C300 必须保留六项固定远端业务名称和格式")
            name = match.group(1)
            if name in services:
                raise OnuCommandEditError(base, line.number, f"远端业务 {name} 重复")
            services[name] = OnuServiceMapping(int(match.group(2)), int(match.group(3)))
        missing = [name for name in C300_SERVICE_NAMES if name not in services]
        if missing:
            raise OnuCommandEditError(base, lines[-1].number, f"C300 必须保留六项标准业务，缺少：{'、'.join(missing)}")
        return replace(
            base,
            onu_type=onu_type,
            tcont_id=int(tcont.group(1)),
            tcont_profile=tcont.group(2),
            services=tuple(services[name] for name in C300_SERVICE_NAMES),
        )

    def _parse_c600(self, base, lines, onu_type):
        service_rows = []
        for line in lines:
            if not line.normalized.startswith("service "):
                continue
            match = re.fullmatch(r"service ([0-9]+) gemport ([0-9]+) vlan ([0-9]+)", line.normalized)
            if match is None:
                raise OnuCommandEditError(base, line.number, "C600 远端业务格式无效")
            service_rows.append((line, match))
        if not service_rows:
            raise OnuCommandEditError(base, lines[-1].number, "至少需要一条 ServiceID/VLAN 映射")
        speed_rows = [line for line in lines if line.normalized.startswith("real-speed ")]
        if len(speed_rows) > 1:
            raise OnuCommandEditError(base, speed_rows[1].number, "实际速率命令重复")
        real_speed = "auto"
        if speed_rows:
            speed = re.fullmatch(r"real-speed (xgspon|xgpon|gpon)", speed_rows[0].normalized)
            if speed is None:
                raise OnuCommandEditError(base, speed_rows[0].number, "实际速率必须为 xgspon、xgpon 或 gpon；auto 请移除此行")
            real_speed = speed.group(1)
        sn_bind_rows = [line for line in lines if line.normalized.startswith("sn-bind ")]
        if len(sn_bind_rows) > 1:
            raise OnuCommandEditError(base, sn_bind_rows[1].number, "SN 双绑定命令重复")
        if sn_bind_rows and sn_bind_rows[0].normalized != "sn-bind enable both":
            raise OnuCommandEditError(base, sn_bind_rows[0].number, "C600 只支持 SN 双绑定 enable both 或移除此行")
        tcont_id, tcont_profile = base.tcont_id, base.tcont_profile
        gemport_id, vport_id = base.gemport_id, base.vport_id
        data_row = next(
            ((line, match) for line, match in service_rows if int(match.group(3)) not in C600_FIXED_BUSINESS_LAYERS),
            None,
        )
        if data_row:
            service_line, service = data_row
            gemport_id = int(service.group(2))
            gem_rows = [
                (line, re.fullmatch(r"gemport ([0-9]+) tcont ([0-9]+)", line.normalized))
                for line in lines
            ]
            gems = [(line, match) for line, match in gem_rows if match and int(match.group(1)) == gemport_id]
            if len(gems) != 1:
                error_line = gems[-1][0] if gems else service_line
                raise OnuCommandEditError(base, error_line.number, f"普通数据 GEM {gemport_id} 必须有且仅有一条关联 T-CONT 命令")
            tcont_id = int(gems[0][1].group(2))
            tcont_rows = [
                (line, re.fullmatch(r"tcont ([0-9]+) profile (\S+)", line.normalized))
                for line in lines
            ]
            tconts = [(line, match) for line, match in tcont_rows if match and int(match.group(1)) == tcont_id]
            if len(tconts) != 1:
                error_line = tconts[-1][0] if tconts else gems[0][0]
                raise OnuCommandEditError(base, error_line.number, f"普通数据 T-CONT {tcont_id} 必须有且仅有一条 DBA 命令")
            tcont_profile = tconts[0][1].group(2)
            vport_id = gemport_id
        return replace(
            base,
            onu_type=onu_type,
            real_speed=real_speed,
            sn_bind_both=bool(sn_bind_rows),
            tcont_id=tcont_id,
            tcont_profile=tcont_profile,
            gemport_id=gemport_id,
            vport_id=vport_id,
            services=tuple(OnuServiceMapping(int(match.group(1)), int(match.group(3))) for _line, match in service_rows),
        )
