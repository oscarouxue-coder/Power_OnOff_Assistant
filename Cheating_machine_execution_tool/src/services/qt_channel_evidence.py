"""One local, read-only question over an admitted continuous-aging run."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
import json
import math
import re
import time

from src.models.capabilities import CapabilitySpec, object_schema
from src.models.project_profile import COLLECTOR_LABELS, normalize_project_profile
from src.services.capability_registry import CapabilityRegistry
from src.services.project_profile_store import PROFILE_FILE, active_project_duts
from src.services.qt_service_aging import START
from src.services.service_aging_history import ServiceAgingHistory


@dataclass(frozen=True)
class EvidenceTarget:
    project_id: str
    job_id: str
    run_id: str
    revision: str
    dut_id: str
    channel: int


def _json(path):
    if path.resolve() != path:
        raise ValueError('批次快照路径已重定向')
    with path.open('rb') as stream:
        data = stream.read(256 * 1024 + 1)
    if len(data) > 256 * 1024:
        raise ValueError('批次快照超出读取上限')
    return json.loads(data.decode('utf-8'))


def _channels(directory):
    profile = normalize_project_profile(_json(directory / PROFILE_FILE), assign_ids=False)
    if profile['test_type'] != 'service_aging':
        raise ValueError('快照不是持续老化批次')
    return tuple((row['dut_id'], row['channel']) for row in active_project_duts(profile, directory)
                 if row['channel'] is not None)


@lru_cache(maxsize=64)
def _display_channels(directory):
    # Immutable run configuration; the query independently rechecks the actual file.
    return _channels(directory)


def display_channels(context, record):
    run_id = record.get('run_id')
    if not isinstance(run_id, str) or not re.fullmatch('[0-9a-f]{32}', run_id):
        return ()
    run = context.root / 'runs' / run_id
    if record.get('_path') != run / 'run.json' or record.get('project_id') != context.identity.project_id:
        return ()
    try:
        return _display_channels(run / 'Auto_power_on_off_tool/config')
    except (OSError, ValueError, RuntimeError):
        return ()


def _verify_binding(target, context, record):
    if context.identity.project_id != target.project_id or not re.fullmatch('[0-9a-f]{32}', target.run_id):
        raise ValueError('项目与运行批次不一致')
    run = context.root / 'runs' / target.run_id
    manifest = run / 'run.json'
    expected = dict(owner=target.job_id, project_id=target.project_id, run_id=target.run_id,
                    revision=target.revision, operation=START)
    if record.get('_path') != manifest or any(record.get(k) != v for k, v in expected.items()):
        raise ValueError('任务与批次不一致，未读取观测')
    saved = _json(manifest)
    if any(saved.get(k) != v for k, v in expected.items()):
        raise ValueError('批次身份已变化，未读取观测')
    if (target.dut_id, target.channel) not in _channels(run / 'Auto_power_on_off_tool/config'):
        raise ValueError('该批次的通道与所选 DUT 不一致，未读取观测')


def _report(target, rows, run, now):
    lines = []
    presence = []
    sources = {'manual': '人工记录', 'icmp': '绑定网卡 Ping', 'jsonl': '现场采集'}
    for row in rows:
        at = row['at']
        if type(at) not in (int, float) or not math.isfinite(at) or not run['started'] <= at <= now:
            continue
        try:
            stamp = datetime.fromtimestamp(at, timezone.utc).isoformat(timespec='seconds')
        except (ValueError, OSError, OverflowError):
            continue
        collector, outcome = row['collector'], row['outcome']
        status = {'healthy': '正常', 'abnormal': '异常', 'unknown': '未知'}.get(outcome, '未知')
        if collector == 'dut_presence' and row['kind'] == 'sample' and row['source'] == 'jsonl' and row['has_event']:
            status = {'healthy': '在线心跳', 'abnormal': '离线', 'unknown': '未知'}.get(outcome, '未知')
            presence.append((status, row['id']))
        age = 86400 if row['source'] == 'manual' else run['freshness']
        stale = ' · 已过有效期' if now - at > age else ''
        excerpt = '\n'.join('  │ ' + line for line in (row['evidence'] or '').splitlines())
        lines.append(f"{stamp} · {sources.get(row['source'], '来源未知')} · 观测 #{row['id']} · "
                     f"{COLLECTOR_LABELS.get(collector, '未知采集项')} · {status}{stale}\n{excerpt}")
    offline = [identifier for status, identifier in presence if status == '离线']
    summary = ('本页缺少设备离线观测，无法确认掉线或其原因。' if not offline else
               f'本页记录了 {len(offline)} 条设备离线观测（记录 #{", #".join(map(str, offline))}），掉线原因未确定。')
    if offline and any(status == '在线心跳' and offline[-1] < key < offline[0] for status, key in presence):
        summary += '两次离线观测之间有在线心跳。'
    if not lines:
        summary = '指定范围内没有可引用的有效观测，无法判断掉线原因。'
    return '\n\n'.join([f'CH{target.channel:02d} · {summary}', '以下为历史观测，最多显示最近 48 条。', *lines])


def _read(args, request):
    context, record, stop, clock = request
    target = EvidenceTarget(**args)
    if stop.is_set():
        raise InterruptedError()
    _verify_binding(target, context, record)
    history = ServiceAgingHistory(context, clock)
    rows, run = history.channel_observations(target.job_id, target.revision, target.dut_id, stop)
    if stop.is_set():
        raise InterruptedError()
    return _report(target, rows, run, clock())


# Only this in-process reader is reachable from the offline entry. Initializing
# the live project registry would also initialize its persistent job store.
_REGISTRY = CapabilityRegistry()
_ID = 'service_aging.channel_evidence'
_FIELDS = {k: dict(type='string', minLength=1, maxLength=128)
           for k in ('project_id', 'job_id', 'run_id', 'revision', 'dut_id')}
_FIELDS['channel'] = dict(type='integer', minimum=1, maximum=16)
_REGISTRY.register(CapabilitySpec(_ID, '查看通道掉线证据', '查询指定持续老化批次已经记录的观测',
    object_schema(_FIELDS, tuple(_FIELDS)), _read, sources=('gui',)))


def read_channel_evidence(context, record, target, stop, clock=time.time):
    args = asdict(target)
    spec = _REGISTRY.validate(_ID, args)
    return spec.handler(args, (context, record, stop, clock))
