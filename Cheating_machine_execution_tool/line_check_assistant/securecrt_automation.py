from __future__ import annotations

import os
import re
import subprocess
import time
import ctypes
import tempfile
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
BOOT_USERNAME = "telecomadmin"
BOOT_PASSWORD = "nE7jA%5m"
FACTORY_RESET_COMMAND = "firstboot -y;reboot"
TFTP_REMOTE_IMAGE = "tclinux_allinone"


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


@dataclass(frozen=True)
class SecureCRTUpgradeTarget:
    vlan: str
    port: str
    log_path: str
    status_path: str
    boot_enter_signal_path: str
    command_signal_path: str
    final_login_signal_path: str
    tftp_command: str
    restore_factory: bool = False
    baud: int = DEFAULT_SERIAL_BAUD
    data_bits: int = 8
    parity: str = "NONE"
    stop_bits: int = 0
    username: str = BOOT_USERNAME
    password: str = BOOT_PASSWORD
    final_username: str = ""
    final_password: str = ""
    factory_reset_command: str = FACTORY_RESET_COMMAND


@dataclass(frozen=True)
class SecureCRTUpgradeLaunchResult:
    success: bool
    message: str
    target: SecureCRTUpgradeTarget | None = None
    log_directory: str = ""
    status_path: str = ""


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

    runtime_dir = _securecrt_runtime_dir(tool_root)
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

    existing_windows = _securecrt_window_handles()
    try:
        process = subprocess.Popen(
            _securecrt_command(securecrt_path, manifest_path, script_path),
            cwd=str(securecrt_path.parent),
            shell=False,
        )
    except OSError as exc:
        return SecureCRTLaunchResult(False, f"启动 SecureCRT 失败：{exc}", tuple(targets), str(log_dir))

    if not _wait_for_new_securecrt_window(process, existing_windows):
        return SecureCRTLaunchResult(
            False,
            "已提交 SecureCRT 启动命令，但未检测到本次新打开的 SecureCRT 主窗口。请确认旧 SecureCRT 是否占用了脚本启动。",
            tuple(targets),
            str(log_dir),
        )

    mapping = "、".join(f"{target.vlan}→{target.port}" for target in targets)
    return SecureCRTLaunchResult(True, f"已启动 SecureCRT 串口连接：{mapping}", tuple(targets), str(log_dir))


def _securecrt_command(securecrt_path: Path, manifest_path: Path, script_path: Path) -> list[str]:
    return [str(securecrt_path), "/ARG", str(manifest_path), "/SCRIPT", str(script_path)]


def _securecrt_runtime_dir(tool_root: Path) -> Path:
    # SecureCRT 9.7 command-line /SCRIPT can fail when the script path contains Chinese characters.
    temp_root = Path(os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir())
    if _is_ascii_path(temp_root):
        return temp_root / "LineCheckAssistant" / RUNTIME_DIR_NAME
    return tool_root / RUNTIME_DIR_NAME


def _is_ascii_path(path: Path) -> bool:
    try:
        str(path).encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def _wait_for_new_securecrt_window(
    process: subprocess.Popen,
    existing_windows: set[int],
    timeout_seconds: float = 12.0,
) -> bool:
    # SecureCRT can hand off to an existing/broker process before the UI is visible.
    _ = process
    if os.name != "nt":
        return True
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        new_windows = _securecrt_window_handles() - existing_windows
        if new_windows:
            handle = next(iter(new_windows))
            _activate_window(handle)
            return True
        time.sleep(0.25)
    return False


def _securecrt_window_handles() -> set[int]:
    if os.name != "nt":
        return set()
    user32 = ctypes.windll.user32
    handles: set[int] = set()

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
            handles.add(int(handle))
        return True

    user32.EnumWindows(enum_callback, 0)
    return handles


def _activate_window(handle: int) -> None:
    user32 = ctypes.windll.user32
    user32.ShowWindow(handle, 9)
    user32.BringWindowToTop(handle)
    user32.SetForegroundWindow(handle)


def _wait_for_visible_securecrt_window(timeout_seconds: float = 12.0) -> bool:
    if os.name != "nt":
        return True
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        handle = _find_securecrt_window()
        if handle:
            _activate_window(handle)
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


