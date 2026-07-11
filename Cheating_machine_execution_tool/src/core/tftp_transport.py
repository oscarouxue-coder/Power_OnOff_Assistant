from __future__ import annotations

import socket
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import tftpy
from tftpy.TftpShared import TftpException


# Windows 上 bind 一个不在本机网卡上的 IP 会抛 WSAEADDRNOTAVAIL(10049);
# 这里同时收集 POSIX 上的等价 errno 和 tftpy 自己的异常码,便于跨平台 fallback。
_BIND_UNAVAILABLE_ERRNOS = {
    getattr(socket, "WSAEADDRNOTAVAIL", None),  # Windows: 10049
    99,  # EADDRNOTAVAIL on Linux
}
_BIND_UNAVAILABLE_ERRNOS.discard(None)


def _ip_is_bindable_locally(ip: str) -> bool:
    """检查指定 IPv4 是否能作为本机地址绑定(用于 TFTP 服务 start 前预检)。

    通过在指定 IP 上开一个 UDP socket 试 bind;若 bind 成功,说明该地址确实属于本机某张网卡,
    可以放心让 tftpy 监听;若失败,通常是该 IP 未配置在任何活动接口上,需要回退到 INADDR_ANY。
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


@dataclass(frozen=True)
class TftpTransferResult:
    bytes_transferred: int = 0
    duration_seconds: float = 0.0


class TftpServerHandle:
    def __init__(self, bind_ip: str, firmware_path: Path, alias: str = "tclinux_allinone", port: int = 69) -> None:
        self.bind_ip = bind_ip
        self.firmware_path = Path(firmware_path)
        self.alias = alias
        self.port = port
        self._temporary_root: tempfile.TemporaryDirectory | None = None
        self._server = None
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None
        # 实际监听的 bind_ip;若配置的 IP 不可绑定,会在 start() 中回退到 "" 并把这里更新为 INADDR_ANY 的语义值。
        self._bind_ip_actually_used: str = bind_ip

    @property
    def bind_ip_actually_used(self) -> str:
        """启动后回填:start() 真正监听的 IP(INADDR_ANY 时返回空串)。供上层日志展示。"""
        return self._bind_ip_actually_used

    def start(self, timeout_seconds: float = 10) -> None:
        if not self.firmware_path.is_file():
            raise RuntimeError(f"升级固件不存在：{self.firmware_path}")
        self._temporary_root = tempfile.TemporaryDirectory(prefix="line_check_tftp_")

        def only_selected_file(requested_path: str, **_kwargs):
            normalized = requested_path.replace("\\", "/").strip("/")
            if normalized != self.alias:
                return None
            return self.firmware_path.open("rb")

        self._server = tftpy.TftpServer(self._temporary_root.name, dyn_file_func=only_selected_file, flock=False)

        # 预检 bind_ip 是否真正属于本机网卡;若 network_card_ip.ini 与实际网络状态不一致
        # (例如 VLAN 网卡当前静态 IP 与配置不符,或网卡被禁用)直接 listen 会撞 WSAEADDRNOTAVAIL(10049)。
        # 这里提前回退到 INADDR_ANY(""),由 OS 路由决定回应哪个接口,TFTP 客户端拿到固件不会受影响。
        bind_ip = self.bind_ip
        if bind_ip and not _ip_is_bindable_locally(bind_ip):
            self._bind_ip_actually_used = ""
            bind_ip = ""

        def run() -> None:
            try:
                self._server.listen(bind_ip, self.port, timeout=1, retries=3)
            except OSError as exc:
                # listen 阶段也可能因 IP 失效抛 WSAEADDRNOTAVAIL;
                # 此时第二次尝试用 INADDR_ANY 兜底,避免现场踩到 ini 配置与实际网络状态不一致的情况。
                if exc.errno in _BIND_UNAVAILABLE_ERRNOS and bind_ip:
                    self._bind_ip_actually_used = ""
                    try:
                        self._server.listen("", self.port, timeout=1, retries=3)
                        return
                    except Exception as inner_exc:
                        self._error = inner_exc
                        return
                self._error = exc
            except Exception as exc:
                self._error = exc

        self._thread = threading.Thread(target=run, name=f"tftpy-server-{self.bind_ip}", daemon=True)
        self._thread.start()
        if not self._server.is_running.wait(timeout_seconds):
            self.stop()
            detail = f"：{self._error}" if self._error else ""
            raise RuntimeError(f"TFTP 服务未能绑定 {self.bind_ip}:{self.port}{detail}")

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.stop(now=True)
            except Exception:
                pass
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)
        if self._temporary_root is not None:
            self._temporary_root.cleanup()
        self._server = None
        self._thread = None
        self._temporary_root = None


def upload_firmware(
    firmware_path: Path,
    device_ip: str,
    source_ip: str,
    remote_name: str | None = None,
    port: int = 69,
    timeout_seconds: float = 600,
    on_output: Callable[[str], None] | None = None,
) -> TftpTransferResult:
    path = Path(firmware_path)
    if not path.is_file():
        raise RuntimeError(f"升级固件不存在：{path}")
    name = remote_name or path.name
    if on_output:
        on_output(f"TFTPy 上传：{source_ip} -> {device_ip}:{port}，远端文件：{name}")
    try:
        deadline = time.monotonic() + timeout_seconds

        def enforce_deadline(_packet) -> None:
            if time.monotonic() > deadline:
                raise TftpException(f"上传超过 {int(timeout_seconds)} 秒")

        client = tftpy.TftpClient(device_ip, port, options={}, localip=source_ip, flock=False)
        client.upload(name, str(path), packethook=enforce_deadline, timeout=5, retries=3)
    except (TftpException, OSError) as exc:
        raise RuntimeError(f"TFTP Put 失败：{exc}") from exc
    metrics = client.context.metrics if client.context is not None else None
    result = TftpTransferResult(
        bytes_transferred=int(getattr(metrics, "bytes", 0) or 0),
        duration_seconds=float(getattr(metrics, "duration", 0.0) or 0.0),
    )
    if on_output:
        on_output(f"TFTPy 上传完成：{result.bytes_transferred} 字节。")
    return result
