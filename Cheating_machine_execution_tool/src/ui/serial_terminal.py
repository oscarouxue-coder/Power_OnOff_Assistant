from __future__ import annotations

import json
import os
import queue
import re
import time
from collections import deque
from datetime import date
from pathlib import Path
from tkinter import END, Frame, Label, StringVar, Text, Toplevel, filedialog, messagebox, ttk
from typing import Callable

from src.config import DEFAULT_LOG_DIR
from src.core import SerialSessionManager, vlan_to_serial_port
from src.models import SerialSettings
from src.ui.closable_notebook import ClosableNotebook
from src.ui.window_paint import center_toplevel_on_parent
from src.ui.module_theme import apply_module_theme
from src.ui.tk_lifecycle import TkScope
from src.utils.bounded_mailbox import BoundedMailbox
from src.models.serial_delivery import SerialDelivery


_DEFAULT_GEOMETRY = "1000x650"
_MIN_WIDTH = 1000
_MIN_HEIGHT = 650
_GEOMETRY_PATTERN = re.compile(r"^(?P<w>\d+)x(?P<h>\d+)(?P<x>[+-]\d+)(?P<y>[+-]\d+)$")
_MIN_VISIBLE = 120  # 窗口在屏幕内至少要可见的像素,避免开屏外
_RENDER_EVENTS_PER_TICK = 120
_RENDER_TIME_BUDGET_SECONDS = 0.010
_RENDER_ACTIVE_DELAY_MS = 33
_RENDER_IDLE_DELAY_MS = 80
_PENDING_CHARS_PER_VLAN = 64 * 1024
_DISPLAY_MAX_LINES = 5000


def build_serial_log_path(
    log_dir: Path,
    vlan: str,
    port: str,
    opened_on: date | None = None,
) -> Path:
    """按 VLAN、COM 和打开日期生成串口日志文件名。"""
    day = opened_on or date.today()
    return Path(log_dir) / f"{vlan}_{port}_{day:%Y%m%d}.log"


