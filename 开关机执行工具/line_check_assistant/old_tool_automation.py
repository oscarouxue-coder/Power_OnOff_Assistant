from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional

from .network_ops import CommandResult
from .subprocess_window import hidden_window_kwargs


def automate_power_on(
    tool_path: Path,
    serial_port: str,
    scheme_name: str = "Fully_powered_on",
    wait_seconds: int = 60,
    on_output: Optional[Callable[[str], None]] = None,
) -> CommandResult:
    if not tool_path.exists():
        return CommandResult(False, f"未找到旧软件：{tool_path}")

    script = _build_power_on_script(tool_path, serial_port, scheme_name, wait_seconds)
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
        return CommandResult(True, "旧软件自动上电流程完成。", output)
    return CommandResult(False, f"旧软件自动上电流程失败：{output.strip() or return_code}", output)


def _build_power_on_script(tool_path: Path, serial_port: str, scheme_name: str, wait_seconds: int) -> str:
    tool = _ps_quote(str(tool_path))
    serial = _ps_quote(serial_port)
    scheme = _ps_quote(scheme_name)
    return f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Window {{
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int X, int Y);
    [DllImport("user32.dll")]
    public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
}}
"@

$toolPath = {tool}
$serialPort = {serial}
$schemeName = {scheme}
$waitSeconds = {int(wait_seconds)}
$workDir = Split-Path -Parent $toolPath
$expectedSchemeFile = "Fully_powered_on_config.ini"

function Click-Point([int]$x, [int]$y) {{
    [void][Win32Window]::SetCursorPos($x, $y)
    [Win32Window]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 80
    [Win32Window]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
}}

function Test-SchemeSelected {{
    $logDir = Join-Path $workDir "script_logs"
    if (-not (Test-Path $logDir)) {{ return $false }}
    $latestLog = Get-ChildItem -Path $logDir -Filter "Power_on_off_*.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latestLog -eq $null) {{ return $false }}
    $content = Get-Content -Raw -Encoding UTF8 $latestLog.FullName -ErrorAction SilentlyContinue
    return ($content -match "on_scheme_selected\\s+Fully_powered_on_config\\.ini")
}}

function Select-FirstRealProfile {{
    param($combo, [string]$reason)
    try {{
        $comboRect = $combo.Current.BoundingRectangle
        if ($comboRect.Width -gt 0 -and $comboRect.Height -gt 0) {{
            $comboX = [int]($comboRect.Left + ($comboRect.Width / 2))
            $comboY = [int]($comboRect.Top + ($comboRect.Height / 2))
            Click-Point $comboX $comboY
            Start-Sleep -Milliseconds 250
            Write-Output "已点击配置下拉框中心: x=$comboX y=$comboY"
        }}
    }} catch {{
        Write-Output "点击配置下拉框中心失败: $($_.Exception.Message)"
    }}
    try {{
        $combo.SetFocus()
    }} catch {{
    }}
    try {{
        $expandPattern = $combo.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
        $expandPattern.Expand()
    }} catch {{
        Write-Output "ExpandCollapse 展开失败，使用 Alt+Down"
    }}
    [System.Windows.Forms.SendKeys]::SendWait("%{{DOWN}}")
    Start-Sleep -Milliseconds 300
    [System.Windows.Forms.SendKeys]::SendWait("{{HOME}}")
    Start-Sleep -Milliseconds 120
    [System.Windows.Forms.SendKeys]::SendWait("{{DOWN}}")
    Start-Sleep -Milliseconds 120
    [System.Windows.Forms.SendKeys]::SendWait("{{ENTER}}")
    Start-Sleep -Seconds 1
    Write-Output "已通过键盘选择第一条真实配置：$reason"
}}

function Find-TextLabel {{
    param($window, [string]$labelText)
    $textCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Text
    )
    $texts = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $textCondition)
    for ($t = 0; $t -lt $texts.Count; $t++) {{
        $textItem = $texts.Item($t)
        $textName = $textItem.Current.Name
        if ($textName -and $textName.ToLower().Contains($labelText.ToLower())) {{
            return $textItem
        }}
    }}
    return $null
}}

