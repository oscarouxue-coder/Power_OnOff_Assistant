from __future__ import annotations

import os
import re
import subprocess
import time
import ctypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


DEFAULT_SERIAL_BAUD = 115200
SECURECRT_RELATIVE_PATH = Path("VanDyke Software") / "Clients" / "SecureCRT.exe"
RUNTIME_DIR_NAME = "securecrt_runtime"
PRIMARY_LOG_DIR = Path(r"F:\Aouxue\开关机环境搭建工具\开关机执行工具\样机串口日志")
FALLBACK_LOG_DIR = Path(r"D:\样机串口日志")
SECURECRT_LOG_FILE_TEMPLATE = "%H-%M%D.log"


@dataclass(frozen=True)
class SerialLogTarget:
    vlan: str
    port: str
    log_path: str
    baud: int = DEFAULT_SERIAL_BAUD
    data_bits: int = 8
    parity: str = "NONE"
    stop_bits: int = 0


@dataclass(frozen=True)
class SecureCRTLaunchResult:
    success: bool
    message: str
    targets: tuple[SerialLogTarget, ...] = ()
    log_directory: str = ""


def vlan_to_serial_port(vlan: str) -> str:
    match = re.fullmatch(r"vlan(\d+)", (vlan or "").strip(), re.IGNORECASE)
    if not match:
        raise ValueError(f"无法从 VLAN 名称确定串口：{vlan or '空值'}")
    port_number = int(match.group(1)) - 100
    if port_number < 1:
        raise ValueError(f"VLAN 与串口映射无效：{vlan}")
    return f"COM{port_number}"


def build_serial_log_targets(
    vlans: Iterable[str],
    log_dir: Path,
    baud: int = DEFAULT_SERIAL_BAUD,
) -> list[SerialLogTarget]:
    targets: list[SerialLogTarget] = []
    seen_ports = set()
    for value in vlans:
        vlan = value.strip().lower()
        port = vlan_to_serial_port(vlan)
        if port in seen_ports:
            continue
        seen_ports.add(port)
        log_path = log_dir / SECURECRT_LOG_FILE_TEMPLATE
        targets.append(SerialLogTarget(vlan=vlan, port=port, log_path=str(log_path), baud=baud))
    return targets


def resolve_serial_log_directory(
    primary_log_dir: Path = PRIMARY_LOG_DIR,
    fallback_log_dir: Path = FALLBACK_LOG_DIR,
    primary_drive: Path | None = None,
) -> Path:
    drive = primary_drive or Path(primary_log_dir.anchor)
    log_dir = primary_log_dir if drive.exists() else fallback_log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def find_securecrt_executable() -> Path | None:
    candidates = []
    for environment_name in ("ProgramW6432", "ProgramFiles"):
        program_files = os.environ.get(environment_name)
        if program_files:
            candidates.append(Path(program_files) / SECURECRT_RELATIVE_PATH)
    candidates.append(Path(r"C:\Program Files") / SECURECRT_RELATIVE_PATH)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def launch_securecrt_serial_logs(tool_root: Path, vlans: Iterable[str]) -> SecureCRTLaunchResult:
    securecrt_path = find_securecrt_executable()
    if securecrt_path is None:
        return SecureCRTLaunchResult(False, "未找到 SecureCRT 9.7，请确认已安装到 Program Files。")
    log_dir = resolve_serial_log_directory()
    targets = build_serial_log_targets(vlans, log_dir)
    if not targets:
        return SecureCRTLaunchResult(False, "没有可连接的目标 VLAN。")

    runtime_dir = tool_root / RUNTIME_DIR_NAME
    runtime_dir.mkdir(parents=True, exist_ok=True)
    script_path = runtime_dir / "open_serial_logs.vbs"
    if not script_path.exists() or script_path.read_text(encoding="utf-8") != SECURECRT_SCRIPT:
        script_path.write_text(SECURECRT_SCRIPT, encoding="utf-8")

    manifest_path = runtime_dir / f"serial_targets_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.txt"
    manifest_lines = [
        "\t".join(
            [
                target.vlan,
                target.port,
                target.log_path,
                str(target.baud),
                str(target.data_bits),
                target.parity,
                str(target.stop_bits),
            ]
        )
        for target in targets
    ]
    manifest_path.write_text("\n".join(manifest_lines), encoding="utf-16")

    try:
        subprocess.Popen(
            [str(securecrt_path), "/ARG", str(manifest_path), "/SCRIPT", str(script_path)],
            cwd=str(securecrt_path.parent),
            shell=False,
        )
    except OSError as exc:
        return SecureCRTLaunchResult(False, f"启动 SecureCRT 失败：{exc}", tuple(targets), str(log_dir))

    if not _wait_for_visible_securecrt_window():
        return SecureCRTLaunchResult(
            False,
            "已提交 SecureCRT 启动命令，但未检测到可见主窗口。请检查 SecureCRT 是否立即退出或被安全软件拦截。",
            tuple(targets),
            str(log_dir),
        )

    mapping = "、".join(f"{target.vlan}→{target.port}" for target in targets)
    return SecureCRTLaunchResult(True, f"已启动 SecureCRT 串口连接：{mapping}", tuple(targets), str(log_dir))


