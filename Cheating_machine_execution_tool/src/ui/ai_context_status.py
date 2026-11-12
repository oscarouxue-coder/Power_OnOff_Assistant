"""固定上下文状态区；仅渲染service的快照，不读取草稿或重绘聊天。"""
import tkinter as tk
from tkinter import ttk


class AiContextStatus(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.status_text = tk.StringVar(self, value="待下一次请求更新")
        self.status_label = ttk.Label(self, textvariable=self.status_text, anchor="w", wraplength=880)
        self.status_label.pack(fill="x")
        self.progress = ttk.Progressbar(self, maximum=100, mode="determinate")
        self.progress.pack(fill="x", pady=(3, 0))
        self.bind("<Configure>", self._resize)
        self._view = None

    def _resize(self, event):
        width = max(100, event.width - 8)
        self.status_label.configure(wraplength=width)

    def show(self, status=None):
        selected = status is not None
        status = status or {}
        capacity = status.get("capacity", 0)
        title = f"上下文容量：{capacity:,} Token" if capacity else "上下文容量：未知"
        if not selected:
            title = "上下文容量：选择会话后显示"
        snapshot = status.get("snapshot") or {}
        state = snapshot.get("state")
        suffix = {"requesting": "请求中", "failed": "本轮失败，保留已有用量", "cancelled": "本轮已取消，保留已有用量"}.get(state, "")
        ratio = 0
        if status.get("stale"):
            text = "用量记录已过期，待下一次请求更新"
        elif "input_tokens" not in snapshot:
            text = "待下一次请求更新"
        else:
            total = snapshot["total_tokens"]
            if snapshot.get("basis") == "input":
                text = f"预计输入：约 {snapshot['input_tokens']:,} Token"
            else:
                approximate = "" if snapshot.get("source") == "api" else "约 "
                text = f"当前上下文用量：{approximate}{total:,}"
            if capacity:
                ratio = total / capacity * 100
                text += f"（{ratio:.2f}%）"
        if suffix:
            text += "；" + suffix
        view = (f"{title} ｜ {text}", min(100, max(0, ratio)))
        if view != self._view:
            self.status_text.set(view[0])
            self.progress.configure(value=view[1])
            self._view = view
