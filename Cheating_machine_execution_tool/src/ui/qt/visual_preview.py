"""Isolated review of the workbench styling with fictional snapshots."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QHBoxLayout,
                               QStackedWidget, QVBoxLayout, QWidget)

from src.ui.qt.main_window import MainWindow
from src.ui.qt.theme import button, label
from src.ui.qt.visual_preview_data import AGING, POWER, preview_snapshots


class PreviewWorkbench(MainWindow):
    def __init__(self, projects, logs, health, *, revised):
        super().__init__(projects, logs, demo=True, refreshed=revised)
        self.mode_label.setText('样式预览 · 模拟数据')
        panel = self.dashboard.system_health
        panel.update_status(health, 0.6, 22, len(logs), projects)
        panel.show()
        self.vertical.setSizes((660, 145))
        self.detail.start_button.clicked.connect(lambda: self._confirm('启动'))
        self.detail.stop_button.clicked.connect(lambda: self._confirm('停止'))

    def _confirm(self, action):
        dialog = QDialog(self)
        dialog.setWindowTitle(f'确认{action} · 样式预览')
        layout = QVBoxLayout(dialog)
        layout.addWidget(label(f'{action}「{self.detail.project.name}」的模拟任务？'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(action)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText('取消')
        cancel.setDefault(True)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog.accepted.connect(lambda: self.statusBar().showMessage(f'已确认{action}模拟任务', 4000))
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout.addWidget(buttons)
        dialog.open()
        cancel.setFocus()


class VisualPreview(QWidget):
    """Switch between original and proposed layouts using identical snapshots."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle('DUTPilot · GUI 改版预览')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        controls = QWidget(self)
        bar = QHBoxLayout(controls)
        bar.setContentsMargins(10, 5, 10, 5)
        self.pages = QStackedWidget(self)
        data = preview_snapshots()
        self.original = PreviewWorkbench(*data, revised=False)
        self.proposed = PreviewWorkbench(*data, revised=True)
        self.pages.addWidget(self.original)
        self.pages.addWidget(self.proposed)

        self.variants = QButtonGroup(self)
        for index, name in enumerate(('当前版', '改版预览')):
            control = button(name)
            control.setCheckable(True)
            self.variants.addButton(control, index)
            bar.addWidget(control)
        self.variants.idClicked.connect(self._show_variant)
        self.variants.button(1).setChecked(True)
        self.pages.setCurrentIndex(1)
        bar.addStretch()
        for name, project_id in (('总览', ''), ('自动开关机', POWER), ('全业务老化', AGING)):
            bar.addWidget(button(name, lambda _checked=False, pid=project_id: self.show_page(pid)))
        bar.addWidget(button('业务窗口预览…', self._open_module_preview))
        layout.addWidget(controls)
        layout.addWidget(self.pages, 1)

    def _show_variant(self, index):
        old = self.pages.currentWidget()
        new = self.pages.widget(index)
        if old.selected_project:
            new.select_project(old.selected_project)
        elif old.pages.currentWidget() is old.templates_page:
            new.show_templates()
        else:
            new.show_dashboard()
        self.pages.setCurrentIndex(index)

    def show_page(self, identifier):
        workbench = self.pages.currentWidget()
        if identifier:
            workbench.select_project(identifier)
        else:
            workbench.show_dashboard()

    def _open_module_preview(self):
        from src.ui.qt.module_visual_preview import ModuleVisualPreview

        ModuleVisualPreview(self).open()
