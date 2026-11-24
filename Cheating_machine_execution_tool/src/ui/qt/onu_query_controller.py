"""Route the ONU window through the existing project worker and refresh loop."""
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox, QPlainTextEdit, QVBoxLayout

from src.ui.qt.onu_query_dialog import OnuQueryDialog
from src.ui.qt.theme import button, label


def confirm_onu_delete(parent, payload):
    dialog = QDialog(parent)
    dialog.setWindowTitle('确认删除已注册 ONU')
    dialog.resize(620, 400)
    layout = QVBoxLayout(dialog)
    details = label(payload['summary'])
    details.setWordWrap(True)
    layout.addWidget(details)
    targets = QPlainTextEdit('\n'.join(payload['targets']))
    targets.setReadOnly(True)
    layout.addWidget(targets)
    warning = label('删除在线 ONU 会中断业务。请核对接口和 SN。')
    warning.setWordWrap(True)
    layout.addWidget(warning)
    actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    delete = button('确认删除', dialog.accept, 'danger')
    delete.setAutoDefault(False)
    actions.addButton(delete, QDialogButtonBox.ButtonRole.ActionRole)
    actions.rejected.connect(dialog.reject)
    cancel = actions.button(QDialogButtonBox.StandardButton.Cancel)
    cancel.setDefault(True)
    cancel.setFocus()
    layout.addWidget(actions)
    return dialog.exec() == QDialog.DialogCode.Accepted


