"""Voice and TR069 forms for the project-scoped DUT dialog."""
from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QComboBox, QFrame, QLineEdit, QSizePolicy

from src.models.dut_config_models import DutTr069Settings, DutVoiceSettings
from src.models.dut_voice_tr069_form import (
    tr069_editor_defaults, tr069_status_form_values, voice_choice_options, voice_status_form_values,
)
from src.ui.qt.dut_wan_panel import AdaptiveWanForm
from src.ui.qt.theme import label


VOICE_LABELS = {
    'line_index': '线路索引', 'account_enabled': '启用 SIP 账号',
    'display_name': '显示名称', 'auth_username': '认证账号', 'auth_password': '认证密码',
    'proxy_server': '代理服务器', 'proxy_port': '代理端口',
    'outbound_proxy': '出站代理', 'outbound_proxy_port': '出站代理端口',
    'registrar_server': '注册服务器', 'registrar_server_port': '注册服务器端口',
    'dtmf_method': 'DTMF', 'register_expires': '注册有效期', 'sip_mode': 'SIP 模式', 'digit_map': 'DigitMap',
}
TR069_LABELS = {
    'acs_url': 'ACS URL', 'acs_username': 'ACS 账号', 'acs_password': 'ACS 密码',
    'periodic_inform_enabled': '启用周期 Inform', 'periodic_inform_interval': 'Inform 间隔（秒）',
    'connection_request_enabled': '启用 HTTP 连接请求',
    'connection_request_username': '连接请求账号', 'connection_request_password': '连接请求密码',
    'certificate_enabled': '启用证书', 'manual_inform': '配置后手动 Inform',
}


class DutVoiceTr069Panel(QFrame):
    query_index_changed = Signal()

    def __init__(self, feature, parent=None):
        super().__init__(parent)
        self.feature = feature
        self.setProperty('card', True)
        self.form = AdaptiveWanForm(self)
        self.inputs = {}
        self.codecs = []
        self.query_id = self.last_query_id = ''
        if feature == 'voice':
            defaults = DutVoiceSettings()
            choices = voice_choice_options(defaults)
            values = voice_status_form_values(defaults)
            for key, title in VOICE_LABELS.items():
                self.inputs[key] = self._field(key, title, values[key], choices.get(key))
            for position, codec in enumerate(defaults.codecs, 1):
                self.codecs.append(self._field('codecs', f'编码 {position}', codec, choices['codecs']))
            self.inputs['line_index'].textChanged.connect(lambda _: self.query_index_changed.emit())
        else:
            defaults = tr069_editor_defaults()
            values = tr069_status_form_values(defaults)
            values['manual_inform'] = defaults.manual_inform
            for key, title in TR069_LABELS.items():
                self.inputs[key] = self._field(key, title, values[key])
        self.feedback = label('', 'muted')
        self.feedback.setWordWrap(True)
        self.form.addRow(self.feedback)
        self.form.finish_initial_layout()

    def _field(self, key, title, value, choices=None):
        if choices is not None:
            widget = QComboBox()
            widget.addItems(choices)
            widget.setCurrentText(value)
        elif isinstance(value, bool):
            widget = QCheckBox(title)
            widget.setChecked(value)
        else:
            widget = QLineEdit(value)
        widget.setMaximumWidth(380)
        if isinstance(widget, (QLineEdit, QComboBox)):
            widget.setMinimumWidth(0)
            widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.form.addRow('' if isinstance(widget, QCheckBox) else title, widget)
        if key.endswith('_password'):
            widget.setEchoMode(QLineEdit.EchoMode.Password)
            reveal = QCheckBox(f'显示{title}')
            reveal.toggled.connect(lambda checked: widget.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
            self.form.addRow('', reveal)
        return widget

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'form'):
            self.form.reflow()

    @staticmethod
    def _read(widget):
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QComboBox):
            return widget.currentText()
        return widget.text()

    @staticmethod
    def _write(widget, value):
        with QSignalBlocker(widget):
            if isinstance(widget, QCheckBox):
                widget.setChecked(value)
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(value)
            else:
                widget.setText(value)

    @property
    def line_index(self):
        return self.inputs['line_index'].text().strip() if self.feature == 'voice' else ''

    def settings(self):
        values = {key: self._read(widget) for key, widget in self.inputs.items()}
        if self.feature == 'voice':
            keys = ('line_index', 'proxy_server', 'proxy_port', 'outbound_proxy', 'outbound_proxy_port',
                    'registrar_server', 'registrar_server_port', 'register_expires')
            values['codecs'] = [item.currentText() for item in self.codecs]
        else:
            keys = ('acs_url', 'periodic_inform_interval')
        for key in keys:
            values[key] = values[key].strip()
        return values

    def _update_feedback(self, text):
        self.feedback.setText(text)
        self.form._signature = None
        self.form.reflow()

    def _voice_choices(self, settings, reset=False):
        choices = voice_choice_options(settings)
        items = [(self.inputs[key], choices[key], getattr(settings, key)) for key in ('dtmf_method', 'sip_mode')]
        items.extend((widget, choices['codecs'], value) for widget, value in zip(self.codecs, settings.codecs))
        for widget, options, default in items:
            previous = widget.currentText()
            widget.clear()
            widget.addItems(options)
            widget.setCurrentText(previous if reset and previous in options else default)

    def _tr069_capabilities(self, fields):
        supported = set(fields)
        for key, widget in self.inputs.items():
            widget.setEnabled(not supported or key in supported)
        if supported and 'manual_inform' not in supported:
            self.inputs['manual_inform'].setChecked(False)

    def _reset_capabilities(self):
        if self.feature == 'voice':
            self._voice_choices(DutVoiceSettings(), reset=True)
        else:
            self._tr069_capabilities(())

    def invalidate_query(self):
        if not self.query_id:
            return
        self.query_id = ''
        self._reset_capabilities()
        self._update_feedback('')

    def set_query(self, query):
        identifier = query['query_id']
        if identifier == self.last_query_id:
            return
        self.query_id = self.last_query_id = identifier
        raw = query['settings']
        if raw is None:
            self._reset_capabilities()
            self._update_feedback('目标状态或能力不一致，未自动回填' if query['all_succeeded'] else '查询未全部成功，未自动回填')
            return
        if self.feature == 'voice':
            settings = DutVoiceSettings(**raw)
            values = voice_status_form_values(settings)
            values.pop('codecs')
            self._voice_choices(settings)
        else:
            settings = DutTr069Settings(**raw)
            values = tr069_status_form_values(settings)
            self._tr069_capabilities(settings.supported_fields)
        for key, value in values.items():
            self._write(self.inputs[key], value)
        self._update_feedback('已同步所有目标的共同状态与能力')