def _wait_for_visible_securecrt_window(timeout_seconds: float = 12.0) -> bool:
    if os.name != "nt":
        return True
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        handle = _find_securecrt_window()
        if handle:
            user32 = ctypes.windll.user32
            user32.ShowWindow(handle, 9)
            user32.BringWindowToTop(handle)
            user32.SetForegroundWindow(handle)
            return True
        time.sleep(0.25)
    return False


def _find_securecrt_window() -> int:
    user32 = ctypes.windll.user32
    handles: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_callback(handle, _lparam):
        if not user32.IsWindowVisible(handle):
            return True
        title_length = user32.GetWindowTextLengthW(handle)
        if title_length <= 0:
            return True
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(handle, title_buffer, title_length + 1)
        if _is_securecrt_main_window_title(title_buffer.value):
            handles.append(int(handle))
            return False
        return True

    user32.EnumWindows(enum_callback, 0)
    return handles[0] if handles else 0
def _is_securecrt_main_window_title(title: str) -> bool:
    normalized = (title or "").strip().lower()
    return "securecrt" in normalized and normalized != "securecrt"


SECURECRT_SCRIPT = '''#$language = "VBScript"
#$interface = "1.0"

Option Explicit

Sub Main
    If crt.Arguments.Count < 1 Then
        crt.Dialog.MessageBox "Missing serial target manifest.", "Serial Logging"
        Exit Sub
    End If

    Dim fso, manifestFile, line, fields, sessionName, sessionConfig, tab, errors
    Set fso = CreateObject("Scripting.FileSystemObject")
    Set manifestFile = fso.OpenTextFile(crt.Arguments.GetArg(0), 1, False, -1)
    errors = ""

    Do Until manifestFile.AtEndOfStream
        line = manifestFile.ReadLine
        If Len(Trim(line)) > 0 Then
            fields = Split(line, vbTab)
            If UBound(fields) >= 6 Then
                sessionName = fields(0)

                On Error Resume Next
                Err.Clear
                Set sessionConfig = crt.OpenSessionConfiguration("Default_Serial")
                sessionConfig.SetOption "Protocol Name", "Serial"
                sessionConfig.SetOption "Com Port", fields(1)
                sessionConfig.SetOption "Baud Rate", CLng(fields(3))
                sessionConfig.SetOption "Data Bits", CInt(fields(4))
                sessionConfig.SetOption "Parity", 0
                sessionConfig.SetOption "Stop Bits", CInt(fields(6))
                sessionConfig.SetOption "CTS Flow", False
                sessionConfig.SetOption "DSR Flow", False
                sessionConfig.SetOption "XON Flow", False
                sessionConfig.SetOption "Log Filename V2", fields(2)
                sessionConfig.SetOption "Custom Log Message Each Line", "[%Y-%M-%D %h:%m:%s] "
                sessionConfig.SetOption "Log Timestamp Each Line", False
                sessionConfig.SetOption "Log Mode", 1
                sessionConfig.SetOption "Start Log Upon Connect", True
                sessionConfig.SetOption "New Log File At Midnight", True
                sessionConfig.Save sessionName

                Err.Clear
                Set tab = crt.Session.ConnectInTab("/S " & Chr(34) & sessionName & Chr(34), True, True)
                If Err.Number <> 0 Then
                    errors = errors & fields(0) & " (" & fields(1) & "): " & Err.Description & vbCrLf
                ElseIf Not tab.Session.Connected Then
                    errors = errors & fields(0) & " (" & fields(1) & "): connection failed" & vbCrLf
                Else
                    tab.Session.SetStatusText fields(0) & " / " & fields(1) & " / logging"
                End If
                On Error GoTo 0
            End If
        End If
    Loop
    manifestFile.Close

    If Len(errors) > 0 Then
        crt.Dialog.MessageBox "Some serial connections failed:" & vbCrLf & vbCrLf & errors, "Serial Logging"
    End If
End Sub
'''
