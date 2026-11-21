"""Bounded, read-only access to the selected project's original job database."""
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from heapq import nlargest
import sqlite3

from src.models.qt_log_history import (ChannelHistoryEvent, HistoryEventFilter, HistoryJob, HistoryPage, LegacyRun,
    job_event_channel, job_event_level, job_event_message, job_event_view)
from src.services.project_store import ProjectStore


JOBS_PER_PAGE = 50
EVENTS_PER_PAGE = 60
MAX_MESSAGE_CHARS = 8192

_LEGACY_STATES = {'succeeded': '成功', 'failed': '失败', 'skipped': '未执行', 'stopped': '已停止',
                  'unchecked': '已执行，未配置结果校验', 'unknown': '结果未知，待核实',
                  'running': '历史运行记录，待核实', 'prepared': '历史准备记录，待核实',
                  'queued': '历史排队记录，待核实', 'stopping': '历史停止请求，待核实'}


def _valid_time(value):
    # Unix timestamps representable between years 1 and 9999.
    return type(value) in (int, float) and -62135596800 <= value <= 253402300799


def _legacy_time(value):
    if _valid_time(value):
        try:
            return datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, OverflowError, OSError):
            pass
    return '—'


def read_legacy_runs(status, project_id, before=None):
    """Page the original GUI ledger by immutable creation time and owner."""
    prefix = 'gui:' + project_id + ':'
    if before is not None and not (isinstance(before, tuple) and len(before) == 2 and _valid_time(before[0])
                                   and isinstance(before[1], str) and before[1].startswith(prefix)):
        raise ValueError('运行记录分页位置无效，请重新读取最新记录')
    # The lock protects the service dictionary and mutable state fields. Search the
    # shallow snapshot outside the lock, then copy just the selected records.
    with status.lock:
        records = status.records.copy()

    def keys():
        for owner, record in records.items():
            if owner.startswith(prefix) and record.get('project_id') == project_id:
                created = record.get('created_at')
                key = (created if _valid_time(created) else 0, owner)
                if before is None or key < before:
                    yield key

    positions = nlargest(JOBS_PER_PAGE + 1, keys())
    with status.lock:
        page = [records[owner].copy() for _, owner in positions[:JOBS_PER_PAGE]]
    entries = []
    for row in page:
        state = _LEGACY_STATES.get(row['state'], '状态未知')
        if row['state'] == 'unknown' and row.get('reconciled') is True:
            state = '已核实（原结果未知）'
        entries.append(LegacyRun(str(row.get('run_id') or '—'), str(row.get('operation') or '—'), state,
                                 str(row.get('revision') or '—'), _legacy_time(row.get('started_at')),
                                 _legacy_time(row.get('finished_at'))))
    return HistoryPage(tuple(entries), positions[JOBS_PER_PAGE - 1] if len(positions) > JOBS_PER_PAGE else None)


def _cursor(before):
    if before is None:
        return 2**63 - 1
    if type(before) is not int or not 0 < before < 2**63:
        raise ValueError('历史页边界无效，请重新打开任务历史')
    return before


def job_database_path(context):
    ProjectStore._validate_paths(context)
    database = context.history / 'ai/business/capability_jobs.sqlite3'
    if database.resolve() != database:
        raise ValueError('任务历史数据库路径指向项目外或重定向位置')
    return database


def _event_preview(message, keyword):
    if len(message) <= MAX_MESSAGE_CHARS:
        return message
    head = message[:MAX_MESSAGE_CHARS]
    if keyword and keyword not in head.casefold():
        folded = message.casefold()
        offset = folded.find(keyword)
        if offset >= 0:
            # Unicode folding can expand one source character into several.
            if len(folded) != len(message):
                folded_index = 0
                for index, character in enumerate(message):
                    folded_index += len(character.casefold())
                    if folded_index > offset:
                        offset = index
                        break
            start = max(0, offset - min(100, max(0, MAX_MESSAGE_CHARS - len(keyword))))
            return '…' + message[start:start + MAX_MESSAGE_CHARS] + '\n[命中位置节选，原数据库保留原文]'
    return head + '\n[记录过长，本页仅显示前 8192 个字符，原数据库保留原文]'


