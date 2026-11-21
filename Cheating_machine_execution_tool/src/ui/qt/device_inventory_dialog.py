"""Show original host inventory, active workspace leases and project bindings."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHeaderView, QHBoxLayout, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from src.core.host_resource_lock import physical_key
from src.ui.qt.theme import button, label


def _table(columns, flexible):
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.verticalHeader().hide()
    header = table.horizontalHeader()
    for index in range(len(columns)):
        header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch if index in flexible
                                    else QHeaderView.ResizeMode.ResizeToContents)
    return table


def _replace_rows(table, rows):
    table.setRowCount(len(rows))
    for number, row in enumerate(rows):
        for column, value in enumerate(row):
            current = table.item(number, column)
            if current is None:
                current = QTableWidgetItem()
                table.setItem(number, column, current)
            if current.text() != value:
                current.setText(value)
                current.setToolTip(value)


def _read_status(values, last_read, failed):
    if last_read is None:
        return '读取失败，暂无候选' if failed else '尚未读取'
    stamp = last_read.strftime('%H:%M:%S')
    return (f'读取失败，保留 {stamp} 的 {len(values)} 条记录' if failed
            else f'{len(values)} 条 · 上次读取 {stamp}')


class DeviceInventoryDialog(QDialog):
    def __init__(self, parent, refresh):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('DUTPilot · 设备管理')
        available = self.screen().availableGeometry()
        self.resize(min(1040, int(available.width() * .94)), min(600, int(available.height() * .90)))
        outer = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(label('设备管理', 'title'), 1)
        self.refresh_button = button('刷新串口/网卡', refresh)
        header.addWidget(self.refresh_button)
        outer.addLayout(header)

        self.tabs = QTabWidget()
        self.adapters = _table(('网卡名称', '状态', '接口 GUID', '工作区活动租约'), (0, 2, 3))
        self.ports = _table(('串口', '工作区活动租约'), (1,))
        self.bindings = _table(('项目', '通道', '通道选择', '网卡', '样机 COM', '配置来源'), (0, 3, 5))
        self.adapter_status = self._add_tab('网卡', self.adapters)
        self.port_status = self._add_tab('串口', self.ports)
        self.binding_status = self._add_tab('项目通道', self.bindings)
        outer.addWidget(self.tabs, 1)
        self.lease_status = label('', 'muted')
        self.lease_status.setWordWrap(True)
        outer.addWidget(self.lease_status)
        self._prior = None

    def _add_tab(self, title, table):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        status = label('', 'muted')
        status.setWordWrap(True)
        layout.addWidget(status)
        layout.addWidget(table, 1)
        self.tabs.addTab(panel, title)
        return status

    def update_inventory(self, inventory, leases, projects, refreshing):
        self.refresh_button.setEnabled(not refreshing)
        self.refresh_button.setText('正在读取…' if refreshing else '刷新串口/网卡')
        stamp = leases.sampled_at.strftime('%H:%M:%S') if leases.sampled_at else '尚未采样'
        self.lease_status.setText('工作区资源保护不可用' if leases.protection_unavailable else f'工作区活动租约 · {stamp}')
        bindings = tuple((project.name, f'CH{channel.number:02d}', '未选' if channel.state == 'disabled' else '已选',
                          channel.vlan or '—', channel.port or '—', project.channel_snapshot_label or '项目配置')
                         for project in projects for channel in project.channels
                         if channel.state != 'disabled' or channel.vlan or channel.port)
        snapshot = (inventory, leases.owners, bindings, len(projects))
        if snapshot == self._prior:
            return
        self._prior = snapshot
        owners = dict(leases.owners)

        adapters = []
        for row in inventory.adapters:
            physical = '、'.join(owners.get('adapter:' + row.interface_guid.casefold(), ()))
            named = '、'.join(owners.get('adapter:' + row.alias.casefold(), ()))
            adapters.append((row.alias, row.status or '未报告', row.interface_guid or '—',
                             physical or (f'{named}（名称占用）' if named else '—')))
        ports = [(port, '、'.join(owners.get(physical_key('serial:' + port), ())) or '—') for port in inventory.ports]
        _replace_rows(self.adapters, adapters)
        _replace_rows(self.ports, ports)
        _replace_rows(self.bindings, bindings)
        self.adapter_status.setText(_read_status(adapters, inventory.adapters_at, inventory.adapters_failed))
        self.port_status.setText(_read_status(ports, inventory.ports_at, inventory.ports_failed))
        self.binding_status.setText(f'{len(projects)} 个打开的项目 · {len(bindings)} 条通道记录')