def build_tftp_copy_upgrade_target(
    vlan: str,
    tftp_server_ip: str,
    log_dir: Path,
    restore_factory: bool = False,
    final_username: str = "",
    final_password: str = "",
) -> SecureCRTUpgradeTarget:
    normalized_vlan = (vlan or "").strip().lower()
    port = vlan_to_serial_port(normalized_vlan)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    log_path = log_dir / f"{normalized_vlan}_upgrade_{timestamp}.log"
    status_path = log_dir / f"{normalized_vlan}_upgrade_{timestamp}.status"
    boot_enter_signal_path = log_dir / f"{normalized_vlan}_upgrade_{timestamp}.boot_enter.signal"
    command_signal_path = log_dir / f"{normalized_vlan}_upgrade_{timestamp}.signal"
    final_login_signal_path = log_dir / f"{normalized_vlan}_upgrade_{timestamp}.final_login.signal"
    command = f"tftp {tftp_server_ip}:{TFTP_REMOTE_IMAGE}"
    return SecureCRTUpgradeTarget(
        vlan=normalized_vlan,
        port=port,
        log_path=str(log_path),
        status_path=str(status_path),
        boot_enter_signal_path=str(boot_enter_signal_path),
        command_signal_path=str(command_signal_path),
        final_login_signal_path=str(final_login_signal_path),
        tftp_command=command,
        restore_factory=restore_factory,
        final_username=final_username,
        final_password=final_password,
    )


def launch_securecrt_tftp_copy_upgrade(tool_root: Path, target: SecureCRTUpgradeTarget) -> SecureCRTUpgradeLaunchResult:
    securecrt_path = find_securecrt_executable()
    if securecrt_path is None:
        return SecureCRTUpgradeLaunchResult(False, "未找到 SecureCRT 9.7，请确认已安装到 Program Files。", target)

    runtime_dir = _securecrt_runtime_dir(tool_root)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    script_path = runtime_dir / "tftp_copy_upgrade.vbs"
    if not script_path.exists() or script_path.read_text(encoding="utf-8") != SECURECRT_TFTP_COPY_UPGRADE_SCRIPT:
        script_path.write_text(SECURECRT_TFTP_COPY_UPGRADE_SCRIPT, encoding="utf-8")

    manifest_path = runtime_dir / f"tftp_copy_upgrade_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.txt"
    manifest_line = "\t".join(
        [
            target.vlan,
            target.port,
            target.log_path,
            str(target.baud),
            str(target.data_bits),
            target.parity,
            str(target.stop_bits),
            target.status_path,
            target.tftp_command,
            target.username,
            target.password,
            "1" if target.restore_factory else "0",
            target.factory_reset_command,
            target.boot_enter_signal_path,
            target.command_signal_path,
            target.final_login_signal_path,
            target.final_username,
            target.final_password,
        ]
    )
    manifest_path.write_text(manifest_line, encoding="utf-16")

    try:
        process = subprocess.Popen(
            _securecrt_command(securecrt_path, manifest_path, script_path),
            cwd=str(securecrt_path.parent),
            shell=False,
        )
    except OSError as exc:
        return SecureCRTUpgradeLaunchResult(False, f"启动 SecureCRT 失败：{exc}", target, str(Path(target.log_path).parent), target.status_path)

    if not _wait_for_securecrt_upgrade_started(process, Path(target.status_path), timeout_seconds=20.0):
        return SecureCRTUpgradeLaunchResult(
            False,
            "已提交 SecureCRT 升级脚本，但未检测到可见主窗口或脚本状态文件。请确认 SecureCRT 是否正常打开。",
            target,
            str(Path(target.log_path).parent),
            target.status_path,
        )

    return SecureCRTUpgradeLaunchResult(
        True,
        f"已启动 SecureCRT 单台升级脚本：{target.vlan}→{target.port}",
        target,
        str(Path(target.log_path).parent),
        target.status_path,
    )


