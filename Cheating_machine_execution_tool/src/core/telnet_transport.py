"""Telnet 会话实现（与 PySerialSession 同形：cursor / write / send_line / wait_for_any / wait_for_all / peek）。

背景：
- AGENTS 项目“写样机参数”原本经由串口 (vlan{N} -> COM{N-100})：针对多张同网段网卡，会随机选样机。
- 本类用于按 VLAN 网卡 IP 锁定 TCP 源 IP 的 telnet 写参。与 src/core/parameter_session.py 中
  ``ParameterSession`` 协议完全一致；service 层 run_parameter_write_pipeline 无需感知底层差异。

特性：
- socket.create_connection(..., source_address=(bind_ip, 0)) 强制从 PC 指定网卡出口。
- bind_ip 启动前由 bind_socket.ip_is_bindable_locally 预检；不可绑时直接抛错,不回退 0.0.0.0。
- 单读线程把所有 RX 字节写入 ``bytearray _history``；cursor() 即 ``len(_history)``。
- 保留 ``sensitive`` / ``known_secrets`` 形参兼容旧调用方；按项目约定，终端与日志明文显示密码。
- 与 PySerialSession 同语义：wait_for_any/all 在 cursor 之后字节历史里按 lowercase 子串匹配。

限制（切片 3 阶段）：
- 只保证必要功能完整：登录阶段等待 # 或 > 或 login:、命令阶段逐行读回等。
- 不实现 RFC854 negotiation / IAC handling（依现场样机 OpenWRT BusyBox telnetd 实测字节直传可用）。
"""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Iterable, Optional, Union

from .bind_socket import ip_is_bindable_locally


Marker = Union[bytes, str]

DEFAULT_TELNET_PORT = 23
DEFAULT_CONNECT_TIMEOUT_SECONDS = 15.0
DEFAULT_READ_TIMEOUT_SECONDS = 5.0


def probe_telnet_port(
    bind_ip: str,
    device_host: str,
    device_port: int = DEFAULT_TELNET_PORT,
    timeout: float = 5.0,
) -> None:
    """严格绑定指定源 IP 探测 Telnet TCP 端口；成功后立即关闭连接。"""
    if not ip_is_bindable_locally(bind_ip):
        raise RuntimeError(
            f"Telnet 探测源 IP 不属于本机网卡：{bind_ip}。"
            "请检查对应 VLAN 网卡和 network_card_ip.ini。"
        )
    try:
        with socket.create_connection(
            (device_host, int(device_port)),
            source_address=(bind_ip, 0),
            timeout=float(timeout),
        ):
            return
    except OSError as exc:
        raise RuntimeError(
            f"Telnet 端口不可连接 {device_host}:{int(device_port)} "
            f"源 IP {bind_ip}：{exc}"
        ) from exc


def _normalize_marker(marker: Marker) -> bytes:
    return marker.encode("utf-8") if isinstance(marker, str) else marker


