"""Route Qt conversation input and the existing workspace refresh to one project."""
import time
import threading

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QMenu, QPlainTextEdit,
                               QPushButton, QToolBar, QToolButton)

from src.models.project_review import ReviewRequired
from src.models.qt_ai_chat import CHAT_MANAGEMENT
from src.models.workbench_presentation import LogView
from src.services.qt_channel_evidence import EvidenceTarget
from src.models.qt_ai_reports import REPORT_HANDOFF_OPERATIONS, ReportHandoffPreview
from src.ui.qt.ai_case_dialog import AiCaseDialog
from src.ui.qt.ai_chat_dialog import AiChatDialog
from src.ui.qt.ai_report_dialog import AiReportDialog


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

    def evidence_target(self):
        window = self.workspace.window
        detail = window.detail
        project = self.workspace._current()
        panel = detail.test_type_panel
        if (self.workspace.closing or not self.workspace.ready or project is None
                or window.pages.currentWidget() is not detail or detail.project is None
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
        selected = panel._selected()
        if (not panel.table.isVisibleTo(detail) or not selected
                or not any((r['dut_id'], r['collector']) == selected for r in data.get('rows', ()))):
            raise ReviewRequired('invalid_target', '请在当前批次的业务检查表中选中一个 DUT。', 'project', 'business',
                                 project_id=project.project_id)
        mapping = data.get('evidence_channels', ())
        matches = [channel for dut, channel in mapping if dut == selected[0]]
        if (len(matches) != 1 or type(matches[0]) is not int or not 1 <= matches[0] <= 16
                or sum(ch == matches[0] for _, ch in mapping) != 1
                or any(p.test_overview.get('evidence_channels') != mapping for p in (project, detail.project))):
            raise ValueError('批次缺少所选 DUT 的唯一通道映射，请核对运行快照。')
        return EvidenceTarget(project.project_id, *binding, selected[0], matches[0])

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
            dialog.finished.connect(lambda _: self.windows.pop(identifier, None))
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

    def submit(self, dialog, operation, args):
        if self.workspace.closing or not self._is_open(dialog):
            return False
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
            dialog.show_view(result.payload)
            if result.operation == 'ai_chat_send':
                dialog.composer.clear()
        return True

    def poll(self, opened):
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
