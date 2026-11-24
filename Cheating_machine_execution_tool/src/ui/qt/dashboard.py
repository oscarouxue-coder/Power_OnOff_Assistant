"""Responsive cards and a sortable table share one immutable project model."""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, QSize, Qt, QSortFilterProxyModel, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QBoxLayout, QComboBox, QGridLayout, QHBoxLayout,
    QHeaderView, QLineEdit, QListView, QStackedWidget, QStyle,
    QStyledItemDelegate, QTableView, QVBoxLayout, QWidget)

from src.models.workbench_presentation import matches_project_filter
from src.ui.qt.showcase_components import MetricCard, project_status_icon, project_status_style, semantic_icon, test_type_symbol
from src.ui.qt.theme import (BORDER, BRAND, CARD_PADDING, DANGER, GAP, MUTED, SUCCESS, TEXT,
    V13_PALETTE, assert_gui_thread, button, label)
from src.ui.qt.system_health_panel import SystemHealthPanel


PROJECT_METRICS = (
    ('', '已打开项目', '全部状态'),
    ('running', '运行中项目', '运行中'),
    ('queued', '等待中项目', '等待中'),
    ('completed', '最近任务已完成的项目', '最近任务已完成'),
    ('attention', '需关注项目', '需关注'),
    ('unknown', '状态待核实项目', '状态待核实'),
)
METRIC_CAPTIONS = ('已打开项目', '运行中', '等待中', '最近任务已完成', '需关注', '状态待核实')
METRIC_SYMBOLS = {'': 'projects', 'running': 'play', 'queued': 'clock', 'completed': 'check',
                 'attention': 'warning', 'unknown': 'question'}
WORKBENCH_CARD_HEIGHT = 148
_RUN_ROLE = Qt.ItemDataRole.UserRole + 2
_PRIORITY_ROLE = Qt.ItemDataRole.UserRole + 3


def elapsed_seconds(value):
    parts = value.split(':')
    return sum(int(n) * factor for n, factor in zip(parts, (3600, 60, 1))) if len(parts) == 3 and all(n.isdigit() for n in parts) else -1


@dataclass(frozen=True)
class RunDisplay:
    elapsed: str
    seconds: int
    headline: str
    detail: str
    latest: str
    progress: Optional[int]
    aging: bool

    @property
    def table_detail(self):
        if self.aging:
            return '\n'.join(filter(None, (self.detail, self.latest)))
        percent = f'{self.progress}%' if self.progress is not None else ''
        headline = ' · '.join(filter(None, (percent, self.headline)))
        return '\n'.join(filter(None, (headline, self.detail)))


def _run_display(project):
    if project.project_type != 'service_aging' and project.test_type != '全业务老化':
        progress = None if matches_project_filter(project, 'idle') else project.progress
        return RunDisplay(project.elapsed, elapsed_seconds(project.elapsed), project.progress_text,
                          project.task_stage, '', progress, False)

    observations = project.test_overview or {}
    samples = [row for row in observations.get('rows', ()) if row.get('source') in ('manual', 'icmp', 'jsonl')]
    counts = Counter(row.get('state') for row in samples)
    detail = '暂无业务观测'
    if samples:
        healthy, abnormal = counts['healthy'], counts['abnormal']
        detail = f'健康 {healthy} · 异常 {abnormal} · 未知 {len(samples) - healthy - abnormal}'
    latest = ''
    observed = (row.get('last_observation') for row in samples)
    stamp = max((value for value in observed if type(value) in (int, float) and 0 <= value < 1e12), default=None)
    if stamp is not None:
        try:
            latest = '最近检测 ' + datetime.fromtimestamp(stamp).strftime('%m-%d %H:%M:%S')
        except (ValueError, OSError, OverflowError):
            pass
    duration = observations.get('elapsed_seconds')
    if type(duration) not in (int, float) or not 0 <= duration < 1e12:
        return RunDisplay('—', -1, '监测时长未知', detail, latest, None, True)
    seconds = int(duration)
    days, tail = divmod(seconds, 86400)
    hours, tail = divmod(tail, 3600)
    minutes, tail = divmod(tail, 60)
    elapsed = (f'{days} 天 ' if days else '') + f'{hours:02d}:{minutes:02d}:{tail:02d}'
    return RunDisplay(elapsed, seconds, '监测时长 ' + elapsed, detail, latest, None, True)


