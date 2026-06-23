from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable


OLD_TOOL_NAME = "Auto_Power_On_Off_Tool(2).exe"
CONFIG_DIR_NAME = "config"


def resolve_tool_root() -> Path:
    for candidate in _candidate_roots():
        if (candidate / OLD_TOOL_NAME).exists() or (candidate / CONFIG_DIR_NAME).exists():
            return candidate
    return Path.cwd()


def _candidate_roots() -> Iterable[Path]:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        yield exe_dir
        yield exe_dir.parent
        yield exe_dir.parent.parent

    module_root = Path(__file__).resolve().parents[1]
    yield module_root
    yield module_root.parent

    cwd = Path.cwd().resolve()
    yield cwd
    yield cwd.parent
