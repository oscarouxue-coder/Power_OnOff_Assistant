"""Presentation of events already recorded by the original business jobs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re

from src.models.workbench_presentation import LogView


@dataclass(frozen=True)
class HistoryJob:
    job_id: str
    capability: str
    state: str
    created: str


@dataclass(frozen=True)
class HistoryPage:
    entries: tuple
    next_cursor: int | tuple[float, str] | None


@dataclass(frozen=True)
class LegacyRun:
    run_id: str
    operation: str
    state: str
    revision: str
    started: str
    finished: str


@dataclass(frozen=True)
class HistoryEventFilter:
    keyword: str = ''
    level: str = ''
    channel: int | None = None


@dataclass(frozen=True)
class ChannelHistoryEvent:
    cycle: int
    status: str
    detail: str


@dataclass(frozen=True)
class ArchivedLogFile:
    path: Path
    label: str
    channel: int | None = None
    run_id: str = ''
    kind: str = ''


@dataclass(frozen=True)
class HistoryMaterialTarget:
    project_id: str
    job_id: str
    run_id: str
    channel: int
    power_name: str = ''
    wifi_name: str = ''


@dataclass(frozen=True)
class HistoryMaterialSummary:
    target: HistoryMaterialTarget
    text: str
    read_count: int
    missing_count: int
    failed_count: int


@dataclass(frozen=True)
class SavedMaterialReport:
    report_id: str
    project_id: str
    job_id: str
    run_id: str
    channels: tuple[int, ...]
    generated_at: str
    historical_state: str
    historical_at: str
    saved_at: str
    text: str


@dataclass(frozen=True)
class SavedMaterialReports:
    run_id: str
    reports: tuple[SavedMaterialReport, ...]
    invalid_count: int = 0


@dataclass(frozen=True)
class HistoryMaterialBatchTarget:
    project_id: str
    job_id: str
    run_id: str
    channels: tuple[HistoryMaterialTarget, ...]


@dataclass(frozen=True)
class HistoryMaterialChannelResult:
    target: HistoryMaterialTarget
    state: str
    summary: HistoryMaterialSummary | None = None


@dataclass(frozen=True)
class HistoryMaterialBatchSummary:
    target: HistoryMaterialBatchTarget
    entries: tuple[HistoryMaterialChannelResult, ...]

    def matches(self, target):
        return (isinstance(target, HistoryMaterialBatchTarget) and self.target == target
                and isinstance(self.entries, tuple) and all(isinstance(row, HistoryMaterialChannelResult) for row in self.entries)
                and tuple(row.target for row in self.entries) == target.channels
                and all((row.state == 'completed' and isinstance(row.summary, HistoryMaterialSummary)
                         and row.summary.target == row.target)
                        or (row.state in ('failed', 'cancelled') and row.summary is None) for row in self.entries))

    @property
    def completed_count(self):
        return sum(row.state == 'completed' for row in self.entries)

    @property
    def failed_count(self):
        return sum(row.state == 'failed' for row in self.entries)

    @property
    def cancelled_count(self):
        return sum(row.state == 'cancelled' for row in self.entries)

    @property
    def text(self):
        target = self.target
        partial = sum(row.summary is not None and bool(row.summary.missing_count or row.summary.failed_count)
                      for row in self.entries)
        lines = [f'项目 {target.project_id}\n任务 {target.job_id}\n批次 {target.run_id}',
                 f'选定 {len(target.channels)} 个通道；已完成核对 {self.completed_count} 个（其中资料缺失或读取失败 {partial} 个），'
                 f'无法核对 {self.failed_count} 个，已取消 {self.cancelled_count} 个。'
                 '\n各通道分别核对，历史观测不代表实时状态；故障原因及当前设备状态未知。']
        for row in self.entries:
            title = f'CH{row.target.channel:02d} · '
            if row.summary is not None:
                status = ('无可读资料' if not row.summary.read_count else '部分资料缺失或读取失败'
                          if row.summary.missing_count or row.summary.failed_count else '已读取选定资料')
                lines.append(title + '已完成核对 · ' + status + '\n\n' + row.summary.text)
            else:
                lines.append(title + ('已取消，本通道没有完成的报告。' if row.state == 'cancelled'
                                      else '无法核对，本通道没有完成的报告。'))
                lines.append('选定资料：' + '；'.join((row.target.power_name or '开关机结果缺失',
                                                      row.target.wifi_name or 'WiFi 记录缺失'))
                             + '\n未完成读取，不提供观察、时间或记录引用。')
        return '\n\n'.join(lines)


@dataclass(frozen=True)
class ArchivedLogCursor:
    offset: int
    device: int
    inode: int


@dataclass(frozen=True)
class ArchivedLogPage:
    entries: tuple
    next_cursor: ArchivedLogCursor | None
    note: str = ''


def job_event_channel(stage, message):
    channel = None
    if stage in ('aging', 'history', 'version_item') and message.startswith('{'):
        try:
            row = json.loads(message)
            channel = row.get('channel') if isinstance(row, dict) else None
        except (ValueError, RecursionError):
            pass
        if isinstance(channel, str) and re.fullmatch(r'channel_\d{1,2}', channel):
            channel = int(channel.split('_')[1])
        if type(channel) is not int or not 1 <= channel <= 16:
            channel = None
    return channel


def job_event_level(stage):
    return {'succeeded': 'SUCCESS', 'failed': 'ERROR', 'unknown': 'WARN', 'pretest.success': 'SUCCESS',
             'pretest.warning': 'WARN', 'pretest.error': 'ERROR'}.get(stage, 'INFO')


def job_event_message(job_id, stage, message):
    return f'[业务任务 {job_id[:8]}][{stage}] {message}'


def job_event_view(project_id, project_name, job_id, created, stage, message, *, historical=False):
    time_format = '%Y-%m-%d %H:%M:%S' if historical else '%H:%M:%S'
    return LogView(datetime.fromtimestamp(created).strftime(time_format), job_event_level(stage), project_id,
                   project_name, job_event_message(job_id, stage, message), job_id, job_event_channel(stage, message))
