"""Immutable display snapshots; no widgets, transport or verdict computation."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from src.models.qt_configuration import PushTrialView, VersionQueryView


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
