"""Local workspace observations, separate from DUT test outcomes."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from src.ui.qt.theme import DANGER, WARNING, assert_gui_thread, button, card, label


class SystemHealthPanel(QWidget):
    layout_changed = Signal()
    HEADERS = ('界面与工作区', '消息积压', '工作区日志写入', '测试任务', '工作区资源占用', '串口 / 网卡枚举')

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = card()
        outer.addWidget(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 6, 12, 8)
        header = QHBoxLayout()
        header.addWidget(label('系统状态', 'section'))
        header.addStretch()
        self.toggle = button('收起', self._toggle_details)
        self.toggle.setAccessibleName('展开或收起系统状态')
        header.addWidget(self.toggle)
        layout.addLayout(header)
        self.details = QWidget()
        self.details.setObjectName('SystemHealthDetails')
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setFixedHeight(self.fontMetrics().lineSpacing() * 3)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.details)
        layout.addWidget(self.scroll)
        self.grid = QGridLayout(self.details)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(7)
        self.cells, self.values = [], []
        for title in self.HEADERS:
            cell = QWidget()
            group = QVBoxLayout(cell)
            group.setContentsMargins(0, 0, 0, 0)
            group.setSpacing(1)
            group.addWidget(label(title, 'muted'))
            value = label('等待采集')
            value.setWordWrap(True)
            value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            value.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            group.addWidget(value)
            self.cells.append(cell)
            self.values.append(value)
        self.columns = 0
        self._manually_expanded = False
        self._reflow(3)

    def _toggle_details(self):
        self._manually_expanded = True
        self._set_expanded(self.scroll.isHidden())

    def _set_expanded(self, visible):
        if self.scroll.isHidden() != visible:
            return
        self.scroll.setVisible(visible)
        if visible:
            self.scroll.verticalScrollBar().setValue(0)
        self.toggle.setText('收起' if visible else '展开')
        self.layout_changed.emit()

    def _reflow(self, columns):
        if self.columns == columns:
            return
        self.columns = columns
        for cell in self.cells:
            self.grid.removeWidget(cell)
        for index, cell in enumerate(self.cells):
            self.grid.addWidget(cell, index // columns, index % columns)
        for index in range(3):
            self.grid.setColumnStretch(index, int(index < columns))
        self.details.updateGeometry()
        self.scroll.updateGeometry()
        self.updateGeometry()
        self.layout_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        wide = event.size().width() >= 680
        self._reflow(3 if wide else 2)
        if not self._manually_expanded:
            self._set_expanded(wide)
        if event.oldSize().height() != event.size().height():
            self.layout_changed.emit()

    def fit_body(self, available_height):
        """Allow the full panel when it fits, with vertical scrolling in tight screens."""
        target = min(self.grid.sizeHint().height(), available_height // (5 if self.columns == 3 else 6))
        if self.scroll.minimumHeight() != target:
            self.scroll.setFixedHeight(target)

    def update_status(self, health, now, gui_gap_ms, log_batch_peak, projects):
        assert_gui_thread()
        previous_height = self.grid.sizeHint().height()
        gui = '等待界面回调' if gui_gap_ms is None else f'回调间隔峰值 {gui_gap_ms:.0f} ms'
        worker_age = None if health.worker_tick is None else max(0, now - health.worker_tick)
        worker = '等待工作区响应' if worker_age is None else f'工作区响应于 {worker_age:.1f} 秒前'
        delayed = (gui_gap_ms or 0) >= 500 or worker_age is not None and worker_age >= 3

        write_ok = True
        write = '暂无写入记录'
        if health.log_write is not None:
            at, write_ok = health.log_write
            write = f'{at:%H:%M:%S}  最近写入' + ('成功' if write_ok else '失败')
        if health.log_write_failures:
            write += f' · 失败累计 {health.log_write_failures}'

        active = sum(project.active_task_count for project in projects)
        attention = sum(project.attention_count for project in projects)
        task_log = health.task_log_at
        task = f'运行 / 恢复中 {active} · 需关注 {attention}\n'
        task += f'最近收到任务日志 {task_log:%H:%M:%S}' if task_log else '暂无任务日志'

        resources = health.resources
        occupation = '暂无占用采样'
        resource_warning = False
        if resources is not None:
            occupation = f'串口 / 电源 {resources.serial} · 网卡 {resources.adapters} · 其他 {resources.other}'
            stale = now - resources.sampled_at >= 3
            resource_warning = stale or resources.protection_unavailable
            if stale:
                occupation += '\n采样超过 3 秒'
            elif resources.protection_unavailable:
                occupation += '\n硬件准入保护不可用'

        inventory_ok = True
        inventory = '暂无手动枚举记录'
        if health.inventory_check is not None:
            at, inventory_ok = health.inventory_check
            inventory = f'{at:%H:%M:%S}  ' + ('最近枚举完成' if inventory_ok else '枚举存在失败项')

        values = ((f'{gui}\n{worker}', WARNING if delayed else ''),
            (f'待处理操作 {health.commands_pending} / {health.command_limit} · 日志批量峰值 {log_batch_peak}\n'
             f'显示队列累计略过 {health.logs_omitted}',
             WARNING if health.logs_omitted else ''),
            (write, DANGER if not write_ok else WARNING if health.log_write_failures else ''),
            (task, WARNING if attention else ''),
            (occupation, WARNING if resource_warning else ''),
            (inventory, WARNING if not inventory_ok else ''))
        for widget, (value, color) in zip(self.values, values):
            if widget.text() != value:
                widget.setText(value)
            style = f'color: {color}' if color else ''
            if widget.styleSheet() != style:
                widget.setStyleSheet(style)
        if self.grid.sizeHint().height() != previous_height:
            self.layout_changed.emit()
