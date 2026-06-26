from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional

from .network_ops import CommandResult
from .subprocess_window import hidden_window_kwargs


TFTPD_NAME = "tftpd64.exe"


def prepare_tftpd_server(
    tool_root: Path,
    firmware_path: Path,
    server_interface: str,
    server_ip: str,
    on_output: Optional[Callable[[str], None]] = None,
) -> CommandResult:
    tftpd_path = tool_root / TFTPD_NAME
    if not tftpd_path.exists():
        return CommandResult(False, f"未找到 Tftpd64 工具：{tftpd_path}")
    if not firmware_path.is_file():
        return CommandResult(False, f"升级固件不存在：{firmware_path}")

    script = _build_prepare_tftpd_script(tftpd_path, firmware_path.parent, server_interface, server_ip)
    process = subprocess.Popen(
        ["powershell", "-NoProfile", "-Sta", "-ExecutionPolicy", "Bypass", "-Command", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore",
        shell=False,
        **hidden_window_kwargs(),
    )
    output_lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        cleaned = line.rstrip()
        if cleaned:
            output_lines.append(cleaned)
            if on_output:
                on_output(cleaned)
    return_code = process.wait()
    output = "\n".join(output_lines)
    if return_code == 0:
        return CommandResult(True, f"Tftpd64 已准备好，目录：{firmware_path.parent}", output)
    return CommandResult(False, f"Tftpd64 准备失败：{output.strip() or return_code}", output)


def _build_prepare_tftpd_script(tftpd_path: Path, current_directory: Path, server_interface: str, server_ip: str) -> str:
    tool = _ps_quote(str(tftpd_path))
    directory = _ps_quote(str(current_directory))
    interface = _ps_quote(server_interface)
    ip_address = _ps_quote(server_ip)
    return f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class NativeWindow {{
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT {{
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }}
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")]
    public static extern IntPtr SetFocus(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern IntPtr GetWindow(IntPtr hWnd, uint uCmd);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)]
    public static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)]
    public static extern bool SetWindowText(IntPtr hWnd, string lpString);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)]
    public static extern int GetWindowTextLength(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
}}
"@

$toolPath = {tool}
$currentDirectory = {directory}
$serverInterface = {interface}
$serverIp = {ip_address}
$process = Get-Process | Where-Object {{ $_.Path -eq $toolPath }} | Select-Object -First 1
if ($null -eq $process) {{
    $process = Start-Process -FilePath $toolPath -WorkingDirectory (Split-Path -Parent $toolPath) -PassThru
}}

$deadline = (Get-Date).AddSeconds(15)
do {{
    Start-Sleep -Milliseconds 300
    $process.Refresh()
}} until ($process.MainWindowHandle -ne 0 -or (Get-Date) -gt $deadline)

if ($process.MainWindowHandle -eq 0) {{
    throw "等待 Tftpd64 主窗口超时"
}}

[NativeWindow]::ShowWindow($process.MainWindowHandle, 9) | Out-Null
[NativeWindow]::SetForegroundWindow($process.MainWindowHandle) | Out-Null

$root = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
if ($null -eq $root) {{
    throw "无法获取 Tftpd64 自动化窗口"
}}

function Get-NativeWindowText([IntPtr]$handle) {{
    $length = [NativeWindow]::GetWindowTextLength($handle)
    if ($length -lt 1) {{
        return ""
    }}
    $buffer = New-Object System.Text.StringBuilder ($length + 1)
    [NativeWindow]::GetWindowText($handle, $buffer, $buffer.Capacity) | Out-Null
    return $buffer.ToString()
}}

function Get-NativeChildren([IntPtr]$parentHandle) {{
    $children = @()
    $childHandle = [NativeWindow]::GetWindow($parentHandle, 5)
    while ($childHandle -ne [IntPtr]::Zero) {{
        $className = New-Object System.Text.StringBuilder 256
        [NativeWindow]::GetClassName($childHandle, $className, $className.Capacity) | Out-Null
        $rect = [NativeWindow+RECT]::new()
        [NativeWindow]::GetWindowRect($childHandle, [ref]$rect) | Out-Null
        $children += [pscustomobject]@{{
            Handle = $childHandle
            ClassName = $className.ToString()
            Text = Get-NativeWindowText $childHandle
            Left = $rect.Left
            Top = $rect.Top
            Right = $rect.Right
            Bottom = $rect.Bottom
            Width = $rect.Right - $rect.Left
            Height = $rect.Bottom - $rect.Top
        }}
        $childHandle = [NativeWindow]::GetWindow($childHandle, 2)
    }}
    return $children
}}

