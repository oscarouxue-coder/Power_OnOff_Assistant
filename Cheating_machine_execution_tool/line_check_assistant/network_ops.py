from __future__ import annotations

import ctypes
import ipaddress
import locale
import platform
import re
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional

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


@dataclass(frozen=True)
class UnregisteredOnu:
    onu_index: str
    serial_number: str
    state: str


@dataclass(frozen=True)
class RegisteredOnuState:
    onu_index: str
    admin_state: str
    omcc_state: str
    phase_state: str
    channel: str = ""

    @property
    def interface_name(self) -> str:
        return f"gpon-onu_{self.onu_index}"

    @property
    def pon_path(self) -> str:
        match = re.match(r"^(?P<pon>\d+/\d+/\d+):\d+$", self.onu_index)
        return match.group("pon") if match else ""

    @property
    def onu_id(self) -> str:
        match = re.match(r"^\d+/\d+/\d+:(?P<onu_id>\d+)$", self.onu_index)
        return match.group("onu_id") if match else ""

    @property
    def is_reusable_offline(self) -> bool:
        return self.admin_state.lower() == "enable" and (
            self.omcc_state.lower() != "enable" or self.phase_state.lower() != "working"
        )


ONU_REGISTRATION_TYPE = "SD-41"
ONU_REGISTRATION_SERVICE_PORTS = (
    (1, 1, 200, "Internet"),
    (2, 2, 46, "TR069"),
    (3, 3, 335, "VOICE"),
    (4, 4, 600, "IPTV"),
    (5, 5, 171, "Internet2"),
    (6, 6, 172, "Internet3"),
)


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


def check_telnet_connection(host: str, port: int = 23, timeout: float = 3.0) -> CommandResult:
    host = (host or "").strip()
    if not host:
        return CommandResult(False, "未填写 OLT IP")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return CommandResult(False, f"OLT IP 格式无效：{host}")

    endpoint = f"{host}:{port}"
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return CommandResult(True, f"Telnet 连通性测试通过：{endpoint}")
    except socket.timeout:
        return CommandResult(False, f"Telnet 连接超时：{endpoint}")
    except OSError as exc:
        return CommandResult(False, f"Telnet 连接失败：{endpoint}（{exc}）")


def login_olt_and_enter_global_mode(
    host: str,
    username: str,
    password: str,
    port: int = 23,
    timeout: float = 5.0,
) -> CommandResult:
    host = (host or "").strip()
    username = (username or "").strip()
    password = password or ""
    if not host:
        return CommandResult(False, "未填写 OLT IP")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return CommandResult(False, f"OLT IP 格式无效：{host}")
    if not username:
        return CommandResult(False, "未填写 OLT 用户名")
    if not password:
        return CommandResult(False, "未填写 OLT 密码")

    endpoint = f"{host}:{port}"
    transcript = bytearray()
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            connection.settimeout(timeout)
            output = _telnet_read_until(connection, (b"username", b"login:", b"password", b">", b"#"), timeout)
            transcript.extend(output)
            lowered = bytes(transcript).lower()

            if b"username" in lowered or b"login:" in lowered:
                _telnet_send_line(connection, username)
                output = _telnet_read_until(connection, (b"password",), timeout)
                transcript.extend(output)
                lowered = bytes(transcript).lower()

            if b"password" in lowered:
                _telnet_send_line(connection, password)
                output = _telnet_read_until(connection, (b">", b"#", b"incorrect", b"invalid", b"failed", b"denied"), timeout)
                transcript.extend(output)
                lowered = bytes(transcript).lower()

            if _telnet_has_failure(lowered):
                return CommandResult(False, f"OLT 登录失败：{endpoint}", _decode_telnet_output(bytes(transcript)))
            if b">" not in lowered and b"#" not in lowered:
                return CommandResult(False, f"OLT 登录失败：未检测到命令提示符 {endpoint}", _decode_telnet_output(bytes(transcript)))

            _telnet_send_line(connection, "configure terminal")
            output = _telnet_read_until(connection, (b"(config", b"config)#", b"#", b"invalid", b"error", b"failed"), timeout)
            transcript.extend(output)
            lowered = bytes(transcript).lower()
            if _telnet_has_failure(lowered):
                return CommandResult(False, "OLT 登录成功，但进入全局模式失败", _decode_telnet_output(bytes(transcript)))
            if b"(config" in lowered or b"config)#" in lowered:
                return CommandResult(True, "OLT 登录成功，已进入全局模式", _decode_telnet_output(bytes(transcript)))
            return CommandResult(False, "OLT 登录成功，但未确认已进入全局模式", _decode_telnet_output(bytes(transcript)))
    except socket.timeout:
        return CommandResult(False, f"OLT 登录超时：{endpoint}", _decode_telnet_output(bytes(transcript)))
    except OSError as exc:
        return CommandResult(False, f"OLT 登录失败：{endpoint}（{exc}）", _decode_telnet_output(bytes(transcript)))


