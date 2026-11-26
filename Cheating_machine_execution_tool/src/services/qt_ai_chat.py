"""Reuse original project conversations for local questions and retained reports."""
from concurrent.futures import Future, ThreadPoolExecutor
import threading
from dataclasses import dataclass
from datetime import datetime
import json
import queue
import re
from collections import deque
from weakref import WeakKeyDictionary

from src.models.ai_conversation import timestamp
from src.models.ai_diagnostics import DiagnosticTarget, ProviderProfile, diagnostic_progress_text
from src.models.ai_permissions import PERMISSION_LABELS
from src.models.dependency_repair import maintenance_operation
from src.models.project_review import ReviewRequired
from src.models.ai_session_scope import session_scope, source_identity
from src.models.qt_ai_chat import ChatActivityView, ChatMessageView, ChatSessionView, ChatWorkspaceView, is_model_identity_question
from src.models.qt_ai_cases import CASE_OPERATIONS
from src.models.qt_ai_reports import REPORT_HANDOFF_OPERATIONS, REPORT_OPERATIONS
from src.services.ai_conversation_service import AiConversationService
from src.services.ai_debug_service import tool_schemas
from src.services.qt_device_diagnostics import DIAGNOSTIC_TOOLS, QtDeviceDiagnostics, QtDiagnosticMonitor
from src.services.ai_diagnostic_service import AiDiagnosticService
from src.services.ai_record_titles import AiRecordTitles
from src.services.ai_session_router import explicit_channel_route
from src.services.qt_ai_cases import QtAiCases
from src.services.qt_ai_report_handoff import QtAiReportHandoff
from src.services.qt_ai_reports import QtAiReports


CHAT_PAGE = 120


@dataclass(frozen=True)
class _PendingIntent:
    origin: str
    text: str
    profile: ProviderProfile
    targets: tuple
    run_id: str
    stop: threading.Event
    future: Future


def _local_chat_mode(session, current_run):
    if (session.get('batch_parent') or session.get('capability_business_batch') or
            source_identity(session.get('source')) != source_identity(None)):
        return ''
    scope = session_scope(session)
    if scope == 'batch' and session.get('qt_batch_diagnostics') and session.get('run_id') == current_run:
        return 'batch'
    if scope == 'general' and not session.get('target'):
        return 'general'
    if scope == 'pc' and not session.get('target'):
        if session.get('diagnosis_only') is True:
            return 'pc'
        if session.get('qt_pc_analysis') is True and session.get('run_id') == current_run:
            return 'pc_regular'
    if scope == 'device' and session.get('target'):
        if session.get('source_report_id'):
            return 'report'
        saved_run = session.get('run_id')
        if saved_run == current_run and session.get('qt_channel_analysis') is True:
            return 'channel'
        if isinstance(saved_run, str) and saved_run.strip() and saved_run != current_run:
            return 'archived'
    return ''


def _display_model(model, redactor):
    if (not isinstance(model, str) or not re.fullmatch(r'[\w-]+(?:[./:-][\w-]+)*', model)
            or len(model) > 200 or redactor.text(model) != model or model.lower().startswith(('sk-', 'bearer-'))
            or re.search(r':\d+(?:/|$)|^[\w.-]+\.[a-zA-Z]{2,}(?:/|$)', model)
            or re.search(r'(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)', model)):
        return '型号不可展示'
    return model


def _saved_context_text(snapshot):
    """Display only the already persisted historical usage, never current configuration."""
    unknown = '当前无可核对的模型请求；已保存历史用量未知'
    if not isinstance(snapshot, dict):
        return unknown
    basis, source, state = (snapshot.get(key) for key in ('basis', 'source', 'state'))
    incoming, outgoing, total = (snapshot.get(key) for key in ('input_tokens', 'output_tokens', 'total_tokens'))
    if not all(type(value) is int and value >= 0 for value in (incoming, total)):
        return unknown
    if basis == 'reply' and state in ('completed', 'failed', 'cancelled') and source in ('api', 'estimate'):
        if type(outgoing) is not int or outgoing < 0 or incoming + outgoing != total:
            return unknown
        approx = '' if source == 'api' else '约 '
        numbers = f'输入 {approx}{incoming:,}，输出 {approx}{outgoing:,}，合计 {approx}{total:,} Token'
        note = ('；保存状态为失败，回复计数与该次状态的对应关系未核实' if state == 'failed' else
                '；保存状态为取消，回复计数与该次状态的对应关系未核实' if state == 'cancelled' else '')
    elif (basis == 'input' and source == 'estimate' and state in ('requesting', 'failed', 'cancelled')
          and outgoing is None and incoming == total):
        numbers = f'输入约 {incoming:,} Token，完整回复用量未知'
        note = {'requesting': '；原记录为请求中，结果未核实', 'failed': '；原请求失败',
                'cancelled': '；原请求取消'}[state]
    else:
        return unknown
    identity = snapshot.get('identity')
    capacity = identity.get('capacity') if isinstance(identity, dict) else None
    limit = (f'记录当时上限 {capacity:,} Token' if type(capacity) is int and capacity > 0
             else '记录当时上限未知')
    try:
        when = datetime.fromisoformat(snapshot.get('updated', ''))
        if when.tzinfo is None:
            raise ValueError()
        stamp = when.isoformat(timespec='seconds')
    except (ValueError, TypeError, OverflowError):
        stamp = '未知'
    origin = '接口返回' if source == 'api' else 'UTF-8 字节估算'
    return (f'已保存历史用量（非当前请求）{note}\n{origin}：{numbers} · {limit}'
            f'\n记录时间 {stamp}；不代表当前配置或当前请求。')


