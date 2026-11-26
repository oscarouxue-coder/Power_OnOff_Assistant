"""Project-bound viewer for one page of original job events at a time."""
from dataclasses import replace
from threading import Event
from PySide6.QtCore import QEvent, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QSizePolicy, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from src.models.qt_log_history import (HistoryEventFilter, HistoryMaterialBatchSummary, HistoryMaterialBatchTarget,
                                      HistoryMaterialSummary, HistoryMaterialTarget, SavedMaterialReport,
                                      SavedMaterialReports)
from src.services.qt_power_logs import POWER_HISTORY_CAPABILITIES
from src.services.workbench_status_service import TASK_NAMES
from src.ui.qt.log_panel import LogPanel
from src.ui.qt.theme import button, label


JOB_STATES = {'queued': '记录为等待', 'running': '记录为运行中', 'stop_requested': '记录为停止中', 'succeeded': '已完成',
              'failed': '失败', 'stopped': '已停止', 'skipped': '未执行', 'unknown': '结果未知'}


class HistoryResultFilesDialog(QDialog):
    open_requested = Signal(object)
    summary_requested = Signal(object)
    summary_cancelled = Signal()
    summary_scope_changed = Signal()
    save_report_requested = Signal(int, object)

    def __init__(self, parent, job, files):
        super().__init__(parent)
        self.project_id, self.job, self.entries = parent.project_id, job, tuple(files)
        self.summary_pending = False
        self._generated_report = None
        self.save_pending = False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowTitle('批次结果文件 · ' + parent.project_name)
        available = self.screen().availableGeometry()
        self.resize(min(760, int(available.width() * .94)), min(390, int(available.height() * .90)))
        layout = QVBoxLayout(self)
        batch = label('任务 ' + job[:8], 'section')
        batch.setToolTip(job)
        layout.addWidget(batch)
        self.files = QListWidget()
        self.files.setAccessibleName('批次结果文件')
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files.setToolTip('Ctrl 多选通道或文件，右键汇总；同通道同类型最多选一份')
        for entry in self.entries:
            item = QListWidgetItem(entry.label, self.files)
            item.setData(Qt.ItemDataRole.UserRole, entry.path)
            item.setData(Qt.ItemDataRole.UserRole + 1, entry)
        self.files.setCurrentRow(0)
        self.files.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self._file_menu)
        self.file_menu = QMenu(self.files)
        self.summary_action = self.file_menu.addAction('汇总所选通道留存资料…', self._request_summary)
        self.save_report_action = self.file_menu.addAction('保存本次留存报告', self._request_save_report)
        self.save_report_action.setEnabled(False)
        self.summary_action.setToolTip('可 Ctrl 多选；每通道选中文件及未选的另一类文件（文件名倒序第一份）；仅读取末页')
        layout.addWidget(self.files, 1)
        self.summary = QPlainTextEdit()
        self.summary.setAccessibleName('留存资料汇总')
        self.summary.setReadOnly(True)
        self.summary.hide()
        layout.addWidget(self.summary, 2)
        self.feedback = label('', 'muted')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        actions = QHBoxLayout()
        actions.addStretch()
        self.open_button = button('打开文件', self._open, 'primary')
        actions.addWidget(self.open_button)
        self.summary_cancel = button('取消本次读取', self.summary_cancelled.emit)
        self.summary_cancel.hide()
        actions.addWidget(self.summary_cancel)
        actions.addWidget(button('关闭', self.close))
        layout.addLayout(actions)
        self.files.itemSelectionChanged.connect(self._summary_selection_changed)

    def _open(self):
        items = self.files.selectedItems()
        if len(items) == 1:
            self.open_requested.emit(items[0].data(Qt.ItemDataRole.UserRole))

    def set_busy(self, busy):
        self.files.setEnabled(not busy)
        self.open_button.setEnabled(not busy and len(self.files.selectedItems()) == 1)
        if busy:
            self.feedback.setText('正在打开结果文件…')

    def _file_menu(self, point):
        if not self.summary_pending and not self.save_pending and self.files.currentItem() is not None:
            item = self.files.itemAt(point)
            if item is not None and not item.isSelected():
                self.files.setCurrentItem(item)
            self.file_menu.popup(self.files.viewport().mapToGlobal(point))

    def _summary_selection_changed(self, *_):
        if self.summary_pending or self.save_pending:
            self.summary_scope_changed.emit()
        self._generated_report = None
        self.save_report_action.setEnabled(False)
        self.open_button.setEnabled(self.files.isEnabled() and len(self.files.selectedItems()) == 1)
        self.summary.clear()
        self.summary.hide()

    def summary_target(self):
        groups = {}
        run = None
        for item in self.files.selectedItems():
            entry = item.data(Qt.ItemDataRole.UserRole + 1)
            if entry is None or entry.channel is None or not entry.run_id or entry.kind not in ('command_results', 'wifi'):
                return None
            if run is not None and entry.run_id != run:
                return None
            run = entry.run_id
            group = groups.setdefault(entry.channel, {})
            if entry.kind in group:
                return None
            group[entry.kind] = entry.path.name
        if not groups:
            return None
        for candidate in self.entries:
            if candidate.channel in groups and candidate.run_id == run:
                groups[candidate.channel].setdefault(candidate.kind, candidate.path.name)
        targets = tuple(HistoryMaterialTarget(self.project_id, self.job, run, channel,
                                             names.get('command_results', ''), names.get('wifi', ''))
                        for channel, names in sorted(groups.items()))
        return targets[0] if len(targets) == 1 else HistoryMaterialBatchTarget(self.project_id, self.job, run, targets)

    def _request_summary(self):
        target = self.summary_target()
        if target is not None and not self.summary_pending and not self.save_pending:
            self.summary_requested.emit(target)
        elif not self.summary_pending:
            self.feedback.setText('请选择同一批次的通道；每通道同类文件最多选一份。')

    def set_summary_pending(self, pending):
        self.summary_pending = pending
        self.set_busy(pending)
        self.summary_action.setEnabled(not pending)
        self.summary_cancel.setVisible(pending)
        self.summary_cancel.setEnabled(pending)
        if pending:
            self._generated_report = None
            self.save_report_action.setEnabled(False)
            self.summary.clear()
            self.summary.hide()

    def show_summary(self, identifier, summary):
        self.set_summary_pending(False)
        self.summary.setPlainText(f'留存资料汇总 #{identifier}\n\n' + summary.text)
        self.summary.show()
        if not isinstance(summary, HistoryMaterialBatchSummary) or (summary.completed_count and not summary.cancelled_count):
            self._generated_report = (identifier, summary.target)
            self.save_report_action.setEnabled(True)
        self.feedback.setText('已取消未完成的通道；已完成的结果保留。' if isinstance(summary, HistoryMaterialBatchSummary)
                              and summary.cancelled_count else '已完成本次核对；缺失或无法读取的资料见报告。')

    def _request_save_report(self):
        if (self._generated_report is not None and not self.summary_pending and not self.save_pending
                and self._generated_report[1] == self.summary_target()):
            self.save_report_requested.emit(*self._generated_report)

    def set_save_pending(self, pending, *, saved=False):
        self.save_pending = pending
        self.set_busy(pending)
        self.summary_action.setEnabled(not pending)
        if saved:
            self._generated_report = None
        self.save_report_action.setEnabled(not pending and self._generated_report is not None)


