"""One read-only browser for original workspace and serial text."""
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QSizePolicy, QVBoxLayout

from src.ui.qt.log_panel import LogPanel
from src.ui.qt.theme import button, label


class ArchivedLogsDialog(QDialog):
    page_requested = Signal(str, object, object)
    files_requested = Signal(str)

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('归档日志')
        self.project_id = project.project_id if project else ''
        self.project_name = project.name if project else ''
        self.cursor = None
        self.busy = False
        self.setMinimumSize(590, 340)
        available = self.screen().availableGeometry()
        self.resize(min(1050, int(available.width() * .94)), min(650, int(available.height() * .90)))
        layout = QVBoxLayout(self)
        layout.addWidget(label('归档日志', 'title'))
        top = QHBoxLayout()
        self.source = QComboBox()
        self.source.addItem('工作区日志', 'workspace')
        if project:
            self.source.addItem('项目串口 · ' + self.project_name, 'serial')
            self.source.addItem('项目主日志 · ' + self.project_name, 'project')
        self.source.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.source.setMaximumWidth(230)
        top.addWidget(self.source)
        self.files = QComboBox()
        self.files.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        top.addWidget(self.files, 1)
        self.refresh_files = button('刷新文件', lambda: self.files_requested.emit(self.source.currentData()))
        top.addWidget(self.refresh_files)
        layout.addLayout(top)
        self.logs = LogPanel(history=True, raw=True)
        layout.addWidget(self.logs, 1)
        footer = QHBoxLayout()
        self.feedback = label('', 'muted')
        self.feedback.setWordWrap(True)
        footer.addWidget(self.feedback, 1)
        self.latest = button('最新日志', lambda: self._read(None))
        self.older = button('更早日志', lambda: self._read(self.cursor))
        footer.addWidget(self.latest)
        footer.addWidget(self.older)
        footer.addWidget(button('关闭', self.close))
        layout.addLayout(footer)
        self.source.currentIndexChanged.connect(self.refresh_source)
        self.files.currentIndexChanged.connect(self._choose_file)
        self.set_busy(False)

    def set_busy(self, busy):
        self.busy = busy
        has_files = self.source.currentData() != 'workspace'
        self.source.setEnabled(not busy)
        self.files.setVisible(has_files)
        self.refresh_files.setVisible(has_files)
        self.files.setEnabled(not busy and bool(self.files.count()))
        self.refresh_files.setEnabled(not busy)
        self.latest.setEnabled(not busy and (not has_files or self.files.currentData() is not None))
        self.older.setEnabled(not busy and self.cursor is not None)
        if busy:
            self.feedback.setText('正在读取归档…')
            self.logs.set_export_enabled(False)

    def refresh_source(self, *_):
        self.cursor = None
        self.logs.clear_display()
        if self.source.currentData() != 'workspace':
            with QSignalBlocker(self.files):
                self.files.clear()
            self.files.setToolTip('')
            self.logs.title.setText(self._file_title())
            self.logs.set_scope(self.project_id, self.project_name)
            self.files_requested.emit(self.source.currentData())
        else:
            self.logs.title.setText('工作区日志原文')
            self.logs.set_scope()
            self._read(None)

    def show_files(self, files):
        old = self.files.currentData()
        with QSignalBlocker(self.files):
            self.files.clear()
            for entry in files:
                self.files.addItem(entry.label, entry)
                self.files.setItemData(self.files.count() - 1, str(entry.path), Qt.ItemDataRole.ToolTipRole)
            index = next((i for i, entry in enumerate(files) if entry == old), 0)
            if files:
                self.files.setCurrentIndex(index)
        self.set_busy(False)
        self._choose_file()

    def _choose_file(self, *_):
        self.cursor = None
        self.logs.clear_display()
        file = self.files.currentData()
        if file is not None:
            self.files.setToolTip(str(file.path))
            self.logs.title.setText(self._file_title() + ' · ' + file.path.name)
            self._read(None)
        else:
            self.files.setToolTip('')
            self.logs.title.setText(self._file_title())
            self.feedback.setText('当前项目没有可读的' + self._file_title().removesuffix('原文'))

    def _file_title(self):
        return '项目主日志原文' if self.source.currentData() == 'project' else '串口日志原文'

    def _read(self, cursor):
        source = self.source.currentData()
        file = self.files.currentData() if source != 'workspace' else None
        if not self.busy and (source == 'workspace' or file is not None):
            self.page_requested.emit(source, file.path if file is not None else None, cursor)

    def show_page(self, page):
        self.cursor = page.next_cursor
        self.logs.clear_display()
        self.logs.append_batch(page.entries)
        self.set_busy(False)
        message = f'本页 {len(page.entries)} 行 · 搜索和导出仅作用于本页' if page.entries else '没有可读的日志'
        self.feedback.setText(message + ('。' + page.note if page.note else ''))


class ArchivedLogsController:
    def __init__(self, workspace):
        self.workspace = workspace
        self.dialog = None
        self.requests = {}

    def open(self):
        if not self.workspace.ready or self.workspace.closing:
            return
        if self.dialog is not None:
            self.dialog.showNormal()
            self.dialog.raise_()
            return
        dialog = ArchivedLogsDialog(self.workspace._current(), self.workspace.window)
        self.dialog = dialog
        dialog.files_requested.connect(lambda source: self._submit('archive_' + source + '_files'))
        dialog.page_requested.connect(self._read)
        dialog.logs.export_requested.connect(lambda entries, description: self.workspace.export_logs(entries, description, dialog))
        dialog.finished.connect(lambda _: setattr(self, 'dialog', None))
        dialog.show()
        dialog.refresh_source()

    def _read(self, source, path, cursor):
        if source == 'workspace':
            self._submit('archive_workspace_log', cursor)
        else:
            self._submit('archive_' + source + '_log', path, cursor)

    def _submit(self, operation, *args):
        dialog = self.dialog
        if dialog is None or dialog.busy or self.workspace.closing:
            return
        request = self.workspace.submit(operation, dialog.project_id, *args)
        if request is not None:
            self.requests[request] = dialog
            dialog.set_busy(True)

    def handle_result(self, result):
        dialog = self.requests.pop(result.identifier, None)
        if dialog is None:
            return False
        if dialog is not self.dialog or self.workspace.closing:
            return True
        if result.error:
            dialog.set_busy(False)
            dialog.feedback.setText(result.error)
        elif result.operation in ('archive_serial_files', 'archive_project_files'):
            dialog.show_files(result.payload)
        else:
            dialog.show_page(result.payload)
        return True

    def set_export_enabled(self, enabled):
        if self.dialog is not None:
            self.dialog.logs.set_export_enabled(enabled and not self.dialog.busy)

    def prune(self, opened):
        dialog = self.dialog
        if dialog is not None and (self.workspace.closing or dialog.project_id and dialog.project_id not in opened):
            dialog.close()
