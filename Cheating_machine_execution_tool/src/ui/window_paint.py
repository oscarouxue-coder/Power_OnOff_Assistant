"""Tk顶层窗口在Windows映射后的客户区首帧刷新工具。"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from tkinter import TclError


FIRST_PAINT_REFRESH_DELAYS_MS = (20, 120, 360)


def center_toplevel_on_parent(
    window,
    parent,
    *,
    window_width: int | None = None,
    window_height: int | None = None,
) -> str | None:
    """保持窗口当前尺寸，将其移动到父窗口可见区域中央。

    复杂窗口已知最终尺寸时可直接传入，避免为了读取客户区尺寸而在显示前
    同步刷新整棵控件树；未传尺寸的普通窗口继续沿用原来的实际尺寸探测。
    """
    try:
        parent_width = int(parent.winfo_width())
        parent_height = int(parent.winfo_height())
        if parent_width <= 1 or parent_height <= 1:
            parent.update_idletasks()
            parent_width = int(parent.winfo_width())
            parent_height = int(parent.winfo_height())
        if window_width is None or window_height is None:
            window.update_idletasks()
            actual_width = int(window.winfo_width())
            actual_height = int(window.winfo_height())
            width = actual_width if actual_width > 1 else int(window.winfo_reqwidth())
            height = actual_height if actual_height > 1 else int(window.winfo_reqheight())
        else:
            width = max(int(window_width), 1)
            height = max(int(window_height), 1)
        parent_width = max(parent_width, 1)
        parent_height = max(parent_height, 1)
        parent_x = int(parent.winfo_rootx())
        parent_y = int(parent.winfo_rooty())
        x = parent_x + (parent_width - width) // 2
        y = parent_y + (parent_height - height) // 2
        position = f"{x:+d}{y:+d}"
        window.geometry(position)
        return position
    except (AttributeError, TclError, TypeError, ValueError):
        return None


def schedule_toplevel_client_refresh(
    window,
    *,
    delays_ms: Iterable[int] = FIRST_PAINT_REFRESH_DELAYS_MS,
    on_first_refresh: Callable[[], None] | None = None,
) -> None:
    """用可恢复的1像素尺寸脉冲触发客户区整树重绘。"""
    try:
        current_generation = int(getattr(window, "_client_refresh_generation", 0))
    except (TypeError, ValueError):
        current_generation = 0
    generation = current_generation + 1
    setattr(window, "_client_refresh_generation", generation)
    notified = [False]

    def refresh() -> None:
        try:
            if generation != getattr(window, "_client_refresh_generation", None):
                return
            if not window.winfo_exists() or window.state() != "normal":
                return
            window.update_idletasks()
            width = int(window.winfo_width())
            height = int(window.winfo_height())
            x = int(window.winfo_x())
            y = int(window.winfo_y())
            if width <= 1 or height <= 1:
                return
            screen_width = int(window.winfo_screenwidth())
            delta = 1 if width < screen_width else -1
            position = f"{x:+d}{y:+d}"
            original_geometry = f"{width}x{height}{position}"
            window.geometry(f"{width + delta}x{height}{position}")
            window.update_idletasks()
            window.geometry(original_geometry)
            window.update_idletasks()
            if on_first_refresh is not None and not notified[0]:
                notified[0] = True
                on_first_refresh()
        except (AttributeError, TclError, ValueError):
            return

    for delay_ms in delays_ms:
        try:
            window.after(max(0, int(delay_ms)), refresh)
        except (AttributeError, TclError, ValueError):
            return


__all__ = [
    "FIRST_PAINT_REFRESH_DELAYS_MS",
    "center_toplevel_on_parent",
    "schedule_toplevel_client_refresh",
]
