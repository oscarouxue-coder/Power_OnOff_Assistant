"""Per-DUT observations for the selected project's saved test type."""
from collections import Counter
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from src.ui.qt.progress_widgets import CircularProgress
from src.ui.qt.showcase_components import StatusCard, STATUS_STYLES, semantic_icon
from src.models.project_profile import COLLECTOR_LABELS
from src.models.workbench_presentation import power_cycle_percentage
from src.ui.qt.theme import button, label


HEALTH = {'healthy': '正常', 'abnormal': '异常', 'unknown': '未知', 'unavailable': '未接入'}
SOURCE = {'manual': '人工记录', 'icmp': '绑定网卡 Ping', 'jsonl': '现场采集', 'unavailable': '未接入'}
RECORD = {'observation': '现场观察', 'daily': '每日检查', 'final': '期末检查'}
DUT_STATUS = {'online': ('在线', 'healthy'), 'offline': ('离线', 'error'), 'unknown': ('未知', 'unknown')}


def _clock(value):
    return datetime.fromtimestamp(value).strftime('%m-%d %H:%M:%S') if value is not None else '—'


class TestTypePanel(QWidget):
    record_requested = Signal(str, object)
    history_requested = Signal(str, str)

    def __init__(self, parent=None, *, refreshed=False):
        super().__init__(parent)
        self._refreshed = refreshed
        self._key = None
        self._project = ''
        self._data = {}
        self._dialogs = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QHBoxLayout()
        self.ring = CircularProgress()
        ring_size = 60 if refreshed else 84
        self.ring.setFixedSize(ring_size, ring_size)
        heading.addWidget(self.ring)
        self.title = label('', 'section')
        self.title.setWordWrap(True)
        heading.addWidget(self.title, 1)
        self.record_button = button('记录检查…', self._record)
        heading.addWidget(self.record_button)
        self.history_button = button('检查记录…', self._history)
        heading.addWidget(self.history_button)
        if refreshed:
            band = QFrame()
            band.setProperty('sectionBand', True)
            band.setLayout(heading)
            heading.setContentsMargins(10, 5, 10, 5)
            layout.setSpacing(8)
            layout.addWidget(band)
        else:
            layout.addLayout(heading)
        self.feed_location = QWidget()
        location_row = QFormLayout(self.feed_location)
        location_row.setContentsMargins(0, 0, 0, 0)
        self.feed_path = QLineEdit()
        self.feed_path.setReadOnly(True)
        self.feed_path.setAccessibleName('本批现场采集输入文件')
        location_row.addRow('本批采集文件', self.feed_path)
        self.feed_location.hide()
        layout.addWidget(self.feed_location)
        self.health_cards = QWidget()
        self.health_grid = QGridLayout(self.health_cards)
        self.health_grid.setContentsMargins(0, 0, 0, 0)
        self.cards = {}
        layout.addWidget(self.health_cards)
        self.presence = QTableWidget(0, 8)
        self.presence.setAccessibleName('逐台 DUT 在线与启动状态')
        self.presence.setHorizontalHeaderLabels(('DUT', '设备状态', '最近设备观测', '最近在线心跳',
                                                 '最近启动标识', '上报开机时长', '观测到的周期变化', '最近发现变化'))
        self.presence.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.presence.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.presence.verticalHeader().hide()
        self.presence.hide()
        self._presence_rows = None
        self.presence_title = label('逐台 DUT 在线与启动状态', 'section')
        self.presence_title.hide()
        layout.addWidget(self.presence_title)
        layout.addWidget(self.presence)
        self.table = QTableWidget()
        self.table.setAccessibleName('逐台 DUT 运行数据')
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setMinimumHeight(145)
        self.table.verticalHeader().hide()
        self.table.itemSelectionChanged.connect(self._selection)
        self.observation_title = label('逐台业务检查', 'section')
        self.observation_title.hide()
        layout.addWidget(self.observation_title)
        layout.addWidget(self.table)
        self.inspections = QLabel()
        if refreshed:
            self.inspections.setProperty('role', 'muted')
            for table in (self.presence, self.table):
                table.setAlternatingRowColors(True)
                table.verticalHeader().setDefaultSectionSize(26)
        self.inspections.setWordWrap(True)
        self.inspections.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.inspections)

    def _selected(self):
        item = self.table.item(self.table.currentRow(), 0)
        identity = item.data(Qt.ItemDataRole.UserRole) if item else None
        return tuple(identity) if identity else None

    def _history(self):
        self.history_requested.emit(self._project, self._data.get('job_id', ''))

    def _show_presence(self, rows):
        if self._presence_rows == rows:
            return
        self._presence_rows = rows
        self.presence.setVisible(bool(rows))
        self.presence_title.setVisible(self._refreshed and bool(rows))
        self.presence.setRowCount(len(rows))
        for index, row in enumerate(rows):
            status, badge = DUT_STATUS.get(row['state'], DUT_STATUS['unknown'])
            if not row['subscribed']:
                status, badge = '未接入', 'unavailable'
            seconds = row['last_uptime_seconds']
            uptime = f'{seconds:g} 秒' if seconds is not None else '—'
            changes = row['reboot_count']
            values = (row['label'], status, _clock(row['last_observation']), _clock(row['last_heartbeat']),
                      row['last_boot_id'] or '—', uptime, str(changes) if changes is not None else '—',
                      _clock(row['last_reboot_at']))
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setToolTip(row['dut_id'])
                elif col == 1:
                    style = STATUS_STYLES[badge]
                    item.setIcon(semantic_icon(style.icon, style.color))
                    item.setToolTip(row['detail'] or status)
                elif col in (4, 5):
                    at = row['last_boot_at'] if col == 4 else row['last_uptime_at']
                    item.setToolTip(f'{value} · 采集时间 {_clock(at)}')
                self.presence.setItem(index, col, item)
        if rows:
            self.presence.resizeColumnsToContents()
            height = self.presence.horizontalHeader().sizeHint().height()
            height += self.presence.verticalHeader().defaultSectionSize() * min(len(rows), 5)
            self.presence.setFixedHeight(height + self.presence.horizontalScrollBar().sizeHint().height() + 6)

    def _show_health_cards(self, rows):
        counts = {}
        for row in rows:
            counts.setdefault(row['collector'], Counter())[row['state']] += 1
        for key in self.cards.keys() - counts.keys():
            card = self.cards.pop(key)
            self.health_grid.removeWidget(card)
            card.hide()
            card.deleteLater()
        for key, states in counts.items():
            card = self.cards.get(key)
            if card is None:
                card = self.cards[key] = StatusCard(COLLECTOR_LABELS.get(key, key), '', 'unknown')
            status = next(name for name in ('abnormal', 'unknown', 'unavailable', 'healthy') if states[name])
            card.set_state('error' if status == 'abnormal' else status)
            card.detail.setText(' · '.join(f'{HEALTH[name]} {qty} 台' for name, qty in states.items()))
        self.health_cards.setVisible(bool(counts))
        self._position_health_cards()

    def _position_health_cards(self):
        columns = 4 if self._refreshed and self.health_cards.width() >= 760 else 2
        for index, card in enumerate(self.cards.values()):
            row, column = divmod(index, columns)
            position = self.health_grid.itemAtPosition(row, column)
            if position is None or position.widget() is not card:
                self.health_grid.addWidget(card, row, column)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._refreshed:
            self._position_health_cards()

    def _selection(self):
        chosen = self._selected()
        row = next((r for r in self._data.get('rows', ())
                    if (r['dut_id'], r.get('collector')) == chosen), None)
        self.record_button.setEnabled(bool(row and row.get('source') in ('manual', 'icmp', 'jsonl')))

    def set_project(self, project):
        kind, data = project.project_type, project.test_overview or {}
        key = (project.project_id, kind, data)
        if key == self._key:
            return
        rows = data.get('rows', ())
        same_view = self._key is not None and key[:2] == self._key[:2]
        rows_changed = not same_view or rows != self._data.get('rows', ())
        selected = self._selected() if same_view and rows_changed else None
        self._key, self._project, self._data = key, project.project_id, data
        self.setVisible(bool(kind))
        self._show_presence(data.get('dut_presence', ()) if kind == 'service_aging' else ())
        if not kind:
            return
        power = kind == 'power_cycle'
        self.observation_title.setVisible(self._refreshed and not power)
        self.ring.setVisible(power)
        self.record_button.setVisible(not power)
        self.history_button.setVisible(not power)
        path = data.get('feed_path') if not power else None
        self.feed_location.setVisible(bool(path))
        if self.feed_path.text() != (path or ''):
            self.feed_path.setText(path or '')
            self.feed_path.setCursorPosition(0)
        if power:
            target = data.get('target')
            value = power_cycle_percentage(rows, target)
            self.ring.set_progress(value, 'normal' if value is not None else 'unknown')
            self.title.setText('自动开关机 · 逐台 DUT 轮次记录' if self._refreshed
                               else '自动开关机 · 每台目标 ' + (str(target) if target else '—') + ' 轮')
            headers = ('DUT','通道','阶段','当前轮','完成轮','正常回执','失败轮','重试记录','本轮耗时')
        else:
            run_state = {'running':'监测中','stopped':'已停止','target_reached':'已到计划时长',
                         'interrupted':'中断待核实','failed':'监测失败'}.get(data.get('state'), '尚无运行')
            heading = f'全业务老化 · {run_state}'
            if data.get('target_hours'):
                heading += f" · 目标 {data['target_hours']} 小时"
            if data.get('elapsed_seconds') is not None:
                elapsed = int(data['elapsed_seconds'])
                heading += f' · 监测时长 {elapsed // 3600}时{elapsed // 60 % 60}分'
            self.title.setText(heading)
            headers = ('DUT','业务','状态','来源','有效检查','成功率','最近成功','连续失败','异常时长',
                       '有效观测','最近心跳','恢复次数','最近结果','最近观测','丢包率')
        if rows_changed:
            self._show_health_cards(() if power else rows)
            self._show_rows(rows, headers, power, selected)
        inspections = list(data.get('daily_checks', ())) + list(data.get('final_checks', ()))
        self.inspections.setVisible(bool(inspections))
        if inspections:
            last = max(inspections, key=lambda entry: entry['at'])
            self.inspections.setText(f"{RECORD.get(last['kind'], '')} · {_clock(last['at'])} · {last['operator']} · {last['evidence']}")

    def _show_rows(self, rows, headers, power, selected):
        self.table.setRowCount(0)
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            if power:
                values = [row[field] for field in ('label','channel','stage','cycle','completed','success','failure','retries')]
                values.append(f"{row['duration']:.1f} 秒" if row['duration'] is not None else None)
            else:
                rate = row['success_rate']
                values = (row['label'], COLLECTOR_LABELS.get(row['collector'], row['collector']), HEALTH.get(row['state'], '未知'),
                    SOURCE.get(row['source'], '未接入'), row['checks'], f'{rate:.1%}' if rate is not None else None,
                    _clock(row['last_success']), row['consecutive_failures'], f"{row['abnormal_seconds']:.0f} 秒",
                    f"{row['observed_seconds']:.0f} 秒", _clock(row['last_heartbeat']), row['recoveries'], row['detail'],
                    _clock(row.get('last_observation')), f"{row['packet_loss']:.1%}" if row.get('packet_loss') is not None else None)
            identity = (row['dut_id'], row.get('collector'))
            for col, value in enumerate(values):
                text = str(value) if value is not None and value != '' else '—'
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, identity)
                if not power and col == 2:
                    style = STATUS_STYLES['error' if row['state'] == 'abnormal' else row['state']]
                    item.setIcon(semantic_icon(style.icon, style.color))
                self.table.setItem(index, col, item)
            if selected == identity:
                self.table.selectRow(index)
        self.table.resizeColumnsToContents()
        self._selection()

    def _record(self):
        selected = self._selected()
        if not selected or not self._data.get('job_id'):
            return
        project, job = self._project, self._data['job_id']
        dut_id, collector = selected
        row = next(r for r in self._data['rows'] if (r['dut_id'],r['collector']) == selected)
        dialog = QDialog(self)
        dialog.setWindowTitle('记录业务检查')
        form = QFormLayout(dialog)
        form.addRow('DUT', label(row['label']))
        kind, outcome = QComboBox(), QComboBox()
        for key, name in RECORD.items():
            if key != 'observation' or row['source'] == 'manual':
                kind.addItem(name, key)
        for key in ('healthy','abnormal','unknown'):
            outcome.addItem(HEALTH[key], key)
        outcome.setCurrentIndex(outcome.findData('unknown'))
        evidence = QLineEdit()
        evidence.setMaxLength(1000)
        form.addRow('检查类别', kind)
        form.addRow('结果', outcome)
        form.addRow('观测记录', evidence)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        evidence.textChanged.connect(lambda value: buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(bool(value.strip())))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        dialog.accepted.connect(lambda: self.record_requested.emit(project, dict(job_id=job, dut_id=dut_id,
            collector=collector, outcome=outcome.currentData(), kind=kind.currentData(), evidence=evidence.text().strip())))
        self._dialogs.append(dialog)
        dialog.finished.connect(lambda _: (self._dialogs.remove(dialog), dialog.deleteLater()))
        dialog.open()
