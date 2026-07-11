from __future__ import annotations

import queue
from pathlib import Path
from tkinter import END, Frame, Label, StringVar, Text, Toplevel, messagebox, ttk

from src.core import SerialSessionManager, vlan_to_serial_port
from src.models import SerialSettings


class SerialTerminalWindow:
    def __init__(self, master, manager: SerialSessionManager, log_dir: Path) -> None:
        self.master = master
        self.manager = manager
        self.log_dir = log_dir
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
        self.window = Toplevel(self.master)
        self.window.title("串口日志记录")
        self.window.geometry("900x620")
        toolbar = Frame(self.window)
        toolbar.pack(fill="x", padx=12, pady=8)
        ttk.Button(toolbar, text="打开全部", command=lambda: [self.open_monitor(v) for v in list(self.tabs)]).pack(side="left")
        ttk.Button(toolbar, text="停止全部", command=self.stop_all).pack(side="left", padx=8)
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
            self.window.destroy()
        self.window = None
