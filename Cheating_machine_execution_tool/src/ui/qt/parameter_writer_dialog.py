"""Project parameter-table, preflight and result widgets."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QMessageBox, QPlainTextEdit, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from src.ui.qt.theme import button, label


class ParameterWriterDialog(QDialog):
    command_requested = Signal(str, dict)
    login_editability_changed = Signal()
    login_discarded = Signal()

    def __init__(self, snapshot, parent):
        super().__init__(parent)
        self.token = snapshot['token']
        self.busy = self.allow_close = self.active = self.stoppable = False
        self.close_after_save = False
        self.displayed_job = ()
        self.setWindowTitle('写样机参数 · ' + snapshot['project'])
        self.resize(760, 660)
        layout = QVBoxLayout(self)
        layout.addWidget(label(self.windowTitle(), 'title'))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.body = QWidget()
        content = QVBoxLayout(self.body)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        saved = snapshot['settings']
        self.path = QLineEdit(saved['table_path'])
        self.path.setReadOnly(True)
        self.path.setToolTip(self.path.text())
        self.path.textChanged.connect(self.path.setToolTip)
        source = QWidget()
        path_row = QHBoxLayout(source)
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.addWidget(self.path, 1)
        path_row.addWidget(button('选择…', self._choose))
        self.generate_button = button('生成参数表…', self._generate)
        path_row.addWidget(self.generate_button)
        form.addRow('参数表', source)
        self.username = QLineEdit(saved['initial_username'])
        self.password = QLineEdit(saved['initial_password'])
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.parallel = QSpinBox()
        self.parallel.setRange(1, 8)
        self.parallel.setMaximumWidth(90)
        self.parallel.setValue(saved['parallel_count'])
        form.addRow('首次登录账号', self.username)
        form.addRow('首次登录密码', self.password)
        form.addRow('并行数', self.parallel)
        self.username.setMaximumWidth(320)
        self.password.setMaximumWidth(320)
        self.clear = QCheckBox('清空参数')
        self.clear.setChecked(saved['clear_parameters'])
        self.exit_aging = QCheckBox('退出老化')
        self.exit_aging.setChecked(saved['exit_aging'])
        choices = QHBoxLayout()
        choices.addWidget(self.clear)
        choices.addWidget(self.exit_aging)
        choices.addStretch()
        form.addRow('工厂模式选项', choices)
        content.addLayout(form)
        content.addWidget(label('目标通道', 'section'))
        self.targets = {}
        for target in snapshot['targets']:
            title = f"CH{target['number']:02d} · {target['vlan']} · {target['port'] or '按 VLAN 映射'}"
            check = QCheckBox(title)
            check.setChecked(True)
            check.toggled.connect(self._update_controls)
            self.targets[target['number']] = check
            content.addWidget(check)
        if not self.targets:
            content.addWidget(label('项目未启用通道', 'muted'))
        scroll.setWidget(self.body)
        scroll.setMinimumHeight(155)
        layout.addWidget(scroll, 1)
        layout.addWidget(label('预检与逐台结果', 'section'))
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setMinimumHeight(100)
        layout.addWidget(self.results, 1)
        self.feedback = label('')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        actions = QHBoxLayout()
        self.preflight_button = button('重新预检', lambda: self._preview('preflight'))
        self.save_button = button('保存设置', self._save)
        self.write_button = button('写入参数…', lambda: self._preview('preview'), 'primary')
        self.stop_button = button('停止批次…', lambda: self.request('stop'), 'danger')
        self.close_button = button('关闭窗口', self.close)
        for item in (self.preflight_button, self.save_button, self.write_button, self.stop_button, self.close_button):
            item.setAutoDefault(False)
            actions.addWidget(item)
        layout.addLayout(actions)
        self.saved = self.settings()
        for edit in (self.path, self.username, self.password):
            edit.textChanged.connect(self._update_controls)
        self.apply_job(snapshot)

    def channel_ids(self):
        return [number for number, check in self.targets.items() if check.isChecked()]

    def settings(self):
        return dict(table_path=self.path.text(), initial_username=self.username.text(),
                    initial_password=self.password.text(), parallel_count=self.parallel.value(),
                    clear_parameters=self.clear.isChecked(), exit_aging=self.exit_aging.isChecked())

    def saved_login(self):
        return self.saved['initial_username'], self.saved['initial_password']

    def set_busy(self, value):
        self.busy = value
        self._update_controls()

    def _update_controls(self):
        editable = not self.busy and not self.active
        selected = bool(self.channel_ids())
        ready = editable and selected and bool(self.path.text())
        same_credentials = (self.username.text(), self.password.text()) == self.saved_login()
        self.body.setEnabled(editable)
        self.generate_button.setEnabled(editable and selected)
        self.preflight_button.setEnabled(ready)
        self.write_button.setEnabled(ready and same_credentials)
        self.save_button.setEnabled(editable)
        self.stop_button.setEnabled(not self.busy and self.stoppable)
        self.close_button.setEnabled(not self.busy)
        self.login_editability_changed.emit()

    def request(self, operation, **fields):
        self.set_busy(True)
        self.command_requested.emit(operation, dict(token=self.token, **fields))

    def _choose(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择参数表', self.path.text(),
            '参数表 (*.xlsx *.xls *.xlsm *.csv);;所有文件 (*)')
        if path:
            self.load_table(path)

    def load_table(self, path):
        self.path.setText(path)
        self._preview('select_table')

    def _generate(self):
        editor = ParameterGenerator(self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            save = QFileDialog(self, '保存批量样机参数表')
            save.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
            save.setNameFilter('Excel 参数表 (*.xlsx)')
            save.setDefaultSuffix('xlsx')
            save.selectFile('batch_sample_parameters.xlsx')
            if save.exec() == QDialog.DialogCode.Accepted:
                self.request('generate', channel_ids=self.channel_ids(),
                             template=editor.template(), output_path=save.selectedFiles()[0])

    def _preview(self, operation):
        settings = self.settings()
        settings.pop('initial_username')
        settings.pop('initial_password')
        self.request(operation, selection=dict(settings, channel_ids=self.channel_ids()))

    def _save(self):
        self.request('save', settings=self.settings())

    def restored_table(self):
        if self.path.text() and self.channel_ids() and not self.active:
            self._preview('preflight')

    def apply_preflight(self, snapshot):
        lines = ['预检通过' if snapshot['ok'] else '预检未通过']
        lines += snapshot['errors']
        lines += ['提示：' + item for item in snapshot['warnings']]
        lines += [f"{item['vlan']} / {item['port']} / 第 {item['row']} 行 / MAC {item['mac']}"
                  for item in snapshot['targets']]
        self.results.setPlainText('\n'.join(lines))
        self.feedback.clear()

    def apply_job(self, snapshot):
        self.active, self.stoppable = snapshot['active'], snapshot['stoppable']
        marker = (snapshot['job'], snapshot['state'], snapshot['stage'])
        if snapshot['job'] and self.displayed_job != marker:
            self.displayed_job = marker
            states = {'queued': '等待执行', 'running': '原写参任务运行中', 'stopping': '等待工厂模式清理',
                      'stop_requested': '等待工厂模式清理', 'succeeded': '批次完成',
                      'stopped': '已停止', 'unknown': '结果待核实', 'failed': '写参失败', 'skipped': '未执行'}
            title = states.get(snapshot['state'], '等待原任务结果')
            self.feedback.setText(title)
            lines = []
            for item in snapshot['items']:
                condition = '已停止' if item['cancelled'] else '成功' if item['ok'] else '失败'
                lines.append(f"{item['vlan']} · {condition} · 已写 {item['written_count']} 项 · {item['message']}")
            self.results.setPlainText('\n'.join(lines) if lines else title)
        self._update_controls()

    def accept_save(self):
        self.username.setText(self.username.text().strip())
        self.saved = self.settings()
        self._update_controls()
        self.feedback.setText('已保存项目写参设置')
        if self.close_after_save:
            self.close_after_save = False
            self.request('detach')

    def reject(self):
        if self.allow_close:
            super().reject()
        else:
            self.close()

    def closeEvent(self, event):
        if self.allow_close:
            super().closeEvent(event)
            return
        event.ignore()
        if self.busy:
            return
        if self.stoppable:
            self.feedback.setText('写参正在执行。请停止批次并等待工厂模式清理完成。')
            return
        if self.settings() != self.saved:
            choice = QMessageBox.question(self, '保存写参设置', '保存本项目的写参设置后关闭？',
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save)
            if choice == QMessageBox.StandardButton.Save:
                self.close_after_save = True
                self._save()
                return
            if choice != QMessageBox.StandardButton.Discard:
                return
            self.login_discarded.emit()
        self.request('detach')


class ParameterGenerator(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('生成批量样机参数表')
        self.resize(540, 610)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.fields = {}
        fields = (
            ('sn_prefix', 'SN 前缀', '12345678'), ('xpon_prefix', 'XPON SN 前缀', 'XPON'),
            ('mac_prefix', 'MAC 前 6 位', '020000'), ('ssid_24_prefix', '2.4G SSID 前缀', 'Test24G'),
            ('ssid_5_prefix', '5G SSID 前缀', 'Test5G'),
        )
        for key, title, value in fields:
            edit = QLineEdit(value)
            self.fields[key] = edit
            form.addRow(title, edit)
        self.suffix = QSpinBox()
        self.suffix.setRange(1, 16)
        self.suffix.setMaximumWidth(90)
        self.suffix.setValue(8)
        form.addRow('SN 随机后缀长度', self.suffix)
        defaults = {'2.4G Country Code': 'CN', '5G Country Code': 'CN', 'IP': '192.168.1.1'}
        self.fixed = {}
        for key in ('2.4G WiFi Password', '5G WiFi Password', '2.4G Country Code', '5G Country Code',
                    'Product Class', 'Superuser Name', 'Superuser Password', 'User Name', 'User Password', 'IP'):
            edit = QLineEdit(defaults.get(key, ''))
            if key.endswith('Password'):
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.fixed[key] = edit
            form.addRow(key, edit)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button('取消', self.reject))
        row.addWidget(button('选择保存位置…', self.accept, 'primary'))
        layout.addLayout(row)

    def template(self):
        return dict({key: edit.text() for key, edit in self.fields.items()}, suffix_length=self.suffix.value(),
                    fixed_values={key: edit.text() for key, edit in self.fixed.items()})
