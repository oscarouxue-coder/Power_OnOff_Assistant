"""Local model account editor used by the Qt diagnostics entry points."""
from dataclasses import replace
from uuid import uuid4

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QMenu, QMessageBox, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from src.models.ai_diagnostics import PROVIDERS, ProviderProfile
from src.ui.qt.blocker_review import ReviewFeedback, focus_widget
from src.ui.qt.theme import button, label


class ModelSettingsDialog(QDialog):
    action_requested = Signal(str, object)

    def __init__(self, project, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(project.name + ' · AI 模型连接')
        self.project_id = project.project_id
        self.project_name = project.name
        self.view = None
        self.base = ProviderProfile()
        self.draft = True
        self.busy = False
        self.resize(720, 610)
        layout = QVBoxLayout(self)
        layout.addWidget(label('AI 模型连接 · ' + project.name, 'title'))
        self.panel = QWidget()
        body = QVBoxLayout(self.panel)
        accounts = QHBoxLayout()
        self.accounts = QComboBox()
        self.accounts.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.accounts.setAccessibleName('共享模型配置')
        self.accounts.currentIndexChanged.connect(self._select)
        accounts.addWidget(label('共享模型配置'))
        accounts.addWidget(self.accounts, 1)
        self.account_menu = QMenu(self)
        self.account_menu.addAction('新增配置', lambda: self._draft(ProviderProfile()))
        self.copy_action = self.account_menu.addAction('复制当前配置', self._copy)
        self.delete_action = self.account_menu.addAction('删除共享配置…', self._delete)
        menu_button = button('配置 ▾')
        menu_button.setMenu(self.account_menu)
        accounts.addWidget(menu_button)
        body.addLayout(accounts)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.fields = {key: QLineEdit() for key in ('name', 'base_url', 'timeout', 'max_output', 'context_tokens')}
        self.fields['provider'] = self.provider = QComboBox()
        self.provider.addItems(tuple(PROVIDERS))
        self.provider.currentTextChanged.connect(self._provider_changed)
        self.fields['protocol'] = self.protocol = QComboBox()
        self.protocol.addItems(('chat_completions', 'responses'))
        self.fields['model'] = self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.model.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for key in ('timeout', 'max_output', 'context_tokens'):
            self.fields[key].setMaximumWidth(210)
        for key, title in (('name', '配置名称'), ('provider', '模型厂商'), ('base_url', 'API 地址'),
                           ('protocol', '接口协议'), ('model', '模型 ID'), ('timeout', '请求超时（秒）'),
                           ('max_output', '最大输出 Token'), ('context_tokens', '上下文上限 Token')):
            form.addRow(title, self.fields[key])
            self.fields[key].setAccessibleName(title)
        self.fields['context_tokens'].setPlaceholderText('留空自动识别')
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText('留空保留当前账号和地址绑定的密钥')
        form.addRow('API 密钥', self.key)
        self.capacity = label('', 'muted')
        self.capacity.setWordWrap(True)
        self.fields['base_url'].textChanged.connect(self._update_capacity)
        self.fields['context_tokens'].textChanged.connect(self._update_capacity)
        self.model.currentTextChanged.connect(self._update_capacity)
        body.addLayout(form)
        body.addWidget(self.capacity)
        self.source_ip = ''
        self.source = button('指定出口 IP…', lambda: self._request('ai_model_sources'))
        body.addWidget(self.source, alignment=Qt.AlignmentFlag.AlignLeft)
        body.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.panel)
        layout.addWidget(scroll, 1)

        self.feedback = ReviewFeedback(role='muted')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        buttons = QHBoxLayout()
        self.refresh_button = button('刷新模型', lambda: self._save('ai_model_refresh'))
        self.test_button = button('测试连接与工具能力', lambda: self._save('ai_model_test'))
        self.save_button = button('保存并选择', lambda: self._save('ai_model_save'), 'primary')
        self.close_button = button('关闭', self.close)
        for control in (self.refresh_button, self.test_button, self.save_button, self.close_button):
            buttons.addWidget(control)
        layout.addLayout(buttons)
        self.set_busy(True)

    def set_busy(self, busy):
        self.busy = busy
        editable = not busy and self.view is not None
        self.panel.setEnabled(editable)
        for control in (self.refresh_button, self.test_button, self.save_button):
            control.setEnabled(editable)
        if busy:
            self.feedback.setText('正在处理模型配置…')

    def _request(self, operation, *args):
        if not self.busy:
            self.action_requested.emit(operation, args)

    def _select(self, *_):
        identifier = self.accounts.currentData()
        if identifier:
            self._request('ai_model_select', identifier)

    def _provider_changed(self, provider):
        if self.busy or not provider:
            return
        if not self.draft and provider != self.base.provider:
            self._request('ai_model_provider', provider)
        elif self.draft:
            address, protocol = PROVIDERS[provider]
            self.fields['base_url'].setText(address)
            self.protocol.setCurrentText(protocol)
            self.model.clear()
            self.fields['context_tokens'].clear()
            self.key.clear()
            self._update_capacity()

    def _draft(self, profile):
        self.show_view(replace(self.view, profile=profile, draft=True, context_tokens=profile.context_tokens,
                               context_source='手动填写' if profile.context_tokens else '', notice='', model_ids=()))

    def _copy(self):
        self._draft(replace(self.base, id=uuid4().hex, name=self.base.name + ' 副本',
                            capability='未验证', tested_fingerprint='', credential_revision=''))

    def _delete(self):
        if self.draft or self.busy:
            return
        base = self.base
        answer = QMessageBox.question(self, '删除共享模型配置',
            f'删除「{base.name}」及其加密密钥？使用这项共享配置的其他项目也将无法继续选择它。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._request('ai_model_delete', base)

    def _save(self, operation):
        values = {key: (widget.currentText() if isinstance(widget, QComboBox) else widget.text())
                  for key, widget in self.fields.items()}
        self._request(operation, self.base, self.draft, dict(values, source_ip=self.source_ip), self.key.text())

    def show_view(self, view):
        self.view, self.base, self.draft = view, view.profile, view.draft
        with QSignalBlocker(self.accounts), QSignalBlocker(self.provider):
            self.accounts.clear()
            if view.draft:
                self.accounts.addItem('未保存草稿', '')
            for profile in view.profiles:
                self.accounts.addItem(f'{profile.name} | {profile.provider} | {profile.model}', profile.id)
            self.accounts.setCurrentIndex(0 if view.draft else self.accounts.findData(view.profile.id))
            self.model.clear()
            self.model.addItems(view.model_ids)
            for key, widget in self.fields.items():
                value = getattr(view.profile, key)
                if isinstance(widget, QComboBox):
                    widget.setCurrentText(value)
                else:
                    widget.setText('' if key == 'context_tokens' and not value else str(value))
        self.key.clear()
        self.copy_action.setEnabled(not view.draft)
        self.delete_action.setEnabled(not view.draft)
        self.set_source(view.profile.source_ip)
        self._update_capacity()
        self.set_busy(False)
        self.feedback.show_review(view.notice or view.profile.capability,
                                  (lambda: focus_widget(self.fields[view.review_field])) if view.review_field else None)

    def focus_review(self, target):
        widget = self.fields.get(target.field)
        return focus_widget(widget if widget is not None else getattr(self, target.field, None))

    def set_source(self, source):
        self.source_ip = source
        self.source.setText('出口 IP：' + source if source else '指定出口 IP…')

    def _update_capacity(self, *_):
        if self.view is None:
            return
        raw = self.fields['context_tokens'].text().strip()
        if raw:
            try:
                count = int(raw)
                if count <= 0:
                    raise ValueError
            except ValueError:
                self.capacity.setText('上下文上限须为正整数或留空')
            else:
                self.capacity.setText(f'上下文 {count} Token · 手动填写')
        elif (self.fields['base_url'].text().strip().rstrip('/') == self.base.base_url.rstrip('/')
              and self.model.currentText().strip() == self.base.model
              and self.view.context_tokens and not self.base.context_tokens):
            self.capacity.setText(f'上下文 {self.view.context_tokens} Token · {self.view.context_source}')
        else:
            self.capacity.setText('上下文容量未知 · 使用原自动预算')