function Find-ComboRightOfLabel {{
    param($window, $label)
    if ($label -eq $null) {{ return $null }}
    $comboCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::ComboBox
    )
    $combos = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $comboCondition)
    $labelRect = $label.Current.BoundingRectangle
    $bestCombo = $null
    $bestDistance = 999999
    for ($i = 0; $i -lt $combos.Count; $i++) {{
        $combo = $combos.Item($i)
        $comboRect = $combo.Current.BoundingRectangle
        $verticalDistance = [Math]::Abs((($comboRect.Top + $comboRect.Bottom) / 2) - (($labelRect.Top + $labelRect.Bottom) / 2))
        if ($comboRect.Left -gt $labelRect.Right -and $verticalDistance -lt $bestDistance) {{
            $bestCombo = $combo
            $bestDistance = $verticalDistance
        }}
    }}
    return $bestCombo
}}

function Select-ComboValue {{
    param($combo, [string]$value, [string]$label)
    if ($combo -eq $null) {{
        throw "未找到 $label 对应的下拉框"
    }}
    $comboRect = $combo.Current.BoundingRectangle
    if ($comboRect.Width -gt 0 -and $comboRect.Height -gt 0) {{
        $comboX = [int]($comboRect.Left + ($comboRect.Width / 2))
        $comboY = [int]($comboRect.Top + ($comboRect.Height / 2))
        Click-Point $comboX $comboY
        Start-Sleep -Milliseconds 250
        Write-Output "已点击 $label 下拉框中心: x=$comboX y=$comboY"
    }}
    try {{
        $combo.SetFocus()
    }} catch {{
    }}
    try {{
        $expandPattern = $combo.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
        $expandPattern.Expand()
    }} catch {{
        Write-Output "$label 下拉框 ExpandCollapse 失败，使用 Alt+Down"
    }}
    [System.Windows.Forms.SendKeys]::SendWait("%{{DOWN}}")
    Start-Sleep -Milliseconds 300

    if ($label.ToLower().Contains("serial")) {{
        $itemCondition = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::ListItem
        )
        $items = [System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Descendants, $itemCondition)
        $visualItems = New-Object System.Collections.Generic.List[object]
        for ($j = 0; $j -lt $items.Count; $j++) {{
            $item = $items.Item($j)
            $name = $item.Current.Name
            if ($name -and $name.ToUpper() -match '^COM\\d+$') {{
                $itemRect = $item.Current.BoundingRectangle
                if (
                    $itemRect.Width -gt 0 -and
                    $itemRect.Height -gt 0 -and
                    $itemRect.Left -ge ($comboRect.Left - 80) -and
                    $itemRect.Right -le ($comboRect.Right + 120) -and
                    $itemRect.Top -gt ($comboRect.Top - 5)
                ) {{
                    $visualItems.Add([pscustomobject]@{{
                        Name = $name
                        Left = $itemRect.Left
                        Top = $itemRect.Top
                        Right = $itemRect.Right
                        Bottom = $itemRect.Bottom
                        Element = $item
                    }}) | Out-Null
                }}
            }}
        }}
        $sortedItems = @($visualItems | Sort-Object Top, Left)
        Write-Output "$label 可见 COM 列表项: $(($sortedItems | ForEach-Object {{ $_.Name }}) -join ', ')"
        $targetIndex = -1
        for ($k = 0; $k -lt $sortedItems.Count; $k++) {{
            if ($sortedItems[$k].Name.ToUpper() -eq $value.ToUpper()) {{
                $targetIndex = $k
                break
            }}
        }}
        if ($targetIndex -ge 0) {{
            [System.Windows.Forms.SendKeys]::SendWait("{{HOME}}")
            Start-Sleep -Milliseconds 120
            for ($k = 0; $k -lt $targetIndex; $k++) {{
                [System.Windows.Forms.SendKeys]::SendWait("{{DOWN}}")
                Start-Sleep -Milliseconds 80
            }}
            [System.Windows.Forms.SendKeys]::SendWait("{{ENTER}}")
            Start-Sleep -Milliseconds 250
            Write-Output "Selected $($label) by keyboard: $value index=$targetIndex"
        }} else {{
            [System.Windows.Forms.SendKeys]::SendWait($value)
            Start-Sleep -Milliseconds 200
            [System.Windows.Forms.SendKeys]::SendWait("{{ENTER}}")
            Write-Output "未在可见 COM 列表项中找到 $value，已通过键盘输入选择 $($label): $value"
        }}
    }} else {{
        $itemCondition = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::ListItem
        )
        $items = [System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Descendants, $itemCondition)
        $clicked = $false
        for ($j = 0; $j -lt $items.Count; $j++) {{
            $item = $items.Item($j)
            $name = $item.Current.Name
            if ($name -and $name.ToUpper().Contains($value.ToUpper())) {{
                $itemRect = $item.Current.BoundingRectangle
                if ($itemRect.Width -gt 0 -and $itemRect.Height -gt 0) {{
                    $itemX = [int]($itemRect.Left + ($itemRect.Width / 2))
                    $itemY = [int]($itemRect.Top + ($itemRect.Height / 2))
                    Click-Point $itemX $itemY
                    $clicked = $true
                    Write-Output "已点击 $label 选项: $name"
                    break
                }}
            }}
        }}
        if (-not $clicked) {{
            [System.Windows.Forms.SendKeys]::SendWait($value)
            Start-Sleep -Milliseconds 200
            [System.Windows.Forms.SendKeys]::SendWait("{{ENTER}}")
            Write-Output "已通过键盘输入选择 $($label): $value"
        }}
    }}
    Start-Sleep -Seconds 1
}}