class SavedMaterialReportsDialog(QDialog):
    def __init__(self, parent, job, page):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowTitle('已保存留存报告 · ' + parent.project_name)
        self.job, self.run_id = job, page.run_id
        available = self.screen().availableGeometry()
        self.resize(min(850, int(available.width() * .94)), min(660, int(available.height() * .90)))
        layout = QVBoxLayout(self)
        self.reports = QListWidget()
        self.reports.setAccessibleName('已保存留存报告')
        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        self.body.setAccessibleName('历史报告正文')
        self.feedback = label(f'已保存 {len(page.reports)} 份；无法读取 {page.invalid_count} 份', 'muted')
        for report in page.reports:
            item = QListWidgetItem(report.saved_at + ' · ' + ', '.join(f'CH{n:02d}' for n in report.channels), self.reports)
            item.setData(Qt.ItemDataRole.UserRole, report)
        self.reports.currentItemChanged.connect(self._show_report)
        layout.addWidget(self.reports, 1)
        layout.addWidget(self.body, 3)
        layout.addWidget(self.feedback)
        layout.addWidget(button('关闭', self.close))
        self.reports.setCurrentRow(0)

    def _show_report(self, current, previous):
        report = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.body.setPlainText(f'保存记录 {report.report_id}\n历史状态 {report.historical_state} · {report.historical_at}'
                               f'\n生成时间 {report.generated_at}\n保存时间 {report.saved_at}'
                               '\n已保存历史报告，不代表实时状态；未重新读取资料。\n\n' + report.text
                               if isinstance(report, SavedMaterialReport) else '')