def _project_priority(project):
    return next((rank for rank, key in enumerate(('running', 'attention', 'active'))
                 if matches_project_filter(project, key)), 3)


class ProjectTableModel(QAbstractTableModel):
    HEADERS = ('项目名称', '测试类型', '任务状态', '运行时间', '进度 / 数据来源', '异常', '成功', '失败')

    def __init__(self, parent=None, *, refreshed=False):
        super().__init__(parent)
        self.refreshed = refreshed
        self.projects = ()
        self.runs = ()

    def replace(self, projects):
        assert_gui_thread()
        # The workspace identifies projects by UUID, including after a rename.
        projects = tuple({p.project_id: p for p in projects}.values())
        if projects == self.projects:
            return
        runs = tuple(map(_run_display, projects)) if self.refreshed else ()
        if tuple(p.project_id for p in projects) == tuple(p.project_id for p in self.projects):
            self.projects = projects
            self.runs = runs
            if projects:
                self.dataChanged.emit(self.index(0, 0), self.index(len(projects) - 1, len(self.HEADERS) - 1), [])
            return
        self.beginResetModel()
        self.projects = projects
        self.runs = runs
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.projects)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.projects):
            return None
        project = self.projects[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return project
        if role == _PRIORITY_ROLE:
            return _project_priority(project) * len(self.projects) + index.row()
        run = self.runs[index.row()] if self.refreshed else None
        if role == _RUN_ROLE:
            return run
        values = (project.name, project.test_type, project.state_text, run.elapsed if run else project.elapsed,
                   run.table_detail if run else project.progress_text, project.attention_text,
                   project.success_text, project.failure_text)
        if role == Qt.ItemDataRole.DecorationRole and index.column() == 2:
            return project_status_icon(project.state)
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == 0:
            parts = [project.name, project.state_text, project.channel_text,
                     f'成功 {project.success_text} · 失败 {project.failure_text} · 异常 {project.attention_text}']
            if run:
                parts.extend((run.headline, run.detail, run.latest))
            return '\n'.join(filter(None, parts))
        if role == Qt.ItemDataRole.AccessibleDescriptionRole and index.column() == 0:
            return '\n'.join(filter(None, (project.state_text, run.table_detail))) if run else project.state_text
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return values[index.column()]
        if role == Qt.ItemDataRole.UserRole + 1:
            if index.column() == 5:
                return project.attention_count
            if index.column() in (6, 7):
                count = project.success_count if index.column() == 6 else project.failure_count
                return -1 if count is None else count
            if index.column() == 3:
                return run.seconds if run else elapsed_seconds(project.elapsed)
            if index.column() == 4:
                return project.progress_text
            return values[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 5 and project.attention_count:
            return QColor(DANGER)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if self.refreshed and section == 4:
                return '进展 / 业务观测'
            return self.HEADERS[section]
        return None


class ProjectFilter(QSortFilterProxyModel):
    def __init__(self, parent=None, *, prioritize=False):
        super().__init__(parent)
        self.keyword, self.state = '', ''
        self.prioritize = prioritize
        self.setSortRole(Qt.ItemDataRole.UserRole + 1)

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        natural = self.prioritize and column == -1
        self.setSortRole(_PRIORITY_ROLE if natural else Qt.ItemDataRole.UserRole + 1)
        super().sort(0 if natural else column, Qt.SortOrder.AscendingOrder if natural else order)

    def filterAcceptsRow(self, row, parent):
        project = self.sourceModel().projects[row]
        return self.keyword in project.name.casefold() and matches_project_filter(project, self.state)

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
        if option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_HasFocus):
            painter.setPen(QPen(QColor(V13_PALETTE.brand), 2))
        else:
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
        style = project_status_style(project.state)
        icon_size, padding, spacing = 16, 7, 4
        badge_width = min(width * .54, metrics.horizontalAdvance(project.state_text) + icon_size + spacing + 2 * padding)
        badge = QRectF(x + width - badge_width, y, badge_width, 23)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(style.background))
        painter.drawRoundedRect(badge, 11, 11)
        icon_rect = QRectF(badge.x() + padding, badge.center().y() - icon_size / 2, icon_size, icon_size)
        project_status_icon(project.state).paint(painter, icon_rect.toRect())
        caption = badge.adjusted(padding + icon_size + spacing, 0, -padding, 0)
        painter.setPen(QColor(style.ink))
        painter.drawText(caption, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         metrics.elidedText(project.state_text, Qt.TextElideMode.ElideRight, max(0, int(caption.width()))))
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
        painter.drawText(QRectF(x, y + 102, width, 21), Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(project.channel_text, Qt.TextElideMode.ElideRight, int(width)))
        summary = f'成功 {project.success_text} · 失败 {project.failure_text} · 异常 {project.attention_text}'
        painter.drawText(QRectF(x, y + 123, width, 21), Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(summary, Qt.TextElideMode.ElideRight, int(width)))
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(x, y + 146, width - 75, 21), Qt.AlignmentFlag.AlignVCenter, project.elapsed)
        painter.setPen(QColor(BRAND))
        painter.drawText(QRectF(x + width - 75, y + 146, 75, 21), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, '查看详情  ›')
        painter.restore()


