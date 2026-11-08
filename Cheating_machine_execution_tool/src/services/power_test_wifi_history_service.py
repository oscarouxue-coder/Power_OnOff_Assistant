"""从原始WiFi消息汇总异常历史；不操作设备，不改变业务结果。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


_CONTEXT = re.compile(r'^\[WiFi测试\] 通道(?P<channel>\d+) 第(?P<cycle>\d+)轮(?: (?P<body>.*))?$', re.S)
_CARD = re.compile(
    r'^网卡=.+? (?=频段=\S+ |入队[；：]|取得使用权|实际无线网卡=|'
    r'等待网卡 |释放使用权|测试环境异常：|验证失败：|取消|跳过：|失败：)')
_BAND = re.compile(r'^频段=(?P<band>\S+) (?P<stage>.*)$', re.S)
_ATTEMPT = re.compile(r'^第\s*(?P<attempt>[1-4])\s*/\s*4\s*次连接[，成]')
_ATTEMPT_FAILURE = re.compile(
    r'^第\s*(?P<attempt>[1-4])\s*/\s*4\s*次(?:未通过：|扫描失败：|未连接，)(?P<reason>.*)$', re.S)
_OUTCOME = re.compile(r'^无线测试(?P<band>.*?)失败$', re.S)
_LEGACY_SSID = re.compile(
    r'^SSID=.* (?P<stage>第\s*[1-4]\s*/\s*4\s*次(?:未连接，|连接成功).*|成功：已连接|失败：.*)$', re.S)


@dataclass
class _BandState:
    attempt: int = 0
    reason: str = ''
    retries: set[int] = field(default_factory=set)
    recovered: bool = False


@dataclass
class _ChannelState:
    cycle: int
    band: str = ''
    groups: dict[str, _BandState] = field(default_factory=dict)
    reason: str = ''


class PowerTestWifiHistory:
    """返回既有(channel, cycle, status, detail)回调事件；每次任务独立持有。"""

    def __init__(self, channels, total_cycles):
        self.channels = set(channels)
        self.total_cycles = total_cycles
        self.states: dict[int, _ChannelState] = {}
        self.closed: set[int] = set()

    def reset(self, channel):
        self.states.pop(channel, None)
        self.closed.discard(channel)

    @staticmethod
    def _detail(state, group, reason):
        context = f'WiFi {state.band or "信息读取/无线环境"}'
        if group.attempt:
            context += f' 第{group.attempt}/4次'
        return context + '：' + reason

    def consume(self, text):
        match = _CONTEXT.fullmatch(text)
        if match is None:
            return []
        channel, cycle = int(match['channel']), int(match['cycle'])
        if channel not in self.channels or channel in self.closed or not 1 <= cycle <= self.total_cycles:
            return []
        body = match['body'] or ''
        # 凭据是用户值，不能把其中的“失败/重试”等字样当成事件。
        if body.startswith('WiFi信息：'):
            return []
        state = self.states.get(channel)
        if state is not None and cycle < state.cycle:
            return []
        if state is None or cycle != state.cycle:
            state = self.states[channel] = _ChannelState(cycle)
        body = _CARD.sub('', body, count=1)
        band_match = _BAND.fullmatch(body)
        if band_match:
            state.band = band_match['band']
            stage = band_match['stage']
        else:
            stage = body
        legacy_stage = _LEGACY_SSID.fullmatch(stage)
        if legacy_stage:
            stage = legacy_stage['stage']
        group = state.groups.setdefault(state.band, _BandState())
        if stage.startswith(('取消', '跳过：')):
            return []
        attempt = _ATTEMPT.match(stage)
        if attempt:
            group.attempt = int(attempt['attempt'])
        failure = _ATTEMPT_FAILURE.fullmatch(stage)
        if failure:
            group.attempt = int(failure['attempt'])
            group.reason = stage
            state.reason = self._detail(state, group, stage)
        # 当前service把原因和等待分别发送；旧连接器在同一条中发送。
        # 两种形式按尝试编号合并，下一条等待不得再次记录。
        if stage == '等待10秒后重试' or (failure and '10秒后重试' in failure['reason']):
            if group.attempt and group.attempt < 4 and group.attempt not in group.retries:
                group.retries.add(group.attempt)
                reason = group.reason or '本次连接未通过'
                if '10秒后重试' not in reason:
                    reason += '；等待10秒后重试'
                return [(channel, cycle, 'retry', self._detail(state, group, reason))]
            return []
        if stage in ('成功：本项无线测试通过', '成功：已连接'):
            state.reason = ''
            group.reason = ''
            if group.retries and not group.recovered:
                group.recovered = True
                return [(channel, cycle, 'success', self._detail(
                    state, group, f'重试{len(group.retries)}次后测试通过'))]
            return []
        outcome = _OUTCOME.fullmatch(stage)
        if outcome:
            # 外层只有“无线测试5G失败”，保留内层详细原因及最后尝试编号。
            if not state.band and outcome['band']:
                state.band = outcome['band'].split('：', 1)[0]
                group = state.groups.setdefault(state.band, _BandState())
            if not state.reason:
                state.reason = self._detail(state, group, stage)
        elif stage.startswith(('测试环境异常：', '验证失败：', '获取WiFi信息失败', '失败：')):
            # 尝试用尽/信息读取的概括不能覆盖此前的具体原因码和核验原因。
            generic = stage.startswith(('失败：第', '获取WiFi信息失败'))
            if not generic or not state.reason:
                group.reason = stage
                state.reason = self._detail(state, group, stage)
        return []

    def finish(self, channel, *, ok, cancelled=False):
        """业务已确认失败才追加一次最终失败；取消不会把暂存异常写入历史。"""
        state = self.states.pop(channel, None)
        self.closed.add(channel)
        if ok or cancelled or state is None or not state.reason:
            return []
        return [(channel, state.cycle, 'failed', state.reason)]
