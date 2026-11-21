"""Select a locally imported platform without revealing its credentials."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QVBoxLayout

from src.ui.qt.theme import button, label


class ImportedConnectionDialog(QDialog):
    selection_requested = Signal(str)

    def __init__(self, choices, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('选择导入的接入配置')
        self.resize(500, 180)
        self.busy = False
        layout = QVBoxLayout(self)
        layout.addWidget(label('选择导入的接入配置', 'title'))
        self.candidates = QComboBox()
        self.candidates.addItem('请选择平台和来源' if choices else '暂无已导入的接入配置')
        for identity, description in choices:
            self.candidates.addItem(description, identity)
        self.candidates.setEnabled(bool(choices))
        layout.addWidget(self.candidates)
        self.feedback = label('保存后保持停用。启用接入须重启后在本机确认。' if choices else '', 'muted')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        layout.addStretch()
        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = button('取消', self.reject)
        self.apply_button = button('选择并保存', self._apply, 'primary')
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)
        self.candidates.currentIndexChanged.connect(self._sync)
        self._sync()

    def _sync(self, *_):
        self.apply_button.setEnabled(not self.busy and bool(self.candidates.currentData()))

    def set_busy(self, busy):
        self.busy = busy
        self.cancel_button.setEnabled(not busy)
        self.candidates.setEnabled(not busy and self.candidates.count() > 1)
        self._sync()

    def _apply(self):
        identity = self.candidates.currentData()
        if identity and not self.busy:
            self.selection_requested.emit(identity)

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)
