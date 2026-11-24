"""Present an actionable warning and focus its existing control without invoking it."""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QScrollArea, QStackedWidget, QTabWidget, QWidget

from src.ui.qt.theme import button, label


def show_warning(parent, title, message, review=None):
    if review is None:
        QMessageBox.warning(parent, title, message)
        return
    box = QMessageBox(QMessageBox.Icon.Warning, title, message, QMessageBox.StandardButton.Ok, parent)
    box.setTextFormat(Qt.TextFormat.PlainText)
    close = box.button(QMessageBox.StandardButton.Ok)
    close.setText('确定')
    box.setDefaultButton(close)
    box.setEscapeButton(close)
    go = box.addButton('前往确认', QMessageBox.ButtonRole.ActionRole)
    def finished(_):
        selected = box.clickedButton() is go
        box.deleteLater()
        if selected:
            review()

    box.finished.connect(finished)
    box.open()


class ReviewFeedback(QWidget):
    """An existing feedback row with an action that clears when the feedback changes."""
    def __init__(self, text='', role=''):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.message = label(text, role)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message, 1)
        self.review_button = button('前往确认', self._go)
        self.review_button.setAutoDefault(False)
        layout.addWidget(self.review_button)
        self.review_button.hide()
        self._review = None

    def _go(self):
        if self._review is not None:
            self._review()

    def show_review(self, message, review):
        self.setText(message)
        self._review = review
        self.review_button.setVisible(review is not None)

    def setText(self, text):
        if text != self.message.text():
            self._review = None
            self.review_button.hide()
        self.message.setText(text)

    def text(self):
        return self.message.text()

    def clear(self):
        self.show_review('', None)

    def setWordWrap(self, value):
        self.message.setWordWrap(value)


def focus_widget(widget):
    if widget is None:
        return False
    # Select the enclosing page before scrolling or setting keyboard focus.
    parents = []
    child = widget
    while child.parentWidget() is not None:
        parent = child.parentWidget()
        parents.append((parent, child))
        child = parent
    for parent, child in reversed(parents):
        if isinstance(parent, QStackedWidget) and parent.indexOf(child) >= 0:
            tab = parent.parentWidget()
            if isinstance(tab, QTabWidget):
                tab.setCurrentIndex(tab.indexOf(child))
            else:
                parent.setCurrentWidget(child)
        elif isinstance(parent, QScrollArea) and parent.widget() is not None and parent.widget().isAncestorOf(widget):
            parent.ensureWidgetVisible(widget)
    widget.setFocus(Qt.FocusReason.OtherFocusReason)
    return True


