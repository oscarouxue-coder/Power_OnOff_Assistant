"""Application-wide admission, retaining host locks and durable unknown fences."""
from pathlib import Path
from collections import defaultdict
import ipaddress
import sqlite3
import threading
import uuid
import json

from src.core.host_resource_lock import HostResourceLock, physical_key
from src.models.capabilities import CapabilityError
from src.models.qt_device_inventory import ResourceLeaseEntry
from src.services.host_resource_fence import HostResourceFence


PHYSICAL_PREFIXES = ("serial:", "power:", "adapter:", "olt:", "pon:", "wifi:", "tftp:", "dut:", "adb:")


def _pon_parent(value):
    # Current ONU adapters produce <host>:gpon-olt_1/2/3 (or :OLT).
    # Earlier callers may supply <host>/<target>. Preserve complete IPv6 hosts.
    head = value.split('/', 1)[0]
    try:
        ipaddress.ip_address(head.strip('[]'))
    except ValueError:
        host, separator, _ = head.rpartition(':')
        return host if separator else head
    return head


class WorkspaceResources:
    def __init__(self, directory):
        self.lock = threading.RLock()
        self.owners = {}
        self.labels = {}
        self.guards = {}
        self.fence = HostResourceFence(directory)
        self.aliases = {}
        self.run_id = uuid.uuid4().hex
        self.uncertain = set()
        self.inventory_ready = True
        self.hardware_error = ''
        with self.fence.db:
            self.fence.db.execute('CREATE TABLE IF NOT EXISTS workspace_owners(owner TEXT PRIMARY KEY,group_id TEXT,state TEXT,label TEXT)')
            if 'label' not in {row[1] for row in self.fence.db.execute('PRAGMA table_info(workspace_owners)')}:
                self.fence.db.execute("ALTER TABLE workspace_owners ADD COLUMN label TEXT DEFAULT ''")
            if 'keys' not in {row[1] for row in self.fence.db.execute('PRAGMA table_info(workspace_owners)')}:
                self.fence.db.execute("ALTER TABLE workspace_owners ADD COLUMN keys TEXT")
            self.fence.db.execute("CREATE INDEX IF NOT EXISTS pending_workspace_groups "
                                  "ON workspace_owners(group_id) WHERE state != 'done'")
        # Sampling must not wait behind another process's writer on the command thread.
        database = (Path(directory) / 'resource_fence.sqlite3').resolve()
        self._lease_reader = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=0, check_same_thread=False)

    def register_adapter(self, alias, guid):
        if alias and guid:
            with self.lock:
                self.aliases[str(alias).split(" [", 1)[0].casefold()] = str(guid).casefold()
                alias_key = physical_key('adapter:' + str(alias).split(' [', 1)[0])
                for owner, (project, keys) in tuple(self.owners.items()):
                    if alias_key in keys:
                        self.acquire(owner, project, self.labels[owner], keys)

    def keys(self, keys):
        result = set()
        for key in keys:
            if not str(key).startswith(PHYSICAL_PREFIXES):
                continue
            key = physical_key(key)
            kind, _, value = key.partition(":")
            if kind == "adapter":
                value = value.split(" [", 1)[0]
                result.add('adapter:' + value)
                value = self.aliases.get(value, value)
                key = "adapter:" + value
            if kind == "pon":
                result.add("olt:" + _pon_parent(value))
            result.add(key)
        return tuple(sorted(result))

    def acquire(self, owner, project_id, label, keys):
        keys = self.keys(keys)
        with self.lock:
            if keys and self.hardware_error:
                raise CapabilityError('host_protection_unavailable', self.hardware_error)
            if not self.inventory_ready and any(key.startswith('adapter:') for key in keys):
                raise CapabilityError('inventory_pending', '网卡身份尚未完成核验，请等待或刷新串口/网卡后重试')
            group = self.run_id + ':' + project_id
            if group in self.uncertain:
                raise CapabilityError('host_result_unknown', '本项目存在未核实操作，请先核实任务结果')
            for key in keys:
                for held, (project, held_keys) in self.owners.items():
                    if project != project_id and key in held_keys:
                        raise CapabilityError("resource_busy", "资源 " + key + " 正由项目“" + self.labels[held] + "”使用")
            previous = self.owners.get(owner)
            keys = tuple(sorted(set(keys) | set(previous[1] if previous else ())))
            guard = HostResourceLock(keys).acquire()
            try:
                self.fence.acquire(group, keys)
            except BaseException:
                guard.close()
                raise
            old = self.guards.pop(owner, None)
            self.guards[owner] = guard
            self.owners[owner], self.labels[owner] = (project_id, keys), label
            with self.fence.db:
                self.fence.db.execute('INSERT OR REPLACE INTO workspace_owners(owner,group_id,state,label,keys) VALUES(?,?,?,?,?)',
                                     (owner, group, 'active', label, json.dumps(keys)))
            if old:
                old.close()

    def busy_for(self, project_id, keys):
        keys = set(self.keys(keys))
        with self.lock:
            if keys and self.hardware_error:
                return True
            if not self.inventory_ready and any(key.startswith('adapter:') for key in keys):
                return True
            return any(project != project_id and keys.intersection(held) for project, held in self.owners.values())

    def lease_entries(self):
        """Actual local reservations and durable protection with no verified local owner."""
        with self.lock:
            rows = set()
            assigned = defaultdict(set)
            for owner, (project, keys) in self.owners.items():
                group = self.run_id + ':' + project
                assigned[group].update(keys)
                for key in keys:
                    rows.add(ResourceLeaseEntry(key, project, self.labels.get(owner, ''), owner, 'held'))

            # Both halves read one SQLite snapshot. Old completed jobs never imply a
            # current reservation, and per-job key lists cannot outlive their fence.
            records = self._lease_reader.execute("""
                SELECT owner,resource,NULL,NULL,NULL FROM fence
                UNION ALL
                SELECT group_id,NULL,owner,label,keys FROM workspace_owners
                WHERE state != 'done' AND group_id IN (SELECT owner FROM fence)
            """).fetchall()
            fenced = defaultdict(set)
            names = defaultdict(set)
            unmapped = set()
            for group, key, _, _, _ in records:
                if key is not None:
                    fenced[group].add(key)
            for group, key, owner, name, payload in records:
                if key is not None:
                    continue
                if name:
                    names[group].add(name)
                if owner in self.owners and group == self.run_id + ':' + self.owners[owner][0]:
                    continue
                try:
                    owned = json.loads(payload) if payload is not None else None
                except (TypeError, ValueError, RecursionError):
                    owned = None
                if not isinstance(owned, list) or not all(isinstance(k, str) for k in owned):
                    unmapped.add(group)
                    continue
                project = group.partition(':')[2]
                for retained in fenced[group].intersection(owned):
                    rows.add(ResourceLeaseEntry(retained, project, name or '', owner, 'unresolved'))
                    assigned[group].add(retained)
            for group, keys in fenced.items():
                for key in keys if group in unmapped else keys - assigned[group]:
                    # A legacy row or interrupted handoff may retain a key without
                    # any per-job mapping. Do not invent an owner from a group ID.
                    run, _, project = group.partition(':')
                    if len(run) != 32 or any(ch not in '0123456789abcdef' for ch in run):
                        project = ''
                    label = next(iter(names[group])) if len(names[group]) == 1 else ''
                    rows.add(ResourceLeaseEntry(key, project, label, '', 'unresolved'))
            return tuple(sorted(rows, key=lambda row: (row.resource_key, row.state, row.project_id, row.owner_id)))

    def _refresh_fence(self, group):
        """Keep only resources still owned by active or unreviewed operations."""
        existing = {row[0] for row in self.fence.db.execute('SELECT resource FROM fence WHERE owner=?', (group,))}
        retained = set()
        uncertain = False
        for payload, state in self.fence.db.execute("SELECT keys,state FROM workspace_owners WHERE group_id=? AND state != 'done'", (group,)):
            uncertain |= state == 'unknown'
            try:
                keys = json.loads(payload) if payload is not None else None
                # A new logical operation may own no physical keys. Only legacy
                # or malformed rows without key metadata retain the whole group.
                retained.update(keys if isinstance(keys, list) and all(isinstance(key, str) for key in keys) else existing)
            except (ValueError, TypeError):
                retained.update(existing)
        for key in existing - retained:
            self.fence.db.execute('DELETE FROM fence WHERE resource=? AND owner=?', (key, group))
        if uncertain:
            self.uncertain.add(group)
        else:
            self.uncertain.discard(group)
        self.fence.db.execute('UPDATE fence SET state=? WHERE owner=?', ('unknown' if uncertain else 'active', group))

    def release(self, owner, uncertain=False):
        with self.lock:
            previous = self.owners.pop(owner, None)
            row = self.fence.db.execute('SELECT group_id FROM workspace_owners WHERE owner=?', (owner,)).fetchone()
            group = row[0] if row else None
            if group:
                if uncertain:
                    self.uncertain.add(group)
                with self.fence.db:
                    self.fence.db.execute("UPDATE workspace_owners SET state=? WHERE owner=?", ('unknown' if uncertain else 'done', owner))
                    self._refresh_fence(group)
            self.labels.pop(owner, None)
            guard = self.guards.pop(owner, None)
            if guard:
                guard.close()

    def resolve(self, owner):
        with self.lock, self.fence.db:
            row = self.fence.db.execute('SELECT group_id FROM workspace_owners WHERE owner=?', (owner,)).fetchone()
            if row:
                group = row[0]
                keys = [r[0] for r in self.fence.db.execute('SELECT resource FROM fence WHERE owner=?', (group,))]
                with HostResourceLock(keys):
                    self.fence.db.execute("UPDATE workspace_owners SET state='done' WHERE owner=?", (owner,))
                    self._refresh_fence(group)
            else:
                self.fence.resolve(owner)

    def unknown_for(self, project_id):
        with self.lock:
            return tuple(owner for owner, group, state in self.fence.db.execute(
                "SELECT owner,group_id,state FROM workspace_owners WHERE state != 'done'")
                if group.endswith(':' + project_id) and
                (state == 'unknown' or not group.startswith(self.run_id + ':')))

    def unknown_gui(self):
        with self.lock:
            return [(owner, label or owner) for owner, group, state, label in self.fence.db.execute(
                "SELECT owner,group_id,state,label FROM workspace_owners WHERE owner LIKE 'gui:%' AND state != 'done'")
                if state == 'unknown' or not group.startswith(self.run_id + ':')]

    def close(self):
        with self.lock:
            for owner in tuple(self.owners):
                self.release(owner, uncertain=True)
            self._lease_reader.close()
            self.fence.db.close()
