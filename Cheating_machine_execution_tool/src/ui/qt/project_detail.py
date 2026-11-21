"""Project presentation only: status, responsive channel matrix and config summary."""
from functools import partial

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QBoxLayout, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout,
    QAbstractItemView, QHeaderView, QHBoxLayout, QMenu, QProgressBar, QScrollArea, QSizePolicy,
    QSplitter, QStackedWidget, QTabBar, QTableView, QVBoxLayout, QWidget)
from src.ui.qt.channel_table_model import ChannelTableModel
from src.ui.qt.theme import (BRAND, GAP, MUTED, assert_gui_thread, button, card, label, status_style)


class ChannelMatrix(QWidget):
    selected = Signal(int)
    context_requested = Signal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
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
        states = {'running': '● 运行中', 'success': '✓ 正常', 'failed': '异常',
                  'unknown': '未知', 'disabled': '未启用', 'stopped': '已停止', 'retry': '重试中'}
        for channel in self.channels:
            state = states.get(channel.state, '未知')
            text = f'CH{channel.number:02d}   {state}'
            if channel.cycle is not None:
                text += f'\n已完成 {channel.cycle} 轮'
            tile = button(text, lambda checked=False, number=channel.number: self.selected.emit(number))
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
            if channel.state in ('running', 'success'):
                tile.setStyleSheet('QPushButton { background: #E9F9EF; color: #166534; border: 1px solid #9CD7AC; }')
            elif channel.state == 'failed':
                tile.setStyleSheet('QPushButton { background: #FEF2F2; color: #DC2626; border: 1px solid #F2BABA; }')
            elif channel.state == 'retry':
                tile.setStyleSheet('QPushButton { background: #FFFBEB; color: #D97706; border: 1px solid #F4D9A6; }')
            else:
                tile.setStyleSheet('QPushButton { background: #F0F3F6; color: #6B7280; border: 1px solid #E5E7EB; }')
            tile.setMinimumHeight(max(44, tile.sizeHint().height()))
            self.tiles.append(tile)
        self.reflow()

    def reflow(self):
        minimum = max(88, max((tile.sizeHint().width() for tile in self.tiles), default=0))
        spacing = self.grid.spacing()
        columns = max(1, min(8, (self.width() + spacing) // (minimum + spacing)))
        for index, tile in enumerate(self.tiles):
            self.grid.addWidget(tile, index // columns, index % columns)
        for index in range(8):
            self.grid.setColumnStretch(index, int(index < columns))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()


class ChannelViewStack(QStackedWidget):
    """Hidden table dimensions must not enlarge the compact channel matrix."""
    def sizeHint(self):
        widget = self.currentWidget()
        return widget.sizeHint() if widget is not None else super().sizeHint()

    def minimumSizeHint(self):
        widget = self.currentWidget()
        return widget.minimumSizeHint().expandedTo(widget.minimumSize()) if widget is not None else super().minimumSizeHint()


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self._configuration_snapshot = None
        self.dialogs = []
        self._narrow = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        breadcrumb = QHBoxLayout()
        breadcrumb.addWidget(button('‹  返回总览', self.back_requested.emit, 'link'))
        breadcrumb.addWidget(label('项目详情', 'muted'))
        breadcrumb.addStretch()
        self.config_toggle = button('收起配置', self.toggle_configuration)
        breadcrumb.addWidget(self.config_toggle)
        layout.addLayout(breadcrumb)
        header = card()
        self.header_layout = QHBoxLayout(header)
        self.header_layout.setContentsMargins(16, 10, 16, 10)
        identity = QHBoxLayout()
        self.header_layout.addLayout(identity, 1)
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
        self.state = label('')
        identity.addWidget(self.state)
        actions = QHBoxLayout()
        actions.addStretch()
        self.header_layout.addLayout(actions)
        self.start_button = button('▷ 开始测试', kind='primary')
        self.stop_button = button('■ 停止测试', kind='danger')
        self.environment_button = button('环境检查')
        self.pipeline_button = button('全流程…')
        for control in (self.pipeline_button, self.environment_button, self.start_button, self.stop_button):
            control.setEnabled(False)
            control.setToolTip('迁移原型：尚未接入真实任务控制，不发送设备命令')
            actions.addWidget(control)
        layout.addWidget(header)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(True)
        for index, name in enumerate(('运行概览', '自动上/下电', '样机升级', '写样机参数', 'ONU注册', '串口日志', 'DUT配置', 'AI 模型连接', 'AI 诊断')):
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
        self.execution_layout = QVBoxLayout(self.execution)
        self.execution_layout.setContentsMargins(0, 0, 2, 0)
        self.execution_layout.setSpacing(GAP)
        self.summary = card()
        summary_layout = QVBoxLayout(self.summary)
        summary_layout.setContentsMargins(16, 10, 16, 12)
        status_row = QHBoxLayout()
        self.percent = label('—', 'metric')
        status_row.addWidget(self.percent)
        status_row.addSpacing(16)
        self.progress_text = label('', 'section')
        status_row.addWidget(self.progress_text, 1)
        self.elapsed = label('')
        status_row.addWidget(self.elapsed)
        summary_layout.addLayout(status_row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        summary_layout.addWidget(self.progress)
        counts = QHBoxLayout()
        self.success = label('')
        self.failure = label('')
        counts.addWidget(self.success)
        counts.addSpacing(30)
        counts.addWidget(self.failure)
        counts.addStretch()
        self.run_id = label('', 'muted')
        counts.addWidget(self.run_id)
        summary_layout.addLayout(counts)
        self.stage = label('', 'muted')
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
        self.channel_edit_button = button('通道配置', self.channels_configuration_requested.emit)
        self.channel_edit_button.setEnabled(False)
        self.matrix_button = button('矩阵', lambda: self.set_channel_mode(0))
        self.table_button = button('列表', lambda: self.set_channel_mode(1))
        for control in (self.channel_edit_button, self.matrix_button, self.table_button):
            controls.addWidget(control)
        self.matrix_button.setCheckable(True)
        self.table_button.setCheckable(True)
        self.matrix_button.setChecked(True)
        channels_layout.addLayout(controls)
        self.no_channels = label('尚无通道快照', 'muted')
        channels_layout.addWidget(self.no_channels)
        self.channels = ChannelMatrix()
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
        self.channel_table = QTableView()
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

    def _module_clicked(self, index):
        if index == 1:
            self.single_power_requested.emit()
            self.tabs.setCurrentIndex(0)
        elif index == 2:
            self.upgrade_requested.emit()
            self.tabs.setCurrentIndex(0)
        elif index == 3:
            self.parameter_requested.emit()
            self.tabs.setCurrentIndex(0)
        elif index == 4:
            self.onu_requested.emit()
            self.tabs.setCurrentIndex(0)
        elif index == 5:
            self.serial_requested.emit()
            self.tabs.setCurrentIndex(0)
        elif index == 6:
            self.dut_requested.emit()
            self.tabs.setCurrentIndex(0)
        elif index == 7:
            self.model_settings_requested.emit()
            self.tabs.setCurrentIndex(0)
        elif index == 8:
            self.ai_chat_requested.emit()
            self.tabs.setCurrentIndex(0)

    def set_project(self, project):
        assert_gui_thread()
        if project == self.project:
            return
        self.project = project
        self.name.setText(project.name)
        metadata = (f'类型：{project.test_type}', f'DUT：{project.dut}', project.started_text)
        self.metadata.setText('   |   '.join(filter(None, metadata)))
        self.state.setText(project.state_text)
        self.state.setStyleSheet(status_style(project.state))
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
        self.elapsed.setText('运行时间  ' + project.elapsed)
        self.success.setText('✓ 成功  ' + (str(project.success_count) if project.success_count is not None else '—'))
        self.failure.setText('异常  ' + str(project.attention_count))
        self.run_id.setText(project.run_id or '尚无任务编号')
        stage = '当前阶段：' + project.task_stage if project.task_stage else ''
        self.stage.setText(' · '.join(filter(None, (stage, project.resume_detail))))
        self.stage.setVisible(bool(stage or project.resume_detail))
        self.channel_title.setText('通道运行状态   ' + project.channel_text)
        self.channel_title.setToolTip(project.channel_snapshot_label or '当前项目配置；未收到实际任务事件时不推定运行')
        self.channel_edit_button.setEnabled(project.can_configure and project.editor_kind != 'configuration')
        self.channels.set_channels(project.channels)
        self.channel_model.set_channels(project.channels)
        self.no_channels.setVisible(not bool(project.channels))
        snapshot = (project.configuration, bool(project.channel_snapshot_label))
        if snapshot == self._configuration_snapshot:
            return
        self._configuration_snapshot = snapshot
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
        edit = button('编辑配置', self.configuration_requested.emit)
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

    def toggle_configuration(self):
        visible = not self.config_scroll.isVisible()
        self.config_scroll.setVisible(visible)
        self.config_toggle.setText('收起配置' if visible else '测试配置')

    def set_channel_mode(self, mode):
        assert_gui_thread()
        self.channel_modes.setCurrentIndex(mode)
        self.channel_modes.updateGeometry()
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
            self.config_scroll.setVisible(not narrow)
            self.config_toggle.setText('测试配置' if narrow else '收起配置')
