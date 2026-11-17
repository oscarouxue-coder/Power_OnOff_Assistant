"""Instance relay inbox and bridge to the existing Agent. Never creates business authority."""
from dataclasses import asdict
import json
from pathlib import Path
import re
import sqlite3
import threading
import time

from src.models.remote_gateway import RemotePrincipal, allows, canonical, digest, validate_request
from src.models.capabilities import CapabilityError
from src.models.ai_session_scope import source_identity


class RemoteInstanceInbox:
    def __init__(self, directory, instance_id, run_id, *, clock=time.time):
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.instance_id, self.run_id, self.clock = instance_id, run_id, clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(Path(directory) / "relay_inbox.sqlite3"), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY,digest TEXT,payload TEXT,state TEXT,receipt TEXT)")
        with self.db:
            pending = self.db.execute("SELECT id,receipt FROM inbox WHERE state IN ('received','processing')").fetchall()
            for request_id, receipt in pending:
                value = dict(json.loads(receipt), state="interrupted", notice="进程重启，不重新提交Agent")
                self.db.execute("UPDATE inbox SET state='interrupted',receipt=? WHERE id=?", (canonical(value), request_id))

    def admit(self, request):
        with self.lock, self.db:
            old = self.db.execute("SELECT digest,receipt FROM inbox WHERE id=?", (request.get("request_id"),)).fetchone()
            if old:
                if digest(request) != old[0]:
                    raise ValueError("相同请求标识内容发生变化")
                # A duplicate can retrieve an old receipt after expiry, never execute it again.
                return json.loads(old[1]), False
            validate_request(request, self.instance_id, self.run_id, self.clock())
            count = self.db.execute("SELECT COUNT(*) FROM inbox WHERE state IN ('received','processing')").fetchone()[0]
            if count >= 64:
                raise ValueError("实例接收队列已满")
            receipt = dict(state="received", request_id=request["request_id"])
            self.db.execute("INSERT INTO inbox VALUES(?,?,?,'received',?)", (request["request_id"], digest(request), canonical(request), canonical(receipt)))
            return receipt, True

    def next(self):
        with self.lock, self.db:
            row = self.db.execute("SELECT id,payload FROM inbox WHERE state='received' ORDER BY rowid LIMIT 1").fetchone()
            if row:
                self.db.execute("UPDATE inbox SET state='processing' WHERE id=?", (row[0],))
            return json.loads(row[1]) if row else None

    def finish(self, request_id, receipt):
        with self.lock, self.db:
            self.db.execute("UPDATE inbox SET state=?,receipt=? WHERE id=?", (receipt["state"], canonical(receipt), request_id))

    def associate(self, request_id, session_id, cursor):
        """Commit correlation before the Agent is allowed to enqueue any work."""
        with self.lock, self.db:
            row = self.db.execute("SELECT receipt FROM inbox WHERE id=? AND state='processing'", (request_id,)).fetchone()
            if not row:
                raise ValueError("请求接收状态已变化，未提交Agent")
            receipt = dict(json.loads(row[0]), session_id=session_id, cursor=cursor)
            self.db.execute("UPDATE inbox SET receipt=? WHERE id=?", (canonical(receipt), request_id))

    def receipts(self):
        with self.lock:
            return {r[0]: json.loads(r[1]) for r in self.db.execute("SELECT id,receipt FROM inbox")}

    def requests(self):
        with self.lock:
            return [(json.loads(r[0]), json.loads(r[1])) for r in self.db.execute("SELECT payload,receipt FROM inbox")]

    def close(self):
        self.db.close()


