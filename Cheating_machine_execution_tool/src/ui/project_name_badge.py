"""工具栏项目名称展示；数据由主窗口读取已保存配置后传入。"""
from __future__ import annotations

from tkinter import Frame, Label, Toplevel
from tkinter.font import Font


def fit_project_name(text: str, measure, width: int) -> str:
    """按实际字体像素宽度省略，避免长中文名称挤占工具按钮。"""
    text = " ".join(text.splitlines())
    if measure(text) <= width:
        return text
    suffix = "…"
    if measure(suffix) > width:
        return ""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if measure(text[:middle] + suffix) <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low] + suffix


class ProjectNameBadge(Frame):
    """固定宽度名称徽标及完整名称提示，不读取配置或触发业务。"""

    def __init__(self, parent, *, font_family, background, foreground):
        self.name_font = Font(root=parent, family=font_family, size=11, weight="bold")
        super().__init__(parent, background=background, width=180,
                         height=self.name_font.metrics("linespace") + 16)
        self.pack_propagate(False)
        self.full_text = "未设置"
        self.tooltip = None
        self.tooltip_job = None
        self.label = Label(self, background=background, foreground=foreground,
                           font=self.name_font, anchor="w", padx=10, pady=6)
        self.label.pack(fill="both", expand=True)
        self.label.bind("<Configure>", self._render)
        self.label.bind("<Enter>", self._schedule_tooltip)
        self.label.bind("<Leave>", self._hide_tooltip)
        self.label.bind("<ButtonPress>", self._hide_tooltip)
        self.bind("<Unmap>", self._hide_tooltip)
        self.bind("<Destroy>", self._hide_tooltip)
        self.set_name("")

    def set_name(self, name: str, *, failed: bool = False) -> None:
        self._hide_tooltip()
        self.full_text = "读取失败" if failed else name.strip() or "未设置"
        self._render()

    def _render(self, _event=None) -> None:
        actual_width = self.label.winfo_width()
        width = max(0, (actual_width if actual_width > 1 else int(self.cget("width"))) - 24)
        self.label.configure(text=fit_project_name(self.full_text, self.name_font.measure, width))

    def _schedule_tooltip(self, _event=None) -> None:
        self._hide_tooltip()
        self.tooltip_job = self.after(400, self._show_tooltip)

    def _show_tooltip(self) -> None:
        self.tooltip_job = None
        self.tooltip = Toplevel(self)
        self.tooltip.withdraw()
        self.tooltip.overrideredirect(True)
        Label(self.tooltip, text=self.full_text, justify="left", wraplength=560,
              background="#fffbe6", foreground="#18263b", relief="solid",
              borderwidth=1, padx=8, pady=6).pack()
        self.tooltip.update_idletasks()
        x = self.label.winfo_rootx()
        y = self.label.winfo_rooty() + self.label.winfo_height() + 4
        self.tooltip.geometry(f"+{x}+{y}")
        self.tooltip.deiconify()

    def _hide_tooltip(self, _event=None) -> None:
        if self.tooltip_job is not None:
            self.after_cancel(self.tooltip_job)
            self.tooltip_job = None
        if self.tooltip is not None:
            popup, self.tooltip = self.tooltip, None
            popup.destroy()
