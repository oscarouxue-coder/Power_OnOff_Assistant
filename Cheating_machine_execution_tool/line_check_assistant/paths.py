from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, Optional


OLD_TOOL_NAME_KEYWORD = "Auto_Power_On_Off_Tool"
OLD_TOOL_SOURCE_DIR_NAME = "Auto_power_on_off_tool"
CONFIG_DIR_NAME = "config"


def resolve_tool_root() -> Path:
    for candidate in _candidate_roots():
        if _find_old_tool_path(candidate) or resolve_config_dir(candidate).is_dir():
            return candidate
    return Path.cwd()


def resolve_config_dir(root: Path) -> Path:
    return root / OLD_TOOL_SOURCE_DIR_NAME / CONFIG_DIR_NAME


def resolve_old_tool_path(root: Path) -> Path:
    matched = _find_old_tool_path(root)
    if matched is not None:
        return matched
    return root / f"{OLD_TOOL_NAME_KEYWORD}.exe"


def _find_old_tool_path(root: Path) -> Optional[Path]:
    try:
        candidates = [
            path
            for path in root.iterdir()
            if path.is_file()
            and path.suffix.lower() == ".exe"
            and OLD_TOOL_NAME_KEYWORD.lower() in path.name.lower()
        ]
    except OSError:
        return None
    if not candidates:
        return None
    return sorted(candidates, key=_old_tool_sort_key)[0]


def _old_tool_sort_key(path: Path) -> tuple[int, str]:
    exact_name = f"{OLD_TOOL_NAME_KEYWORD}.exe".lower()
    return (0 if path.name.lower() == exact_name else 1, path.name.lower())


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
