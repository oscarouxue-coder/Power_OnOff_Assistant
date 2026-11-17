"""Observational run ledger; never executes, replays or authorizes a device job."""
import json
import math
import threading
import time

from src.models.project_status import ProjectStatus
from src.services.project_store import atomic_json

TERMINAL = frozenset(('succeeded', 'failed', 'stopped', 'skipped', 'unknown', 'unchecked'))


def result_state(result):
    """Normalize structured results, never log text or thread liveness."""
    if isinstance(result, (list, tuple)):
        states = [result_state(item) for item in result]
        return next((state for state in ('unknown', 'failed', 'stopped') if state in states),
                    'succeeded' if states else 'skipped')
    if isinstance(result, bool):
        return 'succeeded' if result else 'failed'
    get = result.get if isinstance(result, dict) else lambda key, default=None: getattr(result, key, default)
    state = get('state')
    if state in TERMINAL:
        return state
    if get('uncertain', False) or get('unknown', False) or get('outcome_uncertain', False):
        return 'unknown'
    items = get('items')
    if isinstance(items, (list, tuple)) and any(
            result_state(getattr(item, 'operation', None)) == 'unknown'
            for item in items if getattr(item, 'operation', None) is not None):
        return 'unknown'
    if get('failed', 0) or get('device_errors', 0):
        return 'failed'
    # Upgrade transport results carry an explicit stop-result type.
    from src.models.upgrade_stop import UpgradeStoppedResult
    if (isinstance(result, UpgradeStoppedResult) or get('cancelled', False) or get('stopped', False)
            or get('error_kind') == 'cancelled' or get('stage') in ('stopped', 'cancelled')):
        return 'stopped'
    nested = get('result')
    if nested is not None:
        return result_state(nested)
    ok = get('ok')
    if type(ok) is bool:
        return 'succeeded' if ok else 'failed'
    success = get('success')
    if type(success) is bool:
        return 'succeeded' if success else 'failed'
    if get('executed') is not None:
        return 'unchecked' if get('unchecked', 0) else 'succeeded' if get('executed') else 'skipped'
    return 'unknown'