class WorkbenchCardDelegate(ProjectCardDelegate):
    """Show project identity, then the reported run data for its test type."""

    def sizeHint(self, option, index):
        return QSize(max(1, self.parent().gridSize().width()), WORKBENCH_CARD_HEIGHT)

    def paint(self, painter, option, index):
        project = index.data(Qt.ItemDataRole.UserRole)
        if project is None:
            return
        run = index.data(_RUN_ROLE)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QRectF(option.rect).adjusted(1, 1, -9, -9)
        focus = option.state & (QStyle.StateFlag.State_HasFocus | QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        outline = V13_PALETTE.border
        if project.attention_count:
            outline = '#EAB2B2'
        elif matches_project_filter(project, 'running'):
            outline = '#A7CCC8'
        if focus or hover:
            outline = V13_PALETTE.brand if focus else '#A7CCC8'
        painter.setPen(QPen(QColor(outline), 2 if focus else 1))
        painter.setBrush(QColor(V13_PALETTE.surface))
        painter.drawRoundedRect(frame, 9, 9)
        x, y, width = frame.x() + 13, frame.y() + 10, frame.width() - 26
        if width <= 0:
            painter.restore()
            return
        normal = QFont(option.font)
        bold = QFont(normal)
        bold.setBold(True)
        title = QFont(bold)
        title.setPointSizeF(max(9.0, normal.pointSizeF() + 1))

        def line(text, left, top, span, ink=V13_PALETTE.text, font=normal, *, right=False):
            if span <= 0:
                return
            painter.setFont(font)
            painter.setPen(QColor(ink))
            caption = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(span))
            anchor = Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft
            painter.drawText(QRectF(left, top, span, 20), Qt.AlignmentFlag.AlignVCenter | anchor, caption)

        style = project_status_style(project.state)
        painter.setFont(normal)
        badge_width = min(width * .52, painter.fontMetrics().horizontalAdvance(project.state_text) + 29)
        badge_x = x + width - badge_width
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(style.background))
        painter.drawRoundedRect(QRectF(badge_x, y + 22, badge_width, 21), 6, 6)
        project_status_icon(project.state).paint(painter, QRectF(badge_x + 5, y + 25, 14, 14).toRect())
        line(project.state_text, badge_x + 22, y + 23, badge_width - 26, style.ink)
        line(project.name, x, y, width, font=title)
        metadata = ' · '.join(filter(None, (project.test_type, project.dut if project.dut != '—' else '')))
        meta_width = width - badge_width - 8
        symbol = test_type_symbol(project.project_type, project.test_type)
        inset = 0
        if symbol and meta_width >= 36:
            semantic_icon(symbol, V13_PALETTE.muted).paint(painter, QRectF(x, y + 25, 16, 16).toRect())
            inset = 20
        line(metadata, x + inset, y + 23, meta_width - inset, V13_PALETTE.muted)

        alert_ink = V13_PALETTE.error.text if project.attention_count else V13_PALETTE.muted
        if run.aging:
            line(run.headline, x, y + 46, width, font=bold)
            line(run.detail, x, y + 70, width, alert_ink)
            footer = run.latest or project.channel_text
        else:
            percent_width = 43 if run.progress is not None else 0
            line(run.headline or project.channel_text, x, y + 46, width - percent_width, font=bold)
            if run.progress is not None:
                line(f'{run.progress}%', x + width - percent_width, y + 46, percent_width,
                     V13_PALETTE.brand, bold, right=True)
                track = QRectF(x, y + 68, width, 4)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor('#E2ECEE'))
                painter.drawRoundedRect(track, 2, 2)
                if run.progress > 0:
                    painter.setBrush(QColor(V13_PALETTE.brand))
                    painter.drawRoundedRect(QRectF(x, track.y(), width * min(run.progress, 100) / 100, 4), 2, 2)
            secondary = run.detail or project.channel_text
            if run.elapsed not in ('', '—') and not run.detail:
                secondary = ' · '.join(filter(None, (secondary, run.elapsed)))
            line(secondary, x, y + (76 if run.progress is not None else 69), width, alert_ink)
            footer = ' · '.join(f'{label} {value}' for label, value in (
                ('成功', project.success_text), ('失败', project.failure_text), ('异常', project.attention_text))
                if value != '—')
            if not footer and run.detail and run.elapsed != '—':
                footer = run.elapsed
        link_width = 77
        line(footer, x, y + 101, width - link_width, alert_ink)
        line('查看详情 ›', x + width - link_width, y + 101, link_width, V13_PALETTE.brand, bold, right=True)
        painter.restore()


