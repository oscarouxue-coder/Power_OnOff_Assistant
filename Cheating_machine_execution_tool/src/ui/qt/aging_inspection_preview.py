"""Read-only navigation of the planned service-aging system inspections."""
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QPushButton,
    QTabBar, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from src.ui.qt.theme import V13_PALETTE as COLORS, card, label


STAGES = ('开始基线', '运行中', '结束')
INSPECTIONS = (
    ('进程', '进程清单', ('进程列表', 'PID', '进程数量', '疑似消失线索', '疑似重启线索'),
     '跨阶段核对进程名称、PID 和数量。进程未再出现或 PID 改变可提示疑似消失或重启，仍需其他记录佐证。'),
    ('进程', '状态与占用', ('进程状态', '线程数', 'VmSize · 虚拟内存', 'VmRSS · 驻留内存'),
     '按进程查看状态、线程数，以及虚拟地址空间和实际驻留内存的变化。'),
    ('进程', '文件描述符', ('实际打开的 FD 数', '已打开 FD 类型分布', 'FDSize · 描述符表容量'),
     '按实际打开的描述符统计数量与类型。FDSize 单独表示描述符表已分配的槽位数。'),
    ('内存', '系统可用内存', ('MemAvailable · 可用内存', '可用内存趋势'),
     '结合多个采样点查看可用内存走势。单点下降不足以判断内存泄漏。'),
    ('内存', 'Slab 内存', ('Slab · 总量', 'SReclaimable · 可回收', 'SUnreclaim · 不可回收', '各分项趋势'),
     '分别查看 Slab 总量、可回收与不可回收部分，并对照各自的变化趋势。'),
    ('网络', '套接字', ('TCP 套接字', 'UDP 套接字', 'Unix 域套接字', '监听或绑定状态', '连接方向', '分类数量变化'),
     '分协议查看监听、绑定或连接状态。方向仅在可判定时展示，数量按同一分类跨阶段对照。'),
    ('CPU', 'CPU 使用率', ('CPU 使用率', '使用率趋势'),
     '使用率依赖采样间隔。连续样本可用于观察持续负载与短时波动。'),
)


