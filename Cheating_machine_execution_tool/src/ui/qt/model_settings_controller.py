"""Routes model settings from one Qt project editor to the workspace worker."""
from PySide6.QtWidgets import QInputDialog

from src.ui.qt.blocker_review import focus_widget
from src.ui.qt.model_settings_dialog import ModelSettingsDialog


class ModelSettingsController:
    def __init__(self, workspace):
        self.workspace = workspace
        self.windows = {}
        self.requests = {}

    def open(self):
        self.open_for(self.workspace._current())

    def open_for(self, project):
        if project is None or not self.workspace.ready or self.workspace.closing:
            return
        identifier = project.project_id
        dialog = self.windows.get(identifier)
        if dialog is None:
            dialog = ModelSettingsDialog(project, self.workspace.window)
            self.windows[identifier] = dialog
            dialog.action_requested.connect(lambda operation, args: self.submit(dialog, operation, args))
            dialog.finished.connect(lambda _: self.windows.pop(identifier, None))
            if not self.submit(dialog, 'ai_model_open', ()):
                dialog.close()
                return
        dialog.showNormal()
        dialog.raise_()

    def submit(self, dialog, operation, args):
        if self.workspace.closing or self.windows.get(dialog.project_id) is not dialog:
            return False
        request = self.workspace.submit(operation, dialog.project_id, *args)
        if request is not None:
            self.requests[request] = dialog
            dialog.set_busy(True)
        return request is not None

    def handle_result(self, result):
        dialog = self.requests.pop(result.identifier, None)
        if dialog is None:
            return False
        if self.workspace.closing or self.windows.get(dialog.project_id) is not dialog:
            return True
        dialog.set_busy(False)
        if result.error:
            self.workspace.blocker_review.inline(dialog, result, dialog.project_id)
            if result.operation == 'ai_model_open':
                self.workspace.blocker_review.finish(dialog.project_id, 'model', None)
        elif result.operation == 'ai_model_sources':
            self._choose_source(dialog, result.payload)
        elif result.operation == 'ai_model_source_check':
            dialog.set_source(result.payload)
            dialog.feedback.setText('出口 IP 草稿已更新，保存并选择后生效')
        else:
            dialog.show_view(result.payload)
            if result.operation == 'ai_model_open':
                self.workspace.blocker_review.finish(dialog.project_id, 'model', dialog)
        return True

    def _choose_source(self, dialog, inventory):
        choices = {'不指定（自动选择）': ('', True)}
        for row in inventory:
            description = f"{row['name']} | {row['ip']}" + ('' if row['available'] else '（不可用）')
            choices[description] = (row['ip'], row['available'])
        ips = [ip for ip, _ in choices.values()]
        if dialog.source_ip not in ips:
            choices[dialog.source_ip + '（原设置，当前不可用）'] = (dialog.source_ip, False)
            ips.append(dialog.source_ip)
        index = ips.index(dialog.source_ip)
        selected, accepted = QInputDialog.getItem(dialog, '指定出口 IP', '本机 IPv4', tuple(choices), index, False)
        if accepted and selected in choices:
            if self.windows.get(dialog.project_id) is not dialog:
                return
            ip, available = choices[selected]
            if available:
                self.submit(dialog, 'ai_model_source_check', (ip,))
            else:
                dialog.feedback.show_review('所选地址当前不可用，保留原出口 IP', lambda: focus_widget(dialog.source))

    def prune(self, opened):
        for identifier, dialog in tuple(self.windows.items()):
            if self.workspace.closing or identifier not in opened:
                dialog.close()
