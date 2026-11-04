"""只读接口地址枚举与指定接口DNS；不改IP、DNS或系统路由。"""
import ctypes as C
from ctypes import wintypes as W
import ipaddress
import os
import re
import socket
import threading
import time

from src.models.wifi_test_models import WifiEnvironmentError, WifiCancelled, check_stop

U32 = C.c_uint32


class SocketAddress(C.Structure):
    _fields_ = [('address', C.c_void_p), ('length', C.c_int32)]


class UnicastAddress(C.Structure):
    pass


UnicastAddress._fields_ = [('alignment', C.c_uint64), ('next', C.POINTER(UnicastAddress)),
                          ('socket', SocketAddress), ('prefix_origin', U32), ('suffix_origin', U32),
                          ('dad_state', U32), ('valid', U32), ('preferred', U32), ('lease', U32),
                          ('prefix_length', C.c_ubyte)]


class AdapterAddress(C.Structure):
    pass


AdapterAddress._fields_ = [
    ('length', U32), ('index', U32), ('next', C.POINTER(AdapterAddress)),
    ('name', C.c_char_p), ('unicast', C.POINTER(UnicastAddress)),
    ('anycast', C.c_void_p), ('multicast', C.c_void_p), ('dns', C.c_void_p),
    ('suffix', W.LPWSTR), ('description', W.LPWSTR), ('friendly', W.LPWSTR),
    ('physical', C.c_ubyte * 8), ('physical_length', U32), ('flags', U32),
    ('mtu', U32), ('type', U32), ('status', U32), ('ipv6_index', U32),
]


def adapters_ipv4():
    if os.name != 'nt':
        raise WifiEnvironmentError('无线地址查询仅支持Windows')
    api = C.WinDLL('iphlpapi.dll').GetAdaptersAddresses
    api.argtypes = [U32, U32, C.c_void_p, C.c_void_p, C.POINTER(U32)]
    api.restype = U32
    size = U32(16384)
    for _ in range(3):
        buffer = C.create_string_buffer(size.value)
        code = api(socket.AF_INET, 0, None, buffer, C.byref(size))
        if code == 111:
            continue
        if code:
            raise WifiEnvironmentError(f'读取无线IP地址失败（Windows错误码{code}）')
        results = []
        pointer = C.cast(buffer, C.POINTER(AdapterAddress))
        while pointer:
            adapter = pointer.contents
            addresses = []
            current = adapter.unicast
            while current:
                entry = current.contents
                if entry.socket.address and entry.socket.length >= 8 and entry.dad_state == 4:
                    raw = C.string_at(entry.socket.address, entry.socket.length)
                    if int.from_bytes(raw[:2], 'little') == socket.AF_INET:
                        address = socket.inet_ntoa(raw[4:8])
                        addresses.append((address, int(entry.prefix_length)))
                current = entry.next
            results.append({'guid': adapter.name.decode('ascii', 'replace').strip('{}') if adapter.name else '',
                            'name': adapter.friendly or adapter.description or '', 'index': adapter.index,
                            'up': adapter.status == 1, 'addresses': tuple(addresses)})
            pointer = adapter.next
        return results
    raise WifiEnvironmentError('读取无线IP地址时接口列表持续变化')


def validate_ping_target(text):
    text = str(text).strip()
    if not text:
        raise ValueError('启用无线Ping时必须填写目标IPv4地址或域名')
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        if re.fullmatch(r'[0-9.]+', text):
            raise ValueError('无线Ping目标IPv4地址格式无效') from None
        try:
            text = text.rstrip('.').encode('idna').decode('ascii')
        except UnicodeError:
            raise ValueError('无线Ping域名格式无效') from None
        if len(text) > 253 or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part)
                                  for part in text.split('.')):
            raise ValueError('无线Ping只接受IPv4地址或域名，不接受URL、端口或IPv6')
        if text.lower() == 'localhost' or text.lower().endswith('.localhost'):
            raise ValueError('无线Ping目标不能是本机回环名称')
        return text
    if ip.version != 4 or ip.is_loopback or ip.is_multicast or ip.is_unspecified or str(ip) == '255.255.255.255':
        raise ValueError('无线Ping目标必须是非回环、非广播的单播IPv4地址')
    return str(ip)


