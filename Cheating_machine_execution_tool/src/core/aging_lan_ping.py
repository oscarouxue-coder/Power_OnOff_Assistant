"""One ICMP echo on the reviewed Windows LAN interface and source address."""
import secrets
import socket
import struct
import time

from src.core.wireless_ping import echo_request, valid_reply


def bound_echo(binding, stop, dispatch, *, socket_factory=socket.socket, monotonic=time.monotonic):
    source, target = binding['source'], binding['target']
    identifier, payload = secrets.randbelow(65536), secrets.token_bytes(32)
    with socket_factory(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP) as sock:
        sock.bind((source, 0))
        sock.setsockopt(socket.IPPROTO_IP, getattr(socket, 'IP_UNICAST_IF', 31), struct.pack('!I', binding['index']))
        stop.checkpoint()
        sock.sendto(echo_request(identifier, 1, payload), (target, 0))
        dispatch(f"ICMP Echo · {binding['name']} ifIndex={binding['index']} · {source} → {target}")
        deadline = monotonic() + 1
        while True:
            stop.checkpoint()
            remaining = deadline - monotonic()
            if remaining <= 0:
                return False
            sock.settimeout(min(0.15, remaining))
            try:
                packet, _ = sock.recvfrom(65535)
            except socket.timeout:
                continue
            if valid_reply(packet, target, source, identifier, 1, payload):
                return True
