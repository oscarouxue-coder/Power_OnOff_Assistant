"""单行会话状态显示；不读取会话或执行业务。"""
from datetime import datetime
import tkinter as tk
from tkinter import ttk
from tkinter.font import Font


def _fit_text(text, measure, width):
    if measure(text) <= width:
        return text
    if measure("…") > width:
        return ""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if measure(text[:middle] + "…") <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low] + "…"


class AiChatStatus(ttk.Frame):
    def __init__(self, parent, *, background, font_family):
        super().__init__(parent)
        self.background = background
        self.body_font = Font(root=self, family=font_family, size=11, weight="bold")
        self.time_font = Font(root=self, family=font_family, size=9)
        self.output = tk.Text(self, state="disabled", wrap="none", height=1, width=1,
                              font=self.body_font, background=background, borderwidth=0,
                              highlightthickness=0, padx=6, pady=2, exportselection=False,
                              selectbackground="#cbdff5", selectforeground="#17202a")
        self.output.pack(fill="x")
        self.output.tag_configure("status_time", font=self.time_font)
        self.output.bind("<Configure>", self._render_line)
        self.full_text = ""
        self._view = None
        self._line_view = None
        self.show()

    def show(self, selected="", message=None, created=""):
        text = message["text"] if message else ("暂无状态" if selected else "请选择会话")
        error = bool(message and message.get("kind") == "error")
        view = (selected, text, created, error)
        if view == self._view:
            return
        self._view = view
        self.full_text = "状态" + (" · " + created if created else "") + "\n" + text
        clock = created
        try:
            clock = datetime.strptime(created, "%Y-%m-%d %H:%M:%S").strftime("%H:%M:%S")
        except ValueError:
            pass  # 旧时间不猜测，保留原始时间文本。
        self._prefix = "状态" + (" · " + clock if clock else "") + " ｜ "
        self._body = " ".join(text.splitlines()).replace("\t", " ")
        self._color = "#b42318" if error else "#174b80"
        self.output.configure(foreground=self._color)
        self._render_line()

    def _render_line(self, _event=None):
        width = max(0, self.output.winfo_width() - 12)
        prefix_width = self.time_font.measure(self._prefix)
        if prefix_width > width:
            prefix, body = _fit_text(self._prefix, self.time_font.measure, width), ""
        else:
            prefix, body = self._prefix, _fit_text(self._body, self.body_font.measure, width - prefix_width)
        view = (prefix, body)
        if view == self._line_view:
            return
        self._line_view = view
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("end", prefix, "status_time")
        self.output.insert("end", body)
        self.output.configure(state="disabled")
        self.output.xview_moveto(0)
