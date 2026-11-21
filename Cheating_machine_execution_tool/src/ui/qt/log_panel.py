"""Bounded, project/run-associated display buffer; no business log persistence."""
from collections import deque
import re
from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFrame, QHBoxLayout, QLineEdit, QPlainTextEdit, QSizePolicy, QVBoxLayout
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from src.ui.qt.theme import DANGER, SUCCESS, WARNING, assert_gui_thread, button, label


class OutcomeHighlight(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.formats = {}
        for level, color in (('SUCCESS', SUCCESS), ('WARN', WARNING), ('ERROR', DANGER)):
            style = QTextCharFormat()
            style.setForeground(QColor(color))
            self.formats[level] = style

    def highlightBlock(self, text):
        match = re.match(r'^(?:\d{4}-\d{2}-\d{2} )?\S+\s+(SUCCESS|WARN|ERROR)\s+\[', text)
        if match:
            self.setFormat(0, len(text), self.formats[match[1]])


class LogPanel(QFrame):
    expanded_changed = Signal(bool)
    export_requested = Signal(object, str)
    MAX_LINES = 5000
    MAX_CHARS = 1024 * 1024

    def __init__(self, parent=None, *, history=False, raw=False):
        super().__init__(parent)
        self.setProperty('card', True)
        self.entries = deque()
        self._chars = 0
        self._blocks = 0
        self.scope_id = ''
        self.scope_name = ''
        self.run_id = ''
        self.channels = ()
        self._selected = deque()
        self._export_enabled = False
        self.history = history
        self.raw = raw
        self.expanded = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 8)
        layout.setSpacing(5)
        header = QHBoxLayout()
        self.title = label('历史日志' if history else '实时日志（全局）', 'section')
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        header.addWidget(self.title, 1)
        self.scope = QComboBox()
        self.scope.setToolTip('已关联任务时按当前任务筛选通道，否则按项目筛选通道')
        if history:
            self.scope.setToolTip('筛选当前页中的通道记录')
        self.scope.setAccessibleName('日志范围')
        self.scope.setVisible(False)
        header.addWidget(self.scope)
        self.level = QComboBox()
        self.level.addItems(('全部级别', 'INFO', 'WARN', 'ERROR', 'SUCCESS'))
        self.level.setVisible(not raw)
        header.addWidget(self.level)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索日志关键字…')
        self.search.setMaximumWidth(240)
        self.search.setClearButtonEnabled(True)
        header.addWidget(self.search)
        self.auto_scroll = QCheckBox('自动滚动')
        self.auto_scroll.setChecked(True)
        header.addWidget(self.auto_scroll)
        if not history:
            header.addWidget(button('清空显示', self.clear_display))
        self.export_button = button('导出', self.request_export)
        self.export_button.setEnabled(False)
        self.export_button.setToolTip('将当前历史页的筛选日志保存到新的文本文件' if history
                                      else '将当前显示缓冲的筛选日志保存到新的文本文件')
        header.addWidget(self.export_button)
        self.fold_button = button('收起', self.toggle_expanded)
        self.fold_button.setVisible(not history)
        header.addWidget(self.fold_button)
        layout.addLayout(header)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(self.MAX_LINES)
        self.outcome_highlight = OutcomeHighlight(self.text.document())
        self.text.setFont(QFont('Consolas', 9))
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.text, 1)
        self.level.currentIndexChanged.connect(self.render)
        self.scope.currentIndexChanged.connect(self.render)
        self.search.textChanged.connect(self.render)

    def append_batch(self, entries):
        assert_gui_thread()
        batch = tuple(entries)
        removed_blocks = 0
        for entry in batch:
            self.entries.append(entry)
            self._chars += len(entry.message) + len(entry.project_name) + 80
            self._blocks += self._display_text(entry).count('\n') + 1
            while self._blocks > self.MAX_LINES or self._chars > self.MAX_CHARS:
                old = self.entries.popleft()
                blocks = self._display_text(old).count('\n') + 1
                self._blocks -= blocks
                self._chars -= len(old.message) + len(old.project_name) + 80
                if self._selected and old is self._selected[0]:
                    self._selected.popleft()
                    removed_blocks += blocks
        # Retention only removes a prefix, including any new entries evicted by this batch.
        kept = min(len(batch), len(self.entries))
        added = tuple(self._filtered(batch[-kept:])) if kept else ()
        if removed_blocks or added:
            self._append_visible(removed_blocks, added)

    @staticmethod
    def _display_text(entry):
        text = entry.message if entry.raw else f'{entry.time}   {entry.level:<5}   [{entry.project_name}]  {entry.message}'
        return text.replace('\r\n', '\n').replace('\r', '\n').replace('\u2029', '\n')

    def _append_visible(self, removed_blocks, added):
        scrollbar = self.text.verticalScrollBar()
        position = scrollbar.value()
        document = self.text.document()
        cursor = QTextCursor(document)
        if removed_blocks:
            retained = document.findBlockByNumber(removed_blocks)
            boundary = retained.position() if retained.isValid() else document.characterCount() - 1
            cursor.setPosition(boundary, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
        if added:
            cursor.movePosition(QTextCursor.MoveOperation.End)
            separator = '\n' if self._selected else ''
            cursor.insertText(separator + '\n'.join(map(self._display_text, added)))
        self._selected.extend(added)
        self.export_button.setEnabled(self._export_enabled and bool(self._selected))
        scrollbar.setValue(scrollbar.maximum() if self.auto_scroll.isChecked() else min(position, scrollbar.maximum()))

    def set_scope(self, project_id='', name='', run_id='', channels=()):
        assert_gui_thread()
        if (project_id, run_id, channels, name) == (self.scope_id, self.run_id, self.channels, self.scope_name):
            return
        previous = self.scope.currentData() if self.scope_id == project_id else None
        self.scope_id = project_id
        self.scope_name = name
        self.run_id = run_id
        self.channels = channels
        if not self.history:
            self.title.setText('项目日志' if project_id else '实时日志（全局）')
        self.title.setToolTip(name or self.title.text())
        with QSignalBlocker(self.scope):
            self.scope.clear()
            self.scope.addItem('本页全部' if self.history else '项目全部', 'project')
            if run_id and not self.history:
                self.scope.addItem('当前任务', 'run')
            for number in channels:
                self.scope.addItem(f'CH{number:02d}', number)
            self.scope.setCurrentIndex(max(0, self.scope.findData(previous)))
        self.scope.setVisible(bool(project_id and (run_id or channels)))
        self.render()

    def _filtered(self, entries):
        keyword, level = self.search.text().casefold(), self.level.currentText()
        scope = self.scope.currentData()
        run = self.run_id if scope == 'run' or type(scope) is int else ''
        return (entry for entry in entries if
                    (not self.scope_id or entry.project_id == self.scope_id) and
                    (not run or entry.run_id == run) and
                    (type(scope) is not int or entry.channel == scope) and
                    (level == '全部级别' or entry.level == level) and
                    (not keyword or keyword in (entry.message + entry.project_name).casefold()))

    def render(self):
        assert_gui_thread()
        selected = deque(self._filtered(self.entries))
        if selected == self._selected:
            return
        self._selected = selected
        self.export_button.setEnabled(self._export_enabled and bool(selected))
        scroll = self.text.verticalScrollBar()
        position = scroll.value()
        self.text.setPlainText('\n'.join(map(self._display_text, selected)))
        scroll.setValue(scroll.maximum() if self.auto_scroll.isChecked() else min(position, scroll.maximum()))

    def set_export_enabled(self, enabled):
        self._export_enabled = enabled
        self.export_button.setEnabled(enabled and bool(self._selected))

    def request_export(self):
        if self._export_enabled and self._selected:
            scope = self.scope.currentData()
            description = self.title.text() if self.history else self.title.text() + ' · 当前显示缓冲'
            if self.scope_name:
                description += ' · ' + self.scope_name
            if self.history or scope == 'run' or type(scope) is int:
                if self.run_id:
                    description += ' · 任务 ' + self.run_id
                if type(scope) is int:
                    description += f' · CH{scope:02d}'
            if not self.raw:
                description += ' · ' + self.level.currentText()
            self.export_requested.emit(tuple(self._selected), description)

    def clear_display(self):
        assert_gui_thread()
        self.entries.clear()
        self._chars = 0
        self._blocks = 0
        self.render()

    def toggle_expanded(self):
        self.expanded = not self.expanded
        self.text.setVisible(self.expanded)
        self.fold_button.setText('收起' if self.expanded else '展开')
        self.expanded_changed.emit(self.expanded)
