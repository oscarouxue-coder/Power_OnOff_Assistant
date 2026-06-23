from __future__ import annotations

import ctypes
import ipaddress
import locale
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from .subprocess_window import hidden_window_kwargs


@dataclass
class CommandResult:
    ok: bool
    message: str
    output: str = ""


@dataclass(frozen=True)
class AdapterInfo:
    alias: str
    status: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.alias} [{self.status}]" if self.status else self.alias


def is_windows() -> bool:
    return platform.system().lower() == "windows"


def is_admin() -> bool:
    if not is_windows():
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def list_adapter_aliases() -> List[str]:
    return [adapter.alias for adapter in list_adapters()]


def list_adapter_display_names() -> List[str]:
    return [adapter.display_name for adapter in list_adapters()]


def adapter_alias_from_display(value: str) -> str:
    return re.sub(r"\s+\[[^\]]+\]\s*$", "", value or "").strip()


def static_ip_for_vlan(vlan_name: str, device_manage_ip: str) -> str:
    """Build the PC's /24 address from the VLAN suffix and device network."""
    alias = adapter_alias_from_display(vlan_name)
    match = re.search(r"(\d+)$", alias)
    if not match:
        raise ValueError(f"VLAN 名称末尾没有可用的主机号：{alias or '未选择'}")

    host_number = int(match.group(1))
    if not 1 <= host_number <= 254:
        raise ValueError(f"VLAN 主机号必须在 1-254 之间：{host_number}")

    try:
        device_ip = ipaddress.IPv4Address((device_manage_ip or "").strip())
    except ipaddress.AddressValueError as exc:
        raise ValueError(f"样机管理 IP 格式无效：{device_manage_ip or '未填写'}") from exc

    octets = str(device_ip).split(".")
    return ".".join((*octets[:3], str(host_number)))


def list_adapters() -> List[AdapterInfo]:
    adapters = _list_adapters_with_powershell()
    if adapters:
        return _merge_ipconfig_names(adapters)
    adapters = _list_adapters_with_netsh()
    if adapters:
        return _merge_ipconfig_names(adapters)
    return _list_adapters_with_ipconfig()


def _list_adapters_with_powershell() -> List[AdapterInfo]:
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "Get-NetAdapter -IncludeHidden | Select-Object -Property Name,Status | ConvertTo-Csv -NoTypeInformation",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        shell=False,
        **hidden_window_kwargs(),
    )
    if result.returncode != 0:
        return []
    adapters: List[AdapterInfo] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('"Name"'):
            continue
        parts = _parse_csv_line(line)
        if parts:
            adapters.append(AdapterInfo(alias=_repair_mojibake(parts[0]), status=parts[1] if len(parts) > 1 else ""))
    return _unique_adapters(adapters)


def _list_adapters_with_netsh() -> List[AdapterInfo]:
    result = subprocess.run(
        ["netsh", "interface", "show", "interface"],
        capture_output=True,
        text=True,
        encoding=_console_encoding(),
        errors="ignore",
        shell=False,
        **hidden_window_kwargs(),
    )
    if result.returncode != 0:
        return []
    adapters: List[AdapterInfo] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line or "---" in line:
            continue
        if line.lower().startswith("admin") or line.startswith("管理员"):
            continue
        match = re.match(r"^(\S+)\s+(\S+)\s+(\S+)\s+(.+)$", line)
        if match:
            adapters.append(AdapterInfo(alias=_repair_mojibake(match.group(4).strip()), status=match.group(2).strip()))
    return _unique_adapters(adapters)


def _list_adapters_with_ipconfig() -> List[AdapterInfo]:
    result = subprocess.run(
        ["ipconfig", "/all"],
        capture_output=True,
        text=True,
        encoding=_console_encoding(),
        errors="ignore",
        shell=False,
        **hidden_window_kwargs(),
    )
    if result.returncode != 0:
        return []
    adapters: List[AdapterInfo] = []
    pattern = re.compile(r"^(?:Ethernet adapter|Wireless LAN adapter|未知适配器|以太网适配器|无线局域网适配器)\s+(.+?):\s*$")
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        match = pattern.match(line)
        if match:
            adapters.append(AdapterInfo(alias=_repair_mojibake(match.group(1).strip())))
    return _unique_adapters(adapters)


def set_static_ip(adapter_alias: str, ip_address: str, subnet_mask: str) -> CommandResult:
    adapter_alias = adapter_alias_from_display(adapter_alias)
    if not adapter_alias:
        return CommandResult(False, "未选择虚拟网卡")
    if not ip_address:
        return CommandResult(False, "未配置 PC 静态 IP")

    command = [
        "netsh",
        "interface",
        "ip",
        "set",
        "address",
        f"name={adapter_alias}",
        "static",
        ip_address,
        subnet_mask or "255.255.255.0",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding=_console_encoding(),
        errors="ignore",
        shell=False,
        **hidden_window_kwargs(),
    )
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 0:
        return CommandResult(True, f"已设置 {adapter_alias} 为 {ip_address}", output)
    return CommandResult(False, f"设置网卡静态 IP 失败：{output.strip() or result.returncode}", output)


def enable_adapter(adapter_alias: str) -> CommandResult:
    adapter_alias = adapter_alias_from_display(adapter_alias)
    if not adapter_alias:
        return CommandResult(False, "未选择 VLAN 网卡")

    command = [
        "netsh",
        "interface",
        "set",
        "interface",
        f"name={adapter_alias}",
        "admin=enabled",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding=_console_encoding(),
        errors="ignore",
        shell=False,
        **hidden_window_kwargs(),
    )
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 0:
        return CommandResult(True, f"已启用网卡 {adapter_alias}", output)
    return CommandResult(False, f"启用网卡失败：{output.strip() or result.returncode}", output)