Write-Output "启动旧软件: $toolPath"
$process = Start-Process -FilePath $toolPath -WorkingDirectory $workDir -PassThru

$root = [System.Windows.Automation.AutomationElement]::RootElement
$windowCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Window
)
$window = $null
$windowProcess = $process
$expectedExe = [System.IO.Path]::GetFileNameWithoutExtension($toolPath).ToLower()
for ($i = 0; $i -lt 100; $i++) {{
    $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $windowCondition)
    $bestScore = 0
    $bestDescription = ""
    for ($w = 0; $w -lt $windows.Count; $w++) {{
        $candidate = $windows.Item($w)
        $title = $candidate.Current.Name
        $candidatePid = $candidate.Current.ProcessId
        $proc = $null
        try {{ $proc = Get-Process -Id $candidatePid -ErrorAction Stop }} catch {{ }}
        $procName = if ($proc -ne $null) {{ $proc.ProcessName }} else {{ "" }}
        $procPath = ""
        try {{ $procPath = $proc.Path }} catch {{ }}
        $titleLower = if ($title) {{ $title.ToLower() }} else {{ "" }}
        $procNameLower = if ($procName) {{ $procName.ToLower() }} else {{ "" }}
        $procPathLower = if ($procPath) {{ $procPath.ToLower() }} else {{ "" }}
        if (
            $procNameLower.Contains("powershell") -or
            $titleLower.Contains("powershell") -or
            $procNameLower -eq "explorer"
        ) {{
            continue
        }}
        $score = 0
        if ($titleLower.Contains("auto_power_on_off_tool_v3.0_20260130")) {{ $score += 120 }}
        if ($titleLower.Contains("auto_power_on_off_tool")) {{ $score += 100 }}
        if ($titleLower.Contains("auto_power")) {{ $score += 80 }}
        if ($procPathLower -eq $toolPath.ToLower()) {{ $score += 100 }}
        if ($procNameLower.Contains("auto_power_on_off_tool")) {{ $score += 90 }}
        if ($procNameLower.Contains("auto_power")) {{ $score += 70 }}
        if ($candidatePid -eq $process.Id) {{ $score += 20 }}
        if ($score -gt $bestScore) {{
            $bestScore = $score
            $window = $candidate
            $windowProcess = $proc
            $bestDescription = "pid=$candidatePid process=$procName title=$title score=$score"
        }}
    }}
    if ($window -ne $null -and $bestScore -ge 80) {{
        Write-Output "匹配旧软件窗口：$bestDescription"
        break
    }}
    $window = $null
    Start-Sleep -Milliseconds 500
}}
if ($window -eq $null) {{
    Write-Output "窗口候选："
    $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $windowCondition)
    for ($w = 0; $w -lt $windows.Count; $w++) {{
        $candidate = $windows.Item($w)
        $candidatePid = $candidate.Current.ProcessId
        $title = $candidate.Current.Name
        $procName = ""
        try {{ $procName = (Get-Process -Id $candidatePid -ErrorAction Stop).ProcessName }} catch {{ }}
        Write-Output "pid=$candidatePid process=$procName title=$title"
    }}
    throw "等待旧软件窗口超时"
}}

