"""Notebook with a separate close hit target on each tab."""
from __future__ import annotations

from copy import deepcopy
from tkinter import PhotoImage, TclError, ttk
from typing import Callable


class ClosableNotebook(ttk.Notebook):
    """Request a close by frame path; the owner decides whether to remove it."""

    def __init__(self, master, on_close: Callable[[str], None], **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._on_close = on_close
        self._pressed_tab: str | None = None
        self._close_element = self._install_close_style()
        self.bind("<ButtonPress-1>", self._on_close_press)
        self.bind("<ButtonRelease-1>", self._on_close_release)

    def _install_close_style(self) -> str:
        style = ttk.Style(self)
        root = self._root()
        # Keep images alive for this Tcl interpreter, including window reopenings.
        cache = getattr(root, "_serial_close_styles", None)
        if cache is None:
            cache = root._serial_close_styles = {}
        theme = style.theme_use()
        if theme not in cache:
            size = max(12, round(12 * self.winfo_fpixels("1i") / 96))
            icon = PhotoImage(master=self, width=size, height=size)
            inset = max(3, size // 4)
            for pos in range(inset, size - inset):
                for offset in (0, 1):
                    icon.put("#555555", (pos, pos + offset))
                    icon.put("#555555", (pos, size - 1 - pos + offset))
            element = f"SerialClose{len(cache)}.close"
            style.element_create(element, "image", icon)
            layout = deepcopy(style.layout("TNotebook.Tab"))

            def add_close(nodes) -> bool:
                for name, options in nodes:
                    if name == "Notebook.label":
                        options["side"] = "left"
                        nodes.append((element, {"side": "left", "sticky": ""}))
                        return True
                    if add_close(options.get("children", [])):
                        return True
                return False

            if not add_close(layout):
                raise RuntimeError("当前 Notebook 主题缺少标签布局")
            style.layout("SerialClosable.TNotebook.Tab", layout)
            cache[theme] = (element, icon)
        self.configure(style="SerialClosable.TNotebook")
        return cache[theme][0]

    def _close_tab_at(self, x: int, y: int) -> str | None:
        if self.identify(x, y) != self._close_element:
            return None
        try:
            return self.tabs()[self.index(f"@{x},{y}")]
        except (TclError, IndexError):
            return None

    def _on_close_press(self, event):
        self._pressed_tab = self._close_tab_at(event.x, event.y)
        if self._pressed_tab is not None:
            return "break"
        return None

    def _on_close_release(self, event):
        pressed = self._pressed_tab
        self._pressed_tab = None
        if pressed is None:
            return None
        if self._close_tab_at(event.x, event.y) == pressed:
            self._on_close(pressed)
        return "break"
