"""Local-operator-reviewed resource scopes, independent of model-supplied arguments."""
import json
import time
from src.models.capabilities import CapabilityError, fingerprint


class CapabilityScopes:
    def __init__(self, jobs):
        self.jobs = jobs
        with jobs.lock, jobs.db:
            jobs.db.execute("CREATE TABLE IF NOT EXISTS capability_scopes(principal TEXT,scope TEXT,digest TEXT,"
                "reviewer TEXT,created REAL,enabled INTEGER,PRIMARY KEY(principal,scope))")

    def allowed(self, principal, scope):
        if not scope:
            return True
        with self.jobs.lock:
            row = self.jobs.db.execute("SELECT digest,enabled FROM capability_scopes WHERE principal=? AND scope=?",
                                       (principal, scope["id"])).fetchone()
            if row and row[1] and row[0] == fingerprint(scope):
                return True
            if scope.get("access") == "read":
                write_scope = dict(scope, id=scope["id"].rsplit(":", 1)[0] + ":write", access="write")
                row = self.jobs.db.execute("SELECT digest,enabled FROM capability_scopes WHERE principal=? AND scope=?",
                                           (principal, write_scope["id"])).fetchone()
                return bool(row and row[1] and row[0] == fingerprint(write_scope))
            return False

    def require(self, authority, scope):
        if not self.allowed(authority.principal, scope):
            raise CapabilityError("local_scope_approval_required", "资源超出已审核范围，须本地负责人确认后才能复用", scope=scope)

    def grant(self, principal, scope, reviewer):
        """Called only after a fingerprint-bound local operator action, not exposed as an AI tool."""
        if not reviewer or not scope.get("id"):
            raise ValueError("缺少本地审阅人或资源范围")
        with self.jobs.lock, self.jobs.db:
            self.jobs.db.execute("INSERT OR REPLACE INTO capability_scopes VALUES(?,?,?,?,?,1)",
                                (principal, scope["id"], fingerprint(scope), reviewer, time.time()))

    def revoke(self, principal, scope_id):
        with self.jobs.lock, self.jobs.db:
            self.jobs.db.execute("UPDATE capability_scopes SET enabled=0 WHERE principal=? AND scope=?", (principal, scope_id))
