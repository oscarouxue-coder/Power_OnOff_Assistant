"""DUT target selection and configuration through the original services."""
from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QPlainTextEdit, QScrollArea, QSpinBox, QSplitter, QTabBar, QVBoxLayout, QWidget)
from src.models.qt_window_placement import (DUT_STATUS_DEFAULT_ROWS, DUT_STATUS_FEATURES, DUT_STATUS_MAX_ROWS,
                                             DUT_STATUS_MIN_ROWS, dut_status_rows)
from src.ui.qt.theme import BACKGROUND, assert_gui_thread, button, card, label


class DutConfigurationDialog(QDialog):
    command_requested = Signal(str, dict)
    status_heights_changed = Signal(dict)
    login_editability_changed = Signal()

    def __init__(self, snapshot, parent=None):
        super().__init__(parent)
        self.token = snapshot['token']
        self.project_id = snapshot['project_id']
        self.busy = False
        self.active = False
        self.can_execute = True
        self.detaching = False
        self._allow_close = False
        self.targets = {}
        self._binding = None
        self._result_job = ''
        self._suppressed = False
        self._blocked_jobs = set()
        self._snapshots = {}
        self._last_snapshot = None
        self.status_heights = dict(snapshot.get('status_heights', {}))
        self._persist_status_size = False
        self._dragging_status = False
        self._status_layout_timer = QTimer(self)
        self._status_layout_timer.setSingleShot(True)
        self._status_layout_timer.timeout.connect(self._fit_status_height)
        self.setWindowTitle('DUT配置 · ' + snapshot['project_name'])
        self.setStyleSheet('QDialog { background: ' + BACKGROUND + '; }')
        self.resize(1000, 740)
        self.setMinimumSize(530, 430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(label('DUT 配置 · ' + snapshot['project_name'], 'title'))
        tabs = QTabBar()
        tabs.setExpanding(False)
        self.tabs = tabs
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.page_scroll = page
        body = QWidget()
        page.setWidget(body)
        tabs.addTab('Telnet')
        for title in ('WAN', '2.4G WiFi', '5G WiFi', '语音', 'TR069'):
            index = tabs.addTab(title)
            tabs.setTabToolTip(index, '调用原DUT业务服务')
        layout.addWidget(tabs)
        layout.addWidget(page, 1)
        content = QVBoxLayout(body)
        self.form_card = card()
        form = QFormLayout(self.form_card)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.username = QLineEdit(snapshot['username'])
        self.password = QLineEdit(snapshot['password'])
        self.saved_parameter_login = snapshot['saved_parameter_login']
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_password = QCheckBox('显示密码')
        self.show_password.toggled.connect(lambda checked: self.password.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        self.parallel = QSpinBox()
        self.parallel.setRange(1, 8)
        self.parallel.setValue(snapshot.get('parallel_count', 1))
        for title, field in (('UBUS 登录账号', self.username), ('密码', self.password), ('并行数', self.parallel)):
            field.setMaximumWidth(380)
            field.setMinimumWidth(0)
            form.addRow(title, field)
        form.addRow('', self.show_password)
        content.addWidget(self.form_card)
        from src.ui.qt.dut_wan_panel import DutWanPanel
        self.wan = DutWanPanel()
        content.addWidget(self.wan)
        self.wan.hide()
        from src.ui.qt.dut_wifi_panel import DutWifiPanel
        self.wifi_panels={}
        for feature in ('wifi_2g','wifi_5g'):
            panel=DutWifiPanel(feature)
            self.wifi_panels[feature]=panel
            content.addWidget(panel)
            panel.hide()
            panel.dual_changed.connect(lambda checked,name=feature:self._sync_dual(name,checked))
            panel.query_index_changed.connect(lambda name=feature:self._invalidate_feature(name))
        from src.ui.qt.dut_voice_tr069_panel import DutVoiceTr069Panel
        self.voice_tr069_panels = {}
        for feature in ('voice', 'tr069'):
            panel = DutVoiceTr069Panel(feature)
            self.voice_tr069_panels[feature] = panel
            content.addWidget(panel)
            panel.hide()
            if feature == 'voice':
                panel.query_index_changed.connect(lambda: self._invalidate_feature('voice'))
        tools = QHBoxLayout()
        self.select_all = button('全选', lambda: self.select_targets(True), 'link')
        self.clear_all = button('清除选择', lambda: self.select_targets(False), 'link')
        tools.addWidget(label('目标 DUT', 'section'))
        tools.addStretch()
        tools.addWidget(self.select_all)
        tools.addWidget(self.clear_all)
        content.addLayout(tools)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.status_splitter = splitter
        splitter.setChildrenCollapsible(False)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.target_area = QWidget()
        self.target_layout = QVBoxLayout(self.target_area)
        self.target_layout.setContentsMargins(4, 4, 4, 4)
        self.target_layout.addStretch()
        self.scroll.setWidget(self.target_area)
        splitter.addWidget(self.scroll)
        self.status = QPlainTextEdit()
        self.status.setReadOnly(True)
        self.status.setMaximumBlockCount(300)
        self.status.setPlaceholderText('尚未查询当前 Telnet 状态')
        self.status.setAccessibleName('当前 DUT 状态')
        self.status.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        splitter.addWidget(self.status)
        self.status.setMinimumHeight(self._status_pixels(DUT_STATUS_MIN_ROWS))
        self.status.setMaximumHeight(self._status_pixels(DUT_STATUS_MAX_ROWS))
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        self._status_handle = splitter.handle(1)
        self._status_handle.setToolTip('拖动调整本页状态区高度')
        self._status_handle.setAccessibleName('当前状态高度调节条')
        self._status_handle.installEventFilter(self)
        splitter.installEventFilter(self)
        splitter.splitterMoved.connect(self._status_dragged)
        content.addWidget(splitter, 1)
        self.feedback = label('')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        actions = QHBoxLayout()
        self.query_button = button('查询当前状态', lambda: self.preview('query'))
        self.enable_button = button('开启 Telnet', lambda: self.preview('enable'), 'primary')
        self.stop_button = button('停止任务', lambda: self.command('stop'), 'danger')
        self.close_button = button('关闭窗口', self.close)
        tabs.currentChanged.connect(self._switch_feature)
        self.username.textChanged.connect(self._invalidate_status)
        self.password.textChanged.connect(self._invalidate_status)
        for field in (self.query_button, self.enable_button, self.stop_button, self.close_button):
            field.setAutoDefault(False)
            actions.addWidget(field)
        layout.addLayout(actions)
        self.apply_snapshot(snapshot)

    def _status_padding(self):
        return 2 * self.status.frameWidth() + round(2 * self.status.document().documentMargin())

    def _status_pixels(self, rows):
        return rows * self.status.fontMetrics().lineSpacing() + self._status_padding()

    def _fit_status_height(self):
        if not self.isVisible() or self._dragging_status:
            return
        height = sum(self.status_splitter.sizes())
        if height <= 0:
            return
        target_minimum = self.scroll.minimumSizeHint().expandedTo(self.scroll.minimumSize()).height()
        max_pixels = min(height - target_minimum, self.page_scroll.viewport().height())
        max_rows = dut_status_rows((max_pixels - self._status_padding()) // self.status.fontMetrics().lineSpacing())
        feature = self.feature
        requested = self.status_heights.get(feature, DUT_STATUS_DEFAULT_ROWS)
        effective = min(requested, max_rows)
        if effective != requested:
            self.status_heights[feature] = effective
        status_pixels = self._status_pixels(effective)
        with QSignalBlocker(self.status_splitter):
            self.status_splitter.setSizes([height - status_pixels, status_pixels])
        if effective != requested or self._persist_status_size:
            self._persist_status_size = False
            self.status_heights_changed.emit(dict(self.status_heights))

    def _status_dragged(self, _position, _index):
        pixels = self.status_splitter.sizes()[1]
        rows = round((pixels - self._status_padding()) / self.status.fontMetrics().lineSpacing())
        self.status_heights[self.feature] = dut_status_rows(rows)

    def eventFilter(self, watched, event):
        if watched is getattr(self, 'status_splitter', None) and event.type() == QEvent.Type.Resize:
            self._status_layout_timer.start(0)
        elif watched is getattr(self, '_status_handle', None):
            kind = event.type()
            if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._dragging_status = True
            elif self._dragging_status and (kind == QEvent.Type.UngrabMouse or
                    kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton):
                self._dragging_status = False
                self._persist_status_size = True
                self._status_layout_timer.start(0)
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._status_layout_timer.start(0)

    def select_targets(self, checked):
        for view in self.targets.values():
            view['selected'].setChecked(checked)

    @property
    def feature(self):
        index = self.tabs.currentIndex()
        return DUT_STATUS_FEATURES[index] if index >= 0 else DUT_STATUS_FEATURES[0]

    def _switch_feature(self, index):
        self.wan.setVisible(index == 1)
        for panels in (self.wifi_panels, self.voice_tr069_panels):
            for feature, panel in panels.items():
                panel.setVisible(feature == self.feature)
        names = {'telnet': 'Telnet', 'wan': 'WAN', 'wifi_2g': '2.4G WiFi', 'wifi_5g': '5G WiFi',
                 'voice': '语音', 'tr069': 'TR069'}
        feature_name = names[self.feature]
        self.enable_button.setText('开启 Telnet' if self.feature == 'telnet' else f'执行 {feature_name} 配置')
        query_names = {'wan': '查询现有 WAN', 'voice': '查询当前语音', 'tr069': '查询当前TR069'}
        self.query_button.setText(query_names.get(self.feature, '查询当前状态'))
        self.status.setPlaceholderText(f'尚未查询当前 {feature_name} 状态')
        self.page_scroll.verticalScrollBar().setValue(0)
        self._status_layout_timer.start(0)
        for view in self.targets.values(): view['result'].setText('待查询 / 执行')
        if self._last_snapshot is not None: self.apply_snapshot(self._last_snapshot)

    def _sync_dual(self,source,checked):
        for feature,panel in self.wifi_panels.items():
            if feature!=source:panel.set_dual(checked)

    def _invalidate_feature(self,feature):
        snapshot=self._snapshots.get(feature)
        if snapshot and snapshot['job_id']:self._blocked_jobs.add(snapshot['job_id'])
        panels = self.wifi_panels if feature in self.wifi_panels else self.voice_tr069_panels
        panels[feature].invalidate_query()
        if self.feature==feature:
            self.status.clear()
            for view in self.targets.values():view['result'].setText('待查询 / 执行')

    def _invalidate_status(self, *_):
        self._suppressed = True
        self._blocked_jobs.update(s['job_id'] for s in self._snapshots.values() if s['job_id'])
        self.wan.invalidate_query()
        for panels in (self.wifi_panels, self.voice_tr069_panels):
            for panel in panels.values():
                panel.invalidate_query()
        self.status.clear()
        for view in self.targets.values():
            view['result'].setText('待查询 / 执行')

    def preview(self, action):
        self.set_busy(True)
        if self.feature == 'wan': action = 'wan_query' if action == 'query' else 'wan_configure'
        elif self.feature in self.wifi_panels or self.feature in self.voice_tr069_panels:
            action = self.feature + ('_query' if action == 'query' else '_configure')
        arguments = dict(token=self.token, action=action,
            channel_ids=[n for n, view in self.targets.items() if view['selected'].isChecked()],
            username=self.username.text(), password=self.password.text(), parallel_count=self.parallel.value())
        if action == 'wan_configure': arguments.update(settings=self.wan.settings(), query_id=self.wan.query_id)
        elif self.feature in self.wifi_panels:
            panel=self.wifi_panels[self.feature]
            arguments['ssid_index']=panel.text('ssid_index')
            if action.endswith('_configure'):
                arguments.update(settings=panel.settings(),query_id=panel.query_id,
                    increment_ssid=panel.inputs['ssid_increment'].isChecked())
        elif self.feature in self.voice_tr069_panels:
            panel = self.voice_tr069_panels[self.feature]
            if self.feature == 'voice':
                arguments['line_index'] = panel.line_index
            if action.endswith('_configure'):
                arguments.update(settings=panel.settings(), query_id=panel.query_id)
        self.command_requested.emit('preview', arguments)

    def command(self, action):
        self.set_busy(True)
        self.command_requested.emit(action, dict(token=self.token))

    def set_busy(self, busy):
        self.busy = busy
        self._sync_controls()

    def _sync_controls(self):
        allowed = not (self.busy or self.active or self.detaching)
        for widget in (self.form_card, self.select_all, self.clear_all, self.query_button, self.enable_button):
            widget.setEnabled(allowed)
        self.target_area.setEnabled(allowed)
        self.wan.setEnabled(allowed)
        for panels in (self.wifi_panels, self.voice_tr069_panels):
            for panel in panels.values():
                panel.setEnabled(allowed)
        self.query_button.setEnabled(allowed and self.can_execute)
        self.enable_button.setEnabled(allowed and self.can_execute)
        self.stop_button.setEnabled(self.active and not self.busy and not self.detaching)
        self.close_button.setEnabled(not self.busy and not self.detaching)
        self.login_editability_changed.emit()

    def apply_snapshot(self, snapshot):
        assert_gui_thread()
        self._last_snapshot = snapshot
        signature = tuple(tuple(t.items()) for t in snapshot['targets'])
        if signature != self._binding:
            selected = {n for n, v in self.targets.items() if v['selected'].isChecked()}
            old_numbers = set(self.targets)
            first = self._binding is None
            if not first:
                self._invalidate_status()
            for view in self.targets.values():
                self.target_layout.removeWidget(view['card'])
                view['card'].deleteLater()
            self.targets.clear()
            for target in snapshot['targets']:
                row = card()
                row.setMinimumWidth(0)
                box = QVBoxLayout(row)
                box.setContentsMargins(10, 7, 10, 7)
                check = QCheckBox(f"CH{target['number']:02d} · {target['vlan']}")
                check.setChecked(first or target['number'] not in old_numbers or target['number'] in selected)
                check.setToolTip(target['adapter'])
                check.toggled.connect(self._invalidate_status)
                text = label(f"网卡：{target['adapter']}\n{target['source']} → {target['host']}", 'muted')
                text.setWordWrap(True)
                result = label('待执行', 'muted')
                result.setWordWrap(True)
                box.addWidget(check)
                box.addWidget(text)
                box.addWidget(result)
                self.target_layout.insertWidget(self.target_layout.count() - 1, row)
                self.targets[target['number']] = dict(card=row, selected=check, result=result)
            self._binding = signature
        self.active = snapshot['active']
        self.can_execute = snapshot['can_execute']
        snapshot_feature = snapshot.get('feature', 'telnet')
        self._snapshots[snapshot_feature] = snapshot
        self._blocked_jobs.intersection_update(s['job_id'] for s in self._snapshots.values())
        display = self._snapshots.get(self.feature)
        display_job = display['job_id'] if display else ''
        self._suppressed = display_job in self._blocked_jobs
        if snapshot_feature == 'wan' and snapshot.get('wan_query') and not self._suppressed:
            if snapshot['wan_query']['channel_ids'] == [n for n, v in self.targets.items() if v['selected'].isChecked()]:
                self.wan.set_connections(snapshot['wan_query'])
        elif snapshot_feature == 'wan' and not snapshot.get('wan_query'):
            self.wan.invalidate_query()
        for feature,panel in self.wifi_panels.items():
            query=snapshot.get('wifi_queries',{}).get(feature)
            if query and (self._snapshots.get(feature,{}).get('job_id') not in self._blocked_jobs):
                if query['channel_ids']==[n for n,v in self.targets.items() if v['selected'].isChecked()] and query['ssid_index']==panel.text('ssid_index'):
                    panel.set_query(query)
            elif snapshot_feature==feature and not query:
                panel.invalidate_query()
        selected = [n for n, view in self.targets.items() if view['selected'].isChecked()]
        for feature, panel in self.voice_tr069_panels.items():
            query = snapshot.get('voice_tr069_queries', {}).get(feature)
            if query and self._snapshots.get(feature, {}).get('job_id') not in self._blocked_jobs:
                if query['channel_ids'] == selected and query['line_index'] == panel.line_index:
                    panel.set_query(query)
            elif snapshot_feature == feature and not query:
                panel.invalidate_query()
        states = {'idle': '尚未执行', 'queued': '等待执行', 'running': '执行中', 'stop_requested': '停止中',
            'succeeded': '已完成', 'failed': '失败', 'unknown': '结果未知，需人工核实', 'stopped': '已停止'}
        self.feedback.setText(states.get(snapshot['state'], snapshot['state']) +
            (' · 任务 ' + snapshot['job_id'][:8] if snapshot['job_id'] else '') +
            (' · ' + snapshot['error'] if snapshot['error'] else ''))
        details = []
        for row in (() if self._suppressed or display is None else display['rows']):
            stage = {'queued': '等待执行', 'completed': '已完成', 'stopped': '已停止',
                'network': '网络准备', 'exception': '执行异常', 'preflight': '预检失败',
                'query': '查询失败', 'ubus': 'UBUS', 'probe': '端口验证'}.get(row['stage'], row['stage'])
            text = stage + ' · ' + row['message']
            target = next((t for t in snapshot['targets'] if t['number'] == row['number']), None)
            same = target and (row.get('source'), row.get('host'), row.get('vlan', '').lower()) == (
                target['source'], target['host'], target['vlan'].lower())
            if row['number'] in self.targets and (same or row['stage'] == 'queued'):
                self.targets[row['number']]['result'].setText(text)
            detail = f"CH{row['number']:02d} · {text}"
            if row.get('source'):
                detail += f"\n任务目标：{row['vlan']} · {row['source']} → {row['host']}"
            settings = row.get('settings')
            if settings and 'access_control_enabled' in settings:
                detail += '\n' + ' · '.join((
                    'AccessCtrl=' + ('启用' if settings['access_control_enabled'] else '关闭'),
                    'Telnet规则=' + ('启用' if settings['rule_present'] and settings['rule_enabled'] else '未启用'),
                    'TCP 23=' + ('可达' if settings['tcp_port_open'] else '不可达'),
                    '源接口=' + ', '.join(settings['source_interfaces'])))
            elif settings and 'band' in settings:
                detail += (f"\n{settings['band']} WiFi · SSID {settings['ssid_index']} · {settings['ssid']} · "
                    f"{settings['channel']}/{settings['channel_bandwidth']}/{settings['operating_mode']} · 功率 {settings['transmit_power']}%")
                if settings.get('peer_radio'):
                    peer=settings['peer_radio']
                    detail += f"\n{peer['band']} Radio · {peer['channel']}/{peer['channel_bandwidth']}/{peer['operating_mode']} · 功率 {peer['transmit_power']}%"
            elif settings and 'line_index' in settings:
                detail += (f"\n语音线路 {settings['line_index']} · {settings['sip_mode']} · {settings['dtmf_method']}"
                           f" · 编码 {', '.join(settings['codecs'])}")
            elif settings and 'acs_url' in settings:
                supported = settings['supported_fields']
                periodic = '未报告'
                if 'periodic_inform_enabled' in supported:
                    periodic = '启用' if settings['periodic_inform_enabled'] else '停用'
                interval = settings['periodic_inform_interval']
                detail += (f"\nACS：{settings['acs_url'] or '未报告'} · 周期 Inform：{periodic}"
                           + (f' · 间隔 {interval} 秒' if interval else ' · 间隔未报告'))
            for connection in row.get('connections', ()):
                detail += (f"\n{connection['name']} · VLAN {connection['vlan_id']} · {connection['mode']} · "
                    f"{connection['service_type']} · {connection['access_type']}")
            details.append(detail)
        text = '\n\n'.join(details)
        if self.status.toPlainText() != text:
            self.status.setPlainText(text)
        self._sync_controls()

    def reject(self):
        if self._allow_close:
            super().reject()
        else:
            self.close()

    def closeEvent(self, event):
        if self._allow_close:
            super().closeEvent(event)
        elif not self.busy and not self.detaching:
            self.detaching = True
            self.set_busy(True)
            self.command_requested.emit('detach', dict(token=self.token, username=self.username.text(),
                password=self.password.text(), parallel_count=self.parallel.value()))
            event.ignore()
        else:
            event.ignore()
