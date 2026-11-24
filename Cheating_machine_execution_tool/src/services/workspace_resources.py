"""Application-wide admission, retaining host locks and durable unknown fences."""
from pathlib import Path
from collections import defaultdict
import ipaddress
import os
import sqlite3
import threading
import uuid
import json

from src.core.host_resource_lock import HostResourceBusy, HostResourceLock, physical_key
from src.models.capabilities import CapabilityError
from src.models.project_review import ReviewRequired
from src.models.qt_device_inventory import ResourceLeaseEntry
from src.services.host_resource_fence import HostResourceFence


PHYSICAL_PREFIXES = ("serial:", "power:", "adapter:", "olt:", "pon:", "wifi:", "tftp:", "dut:", "adb:")


def host_resource_directory():
    return Path(os.environ.get('PROGRAMDATA', str(Path.home()))) / 'LineCheckAssistant' / 'host-resource-fence'


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
        self.recovery_context = None
        self.emit = lambda message: None
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
                raise ReviewRequired('inventory_pending', '网卡身份尚未完成核验，请等待或刷新串口/网卡后重试',
                                     'inventory', reference='adapter:')
            group = self.run_id + ':' + project_id
            if self.recovery_context is not None:
                self.recover_stale(project_id, keys, strict=True)
            elif group in self.uncertain:
                raise ReviewRequired('host_result_unknown', '本项目存在未核实操作，请先核实任务结果', 'project', 'task')
            for key in keys:
                for held, (project, held_keys) in self.owners.items():
                    if project != project_id and key in held_keys:
                        raise ReviewRequired("resource_busy", "资源 " + key + " 正由项目“" + self.labels[held] + "”使用",
                                             'inventory', reference=key)
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

    @property
    def automatic_recovery(self):
        return self.recovery_context is not None

    @staticmethod
    def _owner_keys(payload, fallback):
        try:
            keys = json.loads(payload) if payload is not None else None
        except (TypeError, ValueError, RecursionError):
            keys = None
        return set(keys) if isinstance(keys, list) and all(isinstance(key, str) for key in keys) else fallback

    def recover_stale(self, project_id, keys=(), *, strict=False):
        """Retire stale reservations once their project and resources can be locked."""
        if not self.automatic_recovery:
            return
        requested = set(keys)
        with self.lock:
            records = self.fence.db.execute(
                "SELECT owner,group_id,state,keys FROM workspace_owners WHERE state != 'done'").fetchall()
            groups = defaultdict(list)
            for owner, group, state, payload in records:
                if owner not in self.owners and (state == 'unknown' or not group.startswith(self.run_id + ':')):
                    groups[group].append((owner, state, payload))
            fences = defaultdict(set)
            for key, group in self.fence.db.execute('SELECT resource,owner FROM fence'):
                fences[group].add(key)
                if (key in requested or group.endswith(':' + project_id)) and not group.startswith(self.run_id + ':'):
                    groups.setdefault(group, [])
            for group, entries in groups.items():
                run, separator, origin = group.partition(':')
                if origin != project_id and not requested.intersection(fences[group]):
                    continue
                foreign = run != self.run_id
                if not separator or not origin or len(run) != 32 or any(ch not in '0123456789abcdef' for ch in run):
                    notice = '无法识别旧占用所属项目'
                else:
                    notice = self._recover_group(group, origin, entries, fences[group], requested, foreign)
                if notice:
                    message = '[资源保护] ' + (', '.join(sorted(fences[group])) or origin) + '：' + notice
                    self.emit(message)
                    if strict and (origin == project_id or requested.intersection(fences[group])):
                        raise CapabilityError('resource_busy', message)

    def _recover_group(self, group, project_id, entries, fenced, requested, foreign):
        from src.services.power_worker_lifetime import power_worker_notice

        context, own_project_lease = self.recovery_context(project_id)
        if context is None:
            return '无法读取旧占用所属项目，待项目路径可用后重试'
        project_lock = HostResourceLock(['project:' + project_id], reentrant=own_project_lease)
        try:
            with project_lock:
                notice = power_worker_notice(context)
                if notice:
                    return notice
                if not entries:
                    try:
                        with HostResourceLock(fenced, reentrant=False), self.fence.db:
                            cursor = self.fence.db.execute(
                                "DELETE FROM fence WHERE owner=? AND NOT EXISTS ("
                                "SELECT 1 FROM workspace_owners WHERE group_id=? AND state != 'done')",
                                (group, group))
                    except HostResourceBusy:
                        return '关联资源仍被原进程占用或无法取得系统锁，请等待释放'
                    if cursor.rowcount:
                        self.emit('[资源保护] 已释放失效占用 ' + ', '.join(sorted(fenced)))
                for owner, state, payload in entries:
                    keys = self._owner_keys(payload, fenced) & fenced
                    if not foreign and owner.startswith('serial-session:'):
                        if requested.intersection(keys):
                            return '本次运行的串口会话尚未确认关闭，请等待程序退出后重试'
                        continue
                    try:
                        with HostResourceLock(keys, reentrant=False), self.fence.db:
                            cursor = self.fence.db.execute(
                                "UPDATE workspace_owners SET state='done' "
                                "WHERE owner=? AND group_id=? AND state=? AND keys IS ?",
                                (owner, group, state, payload))
                            if cursor.rowcount:
                                self._refresh_fence(group, release_keys=keys)
                    except HostResourceBusy:
                        if requested.intersection(keys):
                            return '关联资源仍被原进程占用或无法取得系统锁，请等待释放'
                        continue
                    if cursor.rowcount:
                        self.emit('[资源保护] 已释放失效占用 ' + owner +
                                  (' · ' + ', '.join(sorted(keys)) if keys else ''))
        except HostResourceBusy:
            return '原项目仍由其他进程持有或无法取得项目锁，请等待释放'
        return ''

    def busy_for(self, project_id, keys):
        keys = set(self.keys(keys))
        with self.lock:
            if keys and self.hardware_error:
                return True
            if not self.inventory_ready and any(key.startswith('adapter:') for key in keys):
                return True
            return any(project != project_id and keys.intersection(held) for project, held in self.owners.values())

    def extend_adapter_owner(self, owner, bindings):
        """Add verified alias/GUID pairs to the same live project admission."""
        with self.lock:
            if owner not in self.owners:
                raise CapabilityError('owner_changed', '挂测原资源所有者已失效')
            if any(self.aliases.get(alias, guid) != guid for alias, guid in bindings):
                raise CapabilityError('target_changed', '已登记的网卡身份与当前接口不符')
            keys = {'adapter:' + name for pair in bindings for name in pair}
            if any(other != owner and keys.intersection(held)
                   for other, (_, held) in self.owners.items()):
                raise CapabilityError('resource_busy', '挂测网卡已由另一项操作占用')
            project, _ = self.owners[owner]
            self.acquire(owner, project, self.labels[owner], keys)

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

    def _refresh_fence(self, group, *, release_keys=None):
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
        released = existing - retained
        if release_keys is not None:
            released.intersection_update(release_keys)
        for key in released:
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