class TelnetSession:
    """按 PC 源 IP (bind_ip) 强绑定,目标 device_host:port 的 telnet 会话。"""

    def __init__(
        self,
        bind_ip: str,
        device_host: str,
        device_port: int = DEFAULT_TELNET_PORT,
        log_path: Path | None = None,
        known_secrets: Iterable[str] = (),
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    ) -> None:
        # 严格语义: 不可绑直接报错,不回退 0.0.0.0。
        if not ip_is_bindable_locally(bind_ip):
            raise RuntimeError(
                f"Telnet 源 IP 不属于本机网卡：{bind_ip}。"
                "请在 network_card_ip.ini 调整对应 VLAN 的 network_card_ip，"
                "或用 'netsh interface ip set address' 重新启用该网卡。"
            )
        self.bind_ip = bind_ip
        self.device_host = device_host
        self.device_port = int(device_port)
        self.log_path = Path(log_path) if log_path else None
        self._connect_timeout = float(connect_timeout)
        self._known_secrets = tuple(
            secret.encode("utf-8") for secret in known_secrets if secret
        )

        self._sock: socket.socket | None = None
        self._history = bytearray()
        self._condition = threading.Condition()
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._closed = False
        self._log_handle = None
        self.error: Exception | None = None

        self._open_socket()
        self._start_reader()
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = self.log_path.open("a", encoding="utf-8", errors="replace")
        self._emit(b"STATE", "Telnet 已连接".encode("utf-8"))

    def _open_socket(self) -> None:
        try:
            self._sock = socket.create_connection(
                (self.device_host, self.device_port),
                source_address=(self.bind_ip, 0),
                timeout=self._connect_timeout,
            )
        except OSError as exc:
            # 2026-07-18: bind_ip 与 device_host 相同 → PC 把自己作为目标连接,OS 不响应 SYN,
            # 15 秒后 timed out。给操作员明确修复指引,避免反复猜测 network_card_ip.ini 配置。
            hint = ""
            if self.bind_ip == self.device_host:
                hint = (
                    "（提示：bind_ip 与 device_host 相同,PC 无法把自己作为目标连接；"
                    "请检查 network_card_ip.ini 中该 VLAN 的 device_manage_ip 是否误填为 PC 静态 IP,"
                    "样机管理 IP 应是设备自身 IP,典型 192.168.1.1。）"
                )
            raise RuntimeError(
                f"Telnet 连接失败 {self.device_host}:{self.device_port} 源 IP {self.bind_ip}：{exc}{hint}"
            ) from exc

    def _start_reader(self) -> None:
        self._reader = threading.Thread(
            target=self._reader_loop, name=f"telnet-reader-{self.device_host}", daemon=True
        )
        self._reader.start()

    def _reader_loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                chunk = self._sock.recv(4096)
            except OSError as exc:
                if not self._stop.is_set():
                    self.error = exc
                    self._emit(b"ERROR", f"Telnet 读取失败：{exc}".encode("utf-8"))
                break
            if not chunk:
                break
            with self._condition:
                self._history.extend(chunk)
                self._condition.notify_all()
            self._emit(b"RX", chunk)
        self._closed = True

    def cursor(self) -> int:
        with self._condition:
            return len(self._history)

    def peek_since(self, cursor: int) -> str:
        with self._condition:
            data = bytes(self._history[cursor:])
        return self._display(data)

    def write(self, data: bytes, sensitive: bool = False) -> None:
        if self._sock is None:
            raise RuntimeError(
                f"Telnet 未连接：{self.device_host}:{self.device_port}（源 IP {self.bind_ip}）"
            )
        if self._closed:
            raise RuntimeError(
                f"Telnet 连接已关闭：{self.device_host}:{self.device_port}"
            )
        try:
            self._sock.sendall(data)
        except OSError as exc:
            raise RuntimeError(
                f"Telnet 写入失败：{self.device_host}:{self.device_port}（{exc}）"
            ) from exc
        self._emit(b"TX", data, sensitive=sensitive)

    def send_line(self, text: str, sensitive: bool = False) -> None:
        # 业务侧约定使用 \r 作为行结束；OpenWRT telnetd 与 BusyBox 通用既支持 \r 也支持 \n。
        self.write(text.encode("utf-8") + b"\r", sensitive=sensitive)

    def wait_for_any(
        self,
        markers: Iterable[Marker],
        timeout_seconds: float,
        cursor: int,
    ) -> Optional[str]:
        normalized: list[bytes] = [_normalize_marker(m) for m in markers]
        deadline = time.monotonic() + float(timeout_seconds)
        needle_display = [(m.decode("utf-8") if isinstance(m, bytes) else m) for m in markers]
        with self._condition:
            while not self._stop.is_set():
                haystack = bytes(self._history[cursor:]).lower()
                for needle, label in zip(normalized, needle_display):
                    if needle.lower() in haystack:
                        return label if isinstance(label, str) else label.decode("utf-8")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(min(remaining, 0.25))
        return None

    def wait_for_all(
        self,
        markers: Iterable[Marker],
        timeout_seconds: float,
        cursor: int,
    ) -> bool:
        normalized: list[bytes] = [_normalize_marker(m) for m in markers]
        deadline = time.monotonic() + float(timeout_seconds)
        with self._condition:
            while not self._stop.is_set():
                haystack = bytes(self._history[cursor:]).lower()
                if all(m.lower() in haystack for m in normalized):
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(min(remaining, 0.25))
        return False

    def close(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._closed = True
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(timeout=2)
        self._emit(b"STATE", b"CLOSED")
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None

    def _display(self, data: bytes) -> str:
        # 操作员要求明文显示所有下发/回显内容,不再按 known_secrets 脱敏。
        return data.decode("utf-8", errors="replace")

    def _emit(self, direction: bytes, data: bytes, sensitive: bool = False) -> None:
        # ``sensitive`` 形参保留以兼容既有调用方;按操作员要求一律明文。
        text = self._display(data)
        if self._log_handle is not None:
            try:
                timestamp = time.strftime("[%Y-%m-%d %H:%M:%S] ")
                self._log_handle.write(f"{timestamp}{direction.decode('utf-8')} {text}\n")
                self._log_handle.flush()
            except OSError:
                pass
