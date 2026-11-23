"""Read-only browser for structured workspace events and original text archives."""
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QComboBox, QDialog, QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from src.models.workbench_presentation import LogView
from src.ui.qt.log_panel import LogPanel
from src.ui.qt.theme import button, label


class ArchivedLogsDialog(QDialog):
    page_requested = Signal(str, object, object)
    files_requested = Signal(str)

    def __init__(self, project, parent=None, *, projects=()):
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
        self.source.addItem('结构化事件', 'events')
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
        self.event_filters = QWidget()
        filters = QGridLayout(self.event_filters)
        filters.setContentsMargins(0, 0, 0, 0)
        self.event_project = self._identity_box('全部项目', '选择项目或输入历史项目 ID')
        for entry in projects:
            self.event_project.addItem(f'{entry.name} · {entry.project_id[:8]}', entry.project_id)
            self.event_project.setItemData(self.event_project.count() - 1, entry.project_id, Qt.ItemDataRole.ToolTipRole)
        self.event_project.setCurrentIndex(max(0, self.event_project.findData(self.project_id)))
        self.event_dut = self._identity_box('全部 DUT', '选择 DUT 或输入历史 DUT ID')
        identities = {}
        for entry in projects:
            for dut in (entry.test_overview or {}).get('rows', ()):
                if dut.get('dut_id'):
                    identities[dut['dut_id']] = dut.get('label') or dut['dut_id']
        for identifier, name in identities.items():
            self.event_dut.addItem(f'{name} · {identifier[:8]}', identifier)
        self.event_channel = QComboBox()
        self.event_channel.addItem('全部通道', None)
        for channel in range(1, 17):
            self.event_channel.addItem(f'CH{channel:02d}', channel)
        self.event_level = QComboBox()
        self.event_level.addItem('全部等级', None)
        for level in ('INFO', 'SUCCESS', 'WARN', 'ERROR', 'DEBUG'):
            self.event_level.addItem(level, level)
        for i, (title, control) in enumerate((('项目', self.event_project), ('DUT', self.event_dut),
                                              ('通道', self.event_channel), ('等级', self.event_level))):
            row, col = divmod(i, 2)
            control.setAccessibleName('结构化事件' + title)
            filters.addWidget(label(title), row, col * 2)
            filters.addWidget(control, row, col * 2 + 1)
            control.currentTextChanged.connect(self._filters_changed)
        layout.addWidget(self.event_filters)
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

    @staticmethod
    def _identity_box(all_text, hint):
        box = QComboBox()
        box.setEditable(True)
        box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        box.addItem(all_text, None)
        box.setToolTip(hint)
        box.lineEdit().setPlaceholderText(hint)
        return box

    @staticmethod
    def _identity(box):
        value = box.currentText().strip()
        if value == box.itemText(box.currentIndex()):
            return box.currentData()
        return value or None

    def filters(self):
        return dict(project_id=self._identity(self.event_project), dut_id=self._identity(self.event_dut),
                    channel=self.event_channel.currentData(), level=self.event_level.currentData())

    def _filters_changed(self):
        if self.source.currentData() == 'events':
            self.cursor = None
            self.logs.clear_display()
            self.older.setEnabled(False)
            self.feedback.setText('筛选条件已更改，点击查询最新事件')

    def set_busy(self, busy):
        self.busy = busy
        source = self.source.currentData()
        has_files = source in ('project', 'serial')
        self.event_filters.setVisible(source == 'events')
        self.event_filters.setEnabled(not busy)
        self.latest.setText('查询最新事件' if source == 'events' else '最新日志')
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
        source = self.source.currentData()
        self.set_busy(self.busy)
        if source in ('serial', 'project'):
            with QSignalBlocker(self.files):
                self.files.clear()
            self.files.setToolTip('')
            self.logs.title.setText(self._file_title())
            self.logs.set_scope(self.project_id, self.project_name)
            self.files_requested.emit(self.source.currentData())
        else:
            self.logs.title.setText('结构化事件' if source == 'events' else '工作区日志原文')
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
        self.cursor = None
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
        if source == 'events':
            if not self.busy:
                self.page_requested.emit(source, self.filters(), cursor)
            return
        file = self.files.currentData() if source != 'workspace' else None
        if not self.busy and (source == 'workspace' or file is not None):
            self.page_requested.emit(source, file.path if file is not None else None, cursor)

    def show_events(self, rows):
        page = rows[:100]
        self.cursor = page[-1]['cursor'] if len(rows) > len(page) else None
        self.logs.clear_display()
        entries = []
        for row in reversed(page):
            parts = [row['observed'], row['level']]
            for key, title in (('project_name', ''), ('project_id', '项目 ID '), ('dut_id', 'DUT '),
                               ('channel', '通道 '), ('step', '步骤 '), ('job_id', 'Job '), ('run_id', '批次 ')):
                value = row[key]
                if value is not None and value != '':
                    parts.append(title + str(value))
            text = ' · '.join(parts) + '\n' + row['message']
            entries.append(LogView(row['time'], row['level'], row['project_id'], row['project_name'], text,
                                   channel=row['channel'], raw=True, dut_id=row['dut_id'], step=row['step'],
                                   job_id=row['job_id'], batch_id=row['run_id']))
        self.logs.append_batch(entries)
        self.set_busy(False)
        self.feedback.setText(f'本页 {len(page)} 条结构化事件' if page else '没有符合筛选条件的结构化事件')

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
        self.queued = None

    def open(self):
        if not self.workspace.ready or self.workspace.closing:
            return
        project = self.workspace._current()
        identifier = project.project_id if project else ''
        if self.dialog is not None and self.dialog.project_id != identifier:
            self.dialog.close()
        if self.dialog is not None:
            self.dialog.showNormal()
            self.dialog.raise_()
            return
        dialog = ArchivedLogsDialog(project, self.workspace.window, projects=self.workspace.window.projects)
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
        elif source == 'events':
            self._submit('archive_workspace_events', path, cursor)
        else:
            self._submit('archive_' + source + '_log', path, cursor)

    def _submit(self, operation, *args):
        dialog = self.dialog
        if dialog is None or dialog.busy or self.workspace.closing:
            return
        if self.requests:
            self.queued = (dialog, operation, args)
            dialog.set_busy(True)
            return
        request = self.workspace.submit(operation, dialog.project_id, *args)
        if request is not None:
            self.requests[request] = (dialog, dialog.source.currentData(), dialog.filters())
            dialog.set_busy(True)

    def handle_result(self, result):
        target = self.requests.pop(result.identifier, None)
        if target is None:
            return False
        dialog, source, filters = target
        if dialog is not self.dialog or self.workspace.closing:
            if self.queued:
                view, operation, args = self.queued
                self.queued = None
                if view is self.dialog and not self.workspace.closing:
                    view.set_busy(False)
                    self._submit(operation, *args)
            return True
        if source != dialog.source.currentData():
            dialog.set_busy(False)
            dialog.refresh_source()
            return True
        if source == 'events' and filters != dialog.filters():
            dialog.set_busy(False)
            dialog._filters_changed()
            return True
        if result.error:
            dialog.set_busy(False)
            dialog.feedback.setText(result.error)
        elif result.operation in ('archive_serial_files', 'archive_project_files'):
            dialog.show_files(result.payload)
        elif result.operation == 'archive_workspace_events':
            dialog.show_events(result.payload)
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