def query_unregistered_onus(
    host: str,
    username: str,
    password: str,
    port: int = 23,
    timeout: float = 5.0,
) -> CommandResult:
    host = (host or "").strip()
    username = (username or "").strip()
    password = password or ""
    if not host:
        return CommandResult(False, "未填写 OLT IP")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return CommandResult(False, f"OLT IP 格式无效：{host}")
    if not username:
        return CommandResult(False, "未填写 OLT 用户名")
    if not password:
        return CommandResult(False, "未填写 OLT 密码")

    endpoint = f"{host}:{port}"
    transcript = bytearray()
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            connection.settimeout(timeout)
            output = _telnet_read_until(connection, (b"username", b"login:", b"password", b">", b"#"), timeout)
            transcript.extend(output)
            lowered = bytes(transcript).lower()

            if b"username" in lowered or b"login:" in lowered:
                _telnet_send_line(connection, username)
                output = _telnet_read_until(connection, (b"password",), timeout)
                transcript.extend(output)
                lowered = bytes(transcript).lower()

            if b"password" in lowered:
                _telnet_send_line(connection, password)
                output = _telnet_read_until(connection, (b">", b"#", b"incorrect", b"invalid", b"failed", b"denied"), timeout)
                transcript.extend(output)
                lowered = bytes(transcript).lower()

            if _telnet_has_failure(lowered):
                return CommandResult(False, f"OLT 登录失败：{endpoint}", _decode_telnet_output(bytes(transcript)))
            if b">" not in lowered and b"#" not in lowered:
                return CommandResult(False, f"OLT 登录失败：未检测到命令提示符 {endpoint}", _decode_telnet_output(bytes(transcript)))

            _telnet_send_line(connection, "terminal length 0")
            transcript.extend(_telnet_read_until(connection, (b"#", b">"), timeout))
            _telnet_send_line(connection, "show gpon onu uncfg")
            output = _telnet_read_until(connection, (b"#", b">"), timeout)
            transcript.extend(output)
            raw_output = _decode_telnet_output(output)
            onus = parse_unregistered_onus(raw_output)
            if not onus:
                if "No related information" in raw_output or "No relate information" in raw_output:
                    return CommandResult(True, "未查询到未注册 ONU", raw_output)
                return CommandResult(True, "未查询到未注册 ONU", raw_output)
            lines = [f"查询到 {len(onus)} 个未注册 ONU："]
            lines.extend(f"{onu.onu_index}  SN:{onu.serial_number}  状态:{onu.state}" for onu in onus)
            return CommandResult(True, "\n".join(lines), raw_output)
    except socket.timeout:
        return CommandResult(False, f"查询未注册 ONU 超时：{endpoint}", _decode_telnet_output(bytes(transcript)))
    except OSError as exc:
        return CommandResult(False, f"查询未注册 ONU 失败：{endpoint}（{exc}）", _decode_telnet_output(bytes(transcript)))


