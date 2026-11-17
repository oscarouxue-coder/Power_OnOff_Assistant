"""Versioned project configurations, durable drafts, and non-destructive imports."""
from dataclasses import asdict, replace
import configparser
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import threading
import uuid

from src.core.host_resource_lock import HostResourceLock
from src.models.project import FORMAT_VERSION, PROJECT_FILE, ProjectContext, ProjectIdentity


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def configuration_digest(directory):
    digest = hashlib.sha256()
    directory = Path(directory)
    if directory.is_dir():
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix.lower() not in (".tmp", ".pyc"):
                digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
                digest.update(b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


class ProjectStore:
    def __init__(self, source_root, emit=lambda text: None):
        self.source_root = Path(source_root).resolve()
        self.emit = emit
        self.lock = threading.RLock()
        self.opened = {}
        self.leases = {}
        self.import_backups = {}

    def create(self, directory, name, *, import_directory=None, _configuration_copy=False):
        root = Path(directory).resolve()
        name = str(name).strip()
        if not name or len(name) > 160 or any(c in name for c in "\r\n\0"):
            raise ValueError("项目名称须为1至160个字符")
        if root.exists() and any(root.iterdir()):
            raise ValueError("新项目必须选择空文件夹，以免覆盖已有文件")
        root.mkdir(parents=True, exist_ok=True)
        context = ProjectContext(root, ProjectIdentity(str(uuid.uuid4()), name, ""), self.source_root)
        context.config_dir.mkdir(parents=True)
        try:
            if import_directory is not None:
                incoming = Path(import_directory).resolve()
                candidates = (incoming / "Auto_power_on_off_tool/config", incoming / "config", incoming)
                config = next((p for p in candidates if (p / "test_project_config.ini").is_file()
                               or (p / "network_card_ip.ini").is_file()), None)
                if config is None:
                    raise ValueError("未找到旧项目配置目录")
                if not _configuration_copy:
                    from src.services.project_import_service import backup_import
                    backup = backup_import(config, root, self.emit)
                    self.import_backups[context.identity.project_id] = backup
                    self._copy_config(backup / 'config', context.config_dir)
                else:
                    self._copy_config(config, context.config_dir)
                self._import_assets(context, config)
            else:
                from scripts.create_portable_config import create_portable_config
                # Use the same sanitized defaults as portable delivery, never local credentials.
                create_portable_config(self.source_root / "Auto_power_on_off_tool/config", context.config_dir)
            self._set_name(context.config_dir, name)
            self._commit(context, initial=True)
        except BaseException:
            # Leave user-owned paths untouched; an incomplete new directory is inspectable.
            self.emit("[项目管理] 创建失败，未改写原项目；目标目录保留供检查")
            raise
        self.emit("[项目管理] 已创建项目：" + name)
        return self.open(root)

    @staticmethod
    def _copy_config(source, target):
        target.mkdir(parents=True, exist_ok=True)
        for path in Path(source).iterdir():
            if path.is_symlink():
                raise ValueError("配置目录含链接，不能作为项目配置导入")
            if path.is_file() and path.suffix.lower() in (".ini", ".json", ".txt", ".csv", ".xlsx", ".xls"):
                shutil.copy2(path, target / path.name)

    @staticmethod
    def _set_name(config, name):
        path = Path(config) / "test_project_config.ini"
        parser = configparser.RawConfigParser()
        parser.optionxform = str
        parser.read(path, encoding="utf-8-sig")
        if not parser.has_section("project_info"):
            parser.add_section("project_info")
        parser.set("project_info", "project_name", name)
        with path.open("w", encoding="utf-8") as stream:
            parser.write(stream)

    @staticmethod
    def _import_assets(context, source_config):
        from src.models.project import project_root_for
        path = context.config_dir / 'sample_upgrade_settings.ini'
        if not path.exists():
            return
        origin = project_root_for(source_config / 'sample_upgrade_settings.ini')
        if origin is None:
            origin = source_config.parent.parent if source_config.parent.name.lower() == 'auto_power_on_off_tool' else source_config.parent
        parser = configparser.RawConfigParser()
        parser.optionxform = str
        parser.read(path, encoding='utf-8-sig')
        changed = False
        for section in parser.sections():
            for field in ('firmware_path', 'parameter_table_path'):
                raw = parser.get(section, field, fallback='').strip()
                if not raw:
                    continue
                source = Path(raw)
                if not source.is_absolute():
                    source = origin / source
                if field == 'parameter_table_path' and source.is_file():
                    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
                    target = context.root / 'inputs' / (digest + '_' + source.name)
                    target.parent.mkdir(exist_ok=True)
                    shutil.copy2(source, target)
                    value = target.relative_to(context.root).as_posix()
                else:
                    value = str(source)
                parser.set(section, field, value)
                changed = True
        if changed:
            with path.open('w', encoding='utf-8') as stream:
                parser.write(stream)

    @staticmethod
    def _validate_paths(context):
        paths = [context.root / name for name in ('draft', 'revisions', 'history', 'runs', 'ui', 'inputs', 'logs', 'backups')]
        paths.extend((context.config_dir, context.saved_root / 'Auto_power_on_off_tool/config'))
        for expected in paths:
            if expected.resolve() != expected:
                raise ValueError('项目数据目录不能通过链接重定向：' + str(expected.relative_to(context.root)))

    def open(self, directory):
        root = Path(directory).resolve()
        if root.is_file():
            root = root.parent
        import_state = root / 'import_state.json'
        if import_state.exists() and json.loads(import_state.read_text(encoding='utf-8')).get('state') != 'complete':
            raise ValueError('该目录导入未完成；原始备份保留，请先核对导入失败记录')
        value = json.loads((root / PROJECT_FILE).read_text(encoding="utf-8"))
        if type(value.get('format_version')) is not int or value.get("format_version") != FORMAT_VERSION:
            raise ValueError("项目格式版本不受支持，请使用匹配版本的程序")
        identity = ProjectIdentity(**{key: value[key] for key in ("project_id", "name", "revision", "format_version")})
        uuid.UUID(identity.project_id)
        if not re.fullmatch(r'[0-9a-f]{32}', identity.revision):
            raise ValueError("项目配置版本无效")
        with self.lock:
            existing = self.opened.get(identity.project_id)
            if existing is not None:
                if existing.root != root:
                    raise ValueError("该项目身份已从另一目录打开，请使用复制项目创建独立身份")
                return existing
            lease = HostResourceLock(["project:" + identity.project_id], reentrant=False).acquire()
            context = ProjectContext(root, identity, self.source_root)
            try:
                self._validate_paths(context)
                if not (context.saved_root / "Auto_power_on_off_tool/config").is_dir():
                    raise ValueError("项目已保存配置缺失，未使用其它项目配置代替")
                if not context.config_dir.is_dir():
                    self._copy_config(context.saved_root / "Auto_power_on_off_tool/config", context.config_dir)
                context.history.mkdir(exist_ok=True)
            except BaseException:
                lease.close()
                raise
            self.opened[identity.project_id], self.leases[identity.project_id] = context, lease
        self.emit("[项目管理] 已打开：" + identity.name)
        return context

    def dirty(self, context):
        return configuration_digest(context.config_dir) != configuration_digest(
            context.saved_root / "Auto_power_on_off_tool/config")

    def save(self, context):
        with self.lock:
            self._commit(context)
        self.emit("[项目管理] 已保存：" + context.identity.name + "；版本=" + context.identity.revision)

    def _commit(self, context, initial=False):
        self._validate_paths(context)
        path = context.root / PROJECT_FILE
        if not initial:
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            if on_disk["project_id"] != context.identity.project_id or on_disk["revision"] != context.identity.revision:
                raise ValueError("项目已被其它操作修改，请重新打开后核对；当前草稿保留")
        revision = uuid.uuid4().hex
        target = context.root / "revisions" / revision / "Auto_power_on_off_tool/config"
        self._copy_config(context.config_dir, target)
        identity = replace(context.identity, revision=revision)
        atomic_json(path, asdict(identity))
        context.identity = identity

    def discard(self, context):
        # Replace only app-owned draft configs; keep old directory until replacement succeeds.
        destination = context.config_dir
        temporary = destination.with_name("config.restore." + uuid.uuid4().hex)
        previous = destination.with_name("config.previous." + uuid.uuid4().hex)
        self._copy_config(context.saved_root / "Auto_power_on_off_tool/config", temporary)
        destination.rename(previous)
        try:
            temporary.rename(destination)
        except BaseException:
            previous.rename(destination)
            raise
        shutil.rmtree(previous)
        self.emit("[项目管理] 已放弃配置草稿：" + context.identity.name)

    def rename(self, context, name):
        name = str(name).strip()
        if not name or len(name) > 160 or any(c in name for c in "\r\n\0"):
            raise ValueError("项目名称须为1至160个字符")
        self._set_name(context.config_dir, name)
        previous = context.identity
        context.identity = replace(previous, name=name)
        try:
            self.save(context)
        except BaseException:
            context.identity = previous
            raise

    def duplicate(self, context, directory, name=None):
        return self.create(directory, name or context.identity.name + " 副本",
                           import_directory=context.saved_root, _configuration_copy=True)

    def snapshot(self, context):
        """New task data directory; immutable saved config, isolated legacy output paths."""
        self._validate_paths(context)
        run_id = uuid.uuid4().hex
        root = context.root / "runs" / run_id
        self._copy_config(context.saved_root / "Auto_power_on_off_tool/config",
                          root / "Auto_power_on_off_tool/config")
        atomic_json(root / "run.json", dict(project_id=context.identity.project_id, run_id=run_id,
                    revision=context.identity.revision, state="prepared"))
        return root

    def import_history(self, context, legacy_root):
        from src.services.ai_project_store import project_directory
        source = project_directory(legacy_root) / "diagnostics.sqlite3"
        backup = self.import_backups.get(context.identity.project_id)
        if backup is not None:
            source = backup / 'history' / 'diagnostics.sqlite3'
        target = context.history / "ai" / "diagnostics.sqlite3"
        if source.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            incoming = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
            outgoing = sqlite3.connect(str(target))
            try:
                incoming.backup(outgoing)
                with outgoing:
                    tables = {row[0] for row in outgoing.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if 'recovery' in tables:
                        outgoing.execute('DELETE FROM recovery')
                    if 'monitor_contexts' in tables:
                        outgoing.execute('DELETE FROM monitor_contexts')
                    if 'chat_actions' in tables:
                        for identifier, payload in outgoing.execute("SELECT id,payload FROM chat_actions WHERE state NOT IN ('succeeded','failed','rejected','cancelled','unknown')").fetchall():
                            value = json.loads(payload)
                            value['state'] = 'unknown'
                            value['migration_notice'] = '历史导入，仅供查阅；未迁移批准或重新执行操作'
                            outgoing.execute("UPDATE chat_actions SET state='unknown',payload=? WHERE id=?", (json.dumps(value, ensure_ascii=False), identifier))
                    if 'settings' in tables:
                        outgoing.execute("DELETE FROM settings WHERE name LIKE 'monitor%' OR name LIKE 'dingtalk%' OR name LIKE 'feishu%' OR name LIKE 'remote%' OR name LIKE 'debug%'")
            finally:
                outgoing.close()
                incoming.close()
            self.emit("[项目管理] 已关联旧AI历史；历史任务不会自动执行")

    def close(self, context):
        with self.lock:
            self.opened.pop(context.identity.project_id, None)
            lease = self.leases.pop(context.identity.project_id, None)
            if lease:
                lease.close()
        self.emit("[项目管理] 已关闭：" + context.identity.name)
