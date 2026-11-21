"""Read bounded pages from original UTF-8 workspace and serial files."""
import json
import os
from pathlib import Path
import re

from src.models.qt_log_history import ArchivedLogCursor, ArchivedLogFile, ArchivedLogPage
from src.models.workbench_presentation import LogView
from src.services.project_store import ProjectStore


MAX_PAGE_BYTES = 128 * 1024
MAX_PAGE_LINES = 120
SERIAL_NAME = re.compile(r'(?P<vlan>[^\r\n\\/:]+)_(?P<port>COM[1-9]\d*)_(?P<date>\d{8})\.log$', re.IGNORECASE)
PROJECT_LOGS = (
    ('', re.compile(r'line_check_(\d{8}_\d{6})\.log', re.ASCII), '主执行日志'),
    ('resource_monitor', re.compile(r'transport_history_(\d{8}_\d{6}_\d{6})\.jsonl', re.ASCII), '资源监测'),
)


def _project_log_directories(context):
    ProjectStore._validate_paths(context)
    for subdirectory, pattern, title in PROJECT_LOGS:
        directory = context.root / 'logs/main' / subdirectory
        if directory.resolve() != directory:
            raise ValueError('项目主日志目录已重定向，请核对项目路径')
        yield directory, pattern, title


def project_log_files(context):
    found = []
    for directory, pattern, title in _project_log_directories(context):
        if directory.is_dir():
            with os.scandir(directory) as files:
                for item in files:
                    match = pattern.fullmatch(item.name)
                    if match and item.is_file(follow_symlinks=False):
                        stamp = match[1]
                        found.append((stamp, ArchivedLogFile(directory / item.name, f'{stamp} · {title}')))
    return tuple(entry for _, entry in sorted(found, key=lambda pair: pair[0], reverse=True))


def read_project_log(context, path, cursor):
    if isinstance(path, Path):
        for directory, pattern, _ in _project_log_directories(context):
            if path.parent == directory and pattern.fullmatch(path.name):
                return _read_page(path, cursor, context.identity.project_id)
    raise ValueError('该主日志文件不属于当前项目或目录已变化，请刷新文件列表')


def _serial_roots(context):
    ProjectStore._validate_paths(context)
    default = context.root / 'logs/serial'
    if default.resolve() != default:
        raise ValueError('项目串口归档目录已重定向，请核对项目路径')
    roots = [(default, '项目目录')]
    state = context.root / 'ui/serial.json'
    if state.resolve() != state or state.is_symlink():
        raise ValueError('串口目录状态文件已重定向，请核对项目路径')
    try:
        value = json.loads(state.read_text(encoding='utf-8'))
        path = Path(value['log_dir'])
        if path.is_absolute() and path.name == context.identity.project_id and path.resolve() == path and path.is_dir():
            roots.append((path, '已选目录'))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        pass
    return roots


def serial_log_files(context):
    found = []
    for directory, origin in _serial_roots(context):
        if not directory.is_dir():
            continue
        with os.scandir(directory) as files:
            for item in files:
                match = SERIAL_NAME.fullmatch(item.name)
                if match and item.is_file(follow_symlinks=False):
                    day = match['date']
                    title = f'{day[:4]}-{day[4:6]}-{day[6:]} · {match["vlan"]} / {match["port"]} · {origin}'
                    found.append((day, ArchivedLogFile(directory / item.name, title)))
    return tuple(entry for _, entry in sorted(found, key=lambda row: (row[0], row[1].label), reverse=True))


def read_serial_log(context, path, cursor):
    if (not isinstance(path, Path) or not SERIAL_NAME.fullmatch(path.name)
            or path.parent not in {directory for directory, _ in _serial_roots(context)}):
        raise ValueError('该串口文件不属于当前项目或目录已变化，请刷新文件列表')
    return _read_page(path, cursor, context.identity.project_id)


def read_workspace_log(directory, cursor):
    return _read_page(Path(directory).resolve() / 'workspace.log', cursor)


def _read_page(path, cursor, project_id=''):
    if path.resolve() != path or path.is_symlink():
        raise ValueError('归档日志路径已重定向，未读取')
    try:
        stream = path.open('rb')
    except FileNotFoundError:
        if cursor is None and not project_id:
            return ArchivedLogPage((), None)
        raise ValueError('归档已移走，请重新读取最新日志') from None

    with stream:
        stat = os.fstat(stream.fileno())
        end = stat.st_size
        if cursor is not None:
            if (not isinstance(cursor, ArchivedLogCursor) or not 0 < cursor.offset <= end
                    or (cursor.device, cursor.inode) != (stat.st_dev, stat.st_ino)):
                raise ValueError('日志已替换或截短，请重新读取最新日志')
            end = cursor.offset
        if not end:
            return ArchivedLogPage((), None)
        start = max(0, end - MAX_PAGE_BYTES)
        stream.seek(max(0, start - 1))
        leading_partial = start > 0 and stream.read(1) != b'\n'
        data = stream.read(end - start)
        if len(data) != end - start:
            raise ValueError('读取期间日志被截短，请重新读取最新日志')

    parts = data.split(b'\n')
    ends_with_newline = parts[-1] == b''
    if ends_with_newline:
        parts.pop()
    note = ''
    if leading_partial and len(parts) > 1:
        start += len(parts.pop(0)) + 1
    elif leading_partial:
        # When a very long line spans windows, move the byte boundary past
        # any UTF-8 continuation bytes. The older page receives those bytes.
        prefix = 0
        while prefix < min(3, len(parts[0])) and parts[0][prefix] & 0xc0 == 0x80:
            prefix += 1
        start += prefix
        parts[0] = parts[0][prefix:]
    if len(parts) > MAX_PAGE_LINES:
        start += sum(len(line) + 1 for line in parts[:-MAX_PAGE_LINES])
        parts = parts[-MAX_PAGE_LINES:]
    if (leading_partial and b'\n' not in data.rstrip(b'\n')) or (cursor is not None and not ends_with_newline):
        note = '本页包含跨页长行片段，原文件保留'
    if cursor is None and not ends_with_newline:
        note = '最后一行可能仍在写入，查看最新日志可重新读取' if not note else note + '。最后一行可能仍在写入'
    entries = tuple(LogView('', '', project_id, '', line.removesuffix(b'\r').decode(
        'utf-8-sig' if start == 0 and index == 0 else 'utf-8', errors='replace'), raw=True)
        for index, line in enumerate(parts))
    next_cursor = ArchivedLogCursor(start, stat.st_dev, stat.st_ino) if start else None
    return ArchivedLogPage(entries, next_cursor, note)