class ProjectStatusService:
    def __init__(self, emit=lambda text: None):
        self.emit = emit
        self.lock = threading.RLock()
        self.records = {}
        self.contexts = {}
        self.activity = {}
        self.external = {}
        self.observed_at = {}
        self.handoffs = {}

    def attach(self, context):
        key = context.identity.project_id
        with self.lock:
            if key in self.contexts:
                if self.contexts[key] is context:
                    return
                # A closed project may have moved or been updated elsewhere.
                # Re-open from its current root, never write a stale cached path.
                self.records = {owner: value for owner, value in self.records.items()
                                if value['project_id'] != key}
                self.activity.pop(key, None)
                self.external.pop(key, None)
                self.observed_at.pop(key, None)
            self.contexts[key] = context
            for path in (context.root / 'runs').glob('*/run.json'):
                try:
                    value = json.loads(path.read_text(encoding='utf-8'))
                    if value.get('project_id') != key or not value.get('owner'):
                        continue
                    if (not isinstance(value['owner'], str) or value.get('state') not in TERMINAL | {'prepared', 'queued', 'running', 'stopping'}
                            or not isinstance(value.get('updated_at', 0), (int, float))
                            or not math.isfinite(value.get('updated_at', 0))):
                        raise ValueError('invalid runtime metadata')
                    existing = self.records.get(value['owner'])
                    if existing is not None and existing['project_id'] != key:
                        raise ValueError('run identity belongs to another project')
                    value['_path'] = path
                    if value.get('state') in ('running', 'stopping'):
                        value.update(state='unknown', updated_at=time.time())
                        self._write(value)
                    self.records[value['owner']] = value
                except (OSError, ValueError, TypeError):
                    self.emit('[项目状态] 运行记录无法读取，请核实项目：' + context.identity.name)

    def _write(self, record):
        try:
            atomic_json(record['_path'], {k: v for k, v in record.items() if k != '_path'})
        except (OSError, TypeError, ValueError):
            self.emit('[项目状态] 状态记录写入失败，保留原业务结果和执行日志，请核实存储目录')

    def begin(self, context, owner, root, operation):
        self.attach(context)
        with self.lock:
            path = root / 'run.json'
            record = json.loads(path.read_text(encoding='utf-8'))
            record.update(owner=owner, operation=operation, state='prepared', created_at=time.time(), updated_at=time.time(), _path=path)
            self.records[owner] = record
            self._write(record)

    def update(self, owner, state, result=None):
        with self.lock:
            record = self.records.get(owner)
            if record is None:
                return
            # Duplicate/late completion cannot resurrect a finished run.
            if record['state'] in TERMINAL:
                return
            record.update(state=state, updated_at=time.time())
            if state == 'running':
                record.setdefault('started_at', record['updated_at'])
            elif state == 'stopping':
                record.setdefault('stop_requested_at', record['updated_at'])
            elif state in TERMINAL:
                record['finished_at'] = record['updated_at']
            self._write(record)
            if state in TERMINAL:
                self.emit('[项目状态] 任务结束：' + record['operation'] + '；项目=' +
                          self.contexts[record['project_id']].identity.name + '；运行=' + record['run_id'] + '；结果=' + state)

    def complete(self, owner, result=None, state=None):
        self.update(owner, state or result_state(result))

    def finish_unreported(self, owner):
        with self.lock:
            record = self.records.get(owner)
            if record and record['state'] not in TERMINAL:
                self.update(owner, 'skipped' if record['state'] == 'prepared' else 'unknown')

    def request_stop(self, project_id):
        with self.lock:
            for owner, record in self.records.items():
                if record['project_id'] == project_id and record['state'] == 'running':
                    self.update(owner, 'stopping')

    def set_activity(self, project_id, busy=False, closing=False, jobs=(), unknown_owners=()):
        with self.lock:
            external = (tuple(jobs), tuple(unknown_owners))
            if self.activity.get(project_id) != (busy, closing) or self.external.get(project_id) != external:
                self.observed_at[project_id] = time.time()
            self.activity[project_id] = (busy, closing)
            self.external[project_id] = external

    def hold_handoff(self, owner, delta):
        with self.lock:
            self.handoffs[owner] = max(0, self.handoffs.get(owner, 0) + delta)

    def is_held(self, owner):
        with self.lock:
            return bool(self.handoffs.get(owner))

    def is_unknown(self, owner):
        with self.lock:
            record = self.records.get(owner, {})
            return record.get('state') == 'unknown' and not record.get('reconciled', False)

    def reconcile(self, owner, outcome=None):
        with self.lock:
            record = self.records.get(owner)
            if record and record['state'] == 'unknown':
                record.update(updated_at=time.time(), reconciled=True)
                if outcome is not None:
                    record['state'] = outcome
                self._write(record)

    def snapshot(self, context):
        self.attach(context)
        key = context.identity.project_id
        with self.lock:
            records = [v for v in self.records.values() if v['project_id'] == key]
            jobs, fences = self.external.get(key, ((), ()))
            states = {v['owner']: v for v in records}
            states.update({v['job_id']: v for v in jobs})
            values = tuple(states.values())
            active = sum(v['state'] in ('queued', 'running', 'stopping') for v in values)
            unknown = {owner for owner, v in states.items() if v['state'] == 'unknown' and not v.get('reconciled')} | set(fences)
            terminals = [v for v in values if v['state'] in TERMINAL and v['state'] != 'skipped']
            last = max(terminals, key=lambda v: v.get('updated_at', 0), default={})
            result = last.get('state', '')
            busy, closing = self.activity.get(key, (False, False))
            stopping = closing or any(v['state'] == 'stopping' for v in values)
            state = ('stopping' if stopping else 'running' if active or busy else 'unknown' if unknown else
                     'failed' if result == 'failed' else 'stopped' if result == 'stopped' else 'idle')
            return ProjectStatus(state, max(active, int(busy)), len(unknown), result,
                                 max(self.observed_at.get(key, 0),
                                     max((v.get('updated_at', 0) for v in values), default=0)))
