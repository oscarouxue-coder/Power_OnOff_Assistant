"""主窗口装配与主线程桥；诊断状态由独立service持有。"""
from __future__ import annotations

from pathlib import Path

from src.services.ai_diagnostic_service import AiDiagnosticService
from src.services.ai_conversation_service import AiConversationService
from src.ui.ai_diagnostics_window import AiDiagnosticsWindow
from src.ui.ai_serial_bridge import AiSerialBridge
from src.ui.ai_monitor_status import monitor_presentation


class AiAssistantController:
    def __init__(self, master, terminal, manager, targets, busy, forbidden_port, emit, manual_path,
                 background="#eef2f5", foreground="#17202a", context=None, shared_busy=None,
                 on_monitor_status=None, app_dir=None, project_config_path=None):
        self.master = master
        self.on_monitor_status = on_monitor_status
        self.monitor_snapshot = None
        self.targets_provider = targets
        self.remote = None
        self.project_lease = None
        self.remote_refresh = 0
        store = None
        remote_config = None
        if app_dir is not None:
            from src.services.dingtalk_remote_store import RemoteConfigStore
            from src.services.ai_store import DiagnosticStore
            remote_config = RemoteConfigStore(app_dir)
            if remote_config.load()["isolated"]:
                from src.core.dingtalk_stream import InstanceLease
                self.project_lease = InstanceLease("project:" + str(remote_config.directory.resolve()))
                self.project_lease.acquire()  # 打开数据库/初始化操作状态前就排除重复进程。
                store = DiagnosticStore(remote_config.directory)
        self.bridge = AiSerialBridge(terminal, manager, busy, forbidden_port)
        client = self.bridge.client
        self.bridge.dispatcher.handlers['shared_busy'] = lambda request: shared_busy(request.args[0]) if shared_busy else False
        self.bridge.dispatcher.handlers['target_current'] = lambda request: request.args[0] in tuple(targets())
        self.service = AiDiagnosticService(emit, client.acquire, client.read,
                                           client.busy, manual_path=manual_path, store=store)
        self.service.serial_status = client.serial_status
        self.service.target_current = client.target_current
        self.service.shared_busy = client.shared_busy if shared_busy else client.busy
        self.conversation = AiConversationService(self.service, context,
            client.shared_busy if shared_busy else None, target_current=client.target_current)
        self.service.conversation = self.conversation
        self.dialog = AiDiagnosticsWindow(master, self.service, targets, background, foreground,
                                          conversation=self.conversation)
        terminal.diagnostic_observer = self.service.serial_receiver
        self.terminal = terminal
        self.closing = False
        self.closed = False
        if store is not None and project_config_path is not None:
            from src.services.dingtalk_remote_service import DingTalkRemoteService
            self.remote = DingTalkRemoteService(self.conversation, remote_config, project_config_path, project_guarded=True)
            self.dialog.project_isolated = True
            if self.remote.config["enabled"]:
                try:
                    self.remote.start()
                except Exception as exc:
                    self.service.emit("[钉钉接入] 启动失败：" + str(exc))
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
            if getattr(self, "remote", None) is not None and not self.closing:
                self._refresh_remote_targets()
            snapshot = self.service.monitor_status()
            if snapshot != self.monitor_snapshot:
                previous = (monitor_presentation(self.monitor_snapshot)[0]
                            if self.monitor_snapshot is not None else None)
                self.monitor_snapshot = snapshot
                text = monitor_presentation(snapshot)[0]
                if text != previous:
                    self.service.emit("[AI监控] 状态更新：" + text)
                if self.on_monitor_status is not None:
                    self.on_monitor_status(snapshot)
                if self.dialog.window is not None:
                    self.dialog.monitor_panel.update_status(snapshot)
            self.after_id = self.master.after(50, self._poll)

    def _refresh_remote_targets(self):
        """主线程收集配置，后台接入不接触Tk变量，也不打开工作台。"""
        import time
        if time.monotonic() < self.remote_refresh:
            return
        self.remote_refresh = time.monotonic() + 1
        try:
            targets = tuple(self.targets_provider())
            profiles = self.service.store.profiles()
            current = self.service.profile
            if current is None:
                wanted = self.service.store.setting("selected_profile", "")
                current = next((p for p in profiles if p.id == wanted), profiles[0] if profiles else None)
            else:
                current = next((p for p in profiles if p.id == current.id), None)
            if current != self.service.profile or {t.channel: t for t in targets} != self.service.targets:
                self.service.configure(current, targets)
        except Exception:
            if self.service.targets:
                self.service.configure(self.service.profile, ())
            self.service.emit("[钉钉接入] 当前项目目标读取失败，暂停目标操作，请在本地检查配置")

    def prepare_app_close(self):
        if self.closed:
            return True
        if not self.closing:
            self.closing = True
            if self.remote is not None:
                self.remote.begin_close()
            self.dialog.begin_close()
            self.service.begin_close()
            self.service.emit("[AI诊断] 程序退出，等待采集清理及网络请求结束")
        if (not self.service.idle or self.dialog.background or self.service.worker_thread.is_alive()
                or self.service.event_thread.is_alive() or self.conversation.worker.is_alive()):
            return False
        if self.remote is not None and not self.remote.idle:
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
        if self.remote is not None:
            self.remote.close()
        self.service.store.close()
        if self.project_lease is not None:
            self.project_lease.close()
        return True
