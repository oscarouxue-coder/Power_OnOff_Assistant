"""Read-only native view of one channel's current power-test history."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QVBoxLayout

from src.ui.qt.theme import button, label


STATUS_LABELS = {'retry': '重试', 'failed': '失败', 'success': '重试后成功', 'resume': '续跑'}


class ChannelHistoryDialog(QDialog):
    page_requested = Signal(object)

    def __init__(self, parent, project, job, number):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.target = (project.project_id, job, number)
        self.setWindowTitle(f'{project.name} · CH{number:02d} 重试/失败历史')
        available = self.screen().availableGeometry()
        self.resize(min(740, int(available.width() * .94)), min(380, int(available.height() * .90)))
        layout = QVBoxLayout(self)
        title = label(f'CH{number:02d} 本次重试/失败历史 · 批次 {job[:8]}', 'section')
        title.setToolTip(job)
        layout.addWidget(title)
        self.body = QPlainTextEdit(readOnly=True)
        self.body.setAccessibleName('本次通道重试与失败记录')
        layout.addWidget(self.body, 1)
        self.feedback = label('', 'muted')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        actions = QHBoxLayout()
        actions.addStretch()
        self.next_cursor = None
        self.following = True
        self.newest = button('最新记录', lambda: self.page_requested.emit(None))
        self.older = button('更早记录', lambda: self.page_requested.emit(self.next_cursor))
        for control in (self.newest, self.older, button('关闭', self.close)):
            actions.addWidget(control)
        layout.addLayout(actions)

    def set_busy(self, busy):
        self.newest.setEnabled(not busy)
        self.older.setEnabled(not busy and self.next_cursor is not None)

    def show_page(self, page, before):
        self.next_cursor = page.next_cursor
        self.following = before is None
        text = '\n'.join(f'第 {entry.cycle} 轮｜{STATUS_LABELS.get(entry.status, entry.status)}：{entry.detail}'
                         for entry in page.entries)
        if text != self.body.toPlainText():
            self.body.setPlainText(text)
            if self.following:
                scroll = self.body.verticalScrollBar()
                scroll.setValue(scroll.maximum())
        self.feedback.setText(f'本页 {len(page.entries)} 条' if page.entries else '本次暂无重试或失败记录')
        self.set_busy(False)


class ChannelHistoryController:
    def __init__(self, workspace):
        self.workspace = workspace
        self.dialog = None
        self.pending = None
        self.last_event = -1

    @staticmethod
    def _project(target, projects):
        project_id, job, number = target
        return next((p for p in projects if p.project_id == project_id and p.power_history_job == job
                     and number in dict(p.power_history_events)), None)

    def open(self, project_id, job, number):
        if not self.workspace.ready or self.workspace.closing:
            return
        target = (project_id, job, number)
        project = self._project(target, self.workspace.window.projects)
        if project is None:
            self.workspace.window.statusBar().showMessage('开关机批次或通道已变化，请重新打开通道历史')
            return
        if self.dialog is not None and self.dialog.target == target:
            self.dialog.showNormal()
            self.dialog.raise_()
            return
        if self.dialog is not None:
            self.dialog.close()
        self.dialog = dialog = ChannelHistoryDialog(self.workspace.window, project, job, number)
        self.workspace.bind_module_window(dialog, project_id, 'power_test_channel_history')
        dialog.finished.connect(self._closed)
        dialog.page_requested.connect(self._request)
        dialog.show()
        self._request(None)

    def _closed(self, _result):
        self.dialog = self.pending = None
        self.last_event = -1

    def _request(self, before):
        if self.dialog is None or self.pending is not None or self.workspace.closing:
            return
        project = self._project(self.dialog.target, self.workspace.window.projects)
        if project is None:
            self.dialog.close()
            return
        request = self.workspace.submit('channel_history', *self.dialog.target, before)
        marker = dict(project.power_history_events)[self.dialog.target[2]]
        if request is not None:
            self.pending = (request, before, marker)
            self.dialog.set_busy(True)
        elif before is None:
            self.last_event = marker

    def handle_result(self, result):
        if result.operation != 'channel_history':
            return False
        if self.pending is None or self.pending[0] != result.identifier:
            return True
        _, before, marker = self.pending
        self.pending = None
        dialog = self.dialog
        if self.workspace.closing or self._project(dialog.target, self.workspace.window.projects) is None:
            dialog.close()
            return True
        if before is None:
            self.last_event = marker
        if result.error:
            dialog.set_busy(False)
            dialog.feedback.setText(result.error)
        else:
            dialog.show_page(result.payload, before)
        return True

    def poll(self, projects):
        if self.dialog is None:
            return
        project = self._project(self.dialog.target, projects)
        if project is None or self.workspace.closing:
            self.dialog.close()
        elif self.pending is None and self.dialog.following:
            marker = dict(project.power_history_events)[self.dialog.target[2]]
            if marker != self.last_event:
                self._request(None)
