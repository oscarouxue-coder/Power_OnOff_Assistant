"""不绑定DUT的电脑快照执行器；不创建串口或Telnet连接。"""
import os
import platform
import time

from src.core.ai_network_probe import read_network_state


class PcConversationExecutor:
    recovery_state = "无临时修改"
    transport = None

    def __init__(self, stop, emit):
        self.stop, self.emit = stop, emit

    def execute(self, name, params, deep=False):
        if self.stop.is_set():
            raise InterruptedError("本轮已取消")
        if name != "read_pc_environment" or params:
            raise ValueError("本机会话不提供设备或串口工具")
        self.emit("[AI采集] 开始读取本机电脑环境；未绑定样机")
        result = dict(system=platform.platform(), python=platform.python_version(),
                      captured_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        if os.name == "nt":
            import ctypes
            result["administrator"] = bool(ctypes.windll.shell32.IsUserAnAdmin())
        for category in ("addresses", "route", "wifi"):
            result[category] = read_network_state(category, self.stop, self.emit)
        self.emit("[AI采集] 本机电脑环境读取完成；无目标网卡推断")
        return result

    def close(self):
        pass
