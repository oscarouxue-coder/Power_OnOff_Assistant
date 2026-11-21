"""Local operator review and confirmation of the workspace's project access scope."""
from html import escape
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QHeaderView,
                               QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from src.ui.qt.theme import button, label


class RemoteProjectScopeDialog(QDialog):
    def __init__(self, workspace):
        super().__init__(workspace.window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('远程可访问项目')
        self.resize(680, 360)
        self.workspace = workspace
        self.request = None
        self.review = None
        self.saving = False
        self.checks = {}
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setAccessibleName('本机保存的远程项目范围')
        self.table.setHorizontalHeaderLabels(('项目', '项目 ID', '当前授权', '保存后允许'))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)
        footer = QHBoxLayout()
        self.feedback = label('', 'muted')
        footer.addWidget(self.feedback, 1)
        self.refresh_button = button('刷新', self.refresh)
        footer.addWidget(self.refresh_button)
        self.save_button = button('核对并保存…', self.save, 'primary')
        self.save_button.setEnabled(False)
        footer.addWidget(self.save_button)
        footer.addWidget(button('关闭', self.close))
        layout.addLayout(footer)

    def refresh(self):
        if self.request is not None or self.workspace.closing:
            return
        self.request = self.workspace.submit('remote_scope_read')
        self.refresh_button.setEnabled(self.request is None)
        self.save_button.setEnabled(False)
        self.table.setEnabled(self.request is None)
        self.feedback.setText('正在读取…' if self.request is not None else '工作区忙，请重试')

    def _changes(self):
        saved = {key for key, _, allowed in self.review.rows if allowed}
        selected = {key for key, check in self.checks.items() if check.isChecked()}
        return selected, selected - saved, saved - selected

    def update_save(self):
        if self.review is None or self.request is not None:
            self.save_button.setEnabled(False)
            return
        _, added, removed = self._changes()
        self.save_button.setEnabled(bool(added or removed))

    def save(self):
        if not self.save_button.isEnabled() or self.workspace.closing:
            return
        review = self.review
        selected, added, removed = self._changes()
        changes = [f'{"新增" if key in added else "撤销"}  {name or "未打开的项目"} · {key}'
                   for key, name, _ in review.rows if key in added or key in removed]
        details = '<br>'.join(escape(line) for line in changes)
        answer = QMessageBox.question(self, '确认远程可访问项目',
            '<p>保存后，钉钉和飞书按新范围访问项目。已准入的业务任务继续运行。</p>' + details,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes or self.workspace.closing or review is not self.review:
            return
        self.request = self.workspace.submit('remote_scope_save', review.token, tuple(sorted(selected)))
        self.saving = self.request is not None
        self.table.setEnabled(not self.saving)
        self.refresh_button.setEnabled(not self.saving)
        self.update_save()
        self.feedback.setText('正在保存…' if self.saving else '工作区忙，请重试')

    def show_result(self, result):
        if self.request != result.identifier:
            return
        self.request = None
        self.saving = False
        self.refresh_button.setEnabled(True)
        self.table.setEnabled(True)
        self.review = result.payload
        self.checks.clear()
        rows = self.review.rows if self.review else ()
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for index, (identifier, name, allowed) in enumerate(rows):
            for column, text in enumerate((name or '未打开的项目', identifier, '已授权' if allowed else '未授权')):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(index, column, item)
            if name:
                check = QCheckBox()
                check.setAccessibleName(f'允许远程访问 {name} · {identifier}')
                check.setChecked(allowed)
                self.table.setCellWidget(index, 3, check)
                self.checks[identifier] = check
                check.toggled.connect(self.update_save)
            else:
                self.table.setItem(index, 3, QTableWidgetItem('保存时撤销'))
        self.update_save()
        if result.error:
            self.feedback.setText(result.error + '。请刷新后核对当前范围。')
        elif result.operation == 'remote_scope_save':
            self.feedback.setText('已保存远程项目范围')
        else:
            self.feedback.setText('已读取本机保存的范围' if rows else '当前没有已打开或已授权的项目')

    def reject(self):
        if not self.saving:
            super().reject()

    def closeEvent(self, event):
        if self.saving:
            event.ignore()
        else:
            super().closeEvent(event)
