"""模型请求的本机 IPv4 枚举与连接池绑定；不修改网卡或系统路由。"""
import ipaddress
import socket

import psutil
from requests.adapters import HTTPAdapter


def normalize_source_ip(value):
    if not isinstance(value, str):
        raise ValueError("出口 IP 须为本机 IPv4，或留空表示不指定")
    value = value.strip()
    if not value:
        return ""
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        raise ValueError("出口 IP 须为有效的本机 IPv4") from None
    if address.is_unspecified or address.is_multicast or int(address) == 0xffffffff:
        raise ValueError("出口 IP 不能为通配、组播或广播地址")
    return str(address)


def list_source_ips(emit=lambda _line: None):
    emit("[AI出口] 开始枚举：本机调用 psutil.net_if_addrs / net_if_stats")
    try:
        addresses, states = psutil.net_if_addrs(), psutil.net_if_stats()
        result = []
        for name, entries in addresses.items():
            for entry in entries:
                if entry.family != socket.AF_INET:
                    continue
                try:
                    value = normalize_source_ip(entry.address)
                except ValueError:
                    continue
                if value:
                    result.append(dict(name=name, ip=value, available=bool(states.get(name) and states[name].isup)))
        result.sort(key=lambda item: (not item["available"], item["name"].casefold(), int(ipaddress.IPv4Address(item["ip"]))))
        emit(f"[AI出口] 枚举成功：{len(result)} 个本机 IPv4")
        return result
    except Exception:
        emit("[AI出口] 枚举失败，保留原出口设置")
        raise


def require_source_ip(value):
    value = normalize_source_ip(value)
    if value and not any(item["ip"] == value and item["available"] for item in list_source_ips()):
        raise ValueError(f"指定出口 IP {value} 当前不在已启用的本机网卡上；未发送请求，请重新选择或恢复不指定")
    return value


class SourceIpAdapter(HTTPAdapter):
    """直连及代理均锁定同一源地址，保留 Requests 的代理/TLS/重试默认值。"""
    def __init__(self, source_ip):
        self.source_address = (normalize_source_ip(source_ip), 0)
        if not self.source_address[0]:
            raise ValueError("空出口应沿用原连接池")
        super().__init__()

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["source_address"] = self.source_address
        return super().init_poolmanager(connections, maxsize, block, **pool_kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs["source_address"] = self.source_address
        return super().proxy_manager_for(proxy, **proxy_kwargs)
