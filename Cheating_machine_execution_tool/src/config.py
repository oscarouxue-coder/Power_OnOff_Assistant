"""项目级别的全局配置。

任何模块需要用到工具全局默认值的(例如日志保存目录),
都应从这里导入,避免在多个文件里重复硬编码,后续调整一处生效。
"""
from __future__ import annotations

from pathlib import Path


# 串口日志的默认保存目录。
# - SerialTerminalWindow 初次打开 / 状态文件丢失时回退到这里
# - app._serial_log_directory() 给 SerialTerminalWindow 传初值
DEFAULT_LOG_DIR: Path = Path(r"D:\Serial_Log")