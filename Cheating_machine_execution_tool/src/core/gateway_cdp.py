"""Small synchronous DevTools client for an owned, loopback browser target."""
import base64
import hashlib
import json
import os
import socket
import struct
import time
from urllib.parse import urlsplit


class DevToolsClient:
    def __init__(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != "ws" or parsed.hostname != "127.0.0.1":
            raise ValueError("DevTools 必须使用本机独立浏览器端口。")
        self.connection = socket.create_connection((parsed.hostname, parsed.port), timeout=10)
        self.sequence = 0
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            self.connection.sendall((
                f"GET {parsed.path} HTTP/1.1\r\nHost: 127.0.0.1:{parsed.port}\r\n"
                f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode())
            header = bytearray()
            while not header.endswith(b"\r\n\r\n"):
                header.extend(self._read(1))
                if len(header) > 16384:
                    raise RuntimeError("DevTools 握手响应过大。")
            expected = base64.b64encode(hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
            ).digest()).decode()
            lines = header.decode().split("\r\n")
            headers = dict(line.split(":", 1) for line in lines[1:] if ":" in line)
            headers = {k.lower(): v.strip() for k, v in headers.items()}
            if " 101 " not in lines[0] or headers.get("sec-websocket-accept") != expected:
                raise RuntimeError("DevTools WebSocket 握手失败。")
        except Exception:
            self.close()
            raise

    def _read(self, size):
        data = bytearray()
        while len(data) < size:
            part = self.connection.recv(size - len(data))
            if not part:
                raise RuntimeError("升级浏览器 DevTools 连接已关闭。")
            data.extend(part)
        return bytes(data)

    def _send(self, payload, opcode=1):
        mask = os.urandom(4)
        length = len(payload)
        header = bytes([0x80 | opcode])
        if length < 126:
            header += bytes([0x80 | length])
        elif length <= 65535:
            header += bytes([0x80 | 126]) + struct.pack("!H", length)
        else:
            header += bytes([0x80 | 127]) + struct.pack("!Q", length)
        self.connection.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _receive(self):
        fragments = bytearray()
        while True:
            first, second = self._read(2)
            opcode = first & 15
            length = second & 127
            if length == 126:
                length = struct.unpack("!H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read(8))[0]
            if length > 8 * 1024 * 1024:
                raise RuntimeError("DevTools 消息过大。")
            mask = self._read(4) if second & 128 else None
            payload = self._read(length)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 8:
                raise RuntimeError("升级浏览器已关闭。")
            if opcode == 9:
                self._send(payload, 10)
                continue
            if opcode == 10:
                continue
            if opcode not in (0, 1):
                raise RuntimeError("DevTools 返回非文本消息。")
            fragments.extend(payload)
            if len(fragments) > 8 * 1024 * 1024:
                raise RuntimeError("DevTools 消息过大。")
            if first & 128:
                return json.loads(fragments)

    def call(self, method, params=None, timeout=15):
        self.sequence += 1
        self._send(json.dumps({"id": self.sequence, "method": method, "params": params or {}}).encode())
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"DevTools {method} 超时。")
            self.connection.settimeout(remaining)
            try:
                response = self._receive()
            except socket.timeout as exc:
                raise TimeoutError(f"DevTools {method} 等待响应超时（{timeout:g}秒）。") from exc
            if response.get("id") != self.sequence:
                continue
            if "error" in response:
                raise RuntimeError(f"DevTools {method}: {response['error']}")
            return response.get("result", {})

    def evaluate(self, expression):
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        if result.get("exceptionDetails"):
            raise RuntimeError(f"升级页面操作失败：{result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def close(self):
        self.connection.close()
