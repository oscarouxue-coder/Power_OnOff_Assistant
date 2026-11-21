"""Target selection and business fields for the Qt ONU window."""
from copy import deepcopy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QPlainTextEdit,
    QScrollArea, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.models.onu_registration_models import C300CleanupCandidate
from src.services.qt_onu_registration import BUSINESS_FIELDS
from src.ui.qt.theme import button, label


class OnuProvisionPage(QWidget):
    changed = Signal()
    preview_requested = Signal()
    cleanup_requested = Signal()
    save_requested = Signal()

    def __init__(self, settings, family):
        super().__init__()
        self._loading = False
        self._drafts = deepcopy(settings)
        self.family = family
        self.discovery = ''
        self.targets = []
        self.cleanup_job = ''
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        target_panel = QWidget()
        target_layout = QVBoxLayout(target_panel)
        target_layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(label('注册目标', 'section'))
        row.addStretch()
        row.addWidget(button('全选', lambda: self._toggle_selection(True)))
        row.addWidget(button('清除', lambda: self._toggle_selection(False)))
        target_layout.addLayout(row)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(('选择', 'SN', 'PON', 'ONU ID'))
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(100)
        target_layout.addWidget(self.table, 1)
        splitter.addWidget(target_panel)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(108)
        body = QWidget()
        self.form = QFormLayout(body)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.fields = {}
        for key, title in (
            ('onu_id', '起始 ONU ID'), ('onu_type', 'ONU 类型模板'), ('tcont_id', 'T-CONT ID'),
            ('tcont_profile', 'DBA 模板'), ('real_speed', '速率模式'), ('gemport_id', 'GEM Port ID'),
            ('vport_id', 'VPort ID'), ('sn_bind_both', 'SN 双重绑定'), ('services', 'Service ID / VLAN'),
        ):
            if key in ('onu_type', 'tcont_profile', 'real_speed'):
                control = QComboBox()
                control.setEditable(key != 'real_speed')
                if key == 'real_speed':
                    control.addItems(('auto', 'gpon', 'xgpon', 'xgspon'))
                control.currentTextChanged.connect(self._edited)
                control.setMaximumWidth(320)
            elif key == 'services':
                control = QPlainTextEdit()
                control.setMinimumHeight(95)
                control.textChanged.connect(self._edited)
            elif key == 'sn_bind_both':
                control = QCheckBox()
                control.toggled.connect(self._edited)
            else:
                control = self._number(1)
                control.valueChanged.connect(self._edited)
            self.fields[key] = control
            self.form.addRow(title, control)
        scroll.setWidget(body)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        self.allow_cleanup = QCheckBox('配置失败时允许清理所选离线 ONU 并重试')
        self.allow_cleanup.toggled.connect(self._cleanup_toggled)
        layout.addWidget(self.allow_cleanup)
        self.cleanup_row = QWidget()
        controls = QHBoxLayout(self.cleanup_row)
        controls.setContentsMargins(0, 0, 0, 0)
        self.cleanup_candidates = QComboBox()
        self.cleanup_candidates.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cleanup_candidates.setMinimumContentsLength(16)
        self.cleanup_candidates.currentIndexChanged.connect(lambda _: self.changed.emit())
        controls.addWidget(self.cleanup_candidates, 1)
        self.cleanup_lookup = button('查询离线候选…', self.cleanup_requested.emit)
        self.cleanup_lookup.setAutoDefault(False)
        controls.addWidget(self.cleanup_lookup)
        layout.addWidget(self.cleanup_row)
        self.set_cleanup('', [])
        self.write_after_success = QCheckBox('完整验证成功后保存 OLT 启动配置')
        self.write_after_success.toggled.connect(self._edited)
        layout.addWidget(self.write_after_success)
        row = QHBoxLayout()
        row.addStretch()
        self.save_button = button('保存业务参数', self.save_requested.emit)
        self.preview_button = button('生成命令预览', self.preview_requested.emit, 'primary')
        for item in (self.save_button, self.preview_button):
            item.setAutoDefault(False)
            row.addWidget(item)
        layout.addLayout(row)
        self.set_family(family)

    @staticmethod
    def _number(minimum):
        control = QSpinBox()
        control.setRange(minimum, 2147483647)
        control.setMaximumWidth(116)
        return control

    def _edited(self):
        if not self._loading:
            self.set_cleanup('', [])
            self.changed.emit()

    def _cleanup_toggled(self, checked):
        self.cleanup_row.setVisible(self.family == 'C300' and checked)
        self._edited()

    def set_family(self, family):
        self._loading = True
        try:
            if family != self.family:
                self.allow_cleanup.setChecked(False)
            self.set_cleanup('', [])
            self.family = family
            self.allow_cleanup.setVisible(family == 'C300')
            self.cleanup_row.setVisible(family == 'C300' and self.allow_cleanup.isChecked())
            self.write_after_success.setVisible(family == 'C600')
            values = self._drafts[family]
            for name, control in self.fields.items():
                self.form.setRowVisible(control, name in values)
                if name not in values:
                    continue
                value = values[name]
                if name == 'services':
                    control.setPlainText(value)
                elif name in ('onu_type', 'tcont_profile', 'real_speed'):
                    if control.isEditable():
                        control.clear()
                        control.addItem(value)
                    control.setCurrentText(value)
                elif name == 'sn_bind_both':
                    control.setChecked(value)
                else:
                    control.setValue(value)
        finally:
            self._loading = False

    def change_family(self, family):
        self._drafts[self.family] = self.business()
        self.set_family(family)

    def saved(self, settings):
        self._drafts[self.family] = deepcopy(settings[self.family])
        self.set_family(self.family)

    def business(self):
        result = {}
        for name in BUSINESS_FIELDS[self.family]:
            control = self.fields[name]
            if name in ('onu_type', 'tcont_profile', 'real_speed'):
                result[name] = control.currentText()
            elif name == 'services':
                result[name] = control.toPlainText()
            elif name == 'sn_bind_both':
                result[name] = control.isChecked()
            else:
                result[name] = control.value()
        return result

    def set_discovery(self, job, rows):
        if self.discovery == job:
            return
        self.discovery = job
        self.set_cleanup('', [])
        self.targets = []
        self.table.setRowCount(len(rows))
        for row, target in enumerate(rows):
            selected = QCheckBox()
            selected.toggled.connect(lambda checked, onu=target: self._select(checked, onu))
            number = self._number(0)
            number.setSpecialValueText('自动')
            number.valueChanged.connect(self._edited)
            self.table.setCellWidget(row, 0, selected)
            for column, value in enumerate((target['serial_number'], target['pon_interface']), 1):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
            self.table.setCellWidget(row, 3, number)
            self.targets.append((target, selected, number))

    def set_cleanup(self, job, rows):
        if not job and not self.cleanup_job and self.cleanup_candidates.count():
            return
        self.cleanup_job = job
        combo = self.cleanup_candidates
        previous = combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem('选择一台离线 ONU')
            for row in rows:
                candidate = C300CleanupCandidate(**row)
                combo.addItem(candidate.display_text, candidate.onu_interface)
        finally:
            combo.blockSignals(previous)

    def cleanup(self):
        interface = self.cleanup_candidates.currentData()
        if self.family == 'C300' and self.allow_cleanup.isChecked() and self.cleanup_job and interface:
            return dict(query_job=self.cleanup_job, interface=interface)
        return None
    def _select(self, checked, target):
        if checked and self.family == 'C600' and not self.fields['onu_type'].currentText().strip():
            self.fields['onu_type'].setCurrentText(target['model'])
        self._edited()

    def _toggle_selection(self, checked):
        for _, control, _ in self.targets:
            control.setChecked(checked)

    def selection(self):
        rows = []
        for target, checked, number in self.targets:
            if checked.isChecked():
                item = dict(sn=target['serial_number'], pon=target['pon_interface'])
                if number.value():
                    item['id'] = number.value()
                rows.append(item)
        return rows

    def update_templates(self, action, options):
        control = self.fields['onu_type' if action == 'onu_type' else 'tcont_profile']
        current = control.currentText()
        self._loading = True
        try:
            control.clear()
            control.addItems(options)
            control.setCurrentText(current)
        finally:
            self._loading = False
