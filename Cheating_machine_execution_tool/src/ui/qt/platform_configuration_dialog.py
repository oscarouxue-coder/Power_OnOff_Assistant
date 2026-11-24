"""Local credential editor for DingTalk and Feishu."""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLineEdit, QMenu, QMessageBox, QVBoxLayout

from src.services.qt_imported_connections import PLATFORM_NAMES
from src.services.qt_platform_configuration import FIELDS
from src.ui.qt.blocker_review import ReviewFeedback
from src.ui.qt.theme import button, label


FIELD_LABELS = {
    'client_id': 'Client ID / AppKey', 'client_secret': 'Client Secret（留空保留）',
    'robot_code': 'Robot Code', 'webhook': '群 Webhook', 'secret': '群 Webhook 加签密钥',
    'ai_card_template_id': 'AI 卡片模板 ID', 'app_id': 'App ID', 'app_secret': 'App Secret（留空保留）',
}


class PlatformConfigurationDialog(QDialog):
    def __init__(self, workspace, project, kind):
        super().__init__(workspace.window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setModal(True)
        self.workspace, self.project_id, self.kind = workspace, project.project_id, kind
        self.setWindowTitle(f'{PLATFORM_NAMES[kind]}应用配置 · {project.name}')
        self.request = None
        self.view = None
        self.binding = None
        self.trial_busy = False
        self.close_after_cancel = False
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.poll)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.fields = {}
        for key in FIELDS[kind]:
            field = QLineEdit()
            if key in ('client_secret', 'webhook', 'secret', 'app_secret'):
                field.setEchoMode(QLineEdit.EchoMode.Password)
            self.fields[key] = field
            form.addRow(FIELD_LABELS[key], field)
        layout.addLayout(form)
        self.feedback = ReviewFeedback(role='muted')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        actions = QHBoxLayout()
        actions.addStretch()
        self.save_button = button('保存应用配置', self.save, 'primary')
        actions.addWidget(self.save_button)
        self.bind_button = button('开始绑定群…', self.change_binding)
        actions.addWidget(self.bind_button)
        self.more = button('更多操作 ▾')
        menu = QMenu(self.more)
        self.cancel_binding_action = menu.addAction('取消当前绑定', self.cancel_binding)
        self.trial_action = menu.addAction('发送飞书测试消息…', self.start_trial)
        self.trial_action.setVisible(kind == 'feishu')
        self.notify_action = menu.addAction('启用飞书挂测通知…', self.change_notifications)
        self.notify_action.setVisible(kind == 'feishu')
        self.direct_actions = {}
        for channel, title in (('group', '群聊直连'), ('p2p', '单聊直连')):
            if channel == 'group' or kind == 'feishu':
                action = menu.addAction(title, lambda checked=False, mode=channel: self.change_direct(mode))
                self.direct_actions[channel] = (action, title)
        self.more.setMenu(menu)
        actions.addWidget(self.more)
        self.close_button = button('关闭', self.close)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        self.resize(560, self.sizeHint().height())
        for field in self.fields.values():
            field.textChanged.connect(self._sync)
        self.request = workspace.submit('platform_configuration_open', self.project_id, self.kind)
        self._sync()

    def _sync(self):
        settling = self.request is not None or self.trial_busy
        editable = not settling and self.view is not None and not self.view['blocked'] and not self.binding
        for field in self.fields.values():
            field.setEnabled(editable)
        self.save_button.setEnabled(editable)
        changed = self.view is not None and self.view['values'] != self._values()
        self.bind_button.setText('确认群绑定…' if self.binding and self.binding['candidate'] else '开始绑定群…')
        self.bind_button.setEnabled(not settling and (bool(self.binding['candidate']) if self.binding else editable and not changed))
        self.cancel_binding_action.setEnabled(not settling and self.binding is not None)
        self.trial_action.setEnabled(not settling and self.binding is None and self.view is not None
                                     and self.view['trial'] is not None)

        for channel, (action, title) in self.direct_actions.items():
            enabled = bool(self.view and self.view['direct'][channel])
            action.setText(('停用' if enabled else '启用') + title + '…')
            action.setEnabled(not settling and self.binding is None and self.view is not None
                              and not self.view['mode_blocked'] and not changed)
        notify_enabled = bool(self.view and self.view['notifications_enabled'])
        self.notify_action.setText('停用飞书挂测通知…' if notify_enabled else '启用飞书挂测通知…')
        self.notify_action.setEnabled(not settling and self.binding is None and self.view is not None
                                      and (notify_enabled or self.view['trial'] is not None))

    def _values(self):
        return {key: field.text() for key, field in self.fields.items()}

    def save(self):
        if not self.save_button.isEnabled():
            return
        message = ('保存后仍保持停用。钉钉配置会同时更新本项目草稿里的通知 Webhook 和签名密钥。是否保存？'
                   if self.kind == 'dingtalk' else '保存后仍保持停用。更换凭据会清除旧群绑定。是否保存？')
        choice = QMessageBox.question(self, '保存应用配置', message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if choice == QMessageBox.StandardButton.Yes:
            self.request = self.workspace.submit('platform_configuration_save', self.project_id, self.kind,
                                                  self.view['revision'], self._values())
            self._sync()

    def _binding_request(self, operation, *arguments):
        if self.request is None:
            self.request = self.workspace.submit(operation, self.project_id, self.kind, *arguments)
            self._sync()

    def change_binding(self):
        if not self.bind_button.isEnabled():
            return
        if self.binding is None:
            self._binding_request('platform_binding_start', self.view['revision'])
            return
        candidate = self.binding['candidate']
        self.timer.stop()
        try:
            choice = QMessageBox.question(self, '确认群绑定',
                f'群：{candidate["name"]}\n群 ID：{candidate["group"]}\n是否绑定到此群？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        finally:
            self.timer.start()
        if choice == QMessageBox.StandardButton.Yes:
            self._binding_request('platform_binding_confirm', candidate)

    def poll(self):
        if self.binding is not None:
            self._binding_request('platform_binding_state')
        elif self.trial_busy:
            self._binding_request('platform_trial_state')

    def cancel_binding(self):
        if self.binding is not None:
            self._binding_request('platform_binding_cancel')

    def start_trial(self):
        if not self.trial_action.isEnabled():
            return
        trial = self.view['trial']
        answer = QMessageBox.question(self, '发送飞书测试消息',
            f'消息项目名：{trial["project"]}\n群 ID：{trial["group"]}\n是否发送一条测试消息？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._binding_request('platform_trial_start', self.view['revision'], trial)

    def change_direct(self, channel):
        action, title = self.direct_actions[channel]
        if not action.isEnabled():
            return
        enable = not self.view['direct'][channel]
        if enable:
            audience = ('绑定群中的成员' if channel == 'group' else '本飞书应用可用范围内的企业成员')
            permission = ('新会话默认完全访问，当前范围内会跳过常规逐项批准。' if self.kind == 'feishu' else
                          '新会话默认帮我批准，危险操作须具体批准。')
            text = (f'{audience}将可向机器人请求当前已授权项目的 AI 排障。{permission}'
                    '回复将发回原聊天，资源占用和停止保护继续生效。是否启用？')
        else:
            text = '停止此类型的新消息和排障会话，已独立准入的业务继续按原流程运行。是否停用？'
        answer = QMessageBox.question(self, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._binding_request('platform_direct_set', self.view['revision'], channel, enable)

    def change_notifications(self):
        if not self.notify_action.isEnabled():
            return
        enabled = not self.view['notifications_enabled']
        target = self.view['trial']
        message = (f'挂测结果将发送到飞书群 {target["group"]}。是否启用？' if enabled
                   else '是否停用飞书自动挂测通知？')
        answer = QMessageBox.question(self, '飞书挂测通知', message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._binding_request('platform_notifications_set', self.view['revision'], enabled)

    def handle_result(self, result):
        if result.identifier != self.request:
            return
        self.request = None
        if result.error:
            if result.operation == 'platform_binding_state':
                self.timer.stop()
                self.binding = None
            if result.operation == 'platform_trial_state':
                self.trial_busy = False
                self.timer.stop()
            self.close_after_cancel = False
            self.workspace.blocker_review.inline(self, result, self.project_id)
            self._sync()
            return
        if result.operation in ('platform_trial_start', 'platform_trial_state'):
            self.trial_busy = result.payload['busy']
            self.feedback.setText(result.payload['message'])
            if self.trial_busy:
                self.timer.start()
            else:
                self.timer.stop()
            self._sync()
            return
        if result.operation in ('platform_binding_start', 'platform_binding_state'):
            state = result.payload
            self.binding = state if state['code'] else None
            if self.binding is None:
                self.timer.stop()
                self.feedback.setText('群绑定已结束或过期。')
            else:
                self.timer.start()
                self.feedback.setText('已收到绑定申请，请核对群 ID。' if state['candidate'] else
                    f'请在目标群 @机器人发送：绑定 {state["code"]}（五分钟内有效）')
            self._sync()
            return
        self.timer.stop()
        self.binding = None
        self.view = result.payload
        for key, value in self.view['values'].items():
            self.fields[key].setText(value)
        details = self.view['blocked'] or ('已绑定群：' + self.view['group'] if self.view['group'] else '尚未绑定群')
        receipt = {'platform_configuration_save': '已保存。', 'platform_binding_confirm': '已确认群绑定。',
                   'platform_binding_cancel': '已取消群绑定。'}
        self.feedback.setText(receipt.get(result.operation, '') + details)
        self._sync()
        if self.close_after_cancel:
            self.done(QDialog.DialogCode.Rejected)

    def _can_close(self):
        if self.request is not None or self.trial_busy:
            return False
        if self.binding is not None:
            self.close_after_cancel = True
            self.cancel_binding()
            return False
        if self.view is None or self.view['values'] == self._values():
            return True
        return QMessageBox.question(self, '放弃未保存的修改', '是否放弃应用配置中的未保存输入？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def reject(self):
        if self._can_close():
            super().reject()

    def closeEvent(self, event):
        if self._can_close():
            self.done(QDialog.DialogCode.Rejected)
        else:
            event.ignore()
