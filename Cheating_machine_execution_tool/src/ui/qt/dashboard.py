"""Responsive cards and a sortable table share one immutable project model."""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, QSize, Qt, QSortFilterProxyModel, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListView, QSizePolicy, QStackedWidget, QStyle,
    QStyledItemDelegate, QTableView, QVBoxLayout, QWidget)

from src.ui.qt.theme import (BACKGROUND, BORDER, BRAND, DANGER, GAP, MUTED, SUCCESS,
    TEXT, WARNING, assert_gui_thread, button, card, label)
from src.ui.qt.system_health_panel import SystemHealthPanel


def elapsed_seconds(value):
    parts = value.split(':')
    return sum(int(n) * factor for n, factor in zip(parts, (3600, 60, 1))) if len(parts) == 3 and all(n.isdigit() for n in parts) else -1


class ProjectTableModel(QAbstractTableModel):
    HEADERS = ('项目名称', '测试类型', '任务状态', '运行时间', '进度 / 数据来源', '异常')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.projects = ()

    def replace(self, projects):
        assert_gui_thread()
        projects = tuple(projects)
        if projects == self.projects:
            return
        if tuple(p.project_id for p in projects) == tuple(p.project_id for p in self.projects):
            self.projects = projects
            if projects:
                self.dataChanged.emit(self.index(0, 0), self.index(len(projects) - 1, len(self.HEADERS) - 1), [])
            return
        self.beginResetModel()
        self.projects = projects
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.projects)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.projects):
            return None
        project = self.projects[index.row()]
        values = (project.name, project.test_type, project.state_text, project.elapsed,
                  project.progress_text, project.attention_count)
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return values[index.column()]
        if role == Qt.ItemDataRole.UserRole:
            return project
        if role == Qt.ItemDataRole.UserRole + 1:
            return elapsed_seconds(project.elapsed) if index.column() == 3 else values[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 5 and project.attention_count:
            return QColor(DANGER)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None


class ProjectFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.keyword, self.state = '', ''
        self.setSortRole(Qt.ItemDataRole.UserRole + 1)

    def filterAcceptsRow(self, row, parent):
        project = self.sourceModel().projects[row]
        return (self.keyword in project.name.casefold() and
                (not self.state or (project.attention_count > 0 if self.state == 'attention' else project.state == self.state)))

    def set_filter(self, keyword, state):
        self.keyword, self.state = keyword.casefold(), state
        self.invalidateFilter()


class ProjectCardDelegate(QStyledItemDelegate):
    """Paint only visible cards; no per-project widget tree or refresh timer."""
    def sizeHint(self, option, index):
        return QSize(max(1, self.parent().gridSize().width()), 194)

    def paint(self, painter, option, index):
        project = index.data(Qt.ItemDataRole.UserRole)
        if project is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(1, 1, -GAP, -GAP)
        painter.setPen(QColor('#F0B7B7' if project.attention_count else BORDER))
        painter.setBrush(QColor('white'))
        painter.drawRoundedRect(rect, 6, 6)
        x, y, width = rect.x() + 16, rect.y() + 12, rect.width() - 32
        normal = QFont(option.font)
        title = QFont(normal)
        title.setBold(True)
        title.setPointSize(normal.pointSize() + 1)
        painter.setFont(normal)
        metrics = painter.fontMetrics()
        badge_width = min(width * .54, metrics.horizontalAdvance(project.state_text) + 18)
        badge_color = {'running': SUCCESS, 'queued': WARNING, 'unknown': WARNING}.get(project.state, MUTED)
        badge = QRectF(x + width - badge_width, y, badge_width, 23)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(badge_color))
        painter.drawRoundedRect(badge, 11, 11)
        painter.setPen(QColor('white'))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, project.state_text)
        painter.setFont(title)
        painter.setPen(QColor(TEXT))
        painter.drawText(QRectF(x, y, width - badge_width - 8, 25), Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(project.name, Qt.TextElideMode.ElideRight, int(width - badge_width - 8)))
        painter.setFont(normal)
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(x, y + 29, width, 23), Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(project.dut + '  |  ' + project.test_type, Qt.TextElideMode.ElideRight, int(width)))
        painter.setPen(QColor(TEXT))
        painter.setFont(title)
        progress = f'{project.progress}%' if project.progress is not None else '—'
        painter.drawText(QRectF(x, y + 58, 64, 26), Qt.AlignmentFlag.AlignVCenter, progress)
        painter.setFont(normal)
        painter.drawText(QRectF(x + 65, y + 58, width - 65, 26), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(project.progress_text, Qt.TextElideMode.ElideRight, int(width - 65)))
        bar = QRectF(x, y + 90, width, 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#E2E7EC'))
        painter.drawRoundedRect(bar, 4, 4)
        if project.progress is not None and project.progress > 0:
            painter.setBrush(QColor(BRAND))
            painter.drawRoundedRect(QRectF(x, bar.y(), width * min(100, max(0, project.progress)) / 100, 8), 4, 4)
        painter.setPen(QColor(TEXT))
        summary = project.channel_text + f'   ·   异常 {project.attention_count}'
        painter.drawText(QRectF(x, y + 107, width, 23), Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(summary, Qt.TextElideMode.ElideRight, int(width)))
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(x, y + 139, width - 75, 23), Qt.AlignmentFlag.AlignVCenter, project.elapsed)
        painter.setPen(QColor(BRAND))
        painter.drawText(QRectF(x + width - 75, y + 139, 75, 23), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, '查看详情  ›')
        painter.restore()


