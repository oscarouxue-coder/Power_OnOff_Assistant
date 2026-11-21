"""Read-only view of the same immutable channel snapshots used by the matrix."""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor
from src.ui.qt.theme import DANGER, MUTED, SUCCESS, WARNING, assert_gui_thread


class ChannelTableModel(QAbstractTableModel):
    HEADERS = ('通道', '实际状态', '已完成 / 总轮次', 'VLAN', 'COM')
    STATES = {'running': '运行中', 'success': '正常', 'failed': '异常', 'retry': '重试中',
        'unknown': '未知', 'disabled': '未启用', 'stopped': '已停止'}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.channels = ()

    def set_channels(self, channels):
        assert_gui_thread()
        channels = tuple(channels)
        if channels == self.channels:
            return
        if tuple(c.number for c in channels) == tuple(c.number for c in self.channels):
            self.channels = channels
            if channels:
                self.dataChanged.emit(self.index(0, 0), self.index(len(channels) - 1, 4), [])
        else:
            self.beginResetModel()
            self.channels = channels
            self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.channels)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 5

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.channels):
            return None
        channel = self.channels[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return channel.number
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 1:
            return QColor({'running': SUCCESS, 'success': SUCCESS, 'failed': DANGER,
                'retry': WARNING}.get(channel.state, MUTED))
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            cycle = ('—' if channel.cycle is None else str(channel.cycle))
            total = ('—' if channel.total is None else str(channel.total))
            state = self.STATES.get(channel.state, '未知')
            if channel.stage:
                state += ' · 最近上报：' + channel.stage
            return (f'CH{channel.number:02d}', state, cycle + ' / ' + total,
                channel.vlan or '未配置', channel.port or '未配置')[index.column()]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None
