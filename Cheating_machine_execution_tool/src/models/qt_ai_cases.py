"""Shared case library data for the local operator."""
from dataclasses import dataclass
from typing import Optional, Tuple


CASE_OPERATIONS = frozenset(('ai_case_open', 'ai_case_from_report', 'ai_case_save', 'ai_case_toggle', 'ai_case_delete'))


@dataclass(frozen=True)
class CaseRow:
    identifier: int
    version: int
    report_id: str
    active: bool
    fields: Tuple[str, str, str, str, str]


@dataclass(frozen=True)
class CaseView:
    rows: Tuple[CaseRow, ...]
    selected: Optional[int] = None
    report_id: str = ''
    notice: str = ''