class GatewayAgentBridge:
    """Local allowlist is supplied by the host operator, not by any network message.

    Existing permissions.select(..., confirmed=True) remains the only way to grant
    full access. New relay sessions start ASK even if Feishu/local defaults are FULL.
    """
    def __init__(self, conversation, identity, scopes, channel_ids, capability_ids, *, enabled=False,
                 directory=None, clock=time.time, project_path=None):
        self.owner, self.identity = conversation, identity
        self.scopes, self.channel_ids = list(scopes), tuple(channel_ids)
        self.capability_ids = frozenset(capability_ids)
        self.enabled, self.clock = bool(enabled), clock
        self.project_path = project_path
        self.lock = threading.RLock()
        self.inbox = RemoteInstanceInbox(directory or identity.directory, identity.instance_id, identity.run_id, clock=clock)
        if getattr(conversation, "gateway", None) is not None:
            raise ValueError("该Agent已有统一入口桥")
        conversation.gateway = self

    def authorized_source(self, source, session=None):
        if (not self.enabled or source.get("gateway_instance_id") != self.identity.instance_id
                or source.get("gateway_run_id") != self.identity.run_id):
            return False
        try:
            principal = RemotePrincipal.parse(dict(platform=source["kind"], robot=source["robot"], corp=source["corp"],
                chat_type=source["chat_type"], chat=source["group"], member=source["sender"]))
        except (KeyError, ValueError):
            return False
        if not allows(self.scopes, principal):
            return False
        if session:
            targets = session.get("batch_targets") or ([session["target"]] if session.get("target") else [])
            if any(t["channel"] not in self.channel_ids for t in targets):
                return False
            if session.get("scope") == "pc":
                return False  # Host administration needs a separately reviewed scope in a later batch.
        return True

    def check_capability(self, session, name, params):
        if not self.authorized_source(session.get("source") or {}, session):
            raise CapabilityError("relay_scope_forbidden", "实例本地身份/目标范围未授权")
        from src.services.ai_capability_adapter import FAST_CAPABILITIES
        capability = FAST_CAPABILITIES[name][0] if name in FAST_CAPABILITIES else params.get("capability_id", name)
        queries = {"list_capabilities", "describe_capability", "validate_capability", "get_job_status", "get_job_result"}
        if name not in queries and capability not in self.capability_ids:
            raise CapabilityError("relay_capability_forbidden", "此实例未向该来源开放该能力")
        if name in ("get_job_status", "get_job_result", "cancel_job") and params.get("job_id"):
            authority = self.owner.capabilities.authority(session["id"])
            job = self.owner.capabilities.service.jobs.status(params["job_id"], authority)
            if job["capability_id"] not in self.capability_ids:
                raise CapabilityError("relay_capability_forbidden", "原任务能力不在当前本地授权范围")

    def receive(self, request):
        principal = RemotePrincipal.parse(request.get("principal"))
        source = principal.source(self.identity.instance_id, self.identity.run_id)
        with self.lock:
            if not self.authorized_source(source):
                raise ValueError("实例未启用接入或来源不在本地允许范围")
            receipt, fresh = self.inbox.admit(request)
        if fresh:
            self.owner.emit("[统一接入] 请求已持久化：" + request["request_id"][:8])
        return receipt

    def process_one(self):
        request = self.inbox.next()
        if not request:
            return None
        identifier = ""
        cursor = 0
        try:
            validate_request(request, self.identity.instance_id, self.identity.run_id, self.clock())
            source = RemotePrincipal.parse(request["principal"]).source(self.identity.instance_id, self.identity.run_id)
            if not self.authorized_source(source):
                raise ValueError("来源范围已失效")
            def register(value):
                nonlocal identifier, cursor
                with self.owner.lock:
                    session = self.owner.store.chat(value)
                    if not self.authorized_source(source, session):
                        raise ValueError("目标不在本实例已审核通道范围")
                    if value in self.owner.running:
                        raise ValueError("该成员原会话仍在执行，本条未再次提交")
                    identifier = value
                    cursor = len(self.owner.store.chat_items(value))
                    self.inbox.associate(request["request_id"], value, cursor)
                    self.owner.store.update_chat(value, gateway_request_id=request["request_id"])
            text = request["text"]
            transform = getattr(self, 'project_text', None)
            if transform is not None:
                text = transform(text)
            # Chat stop is explicitly distinct from business cancellation.
            if text == "停止":
                identifier = self.owner.router.current(source)
                if not identifier:
                    raise ValueError("当前没有此成员的会话")
                self.owner.stop(identifier)
                result = dict(identifier=identifier, submitted=False, notice="停止聊天；已准入业务继续")
            else:
                result = self.owner.router.send(text, self.owner.diagnostic.profile, source=source,
                    on_selected=register, guard=lambda: self.authorized_source(source))
            receipt = dict(state="submitted", request_id=request["request_id"], session_id=result["identifier"],
                           notice=result["notice"], submitted=result["submitted"], cursor=cursor)
        except Exception as exc:
            admitted = bool(identifier and (identifier in self.owner.running or any(
                item.get("role") == "user" for item in self.owner.store.chat_items(identifier)[cursor:])))
            receipt = dict(state="unknown" if admitted else "rejected", request_id=request["request_id"],
                           session_id=identifier, cursor=cursor, notice=self.owner.redactor.text(str(exc)))
            if admitted:
                receipt["notice"] = "Agent入队后确认未完成，结果待核实，不自动重发；" + receipt["notice"]
            self.owner.emit("[统一接入] 请求处理未完成，不自动重发：" + receipt["notice"])
        self.inbox.finish(request["request_id"], receipt)
        return request, receipt

    def correlations(self):
        """Read existing action/Job records; no duplicate Job persistence or replay."""
        result = {}
        records = self.inbox.requests()
        for position, (request, receipt) in enumerate(records):
            if request["run_id"] != self.identity.run_id:
                continue
            value = dict(receipt)
            identifier = receipt.get("session_id")
            if identifier:
                end = next((r.get("cursor", 0) for _, r in records[position + 1:] if r.get("session_id") == identifier), None)
                items = self.owner.store.chat_items(identifier)[receipt.get("cursor", 0):end]
                answer = "\n\n".join(str(item.get("text", "")) for item in items if item.get("role") == "assistant"
                                      and item.get("kind") not in ("action", "context"))
                value["answer"] = answer[-16000:]
                actions = self.owner.store.actions(identifier)
                jobs = []
                for action in actions:
                    if action.get("gateway_request_id") != request["request_id"]:
                        continue
                    job_id = (action.get("result") or {}).get("job_id")
                    if job_id:
                        session = self.owner.store.chat(identifier)
                        # History queries use current local scope and the stable business principal.
                        self.check_capability(session, "get_job_status", {})
                        authority = self.owner.capabilities.authority(identifier)
                        status = self.owner.capabilities.service.jobs.status(job_id, authority)
                        jobs.append(dict(job_id=job_id, state=status["state"], result=status["result"],
                                         channel_ids=status["request"]["arguments"].get("channel_ids", [])))
                value["jobs"] = jobs
            result[request["request_id"]] = value
        return result

    def export_receipts(self):
        values = self.correlations()
        def clean(value):
            if isinstance(value, str):
                value = self.owner.redactor.text(value)
                if self.project_path is not None:
                    from src.services.feishu_output import sanitize
                    value = sanitize(value, self.project_path, (), self.owner)
                else:
                    for target in self.owner.diagnostic.targets.values():
                        if target.password:
                            value = value.replace(target.password, "<凭据已隐藏>")
                return value
            if isinstance(value, dict):
                return {k: clean(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [clean(v) for v in value]
            return value
        return {key: clean(dict(value, instance_id=self.identity.instance_id, run_id=self.identity.run_id))
                for key, value in values.items()}

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        # Do not stop or cancel any admitted business Job on connection loss/disable.
        if not enabled:
            for session in self.owner.store.chats():
                if (session.get("source") or {}).get("gateway_instance_id") == self.identity.instance_id:
                    self.owner.permissions.forget(session["id"])

    def close(self):
        self.set_enabled(False)
        self.inbox.close()
