"""Local operator selection and confirmation for project diagnostic channels."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QSpinBox, QVBoxLayout)
from src.models.ai_permissions import PERMISSION_LABELS

from src.ui.qt.theme import button


class AiMonitorDialog(QDialog):
    requested = Signal(str, object)

    def __init__(self, view, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('实时诊断与监控 · ' + parent.project_name)
        self.resize(560, 490)
        layout = QVBoxLayout(self)
        policy, status = view['policy'], view['status']
        self.token = view['token']
        message = QLabel(f"模型 {view['model'] or '未配置'} · {view['provider']}\n"
                         "启用后可登录所选设备读取状态。发送给此模型的诊断材料可能含设备账号和密码。")
        message.setWordWrap(True)
        layout.addWidget(message)
        self.channels = QListWidget()
        self.channels.setAccessibleName('确认诊断目标')
        for channel, title in view['targets']:
            item = QListWidgetItem(title, self.channels)
            item.setData(Qt.ItemDataRole.UserRole, channel)
            item.setCheckState(Qt.CheckState.Checked if channel in (view['active'] or policy.get('channels', ()))
                               else Qt.CheckState.Unchecked)
        layout.addWidget(self.channels)
        self.automatic = QCheckBox('测试异常时自动诊断')
        self.automatic.setChecked(status['enabled'])
        layout.addWidget(self.automatic)
        row = QHBoxLayout()
        self.features = {}
        for code, title in (('power', '电源'), ('telnet', 'Telnet'), ('wifi', 'WiFi'), ('ping', 'Ping')):
            control = QCheckBox(title)
            control.setChecked(code in policy.get('features', ()))
            row.addWidget(control)
            self.features[code] = control
        layout.addLayout(row)
        form = QFormLayout()
        self.threshold, self.cooldown = QSpinBox(), QSpinBox()
        self.threshold.setRange(1, 20)
        self.threshold.setValue(policy.get('threshold', 3))
        self.cooldown.setRange(1, 3600)
        self.cooldown.setValue(policy.get('cooldown', 60))
        self.keywords = QLineEdit(';'.join(policy.get('keywords', ())))
        self.codes = QLineEdit(';'.join(policy.get('error_codes', ())))
        self.permission = QComboBox()
        for key, title in PERMISSION_LABELS.items():
            self.permission.addItem(title, key)
        self.permission.setCurrentIndex(self.permission.findData(view['permission']))
        form.addRow('监控操作权限', self.permission)
        form.addRow('连续异常次数', self.threshold)
        form.addRow('冷却时间（秒）', self.cooldown)
        form.addRow('关键词（分号分隔）', self.keywords)
        form.addRow('错误码（分号分隔）', self.codes)
        layout.addLayout(form)
        self.status = QLabel()
        self.update_status(status)
        layout.addWidget(self.status)
        row = QGridLayout()
        self.apply_button = button('确认启用所选通道诊断', self.apply, 'primary')
        row.addWidget(self.apply_button, 0, 0)
        row.addWidget(button('关闭主动诊断与监控', lambda: self.submit('ai_chat_monitor_off')), 0, 1)
        row.addWidget(button('查看待批准监控操作', lambda: self.submit('ai_chat_monitor_review')), 1, 0)
        row.addWidget(button('取消', self.reject), 1, 1)
        layout.addLayout(row)

    def update_status(self, status):
        state = '监控已启用' if status['enabled'] else '监控已关闭'
        self.status.setText(f"{state} · 排队 {status['queued']} · 运行 {status['running']} · 收尾 {status['cleaning']} · 待批准 {status['waiting_approval']}")

    def submit(self, operation, *args):
        self.requested.emit(operation, args)
        self.accept()

    def apply(self):
        items = (self.channels.item(i) for i in range(self.channels.count()))
        selected = tuple(item.data(Qt.ItemDataRole.UserRole) for item in items if item.checkState() == Qt.CheckState.Checked)
        def entries(field):
            return tuple(value.strip() for value in field.text().split(';') if value.strip())
        self.submit('ai_chat_monitor_apply', self.token, selected,
                    tuple(code for code, control in self.features.items() if control.isChecked()),
                    self.threshold.value(), self.cooldown.value(), entries(self.keywords),
                    entries(self.codes), self.automatic.isChecked(), self.permission.currentData())
