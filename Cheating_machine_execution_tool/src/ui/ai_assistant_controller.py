"""主窗口装配与主线程桥；诊断状态由独立service持有。"""
from __future__ import annotations

from pathlib import Path
import threading

from src.services.ai_diagnostic_service import AiDiagnosticService
from src.services.ai_conversation_service import AiConversationService
from src.ui.ai_diagnostics_window import AiDiagnosticsWindow
from src.ui.ai_serial_bridge import AiSerialBridge


class AiAssistantController:
    def __init__(self, master, terminal, manager, targets, busy, forbidden_port, emit, manual_path,
                 background="#eef2f5", foreground="#17202a", context=None, shared_busy=None):
        self.master = master
        self.bridge = AiSerialBridge(terminal, manager, busy, forbidden_port)
        self.service = AiDiagnosticService(emit, self.bridge.acquire, self.bridge.read,
                                           self.bridge.busy, manual_path=manual_path)
        self.conversation = AiConversationService(self.service, context,
            (lambda target: self.bridge.call_ui(lambda: shared_busy(target))) if shared_busy else None,
            target_current=lambda target: (target in tuple(targets()) if threading.current_thread() is threading.main_thread()
                                           else self.bridge.call_ui(lambda: target in tuple(targets()))))
        self.service.conversation = self.conversation
        self.dialog = AiDiagnosticsWindow(master, self.service, targets, background, foreground,
                                          conversation=self.conversation)
        terminal.diagnostic_observer = self.service.observe_serial
        self.terminal = terminal
        self.closing = False
        self.closed = False
        self.after_id = master.after(50, self._poll)

    def open(self):
        if not self.closing:
            self.dialog.open()

    def observe(self, message):
        self.service.observe(message)

    def refresh_targets(self):
        if self.dialog.window is not None:
            self.dialog.refresh_targets()

    def _poll(self):
        self.after_id = None
        if not self.closed:
            self.bridge.poll()
            self.after_id = self.master.after(50, self._poll)

    def prepare_app_close(self):
        if self.closed:
            return True
        if not self.closing:
            self.closing = True
            self.dialog.begin_close()
            self.service.begin_close()
            self.service.emit("[AI诊断] 程序退出，等待采集清理及网络请求结束")
        if (not self.service.idle or self.dialog.background or self.service.worker_thread.is_alive()
                or self.service.event_thread.is_alive() or self.conversation.worker.is_alive()):
            return False
        self.closed = True
        self.bridge.close()
        if self.after_id:
            self.master.after_cancel(self.after_id)
        if self.dialog._poll_id:
            self.master.after_cancel(self.dialog._poll_id)
            self.dialog._poll_id = None
        if self.dialog.window is not None:
            self.dialog.window.destroy()
            self.dialog.window = None
        self.terminal.diagnostic_observer = None
        self.service.store.close()
        return True
