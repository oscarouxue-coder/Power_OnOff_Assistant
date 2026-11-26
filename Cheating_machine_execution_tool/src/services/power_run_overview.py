"""Incremental read-only projection of original per-channel power run events."""
from contextlib import closing
from datetime import datetime
import json
import re
import sqlite3

from src.services.project_profile_store import active_project_duts, configured_power_cycles, read_project_profile
from src.services.qt_log_history import job_database_path
from src.models.workbench_presentation import AttentionView


def _event_time(value):
    try:
        return datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError, OverflowError, OSError):
        return ''


def _specific_reason(value):
    return (value if isinstance(value, str) and value.strip() and value.strip() not in
            ('失败', '执行失败', '结果未知', '测试失败，详细信息请查看执行日志') else '')


def _track_channel_event(row, at, data, stage):
    status = data.get('status')
    if status not in ('failed', 'running', 'retry', 'resume', 'success', 'stopped', 'unknown'):
        return
    detail = data.get('detail')
    detail = detail if isinstance(detail, str) else ''
    cycle = data.get('cycle')
    event_time = _event_time(at)
    if status == 'failed':
        if stage != 'history':
            row['had_failure'] = True
        row['current_failure_stage'] = row.get('reported_stage', '')
        if _specific_reason(detail) or not row.get('current_reason'):
            row['current_reason'] = detail
            row['current_failure_time'] = event_time
        if type(cycle) is int and cycle > 0:
            row['current_failure_cycle'] = cycle
    elif stage != 'history' or row.get('current_status') != 'failed':
        row.update(current_reason='', current_failure_cycle=None, current_failure_time='', current_failure_stage='')
    if status == 'resume' and row.get('had_failure'):
        row['resumed_after_failure'] = True
    # History also records process errors that may still be retried. Only the
    # original channel-state receipt establishes the current failed state.
    if stage != 'history':
        row['current_status'] = status
    if stage == 'history' or status in ('failed', 'resume'):
        prefix = f'第{cycle}轮 · ' if type(cycle) is int and cycle > 0 else ''
        line = ' · '.join(filter(None, (event_time, prefix + detail)))
        recent = row.get('recent_events', ())
        if line and (not recent or recent[-1] != line):
            row['recent_events'] = (*recent[-5:], line)


def matching_power_overview(project):
    """Return receipts only for the task shown in the current project view."""
    overview = project.test_overview or {}
    job = overview.get('job_id')
    if project.project_type != 'power_cycle' or not job or not project.run_id:
        return {}
    if project.run_id in (job, overview.get('run_id')):
        return overview
    if job == project.power_history_job and project.resume_detail:
        return overview
    return {}


