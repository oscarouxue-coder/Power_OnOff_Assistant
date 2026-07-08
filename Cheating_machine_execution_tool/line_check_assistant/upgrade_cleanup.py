from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Iterable, Optional

from .network_ops import CommandResult
from .subprocess_window import hidden_window_kwargs
from .tftpd_automation import TFTPD_NAME


def close_upgrade_tools(
    tool_root: Path,
    securecrt_pids: Iterable[int] = (),
    on_output: Optional[Callable[[str], None]] = None,
) -> CommandResult:
    script = _build_close_upgrade_tools_script(tool_root / TFTPD_NAME, securecrt_pids)
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


def _build_close_upgrade_tools_script(tftpd_path: Path, securecrt_pids: Iterable[int] = ()) -> str:
    tftpd = _ps_quote(str(tftpd_path))
    securecrt_pid_values = []
    for pid in securecrt_pids:
        try:
            pid_value = int(pid)
        except (TypeError, ValueError):
            continue
        if pid_value > 0:
            securecrt_pid_values.append(pid_value)
    securecrt_pid_array = "@(" + ", ".join(str(pid) for pid in sorted(set(securecrt_pid_values))) + ")"
    return f"""
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$tftpdPath = {tftpd}
$secureCrtProcessIds = {securecrt_pid_array}

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

if ($secureCrtProcessIds.Count -eq 0) {{
    Write-Output "未检测到本次新增的 SecureCRT 窗口 PID，已跳过按 PID 关闭 SecureCRT；升级脚本完成时会自行请求关闭当前升级 Tab。"
}} else {{
    foreach ($secureCrtPid in $secureCrtProcessIds) {{
        $process = Get-Process -Id $secureCrtPid -ErrorAction SilentlyContinue
        if ($null -eq $process) {{
            Write-Output "本次 SecureCRT 进程已不存在：pid=$secureCrtPid"
            continue
        }}
        if ($process.ProcessName -ine "SecureCRT") {{
            Write-Output "跳过非 SecureCRT 进程：pid=$secureCrtPid process=$($process.ProcessName)"
            continue
        }}
        $closedAny = $true
        Stop-ProcessGracefully $process "SecureCRT"
    }}
}}

if (-not $closedAny) {{
    Write-Output "未检测到需要关闭的项目 Tftpd64 或本次 SecureCRT 进程。"
}}
exit 0
"""


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
