"""Windows 网卡身份查询与单次重命名；不启停网卡或修改 IP。"""
from __future__ import annotations

import json
import locale
import subprocess

from line_check_assistant.subprocess_window import hidden_window_kwargs
from src.models.network_adapter import AdapterIdentity


COMMAND_TIMEOUT_SECONDS = 15


def read_adapter_identities() -> tuple[AdapterIdentity, ...]:
    script = (
        "$ErrorActionPreference='Stop'; "
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
        "@(Get-NetAdapter -IncludeHidden | Select-Object Name,InterfaceGuid,Status) "
        "| ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        shell=False, timeout=COMMAND_TIMEOUT_SECONDS, **hidden_window_kwargs(),
    )
    if result.returncode:
        raise RuntimeError(f"查询网卡身份失败：{result.stderr.strip() or result.returncode}")
    items = json.loads(result.stdout.lstrip("\ufeff").strip() or "[]")
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise ValueError("网卡身份查询返回格式无效")
    adapters = []
    for item in items:
        alias = str(item.get("Name") or "").strip()
        guid = str(item.get("InterfaceGuid") or "").strip().strip("{}").casefold()
        if not alias or not guid:
            raise ValueError("网卡身份查询缺少名称或 InterfaceGuid")
        adapters.append(AdapterIdentity(alias, guid, str(item.get("Status") or "")))
    return tuple(adapters)


def rename_adapter_command(old_name: str, new_name: str) -> list[str]:
    return ["netsh", "interface", "set", "interface", f"name={old_name}", f"newname={new_name}"]


def rename_adapter(old_name: str, new_name: str) -> None:
    result = subprocess.run(
        rename_adapter_command(old_name, new_name), capture_output=True, text=True,
        encoding=locale.getpreferredencoding(False), errors="replace", shell=False,
        timeout=COMMAND_TIMEOUT_SECONDS, **hidden_window_kwargs(),
    )
    if result.returncode:
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        raise RuntimeError(f"系统重命名失败：{output or result.returncode}")
