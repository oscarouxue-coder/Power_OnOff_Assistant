"""Immutable display snapshots; no widgets, transport or verdict computation."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from src.models.qt_configuration import PushTrialView, VersionQueryView


def power_cycle_percentage(rows, target):
    """Show a batch percentage only when every DUT has a completed-round receipt."""
    if not target or not rows or any(row['completed'] is None for row in rows):
        return None
    return min(100, min(row['completed'] for row in rows) * 100 // target)


@dataclass(frozen=True)
class ChannelView:
    number: int
    state: str = 'disabled'
    cycle: Optional[int] = None
    total: Optional[int] = None
    vlan: str = ''
    port: str = ''
    can_resume: bool = False
    detail: str = ''
    stage: str = ''
    selected: bool = False


@dataclass(frozen=True)
class ProjectView:
    project_id: str
    name: str
    test_type: str
    dut: str
    state: str
    state_text: str
    elapsed: str
    progress_text: str
    progress: Optional[int]
    channel_text: str
    attention_count: int = 0
    success_count: Optional[int] = None
    failure_count: Optional[int] = None
    run_id: str = ''
    channels: Tuple[ChannelView, ...] = ()
    configuration: Tuple[Tuple[str, Tuple[Tuple[str, str], ...]], ...] = ()
    active_task_count: int = 0
    dirty: bool = False
    can_start: bool = False
    can_stop: bool = False
    task_stage: str = ''
    can_configure: bool = False
    editor_open: bool = False
    editor_kind: str = ''
    channel_snapshot_label: str = ''
    serial_observation: tuple[str, str] = ('', '')
    pipeline_serial_run: str = ''
    pipeline_detail: str = ''
    pretest_run: tuple[str, str, bool, str] = ('', '', False, '')
    version_query: Optional[VersionQueryView] = None
    push_trial: Optional[PushTrialView] = None
    resume_detail: str = ''
    resume_waiting: tuple[int, ...] = ()
    power_history_job: str = ''
    power_history_events: tuple[tuple[int, int], ...] = ()
    started_text: str = ''
    parallel_power_available: bool = False
    overview_state: str = ''
    unresolved_tasks: bool = False
    saved_revision: str = ''
    count_unit: str = ''
    observed_active_task_count: int = 0
    project_type: str = ''
    test_overview: Optional[dict] = None

    @property
    def overview_task_count(self):
        # Managed tasks and the runtime job registry can describe the same job.
        return max(self.active_task_count, self.observed_active_task_count)

    @property
    def success_text(self):
        return '—' if self.success_count is None else f'{self.success_count} {self.count_unit}'.rstrip()

    @property
    def failure_text(self):
        return '—' if self.failure_count is None else f'{self.failure_count} {self.count_unit}'.rstrip()

    @property
    def attention_text(self):
        if self.attention_count or self.failure_count == 0:
            return str(self.attention_count)
        return '—'


_OVERVIEW_STATES = frozenset(('idle', 'running', 'queued', 'stopping', 'finishing', 'completed', 'unchecked',
                              'failed', 'unknown', 'reviewed_unknown', 'recovery_required', 'stopped', 'skipped', 'pending'))


def matches_project_filter(project, key):
    """Count or filter an opened project without reinterpreting its display text."""
    state = project.overview_state or project.state
    if state not in _OVERVIEW_STATES:
        state = 'unknown'
    if not key:
        return True
    if key == 'active':
        return (project.overview_task_count > 0
                or project.overview_state in ('running', 'queued', 'stopping', 'finishing'))
    if key == 'unknown':
        return project.unresolved_tasks or state in ('unknown', 'recovery_required')
    if key == 'attention':
        return (project.attention_count > 0 or project.unresolved_tasks
                or state in ('failed', 'unchecked', 'unknown', 'recovery_required'))
    return state == key


@dataclass(frozen=True)
class LogView:
    time: str
    level: str
    project_id: str
    project_name: str
    message: str
    run_id: str = ''
    channel: Optional[int] = None
    raw: bool = False
    dut_id: str = ''
    step: str = ''
    job_id: str = ''
    batch_id: str = ''


@dataclass(frozen=True)
class WorkspaceResourceView:
    sampled_at: float
    serial: int
    adapters: int
    other: int
    protection_unavailable: bool


@dataclass(frozen=True)
class WorkspaceHealthView:
    worker_tick: Optional[float]
    commands_pending: int
    command_limit: int
    logs_omitted: int
    log_write_failures: int
    log_write: Optional[Tuple[datetime, bool]]
    task_log_at: Optional[datetime]
    inventory_check: Optional[Tuple[datetime, bool]]
    resources: Optional[WorkspaceResourceView]
    pending_log_writes: int = 0
    log_write_age: float = 0.