def _task_attention(context, record, project):
    """Read only this project's displayed task, never the latest unrelated power run."""
    owner = record.get('owner')
    if (not owner or record.get('project_id') != context.identity.project_id or
            project.run_id not in (owner, record.get('run_id'))):
        return None
    from src.services.pipeline_orchestrator import SUBTASK_LABELS
    from src.services.workbench_status_service import TASK_NAMES

    operation = record.get('operation', '')
    title = TASK_NAMES.get(operation, {'network.line_check': '环境线路检查',
        'pretest.start': '预测试', 'aging.resume': '通道续跑', 'power.on': '上电',
        'power.off': '下电', 'power.qt_single': '单次电源控制'}.get(operation, operation or '任务'))
    state = '结果未知' if project.state == 'unknown' else '失败'
    timestamp = _event_time(record.get('finished_at') or record.get('updated_at'))
    reason = ''
    stage = project.task_stage if project.task_stage not in ('执行失败', '结果未知') else ''
    related = ()
    unavailable = '原任务未保存具体失败原因，请核对执行事件'
    try:
        database = job_database_path(context)
        if database.is_file():
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=.05)) as db:
                job = db.execute('SELECT state,stage,updated,result FROM jobs WHERE id=? AND capability=?',
                                 (owner, operation)).fetchone()
                if job:
                    try:
                        events = db.execute('''SELECT created,stage,substr(message,1,8192),length(message)
                            FROM job_events WHERE job_id=? AND message != '' ORDER BY id DESC LIMIT 12''',
                            (owner,)).fetchall()
                        related = tuple(f'{_event_time(at)} · [{event_stage}] {message}' +
                                        (' …（事件过长，请在任务历史查看原文）' if length > 8192 else '')
                                        for at, event_stage, message, length in reversed(events))
                    except sqlite3.Error:
                        events = ()
                        related = ('原任务执行事件列表暂无法读取',)
                    if job[0] in ('failed', 'unknown'):
                        timestamp = _event_time(job[2]) or timestamp
                        try:
                            result = json.loads(job[3]) if job[3] else None
                        except (ValueError, TypeError, RecursionError):
                            result = None
                            unavailable = '原任务执行回执暂无法读取，请在任务历史核对'
                        if isinstance(result, dict):
                            reason = (_specific_reason(result.get('error')) or _specific_reason(result.get('message')) or
                                      _specific_reason(result.get('detail')))
                            items = result.get('items')
                            failed_items = ([item for item in items if isinstance(item, dict) and item.get('ok') is False]
                                            if isinstance(items, list) else [])
                            errors = []
                            for item in failed_items:
                                code = item.get('code')
                                code = code if isinstance(code, str) else ''
                                subtask = SUBTASK_LABELS.get(code, str(code or '子任务'))
                                error = (_specific_reason(item.get('error')) or _specific_reason(item.get('message')) or
                                         _specific_reason(item.get('detail')))
                                errors.append(f'{subtask}：{error or "未保存具体失败原因"}')
                            if errors:
                                reason = '\n'.join(filter(None, (reason, *errors)))
                                stage = '、'.join(error.split('：', 1)[0] for error in errors)
                            elif reason:
                                for code, subtask in SUBTASK_LABELS.items():
                                    if reason.startswith(f'子任务 {code} 失败'):
                                        stage = subtask
                                        break
                        if job[1] == 'process_interrupted':
                            reason = reason or '原任务执行进程中断，未取得最终执行回执'
                        if not reason:
                            reason = next((message for _, event_stage, message, _ in events
                                           if event_stage == 'pretest.error' or
                                           (event_stage == 'pipeline' and message.startswith('[全流程] 子任务 ')
                                            and ' 失败:' in message)), '')
                        if not stage:
                            for _, event_stage, message, _ in events:
                                if event_stage == 'pipeline' and message.startswith('=== 开始子任务 ') and message.endswith(' ==='):
                                    stage = message[len('=== 开始子任务 '):-len(' ===')]
                                    break
                        stage = stage or next((event_stage for _, event_stage, _, _ in events
                                               if event_stage not in ('failed', 'unknown', 'succeeded')), '')
                else:
                    unavailable = '未找到匹配的任务执行回执'
        else:
            unavailable = '原任务事件数据库缺失'
    except (OSError, ValueError, sqlite3.Error):
        unavailable = '原任务执行回执暂无法读取，请在任务历史核对'
    pretest = project.pretest_run
    if operation != 'aging.resume':
        reason = reason or _specific_reason(project.pipeline_detail)
    if not reason and pretest[0] == project.run_id:
        reason = _specific_reason(pretest[3])
    if reason == project.state_text:
        reason = ''
    event = f'{stage}{state}' if stage in SUBTASK_LABELS.values() else f'{title}{state}'
    return AttentionView('任务', None, timestamp, event, reason or unavailable,
                         stage, related_events=related, reason_recorded=bool(reason))