class BlockerReview:
    def __init__(self, workspace):
        self.workspace = workspace
        self.pending = None
        self.waiting_for_editor = False
        self._status_button = None
        self._status_action = None

    def action(self, result, identifier=''):
        target = getattr(result, 'review', None)
        if target is None:
            return None
        identifier = target.project_id or result.project_id or identifier
        return lambda: self.open(identifier, target)

    def warning(self, result, title, parent=None, identifier=''):
        show_warning(parent or self.workspace.window, title, result.error, self.action(result, identifier))

    def inline(self, dialog, result, identifier=''):
        dialog.feedback.show_review(result.error, self.action(result, identifier))

    def status(self, message, identifier, target):
        bar = self.workspace.window.statusBar()
        if self._status_button is None:
            self._status_button = button('前往确认', self._go_from_status)
            bar.addPermanentWidget(self._status_button)
            bar.messageChanged.connect(self._clear_status_action)
        bar.showMessage(message, 8000)
        self._status_action = (identifier, target)
        self._status_button.show()

    def _clear_status_action(self, _message):
        self._status_action = None
        self._status_button.hide()

    def _go_from_status(self):
        if self._status_action is not None:
            identifier, target = self._status_action
            self._clear_status_action('')
            self.open(identifier, target)

    def _report(self, identifier, message, *, level='INFO'):
        workspace = self.workspace
        workspace.window.statusBar().showMessage(message, 7000)
        workspace.adapter.record_review(identifier, message, level)

    def _unavailable(self, identifier):
        self._report(identifier, '无法定位需要确认的内容，请核对当前项目与任务状态', level='WARN')

    def open(self, identifier, target):
        workspace = self.workspace
        window = workspace.window
        self.pending = None
        self.waiting_for_editor = False
        if workspace.closing or not workspace.ready:
            self._unavailable(identifier)
            return
        if identifier:
            if not any(project.project_id == identifier for project in window.projects):
                self._unavailable(identifier)
                return
            window.select_project(identifier)
            if window.selected_project != identifier:
                self._unavailable(identifier)
                return
        page = target.page
        if page in ('project', 'log', 'inventory'):
            if not self._show_workspace_page(identifier, target):
                self._unavailable(identifier)
            else:
                self._report(identifier, '已定位需要确认的内容')
            return
        if page in ('editor', 'channels', 'configuration'):
            editor = workspace.configuration_editors.get(identifier)
            if page == 'editor':
                self._show_dialog(identifier, editor, target)
                return
            if editor is not None:
                if editor.editor_kind == page:
                    self._show_dialog(identifier, editor, target)
                    return
                self.pending = (identifier, target)
                self.waiting_for_editor = True
                editor.showNormal()
                editor.raise_()
                editor.activateWindow()
                message = '请先处理当前配置窗口中的修改，窗口关闭后将打开需要核对的配置'
                editor.feedback.setText(message)
                self._report(identifier, message)
                return
            project = workspace._current()
            if project is None or not project.can_configure:
                self._unavailable(identifier)
                return
            self.pending = (identifier, target)
            workspace._open_editor(page)
            if identifier not in workspace._configuration_pending:
                self.pending = None
                self._unavailable(identifier)
            return
        dialogs = {
            'serial': workspace.serial_windows,
            'upgrade': workspace.upgrade_windows,
            'dut': workspace.dut_windows,
            'parameter': workspace.parameter_writer.windows,
            'onu': workspace.onu_query.windows,
            'pipeline': workspace.pipeline_windows,
            'model': workspace.model_settings.windows,
        }
        dialog = dialogs.get(page, {}).get(identifier)
        if page == 'wizard':
            dialog = workspace.project_wizard.dialog
            if dialog is not None and dialog.project_id != identifier:
                self._unavailable(identifier)
                return
        elif page == 'single_power':
            dialog = workspace._single_power_dialog
            if dialog is not None and dialog.project_id != identifier:
                self._unavailable(identifier)
                return
        elif page == 'platform':
            dialog = workspace.platform_configuration_dialog
            if dialog is not None and (dialog.project_id != identifier or dialog.kind != target.reference):
                self._unavailable(identifier)
                return
        elif page == 'extensions':
            dialog = workspace.extensions_dialog
            if dialog is not None and dialog.project_id != identifier:
                self._unavailable(identifier)
                return
        if dialog is not None:
            self._show_dialog(identifier, dialog, target)
            return
        openers = {
            'wizard': workspace.open_project_setup,
            'serial': workspace.open_serial,
            'upgrade': workspace.open_upgrade,
            'dut': workspace.open_dut,
            'parameter': workspace.parameter_writer.open,
            'onu': workspace.onu_query.open,
            'pipeline': workspace.open_pipeline,
            'single_power': workspace.open_single_power,
            'model': workspace.model_settings.open,
        }
        opener = openers.get(page)
        if opener is None or not identifier:
            self._unavailable(identifier)
            return
        self.pending = (identifier, target)
        opener()
        if page == 'pipeline':
            self.finish(identifier, page, workspace.pipeline_windows.get(identifier))

    def _show_workspace_page(self, identifier, target):
        workspace = self.workspace
        window = workspace.window
        if target.page == 'inventory':
            workspace.open_device_inventory(refresh_initial=False)
            dialog = workspace.device_inventory_dialog
            return bool(dialog and dialog.focus_resource(target.reference))
        if target.page == 'log':
            if not identifier:
                window.show_dashboard()
            logs = window.logs
            if not logs.expanded:
                logs.toggle_expanded()
            if not identifier and logs.project_filter is not None:
                logs.project_filter.setCurrentIndex(0)
            index = logs.scope.findData(target.channels[0] if target.channels else 'project')
            if index >= 0:
                logs.scope.setCurrentIndex(index)
            if target.reference:
                logs.level.setCurrentIndex(0)
                logs.search.setText(target.reference)
            return focus_widget(logs.text)
        if not identifier:
            return False
        if target.field == 'save':
            button = workspace.project_menu_button
            anchor = button if button.isVisible() else window.navigation.viewport()
            workspace._sync_actions()
            workspace.menu.popup(anchor.mapToGlobal(QPoint(0, anchor.height() if anchor is button else 0)))
            workspace.menu.setActiveAction(workspace.save_action)
            return True
        if target.field == 'task':
            return focus_widget(window.detail.stop_button if window.detail.stop_button.isEnabled() else window.detail.state)
        if target.field == 'channel' and target.channels:
            number = target.channels[0]
            if (window.detail.project is not None and
                    any(channel.number == number for channel in window.detail.project.channels)):
                window.detail.open_channel(number)
                return True
            return False
        if target.field == 'business':
            return focus_widget(window.detail.test_type_panel.table)
        return focus_widget(window.detail.start_button)

    def _show_dialog(self, identifier, dialog, target):
        if dialog is None:
            self._unavailable(identifier)
            return
        dialog.showNormal()
        dialog.raise_()
        dialog.activateWindow()
        if target.page == 'editor':
            located = focus_widget(dialog.close_button)
        elif hasattr(dialog, 'focus_review'):
            located = dialog.focus_review(target)
        else:
            located = focus_widget(getattr(dialog, target.field, None))
        if located:
            self._report(identifier, '已定位需要确认的内容')
        else:
            self._unavailable(identifier)

    def finish(self, identifier, page, dialog):
        if self.pending is None:
            return
        expected, target = self.pending
        if expected != identifier or target.page != page or self.waiting_for_editor:
            return
        self.pending = None
        if self.workspace.closing or self.workspace.window.selected_project != identifier:
            return
        self._show_dialog(identifier, dialog, target)

    def editor_closed(self, identifier, succeeded):
        if self.pending is None or not self.waiting_for_editor or self.pending[0] != identifier:
            return
        _, target = self.pending
        self.pending = None
        self.waiting_for_editor = False
        if self.workspace.closing or self.workspace.window.selected_project != identifier:
            return
        if succeeded:
            self.open(identifier, target)
        else:
            self._unavailable(identifier)
