"""Preparation receipts for one project's DUTs. Commands stay in the workspace."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLineEdit,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .theme import button, label


STATE_LABELS = {
    'pending': '待执行', 'running': '执行中', 'executed': '已执行，待验证',
    'verified': '已验证', 'skipped': '已跳过', 'failed': '失败', 'stopped': '已停止',
    'stale': '证据已过期', 'interrupted': '执行中断',
}


class ProjectPreparationPage(QWidget):
    record_requested = Signal(dict)
    module_requested = Signal(str)
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.snapshot = {}
        self.steps = ()
        self.has_identity = False
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(label('DUT'))
        self.dut = QComboBox()
        self.dut.setAccessibleName('准备目标 DUT')
        row.addWidget(self.dut, 1)
        row.addWidget(button('刷新记录', self.refresh_requested.emit))
        layout.addLayout(row)
        self.summary = label('')
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(('准备步骤', '方式', '状态'))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.setAccessibleName('逐 DUT 准备记录')
        layout.addWidget(self.table, 1)
        self.detail = label('', 'muted')
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.detail)
        self.evidence = QLineEdit()
        self.evidence.setPlaceholderText('填写检查依据、记录位置或跳过原因')
        layout.addWidget(self.evidence)
        row = QHBoxLayout()
        self.operation = QComboBox()
        self.operation.setAccessibleName('准备操作')
        row.addWidget(self.operation, 1)
        self.apply = button('提交记录', self._submit)
        row.addWidget(self.apply)
        self.module = button('打开业务模块', self._open_module)
        row.addWidget(self.module)
        layout.addLayout(row)
        self.dut.currentIndexChanged.connect(self._render_steps)
        self.table.itemSelectionChanged.connect(self._render_step)
        self.operation.currentIndexChanged.connect(self._prompt)

    def show_snapshot(self, snapshot):
        self.snapshot = snapshot
        previous = self.dut.currentData()
        self.dut.blockSignals(True)
        self.dut.clear()
        for dut in snapshot.get('duts', ()):
            self.dut.addItem(dut['label'], dut['dut_id'])
        self.dut.setCurrentIndex(max(0, self.dut.findData(previous)))
        self.dut.blockSignals(False)
        totals = [f"已验证 {snapshot['verified']} / {snapshot['total']}"]
        if snapshot.get('skipped'):
            totals.append(f"已跳过 {snapshot['skipped']}")
        if snapshot.get('dirty'):
            totals.append('项目有未保存更改')
        elif snapshot.get('ready'):
            totals.append('准备检查已完成')
        self.summary.setText(' · '.join(totals))
        self._render_steps()

    def _step(self):
        index = self.table.currentRow()
        return self.steps[index] if 0 <= index < len(self.steps) else None

    def _render_steps(self):
        previous = self._step()
        dut = next((item for item in self.snapshot.get('duts', ()) if item['dut_id'] == self.dut.currentData()), {})
        self.has_identity = bool(dut.get('identity_confirmed'))
        self.steps = dut.get('steps', ())
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.steps))
        selected = 0
        for index, step in enumerate(self.steps):
            if previous and previous['id'] == step['id']:
                selected = index
            values = (step['label'], '人工' if step['mode'] == 'manual' else '业务模块',
                      STATE_LABELS.get(step['state'], step['state']))
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(value))
        if self.steps:
            self.table.setCurrentCell(selected, 0)
        self.table.blockSignals(False)
        self._render_step()

    def _render_step(self):
        self.evidence.clear()
        self.operation.clear()
        step = self._step()
        self.module.setVisible(bool(step and step['mode'] == 'automatic'))
        editable = self.has_identity and not self.snapshot.get('dirty', False)
        self.module.setEnabled(bool(step and editable and not step['blocked_by'] and step['state'] != 'interrupted'))
        if step:
            self.module.setText('打开业务模块' if step['state'] == 'running' else '开始并打开业务模块')
            waiting = [row['label'] for row in self.steps if row['id'] in step['blocked_by']]
            source = {'manual': '人工执行 / 现场核对', 'job': '业务任务回执'}.get(step.get('source'), '')
            self.detail.setText(' · '.join(str(item) for item in (
                '请在项目设置中填写 DUT 实物标识并保存' if not self.has_identity else '',
                '等待 ' + '、'.join(waiting) if waiting else '', source, step.get('evidence'),
                step.get('verification')) if item))
            if editable:
                if step['state'] == 'interrupted':
                    self.operation.addItem('已核实原执行停止', 'stopped')
                    self.operation.addItem('已核实原执行失败', 'failed')
                elif not waiting and step['mode'] == 'manual':
                    if step['state'] != 'running':
                        self.operation.addItem('开始执行' if step['state'] == 'pending' else '重新执行', 'begin')
                    else:
                        for title, action in (('执行完成', 'executed'), ('执行失败', 'failed'), ('已停止', 'stopped')):
                            self.operation.addItem(title, action)
                elif not waiting:
                    if step['state'] == 'running':
                        self.operation.addItem('关联已完成任务回执', 'job')
                        self.operation.addItem('记录执行中止', 'stopped')
                    else:
                        self.operation.addItem('记录人工执行 / 现场已有状态', 'manual')
                if not waiting and step['state'] == 'executed':
                    self.operation.insertItem(0, '验证通过', 'pass')
                    self.operation.insertItem(1, '验证失败', 'fail')
                    self.operation.setCurrentIndex(0)
                if step.get('optional') and step['state'] not in ('verified', 'skipped', 'running', 'interrupted'):
                    self.operation.addItem('记录跳过', 'skip')
        else:
            self.detail.setText('尚未配置 DUT')
        self.apply.setEnabled(bool(self.operation.count()))
        self.evidence.setEnabled(bool(self.operation.count()))
        self._prompt()

    def _prompt(self):
        action = self.operation.currentData()
        self.evidence.setVisible(bool(action and action != 'begin'))
        self.evidence.setPlaceholderText('填写原任务 Job ID' if action == 'job' else '填写检查依据、记录位置或跳过原因')

    def _open_module(self):
        step = self._step()
        if step:
            self.module_requested.emit(step['id'])

    def _submit(self):
        step, action = self._step(), self.operation.currentData()
        if not step or not action:
            return
        params = dict(dut_id=self.dut.currentData(), step_id=step['id'], token=step['token'])
        evidence = self.evidence.text().strip()
        if action == 'job':
            params.update(action='job', job_id=evidence)
        elif action == 'manual':
            params.update(action='manual', evidence=evidence)
        elif action in ('pass', 'fail'):
            params.update(action='verify', passed=action == 'pass', evidence=evidence, attempt=step['attempt'])
        elif action in ('executed', 'failed', 'stopped'):
            params.update(action='finish', outcome=action, evidence=evidence, attempt=step['attempt'])
        elif action == 'skip':
            params.update(action='skip', reason=evidence)
        else:
            params.update(action='begin')
        self.record_requested.emit(params)