class CardList(QListView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWrapping(True)
        self.setUniformItemSizes(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setStyleSheet('QListView { border: none; background: transparent; }')
        self.setItemDelegate(ProjectCardDelegate(self))

    def reflow(self):
        width = max(1, self.viewport().width())
        count = self.model().rowCount() if self.model() is not None else 0
        if count > 1:
            # IconMode reserves room for a potential vertical scrollbar during
            # its wrapping pass, even when the final rows do not need one.
            width = max(1, width - self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent) - 2)
        columns = max(1, min(count or 1, 4, width // 310))
        size = QSize(max(1, width // columns - 1), 194)
        if size != self.gridSize():
            self.setGridSize(size)
            if count:
                self.itemDelegate().sizeHintChanged.emit(self.model().index(0, 0))
            self.doItemsLayout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()


class Dashboard(QWidget):
    project_requested = Signal(str)
    new_requested = Signal()
    open_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GAP)
        heading = QHBoxLayout()
        heading.addWidget(label('总览工作台', 'title'))
        heading.addStretch()
        self.cards_button = button('▦  卡片视图', lambda: self.set_mode(0))
        self.list_button = button('☷  列表视图', lambda: self.set_mode(1))
        for control in (self.cards_button, self.list_button):
            control.setCheckable(True)
            heading.addWidget(control)
        self.new_button = button('＋ 新建项目', self.new_requested.emit, 'primary')
        self.open_button = button('打开项目…', self.open_requested.emit)
        heading.addWidget(self.open_button)
        heading.addWidget(self.new_button)
        layout.addLayout(heading)
        self.metrics = QGridLayout()
        self.metric_cards, self.metric_numbers = [], []
        for title in ('已打开项目', '运行 / 恢复中', '需要关注', '结果未知 / 中断'):
            frame = card()
            column = QVBoxLayout(frame)
            column.setContentsMargins(16, 10, 16, 10)
            column.addWidget(label(title, 'muted'))
            number = label('0', 'metric')
            column.addWidget(number)
            self.metric_cards.append(frame)
            self.metric_numbers.append(number)
        layout.addLayout(self.metrics)
        filters = QHBoxLayout()
        filters.addWidget(label('▎ 项目运行情况', 'section'))
        filters.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索项目名称')
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(240)
        filters.addWidget(self.search)
        self.state_filter = QComboBox()
        for title, state in (('全部状态', ''), ('运行中', 'running'), ('等待中', 'queued'),
                              ('需关注', 'attention'), ('结果未知', 'unknown'), ('待接入', 'pending')):
            self.state_filter.addItem(title, state)
        filters.addWidget(self.state_filter)
        layout.addLayout(filters)
        self.model = ProjectTableModel(self)
        self.proxy = ProjectFilter(self)
        self.proxy.setSourceModel(self.model)
        self.views = QStackedWidget()
        self.cards = CardList()
        self.cards.setModel(self.proxy)
        self.cards.clicked.connect(self._selected)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.clicked.connect(self._selected)
        self.views.addWidget(self.cards)
        self.views.addWidget(self.table)
        layout.addWidget(self.views, 1)
        self.system_health = SystemHealthPanel(self)
        layout.addWidget(self.system_health)
        self.system_health.hide()
        self.search.textChanged.connect(self._filter)
        self.state_filter.currentIndexChanged.connect(self._filter)
        self.set_mode(0)

    def _selected(self, index):
        self.project_requested.emit(index.data(Qt.ItemDataRole.UserRole).project_id)

    def _filter(self):
        self.proxy.set_filter(self.search.text(), self.state_filter.currentData())
        self.cards.reflow()

    def set_mode(self, mode):
        assert_gui_thread()
        self.views.setCurrentIndex(mode)
        self.cards_button.setChecked(mode == 0)
        self.list_button.setChecked(mode == 1)
        self.cards.reflow()

    def set_projects(self, projects):
        assert_gui_thread()
        self.model.replace(projects)
        values = (len(projects), sum(p.active_task_count for p in projects),
                  sum(p.attention_count for p in projects), sum(p.state == 'unknown' for p in projects))
        for widget, value in zip(self.metric_numbers, values):
            widget.setText(str(value))
        self.metric_numbers[1].setStyleSheet(f'color: {SUCCESS}')
        self.metric_numbers[2].setStyleSheet(f'color: {DANGER}')
        self.cards.reflow()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        columns = 4 if self.width() >= 560 else 2
        for index, frame in enumerate(self.metric_cards):
            self.metrics.addWidget(frame, index // columns, index % columns)
        for index in range(4):
            self.metrics.setColumnStretch(index, int(index < columns))
