from __future__ import annotations

import importlib
import socket
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import tftpy
from tftpy.TftpShared import TftpException


_tftp_server_module = importlib.import_module("tftpy.TftpServer")
_original_tftp_context_server = _tftp_server_module.TftpContextServer
_tftp_context_local = threading.local()


class _VlanBoundTftpContextServer(_original_tftp_context_server):
    """让 TFTPy 的传输数据 socket 使用监听该请求的 VLAN IP。"""

    def __init__(self, host, port, timeout, *args, **kwargs) -> None:
        super().__init__(host, port, timeout, *args, **kwargs)
        local_ip = getattr(_tftp_context_local, "local_ip", "")
        if not local_ip:
            return
        self.sock.close()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((local_ip, 0))
        self.sock.settimeout(timeout)


# TftpServer.listen() 没有提供 session 数据 socket 的 localip 参数。替换其上下文工厂，
# 由每个监听线程通过 thread-local 提供当前 VLAN IP；没有设置时保持第三方库原有行为。
_tftp_server_module.TftpContextServer = _VlanBoundTftpContextServer


# Windows 上 bind 一个不在本机网卡上的 IP 会抛 WSAEADDRNOTAVAIL(10049);
# 这里同时收集 POSIX 上的等价 errno 和 tftpy 自己的异常码,便于跨平台 fallback。
_BIND_UNAVAILABLE_ERRNOS = {
    getattr(socket, "WSAEADDRNOTAVAIL", None),  # Windows: 10049
    99,  # EADDRNOTAVAIL on Linux
}
_BIND_UNAVAILABLE_ERRNOS.discard(None)


# 源 IP 可绑校验抽到 bind_socket 模块,telnet_transport / ubus_http_client 共享。
# 这里保留旧名作为薄 shim,避免本模块以外的下游测试(例如 test_tftp_transport.py)导入路径被破坏。
# 注意:wait_for_bindable_ip 必须在本模块内"重新指过来",这样测试用 mock.patch
# `src.core.tftp_transport._ip_is_bindable_locally` 才会真正命中这一份闭包引用。
from .bind_socket import ip_is_bindable_locally as _ip_is_bindable_locally  # noqa: E402


def wait_for_bindable_ip(
    ip: str,
    timeout_seconds: float = 15.0,
    poll_seconds: float = 0.5,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> bool:
    """等待 Windows 将刚设置的网卡 IP 注册为可绑定地址。"""
    deadline = monotonic_fn() + max(0.0, timeout_seconds)
    while True:
        if _ip_is_bindable_locally(ip):
            return True
        remaining = deadline - monotonic_fn()
        if remaining <= 0:
            return False
        sleep_fn(min(max(0.01, poll_seconds), remaining))


@dataclass(frozen=True)
class TftpTransferResult:
    bytes_transferred: int = 0
    duration_seconds: float = 0.0


class TftpServerHandle:
    def __init__(
        self,
        bind_ip: str,
        firmware_path: Path,
        alias: str = "tclinux_allinone",
        port: int = 69,
        *,
        allow_any_fallback: bool = True,
    ) -> None:
        self.bind_ip = bind_ip
        self.firmware_path = Path(firmware_path)
        self.alias = alias
        self.port = port
        self.allow_any_fallback = allow_any_fallback
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
            if not self.allow_any_fallback:
                self.stop()
                raise RuntimeError(f"TFTP 服务无法严格绑定本机 IP：{self.bind_ip}:{self.port}")
            self._bind_ip_actually_used = ""
            bind_ip = ""

        def run() -> None:
            previous_local_ip = getattr(_tftp_context_local, "local_ip", None)
            _tftp_context_local.local_ip = bind_ip
            try:
                self._server.listen(bind_ip, self.port, timeout=1, retries=3)
            except OSError as exc:
                # listen 阶段也可能因 IP 失效抛 WSAEADDRNOTAVAIL;
                # 此时第二次尝试用 INADDR_ANY 兜底,避免现场踩到 ini 配置与实际网络状态不一致的情况。
                if self.allow_any_fallback and exc.errno in _BIND_UNAVAILABLE_ERRNOS and bind_ip:
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
            finally:
                if previous_local_ip is None:
                    try:
                        del _tftp_context_local.local_ip
                    except AttributeError:
                        pass
                else:
                    _tftp_context_local.local_ip = previous_local_ip

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
