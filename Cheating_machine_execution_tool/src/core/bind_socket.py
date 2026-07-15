"""源 IP 可绑校验工具。

Windows 上 bind 一个不在本机网卡上的 IP 会抛 WSAEADDRNOTAVAIL(10049)。把
``ip_is_bindable_locally`` 抽到这里供多模块共用：tftp_transport.py、未来的
telnet_transport.py、ubus_http_client.py 都通过 source_address 绑定走
同一份预检逻辑，保证\"严格绑定 VLAN IP，不回退 0.0.0.0\"语义统一。
"""
from __future__ import annotations

import socket
import time
from typing import Callable


# Windows 上 bind 一个不在本机网卡上的 IP 会抛 WSAEADDRNOTAVAIL(10049);
# 这里同时收集 POSIX 上的等价 errno,便于跨平台 fallback。
_BIND_UNAVAILABLE_ERRNOS = {
    getattr(socket, "WSAEADDRNOTAVAIL", None),  # Windows: 10049
    99,  # EADDRNOTAVAIL on Linux
}
_BIND_UNAVAILABLE_ERRNOS.discard(None)


def ip_is_bindable_locally(ip: str) -> bool:
    """检查指定 IPv4 是否能作为本机地址绑定(用于 TFTP / Telnet / UBUS 客户端 start 前预检)。

    通过在指定 IP 上开一个 UDP socket 试 bind；若 bind 成功,说明该地址确实属于本机某张网卡,
    可以放心让下游绑定；失败通常是该 IP 未配置在任何活动接口上。
    """
    if not ip:
        return True
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((ip, 0))
        return True
    except OSError:
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def wait_for_bindable_ip(
    ip: str,
    timeout_seconds: float = 15.0,
    poll_seconds: float = 0.5,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> bool:
    """等待 Windows 将刚设置的网卡 IP 注册为可绑定地址。

    与 tftp_transport / 即将上线的 telnet_transport 共用。
    """
    deadline = monotonic_fn() + max(0.0, timeout_seconds)
    while True:
        if ip_is_bindable_locally(ip):
            return True
        remaining = deadline - monotonic_fn()
        if remaining <= 0:
            return False
        sleep_fn(min(max(0.01, poll_seconds), remaining))