class CardList(QListView):
    def __init__(self, parent=None, *, refreshed=False):
        super().__init__(parent)
        self.refreshed = refreshed
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWrapping(True)
        self.setUniformItemSizes(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setStyleSheet('QListView { border: none; background: transparent; }')
        self.setItemDelegate(WorkbenchCardDelegate(self) if refreshed else ProjectCardDelegate(self))
        self.setMouseTracking(refreshed)

    def reflow(self):
        width = max(1, self.viewport().width())
        count = self.model().rowCount() if self.model() is not None else 0
        if count > 1:
            # IconMode reserves room for a potential vertical scrollbar during
            # its wrapping pass, even when the final rows do not need one.
            width = max(1, width - self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent) - 2)
        minimum = 270 if self.refreshed else 310
        columns = max(1, min(count or 1, 4, width // minimum))
        size = QSize(max(1, width // columns - 1), WORKBENCH_CARD_HEIGHT if self.refreshed else 194)
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

    def __init__(self, parent=None, *, refreshed=False):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9 if refreshed else GAP)
        heading = QHBoxLayout()
        heading.addWidget(label('总览工作台', 'title'))
        heading.addStretch()
        self.cards_button = button('▦  卡片视图', lambda: self.set_mode(0))
        self.list_button = button('☷  列表视图', lambda: self.set_mode(1))
        if refreshed:
            for control, text, symbol in ((self.cards_button, '卡片视图', 'grid'),
                                          (self.list_button, '列表视图', 'queue')):
                control.setText(text)
                control.setAccessibleName(text)
                control.setIcon(semantic_icon(symbol))
        for control in (self.cards_button, self.list_button):
            control.setCheckable(True)
            control.setProperty('viewMode', refreshed)
            heading.addWidget(control)
        self.new_button = button('＋ 新建项目', self.new_requested.emit, 'primary')
        self.open_button = button('打开项目…', self.open_requested.emit)
        heading.addWidget(self.open_button)
        heading.addWidget(self.new_button)
        layout.addLayout(heading)
        self.metrics = QGridLayout()
        if refreshed:
            self.metrics.setSpacing(8)
        self.metric_cards, self.metric_numbers = [], []
        self._metric_columns = 0
        for (key, title, _), caption in zip(PROJECT_METRICS, METRIC_CAPTIONS):
            frame = MetricCard(caption if refreshed else title, 0, self,
                               symbol=METRIC_SYMBOLS[key] if refreshed else None)
            frame.setToolTip(title)
            # These summary tiles share the vertical splitter with live logs
            # and the expanded health panel. Reserve room for the project row.
            frame.layout().setContentsMargins(CARD_PADDING, CARD_PADDING // 2,
                                              CARD_PADDING, CARD_PADDING // 2)
            number = frame.value_label
            number.setAccessibleName(title)
            if key == 'running':
                number.setStyleSheet(f'color: {SUCCESS}')
            elif key == 'attention':
                number.setStyleSheet(f'color: {DANGER}')
            self.metric_cards.append(frame)
            self.metric_numbers.append(number)
        if refreshed:
            self.set_compact_metrics(False)
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
        for key, _, title in PROJECT_METRICS:
            self.state_filter.addItem(title, key)
        for key, title in (('active', '有活动任务'), ('stopping', '停止中'), ('unchecked', '含未校验'),
                           ('failed', '失败'), ('stopped', '已停止'), ('idle', '空闲'), ('pending', '待接入')):
            self.state_filter.addItem(title, key)
        filters.addWidget(self.state_filter)
        layout.addLayout(filters)
        self.model = ProjectTableModel(self, refreshed=refreshed)
        self.proxy = ProjectFilter(self, prioritize=refreshed)
        self.proxy.setSourceModel(self.model)
        self.views = QStackedWidget()
        self.cards = CardList(refreshed=refreshed)
        self.cards.setModel(self.proxy)
        self.cards.clicked.connect(self._selected)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for column in (5, 6, 7):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().hide()
        self.table.clicked.connect(self._selected)
        if refreshed:
            self.cards.activated.connect(self._activate_from_keyboard)
            self.table.activated.connect(self._activate_from_keyboard)
            self.table.setAlternatingRowColors(True)
            for column in (1, 2, 3):
                self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
            self.table.verticalHeader().setDefaultSectionSize(38)
        self.views.addWidget(self.cards)
        self.views.addWidget(self.table)
        layout.addWidget(self.views, 1)
        self.system_health = SystemHealthPanel(self, compact_summary=refreshed)
        layout.addWidget(self.system_health)
        self.system_health.hide()
        self.search.textChanged.connect(self._filter)
        self.state_filter.currentIndexChanged.connect(self._filter)
        self.set_mode(0)

    def _selected(self, index):
        self.project_requested.emit(index.data(Qt.ItemDataRole.UserRole).project_id)

    def _activate_from_keyboard(self, index):
        if not QApplication.mouseButtons():
            self._selected(index)

    def set_compact_metrics(self, compact):
        direction = QBoxLayout.Direction.LeftToRight if compact else QBoxLayout.Direction.TopToBottom
        margins = (10, 3, 10, 3) if compact else (12, 5, 12, 5)
        for metric in self.metric_cards:
            layout = metric.layout()
            layout.setDirection(direction)
            layout.setSpacing(8 if compact else 2)
            layout.setContentsMargins(*margins)
            metric.ensurePolished()
            metric.setMinimumHeight(metric.sizeHint().height())

    def _filter(self):
        self.proxy.set_filter(self.search.text(), self.state_filter.currentData())
        self.cards.reflow()

    def show_active_projects(self):
        self.search.clear()
        self.state_filter.setCurrentIndex(self.state_filter.findData('active'))

    def clear_project_filter(self):
        self.search.clear()
        self.state_filter.setCurrentIndex(self.state_filter.findData(''))

    def set_mode(self, mode):
        assert_gui_thread()
        self.views.setCurrentIndex(mode)
        self.cards_button.setChecked(mode == 0)
        self.list_button.setChecked(mode == 1)
        self.cards.reflow()

    def set_projects(self, projects):
        assert_gui_thread()
        self.model.replace(projects)
        for (key, _, _), frame in zip(PROJECT_METRICS, self.metric_cards):
            count = sum(matches_project_filter(project, key) for project in self.model.projects)
            frame.set_value(count)
        self.cards.reflow()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep long Chinese headings readable as the sidebar or DPI changes.
        card_width = max(frame.sizeHint().width() for frame in self.metric_cards)
        gap = self.metrics.horizontalSpacing()
        columns = next(n for n in (6, 3, 2, 1)
                       if n == 1 or n * card_width + (n - 1) * gap <= self.contentsRect().width())
        if columns == self._metric_columns:
            return
        self._metric_columns = columns
        for index, frame in enumerate(self.metric_cards):
            self.metrics.addWidget(frame, index // columns, index % columns)
        for index in range(len(self.metric_cards)):
            self.metrics.setColumnStretch(index, int(index < columns))
