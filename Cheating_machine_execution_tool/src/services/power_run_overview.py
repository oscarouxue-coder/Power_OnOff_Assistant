"""Incremental read-only projection of original per-channel power run events."""
from contextlib import closing
import json
import re
import sqlite3

from src.services.project_profile_store import active_project_duts, configured_power_cycles, read_project_profile
from src.services.qt_log_history import job_database_path


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
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict) or type(data.get('channel')) is not int:
            return
        number = data['channel']
        if number not in self.selected:
            return
        row = self.channels.setdefault(number, dict(completed=None, stage='', success=0, failure=0, retries=0,
            last_success=0, last_failure=0, failure_reason='', cycle=None, began=None, duration=None))
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

    def snapshot(self, context, record, profile):
        job = record.get('owner', '')
        if job and (record.get('project_id') != context.identity.project_id or
                    record.get('operation') not in ('aging.start', 'pipeline.start')):
            return {}
        if job != self.job or self.project_id != context.identity.project_id:
            self.project_id = context.identity.project_id
            self.job, self.after, self.finished = job, 0, False
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
        if not plan or plan['test_type'] != 'power_cycle':
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
                        events = db.execute("""SELECT id,created,stage,substr(message,1,8192)
                            FROM job_events WHERE job_id=? AND id>? ORDER BY id LIMIT 512""", (job, self.after)).fetchall()
                        for event in events:
                            if event[2] in ('aging', 'history'):
                                self._accept(event)
                            self.after = event[0]
                        # A resumed failed channel appends evidence to the original job.
                        self.finished = len(events) < 512 and record['state'] in ('succeeded', 'skipped', 'stopped')
                except sqlite3.Error:
                    pass  # Existing observations remain valid while the event store is busy.
        rows = []
        directory = self.directory if job else context.saved_root / 'Auto_power_on_off_tool/config'
        for dut in active_project_duts(plan, directory):
            if job and dut['channel'] not in self.selected:
                continue
            data = self.channels.get(dut['channel'], {})
            rows.append(dict(label=dut['label'], dut_id=dut['dut_id'], channel=dut['channel'],
                             **{key: data.get(key) for key in ('completed', 'cycle', 'stage', 'success', 'failure',
                                                             'retries', 'duration', 'last_failure', 'failure_reason')}))
        try:
            target = configured_power_cycles(directory) if plan.get('environment_channels') else plan['type_config']['target_cycles']
        except (KeyError, ValueError):
            target = None
        return dict(job_id=job, run_id=record.get('run_id', ''), target=target, rows=rows)
