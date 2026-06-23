from __future__ import annotations

import subprocess
from typing import Any


def hidden_window_kwargs() -> dict[str, Any]:
    if not hasattr(subprocess, "STARTUPINFO"):
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }
