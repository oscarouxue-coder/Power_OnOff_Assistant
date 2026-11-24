"""Responsive local channel form. Validation and publication stay in services."""
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout,
    QHBoxLayout, QInputDialog, QLineEdit, QMenu, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)
from line_check_assistant.network_ops import adapter_alias_from_display, static_ip_for_vlan
from src.models.channel_resource_options import (
    POWER_SERIAL_OPTIONS, serial_options_for_power_serial_port, vlan_options_for_power_serial_port,
)
from src.services.adapter_rename_service import ADAPTER_NAME_HINT, adapter_has_numeric_suffix
from src.services.qt_channel_configuration import DUT_CHANNEL_DETAILS
from src.ui.qt.blocker_review import ReviewFeedback, focus_widget
from src.ui.qt.theme import BACKGROUND, DANGER, assert_gui_thread, button, card, label


class ChannelRow(QWidget):
    changed = Signal()

    def __init__(self, channel, parent=None):
        super().__init__(parent)
        self.number = int(channel['section'].rsplit('_', 1)[1])
        self._wide = None
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(6, 6, 6, 6)
        self.grid.setSpacing(8)
        self.enabled = QCheckBox(f'CH{self.number:02d}')
        self.enabled.setChecked(channel['enabled'])
        self.vlan = QComboBox()
        self.vlan.setEditable(True)
        self.vlan.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.vlan.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.vlan.setMinimumWidth(0)
        self.vlan.addItem(channel['vlan_name'])
        self.previous_vlan = self.current_vlan = channel['vlan_name']
        self.port = QComboBox()
        self.port.setEditable(True)
        self.port.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.port.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.port.setMinimumWidth(0)
        self.port.addItem(channel['serial_port'])
        self.source = QLineEdit(channel['network_card_ip'])
        self.source.setReadOnly(True)
        self.source.setMinimumWidth(0)
        self.source.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.groups = []
        for title, field in (('VLAN / 网卡名称', self.vlan), ('样机 COM', self.port), ('PC 源 IP（推导）', self.source)):
            group = QWidget()
            layout = QVBoxLayout(group)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(3)
            layout.addWidget(label(title, 'muted'))
            layout.addWidget(field)
            self.groups.append(group)
        self.enabled.toggled.connect(lambda *_: self.changed.emit())
        self.vlan.currentTextChanged.connect(self._vlan_changed)
        self.port.currentTextChanged.connect(lambda *_: self.changed.emit())
        self.reflow()

    def _vlan_changed(self, value):
        self.previous_vlan, self.current_vlan = self.current_vlan, value
        self.changed.emit()

    def reflow(self):
        wide = self.width() >= 650
        if wide == self._wide:
            return
        self._wide = wide
        for widget in (self.enabled, *self.groups):
            self.grid.removeWidget(widget)
        if wide:
            self.grid.addWidget(self.enabled, 0, 0)
            for index, group in enumerate(self.groups, 1):
                self.grid.addWidget(group, 0, index)
            stretches = (0, 3, 2, 2)
        else:
            self.grid.addWidget(self.enabled, 0, 0, 1, 2)
            self.grid.addWidget(self.groups[0], 1, 0, 1, 2)
            self.grid.addWidget(self.groups[1], 2, 0)
            self.grid.addWidget(self.groups[2], 2, 1)
            stretches = (1, 1, 0, 0)
        for index, stretch in enumerate(stretches):
            self.grid.setColumnStretch(index, stretch)
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()


