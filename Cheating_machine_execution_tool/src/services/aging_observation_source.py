"""Read bounded batches of external DUT facts from this run's local JSONL file."""
from collections import Counter, OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import time
from typing import Optional
from uuid import uuid4


@dataclass(frozen=True)
class Observation:
    """On dut_presence only, healthy/abnormal/unknown means online/offline/unknown."""

    project_id: str
    job_id: str
    dut_id: str
    collector: str
    event_id: str
    observed_at: float
    outcome: str
    evidence: str
    boot_id: Optional[str] = None
    uptime_seconds: Optional[float] = None


@dataclass(frozen=True)
class ObservationBatch:
    events: tuple
    status: str
    rejected: dict
    has_more: bool = False


class _Rejected(ValueError):
    pass


def _job_directory(context, job_id):
    if (not isinstance(job_id, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}', job_id)
            or PureWindowsPath(job_id + '.jsonl').is_reserved()):
        raise ValueError('无效的本地批次文件名')
    history = Path(context.root) / 'history'
    if (not history.is_absolute() or history != Path(context.history) or '..' in history.parts
            or history.drive.startswith('\\\\')):
        raise ValueError('项目本地历史目录不匹配')
    return history / 'aging-input'


def _safe_stat(path, *, directory=False, allow_links=False):
    for node in (*reversed(path.parents), path):
        entry = node.lstat()
        if (stat.S_ISLNK(entry.st_mode) or getattr(entry, 'st_file_attributes', 0) &
                getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)):
            raise _Rejected('unsafe_path')
    if directory:
        if not stat.S_ISDIR(entry.st_mode):
            raise _Rejected('unsafe_path')
    elif not stat.S_ISREG(entry.st_mode) or (not allow_links and entry.st_nlink > 1):
        raise _Rejected('unsafe_path')
    return entry


@contextmanager
def _open_input(path, *, allow_links=False):
    before = _safe_stat(path, allow_links=allow_links)
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        actual = os.fstat(stream.fileno())
        if not os.path.samestat(actual, before) or not os.path.samestat(actual, _safe_stat(path, allow_links=allow_links)):
            raise _Rejected('unsafe_path')
        yield stream, actual


