"""Open a local operator's channel log through the Windows file association."""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3

from src.models.qt_log_history import ArchivedLogFile
from src.services.power_test_log_service import latest_power_test_result_log
from src.services.project_store import ProjectStore
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


def _history_directories(context, job_id, record):
    """Bind the job's original channels to its project-owned run snapshot."""
    database = job_database_path(context)
    if not database.is_file():
        raise ValueError('该项目的任务历史库不存在')
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
                    files.append(ArchivedLogFile(directory / item.name, f'CH{number:02d} · {title} · {item.name}'))
    return tuple(files)


def open_history_result_file(context, job_id, record, path):
    directories = _history_directories(context, job_id, record)
    number = directories.get(path.parent) if isinstance(path, Path) else None
    if number is None or not _history_file_type(path.name, number):
        raise ValueError('该文件不属于选定批次及通道')
    _launch(path)
    return number