class LogHistoryDialog(QDialog):
    jobs_requested = Signal(object)
    legacy_requested = Signal(object)
    events_requested = Signal(str, object, object)
    stop_requested = Signal(str)
    result_files_requested = Signal(str)
    saved_reports_requested = Signal(str)

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(project.name + ' · 任务历史')
        self.project_id, self.project_name = project.project_id, project.name
        self.jobs_cursor = self.events_cursor = self.legacy_cursor = None
        self.source_generation = 0
        self.page_filter = HistoryEventFilter()
        self.busy = False
        self.result_files_dialog = None
        self.saved_reports_dialog = None
        self.setMinimumSize(650, 390)
        available = self.screen().availableGeometry()
        self.resize(min(1050, int(available.width() * .94)), min(680, int(available.height() * .90)))

        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        heading.addWidget(label('任务历史 · ' + project.name, 'title'), 1)
        heading.addWidget(label('来源'))
        self.source = QComboBox()
        self.source.setAccessibleName('历史来源')
        self.source.addItem('业务任务', 'jobs')
        self.source.addItem('旧工作台运行记录', 'legacy')
        heading.addWidget(self.source)
        layout.addLayout(heading)

        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        jobs_page = QWidget()
        jobs_layout = QVBoxLayout(jobs_page)
        jobs_layout.setContentsMargins(0, 0, 0, 0)
        self.pages.addWidget(jobs_page)
        jobs_bar = QHBoxLayout()
        jobs_bar.addWidget(label('任务'))
        self.jobs = QComboBox()
        self.jobs.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.jobs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.jobs.customContextMenuRequested.connect(self._job_menu)
        self.job_menu = QMenu(self.jobs)
        self.stop_action = self.job_menu.addAction('请求安全停止…', self._request_stop)
        self.result_files_action = self.job_menu.addAction('查看批次结果文件…', self._request_result_files)
        self.saved_reports_action = self.job_menu.addAction('查看已保存留存报告…', self._request_saved_reports)
        jobs_bar.addWidget(self.jobs, 1)
        self.newest_jobs = button('最新任务', lambda: self.jobs_requested.emit(None))
        self.older_jobs = button('更早任务', lambda: self.jobs_requested.emit(self.jobs_cursor))
        jobs_bar.addWidget(self.newest_jobs)
        jobs_bar.addWidget(self.older_jobs)
        jobs_layout.addLayout(jobs_bar)
        self.logs = LogPanel(history=True)
        jobs_layout.addWidget(self.logs, 1)
        self.legacy_table = QTableWidget(0, 6)
        self.legacy_table.setAccessibleName('旧工作台运行记录')
        self.legacy_table.setHorizontalHeaderLabels(('运行 ID', '操作', '状态', '配置版本', '开始时间', '结束时间'))
        self.legacy_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.legacy_table.verticalHeader().hide()
        self.legacy_table.setWordWrap(False)
        self.legacy_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.legacy_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.pages.addWidget(self.legacy_table)
        footer = QHBoxLayout()
        self.feedback = label('', 'muted')
        self.feedback.setWordWrap(True)
        footer.addWidget(self.feedback, 1)
        self.newest_logs = button('查询任务日志', lambda: self._request_events(None))
        self.newest_logs.setToolTip('按当前通道、级别和关键词，从此任务最新记录开始查找')
        self.logs.search.setPlaceholderText('输入关键词后查询任务日志…')
        self.logs.scope.setToolTip('预筛当前页，点击「查询任务日志」可查找此任务所有页')
        self.older_logs = button('更早日志', lambda: self._request_events(self.events_cursor))
        footer.addWidget(self.newest_logs)
        footer.addWidget(self.older_logs)
        self.latest_legacy = button('最新记录', lambda: self.legacy_requested.emit(None))
        self.older_legacy = button('更早记录', lambda: self.legacy_requested.emit(self.legacy_cursor))
        footer.addWidget(self.latest_legacy)
        footer.addWidget(self.older_legacy)
        self.latest_legacy.hide()
        self.older_legacy.hide()
        self.close_button = button('关闭', self.close)
        footer.addWidget(self.close_button)
        layout.addLayout(footer)
        self.jobs.currentIndexChanged.connect(self._select_job)
        self.source.currentIndexChanged.connect(self._select_source)
        self.logs.search.installEventFilter(self)
        self.logs.search.textChanged.connect(self._update_filter_feedback)
        self.logs.scope.currentIndexChanged.connect(self._update_filter_feedback)
        self.logs.level.currentIndexChanged.connect(self._update_filter_feedback)
        self.set_busy(False)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.KeyPress and watched is self.logs.search
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
            self._request_events(None)
            return True
        return super().eventFilter(watched, event)

    def _select_source(self, index):
        self.source_generation += 1
        self.pages.setCurrentIndex(index)
        legacy = self.source.currentData() == 'legacy'
        self.newest_logs.setVisible(not legacy)
        self.older_logs.setVisible(not legacy)
        self.latest_legacy.setVisible(legacy)
        self.older_legacy.setVisible(legacy)
        self.legacy_table.setRowCount(0)
        with QSignalBlocker(self.jobs):
            self.jobs.clear()
        self.logs.clear_display()
        self.jobs_cursor = self.events_cursor = self.legacy_cursor = None
        self.set_busy(self.busy, reading=True)
        if not self.busy:
            self.load_source()

    def load_source(self):
        if self.source.currentData() == 'legacy':
            self.legacy_requested.emit(None)
        else:
            self.jobs_requested.emit(None)

    def show_legacy(self, page):
        self.legacy_cursor = page.next_cursor
        self.legacy_table.setRowCount(len(page.entries))
        for row, entry in enumerate(page.entries):
            values = (entry.run_id, TASK_NAMES.get(entry.operation, entry.operation), entry.state,
                      entry.revision, entry.started, entry.finished)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.legacy_table.setItem(row, column, item)
        self.legacy_table.scrollToTop()
        self.set_busy(False)
        self.feedback.setText(f'本页 {len(page.entries)} 条' if page.entries else '该项目没有旧工作台运行记录')

    def _job_menu(self, point):
        if self.stop_action.isEnabled() or self.result_files_action.isEnabled() or self.saved_reports_action.isEnabled():
            self.job_menu.popup(self.jobs.mapToGlobal(point))

    def _request_stop(self):
        if not self.stop_action.isEnabled():
            return
        identifier = self.jobs.currentData()
        answer = QMessageBox.question(self, '请求安全停止',
            f'是否请求所选任务 {identifier[:8]} 安全停止？已执行步骤仍按原流程收尾。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.stop_requested.emit(identifier)

    def _request_result_files(self):
        if self.result_files_action.isEnabled():
            self.result_files_requested.emit(self.jobs.currentData())

    def _request_saved_reports(self):
        if self.saved_reports_action.isEnabled():
            self.saved_reports_requested.emit(self.jobs.currentData())

    @staticmethod
    def _job_title(job, state):
        capability = TASK_NAMES.get(job.capability, job.capability)
        return f'{job.created} · {capability} · {JOB_STATES.get(state, "状态未知")} · {job.job_id[:8]}'

    def set_busy(self, busy, *, reading=False):
        self.busy = busy
        self.source.setEnabled((not busy or reading) and self.result_files_dialog is None)
        self.latest_legacy.setEnabled(not busy)
        self.older_legacy.setEnabled(not busy and self.legacy_cursor is not None)
        has_job = bool(self.jobs.currentData())
        self.jobs.setEnabled(not busy and has_job)
        self.newest_jobs.setEnabled(not busy)
        self.older_jobs.setEnabled(not busy and self.jobs_cursor is not None)
        self.newest_logs.setEnabled(not busy and has_job)
        for control in (self.logs.search, self.logs.level, self.logs.scope):
            control.setEnabled(not busy and has_job)
        self.older_logs.setEnabled(not busy and self.events_cursor is not None)
        row = self.jobs.currentData(Qt.ItemDataRole.UserRole + 1)
        job_menu_ready = not busy and self.source.currentData() == 'jobs' and self.source.isEnabled() and row is not None
        can_stop = job_menu_ready and row.state in ('queued', 'running')
        can_view_files = job_menu_ready and row.capability in POWER_HISTORY_CAPABILITIES
        self.stop_action.setEnabled(can_stop)
        self.result_files_action.setEnabled(can_view_files)
        self.saved_reports_action.setEnabled(can_view_files)
        tip = ('\n右键查看任务操作' if can_stop or can_view_files else '')
        self.jobs.setToolTip(row.job_id + tip if row else '')
        if busy:
            self.feedback.setText('正在读取历史…')

    def show_jobs(self, page):
        self.jobs_cursor = page.next_cursor
        with QSignalBlocker(self.jobs):
            self.jobs.clear()
            for job in page.entries:
                self.jobs.addItem(self._job_title(job, job.state), job.job_id)
                self.jobs.setItemData(self.jobs.count() - 1, job, Qt.ItemDataRole.UserRole + 1)
        self._select_job()

    def _select_job(self, *_):
        job_id = self.jobs.currentData() or ''
        self.events_cursor = None
        self.logs.clear_display()
        self.logs.set_scope(self.project_id, self.project_name, job_id, tuple(range(1, 17)) if job_id else ())
        self.set_busy(False)
        if job_id:
            self._request_events(None, HistoryEventFilter())
        else:
            self.feedback.setText('该项目没有可读的业务任务记录')

    def _request_events(self, before, filters=None):
        job_id = self.jobs.currentData()
        if job_id and not self.busy:
            if filters is None:
                filters = self._filters()
            self.events_requested.emit(job_id, before if filters == self.page_filter else None, filters)

    def _filters(self):
        channel = self.logs.scope.currentData()
        level = self.logs.level.currentText() if self.logs.level.currentIndex() > 0 else ''
        return HistoryEventFilter(self.logs.search.text(), level, channel if type(channel) is int else None)

    def _update_filter_feedback(self, *_):
        if self.busy or not self.jobs.currentData():
            return
        changed = self._filters() != self.page_filter
        self.older_logs.setEnabled(not changed and self.events_cursor is not None)
        if changed:
            self.feedback.setText('正在预筛本页。点击「查询任务日志」查找全部记录。')
        elif self.logs.entries:
            self.feedback.setText(f'本页 {len(self.logs.entries)} 条')
        else:
            self.feedback.setText('没有匹配记录' if self.page_filter != HistoryEventFilter() else '此任务暂无日志记录')

    def show_logs(self, page, filters):
        self.events_cursor = page.next_cursor
        self.logs.clear_display()
        self.logs.append_batch(page.entries)
        self.set_busy(False)
        self.page_filter = filters
        self._update_filter_feedback()

    def show_job_state(self, identifier, state):
        index = self.jobs.findData(identifier)
        if index >= 0:
            job = self.jobs.itemData(index, Qt.ItemDataRole.UserRole + 1)
            self.jobs.setItemText(index, self._job_title(job, state))
            self.jobs.setItemData(index, replace(job, state=state), Qt.ItemDataRole.UserRole + 1)

class LogHistoryController:
    def __init__(self, workspace):
        self.workspace = workspace
        self.windows = {}
        self.requests = {}
        self.summary_requests = {}
        self.report_requests = {}
        workspace.window.project_context_updated.connect(self._summary_context_changed)

    def open(self):
        project = self.workspace._current()
        if project is None or not self.workspace.ready or self.workspace.closing:
            return
        dialog = self.windows.get(project.project_id)
        if dialog is not None:
            dialog.showNormal()
            dialog.raise_()
            return
        dialog = LogHistoryDialog(project, self.workspace.window)
        self.windows[project.project_id] = dialog
        dialog.jobs_requested.connect(lambda before: self._submit(dialog, 'history_jobs', before))
        dialog.legacy_requested.connect(lambda before: self._submit(dialog, 'history_legacy_runs', before))
        dialog.events_requested.connect(lambda job, before, filters: self._submit(dialog, 'history_events', before, job, filters))
        dialog.stop_requested.connect(lambda job: self._submit(dialog, 'job_stop_active', job))
        dialog.result_files_requested.connect(lambda job: self._submit(dialog, 'history_result_files', job))
        dialog.saved_reports_requested.connect(lambda job: self._read_saved_reports(dialog, job))
        dialog.jobs.currentIndexChanged.connect(lambda *_: self._summary_context_changed())
        dialog.source.currentIndexChanged.connect(lambda *_: self._summary_context_changed())
        dialog.logs.export_requested.connect(lambda entries, description: self.workspace.export_logs(entries, description, dialog))
        def finished(_):
            if dialog.result_files_dialog is not None:
                self._cancel_summary(dialog.result_files_dialog, '', display=False)
            self.windows.pop(project.project_id, None)
            self._cancel_report_requests(dialog)

        dialog.finished.connect(finished)
        dialog.show()
        self._submit(dialog, 'history_jobs', None)

    def _submit(self, dialog, operation, *arguments):
        if self.workspace.closing or dialog.busy:
            return
        request = self.workspace.submit(operation, dialog.project_id, *arguments)
        if request is not None:
            self.requests[request] = (dialog, dialog.source_generation,
                                      arguments[-1] if operation == 'history_events' else None)
            dialog.set_busy(True, reading=operation in ('history_jobs', 'history_events', 'history_legacy_runs'))
            dialog.logs.set_export_enabled(False)

    def handle_result(self, result):
        if result.operation in ('history_material_report_save', 'history_material_reports'):
            request = self.report_requests.pop(result.identifier, None)
            if request is None:
                return True
            dialog, files, target, generation, stop = request
            if not self._report_matches(dialog, files, target, generation) or stop.is_set():
                return True
            if result.project_id != dialog.project_id:
                return True
            if files is not None:
                payload = result.payload
                matched = isinstance(payload, SavedMaterialReport) and (
                    payload.project_id, payload.job_id, payload.run_id) == (target.project_id, target.job_id, target.run_id)
                files.set_save_pending(False, saved=not result.error and matched)
                files.feedback.setText('报告未保存：' + result.error if result.error else
                                       '已保存历史报告。可从任务菜单查看。' if matched else '报告保存回执范围不符。')
            elif result.error:
                dialog.feedback.setText('保存报告无法读取：' + result.error)
            elif isinstance(result.payload, SavedMaterialReports) and all(
                    (row.project_id, row.job_id, row.run_id) == (dialog.project_id, target, result.payload.run_id)
                    for row in result.payload.reports):
                old = dialog.saved_reports_dialog
                if old is not None:
                    old.close()
                view = SavedMaterialReportsDialog(dialog, target, result.payload)
                dialog.saved_reports_dialog = view
                view.finished.connect(lambda _: setattr(dialog, 'saved_reports_dialog', None))
                view.show()
            else:
                dialog.feedback.setText('保存报告回执范围不符。')
            return True
        if result.operation in ('history_material_summary', 'history_material_batch_summary'):
            request = self.summary_requests.pop(result.identifier, None)
            if request is None:
                return True
            dialog, files, target, generation, stop = request
            batch = isinstance(target, HistoryMaterialBatchTarget)
            if ((stop.is_set() and not batch) or self.workspace.closing or self.windows.get(target.project_id) is not dialog
                    or dialog.result_files_dialog is not files):
                return True
            files.set_summary_pending(False)
            if (not self._summary_matches(dialog, files, target, generation)
                    or result.project_id != target.project_id):
                files.feedback.setText('选定范围已变化，汇总结果作废。')
            elif result.error:
                files.feedback.setText('汇总未完成：' + result.error)
            elif (batch and (result.operation != 'history_material_batch_summary'
                             or not isinstance(result.payload, HistoryMaterialBatchSummary) or not result.payload.matches(target))
                  or not batch and (result.operation != 'history_material_summary'
                                    or not isinstance(result.payload, HistoryMaterialSummary) or result.payload.target != target)):
                files.feedback.setText('汇总回执与选定范围不符，未显示结果。')
            else:
                files.show_summary(result.identifier, result.payload)
            return True
        request = self.requests.pop(result.identifier, None)
        if request is None:
            return False
        dialog, generation, filters = request
        if self.workspace.closing or self.windows.get(result.project_id or dialog.project_id) is not dialog:
            return True
        if generation != dialog.source_generation:
            # The source changed while this read was in flight. Keep one read
            # per dialog and load the most recently selected page when it ends.
            dialog.set_busy(False)
            dialog.load_source()
            return True
        if result.operation == 'open_history_result':
            dialog.set_busy(False)
            files = dialog.result_files_dialog
            if files is not None:
                files.set_busy(False)
                files.feedback.setText(result.error or result.payload)
        elif result.error:
            dialog.set_busy(False)
            dialog.feedback.setText(result.error)
        elif result.operation == 'history_jobs':
            dialog.show_jobs(result.payload)
        elif result.operation == 'history_legacy_runs':
            dialog.show_legacy(result.payload)
        elif result.operation == 'history_result_files':
            self._show_result_files(dialog, result.payload)
        elif result.operation == 'job_stop_active':
            dialog.show_job_state(result.payload['job_id'], result.payload['state'])
            dialog.set_busy(False)
            dialog.feedback.setText(result.payload['notice'])
        else:
            dialog.show_logs(result.payload, filters)
        return True

    def _show_result_files(self, dialog, entries):
        if not entries:
            dialog.set_busy(False)
            dialog.feedback.setText('该批次尚无开关机结果或 WiFi 文件')
            return
        job = dialog.jobs.currentData()
        files = HistoryResultFilesDialog(dialog, job, entries)
        dialog.result_files_dialog = files
        dialog.set_busy(False)

        def open_file(path):
            self._submit(dialog, 'open_history_result', job, path)
            if dialog.busy:
                files.set_busy(True)

        def finished(_):
            self._cancel_summary(files, '', display=False)
            self._cancel_report_requests(dialog, files)
            dialog.result_files_dialog = None
            dialog.set_busy(dialog.busy)

        files.open_requested.connect(open_file)
        files.summary_requested.connect(lambda target: self._start_summary(dialog, files, target))
        files.save_report_requested.connect(lambda original, target: self._save_material_report(dialog, files, original, target))
        files.summary_cancelled.connect(lambda: self._request_summary_cancel(files))
        files.summary_scope_changed.connect(lambda: self._cancel_summary(files, '选定范围已变化，汇总结果作废。'))
        files.finished.connect(finished)
        files.show()

    def _report_matches(self, dialog, files, target, generation):
        if self.workspace.closing or self.windows.get(dialog.project_id) is not dialog:
            return False
        if files is not None:
            return self._summary_matches(dialog, files, target, generation)
        return (self.workspace.window.selected_project == dialog.project_id
                and dialog.source_generation == generation and dialog.jobs.currentData() == target)

    def _save_material_report(self, dialog, files, original, target):
        generation = dialog.source_generation
        if not self._report_matches(dialog, files, target, generation) or files.save_pending:
            return
        stop = Event()
        identifier = self.workspace.submit('history_material_report_save', dialog.project_id, original, target, stop)
        if identifier is not None:
            self.report_requests[identifier] = (dialog, files, target, generation, stop)
            files.set_save_pending(True)
            files.feedback.setText('正在保存已生成的报告…')

    def _read_saved_reports(self, dialog, job):
        generation = dialog.source_generation
        if not self._report_matches(dialog, None, job, generation):
            return
        self._cancel_report_requests(dialog)
        stop = Event()
        identifier = self.workspace.submit('history_material_reports', dialog.project_id, job, stop)
        if identifier is not None:
            self.report_requests[identifier] = (dialog, None, job, generation, stop)
            dialog.feedback.setText('正在读取已保存报告…')

    def _cancel_report_requests(self, dialog, files=None):
        for identifier, (owner, window, _, _, stop) in tuple(self.report_requests.items()):
            if owner is dialog and (files is None or window is files):
                stop.set()
                self.report_requests.pop(identifier, None)

    def _summary_matches(self, dialog, files, target, generation):
        return (self.workspace.window.selected_project == target.project_id
                and dialog.source_generation == generation and dialog.jobs.currentData() == target.job_id
                and dialog.result_files_dialog is files and files.summary_target() == target)

    def _start_summary(self, dialog, files, target):
        generation = dialog.source_generation
        if (self.workspace.closing or dialog.busy or files.summary_pending
                or not self._summary_matches(dialog, files, target, generation)):
            files.feedback.setText('项目、任务或所选通道已变化，未开始汇总。')
            return
        stop = Event()
        batch = isinstance(target, HistoryMaterialBatchTarget)
        operation = 'history_material_batch_summary' if batch else 'history_material_summary'
        identifier = self.workspace.submit(operation, dialog.project_id, target, stop)
        if identifier is None:
            files.feedback.setText('本次汇总未受理。')
            return
        self.summary_requests[identifier] = (dialog, files, target, generation, stop)
        files.set_summary_pending(True)
        scope = f'{len(target.channels)} 个选定通道' if batch else f'CH{target.channel:02d}'
        files.feedback.setText(f'请求 #{identifier} · 正在只读核对 {scope} 留存资料…')

    def _request_summary_cancel(self, files):
        for _, owner, target, _, stop in tuple(self.summary_requests.values()):
            if owner is files and isinstance(target, HistoryMaterialBatchTarget):
                stop.set()
                files.summary_cancel.setEnabled(False)
                files.feedback.setText('已请求取消；等待已完成通道的结果，其余通道将标记未完成。')
                return
        self._cancel_summary(files, '已取消本次只读汇总。')

    def _cancel_summary(self, files, reason, *, display=True):
        for identifier, (_, owner, _, _, stop) in tuple(self.summary_requests.items()):
            if owner is files:
                stop.set()
                del self.summary_requests[identifier]
                if display:
                    files.set_summary_pending(False)
                    files.feedback.setText(reason)

    def _summary_context_changed(self):
        for dialog, files, target, generation, _ in tuple(self.summary_requests.values()):
            if not self._summary_matches(dialog, files, target, generation):
                self._cancel_summary(files, '选定范围已变化，汇总结果作废。')
        for identifier, (dialog, files, target, generation, stop) in tuple(self.report_requests.items()):
            if not self._report_matches(dialog, files, target, generation):
                stop.set()
                self.report_requests.pop(identifier, None)
                if files is not None and dialog.result_files_dialog is files:
                    files.set_save_pending(False)
                    files.feedback.setText('选定范围已变化，本次保存回执不再显示。')
        for dialog in tuple(self.windows.values()):
            view = dialog.saved_reports_dialog
            if view is not None and (self.workspace.window.selected_project != dialog.project_id
                                     or dialog.jobs.currentData() != view.job):
                view.close()
            files = dialog.result_files_dialog
            if files is not None and self.workspace.window.selected_project != dialog.project_id:
                files._generated_report = None
                files.save_report_action.setEnabled(False)

    def set_export_enabled(self, enabled):
        for dialog in self.windows.values():
            dialog.logs.set_export_enabled(enabled and not dialog.busy)

    def prune(self, opened):
        for identifier, dialog in tuple(self.windows.items()):
            if self.workspace.closing or identifier not in opened:
                dialog.close()
