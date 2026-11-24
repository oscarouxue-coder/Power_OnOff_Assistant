"""Bind the local project wizard to one workspace request and project at a time."""
from PySide6.QtWidgets import QMessageBox

from .project_wizard import ProjectWizard


class ProjectWizardController:
    def __init__(self, workspace):
        self.workspace = workspace
        self.dialog = None
        self.pending = None
        self.token = ''
        self.final_save = False
        self.loaded_revision = ''

    def _send(self, operation, *args):
        dialog = self.dialog
        if not dialog or self.pending is not None or self.workspace.closing:
            return
        request = self.workspace.submit(operation, *args)
        if request is None:
            dialog.feedback.setText(self.workspace.window.statusBar().currentMessage())
            return
        self.pending = request
        dialog.set_busy(True)

    def open(self, project=None):
        if not self.workspace.ready or self.workspace.closing:
            return
        identifier = project.project_id if project else ''
        if self.dialog is not None:
            if self.dialog.project_id == identifier:
                self.dialog.showNormal()
                self.dialog.raise_()
                return
            if not self.dialog.close():
                return
        self.token = ''
        self.loaded_revision = ''
        dialog = self.dialog = ProjectWizard(self.workspace.window, project_id=identifier,
                                              name=project.name if project else '')
        dialog.finished.connect(lambda _result: self._closed(dialog))
        dialog.draft_requested.connect(lambda: self._save(False))
        dialog.commit_requested.connect(lambda: self._save(True))
        if identifier:
            dialog.project_menu.aboutToShow.connect(self._update_preset_action)
            dialog.save_preset_action.triggered.connect(self._save_preset)
        dialog.show()
        if identifier:
            self._send('wizard_profile_get', identifier)
        else:
            self._send('wizard_draft_get')

    def _closed(self, dialog):
        if self.dialog is dialog:
            self.dialog = None
            self.final_save = False
        dialog.deleteLater()

    def _save(self, final):
        dialog = self.dialog
        self.final_save = final
        if dialog.project_id:
            self._send('wizard_profile_save', dialog.project_id, dialog.profile(), self.token,
                       None, final)
        elif final:
            self._send('wizard_create', dialog.directory.text().strip(), dialog.name.text().strip(),
                       dialog.profile(), self.token, dialog.legacy_environment)
        else:
            self._send('wizard_draft_save', dialog.draft(), self.token)

    def _preset_problem(self):
        dialog = self.dialog
        if not dialog or not dialog.project_id or self.workspace.closing or dialog.busy:
            return '项目正忙'
        project = next((p for p in self.workspace.window.projects if p.project_id == dialog.project_id), None)
        if dialog.preset_error.text():
            return dialog.preset_error.text()
        if not project or not project.saved_revision or self.loaded_revision != project.saved_revision:
            return '请重新打开向导核对当前保存版本'
        if project.dirty or dialog.has_unsaved_inputs():
            return '请先保存项目与向导中的修改'
        if not dialog.model.text().strip() or not dialog.test_type.currentData():
            return '请先保存产品型号和测试类型'
        return ''

    def _update_preset_action(self):
        action = self.dialog.save_preset_action
        problem = self._preset_problem()
        action.setEnabled(not problem)
        action.setToolTip(problem or '使用当前项目保存版本中的测试计划')

    def _save_preset(self):
        dialog = self.dialog
        problem = self._preset_problem()
        if problem:
            if dialog:
                dialog.feedback.setText(problem)
            return
        model, kind = dialog.model.text().strip(), dialog.test_type.currentData()
        version = next((p['version'] for p in dialog.presets
                        if p['model'].casefold() == model.casefold() and p['test_type'] == kind), 0)
        buttons = QMessageBox.StandardButton
        detail = f'更新已有型号模板（当前版本 {version}）' if version else '创建型号模板'
        answer = QMessageBox.question(dialog, '保存为型号模板',
            f'{detail}「{model} · {dialog.test_type.currentText()}」？\n将提取专属测试计划。',
            buttons.Yes | buttons.No, buttons.No)
        if answer == buttons.Yes:
            self._send('wizard_preset_save', dialog.project_id, self.loaded_revision, version)

    def handle_result(self, result):
        dialog = self.dialog
        if dialog is None or result.identifier != self.pending:
            return False
        self.pending = None
        dialog.set_busy(False)
        if result.error:
            self.final_save = False
            self.workspace.blocker_review.inline(dialog, result, dialog.project_id)
            if result.operation == 'wizard_profile_get':
                self.workspace.blocker_review.finish(dialog.project_id, 'wizard', None)
            return True
        operation = result.operation
        payload = result.payload
        if operation in ('wizard_draft_get', 'wizard_profile_get', 'wizard_preset_save'):
            dialog.set_presets(payload.get('presets', ()))
            error = payload.get('preset_error', '')
            dialog.preset_error.setText(error)
            dialog.preset_error.setVisible(bool(error))
        if operation in ('wizard_draft_get', 'wizard_draft_save'):
            self.token = payload['token']
            if operation == 'wizard_draft_get':
                dialog.set_power_cycles(payload.get('power_cycles'))
                if payload['draft']:
                    dialog.blank.show()
                    try:
                        old_destination = dialog.load(payload['draft'])
                    except (ValueError, TypeError, KeyError, AttributeError):
                        dialog.load({})
                        dialog.feedback.setText('向导草稿格式无法读取，可从空白开始')
                        dialog.pages.setEnabled(False)
                        dialog.forward.setEnabled(False)
                        dialog.save_draft.setEnabled(False)
                    else:
                        dialog.feedback.setText('已恢复旧版草稿，请重新选择「保存到」的父目录'
                                                if old_destination else '已恢复向导草稿')
                else:
                    dialog.remember()
            else:
                dialog.remember()
                dialog.feedback.setText('向导草稿已保存')
        elif operation in ('wizard_profile_get', 'wizard_profile_save'):
            self.token = payload['token']
            if operation == 'wizard_profile_get':
                dialog.load_current(payload)
                project = next((p for p in self.workspace.window.projects if p.project_id == dialog.project_id), None)
                self.loaded_revision = payload.get('saved_revision', project.saved_revision if project else '')
                if payload['profile']:
                    if project is not None and project.dirty:
                        dialog.feedback.setText('已载入项目草稿，请确认设置后保存为正式版本')
                self.workspace.blocker_review.finish(dialog.project_id, 'wizard', dialog)
            else:
                dialog.remember()
                if self.final_save:
                    self.final_save = False
                    self.workspace._recent_projects = payload.get('recent_projects', self.workspace._recent_projects)
                    dialog.accept()
                    self.workspace.window.statusBar().showMessage('项目设置已保存', 5000)
                else:
                    dialog.feedback.setText('项目草稿已保存，正式版本尚未更新')
        elif operation == 'wizard_create':
            dialog.remember()
            dialog.accept()
            self.workspace._recent_projects = payload
            window = self.workspace.window
            window.select_project(result.project_id)
        elif operation == 'wizard_preset_save':
            dialog.feedback.setText('已保存型号模板')
        return True

    def prune(self, opened):
        dialog = self.dialog
        if dialog and dialog.project_id and dialog.project_id not in opened and not dialog.busy:
            dialog.accept()
