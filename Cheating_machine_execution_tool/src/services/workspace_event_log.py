"""Bounded workspace log handoff, compatible text output and dated event archives."""
from collections import deque
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from functools import lru_cache
from itertools import groupby
from pathlib import Path
import re
import sqlite3
import threading
import time

from src.models.workbench_presentation import LogView
from src.services.project_profile_store import read_project_profile


DAY = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')
INDEXES = ('project_id', 'dut_id', 'channel', 'level', 'step', 'job_id', 'run_id')
FIELDS = 'observed, time, level, project_id, project_name, dut_id, channel, step, job_id, run_id, message'


def _local(path):
    if path.resolve() != path or path.is_symlink():
        raise ValueError('工作区日志路径已重定向')
    return path


@lru_cache(maxsize=128)
def _run_channels(root):
    profile = read_project_profile(_local(root / 'Auto_power_on_off_tool/config'))
    return tuple((d['dut_id'], d['channel']) for d in (profile or {}).get('duts', ()))


def associate_run(entry, records):
    """Read only an admitted Job's frozen DUT/channel map, on the archive thread."""
    record = records.get(entry.job_id) if entry.job_id else None
    if not record or record.get('project_id') != entry.project_id:
        return entry
    run_id = record.get('run_id', '')
    if not run_id or entry.batch_id and entry.batch_id != run_id:
        return entry
    entry = replace(entry, batch_id=run_id)
    path = record.get('_path')
    if not isinstance(path, Path) or path.parent.name != run_id or path.name != 'run.json':
        return entry
    if (entry.dut_id and entry.channel is not None) or (not entry.dut_id and entry.channel is None):
        return entry
    try:
        matches = [(dut, channel) for dut, channel in _run_channels(path.parent) if
                   (dut == entry.dut_id if entry.dut_id else channel == entry.channel)]
    except (OSError, ValueError, RuntimeError):
        return entry
    return replace(entry, dut_id=matches[0][0], channel=matches[0][1]) if len(matches) == 1 else entry