def read_log_history(context, before, job_id=None, filters=HistoryEventFilter(), *, closing_event=None):
    def check_cancelled():
        if closing_event is not None and closing_event.is_set():
            raise ValueError('已取消任务历史读取')

    check_cancelled()
    boundary = _cursor(before)
    database = job_database_path(context)
    if not database.is_file():
        check_cancelled()
        return HistoryPage((), None)
    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=.25)) as connection:
            check_cancelled()
            if closing_event is not None:
                connection.set_progress_handler(closing_event.is_set, 1000)
            if job_id is None:
                rows = connection.execute('SELECT rowid,id,capability,state,created FROM jobs '
                    'WHERE rowid < ? ORDER BY rowid DESC LIMIT ?', (boundary, JOBS_PER_PAGE + 1)).fetchall()
                entries = tuple(HistoryJob(identifier, capability, state,
                    datetime.fromtimestamp(created).strftime('%Y-%m-%d %H:%M:%S'))
                    for _, identifier, capability, state, created in rows[:JOBS_PER_PAGE])
                check_cancelled()
                return HistoryPage(entries, rows[JOBS_PER_PAGE - 1][0] if len(rows) > JOBS_PER_PAGE else None)
            job = connection.execute('SELECT 1 FROM jobs WHERE id = ?', (job_id,)).fetchone()
            check_cancelled()
            if job is None:
                raise ValueError('此任务不属于当前项目的历史库')
            keyword = filters.keyword.casefold()
            project_name = context.identity.name

            def matches(stage, message):
                return ((not filters.level or job_event_level(stage) == filters.level) and
                        (filters.channel is None or job_event_channel(stage, message) == filters.channel) and
                        (not keyword or keyword in (job_event_message(job_id, stage, message) + project_name).casefold()))

            condition = ''
            if keyword or filters.level or filters.channel is not None:
                connection.create_function('matches_history_event', 2, matches)
                condition = 'AND matches_history_event(stage, message) '
            rows = connection.execute('SELECT id,created,stage,message '
                'FROM job_events WHERE job_id = ? AND id < ? AND message != ? '
                + condition + 'ORDER BY id DESC LIMIT ?', (job_id, boundary, '', EVENTS_PER_PAGE + 1))
            entries = []
            last_id = next_cursor = None
            for identifier, created, stage, message in rows:
                if len(entries) == EVENTS_PER_PAGE:
                    next_cursor = last_id
                    break
                entry = job_event_view(context.identity.project_id, project_name, job_id, created, stage,
                                       message, historical=True)
                if len(message) > MAX_MESSAGE_CHARS:
                    preview = _event_preview(message, keyword)
                    entry = replace(entry, message=job_event_message(job_id, stage, preview))
                entries.append(entry)
                last_id = identifier
    except sqlite3.Error as error:
        if closing_event is not None and closing_event.is_set():
            raise ValueError('已取消任务历史读取') from error
        raise ValueError('项目历史暂时无法读取，请核对数据库后重试') from error
    check_cancelled()
    return HistoryPage(tuple(reversed(entries)), next_cursor)


def read_channel_history(context, job_id, number, before):
    """Page through one admitted channel's original retry and failure events."""
    boundary = _cursor(before)
    database = job_database_path(context)
    if not database.is_file():
        raise ValueError('当前项目没有可读取的开关机批次任务库')
    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=.25)) as connection:
            if connection.execute('SELECT 1 FROM jobs WHERE id = ?', (job_id,)).fetchone() is None:
                raise ValueError('此批次不属于当前项目的历史库')
            rows = connection.execute('''
                WITH history AS (
                    SELECT id, CASE WHEN json_valid(message) THEN message END AS body
                    FROM job_events WHERE job_id = ? AND id < ? AND stage = 'history'
                )
                SELECT id, json_extract(body, '$.cycle'), json_extract(body, '$.status'),
                    substr(json_extract(body, '$.detail'), 1, ?)
                FROM history WHERE json_type(body, '$.channel') = 'integer'
                    AND json_extract(body, '$.channel') = ?
                    AND json_type(body, '$.cycle') = 'integer'
                    AND json_type(body, '$.status') = 'text'
                    AND json_type(body, '$.detail') = 'text'
                ORDER BY id DESC LIMIT ?
                ''', (job_id, boundary, MAX_MESSAGE_CHARS + 1, number, EVENTS_PER_PAGE + 1)).fetchall()
    except sqlite3.Error as error:
        raise ValueError('通道历史暂时无法读取，请稍后重试') from error
    entries = tuple(ChannelHistoryEvent(cycle, status,
        detail[:MAX_MESSAGE_CHARS] + ('…（完整内容见任务日志）' if len(detail) > MAX_MESSAGE_CHARS else ''))
        for _, cycle, status, detail in reversed(rows[:EVENTS_PER_PAGE]))
    return HistoryPage(entries, rows[EVENTS_PER_PAGE - 1][0] if len(rows) > EVENTS_PER_PAGE else None)
