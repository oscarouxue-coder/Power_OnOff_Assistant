"""按程序目录隔离AI运行数据；旧库只读，模型凭据原密文复制。"""
import hashlib
import os
from pathlib import Path
import sqlite3

from src.services.ai_store import DiagnosticStore, default_ai_data_dir


def project_directory(app_dir):
    identity = os.path.normcase(str(Path(app_dir).resolve()))
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return default_ai_data_dir().parent / "projects" / key


def readonly_database(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", timeout=5, uri=True)


def initialize_project(directory, legacy=None, cipher=None):
    """事务性、仅一次导入模型；不复制历史、恢复任务或权限。"""
    store = DiagnosticStore(directory, cipher)
    try:
        if store.setting("project_initialized", False):
            return
        legacy = Path(legacy) if legacy else default_ai_data_dir() / "diagnostics.sqlite3"
        profiles, settings = [], []
        if legacy.is_file():
            source = readonly_database(legacy)
            try:
                source.execute("BEGIN")
                profiles = source.execute("SELECT id,payload,binding,credential FROM profiles").fetchall()
                settings = source.execute("SELECT name,payload FROM settings WHERE name='selected_profile' "
                                          "OR name LIKE 'model_context:%'").fetchall()
            finally:
                source.close()
        with store.lock, store.db:
            store.db.executemany("INSERT OR IGNORE INTO profiles VALUES(?,?,?,?)", profiles)
            store.db.executemany("INSERT OR IGNORE INTO settings VALUES(?,?)", settings)
            store.db.execute("INSERT INTO settings VALUES(?,?)", ("project_initialized", "true"))
    finally:
        store.close()
