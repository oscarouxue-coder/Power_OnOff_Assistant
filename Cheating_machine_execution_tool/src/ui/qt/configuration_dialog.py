"""Six-tab local editor. Widgets collect data; services validate and write it."""
from copy import deepcopy
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout,
    QLineEdit, QMenu, QMessageBox, QScrollArea, QSizePolicy, QTabWidget, QVBoxLayout, QWidget)
from line_check_assistant.test_item_config_store import WIFI_AUTH_MODE_OPTIONS, WIFI_CIPHER_OPTIONS
from src.ui.qt.blocker_review import ReviewFeedback, focus_widget
from src.ui.qt.theme import BACKGROUND, DANGER, assert_gui_thread, button, card, label


HIDDEN_RUNTIME = frozenset(('telnet_enable', 'communication_method', 'baud_rate', 'selected_profile'))
RUNTIME_LABELS = {'startup_time': '设备启动等待（秒）', 'interval_time': '每轮断电等待（秒）',
    'number_of_tests': '测试循环次数', 'wait_command_done': '命令完成后等待（秒）'}
VERSION_FIELDS = (('software_version', '软件版本'), ('internal_software_version', '内部软件版本'),
    ('onu_compile_time', 'ONU 软件编译时间'))


class ConfigurationDialog(QDialog):
    save_requested = Signal(object)
    reload_requested = Signal(object)
    checkpoint_requested = Signal(object)
    defaults_requested = Signal(object)
    wifi_interfaces_requested = Signal(object)
    pretest_requested = Signal(object)
    pretest_stop_requested = Signal(object)
    version_requested = Signal(object)
    push_trial_requested = Signal(object)

    def __init__(self, draft, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(draft.project_name + ' · 测试项配置')
        self.setMinimumSize(520, 360)
        self.setStyleSheet(f'QDialog {{ background: {BACKGROUND}; }}')
        self.busy = False
        self.dirty = False
        self.discard_revision = ''
        self._loading = False
        self._checkpoint_timer = QTimer(self)
        self._checkpoint_timer.setSingleShot(True)
        self._checkpoint_timer.setInterval(500)
        self._checkpoint_timer.timeout.connect(self._checkpoint)
        self._pretest_view = ('', '', False, '')
        self._version_view = None
        self._version_readback = None
        self._version_options = None
        self._push_trial_view = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(12)
        outer.addWidget(label(draft.project_name + ' · 测试项配置', 'title'))
        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        outer.addWidget(self.tabs, 1)
        self.feedback = ReviewFeedback(role='muted')
        self.feedback.setWordWrap(True)
        outer.addWidget(self.feedback)
        actions = QHBoxLayout()
        self.reload_button = button('重新加载', self.request_reload)
        actions.addWidget(self.reload_button)
        actions.addStretch()
        self.pretest_stop_button = button('停止预备测试', self.request_pretest_stop, 'danger')
        self.pretest_stop_button.setVisible(False)
        actions.addWidget(self.pretest_stop_button)
        self.close_button = button('关闭', self.close)
        self.save_button = button('保存', self.request_save, 'primary')
        actions.addWidget(self.close_button)
        actions.addWidget(self.save_button)
        outer.addLayout(actions)
        self.set_draft(draft)
        available = self.screen().availableGeometry()
        self.resize(min(980, int(available.width() * .88)), min(740, int(available.height() * .88)))

    def _changed(self, *_args):
        if not self._loading:
            self.dirty = True
            warning = self.draft.recovery_warning
            self.feedback.setText(('有未保存的修改。' + warning) if warning else '有未保存的修改')
            if not warning:
                self._checkpoint_timer.start()

    def _page(self, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setObjectName('ConfigurationViewport')
        content = QWidget()
        content.setObjectName('ConfigurationPage')
        content.setMinimumWidth(0)
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        scroll.setWidget(content)
        self.tabs.addTab(scroll, title)
        return layout

    def _form(self, layout, title):
        group = card()
        section = QVBoxLayout(group)
        section.setContentsMargins(16, 12, 16, 14)
        section.addWidget(label(title, 'section'))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(20)
        form.setVerticalSpacing(10)
        section.addLayout(form)
        layout.addWidget(group)
        return form

    def _line(self, form, domain, key, title, value, *, secret=False):
        field = QLineEdit(str(value))
        field.setMaximumWidth(140 if (domain == 'telnet' and key in ('port', 'timeout')) or
            (domain == 'runtime' and key in RUNTIME_LABELS) else 460)
        field.textChanged.connect(self._changed)
        self.fields[domain][key] = field
        if secret:
            field.setEchoMode(QLineEdit.EchoMode.Password)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(field, 1)
            visible = QCheckBox('显示')
            visible.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            visible.toggled.connect(lambda checked: field.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
            row_layout.addWidget(visible)
            row_layout.addStretch()
            form.addRow(label(title), row)
        else:
            form.addRow(label(title), field)
        return field

    def _check(self, form, domain, key, title, value):
        field = QCheckBox(title)
        field.setChecked(bool(value))
        field.toggled.connect(self._changed)
        self.fields[domain][key] = field
        form.addRow(field)
        return field

    def _choice(self, form, domain, key, title, value, choices):
        field = QComboBox()
        field.setMaximumWidth(460)
        for text, data in choices:
            field.addItem(text, data)
        index = field.findData(value)
        if index < 0:
            field.addItem(str(value), value)
            index = field.count() - 1
        field.setCurrentIndex(index)
        field.currentIndexChanged.connect(self._changed)
        self.fields[domain][key] = field
        form.addRow(label(title), field)
        return field

    def _telnet(self, values):
        layout = self._page('Telnet')
        form = self._form(layout, 'Telnet 连接与登录')
        self._check(form, 'telnet', 'telnet_default_on', '设备默认已开启 Telnet', values['telnet_default_on'])
        for key, title in (('request_url', '请求地址'), ('port', '连接端口'), ('user', '用户名'),
            ('password', '密码'), ('timeout', '连接超时（秒）'), ('input_user_flag', '用户名提示符'),
            ('input_password_flag', '密码提示符'), ('login_success_flag', '登录成功提示符'), ('login_after_input_str', '登录后命令')):
            self._line(form, 'telnet', key, title, values[key], secret=key == 'password')
        for key, title in (('telnet_no_user_password_flag', '免用户名密码登录'), ('only_power_off_on', '仅执行上下电')):
            field = self._choice(form, 'telnet', key, title, values[key], (('否', 0), ('是', 1)))
            field.currentIndexChanged.connect(self._credentials_state)
        self._credentials_state()
        layout.addStretch()

    def _credentials_state(self, *_args):
        fields = self.fields['telnet']
        if not all(key in fields for key in ('telnet_no_user_password_flag', 'only_power_off_on')):
            return
        enabled = not any(fields[key].currentData() for key in ('telnet_no_user_password_flag', 'only_power_off_on'))
        for key in ('user', 'password'):
            fields[key].setEnabled(enabled)

    def _order(self, values, *, recovering=False):
        layout = self._page('测试项')
        top = QHBoxLayout()
        self.interval = QLineEdit(str(values['command_fail_retry_interval_time']))
        self.interval.setMaximumWidth(90)
        self.interval.textChanged.connect(self._changed)
        top.addWidget(label('全局重试间隔（秒）'))
        top.addWidget(self.interval)
        top.addStretch()
        top.addWidget(button('添加命令', lambda: self.add_command()))
        top.addWidget(button('恢复默认', self.request_defaults))
        layout.addLayout(top)
        self.command_host = QWidget()
        self.command_layout = QVBoxLayout(self.command_host)
        self.command_layout.setContentsMargins(0, 0, 0, 0)
        self.command_layout.setSpacing(12)
        layout.addWidget(self.command_host)
        items = values['items']
        if not items and not recovering:
            items = [{'command': '', 'retry_times': 5, 'expected_segments': []}]
        for item in items:
            self.add_command(item)
        self.pretest_button = button('执行预备测试…', self.request_pretest)
        layout.addWidget(self.pretest_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()

    def add_command(self, item=None):
        assert_gui_thread()
        item = item or {'command': '', 'retry_times': 5, 'expected_segments': []}
        group = card()
        content = QVBoxLayout(group)
        content.setContentsMargins(12, 10, 12, 10)
        top = QHBoxLayout()
        number = label(str(len(self.commands) + 1))
        command = QLineEdit(item['command'])
        command.setPlaceholderText('测试命令')
        command.textChanged.connect(self._changed)
        retry = QLineEdit(str(item['retry_times']))
        retry.setMaximumWidth(60)
        retry.textChanged.connect(self._changed)
        top.addWidget(number)
        top.addWidget(command, 1)
        top.addWidget(label('重试'))
        top.addWidget(retry)
        row = dict(widget=group, number=number, command=command, retry=retry, segments=[], layout=content)
        menu = QMenu(group)
        menu.addAction('添加期望段', lambda: self.add_segment(row))
        menu.addAction('删除命令', lambda: self.remove_command(row))
        more = button('⋯')
        more.setToolTip('添加期望段 / 删除命令')
        more.setMenu(menu)
        top.addWidget(more)
        content.addLayout(top)
        self.command_layout.addWidget(group)
        self.commands.append(row)
        for segment in item['expected_segments']:
            self.add_segment(row, segment)
        self._changed()
        return row

    def add_segment(self, row, value=None):
        value = value or {'text': '', 'negate': False}
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        negate = QCheckBox('否定')
        negate.setChecked(value['negate'])
        negate.toggled.connect(self._changed)
        text = QLineEdit(value['text'])
        text.setPlaceholderText('期望匹配内容（多个段按 AND 匹配）')
        text.textChanged.connect(self._changed)
        segment = dict(widget=widget, text=text, negate=negate)
        layout.addWidget(negate)
        layout.addWidget(text, 1)
        remove = button('×', lambda: self.remove_segment(row, segment))
        remove.setToolTip('删除此期望段')
        layout.addWidget(remove)
        row['layout'].addWidget(widget)
        row['segments'].append(segment)
        self._changed()

    def remove_segment(self, row, segment):
        row['segments'].remove(segment)
        row['layout'].removeWidget(segment['widget'])
        segment['widget'].deleteLater()
        self._changed()

    def remove_command(self, row):
        self.commands.remove(row)
        self.command_layout.removeWidget(row['widget'])
        row['widget'].deleteLater()
        for index, entry in enumerate(self.commands, 1):
            entry['number'].setText(str(index))
        self._changed()

    def _wifi(self, values):
        layout = self._page('WiFi')
        form = self._form(layout, 'WiFi 连接测试')
        for key, title in (('enable', '连接 WiFi（主控）'), ('test_2g_enable', '测试 2.4G WiFi'),
            ('test_5g_enable', '测试 5G WiFi'), ('choose_wireless_card', '指定无线网卡'), ('wireless_ping_enable', '启用无线 Ping')):
            self._check(form, 'connect_wifi', key, title, values[key])
        for key, title, choices in (
            ('product_solution', 'ONU 方案', tuple((v, v) for v in ('openwrt', 'bcm', 'mtk'))),
            ('connection_test_mode', '连接测试模式', (('分别验证频段', 'per_band'), ('双频合一', 'unified'))),
            ('security_source', '认证参数来源', (('自动识别', 'auto'), ('高级手动', 'manual'))),
            ('auth_mode', '认证方式', tuple((v, v) for v in WIFI_AUTH_MODE_OPTIONS)),
            ('cipher', '加密算法', tuple((v, v) for v in WIFI_CIPHER_OPTIONS)),
        ):
            self._choice(form, 'connect_wifi', key, title, values[key], choices)
        self._choice(form, 'connect_wifi', 'wireless_card_name', '无线网卡名称', values['wireless_card_name'],
            ((values['wireless_card_name'], values['wireless_card_name']),))
        self._line(form, 'connect_wifi', 'wireless_ping_target', '无线 Ping 目标', values['wireless_ping_target'])
        fields = self.fields['connect_wifi']
        def update(*_args):
            for key in ('test_2g_enable', 'test_5g_enable'):
                fields[key].setEnabled(fields['connection_test_mode'].currentData() != 'unified')
            for key in ('auth_mode', 'cipher'):
                visible = fields['security_source'].currentData() == 'manual'
                form.labelForField(fields[key]).setVisible(visible)
                fields[key].setVisible(visible)
            fields['wireless_ping_target'].setEnabled(fields['wireless_ping_enable'].isChecked())
        fields['connection_test_mode'].currentIndexChanged.connect(update)
        fields['security_source'].currentIndexChanged.connect(update)
        fields['wireless_ping_enable'].toggled.connect(update)
        update()
        layout.addWidget(button('刷新无线网卡', self.request_wifi_interfaces), 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()

    def _project_info(self, values):
        layout = self._page('项目信息')
        form = self._form(layout, '项目与版本基准')
        for key, title in (('project_name', '项目名称'), *VERSION_FIELDS):
            self._line(form, 'project_info', key, title, values[key])
        readback = self._form(layout, '当前样机查询结果（只读）')
        self.version_channel = QComboBox()
        self.version_channel.setMaximumWidth(240)
        self.version_channel.addItem('选择项目通道', None)
        self._version_options = None
        query_row = QWidget()
        query_layout = QHBoxLayout(query_row)
        query_layout.setContentsMargins(0, 0, 0, 0)
        self.version_button = button('查询当前样机版本', self.request_version_query)
        self.version_button.setEnabled(False)
        self.version_channel.currentIndexChanged.connect(
            lambda: self.version_button.setEnabled(self.version_channel.currentData() is not None))
        query_layout.addWidget(self.version_channel)
        query_layout.addWidget(self.version_button)
        query_layout.addStretch()
        readback.addRow(label('查询通道'), query_row)
        self.version_fields = []
        for _, title in VERSION_FIELDS:
            field = QLineEdit()
            field.setReadOnly(True)
            field.setMaximumWidth(460)
            self.version_fields.append(field)
            readback.addRow(label(title), field)
        self.version_target = label('', 'muted')
        self.version_target.setVisible(False)
        readback.addRow(self.version_target)
        self._render_version_readback()
        layout.addStretch()

    def set_version_channels(self, channels):
        options = tuple((channel.number, channel.vlan) for channel in channels if channel.state != 'disabled')
        if options == self._version_options:
            return
        self._version_options = options
        number = self.version_channel.currentData()
        self.version_channel.clear()
        self.version_channel.addItem('选择项目通道' if options else '没有已启用通道', None)
        for channel, vlan in options:
            self.version_channel.addItem(f'CH{channel:02d}' + (f' · {vlan}' if vlan else ''), channel)
        index = self.version_channel.findData(number)
        self.version_channel.setCurrentIndex(1 if len(options) == 1 else max(0, index))

    def _render_version_readback(self):
        view = self._version_readback
        if view is None:
            return
        self.version_target.setText(f'查询结果来自 CH{view.channel:02d}')
        self.version_target.setVisible(True)
        for field, value in zip(self.version_fields, view.values):
            field.setText(value)
            field.setCursorPosition(0)
            field.setToolTip(value)

    def _runtime(self, values):
        layout = self._page('开关机运行参数')
        form = self._form(layout, '开关机运行参数')
        for key in dict.fromkeys((*RUNTIME_LABELS, *(k for k in values if k.lower() not in HIDDEN_RUNTIME))):
            self._line(form, 'runtime', key, RUNTIME_LABELS.get(key, key), values.get(key, ''))
        layout.addStretch()

    def _push(self, values):
        layout = self._page('消息推送')
        form = self._form(layout, '消息推送配置')
        for key, title in (('dingtalk_flag', '启用消息推送'), ('at_all', '@所有人')):
            self._check(form, 'push', key, title, values[key] == '1')
        self._line(form, 'push', 'webhook', 'Webhook 地址', values['webhook'], secret=True)
        self._line(form, 'push', 'secret', '加签密钥', values['secret'], secret=True)
        self.push_trial_button = button('发送测试消息', self.request_push_trial)
        layout.addWidget(self.push_trial_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()

    def set_draft(self, draft, *, restore=False):
        assert_gui_thread()
        selected = max(0, self.tabs.currentIndex())
        self._loading = True
        self._checkpoint_timer.stop()
        self.draft = draft
        values = draft.recovered_values if restore else draft.values
        self.fields = {name: {} for name in draft.values}
        self.commands = []
        while self.tabs.count():
            page = self.tabs.widget(0)
            self.tabs.removeTab(0)
            page.deleteLater()
        self._telnet(values['telnet'])
        self._order(values['order'], recovering=restore)
        self._wifi(values['connect_wifi'])
        self._project_info(values['project_info'])
        self._runtime(values['runtime'])
        self._push(values['push'])
        self.tabs.setCurrentIndex(selected)
        self._loading = False
        self.dirty = restore
        self.feedback.setText('。'.join(filter(None, (
            '已恢复未保存的草稿，保存前请核对' if restore else '',
            draft.recovery_warning,
            '已保留旧版页面草稿。请核对已保存的配置并补录未提交的修改' if draft.legacy_recovery else '',
            '缺少配置文件：' + '、'.join(draft.missing_files) + '；已加载原存储默认值，保存前请核对'
            if draft.missing_files else ''))))

    @staticmethod
    def _integer(value, title):
        try:
            return int(value)
        except ValueError:
            raise ValueError(title + '必须是整数') from None

    def focus_review(self, target):
        if target.field == 'reload':
            return focus_widget(self.reload_button)
        if target.field == 'order':
            return focus_widget(self.interval)
        if target.field == 'version_baseline':
            return focus_widget(self.version_fields[0])
        domain = self.fields.get(target.field)
        if domain:
            return focus_widget(next(iter(domain.values())))
        return focus_widget(next((fields[target.field] for fields in self.fields.values() if target.field in fields), None))

    def _capture_fields(self, values, *, raw=False):
        for domain in values:
            for key, widget in self.fields[domain].items():
                if isinstance(widget, QCheckBox):
                    value = int(widget.isChecked())
                    if domain == 'push':
                        value = str(value)
                elif isinstance(widget, QComboBox):
                    value = widget.currentData()
                else:
                    value = widget.text()
                    if not raw and domain == 'telnet' and key in ('port', 'timeout'):
                        value = self._integer(value, 'Telnet数值')
                    elif not raw and (domain in ('runtime', 'project_info', 'connect_wifi') or key == 'request_url'):
                        value = value.strip()
                values[domain][key] = value
        if 'telnet' in values:
            values['telnet']['telnet_need_enter_password_flag'] = 0
        return values

    def _checkpoint(self):
        if self.dirty and not self.busy and not self.draft.recovery_warning:
            values = self._capture_fields(deepcopy(self.draft.values), raw=True)
            values['order'] = dict(command_fail_retry_interval_time=self.interval.text(), items=[
                dict(command=row['command'].text(), retry_times=row['retry'].text(), expected_segments=[
                    dict(text=segment['text'].text(), negate=segment['negate'].isChecked())
                    for segment in row['segments']]) for row in self.commands])
            self.checkpoint_requested.emit(dict(token=self.draft.token, revision=self.draft.revision, values=values))

    def capture(self, *, pretest=False):
        values = self._capture_fields(deepcopy({'telnet': self.draft.values['telnet']} if pretest else self.draft.values))
        items = []
        for row in self.commands:
            command = row['command'].text().strip()
            segments = [dict(text=s['text'].text(), negate=s['negate'].isChecked())
                for s in row['segments'] if s['text'].text().strip()]
            if not command and not segments:
                continue
            retry = 1 if pretest else self._integer(row['retry'].text(), '重试次数')
            items.append(dict(command=command, retry_times=retry, expected_segments=segments))
        interval = 0 if pretest else self._integer(self.interval.text(), '全局重试间隔')
        values['order'] = dict(command_fail_retry_interval_time=interval, items=items)
        if pretest:
            return dict(token=self.draft.token, revision=self.draft.revision, **values)
        return dict(token=self.draft.token, revision=self.draft.revision, values=values)

    def set_busy(self, value):
        self.busy = value
        _, state, active, _ = self._pretest_view
        locked = value or active or bool(self._version_view and self._version_view.active) or self._push_trial_active
        self.tabs.setEnabled(not locked)
        self.save_button.setEnabled(not locked)
        self.reload_button.setEnabled(not locked)
        self.close_button.setEnabled(not value)
        self.pretest_stop_button.setVisible(active)
        self.pretest_stop_button.setEnabled(not value and state in ('queued', 'running'))

    @property
    def _push_trial_active(self):
        return self._push_trial_view is not None and self._push_trial_view.state == 'sending'

    def request_push_trial(self):
        if self.tabs.isEnabled():
            values = self._capture_fields({'push': {}})['push']
            self.set_busy(True)
            self.push_trial_requested.emit(dict(token=self.draft.token, revision=self.draft.revision, values=values))

    def show_push_trial(self, view):
        if view is None or view == self._push_trial_view:
            return
        self._push_trial_view = view
        self.set_busy(self.busy)
        self.feedback.setText(view.message)

    def request_version_query(self):
        channel = self.version_channel.currentData()
        if not self.tabs.isEnabled() or channel is None:
            return
        try:
            values = self._capture_fields({'telnet': deepcopy(self.draft.values['telnet'])})
        except ValueError as error:
            self.feedback.setText(str(error))
            return
        self.set_busy(True)
        self.version_requested.emit(dict(token=self.draft.token, revision=self.draft.revision, channel=channel, **values))

    def show_version_query(self, view):
        if view is None or view == self._version_view:
            return
        self._version_view = view
        self.set_busy(self.busy)
        if view.values:
            self._version_readback = view
            self._render_version_readback()
        states = {'queued': '等待查询', 'running': '正在查询', 'stop_requested': '正在收尾',
            'succeeded': '查询成功', 'failed': '查询失败', 'unknown': '查询结果待核实', 'stopped': '查询已停止'}
        status = f'CH{view.channel:02d} · {states.get(view.state, view.state)}'
        self.feedback.setText(status + (f' · {view.error}' if view.error else ''))

    def request_pretest(self):
        if self.busy or self._pretest_view[2]:
            return
        try:
            values = self.capture(pretest=True)
        except ValueError as error:
            self.feedback.setText(str(error))
            return
        self.set_busy(True)
        self.pretest_requested.emit(values)

    def request_pretest_stop(self):
        if self.pretest_stop_button.isEnabled() and self._pretest_view[2]:
            self.set_busy(True)
            self.pretest_stop_requested.emit(dict(token=self.draft.token))

    def show_pretest(self, snapshot):
        identifier, state, active, message = snapshot
        if not identifier or snapshot == self._pretest_view:
            return
        self._pretest_view = snapshot
        self.set_busy(self.busy)
        label_text = {'queued': '预备测试等待执行', 'running': '预备测试执行中',
            'stop_requested': '已请求停止，等待连接和日志收尾', 'stopped': '预备测试已停止',
            'succeeded': '预备测试完成', 'failed': '预备测试失败', 'unknown': '预备测试结果待核实',
            'skipped': '预备测试未执行', 'unchecked': '预备测试完成（含未校验）'}
        self.feedback.setText(' · '.join(filter(None, (label_text.get(state, state), message))))

    def request_save(self):
        if self.busy:
            return
        try:
            values = self.capture()
        except ValueError as error:
            self.feedback.setText(str(error))
            return
        answer = QMessageBox.question(self, '保存测试配置',
            '将保存六个标签页的配置并提交当前项目版本。\n测试项ini注释会按原存储方式重写；config.ini其它段和注释保留。\n不会执行设备命令或发送消息，是否继续？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.set_busy(True)
            self.save_requested.emit(values)

    def _discard(self, title):
        return not self.dirty or QMessageBox.question(self, title, '放弃当前窗口未保存的修改？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def request_reload(self):
        if self.busy:
            return
        if self.draft.recovery_warning:
            if QMessageBox.question(self, '重新加载', '放弃当前窗口未保存的输入，清除无法应用的 Qt 恢复草稿，再读取当前配置？',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        elif not self._discard('重新加载'):
            return
        self.reload_discarding_recovery()

    def reload_discarding_recovery(self):
        self._checkpoint_timer.stop()
        self.set_busy(True)
        self.reload_requested.emit(dict(token=self.draft.token, discard_recovery=True))

    def request_defaults(self):
        if self.busy:
            return
        answer = QMessageBox.question(self, '恢复默认测试项', '用原默认模板替换当前命令草稿？全局重试间隔保留，仍需点击保存。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.set_busy(True)
            self.defaults_requested.emit(dict(token=self.draft.token))

    def set_default_commands(self, items):
        for row in tuple(self.commands):
            self.remove_command(row)
        for item in items:
            self.add_command(item)
        self._changed()

    def request_wifi_interfaces(self):
        if not self.busy:
            self.set_busy(True)
            self.wifi_interfaces_requested.emit(dict(token=self.draft.token))

    def set_wifi_interfaces(self, names):
        field = self.fields['connect_wifi']['wireless_card_name']
        current = field.currentData()
        was_dirty = self.dirty
        self._loading = True
        field.clear()
        for name in dict.fromkeys((*names, *((current,) if current else ()))):
            field.addItem(name, name)
        if not field.count():
            field.addItem('', '')
        if current:
            field.setCurrentIndex(field.findData(current))
        self._loading = False
        self.dirty = was_dirty
        if names and not current:
            self._changed()
        self.feedback.setText('已读取无线网卡，原选择保留' if names else '未发现无线网卡，原选择保留，请检查网卡及驱动')

    def reject(self):
        self.close()

    def closeEvent(self, event):
        if self.busy:
            self.feedback.setText('正在处理配置操作，请等待结果后关闭')
            event.ignore()
        elif self._pretest_view[2]:
            self.request_pretest_stop()
            self.feedback.setText('预备测试正在停止并保存日志，请等待后再关闭')
            event.ignore()
        elif self._version_view and self._version_view.active:
            self.feedback.setText('样机版本查询正在收尾，请等待结束后关闭')
            event.ignore()
        elif self._push_trial_active:
            self.feedback.setText('测试消息正在发送，请等待结果后关闭')
            event.ignore()
        elif not self._discard('关闭配置窗口'):
            event.ignore()
        else:
            self._checkpoint_timer.stop()
            self.discard_revision = self.draft.revision if self.dirty else ''
            event.accept()
            # Emit finished only after the same close guard handles Escape and X.
            super().reject()
