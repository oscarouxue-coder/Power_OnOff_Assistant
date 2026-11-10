"""模块窗口的统一浅蓝灰背景；局部派生样式保留字体、状态色与控件语义。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


MODULE_BACKGROUND = "#eef2f5"


def apply_module_theme(window, background=MODULE_BACKGROUND):
    """构造完成后调用；后续映射的动态控件也使用同一背景。"""
    if not isinstance(window, tk.Misc):
        return  # 兼容只测试窗口编排的最小替身。
    style = ttk.Style(window)

    def apply(widget):
        try:
            if widget.winfo_toplevel() != window:
                return
            kind = widget.winfo_class()
            if kind in ("Toplevel", "Frame", "Labelframe", "Label", "Panedwindow"):
                widget.configure(background=background)
            elif kind == "Checkbutton":
                widget.configure(background=background, activebackground=background)
            elif kind in ("TFrame", "TLabel", "TNotebook", "TLabelframe", "TPanedwindow"):
                original = widget.cget("style") or kind
                derived = original if original.startswith("Module.") else "Module." + original
                style.configure(derived, background=background)
                if kind == "TNotebook":
                    style.configure(derived + ".Tab", background=background)
                    style.map(derived + ".Tab", background=[("selected", background), ("active", background)])
                elif kind == "TLabelframe":
                    style.configure(derived + ".Label", background=background)
                widget.configure(style=derived)
            for child in widget.winfo_children():
                apply(child)
        except tk.TclError:
            return

    apply(window)
    if not getattr(window, "_module_theme_bound", False):
        window.bind("<Map>", lambda event: apply(event.widget), add="+")
        window._module_theme_bound = True
