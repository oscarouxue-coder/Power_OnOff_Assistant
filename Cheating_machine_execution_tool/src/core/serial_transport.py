from __future__ import annotations

import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable, Optional

import serial

from src.models import SerialEvent, SerialSettings


Subscriber = Callable[[SerialEvent], None]


def vlan_to_serial_port(vlan: str) -> str:
    normalized = (vlan or "").strip().lower()
    if not normalized.startswith("vlan") or not normalized[4:].isdigit():
        raise ValueError(f"无法从 VLAN 名称确定串口：{vlan or '空值'}")
    number = int(normalized[4:]) - 100
    if number < 1:
        raise ValueError(f"VLAN 与串口映射无效：{vlan}")
    return f"COM{number}"


class PySerialSession:
    """One reader thread per physical COM port.

    All marker waits inspect the same byte history, so markers split across
    driver reads are still detected and no second reader can steal data.
    """

    def __init__(
        self,
        settings: SerialSettings,
        log_path: Path | None = None,
        serial_factory: Callable[..., object] = serial.Serial,
        known_secrets: Iterable[str] = (),
    ) -> None:
        self.settings = settings
        self.log_path = log_path
        self._serial_factory = serial_factory
        self._known_secrets = tuple(secret.encode("utf-8") for secret in known_secrets if secret)
        self._serial = None
        self._condition = threading.Condition()
        self._write_lock = threading.Lock()
        self._history = bytearray()
        self._subscribers: set[Subscriber] = set()
        self._stop = threading.Event()
        self._closed = False
        self._reader: threading.Thread | None = None
        self._log_handle = None
        self.error: Exception | None = None

    def open(self) -> None:
        if self._serial is not None:
            return
        try:
            self._serial = self._serial_factory(
                port=self.settings.port,
                baudrate=self.settings.baudrate,
                bytesize=self.settings.bytesize,
                parity=self.settings.parity,
                stopbits=self.settings.stopbits,
                timeout=self.settings.timeout,
                write_timeout=self.settings.write_timeout,
                xonxoff=self.settings.xonxoff,
                rtscts=self.settings.rtscts,
                dsrdtr=self.settings.dsrdtr,
            )
        except Exception as exc:
            raise RuntimeError(f"打开串口 {self.settings.port} 失败：{exc}") from exc
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = self.log_path.open("a", encoding="utf-8", errors="replace")
        self._reader = threading.Thread(target=self._reader_loop, name=f"serial-reader-{self.settings.port}", daemon=True)
        self._reader.start()
        self._emit("STATE", b"OPEN", "串口已打开")

    def cursor(self) -> int:
        with self._condition:
            return len(self._history)

    def subscribe(self, subscriber: Subscriber) -> None:
        with self._condition:
            self._subscribers.add(subscriber)

    def unsubscribe(self, subscriber: Subscriber) -> None:
        with self._condition:
            self._subscribers.discard(subscriber)

    def write(self, data: bytes, sensitive: bool = False) -> None:
        if self._serial is None or self._closed:
            raise RuntimeError(f"串口 {self.settings.port} 未打开")
        try:
            with self._write_lock:
                self._serial.write(data)
                flush = getattr(self._serial, "flush", None)
                if flush:
                    flush()
        except Exception as exc:
            raise RuntimeError(f"向串口 {self.settings.port} 发送失败：{exc}") from exc
        self._emit("TX", data, "[敏感内容已隐藏]" if sensitive else self._display(data), sensitive=sensitive)

    def send_line(self, text: str, sensitive: bool = False) -> None:
        self.write(text.encode("utf-8") + b"\r", sensitive=sensitive)

    def wait_for_any(self, markers: Iterable[bytes | str], timeout_seconds: float, cursor: int | None = None) -> str | None:
        normalized = [(item.decode("utf-8") if isinstance(item, bytes) else item).lower() for item in markers]
        needle_bytes = [item.encode("utf-8") for item in normalized]
        start = self.cursor() if cursor is None else cursor
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while not self._stop.is_set():
                haystack = bytes(self._history[start:]).lower()
                for marker, needle in zip(normalized, needle_bytes):
                    if needle in haystack:
                        return marker
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(min(remaining, 0.25))
        return None

    def wait_for_all(self, markers: Iterable[bytes | str], timeout_seconds: float, cursor: int | None = None) -> bool:
        normalized = [(item.decode("utf-8") if isinstance(item, bytes) else item).lower().encode("utf-8") for item in markers]
        start = self.cursor() if cursor is None else cursor
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while not self._stop.is_set():
                haystack = bytes(self._history[start:]).lower()
                if all(marker in haystack for marker in normalized):
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(min(remaining, 0.25))
        return False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        if self._serial is not None:
            try:
                cancel_read = getattr(self._serial, "cancel_read", None)
                if cancel_read:
                    cancel_read()
            except Exception:
                pass
            try:
                self._serial.close()
            except Exception:
                pass
        with self._condition:
            self._condition.notify_all()
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(timeout=2)
        self._emit("STATE", b"CLOSED", "串口已关闭")
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def _reader_loop(self) -> None:
        while not self._stop.is_set() and self._serial is not None:
            try:
                waiting = int(getattr(self._serial, "in_waiting", 0) or 0)
                data = self._serial.read(waiting or 1)
            except Exception as exc:
                if not self._stop.is_set():
                    self.error = exc
                    self._emit("ERROR", str(exc).encode("utf-8", errors="replace"), f"串口读取失败：{exc}")
                break
            if not data:
                continue
            with self._condition:
                self._history.extend(data)
                self._condition.notify_all()
            self._emit("RX", data, self._display(data))

    def _display(self, data: bytes) -> str:
        text = data.decode("utf-8", errors="replace")
        for secret in self._known_secrets:
            decoded = secret.decode("utf-8", errors="ignore")
            if decoded:
                text = text.replace(decoded, "[敏感内容已隐藏]")
        return text

    def _emit(self, direction: str, data: bytes, text: str, sensitive: bool = False) -> None:
        event = SerialEvent(self.settings.port, direction, data, text, sensitive)
        if self._log_handle is not None and direction in {"RX", "TX", "ERROR", "STATE"}:
            timestamp = time.strftime("[%Y-%m-%d %H:%M:%S] ")
            self._log_handle.write(f"{timestamp}{direction} {text}\n")
            self._log_handle.flush()
        with self._condition:
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber(event)
            except Exception:
                continue


class SerialSessionManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, PySerialSession] = {}
        self._owners: dict[str, set[str]] = defaultdict(set)
        self._controllers: dict[str, str] = {}

    def acquire_monitor(self, owner: str, settings: SerialSettings, log_path: Path | None = None) -> PySerialSession:
        return self._acquire(owner, settings, log_path, control=False)

    def acquire_control(self, owner: str, settings: SerialSettings, log_path: Path | None = None) -> PySerialSession:
        return self._acquire(owner, settings, log_path, control=True)

    def _acquire(self, owner: str, settings: SerialSettings, log_path: Path | None, control: bool) -> PySerialSession:
        port = settings.port.upper()
        with self._lock:
            existing_controller = self._controllers.get(port)
            if control and existing_controller not in (None, owner):
                raise RuntimeError(f"串口 {port} 正被升级流程占用")
            session = self._sessions.get(port)
            if session is None:
                session = PySerialSession(settings, log_path)
                session.open()
                self._sessions[port] = session
            self._owners[port].add(owner)
            if control:
                self._controllers[port] = owner
            return session

    def release(self, owner: str, port: str) -> None:
        key = port.upper()
        with self._lock:
            if self._controllers.get(key) == owner:
                self._controllers.pop(key, None)
            self._owners[key].discard(owner)
            if self._owners[key]:
                return
            session = self._sessions.pop(key, None)
            self._owners.pop(key, None)
        if session is not None:
            session.close()

    def manual_writable(self, port: str) -> bool:
        with self._lock:
            return port.upper() not in self._controllers

    def shutdown_all(self) -> None:
        with self._lock:
            sessions = tuple(self._sessions.values())
            self._sessions.clear()
            self._owners.clear()
            self._controllers.clear()
        for session in sessions:
            session.close()
