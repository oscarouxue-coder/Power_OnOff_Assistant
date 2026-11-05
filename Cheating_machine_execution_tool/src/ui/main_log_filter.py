"""主界面 WiFi 日志摘要；原始消息由调用者完整保存到日志文件。"""
from __future__ import annotations

import re


_WIFI_MESSAGE = re.compile(
    r"\[旧工具Logs\]\[(?P<level>[A-Za-z]+)\] \[WiFi测试\] "
    r"(?P<context>通道\d+ 第\d+轮) (?P<body>.+)"
)
_CARD_PREFIX = re.compile(
    r"^网卡=.+? (?=频段=\S+ |入队[；：]|取得使用权|实际无线网卡=|"
    r"等待网卡 |释放使用权|测试环境异常：|验证失败：|取消|跳过：|失败：)"
)
_BAND_PREFIX = re.compile(r"^频段=\S+ ")
_IMPORTANT = re.compile(r"失败|异常|未通过|取消|跳过|错误")
_DETAILS = tuple(re.compile(pattern) for pattern in (
    r"下发只读命令：.+",
    r"只读命令返回（WiFi回显隐藏）",
    r"目标已读取：.+",
    r"双频合一状态=(?:开启|关闭)",
    r"等待网卡 \d+(?:\.\d+)?秒；当前占用=.+",
    r"下发无线扫描",
    r"目标SSID=.+",
    r"等待10秒后重试",
    r"无线Ping：等待无线IPv4地址（最长30秒）",
    r"无线DNS查询：目标=.+ 接口索引=\d+",
    r"无线DNS结果：.+；本项使用第一个IPv4",
    r"无线Ping下发：第[1-4]/4包，.+，超时2秒",
    r"无线Ping第[1-4]/4包：(?:超时|回复 \d+(?:\.\d+)?ms)",
    r"成功：本项无线测试通过",
    r"下发断开临时连接；不删除电脑原有无线配置",
    r"临时连接已清理",
))


def format_main_log_message(message: str) -> str | None:
    """只隐藏已知 INFO 细节；凭据原值、异常及未知消息均保留。"""
    match = _WIFI_MESSAGE.fullmatch(message)
    if match is None:
        return message
    level = match['level'].upper()
    body = match['body']
    # 凭据作为不透明文本处理，密码中的空格/阶段词不能触发过滤或替换。
    if not body.startswith('WiFi信息：'):
        body = _CARD_PREFIX.sub('', body, count=1)
        stage = _BAND_PREFIX.sub('', body, count=1)
        if level == 'INFO' and not _IMPORTANT.search(stage):
            if any(pattern.fullmatch(stage) for pattern in _DETAILS):
                return None
    prefix = '[WiFi]' if level == 'INFO' else f'[WiFi][{level}]'
    return f"{prefix} {match['context']} {body}"
