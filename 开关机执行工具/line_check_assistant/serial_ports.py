from __future__ import annotations

import locale
import re
import subprocess
from dataclasses import dataclass
from typing import List, Optional

from .subprocess_window import hidden_window_kwargs


@dataclass(frozen=True)
class SerialPortInfo:
    friendly_name: str
    port: str
    status: str = ""

    @property
    def display_name(self) -> str:
        suffix = f" [{self.status}]" if self.status else ""
        return f"{self.friendly_name}{suffix}"


def list_prolific_ports() -> List[SerialPortInfo]:
    ports = _list_with_pnp_device()
    if ports:
        return ports
    return _list_with_wmi()


def port_from_display(display_name: str) -> str:
    match = re.search(r"\((COM\d+)\)", display_name or "", re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _list_with_pnp_device() -> List[SerialPortInfo]:
    script = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "Get-PnpDevice -Class Ports | "
        "Where-Object { $_.FriendlyName -like 'Prolific*' } | "
        "Select-Object FriendlyName,Status | ConvertTo-Csv -NoTypeInformation"
    )
    return _run_port_script(script)


def _list_with_wmi() -> List[SerialPortInfo]:
    script = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "Get-CimInstance Win32_PnPEntity | "
        "Where-Object { $_.Name -like 'Prolific*' -and $_.Name -match '\\\\(COM\\\\d+\\\\)' } | "
        "Select-Object @{Name='FriendlyName';Expression={$_.Name}},@{Name='Status';Expression={$_.Status}} | "
        "ConvertTo-Csv -NoTypeInformation"
    )
    return _run_port_script(script)


def _run_port_script(script: str) -> List[SerialPortInfo]:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        shell=False,
        **hidden_window_kwargs(),
    )
    if result.returncode != 0:
        return []

    ports: List[SerialPortInfo] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith('"FriendlyName"'):
            continue
        parts = _parse_csv_line(line)
        if not parts:
            continue
        friendly_name = _repair_mojibake(parts[0])
        port = port_from_display(friendly_name)
        if not port:
            continue
        ports.append(SerialPortInfo(friendly_name=friendly_name, port=port, status=parts[1] if len(parts) > 1 else ""))
    return _unique_ports(ports)


def _parse_csv_line(line: str) -> List[str]:
    values: List[str] = []
    current = ""
    in_quote = False
    index = 0
    while index < len(line):
        char = line[index]
        if char == '"':
            if in_quote and index + 1 < len(line) and line[index + 1] == '"':
                current += '"'
                index += 1
            else:
                in_quote = not in_quote
        elif char == "," and not in_quote:
            values.append(current)
            current = ""
        else:
            current += char
        index += 1
    values.append(current)
    return [value.strip() for value in values]


def _unique_ports(ports: List[SerialPortInfo]) -> List[SerialPortInfo]:
    seen = set()
    unique: List[SerialPortInfo] = []
    for item in ports:
        if item.port in seen:
            continue
        seen.add(item.port)
        unique.append(item)
    return sorted(unique, key=lambda item: _port_sort_key(item.port))


def _port_sort_key(port: str) -> int:
    match = re.search(r"\d+", port)
    return int(match.group(0)) if match else 9999


def _repair_mojibake(value: str) -> str:
    try:
        return value.encode("gbk").decode("utf-8")
    except UnicodeError:
        return value