def _unique_object(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise _Rejected('invalid_json')
        data[key] = value
    return data


def _reject_constant(value):
    raise _Rejected('invalid_json')


def _text(data, field, maximum):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _Rejected('invalid_fields')
    if any((ord(c) < 32 and not (field == 'detail' and c in '\n\r\t')) or
           0xd800 <= ord(c) <= 0xdfff for c in value):
        raise _Rejected('invalid_fields')
    return value


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 48 or value[10:11] not in ('T', ' '):
        raise _Rejected('invalid_time')
    try:
        stamp = datetime.fromisoformat(value[:-1] + '+00:00' if value.endswith('Z') else value)
        if stamp.tzinfo is None:
            raise ValueError('missing offset')
        return stamp.timestamp()
    except (ValueError, OverflowError, OSError):
        raise _Rejected('invalid_time') from None


def _boot_evidence(data, collector, outcome):
    if 'boot_id' not in data and 'uptime_seconds' not in data:
        return None, None
    if collector != 'dut_presence' or outcome != 'healthy':
        raise _Rejected('invalid_fields')
    boot_id = uptime = None
    if 'boot_id' in data:
        boot_id = data['boot_id']
        if not isinstance(boot_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', boot_id):
            raise _Rejected('invalid_fields')
    if 'uptime_seconds' in data:
        value = data['uptime_seconds']
        if type(value) not in (int, float) or value < 0:
            raise _Rejected('invalid_fields')
        try:
            uptime = float(value)
        except OverflowError:
            raise _Rejected('invalid_fields') from None
        if not math.isfinite(uptime):
            raise _Rejected('invalid_fields')
    return boot_id, uptime


class JsonlObservationSource:
    """One reader per job, polled serially by the monitor worker; never creates files."""

    BYTE_BUDGET = 64 * 1024
    LINE_BUDGET = 128
    MAX_LINE = 8192
    RECENT_EVENTS = 4096
    _ANCHOR = 64

    def __init__(self, context, job_id, plan, *, started_at, clock=time.time, max_age=120):
        self.project_id = context.identity.project_id
        if 'project_id' in plan and plan['project_id'] != self.project_id:
            raise ValueError('业务事实订阅与当前项目不符')
        self.job_id = job_id
        self.started_at, self.max_age = float(started_at), float(max_age)
        if not math.isfinite(self.started_at) or not math.isfinite(self.max_age) or self.max_age <= 0:
            raise ValueError('批次开始时间或观测有效期无效')
        self.clock = clock
        self._duts = frozenset(dut['dut_id'] for dut in plan['duts'])
        self._collectors = frozenset(plan['feed_collectors']) - {'lan_ping'}
        self.path = _job_directory(context, job_id) / (job_id + '.jsonl')
        self._identity = None
        self._offset = 0
        self._anchor = b''
        self._partial = b''
        self._discard = False
        self._recent = OrderedDict()

    def _observation(self, raw, now):
        try:
            data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
            raise _Rejected('invalid_json') from None
        if not isinstance(data, dict):
            raise _Rejected('invalid_fields')
        if 'schema_version' in data and (type(data['schema_version']) is not int or data['schema_version'] != 1):
            raise _Rejected('invalid_fields')
        if data.get('project_id') != self.project_id or data.get('job_id') != self.job_id:
            raise _Rejected('wrong_batch')
        dut = _text(data, 'dut_id', 128)
        collector = _text(data, 'collector', 128)
        if dut not in self._duts or collector not in self._collectors:
            raise _Rejected('unsubscribed')
        event_id = _text(data, 'event_id', 128)
        evidence = _text(data, 'detail', 4096).strip()
        outcome = data.get('outcome')
        if outcome not in ('healthy', 'abnormal', 'unknown'):
            raise _Rejected('invalid_fields')
        boot_id, uptime = _boot_evidence(data, collector, outcome)
        at = _timestamp(data.get('observed_at'))
        if at < self.started_at:
            raise _Rejected('before_start')
        if at > now:
            raise _Rejected('future')
        if now - at > self.max_age:
            raise _Rejected('expired')
        key = (dut, collector, event_id)
        if key in self._recent:
            raise _Rejected('duplicate')
        self._recent[key] = None
        if len(self._recent) > self.RECENT_EVENTS:
            self._recent.popitem(last=False)
        return Observation(self.project_id, self.job_id, dut, collector, event_id, at, outcome, evidence,
                           boot_id, uptime)

    def _consume(self, data, now):
        events, rejected = [], Counter()
        pos = lines = 0
        while pos < len(data) and lines < self.LINE_BUDGET:
            end = data.find(b'\n', pos)
            complete = end != -1
            if not complete:
                end = len(data)
            piece = data[pos:end]
            pos = end + int(complete)
            if not self._discard and len(self._partial) + len(piece) > self.MAX_LINE:
                rejected['oversize'] += 1
                self._discard, self._partial = True, b''
            if not self._discard:
                self._partial += piece
            if complete:
                if not self._discard:
                    try:
                        events.append(self._observation(self._partial, now))
                    except _Rejected as reason:
                        rejected[str(reason)] += 1
                self._partial, self._discard = b'', False
                lines += 1
        self._offset += pos
        self._anchor = (self._anchor + data[:pos])[-self._ANCHOR:]
        return tuple(events), dict(rejected)

    def poll(self):
        try:
            with _open_input(self.path) as (stream, actual):
                identity = actual.st_dev, actual.st_ino
                reset = self._identity is not None and (identity != self._identity or actual.st_size < self._offset)
                if self._anchor and not reset:
                    stream.seek(self._offset - len(self._anchor))
                    reset = stream.read(len(self._anchor)) != self._anchor
                start = 0 if reset else self._offset
                stream.seek(start)
                data = stream.read(self.BYTE_BUDGET)
            now = float(self.clock())
            if not math.isfinite(now):
                raise _Rejected('invalid_clock')
            if reset:
                self._partial, self._discard, self._anchor, self._offset = b'', False, b'', 0
            self._identity = identity
            events, rejected = self._consume(data, now)
            return ObservationBatch(events, 'reset' if reset else 'ready', rejected, self._offset < actual.st_size)
        except FileNotFoundError:
            return ObservationBatch((), 'waiting', {})
        except _Rejected as reason:
            return ObservationBatch((), 'unavailable', {str(reason): 1})
        except (OSError, RuntimeError):
            return ObservationBatch((), 'unavailable', {'read_error': 1})


@contextmanager
def _pin_windows_directory(path):
    """Deny rename/delete sharing while publishing under a verified directory."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    _safe_stat(path, directory=True)
    # FILE_READ_ATTRIBUTES, share read/write, OPEN_EXISTING, BACKUP_SEMANTICS | OPEN_REPARSE_POINT.
    handle = create(str(path), 0x80, 3, None, 3, 0x02200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        _safe_stat(path, directory=True)
        yield
    finally:
        close(handle)


@contextmanager
def _manifest_directory(directory):
    history = directory.parent
    if os.name == 'nt':
        with _pin_windows_directory(history):
            directory.mkdir(exist_ok=True)
            with _pin_windows_directory(directory):
                yield None
        return
    before = _safe_stat(history, directory=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent_fd = os.open(history, flags)
    try:
        if not os.path.samestat(before, os.fstat(parent_fd)):
            raise _Rejected('unsafe_path')
        try:
            os.mkdir(directory.name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        folder_fd = os.open(directory.name, flags, dir_fd=parent_fd)
        try:
            if not os.path.samestat(os.fstat(folder_fd), _safe_stat(directory, directory=True)):
                raise _Rejected('unsafe_path')
            yield folder_fd
        finally:
            os.close(folder_fd)
    finally:
        os.close(parent_fd)


def write_observation_manifest(context, job_id, plan, started_at):
    """Publish the frozen public mapping once; a matching retry returns the existing path."""
    folder = _job_directory(context, job_id)
    project = context.identity.project_id
    if 'project_id' in plan and plan['project_id'] != project:
        raise ValueError('采集计划与当前项目不符')
    duts = []
    for row in plan['duts']:
        dut = {key: row[key] for key in ('dut_id', 'label', 'channel')}
        if row.get('hardware_id'):
            dut['hardware_id'] = row['hardware_id']
        duts.append(dut)
    manifest = dict(schema_version=1, project_id=project, job_id=job_id, duts=duts,
                    started_at=datetime.fromtimestamp(started_at, timezone.utc).isoformat(),
                    feed_collectors=[c for c in plan['feed_collectors'] if c != 'lan_ping'])
    payload = (json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    target = folder / (job_id + '.plan.json')
    with _manifest_directory(folder) as folder_fd:
        pending = '.plan-' + uuid4().hex + '.tmp'
        source = folder / pending if folder_fd is None else pending
        fd = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0),
                     0o600, dir_fd=folder_fd)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                if folder_fd is None:
                    os.rename(source, target)  # Windows rejects an existing destination.
                else:
                    os.link(source, target.name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
            except FileExistsError:
                # Concurrent POSIX publishers can briefly observe both links to a
                # just-published manifest. Compare bytes only; never write that file.
                with _open_input(target, allow_links=True) as (existing, _):
                    if existing.read(len(payload) + 1) != payload:
                        raise FileExistsError('本批次已有不同的采集计划文件') from None
        finally:
            try:
                os.unlink(source, dir_fd=folder_fd)
            except FileNotFoundError:
                pass
    return target
