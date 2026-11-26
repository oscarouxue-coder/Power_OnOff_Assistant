"""Open a local operator's channel log through the Windows file association."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import uuid

from src.models.capabilities import CapabilitySpec, object_schema
from src.models.qt_log_history import (ArchivedLogFile, HistoryMaterialBatchSummary, HistoryMaterialBatchTarget,
                                      HistoryMaterialChannelResult, HistoryMaterialSummary, HistoryMaterialTarget,
                                      SavedMaterialReport, SavedMaterialReports)
from src.services.capability_registry import CapabilityRegistry
from src.services.power_test_log_service import latest_power_test_result_log
from src.services.project_store import ProjectStore, atomic_json
from src.services.qt_log_history import job_database_path


POWER_HISTORY_CAPABILITIES = frozenset(('aging.start', 'pipeline.start'))


def _launch(path):
    if path.resolve() != path or not path.is_file():
        raise ValueError('日志文件已移动、重定向或不再存在')
    try:
        os.startfile(str(path))
    except OSError as error:
        raise ValueError('Windows 无法打开日志，请检查文件或 .log 关联程序') from error
    return path


def open_channel_log(context, number, kind, *, run_root=None, session=None):
    if type(number) is not int or not 1 <= number <= 16 or kind not in ('power', 'wifi'):
        raise ValueError('请选择有效的日志类型及通道')
    ProjectStore._validate_paths(context)
    if run_root is not None and (run_root.parent != context.root / 'runs' or run_root.resolve() != run_root):
        raise ValueError('运行日志目录不属于本项目')
    tool_root = (run_root or context.working_root) / 'Auto_power_on_off_tool'
    directory = tool_root / 'test_results' / f'device_{number}'
    if directory.resolve() != directory:
        raise ValueError('通道结果目录已重定向，未打开日志')

    if kind == 'wifi':
        if session is None:
            raise ValueError('暂无本次 WiFi 日志。当前通道没有可查看的开关机执行尝试')
        if session.request.tool_root != tool_root:
            raise ValueError('WiFi 日志的运行批次已变化，请重新查看')
        path = session.current_wifi_log(number)
        if path is None:
            raise ValueError('该通道本次执行尝试尚未生成 WiFi 日志')
        if not path.name.startswith(f'device_{number}_wifi_'):
            raise ValueError('WiFi 日志与所选通道不符，请重新查看')
    else:
        path = latest_power_test_result_log(tool_root, number)
        if path is None:
            raise ValueError('该通道暂无开关机运行日志')

    if path.parent != directory or path.suffix.lower() != '.log' or path.resolve() != path:
        raise ValueError('日志路径与所选项目、批次或通道不符，未打开')
    return _launch(path)


def _history_directories(context, job_id, record, *, summary=False):
    """Bind the job's original channels to its project-owned run snapshot."""
    database = job_database_path(context)
    if not database.is_file():
        raise ValueError('该项目的任务历史库不存在')
    if summary:
        # Even SQLite mode=ro can create WAL sidecars. The original job store
        # uses the rollback journal; never open an unexpected WAL for summary.
        if database.stat().st_nlink > 1:
            raise ValueError('任务历史库不是独立文件，未读取留存资料')
        with database.open('rb') as source:
            source.seek(18)
            if source.read(2) == b'\x02\x02':
                raise ValueError('任务历史库采用 WAL 格式，未打开数据库')
    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=.25)) as connection:
            row = connection.execute('SELECT capability,payload FROM jobs WHERE id=?', (job_id,)).fetchone()
    except sqlite3.Error as error:
        raise ValueError('暂时无法读取任务记录，请稍后重试') from error
    if row is None or row[0] not in POWER_HISTORY_CAPABILITIES:
        raise ValueError('此任务不属于当前项目的开关机批次')
    try:
        arguments = json.loads(row[1])['arguments']
        channels = tuple(arguments['channel_ids'])
        tasks = arguments.get('tasks', ())
        if not channels or any(type(n) is not int or not 1 <= n <= 16 for n in channels):
            raise ValueError('通道记录无效')
        if row[0] == 'pipeline.start' and ('legacy_power_test' not in tasks or not isinstance(tasks, list)):
            raise ValueError('全流程未包含开关机测试')
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise ValueError('该任务没有有效的开关机子任务或通道记录') from error

    run_id = (record or {}).get('run_id')
    if (not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{32}', run_id)
            or record.get('project_id') != context.identity.project_id or record.get('operation') != row[0]):
        raise ValueError('该任务缺少本项目的运行快照')
    run = context.root / 'runs' / run_id
    manifest = run / 'run.json'
    if record.get('_path') != manifest or manifest.resolve() != manifest:
        raise ValueError('运行快照路径已变化或重定向')
    try:
        if summary:
            if manifest.stat().st_nlink > 1:
                raise ValueError('运行快照不是独立文件')
            with manifest.open('rb') as source:
                raw = source.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                raise ValueError('运行快照超出读取上限')
            data = json.loads(raw.decode('utf-8'))
        else:
            data = json.loads(manifest.read_text(encoding='utf-8'))
        matches = (data['owner'], data['project_id'], data['run_id'], data['operation'])
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ValueError('运行快照记录不存在或无法读取') from error
    if matches != (job_id, context.identity.project_id, run_id, row[0]):
        raise ValueError('任务与运行快照身份不符')
    root = run / 'Auto_power_on_off_tool/test_results'
    if root.resolve() != root:
        raise ValueError('批次结果目录已重定向')
    return {root / f'device_{n}': n for n in sorted(set(channels))}


