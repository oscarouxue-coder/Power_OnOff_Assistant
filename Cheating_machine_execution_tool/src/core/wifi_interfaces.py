"""Windows WiFi 接口枚举能力。"""
from __future__ import annotations

from typing import Callable, Iterable


def list_wifi_interface_names(
    interfaces_provider: Callable[[], Iterable[object]] | None = None,
) -> list[str]:
    """返回 pywifi 可用接口名称，去空、去重并保留发现顺序。"""
    if interfaces_provider is None:
        import pywifi

        interfaces_provider = pywifi.PyWiFi().interfaces

    names: list[str] = []
    seen: set[str] = set()
    for interface in interfaces_provider():
        name_getter = getattr(interface, "name", None)
        name = str(name_getter() if callable(name_getter) else "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


__all__ = ["list_wifi_interface_names"]
