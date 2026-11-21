"""Report projections for the project-bound Qt viewer."""
from dataclasses import dataclass
from typing import Optional, Tuple


REPORT_OPERATIONS = frozenset(('ai_report_open', 'ai_report_select', 'ai_report_rename', 'ai_report_delete'))
REPORT_HANDOFF_OPERATIONS = frozenset(('ai_report_handoff', 'ai_report_handoff_finish'))


@dataclass(frozen=True)
class ReportRow:
    identifier: str
    title: str
    created: str
    channel: str
    provider: str
    model: str
    status: str
    busy: bool


@dataclass(frozen=True)
class ReportDetail:
    identifier: str
    analysis: str
    evidence: str
    revision: str


@dataclass(frozen=True)
class ReportView:
    rows: Tuple[ReportRow, ...]
    detail: Optional[ReportDetail]
    deleted: Optional[int] = None


@dataclass(frozen=True)
class ReportHandoffPreview:
    token: str
    report_id: str
    channel: int
    target: str
