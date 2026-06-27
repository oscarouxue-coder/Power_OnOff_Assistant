from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional

from .network_ops import CommandResult
from .subprocess_window import hidden_window_kwargs
from .tftpd_automation import TFTPD_NAME


def close_upgrade_tools(
    tool_root: Path,
    on_output: Optional[Callable[[str], None]] = None,
) -> CommandResult:
    script = _build_close_upgrade_tools_script(tool_root / TFTPD_NAME)
    process = subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
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
        return CommandResult(True, "升级收尾工具已关闭。", output)
    return CommandResult(False, f"升级收尾工具关闭失败：{output.strip() or return_code}", output)


def _build_close_upgrade_tools_script(tftpd_path: Path) -> str:
    tftpd = _ps_quote(str(tftpd_path))
    return f"""
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$tftpdPath = {tftpd}

function Stop-ProcessGracefully([System.Diagnostics.Process]$process, [string]$label) {{
    if ($null -eq $process -or $process.HasExited) {{
        return
    }}
    try {{
        if ($process.MainWindowHandle -ne 0) {{
            [void]$process.CloseMainWindow()
            if ($process.WaitForExit(3000)) {{
                Write-Output "已关闭 $label：pid=$($process.Id)"
                return
            }}
        }}
    }} catch {{
        Write-Output "关闭 $label 主窗口失败：pid=$($process.Id) $($_.Exception.Message)"
    }}
    try {{
        Stop-Process -Id $process.Id -Force -ErrorAction Stop
        Write-Output "已强制关闭 $label：pid=$($process.Id)"
    }} catch {{
        Write-Output "关闭 $label 失败：pid=$($process.Id) $($_.Exception.Message)"
    }}
}}

$closedAny = $false
$tftpdProcesses = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {{
    try {{ $_.Path -eq $tftpdPath }} catch {{ $false }}
}})
foreach ($process in $tftpdProcesses) {{
    $closedAny = $true
    Stop-ProcessGracefully $process "Tftpd64"
}}

$secureCrtProcesses = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {{
    $_.ProcessName -ieq "SecureCRT"
}})
foreach ($process in $secureCrtProcesses) {{
    $closedAny = $true
    Stop-ProcessGracefully $process "SecureCRT"
}}

if (-not $closedAny) {{
    Write-Output "未检测到需要关闭的 SecureCRT 或 Tftpd64 进程。"
}}
exit 0
"""


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
