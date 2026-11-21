"""Private local-editor payload. Never include this in a model transcript/log."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ConfigurationDraft:
    project_id: str
    project_name: str
    token: str
    revision: str
    values: dict = field(repr=False)
    missing_files: tuple = ()
    recovered_values: Optional[dict] = field(default=None, repr=False)
    recovery_warning: str = ''
    legacy_recovery: bool = False


@dataclass(frozen=True)
class VersionQueryView:
    job_id: str
    state: str
    active: bool
    channel: int
    values: tuple[str, ...] = ()
    error: str = ''


@dataclass(frozen=True)
class PushTrialView:
    trial_id: str
    state: str
    message: str
