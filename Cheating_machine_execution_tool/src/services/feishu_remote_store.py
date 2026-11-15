"""飞书配置及独立收件箱；与钉钉共用项目AI目录，秘密仅DPAPI密文落盘。"""
import base64
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import uuid

from src.core.ai_credentials import WindowsCredentialCipher
from src.services.ai_project_store import initialize_project, project_directory


class FeishuConfigStore:
    def __init__(self, app_dir, directory=None, cipher=None):
        self.directory = Path(directory) if directory else project_directory(app_dir)
        self.path = self.directory / "feishu.json"
        self.cipher = cipher or WindowsCredentialCipher()
        self.binding = str(self.directory.resolve()) + "|feishu"

    @staticmethod
    def defaults():
        return dict(isolated=False, enabled=False, group_enabled=False, p2p_enabled=False,
                    push_enabled=False, push_revision=0, app_id="", app_secret="", group="", corp="", group_name="")

    def load(self):
        if not self.path.exists():
            return self.defaults()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            secret = self.cipher.decrypt(base64.b64decode(raw.pop("encrypted")), self.binding)
            result = dict(self.defaults(), **raw, app_secret=secret)
            return self.validate(result)
        except Exception:
            raise ValueError("飞书接入配置无法读取，请用当前Windows账号重新配置") from None

    @classmethod
    def validate(cls, values):
        result = {key: values.get(key, value) for key, value in cls.defaults().items()}
        for key in ("isolated", "group_enabled", "p2p_enabled", "push_enabled"):
            if type(result[key]) is not bool:
                raise ValueError("飞书开关配置无效")
        for key in ("app_id", "app_secret", "group", "corp", "group_name"):
            if not isinstance(result[key], str) or any(c in result[key] for c in "\r\n"):
                raise ValueError("飞书配置字段无效")
        result["enabled"] = result["group_enabled"] or result["p2p_enabled"]
        if type(result["push_revision"]) is not int or result["push_revision"] < 0:
            raise ValueError("飞书通知配置版本无效")
        if result["enabled"] or result["push_enabled"]:
            if not result["app_id"] or not result["app_secret"]:
                raise ValueError("启用前须保存飞书应用凭据")
        if result["group_enabled"] or result["push_enabled"]:
            if not result["group"] or not result["corp"]:
                raise ValueError("启用群排障或测试通知前须完成群绑定")
        return result

    def save(self, values):
        values = self.validate(values)
        secret = values.pop("app_secret")
        values["encrypted"] = base64.b64encode(self.cipher.encrypt(secret, self.binding)).decode("ascii")
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name("feishu." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def configure(self, values):
        saved = self.load()
        if saved["enabled"] or saved["push_enabled"]:
            raise ValueError("请先关闭飞书群排障、单聊排障及测试通知，再保存凭据")
        app = str(values.get("app_id", "")).strip()
        secret = str(values.get("app_secret", "")).strip()
        if not secret and app == saved["app_id"]:
            secret = saved["app_secret"]
        if not re.fullmatch(r"cli_[A-Za-z0-9_-]+", app) or not secret or any(c in secret for c in "\r\n"):
            raise ValueError("请填写有效App ID（cli_开头）及App Secret")
        config = dict(saved, app_id=app, app_secret=secret, isolated=True)
        if app != saved["app_id"] or secret != saved["app_secret"]:
            config.update(group="", corp="", group_name="", group_enabled=False, p2p_enabled=False, push_enabled=False)
            config["push_revision"] += 1
        initialize_project(self.directory, cipher=self.cipher)
        self.save(config)
        return self.load()


class FeishuMailbox:
    def __init__(self, directory):
        self.lock = threading.RLock()
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(Path(directory) / "feishu.sqlite3"), timeout=1, check_same_thread=False)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS routes(key TEXT PRIMARY KEY, session TEXT NOT NULL, cursor INTEGER NOT NULL);
        ''')
        with self.db:
            self.db.execute("UPDATE inbox SET state='interrupted',payload='{}' WHERE state IN ('pending','processing')")

    def admit(self, message, limit=64):
        with self.lock, self.db:
            if self.db.execute("SELECT 1 FROM inbox WHERE id=?", (message.id,)).fetchone():
                return False
            if self.db.execute("SELECT COUNT(*) FROM inbox WHERE state='pending'").fetchone()[0] >= limit:
                raise RuntimeError("飞书收件队列已满")
            self.db.execute("INSERT INTO inbox VALUES(?,'pending',?)", (message.id, json.dumps(asdict(message), ensure_ascii=False)))
            return True

    def next(self):
        with self.lock, self.db:
            row = self.db.execute("SELECT id,payload FROM inbox WHERE state='pending' ORDER BY rowid LIMIT 1").fetchone()
            if row:
                self.db.execute("UPDATE inbox SET state='processing' WHERE id=?", (row[0],))
            return json.loads(row[1]) if row else None

    def finish(self, identifier, state="done"):
        with self.lock, self.db:
            self.db.execute("UPDATE inbox SET state=?,payload='{}' WHERE id=?", (state, identifier))

    def discard_pending(self):
        with self.lock, self.db:
            self.db.execute("UPDATE inbox SET state='cancelled',payload='{}' WHERE state='pending'")

    def routes(self):
        with self.lock:
            return {r[0]: (r[1], r[2]) for r in self.db.execute("SELECT * FROM routes")}

    def route(self, key, session, cursor=0):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO routes VALUES(?,?,?)", (key, session, cursor))

    def close(self):
        with self.lock:
            self.db.close()
