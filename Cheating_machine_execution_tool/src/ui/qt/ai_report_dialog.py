"""Browse and manage a single project's existing diagnostic reports."""
from PySide6.QtCore import QItemSelectionModel, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QSplitter, QTabWidget, QVBoxLayout)

from src.ui.qt.theme import button, label


class AiReportDialog(QDialog):
    action_requested = Signal(str, object)
    case_requested = Signal(str)

    def __init__(self, project, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.project_id = project.project_id
        self.project_name = project.name
        self.setWindowTitle('诊断报告 · ' + self.project_name)
        available = self.screen().availableGeometry()
        self.resize(min(1000, int(available.width() * .94)), min(660, int(available.height() * .90)))
        self.rows = {}
        self.detail = None
        self.handoff_confirmation = None
        self.busy = False

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = label('诊断报告 · ' + self.project_name, 'title')
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        header.addWidget(title, 1)
        self.handoff_button = button('继续排查…', self._handoff)
        header.addWidget(self.handoff_button)
        self.refresh_button = button('刷新报告', lambda: self._submit('ai_report_open', self._current()))
        header.addWidget(self.refresh_button)
        self.manage_button = button('管理报告')
        menu = QMenu(self.manage_button)
        menu.addAction('全选报告', lambda: self.reports.selectAll())
        menu.addAction('取消选择', lambda: self.reports.clearSelection())
        self.rename_action = menu.addAction('重命名报告…', self._rename)
        self.case_action = menu.addAction('从当前报告新建案例…', self._case_from_report)
        self.delete_action = menu.addAction('删除选中…', lambda: self._delete(self._selected()))
        self.clear_action = menu.addAction('清空全部…', lambda: self._delete(tuple(self.rows)))
        self.manage_button.setMenu(menu)
        header.addWidget(self.manage_button)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.reports = QListWidget()
        self.reports.setAccessibleName('项目诊断报告')
        self.reports.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.reports.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.reports.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.reports.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.reports.customContextMenuRequested.connect(
            lambda point: menu.popup(self.reports.viewport().mapToGlobal(point)))
        self.reports.currentItemChanged.connect(self._select)
        self.reports.itemSelectionChanged.connect(self._sync)
        splitter.addWidget(self.reports)
        tabs = QTabWidget()
        self.analysis = QPlainTextEdit()
        self.evidence = QPlainTextEdit()
        for name, editor in (('诊断分析', self.analysis), ('本地证据', self.evidence)):
            editor.setAccessibleName(name)
            editor.setReadOnly(True)
            tabs.addTab(editor, name)
        self.tabs = tabs
        splitter.addWidget(tabs)
        splitter.setSizes((280, 720))
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        self.metadata = label('', 'muted')
        self.metadata.setTextFormat(Qt.TextFormat.PlainText)
        self.metadata.setWordWrap(True)
        self.feedback = label('', 'muted')
        self.feedback.setTextFormat(Qt.TextFormat.PlainText)
        self.feedback.setWordWrap(True)
        layout.addWidget(self.metadata)
        layout.addWidget(self.feedback)
        self._sync()

    def _current(self):
        item = self.reports.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else ''

    def _selected(self):
        return tuple(item.data(Qt.ItemDataRole.UserRole) for item in self.reports.selectedItems())

    def _sync(self):
        selected = self._selected()
        self.refresh_button.setEnabled(not self.busy)
        self.handoff_button.setEnabled(not self.busy and self.detail is not None and self.handoff_confirmation is None)
        self.reports.setEnabled(not self.busy)
        self.manage_button.setEnabled(bool(self.rows) and not self.busy)
        self.rename_action.setEnabled(len(selected) == 1 and not self.busy)
        self.case_action.setEnabled(self.detail is not None and not self.busy)
        self.delete_action.setEnabled(bool(selected) and not self.busy)
        self.clear_action.setEnabled(bool(self.rows) and not self.busy)

    def set_busy(self, busy):
        self.busy = busy
        self._sync()

    def _submit(self, operation, *args):
        if not self.busy:
            self.action_requested.emit(operation, args)

    def _select(self, item, _previous):
        if item is not None:
            self._submit('ai_report_select', item.data(Qt.ItemDataRole.UserRole))

    def _rename(self):
        selected = self._selected()
        if self.busy or len(selected) != 1:
            return
        row = self.rows[selected[0]]
        name, accepted = QInputDialog.getText(self, '重命名报告', '报告名称', text=row.title)
        if accepted:
            self._submit('ai_report_rename', row.identifier, name)

    def _case_from_report(self):
        if self.detail is not None and not self.busy:
            self.case_requested.emit(self.detail.identifier)

    def _handoff(self):
        detail = self.detail
        if detail is not None and self.handoff_confirmation is None:
            self._submit('ai_report_handoff', detail.identifier, detail.revision)

    def confirm_handoff(self, preview):
        prompt = QDialog(self)
        prompt.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        prompt.setWindowTitle('关联旧报告材料')
        layout = QVBoxLayout(prompt)
        message = label(f'项目「{self.project_name}」的旧报告 {preview.report_id} 缺少完整目标快照。'
                        f'请选择通道 {preview.channel} 的当前目标，确认将报告作为历史材料关联。')
        message.setTextFormat(Qt.TextFormat.PlainText)
        message.setWordWrap(True)
        layout.addWidget(message)
        target = QComboBox()
        target.setAccessibleName('同通道关联目标')
        target.addItems(('请选择同通道目标', preview.target))
        layout.addWidget(target)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        confirm = buttons.button(QDialogButtonBox.StandardButton.Ok)
        confirm.setText('确认关联')
        confirm.setEnabled(False)
        confirm.setAutoDefault(False)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText('取消')
        cancel.setDefault(True)
        target.currentIndexChanged.connect(lambda index: confirm.setEnabled(index == 1))
        buttons.accepted.connect(prompt.accept)
        buttons.rejected.connect(prompt.reject)
        layout.addWidget(buttons)
        self.handoff_confirmation = prompt
        self._sync()

        def finished(result):
            self.handoff_confirmation = None
            self._sync()
            self._submit('ai_report_handoff_finish', preview.token, result == QDialog.DialogCode.Accepted)

        prompt.finished.connect(finished)
        prompt.open()

    def _delete(self, identifiers):
        if self.busy or not identifiers:
            return
        current = self._current()
        preview = '\n'.join(f'{row.title} | {row.created} | 通道 {row.channel} | {row.provider} / {row.model} | {row.identifier}'
                            for row in (self.rows[identifier] for identifier in identifiers[:12]))
        if len(identifiers) > 12:
            preview += f'\n另有 {len(identifiers) - 12} 份报告'
        prompt = QMessageBox(QMessageBox.Icon.Warning, '永久删除诊断报告',
            f'从「{self.project_name}」永久删除以下 {len(identifiers)} 份报告？\n\n{preview}\n\n'
            '会话、材料、案例、原始日志和模型配置将保留。任一报告仍在排队、生成或清理时，整批取消。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        prompt.setTextFormat(Qt.TextFormat.PlainText)
        prompt.setDefaultButton(QMessageBox.StandardButton.No)
        prompt.setEscapeButton(QMessageBox.StandardButton.No)
        if prompt.exec() == QMessageBox.StandardButton.Yes:
            self._submit('ai_report_delete', current, identifiers)
        else:
            self.feedback.setText('已取消删除')
        prompt.deleteLater()

    def show_view(self, view):
        selected = set(self._selected()).intersection(row.identifier for row in view.rows)
        self.rows = {row.identifier: row for row in view.rows}
        with QSignalBlocker(self.reports):
            self.reports.clear()
            for row in view.rows:
                status = '排队 / 生成 / 清理中' if row.busy else row.status
                created = row.created.replace('T', ' ', 1)
                item = QListWidgetItem(f'{row.title}\n{created}  ·  通道 {row.channel}  ·  {status}')
                item.setData(Qt.ItemDataRole.UserRole, row.identifier)
                self.reports.addItem(item)
                item.setSelected(row.identifier in selected)
                if view.detail is not None and view.detail.identifier == row.identifier:
                    self.reports.setCurrentItem(item, QItemSelectionModel.SelectionFlag.NoUpdate)
                    if not selected:
                        item.setSelected(True)
                    self.reports.scrollToItem(item)
        self.show_detail(view.detail)
        if view.deleted is not None:
            self.feedback.setText(f'已删除 {view.deleted} 份报告')
        self._sync()

    def show_detail(self, detail):
        if detail != self.detail:
            self.analysis.setPlainText(detail.analysis if detail else '')
            self.evidence.setPlainText(detail.evidence if detail else '')
        self.detail = detail
        row = self.rows.get(detail.identifier) if detail else None
        parts = (row.title, row.provider, row.model, row.identifier) if row else ()
        self.metadata.setText('  ·  '.join(part for part in parts if part) or '暂无诊断报告')
        self._sync()