def save_olt_configuration(
    host: str,
    username: str,
    password: str,
    port: int = 23,
    timeout: float = 8.0,
) -> CommandResult:
    host = (host or "").strip()
    username = (username or "").strip()
    password = password or ""
    if not host:
        return CommandResult(False, "未填写 OLT IP")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return CommandResult(False, f"OLT IP 格式无效：{host}")
    if not username:
        return CommandResult(False, "未填写 OLT 用户名")
    if not password:
        return CommandResult(False, "未填写 OLT 密码")

    endpoint = f"{host}:{port}"
    transcript = bytearray()
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            connection.settimeout(timeout)
            output = _telnet_read_until(connection, (b"username", b"login:", b"password", b">", b"#"), timeout)
            transcript.extend(output)
            lowered = bytes(transcript).lower()

            if b"username" in lowered or b"login:" in lowered:
                _telnet_send_line(connection, username)
                output = _telnet_read_until(connection, (b"password",), timeout)
                transcript.extend(output)
                lowered = bytes(transcript).lower()

            if b"password" in lowered:
                _telnet_send_line(connection, password)
                output = _telnet_read_until(connection, (b">", b"#", b"incorrect", b"invalid", b"failed", b"denied"), timeout)
                transcript.extend(output)
                lowered = bytes(transcript).lower()

            if _telnet_has_failure(lowered):
                return CommandResult(False, f"OLT 登录失败：{endpoint}", _decode_telnet_output(bytes(transcript)))
            if b">" not in lowered and b"#" not in lowered:
                return CommandResult(False, f"OLT 登录失败：未检测到命令提示符 {endpoint}", _decode_telnet_output(bytes(transcript)))

            if b"(config" in lowered:
                exit_result = _telnet_exit_to_exec_mode(connection, timeout, transcript, output)
                if not exit_result.ok:
                    return exit_result

            _telnet_send_line(connection, "write")
            output = _telnet_read_until(connection, (b"#", b">", b"invalid", b"error", b"failed", b"success", b"complete"), timeout)
            transcript.extend(output)
            if _telnet_has_failure(output.lower()):
                return CommandResult(False, "OLT 配置保存失败", _decode_telnet_output(bytes(transcript)))
            return CommandResult(True, "OLT 最新配置已写入启动配置", _decode_telnet_output(bytes(transcript)))
    except socket.timeout:
        return CommandResult(False, f"OLT 配置保存超时：{endpoint}", _decode_telnet_output(bytes(transcript)))
    except OSError as exc:
        return CommandResult(False, f"OLT 配置保存失败：{endpoint}（{exc}）", _decode_telnet_output(bytes(transcript)))


