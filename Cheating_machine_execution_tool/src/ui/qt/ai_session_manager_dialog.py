"""Manage the original project sessions without changing the active chat."""
from datetime import datetime

from PySide6.QtCore import QItemSelectionModel, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHeaderView, QHBoxLayout, QInputDialog,
                               QMenu, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from src.ui.qt.theme import button, label


def _display_time(value):
    value = str(value)
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        return value


class AiSessionManagerDialog(QDialog):
    action_requested = Signal(str, object)

    def __init__(self, project_name, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.project_name = project_name
        self.setWindowTitle('管理排障会话 · ' + project_name)
        available = self.screen().availableGeometry()
        self.resize(min(960, int(available.width() * .94)), min(550, int(available.height() * .90)))
        self.busy = False
        self.rows = {}
        self.loaded = False
        layout = QVBoxLayout(self)
        heading = label('管理排障会话 · ' + project_name, 'title')
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        layout.addWidget(heading)

        self.table = QTableWidget(0, 5)
        self.table.setAccessibleName('排障会话列表')
        self.table.setHorizontalHeaderLabels(('创建时间', '标题', '目标', '模型', '当前状态'))
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(45)
        for column, width in ((0, 147), (2, 125), (3, 125), (4, 140)):
            self.table.setColumnWidth(column, width)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._sync)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.menu = QMenu(self)
        self.menu.addAction('重命名会话…', self._rename)
        layout.addWidget(self.table, 1)
        self.counts = label('', 'muted')
        layout.addWidget(self.counts)
        self.feedback = label('', 'muted')
        self.feedback.setTextFormat(Qt.TextFormat.PlainText)
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)

        tools = QHBoxLayout()
        self.select_button = button('全选', self.table.selectAll)
        self.none_button = button('取消选择', self.table.clearSelection)
        self.refresh_button = button('刷新', lambda: self._submit('ai_chat_manage'))
        self.delete_button = button('删除选中', lambda: self._delete(self._selected()), 'danger')
        self.clear_button = button('清空全部', lambda: self._delete(tuple(self.rows)))
        for control in (self.select_button, self.none_button, self.refresh_button, self.delete_button, self.clear_button):
            tools.addWidget(control)
        tools.addStretch(1)
        self.close_button = button('关闭', self.close)
        tools.addWidget(self.close_button)
        layout.addLayout(tools)
        self._sync()

    def _selected(self):
        return tuple(self.table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
                     for index in self.table.selectionModel().selectedRows())

    def _sync(self):
        selection = self._selected()
        self.counts.setText(f'共 {len(self.rows)} 个会话，已选 {len(selection)} 个')
        self.table.setEnabled(not self.busy)
        self.refresh_button.setEnabled(not self.busy)
        self.select_button.setEnabled(not self.busy and bool(self.rows))
        self.none_button.setEnabled(not self.busy and bool(selection))
        self.delete_button.setEnabled(not self.busy and bool(selection))
        self.clear_button.setEnabled(not self.busy and bool(self.rows))

    def set_busy(self, busy):
        self.busy = busy
        self._sync()

    def show_view(self, view):
        previous = tuple(self.rows.values())
        if not self.loaded or previous != view.sessions:
            selection = set(self._selected())
            if not self.loaded and view.selected:
                selection.add(view.selected)
            self.loaded = True
            self.rows = {row.identifier: row for row in view.sessions}
            scrollbar = self.table.verticalScrollBar()
            offset = scrollbar.value()
            with QSignalBlocker(self.table):
                self.table.clearContents()
                self.table.clearSelection()
                self.table.setRowCount(len(self.rows))
                for number, row in enumerate(view.sessions):
                    status = '排查 / 排队 / 清理中' if row.busy else row.status
                    values = (_display_time(row.created), row.title, row.target, row.model, status)
                    for column, value in enumerate(values):
                        text = str(value or '')
                        item = QTableWidgetItem(text)
                        item.setToolTip(text)
                        item.setData(Qt.ItemDataRole.UserRole, row.identifier)
                        self.table.setItem(number, column, item)
                    if row.identifier in selection:
                        index = self.table.model().index(number, 0)
                        self.table.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Select |
                                                            QItemSelectionModel.SelectionFlag.Rows)
                scrollbar.setValue(offset)
        if view.deleted is not None:
            self.feedback.setText(f'已删除 {view.deleted} 个会话，剩余 {len(self.rows)} 条可见会话')
        self._sync()

    def _submit(self, operation, *args):
        if not self.busy:
            self.feedback.clear()
            self.action_requested.emit(operation, args)

    def _menu(self, point):
        item = self.table.itemAt(point)
        if not self.busy and item is not None and self._selected() == (item.data(Qt.ItemDataRole.UserRole),):
            self.menu.popup(self.table.viewport().mapToGlobal(point))

    def _rename(self):
        if self.busy or len(self._selected()) != 1:
            return
        identifier, = self._selected()
        row = self.rows[identifier]
        title, accepted = QInputDialog.getText(self, '重命名会话', '会话名称', text=row.title)
        if accepted and title.strip():
            self._submit('ai_chat_manage_rename', identifier, title)

    def _delete(self, identifiers):
        if self.busy or not identifiers:
            return
        preview = '\n'.join(f'{_display_time(row.created)} | {row.title} | {row.target} | {row.model}'
                            for row in (self.rows[key] for key in identifiers[:12]))
        if len(identifiers) > 12:
            preview += f'\n另有 {len(identifiers) - 12} 个会话'
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        prompt = QMessageBox(QMessageBox.Icon.Warning, '永久删除排障会话',
            f'从「{self.project_name}」永久删除以下 {len(identifiers)} 个会话？\n\n{preview}\n\n'
            '会话的消息、模型上下文、留存证据和所属批量子会话将删除。原始文件、诊断报告和已确认案例保留。'
            '\n任一会话仍在排查、排队或清理时，整批保留。',
            yes | no, self)
        prompt.setTextFormat(Qt.TextFormat.PlainText)
        prompt.setDefaultButton(no)
        prompt.setEscapeButton(no)
        answer = prompt.exec()
        prompt.deleteLater()
        if answer == yes:
            self._submit('ai_chat_delete_many', identifiers)
        else:
            self.feedback.setText('已取消删除')
