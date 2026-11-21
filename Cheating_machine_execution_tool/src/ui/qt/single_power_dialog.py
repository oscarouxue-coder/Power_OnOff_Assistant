"""Select the port and direction for one explicitly reviewed power operation."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QVBoxLayout

from src.models.channel_resource_options import POWER_SERIAL_OPTIONS
from src.services.qt_single_power import POWER_ACTIONS, SinglePowerTarget
from src.ui.qt.theme import button, label


class SinglePowerDialog(QDialog):
    review_requested = Signal(object)
    inventory_requested = Signal()

    def __init__(self, project, selection, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.project_id = project.project_id
        self.selection = selection
        self.setWindowTitle('单次自动上/下电 · ' + project.name)
        self.resize(470, 225)
        layout = QVBoxLayout(self)
        heading = label('单次自动上/下电 · ' + project.name, 'title')
        heading.setWordWrap(True)
        layout.addWidget(heading)
        form = QFormLayout()
        targets = label('、'.join(f'CH{number:02d}' for number in selection.numbers))
        targets.setWordWrap(True)
        form.addRow('目标通道', targets)
        self.port = QComboBox()
        form.addRow('程控电源', self.port)
        self.action = QComboBox()
        for action, text in POWER_ACTIONS.items():
            self.action.addItem(text, action)
        form.addRow('操作', self.action)
        self.all_ports = QCheckBox('显示所有串口')
        self.all_ports.toggled.connect(self._show_all)
        form.addRow('', self.all_ports)
        layout.addLayout(form)
        self.detected = selection.detected_ports
        self._update_ports(selection.configured_port)

        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button('取消', self.reject))
        self.review_button = button('核对并继续…', self._review, 'primary')
        actions.addWidget(self.review_button)
        layout.addLayout(actions)

    def _update_ports(self, selected):
        options = ('', *self.detected) if self.all_ports.isChecked() else POWER_SERIAL_OPTIONS
        self.port.clear()
        for port in dict.fromkeys((*options, self.selection.configured_port, selected or '')):
            self.port.addItem(port or '手动重启（不选电源口）', port)
        self.port.setCurrentIndex(max(0, self.port.findData(selected)))

    def _show_all(self, checked):
        self._update_ports(self.port.currentData())
        if checked:
            self.inventory_requested.emit()

    def update_inventory(self, ports):
        self.detected = ports
        self._update_ports(self.port.currentData())

    def _review(self):
        self.review_requested.emit(SinglePowerTarget(self.port.currentData(), self.action.currentData(), self.selection.binding))
        self.accept()
