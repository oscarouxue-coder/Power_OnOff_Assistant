"""Local operator view for gateway invitations and instance enrollment."""
import math
import time

from PySide6.QtCore import QSignalBlocker, QTimer, Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFormLayout, QHBoxLayout,
    QLineEdit, QSpinBox, QVBoxLayout)

from src.ui.qt.blocker_review import ReviewFeedback, focus_widget
from src.ui.qt.theme import button, label


class InstancePairingDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('实例配对')
        self.request = None
        self.loaded = None
        self.expires = 0
        layout = QVBoxLayout(self)
        layout.addWidget(label('本机网关签发', 'section'))
        invite = QHBoxLayout()
        self.generated = QLineEdit()
        self.generated.setAccessibleName('本机网关生成的配对码')
        self.generated.setReadOnly(True)
        self.generate = button('生成配对码', self.generate_code)
        self.copy = button('复制', self.copy_code)
        invite.addWidget(self.generated, 1)
        invite.addWidget(self.generate)
        invite.addWidget(self.copy)
        layout.addLayout(invite)
        self.expiry = QTimer(self)
        self.expiry.setSingleShot(True)
        self.expiry.timeout.connect(self.sync_code)
        layout.addWidget(label('本机实例接入', 'section'))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        layout.addLayout(form)
        slots = QHBoxLayout()
        self.slot = QSpinBox()
        self.slot.setRange(1, 64)
        slots.addWidget(self.slot)
        self.reload = button('读取槽位', lambda: self.read_slot(self.slot.value()))
        slots.addWidget(self.reload)
        slots.addStretch()
        form.addRow('实例槽位', slots)
        self.identity = label('')
        self.identity.setWordWrap(True)
        self.identity.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow('实例 ID', self.identity)
        self.name = QLineEdit()
        self.url = QLineEdit()
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        for title, field in (('配对名称', self.name), ('网关地址', self.url), ('一次性配对码', self.secret)):
            form.addRow(title, field)
        self.vpn = QCheckBox('已使用受保护的 VPN 网络')
        form.addRow(self.vpn)
        self.feedback = ReviewFeedback(role='muted')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        actions = QHBoxLayout()
        actions.addStretch()
        self.pair = button('配对…', self.pair_instance)
        actions.addWidget(self.pair)
        actions.addWidget(button('关闭', self.close))
        layout.addLayout(actions)
        self.slot.valueChanged.connect(self.slot_changed)
        for field in (self.name, self.url, self.secret):
            field.textChanged.connect(self.sync)
        self.sync()
        self.resize(min(580, int(self.screen().availableGeometry().width() * .94)), self.sizeHint().height())

    def sync(self):
        idle = self.request is None
        writable = bool(idle and self.loaded and not self.loaded['paired'] and self.loaded['slot'] == self.slot.value())
        for control in (self.generate, self.slot, self.reload):
            control.setEnabled(idle)
        for control in (self.name, self.url, self.vpn, self.secret):
            control.setEnabled(writable)
        self.pair.setEnabled(bool(writable and self.name.text().strip() and self.url.text().strip() and self.secret.text().strip()))
        self.sync_code()

    def sync_code(self):
        remaining = self.expires - time.monotonic()
        if remaining <= 0:
            self.generated.clear()
            self.expiry.stop()
        else:
            self.expiry.start(math.ceil(remaining * 1000))
        self.copy.setEnabled(bool(self.generated.text()))

    def copy_code(self):
        self.sync_code()
        if self.copy.isEnabled():
            QApplication.clipboard().setText(self.generated.text())

    def submit(self, operation, *args):
        workspace = self.parent().workspace
        if self.request is None and not workspace.closing:
            self.request = workspace.submit(operation, *args)
            self.feedback.setText('处理中…' if self.request is not None else '工作区忙，请重试')
            self.sync()

    def generate_code(self):
        self.generated.clear()
        self.submit('gateway_pairing_code')

    def slot_changed(self, number):
        self.loaded = None
        self.identity.clear()
        self.name.clear()
        self.url.clear()
        self.secret.clear()
        self.vpn.setChecked(False)
        self.read_slot(number)

    def read_slot(self, number):
        self.loaded = None
        self.identity.clear()
        self.secret.clear()
        self.submit('gateway_pairing_slot', number)

    def pair_instance(self):
        if not self.pair.isEnabled():
            return
        number, identity = self.loaded['slot'], self.loaded['instance_id']
        url, name = self.url.text().strip(), self.name.text().strip()
        if self.parent().confirm('确认配对', f'将槽位 {number} 的实例 {identity}（{name}）配对到 {url}？'):
            self.submit('gateway_pair_instance', number, identity, url, name, self.vpn.isChecked(), self.secret.text())
            if self.request is not None:
                self.secret.clear()

    def show_result(self, result):
        if result.identifier != self.request:
            return
        self.request = None
        if result.error:
            if result.operation == 'gateway_pair_instance':
                self.loaded = None
            target = getattr(result, 'review', None)
            self.feedback.show_review(result.error, (lambda: focus_widget(self.reload)) if target else None)
        elif result.operation == 'gateway_pairing_code':
            value, self.expires = result.payload
            self.generated.setText(value)
            self.feedback.setText('配对码已生成，五分钟内可使用一次' if self.expires > time.monotonic() else '配对码已过期')
        else:
            self.loaded = row = result.payload
            with QSignalBlocker(self.slot):
                self.slot.setValue(row['slot'])
            self.identity.setText(row['instance_id'])
            self.name.setText(row['name'])
            self.url.setText(row['url'])
            self.vpn.setChecked(row['vpn'])
            self.feedback.setText('已配对' if row['paired'] else '已读取空闲槽位')
        self.sync()