def register_unregistered_onus(
    host: str,
    username: str,
    password: str,
    onus: Iterable[UnregisteredOnu],
    onu_type: str = ONU_REGISTRATION_TYPE,
    port: int = 23,
    timeout: float = 5.0,
) -> CommandResult:
    host = (host or "").strip()
    username = (username or "").strip()
    password = password or ""
    onu_type = (onu_type or "").strip() or ONU_REGISTRATION_TYPE
    selected_onus = list(onus or [])
    if not host:
        return CommandResult(False, "未填写 OLT IP")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return CommandResult(False, f"OLT IP 格式无效：{host}")
    if not username:
        return CommandResult(False, "未填写 OLT 用户名")
    if not password:
        return CommandResult(False, "未填写 OLT 密码")
    if not selected_onus:
        return CommandResult(False, "未选择要注册的 ONU")

    try:
        command_groups = [(onu, build_onu_registration_commands(onu, onu_type)) for onu in selected_onus]
    except ValueError as exc:
        return CommandResult(False, str(exc))

    endpoint = f"{host}:{port}"
    transcript = bytearray()
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            connection.settimeout(timeout)
            output = _telnet_read_until(connection, (b"username", b"login:", b"password", b">", b"#"), timeout)
            transcript.extend(output)
            lowered = bytes(transcript).lower()

            if b"username" in lowered or b"login:" in lowered:
                _telnet_send_line(connection, username)
                output = _telnet_read_until(connection, (b"password",), timeout)
                transcript.extend(output)
                lowered = bytes(transcript).lower()

            if b"password" in lowered:
                _telnet_send_line(connection, password)
                output = _telnet_read_until(connection, (b">", b"#", b"incorrect", b"invalid", b"failed", b"denied"), timeout)
                transcript.extend(output)
                lowered = bytes(transcript).lower()

            if _telnet_has_failure(lowered):
                return CommandResult(False, f"OLT 登录失败：{endpoint}", _decode_telnet_output(bytes(transcript)))
            if b">" not in lowered and b"#" not in lowered:
                return CommandResult(False, f"OLT 登录失败：未检测到命令提示符 {endpoint}", _decode_telnet_output(bytes(transcript)))

            _telnet_send_line(connection, "configure terminal")
            output = _telnet_read_until(connection, (b"(config", b"config)#", b"#", b"invalid", b"error", b"failed"), timeout)
            transcript.extend(output)
            if _telnet_has_failure(output.lower()):
                return CommandResult(False, "进入全局模式失败，未执行 ONU 注册", _decode_telnet_output(bytes(transcript)))

            actions: List[str] = []
            for onu, commands in command_groups:
                register_result = _run_onu_registration_commands(connection, timeout, transcript, commands)
                if register_result.ok:
                    actions.append(f"{onu.onu_index} SN:{onu.serial_number} 新增配置成功")
                    continue

                cleanup = _delete_offline_onus_and_reregister(
                    connection,
                    timeout,
                    transcript,
                    onu,
                    commands,
                )
                if not cleanup.ok:
                    return CommandResult(
                        False,
                        f"ONU 新增注册失败，且清理离线 ONU 后重新注册失败：{onu.onu_index} SN:{onu.serial_number} / {register_result.message}；{cleanup.message}",
                        _decode_telnet_output(bytes(transcript)),
                    )
                actions.append(f"{onu.onu_index} SN:{onu.serial_number} 新增配置失败后{cleanup.message}")

            _telnet_send_line(connection, "end")
            transcript.extend(_telnet_read_until(connection, (b"#", b">"), timeout))
            return CommandResult(
                True,
                f"已处理 {len(selected_onus)} 个 ONU 注册配置（未保存 OLT 配置，请重新查询确认上线）：{'；'.join(actions)}",
                _decode_telnet_output(bytes(transcript)),
            )
    except socket.timeout:
        return CommandResult(False, f"ONU 注册超时：{endpoint}", _decode_telnet_output(bytes(transcript)))
    except OSError as exc:
        return CommandResult(False, f"ONU 注册失败：{endpoint}（{exc}）", _decode_telnet_output(bytes(transcript)))


def build_onu_registration_commands(onu: UnregisteredOnu, onu_type: str = ONU_REGISTRATION_TYPE) -> List[str]:
    onu_index = (onu.onu_index or "").strip()
    serial_number = (onu.serial_number or "").strip()
    if not serial_number:
        raise ValueError(f"ONU 缺少 SN：{onu_index or '未知接口'}")
    match = re.match(r"^gpon-onu_(?P<pon>\d+/\d+/\d+):(?P<onu_id>\d+)$", onu_index, re.IGNORECASE)
    if not match:
        raise ValueError(f"ONU 接口格式无效：{onu_index or '未填写'}")

    pon_path = match.group("pon")
    onu_id = match.group("onu_id")
    onu_interface = f"gpon-onu_{pon_path}:{onu_id}"
    commands = [
        f"interface gpon-olt_{pon_path}",
        f"onu {onu_id} type {onu_type} sn {serial_number}",
        "exit",
        f"interface {onu_interface}",
        "sn-bind enable sn",
        "tcont 1 profile 1G",
    ]
    commands.extend(f"gemport {gemport} tcont 1" for gemport, _vport, _vlan, _service in ONU_REGISTRATION_SERVICE_PORTS)
    commands.extend(
        f"service-port {gemport} vport {vport} user-vlan {vlan} vlan {vlan}"
        for gemport, vport, vlan, _service in ONU_REGISTRATION_SERVICE_PORTS
    )
    commands.extend(["exit", f"pon-onu-mng {onu_interface}"])
    commands.extend(
        f"service {service} gemport {gemport} vlan {vlan}"
        for gemport, _vport, vlan, service in ONU_REGISTRATION_SERVICE_PORTS
    )
    commands.extend(["mvlan 600", "exit"])
    return commands


def _run_onu_registration_commands(
    connection,
    timeout: float,
    transcript: bytearray,
    commands: Iterable[str],
) -> CommandResult:
    for command in commands:
        _telnet_send_line(connection, command)
        output = _telnet_read_until(connection, (b"#", b">", b"invalid", b"error", b"failed"), timeout)
        transcript.extend(output)
        if _telnet_has_failure(output.lower()):
            return CommandResult(False, f"注册命令失败：{command}")
    return CommandResult(True, "注册命令下发成功")