def ping_host(
    host: str,
    source_address: str,
    count: int = 2,
    timeout_ms: int = 1000,
    attempts: int = 3,
    retry_seconds: float = 2.0,
) -> CommandResult:
    if not host:
        return CommandResult(False, "未配置样机管理 IP")
    if not source_address:
        return CommandResult(False, "未配置用于 ping 的 PC 静态 IP")
    command = ["ping", "-S", source_address, "-n", str(count), "-w", str(timeout_ms), host]
    command_text = " ".join(command)
    attempt_outputs = []
    for attempt in range(1, max(attempts, 1) + 1):
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding=_console_encoding(),
            errors="ignore",
            shell=False,
            **hidden_window_kwargs(),
        )
        output = (result.stdout or "") + (result.stderr or "")
        attempt_outputs.append(f"$ {command_text}\n[尝试 {attempt}]\n{output.strip()}")
        if result.returncode == 0 and _ping_has_reply(output):
            suffix = f"（第 {attempt} 次尝试）" if attempt > 1 else ""
            return CommandResult(True, f"ping {host} 成功{suffix}", "\n\n".join(attempt_outputs))
        if attempt < max(attempts, 1):
            time.sleep(retry_seconds)
    return CommandResult(False, f"ping {host} 失败", "\n\n".join(attempt_outputs))


def launch_old_tool(tool_path: Path) -> CommandResult:
    if not tool_path.exists():
        return CommandResult(False, f"未找到旧软件：{tool_path}")
    try:
        subprocess.Popen([str(tool_path)], cwd=str(tool_path.parent), shell=False)
        return CommandResult(True, "已启动旧软件，请在旧软件中完成所有样机上电")
    except OSError as exc:
        return CommandResult(False, f"启动旧软件失败：{exc}")


def run_line_check(
    adapter_alias: str,
    network_card_ip: str,
    subnet_mask: str,
    device_manage_ip: str,
    settle_seconds: float = 2.0,
) -> CommandResult:
    enable_result = enable_adapter(adapter_alias)
    if not enable_result.ok:
        return enable_result
    time.sleep(settle_seconds)

    set_output = enable_result.output
    if network_card_ip:
        set_result = set_static_ip(adapter_alias, network_card_ip, subnet_mask)
        if not set_result.ok:
            return set_result
        set_output += "\n" + set_result.output
        time.sleep(settle_seconds)
    if not network_card_ip:
        return CommandResult(False, "未配置用于 ping 的 PC 静态 IP")
    ping_result = ping_host(device_manage_ip, network_card_ip)
    if ping_result.ok:
        return CommandResult(True, ping_result.message, set_output + "\n" + ping_result.output)
    message = (
        f"{ping_result.message}。请检查样机是否已上电、网线是否松动、是否接错网卡/通道、"
        f"样机管理 IP 是否为 {device_manage_ip}。"
    )
    return CommandResult(False, message, set_output + "\n" + ping_result.output)


def missing_adapter_aliases(configured: Iterable[str], available: Iterable[str]) -> List[str]:
    available_set = {adapter_alias_from_display(item) for item in available}
    return sorted({item for item in configured if item and adapter_alias_from_display(item) not in available_set})


def _ping_has_reply(output: str) -> bool:
    lowered = output.lower()
    return (
        "ttl=" in lowered
        or "字节=" in output
        or "bytes=" in lowered
    ) and "100% loss" not in lowered and "100% 丢失" not in output


def _console_encoding() -> Optional[str]:
    return locale.getpreferredencoding(False) or None


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


def _unique_adapters(adapters: Iterable[AdapterInfo]) -> List[AdapterInfo]:
    seen = set()
    unique: List[AdapterInfo] = []
    for adapter in adapters:
        if not adapter.alias or adapter.alias in seen:
            continue
        seen.add(adapter.alias)
        unique.append(adapter)
    return unique


def _repair_mojibake(value: str) -> str:
    if not value:
        return value
    replacements = {
        "铏氭嫙缃戝崱": "虚拟网卡",
        "鏈鍦扮綉鍗": "本地网卡",
        "涓插彛鏈嶅姟鍣": "串口服务器",
        "涓奯": "上_",
        "涓媉": "下_",
        "鍙": "口",
    }
    fixed = value
    for source, target in replacements.items():
        fixed = fixed.replace(source, target)
    if fixed != value:
        return fixed
    try:
        repaired = value.encode("gbk").decode("utf-8")
    except UnicodeError:
        return value
    useful_terms = ("网卡", "串口", "虚拟", "本地", "服务器")
    if any(term in repaired for term in useful_terms):
        return repaired
    return value


def _merge_ipconfig_names(adapters: List[AdapterInfo]) -> List[AdapterInfo]:
    ipconfig_adapters = _list_adapters_with_ipconfig()
    if not ipconfig_adapters:
        return adapters

    fixed: List[AdapterInfo] = []
    for adapter in adapters:
        fixed_alias = adapter.alias
        for ipconfig_adapter in ipconfig_adapters:
            mojibake = _to_possible_mojibake(ipconfig_adapter.alias)
            if adapter.alias == mojibake or adapter.alias.startswith(mojibake) or mojibake.startswith(adapter.alias):
                fixed_alias = ipconfig_adapter.alias
                break
        fixed.append(AdapterInfo(alias=fixed_alias, status=adapter.status))
    return _unique_adapters(fixed)


def _to_possible_mojibake(value: str) -> str:
    try:
        return value.encode("utf-8").decode("gbk", errors="ignore")
    except UnicodeError:
        return value
