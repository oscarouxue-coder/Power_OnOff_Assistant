"""The original three pipeline choices and their current project readiness."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QDialog, QGridLayout, QHBoxLayout, QVBoxLayout

from src.services.qt_execution_adapter import PIPELINE_TASKS
from src.ui.qt.theme import button, label, status_style


class PipelineDialog(QDialog):
    start_requested = Signal(tuple)
    configuration_requested = Signal(str)
    refresh_requested = Signal()

    def __init__(self, project, parent):
        super().__init__(parent)
        self.setWindowTitle('全流程执行 · ' + project)
        self.resize(570, 355)
        self.checks, self.statuses = {}, {}
        self.ready = {}
        self.available = False
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setColumnStretch(0, 1)
        for index, (code, name) in enumerate(PIPELINE_TASKS.items(), 1):
            check = self.checks[code] = QCheckBox(f'{index}. {name}')
            check.toggled.connect(self._update)
            grid.addWidget(check, 2 * index - 2, 0)
            configure = button('去配置…', lambda task=code: self.configuration_requested.emit(task))
            configure.setAutoDefault(False)
            grid.addWidget(configure, 2 * index - 2, 1)
            status = self.statuses[code] = label('等待检查', 'muted')
            status.setWordWrap(True)
            grid.addWidget(status, 2 * index - 1, 0, 1, 2)
        layout.addLayout(grid)
        layout.addStretch()
        self.feedback = label('', 'muted')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        row = QHBoxLayout()
        refresh = button('刷新状态', self.refresh_requested.emit)
        row.addWidget(refresh)
        row.addStretch()
        self.start_button = button('开始执行…', lambda: self.start_requested.emit(self.selection()), 'primary')
        close = button('关闭', self.close)
        for control in (refresh, self.start_button, close):
            control.setAutoDefault(False)
        row.addWidget(self.start_button)
        row.addWidget(close)
        layout.addLayout(row)
        self._update()

    def selection(self):
        return tuple(code for code, check in self.checks.items() if check.isChecked())

    def set_availability(self, allowed):
        self.available = allowed
        self._update()

    def show_status(self, statuses):
        for code, status in statuses.items():
            self.ready[code] = status['ready']
            detail = status['summary'] if status['ready'] else '缺：' + '、'.join(status['missing'])
            self.statuses[code].setText(('就绪 · ' if status['ready'] else '') + detail)
            self.statuses[code].setStyleSheet(status_style('completed' if status['ready'] else 'failed'))
        self._update()

    def _update(self):
        tasks = self.selection()
        self.start_button.setEnabled(self.available and bool(tasks) and all(self.ready.get(code) for code in tasks))
