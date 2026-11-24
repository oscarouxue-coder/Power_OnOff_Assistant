"""Local confirmation and progress for Feishu SDK repair."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox, QVBoxLayout

from src.models.project_review import ReviewTarget
from src.ui.qt.blocker_review import show_warning
from src.ui.qt.theme import label


class FeishuRepairDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle('安装飞书 SDK')
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.waiting = True
        self.feedback = label('正在检查源码环境和工作区状态…')
        self.feedback.setWordWrap(True)
        QVBoxLayout(self).addWidget(self.feedback)
        self.resize(500, self.sizeHint().height())

    def reject(self):
        if not self.waiting:
            super().reject()

    def closeEvent(self, event):
        if self.waiting:
            event.ignore()
        else:
            super().closeEvent(event)


class FeishuRepairController:
    def __init__(self, workspace):
        self.workspace = workspace
        self.dialog = None
        self.request = None
        self.restart_requested = False

    def open(self):
        workspace = self.workspace
        if not workspace.ready or workspace.closing or self.dialog is not None:
            return
        if not workspace.app_update.worker.idle:
            workspace.window.statusBar().showMessage('请等待检查更新或下载结束后再安装飞书 SDK。', 5000)
            return
        answer = QMessageBox.question(workspace.window, '安装飞书 SDK 并重启',
            '将把项目锁定的飞书 SDK 安装到当前源码环境。验证成功后请求安全退出并重启。是否继续？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes or not workspace.app_update.worker.idle:
            return
        self.request = workspace.submit('feishu_repair_start')
        if self.request is not None:
            self.dialog = FeishuRepairDialog(workspace.window)
            self.dialog.show()

    def _dismiss(self):
        dialog, self.dialog = self.dialog, None
        dialog.waiting = False
        dialog.close()

    def handle_result(self, result):
        if result.operation == 'feishu_repair_release':
            if result.error:
                self.workspace.window.statusBar().showMessage(result.error, 5000)
            return True
        if result.operation != 'feishu_repair_start':
            return False
        if self.request == result.identifier:
            self.request = None
            if result.error:
                self._dismiss()
                QMessageBox.warning(self.workspace.window, '飞书 SDK 未安装', result.error)
        return True

    def poll(self):
        if self.dialog is None or self.request is not None:
            return
        message, success = self.workspace.adapter.feishu_repair_status()
        self.dialog.feedback.setText(message)
        if success is None:
            return
        self._dismiss()
        if not success:
            show_warning(self.workspace.window, '飞书 SDK 安装未完成', message,
                         lambda: self.workspace.blocker_review.open('', ReviewTarget('log', reference='[飞书依赖]')))
            return
        self.restart_requested = True
        self.workspace.request_close()
        if not self.workspace.closing:
            self.cancel_restart()

    def cancel_restart(self):
        if not self.restart_requested:
            return
        self.restart_requested = False
        self.workspace.submit('feishu_repair_release')
        self.workspace.window.statusBar().showMessage('SDK 已安装，请处理当前窗口后手动重启。', 8000)