Start-Sleep -Seconds 1
Write-Output "旧软件窗口已打开：pid=$($window.Current.ProcessId) title=$($window.Current.Name)"
try {{
    if ($windowProcess -ne $null) {{
        [void][Win32Window]::SetForegroundWindow($windowProcess.MainWindowHandle)
    }}
}} catch {{
}}

$comboCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::ComboBox
)
$combos = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $comboCondition)
$selected = $false
$profileLabel = $null
$textCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Text
)
$texts = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $textCondition)
for ($t = 0; $t -lt $texts.Count; $t++) {{
    $textItem = $texts.Item($t)
    $textName = $textItem.Current.Name
    if ($textName -and $textName.ToLower().Contains("select profile")) {{
        $profileLabel = $textItem
        break
    }}
}}

$serialLabel = Find-TextLabel $window "serial num"
$serialCombo = Find-ComboRightOfLabel $window $serialLabel
Select-ComboValue $serialCombo $serialPort "Serial Num"

if ($combos.Count -eq 0) {{
    Write-Output "未找到 ComboBox 控件，尝试通过 Select profile: 标签定位下拉框"
    Write-Output "窗口文本候选："
    for ($t = 0; $t -lt [Math]::Min($texts.Count, 40); $t++) {{
        $textItem = $texts.Item($t)
        if ($textItem.Current.Name) {{
            Write-Output "text[$t]=$($textItem.Current.Name)"
        }}
    }}
    if ($profileLabel -eq $null) {{
        throw "未找到配置文件下拉框，也未找到 Select profile: 标签"
    }}
    $rect = $profileLabel.Current.BoundingRectangle
    $clickX = [int]($rect.Right + 70)
    $clickY = [int]($rect.Top + (($rect.Bottom - $rect.Top) / 2))
    Write-Output "通过 Select profile: 标签点击下拉框附近坐标 x=$clickX y=$clickY"
    [void][Win32Window]::SetCursorPos($clickX, $clickY)
    Click-Point $clickX $clickY
    Start-Sleep -Milliseconds 300
    [System.Windows.Forms.SendKeys]::SendWait("%{{DOWN}}")
    Start-Sleep -Milliseconds 200
    [System.Windows.Forms.SendKeys]::SendWait("{{HOME}}")
    Start-Sleep -Milliseconds 120
    [System.Windows.Forms.SendKeys]::SendWait("{{DOWN}}")
    Start-Sleep -Milliseconds 120
    [System.Windows.Forms.SendKeys]::SendWait("{{ENTER}}")
    Start-Sleep -Seconds 1
    $selected = $true
    Write-Output "已通过 Select profile: 标签附近坐标选择第一条真实配置"
}} else {{
    Write-Output "找到 $($combos.Count) 个下拉框，开始选择 $schemeName"
}}

$comboIndexes = New-Object System.Collections.Generic.List[int]
if ($profileLabel -ne $null -and $combos.Count -gt 0) {{
    $labelRect = $profileLabel.Current.BoundingRectangle
    $bestComboIndex = -1
    $bestComboDistance = 999999
    for ($i = 0; $i -lt $combos.Count; $i++) {{
        $comboRect = $combos.Item($i).Current.BoundingRectangle
        $verticalDistance = [Math]::Abs((($comboRect.Top + $comboRect.Bottom) / 2) - (($labelRect.Top + $labelRect.Bottom) / 2))
        if ($comboRect.Left -gt $labelRect.Right -and $verticalDistance -lt $bestComboDistance) {{
            $bestComboDistance = $verticalDistance
            $bestComboIndex = $i
        }}
    }}
    if ($bestComboIndex -ge 0) {{
        [void]$comboIndexes.Add($bestComboIndex)
        $comboRect = $combos.Item($bestComboIndex).Current.BoundingRectangle
        Write-Output "按 Select profile: 位置锁定下拉框 index=$bestComboIndex rect=[$($comboRect.Left),$($comboRect.Top),$($comboRect.Right),$($comboRect.Bottom)]"
    }}
}}
for ($i = 0; $i -lt $combos.Count; $i++) {{
    if (-not $comboIndexes.Contains($i)) {{
        [void]$comboIndexes.Add($i)
    }}
}}

