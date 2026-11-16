"""主窗口装配与主线程桥；诊断状态由独立service持有。"""
from __future__ import annotations

from pathlib import Path
import os

from src.services.ai_diagnostic_service import AiDiagnosticService
from src.services.ai_conversation_service import AiConversationService
from src.ui.ai_diagnostics_window import AiDiagnosticsWindow
from src.ui.ai_serial_bridge import AiSerialBridge
from src.ui.ai_monitor_status import monitor_presentation


class AiAssistantController:
    def __init__(self, master, terminal, manager, targets, busy, forbidden_port, emit, manual_path,
                 background="#eef2f5", foreground="#17202a", context=None, shared_busy=None,
                 on_monitor_status=None, app_dir=None, project_config_path=None, remote_tab_factory=None, host_busy=None):
        self.master = master
        self.on_monitor_status = on_monitor_status
        self.monitor_snapshot = None
        self.targets_provider = targets
        self.remote = None
        self.feishu_remote = None
        self.project_lease = None
        self.gateway_runtime = None
        self.gateway_requested = False
        self.gateway_startup_error = False
        if app_dir is not None:
            from src.services.remote_instance_management import selected_gateway_slot
            try:
                gateway_slot = selected_gateway_slot(app_dir)
                self.gateway_requested = gateway_slot is not None
                if gateway_slot is not None:
                    from src.services.remote_gateway_runtime import RemoteGatewayRuntime
                    self.gateway_runtime = RemoteGatewayRuntime(app_dir, gateway_slot)
            except Exception:
                self.gateway_requested = self.gateway_startup_error = True
                emit("[多实例管理] 统一接入启动失败；未切换到直接接入，请在多实例管理页重新保存配置")
        self.remote_refresh = 0
        store = None
        remote_config = None
        feishu_config = None
        remote_values, feishu_values = None, None
        if app_dir is not None:
            from src.services.dingtalk_remote_store import RemoteConfigStore
            from src.services.feishu_remote_store import FeishuConfigStore
            from src.services.ai_store import DiagnosticStore
            remote_config = RemoteConfigStore(app_dir)
            feishu_config = FeishuConfigStore(app_dir)
            try:
                remote_values = remote_config.load()
            except ValueError:
                emit("[钉钉接入] 配置读取失败，该平台未启动（凭据省略）")
            try:
                feishu_values = feishu_config.load()
            except ValueError:
                emit("[飞书接入] 配置读取失败，该平台未启动（凭据省略）")
            if self.gateway_runtime is not None:
                store = self.gateway_runtime.open_store(app_dir, emit)
            elif not self.gateway_requested and ((remote_values and remote_values["isolated"]) or (feishu_values and feishu_values["isolated"])
                    or ((remote_config.path.exists() or feishu_config.path.exists())
                        and (remote_config.directory / "diagnostics.sqlite3").is_file())):
                from src.core.dingtalk_stream import InstanceLease
                self.project_lease = InstanceLease("project:" + str(remote_config.directory.resolve()))
                self.project_lease.acquire()  # 打开数据库/初始化操作状态前就排除重复进程。
                from src.services.ai_case_store import open_shared_cases
                store = DiagnosticStore(remote_config.directory, case_store=open_shared_cases(emit))
        self.bridge = AiSerialBridge(terminal, manager, busy, forbidden_port)
        client = self.bridge.client
        self.bridge.dispatcher.handlers['shared_busy'] = lambda request: shared_busy(request.args[0]) if shared_busy else False
        self.bridge.dispatcher.handlers['host_busy'] = lambda request: bool(host_busy()) if host_busy else False
        self.bridge.dispatcher.handlers['target_current'] = lambda request: request.args[0] in tuple(targets())
        self.service = AiDiagnosticService(emit, client.acquire, client.read,
                                           client.busy, manual_path=manual_path, store=store)
        self.service.serial_status = client.serial_status
        self.service.target_current = client.target_current
        self.service.shared_busy = client.shared_busy if shared_busy else client.busy
        self.service.host_busy = client.host_busy if host_busy else lambda: False
        self.conversation = AiConversationService(self.service, context,
            client.shared_busy if shared_busy else None, target_current=client.target_current)
        maintenance = vars(master).get('_source_maintenance_gate')
        self.service.maintenance = self.conversation.maintenance = maintenance
        self.conversation.router.maintenance = maintenance
        self.service.conversation = self.conversation
        self.capability_bridge = None
        if (app_dir is not None and hasattr(master, "channels") and hasattr(master, "serial_session_manager")
                and not self.gateway_startup_error
                and os.environ.get('LINECHECK_DISABLE_CAPABILITIES') != '1'):
            from src.ui.capability_ui_bridge import CapabilityUiBridge
            from src.services.capability_service import CapabilityService
            from src.services.ai_capability_adapter import AiCapabilityAdapter
            from src.services.ai_project_store import project_directory
            from src.services.firmware_upgrade_validation_service import inspect_upgrade_network
            self.capability_bridge = CapabilityUiBridge(master)
            data = self.capability_bridge.client
            business_directory = (self.gateway_runtime.identity.directory if self.gateway_runtime else project_directory(app_dir)) / "business"
            self.capabilities = CapabilityService(business_directory, manager,
                data.snapshot, data.admissible, lambda requests: inspect_upgrade_network(requests, emit), emit,
                released=data.released, tool_root=app_dir, onu_configuration=data.onu_snapshot, channel_commit=data.commit_channels,
                settings_commit=data.commit_settings)
            self.capabilities.maintenance = maintenance
            self.capability_bridge.channel_configuration = getattr(self.capabilities, 'channel_configuration', None)
            self.capability_bridge.settings_configuration = getattr(self.capabilities, 'settings', None)
            self.conversation.capabilities = AiCapabilityAdapter(self.conversation, self.capabilities)
            if 'ai_data' in self.capabilities.enabled_modules:
                from src.services.capability_ai_data_service import AiDataCapabilities
                self.capabilities.ai_data = AiDataCapabilities(self.capabilities, self.conversation)
            if 'extensions' in self.capabilities.enabled_modules:
                self.capabilities.extensions.restore()
            self.service.capability_runtime = self.capabilities
        elif app_dir is not None and os.environ.get('LINECHECK_DISABLE_CAPABILITIES') == '1':
            emit('[能力目录] 已按本机启动配置停用业务Agent接入；原GUI入口保持')
        self.instance_management = None
        if app_dir is not None:
            from src.services.remote_instance_management import RemoteInstanceManagement
            self.instance_management = RemoteInstanceManagement(app_dir, runtime=lambda: self.gateway_runtime,
                registry=lambda: getattr(getattr(self, 'capabilities', None), 'registry', None), emit=emit, maintenance=maintenance)
            self.instance_management.startup_error = self.gateway_startup_error
            if getattr(self, 'capabilities', None) is not None:
                self.instance_management.register_status(self.capabilities.registry)
        self.dialog = AiDiagnosticsWindow(master, self.service, targets, background, foreground,
            conversation=self.conversation, remote_tab_factory=remote_tab_factory,
            multi_instance_factory=self._multi_instance_panel if self.instance_management is not None else None)
        terminal.diagnostic_observer = self.service.serial_receiver
        self.terminal = terminal
        self.closing = False
        self.closed = False
        if self.gateway_runtime is not None:
            self.gateway_runtime.attach(self.conversation, project_config_path)
        if store is not None and project_config_path is not None and not self.gateway_requested:
            from src.services.dingtalk_remote_service import DingTalkRemoteService
            if remote_values is not None:
                try:
                    self.remote = DingTalkRemoteService(self.conversation, remote_config, project_config_path, project_guarded=True)
                except Exception:
                    self.service.emit("[钉钉接入] 服务初始化失败，该平台未启动（凭据省略）")
            if self.remote is not None and self.remote.config["enabled"]:
                try:
                    self.remote.start()
                except Exception as exc:
                    self.service.emit("[钉钉接入] 启动失败：" + str(exc))
            if feishu_values is not None:
                from src.services.feishu_remote_service import FeishuRemoteService
                try:
                    self.feishu_remote = FeishuRemoteService(self.conversation, feishu_config, project_config_path,
                                                             project_guarded=True)
                except Exception:
                    self.service.emit("[飞书接入] 服务初始化失败，该平台未启动（凭据省略）")
                if self.feishu_remote is not None and self.feishu_remote.config["enabled"]:
                    try:
                        self.feishu_remote.start()
                    except Exception:
                        self.service.emit("[飞书接入] 启动失败，请检查实例占用及配置（凭据省略）")
        if self.instance_management is not None:
            for remote in (self.remote, self.feishu_remote):
                if remote is not None:
                    remote.direct_admission = self.instance_management.host.ensure_direct_available
        self.after_id = master.after(50, self._poll)

    def _multi_instance_panel(self, parent):
        from src.ui.ai_multi_instance_tab import MultiInstanceTab
        return MultiInstanceTab(parent, self.instance_management)

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
            if getattr(self, "capability_bridge", None) is not None:
                self.capability_bridge.poll()
            if (getattr(self, "remote", None) is not None or getattr(self, "feishu_remote", None) is not None
                    or getattr(self, "gateway_runtime", None) is not None) and not self.closing:
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
            self.service.emit("[远程管理] 当前项目目标读取失败，暂停目标操作，请在本地检查配置")

    def prepare_app_close(self):
        if self.closed:
            return True
        capabilities = getattr(self, "capabilities", None)
        if capabilities is not None:
            capabilities.jobs.begin_close()
            if not capabilities.jobs.idle:
                return False
        if not self.closing:
            self.closing = True
            if getattr(self, 'instance_management', None) is not None:
                self.instance_management.begin_close()
            if getattr(self, "gateway_runtime", None) is not None:
                self.gateway_runtime.begin_close()
            if self.remote is not None:
                self.remote.begin_close()
            if getattr(self, "feishu_remote", None) is not None:
                self.feishu_remote.begin_close()
            self.dialog.begin_close()
            self.service.begin_close()
            self.service.emit("[AI诊断] 程序退出，等待采集清理及网络请求结束")
        if (not self.service.idle or self.dialog.background or self.service.worker_thread.is_alive()
                or self.service.event_thread.is_alive() or self.conversation.worker.is_alive()):
            return False
        if self.remote is not None and not self.remote.idle:
            return False
        if getattr(self, "feishu_remote", None) is not None and not self.feishu_remote.idle:
            return False
        if getattr(self, "gateway_runtime", None) is not None and not self.gateway_runtime.idle:
            return False
        if getattr(self, 'instance_management', None) is not None and not self.instance_management.idle:
            return False
        self.closed = True
        if capabilities is not None:
            observations = getattr(capabilities, 'observations', None)
            if observations is not None:
                observations.close_all()
            capabilities.jobs.close()
            self.capability_bridge.close()
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
        if getattr(self, "feishu_remote", None) is not None:
            self.feishu_remote.close()
        if getattr(self, "gateway_runtime", None) is not None:
            self.gateway_runtime.close()
        self.service.store.close()
        if self.project_lease is not None:
            self.project_lease.close()
        return True
