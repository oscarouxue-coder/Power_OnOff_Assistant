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
