"""Snapshot original import inputs before any conversion; original paths are read-only."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import shutil
import sqlite3
import uuid

from src.services.project_store import atomic_json

CONFIG_SUFFIXES = frozenset(('.ini', '.json', '.txt', '.csv', '.xlsx', '.xls'))


def legacy_root(config):
    config = Path(config)
    if config.name.lower() == 'config':
        config = config.parent
    if config.name.lower() == 'auto_power_on_off_tool':
        config = config.parent
    return config


def _files(root):
    pending = [root]
    while pending:
        path = pending.pop()
        if path.is_symlink() or path.resolve() != path.absolute():
            raise ValueError('备份来源含链接或重定向目录，导入未执行')
        if path.is_dir():
            pending.extend(path.iterdir())
        elif path.is_file():
            yield path


def _digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def backup_import(config, destination, emit):
    from src.services.ai_project_store import project_directory
    source = legacy_root(config)
    backup = Path(destination) / 'backups' / 'imports' / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex)
    backup.mkdir(parents=True)
    manifest = dict(state='preparing', created_at=datetime.now(timezone.utc).isoformat(),
                    source=str(source), files=[])
    emit('[项目导入] 开始备份原始输入：' + str(backup))
    try:
        discovered = list(_files(Path(config)))
        files = [path for path in discovered if path.suffix.lower() in CONFIG_SUFFIXES]
        manifest['excluded_non_configuration'] = [path.relative_to(config).as_posix()
                                                   for path in discovered if path not in files]
        pairs = [(p, Path('config') / p.relative_to(config), 'bytes') for p in files]
        history = project_directory(source)
        for name in ('diagnostics.sqlite3', 'dingtalk.json', 'feishu.json'):
            path = history / name
            if path.exists():
                if path.is_symlink() or path.resolve() != path.absolute():
                    raise ValueError('历史或接入配置包含链接，导入未执行')
                pairs.append((path, Path('history') / name,
                              'sqlite_snapshot' if name.endswith('.sqlite3') else 'bytes'))
        original_hashes = {}
        for origin, relative, kind in pairs:
            target = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if kind == 'sqlite_snapshot':
                incoming = sqlite3.connect(origin.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
                outgoing = sqlite3.connect(str(target))
                try:
                    incoming.backup(outgoing)
                    if outgoing.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                        raise ValueError('历史数据库备份校验失败')
                finally:
                    outgoing.close()
                    incoming.close()
            else:
                before = _digest(origin)
                shutil.copy2(origin, target)
                if _digest(origin) != before or _digest(target) != before:
                    raise ValueError('备份期间原始输入已变化，导入未执行')
                original_hashes[origin] = before
            manifest['files'].append(dict(path=relative.as_posix(), kind=kind,
                                          size=target.stat().st_size, sha256=_digest(target)))
        current = {path for path in _files(Path(config)) if path.suffix.lower() in CONFIG_SUFFIXES}
        if current != set(files) or any(_digest(p) != value for p, value in original_hashes.items()):
            raise ValueError('备份期间来源文件集合或内容已变化，导入未执行')
        manifest['state'] = 'complete'
        atomic_json(backup / 'manifest.json', manifest)
    except BaseException:
        manifest['state'] = 'failed'
        try:
            atomic_json(backup / 'manifest.json', manifest)
        finally:
            emit('[项目导入] 备份失败，转换未执行；原目录未改写，目标备份保留：' + str(backup))
        raise
    emit('[项目导入] 原始备份及SHA256校验完成：' + str(backup))
    return backup
