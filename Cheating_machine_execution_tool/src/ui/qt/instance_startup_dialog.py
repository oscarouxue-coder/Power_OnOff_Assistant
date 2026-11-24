"""Edit next-start settings without connecting the current workspace to a gateway."""
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QSpinBox, QVBoxLayout)

from src.ui.qt.blocker_review import ReviewFeedback, focus_widget
from src.ui.qt.theme import button, label


class InstanceStartupDialog(QDialog):
    def __init__(self, parent, project):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('下次启动配置')
        self.project = project
        self.request = self.review = None
        self.loaded_once = False
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.mode = QComboBox()
        self.mode.addItem('普通直接接入', 'direct')
        self.mode.addItem('统一网关接入', 'gateway')
        form.addRow('下次启动模式', self.mode)
        row = QHBoxLayout()
        self.slot = QSpinBox()
        self.slot.setRange(1, 64)
        row.addWidget(self.slot)
        self.reload = button('重新读取槽位', lambda: self.read(self.slot.value()))
        row.addWidget(self.reload)
        row.addStretch()
        form.addRow('实例槽位', row)
        self.identity = QPlainTextEdit()
        self.identity.setReadOnly(True)
        self.identity.setMaximumHeight(4 * self.identity.fontMetrics().lineSpacing() + 8)
        form.addRow('实例与成员范围', self.identity)
        self.url = QLineEdit()
        form.addRow('网关地址', self.url)
        self.vpn = QCheckBox('已使用受保护的 VPN 网络')
        form.addRow(self.vpn)
        lists = QHBoxLayout()
        layout.addLayout(lists, 1)
        self.channels, self.capabilities = QListWidget(), QListWidget()
        for title, widget, stretch in (('允许通道', self.channels, 1), ('允许业务能力', self.capabilities, 3)):
            column = QVBoxLayout()
            column.addWidget(label(title))
            widget.setAccessibleName(title)
            column.addWidget(widget)
            lists.addLayout(column, stretch)
        self.feedback = ReviewFeedback(role='muted')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        footer = QHBoxLayout()
        footer.addStretch()
        self.save = button('保存启动配置', self.save_settings, 'primary')
        footer.addWidget(self.save)
        footer.addWidget(button('关闭', self.close))
        layout.addLayout(footer)
        self.slot.valueChanged.connect(self.read)
        self.mode.currentIndexChanged.connect(self.sync)
        self.channels.itemChanged.connect(self.sync)
        self.capabilities.itemChanged.connect(self.sync)
        self.resize(620, 510)
        self.sync()

    def submit(self, operation, *args):
        self.request = self.parent().workspace.submit(operation, self.project, *args)
        self.feedback.setText('正在处理…' if self.request is not None else '工作区忙，请重试')
        self.sync()

    def read(self, number):
        self.review = None
        self.url.clear()
        self.identity.clear()
        self.channels.clear()
        self.capabilities.clear()
        self.vpn.setChecked(False)
        self.submit('gateway_startup_read', number)

    @staticmethod
    def fill(widget, choices, selected):
        first_checked = None
        with QSignalBlocker(widget):
            widget.clear()
            for key, title in choices:
                item = QListWidgetItem(title, widget)
                item.setToolTip(title)
                item.setData(Qt.ItemDataRole.UserRole, key)
                item.setCheckState(Qt.CheckState.Checked if key in selected else Qt.CheckState.Unchecked)
                if first_checked is None and key in selected:
                    first_checked = item
        if first_checked is not None:
            widget.scrollToItem(first_checked)

    @staticmethod
    def checked(widget):
        return [widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(widget.count())
                if widget.item(i).checkState() == Qt.CheckState.Checked]

    def sync(self):
        ready = self.review is not None and self.request is None
        gateway = self.mode.currentData() == 'gateway'
        self.slot.setEnabled(self.request is None)
        self.reload.setEnabled(self.request is None)
        self.mode.setEnabled(ready)
        for control in (self.url, self.vpn, self.channels, self.capabilities):
            control.setEnabled(ready and gateway)
        self.save.setEnabled(bool(ready and (not gateway or self.review['slot'] and self.review['slot']['paired']
            and self.checked(self.channels) and self.checked(self.capabilities))))

    def save_settings(self):
        if not self.save.isEnabled():
            return
        mode, number = self.mode.currentData(), self.slot.value()
        channels, capabilities = self.checked(self.channels), self.checked(self.capabilities)
        if mode == 'gateway':
            details = (f"槽位 {number} · {self.review['slot']['instance_id']}\n网关：{self.url.text().strip()}"
                       f"\n受保护的 VPN：{'是' if self.vpn.isChecked() else '否'}"
                       f"\n通道：{', '.join(map(str, channels))}\n业务能力：{', '.join(capabilities)}")
            removed = sorted(set(self.review['slot']['capability_ids']) - set(capabilities))
            if removed:
                details += '\n移除的能力：' + ', '.join(removed)
            if not self.parent().confirm('确认本地接入范围', details + '\n下次启动生效。远程新会话仍需本地批准。'):
                return
        self.submit('gateway_startup_save', self.review, mode, self.url.text().strip(),
                    self.vpn.isChecked(), channels, capabilities)

    def show_result(self, result):
        if result.identifier != self.request:
            return
        self.request = None
        if result.error:
            target = getattr(result, 'review', None)
            self.feedback.show_review(result.error, (lambda: focus_widget(self.reload)) if target else None)
        elif result.operation == 'gateway_startup_save':
            self.parent().feedback.setText('下次启动配置已保存')
            self.accept()
            return
        else:
            self.review = result.payload
            row = self.review['slot']
            with QSignalBlocker(self.slot):
                self.slot.setValue(self.review['number'])
            if not self.loaded_once:
                self.mode.setCurrentIndex(self.mode.findData(self.review['startup']['mode']))
                self.loaded_once = True
            if row is None:
                self.feedback.show_review(self.review['slot_error'], lambda: focus_widget(self.slot))
                self.sync()
                return
            self.url.setText(row['url'])
            self.vpn.setChecked(row['vpn'])
            scopes = '；'.join(f"{s['platform']} / {s['chat']} · {', '.join(s['members'])}" for s in row['scopes'])
            self.identity.setPlainText(row['instance_id'] + ('\n' + scopes if scopes else ''))
            self.fill(self.channels, [(n, str(n)) for n in range(1, 17)], row['channel_ids'])
            self.fill(self.capabilities, [(k, f'{name} · {k}') for k, name in self.review['options']], row['capability_ids'])
            status = '已读取待重启的范围' if row['pending'] else '已配对' if row['paired'] else '此槽位尚未配对'
            if row['channel_ids']:
                status += ' · 通道 ' + ', '.join(map(str, row['channel_ids']))
            if not self.review['options']:
                status += '。要选择业务能力，请从已打开的项目进入启动配置'
            if self.review['invalid_digest']:
                status += '。原启动配置损坏，请核对模式后保存'
            if self.review['invalid_digest']:
                self.feedback.show_review(status, lambda: focus_widget(self.mode))
            else:
                self.feedback.setText(status)
        self.sync()
