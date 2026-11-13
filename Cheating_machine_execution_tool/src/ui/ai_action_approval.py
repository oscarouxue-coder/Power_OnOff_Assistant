"""具体操作确认窗口；UI不判断风险、不执行命令。"""
import json
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

from src.ui.module_theme import apply_module_theme


class AiActionApproval(ttk.Frame):
    def __init__(self, parent, service, background="#eef2f5"):
        super().__init__(parent)
        self.service, self.background = service, background
        self.identifier, self.action = "", None
        self.window = None
        self.window_action = None
        self.button = ttk.Button(self, text="查看待确认操作", command=self.open, state="disabled")
        self.button.pack(side="left")

    def show(self, identifier=""):
        if self.identifier != identifier:
            self.close()
        self.identifier = identifier
        try:
            self.action = self.service.actions.pending(identifier) if identifier else None
        except ValueError:
            self.action = None
        self.button.configure(state="normal" if self.action else "disabled")
        if self.window is not None and self.window.winfo_exists():
            same = self.action is not None and self.window_action["id"] == self.action["id"]
            for button in (self.approve_button, self.reject_button):
                button.configure(state="normal" if same else "disabled")
            if not same:
                self.window.title("操作已结束或授权已失效")

    def open(self):
        self.show(self.identifier)
        if not self.action:
            return
        self.close()
        action = self.action
        self.window_action = action
        window = self.window = tk.Toplevel(self)
        window.title("确认AI具体操作")
        window.geometry("850x580")
        window.minsize(680, 420)
        window.transient(self.winfo_toplevel())
        window.protocol("WM_DELETE_WINDOW", self.close)
        target = action["target"]
        ttk.Label(window, text=f"通道{target['channel']} | {target['vlan']} | {target['port']} | "
                  f"{target['bind_ip']} → {target['host']}:{target['telnet_port']}\n"
                  f"操作：{action['name']} | 编号：{action['id'][:8]}\n"
                  f"原因：{action['assessment']['reason']}", wraplength=800).pack(fill="x", padx=12, pady=10)
        controls = ttk.Frame(window)
        controls.pack(side="bottom", fill="x", padx=12, pady=10)
        self.approve_button = ttk.Button(controls, text="批准本次操作", command=lambda: self.decide(True))
        self.approve_button.pack(side="left")
        self.reject_button = ttk.Button(controls, text="拒绝", command=lambda: self.decide(False))
        self.reject_button.pack(side="left", padx=8)
        ttk.Label(controls, text="关闭窗口不代表批准；停止本轮会取消待执行操作。", wraplength=430).pack(side="left", padx=8)
        self.detail = ScrolledText(window, wrap="word", font=("Microsoft YaHei UI", 10), padx=8, pady=8)
        self.detail.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        self.detail.insert("end", "实际命令 / 文件内容：\n")
        for name, value in action["params"].items():
            self.detail.insert("end", name + ":\n" + str(value) + "\n\n")
        if action.get("preview"):
            self.detail.insert("end", "\n\n文件差异（可能截断，以完整拟写入内容及哈希为准）：\n" +
                               json.dumps(action["preview"], ensure_ascii=False, indent=2))
        self.detail.insert("end", "\n\n绑定指纹：" + action["fingerprint"])
        self.detail.configure(state="disabled")
        apply_module_theme(window, self.background)
        # 非模态：操作员仍可切换会话或停止；默认焦点放在拒绝按钮。
        self.reject_button.focus_set()

    def decide(self, approved):
        action = self.window_action
        if not action:
            return
        try:
            self.service.actions.decide(action["session_id"], action["id"], action["fingerprint"], approved)
            self.close()
            self.show(self.identifier)
        except Exception as exc:
            messagebox.showerror("操作确认未完成", str(exc), parent=self.window or self)
            self.show(self.identifier)

    def close(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.destroy()
        self.window = None
        self.window_action = None
