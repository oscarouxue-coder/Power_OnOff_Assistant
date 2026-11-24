"""Durable host resource quarantine, not a second business task database."""
from pathlib import Path
import sqlite3
import threading

from src.models.capabilities import CapabilityError
from src.core.host_resource_lock import physical_key


class HostResourceFence:
    def __init__(self, directory):
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(Path(directory) / "resource_fence.sqlite3"), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS fence(resource TEXT PRIMARY KEY,owner TEXT,state TEXT)")
        self.db.commit()

    def acquire(self, owner, keys):
        # Caller already owns the OS locks; a leftover row is an interrupted/unknown operation.
        with self.lock, self.db:
            for key in keys:
                row = self.db.execute("SELECT owner FROM fence WHERE resource=?", (key,)).fetchone()
                if row and row[0] != owner:
                    raise CapabilityError("host_result_unknown", "物理资源存在未核实操作，禁止自动重试：" + key)
            self.db.executemany("INSERT OR REPLACE INTO fence VALUES(?,?,'active')", [(k, owner) for k in keys])

    def extend_active(self, owner, keys):
        """Only an existing, active capability job may extend its original fence."""
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            states = set(self.db.execute("SELECT DISTINCT state FROM fence WHERE owner=?", (owner,)))
            if states != {('active',)}:
                raise CapabilityError('owner_changed', '原任务没有可核实的活动资源占用')
            self.acquire(owner, keys)

    def release(self, owner, uncertain=False):
        with self.lock, self.db:
            if uncertain:
                self.db.execute("UPDATE fence SET state='unknown' WHERE owner=?", (owner,))
            else:
                self.db.execute("DELETE FROM fence WHERE owner=?", (owner,))

    def resolve(self, owner):
        # Only the existing locally reviewed jobs.resolve_unknown path calls this.
        with self.lock, self.db:
            self.db.execute("DELETE FROM fence WHERE owner=?", (owner,))

    def close(self):
        self.db.close()
