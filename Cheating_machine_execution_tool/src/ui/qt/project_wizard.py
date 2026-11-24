"""Project details and test plan editor backed by workspace receipts."""
from copy import deepcopy
from uuid import uuid4

from PySide6.QtCore import QRegularExpression, Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator, QTextOption
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
    QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QScrollArea, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from src.models.project import wizard_project_destination
from src.models.project_profile import COLLECTORS, COLLECTOR_LABELS, FEED_COLLECTORS, TEST_TYPES
from .showcase_components import semantic_icon, test_type_symbol
from src.ui.qt.blocker_review import ReviewFeedback, focus_widget
from .theme import button, label
from .window_placement import restore_placement


class ProjectWizard(QDialog):
    draft_requested = Signal()
    commit_requested = Signal()
    TITLES = ('项目与测试类型', '确认项目')
    REVIEW = 1

    def __init__(self, parent=None, *, project_id='', name=''):
        super().__init__(parent)
        self.project_id = project_id
        self.busy = False
        self.setWindowTitle('项目向导' if project_id else '新建项目')
        self.resize(810, 560)
        self.presets = ()
        self.duts = []
        self.environment_managed = False
        self.legacy_optional_steps = []
        self.legacy_environment = None
        self.power_cycles = None
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
        self.page_scroll = QScrollArea()
        self.page_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setWidget(self.pages)
        layout.addWidget(self.page_scroll, 1)
        page = QWidget()
        form = QFormLayout(page)
        self.test_type = QComboBox()
        self.test_type.addItem('请选择测试类型', '')
        for key, title in TEST_TYPES.items():
            self.test_type.addItem(title, key)
            symbol = test_type_symbol(key)
            if symbol:
                self.test_type.setItemIcon(self.test_type.count() - 1, semantic_icon(symbol))
        self.name = QLineEdit(name)
        self.name.setReadOnly(bool(project_id))
        self.directory = QLineEdit()
        form.addRow('测试类型', self.test_type)
        form.addRow('项目名称', self.name)
        if not project_id:
            destination = QHBoxLayout()
            self.directory.setAccessibleName('保存到')
            destination.addWidget(self.directory)
            destination.addWidget(button('选择文件夹…', self._browse))
            form.addRow('保存到', destination)
            self.final_path = QPlainTextEdit()
            self.final_path.setReadOnly(True)
            self.final_path.setTabChangesFocus(True)
            self.final_path.setFixedHeight(60)
            self.final_path.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            self.final_path.setAccessibleName('最终路径')
            form.addRow('最终路径', self.final_path)
            self.name.textChanged.connect(self._update_destination_preview)
            self.directory.textChanged.connect(self._update_destination_preview)
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
        self.hours = self._number()
        self.type_settings = QStackedWidget()
        power = QWidget()
        self.cycles = QLineEdit()
        self.cycles.setReadOnly(True)
        self.cycles.setPlaceholderText('在测试项配置中设置')
        QFormLayout(power).addRow('测试循环次数', self.cycles)
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
        form.addRow(self.type_settings)
        self.pages.addWidget(page)
        self.review = QPlainTextEdit()
        self.review.setReadOnly(True)
        self.review.setAccessibleName('创建或保存前核对')
        self.pages.addWidget(self.review)
        self.feedback = ReviewFeedback(role='muted')
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
        restore_placement(self, None, reference_window=parent)

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
        value = QFileDialog.getExistingDirectory(self, '选择保存位置', self.directory.text())
        if value:
            self.directory.setText(value)

    def _destination(self):
        return wizard_project_destination(self.directory.text().strip(), self.name.text(), self.test_type.currentData())

    def _update_destination_preview(self):
        path, placeholder = '', '—'
        if self.directory.text().strip() and self.name.text().strip() and self.test_type.currentData():
            try:
                path = str(self._destination())
            except ValueError as error:
                placeholder = str(error)
        self.final_path.setPlainText(path)
        self.final_path.setToolTip(path)
        self.final_path.setPlaceholderText(placeholder)

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
        has_plan = current['test_type'] == 'service_aging' and any(current['type_config'].values())
        changes_plan = preset['test_type'] == 'service_aging' and current['type_config'] != preset['type_config']
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

    def _type_changed(self):
        selected = self.test_type.currentData()
        aging = selected == 'service_aging'
        self.type_settings.setCurrentIndex(int(aging))
        self.type_settings.setVisible(bool(selected))
        if not self.project_id:
            self._update_destination_preview()

    @staticmethod
    def _set_source_enabled(source, enabled):
        source.setEnabled(enabled)
        if not enabled:
            source.setCurrentIndex(0)

    def profile(self):
        selected = self.test_type.currentData()
        if selected == 'service_aging':
            collectors = [key for key, box in self.collectors.items() if box.isChecked()]
            config = dict(target_hours=self._quantity(self.hours), collectors=collectors)
            feeds = [key for key in collectors if key == 'dut_presence' or
                     (key in self.collector_sources and self.collector_sources[key].currentData() == 'feed')]
            if feeds:
                config['feed_collectors'] = feeds
        else:
            config = dict(target_cycles=self.power_cycles)
        return dict(schema_version=1, test_type=selected, model=self.model.text().strip(),
                    software_version=self.version.text().strip(), requirements=self.requirements.toPlainText().strip(),
                    duts=deepcopy(self.duts), optional_steps=list(self.legacy_optional_steps),
                    type_config=config, **({'environment_channels': True} if self.environment_managed else {}))

    def draft(self):
        values = dict(name=self.name.text().strip(), parent_directory=self.directory.text().strip(),
                      profile=self.profile(), page=self.pages.currentIndex())
        if self.legacy_environment is not None:
            values['environment'] = deepcopy(self.legacy_environment)
        return values

    def load(self, draft):
        profile = draft.get('profile') or {}
        if not isinstance(profile, dict) or profile.get('schema_version', 1) != 1:
            raise ValueError('向导草稿档案格式或版本不受支持')
        legacy_destination = not self.project_id and 'directory' in draft and 'parent_directory' not in draft
        if not self.project_id:
            self.name.setText(draft.get('name', ''))
            self.directory.setText(draft.get('parent_directory', ''))
        self.test_type.setCurrentIndex(max(0, self.test_type.findData(profile.get('test_type'))))
        self.model.setText(profile.get('model', ''))
        self.version.setText(profile.get('software_version', ''))
        self.requirements.setPlainText(profile.get('requirements', ''))
        self.duts = deepcopy(profile.get('duts', []))
        for dut in self.duts:
            if not dut.get('dut_id'):
                dut['dut_id'] = str(uuid4())
        self.environment_managed = bool(profile.get('environment_channels'))
        self._load_plan(profile)
        self.legacy_optional_steps = list(profile.get('optional_steps', ()))
        self.legacy_environment = deepcopy(draft.get('environment'))
        index = int(draft.get('page', 0))
        page = self.REVIEW if not legacy_destination and index > 0 else 0
        self.pages.setCurrentIndex(page)
        self._page_changed()
        self.remember()
        return legacy_destination

    def load_current(self, payload):
        self.set_power_cycles(payload.get('power_cycles'))
        self.load(dict(profile=payload['profile']))

    def set_power_cycles(self, cycles):
        self.power_cycles = cycles
        self.cycles.setText('' if cycles is None else str(cycles))

    def _load_plan(self, profile):
        config = profile.get('type_config', {})
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
        return any(draft[key] != self._saved[key] for key in ('name', 'parent_directory', 'profile'))

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
        self.pages.setCurrentIndex(0)
        self.feedback.clear()

    def _next(self):
        page = self.pages.currentIndex()
        if page in (0, self.REVIEW):
            if not self.test_type.currentData() or not self.name.text().strip():
                self.pages.setCurrentIndex(0)
                field = self.test_type if not self.test_type.currentData() else self.name
                self.feedback.show_review('请选择测试类型，并填写项目名称', lambda: focus_widget(field))
                return
            if not self.project_id:
                try:
                    self._destination()
                except ValueError as error:
                    self.pages.setCurrentIndex(0)
                    message = str(error) if self.directory.text().strip() else '请选择保存位置'
                    self.feedback.show_review(message, lambda: focus_widget(self.directory))
                    return
        if page == self.REVIEW:
            self.commit_requested.emit()
        else:
            self.feedback.clear()
            self.pages.setCurrentIndex(page + 1)

    def focus_review(self, target):
        self.pages.setCurrentIndex(0)
        if target.field == 'collectors':
            return focus_widget(next(iter(self.collectors.values()), None))
        return focus_widget(getattr(self, target.field, None))

    def _page_changed(self):
        page = self.pages.currentIndex()
        self.page_scroll.verticalScrollBar().setValue(0)
        self.heading.setText(self.TITLES[page])
        self.back.setEnabled(page != 0 and not self.busy)
        self.forward.setText(('保存项目设置' if self.project_id else '创建项目') if page == self.REVIEW else '下一步')
        self.forward.setEnabled(not self.busy)
        if page == self.REVIEW:
            p = self.profile()
            lines = [self.name.text(), self.test_type.currentText()]
            if not self.project_id:
                lines.append('最终路径  ' + (self.final_path.toPlainText() or '请核对保存位置和项目名称'))
            lines.extend((p['model'], p['software_version'], p['requirements']))
            if p['test_type'] == 'power_cycle':
                lines.append('测试循环次数  ' + (self.cycles.text().strip() or '请在测试项配置中设置'))
            else:
                lines.append('目标时长（小时）：' + (self.hours.text().strip() or '未填写'))
                names = [COLLECTOR_LABELS[key] for key in p['type_config']['collectors']]
                lines.append('监测业务：' + ('、'.join(names) if names else '未选择'))
                feeds = p['type_config'].get('feed_collectors', ())
                if feeds:
                    lines.append('现场采集：' + '、'.join(COLLECTOR_LABELS[key] for key in feeds))
            if self.legacy_environment is not None:
                lines.append('将沿用旧草稿中的通道设置。创建后可在项目主界面的「环境配置」核对。')
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