def _write_events(directory, batch):
    archive = _local(directory / 'workspace-events')
    archive.mkdir(exist_ok=True)
    for day, events in groupby(batch, key=lambda item: item[0][:10]):
        path = _local(archive / (day + '.sqlite3'))
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, observed TEXT, time TEXT, level TEXT, project_id TEXT,
                project_name TEXT, dut_id TEXT, channel INTEGER, step TEXT, job_id TEXT, run_id TEXT, message TEXT)''')
            for key in INDEXES:
                db.execute(f'CREATE INDEX IF NOT EXISTS event_{key} ON events({key}, id)')
            db.executemany(f'INSERT INTO events ({FIELDS}) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                           ((stamp, e.time, e.level, e.project_id, e.project_name, e.dut_id, e.channel,
                             e.step, e.job_id, e.batch_id, e.message) for stamp, e in events))


def read_workspace_events(directory, *, project_id=None, dut_id=None, channel=None, level=None,
                          step=None, job_id=None, run_id=None, before=None, limit=120):
    """Newest first, with an exclusive per-row cursor. Reads never create files."""
    if type(limit) is not int or not 1 <= limit <= 120:
        raise ValueError('日志分页条数必须为 1 到 120')
    if before is not None and not (isinstance(before, (tuple, list)) and len(before) == 2
            and isinstance(before[0], str) and DAY.fullmatch(before[0])
            and type(before[1]) is int and before[1] > 0):
        raise ValueError('日志分页位置无效')
    archive = _local(Path(directory).resolve() / 'workspace-events')
    filters = dict(project_id=project_id, dut_id=dut_id, channel=channel, level=level,
                   step=step, job_id=job_id, run_id=run_id)
    results = []
    for path in sorted(archive.glob('*.sqlite3'), reverse=True):
        day = path.stem
        if not DAY.fullmatch(day) or (before and day > before[0]):
            continue
        params = [v for v in filters.values() if v is not None]
        terms = [f'{k}=?' for k, v in filters.items() if v is not None]
        if before and day == before[0]:
            terms.append('id < ?')
            params.append(before[1])
        where = ' WHERE ' + ' AND '.join(terms) if terms else ''
        with closing(sqlite3.connect(_local(path).as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(f'SELECT id, {FIELDS} FROM events{where} ORDER BY id DESC LIMIT ?',
                              [*params, limit - len(results)])
            results.extend(dict(row, cursor=(day, row['id'])) for row in rows)
        if len(results) == limit:
            break
    return tuple(results)


class WorkspaceEventWriter:
    """One disk writer with background backpressure and a nonblocking control reserve."""
    def __init__(self, report, *, max_events=16384, max_chars=8 * 1024 * 1024,
                 reserve_events=256, reserve_chars=512 * 1024, clock=datetime.now, associate=None):
        self.report = report
        self.max_events = max_events
        self.max_chars = max_chars
        self.reserve_events = reserve_events
        self.reserve_chars = reserve_chars
        self.clock = clock
        self.associate = associate
        self.condition = threading.Condition()
        self.pending = deque()
        self.chars = self.accepted = self.finished = self.overflow = 0
        self.closing = False
        self.thread = None
        self.progress_at = None
        self._archive_drained = False

    def start(self, directory):
        self.directory = Path(directory).resolve()
        self.thread = threading.Thread(target=self._run, name='workspace-event-writer', daemon=False)
        self.thread.start()

    def offer(self, entry, *, control=False):
        count_limit = self.max_events + (self.reserve_events if control else 0)
        char_limit = self.max_chars + (self.reserve_chars if control else 0)
        length = len(entry.message)

        def has_space():
            # An original message exceeding the budget is admitted as the sole queued row.
            return self.closing or not self.pending or (
                len(self.pending) < count_limit and self.chars + length <= char_limit)

        with self.condition:
            if not control:
                self.condition.wait_for(has_space)
            if self.closing:
                return False
            if not has_space():
                self.overflow += 1
                self.condition.notify()
                return False
            self.pending.append((self.clock().astimezone().isoformat(timespec='milliseconds'), entry))
            if self.accepted == self.finished:
                self.progress_at = time.monotonic()
            self.chars += length
            self.accepted += 1
            self.condition.notify_all()
            return True

    def pending_snapshot(self):
        with self.condition:
            count = self.accepted - self.finished
            return count, (time.monotonic() - self.progress_at if count else 0.)

    def flush(self, timeout=10):
        """Wait only for the accepted prefix observed on entry, on a reader or test thread."""
        with self.condition:
            target = self.accepted
            return self.condition.wait_for(lambda: self.finished >= target, timeout)

    def begin_close(self):
        with self.condition:
            self.closing = True
            self.condition.notify_all()
        return self.thread is None or not self.thread.is_alive()

    def close(self):
        self.begin_close()
        if self.thread is not None:
            self.thread.join()
        self.release_closed_callbacks()

    def release_closed_callbacks(self):
        """Release ownership only after the original writer has drained and stopped."""
        with self.condition:
            if not self.closing or (self.thread is not None and self.thread.is_alive()):
                return False
            if (self.pending or self.overflow or self.finished != self.accepted or
                    (self.thread is not None and not self._archive_drained)):
                return False
            self.report = self.associate = None
            return True

    def _write_text(self, batch):
        with _local(self.directory / 'workspace.log').open('a', encoding='utf-8') as stream:
            stream.writelines(e.time + ' [' + e.project_id + '] ' + e.message + '\n' for _, e in batch)

    def _run(self):
        unreported = 0
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.pending or self.overflow or self.closing)
                if not self.pending and not self.overflow and self.closing:
                    self._archive_drained = not unreported
                    return
                size = min(len(self.pending), 128)
                batch = [self.pending.popleft() for _ in range(size)]
                self.chars -= sum(len(e.message) for _, e in batch)
                dropped, self.overflow = self.overflow, 0
                self.condition.notify_all()
            if dropped:
                now = self.clock().astimezone()
                gap = LogView(now.strftime('%H:%M:%S'), 'ERROR', '', '项目管理',
                              f'工作区日志写入队列已满，{dropped} 条原始记录未进入归档', step='workspace_log')
                batch.append((now.isoformat(timespec='milliseconds'), gap))
            if unreported:
                now = self.clock().astimezone()
                batch.insert(0, (now.isoformat(timespec='milliseconds'), LogView(now.strftime('%H:%M:%S'),
                    'ERROR', '', '项目管理', f'此前 {unreported} 条工作区记录的两份日志都未确认写入',
                    step='workspace_log')))
            errors = []
            try:
                self._write_text(batch)
            except (OSError, ValueError, RuntimeError) as error:
                errors.append('workspace.log ' + type(error).__name__)
            try:
                events = [(stamp, self.associate(row)) for stamp, row in batch] if self.associate else batch
                _write_events(self.directory, events)
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
                errors.append('结构化归档 ' + type(error).__name__)
            if len(errors) == 2:
                unreported += size + int(bool(dropped))
            else:
                unreported = 0
            stamp, row = batch[-1]
            if any(item.project_id != row.project_id for _, item in batch):
                row = replace(row, project_id='', project_name='项目管理')
            if len(errors) == 1:
                incident = [(stamp, LogView(row.time, 'ERROR', row.project_id, row.project_name,
                    '工作区日志写盘失败：' + errors[0] + f'，本批 {size} 条原文保存在此归档',
                    step='workspace_log'))]
                try:
                    if errors[0].startswith('workspace.log '):
                        _write_events(self.directory, incident)
                    else:
                        self._write_text(incident)
                except (OSError, ValueError, RuntimeError, sqlite3.Error):
                    pass  # The original batch is already in the other sink. UI still reports this failure.
            self.report(row, '；'.join(errors), size, dropped)
            with self.condition:
                self.finished += size
                self.progress_at = time.monotonic()
                self.condition.notify_all()
