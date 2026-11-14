"""按程序目录隔离AI运行数据；旧库只读，模型凭据原密文复制。"""
import hashlib
import json
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


def legacy_records(path=None):
    """只读展示材料，不实例化会启动恢复/改写状态的诊断服务。"""
    path = Path(path) if path else default_ai_data_dir() / "diagnostics.sqlite3"
    if not path.is_file():
        return []
    db = readonly_database(path)
    try:
        result = []
        for identifier, created, payload in db.execute("SELECT * FROM chat_sessions ORDER BY created DESC"):
            session = json.loads(payload)
            messages = [json.loads(r[0]) for r in db.execute(
                "SELECT payload FROM chat_messages WHERE session_id=? ORDER BY id", (identifier,))]
            body = "\n\n".join(str(m.get("role", "")) + "：\n" + str(m.get("text", "")) for m in messages)
            result.append(("会话 | " + session.get("title", identifier) + " | " + created, body))
        for identifier, created, payload in db.execute("SELECT * FROM reports ORDER BY created DESC"):
            result.append(("报告 | " + identifier[:8] + " | " + created,
                           json.dumps(json.loads(payload), ensure_ascii=False, indent=2)))
        for row in db.execute("SELECT title,cause,solution,verification,scope FROM cases ORDER BY id DESC"):
            result.append(("案例 | " + row[0], "\n\n".join(str(v) for v in row)))
        return result
    finally:
        db.close()
