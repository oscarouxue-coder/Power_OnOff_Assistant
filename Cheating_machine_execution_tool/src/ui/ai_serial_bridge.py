"""诊断后台线程到现有串口窗口的主线程桥；不模拟键盘，不新建读线程。"""
from __future__ import annotations

from concurrent.futures import Future
import queue
import threading
import time
import uuid

from src.models.serial_models import SerialSettings


class AiSerialBridge:
    def __init__(self, terminal, manager, busy, forbidden_port=lambda: ""):
        self.terminal, self.manager = terminal, manager
        self.busy_callback, self.forbidden_port = busy, forbidden_port
        self.requests = queue.Queue(maxsize=32)
        self.controls = {}
        self.lock = threading.RLock()
        self.closed = False
        terminal.ai_debug_cancel = self.cancel_port

    def call_ui(self, action, stop=None):
        future = Future()
        self.requests.put_nowait((future, action, stop))
        deadline = time.monotonic() + 20
        while not future.done():
            if self.closed or (stop is not None and stop.is_set()) or time.monotonic() >= deadline:
                future.cancel()
                raise InterruptedError("主线程操作已取消或超时")
            time.sleep(0.02)
        return future.result()

    def poll(self):
        for _ in range(20):
            try:
                future, action, stop = self.requests.get_nowait()
            except queue.Empty:
                break
            if future.cancelled():
                continue
            if self.closed or (stop is not None and stop.is_set()):
                future.set_exception(InterruptedError("串口诊断已取消"))
                continue
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(action())
            except Exception as exc:
                future.set_exception(exc)

    def busy(self, target):
        return self.call_ui(lambda: self.busy_callback(target))

    def acquire(self, target, stop):
        def open_on_ui():
            if self.busy_callback(target):
                raise RuntimeError("目标设备正在执行操作，跳过串口主动采集")
            if not target.port or target.port.upper() == self.forbidden_port().upper():
                raise ValueError("目标串口不明确或与程控电源串口冲突")
            existing = self.terminal.tabs.get(target.vlan.lower())
            if existing and existing["session"] is not None and existing["port"].upper() != target.port.upper():
                raise ValueError("已打开的目标标签与本次COM快照不一致")
            if not self.manager.manual_writable(target.port):
                raise RuntimeError("目标串口已被其它流程控制，只允许读取日志")
            self.terminal.show([(target.vlan, target.port)])
            if not self.terminal.open_monitor(target.vlan.lower()):
                raise RuntimeError("目标串口打开失败")
            owner = "ai-debug:" + uuid.uuid4().hex
            session = self.manager.acquire_existing_control(owner, SerialSettings(target.port))
            cancelled = threading.Event()
            with self.lock:
                self.controls[target.port.upper()] = (owner, cancelled)
            self.terminal.tabs[target.vlan.lower()]["status"].set(
                f"{target.port} AI Debug中，手动发送暂时锁定；日志继续记录")
            return session, owner, cancelled
        session, owner, cancelled = self.call_ui(open_on_ui, stop)

        def release():
            self.manager.release(owner, target.port)
            with self.lock:
                self.controls.pop(target.port.upper(), None)
            try:
                self.requests.put_nowait((Future(), lambda: self._restore_status(target), None))
            except queue.Full:
                pass
        return session, release, cancelled

    def _restore_status(self, target):
        item = self.terminal.tabs.get(target.vlan.lower())
        if item and item["session"] is not None:
            item["status"].set(f"{target.port} 监控中，AI Debug已结束，日志继续记录")

    def cancel_port(self, port):
        with self.lock:
            item = self.controls.get(port.upper())
            if item:
                item[1].set()
                return True
        return False

    def read(self, target):
        session = self.manager.existing_session(SerialSettings(target.port)) if target.port else None
        if session is None:
            return "目标串口未打开，无实时串口输出；未为被动读取自动打开COM"
        return session.peek_since(max(0, session.cursor() - 65536))

    def close(self):
        self.closed = True
        with self.lock:
            for _, cancel in self.controls.values():
                cancel.set()
