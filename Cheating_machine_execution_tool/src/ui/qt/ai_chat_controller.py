"""Route Qt conversation input and the existing workspace refresh to one project."""
import time
import threading
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QMenu, QPlainTextEdit,
                               QPushButton, QToolBar, QToolButton)

from src.models.project_review import ReviewRequired
from src.models.qt_ai_chat import CHAT_MANAGEMENT, ChatActivityView
from src.models.workbench_presentation import LogView
from src.services.qt_channel_evidence import ChatEvidenceResult, EvidenceTarget, disconnect_question_channel
from src.models.qt_ai_reports import REPORT_HANDOFF_OPERATIONS, ReportHandoffPreview
from src.ui.qt.ai_case_dialog import AiCaseDialog
from src.ui.qt.ai_chat_dialog import AiChatDialog
from src.ui.qt.ai_report_dialog import AiReportDialog


@dataclass(frozen=True)
class _ChatEvidenceRequest:
    identifier: int
    dialog: AiChatDialog
    session: str
    question: str
    target: EvidenceTarget
    stop: threading.Event


class AiChatController:
    def __init__(self, workspace):
        self.workspace = workspace
        self.windows = {}
        self.report_windows = {}
        self.case_windows = {}
        self.requests = {}
        self.polling = set()
        self.next_poll = 0.0
        self.evidence_dialog = None
        self.chat_evidence = None
        workspace.window.project_context_updated.connect(self._check_chat_evidence)
        toolbar = workspace.window.findChild(QToolBar, 'GlobalHeader')
        chat = workspace.window.ai_chat_action
        control = toolbar.widgetForAction(chat)
        menu = QMenu(control)
        evidence = menu.addAction('查询所选 DUT 的掉线证据（本地只读）…', self.open_evidence)
        control.setMenu(menu)
        control.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        # Qt overflows the default action of a split button, but not its arrow menu.
        overflow = toolbar.findChild(QToolButton, 'qt_toolbar_ext_button').menu()
        def include_split_action():
            overflow.removeAction(evidence)
            actions = overflow.actions()
            if chat in actions:
                index = actions.index(chat) + 1
                overflow.insertAction(actions[index] if index < len(actions) else None, evidence)
        evidence.setEnabled(chat.isEnabled())
        chat.enabledChanged.connect(evidence.setEnabled)
        overflow.aboutToShow.connect(include_split_action)

    def evidence_target(self, *, channel=None, project_id=None):
        window = self.workspace.window
        detail = window.detail
        project = self.workspace._current()
        panel = detail.test_type_panel
        if (self.workspace.closing or not self.workspace.ready or project is None
                or window.pages.currentWidget() is not detail or detail.project is None
                or (project_id is not None and project.project_id != project_id)
                or project.project_id != window.selected_project or project.project_id != detail.project.project_id
                or project.project_id != panel._project or project.project_id != window.logs.scope_id
                or project.run_id != window.logs.run_id or project.run_id != detail.run_id.text()
                or detail.project.run_id != project.run_id or detail.name.text() != project.name):
            raise ValueError('上下文不一致，请重新打开目标项目详情。')
        data = panel._data
        fields = ('job_id', 'evidence_run_id', 'revision')
        binding = tuple(data.get(key) for key in fields)
        if (project.project_type != 'service_aging' or not all(binding) or project.run_id not in binding[:2]
                or any(tuple((p.test_overview or {}).get(k) for k in fields) != binding
                       for p in (project, detail.project))):
            raise ValueError('缺少一致的持续老化批次和任务，请核对当前详情。')
        mapping = data.get('evidence_channels') or ()
        rows = data.get('rows', ())
        if channel is None:
            selected = panel._selected()
            if (not panel.table.isVisibleTo(detail) or not selected
                    or not any((r['dut_id'], r['collector']) == selected for r in rows)):
                raise ReviewRequired('invalid_target', '请在当前批次的业务检查表中选中一个 DUT。', 'project', 'business',
                                     project_id=project.project_id)
            matches = [(dut, ch) for dut, ch in mapping if dut == selected[0]]
        else:
            matches = [(dut, ch) for dut, ch in mapping if ch == channel]
        if (len(matches) != 1
                or any(p.test_overview.get('evidence_channels') != mapping for p in (project, detail.project))):
            raise ValueError('当前批次缺少目标的唯一通道映射，请核对运行快照。')
        dut, number = matches[0]
        if (not dut or type(number) is not int or not 1 <= number <= 16
                or sum(ch == number for _, ch in mapping) != 1
                or sum(key == dut for key, _ in mapping) != 1
                or not any(row['dut_id'] == dut for row in rows)):
            raise ValueError('当前批次缺少目标的唯一通道映射，请核对运行快照。')
        return EvidenceTarget(project.project_id, *binding, dut, number)

    def open_evidence(self):
        try:
            target = self.evidence_target()
        except ReviewRequired as error:
            self.workspace.blocker_review.status(str(error), error.review.project_id, error.review)
            return
        except ValueError as error:
            self.workspace.window.statusBar().showMessage(str(error), 8000)
            return
        if self.evidence_dialog is not None:
            self.evidence_dialog.close()
        dialog = _ChannelEvidenceDialog(self, target)
        self.evidence_dialog = dialog
        dialog.show()

    def open(self):
        project = self.workspace._current()
        if project is None or not self.workspace.ready or self.workspace.closing:
            return
        self._show_chat(project)

    def _show_chat(self, project, view=None):
        identifier = project.project_id
        dialog = self.windows.get(identifier)
        created = dialog is None
        if created:
            dialog = AiChatDialog(project, self.workspace.window)
            self.windows[identifier] = dialog
            dialog.action_requested.connect(lambda operation, args: self.submit(dialog, operation, args))
            dialog.model_settings_requested.connect(lambda: self.workspace.model_settings.open_for(project))
            dialog.reports_requested.connect(lambda: self.open_reports(project))
            dialog.cases_requested.connect(lambda: self.open_cases(project))
            dialog.finished.connect(lambda _: self._chat_closed(dialog))
            if view is None and not self.submit(dialog, 'ai_chat_open', ()):
                dialog.close()
                return
        if view is not None:
            dialog.show_view(view)
            if created:
                dialog.set_busy(False)
        dialog.showNormal()
        dialog.raise_()

    def open_reports(self, project):
        identifier = project.project_id
        dialog = self.report_windows.get(identifier)
        if dialog is None:
            dialog = AiReportDialog(project, self.workspace.window)
            self.report_windows[identifier] = dialog
            dialog.action_requested.connect(lambda operation, args: self.submit(dialog, operation, args))
            dialog.case_requested.connect(lambda report_id: self.open_cases(project, report_id))
            dialog.finished.connect(lambda _: self.report_windows.pop(identifier, None))
            if not self.submit(dialog, 'ai_report_open', ('',)):
                dialog.close()
                return
        dialog.showNormal()
        dialog.raise_()

    def open_cases(self, project, report_id=''):
        identifier = project.project_id
        dialog = self.case_windows.get(identifier)
        created = dialog is None
        if created:
            dialog = AiCaseDialog(project, self.workspace.window)
            self.case_windows[identifier] = dialog
            dialog.action_requested.connect(lambda operation, args: self.submit(dialog, operation, args))
            dialog.finished.connect(lambda _: self.case_windows.pop(identifier, None))
        elif report_id and (dialog.busy or not dialog.can_replace()):
            return
        if created or report_id:
            operation, args = ('ai_case_from_report', (report_id,)) if report_id else ('ai_case_open', (None, ''))
            if not self.submit(dialog, operation, args) and created:
                dialog.close()
                return
        dialog.showNormal()
        dialog.raise_()

    def can_close_case(self, identifier):
        dialog = self.case_windows.get(identifier)
        return dialog is None or dialog.can_replace()

    def _is_open(self, dialog):
        identifier = dialog.project_id
        return any(windows.get(identifier) is dialog for windows in (self.windows, self.report_windows, self.case_windows))

    def _chat_closed(self, dialog):
        self.windows.pop(dialog.project_id, None)
        self._check_chat_evidence()

    def _log_chat_evidence(self, dialog, channel, message, target=None):
        self.workspace.window.logs.append_batch((LogView(time.strftime('%H:%M:%S'), 'INFO',
            dialog.project_id, dialog.project_name, f'[Ai助手 · 本地证据] CH{channel:02d} · {message}',
            run_id=target.job_id if target else '', job_id=target.job_id if target else '',
            batch_id=target.run_id if target else '', dut_id=target.dut_id if target else '',
            channel=channel if 1 <= channel <= 16 else None),))

    def _send_chat_evidence(self, dialog, session, question, channel):
        question = question.strip()
        try:
            target = self.evidence_target(channel=channel, project_id=dialog.project_id)
        except ValueError as error:
            self._log_chat_evidence(dialog, channel, '跳过查询：' + str(error))
            dialog.show_local_evidence(question, '本地查询 · 未开始\n目标核对失败。' + str(error),
                ChatActivityView(session, 'local_evidence', '', 'not_started', str(error)))
        else:
            stop = threading.Event()
            identifier = self.workspace.submit('channel_evidence', target.project_id, target, stop, True)
            if identifier is None:
                dialog.show_local_evidence(question, '本地查询 · 未受理\n本地证据查询未受理，请重试。',
                    ChatActivityView(session, 'local_evidence', '', 'rejected', '查询未受理'))
                self._log_chat_evidence(dialog, channel, '查询未受理', target)
            else:
                self.chat_evidence = _ChatEvidenceRequest(identifier, dialog, session, question, target, stop)
                dialog.set_local_evidence_pending(True)
                dialog.show_local_evidence(question, f'本地查询 #{identifier} · 已受理\n'
                    f'正在核对 CH{channel:02d} 的冻结映射及本批次观测…',
                    ChatActivityView(session, 'local_evidence', str(identifier), 'accepted', '等待冻结目标与只读观测回执'))
                self._log_chat_evidence(dialog, channel, f'请求 #{identifier} 开始核对批次与通道观测', target)
        dialog.feedback.clear()
        dialog.composer.clear()
        return True

    def _cancel_chat_evidence(self, request, reason):
        self.chat_evidence = None
        request.stop.set()
        dialog, target = request.dialog, request.target
        self._log_chat_evidence(dialog, target.channel, f'请求 #{request.identifier} 已取消：' + reason, target)
        if self._is_open(dialog):
            dialog.set_local_evidence_pending(False)
            if dialog.view is not None and dialog.view.selected == request.session:
                dialog.show_local_evidence(request.question, f'本地查询 #{request.identifier} · 已取消\n' + reason,
                    ChatActivityView(request.session, 'local_evidence', str(request.identifier), 'cancelled', reason))

    def _check_chat_evidence(self):
        request = self.chat_evidence
        if request is None:
            return
        dialog, target = request.dialog, request.target
        opened = self._is_open(dialog)
        if opened and dialog.view is not None and dialog.view.selected == request.session:
            try:
                if self.evidence_target(channel=target.channel, project_id=target.project_id) == target:
                    return
            except ValueError:
                pass
        self._cancel_chat_evidence(request, '上下文已变化，结果作废。请在当前项目与批次重新提问。')

    def submit(self, dialog, operation, args):
        if self.workspace.closing or not self._is_open(dialog):
            return False
        if operation == 'ai_chat_cancel_local_evidence':
            request = self.chat_evidence
            if request is not None and request.dialog is dialog and args == (request.session,):
                self._cancel_chat_evidence(request, '已请求停止本地查询，结果作废。')
                return True
            return False
        if (operation == 'ai_chat_send' and dialog.view is not None
                and dialog.view.ordinary_chat and not dialog.view.running):
            session, question = args
            channel = disconnect_question_channel(question)
            if channel is not None and session == dialog.view.selected:
                return self._send_chat_evidence(dialog, session, question, channel)
        identifier = self.workspace.submit(operation, dialog.project_id, *args)
        if identifier is None:
            return False
        self.requests[identifier] = dialog
        if operation == 'ai_chat_poll':
            self.polling.add(dialog.project_id)
        else:
            dialog.set_busy(True)
            dialog.feedback.clear()
        return True

    def handle_result(self, result):
        if result.operation == 'channel_evidence':
            self._check_chat_evidence()
            request = self.chat_evidence
            if request is not None and result.identifier == request.identifier:
                if request.stop.is_set():
                    self._cancel_chat_evidence(request, '已收到停止信号，结果作废。')
                    return True
                self.chat_evidence = None
                dialog, target = request.dialog, request.target
                payload = result.payload
                error = result.error
                if result.project_id != target.project_id or (not error and (
                        not isinstance(payload, ChatEvidenceResult) or payload.target != target)):
                    error = '返回的目标不一致或缺少核对回执，已丢弃结果。'
                dialog.set_local_evidence_pending(False)
                if error:
                    answer = f'本地查询 #{request.identifier} · 未完成\n' + error
                    log = f'请求 #{request.identifier} 查询失败：' + error
                else:
                    answer = payload.render(request.identifier)
                    log = (f'请求 #{request.identifier} 查询完成：目标核对通过，候选 {payload.candidates} 条，'
                           f'符合时效 {payload.valid} 条，引用 {len(payload.cited_ids)} 条；' + payload.outcome)
                activity = ChatActivityView(request.session, 'local_evidence', str(request.identifier),
                    'failed' if error else 'completed', error or payload.outcome)
                dialog.show_local_evidence(request.question, answer, activity)
                self._log_chat_evidence(dialog, target.channel, log, target)
                return True
            dialog = self.evidence_dialog
            if dialog is not None and result.identifier == dialog.request_id:
                dialog.finish(result)
            return True
        dialog = self.requests.pop(result.identifier, None)
        if dialog is None:
            return False
        polling = result.operation == 'ai_chat_poll'
        if polling:
            self.polling.discard(dialog.project_id)
        if self.workspace.closing or not self._is_open(dialog):
            return True
        if polling:
            if not result.error and result.payload is not None:
                dialog.show_view(result.payload)
            return True
        dialog.set_busy(False)
        if result.error:
            if hasattr(dialog.feedback, 'show_review'):
                self.workspace.blocker_review.inline(dialog, result, dialog.project_id)
            else:
                dialog.feedback.setText(result.error)
            if result.operation in CHAT_MANAGEMENT and dialog.manager is not None:
                dialog.manager.feedback.setText(result.error)
        elif result.operation == 'ai_chat_progress':
            dialog.show_progress(*result.payload)
        elif result.operation == 'ai_chat_monitor_settings':
            dialog.show_monitor(result.payload)
        elif result.operation == 'ai_chat_monitor_review':
            dialog.review_action_result('', result.payload, monitor=True)
        elif result.operation == 'ai_chat_permissions':
            dialog.show_permissions(*result.payload)
        elif result.operation == 'ai_chat_review':
            dialog.review_action_result(*result.payload)
        elif result.operation == 'ai_chat_evidence':
            dialog.show_evidence(result.payload)
        elif result.operation == 'ai_report_select':
            dialog.show_detail(result.payload)
        elif result.operation in REPORT_HANDOFF_OPERATIONS:
            if isinstance(result.payload, ReportHandoffPreview):
                dialog.confirm_handoff(result.payload)
            elif result.payload is None:
                dialog.feedback.setText('已取消关联')
            else:
                project = next((p for p in self.workspace.window.projects if p.project_id == dialog.project_id), None)
                if project is not None:
                    dialog.feedback.setText('已转入排查会话，可继续分析留存材料')
                    self._show_chat(project, result.payload)
        else:
            if result.operation == 'ai_chat_send' and dialog.accepts_view(result.payload):
                dialog.clear_local_evidence()
                dialog.composer.clear()
            dialog.show_view(result.payload)
        return True

    def poll(self, opened):
        self._check_chat_evidence()
        if self.evidence_dialog is not None:
            self.evidence_dialog.check_context()
        now = time.monotonic()
        refresh = now >= self.next_poll
        if refresh:
            self.next_poll = now + .3
        for identifier, dialog in tuple(self.windows.items()):
            if self.workspace.closing or identifier not in opened:
                dialog.close()
            elif refresh and dialog.view is not None and not dialog.busy and identifier not in self.polling:
                self.submit(dialog, 'ai_chat_poll', ())
        for identifier, dialog in tuple(self.report_windows.items()):
            if self.workspace.closing or identifier not in opened:
                dialog.close()
        for identifier, dialog in tuple(self.case_windows.items()):
            if identifier not in opened or (self.workspace.closing and self.workspace.adapter.closed.is_set()):
                dialog.close_for_project()