def _delete_offline_onus_and_reregister(
    connection,
    timeout: float,
    transcript: bytearray,
    onu: UnregisteredOnu,
    commands: Iterable[str],
) -> CommandResult:
    pon_path = _pon_path_from_onu_index(onu.onu_index)
    if not pon_path:
        return CommandResult(False, f"无法识别新 ONU 所在 PON 口：{onu.onu_index}")

    _telnet_send_line(connection, "end")
    transcript.extend(_telnet_read_until(connection, (b"#", b">"), timeout))
    _telnet_send_line(connection, "terminal length 0")
    transcript.extend(_telnet_read_until(connection, (b"#", b">"), timeout))
    _telnet_send_line(connection, "show gpon onu state")
    output = _telnet_read_until(connection, (b"#", b">"), timeout)
    transcript.extend(output)
    offline_onus = [item for item in parse_registered_onu_states(_decode_telnet_output(output)) if item.is_reusable_offline]
    if not offline_onus:
        return CommandResult(False, "未找到已注册但不在线的 ONU，无法清理后重试")

    ordered_offline_onus = sorted(offline_onus, key=lambda item: 0 if item.pon_path == pon_path else 1)
    _telnet_send_line(connection, "configure terminal")
    output = _telnet_read_until(connection, (b"(config", b"config)#", b"#", b"invalid", b"error", b"failed"), timeout)
    transcript.extend(output)
    if _telnet_has_failure(output.lower()):
        return CommandResult(False, "重新进入全局模式失败，未能删除离线 ONU")

    deleted: List[str] = []
    for offline_onu in ordered_offline_onus:
        if not offline_onu.pon_path or not offline_onu.onu_id:
            continue
        delete_commands = [
            f"interface gpon-olt_{offline_onu.pon_path}",
            f"no onu {offline_onu.onu_id}",
            "exit",
        ]
        for command in delete_commands:
            _telnet_send_line(connection, command)
            output = _telnet_read_until(connection, (b"#", b">", b"invalid", b"error", b"failed"), timeout)
            transcript.extend(output)
            if _telnet_has_failure(output.lower()):
                return CommandResult(False, f"删除离线 ONU 失败：{offline_onu.interface_name} / {command}")
        deleted.append(offline_onu.interface_name)

    if not deleted:
        return CommandResult(False, "未解析到可删除的离线 ONU 接口")

    retry_result = _run_onu_registration_commands(connection, timeout, transcript, commands)
    if not retry_result.ok:
        return CommandResult(False, f"已删除离线 ONU，但重新注册失败：{retry_result.message}")

    same_pon_count = sum(1 for item in ordered_offline_onus if item.interface_name in deleted and item.pon_path == pon_path)
    other_pon_count = len(deleted) - same_pon_count
    return CommandResult(True, f"删除 {len(deleted)} 个离线 ONU 后重新注册成功（同 PON {same_pon_count} 个，其它 PON {other_pon_count} 个）")


def _pon_path_from_onu_index(onu_index: str) -> str:
    match = re.match(r"^gpon-onu_(?P<pon>\d+/\d+/\d+):\d+$", (onu_index or "").strip(), re.IGNORECASE)
    return match.group("pon") if match else ""


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