def power_attention_records(project, context=None, record=None, fallback_overview=None):
    """Report current channel anomalies and exact-task failure evidence."""
    overview = matching_power_overview(project)
    if not overview and fallback_overview and (project.run_id in (
            fallback_overview.get('job_id'), fallback_overview.get('run_id')) or
            project.resume_detail and fallback_overview.get('job_id') == project.power_history_job):
        overview = fallback_overview
    by_number = {row['channel']: row for row in overview.get('rows', ())}
    live = {channel.number: channel for channel in project.channels}
    entries = []
    for number in sorted(set(live) | set(by_number)):
        channel = live.get(number)
        row = by_number.get(number, {})
        observed = row.get('current_status') if overview.get('caught_up') else None
        # The replay follows the live poll and may have received later events.
        failed = observed == 'failed' if observed else channel is not None and channel.state == 'failed'
        if not failed:
            continue
        reason = (_specific_reason(row.get('current_reason')) if observed == 'failed' else '') or (
            _specific_reason(channel.detail) if channel else '')
        cycle = row.get('current_failure_cycle') if observed == 'failed' else None
        if context is None:  # Preview snapshots may contain the original summary fields only.
            reason = reason or _specific_reason(row.get('failure_reason'))
            cycle = cycle or row.get('last_failure')
        entries.append(AttentionView(row.get('label') or f'CH{number:02d}', number,
            (row.get('current_failure_time') or '') if observed == 'failed' else '',
            f'第{cycle}轮验证失败' if cycle else '通道测试失败',
            reason or '当前通道未保存具体失败原因，请核对执行日志',
            row.get('current_failure_stage') or (channel.stage if channel else '') or row.get('stage') or '', cycle,
            tuple(row.get('recent_events') or ()) if observed == 'failed' else ()))
    active_resume = bool(record and record.get('operation') == 'aging.resume' and
                         record.get('state') in ('prepared', 'queued', 'running', 'stopping'))
    task = (_task_attention(context, record or {}, project) if context is not None and not active_resume and
            project.state in ('failed', 'unknown') else None)
    # The legacy power engine's final failure receipt may simply aggregate its
    # failed channel numbers. The individual channel events are more specific.
    aggregate_failure = bool(task and re.match(r'(?:子任务 legacy_power_test 失败[:：]\s*)?失败通道[:：]', task.reason))
    if entries:
        if task and not aggregate_failure and task.reason_recorded:
            entries.append(task)
        return tuple(entries)
    if active_resume:
        return ()
    if project.state not in ('failed', 'unknown'):
        return ()
    # Once every previously failed channel has explicitly recovered, the old
    # batch verdict still belongs to history, but no current channel is failed.
    previously_failed = [row for row in by_number.values() if row.get('had_failure')]
    if (overview.get('caught_up') and previously_failed and project.state == 'failed' and
            (aggregate_failure or task is None) and
            all(row.get('resumed_after_failure') and row.get('current_status') == 'success'
                for row in previously_failed)):
        return ()
    if task:
        return (task,)
    pretest = project.pretest_run
    reason = project.pipeline_detail or (pretest[3] if pretest[0] == project.run_id else '')
    if not _specific_reason(reason) or reason == project.state_text:
        reason = '当前任务未保存具体失败原因，请核对执行日志'
    state = '结果未知' if project.state == 'unknown' else project.state_text
    return (AttentionView('任务', None, '', state, reason, project.task_stage),)


