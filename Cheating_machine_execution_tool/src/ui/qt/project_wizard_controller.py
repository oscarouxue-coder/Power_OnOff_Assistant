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
        self.start_request = None
        self.start_project = ''
        self.module_after = ''
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
        dialog.start_requested.connect(self._start)
        dialog.preparation.record_requested.connect(self._record)
        dialog.preparation.module_requested.connect(self._module)
        dialog.preparation.refresh_requested.connect(self._refresh)
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
            self.start_request = None
            self.start_project = ''
            self.module_after = ''
        dialog.deleteLater()

    def _save(self, final):
        dialog = self.dialog
        self.final_save = final
        if dialog.project_id:
            self._send('wizard_profile_save', dialog.project_id, dialog.profile(), self.token)
        elif final:
            self._send('create_typed', dialog.directory.text().strip(), dialog.name.text().strip(),
                       dialog.profile(), self.token)
        else:
            self._send('wizard_draft_save', dialog.draft(), self.token)

    def _refresh(self):
        if self.dialog and self.dialog.project_id:
            self._send('preparation_view', self.dialog.project_id)

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
            f'{detail}「{model} · {dialog.test_type.currentText()}」？\n将提取选做准备和专属测试计划。',
            buttons.Yes | buttons.No, buttons.No)
        if answer == buttons.Yes:
            self._send('wizard_preset_save', dialog.project_id, self.loaded_revision, version)

    def _record(self, params):
        self._send('preparation_record', self.dialog.project_id, params)

    def _module(self, step):
        current = self.dialog.preparation._step()
        if not current or current['id'] != step:
            return
        if current['state'] != 'running':
            self.module_after = step
            self._record({'action': 'begin', 'dut_id': self.dialog.preparation.dut.currentData(),
                          'step_id': step, 'token': current['token']})
        else:
            self._open_module(step)

    def _open_module(self, step):
        dialog = self.dialog
        workspace = self.workspace
        project = next((p for p in workspace.window.projects if p.project_id == dialog.project_id), None)
        if not project or workspace.closing:
            return
        workspace.window.select_project(project.project_id)
        workspace._sync_actions()
        detail = workspace.window.detail
        routes = {
            'firmware': (2, workspace.open_upgrade), 'parameters': (3, workspace.parameter_writer.open),
            'onu': (4, workspace.onu_query.open),
            **{key: (6, workspace.open_dut) for key in ('telnet', 'wan', 'voice', 'tr069', 'wifi')},
        }
        if step == 'pretest':
            allowed = project.can_configure and project.editor_kind != 'channels'
            handler = workspace.open_configuration
        else:
            route = routes.get(step)
            if route is None:
                return
            index, handler = route
            allowed = detail.tabs.isTabEnabled(index)
        if allowed:
            handler()
            dialog.feedback.setText('请在业务窗口核对目标并执行，然后返回本页关联执行回执')
        else:
            dialog.feedback.setText('该项目当前不能打开此业务操作')

    def _start(self):
        dialog, workspace = self.dialog, self.workspace
        snapshot = dialog.preparation.snapshot
        if not snapshot.get('ready') or snapshot.get('dirty'):
            return
        workspace.window.select_project(dialog.project_id)
        request = workspace.start_test()
        if request is None:
            dialog.feedback.setText('当前项目未获准启动，请核对准备、资源与任务状态')
        else:
            self.start_request, self.start_project = request, dialog.project_id
            dialog.set_busy(True)
            dialog.feedback.setText('正在核对已保存配置与目标通道')

    def track_confirmation(self, request, project_id, prepared_request):
        if self.dialog and self.start_project == project_id and prepared_request == self.start_request:
            self.start_request = request
            if request is None:
                self.dialog.set_busy(False)
                self.dialog.feedback.setText('启动请求未提交')
                self.start_project = ''

    def _show_preparation(self, result):
        dialog = self.dialog
        dialog.preparation.show_snapshot(result.payload)
        dialog.pages.setCurrentIndex(4)
        dialog._page_changed()

    def handle_result(self, result):
        dialog = self.dialog
        if dialog and self.start_request == result.identifier:
            if result.error or result.operation != 'prepare_execution':
                dialog.set_busy(False)
                dialog.feedback.setText(result.error or ('已取消启动' if result.operation == 'cancel_confirmation'
                                                         else '原测试任务已提交'))
                self.start_project = ''
                self.start_request = None
            return False  # The original safety confirmation and job handler run normally.
        if dialog is None or result.identifier != self.pending:
            return False
        self.pending = None
        dialog.set_busy(False)
        if result.error:
            self.final_save = False
            self.module_after = ''
            dialog.feedback.setText(result.error)
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
                if payload['draft']:
                    dialog.blank.show()
                    try:
                        dialog.load(payload['draft'])
                    except (ValueError, TypeError, KeyError, AttributeError):
                        dialog.load({})
                        dialog.feedback.setText('向导草稿格式无法读取，可从空白开始')
                        dialog.pages.setEnabled(False)
                        dialog.forward.setEnabled(False)
                        dialog.save_draft.setEnabled(False)
                    else:
                        dialog.feedback.setText('已恢复向导草稿')
            else:
                dialog.remember()
                dialog.feedback.setText('向导草稿已保存')
        elif operation in ('wizard_profile_get', 'wizard_profile_save'):
            self.token = payload['token']
            if operation == 'wizard_profile_get':
                dialog.load(dict(profile=payload['profile']))
                project = next((p for p in self.workspace.window.projects if p.project_id == dialog.project_id), None)
                self.loaded_revision = payload.get('saved_revision', project.saved_revision if project else '')
                if payload['profile']:
                    if project is not None and project.dirty:
                        dialog.feedback.setText('已载入项目草稿，请确认设置后保存为正式版本')
                    else:
                        self._refresh()
            else:
                dialog.remember()
                if self.final_save:
                    self.final_save = False
                    self._send('save', dialog.project_id)
                else:
                    dialog.feedback.setText('项目草稿已保存，正式版本尚未更新')
        elif operation == 'create_typed':
            dialog.remember()
            dialog.accept()
            self.workspace._recent_projects = payload
            window = self.workspace.window
            window.select_project(result.project_id)
            project = next((p for p in window.projects if p.project_id == result.project_id), None)
            if project is not None:
                self.open(project)
        elif operation == 'save':
            self.workspace._recent_projects = payload
            dialog.feedback.setText('项目设置已保存为新版本')
            self._send('wizard_profile_get', dialog.project_id)
        elif operation == 'wizard_preset_save':
            dialog.feedback.setText('已保存型号模板')
        elif operation in ('preparation_view', 'preparation_record'):
            self._show_preparation(result)
            if operation == 'preparation_record':
                dialog.feedback.setText('准备记录已保存')
            if self.module_after:
                step, self.module_after = self.module_after, ''
                self._open_module(step)
        return True

    def prune(self, opened):
        dialog = self.dialog
        if dialog and dialog.project_id and dialog.project_id not in opened and not dialog.busy:
            dialog.accept()
