"""Project setup and preparation UI; storage and execution use workspace receipts."""
from uuid import uuid4

from PySide6.QtCore import QRegularExpression, Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout,
    QHBoxLayout, QHeaderView, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QStackedWidget,
    QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from src.models.project_profile import COLLECTORS, COLLECTOR_LABELS, FEED_COLLECTORS, TEST_TYPES
from src.services.project_preparation import OPTIONAL_STEPS, preparation_plan
from .project_preparation_page import ProjectPreparationPage
from .theme import button, label


DUT_FIELDS = (
    ('label', 'DUT 名称'), ('hardware_id', '设备标识'), ('target_firmware', '目标固件'),
    ('channel', '测试通道'), ('serial_port', '串口'), ('network_adapter', '网卡'),
    ('vlan', 'VLAN'), ('power_channel', '电源通道'), ('other_devices', '其他设备'),
    ('adb_serial', 'ADB 设备标识'),
)


class ProjectWizard(QDialog):
    draft_requested = Signal()
    commit_requested = Signal()
    start_requested = Signal()
    TITLES = ('项目与测试类型', 'DUT 与硬件资源', '准备计划与专属配置', '确认项目', '公共准备')

    def __init__(self, parent=None, *, project_id='', name=''):
        super().__init__(parent)
        self.project_id = project_id
        self.busy = False
        self.setWindowTitle('项目向导' if project_id else '新建项目')
        self.resize(810, 560)
        self.presets = ()
        layout = QVBoxLayout(self)
        self.heading = label('', 'title')
        header = QHBoxLayout()
        header.addWidget(self.heading, 1)
        if project_id:
            self.project_menu = QMenu(self)
            self.project_menu.setToolTipsVisible(True)
            self.save_preset_action = self.project_menu.addAction('保存为型号模板…')
            options = QToolButton()
            options.setText('项目操作')
            options.setMenu(self.project_menu)
            options.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            header.addWidget(options)
        layout.addLayout(header)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        page = QWidget()
        form = QFormLayout(page)
        self.test_type = QComboBox()
        self.test_type.addItem('请选择测试类型', '')
        for key, title in TEST_TYPES.items():
            self.test_type.addItem(title, key)
        self.name = QLineEdit(name)
        self.name.setReadOnly(bool(project_id))
        self.directory = QLineEdit()
        form.addRow('测试类型', self.test_type)
        form.addRow('项目名称', self.name)
        if not project_id:
            destination = QHBoxLayout()
            destination.addWidget(self.directory)
            destination.addWidget(button('选择文件夹…', self._browse))
            form.addRow('项目文件夹', destination)
        self.model = QLineEdit()
        self.version = QLineEdit()
        self.requirements = QPlainTextEdit()
        form.addRow('产品型号', self.model)
        if not project_id:
            presets = QHBoxLayout()
            self.preset_choice = QComboBox()
            self.preset_choice.setAccessibleName('已保存的型号模板及版本')
            self.apply_preset = button('应用模板', self._apply_preset)
            self.preset_choice.currentIndexChanged.connect(
                lambda index: self.apply_preset.setEnabled(index > 0))
            presets.addWidget(self.preset_choice, 1)
            presets.addWidget(self.apply_preset)
            form.addRow('型号模板', presets)
            self.set_presets(())
        form.addRow('软件版本', self.version)
        form.addRow('测试要求', self.requirements)
        self.pages.addWidget(page)

        page = QWidget()
        column = QVBoxLayout(page)
        self.dut_table = QTableWidget(0, len(DUT_FIELDS))
        self.dut_table.setAccessibleName('DUT 身份与资源')
        self.dut_table.setHorizontalHeaderLabels([text for _, text in DUT_FIELDS])
        self.dut_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.dut_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        column.addWidget(self.dut_table)
        row = QHBoxLayout()
        row.addWidget(button('添加 DUT', lambda: self.add_dut()))
        row.addWidget(button('移除所选 DUT', self._remove_dut))
        row.addStretch()
        column.addLayout(row)
        self.pages.addWidget(page)

        page = QWidget()
        column = QVBoxLayout(page)
        self.cycles = self._number()
        self.hours = self._number()
        self.type_settings = QStackedWidget()
        power = QWidget()
        QFormLayout(power).addRow('计划目标轮数', self.cycles)
        aging = QWidget()
        aging_layout = QVBoxLayout(aging)
        duration = QFormLayout()
        duration.addRow('目标时长（小时）', self.hours)
        aging_layout.addLayout(duration)
        self.collectors = {}
        self.collector_sources = {}
        checks = QGridLayout()
        for i, key in enumerate(COLLECTORS):
            title = COLLECTOR_LABELS[key]
            widget = self.collectors[key] = QCheckBox(title)
            row, pair = divmod(i, 2)
            checks.addWidget(widget, row, pair * 2)
            if key == 'dut_presence':
                source = label('现场采集', 'muted')
                source.setAccessibleName(title + '的记录来源：现场采集')
                source.setToolTip('由现场接口提供设备在线与启动证据')
            elif key in FEED_COLLECTORS:
                source = self.collector_sources[key] = QComboBox()
                source.setAccessibleName(title + '的记录来源')
                source.addItem('人工记录', 'manual')
                source.addItem('现场采集', 'feed')
                source.setEnabled(False)
                widget.toggled.connect(lambda enabled, box=source: self._set_source_enabled(box, enabled))
            else:
                source = label('绑定网卡 Ping', 'muted')
            checks.addWidget(source, row, pair * 2 + 1)
        aging_layout.addLayout(checks)
        self.type_settings.addWidget(power)
        self.type_settings.addWidget(aging)
        column.addWidget(self.type_settings)
        column.addWidget(label('可选准备步骤', 'section'))
        choices = QHBoxLayout()
        self.optional = {}
        for key, text in OPTIONAL_STEPS.items():
            choice = self.optional[key] = QCheckBox(text)
            choice.toggled.connect(self._preview_plan)
            choices.addWidget(choice)
        choices.addStretch()
        column.addLayout(choices)
        self.plan_text = label('')
        self.plan_text.setWordWrap(True)
        column.addWidget(self.plan_text)
        column.addStretch()
        self.pages.addWidget(page)
        self.review = QPlainTextEdit()
        self.review.setReadOnly(True)
        self.review.setAccessibleName('创建或保存前核对')
        self.pages.addWidget(self.review)
        self.preparation = ProjectPreparationPage()
        self.pages.addWidget(self.preparation)
        self.feedback = label('', 'muted')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.preset_error = label('', 'muted')
        self.preset_error.setWordWrap(True)
        self.preset_error.hide()
        layout.addWidget(self.preset_error)
        actions = QHBoxLayout()
        self.save_draft = button('保存草稿', self.draft_requested.emit)
        self.blank = button('从空白开始', self._blank)
        self.blank.hide()
        self.back = button('上一步', self._back)
        self.forward = button('下一步', self._next, 'primary')
        self.close_button = button('关闭', self.reject)
        actions.addWidget(self.save_draft)
        actions.addWidget(self.blank)
        actions.addStretch()
        for control in (self.back, self.forward, self.close_button):
            actions.addWidget(control)
        layout.addLayout(actions)
        self.test_type.currentIndexChanged.connect(self._type_changed)
        self.pages.currentChanged.connect(self._page_changed)
        self._type_changed()
        self._page_changed()
        self.remember()

    @staticmethod
    def _number():
        result = QLineEdit()
        result.setPlaceholderText('未填写')
        result.setValidator(QRegularExpressionValidator(QRegularExpression('[0-9]+'), result))
        return result

    @staticmethod
    def _quantity(field):
        text = field.text().strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            # Preserve invalid unfinished input in a draft. Publishing validates the profile.
            return text

    def _browse(self):
        value = QFileDialog.getExistingDirectory(self, '选择空项目文件夹', self.directory.text())
        if value:
            self.directory.setText(value)

    def set_presets(self, presets):
        self.presets = tuple(presets)
        if self.project_id:
            return
        self.preset_choice.clear()
        self.preset_choice.addItem('请选择模板' if self.presets else '暂无型号模板')
        for preset in self.presets:
            title = f"{preset['model']} · {TEST_TYPES[preset['test_type']]} · 版本 {preset['version']}"
            self.preset_choice.addItem(title)
        self.preset_choice.setEnabled(bool(self.presets))
        self.apply_preset.setEnabled(False)

    def _apply_preset(self):
        index = self.preset_choice.currentIndex() - 1
        if self.busy or not 0 <= index < len(self.presets):
            return
        preset = self.presets[index]
        current = self.profile()
        changes_identity = ((current['test_type'] and current['test_type'] != preset['test_type']) or
                            (current['model'] and current['model'] != preset['model']))
        has_plan = bool(current['optional_steps'] or any(current['type_config'].values()))
        changes_plan = (current['optional_steps'] != preset['optional_steps'] or
                        current['type_config'] != preset['type_config'])
        title = self.preset_choice.currentText()
        if changes_identity or (has_plan and changes_plan):
            buttons = QMessageBox.StandardButton
            answer = QMessageBox.question(self, '应用型号模板', f'使用「{title}」替换当前型号、类型和测试方案？',
                                          buttons.Yes | buttons.No, buttons.No)
            if answer != buttons.Yes:
                return
        self.test_type.setCurrentIndex(self.test_type.findData(preset['test_type']))
        self.model.setText(preset['model'])
        self._load_plan(preset)
        self.feedback.setText('已应用「' + title + '」，可继续修改或保存草稿')

    def add_dut(self, values=None):
        values = values or {}
        row = self.dut_table.rowCount()
        self.dut_table.insertRow(row)
        for col, (field, _) in enumerate(DUT_FIELDS):
            value = values.get(field)
            item = QTableWidgetItem('' if value is None else str(value))
            if col == 0:
                item.setData(Qt.ItemDataRole.UserRole, values.get('dut_id') or str(uuid4()))
            self.dut_table.setItem(row, col, item)
        self.dut_table.setCurrentCell(row, 0)

    def _remove_dut(self):
        row = self.dut_table.currentRow()
        if row >= 0:
            self.dut_table.removeRow(row)

    def _type_changed(self):
        aging = self.test_type.currentData() == 'service_aging'
        self.type_settings.setCurrentIndex(int(aging))
        self.dut_table.setColumnHidden(7, aging)
        self._preview_plan()

    @staticmethod
    def _set_source_enabled(source, enabled):
        source.setEnabled(enabled)
        if not enabled:
            source.setCurrentIndex(0)

    def _preview_plan(self):
        selected = self.test_type.currentData()
        if selected:
            steps = preparation_plan({'test_type': selected,
                                      'optional_steps': [k for k, box in self.optional.items() if box.isChecked()]})
            self.plan_text.setText(' → '.join(step['label'] for step in steps))
        else:
            self.plan_text.clear()

    def profile(self):
        selected = self.test_type.currentData()
        duts = []
        for row in range(self.dut_table.rowCount()):
            dut = {field: self.dut_table.item(row, col).text().strip() for col, (field, _) in enumerate(DUT_FIELDS)}
            if not dut['adb_serial']:
                del dut['adb_serial']
            dut['dut_id'] = self.dut_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            channel = dut['channel']
            dut['channel'] = int(channel) if channel.isascii() and channel.isdecimal() and len(channel) <= 2 else channel or None
            duts.append(dut)
        if selected == 'service_aging':
            collectors = [key for key, box in self.collectors.items() if box.isChecked()]
            config = dict(target_hours=self._quantity(self.hours), collectors=collectors)
            feeds = [key for key in collectors if key == 'dut_presence' or
                     (key in self.collector_sources and self.collector_sources[key].currentData() == 'feed')]
            if feeds:
                config['feed_collectors'] = feeds
        else:
            config = dict(target_cycles=self._quantity(self.cycles))
        return dict(schema_version=1, test_type=selected, model=self.model.text().strip(),
                    software_version=self.version.text().strip(), requirements=self.requirements.toPlainText().strip(),
                    duts=duts, optional_steps=[key for key, box in self.optional.items() if box.isChecked()],
                    type_config=config)

    def draft(self):
        return dict(name=self.name.text().strip(), directory=self.directory.text().strip(),
                    profile=self.profile(), page=self.pages.currentIndex())

    def load(self, draft):
        profile = draft.get('profile') or {}
        if not isinstance(profile, dict) or profile.get('schema_version', 1) != 1:
            raise ValueError('向导草稿档案格式或版本不受支持')
        if not self.project_id:
            self.name.setText(draft.get('name', ''))
            self.directory.setText(draft.get('directory', ''))
        self.test_type.setCurrentIndex(max(0, self.test_type.findData(profile.get('test_type'))))
        self.model.setText(profile.get('model', ''))
        self.version.setText(profile.get('software_version', ''))
        self.requirements.setPlainText(profile.get('requirements', ''))
        self.dut_table.setRowCount(0)
        for dut in profile.get('duts', ()):
            self.add_dut(dut)
        self._load_plan(profile)
        page = max(0, min(3, int(draft.get('page', 0))))
        self.pages.setCurrentIndex(page)
        self._page_changed()
        self.remember()

    def _load_plan(self, profile):
        for key, box in self.optional.items():
            box.setChecked(key in profile.get('optional_steps', ()))
        config = profile.get('type_config', {})
        self.cycles.setText('' if config.get('target_cycles') is None else str(config['target_cycles']))
        self.hours.setText('' if config.get('target_hours') is None else str(config['target_hours']))
        for key, box in self.collectors.items():
            box.setChecked(key in config.get('collectors', ()))
        for key, source in self.collector_sources.items():
            chosen = self.collectors[key].isChecked() and key in config.get('feed_collectors', ())
            source.setCurrentIndex(source.findData('feed' if chosen else 'manual'))

    def remember(self):
        self._saved = self.draft()

    def has_unsaved_inputs(self):
        draft = self.draft()
        return any(draft[key] != self._saved[key] for key in ('name', 'directory', 'profile'))

    def _blank(self):
        buttons = QMessageBox.StandardButton
        answer = QMessageBox.question(self, '从空白开始', '清空窗口中的输入？之前保存的向导草稿仍可在重新打开时恢复。',
                                      buttons.Yes | buttons.No, buttons.No)
        if answer == buttons.Yes:
            self.load({})
            self.set_busy(False)
            self.blank.hide()
            self.feedback.setText('已开始空白向导')

    def _back(self):
        self.pages.setCurrentIndex(0 if self.pages.currentIndex() == 4 else self.pages.currentIndex() - 1)
        self.feedback.clear()

    def _next(self):
        page = self.pages.currentIndex()
        if page in (0, 3) and (not self.test_type.currentData() or not self.name.text().strip() or
                               (not self.project_id and not self.directory.text().strip())):
            self.pages.setCurrentIndex(0)
            self.feedback.setText('请选择测试类型，并填写项目名称和文件夹')
            return
        if page == 3:
            self.commit_requested.emit()
        elif page == 4:
            self.start_requested.emit()
        else:
            self.feedback.clear()
            self.pages.setCurrentIndex(page + 1)

    def _page_changed(self):
        page = self.pages.currentIndex()
        self.heading.setText(self.TITLES[page])
        self.save_draft.setVisible(page < 4)
        self.back.setEnabled(page != 0 and not self.busy)
        self.back.setText('项目设置' if page == 4 else '上一步')
        self.forward.setText(('保存项目设置' if self.project_id else '创建项目') if page == 3 else
                             '确认并启动…' if page == 4 else '下一步')
        self.forward.setEnabled(not self.busy and (page != 4 or (
            self.preparation.snapshot.get('ready', False)
            and not self.preparation.snapshot.get('dirty', False))))
        if page == 3:
            p = self.profile()
            lines = [self.name.text(), self.test_type.currentText(), self.directory.text(), p['model'], p['software_version'],
                     p['requirements'], self.plan_text.text()]
            if p['test_type'] == 'power_cycle':
                lines.append('计划目标轮数：' + str(p['type_config']['target_cycles'] or '未填写'))
            else:
                lines.append('目标时长（小时）：' + str(p['type_config']['target_hours'] or '未填写'))
                names = [COLLECTOR_LABELS[key] for key in p['type_config']['collectors']]
                lines.append('监测业务：' + ('、'.join(names) if names else '未选择'))
                feeds = p['type_config'].get('feed_collectors', ())
                if feeds:
                    lines.append('现场采集：' + '、'.join(COLLECTOR_LABELS[key] for key in feeds))
            lines.extend(f"{d['label']} · " + ' / '.join(str(d[k]) for k, _ in DUT_FIELDS[1:] if d.get(k)) for d in p['duts'])
            self.review.setPlainText('\n'.join(filter(None, lines)))

    def set_busy(self, value):
        self.busy = value
        self.pages.setEnabled(not value)
        self.save_draft.setEnabled(not value)
        self.blank.setEnabled(not value)
        self.close_button.setEnabled(not value)
        self._page_changed()

    def may_close(self):
        if self.busy:
            return False
        if not self.has_unsaved_inputs():
            return True
        buttons = QMessageBox.StandardButton
        return QMessageBox.question(self, '关闭项目向导', '放弃本次未保存的输入？',
                                    buttons.Yes | buttons.No, buttons.No) == buttons.Yes

    def reject(self):
        if self.may_close():
            super().reject()

    def closeEvent(self, event):
        if self.may_close():
            super().reject()
            event.accept()
        else:
            event.ignore()