def _history_file_type(name, number):
    match = re.fullmatch(fr'device_{number}_(command_results|wifi)_[^\\/:\r\n]+\.log', name)
    return match[1] if match else None


def history_result_files(context, job_id, record):
    files = []
    for directory, number in _history_directories(context, job_id, record).items():
        if directory.resolve() != directory:
            raise ValueError('批次通道目录已重定向')
        if not directory.is_dir():
            continue
        with os.scandir(directory) as entries:
            for item in sorted(entries, key=lambda entry: entry.name, reverse=True):
                kind = _history_file_type(item.name, number)
                if kind and item.is_file(follow_symlinks=False):
                    title = '开关机结果' if kind == 'command_results' else 'WiFi 记录'
                    files.append(ArchivedLogFile(directory / item.name, f'CH{number:02d} · {title} · {item.name}',
                                                 number, record['run_id'], kind))
    return tuple(files)


def open_history_result_file(context, job_id, record, path):
    directories = _history_directories(context, job_id, record)
    number = directories.get(path.parent) if isinstance(path, Path) else None
    if number is None or not _history_file_type(path.name, number):
        raise ValueError('该文件不属于选定批次及通道')
    _launch(path)
    return number


_WIFI_HEADER = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{6}) '
                          r'\[(INFO|DEBUG|WARN|WARNING|ERROR|CRITICAL|SUCCESS)\] '
                          r'\[WiFi\] 通道(\d{1,2}) 第(\d{1,9})轮(?: |$)')


