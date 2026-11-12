"""单行会话状态及可复制的完整内容悬浮提示；不读取会话或执行业务。"""
from datetime import datetime
import tkinter as tk
from tkinter import ttk
from tkinter.font import Font

from src.ui.module_theme import apply_module_theme


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
        self.tooltip_font = (font_family, 10)
        self.output = tk.Text(self, state="disabled", wrap="none", height=1, width=1,
                              font=self.body_font, background=background, borderwidth=0,
                              highlightthickness=0, padx=6, pady=2, exportselection=False,
                              selectbackground="#cbdff5", selectforeground="#17202a")
        self.output.pack(fill="x")
        self.output.tag_configure("status_time", font=self.time_font)
        self.output.bind("<Configure>", self._render_line)
        self.output.bind("<Enter>", self._enter)
        self.output.bind("<Leave>", self._leave)
        self.bind("<Unmap>", self._hide_tooltip)
        self.bind("<Destroy>", self._destroyed)
        self.tooltip = None
        self.tooltip_text = None
        self.tooltip_job = None
        self.hide_job = None
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
        self._hide_tooltip()
        self._view = view
        self.full_text = "状态" + (" · " + created if created else "") + "\n" + text
        clock = created
        try:
            clock = datetime.strptime(created, "%Y-%m-%d %H:%M:%S").strftime("%H:%M:%S")
        except ValueError:
            pass  # 旧时间不猜测，完整原文仍在悬浮提示中。
        self._prefix = "状态" + (" · " + clock if clock else "") + " ｜ "
        self._body = " ".join(text.splitlines()).replace("\t", " ")
        self._color = "#b42318" if error else "#174b80"
        self._border = "#b42318" if error else "#3b82f6"
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
        self._hide_tooltip()
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("end", prefix, "status_time")
        self.output.insert("end", body)
        self.output.configure(state="disabled")
        self.output.xview_moveto(0)

    def _cancel_job(self, name):
        job = getattr(self, name)
        if job is not None:
            self.after_cancel(job)
            setattr(self, name, None)

    def _enter(self, _event=None):
        self._cancel_job("hide_job")
        if self.tooltip is None and self.tooltip_job is None:
            self.tooltip_job = self.after(400, self._show_tooltip)

    def _leave(self, _event=None):
        self._cancel_job("tooltip_job")
        self._cancel_job("hide_job")
        if self.tooltip is not None:
            # 留出鼠标从状态行移入悬浮提示的时间，允许选择/复制和滚动。
            self.hide_job = self.after(150, self._hide_if_outside)

    def _hide_if_outside(self):
        self.hide_job = None
        widget = self.winfo_containing(*self.winfo_pointerxy())
        while widget is not None:
            if widget is self or widget is self.tooltip:
                return
            widget = widget.master
        self._hide_tooltip()

    def _show_tooltip(self):
        self._cancel_job("tooltip_job")
        if not self.winfo_viewable() or self.tooltip is not None:
            return
        popup = self.tooltip = tk.Toplevel(self, takefocus=False)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.transient(self.winfo_toplevel())
        self.tooltip_text = text = tk.Text(popup, wrap="word", width=1, height=2,
                                          font=self.tooltip_font, background=self.background,
                                          foreground=self._color, borderwidth=0, padx=8, pady=6,
                                          highlightthickness=1, highlightbackground=self._border,
                                          highlightcolor=self._border, exportselection=False,
                                          selectbackground="#cbdff5", selectforeground="#17202a")
        scroll = ttk.Scrollbar(popup, orient="vertical", command=text.yview)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.configure(yscrollcommand=scroll.set)
        text.insert("1.0", self.full_text)
        text.configure(state="disabled")
        popup.bind("<Enter>", lambda _event: self._cancel_job("hide_job"))
        popup.bind("<Leave>", self._leave)
        popup.bind("<Escape>", self._hide_tooltip)
        apply_module_theme(popup, self.background)
        width = min(640, self.winfo_screenwidth() - 16)
        popup.geometry(f"{width}x{text.winfo_reqheight()}")
        popup.update_idletasks()
        lines = text.count("1.0", "end-1c", "displaylines")
        text.configure(height=min(8, max(2, (lines[0] if lines else 0) + 1)))
        popup.update_idletasks()
        height = min(popup.winfo_reqheight(), self.winfo_screenheight() - 16)
        left = self.winfo_vrootx()
        top = self.winfo_vrooty()
        x = max(left + 4, min(self.winfo_rootx(), left + self.winfo_screenwidth() - width - 4))
        y = self.winfo_rooty() + self.winfo_height() + 2
        if y + height > top + self.winfo_screenheight() - 4:
            y = self.winfo_rooty() - height - 2
        popup.geometry(f"{width}x{height}{x:+d}{max(top + 4, y):+d}")
        popup.deiconify()

    def _hide_tooltip(self, _event=None):
        self._cancel_job("tooltip_job")
        self._cancel_job("hide_job")
        if self.tooltip is not None:
            popup, self.tooltip = self.tooltip, None
            self.tooltip_text = None
            popup.destroy()

    def _destroyed(self, event):
        if event.widget is self:
            self._hide_tooltip()
