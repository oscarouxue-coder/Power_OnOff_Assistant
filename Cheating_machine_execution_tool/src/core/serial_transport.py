from __future__ import annotations

import codecs
import re
import tempfile
import threading
import time
import weakref
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable, Optional

import serial

from src.models import SerialEvent, SerialSettings
from src.core.transport_observation import register_session, retire_session
from src.core.host_resource_lock import HostResourceLock


Subscriber = Callable[[SerialEvent], None]
_LINE_END = re.compile(r'\r\n|\n|\r')


class SerialCloseError(RuntimeError):
    """The session could not confirm clean shutdown of all serial resources."""


class SerialCloseStartError(RuntimeError):
    """No worker started. The original serial ownership is still in effect."""


class SerialCloseTicket:
    """Data-only completion; failures never transport a reader traceback to Tk."""
    def __init__(self):
        self.done = threading.Event()
        self.error = ""


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

    HISTORY_LIMIT = 256 * 1024
    READ_CHUNK = 64 * 1024
    LOG_LINE_LIMIT = 64 * 1024

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
        self._host_resource_lock = None
        self._condition = threading.Condition()
        self._write_lock = threading.Lock()
        self._log_lock = threading.Lock()
        self._history = bytearray()
        self._history_offset = 0
        self._history_peak = 0
        self._unretained_bytes = 0
        self._history_file = None
        self._history_error = ''
        self._subscribers: set[Subscriber] = set()
        self._stop = threading.Event()
        self._closed = False
        self._close_lock = threading.Lock()
        self._close_done = threading.Event()
        self._close_started = False
        self._closer_ident = None
        self._close_error = ""
        self._reader: threading.Thread | None = None
        self._log_handle = None
        self._rx_log_line_buffer = ""
        self._rx_line_file = None
        self._rx_line_spilled = 0
        self._rx_line_cr = False
        self._rx_log_error = ''
        self.error: Exception | None = None
        register_session(self, "serial", settings.port)

    def open(self) -> None:
        if self._closed:
            raise RuntimeError(f"串口 {self.settings.port} 会话已结束，请重新取得会话")
        if self._serial is not None:
            return
        try:
            self._host_resource_lock = HostResourceLock(["serial:" + self.settings.port]).acquire()
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
            if self._host_resource_lock:
                self._host_resource_lock.close()
                self._host_resource_lock = None
            raise RuntimeError(f"打开串口 {self.settings.port} 失败：{exc}") from exc
        try:
            if self.log_path is not None:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                self._log_handle = self.log_path.open("a", encoding="utf-8", errors="replace")
            self._reader = threading.Thread(target=self._reader_loop, name=f"serial-reader-{self.settings.port}", daemon=True)
            self._reader.start()
            self._emit("STATE", b"OPEN", "串口已打开")
        except BaseException as open_error:
            # The driver is already open, even if the reader never started.
            try:
                self.close()
            except SerialCloseError as close_error:
                raise SerialCloseError(f"串口 {self.settings.port} 启动失败：{open_error}；"
                                       f"收尾失败：{close_error}") from close_error
            raise

    def cursor(self) -> int:
        with self._condition:
            return self._history_offset + len(self._history)

    def _append_history(self, data):
        """Called under _condition. Commit a new absolute offset only after writing the old bytes."""
        overflow = len(self._history) + len(data) - self.HISTORY_LIMIT
        if overflow > 0:
            if self._history_file is None:
                self._history_file = tempfile.TemporaryFile(mode='w+b', buffering=0, prefix='dutpilot-serial-rx-')
                # cursor and peek_since remain usable by holders of a closed session.
                weakref.finalize(self, self._history_file.close)
            move = min(len(self._history), max(self.READ_CHUNK, overflow))
            incoming = max(0, overflow - move)
            self._history_file.seek(self._history_offset)
            if self._history_file.write(memoryview(self._history)[:move]) != move:
                raise OSError('临时串口历史写入不完整')
            if incoming and self._history_file.write(memoryview(data)[:incoming]) != incoming:
                raise OSError('临时串口历史写入不完整')
            del self._history[:move]
            self._history_offset += move + incoming
            data = memoryview(data)[incoming:]
        self._history.extend(data)
        self._history_peak = max(self._history_peak, len(self._history))

    def _history_chunks(self, start, end):
        while start < end:
            with self._condition:
                if self._history_error:
                    raise RuntimeError(self._history_error)
                if start < self._history_offset:
                    size = min(end - start, self._history_offset - start, self.READ_CHUNK)
                    self._history_file.seek(start)
                    block = self._history_file.read(size)
                    if len(block) != size:
                        raise OSError('临时串口历史读取不完整')
                else:
                    size = min(end - start, self.READ_CHUNK)
                    offset = start - self._history_offset
                    block = bytes(self._history[offset:offset + size])
            yield block
            start += size

    def iter_rx_history(self, cursor=0):
        """Read the raw history as of this call in bounded chunks, including after close."""
        with self._condition:
            if self._history_error:
                raise RuntimeError(self._history_error)
            end = self.cursor()
            start = slice(cursor, None).indices(end)[0]
        return self._history_chunks(start, end)

    def peek_since(self, cursor: int) -> str:
        """从指定游标读取到当前的全部历史数据的解码字符串。

        用于诊断（如检测 UTF-8 解码失败标记），不消费也不修改历史。
        """
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        parts = [decoder.decode(block) for block in self.iter_rx_history(cursor)]
        parts.append(decoder.decode(b'', final=True))
        return ''.join(parts)

    def subscribe(self, subscriber: Subscriber) -> None:
        with self._condition:
            self._subscribers.add(subscriber)

    def unsubscribe(self, subscriber: Subscriber) -> None:
        # Keep the removed reference alive until after leaving the session lock.
        with self._condition:
            self._subscribers.discard(subscriber)

    def write(self, data: bytes, sensitive: bool = False) -> None:
        if self._serial is None:
            raise RuntimeError(
                f"串口 {self.settings.port} 未打开(open() 失败或从未调用,常见原因:"
                "该 COM 端口不存在、PC 串口驱动异常或权限不足)"
            )
        if self._closed:
            raise RuntimeError(f"串口 {self.settings.port} 已关闭")
        if self._history_error:
            raise RuntimeError(self._history_error)
        try:
            with self._write_lock:
                self._serial.write(data)
                flush = getattr(self._serial, "flush", None)
                if flush:
                    flush()
        except Exception as exc:
            raise RuntimeError(f"向串口 {self.settings.port} 发送失败：{exc}") from exc
        self._emit("TX", data, self._display(data), sensitive=sensitive)

    def send_line(self, text: str, sensitive: bool = False) -> None:
        self.write(text.encode("utf-8") + b"\r", sensitive=sensitive)

    def wait_for_any(self, markers: Iterable[bytes | str], timeout_seconds: float, cursor: int | None = None) -> str | None:
        normalized = [(item.decode("utf-8") if isinstance(item, bytes) else item).lower() for item in markers]
        result = self._wait_markers([s.encode('utf-8') for s in normalized], timeout_seconds, cursor, False)
        return normalized[result] if result is not None else None

    def wait_for_all(self, markers: Iterable[bytes | str], timeout_seconds: float, cursor: int | None = None) -> bool:
        needles = [(item.decode("utf-8") if isinstance(item, bytes) else item).lower().encode("utf-8") for item in markers]
        return self._wait_markers(needles, timeout_seconds, cursor, True) is not None

    def _wait_markers(self, needles, timeout_seconds, cursor, need_all):
        start = self.cursor() if cursor is None else cursor
        scanned = start
        overlap_size = max(0, max((len(n) for n in needles), default=0) - 1)
        overlap = b''
        found = {i for i, needle in enumerate(needles) if not needle}
        deadline = time.monotonic() + timeout_seconds
        while not self._stop.is_set():
            with self._condition:
                if self._history_error:
                    raise RuntimeError(self._history_error)
                end = self.cursor()
            if start < 0:
                # A negative cursor refers to the current suffix, which moves on append.
                scanned = max(0, end + start)
                overlap = b''
                found = {i for i, needle in enumerate(needles) if not needle}
            for block in self._history_chunks(scanned, end):
                if self._stop.is_set():
                    return None
                segment = overlap + block.lower()
                found.update(i for i, needle in enumerate(needles) if i not in found and needle in segment)
                if len(found) == len(needles) or (not need_all and 0 in found):
                    break
                overlap = segment[-overlap_size:] if overlap_size else b''
            if need_all and len(found) == len(needles):
                return 0
            if not need_all and found:
                return min(found)
            scanned = max(scanned, end)
            with self._condition:
                if self._history_error:
                    raise RuntimeError(self._history_error)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                if self.cursor() != end:
                    continue
                self._condition.wait(min(remaining, threading.TIMEOUT_MAX))
        return None

    def close(self) -> None:
        with self._close_lock:
            if self._close_done.is_set():
                if self._close_error:
                    raise SerialCloseError(self._close_error)
                return
            other_closer = self._close_started
            same_closer = self._closer_ident == threading.get_ident()
            self._close_started = True
            if not other_closer:
                self._closer_ident = threading.get_ident()
        if other_closer:
            if same_closer:
                return  # a CLOSED subscriber may call close() idempotently
            self._close_done.wait()
            if self._close_error:
                raise SerialCloseError(self._close_error)
            return
        driver_error = ""
        try:
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
                except Exception as exc:
                    driver_error = f"串口 {self.settings.port} 驱动关闭失败：{exc}"
            with self._condition:
                self._condition.notify_all()
            if self._reader is threading.current_thread():
                raise RuntimeError('串口读线程不能同步关闭自身')
            if self._reader is not None and self._reader.ident is not None:
                # Only background owners / close workers call this blocking API.
                # Do not close the log under a still-executing reader callback.
                self._reader.join()
            try:
                if self._rx_log_error:
                    raise SerialCloseError(self._rx_log_error)
                self._flush_pending_rx_log_line()
                if driver_error:
                    self._emit("ERROR", b"", driver_error)
                else:
                    self._emit("STATE", b"CLOSED", "串口已关闭")
            finally:
                if self._rx_line_file is not None:
                    self._rx_line_file.close()
                    self._rx_line_file = None
                if self._log_handle is not None:
                    self._log_handle.close()
                    self._log_handle = None
            if driver_error:
                raise SerialCloseError(driver_error)
            if self._host_resource_lock:
                self._host_resource_lock.close()
                self._host_resource_lock = None
        except Exception as exc:
            self._close_error = str(exc) or type(exc).__name__
            if isinstance(exc, SerialCloseError):
                raise
            raise SerialCloseError(self._close_error) from exc
        finally:
            self._close_done.set()
            retire_session(self)

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
                try:
                    self._append_history(data)
                except OSError as exc:
                    self._unretained_bytes += len(data)
                    self._history_error = f'串口 {self.settings.port} 临时原始历史写入失败，已停止接收：{exc}'
                    self.error = RuntimeError(self._history_error)
                self._condition.notify_all()
            try:
                self._emit("RX", data, self._display(data))
                if self._history_error:
                    self._emit("ERROR", b'', self._history_error)
            except OSError as exc:
                self._rx_log_error = f'串口 {self.settings.port} 日志或临时行缓冲写入失败，已停止接收：{exc}'
                with self._condition:
                    self._history_error = self._history_error or self._rx_log_error
                    self.error = RuntimeError(self._history_error)
                    self._condition.notify_all()
                # A failed log destination cannot carry its own diagnostic.
                self._notify_subscribers(SerialEvent(self.settings.port, 'ERROR', b'', self._rx_log_error, False))
            if self._history_error:
                break

    def _display(self, data: bytes) -> str:
        # 操作员要求明文显示所有下发/回显内容,不再按 known_secrets 脱敏。
        return data.decode("utf-8", errors="replace")

    def _emit(self, direction: str, data: bytes, text: str, sensitive: bool = False) -> None:
        event = SerialEvent(self.settings.port, direction, data, text, sensitive)
        if self._log_handle is not None and direction in {"RX", "TX", "ERROR", "STATE"}:
            self._write_timestamped_log_event(direction, text)
        self._notify_subscribers(event)

    def _notify_subscribers(self, event):
        with self._condition:
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber(event)
            except Exception:
                continue

    def _write_timestamped_log_event(self, direction: str, text: str) -> None:
        """逐行写入带时间戳的日志，RX 半行允许跨串口读取块拼接。"""
        with self._log_lock:
            if self._log_handle is None:
                return
            if direction == "RX":
                self._write_rx_lines_locked(text)
            else:
                self._flush_pending_rx_log_line_locked()
                lines = text.splitlines() or [""]
                for line in lines:
                    self._write_timestamped_log_line_locked(direction, line)
            self._log_handle.flush()

    def _append_rx_text(self, text):
        if len(self._rx_log_line_buffer) + len(text) <= self.LOG_LINE_LIMIT:
            self._rx_log_line_buffer += text
            return
        if self._rx_line_file is None:
            self._rx_line_file = tempfile.TemporaryFile(mode='w+t', encoding='utf-8', newline='', prefix='dutpilot-serial-line-')
        self._rx_line_file.write(self._rx_log_line_buffer)
        for start in range(0, len(text), self.READ_CHUNK):
            self._rx_line_file.write(text[start:start + self.READ_CHUNK])
        self._rx_line_spilled += len(self._rx_log_line_buffer) + len(text)
        self._rx_log_line_buffer = ''

    def _write_rx_lines_locked(self, text):
        if not text:
            return
        start = 0
        if self._rx_line_cr:
            self._finish_rx_line_locked()
            start = int(text.startswith('\n'))
        for match in _LINE_END.finditer(text, start):
            self._append_rx_text(text[start:match.start()])
            start = match.end()
            if start == len(text) and match.group() == '\r':
                self._rx_line_cr = True
                return
            self._finish_rx_line_locked()
        self._append_rx_text(text[start:])

    def _finish_rx_line_locked(self):
        if self._rx_line_file is None:
            self._write_timestamped_log_line_locked('RX', self._rx_log_line_buffer)
        else:
            self._rx_line_file.seek(0)
            self._log_handle.write(time.strftime('%Y-%m-%d_%H:%M:%S') + ' RX ')
            while True:
                part = self._rx_line_file.read(self.READ_CHUNK)
                if not part:
                    break
                self._log_handle.write(part)
            self._log_handle.write(self._rx_log_line_buffer + '\n')
            self._rx_line_file.close()
            self._rx_line_file = None
        self._rx_log_line_buffer = ''
        self._rx_line_spilled = 0
        self._rx_line_cr = False

    def _flush_pending_rx_log_line(self) -> None:
        with self._log_lock:
            self._flush_pending_rx_log_line_locked()
            if self._log_handle is not None:
                self._log_handle.flush()

    def _flush_pending_rx_log_line_locked(self) -> None:
        if self._rx_log_line_buffer or self._rx_line_cr or self._rx_line_file is not None:
            self._finish_rx_line_locked()

    def _write_timestamped_log_line_locked(self, direction: str, line: str) -> None:
        if self._log_handle is None:
            return
        timestamp = time.strftime("%Y-%m-%d_%H:%M:%S")
        self._log_handle.write(f"{timestamp} {direction} {line}\n")