class ChannelConfigurationDialog(QDialog):
    save_requested = Signal(object)
    reload_requested = Signal(object)
    resources_requested = Signal()
    rename_requested = Signal(object)

    def __init__(self, draft, parent=None, *, embedded=False):
        super().__init__(parent, Qt.WindowType.Widget if embedded else Qt.WindowType.Dialog)
        self.embedded = embedded
        self.service_aging = False
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        else:
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(draft.project_name + ' · 通道配置')
        if not embedded:
            self.setMinimumSize(520, 360)
        self.setStyleSheet(f'QDialog {{ background: {BACKGROUND}; }}')
        self.busy, self.dirty, self._loading = False, False, False
        self.resources_refreshing = False
        self.adapters, self.ports = [], []
        self.rows = []
        self.dut_edits = {}
        self.assignments = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*((0, 0, 0, 0) if embedded else (16, 14, 16, 14)))
        if not embedded:
            outer.addWidget(label(draft.project_name + ' · 通道配置', 'title'))
        globals_card = card()
        form = QFormLayout(globals_card)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setHorizontalSpacing(16)
        self.device_ip = QLineEdit()
        self.device_ip.setMaximumWidth(340)
        self.device_ip.setPlaceholderText('样机管理 IPv4')
        self.power_port = QComboBox()
        self.power_port.setEditable(True)
        self.power_port.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.power_port.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.power_port.setMaximumWidth(340)
        self.power_port.setMinimumWidth(0)
        self.show_all_resources = QCheckBox('显示所有网卡和串口')
        power_row = QHBoxLayout()
        power_row.setSpacing(12)
        power_row.addWidget(self.power_port, 1)
        power_row.addWidget(self.show_all_resources)
        form.addRow(label('样机管理 IP'), self.device_ip)
        self.power_label = label('程控电源 COM')
        form.addRow(self.power_label, power_row)
        outer.addWidget(globals_card)
        tools = QHBoxLayout()
        self.all_button = button('全选', lambda: self.select_all(True))
        self.none_button = button('清除选择', lambda: self.select_all(False))
        self.resources_button = button('刷新串口/网卡', self.request_resources)
        tools.addWidget(self.all_button)
        tools.addWidget(self.none_button)
        tools.addStretch()
        tools.addWidget(self.resources_button)
        outer.addLayout(tools)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setObjectName('ConfigurationViewport')
        self.content = QWidget()
        self.content.setObjectName('ConfigurationPage')
        self.content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.rows_layout = QVBoxLayout(self.content)
        self.rows_layout.setContentsMargins(0, 0, 4, 0)
        self.rows_layout.setSpacing(4)
        self.scroll.setWidget(self.content)
        self.assignment_form = QFormLayout()
        self.rows_layout.addLayout(self.assignment_form)
        outer.addWidget(self.scroll, 1)
        self.feedback = ReviewFeedback(role='muted')
        self.feedback.setWordWrap(True)
        outer.addWidget(self.feedback)
        footer = QHBoxLayout()
        self.reload_button = button('重新加载', self.request_reload)
        self.close_button = button('关闭', self.close)
        self.save_button = button('预览并保存', self.request_save, 'primary')
        footer.addWidget(self.reload_button)
        footer.addStretch()
        footer.addWidget(self.close_button)
        footer.addWidget(self.save_button)
        outer.addLayout(footer)
        if embedded:
            for control in (self.reload_button, self.close_button, self.save_button):
                control.hide()
        self.device_ip.textChanged.connect(self._changed)
        self.power_port.currentTextChanged.connect(self._changed)
        self.power_port.currentTextChanged.connect(self._power_port_changed)
        self.show_all_resources.toggled.connect(self._resource_mode_changed)
        self.set_draft(draft)
        if not embedded:
            available = self.screen().availableGeometry()
            self.resize(min(1100, int(available.width() * .9)), min(780, int(available.height() * .9)))

    def _changed(self, *_args):
        if not self._loading:
            self.dirty = True
            self.feedback.setText('有未保存的通道修改')
            self._update_source_ips()

    def _update_source_ips(self):
        for row in self.rows:
            try:
                value = static_ip_for_vlan(row.vlan.currentText(), self.device_ip.text())
            except ValueError:
                value = ''
            row.source.setText(value)

    def set_draft(self, draft):
        assert_gui_thread()
        self._loading = True
        self.draft = draft
        self.device_ip.setText(draft.values['device_ip'])
        self.power_port.setEditText(draft.values['power_serial_port'])
        for row in self.rows:
            self.rows_layout.removeWidget(row)
            row.deleteLater()
        self.rows.clear()
        self.dut_edits.clear()
        self.assignments.clear()
        while self.assignment_form.rowCount():
            self.assignment_form.removeRow(0)
        for dut in draft.values.get('unbound_duts', ()):
            choice = QComboBox()
            choice.addItem('选择通道或移出本批', None)
            choice.addItem('移出本批', 0)
            for number in range(1, 17):
                choice.addItem(f'CH{number:02d}', number)
            self.assignment_form.addRow(dut['label'], choice)
            choice.currentIndexChanged.connect(self._changed)
            self.assignments[dut['dut_id']] = choice
        for channel in draft.values['channels']:
            row = ChannelRow(channel, self.content)
            row.changed.connect(self._changed)
            if not self.embedded:
                row.vlan.textActivated.connect(lambda name, current=row: self._adapter_selected(current, name))
            if 'dut_details' in draft.values:
                row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                row.customContextMenuRequested.connect(lambda point, current=row: self._dut_menu(current, point))
            self.rows_layout.addWidget(row)
            self.rows.append(row)
        self.set_service_aging(draft.values.get('service_aging', False))
        self._loading = False
        self.dirty = False
        self.feedback.setText('')

    def focus_review(self, target):
        marked = [row for row in self.rows if row.number in target.channels]
        if target.channels and not marked:
            return False
        for row in self.rows:
            row.enabled.setStyleSheet(f'color: {DANGER}; font-weight: bold;' if row in marked else '')
            row.enabled.setAccessibleDescription('需要核对的通道' if row in marked else '')
        if target.field == 'device_ip':
            return focus_widget(self.device_ip)
        if target.field == 'power':
            return focus_widget(self.power_port)
        if target.field == 'assignments' or target.field == 'dut' and not marked and self.assignments:
            return focus_widget(self.assignments.get(target.reference) if target.reference else next(iter(self.assignments.values()), None))
        if target.field == 'reload':
            return focus_widget(self.reload_button)
        if target.field == 'save':
            return focus_widget(self.save_button)
        if target.field == 'resources':
            return focus_widget(self.resources_button)
        row = marked[0] if marked else next(iter(self.rows), None)
        if row is None:
            return False
        return focus_widget({'vlan': row.vlan, 'binding': row.vlan, 'port': row.port}.get(target.field, row.enabled))

    def _dut_menu(self, row, point):
        if self.busy or not row.enabled.isChecked():
            return
        menu = QMenu(row)
        for key, title in DUT_CHANNEL_DETAILS:
            action = menu.addAction(title + '…')
            action.triggered.connect(lambda _checked, field=key, caption=title:
                                     self._edit_dut(row.number, field, caption))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(row.mapToGlobal(point))

    def _edit_dut(self, number, key, title):
        if self.busy or not self.rows[number - 1].enabled.isChecked():
            return
        saved = self.draft.values['dut_details'].get(number, {})
        edits = self.dut_edits.get(number, {})
        value, accepted = QInputDialog.getText(self, f'CH{number:02d} · {title}', title,
                                               text=edits.get(key, saved.get(key, '')))
        if accepted:
            self.dut_edits.setdefault(number, {})[key] = value.strip()
            self._changed()

    def select_all(self, selected):
        for row in self.rows:
            row.enabled.setChecked(selected)

    def set_service_aging(self, value):
        self.service_aging = value
        self.power_label.setVisible(not value)
        self.power_port.setVisible(not value)
        self._update_options()

    def set_busy(self, value):
        self.busy = value
        for widget in (self.content, self.device_ip, self.power_port, self.all_button, self.none_button,
            self.show_all_resources, self.reload_button, self.save_button, self.close_button):
            widget.setEnabled(not value)
        self.resources_button.setEnabled(not value and not self.resources_refreshing)

    def request_save(self):
        if self.busy:
            return
        self.set_busy(True)
        self.save_requested.emit(dict(token=self.draft.token, revision=self.draft.revision, **self._input()))

    def _input(self):
        values = dict(
            device_ip=self.device_ip.text().strip(), power_serial_port=self.power_port.currentText().strip(),
            rows=[dict(number=r.number, enabled=r.enabled.isChecked(), vlan_name=r.vlan.currentText().strip(),
                serial_port=r.port.currentText().strip()) for r in self.rows])
        if self.assignments:
            values['assignments'] = [dict(dut_id=dut_id, number=choice.currentData())
                                     for dut_id, choice in self.assignments.items() if choice.currentData() is not None]
        if self.dut_edits:
            values['dut_details'] = [dict(number=number, **edits) for number, edits in self.dut_edits.items()
                                     if self.rows[number - 1].enabled.isChecked()]
        return values

    def _draft_input(self):
        values = self.draft.values
        return dict(device_ip=values['device_ip'], power_serial_port=values['power_serial_port'],
            rows=[dict(number=int(c['section'].rsplit('_', 1)[1]), enabled=c['enabled'],
                       vlan_name=c['vlan_name'], serial_port=c['serial_port']) for c in values['channels']])

    def _adapter_selected(self, row, display_name):
        alias = adapter_alias_from_display(display_name)
        if self.busy or not alias or alias not in self.adapters or adapter_has_numeric_suffix(alias):
            return
        previous = row.previous_vlan
        row.vlan.setEditText(previous)
        self.dirty = self._input() != self._draft_input()
        new_name, accepted = QInputDialog.getText(self, '修改网卡名称',
            f'网卡“{alias}”没有数字尾号，无法自动生成 PC 静态 IP。\n{ADAPTER_NAME_HINT}')
        if accepted:
            if not new_name.strip():
                self.feedback.setText('请输入新网卡名称')
                return
            self.set_busy(True)
            self.rename_requested.emit(dict(token=self.draft.token, revision=self.draft.revision,
                number=row.number, old_name=alias, new_name=new_name.strip()))
        else:
            self.feedback.setText('已取消改名，原选择保留' + ('；有未保存的通道修改' if self.dirty else ''))

    def apply_rename(self, payload):
        prior, base = self._input(), self._draft_input()
        self.set_draft(payload['draft'])
        self._loading = True
        if prior['device_ip'] != base['device_ip']:
            self.device_ip.setText(prior['device_ip'])
        if prior['power_serial_port'] != base['power_serial_port']:
            self.power_port.setEditText(prior['power_serial_port'])
        for row, entered, original in zip(self.rows, prior['rows'], base['rows']):
            if entered['enabled'] != original['enabled']:
                row.enabled.setChecked(entered['enabled'])
            if entered['serial_port'] != original['serial_port']:
                row.port.setEditText(entered['serial_port'])
            if ('channel_' + str(row.number) != payload['section'] and entered['vlan_name'] != original['vlan_name']):
                name = entered['vlan_name']
                row.vlan.setEditText(payload['new'] if adapter_alias_from_display(name).casefold() ==
                                     payload['old'].casefold() else name)
        self._loading = False
        self._update_options()
        self.dirty = self._input() != self._draft_input()
        self._update_source_ips()

    def request_resources(self):
        if not self.busy and not self.resources_refreshing:
            self.resources_requested.emit()

    def set_resources_refreshing(self, value):
        self.resources_refreshing = value
        self.resources_button.setEnabled(not self.busy and not value)

    @staticmethod
    def _options(combo, values):
        previous = combo.currentText()
        changed = list(values) != [combo.itemText(index) for index in range(combo.count())]
        if not changed and combo.currentIndex() == combo.findText(previous):
            return
        editor = combo.lineEdit()
        cursor, selection = editor.cursorPosition(), editor.selectionStart()
        selection_length = len(editor.selectedText())
        with QSignalBlocker(combo):
            if changed:
                combo.clear()
                combo.addItems(values)
            combo.setCurrentIndex(combo.findText(previous))
            combo.setEditText(previous)
            editor.setCursorPosition(cursor)
            if selection >= 0:
                editor.setSelection(selection, selection_length)

    def _power_port_changed(self, _value):
        if not self._loading and not self.show_all_resources.isChecked():
            self._update_channel_options()

    def _resource_mode_changed(self, show_all):
        self._update_options()
        if show_all:
            self.request_resources()

    def _update_options(self):
        show_all = self.service_aging or self.show_all_resources.isChecked()
        self._options(self.power_port, ('', *self.ports) if show_all else POWER_SERIAL_OPTIONS)
        self._update_channel_options()

    def _update_channel_options(self):
        show_all = self.service_aging or self.show_all_resources.isChecked()
        power = self.power_port.currentText()
        adapters = vlan_options_for_power_serial_port(self.adapters, '' if show_all else power)
        ports = self.ports if show_all else serial_options_for_power_serial_port(power)
        for row in self.rows:
            self._options(row.vlan, adapters)
            self._options(row.port, ports)

    def finish_resources(self, values=None, error=''):
        self.set_resources_refreshing(False)
        if values is not None:
            self.adapters, self.ports = values['adapters'], values['ports']
            self._update_options()
            error = '；'.join(values['errors'])
        status = error or '串口/网卡候选已更新'
        self.feedback.setText(f'{status}；有未保存的通道修改' if self.dirty else status)

    def _discard(self, title):
        from PySide6.QtWidgets import QMessageBox
        return not self.dirty or QMessageBox.question(self, title, '放弃本窗口未保存的通道修改？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def request_reload(self):
        if not self.busy and self._discard('重新加载通道'):
            self.set_busy(True)
            self.reload_requested.emit(dict(token=self.draft.token))

    def reject(self):
        if not self.embedded:
            super().reject()

    def closeEvent(self, event):
        if self.embedded:
            event.accept()
        elif self.busy:
            self.feedback.setText('通道操作尚未完成，请等待结果后关闭')
            event.ignore()
        elif not self._discard('关闭通道配置'):
            event.ignore()
        else:
            super().closeEvent(event)
