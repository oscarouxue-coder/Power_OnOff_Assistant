"""功能模块窗口宽高的本机持久化工具。"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path


MODULE_WINDOW_SIZE_STATE_PATH = Path.home() / ".aouxue_line_check_module_window_sizes.json"
_WINDOW_SIZES_KEY = "window_sizes"


def _load_state(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_state(path: Path, payload: Mapping[str, object]) -> bool:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def clamp_module_window_size(
    width: object,
    height: object,
    *,
    default_width: int,
    default_height: int,
    min_width: int,
    min_height: int,
    screen_width: object | None = None,
    screen_height: object | None = None,
) -> tuple[int, int]:
    """收敛保存值，兼容更换显示器或损坏的本机状态文件。"""
    try:
        safe_width = int(width)
    except (TypeError, ValueError):
        safe_width = default_width
    try:
        safe_height = int(height)
    except (TypeError, ValueError):
        safe_height = default_height

    safe_width = max(min_width, safe_width)
    safe_height = max(min_height, safe_height)
    try:
        maximum_width = max(min_width, int(screen_width))
    except (TypeError, ValueError):
        maximum_width = safe_width
    try:
        maximum_height = max(min_height, int(screen_height))
    except (TypeError, ValueError):
        maximum_height = safe_height
    return min(safe_width, maximum_width), min(safe_height, maximum_height)


def load_module_window_size(
    path: Path,
    module_key: str,
    *,
    default_width: int,
    default_height: int,
    min_width: int,
    min_height: int,
    screen_width: object,
    screen_height: object,
) -> tuple[int, int]:
    """读取指定模块的宽高；缺失、损坏时使用默认值。"""
    payload = _load_state(path)
    values = payload.get(_WINDOW_SIZES_KEY)
    value = values.get(module_key) if isinstance(values, dict) else None
    if not isinstance(value, dict):
        value = {}
    return clamp_module_window_size(
        value.get("width", default_width),
        value.get("height", default_height),
        default_width=default_width,
        default_height=default_height,
        min_width=min_width,
        min_height=min_height,
        screen_width=screen_width,
        screen_height=screen_height,
    )


def save_module_window_size(
    path: Path,
    module_key: str,
    width: object,
    height: object,
    *,
    default_width: int,
    default_height: int,
    min_width: int,
    min_height: int,
) -> bool:
    """保存指定模块的宽高，并保留其它模块的状态。"""
    safe_width, safe_height = clamp_module_window_size(
        width,
        height,
        default_width=default_width,
        default_height=default_height,
        min_width=min_width,
        min_height=min_height,
    )
    payload = _load_state(path)
    values = payload.get(_WINDOW_SIZES_KEY)
    window_sizes = dict(values) if isinstance(values, dict) else {}
    window_sizes[module_key] = {"width": safe_width, "height": safe_height}
    payload[_WINDOW_SIZES_KEY] = window_sizes
    return _save_state(path, payload)


__all__ = [
    "MODULE_WINDOW_SIZE_STATE_PATH",
    "clamp_module_window_size",
    "load_module_window_size",
    "save_module_window_size",
]
