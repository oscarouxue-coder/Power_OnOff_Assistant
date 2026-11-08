"""主界面日志适配；WiFi摘要规则与文件记录共用。"""
from __future__ import annotations

from src.utils.wifi_log_summary import WifiLogSummary


def format_main_log_message(message: str, summary: WifiLogSummary | None = None) -> str | None:
    """保留既有入口；有状态的调用者传入自己的摘要器。"""
    return (summary if summary is not None else WifiLogSummary()).format(message)
