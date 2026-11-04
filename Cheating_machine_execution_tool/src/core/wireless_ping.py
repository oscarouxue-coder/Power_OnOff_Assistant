"""限定无线源IPv4和出口接口的ICMP Echo；不调用系统默认出口ping。"""
import ipaddress
import os
import secrets
import socket
import struct
import time

from src.core.wireless_ip import adapters_ipv4, resolve_ipv4, validate_ping_target, validate_remote_ipv4
from src.models.wifi_test_models import (
    WifiEnvironmentError, WirelessPingResult, check_stop, wait,
)


def checksum(data):
    if len(data) % 2:
        data += b'\0'
    total = sum(struct.unpack('!' + 'H' * (len(data) // 2), data))
    total = (total & 65535) + (total >> 16)
    total = (total & 65535) + (total >> 16)
    return (~total) & 65535


def echo_request(identifier, sequence, payload):
    data = struct.pack('!BBHHH', 8, 0, 0, identifier, sequence) + payload
    return struct.pack('!BBHHH', 8, 0, checksum(data), identifier, sequence) + payload


def valid_reply(packet, remote, local, identifier, sequence, payload):
    if len(packet) < 28 or packet[0] >> 4 != 4:
        return False
    length = (packet[0] & 15) * 4
    total = struct.unpack_from('!H', packet, 2)[0]
    if length < 20 or total != len(packet) or packet[9] != 1 or len(packet) != length + 8 + len(payload):
        return False
    if socket.inet_ntoa(packet[12:16]) != remote or socket.inet_ntoa(packet[16:20]) != local:
        return False
    icmp = packet[length:]
    return (icmp[0:2] == b'\x00\x00' and checksum(icmp) == 0 and
            struct.unpack_from('!HH', icmp, 4) == (identifier, sequence) and icmp[8:] == payload)


def preflight_raw_socket(socket_factory=socket.socket):
    try:
        with socket_factory(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP):
            pass
    except OSError:
        raise WifiEnvironmentError('无法创建无线Ping原始socket，请以管理员身份运行并检查安全软件权限') from None


def run_wireless_ping(interface, target, stop, emit, guard, *,
                      adapter_provider=adapters_ipv4, resolver=resolve_ipv4,
                      socket_factory=socket.socket, clock=time.monotonic):
    target = validate_ping_target(target)
    deadline = clock() + 30
    emit('无线Ping：等待无线IPv4地址（最长30秒）')
    while True:
        check_stop(stop)
        guard()
        adapters = adapter_provider()
        selected = next((a for a in adapters if a['index'] == interface.index and
                         a['guid'].lower() == interface.guid.lower() and a['up']), None)
        sources = [] if selected is None else [v[0] for v in selected['addresses']
                   if not ipaddress.IPv4Address(v[0]).is_link_local and
                   not ipaddress.IPv4Address(v[0]).is_loopback and not ipaddress.IPv4Address(v[0]).is_unspecified]
        if sources:
            source = sources[0]
            break
        if clock() >= deadline:
            raise WifiEnvironmentError('所选无线网卡30秒内未获得可用IPv4地址')
        wait(min(0.2, deadline - clock()), stop, guard, clock)

    try:
        ipaddress.IPv4Address(target)
        addresses = (target,)
    except ipaddress.AddressValueError:
        emit(f'无线DNS查询：目标={target} 接口索引={interface.index}')
        addresses = resolver(target, interface.index, stop, guard)
        emit(f'无线DNS结果：{", ".join(addresses)}；本项使用第一个IPv4')
    remote = validate_remote_ipv4(addresses[0], adapters)

    def probe_guard():
        check_stop(stop)
        guard()
        check_stop(stop)
        current = adapter_provider()
        active = next((a for a in current if a['index'] == interface.index and
                       a['guid'].lower() == interface.guid.lower() and a['up']), None)
        if not active or source not in [a for a, _ in active['addresses']]:
            raise WifiEnvironmentError('无线Ping期间无线接口或源IPv4已改变')
        validate_remote_ipv4(remote, current)
        check_stop(stop)

    emit(f'无线Ping开始：网卡={interface.name} ifIndex={interface.index} 源IP={source} 目标={target} 实际IP={remote}')
    times = []
    identifier = secrets.randbelow(65536)
    payload = secrets.token_bytes(32)
    try:
        with socket_factory(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP) as sock:
            sock.bind((source, 0))
            sock.setsockopt(socket.IPPROTO_IP, getattr(socket, 'IP_UNICAST_IF', 31), struct.pack('!I', interface.index))
            # UDP connect只查询限定接口的可用路由，不发送探测、不修改路由。
            with socket_factory(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as route:
                route.bind((source, 0))
                route.setsockopt(socket.IPPROTO_IP, getattr(socket, 'IP_UNICAST_IF', 31), struct.pack('!I', interface.index))
                route.connect((remote, 9))
                if route.getsockname()[0] != source:
                    raise WifiEnvironmentError('无线Ping出口源地址不一致')
            for sequence in range(1, 5):
                probe_guard()
                started = clock()
                emit(f'无线Ping下发：第{sequence}/4包，{source} → {remote}，超时2秒')
                check_stop(stop)
                sock.sendto(echo_request(identifier, sequence, payload), (remote, 0))
                elapsed = None
                while clock() - started < 2:
                    probe_guard()
                    sock.settimeout(min(0.2, max(0.001, 2 - (clock() - started))))
                    try:
                        packet, _peer = sock.recvfrom(65535)
                    except socket.timeout:
                        continue
                    probe_guard()
                    if valid_reply(packet, remote, source, identifier, sequence, payload):
                        elapsed = (clock() - started) * 1000
                        times.append(elapsed)
                        break
                emit(f'无线Ping第{sequence}/4包：' + ('超时' if elapsed is None else f'回复 {elapsed:.2f}ms'))
                if sequence < 4:
                    wait(1, stop, probe_guard, clock)
            probe_guard()
    except OSError as exc:
        raise WifiEnvironmentError(f'无线Ping接口/socket异常（错误码{getattr(exc, "winerror", None) or exc.errno}），未回退其它网卡') from None
    result = WirelessPingResult(remote, 4, tuple(times))
    detail = f'发送4 接收{len(times)} 丢包率={(4 - len(times)) * 25}%'
    if times:
        detail += f' 时延min/avg/max={min(times):.2f}/{sum(times) / len(times):.2f}/{max(times):.2f}ms'
    emit('无线Ping汇总：' + detail + (' 通过' if result.ok else ' 失败'))
    return result
