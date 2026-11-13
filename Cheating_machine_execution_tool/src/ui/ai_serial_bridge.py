"""GUI-owned diagnostic handlers; workers receive only AiSerialClient."""
from __future__ import annotations
import threading
import uuid
from src.models.serial_models import SerialSettings
from src.services.ai_serial_client import AiSerialClient, SerialLease
from src.services.pipeline_runtime import PipelineDispatcher, PipelineUiError


class AiSerialBridge:
    def __init__(self, terminal, manager, busy, forbidden_port=lambda: ''):
        self.terminal, self.manager = terminal, manager
        self.busy_callback, self.forbidden_port = busy, forbidden_port
        self.client = AiSerialClient(manager)
        self.requests = self.client.channel.requests
        self.controls, self.lock = self.client.controls, self.client.lock
        self.closed = False
        self.dispatcher = PipelineDispatcher(self.client.channel)
        self.dispatcher.handlers.update(busy=lambda request: self.busy_callback(request.args[0]),
                                        acquire=self._acquire, restore=self._restore_status,
                                        status=self._status)
        terminal.ai_debug_cancel = self.client.cancel_port

    def poll(self):
        self.dispatcher.poll(20)

    def _acquire(self, request):
        target = request.args[0]
        if self.busy_callback(target):
            raise RuntimeError('目标设备正在执行操作，跳过串口主动采集')
        if not target.port or target.port.upper() == self.forbidden_port().upper():
            raise ValueError('目标串口不明确或与程控电源串口冲突')
        existing = self.terminal.tabs.get(target.vlan.lower())
        if existing and existing['session'] is not None and existing['port'].upper() != target.port.upper():
            raise ValueError('已打开的目标标签与本次COM快照不一致')
        if not self.manager.manual_writable(target.port):
            raise RuntimeError('目标串口已被其它流程控制，只允许读取日志')
        if not request.admit():
            raise PipelineUiError('串口诊断已取消')
        self.terminal.show([(target.vlan, target.port)])
        if not self.terminal.open_monitor(target.vlan.lower(), raise_errors=True):
            raise RuntimeError('目标串口打开失败')
        owner = 'ai-debug:' + uuid.uuid4().hex
        session = self.manager.acquire_existing_control(owner, SerialSettings(target.port))
        cancelled = threading.Event()
        with self.lock:
            self.controls[target.port.upper()] = (owner, cancelled)
        item = self.terminal.tabs[target.vlan.lower()]
        item['status'].set(f'{target.port} AI Debug中，手动发送暂时锁定；日志继续记录')
        return SerialLease(self.client, target, session, owner, cancelled, item.get('event_token'))

    def _restore_status(self, request):
        target, token = request.args
        item = self.terminal.tabs.get(target.vlan.lower())
        if (item and item['session'] is not None and item.get('event_token') is token
                and self.manager.manual_writable(target.port)):
            item['status'].set(f'{target.port} 监控中，AI Debug已结束，日志继续记录')

    def _status(self, request):
        target = request.args[0]
        result = self.manager.diagnostic_state(target.port)
        result['last_open_error'] = self.terminal.last_open_errors.get(target.port.upper(), '')
        result['power_port_conflict'] = target.port.upper() == self.forbidden_port().upper()
        return result

    def read(self, target):
        return self.client.read(target)

    def acquire(self, target, stop):
        return self.client.acquire(target, stop)

    def close(self):
        self.closed = True
        self.client.close()
        self.dispatcher.poll(32)
        self.dispatcher.dispose()
        self.terminal.ai_debug_cancel = None
