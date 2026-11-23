"""Read-only index of saved configurations that can seed an independent project."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QVBoxLayout, QWidget

from src.ui.qt.theme import GAP, label


class ProjectTemplatesPage(QWidget):
    project_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = ()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GAP)
        layout.addWidget(label('测试模板', 'title'))
        self.table = QTableView()
        self.table.setAccessibleName('可复用的已保存项目配置')
        description = ('双击或按 Enter 查看源项目，可另存为独立项目。要复用指定型号的测试方案，'
                       '从源项目向导的「项目操作」保存型号模板，再在新建向导选择并应用。')
        self.table.setToolTip(description)
        self.table.setAccessibleDescription(description)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.model = QStandardItemModel(self)
        self.model.setHorizontalHeaderLabels(('源项目', '已保存版本', '草稿状态'))
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.activated.connect(self._open_source)
        layout.addWidget(self.table, 1)
        self.empty = label('暂无可复用的已保存项目配置', 'muted')
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty, 1)
        self.table.hide()

    def set_projects(self, projects):
        rows = tuple((p.project_id, p.name, p.saved_revision, p.dirty) for p in projects if p.saved_revision)
        if self._rows == rows:
            return
        selected = self.table.currentIndex().data(Qt.ItemDataRole.UserRole)
        self._rows = rows
        self.model.removeRows(0, self.model.rowCount())
        for identifier, name, revision, dirty in rows:
            fields = [QStandardItem(value) for value in (
                name, revision[:12], '有未保存更改' if dirty else '与保存版一致')]
            for item in fields:
                item.setData(identifier, Qt.ItemDataRole.UserRole)
            fields[0].setToolTip(name + ' · ' + identifier)
            fields[1].setToolTip(revision)
            self.model.appendRow(fields)
            if identifier == selected:
                self.table.selectRow(fields[0].row())
        self.table.setVisible(bool(rows))
        self.empty.setVisible(not rows)

    def _open_source(self, index):
        identifier = index.data(Qt.ItemDataRole.UserRole)
        if identifier:
            self.project_requested.emit(identifier)
