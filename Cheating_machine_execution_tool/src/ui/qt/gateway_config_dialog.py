"""Local editor for the original gateway configuration and pairing scopes."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLineEdit, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from src.services.remote_gateway_store import validate_pairing_scopes
from src.ui.qt.theme import button, label


class GatewayConfigDialog(QDialog):
    COLUMNS = ('platform', 'robot', 'corp', 'chat_type', 'chat', 'members')

    def __init__(self, config, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('统一网关配置')
        self.original = config
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.text_inputs = {}
        for key, title in (('host', '监听地址'), ('certificate', 'WSS 证书路径'), ('private_key', '私钥文件路径')):
            control = QLineEdit(config.get(key, ''))
            self.text_inputs[key] = control
            form.addRow(title, control)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(config['port'])
        form.addRow('端口', self.port)
        self.vpn = QCheckBox('已使用受保护的 VPN 网络')
        self.vpn.setChecked(config.get('vpn', False))
        form.addRow(self.vpn)
        platforms = QHBoxLayout()
        self.platforms = {}
        for key, title in (('dingtalk', '钉钉'), ('feishu', '飞书')):
            control = QCheckBox(title)
            self.platforms[key] = control
            control.setChecked(key in config.get('platforms', []))
            platforms.addWidget(control)
        form.addRow('接入平台', platforms)
        layout.addWidget(label('配对允许范围', 'section'))
        self.scopes = QTableWidget(0, len(self.COLUMNS))
        self.scopes.setHorizontalHeaderLabels(('平台', '机器人 ID', '企业 ID', '会话类型', '聊天 ID', '成员 ID（逗号分隔）'))
        self.scopes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.scopes, 1)
        for scope in config.get('scopes', []):
            self.add_scope(scope)
        controls = QHBoxLayout()
        controls.addWidget(button('添加范围', lambda: self.add_scope(dict(platform='feishu', chat_type='group'))))
        controls.addWidget(button('移除所选范围', self.remove_scope))
        controls.addStretch()
        controls.addWidget(button('取消', self.reject))
        controls.addWidget(button('保存', self.save))
        layout.addLayout(controls)
        self.feedback = label('', 'muted')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        screen = self.screen().availableGeometry()
        self.resize(min(880, int(screen.width() * .94)), min(500, int(screen.height() * .90)))

    def add_scope(self, scope):
        row = self.scopes.rowCount()
        self.scopes.insertRow(row)
        for column, key in enumerate(self.COLUMNS):
            value = ','.join(scope.get(key, ())) if key == 'members' else scope.get(key, '')
            self.scopes.setItem(row, column, QTableWidgetItem(value))

    def remove_scope(self):
        row = self.scopes.currentRow()
        if row >= 0:
            self.scopes.removeRow(row)

    def save(self):
        scopes = []
        for row in range(self.scopes.rowCount()):
            scope = {key: self.scopes.item(row, col).text().strip() for col, key in enumerate(self.COLUMNS)}
            scope['members'] = [s.strip() for s in scope['members'].replace('，', ',').split(',') if s.strip()]
            scopes.append(scope)
        try:
            if scopes:
                validate_pairing_scopes(scopes)
        except ValueError as error:
            self.feedback.setText(str(error))
            return
        broad = [scope['chat'] for scope in scopes if scope['members'] == ['*']]
        if broad and not self.parent().confirm('确认全群范围', '允许以下聊天的全部成员配对调用？\n' + '\n'.join(broad)):
            return
        changes = {key: field.text().strip() for key, field in self.text_inputs.items()}
        changes.update(port=self.port.value(), vpn=self.vpn.isChecked(),
                       platforms=[key for key, field in self.platforms.items() if field.isChecked()])
        self.parent().submit('gateway_save_config', self.original, changes, scopes)
        self.setEnabled(self.parent().request is None)