class _ChannelEvidenceDialog(QDialog):
    def __init__(self, controller, target):
        super().__init__(controller.workspace.window)
        self.controller, self.target = controller, target
        self.request_id = self.stop_event = None
        self.project_name = controller.workspace.window.detail.project.name
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('Ai助手 · 为什么反复掉线？')
        form = QFormLayout(self)
        for name, value in (('项目 ID', target.project_id), ('任务', target.job_id), ('批次', target.run_id),
                            ('DUT', target.dut_id), ('通道', f'CH{target.channel:02d}')):
            field = QLabel()
            field.setTextFormat(Qt.TextFormat.PlainText)
            field.setText(value)
            form.addRow(name, field)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        form.addRow(self.output)
        actions = QHBoxLayout()
        self.read = QPushButton('查询证据')
        self.stop = QPushButton('停止本次查询')
        self.stop.setEnabled(False)
        actions.addWidget(self.read)
        actions.addWidget(self.stop)
        form.addRow(actions)
        self.resize(590, 390)
        self.read.clicked.connect(self.start)
        self.stop.clicked.connect(self.cancel)
        self.finished.connect(self._closed)

    def check_context(self):
        try:
            matches = self.controller.evidence_target() == self.target
        except ValueError:
            matches = False
        if not matches:
            self.cancel()
            self.output.setPlainText('上下文不一致，请关闭此窗口并从目标项目重新查询。')
            self.read.setEnabled(False)
        return matches

    def log(self, message):
        target = self.target
        self.controller.workspace.window.logs.append_batch((LogView(time.strftime('%H:%M:%S'), 'INFO',
            target.project_id, self.project_name, f'[本地只读] CH{target.channel:02d} · {message}',
            run_id=target.job_id, job_id=target.job_id, batch_id=target.run_id, dut_id=target.dut_id,
            channel=target.channel),))

    def start(self):
        if self.request_id is not None or not self.check_context():
            return
        self.stop_event = threading.Event()
        self.request_id = self.controller.workspace.submit('channel_evidence', self.target.project_id,
                                                          self.target, self.stop_event)
        if self.request_id is None:
            self.output.setPlainText('查询未受理，请重试。')
            return
        self.read.setEnabled(False)
        self.stop.setEnabled(True)
        self.output.setPlainText(f'正在核对 CH{self.target.channel:02d} 的冻结映射并读取本批次观测…')
        self.log('开始核对批次与通道观测')

    def cancel(self):
        if self.stop_event is not None:
            self.stop_event.set()
            if self.request_id is not None:
                self.log('查询已停止')
        self.request_id = self.stop_event = None
        self.stop.setEnabled(False)
        self.read.setText('重新查询')
        self.read.setEnabled(True)
        self.output.setPlainText('已停止本次查询。')

    def finish(self, result):
        if result.project_id != self.target.project_id or not self.check_context():
            self.cancel()
            self.output.setPlainText('上下文不一致，已丢弃返回的结果。')
            return
        self.request_id = self.stop_event = None
        self.stop.setEnabled(False)
        self.read.setText('重新查询')
        self.read.setEnabled(True)
        self.output.setPlainText(result.error or result.payload)
        self.log('查询失败：' + result.error if result.error else '本批次查询完成')

    def _closed(self):
        self.cancel()
        if self.controller.evidence_dialog is self:
            self.controller.evidence_dialog = None
