from __future__ import annotations

import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import tftpy
from tftpy.TftpShared import TftpException


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

        def run() -> None:
            try:
                self._server.listen(self.bind_ip, self.port, timeout=1, retries=3)
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