def _material_observation(kind, line, channel):
    # Result files can contain command output and credentials. Only project
    # known record markers; never copy arbitrary bodies into the summary.
    if kind == 'command_results' and re.fullmatch(fr'通道 {channel} ping 通', line):
        return '时间未知', '原文记录 Ping 通；不代表实时连通或设备在线'
    if kind == 'wifi':
        match = _WIFI_HEADER.match(line)
        if match and int(match[3]) == channel:
            try:
                datetime.strptime(match[1], '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                return None
            return match[1] + '（原日志本地时间）', f'第{int(match[4])}轮，记录等级 {match[2]}；业务结果未知'
    return None


def _material_names(target):
    names = (('command_results', '开关机结果', target.power_name), ('wifi', 'WiFi 记录', target.wifi_name))
    if not any(name for _, _, name in names) or any(
            name and _history_file_type(name, target.channel) != kind for kind, _, name in names):
        raise ValueError('留存文件与所选批次或通道不符')
    return names


def _summarize_materials(args, binding):
    from src.services.qt_archived_logs import _read_page

    context, record, stop = binding
    target = HistoryMaterialTarget(**args)
    if stop.is_set():
        raise InterruptedError()
    if (context.identity.project_id != target.project_id or not record
            or record.get('run_id') != target.run_id):
        raise ValueError('项目或选定批次已变化，未读取留存资料')
    directories = _history_directories(context, target.job_id, record, summary=True)
    directory = next((path for path, number in directories.items() if number == target.channel), None)
    if directory is None:
        raise ValueError('该通道不属于所选批次，未读取留存资料')
    names = _material_names(target)
    lines = [f'项目 {target.project_id}\n任务 {target.job_id}\n批次 {target.run_id}\nCH{target.channel:02d}',
             '仅汇总选定的留存文件末页（每份最多 120 行 / 128 KiB），不代表实时状态。'
             '\n引用格式：文件名@页首字节偏移:页内行号；正文不展开。']
    read = missing = failed = 0
    for kind, title, name in names:
        if stop.is_set():
            raise InterruptedError()
        if not name:
            missing += 1
            lines.append(title + ' · 缺少已列出的留存文件')
            continue
        path = directory / name
        try:
            if path.resolve() != path or path.is_symlink():
                raise ValueError('文件已重定向')
            try:
                info = path.stat()
            except FileNotFoundError:
                missing += 1
                lines.append(f'{title} · {name} · 文件缺失')
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
                raise ValueError('不是独立普通结果文件')
            page = _read_page(path, None, target.project_id)
        except (OSError, ValueError, RuntimeError):
            failed += 1
            lines.append(f'{title} · {name} · 无法读取')
            continue
        if stop.is_set():
            raise InterruptedError()
        read += 1
        start = page.next_cursor.offset if page.next_cursor else 0
        observations = []
        for index, entry in enumerate(page.entries, 1):
            if ('跨页长行片段' in page.note or
                    (index == len(page.entries) and '最后一行可能仍在写入' in page.note)):
                continue
            observation = _material_observation(kind, entry.message, target.channel)
            if observation:
                observations.append((index, *observation))
        lines.append(f'{title} · {name} · 已读取 {len(page.entries)} 行，明确标记 {len(observations)} 条'
                     + ('（有更早内容未读取）' if page.next_cursor else '')
                     + ('\n' + page.note if page.note else ''))
        for index, stamp, observation in observations[-6:]:
            lines.append(f'引用 {name}@{start}:{index} · {stamp} · {observation}')
        if not observations:
            lines.append('本页没有可引用的明确观察；未展开原文。')
        elif len(observations) > 6:
            lines.append(f'其余 {len(observations) - 6} 条明确标记未展开。')
    if stop.is_set():
        raise InterruptedError()
    lines.append(f'汇总结果：读取 {read} 份，缺失 {missing} 份，无法读取 {failed} 份。'
                 '\n以上仅为留存记录；故障原因及当前设备状态未知。')
    return HistoryMaterialSummary(target, '\n\n'.join(lines), read, missing, failed)


_SUMMARY_ID = 'history.material_summary'
_SUMMARY_REGISTRY = CapabilityRegistry()
_SUMMARY_FIELDS = {key: dict(type='string', minLength=1, maxLength=128)
                   for key in ('project_id', 'job_id', 'run_id')}
_SUMMARY_FIELDS.update(channel=dict(type='integer', minimum=1, maximum=16),
                       power_name=dict(type='string', maxLength=255), wifi_name=dict(type='string', maxLength=255))
_SUMMARY_REGISTRY.register(CapabilitySpec(_SUMMARY_ID, '汇总选定通道留存资料', '本机只读取证结果',
    object_schema(_SUMMARY_FIELDS, tuple(_SUMMARY_FIELDS)), _summarize_materials, sources=('gui',)))


def summarize_history_materials(context, record, target, stop):
    args = asdict(target)
    spec = _SUMMARY_REGISTRY.validate(_SUMMARY_ID, args)
    return spec.handler(args, (context, record, stop))


_MATERIAL_READ_WORKERS = 2


def summarize_history_materials_batch(context, record, target, stop):
    """One finite selected set, read in fixed pairs by the original reader."""
    if (not isinstance(target, HistoryMaterialBatchTarget) or not isinstance(target.channels, tuple)
            or not 2 <= len(target.channels) <= 16
            or context.identity.project_id != target.project_id or not record
            or record.get('run_id') != target.run_id):
        raise ValueError('项目、批次或选定通道范围不符，未读取留存资料')
    seen = set()
    for row in target.channels:
        if (not isinstance(row, HistoryMaterialTarget)
                or (row.project_id, row.job_id, row.run_id) != (target.project_id, target.job_id, target.run_id)):
            raise ValueError('选定通道不属于同一项目及批次')
        _SUMMARY_REGISTRY.validate(_SUMMARY_ID, asdict(row))
        _material_names(row)
        if row.channel in seen:
            raise ValueError('选定通道重复，未读取留存资料')
        seen.add(row.channel)
    if not stop.is_set():
        directories = _history_directories(context, target.job_id, record, summary=True)
        if not seen.issubset(set(directories.values())):
            raise ValueError('选定通道不属于原批次，未读取留存资料')
    def read_one(row):
        if stop.is_set():
            return HistoryMaterialChannelResult(row, 'cancelled')
        try:
            summary = summarize_history_materials(context, record, row, stop)
            if not isinstance(summary, HistoryMaterialSummary) or summary.target != row:
                raise ValueError('本通道汇总回执不符')
        except InterruptedError:
            return HistoryMaterialChannelResult(row, 'cancelled')
        except Exception:
            return HistoryMaterialChannelResult(row, 'cancelled' if stop.is_set() else 'failed')
        return HistoryMaterialChannelResult(row, 'completed', summary)

    if stop.is_set():
        return HistoryMaterialBatchSummary(target, tuple(HistoryMaterialChannelResult(row, 'cancelled')
                                                         for row in target.channels))
    results = []
    # This pool belongs only to this read request. Each reader opens its own
    # file/SQLite handles; fixed pairs avoid queuing unstarted channels on
    # cancellation. Join all started reads before the result can be delivered.
    with ThreadPoolExecutor(max_workers=_MATERIAL_READ_WORKERS, thread_name_prefix='qt-local-material') as pool:
        for offset in range(0, len(target.channels), _MATERIAL_READ_WORKERS):
            if stop.is_set():
                results.extend(HistoryMaterialChannelResult(row, 'cancelled') for row in target.channels[offset:])
                break
            pair = target.channels[offset:offset + _MATERIAL_READ_WORKERS]
            pending = tuple(pool.submit(read_one, row) for row in pair)
            results.extend(item.result() for item in pending)
    return HistoryMaterialBatchSummary(target, tuple(results))


_REPORT_LIMIT = 64
_REPORT_BYTES = 512 * 1024


def _report_scope(context, record, job):
    run = record.get('run_id')
    if (record.get('project_id') != context.identity.project_id or record.get('owner') != job
            or not isinstance(run, str) or not run or len(run) > 128
            or not isinstance(job, str) or not job or len(job) > 128):
        raise ValueError('项目、任务或历史批次记录不符，未访问保存报告')
    ProjectStore._validate_paths(context)
    directory = context.history / 'material_reports' / hashlib.sha256(
        (job + '\0' + run).encode('utf-8')).hexdigest()
    if directory.resolve() != directory or directory.is_symlink():
        raise ValueError('留存报告目录已重定向')
    return run, directory


def material_report_snapshot(context, record, summary):
    """Only call with an actual completed history-reader result, never UI text."""
    target = summary.target
    run, _ = _report_scope(context, record, target.job_id)
    if (target.project_id, target.run_id) != (context.identity.project_id, run):
        raise ValueError('汇总回执与项目或历史批次不符')
    if isinstance(summary, HistoryMaterialBatchSummary):
        if not summary.matches(target) or not summary.completed_count:
            raise ValueError('没有已核对通道可保存')
        channels = tuple(row.channel for row in target.channels)
    elif isinstance(summary, HistoryMaterialSummary):
        channels = (target.channel,)
    else:
        raise ValueError('没有有效汇总回执')
    state = record.get('state')
    if state not in ('succeeded', 'failed', 'stopped', 'unknown', 'skipped'):
        raise ValueError('仅可保存已记录终态的历史批次报告')
    try:
        historical_at = datetime.fromtimestamp(record['updated_at']).astimezone().isoformat(timespec='seconds')
    except (KeyError, OSError, TypeError, ValueError, OverflowError) as error:
        raise ValueError('历史批次时间无法核实') from error
    return SavedMaterialReport(uuid.uuid4().hex, target.project_id, target.job_id, run, channels,
        datetime.now().astimezone().isoformat(timespec='seconds'), state, historical_at, '', summary.text)


def _report_entries(directory):
    if not directory.exists():
        return ()
    if not directory.is_dir():
        raise ValueError('留存报告目录无法读取')
    entries = []
    with os.scandir(directory) as items:
        for item in items:
            # Bound the directory examination, including unexpected files.
            if len(entries) >= _REPORT_LIMIT:
                raise ValueError('本批次保存报告数量超出查看上限')
            entries.append(item.name)
    return tuple(entries)


def _report_digest(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def _save_material_report(args, binding):
    context, record, snapshot, stop = binding
    run, directory = _report_scope(context, record, snapshot.job_id)
    if (snapshot.project_id, snapshot.run_id) != (context.identity.project_id, run):
        raise ValueError('报告与历史批次不符')
    if stop.is_set():
        raise InterruptedError()
    if len(_report_entries(directory)) >= _REPORT_LIMIT:
        raise ValueError('本批次保存报告已达上限，未覆盖原报告')
    if not re.fullmatch(r'[a-f0-9]{32}', snapshot.report_id) or snapshot.saved_at:
        raise ValueError('汇总回执无效')
    report = replace(snapshot, saved_at=datetime.now().astimezone().isoformat(timespec='seconds'))
    payload = asdict(report)
    if len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) > _REPORT_BYTES // 2:
        raise ValueError('报告超出保存上限')
    path = directory / (report.report_id + '.json')
    if path.exists() or path.is_symlink() or path.resolve() != path:
        raise ValueError('报告已保存或路径不符，未覆盖原报告')
    if stop.is_set():
        raise InterruptedError()
    atomic_json(path, dict(version=1, report=payload, digest=_report_digest(payload)))
    return report


def _read_material_reports(args, binding):
    context, record, stop = binding
    job = args['job_id']
    run, directory = _report_scope(context, record, job)
    reports, invalid = [], 0
    for name in _report_entries(directory):
        if stop.is_set():
            raise InterruptedError()
        path = directory / name
        try:
            if not re.fullmatch(r'[a-f0-9]{32}\.json', name) or path.resolve() != path or path.is_symlink():
                raise ValueError()
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1 or info.st_size > _REPORT_BYTES:
                raise ValueError()
            with path.open('rb') as stream:
                raw = stream.read(_REPORT_BYTES + 1)
            if len(raw) > _REPORT_BYTES:
                raise ValueError()
            envelope = json.loads(raw.decode('utf-8'))
            payload = envelope['report']
            if envelope['version'] != 1 or envelope['digest'] != _report_digest(payload):
                raise ValueError()
            payload['channels'] = tuple(payload['channels'])
            report = SavedMaterialReport(**payload)
            if ((report.report_id, report.project_id, report.job_id, report.run_id) !=
                    (name[:-5], context.identity.project_id, job, run)
                    or not 1 <= len(report.channels) <= 16 or len(set(report.channels)) != len(report.channels)
                    or any(type(n) is not int or not 1 <= n <= 16 for n in report.channels)
                    or not isinstance(report.text, str) or not report.text
                    or report.historical_state not in ('succeeded', 'failed', 'stopped', 'unknown', 'skipped')):
                raise ValueError()
            for stamp in (report.generated_at, report.historical_at, report.saved_at):
                if datetime.fromisoformat(stamp).tzinfo is None:
                    raise ValueError()
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            invalid += 1
            continue
        reports.append(report)
    if stop.is_set():
        raise InterruptedError()
    return SavedMaterialReports(run, tuple(sorted(reports, key=lambda row: (row.saved_at, row.report_id), reverse=True)), invalid)


_REPORT_FIELDS = {key: dict(type='string', minLength=1, maxLength=128)
                  for key in ('project_id', 'job_id')}
_REPORT_REGISTRY = CapabilityRegistry()
_REPORT_REGISTRY.register(CapabilitySpec('history.material_report_save', '保存已生成留存报告', '本机历史报告',
    object_schema(dict(_REPORT_FIELDS, run_id=dict(type='string', minLength=1, maxLength=128),
                       report_id=dict(type='string', minLength=32, maxLength=32)),
                  ('project_id', 'job_id', 'run_id', 'report_id')), _save_material_report, sources=('gui',)))
_REPORT_REGISTRY.register(CapabilitySpec('history.material_reports', '查看已保存留存报告', '本机历史报告',
    object_schema(_REPORT_FIELDS, tuple(_REPORT_FIELDS)), _read_material_reports, sources=('gui',)))


def save_material_report(context, record, snapshot, stop):
    args = {key: getattr(snapshot, key) for key in ('project_id', 'job_id', 'run_id', 'report_id')}
    spec = _REPORT_REGISTRY.validate('history.material_report_save', args)
    return spec.handler(args, (context, record, snapshot, stop))


def read_material_reports(context, record, job, stop):
    args = dict(project_id=context.identity.project_id, job_id=job)
    spec = _REPORT_REGISTRY.validate('history.material_reports', args)
    return spec.handler(args, (context, record, stop))
