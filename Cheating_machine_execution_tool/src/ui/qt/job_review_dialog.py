"""Confirm an operator's observed result for a single durable Job."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QMessageBox, QPlainTextEdit, QVBoxLayout

from src.models.qt_log_history import JOB_REVIEW_OUTCOMES
from src.services.workbench_status_service import TASK_NAMES
from src.ui.qt.theme import button, label


class JobReviewDialog(QDialog):
    confirmed = Signal(str, str)

    def __init__(self, review, project_name, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('现场核实业务任务')
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.review = review
        self.project_name = project_name
        self.busy = False
        self.finished_with_error = False
        self.resize(540, 320)
        layout = QVBoxLayout(self)
        layout.addWidget(label('现场核实业务任务', 'title'))
        capability = TASK_NAMES.get(review.capability, review.capability)
        summary = label(f'{project_name} · {capability}\n{review.job_id}', 'muted')
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary.setWordWrap(True)
        layout.addWidget(summary)
        if review.channels:
            channels = label('通道 ' + '、'.join(str(channel) for channel in review.channels), 'muted')
            channels.setWordWrap(True)
            layout.addWidget(channels)
        self.outcome = QComboBox()
        self.outcome.setAccessibleName('现场核实结果')
        self.outcome.addItem('请选择现场核实结果')
        for code, title in JOB_REVIEW_OUTCOMES:
            self.outcome.addItem(title, code)
        layout.addWidget(self.outcome)
        self.evidence = QPlainTextEdit()
        self.evidence.setAccessibleName('现场核实依据')
        self.evidence.setPlaceholderText('填写现场核实依据')
        layout.addWidget(self.evidence, 1)
        self.feedback = label('', 'muted')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = button('取消', self.reject)
        self.confirm_button = button('记录核实结论', self._confirm, 'primary')
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.confirm_button)
        layout.addLayout(actions)
        self.outcome.currentIndexChanged.connect(self._sync)
        self.evidence.textChanged.connect(self._sync)
        self._sync()

    def _sync(self, *_):
        self.outcome.setEnabled(not self.busy)
        self.evidence.setEnabled(not self.busy)
        self.cancel_button.setEnabled(not self.busy)
        length = len(self.evidence.toPlainText().strip())
        self.confirm_button.setEnabled(not self.busy and not self.finished_with_error
                                       and bool(self.outcome.currentData()) and 0 < length <= 4000)
        if not self.busy and not self.finished_with_error:
            self.feedback.setText('依据最多 4000 字' if length > 4000 else '')

    def _confirm(self):
        if not self.confirm_button.isEnabled():
            return
        outcome = self.outcome.currentData()
        evidence = self.evidence.toPlainText().strip()
        self.busy = True
        self._sync()
        answer = QMessageBox.question(self, '确认现场核实',
            f'项目：{self.project_name}\n任务：{self.review.job_id}\n结果：{self.outcome.currentText()}\n\n'
            '记录以上结论和已填写的依据，并由原服务解除保护。是否确认？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        self.busy = False
        self._sync()
        if answer == QMessageBox.StandardButton.Yes:
            self.confirmed.emit(outcome, evidence)

    def set_submitted(self):
        self.busy = True
        self._sync()
        self.feedback.setText('正在记录核实结论…')

    def show_error(self, message):
        self.busy = False
        self.finished_with_error = True
        self._sync()
        self.feedback.setText(message + '\n重新提交前请打开新的任务审阅。')

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)