foreach ($comboIndex in $comboIndexes) {{
    if ($selected) {{ break }}
    $i = $comboIndex
    $combo = $combos.Item($i)
    if ($profileLabel -ne $null -and $i -eq $comboIndexes.Item(0)) {{
        Select-FirstRealProfile $combo "Select profile 同行下拉框 index=$i"
        if (Test-SchemeSelected) {{
            $selected = $true
            Write-Output "已确认旧工具选择配置: $expectedSchemeFile"
            break
        }}
        Write-Output "键盘选择后未在旧工具日志中确认配置，继续尝试控件列表项"
    }}
    try {{
        $combo.SetFocus()
        $expandPattern = $combo.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
        $expandPattern.Expand()
        Start-Sleep -Milliseconds 500
    }} catch {{
        Write-Output "下拉框 $i 无法展开，尝试键盘输入"
    }}

    $itemCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::ListItem
    )
    $items = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $itemCondition)
    for ($j = 0; $j -lt $items.Count; $j++) {{
        $item = $items.Item($j)
        $name = $item.Current.Name
        if ($name -and $name.ToLower().Contains($schemeName.ToLower())) {{
            try {{
                $itemRect = $item.Current.BoundingRectangle
                if ($itemRect.Width -gt 0 -and $itemRect.Height -gt 0) {{
                    $itemX = [int]($itemRect.Left + ($itemRect.Width / 2))
                    $itemY = [int]($itemRect.Top + ($itemRect.Height / 2))
                    Click-Point $itemX $itemY
                }} else {{
                    $selectPattern = $item.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
                    $selectPattern.Select()
                }}
            }} catch {{
                $invokePattern = $item.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
                $invokePattern.Invoke()
            }}
            Start-Sleep -Milliseconds 300
            [System.Windows.Forms.SendKeys]::SendWait("{{ENTER}}")
            $selected = $true
            Write-Output "已点击并确认配置: $name"
            if (Test-SchemeSelected) {{
                Write-Output "已确认旧工具选择配置: $expectedSchemeFile"
            }} else {{
                Write-Output "点击列表项后未在旧工具日志中确认配置"
            }}
            break
        }}
    }}
    if ($selected) {{ break }}

    try {{
        $combo.SetFocus()
        Start-Sleep -Milliseconds 200
        [System.Windows.Forms.SendKeys]::SendWait("^a")
        Start-Sleep -Milliseconds 100
        [System.Windows.Forms.SendKeys]::SendWait($schemeName)
        Start-Sleep -Milliseconds 200
        [System.Windows.Forms.SendKeys]::SendWait("{{ENTER}}")
        Start-Sleep -Seconds 1
        $selected = $true
        Write-Output "已通过键盘输入尝试选择配置: $schemeName"
        break
    }} catch {{
        Write-Output "下拉框 $i 键盘输入失败: $($_.Exception.Message)"
    }}
}}
if (-not $selected) {{
    throw "未能在下拉框中选择 $schemeName"
}}
if (-not (Test-SchemeSelected)) {{
    throw "未确认旧工具已选择 Fully_powered_on_config.ini，停止点击 Start ALL"
}}

Start-Sleep -Seconds 1
$buttonCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Button
)
$buttons = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $buttonCondition)
$startButton = $null
for ($i = 0; $i -lt $buttons.Count; $i++) {{
    $button = $buttons.Item($i)
    $buttonName = $button.Current.Name
    if ($buttonName -and ($buttonName -replace '\\s+', '').ToLower().Contains('startall')) {{
        $startButton = $button
        break
    }}
}}
if ($startButton -eq $null) {{
    Write-Output "未通过控件名找到 Start ALL 按钮，尝试键盘 Tab/Enter 兜底"
    [System.Windows.Forms.SendKeys]::SendWait("{{TAB}}")
    Start-Sleep -Milliseconds 100
    [System.Windows.Forms.SendKeys]::SendWait("{{TAB}}")
    Start-Sleep -Milliseconds 100
    [System.Windows.Forms.SendKeys]::SendWait("{{ENTER}}")
}} else {{
    $startButton.SetFocus()
    $invokeStart = $startButton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    $invokeStart.Invoke()
}}
Write-Output "已点击 Start ALL，等待 $waitSeconds 秒"
Start-Sleep -Seconds $waitSeconds

try {{
    if ($windowProcess -ne $null -and -not $windowProcess.HasExited) {{
        [void]$windowProcess.CloseMainWindow()
        Start-Sleep -Seconds 5
    }}
}} catch {{
}}
if ($windowProcess -ne $null -and -not $windowProcess.HasExited) {{
    $windowProcess.Kill()
}}
Write-Output "旧软件已关闭"
"""


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