class AgingInspectionPreview(QDialog):
    def __init__(self, project_name, parent):
        super().__init__(parent)
        self.setWindowTitle(f'系统检测预览 · {project_name}')
        self.resize(840, 480)
        self.setMinimumSize(440, 360)
        self.setStyleSheet(f'QDialog {{background: {COLORS.background};}}')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(10)
        heading = QHBoxLayout()
        heading.addWidget(label('系统检测', 'title'))
        heading.addStretch()
        state = label('界面预览 / 采集未接入')
        state.setStyleSheet(f'background: {COLORS.neutral.background}; color: {COLORS.neutral.text};'
                            'padding: 4px 10px; border-radius: 5px;')
        heading.addWidget(state)
        outer.addLayout(heading)
        self.project_caption = label(f'全业务老化  /  {project_name}', 'muted')
        self.project_caption.setWordWrap(True)
        outer.addWidget(self.project_caption)
        self.compact_items = QComboBox()
        self.compact_items.setAccessibleName('检测项')
        outer.addWidget(self.compact_items)
        body = QHBoxLayout()
        outer.addLayout(body, 1)
        self.navigation = card()
        self.navigation.setFixedWidth(168)
        nav = QVBoxLayout(self.navigation)
        nav.setContentsMargins(10, 12, 10, 10)
        nav.addWidget(label('检测项', 'section'))
        self.tree = QTreeWidget()
        self.tree.setAccessibleName('系统检测项')
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(12)
        self.tree.setRootIsDecorated(False)
        self.tree.setItemsExpandable(False)
        self.tree.setStyleSheet(f'QTreeView {{border: 0; background: {COLORS.surface};}}'
                                'QTreeView::item {padding: 3px;}'
                                f'QTreeView::item:selected {{background: {COLORS.selected_background};'
                                f'color: {COLORS.selected};}}')
        nav.addWidget(self.tree, 1)
        body.addWidget(self.navigation)
        self.leaves = []
        groups = {}
        for index, (group, title, _, _) in enumerate(INSPECTIONS):
            if group not in groups:
                root = groups[group] = QTreeWidgetItem(self.tree, [group])
                root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                root.setForeground(0, QColor(COLORS.muted))
                font = root.font(0)
                font.setBold(True)
                root.setFont(0, font)
            leaf = QTreeWidgetItem(groups[group], [title])
            leaf.setData(0, Qt.ItemDataRole.UserRole, index)
            self.leaves.append(leaf)
            self.compact_items.addItem(f'{group}  /  {title}')
        self.tree.expandAll()

        detail = card()
        body.addWidget(detail, 1)
        pane = QVBoxLayout(detail)
        pane.setContentsMargins(14, 12, 14, 12)
        self.title = label('', 'section')
        pane.addWidget(self.title)
        row = QHBoxLayout()
        self.views = QTabBar()
        self.views.setAccessibleName('检测视图')
        self.views.setExpanding(False)
        self.views.addTab('检测概览')
        self.views.addTab('阶段对比')
        row.addWidget(self.views)
        row.addStretch()
        self.stage = QComboBox()
        self.stage.setAccessibleName('查看阶段')
        self.stage.addItems(STAGES)
        row.addWidget(self.stage)
        pane.addLayout(row)
        self.table = QTableWidget()
        self.table.setAccessibleName('检测项阶段数据')
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setMinimumSectionSize(50)
        pane.addWidget(self.table, 1)
        self.note = label('', 'muted')
        self.note.setWordWrap(True)
        pane.addWidget(self.note)
        self.tree.currentItemChanged.connect(self._tree_changed)
        self.compact_items.currentIndexChanged.connect(self._select)
        self.views.currentChanged.connect(self._render)
        self.stage.currentIndexChanged.connect(self._render)
        self._select(0)

    def _tree_changed(self, item, previous):
        if item and item.parent():
            self._select(item.data(0, Qt.ItemDataRole.UserRole))

    def _select(self, index):
        with QSignalBlocker(self.tree), QSignalBlocker(self.compact_items):
            self.tree.setCurrentItem(self.leaves[index])
            self.compact_items.setCurrentIndex(index)
        self._render()

    def _render(self):
        group, title, fields, note = INSPECTIONS[self.compact_items.currentIndex()]
        self.title.setText(f'{group}  /  {title}')
        self.note.setText(note)
        compare = self.views.currentIndex() == 1
        self.stage.setVisible(not compare)
        stages = STAGES if compare else (self.stage.currentText(),)
        self.table.setColumnCount(len(stages) + 1)
        self.table.setRowCount(len(fields))
        self.table.setHorizontalHeaderLabels(('观察字段', *stages))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for row, field in enumerate(fields):
            self.table.setItem(row, 0, QTableWidgetItem(field))
            for col in range(1, len(stages) + 1):
                value = QTableWidgetItem('无数据')
                value.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                value.setForeground(QColor(COLORS.muted))
                self.table.setItem(row, col, value)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = event.size().width() < 680
        self.navigation.setVisible(not compact)
        self.compact_items.setVisible(compact)
        self.title.setVisible(not compact)


class AgingInspectionEntry(QPushButton):
    def __init__(self, parent):
        super().__init__('系统检测预览…', parent)
        self.project_id = None
        self.project_name = ''
        self.dialog = None
        self.hide()
        self.clicked.connect(self._open)

    def set_project(self, project):
        identifier = project.project_id if project.project_type == 'service_aging' else None
        if self.dialog and (identifier != self.project_id or project.name != self.project_name):
            self.dialog.close()
        self.project_id, self.project_name = identifier, project.name
        self.setVisible(identifier is not None)

    def _open(self):
        if self.project_id is None or not self.isVisible():
            return
        if self.dialog is None:
            self.dialog = AgingInspectionPreview(self.project_name, self)
            self.dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self.dialog.finished.connect(self._closed)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def _closed(self):
        self.dialog = None

    def hideEvent(self, event):
        if self.dialog:
            self.dialog.close()
        super().hideEvent(event)
