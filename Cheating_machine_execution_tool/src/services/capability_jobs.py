"""Durable business jobs; no model stop token, GUI objects, credentials or auto replay."""
from pathlib import Path
import json
import sqlite3
import threading
import time
import uuid
import os

from src.models.capabilities import CapabilityError, fingerprint
from src.services.upgrade_stop_service import UpgradeStopControl


TERMINAL = frozenset(("succeeded", "failed", "stopped", "skipped", "unknown"))


class JobContext:
    def __init__(self, service, identifier, stop):
        self.service, self.job_id, self.stop = service, identifier, stop
        self.dispatched = False

    def event(self, stage, message="", dispatched=False):
        self.dispatched |= dispatched
        self.service.event(self.job_id, stage, message)


class CapabilityJobs:
    def __init__(self, directory, resources, emit=lambda line: None, metrics=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.instance_lease = None
        if os.name == "nt":
            from src.core.dingtalk_stream import InstanceLease
            self.instance_lease = InstanceLease("business-jobs:" + os.path.normcase(str(self.directory.resolve())))
            self.instance_lease.acquire()
        self.lock = threading.RLock()
        self.submit_lock = threading.RLock()
        self.db = sqlite3.connect(str(self.directory / "capability_jobs.sqlite3"), check_same_thread=False)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, request_key TEXT UNIQUE,
                fingerprint TEXT, principal TEXT, session_id TEXT, capability TEXT,
                state TEXT, stage TEXT, created REAL, updated REAL, payload TEXT, result TEXT);
            CREATE TABLE IF NOT EXISTS job_events(id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT, created REAL, stage TEXT, message TEXT);
            CREATE INDEX IF NOT EXISTS job_events_job ON job_events(job_id,id);
        ''')
        with self.db:
            self.db.execute("UPDATE jobs SET state='unknown',stage='process_interrupted',updated=? "
                            "WHERE state NOT IN ('succeeded','failed','stopped','skipped','unknown')", (time.time(),))
        self.resources, self.emit, self.metrics = resources, emit, metrics
        self.threads, self.controls = {}, {}
        self.closing = False

    @property
    def idle(self):
        with self.lock:
            self.threads = {key: value for key, value in self.threads.items() if value.is_alive()}
            return not self.threads

    def _row(self, identifier):
        row = self.db.execute("SELECT id,principal,session_id,capability,state,stage,created,updated,payload,result "
                              "FROM jobs WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise CapabilityError("job_not_found", "任务不存在")
        result = dict(zip(("job_id", "principal", "session_id", "capability_id", "state", "stage", "created", "updated",
                           "request", "result"), row))
        result["request"], result["result"] = json.loads(result["request"]), json.loads(result["result"])
        return result

    def status(self, identifier, authority, after_event=0):
        authority.check()
        with self.lock:
            result = self._row(identifier)
            if result["principal"] != authority.principal:
                raise CapabilityError("job_forbidden", "该任务不属于当前可信操作身份")
            authority.check(result["request"]["arguments"].get("channel_ids", ()))
            authority.check(result["request"].get("arguments", {}).get("channel_ids", ()))
            # A job remains queryable after a conversation switch, but never by another remote identity.
            result.pop("principal")
            result["events"] = [dict(event_id=r[0], created=r[1], stage=r[2], message=r[3]) for r in self.db.execute(
                "SELECT id,created,stage,message FROM job_events WHERE job_id=? AND id>? ORDER BY id LIMIT 200",
                (identifier, after_event))]
            return result

    def find(self, capability, authority):
        """Read-only recovery by the host's original operation identity; never admit."""
        authority.check()
        request_key = fingerprint((authority.principal, authority.operation_id, capability))
        with self.lock:
            row = self.db.execute("SELECT id FROM jobs WHERE request_key=?", (request_key,)).fetchone()
        return self.status(row[0], authority) if row else None

    def event(self, identifier, stage, message=""):
        with self.lock, self.db:
            self.db.execute("UPDATE jobs SET stage=?,updated=? WHERE id=?", (stage, time.time(), identifier))
            self.db.execute("INSERT INTO job_events(job_id,created,stage,message) VALUES(?,?,?,?)",
                            (identifier, time.time(), stage, str(message)))
        if message:
            self.emit(f"[业务任务 {identifier[:8]}][{stage}] {message}")

    def start(self, capability, arguments, authority, resources, runner, *, risk="dangerous", recheck=lambda: None, observational=False):
        # Serialize submissions without keeping the database mutex across Tk admission/snapshots.
        # The GUI is free to inspect/cancel jobs while a worker waits for its data bridge.
        with self.submit_lock:
            return self._start(capability, arguments, authority, resources, runner, risk=risk,
                               recheck=recheck, observational=observational)

    def _start(self, capability, arguments, authority, resources, runner, *, risk, recheck, observational):
        authority.check(arguments.get("channel_ids", ()), risk)
        digest = fingerprint(dict(capability=capability, arguments=arguments))
        request_key = fingerprint((authority.principal, authority.operation_id, capability))
        with self.lock:
            if self.closing:
                raise CapabilityError("closing", "程序正在退出，不启动新业务")
            previous = self.db.execute("SELECT id,fingerprint FROM jobs WHERE request_key=?", (request_key,)).fetchone()
            if previous:
                if previous[1] != digest:
                    raise CapabilityError("request_changed", "同一操作标识的参数已变化，请明确发起新任务")
                return dict(job_id=previous[0], state=self._row(previous[0])["state"], reused=True)
            active = self.db.execute("SELECT id,state FROM jobs WHERE fingerprint=? AND principal=? "
                "AND state NOT IN ('succeeded','failed','stopped','skipped','unknown')", (digest, authority.principal)).fetchone()
            if active:
                return dict(job_id=active[0], state=active[1], reused=True)
            # Unknown results block a new operation even after a process restart.
            for old_id, payload, principal in self.db.execute("SELECT id,payload,principal FROM jobs WHERE state='unknown'"):
                old = json.loads(payload)
                affected = {r for r in old.get("resources", ()) if r.startswith(("channel:", "serial:", "adapter:", "olt:", "pon:"))}
                if not observational and affected & set(resources):
                    raise CapabilityError("previous_result_unknown", "相关资源存在结果未知的历史任务，须先核实处理")
            identifier = uuid.uuid4().hex
        self.resources.acquire(identifier, resources)
        try:
            recheck()
            with self.lock:
                if self.closing:
                    raise CapabilityError("closing", "程序正在退出，任务未下发")
                now = time.time()
                payload = dict(arguments=arguments, resources=list(resources))
                with self.db:
                    self.db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (identifier, request_key, digest, authority.principal, authority.session_id, capability,
                         "queued", "preparing", now, now, json.dumps(payload, ensure_ascii=False), "null"))
                control = self.controls[identifier] = UpgradeStopControl()
                thread = threading.Thread(target=self._run, args=(identifier, runner, control),
                                          name="capability-" + identifier[:8], daemon=True)
                self.threads[identifier] = thread
                thread.start()
        except BaseException:
            self.resources.release(identifier)
            with self.lock:
                self.controls.pop(identifier, None)
                self.threads.pop(identifier, None)
                with self.db:
                    self.db.execute("UPDATE jobs SET state='failed',updated=?,result=? WHERE id=?",
                        (time.time(), json.dumps(dict(ok=False, dispatched=False, error="任务未能启动")), identifier))
            raise
        return dict(job_id=identifier, state="queued", reused=False)

    def _run(self, identifier, runner, control):
        context = JobContext(self, identifier, control)
        started = time.monotonic()
        state, result = "unknown", None
        try:
            with self.lock, self.db:
                self.db.execute("UPDATE jobs SET state='running' WHERE id=?", (identifier,))
            context.event("preparing", "业务任务开始；独立于模型请求运行")
            result = runner(context)
            state = result.get("state", "succeeded" if result.get("ok") else "failed")
            if state not in TERMINAL:
                raise ValueError("业务返回了无效终态")
        except Exception as exc:
            from src.models.upgrade_stop import UpgradeStopped
            state = "stopped" if isinstance(exc, UpgradeStopped) else "unknown" if context.dispatched else "failed"
            result = dict(ok=False, error=str(exc), dispatched=context.dispatched)
        finally:
            try:
                with self.lock, self.db:
                    self.db.execute("UPDATE jobs SET state=?,updated=?,result=? WHERE id=?",
                        (state, time.time(), json.dumps(result, ensure_ascii=False), identifier))
                context.event(state, "业务任务结束：" + state)
                if self.metrics:
                    self.metrics.record(dict(kind="business_job", capability_id=self._row(identifier)["capability_id"],
                                             state=state, total_seconds=time.monotonic() - started))
            finally:
                if getattr(self.resources, "fence", None):
                    self.resources.release(identifier, uncertain=state == "unknown")
                else:
                    self.resources.release(identifier)
                with self.lock:
                    self.controls.pop(identifier, None)

    def cancel(self, identifier, authority):
        status = self.status(identifier, authority)
        authority.check(risk="dangerous")
        with self.lock:
            control = self.controls.get(identifier)
            if control and status["state"] not in TERMINAL:
                control.request_stop()
                with self.db:
                    self.db.execute("UPDATE jobs SET state='stop_requested' WHERE id=?", (identifier,))
                return dict(job_id=identifier, state="stop_requested", notice="等待原业务安全停止边界，不代表已撤销")
        return dict(job_id=identifier, state=status["state"], notice="任务已终结，未重复执行操作")

    def begin_close(self):
        with self.lock:
            self.closing = True
            for control in self.controls.values():
                control.request_stop()

    def resolve_unknown(self, identifier, authority, outcome, evidence):
        """Host calls this only after a locally reviewed, immutable reconciliation scope."""
        self.status(identifier, authority)
        if outcome not in ("succeeded", "failed", "not_executed") or not evidence.strip():
            raise CapabilityError("invalid_parameters", "必须记录明确现场核实结果和依据")
        with self.lock, self.db:
            current = self._row(identifier)
            if current["state"] != "unknown":
                return dict(job_id=identifier, state=current["state"], notice="不是未知任务，未更改结果")
            result = current["result"] or {}
            result["reconciliation"] = dict(outcome=outcome, evidence=evidence, reviewed_scope=True, created=time.time())
            state = "succeeded" if outcome == "succeeded" else "failed"
            self.db.execute("UPDATE jobs SET state=?,updated=?,result=? WHERE id=? AND state='unknown'",
                (state, time.time(), json.dumps(result, ensure_ascii=False), identifier))
        self.event(identifier, "reconciled", "本地负责人已审阅现场核实依据；仅解除未知状态，不执行设备操作")
        if getattr(self.resources, "fence", None):
            self.resources.fence.resolve(identifier)
        return dict(job_id=identifier, state=state, notice="已保留原结果和核实记录；不会自动重试")

    def close(self):
        self.begin_close()
        if not self.idle:
            raise RuntimeError("业务任务仍在安全收尾，不能关闭任务存储")
        self.db.close()
        if self.instance_lease is not None:
            self.instance_lease.close()
