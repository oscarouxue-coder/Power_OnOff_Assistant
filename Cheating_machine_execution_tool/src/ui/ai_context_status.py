"""固定上下文状态区；仅渲染service的快照，不读取草稿或重绘聊天。"""
import tkinter as tk
from tkinter import ttk


class AiContextStatus(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.capacity_text = tk.StringVar(self)
        self.usage_text = tk.StringVar(self, value="待下一次请求更新")
        self.capacity_label = ttk.Label(self, textvariable=self.capacity_text, anchor="w", wraplength=880)
        self.capacity_label.pack(fill="x")
        self.usage_label = ttk.Label(self, textvariable=self.usage_text, anchor="w", wraplength=880)
        self.usage_label.pack(fill="x", pady=(2, 0))
        self.progress = ttk.Progressbar(self, maximum=100, mode="determinate")
        self.progress.pack(fill="x", pady=(3, 0))
        self.bind("<Configure>", self._resize)
        self._view = None

    def _resize(self, event):
        width = max(100, event.width - 8)
        self.capacity_label.configure(wraplength=width)
        self.usage_label.configure(wraplength=width)

    def show(self, status=None):
        selected = status is not None
        status = status or {}
        capacity = status.get("capacity", 0)
        reserve = status.get("max_output", 0)
        title = (f"上下文容量：{capacity:,} Token；来源：{status.get('source', '')}"
                 if capacity else "上下文容量未知：最近50轮 / 100000字符")
        if not selected:
            title = "上下文容量：选择会话后显示"
        if reserve:
            title += f"；输出预留 {reserve:,} Token"
            if capacity:
                title += "，另留5%余量（不计入已用）"
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
                text = f"预计输入 {snapshot['input_tokens']:,} Token（估算）"
            else:
                source = "接口返回" if snapshot.get("source") == "api" else "估算"
                text = (f"最近请求已用 {total:,} Token（{source}）："
                        f"输入 {snapshot['input_tokens']:,}，输出 {snapshot['output_tokens']:,}")
            if capacity:
                ratio = total / capacity * 100
                text += f"；占用 {ratio:.2f}%"
            if snapshot.get("updated"):
                text += "；" + snapshot["updated"].replace("T", " ")[:19]
        if suffix:
            text += "；" + suffix
        view = (title, text, min(100, max(0, ratio)))
        if view != self._view:
            self.capacity_text.set(title)
            self.usage_text.set(text)
            self.progress.configure(value=view[2])
            self._view = view