def _wait_for_securecrt_upgrade_started(
    process: subprocess.Popen,
    status_path: Path,
    timeout_seconds: float = 20.0,
) -> bool:
    # The process returned by Popen can exit before SecureCRT opens the window or runs the script.
    _ = process
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _status_file_has_started(status_path):
            return True
        handle = _find_securecrt_window() if os.name == "nt" else 0
        if handle:
            _activate_window(handle)
            return True
        time.sleep(0.25)
    return _status_file_has_started(status_path)


def _status_file_has_started(status_path: Path) -> bool:
    if not status_path.exists():
        return False
    for encoding in ("utf-16", "utf-8"):
        try:
            text = status_path.read_text(encoding=encoding, errors="ignore")
        except OSError:
            return False
        except UnicodeError:
            continue
        return bool(text.strip())
    return False


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
                sessionConfig.SetOption "DTR Flow Control", False
                sessionConfig.SetOption "RTS Flow Control", False
                sessionConfig.SetOption "Emulation", "ANSI"
                sessionConfig.SetOption "Output Transformer Name", "Default"
                sessionConfig.SetOption "Use Unicode Line Drawing", False
                sessionConfig.SetOption "Enable Xterm-256color", False
                sessionConfig.SetOption "Enable Xterm-Truecolor", False
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


