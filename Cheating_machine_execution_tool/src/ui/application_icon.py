"""Application identity and inherited Tk window icons; no window event hooks."""
from __future__ import annotations

import ctypes
from pathlib import Path
import struct
import sys
from tkinter import TclError


APPLICATION_ID = "Aouxue.LineCheckAssistant"
ICON_RELATIVE_PATH = Path("assets/icons/line_check_assistant_network_topology_v1.ico")


def application_icon_path() -> Path:
    """Resolve assets independently of the launch directory in source/frozen runs."""
    if getattr(sys, "frozen", False):
        root = Path(sys._MEIPASS)
    else:
        root = Path(__file__).resolve().parents[2]
    return root / ICON_RELATIVE_PATH


def set_taskbar_application_id() -> list[str]:
    """Call before creating Tk; optional shell integration must not block startup."""
    if sys.platform != "win32":
        return ["[程序图标] 任务栏标识跳过：当前不是 Windows。"]
    try:
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        setter = shell.SetCurrentProcessExplicitAppUserModelID
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_long  # HRESULT is 32 bits on Windows x64 too.
        result = setter(APPLICATION_ID)
        if result != 0:
            raise OSError(f"HRESULT=0x{result & 0xffffffff:08X}")
    except Exception as exc:
        return [f"[程序图标] 任务栏标识设置失败：{exc}；继续启动。"]
    return [f"[程序图标] 任务栏标识设置成功：{APPLICATION_ID}"]


def apply_application_icon(window) -> list[str]:
    """Set the root and interpreter default, including future nested Toplevels."""
    if sys.platform != "win32":
        return ["[程序图标] Windows ICO 设置跳过：当前不是 Windows。"]
    try:
        icon = application_icon_path()
        if not icon.is_file():
            raise FileNotFoundError(f"图标文件不存在：{icon}")
        data = icon.read_bytes()
        if len(data) < 6 or data[:4] != b"\x00\x00\x01\x00":
            raise ValueError(f"ICO 文件头损坏：{icon}")
        count = struct.unpack_from("<H", data, 4)[0]
        if not count or len(data) < 6 + 16 * count:
            raise ValueError(f"ICO 目录不完整：{icon}")
        for index in range(count):
            length, offset = struct.unpack_from("<II", data, 6 + 16 * index + 8)
            if not length or offset < 6 + 16 * count or offset + length > len(data):
                raise ValueError(f"ICO 图像数据不完整：{icon}")
    except Exception as exc:
        return [f"[程序图标] 图标资源加载失败：{exc}；继续启动。"]

    messages = []
    # The shared ICO uses native DIB frames for title-bar/taskbar sizes. This
    # avoids Tk's generic-file fallback with all-PNG ICOs, without image hooks.
    operations = (("主窗口", lambda: window.iconbitmap(bitmap=str(icon))),
                  ("子窗口默认", lambda: window.iconbitmap(default=str(icon))))
    # Keep the calls independent: failure of one must not prevent the other.
    for label, apply in operations:
        try:
            apply()
        except (TclError, OSError) as exc:
            messages.append(f"[程序图标] {label}图标设置失败：{exc}；继续启动。")
        else:
            messages.append(f"[程序图标] {label}图标设置成功：{icon}")
    return messages