def _saved_empty_cancel_activity(session, latest_message):
    """Only the actual last ordinary question may recover its saved empty cancellation."""
    record = session.get('last_empty_reply_cancel')
    if not isinstance(record, dict) or latest_message is None:
        return None
    message_id, role = latest_message
    reply_id = record.get('reply_id')
    if (role != 'user' or type(message_id) is not int or message_id <= 0 or
            type(record.get('user_message_id')) is not int or record['user_message_id'] != message_id or
            record.get('session_id') != session['id'] or record.get('state') != 'cancelled' or
            record.get('no_body') is not True or not isinstance(reply_id, str) or
            not re.fullmatch(r'[0-9a-f]{32}', reply_id)):
        return None
    return ChatActivityView(session['id'], 'model_reply', reply_id, 'cancelled',
                            '历史记录：没有生成可留存正文')


class QtLocalConversation(AiConversationService):
    def __init__(self, diagnostic, execution):
        self.execution = execution
        self.direct_authority = None
        self.reply_display = {}
        self.aborted_reply_display = {}
        self.route_display = WeakKeyDictionary()
        super().__init__(diagnostic, context=execution.ai_evidence)

    @maintenance_operation
    def resolve_intent(self, text, session, targets, profile, stop):
        def observe(usage):
            keys = ('input_tokens', 'output_tokens') if profile.protocol == 'responses' else ('prompt_tokens', 'completion_tokens')
            counts = tuple(usage.get(key) for key in keys) if isinstance(usage, dict) else ()
            detail = '用量不可用'
            if len(counts) == 2 and all(type(n) is int and n >= 0 for n in counts):
                detail = f'接口返回：输入 {counts[0]:,}，输出 {counts[1]:,}，合计 {sum(counts):,} Token'
            with self.lock:
                self.route_display[stop] = ('目标识别请求模型：' + _display_model(profile.model, self.redactor)
                                            + ' · 服务端实际型号：未确认 · ' + detail)
            self.notify(session['id'])
        return self.router._resolve(text, session, targets, profile, stop, False, observe_request=observe)

    def observe_reply_usage(self, identifier, stop, reply_id, model, snapshot):
        with self.lock:
            draft = self.drafts.get(identifier)
            if self.running.get(identifier) is not stop or stop.is_set() or not draft or draft['reply_id'] != reply_id:
                return
            model = _display_model(model, self.redactor)
            capacity = snapshot['identity']['capacity']
            total = snapshot['total_tokens']
            source = '接口返回' if snapshot['source'] == 'api' else 'UTF-8 字节估算'
            approx = '' if snapshot['source'] == 'api' else '约 '
            output = snapshot['output_tokens']
            if output is None:
                numbers = f'输入约 {total:,} Token，输出用量暂不可用'
            else:
                numbers = f"输入 {snapshot['input_tokens']:,}，输出 {output:,}，合计 {approx}{total:,} Token"
            # Integer tenths avoid overflow for unusual provider counters.
            if capacity:
                tenths = (total * 1000 + capacity // 2) // capacity
                limit = f'上限 {capacity:,} Token，占比 {approx}{tenths // 10}.{tenths % 10}%'
            else:
                limit = '上限未知'
            self.reply_display[identifier] = (stop, f'答复请求模型：{model} · 服务端实际型号：未确认\n{source}：{numbers} · {limit}')

    def local_display(self, identifier, text):
        with self.lock:
            if identifier not in self.running:
                self.reply_display[identifier] = (None, text)

    def message(self, identifier, role, text, kind='text', **metadata):
        if role == 'user' and not metadata.get('supplement'):
            with self.lock:
                self.reply_display.pop(identifier, None)
                self.aborted_reply_display.pop(identifier, None)
        super().message(identifier, role, text, kind, **metadata)

    def _abort_draft(self, identifier, state):
        with self.lock:
            draft = self.drafts.get(identifier)
            super()._abort_draft(identifier, state)
            if draft and draft['reply_id'] and not draft['text']:
                self.aborted_reply_display[identifier] = ChatActivityView(
                    identifier, 'model_reply', draft['reply_id'], state, '没有生成可留存正文')
                if state == 'cancelled':
                    self._save_empty_reply_cancel(identifier, draft['reply_id'])

    def _save_empty_reply_cancel(self, identifier, reply_id):
        # A session-only display receipt, never a chat message or model history.
        try:
            with self.store.lock, self.store.db:
                session = self.store.chat(identifier)
                if self.local_mode(session) != 'general':
                    return
                last = self.store.db.execute(
                    """SELECT id, json_extract(payload,'$.role') FROM chat_messages WHERE session_id=? AND
                       CASE WHEN json_valid(payload) THEN json_extract(payload,'$.role')!='system' ELSE 0 END
                       ORDER BY id DESC LIMIT 1""", (identifier,)).fetchone()
                if last is None or last[1] != 'user' or not re.fullmatch(r'[0-9a-f]{32}', reply_id):
                    return
                self.store.update_chat(identifier, last_empty_reply_cancel=dict(
                    session_id=identifier, user_message_id=last[0], reply_id=reply_id,
                    state='cancelled', no_body=True))
        except Exception:
            # The original cancellation still finishes; do not invent a durable receipt.
            try:
                self.emit('普通问答取消历史保存失败；仅保留当前会话取消状态。')
            except Exception:
                # A secondary presentation/log failure must not interrupt cancellation.
                pass

    def local_mode(self, session):
        return _local_chat_mode(session, self.context.run_id)

    def capabilities_for(self, identifier):
        adapter = getattr(self, 'capabilities', None)
        source = self.store.chat(identifier).get('source') or {}
        if adapter and (source.get('gateway_instance_id') or
                        (self.direct_authority is not None and self.direct_authority(source))):
            return adapter
        return None

    def collection_status(self, identifier):
        session = self.store.chat(identifier)
        if (session.get('source') or {}).get('gateway_instance_id') and getattr(self, 'gateway', None):
            state = super().collection_status(identifier)
            if (self.execution.workspace_close_requested() or self.execution.closing or self.execution.editor_open
                    or self.execution.other_jobs_active()):
                state = dict(state, enabled=False, reason='项目正在收尾、编辑配置或其他项目正在使用设备')
            return dict(state, project_peer=True)
        parent = session.get('batch_parent')
        source = session.get('source') or {}
        if source.get('kind') in ('dingtalk', 'feishu') and self.direct_authority is not None:
            if not self.direct_authority(source):
                return {'enabled': False, 'capable': False, 'reason': '直连平台身份或项目授权已变更'}
            state = super().collection_status(identifier)
            if self.execution.workspace_close_requested() or self.execution.closing or self.execution.editor_open:
                state = dict(state, enabled=False, reason='项目正在收尾或编辑配置')
            return state
        mode = self.local_mode(session)
        if parent and self.local_mode(self.store.chat(parent)) == 'batch':
            mode = 'batch_child'
        if not mode:
            return {'enabled': False, 'capable': False, 'reason': '当前 Qt 会话仅查看历史'}
        state = super().collection_status(identifier)
        if mode in ('batch', 'batch_child'):
            root = self.store.chat(parent) if parent else session
            valid = state['enabled'] and all(self.access.active(DiagnosticTarget(**t)) for t in root['batch_targets'])
            return dict(state, enabled=valid, diagnostic_scope=True,
                        reason='已确认的批量诊断通道' if valid else '本批通道或诊断授权已变化')
        if mode == 'channel' and state['enabled'] and self.access.active(DiagnosticTarget(**session['target'])):
            return dict(state, diagnostic_scope=True)
        if mode == 'channel':
            passive = bool(state['enabled'] and session['target'].get('port')
                           and not self.execution.closing and not self.execution.closed)
            return {'enabled': False, 'capable': state['capable'], 'passive_serial': passive,
                    'reason': '可读取本项目已打开串口的近期输出' if passive else '本机通道会话仅分析留存材料'}
        if mode == 'archived' and state['capable']:
            return {'enabled': False, 'capable': True, 'reason': '历史批次仅分析留存材料'}
        if mode == 'report' and state['capable']:
            return {'enabled': False, 'capable': True, 'reason': '当前报告会话仅分析留存材料'}
        return state

    def tools_for_turn(self, state, scope):
        tools = super().tools_for_turn(state, scope)
        if state.get('diagnostic_scope'):
            return [tool for tool in tools if tool['name'] in DIAGNOSTIC_TOOLS]
        if state.get('project_peer'):
            return [tool for tool in tools if tool['name'] == 'ask_user']
        if state.get('passive_serial'):
            tools.extend(tool for tool in tool_schemas(True) if tool['name'] == 'read_serial_log')
        return tools

    def _collect(self, identifier, name, params, target, settings, stop, executor):
        state = self.collection_status(identifier)
        if state.get('diagnostic_scope') and name not in DIAGNOSTIC_TOOLS:
            raise ValueError('此工具不属于通道诊断范围')
        if state['enabled'] or name != 'read_serial_log' or self.local_mode(self.store.chat(identifier)) != 'channel':
            return super()._collect(identifier, name, params, target, settings, stop, executor)
        if stop.is_set() or not self.collection_status(identifier).get('passive_serial'):
            raise ValueError('已取消或目标串口的读取条件已变化，本次跳过')
        self.message(identifier, 'system', '正在读取已打开的串口：' + target.port, 'progress')
        return executor.execute(name, params, deep=True)

    def refresh_evidence(self, identifier):
        # Device follow-ups in this workspace use only their persisted evidence.
        if session_scope(self.store.chat(identifier)) != 'device':
            super().refresh_evidence(identifier)


class QtAiChat:
    def __init__(self, store, workspace, emit, context, execution):
        self.store = store
        self.access = QtDeviceDiagnostics(execution, store)
        self.diagnostic = AiDiagnosticService(emit, self.access.acquire_serial, execution.read_chat_serial, self.access.busy,
            store=store, manual_path=workspace.source_root / 'line_check_assistant_README.md',
            tool_factory=self.access.tool_factory, monitor_factory=QtDiagnosticMonitor)
        try:
            self.conversation = QtLocalConversation(self.diagnostic, execution)
        except BaseException:
            self.diagnostic.begin_close()
            self.diagnostic.worker_thread.join()
            self.diagnostic.event_thread.join()
            raise
        self.diagnostic.conversation = self.conversation
        self.diagnostic.maintenance = self.conversation.maintenance = workspace.maintenance
        self.conversation.router.maintenance = workspace.maintenance
        self.titles = AiRecordTitles(store, self.diagnostic.emit)
        self.reports = QtAiReports(self.diagnostic, self.titles)
        self.handoff = QtAiReportHandoff(context, self.conversation)
        self.conversation.target_current = lambda target: self.handoff._target(target.channel) == target
        self.conversation.access = self.access
        self.access.bind(self)
        self.diagnostic.shared_busy = self.conversation.shared_busy = self.access.shared_busy
        self.cases = QtAiCases(self.diagnostic)
        self.selected = self.conversation.router.current()
        self.cursor = None
        self.closing = False
        self._last_view = None
        self._snapshot_generation = 0
        self._intent_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='qt-local-intent')
        self._intent = None
        self._route_errors = {}
        self._identity_messages = deque(maxlen=64)

    def _profile(self):
        profiles = self.store.profiles()
        selected = self.store.setting('selected_profile', '')
        return next((profile for profile in profiles if profile.id == selected), profiles[0] if profiles else None)

    @property
    def maintenance_busy(self):
        diagnostic = self.diagnostic
        with diagnostic.lock:
            return (not diagnostic.idle or self._intent is not None or diagnostic.stops
                    or diagnostic.monitor.running or diagnostic.monitor.executors
                    or diagnostic.executors)

    def enable_project_peer(self, execution):
        from src.services.ai_capability_adapter import AiCapabilityAdapter
        execution.instance_registry()
        self.capabilities = execution.capabilities
        self.conversation.capabilities = AiCapabilityAdapter(self.conversation, self.capabilities)
        self.conversation.prepare_gateway_turn = self._configure_peer_turn
        self.conversation.peer_ready = lambda: not self.closing and self._profile() is not None

    def enable_direct_platform(self, authorized):
        from src.services.ai_capability_adapter import AiCapabilityAdapter
        execution = self.conversation.execution
        execution.instance_registry()
        self.capabilities = execution.capabilities
        self.conversation.capabilities = AiCapabilityAdapter(self.conversation, self.capabilities)
        self.conversation.direct_authority = authorized
        self.conversation.prepare_direct_turn = self.refresh_direct_targets
        self.refresh_direct_targets()

    def refresh_direct_targets(self):
        profile = self._profile()
        try:
            targets = self.handoff.configured_targets()
        except ValueError:
            targets = ()
        self.diagnostic.configure(profile, targets)

    def _configure_peer_turn(self):
        execution = self.conversation.execution
        if execution.closing or execution.workspace_close_requested():
            raise ValueError('项目正在收尾，本次消息未提交')
        profile = self._profile()
        if profile is None:
            raise ValueError('项目尚未选择 AI 模型，本次请求未提交')
        self.diagnostic.configure(profile, self.handoff.configured_targets())

    def _managed_session(self, identifier):
        session = self.store.chat(identifier)
        if session.get('batch_parent'):
            raise ValueError('批量内部会话由父记录管理')
        return session

    def _selected_session(self, identifier):
        if not identifier or identifier != self.selected:
            raise ValueError('会话选择已变化，请重新选择')
        return self._managed_session(identifier)

    def _select(self, identifier, *, from_route=False):
        self._managed_session(identifier)
        if self._intent is not None and identifier != self.selected and not from_route:
            self._intent.stop.set()
        self.selected = identifier
        self.cursor = None
        self.conversation.router.select(identifier)

    def _select_channel_route(self, identifier):
        selected_scope = session_scope(self.store.chat(identifier))
        if selected_scope == 'device':
            self.store.update_chat(identifier, qt_channel_analysis=True)
        elif selected_scope == 'batch':
            self.store.update_chat(identifier, qt_batch_diagnostics=True)
        elif selected_scope == 'pc':
            self.store.update_chat(identifier, qt_pc_analysis=True)
        self._select(identifier, from_route=True)

    def _local_identity(self, identifier, text):
        profile = self._profile()
        model = _display_model(profile.model, self.diagnostic.redactor) if profile and profile.model.strip() else '未配置'
        answer = f'请求模型：{model}；服务端实际型号：未确认。\n本条由 DUTPilot 本地读取配置，未调用模型。'
        with self.store.lock:
            anchor = self.store.db.execute('SELECT max(id) FROM chat_messages WHERE session_id=?',
                                           (identifier,)).fetchone()[0] or 0
        stamp = timestamp()
        self._identity_messages.append((identifier, anchor, (ChatMessageView('user', text.strip(), stamp, 'text'),
                                        ChatMessageView('assistant', answer, stamp, 'text'))))
        self._route_errors.pop(identifier, None)
        self.conversation.local_display(identifier, '本条为本地配置查询，未调用模型')
        self.cursor = None
        self.diagnostic.emit('[Ai助手] 已在本地完成模型身份查询')

    def _send(self, identifier, text):
        if (identifier == self.selected and is_model_identity_question(text) and self._intent is None
                and not self._is_running() and (not identifier or
                    self.conversation.local_mode(self._selected_session(identifier)) == 'general')):
            self._local_identity(identifier, text)
            return
        session = self._selected_session(identifier)
        mode = self.conversation.local_mode(session)
        if not mode:
            raise ValueError('此历史会话当前仅可查看；请新建普通问答')
        if self._intent is not None:
            raise ValueError('上一条消息仍在识别目标，请等待或停止本轮')
        if mode in ('general', 'pc', 'pc_regular', 'channel', 'batch'):
            profile = self._profile()
            text = text.strip()
            if not 1 <= len(text) <= 32768:
                raise ValueError('请输入1至32768字符；较长日志请导入文本材料')
            if not profile or not profile.model.strip():
                raise ReviewRequired('configuration_incomplete', '请先保存并选择模型配置', 'model', 'model')
            targets = self.handoff.configured_targets()
            self.diagnostic.configure(profile, targets)
            self._route_errors.pop(identifier, None)
            self.conversation.local_display(identifier, '本条尚无可核对的模型请求')
            router = self.conversation.router
            batch_reply = mode == 'batch' and self.conversation.batch.fast_route(text, session, targets, False)
            if not batch_reply and explicit_channel_route(text, session):
                result = router.send(text, profile, selected=identifier, diagnosis_only=False,
                                     explicit_device_only=True, on_selected=self._select_channel_route)
                if isinstance(result, dict) and result.get('submitted') is False:
                    self.conversation.local_display(self.selected, '本条为本地目标切换，未调用模型')
            else:
                stop = threading.Event()
                run_id = self.conversation.context.run_id
                future = self._intent_worker.submit(self.conversation.resolve_intent, text, session, targets, profile, stop)
                self._intent = _PendingIntent(identifier, text, profile, targets, run_id, stop, future)
        else:
            diagnosis_only = None if mode == 'archived' else mode == 'pc'
            self.conversation.send(identifier, text, diagnosis_only=diagnosis_only)
        self.cursor = None

    def finish_intent(self):
        pending = self._intent
        if pending is None or not pending.future.done():
            return
        try:
            if self.closing or self.selected != pending.origin:
                return
            if pending.stop.is_set():
                raise InterruptedError('本机目标识别已取消')
            decision = pending.future.result()
            if (self._profile() != pending.profile or self.handoff.configured_targets() != pending.targets
                    or self.conversation.context.run_id != pending.run_id):
                raise ValueError('识别期间目标、批次或模型已变化，请重新发送')
            if decision.get('scope') == 'batch' and decision.get('workflow') != 'business' and decision.get('intent') != 'clarify':
                channels = decision.get('channels') or [t['channel'] for t in self.store.chat(pending.origin).get('batch_targets', ())]
                valid = {t.channel for t in pending.targets if self.access.active(t)}
                if not channels or any(c not in valid for c in channels):
                    raise ValueError('请先在“实时诊断与监控”确认本次批量目标')
            result = self.conversation.router.send(pending.text, pending.profile, selected=pending.origin,
                local_intent=decision, diagnosis_only=self.store.chat(pending.origin).get('diagnosis_only') is True,
                on_selected=self._select_channel_route)
            if isinstance(result, dict) and result.get('submitted') is False:
                with self.conversation.lock:
                    info = self.conversation.route_display.get(pending.stop)
                self.conversation.local_display(self.selected, info or '本条为本地目标处理，未调用模型')
            self.cursor = None
        except Exception as exc:
            if not self.closing and self.selected == pending.origin:
                reason = self.diagnostic.redactor.text(str(exc))
                self._route_errors[pending.origin] = (pending.text, reason)
                with self.conversation.lock:
                    info = self.conversation.route_display.get(pending.stop)
                self.conversation.local_display(pending.origin, info or '本次识别没有可核对的模型用量')
                self.diagnostic.emit('本机会话目标识别失败：' + reason)
        finally:
            self._intent = None
            self.conversation.notify(self.selected)

    def _rename(self, identifier, title):
        self.titles.rename('chat', identifier, self.diagnostic.redactor.text(title))

    def _delete(self, identifiers):
        if self._intent is not None and self._intent.origin in identifiers:
            raise ValueError('此会话正在识别目标，请停止并等待收尾后再删除')
        for identifier in identifiers:
            self._managed_session(identifier)
        count = self.conversation.delete_sessions(identifiers)
        for identifier in identifiers:
            self._route_errors.pop(identifier, None)
            with self.conversation.lock:
                self.conversation.reply_display.pop(identifier, None)
                self.conversation.aborted_reply_display.pop(identifier, None)
        remaining = [row for row in self.store.chats() if not row.get('batch_parent')]
        if self.selected and not any(row['id'] == self.selected for row in remaining):
            if remaining:
                self._select(remaining[0]['id'])
            else:
                self.cursor = None
                self.selected = ''
                self.conversation.router.select('')
        return self.snapshot(deleted=count)

    def execute(self, operation, args):
        if operation == 'ai_chat_poll':
            return None if self.closing else self._poll()
        if self.closing:
            raise ValueError('AI 会话正在关闭')
        if operation == 'ai_chat_monitor_settings':
            return self.access.view()
        if operation == 'ai_chat_monitor_apply':
            self.access.confirm(*args)
            return self.snapshot()
        if operation == 'ai_chat_monitor_off':
            self.access.disable()
            return self.snapshot()
        if operation == 'ai_chat_monitor_review':
            return self.diagnostic.monitor.pending()
        if operation == 'ai_chat_monitor_decide':
            action_id, fingerprint, approved = args
            action = self.diagnostic.monitor.pending()
            if not action or (action['id'], action['fingerprint']) != (action_id, fingerprint):
                raise ValueError('待确认监控操作已变化，请重新查看')
            self.diagnostic.monitor.actions.decide(action['session_id'], action_id, fingerprint, approved)
            return self.snapshot()
        if operation in REPORT_OPERATIONS:
            return self.reports.execute(operation, args)
        if operation in REPORT_HANDOFF_OPERATIONS:
            profile = self._profile()
            try:
                result = self.handoff.prepare(*args, profile) if operation == 'ai_report_handoff' else self.handoff.finish(*args, profile)
            except Exception:
                self.conversation.emit('报告接手未完成，请查看报告窗口的状态')
                raise
            if not isinstance(result, str):
                return result
            self._select(result)
            return self.snapshot()
        if operation in CASE_OPERATIONS:
            return self.cases.execute(operation, args)
        if operation == 'ai_chat_permissions':
            identifier, = args
            self._selected_session(identifier)
            status = self.conversation.permissions.status(identifier)
            self.diagnostic.emit('[Ai助手] 已读取当前会话权限')
            details = identifier, PERMISSION_LABELS[status['preferred_mode']], status['label'], status['enabled']
            if self.conversation.collection_status(identifier).get('passive_serial'):
                return (*details, True)
            return details
        if operation in ('ai_chat_review', 'ai_chat_decide'):
            identifier = args[0]
            self._selected_session(identifier)
            if operation == 'ai_chat_review':
                self.diagnostic.emit('[Ai助手] 核对当前会话待批准操作')
                if not self.conversation.collection_status(identifier)['enabled']:
                    return identifier, None
                action = self.conversation.actions.pending(identifier)
                return identifier, action
            action_id, fingerprint, approved = args[1:]
            current = self.conversation.actions.pending(identifier)
            if not current or current['id'] != action_id or current['fingerprint'] != fingerprint:
                raise ValueError('待批准操作已失效，请重新核对')
            self.conversation.actions.decide(current['session_id'], action_id, fingerprint, approved)
            return self.snapshot()
        if operation == 'ai_chat_delete_many':
            return self._delete(args[0])
        if operation == 'ai_chat_manage_rename':
            identifier, title = args
            self._managed_session(identifier)
            self._rename(identifier, title)
        if operation in ('ai_chat_open', 'ai_chat_new', 'ai_chat_new_pc', 'ai_chat_import'):
            profile = self._profile()
            if profile != self.diagnostic.profile:
                self.diagnostic.configure(profile, ())
        if operation == 'ai_chat_select':
            self._select(args[0])
        elif operation == 'ai_chat_new':
            self._select(self.conversation.create_blank_session(profile))
        elif operation == 'ai_chat_new_pc':
            self._select(self.conversation.create_session(None, profile, scope='pc', diagnosis_only=True))
        elif operation == 'ai_chat_send':
            self._send(*args)
        elif operation == 'ai_chat_stop':
            identifier, = args
            if not self.conversation.local_mode(self._selected_session(identifier)):
                raise ValueError('此历史会话当前仅可查看')
            if self._intent is not None and self._intent.origin == identifier:
                self._intent.stop.set()
                self.diagnostic.emit('已取消本机目标识别，等待识别请求收尾')
            self.conversation.stop(identifier)
        elif operation in ('ai_chat_import', 'ai_chat_rename', 'ai_chat_delete', 'ai_chat_evidence', 'ai_chat_page', 'ai_chat_progress'):
            identifier = args[0]
            session = self._selected_session(identifier)
            if operation == 'ai_chat_progress':
                self.diagnostic.emit('[Ai助手] 已读取当前会话的留存排查进展')
                return identifier, diagnostic_progress_text(session)
            if operation == 'ai_chat_evidence':
                return tuple((row['source'], row['timing'], row['text']) for row in self.store.chat_evidence(identifier))
            if operation == 'ai_chat_page':
                cursor = args[1]
                if cursor is not None and (type(cursor) is not int or not 0 < cursor < 2**63):
                    raise ValueError('历史消息页不可用')
                self.cursor = cursor
            elif operation == 'ai_chat_import':
                if not self.conversation.local_mode(session):
                    raise ValueError('此历史会话当前仅可查看')
                self.conversation.import_text(identifier, args[1])
                self.cursor = None
            elif operation == 'ai_chat_rename':
                self._rename(identifier, args[1])
            else:
                return self._delete((identifier,))
        return self.snapshot()

    def _poll(self):
        changed = False
        while True:
            try:
                self.conversation.updates.get_nowait()
            except queue.Empty:
                break
            changed = True
        running = self._is_running()
        if changed or (self._last_view is not None and (running != self._last_view.running or self.diagnostic.monitor_status() != self._last_view.monitor_status)):
            return self.snapshot()
        return None

    def _is_running(self):
        if self._intent is not None and self._intent.origin == self.selected:
            return True
        with self.conversation.lock:
            return self.selected in self.conversation.running or self.selected in self.conversation.executors

    def _context_text(self, session=None, running=False):
        if self.cursor is not None:
            return ''
        with self.conversation.lock:
            if self._intent is not None and self._intent.origin == self.selected:
                return self.conversation.route_display.get(self._intent.stop, '正在识别目标，本条尚无模型请求记录')
            receipt = self.conversation.reply_display.get(self.selected)
            active = self.conversation.running.get(self.selected)
            if receipt and (active is None or active is receipt[0]):
                if receipt[0] is None:
                    return receipt[1]
                heading = ('当前答复请求记录' if active is receipt[0] else
                           '此会话上次答复请求记录（非当前请求）')
                return heading + '\n' + receipt[1]
            if active is not None or running:
                return '本轮暂无可核对的模型请求与用量'
        return _saved_context_text(session.get('context_usage') if isinstance(session, dict)
                                   and session.get('id') == self.selected else None)

    @staticmethod
    def _message_view(message, mode, receipt=None):
        text = message['text']
        if message['role'] == 'user' and message.get('diagnostic_supplement') is True:
            state, supplement_id, request_id = receipt or (None, None, None)
            label = {'confirmed': '已带入下一次请求', 'cancelled': '已取消，未派发',
                     'not_dispatched': '未派发', 'unconfirmed': '派发未核实'}.get(state, '已接收')
            if state == 'confirmed' and not (supplement_id and request_id):
                label = '派发未核实'
            identity = f'补充编号 {supplement_id}\n' if supplement_id else ''
            if state == 'confirmed' and supplement_id and request_id:
                identity += f'请求编号 {request_id}\n'
            text = f'诊断补充（{label}）\n' + identity + text
        if (message['role'] == 'system' and message.get('kind') == 'progress'
                and text == '已采用你的补充，调整后续诊断方向。'):
            text = '本次检查点已留存补充记录。'
        if (mode in ('report', 'archived', 'channel') and message['role'] == 'system' and text.startswith('会话已创建；')
                and text.endswith('发送问题后按需采集。')):
            text = '会话已创建。'
        return ChatMessageView(message['role'], text, message.get('created', ''), message.get('kind', 'text'),
                               message.get('reply_id', ''), message.get('stream_state', ''))

    @staticmethod
    def _ordinary_activity(session, draft, stopping, routing, running, messages, aborted):
        identifier = session['id']
        if draft and draft.get('reply_id'):
            state = 'cancelling' if stopping else 'running'
            detail = ('已请求停止，等待本轮收尾' if stopping else
                      '已收到流式正文' if draft['text'] else '已进入回复生成流程，等待正文')
            return ChatActivityView(identifier, 'model_reply', draft['reply_id'], state, detail)
        if routing:
            return ChatActivityView(identifier, 'conversation', '', 'running', '正在识别目标，答复请求编号尚未分配')
        latest = next((m for m in reversed(messages) if m.role != 'system'), None)
        if latest and latest.role == 'assistant' and latest.reply_id and latest.stream_state in ('completed', 'cancelled', 'failed'):
            detail = '完整正文已保存' if latest.stream_state == 'completed' else '已保留未完成正文'
            return ChatActivityView(identifier, 'model_reply', latest.reply_id, latest.stream_state, detail)
        if latest and latest.role == 'user' and aborted is not None:
            return aborted
        if running:
            state = 'cancelling' if stopping else 'accepted'
            detail = '已请求停止，等待本轮收尾' if stopping else '等待答复请求编号或会话结果'
            return ChatActivityView(identifier, 'conversation', '', state, detail)
        return None

    def snapshot(self, *, deleted=None):
        self._snapshot_generation = getattr(self, '_snapshot_generation', 0) + 1
        generation = self._snapshot_generation
        records = self.store.chats()
        sessions = [row for row in records if not row.get('batch_parent')]
        selected = next((row for row in sessions if row['id'] == self.selected), None)
        rows = self.titles.chat_entries(sessions)
        with self.conversation.lock:
            busy = set(self.conversation.running) | set(self.conversation.executors)
        if self._intent is not None:
            busy.add(self._intent.origin)
        busy.update(row['batch_parent'] for row in records if row.get('batch_parent') and row['id'] in busy)
        view_rows = tuple(ChatSessionView(row['id'], row['title'], row['target_label'],
                          _display_model(row['model'], self.diagnostic.redactor) if row['model'] else '未配置',
                          row['status'], row.get('origin', ''), row['created'], row['id'] in busy) for row in rows)
        if selected is None:
            local = tuple(m for sid, _, pair in self._identity_messages if not sid for m in pair)
            self._last_view = ChatWorkspaceView(view_rows, '', local, deleted=deleted, monitor_status=self.diagnostic.monitor_status(),
                                                snapshot_generation=generation)
            return self._last_view
        # Read the draft and persisted messages on the same side of reply finalization.
        with self.conversation.lock, self.store.lock:
            draft = self.conversation.draft_message(self.selected) if self.cursor is None else None
            stop = self.conversation.running.get(self.selected)
            stopping = stop is not None and stop.is_set()
            aborted = self.conversation.aborted_reply_display.get(self.selected)
            running = self._is_running()
            messages = self.store.db.execute('SELECT m.id,m.payload,r.state,r.supplement_id,r.request_id FROM chat_messages m '
                'LEFT JOIN chat_supplement_receipts r ON r.message_id=m.id AND r.session_id=m.session_id '
                'WHERE m.session_id=? AND m.id<? ORDER BY m.id DESC LIMIT ?',
                (self.selected, self.cursor or 2**63-1, CHAT_PAGE + 1)).fetchall()
            status = self.store.db.execute(
                """SELECT payload FROM chat_messages WHERE session_id=? AND
                   CASE WHEN json_valid(payload) THEN json_extract(payload,'$.role')='system'
                   AND NOT (coalesce(json_extract(payload,'$.kind'),'')='context'
                            AND json_extract(payload,'$.text') LIKE '上下文容量：%') ELSE 0 END
                   ORDER BY id DESC LIMIT 1""", (self.selected,)).fetchone()
        mode = self.conversation.local_mode(selected)
        passive = mode == 'channel' and self.conversation.collection_status(self.selected).get('passive_serial', False)
        local = {}
        for sid, anchor, pair in self._identity_messages:
            if sid == self.selected:
                local.setdefault(anchor, []).extend(pair)
        items = list(local.get(0, ())) if len(messages) <= CHAT_PAGE else []
        latest_message = None
        for row_id, payload, state, supplement_id, request_id in reversed(messages[:CHAT_PAGE]):
            item = self._message_view(json.loads(payload), mode, (state, supplement_id, request_id))
            items.append(item)
            if item.role != 'system':
                latest_message = (row_id, item.role)
            items.extend(local.get(row_id, ()))
        page = tuple(items)
        latest_status = self._message_view(json.loads(status[0]), mode) if status else None
        if self.cursor is None and self.selected in self._route_errors:
            text, reason = self._route_errors[self.selected]
            detail = '目标识别失败：' + reason
            if reason == '当前会话与识别目标不一致或目标已变化，请明确切换目标':
                # This is only the selected conversation's existing display
                # label, not a newly validated or inferred device identity.
                row = next((row for row in view_rows if row.identifier == self.selected), None)
                if row is not None and row.target:
                    detail = f'目标识别失败（当前所选会话：{row.target}）：{reason}'
                detail += '\n本条未通过目标核对，未自动切换会话。'
            latest_status = ChatMessageView('system', detail, '', 'error')
            page += (ChatMessageView('user', self.diagnostic.redactor.text(text), '', 'text'), latest_status)
        if self._intent is not None and self._intent.origin == self.selected and self.cursor is None:
            page += (ChatMessageView('user', self.diagnostic.redactor.text(self._intent.text), '', 'text'),)
        if mode == 'general' and self.cursor is None:
            if stopping:
                latest_status = ChatMessageView('system', '已请求停止，等待本轮收尾', '', 'progress')
            elif draft:
                progress = '已收到本轮模型正文' if draft['text'] else '已进入模型调用，等待回复正文'
                latest_status = ChatMessageView('system', progress, '', 'progress')
        next_page = messages[CHAT_PAGE - 1][0] if len(messages) > CHAT_PAGE else None
        activity = None
        if mode == 'general' and self.cursor is None and self.selected not in self._route_errors:
            if aborted is None and not running:
                aborted = _saved_empty_cancel_activity(selected, latest_message)
            activity = self._ordinary_activity(selected, draft, stopping,
                self._intent is not None and self._intent.origin == self.selected, running, page, aborted)
        self._last_view = ChatWorkspaceView(view_rows, self.selected, page, draft['text'] if draft else '',
            self._context_text(selected, running), running, bool(mode), next_page, history_analysis=mode in ('report', 'archived') or (mode == 'channel' and not passive and not self.conversation.collection_status(self.selected)['enabled']),
            deleted=deleted, latest_status=latest_status, pc_diagnosis=(mode == 'pc'), passive_serial=passive,
            routing=self._intent is not None, retry_input=self._route_errors.get(self.selected, ('', ''))[0],
            monitor_status=self.diagnostic.monitor_status(), ordinary_chat=mode == 'general', snapshot_generation=generation, activity=activity)
        return self._last_view

    def begin_close(self):
        if not self.closing:
            self.closing = True
            if self._intent is not None:
                self._intent.stop.set()
            self._intent_worker.shutdown(wait=False)
            self.diagnostic.begin_close()
        if self._intent is not None and not self._intent.future.done():
            return False
        self._intent_worker.shutdown(wait=True)
        self._intent = None
        return self.diagnostic.idle and not any(thread.is_alive() for thread in (
            self.diagnostic.worker_thread, self.diagnostic.event_thread, self.conversation.worker))
