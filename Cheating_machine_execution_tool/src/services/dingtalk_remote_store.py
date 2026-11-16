"""项目接入配置/收件箱/路由；机器人秘密仅DPAPI密文落盘。"""
import base64
import json
import os
from pathlib import Path
import sqlite3
import threading
import uuid

from src.core.ai_credentials import WindowsCredentialCipher
from src.services.ai_project_store import project_directory
from urllib.parse import parse_qs, urlsplit


class RemoteConfigStore:
    def __init__(self, app_dir, directory=None, cipher=None):
        self.directory = Path(directory) if directory else project_directory(app_dir)
        self.path = self.directory / "dingtalk.json"
        self.cipher = cipher or WindowsCredentialCipher()
        self.binding = str(self.directory.resolve()) + "|dingtalk"

    def load(self):
        defaults = dict(isolated=False, enabled=False, client_id="", client_secret="", robot_code="",
                        group="", corp="", group_name="", webhook="", secret="", ai_card_template_id="")
        if not self.path.exists():
            return defaults
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            secrets = json.loads(self.cipher.decrypt(base64.b64decode(raw.pop("encrypted")), self.binding))
            defaults.update(raw)
            defaults.update(secrets)
            return defaults
        except Exception:
            raise ValueError("钉钉接入配置无法读取，请用当前Windows账号重新配置") from None

    def save(self, values):
        values = dict(values)
        if values.get("enabled") and not all(values.get(k) for k in
                ("client_id", "client_secret", "robot_code", "group", "corp", "webhook")):
            raise ValueError("启用前须保存应用凭据、群Webhook并完成群绑定")
        secrets = {k: str(values.pop(k, "")) for k in ("client_secret", "webhook", "secret")}
        values["encrypted"] = base64.b64encode(self.cipher.encrypt(
            json.dumps(secrets, ensure_ascii=False), self.binding)).decode("ascii")
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name("dingtalk." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def configure(self, values, push_config_path):
        """本地显式保存：准备独立库，并将原测试通知迁移到同一个应用机器人。"""
        from src.services.ai_project_store import initialize_project
        from src.services.message_push_config_service import MessagePushConfigService
        saved = self.load()
        values = {k: str(values.get(k, saved.get(k, "") if k == "ai_card_template_id" else "")).strip() for k in
                  ("client_id", "client_secret", "robot_code", "webhook", "secret", "ai_card_template_id")}
        if len(values["ai_card_template_id"]) > 200:
            raise ValueError("AI卡片模板ID不能超过200字符")
        if not values["client_secret"] and values["client_id"] == saved["client_id"]:
            values["client_secret"] = saved["client_secret"]
        if any("\r" in v or "\n" in v for v in values.values()):
            raise ValueError("应用配置不能包含换行")
        if not all(values[k] for k in ("client_id", "client_secret", "robot_code", "webhook")):
            raise ValueError("请填写完整应用凭据、Robot Code和新应用机器人的群Webhook")
        try:
            parts = urlsplit(values["webhook"])
            valid = (parts.scheme == "https" and parts.hostname == "oapi.dingtalk.com"
                     and parts.path == "/robot/send" and parts.port in (None, 443)
                     and not parts.username and not parts.password and not parts.fragment
                     and bool(parse_qs(parts.query).get("access_token")))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("请填写应用机器人的完整钉钉群HTTPS Webhook（含access_token）")
        config = dict(saved, **values, isolated=True, enabled=False)
        if any(config[k] != saved[k] for k in ("client_id", "robot_code", "webhook", "client_secret")):
            config.update(group="", corp="", group_name="")
        push = MessagePushConfigService(push_config_path)
        notification = push.load()
        notification.update(webhook=values["webhook"], secret=values["secret"])
        initialize_project(self.directory)
        previous = self.path.read_bytes() if self.path.exists() else None
        push_path = Path(push_config_path)
        previous_push = push_path.read_bytes() if push_path.exists() else None
        self.save(config)
        try:
            push.save(notification)
        except Exception:
            for path, snapshot in ((self.path, previous), (push_path, previous_push)):
                try:
                    if snapshot is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.write_bytes(snapshot)
                except OSError:
                    raise ValueError("配置写入及回退失败，请检查应用接入和消息推送配置；接入未启用") from None
            raise ValueError("测试通知配置更新失败，应用配置已回退；请检查文件访问权限") from None
        return config


class RemoteMailbox:
    def __init__(self, directory):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(Path(directory) / "dingtalk.sqlite3"), check_same_thread=False)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS routes(key TEXT PRIMARY KEY, session TEXT NOT NULL, cursor INTEGER NOT NULL);
        ''')
        # 重启不重放远程操作，避免再次下发结果未知的设备命令。
        with self.db:
            self.db.execute("UPDATE inbox SET state='interrupted' WHERE state IN ('pending','processing')")

    def admit(self, message, limit=64):
        with self.lock, self.db:
            if self.db.execute("SELECT 1 FROM inbox WHERE id=?", (message.id,)).fetchone():
                return False
            count = self.db.execute("SELECT COUNT(*) FROM inbox WHERE state='pending'").fetchone()[0]
            if count >= limit:
                raise RuntimeError("钉钉收件队列已满")
            from dataclasses import asdict
            # SessionWebhook含临时凭据，不写入收件箱；正文仅存在项目本地数据。
            payload = asdict(message)
            payload.update(webhook="", expires=0)
            self.db.execute("INSERT INTO inbox VALUES(?,'pending',?)", (message.id, json.dumps(payload, ensure_ascii=False)))
            return True

    def next(self):
        with self.lock, self.db:
            row = self.db.execute("SELECT id,payload FROM inbox WHERE state='pending' ORDER BY rowid LIMIT 1").fetchone()
            if row:
                self.db.execute("UPDATE inbox SET state='processing' WHERE id=?", (row[0],))
            return json.loads(row[1]) if row else None

    def finish(self, identifier, state="done"):
        with self.lock, self.db:
            # 已处理消息只保留去重ID，不长期重复保存聊天正文。
            self.db.execute("UPDATE inbox SET state=?,payload='{}' WHERE id=?", (state, identifier))

    def routes(self):
        with self.lock:
            return dict((r[0], (r[1], r[2])) for r in self.db.execute("SELECT * FROM routes"))

    def route(self, key, session, cursor=0):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO routes VALUES(?,?,?)", (key, session, cursor))

    def close(self):
        with self.lock:
            self.db.close()
