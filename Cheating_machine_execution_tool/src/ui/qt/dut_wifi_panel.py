"""WiFi form projection, shared original mappings and native Qt choices."""
from dataclasses import replace
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFrame, QLineEdit, QSizePolicy
from src.models.dut_config_models import DutWifiSettings, DutWifiRadioSettings
from src.models.dut_wifi_form import wifi_editor_defaults, wifi_status_form_values, wifi_choice_options, WIFI_SSID_INDEX_OPTIONS
from src.ui.qt.dut_wan_panel import AdaptiveWanForm
from src.ui.qt.theme import label


class DutWifiPanel(QFrame):
    dual_changed = Signal(bool)
    query_index_changed = Signal()

    def __init__(self, feature, parent=None):
        super().__init__(parent)
        self.feature = feature
        self.setProperty('card', True)
        self.form = AdaptiveWanForm(self)
        self.inputs = {}
        self.query_id = self.last_query_id = ''
        self._last_status = None
        self._updating = False
        default = wifi_editor_defaults(feature)
        self.band, self.peer_band = default.band, default.peer_radio.band
        values = wifi_status_form_values(default)
        values['ssid_increment'] = False
        choices = wifi_choice_options(default)
        self.show_password = QCheckBox('显示 WiFi 密码')
        titles = {'ssid_index':'SSID 索引', 'ssid':'WiFi 名称', 'password':'WiFi 密码',
            'security_mode':'认证 / 加密模式', 'enabled':'启用 WiFi', 'hidden':'隐藏 SSID',
            'dual_band_enabled':'双频合一', 'ssid_increment':'SSID 递增', 'channel':self.band+' 信道',
            'channel_bandwidth':self.band+' 带宽', 'operating_mode':self.band+' 协议',
            'transmit_power':'公共发射功率 %', 'max_associations':'最大接入数', 'wmm_enabled':'启用 WMM',
            'peer_channel':self.peer_band+' 信道', 'peer_channel_bandwidth':self.peer_band+' 带宽',
            'peer_operating_mode':self.peer_band+' 协议'}
        for key, title in titles.items():
            value = values[key]
            if key in choices or key == 'ssid_index':
                widget = QComboBox()
                # Programmatically preserve a queried/current value outside the
                # dropdown, matching ttk's readonly value without free typing.
                widget.setEditable(True)
                widget.lineEdit().setReadOnly(True)
                widget.lineEdit().setStyleSheet('QLineEdit { border: none; padding: 0; min-height: 0; background: transparent; }')
                widget.setCompleter(None)
                widget.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                widget.addItems(WIFI_SSID_INDEX_OPTIONS if key=='ssid_index' else choices[key])
                widget.setEditText(str(value))
            elif isinstance(value, bool):
                widget = QCheckBox(title)
                widget.setChecked(value)
            else:
                widget = QLineEdit(str(value))
            widget.setMaximumWidth(380)
            widget.setMinimumWidth(0)
            if isinstance(widget, (QComboBox,QLineEdit)):
                widget.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
            self.inputs[key] = widget
            self.form.addRow('' if isinstance(widget,QCheckBox) else title,widget)
            if key == 'password':
                self.form.addRow('', self.show_password)
        self.inputs['password'].setEchoMode(QLineEdit.EchoMode.Password)
        self.show_password.toggled.connect(lambda checked:self.inputs['password'].setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        self.feedback = label('','muted')
        self.feedback.setWordWrap(True)
        self.form.addRow(self.feedback)
        self.inputs['security_mode'].currentTextChanged.connect(lambda *_:self.update_rules())
        self.inputs['dual_band_enabled'].toggled.connect(self._dual_changed)
        self.inputs['ssid_index'].currentTextChanged.connect(self._index_changed)
        self.update_rules()
        self.form.finish_initial_layout()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'form'):self.form.reflow()

    def text(self,key):
        widget=self.inputs[key]
        return widget.currentText() if isinstance(widget,QComboBox) else widget.text()

    def _index_changed(self,*_):
        if not self._updating:self.query_index_changed.emit()

    def _dual_changed(self,checked):
        self.update_rules()
        if not self._updating:self.dual_changed.emit(checked)

    def set_dual(self,checked):
        widget=self.inputs['dual_band_enabled']
        previous=widget.blockSignals(True)
        widget.setChecked(checked)
        widget.blockSignals(previous)
        self.update_rules()

    def _choices(self,reset=False):
        source=self._last_status or wifi_editor_defaults(self.feature)
        if self._last_status is not None and source.peer_radio is not None:
            source=replace(source,dual_band_enabled=self.inputs['dual_band_enabled'].isChecked())
        options=wifi_choice_options(source)
        defaults=wifi_status_form_values(wifi_editor_defaults(self.feature))
        for key,items in options.items():
            widget=self.inputs[key]
            value=widget.currentText()
            if reset and value not in items:value=str(defaults[key])
            previous=widget.blockSignals(True)
            widget.clear();widget.addItems(items);widget.setEditText(value)
            widget.blockSignals(previous)

    def update_rules(self):
        if self._updating:return
        self._updating=True
        try:
            self._choices()
            secured=self.text('security_mode')!='None'
            self.form.setRowVisible(self.inputs['password'],secured)
            self.form.setRowVisible(self.show_password,secured)
            dual=self.inputs['dual_band_enabled'].isChecked()
            for key in ('peer_channel','peer_channel_bandwidth','peer_operating_mode'):
                self.form.setRowVisible(self.inputs[key],dual)
        finally:self._updating=False

    def settings(self):
        values={key:self.text(key).strip() for key in ('ssid_index','channel','channel_bandwidth',
            'security_mode','operating_mode','transmit_power','max_associations')}
        values.update(band=self.band,ssid=self.text('ssid'),password=self.text('password'))
        for key in ('dual_band_enabled','enabled','hidden','wmm_enabled'):
            values[key]=self.inputs[key].isChecked()
        if values['dual_band_enabled']:
            values['peer_radio']=dict(band=self.peer_band,channel=self.text('peer_channel').strip(),
                channel_bandwidth=self.text('peer_channel_bandwidth').strip(),
                operating_mode=self.text('peer_operating_mode').strip(),transmit_power=values['transmit_power'])
        return values

    def invalidate_query(self):
        if not self.query_id and self._last_status is None and not self.feedback.text():return
        self.query_id=''
        self._last_status=None
        self.feedback.clear()
        self._choices(reset=True)
        self.update_rules()

    def set_query(self,query):
        if query['query_id']==self.last_query_id:return
        self.last_query_id=self.query_id=query['query_id']
        raw=query['settings']
        if raw is None:
            self._last_status=None
            self._choices(reset=True)
            self.feedback.setText('目标参数或能力不一致，未自动回填' if query['all_succeeded'] else '查询未全部成功，未自动回填')
            self.form._signature=None;self.form.reflow()
            return
        raw=dict(raw)
        if raw.get('peer_radio') is not None:raw['peer_radio']=DutWifiRadioSettings(**raw['peer_radio'])
        settings=DutWifiSettings(**raw)
        self._last_status=settings
        values=wifi_status_form_values(settings)
        self._updating=True
        try:
            for key,value in values.items():
                widget=self.inputs[key]
                old=widget.blockSignals(True)
                if isinstance(widget,QComboBox):widget.setEditText(str(value))
                elif isinstance(widget,QCheckBox):widget.setChecked(value)
                else:widget.setText(str(value))
                widget.blockSignals(old)
        finally:self._updating=False
        self.update_rules()
        self.dual_changed.emit(settings.dual_band_enabled)
        self.feedback.setText('已同步 '+self.band+' WiFi 当前参数与实际能力')
        self.form._signature=None;self.form.reflow()