class PowerRunOverview:
    def __init__(self):
        self._definitions = {}
        self.project_id = None
        self.job = ''
        self.after = 0
        self.channels = {}
        self.finished = False
        self.profile = None
        self.directory = None
        self.selected = ()
        self.caught_up = False

    def _definition(self, context, record):
        """Only the original request identifies the tasks and channels of a pipeline."""
        key = (context.identity.project_id, record.get('owner'))
        if key in self._definitions:
            return self._definitions[key]
        database = job_database_path(context)
        if not database.is_file():
            return None
        try:
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=.05)) as db:
                row = db.execute('SELECT capability,payload FROM jobs WHERE id=?', (key[1],)).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        try:
            arguments = json.loads(row[1])['arguments']
            numbers = arguments['channel_ids']
            if (not isinstance(numbers, list) or not numbers or
                    any(type(n) is not int or not 1 <= n <= 16 for n in numbers) or
                    len(set(numbers)) != len(numbers)):
                raise ValueError('invalid channels')
            tasks = arguments.get('tasks', [])
            power = row[0] == record.get('operation') and (row[0] == 'aging.start' or (
                row[0] == 'pipeline.start' and isinstance(tasks, list) and 'legacy_power_test' in tasks))
            result = (power, tuple(numbers))
        except (TypeError, ValueError, KeyError):
            result = (False, ())
        self._definitions[key] = result
        return result

    def latest_record(self, context, ordered_records):
        for record in ordered_records:
            if record.get('project_id') != context.identity.project_id or not record.get('owner'):
                continue
            if record.get('operation') in ('aging.start', 'pipeline.start'):
                definition = self._definition(context, record)
                if definition and definition[0]:
                    return record
        return {}

    def _accept(self, event):
        event_id, at, stage, raw = event
        self.after = event_id
        try:
            data = json.loads(raw)
        except (ValueError, TypeError, RecursionError):
            return
        if not isinstance(data, dict) or type(data.get('channel')) is not int:
            return
        number = data['channel']
        if number not in self.selected:
            return
        row = self.channels.setdefault(number, dict(completed=None, stage='', success=0, failure=0, retries=0,
            last_success=0, last_failure=0, failure_reason='', cycle=None, began=None, duration=None))
        _track_channel_event(row, at, data, stage)
        cycle = data.get('cycle')
        if stage == 'history':
            if type(cycle) is int and cycle > 0:
                if row['cycle'] is None or cycle > row['cycle']:
                    row.update(cycle=cycle, began=None, duration=None)
                if data.get('status') == 'retry':
                    row['retries'] += 1
                if data.get('status') == 'resume':
                    row.update(cycle=cycle, began=None, duration=None)
                if data.get('status') == 'failed' and cycle > row['last_failure']:
                    row['last_failure'] = cycle
                    row['failure'] += 1
                    reason = data.get('detail')
                    row['failure_reason'] = reason if isinstance(reason, str) else ''
                    if row['cycle'] == cycle and row['began'] is not None:
                        row['duration'] = at - row['began'] if at >= row['began'] else None
            return
        completed = data.get('completed')
        if type(completed) is int and completed >= 0:
            row['completed'] = max(row['completed'] or 0, completed)
        caption = data.get('stage') or data.get('detail')
        if isinstance(data.get('stage'), str):
            row['reported_stage'] = data['stage']
        if not isinstance(caption, str):
            return
        row['stage'] = caption
        match = re.fullmatch(r'第(\d+)轮(执行中|完成|测试正常)', caption)
        if match:
            cycle = int(match[1])
            if match[2] == '执行中':
                if row['cycle'] != cycle or row['began'] is None:
                    row.update(cycle=cycle, began=at, duration=None)
            elif cycle > row['last_success']:
                row['last_success'] = cycle
                row['success'] += 1
                duration = at - row['began'] if row['cycle'] == cycle and row['began'] is not None else None
                row.update(cycle=cycle, duration=duration if duration is not None and duration >= 0 else None)

    def snapshot(self, context, record, profile, *, attention_only=False):
        job = record.get('owner', '')
        if job and (record.get('project_id') != context.identity.project_id or
                    record.get('operation') not in ('aging.start', 'pipeline.start')):
            return {}
        if job != self.job or self.project_id != context.identity.project_id:
            self.project_id = context.identity.project_id
            self.job, self.after, self.finished = job, 0, False
            self.caught_up = False
            self.channels.clear()
            self.profile, self.selected = None, ()
            self.directory = None
            if job:
                run_id = record.get('run_id', '')
                if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{32}', run_id):
                    return {}
                root = context.root / 'runs' / run_id
                archive = root / 'Auto_power_on_off_tool/config'
                if archive.resolve() != archive or record.get('_path') != root / 'run.json':
                    return {}
                self.profile = read_project_profile(archive)
                self.directory = archive
        plan = self.profile if job else profile
        has_plan = bool(plan and plan['test_type'] == 'power_cycle')
        if not has_plan and not (attention_only and job):
            return {}
        if job and not self.finished:
            definition = self._definition(context, record)
            if not definition or not definition[0]:
                return {}
            self.selected = definition[1]
            database = job_database_path(context)
            if database.is_file():
                try:
                    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=.05)) as db:
                        events = db.execute("""SELECT id,created,stage,
                            CASE WHEN stage IN ('aging', 'history') THEN message ELSE '' END
                            FROM job_events WHERE job_id=? AND id>? ORDER BY id LIMIT 512""", (job, self.after)).fetchall()
                        for event in events:
                            if event[2] in ('aging', 'history'):
                                self._accept(event)
                            self.after = event[0]
                        # A resumed failed channel appends evidence to the original job.
                        self.finished = len(events) < 512 and record['state'] in ('succeeded', 'skipped', 'stopped')
                        self.caught_up = len(events) < 512
                except sqlite3.Error:
                    self.caught_up = False  # Existing totals remain valid while the store is busy.
            else:
                self.caught_up = False
        rows = []
        directory = self.directory if job else context.saved_root / 'Auto_power_on_off_tool/config'
        duts = (active_project_duts(plan, directory) if has_plan else
                [dict(label=f'CH{number:02d}', dut_id='', channel=number) for number in self.selected])
        for dut in duts:
            if job and dut['channel'] not in self.selected:
                continue
            data = self.channels.get(dut['channel'], {})
            rows.append(dict(label=dut['label'], dut_id=dut['dut_id'], channel=dut['channel'],
                             **{key: data.get(key) for key in ('completed', 'cycle', 'stage', 'success', 'failure',
                                                             'retries', 'duration', 'last_failure', 'failure_reason',
                                                             'current_status', 'current_reason', 'current_failure_cycle',
                                                             'current_failure_time', 'current_failure_stage', 'recent_events',
                                                             'had_failure', 'resumed_after_failure')}))
        target = None
        if has_plan:
            try:
                target = configured_power_cycles(directory) if plan.get('environment_channels') else plan['type_config']['target_cycles']
            except (KeyError, ValueError):
                pass
        return dict(job_id=job, run_id=record.get('run_id', ''), target=target, rows=rows, caught_up=self.caught_up)
