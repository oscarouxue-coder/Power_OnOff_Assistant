"""Review high-use module windows with isolated, fictional presentation data."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                               QPlainTextEdit, QPushButton, QStackedWidget, QVBoxLayout)

from src.ui.qt.channel_configuration_dialog import ChannelConfigurationDialog
from src.ui.qt.configuration_dialog import ConfigurationDialog
from src.ui.qt.dut_configuration_dialog import DutConfigurationDialog
from src.ui.qt.firmware_upgrade_dialog import FirmwareUpgradeDialog
from src.ui.qt.serial_terminal_dialog import SerialTerminalDialog
from src.ui.qt.showcase_components import semantic_icon
from src.ui.qt.theme import V13_PALETTE, WORKBENCH_QSS, button, card, label
from src.ui.qt.visual_preview_data import module_preview_snapshots


MODULES = (
    ('串口日志', SerialTerminalDialog),
    ('样机升级', FirmwareUpgradeDialog),
    ('DUT 配置', DutConfigurationDialog),
    ('测试项配置', ConfigurationDialog),
    ('通道配置', ChannelConfigurationDialog),
)

MODULE_QSS = f'''
QDialog {{ background: {V13_PALETTE.background}; }}
QLabel[previewStatus="true"] {{ color: {V13_PALETTE.selected}; background: {V13_PALETTE.hover_background};
                              border: 1px solid #CEE6E1; border-radius: 6px; padding: 7px 9px; }}
QLabel[previewIssue="true"] {{ color: {V13_PALETTE.error.text}; background: {V13_PALETTE.error.background};
                             border: 1px solid #EAB2B2; border-radius: 6px; padding: 7px 9px; }}
QLineEdit:read-only {{ background: #EFF4F8; color: #41576A; }}
QPlainTextEdit[previewReadout="true"] {{ background: #F7F9FC; border-color: #CBD9E4; padding: 8px; }}
QWidget[previewChannel="true"] {{ background: white; border: 1px solid {V13_PALETTE.border};
                                border-radius: 8px; }}
'''


def _style_dialog(dialog):
    dialog.setStyleSheet(WORKBENCH_QSS + MODULE_QSS)
    outer = dialog.layout()
    outer.setContentsMargins(14, 12, 14, 12)
    outer.setSpacing(8)
    for form in dialog.findChildren(QFormLayout):
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setVerticalSpacing(7)
    for readout in dialog.findChildren(QPlainTextEdit):
        if readout.isReadOnly():
            readout.setProperty('previewReadout', True)


def _style_actions(dialog):
    outer = dialog.layout()
    action_index = outer.count() - 1
    actions = outer.takeAt(action_index).layout()
    bar = card()
    bar.setLayout(actions)
    actions.setContentsMargins(9, 5, 9, 5)
    outer.addWidget(bar)


def _style_serial(dialog):
    dialog.open_button.setIcon(semantic_icon('play', 'white'))
    dialog.stop_button.setIcon(semantic_icon('stop'))
    dialog.feedback.setProperty('previewIssue', True)
    for view in dialog.views.values():
        status = 'previewStatus' if view['writable'] else 'previewIssue'
        view['status'].setProperty(status, True)
        view['output'].setFont(QFont('Consolas', 10))
        view['enter'].setIcon(semantic_icon('play'))


def _style_upgrade(dialog):
    _style_actions(dialog)
    fields = dialog.body.layout()
    form = fields.takeAt(0).layout()
    settings = card()
    options = QVBoxLayout(settings)
    options.setContentsMargins(12, 8, 12, 10)
    options.addWidget(label('固件与升级设置', 'section'))
    options.addLayout(form)
    fields.insertWidget(0, settings)

    targets = card()
    target_box = QVBoxLayout(targets)
    target_box.setContentsMargins(12, 8, 12, 10)
    target_box.addWidget(fields.takeAt(1).widget())
    for check in dialog.targets.values():
        fields.removeWidget(check)
        target_box.addWidget(check)
    fields.insertWidget(1, targets)
    fields.insertWidget(2, label('逐台升级结果', 'section'))
    dialog.feedback.setProperty('previewIssue', True)


def _style_dut(dialog):
    _style_actions(dialog)
    dialog.query_button.setIcon(semantic_icon('inspect'))
    dialog.stop_button.setIcon(semantic_icon('stop'))
    dialog.feedback.setProperty('previewIssue', True)
    dialog.status.setFont(QFont('Microsoft YaHei UI', 9))


def _style_configuration(dialog):
    _style_actions(dialog)
    dialog.save_button.setIcon(semantic_icon('check', 'white'))


def _style_channels(dialog):
    _style_configuration(dialog)
    dialog.resources_button.setIcon(semantic_icon('refresh'))
    for row in dialog.rows:
        row.setProperty('previewChannel', True)
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        row.grid.setContentsMargins(9, 6, 9, 6)


STYLES = (_style_serial, _style_upgrade, _style_dut, _style_configuration, _style_channels)


class ModuleVisualPreview(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('DUTPilot · 高频业务窗口评审')
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(1080, 820)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        controls = QHBoxLayout()
        self.modules = QComboBox()
        self.modules.addItems([name for name, _ in MODULES])
        self.modules.setAccessibleName('业务窗口')
        controls.addWidget(self.modules)
        self.variant_buttons = QButtonGroup(self)
        for index, title in enumerate(('当前版', '改版预览')):
            control = button(title)
            control.setCheckable(True)
            self.variant_buttons.addButton(control, index)
            controls.addWidget(control)
        self.variant_buttons.button(1).setChecked(True)
        controls.addStretch()
        controls.addWidget(label('模拟数据', 'muted'))
        layout.addLayout(controls)
        self.versions = QStackedWidget(self)
        layout.addWidget(self.versions, 1)
        self.modules.currentIndexChanged.connect(self._select_module)
        self.variant_buttons.idClicked.connect(self.versions.setCurrentIndex)
        self._select_module(0)

    def _select_module(self, index):
        if index < 0:
            return
        while self.versions.count():
            old = self.versions.widget(0)
            self.versions.removeWidget(old)
            old.deleteLater()
        _, factory = MODULES[index]
        for variant in range(2):
            snapshot = module_preview_snapshots()[index]
            dialog = factory(snapshot)
            if index == 1:
                dialog.apply_snapshot(snapshot)
            dialog.setParent(self.versions, Qt.WindowType.Widget)
            self._disable_external_controls(dialog)
            if variant:
                STYLES[index](dialog)
                _style_dialog(dialog)
            self.versions.addWidget(dialog)
        self.versions.setCurrentIndex(self.variant_buttons.checkedId())

    @staticmethod
    def _disable_external_controls(dialog):
        # Switch tabs and inspect layouts using the real widgets. Sample actions
        # never leave the review; the workspace controller is absent entirely.
        disabled = ('日志目录…', '选择固件…', '关闭窗口', '关闭')
        for control in dialog.findChildren(QPushButton):
            if control.text() in disabled:
                control.setEnabled(False)
