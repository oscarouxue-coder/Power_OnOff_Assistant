"""定位旧开关机测试为指定通道写入的最新结果日志。"""
from __future__ import annotations

from pathlib import Path


def latest_power_test_result_log(tool_root: Path, channel_number: int) -> Path | None:
    """返回通道最新结果日志；文件名的时间戳决定先后，不读取或修改日志内容。"""
    if channel_number < 1:
        raise ValueError("通道编号必须为正整数")

    result_dir = Path(tool_root) / "test_results" / f"device_{channel_number}"
    try:
        candidates = tuple(
            path
            for path in result_dir.glob(
                f"device_{channel_number}_command_results_*.log"
            )
            if path.is_file()
        )
    except OSError as exc:
        raise OSError(f"无法读取开关机结果目录 {result_dir}：{exc}") from exc
    return max(candidates, key=lambda path: path.name) if candidates else None


def latest_power_test_wifi_log(tool_root: Path, channel_number: int) -> Path | None:
    """仅定位当前通道的最新WiFi文件，包含续跑；不打开或修改文件。"""
    if channel_number < 1:
        raise ValueError("通道编号必须为正整数")
    result_dir = Path(tool_root) / "test_results" / f"device_{channel_number}"
    try:
        candidates = tuple(path for path in result_dir.glob(f"device_{channel_number}_wifi_*.log")
                           if path.is_file())
    except OSError as exc:
        raise OSError(f"无法读取WiFi结果目录 {result_dir}：{exc}") from exc
    return max(candidates, key=lambda path: path.name) if candidates else None


__all__ = ["latest_power_test_result_log", "latest_power_test_wifi_log"]
