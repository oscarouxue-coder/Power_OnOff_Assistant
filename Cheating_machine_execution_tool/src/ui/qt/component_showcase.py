"""Interactive, in-memory gallery of the DUTPilot Qt presentation components."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QScrollArea,
    QSlider, QStackedWidget, QVBoxLayout, QWidget,
)

from . import demo_data
from .dashboard import CardList, ProjectTableModel
from .log_panel import LogPanel
from .progress_widgets import CircularProgress, ProgressBar
from .project_detail import ChannelMatrix
from .showcase_components import (
    SHOWCASE_QSS, STATUS_STYLES, MetricCard, StatusBadge, StatusCard, icon_button,
    primary_button, secondary_button,
)
from .theme import CARD_PADDING, GAP, card, label


class ComponentShowcase(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('ComponentShowcase')
        self.setWindowTitle('DUTPilot · GUI 组件展示')
        self.setStyleSheet(SHOWCASE_QSS)
        self.confirm_dialog = None
        self.resize(880, 760)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        root.addWidget(self.scroll_area)
        content = QWidget()
        content.setObjectName('ShowcaseContent')
        self.scroll_area.setWidget(content)
        body = QVBoxLayout(content)
        body.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        body.setSpacing(GAP)
        body.addWidget(label('GUI 组件展示', 'title'))
        body.addWidget(label('开发预览 · 全部项目、通道与日志均为示例数据', 'muted'))

        self._add_progress(body)
        self._add_statuses(body)
        self._add_project(body)
        self._add_view_states(body)
        self.log_panel = LogPanel()
        self.log_panel.title.setText('示例日志')
        self.log_panel.append_batch(demo_data.logs())
        body.addWidget(self.log_panel)
        body.addStretch()

    def _add_progress(self, body):
        panel = card()
        body.addWidget(panel)
        column = QVBoxLayout(panel)
        column.addWidget(label('进度与操作', 'section'))
        preview = QHBoxLayout()
        column.addLayout(preview)
        self.circular_progress = CircularProgress()
        preview.addWidget(self.circular_progress)
        controls = QVBoxLayout()
        preview.addLayout(controls, 1)
        self.progress_bar = ProgressBar()
        controls.addWidget(self.progress_bar)
        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setAccessibleName('示例进度百分比')
        self.progress_slider.setRange(0, 100)
        self.progress_slider.setValue(68)
        controls.addWidget(self.progress_slider)
        self.progress_state = QComboBox()
        self.progress_state.setAccessibleName('示例进度状态')
        for title, state in (('正常', 'normal'), ('警告', 'warning'), ('异常', 'error'),
                             ('未知', 'unknown'), ('未接入', 'unavailable')):
            self.progress_state.addItem(title, state)
        controls.addWidget(self.progress_state)
        self.progress_slider.valueChanged.connect(self._update_progress)
        self.progress_state.currentIndexChanged.connect(self._update_progress)
        row = QHBoxLayout()
        column.addLayout(row)
        self.primary_action = primary_button('应用示例', self._confirm)
        self.secondary_action = secondary_button('重置进度', self._reset_progress)
        self.refresh_action = icon_button('refresh', '重新载入示例日志', self._reload_logs)
        for control in (self.primary_action, self.secondary_action, self.refresh_action):
            row.addWidget(control)
        row.addStretch()
        self.action_feedback = label('', 'muted')
        self.action_feedback.setWordWrap(True)
        self.action_feedback.hide()
        column.addWidget(self.action_feedback)
        self._update_progress(animate=False)

    def _update_progress(self, *_, animate=True):
        state = self.progress_state.currentData()
        known = state not in ('unknown', 'unavailable')
        self.progress_slider.setEnabled(known)
        self.primary_action.setEnabled(known)
        value = self.progress_slider.value() if known else None
        for control in (self.progress_bar, self.circular_progress):
            control.set_progress(value, state, animate=animate)

    def _feedback(self, text):
        self.action_feedback.setText(text)
        self.action_feedback.show()

    def _reset_progress(self):
        self.progress_slider.setValue(68)
        self.progress_state.setCurrentIndex(0)
        self._feedback('已恢复示例进度 68%')

    def _reload_logs(self):
        self.log_panel.clear_display()
        self.log_panel.append_batch(demo_data.logs())
        self._feedback('已重新载入示例日志')

    def _confirm(self):
        if self.confirm_dialog is None:
            self.confirm_dialog = QDialog(self)
            self.confirm_dialog.setWindowTitle('应用示例')
            layout = QVBoxLayout(self.confirm_dialog)
            layout.addWidget(label('确认在展示页应用当前示例进度？'))
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText('应用')
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
            buttons.accepted.connect(self.confirm_dialog.accept)
            buttons.rejected.connect(self.confirm_dialog.reject)
            layout.addWidget(buttons)
            self.confirm_dialog.accepted.connect(
                lambda: self._feedback('已应用示例进度 · ' + self.progress_bar.display_text))
            self.confirm_dialog.rejected.connect(lambda: self._feedback('已取消应用示例'))
        self.confirm_dialog.open()

    def _add_statuses(self, body):
        panel = card()
        body.addWidget(panel)
        column = QVBoxLayout(panel)
        column.addWidget(label('状态标记', 'section'))
        badges = QGridLayout()
        column.addLayout(badges)
        self.badges = {}
        for index, state in enumerate(STATUS_STYLES):
            badge = StatusBadge(state)
            self.badges[state] = badge
            badges.addWidget(badge, index // 5, index % 5, Qt.AlignmentFlag.AlignLeft)
        badges.setColumnStretch(5, 1)

    def _add_project(self, body):
        project = demo_data.projects()[0]
        channels = tuple(channel for channel in project.channels if channel.cycle is not None)
        body.addWidget(label('项目与通道', 'section'))
        metrics = QHBoxLayout()
        metrics.addWidget(MetricCard('参与通道', len(channels)))
        metrics.addWidget(MetricCard('运行任务', project.active_task_count))
        body.addLayout(metrics)
        self.project_cards = CardList()
        self.project_model = ProjectTableModel(self.project_cards)
        self.project_cards.setModel(self.project_model)
        self.project_model.replace((project,))
        card_height = self.project_cards.sizeHintForIndex(self.project_model.index(0, 0)).height()
        self.project_cards.setFixedHeight(card_height + 2 * self.project_cards.frameWidth())
        body.addWidget(self.project_cards)
        self.project_feedback = label('', 'muted')
        self.project_feedback.setWordWrap(True)
        self.project_feedback.hide()
        self.project_cards.clicked.connect(self._show_project)
        body.addWidget(self.project_feedback)
        self.channel_matrix = ChannelMatrix()
        self.channel_matrix.set_channels(channels)
        self.channel_matrix.selected.connect(self._show_channel)
        body.addWidget(self.channel_matrix)
        self.channel_feedback = label('', 'muted')
        self.channel_feedback.hide()
        body.addWidget(self.channel_feedback)
        statuses = QVBoxLayout()
        body.addLayout(statuses)
        self.status_cards = {}
        for key, title, detail, state in (
            ('dut', 'DUT 01', 'PON 已注册', 'healthy'),
            ('resource', '电源通道 01', '示例项目已取得租约', 'busy'),
            ('step', '固件版本回读', '等待设备返回版本信息', 'unknown'),
        ):
            self.status_cards[key] = StatusCard(title, detail, state)
            statuses.addWidget(self.status_cards[key])

    def _show_project(self, index):
        project = index.data(Qt.ItemDataRole.UserRole)
        self.project_feedback.setText(f'{project.name} · {project.channel_text} · 已运行 {project.elapsed}')
        self.project_feedback.show()

    def _show_channel(self, number):
        channel = next(item for item in self.channel_matrix.channels if item.number == number)
        self.channel_feedback.setText(f'CH{number:02d} · {channel.vlan} / {channel.port} · '
                                     f'已完成 {channel.cycle} / {channel.total} 轮')
        self.channel_feedback.show()

    def _add_view_states(self, body):
        panel = card()
        body.addWidget(panel)
        layout = QVBoxLayout(panel)
        row = QHBoxLayout()
        layout.addLayout(row)
        row.addWidget(label('内容状态', 'section'))
        row.addStretch()
        self.view_state = QComboBox()
        self.view_state.setAccessibleName('示例内容状态')
        self.view_state.addItem('空状态', 'empty')
        self.view_state.addItem('加载状态', 'loading')
        row.addWidget(self.view_state)
        self.state_stack = QStackedWidget()
        for text in ('暂无检查记录', '正在载入示例检查记录…'):
            view = label(text, 'muted')
            view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.state_stack.addWidget(view)
        layout.addWidget(self.state_stack)
        self.view_state.currentIndexChanged.connect(self.state_stack.setCurrentIndex)