def prepare_network_for_sample(
    adapter_alias: str,
    network_card_ip: str,
    subnet_mask: str,
    on_output: Optional[Callable[[str], None]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    settle_seconds: float = 2.0,
) -> CommandResult:
    """为单台样机准备网络：先启用网卡，再把 PC 静态 IP 设置到与样机同网段。"""

    def emit(message: str) -> None:
        if on_output:
            on_output(message)

    adapter_alias = adapter_alias_from_display(adapter_alias)
    if not adapter_alias:
        return CommandResult(False, "未选择 VLAN 网卡")
    if not network_card_ip:
        return CommandResult(False, "未配置用于访问样机的 PC 静态 IP")

    emit(f"检查并启用网卡：{adapter_alias}")
    enable_result = enable_adapter(adapter_alias)
    emit(enable_result.message)
    if not enable_result.ok:
        return enable_result
    sleep_fn(settle_seconds)

    emit(f"设置 {adapter_alias} 静态 IP：{network_card_ip}（{subnet_mask or '255.255.255.0'}）")
    set_result = set_static_ip(adapter_alias, network_card_ip, subnet_mask)
    emit(set_result.message)
    if not set_result.ok:
        return set_result
    sleep_fn(settle_seconds)

    return CommandResult(
        True,
        f"已准备 {adapter_alias} 静态 IP：{network_card_ip}",
        enable_result.output + "\n" + set_result.output,
    )


def run_line_check(
    adapter_alias: str,
    network_card_ip: str,
    subnet_mask: str,
    device_manage_ip: str,
    settle_seconds: float = 2.0,
) -> CommandResult:
    if not network_card_ip:
        return CommandResult(False, "未配置用于 ping 的 PC 静态 IP")
    network_result = prepare_network_for_sample(
        adapter_alias,
        network_card_ip,
        subnet_mask,
        sleep_fn=time.sleep,
        settle_seconds=settle_seconds,
    )
    if not network_result.ok:
        return network_result
    set_output = network_result.output
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


def _telnet_send_line(connection, value: str) -> None:
    connection.sendall((value + "\r\n").encode("ascii", errors="ignore"))


def _telnet_read_until(connection, patterns: Iterable[bytes], timeout: float) -> bytes:
    expected = tuple(pattern.lower() for pattern in patterns)
    chunks = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            chunk = connection.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        chunks.extend(chunk)
        lowered = bytes(chunks).lower()
        if any(pattern in lowered for pattern in expected):
            break
    return bytes(chunks)


def _telnet_has_failure(output: bytes) -> bool:
    return any(keyword in output for keyword in (b"incorrect", b"invalid", b"failed", b"denied", b"error"))


def _telnet_exit_to_exec_mode(connection, timeout: float, transcript: bytearray, prompt_output: bytes) -> CommandResult:
    output = prompt_output
    for _attempt in range(5):
        if b"(config" not in output.lower():
            return CommandResult(True, "已退出到 OLT 执行模式")
        _telnet_send_line(connection, "exit")
        output = _telnet_read_until(connection, (b"#", b">", b"invalid", b"error", b"failed"), timeout)
        transcript.extend(output)
        lowered = output.lower()
        if _telnet_has_failure(lowered):
            return CommandResult(False, "退出全局模式失败，未执行 write", _decode_telnet_output(bytes(transcript)))
    return CommandResult(False, "多次 exit 后仍未退出全局模式，未执行 write", _decode_telnet_output(bytes(transcript)))


def _decode_telnet_output(output: bytes) -> str:
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return output.decode(encoding, errors="ignore")
        except UnicodeError:
            continue
    return output.decode(errors="ignore")


def parse_unregistered_onus(output: str) -> List[UnregisteredOnu]:
    onus: List[UnregisteredOnu] = []
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("-") or line.lower().startswith("onuindex"):
            continue
        match = re.match(r"^(gpon-onu_\S+)\s+(\S+)\s+(\S+)\s*$", line, re.IGNORECASE)
        if match:
            onus.append(UnregisteredOnu(onu_index=match.group(1), serial_number=match.group(2), state=match.group(3)))
    return onus


def parse_registered_onu_states(output: str) -> List[RegisteredOnuState]:
    states: List[RegisteredOnuState] = []
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if (
            not line
            or line.startswith("-")
            or line.lower().startswith("onuindex")
            or line.lower().startswith("onu number")
        ):
            continue
        match = re.match(r"^(?P<onu>\d+/\d+/\d+:\d+)\s+(?P<admin>\S+)\s+(?P<omcc>\S+)\s+(?P<phase>\S+)(?:\s+(?P<channel>.+))?$", line)
        if match:
            states.append(
                RegisteredOnuState(
                    onu_index=match.group("onu"),
                    admin_state=match.group("admin"),
                    omcc_state=match.group("omcc"),
                    phase_state=match.group("phase"),
                    channel=(match.group("channel") or "").strip(),
                )
            )
    return states


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
