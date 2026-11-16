"""Durable identities and message receipts. Business jobs remain exclusively in each instance."""
import base64
from dataclasses import asdict
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid

from src.core.ai_credentials import WindowsCredentialCipher
from src.models.remote_gateway import RemotePrincipal, allows, canonical, digest, identifier, signature


class RemoteGatewayStore:
    def __init__(self, directory, *, cipher=None, clock=time.time):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.cipher, self.clock = cipher or WindowsCredentialCipher(), clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.directory / "remote_gateway.sqlite3"), check_same_thread=False)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS pairing(code TEXT PRIMARY KEY, expires REAL, scopes TEXT);
            CREATE TABLE IF NOT EXISTS instances(id TEXT PRIMARY KEY, credential BLOB, name TEXT, scopes TEXT,
                run TEXT, seen REAL, online INTEGER, revoked INTEGER);
            CREATE TABLE IF NOT EXISTS selections(principal TEXT PRIMARY KEY, instance TEXT, run TEXT);
            CREATE TABLE IF NOT EXISTS messages(message_key TEXT PRIMARY KEY, request TEXT UNIQUE, fingerprint TEXT,
                instance TEXT,run TEXT,payload TEXT,state TEXT,correlation TEXT);
            CREATE TABLE IF NOT EXISTS replies(id TEXT PRIMARY KEY,instance TEXT,run TEXT,principal TEXT,payload TEXT,state TEXT);
            CREATE TABLE IF NOT EXISTS controls(id TEXT PRIMARY KEY,fingerprint TEXT,response TEXT);
        ''')

    def recover(self):
        with self.db:
            self.db.execute("UPDATE instances SET online=0")
            self.db.execute("UPDATE messages SET state='uncertain' WHERE state='offered'")

    def _encrypt(self, identifier, secret):
        return self.cipher.encrypt(secret, "remote-gateway|" + identifier)

    def create_pairing(self, scopes):
        # Validate an explicit operator-reviewed allowlist before issuing an invitation.
        if not isinstance(scopes, list) or not scopes:
            raise ValueError("必须明确允许的平台、聊天和成员")
        for scope in scopes:
            if set(scope) != {"platform", "robot", "corp", "chat_type", "chat", "members"}:
                raise ValueError("配对范围字段无效")
            members = scope["members"]
            if not isinstance(members, list) or not members or any(not isinstance(m, str) or not m for m in members):
                raise ValueError("必须指定成员；全群使用显式单独的星号")
            if "*" in members and members != ["*"]:
                raise ValueError("全群范围须明确指定")
            RemotePrincipal.parse(dict({k: v for k, v in scope.items() if k != "members"}, member=members[0]))
        code = secrets.token_urlsafe(24)
        with self.lock, self.db:
            self.db.execute("INSERT INTO pairing VALUES(?,?,?)", (digest(code), self.clock() + 300, canonical(scopes)))
        return code

    def pair(self, code, instance_id, name):
        identifier(instance_id)
        if not isinstance(name, str) or not 1 <= len(name) <= 160:
            raise ValueError("实例名称无效")
        with self.lock, self.db:
            row = self.db.execute("SELECT expires,scopes FROM pairing WHERE code=?", (digest(code),)).fetchone()
            if not row or self.clock() >= row[0]:
                raise ValueError("配对码无效或已过期")
            if self.db.execute("SELECT 1 FROM instances WHERE id=?", (instance_id,)).fetchone():
                raise ValueError("永久实例已登记，重配前须在本地明确撤销旧身份")
            token = secrets.token_urlsafe(32)
            self.db.execute("INSERT INTO instances VALUES(?,?,?,?,?,0,0,0)",
                            (instance_id, self._encrypt(instance_id, token), name, row[1], ""))
            self.db.execute("DELETE FROM pairing WHERE code=?", (digest(code),))
            return dict(instance_id=instance_id, credential=token, scopes=json.loads(row[1]))

    def credential(self, instance_id):
        with self.lock:
            row = self.db.execute("SELECT credential,revoked FROM instances WHERE id=?", (instance_id,)).fetchone()
        if not row or row[1]:
            raise ValueError("实例未登记或凭据已撤销")
        return self.cipher.decrypt(row[0], "remote-gateway|" + instance_id)

    def register(self, instance_id, run_id):
        identifier(run_id)
        self.credential(instance_id)
        with self.lock, self.db:
            row = self.db.execute("SELECT run,seen,online FROM instances WHERE id=?", (instance_id,)).fetchone()
            if row[2] and row[0] != run_id and self.clock() - row[1] < 60:
                raise ValueError("原运行实例仍在线，禁止接管")
            if row[0] != run_id:
                self.db.execute("UPDATE messages SET state='interrupted' WHERE instance=? AND state IN ('queued','offered','uncertain')", (instance_id,))
            self.db.execute("UPDATE instances SET run=?,seen=?,online=1 WHERE id=?", (run_id, self.clock(), instance_id))

    def heartbeat(self, instance_id, run_id):
        self.credential(instance_id)
        with self.lock, self.db:
            result = self.db.execute("UPDATE instances SET seen=?,online=1 WHERE id=? AND run=? AND revoked=0",
                                     (self.clock(), instance_id, run_id))
            if result.rowcount != 1:
                raise ValueError("启动身份已失效")

    def offline(self, instance_id, run_id):
        with self.lock, self.db:
            self.db.execute("UPDATE instances SET online=0 WHERE id=? AND run=?", (instance_id, run_id))

    def revoke(self, instance_id):
        with self.lock, self.db:
            self.db.execute("UPDATE instances SET revoked=1,online=0 WHERE id=?", (instance_id,))
            self.db.execute("DELETE FROM selections WHERE instance=?", (instance_id,))

    def instances(self, principal, *, online_only=True):
        with self.lock:
            rows = self.db.execute("SELECT id,name,scopes,run,seen,online FROM instances WHERE revoked=0").fetchall()
        result = []
        for item, name, scopes, run, seen, online in rows:
            online = bool(online and self.clock() - seen < 60)
            if allows(json.loads(scopes), principal) and (online if online_only else self.clock() - seen < 86400):
                result.append(dict(instance_id=item, name=name, run_id=run, online=online))
        return result

    def select(self, principal, target):
        candidates = [v for v in self.instances(principal) if target in (v["instance_id"], v["instance_id"][:8], v["name"])]
        if len(candidates) != 1:
            raise ValueError("实例不在线、名称重复或超出授权范围，请查看在线实例")
        value = candidates[0]
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO selections VALUES(?,?,?)", (principal.key, value["instance_id"], value["run_id"]))
        return value

    def current(self, principal):
        with self.lock:
            selected = self.db.execute("SELECT instance,run FROM selections WHERE principal=?", (principal.key,)).fetchone()
        values = self.instances(principal)
        value = next((v for v in values if selected and (v["instance_id"], v["run_id"]) == selected), None)
        if not value:
            raise ValueError("请先选择在线实例；原实例离线或重启后须重新选择")
        return value

    def route(self, principal, message_id, text):
        key = digest((asdict(principal), message_id))
        fingerprint = digest(text)
        with self.lock, self.db:
            old = self.db.execute("SELECT request,fingerprint,payload,state,correlation FROM messages WHERE message_key=?", (key,)).fetchone()
            if old:
                if old[1] != fingerprint:
                    raise ValueError("相同消息标识的内容发生变化")
                return dict(request=json.loads(old[2]), state=old[3], correlation=json.loads(old[4]), duplicate=True)
            target = self.current(principal)
            now = self.clock()
            request = dict(version=1, request_id=str(uuid.uuid4()), message_id=message_id,
                instance_id=target["instance_id"], run_id=target["run_id"], principal=asdict(principal),
                text=text, created=now, expires=now + 60)
            self.db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,'queued','{}')", (key,
                request["request_id"], fingerprint, target["instance_id"], target["run_id"], canonical(request)))
            return dict(request=request, state="queued", correlation={}, duplicate=False)

    def poll(self, instance_id, run_id):
        self.heartbeat(instance_id, run_id)
        with self.lock, self.db:
            rows = self.db.execute("SELECT request,payload FROM messages WHERE instance=? AND run=? AND state='queued' ORDER BY rowid LIMIT 1",
                                   (instance_id, run_id)).fetchall()
            result = []
            for identifier_, payload in rows:
                request = json.loads(payload)
                state = "expired" if self.clock() > request["expires"] else "offered"
                self.db.execute("UPDATE messages SET state=? WHERE request=?", (state, identifier_))
                if state == "offered":
                    result.append(request)
            return result

    def acknowledge(self, instance_id, run_id, request_id, receipt):
        if not isinstance(receipt, dict) or receipt.get("state") not in ("received", "submitted", "done", "rejected", "unknown", "interrupted"):
            raise ValueError("接收状态无效")
        with self.lock, self.db:
            row = self.db.execute("SELECT state,correlation FROM messages WHERE request=? AND instance=? AND run=?",
                                  (request_id, instance_id, run_id)).fetchone()
            if not row:
                raise ValueError("请求不属于此实例启动")
            previous = json.loads(row[1])
            merged = dict(previous, **receipt)
            if previous.get("jobs") and not receipt.get("jobs"):
                merged["jobs"] = previous["jobs"]
            if row[0] in ("submitted", "done", "unknown", "interrupted", "rejected") and receipt["state"] == "received":
                merged["state"] = row[0]
            self.db.execute("UPDATE messages SET state=?,correlation=? WHERE request=?",
                            (merged["state"], canonical(merged), request_id))

    def receipt(self, principal, request_id):
        with self.lock:
            row = self.db.execute("SELECT payload,state,correlation FROM messages WHERE request=?", (request_id,)).fetchone()
        if not row or RemotePrincipal.parse(json.loads(row[0])["principal"]) != principal:
            raise ValueError("请求不存在或不属于当前成员")
        target = json.loads(row[0])["instance_id"]
        self.credential(target)
        with self.lock:
            scopes = json.loads(self.db.execute("SELECT scopes FROM instances WHERE id=?", (target,)).fetchone()[0])
        if not allows(scopes, principal):
            raise ValueError("请求的实例范围已撤销")
        return dict(state=row[1], correlation=json.loads(row[2]))

    def close(self):
        self.db.close()
