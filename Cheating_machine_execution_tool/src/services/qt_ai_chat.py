"""Reuse original project conversations for local questions and retained reports."""
from concurrent.futures import Future, ThreadPoolExecutor
import threading
from dataclasses import dataclass
import json
import queue

from src.models.ai_diagnostics import DiagnosticTarget, ProviderProfile, diagnostic_progress_text
from src.models.ai_permissions import PERMISSION_LABELS
from src.models.dependency_repair import maintenance_operation
from src.models.ai_session_scope import session_scope, source_identity
from src.models.qt_ai_chat import ChatMessageView, ChatSessionView, ChatWorkspaceView
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


class QtLocalConversation(AiConversationService):
    def __init__(self, diagnostic, execution):
        self.execution = execution
        super().__init__(diagnostic, context=execution.ai_evidence)

    @maintenance_operation
    def resolve_intent(self, text, session, targets, profile, stop):
        return self.router._resolve(text, session, targets, profile, stop, False)

    def local_mode(self, session):
        return _local_chat_mode(session, self.context.run_id)

    def capabilities_for(self, identifier):
        adapter = getattr(self, 'capabilities', None)
        if adapter and (self.store.chat(identifier).get('source') or {}).get('gateway_instance_id'):
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
        self._intent_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='qt-local-intent')
        self._intent = None
        self._route_errors = {}

    def _profile(self):
        profiles = self.store.profiles()
        selected = self.store.setting('selected_profile', '')
        return next((profile for profile in profiles if profile.id == selected), profiles[0] if profiles else None)

    def enable_project_peer(self, execution):
        from src.services.ai_capability_adapter import AiCapabilityAdapter
        execution.instance_registry()
        self.capabilities = execution.capabilities
        self.conversation.capabilities = AiCapabilityAdapter(self.conversation, self.capabilities)
        self.conversation.prepare_gateway_turn = self._configure_peer_turn
        self.conversation.peer_ready = lambda: not self.closing and self._profile() is not None

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

    def _send(self, identifier, text):
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
                raise ValueError('请先保存并选择模型配置')
            targets = self.handoff.configured_targets()
            self.diagnostic.configure(profile, targets)
            self._route_errors.pop(identifier, None)
            router = self.conversation.router
            batch_reply = mode == 'batch' and self.conversation.batch.fast_route(text, session, targets, False)
            if not batch_reply and explicit_channel_route(text, session):
                router.send(text, profile, selected=identifier, diagnosis_only=False,
                            explicit_device_only=True, on_selected=self._select_channel_route)
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
            self.conversation.router.send(pending.text, pending.profile, selected=pending.origin,
                local_intent=decision, diagnosis_only=self.store.chat(pending.origin).get('diagnosis_only') is True,
                on_selected=self._select_channel_route)
            self.cursor = None
        except Exception as exc:
            if not self.closing and self.selected == pending.origin:
                reason = self.diagnostic.redactor.text(str(exc))
                self._route_errors[pending.origin] = (pending.text, reason)
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

    def _context_text(self):
        usage = self.conversation.context_status(self.selected)
        capacity = usage['capacity']
        title = f'上限 {capacity:,} Token' if capacity else '上下文容量未知'
        snapshot = usage.get('snapshot') or {}
        if usage.get('stale'):
            return title + ' · 旧用量待更新'
        if 'total_tokens' not in snapshot:
            return title
        prefix = '约 ' if snapshot.get('source') != 'api' else ''
        return f"{title} · 最近用量 {prefix}{snapshot['total_tokens']:,} Token"

    @staticmethod
    def _message_view(message, mode):
        text = message['text']
        if (mode in ('report', 'archived', 'channel') and message['role'] == 'system' and text.startswith('会话已创建；')
                and text.endswith('发送问题后按需采集。')):
            text = '会话已创建。'
        return ChatMessageView(message['role'], text, message.get('created', ''), message.get('kind', 'text'))

    def snapshot(self, *, deleted=None):
        records = self.store.chats()
        sessions = [row for row in records if not row.get('batch_parent')]
        selected = next((row for row in sessions if row['id'] == self.selected), None)
        rows = self.titles.chat_entries(sessions)
        with self.conversation.lock:
            busy = set(self.conversation.running) | set(self.conversation.executors)
        if self._intent is not None:
            busy.add(self._intent.origin)
        busy.update(row['batch_parent'] for row in records if row.get('batch_parent') and row['id'] in busy)
        view_rows = tuple(ChatSessionView(row['id'], row['title'], row['target_label'], row['model'],
                          row['status'], row.get('origin', ''), row['created'], row['id'] in busy) for row in rows)
        if selected is None:
            self._last_view = ChatWorkspaceView(view_rows, '', (), deleted=deleted, monitor_status=self.diagnostic.monitor_status())
            return self._last_view
        with self.store.lock:
            messages = self.store.db.execute('SELECT id,payload FROM chat_messages WHERE session_id=? AND id<? '
                'ORDER BY id DESC LIMIT ?', (self.selected, self.cursor or 2**63-1, CHAT_PAGE + 1)).fetchall()
            status = self.store.db.execute(
                """SELECT payload FROM chat_messages WHERE session_id=? AND
                   CASE WHEN json_valid(payload) THEN json_extract(payload,'$.role')='system'
                   AND NOT (coalesce(json_extract(payload,'$.kind'),'')='context'
                            AND json_extract(payload,'$.text') LIKE '上下文容量：%') ELSE 0 END
                   ORDER BY id DESC LIMIT 1""", (self.selected,)).fetchone()
        mode = self.conversation.local_mode(selected)
        passive = mode == 'channel' and self.conversation.collection_status(self.selected).get('passive_serial', False)
        page = tuple(self._message_view(json.loads(payload), mode) for _, payload in reversed(messages[:CHAT_PAGE]))
        latest_status = self._message_view(json.loads(status[0]), mode) if status else None
        if self.cursor is None and self.selected in self._route_errors:
            text, reason = self._route_errors[self.selected]
            latest_status = ChatMessageView('system', '目标识别失败：' + reason, '', 'error')
            page += (ChatMessageView('user', self.diagnostic.redactor.text(text), '', 'text'), latest_status)
        if self._intent is not None and self._intent.origin == self.selected and self.cursor is None:
            page += (ChatMessageView('user', self.diagnostic.redactor.text(self._intent.text), '', 'text'),)
        draft = self.conversation.draft_message(self.selected) if self.cursor is None else None
        next_page = messages[CHAT_PAGE - 1][0] if len(messages) > CHAT_PAGE else None
        self._last_view = ChatWorkspaceView(view_rows, self.selected, page, draft['text'] if draft else '',
            self._context_text(), self._is_running(), bool(mode), next_page, history_analysis=mode in ('report', 'archived') or (mode == 'channel' and not passive and not self.conversation.collection_status(self.selected)['enabled']),
            deleted=deleted, latest_status=latest_status, pc_diagnosis=(mode == 'pc'), passive_serial=passive,
            routing=self._intent is not None, retry_input=self._route_errors.get(self.selected, ('', ''))[0],
            monitor_status=self.diagnostic.monitor_status())
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
