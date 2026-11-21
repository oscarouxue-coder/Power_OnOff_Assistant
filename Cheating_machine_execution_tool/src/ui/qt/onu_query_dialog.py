"""Project OLT profiles and read-only ONU results."""
from copy import deepcopy

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView, QLineEdit,
    QMessageBox, QPlainTextEdit, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.models.onu_registration_models import OLT_FAMILIES, OnuTemplate
from src.services.qt_onu_query import CONNECTION_FIELDS, DISCOVERY_FIELDS
from src.ui.qt.onu_provision_page import OnuProvisionPage
from src.ui.qt.theme import button, label


class OnuQueryDialog(QDialog):
    command_requested = Signal(str, dict)

    def __init__(self, snapshot, parent):
        super().__init__(parent)
        self.token = snapshot['token']
        self.busy = self.active = self.stoppable = self.allow_close = False
        self.close_after_save = False
        self._loading = False
        self._displayed = None
        self._registration_preview = None
        self.registered_job = ''
        self._shown_family = snapshot['family']
        self._profiles = deepcopy(snapshot['profiles'])
        self._saved = dict(family=snapshot['family'], profiles=deepcopy(self._profiles))
        self.setWindowTitle('ONU 注册 · ' + snapshot['project'])
        self.resize(840, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(label(self.windowTitle(), 'title'))
        self.profile = QWidget()
        fields = QFormLayout(self.profile)
        fields.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.family = QComboBox()
        self.family.addItems(OLT_FAMILIES)
        self.family.setMaximumWidth(160)
        self.family.setCurrentText(snapshot['family'])
        fields.addRow('OLT 型号', self.family)
        self.inputs = {}
        connection_grid = QGridLayout()
        connection_grid.setColumnStretch(1, 1)
        connection_grid.setColumnStretch(3, 1)
        for index, (key, text) in enumerate(zip(CONNECTION_FIELDS, ('OLT IP', '源 IP', '用户名', '密码'))):
            entry = QLineEdit()
            entry.setMaximumWidth(320)
            entry.textChanged.connect(self._changed)
            self.inputs[key] = entry
            row, pair = divmod(index, 2)
            connection_grid.addWidget(label(text), row, pair * 2)
            connection_grid.addWidget(entry, row, pair * 2 + 1)
        fields.addRow(connection_grid)
        self.inputs['password'].setEchoMode(QLineEdit.EchoMode.Password)
        show_password = QCheckBox('显示密码')
        show_password.toggled.connect(lambda enabled: self.inputs['password'].setEchoMode(
            QLineEdit.EchoMode.Normal if enabled else QLineEdit.EchoMode.Password))
        fields.addRow(show_password)
        scope = QHBoxLayout()
        scope.setSpacing(10)
        self.scope = {}
        for key, text in zip(DISCOVERY_FIELDS, ('机框', '槽位', 'PON')):
            number = QSpinBox()
            number.setRange(0, 64)
            number.setMaximumWidth(76)
            number.valueChanged.connect(self._changed)
            scope.addWidget(label(text))
            scope.addWidget(number)
            self.scope[key] = number
        scope.addStretch()
        fields.addRow('发现范围', scope)
        self.profile.setToolTip('机框、槽位和 PON 同时为 0 时，可查询整台 OLT 的未注册 ONU')
        layout.addWidget(self.profile)

        self.buttons = {}
        row = QHBoxLayout()
        self._add_action(row, 'connection', '测试连接…')
        self.save_button = button('保存项目设置', self.save)
        self.save_button.setAutoDefault(False)
        row.addWidget(self.save_button)
        row.addStretch()
        layout.addLayout(row)

        self.tabs = QTabWidget()
        self.tables = {}
        self._result_tab('unregistered', '未注册 ONU', ('PON', '序列号', '型号 / 注册类型', 'PON 类型', '状态'),
                         (('unregistered', '查询未注册…'),))
        self._result_tab('registered', '已注册 ONU', ('ONU 接口', '序列号', '类型模板', '状态'),
                         (('registered', '查询当前 PON…'),))
        self._result_tab('templates', '模板', ('类别', '模板'),
                         (('onu_type', '查询 ONU 类型…'), ('dba', '查询 DBA…')))
        self.provision = OnuProvisionPage(snapshot['business'], self._shown_family)
        self.provision.changed.connect(self._registration_changed)
        self.provision.cleanup_requested.connect(self.lookup_cleanup)
        self.provision.preview_requested.connect(self.preview_registration)
        self.provision.save_requested.connect(self.save_business)
        self.tabs.addTab(self.provision, '配置业务')
        confirmation = QWidget()
        confirm_layout = QVBoxLayout(confirmation)
        self.plan_text = QPlainTextEdit()
        self.plan_text.setReadOnly(True)
        confirm_layout.addWidget(self.plan_text, 1)
        row = QHBoxLayout()
        row.addStretch()
        self.register_button = button('开始注册…', self.confirm_registration, 'danger')
        self.register_button.setAutoDefault(False)
        row.addWidget(self.register_button)
        confirm_layout.addLayout(row)
        self.tabs.addTab(confirmation, '确认执行')
        layout.addWidget(self.tabs, 1)

        self.feedback = label('', 'muted')
        self.feedback.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self.feedback, 1)
        self.stop_button = button('停止任务', lambda: self.request('stop'), 'danger')
        self.close_button = button('关闭窗口', self.close)
        for control in (self.stop_button, self.close_button):
            control.setAutoDefault(False)
            row.addWidget(control)
        layout.addLayout(row)
        self.family.currentTextChanged.connect(self._switch_family)
        self._load_profile()
        self.apply_job(snapshot)

    def _add_action(self, row, key, text):
        trigger = button(text, lambda: self.request('preview', action=key, family=self._shown_family),
                         'primary' if key == 'unregistered' else '')
        trigger.setAutoDefault(False)
        row.addWidget(trigger)
        self.buttons[key] = trigger

    def _result_tab(self, key, title, columns, actions):
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()
        for name, text in actions:
            self._add_action(controls, name, text)
        if key == 'registered':
            self.delete_button = button('删除所选 ONU…', self.prepare_delete, 'danger')
            self.delete_button.setAutoDefault(False)
            controls.addWidget(self.delete_button)
        controls.addStretch()
        layout.addLayout(controls)
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().hide()
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        if key == 'registered':
            table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
            table.itemSelectionChanged.connect(self._update_controls)
        layout.addWidget(table, 1)
        self.tabs.addTab(page, title)
        self.tables[key] = table

    def _remember_profile(self):
        self._profiles[self._shown_family] = {
            **{key: edit.text() for key, edit in self.inputs.items()},
            **{key: number.value() for key, number in self.scope.items()},
        }

    def _load_profile(self):
        profile = self._profiles[self._shown_family]
        self._loading = True
        try:
            for name, entry in self.inputs.items():
                entry.setText(profile[name])
            for name, number in self.scope.items():
                number.setValue(profile[name])
        finally:
            self._loading = False

    def _switch_family(self, family):
        self._remember_profile()
        self._shown_family = family
        self._load_profile()
        self.provision.change_family(family)
        self._changed()

    def _changed(self):
        if self._loading or not hasattr(self, 'tables'):
            return
        self._remember_profile()
        self.registered_job = ''
        for table in self.tables.values():
            table.setRowCount(0)
        self.provision.set_discovery('', [])
        self.invalidate_registration()
        self.feedback.clear()
        self._update_controls()

    def _update_controls(self):
        enabled = not self.busy and not self.active
        self.profile.setEnabled(enabled)
        self.save_button.setEnabled(enabled)
        profile = self._profiles[self._shown_family]
        query = enabled and profile == self._saved['profiles'][self._shown_family]
        for action, control in self.buttons.items():
            control.setEnabled(query)
            control.setToolTip('请先保存这组项目设置' if not query and enabled else '')
        self.provision.setEnabled(enabled)
        selection = self.provision.selection()
        cleanup = self._shown_family == 'C300' and self.provision.allow_cleanup.isChecked()
        self.provision.cleanup_lookup.setEnabled(query and cleanup and len(selection) == 1)
        self.provision.cleanup_candidates.setEnabled(bool(query and cleanup and self.provision.cleanup_job))
        self.provision.preview_button.setEnabled(bool(query and self.provision.discovery and selection
            and (not cleanup or len(selection) == 1 and self.provision.cleanup())))
        self.register_button.setEnabled(bool(query and self._registration_preview))
        self.delete_button.setEnabled(bool(query and self.registered_job and self._selected_registered()))
        self.stop_button.setEnabled(not self.busy and self.stoppable)
        self.close_button.setEnabled(not self.busy)

    def set_busy(self, busy):
        self.busy = busy
        self._update_controls()

    def request(self, operation, **values):
        if operation == 'preview':
            self.provision.set_cleanup('', [])
            self.invalidate_registration()
        self.set_busy(True)
        self.command_requested.emit(operation, dict(token=self.token, **values))

    def save(self):
        self._remember_profile()
        self.request('save_profile', family=self._shown_family, profiles=deepcopy(self._profiles))

    def saved(self, payload):
        self._profiles = deepcopy(payload['profiles'])
        self._saved = dict(family=payload['family'], profiles=deepcopy(self._profiles))
        self._load_profile()
        self._changed()
        self.feedback.setText('已保存本项目设置')
        if self.close_after_save:
            self.close_after_save = False
            self.request('detach')

    def _registration_changed(self):
        self.invalidate_registration()
        self._update_controls()

    def invalidate_registration(self):
        self._registration_preview = None
        self.plan_text.clear()

    def _registration_data(self):
        return dict(family=self._shown_family, discovery=self.provision.discovery,
                    selection=self.provision.selection(), business=self.provision.business())

    def _execution_data(self):
        data = dict(self._registration_data(),
                    write_after_success=self._shown_family == 'C600' and self.provision.write_after_success.isChecked())
        candidate = self.provision.cleanup()
        if candidate:
            data['cleanup'] = candidate
        return data

    def lookup_cleanup(self):
        self.provision.set_cleanup('', [])
        self.invalidate_registration()
        self.request('prepare_cleanup', **self._registration_data())

    def preview_registration(self):
        self.invalidate_registration()
        self.request('prepare_registration', **self._execution_data())

    def show_registration_preview(self, payload):
        self._registration_preview = payload
        self.plan_text.setPlainText(payload['commands'])
        self.tabs.setCurrentIndex(self.tabs.indexOf(self.plan_text.parentWidget()))

    def confirm_registration(self):
        if self._registration_preview:
            self.request('confirm_registration', **self._execution_data(),
                         confirmation=self._registration_preview['confirmation'])

    def registration_submitted(self):
        self._registration_preview = None
        self._update_controls()

    def save_business(self):
        self.request('save_business', family=self._shown_family, business=self.provision.business())

    def business_saved(self, payload):
        self.provision.saved(payload)
        self.invalidate_registration()
        self._update_controls()
        self.feedback.setText('已保存当前型号业务参数')

    def _selected_registered(self):
        table = self.tables['registered']
        rows = sorted(index.row() for index in table.selectionModel().selectedRows())
        selected = [table.item(row, 0) for row in rows]
        return [item.text() for item in selected if item is not None]

    def prepare_delete(self):
        self.invalidate_registration()
        self.request('prepare_delete', family=self._shown_family, query_job=self.registered_job,
                     interfaces=self._selected_registered())

    def apply_job(self, snapshot):
        self.active = snapshot['active']
        self.stoppable = snapshot['stoppable']
        profile_saved = self._profiles[self._shown_family] == self._saved['profiles'][self._shown_family]
        registered_job = (snapshot['registered_job'] if profile_saved and
                          snapshot['registered_family'] == self._shown_family else '')
        if registered_job != self.registered_job:
            self.registered_job = registered_job
            rows = snapshot['registered_rows'] if registered_job else []
            self.tables['registered'].setHorizontalHeaderLabels(('ONU 接口', '序列号', '类型模板', '状态'))
            self._fill('registered', ((row['onu_interface'], row['serial_number'], row['onu_type'], row['state'])
                                     for row in rows))
        target_job = snapshot['discovery'] if profile_saved and snapshot['discovery_family'] == self._shown_family else ''
        if target_job != self.provision.discovery:
            self.provision.set_discovery(target_job, snapshot['discovered'] if target_job else [])
            if snapshot['action'] != 'register':
                self.invalidate_registration()
        record = (snapshot['job'], snapshot['state'], snapshot.get('stale'), snapshot.get('save_notice'))
        if snapshot['job'] and record != self._displayed and snapshot['family'] == self._shown_family:
            self._displayed = record
            states = {'queued': '等待查询', 'running': '查询中…', 'stop_requested': '正在停止…',
                      'failed': '查询失败', 'succeeded': '查询完成', 'stopped': '查询已停止'}
            text = ('配置已变化，请重新查询' if snapshot['stale'] else
                    snapshot['message'] or states.get(snapshot['state'], '等待任务结果'))
            if snapshot['action'] == 'register' and snapshot['state'] == 'unknown':
                text = '注册结果待核实 · ' + text
            elif snapshot['action'] == 'save':
                saving = {'idle': '等待保存 OLT 启动配置', 'queued': '等待保存 OLT 启动配置',
                          'running': '正在保存 OLT 启动配置…', 'stop_requested': '正在停止保存…',
                          'stopped': '已停止保存 OLT 启动配置', 'unknown': 'OLT 保存结果待核实'}
                text = ' · '.join(filter(None, ('注册验证完成', saving.get(snapshot['state'], ''), snapshot['message'])))
            self.feedback.setText(text)
            action = snapshot['action']
            if action == 'unregistered':
                self._fill('unregistered', ((r['pon_interface'], r['serial_number'],
                    r['model'] or r['registration_type'], r['pon_type'], r['state']) for r in snapshot['onus']))
            elif action == 'cleanup_query':
                rows = snapshot['cleanup_candidates'] if self.provision.allow_cleanup.isChecked() else []
                self.provision.set_cleanup(snapshot['job'] if rows else '', rows)
            elif action == 'delete':
                if snapshot['state'] == 'unknown':
                    self.feedback.setText('删除结果待核实 · ' + text)
                states = {'success': '成功', 'failed': '失败', 'not_executed': '未执行'}
                self.tables['registered'].setHorizontalHeaderLabels(('ONU 接口', '序列号', '结果', '说明'))
                self._fill('registered', ((row['interface'], row['sn'], states[row['status']], row['message'])
                                         for row in snapshot['deleted']))
            elif action in ('onu_type', 'dba'):
                kind = 'ONU 类型' if action == 'onu_type' else 'DBA'
                options = [OnuTemplate(**row).display_text for row in snapshot['templates']]
                self._fill('templates', ((kind, value) for value in options))
                if options:
                    self.provision.update_templates(action, options)
        self._update_controls()

    def _fill(self, key, rows):
        table = self.tables[key]
        table.setRowCount(0)
        for row, values in enumerate(rows):
            table.insertRow(row)
            for col, value in enumerate(values):
                item = QTableWidgetItem(value or '—')
                item.setToolTip(value)
                table.setItem(row, col, item)

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
            self.feedback.setText('请先停止查询并等待收尾')
            return
        self._remember_profile()
        if self._saved != dict(family=self._shown_family, profiles=self._profiles):
            choice = QMessageBox.question(self, '保存 ONU 项目设置', '保存当前配置后关闭窗口？',
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save)
            if choice == QMessageBox.StandardButton.Save:
                self.close_after_save = True
                self.save()
                return
            if choice != QMessageBox.StandardButton.Discard:
                return
        self.request('detach')
