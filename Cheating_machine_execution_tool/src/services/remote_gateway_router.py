"""Platform-neutral routing after the platform adapter has validated the real sender."""
import json

from src.models.remote_gateway import RemotePrincipal, digest, canonical


class RemoteGatewayRouter:
    def __init__(self, store):
        self.store = store

    def handle(self, principal, message_id, text):
        principal = RemotePrincipal.parse(principal) if isinstance(principal, dict) else principal
        key = digest((principal.key, message_id))
        with self.store.lock, self.store.db:
            old = self.store.db.execute("SELECT fingerprint,response FROM controls WHERE id=?", (key,)).fetchone()
            if old:
                if old[0] != digest(text):
                    raise ValueError("相同平台消息ID内容发生变化")
                return json.loads(old[1])
            result = self._handle(principal, message_id, text)
            self.store.db.execute("INSERT INTO controls VALUES(?,?,?)", (key, digest(text), canonical(result)))
            return result

    def _handle(self, principal, message_id, text):
        if text == "在线实例":
            return dict(kind="instances", instances=self.store.instances(principal))
        if text == "当前实例":
            return dict(kind="current", instance=self.store.current(principal))
        if text.startswith("切换实例 "):
            return dict(kind="current", instance=self.store.select(principal, text.partition(" ")[2].strip()))
        if text.startswith("查询请求 "):
            return dict(kind="receipt", **self.store.receipt(principal, text.partition(" ")[2].strip()))
        return dict(kind="request", **self.store.route(principal, message_id, text))