class SerialSessionManager:
    def __init__(self, *, resource_coordinator=None, project_id='', project_name='') -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, PySerialSession] = {}
        self._owners: dict[str, set[str]] = defaultdict(set)
        self._controllers: dict[str, str] = {}
        self._closing: dict[str, SerialCloseTicket] = {}
        self._resource_coordinator = resource_coordinator
        self._project_id, self._project_name = project_id, project_name

    def _workspace_owner(self, port):
        return 'serial-session:' + self._project_id + ':' + port

    def acquire_monitor(self, owner: str, settings: SerialSettings, log_path: Path | None = None) -> PySerialSession:
        return self._acquire(owner, settings, log_path, control=False)

    def acquire_control(self, owner: str, settings: SerialSettings, log_path: Path | None = None) -> PySerialSession:
        return self._acquire(owner, settings, log_path, control=True)

    def _acquire(self, owner: str, settings: SerialSettings, log_path: Path | None, control: bool) -> PySerialSession:
        port = settings.port.upper()
        with self._lock:
            if port in self._closing:
                raise RuntimeError(f"串口 {port} 正在关闭，请等待日志收尾后重试")
            existing_controller = self._controllers.get(port)
            if control and existing_controller not in (None, owner):
                raise RuntimeError(f"串口 {port} 正被升级流程占用")
            session = self._sessions.get(port)
            if session is None:
                coordinator = self._resource_coordinator
                if coordinator is not None:
                    coordinator.acquire(self._workspace_owner(port), self._project_id, self._project_name, ['serial:' + port])
                try:
                    session = PySerialSession(settings, log_path)
                    session.open()
                except SerialCloseError as exc:
                    # Rollback failed after opening the driver. Fence the port
                    # exactly as for a failure closing an admitted session.
                    ticket = SerialCloseTicket()
                    ticket.error = str(exc)
                    self._closing[port] = ticket
                    ticket.done.set()
                    if coordinator is not None:
                        coordinator.release(self._workspace_owner(port), uncertain=True)
                    raise
                except BaseException:
                    if coordinator is not None:
                        coordinator.release(self._workspace_owner(port))
                    raise
                self._sessions[port] = session
            self._owners[port].add(owner)
            if control:
                self._controllers[port] = owner
            return session

    def _begin_close(self, key, session, wait):
        # Caller holds the manager lock. Commit the handoff only after a worker
        # exists, so a refused nonblocking close leaves every owner intact.
        ticket = SerialCloseTicket()
        if not wait:
            worker = threading.Thread(target=self._close_session, args=(key, session, ticket),
                                      name=f"serial-close-{key}", daemon=True)
            try:
                worker.start()
            except RuntimeError as error:
                if worker.ident is None:
                    raise SerialCloseStartError(str(error)) from error
        self._closing[key] = ticket
        del self._sessions[key]
        self._owners.pop(key, None)
        self._controllers.pop(key, None)
        return ticket

    def release(self, owner: str, port: str, *, wait: bool = True):
        key = port.upper()
        with self._lock:
            if key in self._closing:
                return self._closing[key]
            session = self._sessions.get(key)
            if session is None:
                ticket = SerialCloseTicket()
                ticket.done.set()
                return ticket
            owners = self._owners[key]
            if owners != {owner}:
                owners.discard(owner)
                if self._controllers.get(key) == owner:
                    self._controllers.pop(key)
                return
            ticket = self._begin_close(key, session, wait)
        if wait:
            self._close_session(key, session, ticket)
            if ticket.error:
                raise RuntimeError(ticket.error)
        return ticket

    def _close_session(self, key, session, ticket):
        try:
            session.close()
        except Exception as exc:
            ticket.error = type(exc).__name__ + ': ' + str(exc)
        finally:
            with self._lock:
                # A failed close remains reserved; reopening an unknown driver
                # state could create a second reader on the physical port.
                if self._resource_coordinator is not None:
                    try:
                        self._resource_coordinator.release(self._workspace_owner(key), uncertain=bool(ticket.error))
                    except Exception as exc:
                        message = f"串口 {key} 的工作区资源释放未确认：{type(exc).__name__}: {exc}"
                        ticket.error = (ticket.error + "；" if ticket.error else "") + message
                if not ticket.error:
                    self._closing.pop(key, None)
            ticket.done.set()

    def manual_writable(self, port: str) -> bool:
        with self._lock:
            return port.upper() not in self._controllers

    def existing_session(self, settings: SerialSettings) -> PySerialSession | None:
        """诊断只复用已打开的相同配置；不得悄悄改变串口参数。"""
        with self._lock:
            session = self._sessions.get(settings.port.upper())
            if session is not None and session.settings != settings:
                raise RuntimeError("已打开串口参数与目标配置不一致")
            return session

    def acquire_existing_control(self, owner: str, settings: SerialSettings) -> PySerialSession:
        with self._lock:
            if self.existing_session(settings) is None:
                raise RuntimeError("目标串口尚未打开")
            return self._acquire(owner, settings, None, control=True)

    def control_owner(self, port: str) -> str:
        with self._lock:
            return self._controllers.get(port.upper(), "")

    def diagnostic_state(self, port: str) -> dict:
        """仅查看程序内部已知所有者，不打开设备、不推测外部占用。"""
        with self._lock:
            key = port.upper()
            return {"port": key, "opened_in_program": key in self._sessions,
                    "closing_in_program": key in self._closing,
                    "monitor_owners": sorted(self._owners.get(key, ())),
                    "control_owner": self._controllers.get(key, "")}

    def shutdown_all(self, *, wait: bool = True):
        with self._lock:
            work = []
            for key, session in tuple(self._sessions.items()):
                ticket = self._begin_close(key, session, wait)
                if wait:
                    work.append((key, session, ticket))
            tickets = tuple(self._closing.values())
        if wait:
            for key, session, ticket in work:
                self._close_session(key, session, ticket)
            for ticket in tickets:
                ticket.done.wait()
        return tickets
