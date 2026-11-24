"""Read-only details for an opened run overview metric."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QPlainTextEdit,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from src.services.power_run_overview import matching_power_overview
from src.ui.qt.theme import label


POWER_METRIC_LABELS = {'success': '成功', 'failure': '失败', 'attention': '当前异常'}


class PowerMetricDetailDialog(QDialog):
    def __init__(self, project, metric, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        title = POWER_METRIC_LABELS[metric]
        self.setWindowTitle(f'{project.name} · {title}详情')
        available = self.screen().availableGeometry()
        self.resize(min(720, int(available.width() * .90)), min(400, int(available.height() * .85)))
        layout = QVBoxLayout(self)
        overview = matching_power_overview(project)
        counts = {'success': project.success_text, 'failure': project.failure_text, 'attention': project.attention_text}
        scope = [project.run_id, f'{title} {counts[metric]}']
        if metric != 'attention' and overview and project.run_id not in (overview['job_id'], overview.get('run_id')):
            scope.append(f"原批次 {overview['job_id']}")
        summary = label(' · '.join(filter(None, scope)), 'muted')
        summary.setTextFormat(Qt.TextFormat.PlainText)
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary.setWordWrap(True)
        layout.addWidget(summary)

        rows = overview.get('rows', ())
        if metric == 'attention':
            columns = ('DUT', '通道', '当前状态', '当前阶段', '原因')
            entries = self._attention_rows(project, rows)
            empty = '当前暂无已记录的异常'
        elif metric == 'failure':
            columns = ('DUT', '通道', '失败轮数', '最近失败轮次', '原因')
            entries = [(row['label'], self._channel(row['channel']), row['failure'], row.get('last_failure'),
                        row.get('failure_reason') or '暂无具体原因') for row in rows if row.get('failure')]
            empty = '本任务暂无可核对的失败通道记录'
        else:
            columns = ('DUT', '通道', '成功轮数', '已完成轮数', '最近上报阶段')
            entries = [(row['label'], self._channel(row['channel']), row['success'], row.get('completed'),
                        row.get('stage')) for row in rows if row.get('success')]
            empty = '本任务暂无可核对的成功通道记录'

        self.has_records = bool(entries)
        self.table = QTableWidget(len(entries), len(columns), self)
        self.table.setAccessibleName(f'{title}详情')
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for index, width in enumerate((120, 62, 100, 110)):
            self.table.setColumnWidth(index, width)
        for index, entry in enumerate(entries):
            for column, value in enumerate(entry):
                item = QTableWidgetItem('—' if value is None or value == '' else str(value))
                self.table.setItem(index, column, item)
        layout.addWidget(self.table, 1)
        self.table.setVisible(self.has_records)
        if self.has_records:
            self.record_text = QPlainTextEdit(readOnly=True)
            self.record_text.setAccessibleName(columns[-1])
            self.record_text.setMaximumHeight(94)
            layout.addWidget(self.record_text)
            self.table.currentCellChanged.connect(self._show_selected_record)
            self.table.setCurrentCell(0, 0)
        else:
            layout.addWidget(label(empty, 'muted'), 1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText('关闭')
        close.rejected.connect(self.close)
        layout.addWidget(close)

    @staticmethod
    def _channel(number):
        return f'CH{number:02d}'

    @classmethod
    def _attention_rows(cls, project, rows):
        if not project.attention_count:
            return []
        by_channel = {row['channel']: row for row in rows}
        entries = []
        for channel in project.channels:
            if channel.state != 'failed':
                continue
            row = by_channel.get(channel.number, {})
            entries.append((row.get('label'), cls._channel(channel.number), '失败', channel.stage,
                            channel.detail or row.get('failure_reason') or '暂无具体原因'))
        if entries:
            return entries

        state = '结果未知' if project.state == 'unknown' else project.state_text
        pretest = project.pretest_run
        reason = project.pipeline_detail or (pretest[3] if pretest[0] == project.run_id else '')
        if not reason or reason in (state, project.state_text):
            reason = '暂无具体原因'
        return [('任务', None, state, project.task_stage, reason)]

    def _show_selected_record(self, row, *_):
        item = self.table.item(row, self.table.columnCount() - 1)
        self.record_text.setPlainText(item.text() if item else '')
