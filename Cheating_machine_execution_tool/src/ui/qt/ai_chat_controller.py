"""Route Qt conversation input and the existing workspace refresh to one project."""
import time

from src.models.qt_ai_chat import CHAT_MANAGEMENT
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
