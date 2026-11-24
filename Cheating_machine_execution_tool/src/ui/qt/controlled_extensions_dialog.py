"""Local project editor for reviewed capability templates."""
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPlainTextEdit, QVBoxLayout)

from src.ui.qt.blocker_review import ReviewFeedback
from src.ui.qt.theme import button, label


class TemplateReviewDialog(QDialog):
    def __init__(self, parent, review):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setModal(True)
        self.setWindowTitle('本地审阅受控扩展')
        layout = QVBoxLayout(self)
        preview = QPlainTextEdit()
        preview.setPlainText(json.dumps(review, ensure_ascii=False, indent=2))
        preview.setReadOnly(True)
        layout.addWidget(preview)
        self.accepted_review = QCheckBox('已审阅执行内容、代码哈希、参数约束和资源范围')
        layout.addWidget(self.accepted_review)
        actions = QHBoxLayout()
        actions.addStretch()
        self.approve = button('批准并登记此版本', self.accept, 'primary')
        self.approve.setEnabled(False)
        self.accepted_review.toggled.connect(self.approve.setEnabled)
        actions.addWidget(self.approve)
        actions.addWidget(button('取消', self.reject))
        layout.addLayout(actions)
        self.resize(760, 490)


class ControlledExtensionsDialog(QDialog):
    def __init__(self, workspace, project):
        super().__init__(workspace.window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setModal(True)
        self.setWindowTitle('受控扩展 · ' + project.name)
        self.workspace, self.project_id = workspace, project.project_id
        self.request = None
        self.review = None
        self.enabled = False
        layout = QVBoxLayout(self)
        self.rows = QListWidget()
        self.rows.setAccessibleName('已审阅模板')
        self.rows.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.rows.customContextMenuRequested.connect(self.open_actions)
        layout.addWidget(self.rows)
        self.feedback = ReviewFeedback(role='muted')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        actions = QHBoxLayout()
        self.refresh_button = button('刷新', self.refresh)
        self.import_button = button('导入并审阅模板…', self.import_template, 'primary')
        actions.addWidget(self.refresh_button)
        actions.addStretch()
        actions.addWidget(self.import_button)
        actions.addWidget(button('关闭', self.close))
        layout.addLayout(actions)
        self.resize(560, 400)
        self.refresh()

    def submit(self, operation, *arguments):
        if self.request is not None:
            return
        self.request = self.workspace.submit(operation, self.project_id, *arguments)
        self._sync()

    def _sync(self):
        self.refresh_button.setEnabled(self.request is None)
        self.import_button.setEnabled(self.request is None and self.enabled)

    def refresh(self):
        self.submit('extension_list')

    def import_template(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入待审阅模板', '', 'JSON 模板 (*.json)')
        if path:
            self.submit('extension_review', path)

    def open_actions(self, point):
        if not self.enabled or self.request is not None:
            return
        item = self.rows.itemAt(point)
        if item is None:
            return
        self.rows.setCurrentItem(item)
        row = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.addAction('停用 / 撤销…' if row['enabled'] else '恢复已审阅模板…', lambda: self.toggle(row))
        menu.popup(self.rows.viewport().mapToGlobal(point))

    def toggle(self, row):
        wanted = not row['enabled']
        verb = '恢复' if wanted else '停用'
        result = QMessageBox.question(self, verb + '受控扩展',
            f'是否{verb}模板 {row["id"]} 版本 {row["version"]}？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if result == QMessageBox.StandardButton.Yes:
            self.submit('extension_set_enabled', row['id'], row['reviewed_sha256'], wanted)

    def handle_result(self, result):
        if self.request != result.identifier:
            return
        self.request = None
        if result.error:
            self.workspace.blocker_review.inline(self, result, self.project_id)
        elif result.operation == 'extension_review':
            payload = result.payload
            review = self.review = TemplateReviewDialog(self, payload['review'])
            review.finished.connect(lambda answer: self.finish_review(payload['token'], answer))
            review.show()
        else:
            self.enabled = result.payload['enabled']
            self.rows.clear()
            for row in result.payload['rows']:
                state = '启用' if row['enabled'] else '停用'
                item = QListWidgetItem(f'{row["id"]}  v{row["version"]}  {state}  已执行 {row["uses"]} 次')
                item.setData(Qt.ItemDataRole.UserRole, row)
                self.rows.addItem(item)
            text = '当前启动配置已停用受控扩展。' if not self.enabled else ''
            if result.operation == 'extension_approve':
                text = '已登记所审阅的模板版本。'
            elif result.operation == 'extension_set_enabled':
                text = '模板状态已更新。'
            self.feedback.setText(text)
        self._sync()

    def finish_review(self, token, answer):
        self.review = None
        operation = 'extension_approve' if answer == QDialog.DialogCode.Accepted else 'extension_cancel'
        self.submit(operation, token)

    def reject(self):
        if self.request is None and self.review is None:
            super().reject()

    def closeEvent(self, event):
        if self.request is not None or self.review is not None:
            event.ignore()
        else:
            super().closeEvent(event)