class SerialTerminalWindow:
    def __init__(
        self,
        master,
        manager: SerialSessionManager,
        log_dir: Path,
        state_file: Path | None = None,
        on_log_dir_changed: Callable[[Path], None] | None = None,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        self.master = master
        self.manager = manager
        self.log_dir = log_dir
        self._log_dir_initialized = False
        self._on_log_dir_changed = on_log_dir_changed
        self._logger = logger
        # 默认存到用户目录下,跨平台、安全且不会被误删
        self.state_file = state_file or (Path.home() / ".aouxue_serial_terminal.json")
        self.window = None
        self.notebook = None
        self.tabs = {}
        self.last_open_errors = {}
        self.events = BoundedMailbox(maxsize=2000)
        self._scope = TkScope()
        self._closing = False
        self._deferred = {}
        self._reported_drops = 0
        self._pending_chunks: dict[str, deque[str]] = {}
        self._pending_char_counts: dict[str, int] = {}
        self._pending_dropped_chars: dict[str, int] = {}
        self._after_id = None
        self._upgrade_batch_active = False
        self._auto_opened_for_upgrade = False

    def begin_upgrade_logs(self, vlans: list[str]) -> None:
        """标记本批自动升级；仅本批自动打开的窗口会在完成后自动关闭。"""
        self._upgrade_batch_active = bool(vlans)

    def finish_upgrade_logs(self) -> None:
        """本批升级串口已释放后关闭其自动打开的终端窗口。"""
        self._upgrade_batch_active = False
        if self._auto_opened_for_upgrade:
            self.close()

    @staticmethod
    def _target_values(target: str | tuple[str, str]) -> tuple[str, str]:
        if isinstance(target, tuple):
            vlan, port = target
            return str(vlan), str(port).strip().upper()
        return str(target), ""

    def show(self, vlans: list[str | tuple[str, str]]) -> None:
        self._scope.check()
        if self._closing or self.master.__dict__.get('_app_closing', False):
            return
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            for target in vlans:
                vlan, port = self._target_values(target)
                self._ensure_tab(vlan, port)
            return
        # 优先恢复上次保存的日志目录,失效时回退到默认 D:\Serial_Log
        self.log_dir = self._restore_log_dir()
        self._log_dir_initialized = True
        self.window = Toplevel(self.master)
        self._scope = TkScope()
        self.window.title("串口日志记录")
        # 优先恢复上次窗口位置+大小,无效时回退到默认尺寸
        saved_geometry = self._load_geometry()
        self.window.geometry(saved_geometry or _DEFAULT_GEOMETRY)
        # 禁止用户拖拽到比默认更小,避免内容被挤压变形
        self.window.minsize(_MIN_WIDTH, _MIN_HEIGHT)
        toolbar = Frame(self.window)
        toolbar.pack(fill="x", padx=12, pady=8)
        ttk.Button(toolbar, text="打开全部", command=self.open_all).pack(side="left")
        ttk.Button(toolbar, text="停止全部", command=self.stop_all).pack(side="left", padx=8)
        # 右侧:日志目录选择(只读展示 + 浏览/打开文件夹)
        self.log_dir_var = self._scope.variable(StringVar, self.window, value=str(self.log_dir))
        path_bar = Frame(toolbar)
        path_bar.pack(side="right")
        ttk.Label(path_bar, text="日志目录:").pack(side="left")
        ttk.Entry(path_bar, textvariable=self.log_dir_var, width=50, state="readonly").pack(side="left", padx=(4, 6))
        ttk.Button(path_bar, text="浏览…", command=self._choose_log_dir).pack(side="left", padx=(0, 4))
        ttk.Button(path_bar, text="打开文件夹", command=self._open_log_dir).pack(side="left")
        self.notebook = ClosableNotebook(self.window, on_close=self._on_tab_close)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        for target in vlans:
            vlan, port = self._target_values(target)
            self._ensure_tab(vlan, port)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        apply_module_theme(self.window)
        if saved_geometry is None or self._geometry_is_at_top_left(saved_geometry):
            center_toplevel_on_parent(self.window, self.master)
        self._poll()
        if self._on_log_dir_changed is not None:
            self._on_log_dir_changed(self.log_dir)

    @staticmethod
    def _geometry_is_at_top_left(geometry: str) -> bool:
        match = _GEOMETRY_PATTERN.match(geometry)
        if match is None:
            return True
        return int(match.group("x")) == 0 and int(match.group("y")) == 0

    def _ensure_tab(self, vlan: str, port: str = "") -> None:
        self._scope.check()
        normalized = vlan.lower()
        resolved_port = (port or "").strip().upper() or vlan_to_serial_port(normalized)
        if normalized in self.tabs:
            item = self.tabs[normalized]
            if item["port"] != resolved_port and item["session"] is None:
                item["port"] = resolved_port
                item["status"].set(f"{resolved_port} 未打开")
                self.notebook.tab(item["frame"], text=f"{normalized} / {resolved_port}")
            return
        frame = Frame(self.notebook)
        scope = TkScope()
        status = scope.variable(StringVar, frame, value=f"{resolved_port} 未打开")
        Label(frame, textvariable=status, anchor="w").pack(fill="x", padx=8, pady=5)
        output = Text(frame, wrap="word", state="disabled")
        output.pack(fill="both", expand=True, padx=8, pady=5)
        bottom = Frame(frame)
        bottom.pack(fill="x", padx=8, pady=(0, 8))
        command = ttk.Entry(bottom)
        command.pack(side="left", fill="x", expand=True)
        # 命令输入框按 Enter 等价于点击「发送」按钮；
        # send() 内部会自动处理空字符串、危险命令二次确认和升级中锁定的拦截。
        def _on_command_return_inner(event, _vlan=normalized):
            # event 在标准 Tk 回调中是 Event 对象，仅作为合法签名占位；
            # 通过 _ = event 让静态检查器接受该形参并不再持续提示。
            _ = event
            self._on_command_return(_vlan)
            return "break"
        command.bind("<Return>", _on_command_return_inner)
        ttk.Button(bottom, text="发送", command=lambda v=normalized: self.send(v)).pack(side="left", padx=(6, 0))
        ttk.Button(bottom, text="回车", command=lambda v=normalized: self.send(v, force_enter=True)).pack(side="left", padx=(6, 0))
        ttk.Button(bottom, text="清屏", command=lambda o=output: self.clear(o)).pack(side="left", padx=(6, 0))
        self.tabs[normalized] = {"scope": scope, "port": resolved_port, "frame": frame, "status": status, "output": output, "command": command, "owner": None, "session": None, "subscriber": None}
        self.notebook.add(frame, text=f"{normalized} / {resolved_port}")

    def open_monitor(self, vlan: str, *, raise_errors: bool = False) -> bool:
        self._scope.check()
        item = self.tabs[vlan]
        if self._closing or self.master.__dict__.get('_app_closing', False) or item.get('close_ticket') is not None:
            return False
        if item["session"] is not None:
            return True
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            owner = f"terminal:{id(self)}:{vlan}:{item['port']}"
            path = build_serial_log_path(self.log_dir, vlan, item["port"])
            session = self.manager.acquire_monitor(owner, SerialSettings(item["port"]), path)
            subscriber = self._make_subscriber(vlan, item)
            session.subscribe(subscriber)
            item.update(owner=owner, session=session, subscriber=subscriber)
            item["status"].set(f"{item['port']} 监控中，日志：{path}")
            self.last_open_errors.pop(item["port"].upper(), None)
            return True
        except queue.Full as exc:
            self.last_open_errors[item["port"].upper()] = "串口事件队列已满"
            if raise_errors:
                raise RuntimeError("串口事件队列已满") from exc
            return False
        except Exception as exc:
            self.last_open_errors[item["port"].upper()] = str(exc)
            if raise_errors:
                raise
            messagebox.showerror("打开串口失败", str(exc), parent=self.window)
            return False

    def open_all(self) -> tuple[str, ...]:
        """打开当前窗口中的全部串口，返回未能打开的 VLAN。"""
        failed = []
        for vlan in tuple(self.tabs):
            if not self.open_monitor(vlan):
                failed.append(vlan)
        return tuple(failed)

    def attach_upgrade(self, vlan: str, session, log_path: Path, port: str = "") -> None:
        self._scope.check()
        if self.master.__dict__.get('_app_closing', False):
            return
        opened_by_upgrade = self.window is None or not self.window.winfo_exists()
        if self.window is None or not self.window.winfo_exists():
            self.show([(vlan, port)])
        if opened_by_upgrade and self._upgrade_batch_active:
            self._auto_opened_for_upgrade = True
        self._ensure_tab(vlan, port)
        item = self.tabs[vlan.lower()]
        if item["subscriber"] is None:
            subscriber = self._make_subscriber(vlan.lower(), item)
            session.subscribe(subscriber)
            item.update(session=session, subscriber=subscriber)
        item["status"].set(f"{item['port']} 正在自动升级，手动发送已锁定，日志：{log_path}")

    def _make_subscriber(self, vlan: str, item: dict):
        # Each subscription has its own identity, even after stopping/reopening
        # the same VLAN. Reader callbacks already in flight cannot revive it.
        delivery = SerialDelivery(vlan, self.events, getattr(self, 'diagnostic_observer', None))
        item['event_token'] = delivery
        return delivery

    @staticmethod
    def _invalidate(item):
        subscriber = item.get('subscriber')
        if isinstance(subscriber, SerialDelivery):
            subscriber.invalidate()
        item['event_token'] = None

    def _defer(self, key, action):
        if key in self._deferred or self.window is None:
            return
        def invoke():
            self._deferred.pop(key, None)
            if self.window is not None:
                action()
        self._deferred[key] = self.window.after(100, invoke)

    def _on_tab_close(self, frame: str) -> None:
        for vlan, item in tuple(self.tabs.items()):
            if str(item["frame"]) == frame:
                self.close_tab(vlan)
                return

    def close_tab(self, vlan: str) -> bool:
        """Release only this monitor; upgrade controllers must keep their tab."""
        item = self.tabs.get(vlan.lower())
        if item is None:
            return False
        vlan = vlan.lower()
        self._scope.check()
        if item.get('close_ticket') is not None:
            item['close_remove'] = True
            return True
        target = f"{vlan} / {item['port']}"
        self._log_close(f"请求关闭 {target}")
        try:
            if not self.manager.manual_writable(item["port"]):
                cancel_debug = getattr(self, "ai_debug_cancel", None)
                if cancel_debug is not None and cancel_debug(item["port"]):
                    self._log_close(f"取消 {target} 的AI Debug，等待清理后关闭")
                    self._defer(vlan, lambda: self.close_tab(vlan) if self.tabs.get(vlan) is item else None)
                    return False
                self._log_close(f"跳过关闭 {target}：当前串口正在自动升级")
                messagebox.showwarning(
                    "串口被占用", "当前串口正在自动升级，升级结束后可关闭", parent=self.window,
                )
                return False
            session, subscriber = item["session"], item["subscriber"]
            self._invalidate(item)
            if session is not None and subscriber is not None:
                session.unsubscribe(subscriber)
            try:
                if item["owner"]:
                    ticket = self.manager.release(item["owner"], item["port"], wait=False)
                    item['close_ticket'] = ticket
                    item['close_remove'] = True
            except Exception:
                if session is not None and subscriber is not None:
                    replacement = self._make_subscriber(vlan, item)
                    item['subscriber'] = replacement
                    session.subscribe(replacement)
                raise
            item.update(owner=None, session=None, subscriber=None, event_token=None)
            ticket = item.get('close_ticket')
            if ticket is None or ticket.done.is_set():
                if ticket is not None and ticket.error:
                    raise RuntimeError(ticket.error)
                self._remove_tab(vlan, item)
            else:
                item['status'].set(f"{item['port']} 正在关闭并保存日志")
        except Exception as exc:
            self._log_close(f"关闭失败 {target}：{exc}")
            messagebox.showerror("关闭串口失败", f"{target}\n{exc}", parent=self.window)
            return False
        return True

    def _remove_tab(self, vlan, item):
        self.notebook.forget(item['frame'])
        self.tabs.pop(vlan, None)
        for mapping in (self._pending_chunks, self._pending_char_counts, self._pending_dropped_chars):
            mapping.pop(vlan, None)
        item['frame'].destroy()
        item['scope'].release()
        item['status'] = None
        self._log_close(f"已关闭 {vlan} / {item['port']} 的监控及标签，已保存日志保留")

    def _process_closes(self):
        for vlan, item in tuple(self.tabs.items()):
            ticket = item.get('close_ticket')
            if ticket is None or not ticket.done.is_set():
                continue
            item.pop('close_ticket', None)
            if ticket.error:
                self._closing = False
                item['status'].set(f"{item['port']} 关闭失败：{ticket.error}")
                self._log_close(f"关闭失败 {vlan} / {item['port']}：{ticket.error}")
            elif item.pop('close_remove', False):
                self._remove_tab(vlan, item)
            else:
                item['status'].set(f"{item['port']} 已停止")
        if self._closing and not self.tabs:
            self._finish_close()

    def _log_close(self, message: str) -> None:
        if self._logger is not None:
            self._logger(f"[串口日志] {message}")

    def _on_command_return(self, vlan: str) -> str:
        """命令行输入框按 Enter 时的入口，等价于「发送」按钮。

        返回 "break" 用来阻止 Tk 默认 Enter 行为（例如激活焦点按钮），
        确保自动升级锁定提示、危险命令二次确认等 send() 逻辑都被执行。
        """
        self.send(vlan)
        return "break"

    def send(self, vlan: str, force_enter: bool = False) -> None:
        self._scope.check()
        item = self.tabs[vlan]
        if item["session"] is None:
            self.open_monitor(vlan)
        session = item["session"]
        if session is None:
            return
        if not self.manager.manual_writable(item["port"]):
            cancel_debug = getattr(self, "ai_debug_cancel", None)
            owner = self.manager.control_owner(item["port"]) if cancel_debug is not None else ""
            if owner.startswith("ai-debug:"):
                messagebox.showwarning("串口被占用", "AI Debug正在使用当前串口，结束后恢复手动发送。", parent=self.window)
                return
            messagebox.showwarning("串口被占用", "当前通道正在自动升级，只允许查看串口输出。", parent=self.window)
            return
        value = item["command"].get() if not force_enter else ""
        lowered = value.lower()
        if any(token in lowered for token in ("reboot", "reset", "firstboot", "tftp", "upgrade")):
            if not messagebox.askyesno("确认危险命令", f"将向 {item['port']} 发送：{value or '回车'}\n\n是否继续？", parent=self.window):
                return
        try:
            session.send_line(value)
            item["command"].delete(0, END)
        except Exception as exc:
            messagebox.showerror("发送失败", str(exc), parent=self.window)

    @staticmethod
    def clear(output: Text) -> None:
        output.configure(state="normal")
        output.delete("1.0", END)
        output.configure(state="disabled")

    def stop_all(self) -> None:
        self._scope.check()
        for item in tuple(self.tabs.values()):
            if item.get('close_ticket') is not None:
                continue
            cancel_debug = getattr(self, "ai_debug_cancel", None)
            if cancel_debug is not None:
                cancel_debug(item["port"])
            if item["subscriber"] is not None and item["session"] is not None:
                self._invalidate(item)
                item["session"].unsubscribe(item["subscriber"])
            if item["owner"]:
                item['close_ticket'] = self.manager.release(item["owner"], item["port"], wait=False)
            item.update(owner=None, session=None, subscriber=None, event_token=None)
            ticket = item.get('close_ticket')
            state = '正在停止并保存日志' if ticket is not None and not ticket.done.is_set() else '已停止'
            item['status'].set(f"{item['port']} {state}")

    def _poll(self, scope=None) -> None:
        self._scope.check()
        scope = scope or self._scope
        if scope is not self._scope or scope.closed:
            return
        self._after_id = None
        self._process_closes()
        if scope is not self._scope or scope.closed:
            return
        if self.events.dropped != self._reported_drops:
            self._reported_drops = self.events.dropped
            self._log_close(f"界面事件繁忙，累计合并/跳过 {self._reported_drops} 条显示事件，原始日志独立落盘")
        processed = 0
        deadline = time.monotonic() + _RENDER_TIME_BUDGET_SECONDS
        while processed < _RENDER_EVENTS_PER_TICK and time.monotonic() < deadline:
            try:
                vlan, event, token = self.events.get_nowait()
            except queue.Empty:
                break
            processed += 1
            if vlan in self.tabs and self.tabs[vlan].get("event_token") is token:
                self._append_pending_chunk(vlan, event.text)

        # 仅刷新当前可见 Tab；其它 Tab 的输出先合并缓冲，切换过去后再显示。
        # 这避免多路高频日志同时触发 Text 重绘和滚动，占满 Tk 主线程。
        active_vlan = self._active_vlan()
        render_vlans = tuple(self._pending_chunks) if active_vlan is None else (active_vlan,)
        for vlan in render_vlans:
            chunks = self._pending_chunks.get(vlan)
            if not chunks or vlan not in self.tabs:
                continue
            output = self.tabs[vlan]["output"]
            text = "".join(chunks)
            dropped_chars = self._pending_dropped_chars.pop(vlan, 0)
            if dropped_chars:
                text = f"[界面显示已合并 {dropped_chars} 个字符，原始日志已完整写入文件]\n{text}"
            self._pending_chunks.pop(vlan, None)
            self._pending_char_counts.pop(vlan, None)
            output.configure(state="normal")
            output.insert(END, text)
            self._trim_display(output)
            output.see(END)
            output.configure(state="disabled")

        if scope is self._scope and not scope.closed and self.window is not None and self.window.winfo_exists():
            active_has_pending = active_vlan is not None and bool(self._pending_chunks.get(active_vlan))
            delay = _RENDER_ACTIVE_DELAY_MS if not self.events.empty() or active_has_pending else _RENDER_IDLE_DELAY_MS
            self._after_id = self.window.after(delay, lambda: self._poll(scope))

    def _on_tab_changed(self, _event=None) -> None:
        """切换到积压日志的 Tab 时立即安排一次渲染，不等待空闲轮询。"""
        self._scope.check()
        if self.window is None or not self.window.winfo_exists():
            return
        if self._after_id is not None:
            try:
                self.window.after_cancel(self._after_id)
            except Exception:
                pass
        scope = self._scope
        self._after_id = self.window.after(0, lambda: self._poll(scope))

    def _active_vlan(self) -> str | None:
        if self.notebook is None:
            return None
        try:
            selected = self.notebook.select()
        except Exception:
            return None
        for vlan, item in self.tabs.items():
            if str(item.get("frame")) == selected:
                return vlan
        return None

    def _append_pending_chunk(self, vlan: str, text: str) -> None:
        """为屏幕渲染保留有限的最新输出；完整原始日志由串口线程写入文件。"""
        if not text:
            return
        chunks = self._pending_chunks.setdefault(vlan, deque())
        current = self._pending_char_counts.get(vlan, 0)
        overflow = current + len(text) - _PENDING_CHARS_PER_VLAN
        while overflow > 0 and chunks:
            removed = chunks.popleft()
            current -= len(removed)
            overflow -= len(removed)
            self._pending_dropped_chars[vlan] = self._pending_dropped_chars.get(vlan, 0) + len(removed)
        if overflow > 0:
            text = text[overflow:]
            self._pending_dropped_chars[vlan] = self._pending_dropped_chars.get(vlan, 0) + overflow
        if text:
            chunks.append(text)
            current += len(text)
        self._pending_char_counts[vlan] = current

    @staticmethod
    def _trim_display(output: Text) -> None:
        """限制 Text 的可见行数，避免长时间监控后重绘成本持续增长。"""
        try:
            last_line = int(output.index("end-1c").split(".", 1)[0])
        except Exception:
            return
        lines_to_remove = max(0, last_line - _DISPLAY_MAX_LINES)
        if lines_to_remove:
            output.delete("1.0", f"{lines_to_remove + 1}.0")

    def close(self) -> None:
        self._scope.check()
        if self.window is None:
            return
        if self._closing:
            self._process_closes()
            return
        cancel_debug = getattr(self, "ai_debug_cancel", None)
        if cancel_debug is not None:
            pending = any([cancel_debug(item["port"]) for item in self.tabs.values()])
            if pending and self.window is not None:
                self._defer('window', self.close)
                return
        if any(not self.manager.manual_writable(item['port']) for item in self.tabs.values()):
            messagebox.showwarning('串口被占用', '当前串口正在自动升级，升级结束后可关闭', parent=self.window)
            return
        self._closing = True
        for identifier in self._deferred.values():
            self.window.after_cancel(identifier)
        self._deferred.clear()
        for vlan in tuple(self.tabs):
            if not self.close_tab(vlan):
                self._closing = False
        self._process_closes()

    def _finish_close(self):
        if self._after_id and self.window is not None:
            self.window.after_cancel(self._after_id)
        self._after_id = None
        if self.window is not None:
            self._save_state()
            self.notebook.unbind('<<NotebookTabChanged>>')
            self.notebook._on_close = None
            self.window.destroy()
        self.window = None
        self.notebook = None
        self.tabs = {}
        self._pending_chunks.clear()
        self._pending_char_counts.clear()
        self._pending_dropped_chars.clear()
        self.log_dir_var = None
        self._scope.release()
        self.events.clear()
        self._closing = False
        self._auto_opened_for_upgrade = False
        self._upgrade_batch_active = False

    def _load_state(self) -> dict:
        """读取持久化文件,失败/缺失时返回空字典"""
        try:
            if not self.state_file.exists():
                return {}
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def _save_state(self) -> None:
        """把当前窗口几何和日志目录一起写入本地文件"""
        payload: dict = {"log_dir": str(self.log_dir)}
        if self.window is not None and self.window.winfo_exists():
            geometry = self.window.geometry()
            if _GEOMETRY_PATTERN.match(geometry):
                payload["geometry"] = geometry
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            messagebox.showerror(
                "保存串口终端设置失败",
                f"无法保存窗口状态和日志目录设置：\n{self.state_file}\n\n{exc}",
                parent=self.window or self.master,
            )

    def _load_geometry(self) -> str | None:
        """读取上次保存的窗口尺寸和位置,验证仍在当前屏幕范围内,防止开屏外"""
        geometry = self._load_state().get("geometry")
        if not isinstance(geometry, str):
            return None
        match = _GEOMETRY_PATTERN.match(geometry)
        if match is None:
            return None
        width = int(match.group("w"))
        height = int(match.group("h"))
        # 尺寸低于下限时视为无效,避免恢复出比 minsize 还小的窗口
        if width < _MIN_WIDTH or height < _MIN_HEIGHT:
            return None
        x = int(match.group("x"))
        y = int(match.group("y"))
        screen_w = self.master.winfo_screenwidth()
        screen_h = self.master.winfo_screenheight()
        visible_w = max(0, min(x + width, screen_w) - max(x, 0))
        visible_h = max(0, min(y + height, screen_h) - max(y, 0))
        # 至少要有一部分窗口落在屏幕内,否则视为无效
        if visible_w < _MIN_VISIBLE or visible_h < _MIN_VISIBLE:
            return None
        return geometry

    def get_log_directory(self) -> Path:
        """只读获取当前目录；窗口首次打开前读取有效历史配置，不创建目录或弹窗。"""
        if self._log_dir_initialized:
            return self.log_dir
        return self._saved_log_dir() or DEFAULT_LOG_DIR

    def _saved_log_dir(self) -> Path | None:
        """窗口恢复和全流程摘要共用的历史目录校验。"""
        saved = self._load_state().get("log_dir")
        if isinstance(saved, str) and saved:
            try:
                path = Path(saved)
                if path.exists() and path.is_dir():
                    return path
            except (OSError, ValueError):
                pass
        return None

    def _restore_log_dir(self) -> Path:
        """从 state_file 恢复日志目录;无效或缺失时回退到默认 D:\\Serial_Log"""
        saved = self._saved_log_dir()
        if saved is not None:
            return saved
        # 默认路径不存在时主动创建,首次运行也能直接用
        try:
            DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(
                "日志目录不可用",
                f"无法创建默认串口日志目录：\n{DEFAULT_LOG_DIR}\n\n{exc}\n\n请通过“浏览…”选择可写目录。",
                parent=self.master,
            )
        return DEFAULT_LOG_DIR

    def _choose_log_dir(self) -> None:
        """弹出目录选择框,选择后切换日志目录并立即持久化"""
        if self.window is None:
            return
        initial = str(self.log_dir) if self.log_dir.exists() else str(DEFAULT_LOG_DIR)
        try:
            chosen = filedialog.askdirectory(
                title="选择串口日志保存目录",
                initialdir=initial,
                parent=self.window,
                mustexist=True,
            )
        except Exception as exc:
            messagebox.showerror("选择目录失败", str(exc), parent=self.window)
            return
        if not chosen:
            return  # 用户取消
        new_path = Path(chosen)
        try:
            new_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("无法创建目录", f"{new_path}\n{exc}", parent=self.window)
            return
        self.log_dir = new_path
        self._log_dir_initialized = True
        if self.log_dir_var is not None:
            self.log_dir_var.set(str(new_path))
        self._save_state()
        if self._on_log_dir_changed is not None:
            self._on_log_dir_changed(self.log_dir)

    def _open_log_dir(self) -> None:
        """在系统文件管理器中打开当前日志目录"""
        try:
            if not self.log_dir.exists():
                self.log_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.log_dir))  # Windows 专用,非阻塞
        except OSError as exc:
            messagebox.showerror("打开目录失败", str(exc), parent=self.window)