SECURECRT_TFTP_COPY_UPGRADE_SCRIPT = '''#$language = "VBScript"
#$interface = "1.0"

Option Explicit

Sub WriteStatus(fso, statusPath, statusText)
    Dim statusFile
    Set statusFile = fso.OpenTextFile(statusPath, 8, True, -1)
    statusFile.WriteLine Now & vbTab & statusText
    statusFile.Close
End Sub

Function WaitForAnyText(tab, firstText, secondText, timeoutSeconds)
    Dim startTime, foundIndex
    startTime = Timer
    Do
        foundIndex = tab.Screen.WaitForStrings(firstText, secondText, 1)
        If foundIndex > 0 Then
            WaitForAnyText = foundIndex
            Exit Function
        End If
        If Timer < startTime Then
            startTime = startTime - 86400
        End If
    Loop While Timer - startTime < timeoutSeconds
    WaitForAnyText = 0
End Function

Function WaitForTransferComplete(tab, timeoutSeconds)
    Dim startTime, foundIndex, sawDone, sawWrite
    startTime = Timer
    sawDone = False
    sawWrite = False
    Do
        foundIndex = tab.Screen.WaitForStrings("done", "write", 1)
        If foundIndex = 1 Then
            sawDone = True
        ElseIf foundIndex = 2 Then
            sawWrite = True
        End If
        If sawDone And sawWrite Then
            WaitForTransferComplete = True
            Exit Function
        End If
        If Timer < startTime Then
            startTime = startTime - 86400
        End If
    Loop While Timer - startTime < timeoutSeconds
    WaitForTransferComplete = False
End Function

Function PressEnterUntilLogin(tab, timeoutSeconds)
    Dim startTime
    startTime = Timer
    Do
        tab.Screen.Send vbCr
        If tab.Screen.WaitForString("login", 1) Then
            PressEnterUntilLogin = True
            Exit Function
        End If
        If Timer < startTime Then
            startTime = startTime - 86400
        End If
    Loop While Timer - startTime < timeoutSeconds
    PressEnterUntilLogin = False
End Function

Sub SetLiveMonitorMode(tab)
    tab.Screen.Synchronous = False
End Sub

Sub SetScriptWaitMode(tab)
    tab.Screen.Synchronous = True
End Sub

Function PressEnterUntilBootUserName(tab, timeoutSeconds)
    Dim startTime, foundIndex
    startTime = Timer
    Do
        foundIndex = tab.Screen.WaitForStrings("UserName:", "Username:", "User Name:", 1)
        If foundIndex > 0 Then
            PressEnterUntilBootUserName = True
            Exit Function
        End If
        tab.Screen.Send vbCr
        If Timer < startTime Then
            startTime = startTime - 86400
        End If
    Loop While Timer - startTime < timeoutSeconds
    PressEnterUntilBootUserName = False
End Function

Function SendUserNameAndConfirmEcho(tab, value)
    tab.Screen.Send value
    If Not tab.Screen.WaitForString(value, 5) Then
        SendUserNameAndConfirmEcho = False
        Exit Function
    End If
    crt.Sleep 300
    tab.Screen.Send vbCr
    SendUserNameAndConfirmEcho = True
End Function

Sub SendPasswordAndEnter(tab, value)
    tab.Screen.Send value
    crt.Sleep 300
    tab.Screen.Send vbCr
End Sub

Function WaitForBootShellReady(tab, timeoutSeconds)
    Dim startTime, foundIndex
    startTime = Timer
    Do
        foundIndex = tab.Screen.WaitForStrings("Bood", "#", ">", "UserName:", "Username:", "User Name:", "Passvord:", "Password:", "password:", "Login incorrect", "incorrect", 1)
        If foundIndex >= 1 And foundIndex <= 3 Then
            WaitForBootShellReady = "READY"
            Exit Function
        ElseIf foundIndex >= 4 And foundIndex <= 6 Then
            WaitForBootShellReady = "USERNAME"
            Exit Function
        ElseIf foundIndex >= 7 And foundIndex <= 9 Then
            WaitForBootShellReady = "PASSWORD"
            Exit Function
        ElseIf foundIndex > 9 Then
            WaitForBootShellReady = "FAILED"
            Exit Function
        End If
        If Timer < startTime Then
            startTime = startTime - 86400
        End If
    Loop While Timer - startTime < timeoutSeconds
    WaitForBootShellReady = "TIMEOUT"
End Function

Function WaitForFinalShellReady(tab, timeoutSeconds)
    Dim startTime, foundIndex
    startTime = Timer
    Do
        foundIndex = tab.Screen.WaitForStrings("#", ">", "Login incorrect", "incorrect", 1)
        If foundIndex >= 1 And foundIndex <= 2 Then
            WaitForFinalShellReady = "READY"
            Exit Function
        ElseIf foundIndex >= 3 And foundIndex <= 4 Then
            WaitForFinalShellReady = "FAILED"
            Exit Function
        End If
        If Timer < startTime Then
            startTime = startTime - 86400
        End If
    Loop While Timer - startTime < timeoutSeconds
    WaitForFinalShellReady = "TIMEOUT"
End Function

Function WaitForFile(fso, filePath, timeoutSeconds)
    Dim startTime
    startTime = Timer
    Do
        If fso.FileExists(filePath) Then
            WaitForFile = True
            Exit Function
        End If
        crt.Sleep 500
        If Timer < startTime Then
            startTime = startTime - 86400
        End If
    Loop While Timer - startTime < timeoutSeconds
    WaitForFile = False
End Function

Function WaitForFinalLoginSignalOrBootReset(tab, fso, finalLoginSignalPath, statusPath, timeoutSeconds)
    Dim startTime, foundIndex, resetSent
    startTime = Timer
    resetSent = False
    Do
        If fso.FileExists(finalLoginSignalPath) Then
            WaitForFinalLoginSignalOrBootReset = True
            Exit Function
        End If
        foundIndex = tab.Screen.WaitForStrings("Boot", "Bood", 1)
        If foundIndex > 0 And Not resetSent Then
            crt.Sleep 1000
            tab.Screen.Send "reset" & vbCr
            WriteStatus fso, statusPath, "POST_TFTP_BOOT_RESET_SENT"
            resetSent = True
        End If
        If Timer < startTime Then
            startTime = startTime - 86400
        End If
    Loop While Timer - startTime < timeoutSeconds
    WaitForFinalLoginSignalOrBootReset = False
End Function

Function LoginFinalSystemWithRetry(tab, fso, statusPath, username, password)
    Dim finalLoginAttempt, finalLoginResult, loginTimeout
    For finalLoginAttempt = 1 To 5
        WriteStatus fso, statusPath, "FINAL_LOGIN_ATTEMPT_" & CStr(finalLoginAttempt)
        If finalLoginAttempt > 1 Then
            crt.Sleep 2000
        End If
        If finalLoginAttempt = 1 Then
            loginTimeout = 900
        Else
            loginTimeout = 2
        End If
        If Not PressEnterUntilLogin(tab, loginTimeout) Then
            WriteStatus fso, statusPath, "FINAL_LOGIN_PROMPT_MISSED_" & CStr(finalLoginAttempt)
        Else
            crt.Sleep 1000
            tab.Screen.Send username & vbCr
            If WaitForAnyText(tab, "Password", "password", 60) = 0 Then
                WriteStatus fso, statusPath, "FINAL_PASSWORD_PROMPT_MISSED_" & CStr(finalLoginAttempt)
            Else
                tab.Screen.Send password & vbCr
                finalLoginResult = WaitForFinalShellReady(tab, 60)
                WriteStatus fso, statusPath, "FINAL_LOGIN_RESULT_" & finalLoginResult
                If finalLoginResult = "READY" Then
                    LoginFinalSystemWithRetry = True
                    Exit Function
                End If
            End If
        End If
    Next
    LoginFinalSystemWithRetry = False
End Function

Sub Main
    If crt.Arguments.Count < 1 Then
        crt.Dialog.MessageBox "Missing upgrade target manifest.", "Sample Upgrade"
        Exit Sub
    End If

    Dim fso, manifestFile, line, fields, sessionName, sessionConfig, tab
    Dim loginAttempt, loginResult, bootLoginComplete
    Dim statusPath, tftpCommand, username, password, finalUsername, finalPassword, restoreFactory, factoryResetCommand, bootEnterSignalPath, commandSignalPath, finalLoginSignalPath
    Set fso = CreateObject("Scripting.FileSystemObject")
    Set manifestFile = fso.OpenTextFile(crt.Arguments.GetArg(0), 1, False, -1)
    line = manifestFile.ReadLine
    manifestFile.Close
    fields = Split(line, vbTab)
    If UBound(fields) < 17 Then
        crt.Dialog.MessageBox "Invalid upgrade target manifest.", "Sample Upgrade"
        Exit Sub
    End If

    sessionName = fields(0)
    statusPath = fields(7)
    tftpCommand = fields(8)
    username = "telecomadmin"
    password = "nE7jA%5m"
    restoreFactory = fields(11)
    factoryResetCommand = fields(12)
    bootEnterSignalPath = fields(13)
    commandSignalPath = fields(14)
    finalLoginSignalPath = fields(15)
    finalUsername = fields(16)
    finalPassword = fields(17)
    WriteStatus fso, statusPath, "START"

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
    sessionConfig.SetOption "DTR Flow Control", False
    sessionConfig.SetOption "RTS Flow Control", False
    sessionConfig.SetOption "Emulation", "ANSI"
    sessionConfig.SetOption "Output Transformer Name", "Default"
    sessionConfig.SetOption "Use Unicode Line Drawing", False
    sessionConfig.SetOption "Enable Xterm-256color", False
    sessionConfig.SetOption "Enable Xterm-Truecolor", False
    sessionConfig.SetOption "Log Filename V2", fields(2)
    sessionConfig.SetOption "Custom Log Message Each Line", "[%Y-%M-%D %h:%m:%s] "
    sessionConfig.SetOption "Log Timestamp Each Line", False
    sessionConfig.SetOption "Log Mode", 1
    sessionConfig.SetOption "Start Log Upon Connect", True
    sessionConfig.SetOption "New Log File At Midnight", False
    sessionConfig.Save sessionName

    Err.Clear
    Set tab = crt.Session.ConnectInTab("/S " & Chr(34) & sessionName & Chr(34), True, True)
    If Err.Number <> 0 Then
        WriteStatus fso, statusPath, "ERROR_CONNECT:" & Err.Description
        Exit Sub
    ElseIf Not tab.Session.Connected Then
        WriteStatus fso, statusPath, "ERROR_CONNECT:connection failed"
        Exit Sub
    End If
    On Error GoTo 0

    SetLiveMonitorMode tab
    tab.Session.SetStatusText fields(0) & " / " & fields(1) & " / upgrading"
    WriteStatus fso, statusPath, "SERIAL_CONNECTED"

    WriteStatus fso, statusPath, "BOOT_ENTER_SIGNAL_WAITING"
    If Not WaitForFile(fso, bootEnterSignalPath, 1200) Then
        WriteStatus fso, statusPath, "ERROR_BOOT_ENTER_SIGNAL_TIMEOUT"
        Exit Sub
    End If
    SetScriptWaitMode tab
    WriteStatus fso, statusPath, "BOOT_ENTER_RETRY_STARTED"
    If Not PressEnterUntilBootUserName(tab, 240) Then
        WriteStatus fso, statusPath, "ERROR_BOOT_INTERRUPT_TIMEOUT"
        Exit Sub
    End If
    bootLoginComplete = False
    For loginAttempt = 1 To 3
        WriteStatus fso, statusPath, "BOOT_LOGIN_ATTEMPT_" & CStr(loginAttempt)
        If loginAttempt > 1 Then
            If Not PressEnterUntilBootUserName(tab, 30) Then
                WriteStatus fso, statusPath, "ERROR_BOOT_USERNAME_RETRY_TIMEOUT"
                Exit Sub
            End If
        End If
        WriteStatus fso, statusPath, "BOOT_USERNAME_PROMPT_FOUND"
        crt.Sleep 1000
        If Not SendUserNameAndConfirmEcho(tab, username) Then
            WriteStatus fso, statusPath, "BOOT_USERNAME_ECHO_MISSED"
        Else
            WriteStatus fso, statusPath, "BOOT_USERNAME_SENT"
            If tab.Screen.WaitForStrings("Passvord", "Passvord:", "Password", "Password:", "password", "password:", 30) = 0 Then
                WriteStatus fso, statusPath, "BOOT_PASSWORD_PROMPT_MISSED"
            Else
                WriteStatus fso, statusPath, "BOOT_PASSWORD_PROMPT_FOUND"
                crt.Sleep 300
                SendPasswordAndEnter tab, password
                WriteStatus fso, statusPath, "BOOT_PASSWORD_SENT"
                loginResult = WaitForBootShellReady(tab, 20)
                WriteStatus fso, statusPath, "BOOT_LOGIN_RESULT_" & loginResult
                If loginResult = "READY" Then
                    bootLoginComplete = True
                    Exit For
                End If
            End If
        End If
    Next
    If Not bootLoginComplete Then
        WriteStatus fso, statusPath, "ERROR_BOOT_LOGIN_VERIFY_TIMEOUT"
        Exit Sub
    End If
    WriteStatus fso, statusPath, "BOOT_SHELL_READY"
    WriteStatus fso, statusPath, "BOOT_LOGIN_COMPLETE"

    SetLiveMonitorMode tab
    If Not WaitForFile(fso, commandSignalPath, 300) Then
        WriteStatus fso, statusPath, "ERROR_TFTP_READY_TIMEOUT"
        Exit Sub
    End If

    SetScriptWaitMode tab
    crt.Sleep 1000
    tab.Screen.Send tftpCommand & vbCr
    WriteStatus fso, statusPath, "TFTP_COMMAND_SENT"

    If Not WaitForTransferComplete(tab, 1800) Then
        WriteStatus fso, statusPath, "ERROR_TFTP_TIMEOUT"
        Exit Sub
    End If
    WriteStatus fso, statusPath, "TFTP_COMPLETE"

    SetLiveMonitorMode tab
    WriteStatus fso, statusPath, "FINAL_LOGIN_MONITORING_STARTED"
    If Not WaitForFinalLoginSignalOrBootReset(tab, fso, finalLoginSignalPath, statusPath, 1200) Then
        WriteStatus fso, statusPath, "ERROR_FINAL_LOGIN_READY_TIMEOUT"
        Exit Sub
    End If

    SetScriptWaitMode tab
    If Not LoginFinalSystemWithRetry(tab, fso, statusPath, finalUsername, finalPassword) Then
        WriteStatus fso, statusPath, "ERROR_FINAL_LOGIN_RETRY_EXHAUSTED"
        Exit Sub
    End If
    WriteStatus fso, statusPath, "FINAL_LOGIN_COMPLETE"

    If restoreFactory = "1" Then
        crt.Sleep 1000
        tab.Screen.Send factoryResetCommand & vbCr
        WriteStatus fso, statusPath, "RESTORE_FACTORY_SENT"
    End If

    WriteStatus fso, statusPath, "DONE"
End Sub
'''
