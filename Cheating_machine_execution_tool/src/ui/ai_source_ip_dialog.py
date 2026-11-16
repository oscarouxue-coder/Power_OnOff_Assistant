"""模型出口地址选择；只编辑草稿，不保存配置或发送模型请求。"""
import tkinter as tk
from tkinter import ttk

from src.core.ai_source_ip import list_source_ips, require_source_ip
from src.ui.module_theme import apply_module_theme, MODULE_BACKGROUND
from src.ui.window_paint import center_toplevel_on_parent


class SourceIpDialog:
    def __init__(self, parent, current="", emit=lambda _line: None):
        self.emit, self.result, self.current = emit, None, current
        self.window = tk.Toplevel(parent)
        self.window.withdraw()
        self.window.title("指定出口 IP")
        self.window.transient(parent)
        self.window.resizable(True, False)
        self.window.minsize(540, 150)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        body = ttk.Frame(self.window, padding=14)
        body.pack(fill="both", expand=True)
        self.choice = ttk.Combobox(body, state="readonly", width=66)
        self.choice.pack(fill="x")
        self.status = tk.StringVar(self.window)
        ttk.Label(body, textvariable=self.status, wraplength=560).pack(anchor="w", pady=8)
        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="刷新", command=self.refresh).pack(side="left")
        ttk.Button(buttons, text="取消", command=self.cancel).pack(side="right")
        ttk.Button(buttons, text="确定", command=self.accept).pack(side="right", padx=8)
        self.window.bind("<Escape>", self.cancel)
        self.window.bind("<Return>", self.accept)
        apply_module_theme(self.window, MODULE_BACKGROUND)
        self.refresh()

    def refresh(self):
        selected = self.choice.current()
        wanted = self.values[selected]["ip"] if selected >= 0 else self.current
        self.values = [dict(ip="", available=True)]
        labels = ["不指定（自动选择）"]
        try:
            self.values.extend(list_source_ips(self.emit))
            labels.extend(f"{item['name']}  |  {item['ip']}" + ("" if item["available"] else "（不可用）")
                          for item in self.values[1:])
            self.status.set("" if len(self.values) > 1 else "未发现可选的本机 IPv4；可以保留不指定。")
        except Exception as exc:
            self.status.set("枚举失败：" + type(exc).__name__ + "；可重试或选择不指定。")
        index = next((i for i, item in enumerate(self.values) if item["ip"] == wanted), None)
        if index is None:
            index = len(self.values)
            self.values.append(dict(ip=wanted, available=False))
            labels.append(wanted + "（原设置，当前不可用）")
        self.choice["values"] = labels
        self.choice.current(index)

    def accept(self, _event=None):
        item = self.values[self.choice.current()]
        try:
            if not item["available"]:
                raise ValueError("该地址当前不可用，请刷新或选择其它地址。")
            self.result = require_source_ip(item["ip"])
        except Exception as exc:
            self.status.set(str(exc))
            self.emit("[AI出口] 选择失败：" + str(exc))
            return
        self.window.destroy()

    def cancel(self, _event=None):
        self.emit("[AI出口] 已取消选择，保留原设置")
        self.window.destroy()

    def show(self):
        center_toplevel_on_parent(self.window, self.window.master)
        self.window.deiconify()
        self.window.grab_set()
        self.choice.focus_set()
        self.window.wait_window()
        return self.result
