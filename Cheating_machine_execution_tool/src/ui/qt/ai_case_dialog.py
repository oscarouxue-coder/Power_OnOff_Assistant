"""Local operator controls for the existing shared diagnostic case library."""
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QSplitter, QVBoxLayout, QWidget)

from src.ui.qt.theme import button, label


class AiCaseDialog(QDialog):
    action_requested = Signal(str, object)

    def __init__(self, project, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('已确认案例 · 本机共享')
        self.project_id = project.project_id
        available = self.screen().availableGeometry()
        self.resize(min(980, int(available.width() * .94)), min(610, int(available.height() * .90)))
        self.busy = self.closing_project = False
        self.row = None
        self.report_id = ''
        self.baseline = ('',) * 5
        self.rows = {}

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(label('已确认案例 · 本机共享', 'title'), 1)
        self.refresh_button = button('刷新案例', self._refresh)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.cases = QListWidget()
        self.cases.setAccessibleName('已确认案例')
        self.cases.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.cases.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cases.currentItemChanged.connect(self._choose)
        splitter.addWidget(self.cases)

        editor = QWidget()
        body = QVBoxLayout(editor)
        self.source = label('未关联报告', 'muted')
        self.source.setTextFormat(Qt.TextFormat.PlainText)
        self.source.setWordWrap(True)
        body.addWidget(self.source)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.fields = tuple(QLineEdit() for _ in range(5))
        for name, field in zip(('标题', '已确认实际原因', '处理方法', '复测结果', '适用范围 / 设备版本'), self.fields):
            field.setAccessibleName(name)
            field.setMaximumWidth(570)
            form.addRow(name, field)
        body.addLayout(form)
        body.addStretch()
        actions = QHBoxLayout()
        self.new_button = button('新建案例', self._new)
        self.save_button = button('人工确认并保存', self._save, 'primary')
        self.toggle_button = button('停用检索', self._toggle)
        self.delete_button = button('删除案例…', self._delete, 'danger')
        for widget in (self.new_button, self.save_button, self.toggle_button, self.delete_button):
            actions.addWidget(widget)
        actions.addStretch()
        body.addLayout(actions)
        splitter.addWidget(editor)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes((280, 700))
        layout.addWidget(splitter, 1)
        self.feedback = label('', 'muted')
        self.feedback.setTextFormat(Qt.TextFormat.PlainText)
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self._sync()

    def _values(self):
        return tuple(field.text() for field in self.fields)

    def _confirm(self, title, message):
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        return QMessageBox.question(self, title, message, yes | no, no) == yes

    def can_replace(self):
        return self._values() == self.baseline or self._confirm('放弃未保存的修改', '放弃当前案例中未保存的修改？')

    def _choose(self, item, previous):
        if item is not None and not self.busy:
            if self.can_replace():
                self._fill(self.rows[item.data(Qt.ItemDataRole.UserRole)])
                self.feedback.clear()
            else:
                with QSignalBlocker(self.cases):
                    self.cases.setCurrentItem(previous)

    def _fill(self, row, report_id=''):
        self.row = row
        self.report_id = row.report_id if row else report_id
        self.baseline = row.fields if row else ('',) * 5
        self.source.setText('来源报告 · ' + self.report_id if self.report_id else '未关联报告')
        for field, value in zip(self.fields, self.baseline):
            field.setText(value or '')
        self._sync()

    def _sync(self):
        for widget in (self.refresh_button, self.cases, self.new_button, self.save_button, *self.fields):
            widget.setEnabled(not self.busy)
        self.toggle_button.setEnabled(not self.busy and self.row is not None)
        self.toggle_button.setText('启用检索' if self.row is not None and not self.row.active else '停用检索')
        self.delete_button.setEnabled(not self.busy and self.row is not None)

    def set_busy(self, busy):
        self.busy = busy
        self._sync()

    def _refresh(self):
        if not self.busy and self.can_replace():
            identifier = self.row.identifier if self.row else None
            self.action_requested.emit('ai_case_open', (identifier, self.report_id if self.row is None else ''))

    def _new(self):
        if not self.busy and self.can_replace():
            with QSignalBlocker(self.cases):
                self.cases.setCurrentRow(-1)
            self._fill(None)
            self.feedback.clear()
            self.fields[0].setFocus()

    def _save(self):
        if self.busy:
            return
        row, report_id, values = self.row, self.report_id, self._values()
        if self._confirm('人工确认案例', '确认实际原因、处理方法和复测结果已经核实？保存后本机各项目均可使用此案例。'):
            self.action_requested.emit('ai_case_save', (row.identifier if row else None,
                row.version if row else None, report_id, values))
        else:
            self.feedback.setText('已取消保存')

    def _toggle(self):
        row = self.row
        if not self.busy and row is not None and self.can_replace():
            self.action_requested.emit('ai_case_toggle', (row.identifier, row.version))

    def _delete(self):
        row = self.row
        if not self.busy and row is not None and self._confirm('永久删除案例',
                f'删除共用案例 #{row.identifier} 及其修订记录？此操作对本机所有项目生效。'):
            self.action_requested.emit('ai_case_delete', (row.identifier, row.version))

    def show_view(self, view):
        self.rows = {row.identifier: row for row in view.rows}
        with QSignalBlocker(self.cases):
            self.cases.clear()
            for row in view.rows:
                status = '参与检索' if row.active else '已停用'
                item = QListWidgetItem(f'{row.fields[0]}\n#{row.identifier} · {status}')
                item.setData(Qt.ItemDataRole.UserRole, row.identifier)
                self.cases.addItem(item)
                if row.identifier == view.selected:
                    self.cases.setCurrentItem(item)
                    self.cases.scrollToItem(item)
            if view.selected not in self.rows:
                self.cases.setCurrentRow(-1)
        self._fill(self.rows.get(view.selected), view.report_id)
        self.feedback.setText(view.notice)

    def close_for_project(self):
        self.closing_project = True
        self.close()

    def closeEvent(self, event):
        if self.closing_project or self.busy or self.can_replace():
            super().closeEvent(event)
        else:
            event.ignore()
