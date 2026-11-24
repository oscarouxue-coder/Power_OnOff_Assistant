"""Project presentation: run metrics, channels and configuration."""
from collections import Counter
from functools import partial

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (QBoxLayout, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout,
    QAbstractItemView, QHeaderView, QHBoxLayout, QMenu, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QStackedWidget, QTabBar, QTableView, QVBoxLayout, QWidget)
from src.ui.qt.channel_table_model import ChannelTableModel
from src.ui.qt.power_metric_detail import POWER_METRIC_LABELS, PowerMetricDetailDialog
from src.ui.qt.test_type_panel import TestTypePanel, history_datetime
from src.ui.qt.aging_inspection_preview import AgingInspectionEntry
from src.ui.qt.showcase_components import MetricCard, STATUS_STYLES, StatusBadge, SymbolView, semantic_icon, test_type_symbol
from src.ui.qt.theme import (BRAND, GAP, MUTED, V13_PALETTE, assert_gui_thread, button, card, label)


class ChannelMatrix(QWidget):
    selected = Signal(int)
    context_requested = Signal(int, object)
    layout_changed = Signal()

    def __init__(self, parent=None, *, refreshed=False):
        super().__init__(parent)
        self._refreshed = refreshed
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        self._columns = 0
        self.tiles = []
        self.channels = ()

    def set_channels(self, channels):
        assert_gui_thread()
        if tuple(channels) == self.channels:
            return
        self.channels = tuple(channels)
        for tile in self.tiles:
            self.grid.removeWidget(tile)
            tile.hide()
            tile.deleteLater()
        self.tiles.clear()
        self._columns = 0
        states = {'running': '● 运行中', 'success': '✓ 正常', 'failed': '异常',
                  'unknown': '未知', 'disabled': '未启用', 'stopped': '已停止', 'retry': '重试中'}
        for channel in self.channels:
            state = states.get(channel.state, '未知')
            text = f'CH{channel.number:02d}   {state}'
            if channel.cycle is not None:
                text += f'\n已完成 {channel.cycle} 轮'
            tile = button(text, lambda checked=False, number=channel.number: self.selected.emit(number), parent=self)
            tile.setProperty('channelTile', True)
            tile.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            tooltip = f'CH{channel.number:02d} · {state}\n{channel.vlan or "未配置 VLAN"} / {channel.port or "未配置 COM"}'
            if channel.stage:
                tooltip += '\n最近上报阶段：' + channel.stage
            if channel.can_resume:
                tooltip += '\n右键可从失败轮次继续'
            tile.setToolTip(tooltip)
            tile.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tile.customContextMenuRequested.connect(lambda point, n=channel.number, control=tile:
                self.context_requested.emit(n, control.mapToGlobal(point)))
            if self._refreshed:
                self._style_tile(tile, channel, state)
            elif channel.state in ('running', 'success'):
                tile.setStyleSheet('QPushButton { background: #E9F9EF; color: #166534; border: 1px solid #9CD7AC; }')
            elif channel.state == 'failed':
                tile.setStyleSheet('QPushButton { background: #FEF2F2; color: #DC2626; border: 1px solid #F2BABA; }')
            elif channel.state == 'retry':
                tile.setStyleSheet('QPushButton { background: #FFFBEB; color: #D97706; border: 1px solid #F4D9A6; }')
            else:
                tile.setStyleSheet('QPushButton { background: #F0F3F6; color: #6B7280; border: 1px solid #E5E7EB; }')
            metrics = tile.fontMetrics()
            binding = ' / '.join(
                metrics.elidedText(value, Qt.TextElideMode.ElideRight, width)
                for value, width in ((channel.vlan, 115), (channel.port, 80)) if value)
            if binding:
                tile.setText(tile.text() + '\n' + binding.replace('&', '&&'))
            tile.setMinimumHeight(max(44, tile.sizeHint().height()))
            self.tiles.append(tile)
        self.reflow()

    @staticmethod
    def _style_tile(tile, channel, caption):
        statuses = {'running': 'running', 'success': 'healthy', 'failed': 'error', 'retry': 'warning',
                    'stopped': 'stopped', 'unknown': 'unknown', 'disabled': 'unavailable'}
        status = STATUS_STYLES[statuses.get(channel.state, 'unknown')]
        selected_unknown = channel.selected and channel.state == 'unknown'
        background = V13_PALETTE.selected_background if selected_unknown else status.background
        ink = V13_PALETTE.selected if selected_unknown else status.ink
        hover_border = V13_PALETTE.brand if selected_unknown else status.color
        selection_edge = f'border-left: 3px solid {V13_PALETTE.brand};' if channel.selected else ''
        text = f'CH{channel.number:02d}  {caption.lstrip("●✓ ")}'
        if channel.selected:
            text += '\n已选'
        cycle = f'已完成 {channel.cycle} 轮' if channel.cycle is not None else ''
        stage = tile.fontMetrics().elidedText(channel.stage, Qt.TextElideMode.ElideRight, 115)
        description = ' · '.join(filter(None, (cycle, stage)))
        if description:
            text += '\n' + description
        tile.setText(text)
        tile.setIcon(semantic_icon(status.icon, status.color))
        tile.setAccessibleDescription(tile.toolTip())
        tile.setStyleSheet(f'''
            QPushButton {{ background: {background}; color: {ink};
                           border: 1px solid {V13_PALETTE.border}; border-radius: 6px;
                           text-align: left; padding: 5px 8px; {selection_edge} }}
            QPushButton:hover {{ border-color: {hover_border}; {selection_edge} }}
            QPushButton:focus {{ border: 2px solid {V13_PALETTE.info}; {selection_edge} }}
        ''')

    def reflow(self):
        minimum = max(88, max((tile.sizeHint().width() for tile in self.tiles), default=0))
        spacing = self.grid.spacing()
        columns = max(1, min(8, (self.width() + spacing) // (minimum + spacing)))
        if columns == self._columns:
            return
        self._columns = columns
        for index, tile in enumerate(self.tiles):
            self.grid.addWidget(tile, index // columns, index % columns)
        for index in range(8):
            self.grid.setColumnStretch(index, int(index < columns))
        self.grid.activate()
        self.layout_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()


class ChannelViewStack(QStackedWidget):
    """Hidden table dimensions must not enlarge the compact channel matrix."""

    def update_current_geometry(self):
        self.setMinimumHeight(self.minimumSizeHint().height())
        self.updateGeometry()

    def sizeHint(self):
        widget = self.currentWidget()
        return widget.sizeHint() if widget is not None else super().sizeHint()

    def minimumSizeHint(self):
        widget = self.currentWidget()
        return widget.minimumSizeHint().expandedTo(widget.minimumSize()) if widget is not None else super().minimumSizeHint()


class OverviewMetricButton(QPushButton):
    def __init__(self, title, parent):
        super().__init__(parent)
        self.setProperty('overviewMetric', True)
        self.setToolTip(f'查看{title}详情')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        column = QVBoxLayout(self)
        caption = label(title, 'muted', self)
        self.value_label = label('—', 'section', self)
        for widget in (caption, self.value_label):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            column.addWidget(widget)

    def set_value(self, value):
        self.value_label.setText(str(value))
        self.setAccessibleDescription(f'{value} · 点击查看详情')

    def sizeHint(self):
        return self.layout().sizeHint()

    def minimumSizeHint(self):
        return self.layout().minimumSize()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not event.isAutoRepeat():
                self.click()
            event.accept()
            return
        super().keyPressEvent(event)


class OverviewMetrics(QWidget):
    """Arrange the same metric cards in fewer columns when the split pane narrows."""

    def __init__(self, titles, actions=None):
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)
        actions = actions or {}
        cards = []
        for index, title in enumerate(titles):
            action = actions.get(index)
            if action is None:
                frame = MetricCard(title, '—', self)
            else:
                frame = OverviewMetricButton(title, self)
                frame.clicked.connect(action)
            cards.append(frame)
        self.cards = tuple(cards)
        self.columns = 0
        for frame, title in zip(self.cards, titles):
            frame.setAccessibleName(title)
            frame.layout().setContentsMargins(10, 6, 10, 7)
            frame.layout().setSpacing(2)
            frame.value_label.setProperty('role', 'section')
            frame.value_label.setWordWrap(True)
        self._reflow()

    def set_values(self, values, accents=None):
        accents = accents or {}
        for index, (frame, value) in enumerate(zip(self.cards, values)):
            frame.set_value(value)
            color = accents.get(index, V13_PALETTE.muted if value == '—' else V13_PALETTE.text)
            style = f'font-size: 17px; font-weight: 700; color: {color};'
            if frame.value_label.styleSheet() != style:
                frame.value_label.setStyleSheet(style)

    def _reflow(self):
        count = len(self.cards)
        columns = next(size for size in (count, count // 2, 2, 1)
                       if size == 1 or size * 128 + (size - 1) * self.grid.spacing() <= self.width())
        if columns == self.columns:
            return
        self.columns = columns
        for index, frame in enumerate(self.cards):
            self.grid.addWidget(frame, index // columns, index % columns)
        for index in range(count):
            self.grid.setColumnStretch(index, int(index < columns))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()


class ProjectDetail(QWidget):
    back_requested = Signal()
    configuration_requested = Signal()
    channels_configuration_requested = Signal()
    single_power_requested = Signal()
    serial_requested = Signal()
    dut_requested = Signal()
    upgrade_requested = Signal()
    parameter_requested = Signal()
    onu_requested = Signal()
    model_settings_requested = Signal()
    ai_chat_requested = Signal()
    resume_requested = Signal(str, int)
    power_log_requested = Signal(str, int, str)
    channel_history_requested = Signal(str, str, int)
    metric_detail_opened = Signal(object, str, bool)

    def __init__(self, parent=None, *, refreshed=False):
        super().__init__(parent)
        self._refreshed = refreshed
        self.project = None
        self._configuration_snapshot = None
        self.dialogs = []
        self._metric_dialog = None
        self._narrow = False
        self._user_config_visibility = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        breadcrumb = QHBoxLayout()
        breadcrumb.addWidget(button('‹  返回总览', self.back_requested.emit, 'link'))
        breadcrumb.addWidget(label('项目详情', 'muted'))
        breadcrumb.addStretch()
        self.inspection_entry = AgingInspectionEntry(self)
        breadcrumb.addWidget(self.inspection_entry)
        self.config_toggle = button('收起配置', self.toggle_configuration)
        breadcrumb.addWidget(self.config_toggle)
        layout.addLayout(breadcrumb)
        header = card()
        self.header_layout = QHBoxLayout(header)
        self.header_layout.setContentsMargins(16, 10, 16, 10)
        identity = QHBoxLayout()
        self.header_layout.addLayout(identity, 1)
        if refreshed:
            self.type_symbol = SymbolView(self, 24)
            identity.addWidget(self.type_symbol)
        else:
            icon = label('▱')
            icon.setStyleSheet(f'background: {BRAND}; color: white; padding: 8px; border-radius: 5px; font-size: 22px;')
            identity.addWidget(icon)
        heading = QVBoxLayout()
        self.name = label('', 'title')
        self.name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.metadata = label('', 'muted')
        self.metadata.setWordWrap(True)
        heading.addWidget(self.name)
        heading.addWidget(self.metadata)
        identity.addLayout(heading, 1)
        self.state = StatusBadge()
        identity.addWidget(self.state)
        actions = QHBoxLayout()
        actions.addStretch()
        self.header_layout.addLayout(actions)
        self.start_button = button('▷ 开始测试', kind='primary')
        self.stop_button = button('■ 停止测试', kind='danger')
        if refreshed:
            self.start_button.setIcon(semantic_icon('play', V13_PALETTE.surface, on_dark=True))
            self.stop_button.setIcon(semantic_icon('stop', V13_PALETTE.error.text))
        self.environment_button = button('环境检查')
        self.pipeline_button = button('全流程…')
        for control in (self.pipeline_button, self.environment_button, self.start_button, self.stop_button):
            control.setEnabled(False)
            control.setToolTip('迁移原型：尚未接入真实任务控制，不发送设备命令')
            actions.addWidget(control)
        layout.addWidget(header)
        self.tabs = QTabBar()
        self.tabs.setObjectName('ProjectModuleTabs')
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(True)
        for index, name in enumerate(('运行概览', '自动上/下电', '样机升级', '写样机参数', 'ONU注册', '串口日志', 'DUT配置', 'AI 模型连接', 'Ai助手')):
            self.tabs.addTab(name)
            if index > 0:
                self.tabs.setTabEnabled(index, False)
                self.tabs.setTabToolTip(index, '原Tk功能保留，此Qt页面尚未迁移')
        layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(self._module_clicked)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.execution_scroll = QScrollArea()
        self.execution_scroll.setWidgetResizable(True)
        self.execution_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.execution = QWidget()
        self.execution.setMinimumWidth(0)
        if refreshed:
            self.execution.setProperty('executionPage', True)
            self.execution.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.execution_layout = QVBoxLayout(self.execution)
        self.execution_layout.setContentsMargins(0, 0, 2, 0)
        self.execution_layout.setSpacing(GAP)
        self.test_type_panel = TestTypePanel(refreshed=refreshed)
        self.test_type_panel.hide()
        if refreshed:
            metric_actions = {index: partial(self._open_metric_detail, metric)
                              for index, metric in enumerate(POWER_METRIC_LABELS, start=1)}
            self.cycle_metrics = OverviewMetrics(('运行时长', *POWER_METRIC_LABELS.values()), metric_actions)
            self.aging_metrics = OverviewMetrics(('监测时长', '已接入业务项', '健康', '异常', '状态未知', '最近业务检测'))
            self.execution_layout.addWidget(self.cycle_metrics)
            self.execution_layout.addWidget(self.aging_metrics)
            self.aging_metrics.hide()
        else:
            self.execution_layout.addWidget(self.test_type_panel)
        self.summary = card()
        summary_layout = QVBoxLayout(self.summary)
        summary_layout.setContentsMargins(16, 10, 16, 12)
        status_row = QHBoxLayout()
        if refreshed:
            self.test_type_panel.ring.hide()
            status_row.addWidget(self.test_type_panel.ring)
        self.percent = label('—', 'metric')
        status_row.addWidget(self.percent)
        status_row.addSpacing(16)
        self.progress_text = label('', 'section')
        status_row.addWidget(self.progress_text, 1)
        self.run_id = label('', 'muted')
        if refreshed:
            self.progress_text.setWordWrap(True)
            status_row.addWidget(self.run_id)
        else:
            self.elapsed = label('')
            status_row.addWidget(self.elapsed)
        summary_layout.addLayout(status_row)
        self.progress = QProgressBar()
        if refreshed:
            self.progress.setAccessibleName('已完成开关机轮次进度')
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        summary_layout.addWidget(self.progress)
        if not refreshed:
            counts = QHBoxLayout()
            self.success = label('')
            self.failure = label('')
            counts.addWidget(self.success)
            counts.addSpacing(30)
            counts.addWidget(self.failure)
            counts.addStretch()
            counts.addWidget(self.run_id)
            summary_layout.addLayout(counts)
        self.stage = label('', 'section' if refreshed else 'muted')
        self.stage.setWordWrap(True)
        summary_layout.addWidget(self.stage)
        self.execution_layout.addWidget(self.summary)
        self.channel_card = card()
        channels_layout = QVBoxLayout(self.channel_card)
        channels_layout.setContentsMargins(12, 10, 12, 12)
        self.channel_title = label('通道运行状态', 'section')
        self.channel_title.setWordWrap(True)
        self.channel_title.setMinimumWidth(0)
        self.channel_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        controls = QHBoxLayout()
        controls.addWidget(self.channel_title, 1)
        self.channel_edit_button = button('环境配置', self.channels_configuration_requested.emit)
        self.channel_edit_button.setEnabled(False)
        self.matrix_button = button('矩阵', lambda: self.set_channel_mode(0))
        self.table_button = button('列表', lambda: self.set_channel_mode(1))
        for control in (self.channel_edit_button, self.matrix_button, self.table_button):
            controls.addWidget(control)
        self.matrix_button.setCheckable(True)
        self.table_button.setCheckable(True)
        for option in (self.matrix_button, self.table_button):
            option.setProperty('viewMode', refreshed)
        self.matrix_button.setChecked(True)
        channels_layout.addLayout(controls)
        self.no_channels = label('暂无已启用通道', 'muted')
        channels_layout.addWidget(self.no_channels)
        self.channels = ChannelMatrix(refreshed=refreshed)
        self.channels.selected.connect(self.open_channel)
        self.channels.context_requested.connect(self.channel_context_menu)
        self.recovery_menu = QMenu(self)
        self.recovery_action = self.recovery_menu.addAction('重新开始（从失败轮次继续）', self._resume_menu_selected)
        self.recovery_menu.addSeparator()
        self.channel_history_action = self.recovery_menu.addAction('查看本次重试/失败历史…', self._channel_history_menu_selected)
        self.power_log_actions = {
            kind: self.recovery_menu.addAction(title, partial(self._power_log_menu_selected, kind))
            for kind, title in (('power', '打开开关机运行日志'), ('wifi', '打开本次 WiFi 连接日志'))
        }
        for action in self.power_log_actions.values():
            action.setEnabled(False)
        self.channel_modes = ChannelViewStack()
        self.channel_modes.addWidget(self.channels)
        self.channels.layout_changed.connect(self.channel_modes.update_current_geometry)
        self.channel_table = QTableView()
        if refreshed:
            self.channel_table.setAlternatingRowColors(True)
            self.channel_table.verticalHeader().setDefaultSectionSize(26)
        self.channel_table.setMinimumHeight(140)
        self.channel_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.channel_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.channel_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.channel_table.verticalHeader().hide()
        self.channel_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.channel_model = ChannelTableModel(self.channel_table)
        self.channel_table.setModel(self.channel_model)
        self.channel_table.doubleClicked.connect(lambda index: self.open_channel(index.data(Qt.ItemDataRole.UserRole)))
        self.channel_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.channel_table.customContextMenuRequested.connect(self._table_channel_menu)
        self.channel_modes.addWidget(self.channel_table)
        channels_layout.addWidget(self.channel_modes)
        self.execution_layout.addWidget(self.channel_card)
        if refreshed:
            self.aging_status = QWidget()
            self.aging_status.hide()
            self.aging_status_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.aging_status)
            self.aging_status_layout.setContentsMargins(0, 0, 0, 0)
            self.aging_status_layout.setSpacing(8)
            aging_health = card()
            health_layout = QVBoxLayout(aging_health)
            health_layout.setContentsMargins(12, 8, 12, 9)
            health_heading = QHBoxLayout()
            health_heading.addWidget(label('业务健康', 'section'), 1)
            self.aging_trend = label('暂无业务健康趋势数据', 'muted')
            self.aging_trend.setWordWrap(True)
            health_heading.addWidget(self.aging_trend)
            health_layout.addLayout(health_heading)
            health_layout.addWidget(self.test_type_panel.health_cards)
            self.aging_empty = label('暂无业务检查数据', 'muted')
            health_layout.addWidget(self.aging_empty)
            health_layout.addStretch()
            self.aging_status_layout.addWidget(aging_health, 3)
            aging_presence = card()
            presence_layout = QVBoxLayout(aging_presence)
            presence_layout.setContentsMargins(12, 8, 12, 9)
            presence_layout.addWidget(self.test_type_panel.presence_title)
            presence_layout.addWidget(self.test_type_panel.presence)
            self.aging_presence_empty = label('暂无 DUT 在线观测', 'muted')
            presence_layout.addWidget(self.aging_presence_empty)
            presence_layout.addStretch()
            self.aging_status_layout.addWidget(aging_presence, 2)
            self.execution_scroll.viewport().installEventFilter(self)
            self.execution_layout.addWidget(self.aging_status)
            self.execution_layout.addWidget(self.test_type_panel)
        self.execution_layout.addStretch()
        self.execution_scroll.setWidget(self.execution)
        self.splitter.addWidget(self.execution_scroll)
        self.config_scroll = QScrollArea()
        self.config_scroll.setWidgetResizable(True)
        self.config_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.configuration = card()
        self.configuration.setMinimumWidth(0)
        self.config_layout = QVBoxLayout(self.configuration)
        self.config_layout.setContentsMargins(12, 12, 12, 12)
        self.config_scroll.setWidget(self.configuration)
        self.splitter.addWidget(self.config_scroll)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes((900, 290))
        layout.addWidget(self.splitter, 1)

    def _set_aging_metrics(self, data):
        rows = data.get('rows', ())
        connected = [row for row in rows if row['source'] != 'unavailable']
        health = Counter(row['state'] for row in connected)
        observations = (history_datetime(row.get('last_observation')) for row in connected)
        observed_at = max((stamp for stamp in observations if stamp is not None), default=None)
        seconds = data.get('elapsed_seconds')
        elapsed = '—'
        if seconds is not None:
            days, remaining = divmod(int(seconds), 86400)
            hours, remaining = divmod(remaining, 3600)
            minutes, remaining = divmod(remaining, 60)
            elapsed = (f'{days} 天 ' if days else '') + f'{hours:02d}:{minutes:02d}:{remaining:02d}'
        self.aging_metrics.set_values((elapsed, len(connected) if rows else '—',
            health['healthy'] if connected else '—', health['abnormal'] if connected else '—',
            health['unknown'] if connected else '—', observed_at.strftime('%m-%d %H:%M:%S') if observed_at else '—'),
            {3: V13_PALETTE.error.text} if health['abnormal'] else None)
        self.aging_metrics.cards[-1].value_label.setToolTip(observed_at.strftime('%Y-%m-%d %H:%M:%S') if observed_at else '')
        self.aging_empty.setVisible(not rows)
        self.aging_presence_empty.setVisible(not data.get('dut_presence'))

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and watched is self.execution_scroll.viewport():
            direction = (QBoxLayout.Direction.LeftToRight if event.size().width() >= 700
                         else QBoxLayout.Direction.TopToBottom)
            if direction != self.aging_status_layout.direction():
                self.aging_status_layout.setDirection(direction)
        return super().eventFilter(watched, event)

    def _module_clicked(self, index):
        requests = (self.single_power_requested, self.upgrade_requested, self.parameter_requested,
                    self.onu_requested, self.serial_requested, self.dut_requested,
                    self.model_settings_requested, self.ai_chat_requested)
        if not 1 <= index <= len(requests):
            return
        # A request may synchronously disable its tab. Keep the overview selected
        # so Qt cannot select a neighbouring module while its slot is running.
        with QSignalBlocker(self.tabs):
            self.tabs.setCurrentIndex(0)
        requests[index - 1].emit()

    def set_project(self, project):
        assert_gui_thread()
        if project == self.project:
            return
        if self._metric_dialog is not None and (self.project is None or
                (project.project_id, project.run_id, project.project_type) !=
                (self.project.project_id, self.project.run_id, self.project.project_type)):
            self._metric_dialog.close()
        self.project = None
        self.test_type_panel.set_project(project)
        self.inspection_entry.set_project(project)
        cycles_visible = project.project_type != 'service_aging'
        self.tabs.setTabVisible(1, cycles_visible)
        self.summary.setVisible(cycles_visible)
        self.channel_card.setVisible(cycles_visible)
        self.pipeline_button.setVisible(cycles_visible)
        start_label = '开始测试' if cycles_visible else '开始监测'
        self.start_button.setText(start_label if self._refreshed else '▷ ' + start_label)
        if self._refreshed:
            self.cycle_metrics.setVisible(cycles_visible)
            self.aging_metrics.setVisible(not cycles_visible)
            self.aging_status.setVisible(not cycles_visible)
            if cycles_visible:
                accents = {3: V13_PALETTE.error.text} if project.attention_count else {}
                if project.failure_count:
                    accents[2] = V13_PALETTE.error.text
                self.cycle_metrics.set_values((project.elapsed, project.success_text, project.failure_text,
                                               project.attention_text), accents)
            else:
                self._set_aging_metrics(project.test_overview or {})
            self.stop_button.setText('停止测试' if cycles_visible else '停止监测')
            self.percent.setVisible(project.project_type != 'power_cycle')
        self.name.setText(project.name)
        metadata = (f'类型：{project.test_type}', f'DUT：{project.dut}', project.started_text)
        self.metadata.setText('   |   '.join(filter(None, metadata)))
        if self._refreshed:
            symbol = test_type_symbol(project.project_type, project.test_type)
            self.type_symbol.setVisible(bool(symbol))
            if symbol:
                self.type_symbol.icon = semantic_icon(symbol)
                self.type_symbol.update()
            self.name.setToolTip(project.name)
            self.metadata.setToolTip(self.metadata.text())
        self.state.set_project_state(project.state, project.state_text)
        self.start_button.setEnabled(project.can_start or project.parallel_power_available)
        self.environment_button.setEnabled(project.can_start)
        self.stop_button.setEnabled(project.can_stop)
        for control in (self.start_button, self.environment_button):
            control.setToolTip('核对已保存配置和明确通道后，确认调用原业务执行入口' if control.isEnabled()
                else '演示模式、历史结果未知或已有任务执行/收尾时不可启动')
        self.stop_button.setToolTip('请求当前任务安全停止，等待原业务确认终态')
        self.percent.setText(f'{project.progress}%' if project.progress is not None else '—')
        self.percent.ensurePolished()
        self.percent.setMinimumWidth(self.percent.fontMetrics().horizontalAdvance(self.percent.text()))
        self.progress.setVisible(project.progress is not None)
        self.progress.setValue(project.progress or 0)
        self.progress_text.setText(project.progress_text)
        if not self._refreshed:
            self.elapsed.setText('运行时间  ' + project.elapsed)
            self.success.setText('✓ 成功  ' + project.success_text)
            self.failure.setText('异常  ' + project.attention_text)
        self.run_id.setText(project.run_id or '尚无任务编号')
        stage = '当前阶段：' + project.task_stage if project.task_stage else ''
        self.stage.setText(' · '.join(filter(None, (stage, project.resume_detail))))
        if self._refreshed:
            style = f'color: {V13_PALETTE.error.text};' if project.attention_count else ''
            if self.stage.styleSheet() != style:
                self.stage.setStyleSheet(style)
        self.stage.setVisible(bool(stage or project.resume_detail))
        self.channel_title.setText('通道运行状态   ' + project.channel_text)
        self.channel_title.setToolTip(project.channel_snapshot_label or '当前项目配置；未收到实际任务事件时不推定运行')
        self.channel_edit_button.setEnabled(project.can_configure and project.editor_kind != 'configuration')
        enabled_channels = tuple(channel for channel in project.channels if channel.selected)
        self.channels.set_channels(enabled_channels)
        self.channel_model.set_channels(enabled_channels)
        self.channel_modes.setVisible(bool(enabled_channels))
        self.no_channels.setVisible(not enabled_channels)
        snapshot = (project.configuration, bool(project.channel_snapshot_label), cycles_visible, project.can_configure,
                    project.editor_kind)
        if snapshot == self._configuration_snapshot:
            self.project = project
            return
        self._configuration_snapshot = None
        while self.config_layout.count():
            widget = self.config_layout.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        title_row = QWidget()
        row = QHBoxLayout(title_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(label('任务配置快照' if project.channel_snapshot_label else '测试配置', 'section'))
        row.addStretch()
        if not cycles_visible:
            environment = button('环境配置', self.channels_configuration_requested.emit)
            environment.setEnabled(project.can_configure and project.editor_kind != 'configuration')
            row.addWidget(environment)
        edit = button('测试配置', self.configuration_requested.emit)
        self.edit_button = edit
        edit.setEnabled(project.can_configure)
        edit.setToolTip('编辑当前项目配置；已有任务执行或收尾时不可修改，运行快照保持')
        row.addWidget(edit)
        self.config_layout.addWidget(title_row)
        for name, fields in project.configuration:
            group = QWidget()
            section = QVBoxLayout(group)
            section.setContentsMargins(0, 6, 0, 6)
            section.addWidget(label('▾  ' + name, 'section'))
            form = QFormLayout()
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            for key, value in fields:
                field = label(value)
                field.setWordWrap(True)
                field.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                form.addRow(key, field)
            section.addLayout(form)
            self.config_layout.addWidget(group)
        if not project.configuration:
            text = label('尚无可显示的配置快照', 'muted')
            text.setWordWrap(True)
            self.config_layout.addWidget(text)
        self.config_layout.addStretch()
        self.config_layout.activate()
        self.configuration.updateGeometry()
        self._configuration_snapshot = snapshot
        self.project = project

    def toggle_configuration(self):
        self._user_config_visibility = True
        self._set_configuration_visible(self.config_scroll.isHidden())

    def _open_metric_detail(self, metric):
        project = self.project
        if project is None or project.project_type == 'service_aging':
            return
        if self._metric_dialog is not None:
            self._metric_dialog.close()
        dialog = PowerMetricDetailDialog(project, metric, self)
        self._metric_dialog = dialog
        dialog.finished.connect(self._metric_detail_closed)
        dialog.show()
        self.metric_detail_opened.emit(project, POWER_METRIC_LABELS[metric], dialog.has_records)

    def _metric_detail_closed(self, _result):
        self._metric_dialog = None

    def hideEvent(self, event):
        if self._metric_dialog is not None and not event.spontaneous():
            self._metric_dialog.close()
        super().hideEvent(event)

    def _set_configuration_visible(self, visible):
        self.config_scroll.setVisible(visible)
        self.config_toggle.setText('收起配置' if visible else '测试配置')

    def set_channel_mode(self, mode):
        assert_gui_thread()
        self.channel_modes.setCurrentIndex(mode)
        self.channel_modes.update_current_geometry()
        self.matrix_button.setChecked(mode == 0)
        self.table_button.setChecked(mode == 1)

    def _table_channel_menu(self, point):
        index = self.channel_table.indexAt(point)
        if index.isValid():
            self.channel_context_menu(index.data(Qt.ItemDataRole.UserRole), self.channel_table.viewport().mapToGlobal(point))

    def channel_context_menu(self, number, point):
        channel = next((c for c in self.project.channels if c.number == number), None)
        if channel is not None:
            self.recovery_action.setData((self.project.project_id, number))
            self.recovery_action.setEnabled(channel.can_resume)
            target = self._channel_history_target(number)
            self.channel_history_action.setData(target)
            self.channel_history_action.setEnabled(target is not None)
            self.recovery_menu.popup(point)

    def _channel_history_target(self, number):
        if self.project.power_history_job and number in dict(self.project.power_history_events):
            return self.project.project_id, self.project.power_history_job, number
        return None

    def _channel_history_menu_selected(self):
        target = self.channel_history_action.data()
        if target is not None:
            self.channel_history_requested.emit(*target)

    def _resume_menu_selected(self):
        project, number = self.recovery_action.data()
        self.resume_requested.emit(project, number)

    def _power_log_menu_selected(self, kind):
        target = self.recovery_action.data()
        if target is not None:
            project, number = target
            self.power_log_requested.emit(project, number, kind)

    def open_channel(self, number):
        channel = next(c for c in self.project.channels if c.number == number)
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowTitle(f'CH{number:02d} · 通道快照')
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for key, value in (('通道', f'CH{number:02d}'), ('状态', ChannelTableModel.STATES.get(channel.state, '未知')),
                           ('VLAN', channel.vlan or '未配置'), ('COM', channel.port or '未配置'),
                           ('已完成轮次', str(channel.cycle) if channel.cycle is not None else '未知'),
                           ('目标轮次', str(channel.total) if channel.total is not None else '未知')):
            form.addRow(key, label(value))
        stage = label(channel.stage or '尚无上报')
        stage.setWordWrap(True)
        form.addRow('最近上报阶段', stage)
        if channel.detail and channel.detail != channel.stage:
            detail = label(channel.detail)
            detail.setTextFormat(Qt.TextFormat.PlainText)
            detail.setWordWrap(True)
            detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow('状态详情', detail)
        layout.addLayout(form)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText('关闭')
        close.rejected.connect(dialog.close)
        layout.addWidget(close)
        target = self._channel_history_target(number)
        if target is not None:
            close.addButton(button('重试/失败历史…', lambda: self.channel_history_requested.emit(*target)),
                QDialogButtonBox.ButtonRole.ActionRole)
        if channel.can_resume:
            project = self.project.project_id
            def resume():
                dialog.accept()
                self.resume_requested.emit(project, number)
            close.addButton(button('从失败轮次继续…', resume), QDialogButtonBox.ButtonRole.ActionRole)
        self.dialogs.append(dialog)
        dialog.finished.connect(lambda result: self.dialogs.remove(dialog))
        dialog.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow = self.width() < 850
        if narrow != self._narrow:
            self._narrow = narrow
            self.header_layout.setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
        if not self._user_config_visibility:
            width = 1100 if self._refreshed else 850
            self._set_configuration_visible(self.width() >= width)
