"""Passive monitors and bounded log reads; no serial text injection or DUT commands."""
from pathlib import Path
import threading

from src.models.capabilities import CapabilitySpec, CapabilityError, object_schema, fingerprint
from src.models.serial_models import SerialSettings
from src.core.serial_transport import vlan_to_serial_port
from src.services.capability_device_services import CHANNEL_PROPERTIES
from src.services.power_test_log_service import latest_power_test_result_log


class ObservationCapabilities:
    def __init__(self, service, tool_root):
        self.service, self.root = service, Path(tool_root)
        self.lock, self.monitors = threading.RLock(), {}
        schema = object_schema(CHANNEL_PROPERTIES, ('channel_ids',))
        for identifier, name, handler, risk in (
                ('serial.monitor.open', '打开被动串口日志', self.open, 'modify'),
                ('serial.monitor.close', '关闭本次AI被动监控', self.close, 'modify'),
                ('serial.status', '实时串口所有者状态', self.status, 'read'),
                ('logs.power', '读取通道最新结果日志', self.power, 'read'),
                ('logs.wifi', '读取本次WiFi结果日志', self.wifi, 'read')):
            service.registry.register(CapabilitySpec(identifier, name, name + '；不发送字符、不关闭其他窗口的监控，读取最多64KiB。',
                schema, handler, risk=risk))

    def _targets(self, arguments, authority):
        snapshot, channels = self.service.devices.selected(arguments, authority)
        return snapshot, [(c, c.serial_port or vlan_to_serial_port(c.vlan_name.lower())) for c in channels]

    def open(self, arguments, authority):
        snapshot, targets = self._targets(arguments, authority)
        result = []
        with self.lock:
            for channel, port in targets:
                owner = 'capability-monitor:' + fingerprint([authority.principal, channel.section])
                key = (authority.principal, channel.section)
                existing = self.monitors.get(key)
                if existing and existing[1] != port:
                    raise CapabilityError('target_changed', '先关闭旧通道绑定的AI串口监控，再打开新绑定')
                path = self.service.files.workspace / 'serial' / (owner.rsplit(':', 1)[-1] + '.log')
                path.parent.mkdir(parents=True, exist_ok=True)
                self.service.manager.acquire_monitor(owner, SerialSettings(port), path)
                self.monitors[key] = (owner, port)
                self.service.emit('[被动串口] 已取得监控所有权：' + port + '；未发送字符')
                result.append(dict(channel=channel.section, port=port, monitor_owner=owner))
        return dict(items=result)

    def close(self, arguments, authority):
        authority.check(arguments['channel_ids'])
        items = []
        with self.lock:
            for number in arguments['channel_ids']:
                entry = self.monitors.pop((authority.principal, 'channel_' + str(number)), None)
                if entry:
                    self.service.manager.release(*entry, wait=False)
                items.append(dict(channel=number, state='close_requested' if entry else 'skipped'))
        self.service.emit('[被动串口] 已释放本次身份的监控所有权，其他监控保持')
        return dict(items=items)

    def close_all(self):
        with self.lock:
            entries, self.monitors = list(self.monitors.values()), {}
        for entry in entries:
            self.service.manager.release(*entry, wait=False)

    def status(self, arguments, authority):
        _, targets = self._targets(arguments, authority)
        return dict(items=[dict(channel=c.section, **self.service.manager.diagnostic_state(port)) for c, port in targets])

    @staticmethod
    def tail(path):
        if path is None or not Path(path).is_file():
            return dict(state='missing', notice='本次日志尚未生成或已被移动；未回退到历史WiFi文件')
        path = Path(path)
        with path.open('rb') as stream:
            size = path.stat().st_size
            stream.seek(max(0, size - 65536))
            content = stream.read(65536).decode('utf-8', errors='replace')
        return dict(path=str(path), content=content, truncated=size > 65536)

    def power(self, arguments, authority):
        self.service.devices.selected(arguments, authority)
        return dict(items=[dict(channel=n, **self.tail(latest_power_test_result_log(self.root / 'Auto_power_on_off_tool', n)))
                          for n in arguments['channel_ids']])

    def wifi(self, arguments, authority):
        snapshot, _ = self.service.devices.selected(arguments, authority)
        current = dict(snapshot.get('current_wifi_logs', {}))
        latest = self.service.devices.latest_aging
        if latest is not None and latest[1] == authority.principal:
            # This exact live session supplies the current attempt, never directory recency.
            session = latest[2].power_test_resume_session
            if session is not None:
                current.update({str(n): str(session.current_wifi_log(n) or '') for n in arguments['channel_ids']})
        return dict(items=[dict(channel=n, **self.tail(current.get(str(n)))) for n in arguments['channel_ids']])
