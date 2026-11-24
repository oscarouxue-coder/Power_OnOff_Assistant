"""Qt WAN form using the original shared presentation rules and data model."""
from dataclasses import asdict, fields
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout, QLineEdit, QSizePolicy, QWidget
from src.models.dut_config_models import DutWanConnectionInfo, DutWanSettings
from src.models.dut_wan_form import (WAN_ROUTER_SERVICE_TYPES, WAN_BRIDGE_SERVICE_TYPES,
    WAN_LAN_PORT_MASK, _port_bind_mask_value, normalize_wan_address_modes, resolve_wan_form_rules,
    wan_connection_form_values, wan_lan_ports_from_port_bind, wan_port_bind_from_lan_ports)
from src.ui.qt.theme import label


class AdaptiveWanForm:
    """Reflow existing row widgets; hidden fields keep their actual values."""
    def __init__(self, parent):
        self.parent = parent
        self.grid = QGridLayout(parent)
        self.rows = []
        self.columns = 1
        self._signature = None
        self._building = True

    def addRow(self, title, field=None):
        self.insertRow(len(self.rows), title, field)

    def insertRow(self, index, title, field=None):
        span = field is None
        if span: field, title = title, ''
        group = QWidget(self.parent)
        form = QFormLayout(group)
        form.setContentsMargins(0, 0, 0, 0)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow(field) if span else form.addRow(title, field)
        self.rows.insert(index, dict(group=group, field=field, visible=True, span=span,
            label=None if span else form.labelForField(field)))
        self.reflow()

    def setRowVisible(self, field, visible):
        row = next(r for r in self.rows if r['field'] is field)
        row['visible'] = visible
        self.reflow()

    def finish_initial_layout(self):
        self._building = False
        self.reflow()

    def reflow(self):
        if self._building:
            return
        columns = 2 if self.parent.width() >= 800 else 1
        signature = (columns, self.parent.width(), tuple((id(r['field']), r['visible']) for r in self.rows))
        if signature == self._signature: return
        self._signature = signature
        self.columns = columns
        label_width = max((r['label'].fontMetrics().horizontalAdvance(r['label'].text())
            for r in self.rows if r['visible'] and r['label'] is not None), default=0)
        margins = self.grid.contentsMargins()
        width = max(1, self.parent.width() - margins.left() - margins.right())
        column_width = max(1, (width - self.grid.horizontalSpacing() * (columns - 1)) // columns)
        for row in self.rows: self.grid.removeWidget(row['group'])
        position = 0
        for row in self.rows:
            if not row['visible']:
                row['group'].hide()
                continue
            if row['label'] is not None: row['label'].setMinimumWidth(label_width)
            row['field'].ensurePolished()
            form = row['group'].layout()
            needed = form.totalHeightForWidth(width if row['span'] else column_width)
            row['group'].setMinimumHeight(max(form.minimumSize().height(), needed))
            if row['span']:
                position = ((position + columns - 1) // columns) * columns
                self.grid.addWidget(row['group'], position // columns, 0, 1, columns)
                position += columns
            else:
                self.grid.addWidget(row['group'], position // columns, position % columns)
                position += 1
            row['group'].show()
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, int(columns == 2))


class DutWanPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty('card', True)
        self.form = AdaptiveWanForm(self)
        self.inputs = {}
        self._updating = False
        self._last_access = 'IPoE'
        self._preserved = 0
        self.query_id = ''
        self.last_query_id = ''
        self.connection_details = {}
        defaults = asdict(DutWanSettings(vlan_id='200', ipv4_netmask='255.255.255.0'))
        choices = {'operation': ('新增', '修改', '删除'), 'mode': ('路由', '桥接'),
            'connection_index': (), 'service_type': WAN_ROUTER_SERVICE_TYPES,
            'access_type': ('IPoE', 'PPPoE'), 'ip_protocol': ('IPv4', 'IPv6', 'IPv4+IPv6（双栈）'),
            'ipv4_type': ('DHCP', '静态'), 'ipv6_type': ('SLAAC', 'DHCPv6', '静态')}
        defaults.update(operation='新增', mode='路由', ipv4_type='DHCP')
        titles = {'operation': '操作', 'connection_index': '现有连接名 / 索引', 'mode': '模式',
            'service_type': '业务类型', 'vlan_id': '业务 VLAN ID', 'multicast_vlan_id': '组播 VLAN ID',
            'vlan_priority': 'VLAN 优先级', 'mtu': 'MTU', 'nat_enabled': '启用 NAT', 'access_type': '接入方式',
            'ip_protocol': 'IP 协议', 'ipv4_type': 'IPv4 地址方式', 'ipv4_address': 'IPv4 地址',
            'ipv4_netmask': 'IPv4 子网掩码', 'ipv4_gateway': 'IPv4 网关', 'ipv4_primary_dns': 'IPv4 主 DNS',
            'ipv4_secondary_dns': 'IPv4 备 DNS', 'ipv6_type': 'IPv6 地址方式', 'ipv6_address': 'IPv6 地址',
            'ipv6_prefix': 'IPv6 前缀', 'ipv6_gateway': 'IPv6 网关', 'ipv6_primary_dns': 'IPv6 主 DNS',
            'ipv6_secondary_dns': 'IPv6 备 DNS', 'pppoe_username': 'PPPoE 账号', 'pppoe_password': 'PPPoE 密码'}
        for key, title in titles.items():
            if key in choices:
                widget = QComboBox()
                widget.addItems(choices[key])
                widget.setCurrentText(str(defaults[key]))
            elif isinstance(defaults[key], bool):
                widget = QCheckBox(title)
                widget.setChecked(defaults[key])
            else:
                widget = QLineEdit(str(defaults[key]))
            widget.setMaximumWidth(380)
            widget.setMinimumWidth(0)
            if isinstance(widget, (QComboBox, QLineEdit)):
                widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            self.inputs[key] = widget
            self.form.addRow('' if key == 'nat_enabled' else title, widget)
        self.inputs['pppoe_password'].setEchoMode(QLineEdit.EchoMode.Password)
        self.password_visible = QCheckBox('显示 PPPoE 密码')
        self.password_visible.toggled.connect(lambda checked: self.inputs['pppoe_password'].setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        self.form.addRow('', self.password_visible)
        self.lan_group = QWidget()
        lan = QGridLayout(self.lan_group)
        lan.setContentsMargins(0, 0, 0, 0)
        self.lan = []
        for number in range(1, 9):
            check = QCheckBox('LAN' + str(number))
            lan.addWidget(check, (number - 1) // 4, (number - 1) % 4)
            self.lan.append(check)
        self.form.insertRow(7, '端口绑定', self.lan_group)
        self.feedback = label('', 'muted')
        self.feedback.setWordWrap(True)
        self.form.addRow(self.feedback)
        for key in ('operation', 'mode', 'service_type', 'access_type', 'ip_protocol', 'ipv4_type', 'ipv6_type'):
            self.inputs[key].currentTextChanged.connect(lambda _, name=key: self.update_rules(name))
        self.inputs['connection_index'].currentTextChanged.connect(self.apply_connection)
        self.update_rules('initial')
        self.form.finish_initial_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'form'): self.form.reflow()

    def text(self, key):
        widget = self.inputs[key]
        return widget.currentText() if isinstance(widget, QComboBox) else widget.text()

    def update_rules(self, changed=''):
        if self._updating:
            return
        self._updating = True
        try:
            if changed == 'operation' and self.text('operation') == '新增':
                self._preserved = 0
            access = self.text('access_type')
            if access != self._last_access:
                self.inputs['mtu'].setText('1492' if access == 'PPPoE' else '1500')
                self._last_access = access
            v4, v6 = normalize_wan_address_modes(access, self.text('ip_protocol'),
                self.text('ipv4_type'), self.text('ipv6_type'), changed=changed)
            for key, values, value in (
                ('ipv4_type', ('DHCP',) if access == 'PPPoE' else ('DHCP', '静态'), v4),
                ('ipv6_type', ('SLAAC', 'DHCPv6') if access == 'PPPoE' else ('SLAAC', 'DHCPv6', '静态'), v6)):
                combo = self.inputs[key]
                combo.clear(); combo.addItems(values); combo.setCurrentText(value)
            bridge = self.text('mode') == '桥接'
            services = WAN_BRIDGE_SERVICE_TYPES if bridge else WAN_ROUTER_SERVICE_TYPES
            old = self.text('service_type')
            combo = self.inputs['service_type']
            combo.clear(); combo.addItems(services)
            combo.setCurrentText(old if old in services else 'IPTV' if bridge else 'INTERNET')
            if bridge and self.port_bind() == '0':
                self.lan[0].setChecked(True)
            rules = resolve_wan_form_rules(self.text('operation'), self.text('mode'), access,
                self.text('ip_protocol'), self.text('ipv4_type'), self.text('ipv6_type'), self.text('service_type'))
            visible = dict(connection_index=rules.show_index, multicast_vlan_id=rules.show_multicast_vlan,
                access_type=rules.show_router, ip_protocol=rules.show_router, nat_enabled=rules.show_router,
                ipv4_type=rules.show_ipv4_selector, ipv6_type=rules.show_ipv6_selector,
                pppoe_username=rules.show_pppoe_credentials, pppoe_password=rules.show_pppoe_credentials)
            for key in ('mode', 'service_type', 'vlan_id', 'vlan_priority', 'mtu'):
                visible[key] = rules.show_config
            for key in self.inputs:
                if key.startswith('ipv4_') and key != 'ipv4_type': visible[key] = rules.show_ipv4_static
                if key.startswith('ipv6_') and key != 'ipv6_type': visible[key] = rules.show_ipv6_static
            for key, show in visible.items():
                self.form.setRowVisible(self.inputs[key], show)
            self.form.setRowVisible(self.lan_group, rules.show_config)
            self.form.setRowVisible(self.password_visible, rules.show_pppoe_credentials)
        finally:
            self._updating = False

    def port_bind(self):
        return wan_port_bind_from_lan_ports((n for n, c in enumerate(self.lan, 1) if c.isChecked()), preserved_mask=self._preserved)

    def settings(self):
        values = {f.name: self.text(f.name) for f in fields(DutWanSettings) if f.name not in ('nat_enabled', 'port_bind')}
        values.update(operation={'新增':'add','修改':'modify','删除':'delete'}[values['operation']],
            mode={'路由':'router','桥接':'bridge'}[values['mode']],
            ip_protocol={'IPv4+IPv6（双栈）':'IPv4IPv6'}.get(values['ip_protocol'], values['ip_protocol']),
            ipv4_type={'DHCP':'Dynamic','静态':'Static'}[values['ipv4_type']],
            ipv6_type={'静态':'Static'}.get(values['ipv6_type'], values['ipv6_type']),
            nat_enabled=self.inputs['nat_enabled'].isChecked(), port_bind=self.port_bind())
        # Match original trimming, including untrimmed PPPoE credentials.
        return {k: v.strip() if isinstance(v, str) and k not in ('pppoe_username','pppoe_password') else v for k,v in values.items()}

    def invalidate_query(self):
        self.query_id = ''
        self.connection_details = {}
        self.inputs['connection_index'].clear()
        self.feedback.clear()
        self.form._signature = None
        self.form.reflow()

    def set_connections(self, query):
        if not query or query['query_id'] == self.last_query_id:
            return
        self.last_query_id = self.query_id = query['query_id']
        self.connection_details = query['details']
        combo = self.inputs['connection_index']
        old = combo.currentText()
        combo.blockSignals(True)
        combo.clear(); combo.addItems(query['names'])
        if old in query['names']: combo.setCurrentText(old)
        combo.blockSignals(False)
        self.feedback.setText(f"已查询 {len(query['channel_ids'])} 台，共同 WAN {len(query['names'])} 个")
        self.apply_connection(combo.currentText())

    def apply_connection(self, name):
        if not name:
            return
        info = self.connection_details.get(name)
        if info is None:
            self.feedback.setText('当前连接的完整参数在目标间不一致；可删除，修改前请人工核对参数')
            self.form._signature = None
            self.form.reflow()
            return
        values = wan_connection_form_values(DutWanConnectionInfo(**info))
        self._updating = True
        try:
            for key, value in values.items():
                if key == 'port_bind': continue
                widget = self.inputs[key]
                if isinstance(widget, QCheckBox):
                    if value is not None: widget.setChecked(bool(value))
                elif isinstance(widget, QComboBox):
                    if value not in (None, ''):
                        if widget.findText(value) < 0: widget.addItem(value)
                        widget.setCurrentText(value)
                else:
                    widget.setText(str(value or ''))
            mask = _port_bind_mask_value(values['port_bind'] or '0')
            self._preserved = mask & ~WAN_LAN_PORT_MASK
            ports = wan_lan_ports_from_port_bind(str(mask))
            for number, check in enumerate(self.lan, 1): check.setChecked(number in ports)
            self._last_access = self.text('access_type')
        finally:
            self._updating = False
        self.update_rules('snapshot')
        self.feedback.setText('已同步完整一致的 WAN 信息：' + name)
        self.form._signature = None
        self.form.reflow()
