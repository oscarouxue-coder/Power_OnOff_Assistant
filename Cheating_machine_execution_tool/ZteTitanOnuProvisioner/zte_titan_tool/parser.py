import re
from typing import List, Tuple

from .models import ServiceMapping, UnconfiguredOnu


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
UNCONFIGURED_RE = re.compile(
    r"^(gpon_olt-\d+/\d+/\d+)\s+(\S+)\s+(\S+)\s+(.+?)\s*$",
    re.IGNORECASE,
)
REGISTERED_RE = re.compile(
    r"^\s*onu\s+(\d+)\s+type\s+(\S+)\s+sn\s+(\S+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def clean_terminal_text(text: str) -> str:
    return ANSI_RE.sub("", text).replace("\r", "").replace("\x08", "")


def parse_unconfigured_onus(output: str) -> List[UnconfiguredOnu]:
    result: List[UnconfiguredOnu] = []
    for line in clean_terminal_text(output).splitlines():
        match = UNCONFIGURED_RE.match(line.strip())
        if not match:
            continue
        interface, model, serial_number, speed_mode = match.groups()
        if model.lower() == "model" or serial_number.lower() == "sn":
            continue
        result.append(
            UnconfiguredOnu(
                olt_interface=interface,
                model=model,
                serial_number=serial_number,
                speed_mode=speed_mode.strip(),
            )
        )
    return result


def parse_registered_onus(output: str) -> List[Tuple[int, str, str]]:
    return [
        (int(onu_id), onu_type, serial_number)
        for onu_id, onu_type, serial_number in REGISTERED_RE.findall(
            clean_terminal_text(output)
        )
    ]


def parse_service_mappings(text: str) -> List[ServiceMapping]:
    mappings: List[ServiceMapping] = []
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"(\d+)\s*[,=:]\s*(\d+)", line)
        if not match:
            raise ValueError(
                f"业务映射第 {line_number} 行格式错误，应为 ServiceID,VLAN"
            )
        mappings.append(ServiceMapping(int(match.group(1)), int(match.group(2))))
    return mappings


def speed_mode_to_cli(speed_mode: str) -> str:
    normalized = speed_mode.strip().upper().replace("_", "-")
    return {
        "XGS-PON": "xgspon",
        "XG-PON": "xgpon",
        "GPON": "gpon",
    }.get(normalized, "auto")
