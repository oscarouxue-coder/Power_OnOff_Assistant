"""Read-only view of the engine's existing serial sessions."""
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDialog, QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget

from src.ui.qt.theme import BACKGROUND, assert_gui_thread, label


class SerialObservationDialog(QDialog):
    def __init__(self, project, batch, title, parent=None):
        super().__init__(parent)
        self.batch = batch
        self.setWindowTitle(f'{project} · {title}串口日志')
        self.setStyleSheet(f'QDialog {{ background: {BACKGROUND}; }}')
        self.resize(940, 530)
        self.views = {}
        layout = QVBoxLayout(self)
        layout.addWidget(label(self.windowTitle(), 'title'))
        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        layout.addWidget(self.tabs, 1)
        self.status = label('', 'muted')
        layout.addWidget(self.status)

    @property
    def active(self):
        current = self.tabs.currentWidget()
        return next((vlan for vlan, view in self.views.items() if view[0] is current), '')

    def apply_snapshot(self, snapshot):
        assert_gui_thread()
        if snapshot['batch'] != self.batch:
            return
        for item in snapshot['tabs']:
            vlan = item['vlan']
            view = self.views.get(vlan)
            if view is None:
                page = QWidget()
                layout = QVBoxLayout(page)
                path = label(item['path'] or '原引擎未提供落盘文件', 'muted')
                path.setWordWrap(True)
                layout.addWidget(path)
                output = QPlainTextEdit()
                output.setReadOnly(True)
                output.document().setMaximumBlockCount(1600)
                layout.addWidget(output, 1)
                self.tabs.addTab(page, f"{vlan} / {item['port']}")
                view = self.views[vlan] = (page, output)
            self._append(view[1], item['text'])
        dropped = snapshot['dropped'] + sum(item['dropped'] for item in snapshot['tabs'])
        drops = ' · 显示缓冲已省略部分日志，原文件独立保存' if dropped else ''
        self.status.setText('只读观察 · 串口由原业务任务控制' + drops)

    @staticmethod
    def _append(output, text):
        if not text:
            return
        bar = output.verticalScrollBar()
        previous = bar.value()
        following = previous == bar.maximum()
        cursor = QTextCursor(output.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        excess = output.document().characterCount() - 131072
        if excess > 0:
            cursor.setPosition(0)
            cursor.setPosition(excess, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
        bar.setValue(bar.maximum() if following else previous)
