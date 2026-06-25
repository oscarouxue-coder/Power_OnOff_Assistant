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
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class NativeWindow {{
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
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

function Find-First([object]$scope, [object]$condition) {{
    return $root.FindFirst($scope, $condition)
}}

$comboCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::ComboBox
)
$combos = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $comboCondition)
if ($combos.Count -lt 1) {{
    throw "未找到 Current Directory 输入框"
}}

$directoryCombo = $combos.Item(0)
$valuePattern = $directoryCombo.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
$valuePattern.SetValue($currentDirectory)
Write-Output "已设置 Tftpd64 Current Directory：$currentDirectory"

if ($combos.Count -ge 2 -and -not [string]::IsNullOrWhiteSpace($serverInterface)) {{
    $interfaceCombo = $combos.Item(1)
    $selectedInterface = $false
    try {{
        $expandPattern = $interfaceCombo.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
        $expandPattern.Expand()
        Start-Sleep -Milliseconds 300
        $itemCondition = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::ListItem
        )
        $items = $interfaceCombo.FindAll([System.Windows.Automation.TreeScope]::Descendants, $itemCondition)
        for ($i = 0; $i -lt $items.Count; $i++) {{
            $item = $items.Item($i)
            $name = $item.Current.Name
            if ($name.Contains($serverInterface) -or ((-not [string]::IsNullOrWhiteSpace($serverIp)) -and $name.Contains($serverIp))) {{
                $selectionPattern = $item.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
                $selectionPattern.Select()
                $selectedInterface = $true
                Write-Output "已选择 Tftpd64 Server interfaces：$name"
                break
            }}
        }}
        $expandPattern.Collapse()
    }} catch {{
        Write-Output "按列表选择 Server interfaces 失败，尝试直接写入：$($_.Exception.Message)"
    }}
    if (-not $selectedInterface) {{
        $interfaceValuePattern = $interfaceCombo.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
        $fallbackValue = if ([string]::IsNullOrWhiteSpace($serverIp)) {{ $serverInterface }} else {{ $serverIp }}
        $interfaceValuePattern.SetValue($fallbackValue)
        Write-Output "已设置 Tftpd64 Server interfaces：$fallbackValue"
    }}
}}

$tabCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::TabItem
)
$tabs = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tabCondition)
for ($i = 0; $i -lt $tabs.Count; $i++) {{
    $tab = $tabs.Item($i)
    if ($tab.Current.Name -eq "Tftp Server") {{
        $selectionPattern = $tab.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
        $selectionPattern.Select()
        Write-Output "已切换到 Tftp Server"
        exit 0
    }}
}}

throw "未找到 Tftp Server 页签"
"""


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