def validate_remote_ipv4(text, adapters):
    value = validate_ping_target(text)
    try:
        ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        raise WifiEnvironmentError('DNS未返回有效IPv4地址') from None
    for adapter in adapters:
        for address, prefix in adapter['addresses']:
            network = ipaddress.IPv4Network(f'{address}/{prefix}', strict=False)
            if value == address or (prefix < 31 and value == str(network.broadcast_address)):
                raise WifiEnvironmentError('无线Ping目标不能是本机地址或本地子网广播地址')
    return value


class DnsRecord(C.Structure):
    pass


DnsRecord._fields_ = [('next', C.POINTER(DnsRecord)), ('name', W.LPWSTR),
                     ('type', C.c_uint16), ('length', C.c_uint16), ('flags', U32),
                     ('ttl', U32), ('reserved', U32), ('data', C.c_ubyte * 4)]


class DnsResult(C.Structure):
    _fields_ = [('version', U32), ('status', C.c_int32), ('options', C.c_uint64),
                ('records', C.POINTER(DnsRecord)), ('reserved', C.c_void_p)]


class DnsRequest(C.Structure):
    _fields_ = [('version', U32), ('name', W.LPCWSTR), ('type', C.c_uint16),
                ('options', C.c_uint64), ('servers', C.c_void_p), ('index', U32),
                ('callback', C.c_void_p), ('context', C.c_void_p)]


# Windows在取消后仍可调用completion；保留原生buffer/callback直到完成，禁止提前释放。
_pending_dns = {}
_dns_lock = threading.Lock()


def resolve_ipv4(name, interface_index, stop, guard, timeout=5, clock=time.monotonic):
    if interface_index <= 0:
        raise WifiEnvironmentError('DNS无线接口索引无效')
    check_stop(stop)
    api = C.WinDLL('dnsapi.dll')
    api.DnsQueryEx.argtypes = [C.POINTER(DnsRequest), C.POINTER(DnsResult), C.c_void_p]
    api.DnsQueryEx.restype = C.c_int32
    api.DnsCancelQuery.argtypes = [C.c_void_p]
    api.DnsCancelQuery.restype = C.c_int32
    api.DnsRecordListFree.argtypes = [C.c_void_p, C.c_int]
    event = threading.Event()
    result = DnsResult(version=1)
    cancel = (C.c_ubyte * 32)()
    outcome = {}
    key = object()
    callback_type = C.WINFUNCTYPE(None, C.c_void_p, C.POINTER(DnsResult))

    def complete(_context, pointer):
        try:
            outcome['status'] = pointer.contents.status
            values = []
            record = pointer.contents.records
            seen = set()
            while record and len(seen) < 4096:
                location = C.addressof(record.contents)
                if location in seen:
                    break
                seen.add(location)
                if record.contents.type == 1 and record.contents.length >= 4:
                    values.append(socket.inet_ntoa(bytes(record.contents.data)))
                record = record.contents.next
            outcome['addresses'] = tuple(dict.fromkeys(values))
            if pointer.contents.records:
                api.DnsRecordListFree(pointer.contents.records, 1)
                pointer.contents.records = C.POINTER(DnsRecord)()
        finally:
            with _dns_lock:
                lifetime = _pending_dns.pop(key, None)
            event.set()

    callback = callback_type(complete)
    request = DnsRequest(1, name.rstrip('.') + '.', 1, 8, None, interface_index,
                         C.cast(callback, C.c_void_p), None)  # DNS_QUERY_BYPASS_CACHE
    with _dns_lock:
        _pending_dns[key] = (request, result, cancel, callback, api, outcome)
    try:
        check_stop(stop)
        guard()
        check_stop(stop)
        code = api.DnsQueryEx(C.byref(request), C.byref(result), C.byref(cancel))
    except Exception:
        with _dns_lock:
            _pending_dns.pop(key, None)
        raise
    if code != 9506:  # DNS_REQUEST_PENDING
        complete(None, C.pointer(result))
        outcome['status'] = code
    deadline = clock() + timeout
    try:
        while not event.is_set():
            check_stop(stop)
            guard()
            if clock() >= deadline:
                raise WifiEnvironmentError('无线DNS解析超时（5秒）')
            event.wait(min(0.2, max(0, deadline - clock())))
        check_stop(stop)
        guard()
    except Exception:
        if not event.is_set():
            api.DnsCancelQuery(C.byref(cancel))
        raise
    if outcome.get('status') or not outcome.get('addresses'):
        raise WifiEnvironmentError(f'无线DNS没有返回IPv4地址（错误码{outcome.get("status", -1)}）')
    return outcome['addresses']
