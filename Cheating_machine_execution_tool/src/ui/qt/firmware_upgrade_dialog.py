"""Project upgrade controls. All validation and execution run on the worker."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLineEdit, QPlainTextEdit, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from src.models.boot_entry import BOOT_ENTRY_OPTIONS
from src.services.web_gateway_upgrade_service import TRANSFER_WEB_GATEWAY
from src.ui.qt.theme import button, label


def confirm_manual_restart(parent, summary):
    dialog = QDialog(parent)
    dialog.setWindowTitle('确认样机手动重启')
    dialog.resize(640, 430)
    layout = QVBoxLayout(dialog)
    details = QPlainTextEdit(summary)
    details.setReadOnly(True)
    layout.addWidget(details, 1)
    actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    proceed = button('已重启，继续升级', dialog.accept, kind='danger')
    proceed.setAutoDefault(False)
    actions.addButton(proceed, QDialogButtonBox.ButtonRole.ActionRole)
    actions.rejected.connect(dialog.reject)
    cancel = actions.button(QDialogButtonBox.StandardButton.Cancel)
    cancel.setDefault(True)
    cancel.setFocus()
    layout.addWidget(actions)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    dialog.deleteLater()
    return accepted


class FirmwareUpgradeDialog(QDialog):
    command_requested = Signal(str, dict)

    def __init__(self, snapshot, parent=None):
        super().__init__(parent)
        self.token = snapshot['token']
        self.busy = False
        self.detaching = False
        self.allow_close = False
        self.active = False
        self.stoppable = False
        self.has_power = bool(snapshot['power'])
        self.setWindowTitle('样机升级 · ' + snapshot['project'])
        self.resize(780, 680)
        layout = QVBoxLayout(self)
        layout.addWidget(label(self.windowTitle(), 'title'))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        fields = QVBoxLayout(body)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        defaults = snapshot['defaults']
        self.mode = self._choice(('全包升级', '页面升级'), defaults['upgrade_mode'])
        saved_transfer = defaults['transfer_method']
        if saved_transfer == 'Tftp拷贝命令':
            saved_transfer = 'Tftp指令'
        self.transfer = self._choice(('Tftp指令', 'Tftp Put', TRANSFER_WEB_GATEWAY), saved_transfer)
        self.boot = self._choice(BOOT_ENTRY_OPTIONS, defaults['boot_entry_method'])
        self.parallel = QSpinBox()
        self.parallel.setRange(1, 8)
        self.parallel.setValue(defaults['parallel_count'])
        self.restore = QCheckBox('升级后恢复出厂')
        self.restore.setChecked(defaults['restore_factory'])
        path_widget = QWidget()
        path_row = QHBoxLayout(path_widget)
        path_row.setContentsMargins(0, 0, 0, 0)
        self.firmware = QLineEdit(defaults['firmware_path'])
        path_row.addWidget(self.firmware, 1)
        path_row.addWidget(button('选择固件…', self._choose_firmware))
        self.full_fields = QWidget()
        full = QFormLayout(self.full_fields)
        full.setContentsMargins(0, 0, 0, 0)
        full.addRow('传输方式', self.transfer)
        full.addRow('进入 Boot', self.boot)
        full.addRow('并行数', self.parallel)
        form.addRow('升级模式', self.mode)
        form.addRow(self.full_fields)
        form.addRow('固件文件', path_widget)
        self.power_label = label(snapshot['power'] or '未配置')
        form.addRow('程控电源', self.power_label)
        self.username = QLineEdit(snapshot['username'])
        self.password = QLineEdit(snapshot['password'])
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        show_password = QCheckBox('显示升级密码')
        show_password.toggled.connect(lambda visible: self.password.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password))
        self.saved_credentials = (snapshot['username'], snapshot['password'])
        form.addRow('项目升级账号', self.username)
        form.addRow('项目升级密码', self.password)
        form.addRow(show_password)
        form.addRow(self.restore)
        fields.addLayout(form)
        fields.addWidget(label('目标通道', 'section'))
        self.targets = {}
        for target in snapshot['targets']:
            check = QCheckBox(f"CH{target['number']:02d} · {target['vlan'] or target['adapter']} · {target['host']} · {target['port'] or '按原VLAN映射'}")
            check.setChecked(True)
            check.toggled.connect(self._update_controls)
            self.targets[target['number']] = check
            fields.addWidget(check)
        if not self.targets:
            fields.addWidget(label('项目未选中通道', 'muted'))
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setMinimumHeight(100)
        self.results.setPlaceholderText('逐台结果')
        fields.addWidget(self.results)
        scroll.setWidget(body)
        self.body = body
        layout.addWidget(scroll, 1)
        self.feedback = label('')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.preview_button = button('预检并确认…', self._preview, kind='primary')
        self.save_button = button('保存项目设置', self._save)
        self.stop_button = button('安全停止…', lambda: self.request('stop'), kind='danger')
        self.close_button = button('关闭窗口', self.close)
        for control in (self.save_button, self.preview_button, self.stop_button, self.close_button):
            control.setAutoDefault(False)
            actions.addWidget(control)
        layout.addLayout(actions)
        self.mode.currentTextChanged.connect(self._mode_changed)
        self.transfer.currentTextChanged.connect(self._update_controls)
        self.boot.currentTextChanged.connect(self._update_controls)
        self.firmware.textChanged.connect(self._update_controls)
        self.username.textChanged.connect(self._update_controls)
        self.password.textChanged.connect(self._update_controls)
        self.apply_snapshot(snapshot)
        self._mode_changed()

    @staticmethod
    def _choice(choices, initial):
        box = QComboBox()
        box.addItems(choices)
        index = box.findText(initial)
        box.setCurrentIndex(index)
        return box

    def _choose_firmware(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择升级固件', self.firmware.text())
        if path:
            self.firmware.setText(path)

    def _mode_changed(self):
        full = self.mode.currentText() == '全包升级'
        self.full_fields.setVisible(full)
        if not self.has_power:
            self.power_label.setText('未配置 · 手动重启' if full else '未配置')
        if not self.active:
            self.feedback.clear()
        self._update_controls()

    def _update_controls(self):
        can_edit = not self.busy and not self.active
        self.body.setEnabled(can_edit)
        full_options = bool(self.transfer.currentText() and self.boot.currentText())
        valid_mode = bool(self.mode.currentText()) and (self.mode.currentText() == '页面升级' or full_options)
        saved = self.saved_credentials == (self.username.text(), self.password.text())
        credentials = bool(self.username.text().strip() and self.password.text().strip())
        self.preview_button.setEnabled(can_edit and valid_mode and saved and credentials
                                       and bool(self.firmware.text().strip())
                                       and any(check.isChecked() for check in self.targets.values()))
        self.preview_button.setToolTip('' if saved and credentials else '先填写并保存升级账号和密码')
        self.save_button.setEnabled(can_edit and valid_mode and full_options)
        self.stop_button.setEnabled(not self.busy and self.stoppable)
        self.close_button.setEnabled(not self.busy)

    def set_busy(self, busy):
        self.busy = busy
        self._update_controls()

    def _preview(self):
        args = dict(upgrade_type=self.mode.currentText(), firmware_path=self.firmware.text().strip(),
                    restore_factory=self.restore.isChecked(),
                    channel_ids=[number for number, check in self.targets.items() if check.isChecked()])
        if self.mode.currentText() == '全包升级':
            args.update(transfer_method=self.transfer.currentText(), boot_entry_method=self.boot.currentText(),
                        parallel_count=self.parallel.value())
        self.request('preview', upgrade=args)

    def _save(self):
        self.request('save', settings=dict(upgrade_mode=self.mode.currentText(), transfer_method=self.transfer.currentText(),
            boot_entry_method=self.boot.currentText(), parallel_count=self.parallel.value(),
            restore_factory=self.restore.isChecked(), firmware_path=self.firmware.text().strip(),
            username=self.username.text(), password=self.password.text()))

    def saved(self):
        self.saved_credentials = (self.username.text(), self.password.text())
        self.feedback.setText('已保存项目升级设置')
        self._update_controls()

    def request(self, operation, **fields):
        self.set_busy(True)
        self.command_requested.emit(operation, dict(token=self.token, **fields))

    def apply_snapshot(self, snapshot):
        self.active = snapshot['active']
        self.stoppable = snapshot['stoppable']
        text = {'idle': '', 'queued': '等待执行', 'running': '原升级任务运行中',
                'stop_requested': '等待安全停止', 'succeeded': '已完成', 'failed': '失败',
                'stopped': '已停止', 'unknown': '结果待核实', 'skipped': '未执行'}
        if snapshot['job']:
            self.feedback.setText(snapshot['notice'] or text.get(snapshot['state'], '等待原任务结果'))
        results = '\n'.join(f"{item['vlan']} · {text.get(item['state'], item['state'])} · {item['message']}"
                            for item in snapshot['items'])
        if self.results.toPlainText() != results:
            self.results.setPlainText(results)
        self._update_controls()

    def reject(self):
        if self.allow_close:
            super().reject()
        else:
            self.close()

    def closeEvent(self, event):
        if self.allow_close:
            super().closeEvent(event)
        else:
            event.ignore()
            if not self.busy and not self.detaching:
                self.detaching = True
                self.request('detach')
