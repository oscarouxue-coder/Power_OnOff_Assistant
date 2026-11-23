"""Project-bound, paginated inspection of continuous monitoring evidence."""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout,
                               QHeaderView, QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout)

from src.models.project_profile import COLLECTOR_LABELS
from .test_type_panel import HEALTH, RECORD
from .theme import button, label


KINDS = {'sample': '自动采样', **RECORD}
STATES = {'running': '监测中', 'stopped': '已停止', 'target_reached': '已到计划时长',
          'interrupted': '中断待核实', 'failed': '监测失败'}


def _time(value):
    return datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M:%S') if value is not None else '—'


class AgingHistoryDialog(QDialog):
    runs_requested = Signal(object)
    page_requested = Signal(object)
    export_requested = Signal()

    def __init__(self, parent, project):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.project_id = project.project_id
        self.setWindowTitle('老化检查记录 · ' + project.name)
        available = self.screen().availableGeometry()
        self.resize(min(1040, int(available.width() * .94)), min(580, int(available.height() * .9)))
        self.runs_cursor = self.page_cursor = None
        self.wanted_job = ''
        self.requests = {}
        body = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(label('批次'))
        self.runs = QComboBox()
        self.runs.setAccessibleName('当前项目的持续老化批次')
        header.addWidget(self.runs, 1)
        self.new_runs = button('最新批次', lambda: self.runs_requested.emit(None))
        self.old_runs = button('更早批次', lambda: self.runs_requested.emit(self.runs_cursor))
        header.addWidget(self.new_runs)
        header.addWidget(self.old_runs)
        body.addLayout(header)
        filters = QHBoxLayout()
        filters.addWidget(label('记录类别'))
        self.kind = QComboBox()
        self.kind.addItem('全部记录', None)
        for key, title in KINDS.items():
            self.kind.addItem(title, key)
        filters.addWidget(self.kind)
        filters.addStretch()
        self.new_page = button('最新记录', self._reset_page)
        self.old_page = button('更早记录', lambda: self.page_requested.emit(self.page_cursor))
        filters.addWidget(self.new_page)
        filters.addWidget(self.old_page)
        body.addLayout(filters)
        self.table = QTableWidget(0, 7)
        self.table.setAccessibleName('持续老化检查证据')
        self.table.setHorizontalHeaderLabels(('时间', 'DUT', '业务', '类别', '结果', '记录人', '证据'))
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        body.addWidget(self.table, 1)
        self.evidence = QPlainTextEdit()
        self.evidence.setAccessibleName('所选记录的完整证据')
        self.evidence.setReadOnly(True)
        self.evidence.setMaximumHeight(self.evidence.fontMetrics().lineSpacing() * 4 + 12)
        self.evidence.hide()
        body.addWidget(self.evidence)
        footer = QHBoxLayout()
        self.feedback = label('', 'muted')
        self.feedback.setWordWrap(True)
        footer.addWidget(self.feedback, 1)
        self.export = button('导出当前批次…', self.export_requested.emit)
        footer.addWidget(self.export)
        footer.addWidget(button('关闭', self.close))
        body.addLayout(footer)
        self.runs.currentIndexChanged.connect(self._reset_page)
        self.kind.currentIndexChanged.connect(self._reset_page)
        self.table.itemSelectionChanged.connect(self._show_evidence)
        self.update_actions()

    def _show_evidence(self):
        entry = self.table.item(self.table.currentRow(), 6)
        self.evidence.setPlainText((entry.data(Qt.ItemDataRole.UserRole) or entry.text()) if entry is not None else '')
        self.evidence.setVisible(entry is not None)

    def update_actions(self):
        batch = bool(self.runs.currentData())
        runs_busy, page_busy = 'runs' in self.requests, 'page' in self.requests
        self.new_runs.setEnabled(not runs_busy)
        self.old_runs.setEnabled(not runs_busy and self.runs_cursor is not None)
        self.new_page.setEnabled(batch and not page_busy)
        self.old_page.setEnabled(batch and not page_busy and self.page_cursor is not None)
        self.export.setEnabled(batch and 'export' not in self.requests)

    def set_runs(self, payload, prefer):
        self.runs_cursor = payload['next_before']
        with QSignalBlocker(self.runs):
            self.runs.clear()
            for row in payload['rows']:
                job = row['job_id']
                caption = f"{_time(row['started'])} · {STATES.get(row['state'], row['state'])} · {job[:12]}"
                self.runs.addItem(caption, job)
                self.runs.setItemData(self.runs.count() - 1, job, Qt.ItemDataRole.ToolTipRole)
            if prefer and self.runs.findData(prefer) < 0 and self.wanted_job == prefer:
                # A previously selected live batch may sit outside the current history page.
                self.runs.addItem(prefer, prefer)
            self.runs.setCurrentIndex(max(0, self.runs.findData(prefer)))
        self.wanted_job = ''
        self._reset_page()

    def _reset_page(self):
        self.table.setRowCount(0)
        self.page_cursor = None
        if self.runs.currentData():
            self.page_requested.emit(None)
        else:
            self.feedback.setText('当前项目暂无老化批次')
        self.update_actions()

    def set_page(self, payload):
        self.page_cursor = payload['next_before']
        self.table.setRowCount(len(payload['rows']))
        for index, row in enumerate(payload['rows']):
            dut = row.get('label') or row['dut_id']
            category = '现场自动采样' if row.get('source') == 'jsonl' else KINDS.get(row['kind'], row['kind'])
            outcome = HEALTH.get(row['outcome'], row['outcome'])
            presence = row['collector'] == 'dut_presence' and row.get('source') == 'jsonl'
            if presence:
                outcome = {'healthy': '在线', 'abnormal': '离线', 'unknown': '未知'}.get(row['outcome'], '未知')
            values = (_time(row['at']), dut, COLLECTOR_LABELS.get(row['collector'], row['collector']),
                      category, outcome,
                      row['operator'] or '—', row['evidence'])
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(row['dut_id'] if col == 1 else str(value))
                if col == 6 and row.get('source') == 'jsonl':
                    detail = f"{value}\n\n事件 ID：{row['event_id']}\n接收时间：{_time(row['received_at'])}"
                    if presence and row.get('boot_id') is not None:
                        detail += f"\n启动标识：{row['boot_id']}"
                    if presence and row.get('uptime_seconds') is not None:
                        detail += f"\n上报开机时长：{row['uptime_seconds']:g} 秒"
                    item.setData(Qt.ItemDataRole.UserRole, detail)
                self.table.setItem(index, col, item)
        self.feedback.setText(f"本页 {len(payload['rows'])} 条记录" if payload['rows'] else '此类别暂无检查记录')
        self.update_actions()