function Get-NativeTftpdFieldControls([IntPtr]$parentHandle) {{
    $candidates = Get-NativeChildren $parentHandle |
        Where-Object {{
            ($_.ClassName -match 'ComboBox|Edit') -and
            ($_.Width -ge 120) -and
            ($_.Height -ge 16)
        }} |
        Sort-Object Top, Left

    $fields = @()
    foreach ($candidate in $candidates) {{
        $sameRow = $false
        foreach ($existing in $fields) {{
            if ([Math]::Abs($existing.Top - $candidate.Top) -le 8) {{
                $sameRow = $true
                break
            }}
        }}
        if (-not $sameRow) {{
            $fields += $candidate
        }}
    }}
    return $fields
}}

function Get-ControlEditHandle([object]$control) {{
    $editChildren = Get-NativeChildren $control.Handle |
        Where-Object {{ $_.ClassName -match 'Edit' }} |
        Sort-Object Top, Left
    foreach ($editChild in $editChildren) {{
        return $editChild.Handle
    }}
    return $control.Handle
}}

function Get-ControlText([object]$control) {{
    $editHandle = Get-ControlEditHandle $control
    $text = Get-NativeWindowText $editHandle
    if ([string]::IsNullOrWhiteSpace($text)) {{
        $text = Get-NativeWindowText $control.Handle
    }}
    return $text
}}

function Set-ControlTextByKeyboard([object]$control, [string]$value) {{
    $targetHandle = Get-ControlEditHandle $control
    [NativeWindow]::ShowWindow($process.MainWindowHandle, 9) | Out-Null
    [NativeWindow]::SetForegroundWindow($process.MainWindowHandle) | Out-Null
    [NativeWindow]::SetFocus($targetHandle) | Out-Null
    Start-Sleep -Milliseconds 150

    $hadClipboardText = [System.Windows.Forms.Clipboard]::ContainsText()
    $oldClipboardText = ""
    if ($hadClipboardText) {{
        $oldClipboardText = [System.Windows.Forms.Clipboard]::GetText()
    }}
    [System.Windows.Forms.Clipboard]::SetText($value)
    [System.Windows.Forms.SendKeys]::SendWait("^a")
    Start-Sleep -Milliseconds 80
    [System.Windows.Forms.SendKeys]::SendWait("^v")
    Start-Sleep -Milliseconds 150
    [System.Windows.Forms.SendKeys]::SendWait("{{ENTER}}")
    Start-Sleep -Milliseconds 300
    if ($hadClipboardText) {{
        [System.Windows.Forms.Clipboard]::SetText($oldClipboardText)
    }}
}}

function Normalize-PathText([string]$value) {{
    if ($null -eq $value) {{
        $value = ""
    }}
    $trimmed = $value.Trim().TrimEnd('\\')
    try {{
        return [System.IO.Path]::GetFullPath($trimmed).TrimEnd('\\')
    }} catch {{
        return $trimmed
    }}
}}

function Assert-DirectoryApplied([object]$control, [string]$expectedDirectory) {{
    $actual = Get-ControlText $control
    if ((Normalize-PathText $actual).ToLowerInvariant() -ne (Normalize-PathText $expectedDirectory).ToLowerInvariant()) {{
        throw "Tftpd64 Current Directory 设置失败，当前值：$actual，期望值：$expectedDirectory"
    }}
}}

$nativeFields = @(Get-NativeTftpdFieldControls ([IntPtr]$process.MainWindowHandle))
if ($nativeFields.Count -lt 1) {{
    throw "未找到 Current Directory 输入框"
}}

Set-ControlTextByKeyboard $nativeFields[0] $currentDirectory
Assert-DirectoryApplied $nativeFields[0] $currentDirectory
Write-Output "已设置 Tftpd64 Current Directory：$currentDirectory"

if (-not [string]::IsNullOrWhiteSpace($serverInterface)) {{
    $fallbackValue = if ([string]::IsNullOrWhiteSpace($serverIp)) {{ $serverInterface }} else {{ $serverIp }}
    if ($nativeFields.Count -lt 2) {{
        $nativeFields = @(Get-NativeTftpdFieldControls ([IntPtr]$process.MainWindowHandle))
    }}
    if ($nativeFields.Count -ge 2) {{
        Set-ControlTextByKeyboard $nativeFields[1] $fallbackValue
        $actualInterface = Get-ControlText $nativeFields[1]
        Write-Output "已设置 Tftpd64 Server interfaces：$actualInterface"
    }} else {{
        Write-Output "未找到 Server interfaces 输入框，跳过网卡下拉框设置"
    }}
}}

$tabCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::TabItem
)
$tabs = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tabCondition)
$tftpServerTabFound = $false
for ($i = 0; $i -lt $tabs.Count; $i++) {{
    $tab = $tabs.Item($i)
    if ($tab.Current.Name -eq "Tftp Server") {{
        $selectionPattern = $tab.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
        $selectionPattern.Select()
        Write-Output "已切换到 Tftp Server"
        $tftpServerTabFound = $true
        break
    }}
}}

if (-not $tftpServerTabFound) {{
    Write-Output "未能通过 UI Automation 找到 Tftp Server 页签，继续使用当前页面"
}}
exit 0
"""


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
