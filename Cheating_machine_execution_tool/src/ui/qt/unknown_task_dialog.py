"""Local operator review of the original GUI resource protection records."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QMessageBox, QPlainTextEdit, QVBoxLayout

from src.ui.qt.theme import button, label


class UnknownTaskDialog(QDialog):
    review_confirmed = Signal(str, str, str)

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('本机核实原未知任务')
        self.resize(570, 310)
        self.busy = False
        self.confirming = False
        layout = QVBoxLayout(self)
        layout.addWidget(label('核实未知任务', 'title'))
        self.selection = QComboBox()
        self.selection.setAccessibleName('选择原未知任务')
        self.selection.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.selection.addItem('请选择原未知任务' if entries else '暂无待核实的 GUI 保护记录')
        for owner, name in entries:
            self.selection.addItem(f'{name} · {owner.rsplit(":", 1)[-1]}', (owner, name))
        layout.addWidget(self.selection)
        self.owner = label('', 'muted')
        self.owner.setWordWrap(True)
        self.owner.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.owner)
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
        self.review_button = button('记录并解除保护', self._confirm, 'primary')
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.review_button)
        layout.addLayout(actions)
        self.selection.currentIndexChanged.connect(self._selection_changed)
        self.evidence.textChanged.connect(self._sync)
        self._sync()

    def _selection_changed(self, *_):
        entry = self.selection.currentData()
        self.owner.setText(entry[0] if entry else '')
        self.evidence.clear()
        self.feedback.clear()
        self._sync()

    def _sync(self):
        enabled = not self.busy and not self.confirming
        self.cancel_button.setEnabled(enabled)
        self.selection.setEnabled(enabled and self.selection.count() > 1)
        self.evidence.setEnabled(enabled and bool(self.selection.currentData()))
        self.review_button.setEnabled(self.evidence.isEnabled() and bool(self.evidence.toPlainText().strip()))

    def set_busy(self, busy):
        self.busy = busy
        self.feedback.setText('正在记录核实依据并复核资源保护…' if busy else '')
        self._sync()

    def _confirm(self):
        entry = self.selection.currentData()
        evidence = self.evidence.toPlainText().strip()
        if self.busy or self.confirming or not entry or not evidence:
            return
        owner, name = entry
        self.confirming = True
        self._sync()
        try:
            answer = QMessageBox.question(self, '确认已核实现场结果',
                f'任务：{name}\n记录：{owner}\n\n仅记录核实依据并解除原任务保护。设备操作不会自动重试。是否确认？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        finally:
            self.confirming = False
            self._sync()
        if answer == QMessageBox.StandardButton.Yes:
            self.review_confirmed.emit(owner, name, evidence)

    def reject(self):
        if not self.busy and not self.confirming:
            super().reject()

    def closeEvent(self, event):
        if self.busy or self.confirming:
            event.ignore()
        else:
            super().closeEvent(event)
