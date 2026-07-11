from __future__ import annotations

import json
import os
import queue
import re
from pathlib import Path
from tkinter import END, Frame, Label, StringVar, Text, Toplevel, filedialog, messagebox, ttk

from src.config import DEFAULT_LOG_DIR
from src.core import SerialSessionManager, vlan_to_serial_port
from src.models import SerialSettings


_DEFAULT_GEOMETRY = "1000x650"
_MIN_WIDTH = 1000
_MIN_HEIGHT = 650
_GEOMETRY_PATTERN = re.compile(r"^(?P<w>\d+)x(?P<h>\d+)(?P<x>[+-]\d+)(?P<y>[+-]\d+)$")
_MIN_VISIBLE = 120  # 窗口在屏幕内至少要可见的像素,避免开屏外


class SerialTerminalWindow:
    def __init__(
        self,
        master,
        manager: SerialSessionManager,
        log_dir: Path,
        state_file: Path | None = None,
    ) -> None:
        self.master = master
        self.manager = manager
        self.log_dir = log_dir
        # 默认存到用户目录下,跨平台、安全且不会被误删
        self.state_file = state_file or (Path.home() / ".aouxue_serial_terminal.json")
        self.window = None
        self.notebook = None
        self.tabs = {}
        self.events: queue.Queue = queue.Queue(maxsize=2000)
        self._after_id = None

    def show(self, vlans: list[str]) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            for vlan in vlans:
                self._ensure_tab(vlan)
            return
        # 优先恢复上次保存的日志目录,失效时回退到默认 D:\Serial_Log
        self.log_dir = self._restore_log_dir()
        self.window = Toplevel(self.master)
        self.window.title("串口日志记录")
        # 优先恢复上次窗口位置+大小,无效时回退到默认尺寸
        self.window.geometry(self._load_geometry() or _DEFAULT_GEOMETRY)
        # 禁止用户拖拽到比默认更小,避免内容被挤压变形
        self.window.minsize(_MIN_WIDTH, _MIN_HEIGHT)
        toolbar = Frame(self.window)
        toolbar.pack(fill="x", padx=12, pady=8)
        ttk.Button(toolbar, text="打开全部", command=lambda: [self.open_monitor(v) for v in list(self.tabs)]).pack(side="left")
        ttk.Button(toolbar, text="停止全部", command=self.stop_all).pack(side="left", padx=8)
        # 右侧:日志目录选择(只读展示 + 浏览/打开文件夹)
        self.log_dir_var = StringVar(value=str(self.log_dir))
        path_bar = Frame(toolbar)
        path_bar.pack(side="right")
        ttk.Label(path_bar, text="日志目录:").pack(side="left")
        ttk.Entry(path_bar, textvariable=self.log_dir_var, width=50, state="readonly").pack(side="left", padx=(4, 6))
        ttk.Button(path_bar, text="浏览…", command=self._choose_log_dir).pack(side="left", padx=(0, 4))
        ttk.Button(path_bar, text="打开文件夹", command=self._open_log_dir).pack(side="left")
        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        for vlan in vlans:
            self._ensure_tab(vlan)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._poll()

    def _ensure_tab(self, vlan: str) -> None:
        normalized = vlan.lower()
        if normalized in self.tabs:
            return
        port = vlan_to_serial_port(normalized)
        frame = Frame(self.notebook)
        status = StringVar(value=f"{port} 未打开")
        Label(frame, textvariable=status, anchor="w").pack(fill="x", padx=8, pady=5)
        output = Text(frame, wrap="word", state="disabled")
        output.pack(fill="both", expand=True, padx=8, pady=5)
        bottom = Frame(frame)
        bottom.pack(fill="x", padx=8, pady=(0, 8))
        command = ttk.Entry(bottom)
        command.pack(side="left", fill="x", expand=True)
        ttk.Button(bottom, text="发送", command=lambda v=normalized: self.send(v)).pack(side="left", padx=(6, 0))
        ttk.Button(bottom, text="回车", command=lambda v=normalized: self.send(v, force_enter=True)).pack(side="left", padx=(6, 0))
        ttk.Button(bottom, text="清屏", command=lambda o=output: self.clear(o)).pack(side="left", padx=(6, 0))
        self.tabs[normalized] = {"port": port, "frame": frame, "status": status, "output": output, "command": command, "owner": None, "session": None, "subscriber": None}
        self.notebook.add(frame, text=f"{normalized} / {port}")

    def open_monitor(self, vlan: str) -> None:
        item = self.tabs[vlan]
        if item["session"] is not None:
            return
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            owner = f"terminal:{id(self)}:{item['port']}"
            path = self.log_dir / f"{vlan}_{item['port']}.log"
            session = self.manager.acquire_monitor(owner, SerialSettings(item["port"]), path)
            subscriber = lambda event, v=vlan: self.events.put_nowait((v, event))
            session.subscribe(subscriber)
            item.update(owner=owner, session=session, subscriber=subscriber)
            item["status"].set(f"{item['port']} 监控中，日志：{path}")
        except queue.Full:
            pass
        except Exception as exc:
            messagebox.showerror("打开串口失败", str(exc), parent=self.window)

    def attach_upgrade(self, vlan: str, session, log_path: Path) -> None:
        if self.window is None or not self.window.winfo_exists():
            self.show([vlan])
        self._ensure_tab(vlan)
        item = self.tabs[vlan.lower()]
        if item["subscriber"] is None:
            subscriber = lambda event, v=vlan.lower(): self.events.put_nowait((v, event))
            session.subscribe(subscriber)
            item.update(session=session, subscriber=subscriber)
        item["status"].set(f"{item['port']} 正在自动升级，手动发送已锁定，日志：{log_path}")

    def send(self, vlan: str, force_enter: bool = False) -> None:
        item = self.tabs[vlan]
        if item["session"] is None:
            self.open_monitor(vlan)
        session = item["session"]
        if session is None:
            return
        if not self.manager.manual_writable(item["port"]):
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
        for item in self.tabs.values():
            if item["subscriber"] is not None and item["session"] is not None:
                item["session"].unsubscribe(item["subscriber"])
            if item["owner"]:
                self.manager.release(item["owner"], item["port"])
            item.update(owner=None, session=None, subscriber=None)
            item["status"].set(f"{item['port']} 已停止")

    def _poll(self) -> None:
        try:
            for _ in range(200):
                vlan, event = self.events.get_nowait()
                item = self.tabs.get(vlan)
                if item is None:
                    continue
                output = item["output"]
                output.configure(state="normal")
                output.insert(END, event.text)
                output.see(END)
                output.configure(state="disabled")
        except queue.Empty:
            pass
        if self.window is not None and self.window.winfo_exists():
            self._after_id = self.window.after(80, self._poll)

    def close(self) -> None:
        if self._after_id and self.window is not None:
            self.window.after_cancel(self._after_id)
        self.stop_all()
        if self.window is not None:
            self._save_state()
            self.window.destroy()
        self.window = None
        self.notebook = None
        self.tabs = {}
        self.log_dir_var = None

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

    def _restore_log_dir(self) -> Path:
        """从 state_file 恢复日志目录;无效或缺失时回退到默认 D:\\Serial_Log"""
        saved = self._load_state().get("log_dir")
        if isinstance(saved, str) and saved:
            try:
                path = Path(saved)
                if path.exists() and path.is_dir():
                    return path
            except (OSError, ValueError):
                pass
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
        if self.log_dir_var is not None:
            self.log_dir_var.set(str(new_path))
        self._save_state()

    def _open_log_dir(self) -> None:
        """在系统文件管理器中打开当前日志目录"""
        try:
            if not self.log_dir.exists():
                self.log_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.log_dir))  # Windows 专用,非阻塞
        except OSError as exc:
            messagebox.showerror("打开目录失败", str(exc), parent=self.window)
