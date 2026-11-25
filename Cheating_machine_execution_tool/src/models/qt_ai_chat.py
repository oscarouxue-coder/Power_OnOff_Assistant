"""Read models for local Qt conversation windows."""
from dataclasses import dataclass
from typing import Optional, Tuple

from src.models.ai_diagnostics import MonitorStatus

CHAT_MANAGEMENT = frozenset(('ai_chat_manage', 'ai_chat_manage_rename', 'ai_chat_delete_many'))
CHAT_OPERATIONS = frozenset(('ai_chat_open', 'ai_chat_poll', 'ai_chat_select', 'ai_chat_new', 'ai_chat_send',
    'ai_chat_stop', 'ai_chat_rename', 'ai_chat_delete', 'ai_chat_import', 'ai_chat_evidence', 'ai_chat_page', 'ai_chat_progress',
    'ai_chat_permissions', 'ai_chat_review', 'ai_chat_decide', 'ai_chat_new_pc', 'ai_chat_monitor_settings', 'ai_chat_monitor_apply', 'ai_chat_monitor_off',
    'ai_chat_monitor_review', 'ai_chat_monitor_decide', *CHAT_MANAGEMENT))


def is_model_identity_question(text):
    question = text.strip().casefold()
    if question.endswith(('?', '？')):
        question = question[:-1].rstrip()
    return question in ('你现在是什么模型', '你是什么模型', '当前用的是什么模型',
                        'what model are you', 'which model are you')


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
    reply_id: str = ''
    stream_state: str = ''


@dataclass(frozen=True)
class ChatActivityView:
    session_id: str
    source: str
    request_id: str
    state: str
    detail: str = ''

    def status_message(self):
        source = {'local_evidence': '本地证据查询', 'model_reply': '模型回复', 'conversation': '会话请求'}[self.source]
        state = {'accepted': '已受理', 'running': '运行中', 'completed': '已完成',
                 'cancelling': '正在取消', 'cancelled': '已取消', 'failed': '未完成',
                 'rejected': '未受理', 'not_started': '未开始'}[self.state]
        request = ('查询编号 #' if self.source == 'local_evidence' else '请求编号 ') + self.request_id if self.request_id else ''
        detail = ' · '.join(part for part in (source, state, request, self.detail) if part)
        if self.session_id:
            detail += '\n会话 ' + self.session_id
        return ChatMessageView('system', detail, '', 'error' if self.state in ('failed', 'rejected', 'not_started') else 'progress')


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
    ordinary_chat: bool = False
    snapshot_generation: int = 0
    activity: Optional[ChatActivityView] = None
