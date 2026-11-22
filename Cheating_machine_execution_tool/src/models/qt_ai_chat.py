"""Read models for local Qt conversation windows."""
from dataclasses import dataclass
from typing import Optional, Tuple

from src.models.ai_diagnostics import MonitorStatus

CHAT_MANAGEMENT = frozenset(('ai_chat_manage', 'ai_chat_manage_rename', 'ai_chat_delete_many'))
CHAT_OPERATIONS = frozenset(('ai_chat_open', 'ai_chat_poll', 'ai_chat_select', 'ai_chat_new', 'ai_chat_send',
    'ai_chat_stop', 'ai_chat_rename', 'ai_chat_delete', 'ai_chat_import', 'ai_chat_evidence', 'ai_chat_page', 'ai_chat_progress',
    'ai_chat_permissions', 'ai_chat_review', 'ai_chat_decide', 'ai_chat_new_pc', 'ai_chat_monitor_settings', 'ai_chat_monitor_apply', 'ai_chat_monitor_off',
    'ai_chat_monitor_review', 'ai_chat_monitor_decide', *CHAT_MANAGEMENT))


@dataclass(frozen=True)
class ChatSessionView:
    identifier: str
    title: str
    target: str
    model: str
    status: str
    origin: str = ''
    created: str = ''
    busy: bool = False


@dataclass(frozen=True)
class ChatMessageView:
    role: str
    text: str
    created: str
    kind: str


@dataclass(frozen=True)
class ChatWorkspaceView:
    sessions: Tuple[ChatSessionView, ...]
    selected: str
    messages: Tuple[ChatMessageView, ...]
    draft: str = ''
    context: str = ''
    running: bool = False
    writable: bool = False
    next_cursor: Optional[int] = None
    history_analysis: bool = False
    deleted: Optional[int] = None
    latest_status: Optional[ChatMessageView] = None
    pc_diagnosis: bool = False
    passive_serial: bool = False
    routing: bool = False
    retry_input: str = ''
    monitor_status: Optional[MonitorStatus] = None
