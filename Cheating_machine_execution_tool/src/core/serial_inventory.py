"""只读枚举本机串口，不打开设备或按品牌过滤。"""
from __future__ import annotations

import re
from typing import Callable, Iterable


def normalize_com_port(value: str) -> str:
    """返回标准 COM 编号；空值或非法编号返回空字符串。"""
    match = re.fullmatch(r"COM(\d+)", (value or "").strip(), flags=re.IGNORECASE)
    if not match or int(match.group(1)) < 1:
        return ""
    return f"COM{int(match.group(1))}"


def list_serial_port_names(
    ports_provider: Callable[[], Iterable[object]] | None = None,
) -> list[str]:
    """返回全部实际识别的 COM 口，按编号去重排序；枚举失败向调用方抛出。"""
    if ports_provider is None:
        from serial.tools.list_ports import comports

        ports_provider = comports
    names = {
        name
        for item in ports_provider()
        for name in [normalize_com_port(getattr(item, "device", ""))]
        if name
    }
    return sorted(names, key=lambda name: int(name[3:]))
