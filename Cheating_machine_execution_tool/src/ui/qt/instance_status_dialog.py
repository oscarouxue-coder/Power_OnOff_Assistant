"""Read the current local instance state through the workspace worker."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QFormLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QVBoxLayout)
import json

from src.ui.qt.blocker_review import focus_widget
from src.ui.qt.theme import button, label


class InstanceStatusDialog(QDialog):
    def __init__(self, workspace):
        super().__init__(workspace.window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('多实例接入状态')
        self.workspace = workspace
        self.request = None
        self.fields = {}
        self.config_editor = None
        self.pairing = None
        self.startup_editor = None
        layout = QVBoxLayout(self)
        form = QFormLayout()
        for key, title in (('current_mode', '接入模式'), ('gateway_state', '本机网关'),
                           ('current_slot', '槽位'), ('instance_id', '实例 ID'),
                           ('run_id', '运行 ID'), ('connected', '实例连接')):
            field = label('—')
            field.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse |
                                          Qt.TextInteractionFlag.TextSelectableByKeyboard)
            field.setWordWrap(True)
            self.fields[key] = field
            form.addRow(title, field)
        layout.addLayout(form)
        self.instances = QListWidget()
        self.instances.setAccessibleName('网关登记实例')
        self.instances.hide()
        layout.addWidget(self.instances)
        footer = QHBoxLayout()
        self.feedback = label('', 'muted')
        self.feedback.setWordWrap(True)
        footer.addWidget(self.feedback, 1)
        self.manage = QPushButton('网关操作')
        menu = QMenu(self.manage)
        menu.addAction('刷新登记实例', lambda: self.submit('gateway_instances'))
        self.details = menu.addAction('查看实例详情', self.show_details)
        self.copy_id = menu.addAction('复制实例 ID', self.copy_instance)
        self.revoke = menu.addAction('撤销所选实例接入…', self.revoke_instance)
        menu.addSeparator()
        menu.addAction('编辑网关配置…', self.edit_gateway)
        menu.addAction('实例配对…', self.open_pairing)
        menu.addAction('下次启动配置…', self.open_startup)
        self.start = menu.addAction('按已保存配置启动网关…', lambda: self.change_gateway(True))
        self.stop = menu.addAction('停止本机网关…', lambda: self.change_gateway(False))
        menu.aboutToShow.connect(self.sync_actions)
        self.manage.setMenu(menu)
        footer.addWidget(self.manage)
        self.refresh_button = button('刷新', self.refresh)
        footer.addWidget(self.refresh_button)
        footer.addWidget(button('关闭', self.close))
        layout.addLayout(footer)
        self.resize(460, self.sizeHint().height())

    def refresh(self):
        self.submit('instance_status')

    def submit(self, operation, *args):
        if self.request is not None or self.workspace.closing:
            return
        self.request = self.workspace.submit(operation, *args)
        self.refresh_button.setEnabled(self.request is None)
        self.manage.setEnabled(self.request is None)
        self.feedback.setText('处理中…' if self.request is not None else '工作区忙，请重试')

    def selected(self):
        row = self.instances.currentItem()
        return row.data(Qt.ItemDataRole.UserRole) if row else None

    def edit_gateway(self):
        if self.config_editor is None:
            self.submit('gateway_read_config')
        else:
            self.config_editor.raise_()

    def open_pairing(self):
        if self.pairing is None:
            from src.ui.qt.instance_pairing_dialog import InstancePairingDialog
            self.pairing = InstancePairingDialog(self)
            self.pairing.finished.connect(lambda _: setattr(self, 'pairing', None))
            self.pairing.show()
            self.pairing.read_slot(None)
        else:
            self.pairing.showNormal()
            self.pairing.raise_()

    def open_startup(self):
        if self.startup_editor is None:
            from src.ui.qt.instance_startup_dialog import InstanceStartupDialog
            self.startup_editor = InstanceStartupDialog(self, self.workspace.window.selected_project)
            self.startup_editor.finished.connect(lambda _: setattr(self, 'startup_editor', None))
            self.startup_editor.show()
            self.startup_editor.read(None)
        else:
            self.startup_editor.showNormal()
            self.startup_editor.raise_()

    def sync_actions(self):
        row = self.selected()
        self.details.setEnabled(bool(row))
        self.copy_id.setEnabled(bool(row))
        self.revoke.setEnabled(bool(row and row['state'] != '已撤销'))
        state = self.fields['gateway_state'].text()
        self.start.setEnabled(state == '已停止')
        self.stop.setEnabled(state == '运行中')

    def show_details(self):
        row = self.selected()
        if row:
            box = QMessageBox(self)
            box.setWindowTitle('实例详情')
            box.setTextFormat(Qt.TextFormat.PlainText)
            box.setText(json.dumps(row, ensure_ascii=False, indent=2))
            box.exec()

    def copy_instance(self):
        row = self.selected()
        if row:
            QApplication.clipboard().setText(row['instance_id'])

    def confirm(self, title, text):
        box = QMessageBox(self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def revoke_instance(self):
        row = self.selected()
        if row and row['state'] != '已撤销' and self.confirm('撤销实例接入',
                f"撤销 {row['name']}（{row['instance_id']}）的远程接入？已准入业务继续执行。"):
            self.submit('gateway_revoke', row['instance_id'])

    def change_gateway(self, start):
        title = '按已保存配置启动本机网关' if start else '停止本机网关'
        if self.confirm(title, '使用已保存的监听地址和平台配置启动？' if start else '停止接收和转发消息？已准入业务继续执行。'):
            self.submit('gateway_start' if start else 'gateway_stop')

    def show_result(self, result):
        if self.startup_editor is not None and self.startup_editor.request == result.identifier:
            self.startup_editor.show_result(result)
            return
        if self.pairing is not None and self.pairing.request == result.identifier:
            self.pairing.show_result(result)
            return
        if result.identifier != self.request:
            return
        self.request = None
        self.refresh_button.setEnabled(True)
        self.manage.setEnabled(True)
        if result.operation == 'gateway_read_config' and not result.error:
            from src.ui.qt.gateway_config_dialog import GatewayConfigDialog
            self.config_editor = GatewayConfigDialog(result.payload, self)
            self.config_editor.finished.connect(lambda _: setattr(self, 'config_editor', None))
            self.config_editor.show()
            self.feedback.setText('已读取网关配置')
            return
        if result.operation == 'gateway_save_config':
            if self.config_editor is not None:
                if result.error:
                    self.config_editor.setEnabled(True)
                    target = getattr(result, 'review', None)
                    self.config_editor.feedback.show_review(result.error, (lambda: focus_widget(self.refresh_button)) if target else None)
                else:
                    self.config_editor.accept()
            self.feedback.setText(result.error or '网关配置已保存，重新启动网关后生效')
            return
        if result.operation == 'gateway_instances':
            previous = self.selected()
            self.instances.clear()
            for row in result.payload or ():
                item = QListWidgetItem(f"{row['name']} · {row['state']} · {row['instance_id']}", self.instances)
                item.setData(Qt.ItemDataRole.UserRole, row)
                if previous and previous['instance_id'] == row['instance_id']:
                    self.instances.setCurrentItem(item)
            self.instances.show()
            self.feedback.setText(result.error or f'已读取 {self.instances.count()} 个实例')
            return
        if result.operation != 'instance_status':
            self.feedback.setText(result.error or '操作已完成')
            if not result.error:
                if result.operation == 'gateway_revoke':
                    self.submit('gateway_instances')
                else:
                    self.refresh()
            return
        values = dict(result.payload or {})
        if not result.error:
            mode = values.get('current_mode')
            values['current_mode'] = {'direct': '直接接入', 'gateway': '统一接入', 'project_peers': '按项目路由',
                                      'gateway_pending': '统一接入（尚未启动）', 'error': '启动失败'}.get(mode, '未知')
            if mode in ('direct', 'project_peers'):
                values['connected'] = '不适用'
            elif values.get('connected') is True:
                values['connected'] = '已连接'
            elif values.get('connected') is False:
                values['connected'] = '未连接'
        for key, field in self.fields.items():
            field.setText(str(values.get(key) or '—') if not result.error else '—')
        self.feedback.setText(result.error or '已读取')
