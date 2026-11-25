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


@dataclass(frozen=True)
class ChatEvidenceResult:
    target: EvidenceTarget
    checked_at: str
    candidates: int
    expired: int
    invalid_time: int
    valid: int
    cited_ids: tuple
    outcome: str
    observation_text: str

    def render(self, identifier=None):
        target = self.target
        title = '本地查询' if identifier is None else f'本地查询 #{identifier}'
        return '\n\n'.join((
            title + ' · 已完成',
            f'目标核对通过 · CH{target.channel:02d}\n项目 {target.project_id}\n任务 {target.job_id}\n'
            f'批次 {target.run_id}\n版本 {target.revision}\nDUT {target.dut_id}',
            f'只读取证完成 · 核对时间 {self.checked_at}\n最近候选 {self.candidates} 条，过期 {self.expired} 条，'
            f'时间无效 {self.invalid_time} 条。符合时效 {self.valid} 条，引用 {len(self.cited_ids)} 条，'
            f'其余 {self.valid - len(self.cited_ids)} 条未展开。',
            '分析结果 · ' + self.outcome, self.observation_text))


def disconnect_question_channel(text):
    question = re.fullmatch(r'CH[ \t]*([0-9]{1,8})[ \t]*为什么(?:会)?(?:反复|频繁)掉线[?？]?',
                            text.strip(), re.IGNORECASE | re.ASCII)
    return int(question[1]) if question else None


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


def _report(target, rows, run, now, *, for_chat=False):
    if for_chat and (type(run['freshness']) not in (int, float) or not math.isfinite(run['freshness'])
                     or run['freshness'] <= 0):
        raise ValueError('当前批次缺少有效的观测时效，无法判断掉线原因')
    lines = []
    expired = invalid_time = valid = 0
    cited_ids = []
    presence = []
    sources = {'manual': '人工记录', 'icmp': '绑定网卡 Ping', 'jsonl': '现场采集'}
    for row in rows:
        at = row['at']
        if type(at) not in (int, float) or not math.isfinite(at) or not run['started'] <= at <= now:
            invalid_time += 1
            continue
        try:
            stamp = datetime.fromtimestamp(at, timezone.utc).isoformat(timespec='seconds')
        except (ValueError, OSError, OverflowError):
            invalid_time += 1
            continue
        age = 86400 if row['source'] == 'manual' else run['freshness']
        stale = now - at > age
        if for_chat and stale:
            expired += 1
            continue
        valid += 1
        if for_chat and len(cited_ids) >= 6:
            continue
        cited_ids.append(row['id'])
        collector, outcome = row['collector'], row['outcome']
        status = {'healthy': '正常', 'abnormal': '异常', 'unknown': '未知'}.get(outcome, '未知')
        if collector == 'dut_presence' and row['kind'] == 'sample' and row['source'] == 'jsonl' and row['has_event']:
            status = {'healthy': '在线心跳', 'abnormal': '离线', 'unknown': '未知'}.get(outcome, '未知')
            presence.append((status, row['id'], at))
        validity = ' · 已过有效期' if stale else ''
        excerpt = '\n'.join('  │ ' + line for line in (row['evidence'] or '').splitlines())
        lines.append(f"{stamp} · {sources.get(row['source'], '来源未知')} · 观测 #{row['id']} · "
                     f"{COLLECTOR_LABELS.get(collector, '未知采集项')} · {status}{validity}\n{excerpt}")
    offline = [identifier for status, identifier, _ in presence if status == '离线']
    summary = ('本页缺少设备离线观测，无法确认掉线或其原因。' if not offline else
               f'本页记录了 {len(offline)} 条设备离线观测（记录 #{", #".join(map(str, offline))}），掉线原因未确定。')
    recurrent = bool(offline and any(status == '在线心跳' and offline[-1] < key < offline[0]
                                    for status, key, _ in presence))
    if for_chat and recurrent:
        times = [at for status, _, at in presence if status == '离线']
        recurrent = any(status == '在线心跳' and min(times) < at < max(times) for status, _, at in presence)
    if recurrent:
        summary += '两次离线观测之间有在线心跳。'
    if not lines:
        summary = '指定范围内没有可引用的有效观测，无法判断掉线原因。'
    description = '以下为历史观测，最多显示最近 48 条。'
    if for_chat:
        if not lines and expired:
            summary = '近期可读取的观测已过有效期，无法判断掉线或其原因。'
        description = '最多显示 6 条有效观测，时间为 UTC。'
        if offline:
            next_check = '可按上列离线记录的时间核对该通道的现场记录。'
        elif lines:
            next_check = '可核对同一通道、同一时段是否有明确的设备离线记录。'
        else:
            next_check = '本批次有新的有效观测后，可再次查询。'
        lines.append(next_check)
        outcome = '证据不足，掉线及原因未知'
        if offline:
            outcome = '发现明确离线观测，掉线原因未知'
        if recurrent:
            outcome = '发现离线、在线后再次离线的观测，掉线原因未知'
        text = '\n\n'.join([f'CH{target.channel:02d} · {summary}', description, *lines])
        return ChatEvidenceResult(target, datetime.fromtimestamp(now, timezone.utc).isoformat(timespec='seconds'),
                                  len(rows), expired, invalid_time, valid, tuple(cited_ids), outcome, text)
    return '\n\n'.join([f'CH{target.channel:02d} · {summary}', description, *lines])


def _read(args, request):
    context, record, stop, clock, for_chat = request
    target = EvidenceTarget(**args)
    if stop.is_set():
        raise InterruptedError()
    _verify_binding(target, context, record)
    history = ServiceAgingHistory(context, clock)
    rows, run = history.channel_observations(target.job_id, target.revision, target.dut_id, stop,
                                            current_only=for_chat)
    if stop.is_set():
        raise InterruptedError()
    return _report(target, rows, run, clock(), for_chat=for_chat)


# Only this in-process reader is reachable from the offline entry. Initializing
# the live project registry would also initialize its persistent job store.
_REGISTRY = CapabilityRegistry()
_ID = 'service_aging.channel_evidence'
_FIELDS = {k: dict(type='string', minLength=1, maxLength=128)
           for k in ('project_id', 'job_id', 'run_id', 'revision', 'dut_id')}
_FIELDS['channel'] = dict(type='integer', minimum=1, maximum=16)
_REGISTRY.register(CapabilitySpec(_ID, '查看通道掉线证据', '查询指定持续老化批次已经记录的观测',
    object_schema(_FIELDS, tuple(_FIELDS)), _read, sources=('gui',)))


def _query(context, record, target, stop, clock, for_chat):
    args = asdict(target)
    spec = _REGISTRY.validate(_ID, args)
    return spec.handler(args, (context, record, stop, clock, for_chat))


def read_channel_evidence(context, record, target, stop, clock=time.time, *, for_chat=False):
    result = _query(context, record, target, stop, clock, for_chat)
    return result.render() if for_chat else result


def read_chat_channel_evidence(context, record, target, stop, clock=time.time):
    return _query(context, record, target, stop, clock, True)