class AgingHistoryController:
    def __init__(self, workspace):
        self.workspace = workspace
        self.windows = {}
        self.pending = {}

    def open(self, identifier, job=''):
        workspace = self.workspace
        project = next((p for p in workspace.window.projects if p.project_id == identifier), None)
        if not project or workspace.closing or not workspace.ready:
            return
        dialog = self.windows.get(identifier)
        if dialog is None:
            dialog = self.windows[identifier] = AgingHistoryDialog(workspace.window, project)
            dialog.runs_requested.connect(lambda cursor: self._runs(dialog, cursor))
            dialog.page_requested.connect(lambda cursor: self._page(dialog, cursor))
            dialog.export_requested.connect(lambda: self._export(dialog))
            dialog.finished.connect(lambda _: self.windows.pop(identifier, None))
        dialog.showNormal()
        dialog.raise_()
        dialog.wanted_job = job
        self._runs(dialog, None)

    def _submit(self, dialog, kind, *args):
        if self.workspace.closing or self.windows.get(dialog.project_id) is not dialog:
            return
        req = self.workspace.submit('aging_history_' + kind, dialog.project_id, *args)
        if req is None:
            dialog.feedback.setText(self.workspace.window.statusBar().currentMessage())
            return
        dialog.requests[kind] = req
        self.pending[req] = (dialog.project_id, dialog, kind, args)
        dialog.update_actions()

    def _runs(self, dialog, cursor):
        self._submit(dialog, 'runs', cursor, 50)

    def _page(self, dialog, cursor):
        self._submit(dialog, 'page', dialog.runs.currentData(), cursor, dialog.kind.currentData(), 100)

    def _export(self, dialog):
        job = dialog.runs.currentData()
        if not job or self.workspace.closing or 'export' in dialog.requests:
            return
        destination, _ = QFileDialog.getSaveFileName(
            dialog, '导出整批老化证据至新文件', 'DUTPilot-老化检查-' + job[:12] + '.csv',
            'CSV 文件 (*.csv)', options=QFileDialog.Option.DontConfirmOverwrite)
        if destination and not self.workspace.closing:
            if not Path(destination).suffix:
                destination += '.csv'
            self._submit(dialog, 'export', job, destination)

    def handle_result(self, result):
        request = self.pending.pop(result.identifier, None)
        if request is None:
            return False
        identifier, dialog, kind, args = request
        if kind == 'export':
            outcome = result.error or f'已导出批次 {args[0]} · {result.payload} 条证据 · {args[1]}'
            self.workspace.window.statusBar().showMessage(outcome, 8000)
        if self.windows.get(identifier) is not dialog or dialog.requests.get(kind) != result.identifier:
            return True
        dialog.requests.pop(kind)
        dialog.update_actions()
        if kind == 'page' and (dialog.runs.currentData(), dialog.kind.currentData()) != (args[0], args[2]):
            return True
        if kind == 'export' and dialog.runs.currentData() != args[0]:
            return True
        if result.error:
            dialog.feedback.setText(result.error)
        elif kind == 'runs':
            prefer = (dialog.wanted_job or dialog.runs.currentData()) if args[0] is None else None
            dialog.set_runs(result.payload, prefer)
        elif kind == 'page':
            dialog.set_page(result.payload)
        else:
            dialog.feedback.setText(outcome)
        return True

    def prune(self, opened):
        for key, dialog in tuple(self.windows.items()):
            if key not in opened or self.workspace.closing:
                dialog.close()