class OnuQueryController:
    def __init__(self, workspace):
        self.workspace = workspace
        self.windows = {}
        self.requests = {}
        workspace.window.detail.onu_requested.connect(self.open)

    def open(self):
        project = self.workspace._current()
        if not project or self.workspace.closing:
            return
        identifier = project.project_id
        dialog = self.windows.get(identifier)
        if dialog is not None:
            dialog.showNormal()
            dialog.raise_()
            dialog.activateWindow()
        elif not any(key == identifier for key, _ in self.requests.values()):
            self.submit(identifier, 'show', {})

    def submit(self, identifier, action, arguments):
        if action == 'confirm_registration':
            self._confirm_registration(identifier, arguments)
            return
        request = self.workspace.submit('onu_' + action, identifier, arguments)
        if request is not None:
            self.requests[request] = (identifier, action)
        elif action != 'poll' and identifier in self.windows:
            dialog = self.windows[identifier]
            dialog.set_busy(self.workspace.closing)
            dialog.feedback.setText('请求未提交，请稍后重试')

    def handle_result(self, result):
        entry = self.requests.pop(result.identifier, None)
        if entry is None:
            return False
        identifier, action = entry
        dialog = self.windows.get(identifier)
        if self.workspace.closing:
            return True
        if result.error:
            if action != 'poll':
                if dialog is not None:
                    dialog.close_after_save = False
                    dialog.set_busy(False)
                    self.workspace.blocker_review.inline(dialog, result, identifier)
                else:
                    self.workspace.blocker_review.finish(identifier, 'onu', None)
                    self.workspace.blocker_review.warning(result, 'ONU 窗口未打开', identifier=identifier)
            return True
        payload = result.payload
        if action == 'show':
            if dialog is None and any(p.project_id == identifier for p in self.workspace.window.projects):
                self._present(identifier, payload)
            return True
        if dialog is None:
            return True
        if action in ('preview', 'prepare_cleanup'):
            self._confirm(identifier, dialog, payload)
            return True
        if action == 'prepare_delete':
            accepted = (self.workspace.window.selected_project == identifier and confirm_onu_delete(dialog, payload))
            if not self.workspace.closing and self.windows.get(identifier) is dialog:
                if accepted and self.workspace.window.selected_project == identifier:
                    self.submit(identifier, 'delete', dict(token=dialog.token, confirmation=payload['confirmation']))
                else:
                    self.submit(identifier, 'cancel', dict(token=dialog.token))
            return True
        if action == 'detach':
            dialog.allow_close = True
            dialog.close()
            return True
        if action in ('execute', 'register', 'delete', 'stop', 'save_olt', 'poll'):
            dialog.apply_job(payload)
        if action != 'poll':
            dialog.set_busy(False)
        if action == 'save_profile':
            dialog.saved(payload)
        elif action == 'save_business':
            dialog.business_saved(payload)
        elif action == 'prepare_registration':
            dialog.show_registration_preview(payload)
            dialog.set_busy(False)
        elif action == 'cancel':
            dialog.invalidate_registration()
            dialog.set_busy(False)
            dialog.feedback.setText('已取消，未启动任务')
        if action in ('register', 'poll') and payload.get('save_confirmation'):
            self._confirm_save(identifier, dialog, payload['save_confirmation'])
        return True

    def _confirm_save(self, identifier, dialog, payload):
        if self.workspace.window.selected_project != identifier or dialog.family.currentText() != payload['family']:
            return
        dialog.set_busy(True)
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        confirmation = QMessageBox(QMessageBox.Icon.Question, '保存 OLT 最新配置', payload['summary'], yes | no, dialog)
        confirmation.setDefaultButton(no)
        answer = confirmation.exec()
        confirmation.deleteLater()
        if not self.workspace.closing and self.windows.get(identifier) is dialog:
            accepted = answer == yes and self.workspace.window.selected_project == identifier
            self.submit(identifier, 'save_olt', dict(token=dialog.token, registration_job=payload['registration_job'],
                                                    accepted=accepted))

    def _confirm_registration(self, identifier, arguments):
        dialog = self.windows.get(identifier)
        if dialog is None or self.workspace.closing:
            return
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        answer = no
        if self.workspace.window.selected_project == identifier:
            payload = dialog._registration_preview
            answer = QMessageBox.question(dialog, '确认注册 ONU', payload['summary'], yes | no, no)
        if self.workspace.closing or self.windows.get(identifier) is not dialog:
            return
        if answer == yes and self.workspace.window.selected_project == identifier:
            dialog.registration_submitted()
            self.submit(identifier, 'register', arguments)
        else:
            self.submit(identifier, 'cancel', dict(token=dialog.token))

    def _confirm(self, identifier, dialog, payload):
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        answer = no
        if self.workspace.window.selected_project == identifier:
            answer = QMessageBox.question(dialog, '确认 OLT 查询范围', payload['summary'], yes | no, no)
        if self.workspace.closing or self.windows.get(identifier) is not dialog:
            return
        values = dict(token=dialog.token)
        if answer == yes and self.workspace.window.selected_project == identifier:
            self.submit(identifier, 'execute', dict(values, confirmation=payload['confirmation']))
        else:
            self.submit(identifier, 'cancel', values)

    def _present(self, identifier, snapshot):
        dialog = OnuQueryDialog(snapshot, self.workspace.window)
        self.workspace.bind_module_window(dialog, identifier, 'onu_registration')
        dialog.command_requested.connect(lambda action, values: self.submit(identifier, action, values))
        self.windows[identifier] = dialog

        def finished(_):
            if self.windows.get(identifier) is dialog:
                self.windows.pop(identifier)
            dialog.deleteLater()

        dialog.finished.connect(finished)
        dialog.show()
        self.workspace.blocker_review.finish(identifier, 'onu', dialog)

    def set_closing(self, closing):
        for dialog in self.windows.values():
            dialog.set_busy(closing)

    def prune(self, opened, closed):
        for identifier, dialog in tuple(self.windows.items()):
            if identifier not in opened or closed:
                dialog.allow_close = True
                dialog.close()

    def poll(self):
        pending = {identifier for identifier, _ in self.requests.values()}
        for identifier, dialog in tuple(self.windows.items()):
            if identifier not in pending and not dialog.busy:
                self.submit(identifier, 'poll', dict(token=dialog.token))
