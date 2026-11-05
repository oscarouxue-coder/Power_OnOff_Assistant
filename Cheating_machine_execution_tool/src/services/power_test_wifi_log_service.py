"""逐通道/执行尝试的WiFi原始日志；文件故障只告警，不改变设备测试。"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, TextIO


_WIFI_CONTEXT = re.compile(r'^\[WiFi测试\] 通道(?P<channel>\d+) 第(?P<cycle>\d+)轮(?: |$)')


@dataclass
class _ChannelLog:
    channel: int
    attempt: int
    path: Path | None = None
    file: TextIO | None = None
    disabled: bool = False


class WifiResultLogWriter:
    def __init__(self, tool_root: Path, emit: Callable[[str], None], *, now=datetime.now):
        self.root = Path(tool_root)
        self.emit = emit
        self.now = now
        self.local = threading.local()

    def start_channel(self, channel: int, attempt: int = 0) -> None:
        """只绑定线程上下文，未产生WiFi消息时不创建空文件。"""
        self.local.state = _ChannelLog(channel, attempt)

    def _open(self, state: _ChannelLog) -> None:
        directory = self.root / 'test_results' / f'device_{state.channel}'
        stamp = self.now()
        suffix = f'_resume_{state.attempt}' if state.attempt else ''
        while True:
            state.path = directory / f"device_{state.channel}_wifi_{stamp:%Y%m%d%H%M%S%f}{suffix}.log"
            directory.mkdir(parents=True, exist_ok=True)
            try:
                state.file = state.path.open('x', encoding='utf-8', newline='')
                return
            except FileExistsError:
                stamp += timedelta(microseconds=1)

    def _fail(self, state: _ChannelLog, action: str, exc: Exception) -> None:
        if state.disabled:
            return
        state.disabled = True
        opened, state.file = state.file, None
        if opened is not None:
            try:
                opened.close()
            except (OSError, UnicodeError):
                pass
        self.emit(f'[WiFi日志] 通道 {state.channel} {action}失败：{state.path}；{exc}；'
                  '本次WiFi文件记录已停用，设备测试继续。')

    def write(self, level: str, text: str) -> None:
        state = getattr(self.local, 'state', None)
        match = _WIFI_CONTEXT.match(text)
        if (state is None or state.disabled or match is None
                or int(match['channel']) != state.channel):
            return
        created = state.file is None
        action = '创建' if created else '写入/刷新'
        try:
            if created:
                self._open(state)
            action = '写入/刷新'
            timestamp = self.now().strftime('%Y-%m-%d %H:%M:%S.%f')
            context = match.group(0).rstrip()
            body = text[match.end():]
            # 多行消息仍让每个物理行带上通道/轮次；凭据正文按原值保存。
            for line in body.split('\n'):
                state.file.write(f'{timestamp} [{level.upper()}] {context} {line}\n')
            state.file.flush()
        except (OSError, UnicodeError) as exc:
            self._fail(state, action, exc)
            return
        if created:
            self.emit(f'[WiFi日志] 通道 {state.channel} 已创建：{state.path}')

    def finish_channel(self) -> None:
        state = getattr(self.local, 'state', None)
        if state is None:
            return
        try:
            if state.file is not None:
                try:
                    state.file.close()
                except (OSError, UnicodeError) as exc:
                    self._fail(state, '关闭', exc)
                else:
                    self.emit(f'[WiFi日志] 通道 {state.channel} 已关闭：{state.path}')
                    state.file = None
        finally:
            del self.local.state


class WifiResultLogQueue:
    """在子进程原消息转发之前旁路保存WiFi，不改变消息及尝试标记。"""
    def __init__(self, target, logs: WifiResultLogWriter):
        self.target = target
        self.logs = logs

    def put(self, message):
        if message.get('type') == 'log':
            self.logs.write(str(message.get('level', 'info')), str(message.get('message', '')))
        self.target.put(message)

    def __getattr__(self, name):
        return getattr(self.target, name)
