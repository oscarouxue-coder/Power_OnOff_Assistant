"""正式开关机WiFi日志的共用摘要；不参与设备执行或结果判断。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


_MESSAGE = re.compile(
    r'\[WiFi测试\] 通道(?P<channel>\d+) 第(?P<cycle>\d+)轮(?: (?P<body>.*))?', re.S)
_WRAPPED = re.compile(r'\[旧工具Logs\]\[(?P<level>[A-Za-z]+)\] (?P<text>.*)', re.S)
_CARD = re.compile(
    r'^网卡=.+? (?=频段=\S+ |入队[；：]|取得使用权|实际无线网卡=|'
    r'等待网卡 |释放使用权|测试环境异常：|验证失败：|取消|跳过：|失败：)')
_BAND = re.compile(r'^频段=(?P<band>\S+) (?P<stage>.*)', re.S)
_IMPORTANT = re.compile(r'失败|异常|未通过|取消|跳过|错误|不可用|未知')
_ATTEMPT = re.compile(r'第 (?P<attempt>[1-4])/4 次连接，扫描/连接/核验共约20秒；认证来源=\S+')
_VERIFIED = re.compile(
    r'连接核验成功：SSID=(?P<ssid>.*?) BSSID=\S+ 实际频段=(?P<band>\S+) 认证=\S+ 加密=\S+', re.S)
_PING_START = re.compile(
    r'无线Ping开始：网卡=.+ ifIndex=\d+ 源IP=(?P<source>\S+) 目标=(?P<target>\S+) 实际IP=(?P<remote>\S+)')
_PING_RESULT = re.compile(
    r'无线Ping汇总：发送(?P<sent>\d+) 接收(?P<received>\d+) 丢包率=(?P<loss>\d+)%'
    r'(?: 时延min/avg/max=(?P<latency>[\d.]+/[\d.]+/[\d.]+)ms)? (?P<result>通过|失败)')
_DETAILS = tuple(re.compile(pattern, re.S) for pattern in (
    r'开始获取WiFi信息', r'成功：WiFi信息读取完成',
    r'下发只读命令：.+', r'只读命令返回（WiFi回显隐藏）',
    r'目标已读取：.+', r'双频合一状态=(?:开启|关闭)',
    r'等待网卡 \d+(?:\.\d+)?秒；当前占用=.+',
    r'实际无线网卡=.+ GUID=\S+ ifIndex=\d+',
    r'下发无线扫描', r'目标SSID=.+', r'等待10秒后重试',
    r'无线Ping：等待无线IPv4地址（最长30秒）',
    r'无线DNS查询：目标=.+ 接口索引=\d+',
    r'无线DNS结果：.+；本项使用第一个IPv4',
    r'无线Ping下发：第[1-4]/4包，.+，超时2秒',
    r'无线Ping第[1-4]/4包：(?:超时|回复 \d+(?:\.\d+)?ms)',
    r'下发断开临时连接；不删除电脑原有无线配置', r'临时连接已清理', r'释放使用权',
))


@dataclass
class _Group:
    attempt: int = 1
    ssid: str | None = None
    actual_band: str = ''
    ping_route: str = ''
    ping_result: str = ''
    ping_disabled: bool = False
    invalidated: bool = False


@dataclass
class _Channel:
    cycle: int
    waiting: bool = False
    groups: dict[str, _Group] = field(default_factory=dict)


class WifiLogSummary:
    """每个日志接收端独立持有；每通道只保留当前轮次，首次读取重置续跑状态。"""

    def __init__(self):
        self.channels: dict[int, _Channel] = {}

    def format(self, text: str, level: str = 'INFO') -> str | None:
        wrapped = _WRAPPED.fullmatch(text)
        if wrapped is not None:
            level, text = wrapped['level'], wrapped['text']
        match = _MESSAGE.fullmatch(text)
        if match is None:
            return wrapped.group(0) if wrapped is not None else text
        channel, cycle = int(match['channel']), int(match['cycle'])
        body = match['body'] or ''
        state = self.channels.get(channel)
        if state is None or state.cycle != cycle or body == '开始获取WiFi信息':
            state = self.channels[channel] = _Channel(cycle)
        level = level.upper()
        prefix = '[WiFi]' if level == 'INFO' else f'[WiFi][{level}]'
        context = f'{prefix} 通道{channel} 第{cycle}轮 '
        # 凭据作为不透明正文处理，不能根据密码中的阶段词过滤或改写。
        if body.startswith('WiFi信息：'):
            return context + body
        body = _CARD.sub('', body, count=1)
        band_match = _BAND.fullmatch(body)
        band, stage = (band_match['band'], band_match['stage']) if band_match else ('', body)
        group = state.groups.setdefault(band, _Group())
        if level != 'INFO':
            if level == 'ERROR' or _IMPORTANT.search(stage):
                return context + self._failure(state, band, body)
            return context + body
        if stage == '下发目标BSSID临时连接配置（不保存或覆盖用户配置）':
            return context + f'{band + " " if band else ""}第{group.attempt}/4次下发连接'
        attempt = _ATTEMPT.fullmatch(stage)
        if attempt:
            state.groups[band] = _Group(attempt=int(attempt['attempt']))
            return None
        verified = _VERIFIED.fullmatch(stage)
        if verified:
            group.ssid, group.actual_band = verified['ssid'], verified['band']
            return None
        ping_start = _PING_START.fullmatch(stage)
        if ping_start:
            group.ping_route = f"{ping_start['source']}→{ping_start['target']}"
            if ping_start['target'] != ping_start['remote']:
                group.ping_route += f"({ping_start['remote']})"
            return None
        ping = _PING_RESULT.fullmatch(stage)
        if ping:
            group.ping_result = f"Ping发送{ping['sent']}/接收{ping['received']}，丢包{ping['loss']}%"
            if ping['latency']:
                group.ping_result += f"，时延min/avg/max={ping['latency']}ms"
            if ping['result'] == '失败':
                group.invalidated = True
                return context + body
            return None
        if stage == '跳过：无线Ping未启用':
            group.ping_disabled = True
            return None
        if stage == '成功：本项无线测试通过':
            if group.invalidated:
                return None
            result = f'{band + " " if band else ""}测试通过'
            if group.ssid is not None:
                result += f'；SSID={group.ssid}'
                if band == '合一网络':
                    result += f'；实际频段={group.actual_band}'
            if group.ping_disabled:
                result += '；Ping未启用'
            elif group.ping_result:
                result += '；' + group.ping_result
                if group.ping_route:
                    result += '；' + group.ping_route
            group.invalidated = True
            return context + result
        queued = re.fullmatch(r'入队；当前占用=(.+)', stage)
        if queued:
            state.waiting = queued[1] != '无'
            return context + f'排队；当前占用={queued[1]}' if state.waiting else None
        acquired = re.fullmatch(r'取得使用权；等待 (\d+(?:\.\d+)?)秒', stage)
        if acquired:
            waiting, state.waiting = state.waiting, False
            return context + f'排队等待{acquired[1]}秒' if waiting or float(acquired[1]) >= 1 else None
        if _IMPORTANT.search(stage):
            return context + self._failure(state, band, body)
        if any(pattern.fullmatch(stage) for pattern in _DETAILS):
            return None
        return context + body

    @staticmethod
    def _failure(state, band, body):
        for key, group in state.groups.items():
            if not band or key == band:
                if group.ping_result and not group.invalidated:
                    body += f'；{key} {group.ping_result}'
                group.invalidated = True
        return body
