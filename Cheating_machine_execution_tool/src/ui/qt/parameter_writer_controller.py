"""Route the sample-parameter window over the existing workspace queue."""
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QMessageBox

from src.ui.qt.parameter_writer_dialog import ParameterWriterDialog


class ParameterWriterController:
    def __init__(self, workspace):
        self.workspace = workspace
        self.windows = {}
        self.requests = {}
        self.login_drafts = {}
        workspace.window.detail.parameter_requested.connect(self.open)

    def bind_dut(self, identifier, dialog):
        login = self.login_drafts.get(identifier, dialog.saved_parameter_login)
        self._apply_login(dialog, login, dialog._invalidate_status)
        self._bind_login(identifier, dialog)

    def _bind_login(self, identifier, dialog):
        for field in (dialog.username, dialog.password):
            field.textChanged.connect(lambda _text: self._edit_login(identifier, dialog))
        dialog.login_editability_changed.connect(lambda: self.sync_login_editability(identifier))
        self.sync_login_editability(identifier)

    @staticmethod
    def _apply_login(dialog, login, refresh):
        if (dialog.username.text(), dialog.password.text()) == login:
            return
        with QSignalBlocker(dialog.username), QSignalBlocker(dialog.password):
            dialog.username.setText(login[0])
            dialog.password.setText(login[1])
        refresh()

    def _edit_login(self, identifier, source):
        writer = self.windows.get(identifier)
        dut = self.workspace.dut_windows.get(identifier)
        login = (source.username.text(), source.password.text())
        saved = writer.saved_login() if writer is not None else dut.saved_parameter_login
        if login == saved:
            self.login_drafts.pop(identifier, None)
        else:
            self.login_drafts[identifier] = login
        if writer is not None and writer is not source:
            self._apply_login(writer, login, writer._update_controls)
        if dut is not None and dut is not source:
            self._apply_login(dut, login, dut._invalidate_status)

    def _restore_login(self, identifier, writer):
        login = writer.saved_login()
        self.login_drafts.pop(identifier, None)
        dut = self.workspace.dut_windows.get(identifier)
        if dut is not None:
            dut.saved_parameter_login = login
            self._apply_login(dut, login, dut._invalidate_status)

    def sync_login_editability(self, identifier):
        writer = self.windows.get(identifier)
        dut = self.workspace.dut_windows.get(identifier)
        locked = self.workspace.closing or any(
            dialog.busy or dialog.active for dialog in (writer, dut) if dialog is not None)
        for dialog in (writer, dut):
            if dialog is not None:
                dialog.username.setReadOnly(locked)
                dialog.password.setReadOnly(locked)

    def open(self):
        project = self.workspace._current()
        if not project or self.workspace.closing:
            return
        identifier = project.project_id
        dialog = self.windows.get(identifier)
        if dialog is not None:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        elif not any(key == identifier for key, _ in self.requests.values()):
            self.submit(identifier, 'show', {})

    def submit(self, identifier, action, arguments):
        dialog = self.windows.get(identifier)
        if action == 'stop':
            choice = QMessageBox.question(dialog, '停止批量写参',
                '停止后续写参，等待已进入工厂模式的样机完成清理？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if choice != QMessageBox.StandardButton.Yes or self.workspace.closing:
                dialog.set_busy(self.workspace.closing)
                return
        request = self.workspace.submit('parameter_' + action, identifier, arguments)
        if request is not None:
            self.requests[request] = (identifier, action)
        elif dialog is not None:
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
                    if action == 'select_table':
                        dialog.path.setText(dialog.saved['table_path'])
                    dialog.set_busy(False)
                    self.workspace.blocker_review.inline(dialog, result, identifier)
                else:
                    self.workspace.blocker_review.finish(identifier, 'parameter', None)
                    self.workspace.blocker_review.warning(result, '写参窗口未打开', identifier=identifier)
            return True
        payload = result.payload
        if action == 'show':
            if dialog is None:
                self._present(identifier, payload)
            return True
        if dialog is None:
            return True
        if action in ('preflight', 'preview', 'select_table'):
            if action == 'select_table':
                dialog.path.setText(payload['path'])
                dialog.saved['table_path'] = payload['path']
            dialog.apply_preflight(payload)
            if payload.get('confirmation'):
                answer = QMessageBox.question(dialog, '确认批量写样机参数', payload['summary'],
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if not self.workspace.closing and self.windows.get(identifier) is dialog:
                    arguments = dict(token=dialog.token)
                    if answer == QMessageBox.StandardButton.Yes:
                        self.submit(identifier, 'execute', dict(arguments, confirmation=payload['confirmation']))
                    else:
                        self.submit(identifier, 'cancel', arguments)
                return True
        elif action == 'detach':
            dialog.allow_close = True
            dialog.close()
            return True
        elif action == 'cancel':
            dialog.feedback.setText('已取消，未启动写参')
        elif action in ('poll', 'execute', 'stop'):
            dialog.apply_job(payload)
        if action != 'poll':
            dialog.set_busy(False)
        if action == 'save':
            dialog.accept_save()
            self._restore_login(identifier, dialog)
        elif action == 'generate':
            dialog.load_table(payload['path'])
        return True

    def _present(self, identifier, snapshot):
        dialog = ParameterWriterDialog(snapshot, self.workspace.window)
        self.workspace.bind_module_window(dialog, identifier, 'sample_parameter_writer')
        dialog.command_requested.connect(lambda action, data: self.submit(identifier, action, data))
        self.windows[identifier] = dialog
        self._apply_login(dialog, self.login_drafts.get(identifier, dialog.saved_login()), dialog._update_controls)
        self._bind_login(identifier, dialog)
        dialog.login_discarded.connect(lambda: self._restore_login(identifier, dialog))

        def finished(_):
            if self.windows.get(identifier) is dialog:
                self.windows.pop(identifier)
                self.sync_login_editability(identifier)
            dialog.deleteLater()

        dialog.finished.connect(finished)
        dialog.show()
        self.workspace.blocker_review.finish(identifier, 'parameter', dialog)
        if not snapshot['job']:
            dialog.restored_table()

    def set_closing(self, closing):
        for dialog in self.windows.values():
            dialog.set_busy(closing)

    def prune(self, opened, closed):
        for identifier, dialog in tuple(self.windows.items()):
            if identifier not in opened or closed:
                dialog.allow_close = True
                dialog.close()
        for identifier in tuple(self.login_drafts):
            if identifier not in opened or closed:
                self.login_drafts.pop(identifier)

    def poll(self):
        pending = {identifier for identifier, _ in self.requests.values()}
        for identifier, dialog in tuple(self.windows.items()):
            if identifier not in pending and not dialog.busy:
                self.submit(identifier, 'poll', dict(token=dialog.token))
