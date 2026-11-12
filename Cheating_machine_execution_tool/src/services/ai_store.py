"""独立用户数据：配置、加密模型凭据、真实诊断报告和经人工确认的案例。"""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import uuid
from urllib.parse import urlsplit, urlunsplit

from src.core.ai_credentials import WindowsCredentialCipher
from src.models.ai_diagnostics import ProviderProfile


def canonical_url(value):
    parts = urlsplit(value.strip().rstrip("/"))
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment):
        raise ValueError("API 地址必须为不含账号、查询参数或片段的 HTTPS 地址")
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def profile_fingerprint(profile):
    payload = (profile.id, canonical_url(profile.base_url), profile.protocol, profile.model,
               profile.timeout, profile.max_output, profile.credential_revision)
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


def default_ai_data_dir():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "LineCheckAssistant" / "ai"


class DiagnosticStore:
    def __init__(self, directory=None, cipher=None):
        self.directory = Path(directory) if directory is not None else default_ai_data_dir()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.cipher = cipher or WindowsCredentialCipher()
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.directory / "diagnostics.sqlite3"), check_same_thread=False)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                binding TEXT, credential BLOB);
            CREATE TABLE IF NOT EXISTS settings(name TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, created TEXT, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cases(id INTEGER PRIMARY KEY, report_id TEXT, title TEXT,
                cause TEXT, solution TEXT, verification TEXT, scope TEXT, active INTEGER DEFAULT 1);
            CREATE TABLE IF NOT EXISTS case_revisions(id INTEGER PRIMARY KEY, case_id INTEGER,
                created TEXT, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS recovery(id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chat_sessions(id TEXT PRIMARY KEY, created TEXT NOT NULL,
                payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chat_messages(id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,
                payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chat_groups(id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,
                payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chat_evidence(id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chat_actions(id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                state TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS chat_actions_session ON chat_actions(session_id);
            CREATE INDEX IF NOT EXISTS chat_messages_session ON chat_messages(session_id,id);
            CREATE INDEX IF NOT EXISTS chat_groups_session ON chat_groups(session_id,id);
            CREATE INDEX IF NOT EXISTS chat_evidence_session ON chat_evidence(session_id);
        ''')
        self.db.commit()

    def profiles(self):
        with self.lock:
            return [ProviderProfile(**json.loads(r[0])) for r in
                    self.db.execute("SELECT payload FROM profiles ORDER BY rowid")]

    def save_profile(self, profile, key=None):
        base = canonical_url(profile.base_url)
        if profile.protocol not in ("chat_completions", "responses"):
            raise ValueError("不支持的 API 协议")
        if not 5 <= profile.timeout <= 180 or not 256 <= profile.max_output <= 32768:
            raise ValueError("超时须为5–180秒，输出上限须为256–32768")
        if type(profile.context_tokens) is not int or profile.context_tokens < 0:
            raise ValueError("上下文上限须为正整数，留空表示自动识别")
        profile = replace(profile, base_url=base)
        binding = f"{profile.id}|{base}"
        with self.lock:
            old = self.db.execute("SELECT payload,binding,credential FROM profiles WHERE id=?", (profile.id,)).fetchone()
            credential = old[2] if old and old[1] == binding else None
            if key:
                credential = self.cipher.encrypt(key, binding)
                profile = replace(profile, credential_revision=uuid.uuid4().hex)
            changed = (not old or profile_fingerprint(ProviderProfile(**json.loads(old[0]))) !=
                       profile_fingerprint(profile) or bool(key))
            if changed:
                profile = replace(profile, capability="未验证", tested_fingerprint="")
            self.db.execute("INSERT OR REPLACE INTO profiles VALUES(?,?,?,?)",
                            (profile.id, json.dumps(asdict(profile), ensure_ascii=False), binding, credential))
            self.db.commit()
        return profile

    def key(self, profile):
        binding = f"{profile.id}|{canonical_url(profile.base_url)}"
        with self.lock:
            row = self.db.execute("SELECT binding,credential FROM profiles WHERE id=?", (profile.id,)).fetchone()
        if not row or row[0] != binding or not row[1]:
            raise ValueError("该 API 地址尚未配置密钥，请重新填写")
        return self.cipher.decrypt(row[1], binding)

    def delete_profile(self, identifier):
        with self.lock:
            self.db.execute("DELETE FROM profiles WHERE id=?", (identifier,))
            self.db.commit()

    def setting(self, name, default=None):
        with self.lock:
            row = self.db.execute("SELECT payload FROM settings WHERE name=?", (name,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, name, value):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (name, json.dumps(value, ensure_ascii=False)))
            self.db.commit()

    def model_context(self, profile):
        return self.setting(self._model_context_key(profile.base_url, profile.model), 0)

    @staticmethod
    def _model_context_key(base_url, model):
        identity = json.dumps([canonical_url(base_url), model], ensure_ascii=False)
        return "model_context:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def cache_model_contexts(self, profile, models):
        # 缺字段或刷新失败不抹掉已有容量；不同地址和模型各自保存。
        with self.lock, self.db:
            for model in models:
                capacity = model.get("context_tokens", 0)
                if type(capacity) is int and capacity > 0:
                    key = self._model_context_key(profile.base_url, model["id"])
                    self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)",
                                    (key, json.dumps(capacity)))

    def save_report(self, identifier, payload):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO reports VALUES(?,?,?)",
                            (identifier, datetime.now().isoformat(timespec="seconds"), json.dumps(payload, ensure_ascii=False)))
            self.db.commit()

    def report(self, identifier):
        with self.lock:
            row = self.db.execute("SELECT payload FROM reports WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("诊断报告不存在")
        return json.loads(row[0])

    def reports(self):
        with self.lock:
            return [(r[0], r[1], json.loads(r[2])) for r in
                    self.db.execute("SELECT * FROM reports ORDER BY created DESC LIMIT 100")]

    def confirm_case(self, report_id, title, cause, solution, verification, scope, case_id=None):
        if not all(str(x).strip() for x in (title, cause, solution, verification, scope)):
            raise ValueError("确认案例需填写标题、实际原因、处理方法、复测结果和适用范围")
        values = (report_id, title, cause, solution, verification, scope)
        with self.lock:
            if case_id is None:
                cursor = self.db.execute("INSERT INTO cases(report_id,title,cause,solution,verification,scope) VALUES(?,?,?,?,?,?)", values)
                case_id = cursor.lastrowid
            else:
                self.db.execute("UPDATE cases SET report_id=?,title=?,cause=?,solution=?,verification=?,scope=? WHERE id=?", values + (case_id,))
            self.db.execute("INSERT INTO case_revisions(case_id,created,payload) VALUES(?,?,?)",
                            (case_id, datetime.now().isoformat(), json.dumps(values, ensure_ascii=False)))
            self.db.commit()
        return case_id

    def cases(self, query="", include_inactive=False):
        with self.lock:
            self.db.row_factory = sqlite3.Row
            rows = [dict(r) for r in self.db.execute("SELECT * FROM cases" +
                    ("" if include_inactive else " WHERE active=1") + " ORDER BY id DESC")]
            self.db.row_factory = None
        if not query:
            return rows
        terms = set(re.findall(r"[a-z0-9_.-]+|[\u4e00-\u9fff]{2,8}", query.casefold()))
        ranked = [(sum(term in " ".join(str(v) for v in r.values()).casefold() for term in terms), r) for r in rows]
        return [r for score, r in sorted(ranked, key=lambda x: x[0], reverse=True) if score][:5]

    def update_case_state(self, case_id, delete=False):
        with self.lock:
            if delete:
                self.db.execute("DELETE FROM cases WHERE id=?", (case_id,))
                self.db.execute("DELETE FROM case_revisions WHERE case_id=?", (case_id,))
            else:
                self.db.execute("UPDATE cases SET active=1-active WHERE id=?", (case_id,))
            self.db.commit()

    def recovery(self, identifier, payload, state="pending"):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO recovery VALUES(?,?,?)", (identifier, json.dumps(payload), state))
            self.db.commit()

    def pending_recovery(self):
        with self.lock:
            return [(r[0], json.loads(r[1])) for r in self.db.execute("SELECT id,payload FROM recovery WHERE state='pending'")]

    def create_chat(self, payload):
        with self.lock:
            self.db.execute("INSERT INTO chat_sessions VALUES(?,?,?)",
                            (payload["id"], payload["created"], json.dumps(payload, ensure_ascii=False)))
            self.db.commit()

    def chat(self, identifier):
        with self.lock:
            row = self.db.execute("SELECT payload FROM chat_sessions WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise ValueError("排障会话不存在")
            return json.loads(row[0])

    def chats(self):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute(
                "SELECT payload FROM chat_sessions ORDER BY created DESC, rowid DESC")]

    def update_chat(self, identifier, **changes):
        with self.lock:
            payload = self.chat(identifier)
            payload.update(changes)
            self.db.execute("UPDATE chat_sessions SET payload=? WHERE id=?",
                            (json.dumps(payload, ensure_ascii=False), identifier))
            self.db.commit()
            return payload

    def delete_chats(self, identifiers):
        """仅删除指定会话的数据；整批校验和四张表的删除共用一次事务。"""
        identifiers = tuple(dict.fromkeys(identifiers))
        if not identifiers:
            return 0
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            for identifier in identifiers:
                self.chat(identifier)  # 不允许失效选择造成部分删除。
            parameters = [(identifier,) for identifier in identifiers]
            for table in ("chat_messages", "chat_groups", "chat_evidence", "chat_actions"):
                self.db.executemany("DELETE FROM " + table + " WHERE session_id=?", parameters)
            self.db.executemany("DELETE FROM chat_sessions WHERE id=?", parameters)
        return len(identifiers)

    def append_chat(self, identifier, payload, group=False):
        table = "chat_groups" if group else "chat_messages"
        with self.lock:
            self.db.execute("INSERT INTO " + table + "(session_id,payload) VALUES(?,?)",
                            (identifier, json.dumps(payload, ensure_ascii=False)))
            self.db.commit()

    def save_action(self, action):
        with self.lock:
            self.chat(action["session_id"])
            self.db.execute("INSERT INTO chat_actions VALUES(?,?,?,?)", (action["id"], action["session_id"],
                            action["state"], json.dumps(action, ensure_ascii=False)))
            self.db.commit()

    def actions(self, identifier, states=None):
        with self.lock:
            sql, params = "SELECT payload FROM chat_actions WHERE session_id=?", [identifier]
            if states is not None:
                if not states:
                    return []
                sql += " AND state IN (" + ",".join("?" for _ in states) + ")"
                params.extend(states)
            return [json.loads(row[0]) for row in self.db.execute(
                sql + " ORDER BY rowid", params)]

    def action(self, action_id):
        with self.lock:
            row = self.db.execute("SELECT payload FROM chat_actions WHERE id=?", (action_id,)).fetchone()
            if row is None:
                raise ValueError("操作记录不存在")
            return json.loads(row[0])

    def change_action(self, action_id, expected, state, **changes):
        """比较状态后单次转移，重复点击和旧确认不能重复下发。"""
        with self.lock:
            action = self.action(action_id)
            if action["state"] not in expected:
                raise ValueError("操作状态已变化，本次未授权或执行")
            action.update(changes, state=state)
            self.db.execute("UPDATE chat_actions SET state=?,payload=? WHERE id=?",
                            (state, json.dumps(action, ensure_ascii=False), action_id))
            self.db.commit()
            return action

    def chat_items(self, identifier, group=False):
        table = "chat_groups" if group else "chat_messages"
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute(
                "SELECT payload FROM " + table + " WHERE session_id=? ORDER BY id", (identifier,))]

    def add_chat_evidence(self, identifier, evidence):
        return self.add_chat_evidence_batch(identifier, (evidence,))[0]

    def add_chat_evidence_batch(self, identifier, evidence):
        # 来源/原文相同的快照不重复存储；新时间点的主动查询由来源中的调用ID区分。
        rows = []
        for item in evidence:
            text = json.dumps((identifier, item["source"], item["text"], item["run_id"]), ensure_ascii=False)
            key = hashlib.sha256(text.encode("utf-8")).hexdigest()
            rows.append((key, identifier, json.dumps(dict(item, id=key), ensure_ascii=False)))
        with self.lock:
            self.db.executemany("INSERT OR IGNORE INTO chat_evidence VALUES(?,?,?)", rows)
            self.db.commit()
        return [row[0] for row in rows]

    def chat_evidence(self, identifier):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute(
                "SELECT payload FROM chat_evidence WHERE session_id=? ORDER BY rowid", (identifier,))]

    def close(self):
        with self.lock:
            self.db.close()
