"""Main-thread project command/input adapter; file work stays in the service."""
from datetime import datetime
from importlib.util import find_spec
from pathlib import Path
import time
from weakref import ref
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMenu, QMessageBox, QToolBar, QToolButton
from shiboken6 import isValid
from src.models.workbench_presentation import LogView
from src.models.project_review import ReviewTarget
from src.services.qt_single_power import CAPABILITY as SINGLE_POWER
from src.services.qt_controlled_extensions import EXTENSION_OPERATIONS
from src.services.qt_workspace_adapter import (GATEWAY_OPERATIONS,
    PLATFORM_CONFIG_OPERATIONS, RECENT_CHANGES, QtWorkspaceAdapter)
# Load the updater's Requests dependency before the workspace worker can import it.
from src.ui.qt.app_update_dialog import AppUpdateController
from src.ui.qt.blocker_review import BlockerReview, show_warning
from src.ui.qt.log_presentation import project_live_log
from src.ui.qt.showcase_components import semantic_icon
from src.ui.qt.theme import assert_gui_thread
from src.ui.qt.window_placement import current_placement, restore_placement


class WorkspaceController(QObject):
    closing_changed = Signal(bool)
    _WORKSPACE_OWNERS = ('blocker_review', 'project_wizard', 'parameter_writer', 'onu_query',
                         'log_history', 'aging_history', 'channel_history', 'archived_logs',
                         'model_settings', 'ai_chat', 'app_update', 'feishu_repair')

    def __init__(self, window, source_root, *, directory=None, adapter=None, start_configured_gateway=False):
        super().__init__(window)
        self.window = window
        self.adapter = adapter or QtWorkspaceAdapter(source_root, directory=directory, display_log=project_live_log,
            start_configured_gateway=start_configured_gateway)
        self.blocker_review = BlockerReview(self)
        self.ready = False
        self.closing = False
        self._allow_close = False
        self._workspace_refs_released = False
        self._next_refresh = time.monotonic() + 1
        self._next_health = self._next_refresh - 1
        self._last_gui_poll = None
        self._gui_gap_peak = None
        self._log_batch_peak = 0
        self._preparing = set()
        self._prepare_requests = {}
        from src.ui.qt.project_wizard_controller import ProjectWizardController
        self.project_wizard = ProjectWizardController(self)
        self.pipeline_windows = {}
        self._pipeline_pending = {}
        self._pipeline_serial_seen = {}
        self.configuration_editors = {}
        self._configuration_requests = {}
        self._configuration_pending = set()
        self._inventory_request = None
        self.device_inventory_dialog = None
        self._recent_projects = ()
        self._imported_connection_request = None
        self._imported_connection_dialog = None
        self.instance_status_dialog = None
        self.remote_scope_dialog = None
        self.platform_configuration_dialog = None
        self.extensions_dialog = None
        self._log_export_pending = False
        self._single_power_request = None
        self._single_power_dialog = None
        self.serial_windows = {}
        self._serial_requests = {}
        self._serial_pending = set()
        self._serial_next_poll = time.monotonic()
        self.dut_windows = {}
        self._dut_requests = {}
        self._dut_next_poll = time.monotonic()
        self.upgrade_windows = {}
        self.job_serial_windows = {}
        self._job_serial_seen = {}
        self._job_serial_requests = {}
        self._upgrade_requests = {}
        self._upgrade_next_poll = time.monotonic()
        self.window._close_coordinator = self.request_close
        window.detail.resume_requested.connect(self.resume_channel)
        window.detail.power_log_requested.connect(self.open_power_log)
        window.resource_refresh_action.triggered.connect(self.refresh_resources)
        window.devices_action.triggered.connect(self.open_device_inventory)
        window.sidebar_devices_button.clicked.connect(lambda: self.open_device_inventory(refresh_initial=False))
        window.logs.export_requested.connect(self.export_logs)
        self.window.set_mode_message('正在加载项目服务…')
        self.window.dashboard.new_requested.connect(self.new_project)
        self.window.dashboard.open_requested.connect(self.open_project)
        self.window.dashboard.system_health.show()
        self.window.detail.start_button.clicked.connect(self.start_test)
        self.window.detail.test_type_panel.record_requested.connect(
            lambda project_id, values: self.submit('service_aging_record', project_id, values))
        self.window.detail.environment_button.clicked.connect(self.check_environment)
        self.window.detail.pipeline_button.clicked.connect(self.open_pipeline)
        self.window.detail.stop_button.clicked.connect(self.stop_test)
        self.window.detail.configuration_requested.connect(self.open_configuration)
        self.window.detail.channels_configuration_requested.connect(self.open_channels)
        self.window.detail.single_power_requested.connect(self.open_single_power)
        self.window.detail.serial_requested.connect(self.open_serial)
        self.window.detail.dut_requested.connect(self.open_dut)
        self.window.detail.upgrade_requested.connect(self.open_upgrade)
        from src.ui.qt.parameter_writer_controller import ParameterWriterController
        self.parameter_writer = ParameterWriterController(self)
        from src.ui.qt.onu_query_controller import OnuQueryController
        self.onu_query = OnuQueryController(self)
        from src.ui.qt.log_history_dialog import LogHistoryController
        self.log_history = LogHistoryController(self)
        from src.ui.qt.service_aging_history_dialog import AgingHistoryController
        self.aging_history = AgingHistoryController(self)
        window.detail.test_type_panel.history_requested.connect(self.aging_history.open)
        from src.ui.qt.channel_history_dialog import ChannelHistoryController
        self.channel_history = ChannelHistoryController(self)
        window.detail.channel_history_requested.connect(self.channel_history.open)
        from src.ui.qt.archived_logs_dialog import ArchivedLogsController
        self.archived_logs = ArchivedLogsController(self)
        from src.ui.qt.model_settings_controller import ModelSettingsController
        self.model_settings = ModelSettingsController(self)
        window.model_settings_action.triggered.connect(self.model_settings.open)
        window.detail.model_settings_requested.connect(self.model_settings.open)
        from src.ui.qt.ai_chat_controller import AiChatController
        self.ai_chat = AiChatController(self)
        window.ai_chat_action.triggered.connect(self.ai_chat.open)
        window.detail.ai_chat_requested.connect(self.ai_chat.open)
        self.app_update = AppUpdateController(self, source_root)
        from src.ui.qt.feishu_repair_dialog import FeishuRepairController
        self.feishu_repair = FeishuRepairController(self)
        settings = window.settings_action.menu()
        self.update_action = settings.addAction('检查更新…', self.app_update.open)
        self.extensions_action = settings.addAction('受控扩展…', self.open_extensions)
        self.feishu_repair_action = settings.addAction('安装飞书 SDK…', self.feishu_repair.open)
        self.feishu_repair_action.setVisible(find_spec('lark_oapi') is None)
        self.platform_settings_menu = settings.addMenu('机器人应用配置')
        self.platform_settings_menu.addAction('钉钉应用配置…', lambda: self.open_platform_configuration('dingtalk'))
        self.platform_settings_menu.addAction('飞书应用配置…', lambda: self.open_platform_configuration('feishu'))
        window.sidebar_settings_button.setMenu(settings)
        menu = QMenu(window)
        self.new_action = menu.addAction('新建项目…', self.new_project)
        self.open_action = menu.addAction('打开项目…', self.open_project)
        self.setup_action = menu.addAction('项目向导…', self.open_project_setup)
        self.recent_menu = menu.addMenu('最近项目')
        self.recent_menu.setToolTipsVisible(True)
        self.recent_menu.aboutToShow.connect(self._populate_recent_menu)
        self.import_action = menu.addAction('导入旧配置目录…', self.import_legacy_project)
        self.imported_connection_action = menu.addAction('选择导入的接入配置…', self.open_imported_connections)
        self.remote_scope_action = menu.addAction('远程可访问项目…', self.open_remote_scope)
        settings.addAction(self.remote_scope_action)
        self.instance_status_action = settings.addAction('多实例接入状态…', self.open_instance_status)
        menu.addAction(self.instance_status_action)
        menu.addSeparator()
        self.save_action = menu.addAction('保存当前项目', self.save_project)
        for action, key in ((self.new_action, QKeySequence.StandardKey.New),
                            (self.open_action, QKeySequence.StandardKey.Open),
                            (self.save_action, QKeySequence.StandardKey.Save)):
            action.setShortcut(QKeySequence(key))
            window.addAction(action)
        self.rename_action = menu.addAction('重命名…', self.rename_project)
        self.duplicate_action = menu.addAction('另存为独立项目…', self.duplicate_project)
        self.directory_action = menu.addAction('打开项目目录', self.open_project_directory)
        self.history_action = menu.addAction('任务历史…', self.log_history.open)
        self.archived_logs_action = menu.addAction('归档日志…', self.archived_logs.open)
        history_menu = QMenu(window.history_button)
        history_menu.addAction(self.history_action)
        history_menu.addAction(self.archived_logs_action)
        history_menu.aboutToShow.connect(self._sync_actions)
        window.history_button.setMenu(history_menu)
        self.close_action = menu.addAction('关闭当前项目', self.close_project)
        self.forget_recent_action = menu.addAction('从最近列表移除', self.forget_recent_project)
        menu.setTitle('项目' if window._refreshed else '项目 ▾')
        toolbar = window.findChild(QToolBar, 'GlobalHeader')
        toolbar.addAction(menu.menuAction())
        menu_button = toolbar.widgetForAction(menu.menuAction())
        self.project_menu_button = menu_button
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if window._refreshed:
            menu.setIcon(semantic_icon('projects', '#DDECEF', on_dark=True))
            menu_button.setIconSize(window.settings_button.iconSize())
            menu_button.setAccessibleName('项目')
        window.project_management_button.setMenu(menu)
        menu.aboutToShow.connect(self._sync_actions)
        window.navigation.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        window.navigation.customContextMenuRequested.connect(self.project_menu)
        self.menu = menu
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self._sync_actions()
        owner = ref(self)

        def after_window_destroyed(*_):
            def release():
                controller = owner()
                if controller is not None:
                    controller._release_destroyed_workspace()
            # QWidget.destroyed is emitted before all of its children have
            # been destroyed; never detach a child reference in that signal.
            if QCoreApplication.instance() is not None and not QCoreApplication.closingDown():
                QTimer.singleShot(0, release)

        window.destroyed.connect(after_window_destroyed)

    def _terminal_shutdown_complete(self):
        if (not self.closing or not self._allow_close or not self.adapter.closed.is_set()
                or self.adapter.thread.is_alive() or self.app_update.worker.pending_work):
            return False
        service = getattr(self.adapter, '_service', None)
        writer = self.adapter._log_writer
        return (getattr(service, '_closed', False) and
                writer.report is None and writer.associate is None)

    def _release_destroyed_workspace(self):
        """Only the dead Qt object graph may lose its Python owner backrefs."""
        if self._workspace_refs_released:
            return True
        if (not self._terminal_shutdown_complete() or isValid(self.window)
                or isValid(self) or isValid(self.timer)):
            return False
        for name in self._WORKSPACE_OWNERS:
            child = getattr(self, name)
            if child.workspace is self:
                child.workspace = None
        self._workspace_refs_released = True
        return True

    def dispose_closed_window(self):
        """Finalize a successful workspace close after the application loop exits."""
        if self._workspace_refs_released:
            return True
        if not self._terminal_shutdown_complete():
            return False
        if isValid(self.window):
            if self.window.isVisible():
                return False
            self.window.deleteLater()
            # The main event loop has ended. Deliver only this closed window's
            # deferred deletion, not arbitrary queued application events.
            QCoreApplication.sendPostedEvents(self.window, QEvent.Type.DeferredDelete)
        return self._release_destroyed_workspace()

    def open_instance_status(self):
        if not self.ready or self.closing:
            return
        if self.instance_status_dialog is None:
            from src.ui.qt.instance_status_dialog import InstanceStatusDialog
            self.instance_status_dialog = InstanceStatusDialog(self)
            self.instance_status_dialog.finished.connect(lambda _: setattr(self, 'instance_status_dialog', None))
        self.instance_status_dialog.showNormal()
        self.instance_status_dialog.raise_()
        self.instance_status_dialog.refresh()

    def open_remote_scope(self):
        if self.closing or not self.ready:
            return
        if self.remote_scope_dialog is None:
            from src.ui.qt.remote_project_scope import RemoteProjectScopeDialog
            self.remote_scope_dialog = RemoteProjectScopeDialog(self)
            self.remote_scope_dialog.finished.connect(lambda _: setattr(self, 'remote_scope_dialog', None))
        self.remote_scope_dialog.showNormal()
        self.remote_scope_dialog.raise_()
        self.remote_scope_dialog.refresh()

    def open_extensions(self):
        project = self._current()
        if project is None or self.closing or not self.ready:
            return
        if self.extensions_dialog is None:
            from src.ui.qt.controlled_extensions_dialog import ControlledExtensionsDialog
            dialog = ControlledExtensionsDialog(self, project)
            self.extensions_dialog = dialog
            dialog.finished.connect(lambda _: setattr(self, 'extensions_dialog', None))
        self.extensions_dialog.showNormal()
        self.extensions_dialog.raise_()

    def open_platform_configuration(self, kind):
        project = self._current()
        if project is None or self.closing or not self.ready:
            return
        if self.platform_configuration_dialog is None:
            from src.ui.qt.platform_configuration_dialog import PlatformConfigurationDialog
            dialog = PlatformConfigurationDialog(self, project, kind)
            self.platform_configuration_dialog = dialog
            dialog.finished.connect(lambda _: setattr(self, 'platform_configuration_dialog', None))
        self.platform_configuration_dialog.showNormal()
        self.platform_configuration_dialog.raise_()

    def _current(self):
        return next((p for p in self.window.projects if p.project_id == self.window.selected_project), None)

    def _sync_actions(self):
        allowed = self.ready and not self.closing
        self.feishu_repair_action.setEnabled(allowed)
        self.window.dashboard.new_button.setEnabled(allowed)
        self.window.dashboard.open_button.setEnabled(allowed)
        self.new_action.setEnabled(allowed)
        self.open_action.setEnabled(allowed)
        self.recent_menu.setEnabled(allowed)
        self.import_action.setEnabled(allowed)
        self.imported_connection_action.setEnabled(allowed and self._imported_connection_request is None)
        self.instance_status_action.setEnabled(allowed)
        self.remote_scope_action.setEnabled(allowed)
        self.window.resource_refresh_action.setEnabled(allowed and self._inventory_request is None)
        self.window.devices_action.setEnabled(allowed)
        self.window.sidebar_devices_button.setEnabled(allowed)
        self.window.settings_action.setEnabled(allowed)
        self.window.sidebar_settings_button.setEnabled(allowed)
        self.window.project_management_button.setEnabled(allowed)
        self.window.history_button.setEnabled(allowed)
        self.window.logs.set_export_enabled(allowed and not self._log_export_pending)
        self.log_history.set_export_enabled(allowed and not self._log_export_pending)
        self.archived_logs.set_export_enabled(allowed and not self._log_export_pending)
        self.history_action.setEnabled(allowed and self._current() is not None)
        self.archived_logs_action.setEnabled(allowed)
        for action in (self.save_action, self.rename_action, self.duplicate_action, self.close_action, self.forget_recent_action):
            action.setEnabled(allowed and self._current() is not None)
        project = self._current()
        self.platform_settings_menu.setEnabled(bool(allowed and project))
        self.extensions_action.setEnabled(bool(allowed and project))
        self.setup_action.setEnabled(bool(allowed and project))
        self.directory_action.setEnabled(allowed and project is not None)
        for action in self.window.detail.power_log_actions.values():
            action.setEnabled(bool(allowed and project))
        self.window.detail.tabs.setTabEnabled(2, bool(allowed and project))
        self.window.detail.tabs.setTabToolTip(2, '本项目样机升级与固件预检')
        self.window.detail.tabs.setTabEnabled(3, bool(allowed and project))
        self.window.detail.tabs.setTabToolTip(3, '本项目参数表预检与批量写样机参数')
        self.window.detail.tabs.setTabEnabled(4, bool(allowed and project))
        self.window.detail.tabs.setTabToolTip(4, 'C300/C600 项目配置与 ONU 查询')
        self.window.detail.tabs.setTabEnabled(5, bool(allowed and project))
        self.window.detail.tabs.setTabToolTip(5, '当前项目串口监控；打开窗口不自动打开COM')
        self.window.detail.tabs.setTabEnabled(6, bool(allowed and project))
        self.window.detail.tabs.setTabToolTip(6, 'DUT Telnet、WAN、2.4G/5G WiFi、语音和TR069配置/查询')
        self.window.detail.tabs.setTabEnabled(7, bool(allowed and project))
        self.window.detail.tabs.setTabToolTip(7, '当前项目的模型账号、协议和连接测试')
        self.window.model_settings_action.setEnabled(bool(allowed and project))
        self.window.detail.tabs.setTabEnabled(8, bool(allowed and project))
        self.window.detail.tabs.setTabToolTip(8, '本机普通问答与项目会话历史')
        self.window.ai_chat_action.setEnabled(bool(allowed and project))
        idle = project is not None and not project.active_task_count and not project.editor_open
        for action in (self.save_action, self.rename_action, self.duplicate_action):
            action.setEnabled(allowed and idle)
        ready_to_start = bool(allowed and project and project.project_id not in self._preparing
            and project.project_id not in self._configuration_pending)
        can_start = bool(ready_to_start and project.can_start)
        self.window.detail.tabs.setTabEnabled(1, can_start and self._single_power_request is None)
        self.window.detail.tabs.setTabToolTip(1, '选择电源端口和动作，执行一次上电或下电')
        self.window.detail.start_button.setEnabled(bool(ready_to_start and (project.can_start or project.parallel_power_available)))
        self.window.detail.environment_button.setEnabled(can_start)
        self.window.detail.pipeline_button.setEnabled(bool(allowed and project))
        for identifier, dialog in self.pipeline_windows.items():
            row = next((item for item in self.window.projects if item.project_id == identifier), None)
            dialog.set_availability(bool(allowed and row and row.can_start and identifier not in self._preparing
                and identifier not in self._configuration_pending and identifier not in self._pipeline_pending.values()))
            dialog.feedback.setText(row.pipeline_detail if row else '')
        self.window.detail.stop_button.setEnabled(bool(allowed and project and project.can_stop))
        edit = getattr(self.window.detail, 'edit_button', None)
        if edit is not None:
            edit.setEnabled(bool(allowed and project and project.can_configure and project.editor_kind != 'channels'))
        self.window.detail.channel_edit_button.setEnabled(bool(allowed and project and project.can_configure
            and project.editor_kind != 'configuration'))
        for row in self.window.projects:
            dialog = self.configuration_editors.get(row.project_id)
            if dialog is not None and getattr(dialog, 'editor_kind', '') == 'configuration':
                dialog.show_pretest(row.pretest_run)
                dialog.set_version_channels(row.channels)
                dialog.show_version_query(row.version_query)
                dialog.show_push_trial(row.push_trial)

    def open_upgrade(self):
        project = self._current()
        if not self.ready or self.closing or project is None:
            return
        dialog = self.upgrade_windows.get(project.project_id)
        if dialog is not None:
            dialog.showNormal()
            dialog.raise_()
        elif not any(key == project.project_id for key, _ in self._upgrade_requests.values()):
            self._upgrade_submit(project.project_id, 'show', {})

    def _upgrade_submit(self, identifier, suffix, arguments):
        dialog = self.upgrade_windows.get(identifier)
        if suffix == 'stop':
            accepted = QMessageBox.question(dialog, '请求安全停止', '向原升级任务请求安全停止？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
            if not accepted or self.closing:
                if dialog is not None:
                    dialog.set_busy(self.closing)
                return
        request = self.submit('upgrade_' + suffix, identifier, arguments)
        if request is not None:
            self._upgrade_requests[request] = (identifier, suffix)
        elif dialog is not None and suffix != 'poll':
            dialog.detaching = False
            dialog.set_busy(False)
            dialog.feedback.setText('升级操作未提交，请稍后重试')

    def _upgrade_result(self, result, identifier, suffix):
        dialog = self.upgrade_windows.get(identifier)
        if result.error:
            if suffix != 'poll':
                if dialog is not None:
                    dialog.detaching = False
                    dialog.set_busy(False)
                    dialog.feedback.setText(result.error)
                if suffix == 'show':
                    self.blocker_review.finish(identifier, 'upgrade', None)
                self.blocker_review.warning(result, '升级操作未完成', dialog, identifier)
            return
        if suffix == 'show' and dialog is None and not self.closing:
            from src.ui.qt.firmware_upgrade_dialog import FirmwareUpgradeDialog
            dialog = FirmwareUpgradeDialog(result.payload, self.window)
            self.bind_module_window(dialog, identifier, 'sample_upgrade')
            dialog.command_requested.connect(lambda action, values, key=identifier: self._upgrade_submit(key, action, values))
            self.upgrade_windows[identifier] = dialog
            def finished(_):
                if self.upgrade_windows.get(identifier) is dialog:
                    self.upgrade_windows.pop(identifier)
                dialog.deleteLater()
            dialog.finished.connect(finished)
            dialog.show()
            self.blocker_review.finish(identifier, 'upgrade', dialog)
        if dialog is None or self.closing:
            return
        if suffix == 'preview':
            preview = result.payload
            manual = preview['manual_restart']
            if manual:
                from src.ui.qt.firmware_upgrade_dialog import confirm_manual_restart
                accepted = confirm_manual_restart(dialog, preview['summary'])
            else:
                accepted = QMessageBox.question(dialog, '确认升级目标及固件适配', preview['summary'],
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
            if not self.closing and self.upgrade_windows.get(identifier) is dialog:
                fields = dict(token=dialog.token)
                if accepted:
                    fields['confirmation'] = preview['confirmation']
                    if manual:
                        fields['manual_restart_confirmed'] = True
                self._upgrade_submit(identifier, 'execute' if accepted else 'cancel', fields)
            return
        if suffix == 'detach':
            dialog.allow_close = True
            dialog.close()
            return
        if suffix in ('show', 'poll', 'execute', 'stop'):
            dialog.apply_snapshot(result.payload)
        if suffix != 'poll':
            dialog.set_busy(False)
        if suffix == 'cancel':
            dialog.feedback.setText('已取消，未启动升级')
        elif suffix == 'save':
            dialog.saved()

    def _job_serial_result(self, result, identifier, kind, batch):
        if self.closing or result.error:
            return
        snapshot = result.payload
        if snapshot['batch'] != batch:
            return
        dialog = self.job_serial_windows.get(identifier)
        if snapshot['closed']:
            if dialog is not None and dialog.batch == batch:
                dialog.close()
            return
        project = next((item for item in self.window.projects if item.project_id == identifier), None)
        if project is None or project.serial_observation != (kind, batch):
            return
        if dialog is None:
            if self._job_serial_seen.get(identifier) == batch:
                return
            from src.ui.qt.serial_observation_dialog import SerialObservationDialog
            title = {'upgrade': '升级', 'parameter': '写参'}[kind]
            dialog = SerialObservationDialog(project.name, batch, title, self.window)
            self.job_serial_windows[identifier] = dialog
            self._job_serial_seen[identifier] = batch
            def finished(_):
                if self.job_serial_windows.get(identifier) is dialog:
                    self.job_serial_windows.pop(identifier)
                dialog.deleteLater()
            dialog.finished.connect(finished)
            dialog.apply_snapshot(snapshot)
            dialog.show()
        elif dialog.batch == batch:
            dialog.apply_snapshot(snapshot)

    def _poll_job_serial(self, projects):
        pending = {key for key, _, _ in self._job_serial_requests.values()}
        for project in projects:
            key = project.project_id
            kind, batch = project.serial_observation
            dialog = self.job_serial_windows.get(key)
            if batch and key not in pending and (dialog or self._job_serial_seen.get(key) != batch):
                fields = dict(batch=batch, active=dialog.active if dialog else '')
                request = self.submit(kind + '_logs', key, fields)
                if request is not None:
                    self._job_serial_requests[request] = (key, kind, batch)

    def open_dut(self):
        project = self._current()
        if not self.ready or self.closing or project is None:
            return
        dialog = self.dut_windows.get(project.project_id)
        if dialog is not None:
            dialog.showNormal()
            dialog.raise_()
        elif not any(item[0] == project.project_id for item in self._dut_requests.values()):
            self._dut_submit(project.project_id, 'show', {})

    def _remember_tool_windows(self, identifier):
        for window, dialogs in (('serial', self.serial_windows), ('dut', self.dut_windows)):
            dialog = dialogs.get(identifier)
            if dialog is not None:
                heights = dialog.status_heights if window == 'dut' else None
                self.adapter.remember_window_placement(identifier, window, current_placement(dialog), status_heights=heights)
        for window, dialogs in (('sample_upgrade', self.upgrade_windows), ('pipeline', self.pipeline_windows),
                                ('sample_parameter_writer', self.parameter_writer.windows),
                                ('onu_registration', self.onu_query.windows)):
            dialog = dialogs.get(identifier)
            if dialog is not None:
                self.adapter.remember_window_placement(identifier, window, current_placement(dialog))
        history = self.channel_history.dialog
        if history is not None and history.target[0] == identifier:
            self.adapter.remember_window_placement(identifier, 'power_test_channel_history', current_placement(history))

    def bind_module_window(self, dialog, identifier, module):
        restore_placement(dialog, self.adapter.module_window_placement(identifier, module))
        dialog.finished.connect(lambda _: self.adapter.remember_window_placement(identifier, module, current_placement(dialog)))

    def _dut_submit(self, identifier, suffix, arguments):
        request = self.submit('dut_' + suffix, identifier, arguments)
        if request is not None:
            self._dut_requests[request] = (identifier, suffix)
        else:
            dialog = self.dut_windows.get(identifier)
            if dialog is not None:
                dialog.set_busy(False)
                dialog.feedback.setText('DUT操作未提交，请稍后重试')

    def _dut_result(self, result, identifier, suffix):
        dialog = self.dut_windows.get(identifier)
        if result.error:
            if dialog is not None:
                if suffix != 'poll':
                    dialog.set_busy(False)
                dialog.detaching = False
                dialog.feedback.setText(result.error)
            if suffix != 'poll':
                if suffix == 'show':
                    self.blocker_review.finish(identifier, 'dut', None)
                self.blocker_review.warning(result, 'DUT操作未完成', dialog, identifier)
            return
        if suffix == 'show' and dialog is None and not self.closing:
            from src.ui.qt.dut_configuration_dialog import DutConfigurationDialog
            dialog = DutConfigurationDialog(result.payload, self.window)
            dialog.command_requested.connect(lambda action, values, key=identifier: self._dut_submit(key, action, values))
            dialog.status_heights_changed.connect(lambda heights, key=identifier:
                self.adapter.remember_window_placement(key, 'dut', status_heights=heights))
            self.dut_windows[identifier] = dialog
            self.parameter_writer.bind_dut(identifier, dialog)
            def finished(_):
                if self.dut_windows.get(identifier) is dialog:
                    self.adapter.remember_window_placement(identifier, 'dut', current_placement(dialog),
                                                           status_heights=dialog.status_heights)
                    self.dut_windows.pop(identifier)
                    self.parameter_writer.sync_login_editability(identifier)
                dialog.deleteLater()
            dialog.finished.connect(finished)
            restore_placement(dialog, result.payload['placement'])
            dialog.show()
            self.blocker_review.finish(identifier, 'dut', dialog)
        if dialog is None:
            return
        if suffix == 'preview':
            preview = result.payload
            accepted = QMessageBox.question(dialog, '确认DUT目标与操作', preview['summary'],
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
            if not self.closing and self.dut_windows.get(identifier) is dialog:
                self._dut_submit(identifier, 'execute' if accepted else 'cancel', dict(token=dialog.token,
                    **({'confirmation': preview['confirmation']} if accepted else {})))
            return
        if suffix == 'detach':
            dialog._allow_close = True
            dialog.close()
            return
        if suffix in ('show', 'poll', 'execute', 'stop'):
            dialog.apply_snapshot(result.payload)
        if suffix != 'poll':
            dialog.set_busy(False)
        if suffix == 'cancel':
            dialog.feedback.setText('已取消，未启动DUT操作')

    def open_serial(self):
        project = self._current()
        if not self.ready or self.closing or project is None:
            return
        dialog = self.serial_windows.get(project.project_id)
        if dialog is not None:
            dialog.showNormal()
            dialog.raise_()
            # Add newly selected tabs without disturbing active sessions.
        if not any(item[0] == project.project_id and item[1] != 'poll' for item in self._serial_requests.values()):
            self._serial_submit(project.project_id, 'show', {})

    def _serial_submit(self, identifier, suffix, arguments):
        request = self.submit('serial_' + suffix, identifier, arguments)
        if request is not None:
            self._serial_requests[request] = (identifier, suffix, arguments)
            self._serial_pending.add(identifier)
        else:
            dialog = self.serial_windows.get(identifier)
            if dialog is not None:
                dialog.set_busy(False)
                dialog.feedback.setText('串口操作未提交，请稍后重试')

    def _serial_result(self, result, identifier, suffix, arguments):
        if not any(request[0] == identifier for request in self._serial_requests.values()):
            self._serial_pending.discard(identifier)
        dialog = self.serial_windows.get(identifier)
        if suffix == 'diagnostics':
            if dialog is None or dialog.token != arguments['token']:
                return
            view = dialog.views.get(arguments['target'])
            if self.closing or dialog.detaching or not view or view['port'] != arguments['port']:
                dialog.set_busy(False)
                return
        if result.error:
            if dialog is not None:
                dialog.detaching = False
                if suffix != 'poll':
                    dialog.set_busy(False)
                dialog.feedback.setText(result.error)
            if suffix != 'poll':
                if suffix == 'show':
                    self.blocker_review.finish(identifier, 'serial', None)
                self.blocker_review.warning(result, '串口操作未完成', dialog, identifier)
            return
        if suffix == 'show' and dialog is None and not self.closing:
            from src.ui.qt.serial_terminal_dialog import SerialTerminalDialog
            dialog = SerialTerminalDialog(result.payload)
            dialog.command_requested.connect(lambda action, values, key=identifier: self._serial_submit(key, action, values))
            dialog.window_state_changed.connect(lambda state, key=identifier, name=result.payload['project_name']:
                self.adapter.record_serial_window_state(key, name, state))
            self.serial_windows[identifier] = dialog
            dialog.finished.connect(lambda _, key=identifier, view=dialog: self._serial_finished(key, view))
            restore_placement(dialog, result.payload['placement'], reference_window=self.window)
            dialog.show()
            self.blocker_review.finish(identifier, 'serial', dialog)
        if dialog is None:
            return
        if suffix == 'preview_send':
            preview = result.payload
            accepted = not preview['dangerous'] or QMessageBox.question(dialog, '确认危险命令', preview['summary'],
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
            if self.closing or self.serial_windows.get(identifier) is not dialog:
                return
            if accepted:
                dialog._sending_target = arguments['target']
                self._serial_submit(identifier, 'send', dict(token=dialog.token, confirmation=preview['confirmation']))
            else:
                self._serial_submit(identifier, 'cancel', dict(token=dialog.token))
            return
        if suffix == 'diagnostics':
            dialog.show_diagnostics(result.payload)
        elif suffix == 'send':
            view = dialog.views.get(getattr(dialog, '_sending_target', ''))
            if view is not None:
                view['input'].clear()
            dialog.feedback.setText('发送完成')
        elif suffix == 'cancel':
            dialog.feedback.setText('取消关闭 ' + arguments['target'] if arguments.get('target') else '已取消，未发送字符')
        elif suffix == 'directory':
            dialog.path.setText(result.payload['log_dir'])
        elif suffix in ('show', 'poll', 'open_all', 'stop_all', 'detach', 'close_tab'):
            dialog.apply_snapshot(result.payload)
        if suffix != 'poll':
            dialog.set_busy(False)

    def _serial_finished(self, identifier, dialog):
        if self.serial_windows.get(identifier) is dialog:
            self.adapter.remember_window_placement(identifier, 'serial', current_placement(dialog))
            self.serial_windows.pop(identifier, None)
        dialog.deleteLater()

    def _configuration_submit(self, operation, identifier, arguments=None):
        request = self.submit(operation, identifier, arguments or {})
        if request is not None:
            self._configuration_requests[request] = (identifier, operation)
            if operation in ('configuration_open', 'channels_editor_open'):
                self._configuration_pending.add(identifier)
        else:
            dialog = self.configuration_editors.get(identifier)
            if dialog is not None and operation == 'configuration_checkpoint':
                dialog.feedback.setText('恢复草稿暂未写入，请稍后编辑重试')
            elif dialog is not None:
                dialog.set_busy(False)
                dialog.feedback.setText('配置操作暂未提交，请稍后重试')
        self._sync_actions()
        return request

    def open_device_inventory(self, *, refresh_initial=True):
        if not self.ready or self.closing:
            return
        if self.device_inventory_dialog is None:
            from src.ui.qt.device_inventory_dialog import DeviceInventoryDialog
            self.device_inventory_dialog = DeviceInventoryDialog(self.window, self.refresh_resources)
            self.device_inventory_dialog.finished.connect(self._device_inventory_closed)
            inventory, _ = self.adapter.device_inventory_snapshot()
            if refresh_initial and inventory.ports_at is None and inventory.adapters_at is None:
                self.refresh_resources()
            self._show_device_inventory()
        self.device_inventory_dialog.showNormal()
        self.device_inventory_dialog.raise_()

    def _device_inventory_closed(self, _result):
        self.device_inventory_dialog = None

    def _show_device_inventory(self):
        dialog = self.device_inventory_dialog
        if dialog is not None:
            if self.closing:
                dialog.close()
            else:
                inventory, leases = self.adapter.device_inventory_snapshot()
                dialog.update_inventory(inventory, leases, self.window.projects, self._inventory_request is not None)

    def refresh_resources(self):
        if not self.ready or self.closing or self._inventory_request is not None:
            return
        self._inventory_request = self.submit('refresh_inventory')
        if self._inventory_request is not None:
            self.window.statusBar().showMessage('正在读取本机串口和网卡…')
            for editor in self.configuration_editors.values():
                if editor.editor_kind == 'channels':
                    editor.set_resources_refreshing(True)
        self._sync_actions()
        self._show_device_inventory()

    def export_logs(self, entries, description, parent=None):
        if not self.ready or self.closing or self._log_export_pending:
            return
        self._log_export_pending = True
        self._sync_actions()
        name = 'DUTPilot-日志-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.txt'
        path, _ = QFileDialog.getSaveFileName(parent or self.window, '导出当前筛选日志', name, '文本日志 (*.txt)',
            options=QFileDialog.Option.DontConfirmOverwrite)
        if path and not self.closing:
            if not Path(path).suffix:
                path += '.txt'
            if self.submit('export_logs', path, description, entries) is not None:
                return
        self._log_export_pending = False
        self._sync_actions()

    def _inventory_finished(self, result):
        if result.identifier != self._inventory_request:
            return
        self._inventory_request = None
        if self.closing:
            return
        for editor in self.configuration_editors.values():
            if editor.editor_kind == 'channels':
                editor.finish_resources(result.payload, result.error)
        message = result.error
        if result.payload is not None:
            message = '；'.join(result.payload['errors']) or '串口/网卡候选已更新'
            if self._single_power_dialog is not None:
                self._single_power_dialog.update_inventory(result.payload['ports'])
        self.window.statusBar().showMessage(message, 7000)

    def open_configuration(self):
        self._open_editor('configuration')

    def open_channels(self):
        self._open_editor('channels')

    def _open_editor(self, kind):
        project = self._current()
        if project is None or not self.ready or self.closing:
            return
        dialog = self.configuration_editors.get(project.project_id)
        if dialog is not None:
            if getattr(dialog, 'editor_kind', 'configuration') != kind:
                field = 'enabled' if kind == 'channels' else 'runtime'
                self.blocker_review.status('请先保存或关闭当前项目的另一个配置窗口', project.project_id,
                                           ReviewTarget(kind, field))
                return
            dialog.showNormal()
            dialog.raise_()
            return
        if project.can_configure and project.project_id not in self._configuration_pending:
            self._configuration_submit('configuration_open' if kind == 'configuration' else 'channels_editor_open', project.project_id)

    def _configuration_result(self, result, identifier, operation):
        dialog = self.configuration_editors.get(identifier)
        if operation in ('configuration_close', 'channels_editor_close'):
            self.blocker_review.editor_closed(identifier, not result.error)
            if not result.error:
                return
        opening = operation in ('configuration_open', 'channels_editor_open')
        kind = 'channels' if operation.startswith('channels_editor_') else 'configuration'
        if operation == 'configuration_checkpoint':
            if dialog is not None and dialog.dirty and not dialog.busy:
                if result.error:
                    dialog.feedback.setText(result.error)
                elif dialog.feedback.text() == '有未保存的修改':
                    dialog.feedback.setText('恢复草稿已保存，正式配置待提交')
            return
        if opening:
            self._configuration_pending.discard(identifier)
        if result.error:
            if dialog is not None:
                dialog.set_busy(False)
                dialog.feedback.setText(result.error)
            if opening or operation == 'configuration_reload':
                self.blocker_review.finish(identifier, kind, dialog if not opening else None)
            self.blocker_review.warning(result, '配置操作未完成', dialog, identifier)
            return
        if opening:
            if self.closing:
                return
            draft = result.payload
            if operation == 'configuration_open':
                from src.ui.qt.configuration_dialog import ConfigurationDialog
                dialog = ConfigurationDialog(draft, self.window)
                self.bind_module_window(dialog, identifier, 'test_item_config')
                kind, save_op, reload_op = 'configuration', 'configuration_save', 'configuration_reload'
                dialog.checkpoint_requested.connect(lambda values, key=identifier: self._configuration_submit('configuration_checkpoint', key, values))
                dialog.defaults_requested.connect(lambda values, key=identifier: self._configuration_submit('configuration_defaults', key, values))
                dialog.wifi_interfaces_requested.connect(lambda values, key=identifier: self._configuration_submit('configuration_wifi_interfaces', key, values))
                dialog.pretest_requested.connect(lambda values, key=identifier: self._configuration_submit('configuration_pretest_preview', key, values))
                dialog.pretest_stop_requested.connect(lambda values, key=identifier: self._configuration_submit('configuration_pretest_stop', key, values))
                dialog.version_requested.connect(lambda values, key=identifier: self._configuration_submit('configuration_version_preview', key, values))
                dialog.push_trial_requested.connect(lambda values, key=identifier: self._configuration_submit('configuration_push_preview', key, values))
            else:
                from src.ui.qt.channel_configuration_dialog import ChannelConfigurationDialog
                dialog = ChannelConfigurationDialog(draft, self.window)
                kind, save_op, reload_op = 'channels', 'channels_editor_preview', 'channels_editor_reload'
                dialog.resources_requested.connect(self.refresh_resources)
                dialog.rename_requested.connect(lambda values, key=identifier: self._configuration_submit(
                    'channels_editor_rename_preview', key, values))
            dialog.editor_kind = kind
            self.configuration_editors[identifier] = dialog
            dialog.save_requested.connect(lambda values, key=identifier, op=save_op: self._configuration_submit(op, key, values))
            dialog.reload_requested.connect(lambda values, key=identifier, op=reload_op: self._configuration_submit(op, key, values))
            dialog.finished.connect(lambda outcome, key=identifier, token=draft.token, editor_kind=kind: self._configuration_closed(
                key, token, editor_kind, getattr(dialog, 'discard_revision', '')))
            dialog.show()
            if kind == 'configuration' and draft.recovered_values is not None:
                yes, no, cancel = (QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No, QMessageBox.StandardButton.Cancel)
                choice = QMessageBox.question(dialog, '恢复未保存的配置草稿',
                    '是否恢复上次未保存的页面输入？选择“否”会清除该恢复草稿，选择“取消”可保留草稿并关闭窗口。',
                    yes | no | cancel, cancel)
                if self.closing or self.configuration_editors.get(identifier) is not dialog:
                    return
                if choice == yes:
                    dialog.set_draft(draft, restore=True)
                elif choice == no:
                    dialog.reload_discarding_recovery()
                    if dialog.busy:
                        return
                else:
                    dialog.close()
                    self.blocker_review.finish(identifier, kind, None)
                    return
            if kind == 'channels':
                if self._inventory_request is not None:
                    dialog.set_resources_refreshing(True)
                else:
                    dialog.request_resources()
            self.blocker_review.finish(identifier, kind, dialog)
        elif dialog is not None:
            if operation.startswith('configuration_pretest_'):
                self._pretest_result(identifier, dialog, operation.removeprefix('configuration_pretest_'), result.payload)
                return
            if operation.startswith('configuration_version_'):
                self._version_result(identifier, dialog, operation.removeprefix('configuration_version_'), result.payload)
                return
            if operation.startswith('configuration_push_'):
                self._push_trial_result(identifier, dialog, operation.removeprefix('configuration_push_'), result.payload)
                return
            if operation.startswith('channels_editor_rename_'):
                self._adapter_rename_result(identifier, dialog, operation.removeprefix('channels_editor_rename_'), result.payload)
                return
            if operation == 'channels_editor_preview':
                preview = result.payload
                answer = QMessageBox.question(dialog, '确认通道配置', preview['summary'],
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                self._configuration_submit('channels_editor_save' if answer == QMessageBox.StandardButton.Yes else 'channels_editor_cancel',
                    identifier, dict(token=dialog.draft.token, **({'confirmation': preview['confirmation']}
                    if answer == QMessageBox.StandardButton.Yes else {})))
                return
            dialog.set_busy(False)
            if operation == 'configuration_defaults':
                dialog.set_default_commands(result.payload)
                dialog.feedback.setText('默认命令已载入草稿，等待保存；全局重试间隔保留')
            elif operation == 'configuration_wifi_interfaces':
                dialog.set_wifi_interfaces(result.payload)
            elif operation == 'channels_editor_cancel':
                dialog.feedback.setText('已取消保存，界面输入保留，未写入文件')
            else:
                dialog.set_draft(result.payload)
                if operation == 'configuration_reload':
                    self.blocker_review.finish(identifier, kind, dialog)
                dialog.feedback.setText('保存成功，项目版本已更新' if operation in ('configuration_save', 'channels_editor_save') else '已重新加载磁盘配置')

    def _adapter_rename_result(self, identifier, dialog, operation, payload):
        if operation == 'preview':
            yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
            accepted = (not self.closing and self.window.selected_project == identifier
                        and QMessageBox.question(dialog, '确认 Windows 网卡改名', payload['summary'], yes | no, no) == yes)
            suffix = 'confirm' if accepted else 'cancel'
            arguments = dict(token=dialog.draft.token)
            if accepted:
                arguments['confirmation'] = payload['confirmation']
            self._configuration_submit('channels_editor_rename_' + suffix, identifier, arguments)
            return
        dialog.set_busy(False)
        if operation == 'cancel':
            dialog.feedback.setText('已取消改名，原选择和通道配置保留')
            return
        if payload['state'] == 'done':
            inventory, _ = self.adapter.device_inventory_snapshot()
            dialog.adapters = [adapter.alias for adapter in inventory.adapters]
            dialog.apply_rename(payload)
        else:
            show_warning(dialog, '网卡改名未完成', payload['message'],
                         lambda: self.blocker_review.open(identifier, ReviewTarget('channels', 'resources')))
        extra = '\n有未保存的通道修改' if dialog.dirty else ''
        dialog.feedback.setText(payload['message'] + extra)

    def _pretest_result(self, identifier, dialog, action, payload):
        if action == 'preview':
            yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
            accepted = (not self.closing and self.window.selected_project == identifier
                        and QMessageBox.question(dialog, '确认执行预备测试', payload['summary'], yes | no, no) == yes)
            if not self.closing and self.configuration_editors.get(identifier) is dialog:
                accepted = accepted and self.window.selected_project == identifier
                arguments = dict(token=dialog.draft.token)
                if accepted:
                    arguments['confirmation'] = payload['confirmation']
                self._configuration_submit('configuration_pretest_execute' if accepted else 'configuration_pretest_cancel',
                    identifier, arguments)
            return
        dialog.set_busy(False)
        if action == 'execute':
            dialog.show_pretest((payload, 'queued', True, ''))
        elif action == 'cancel':
            dialog.feedback.setText('已取消，未启动预备测试')
        elif action == 'stop' and payload.get('state') == 'stop_requested':
            dialog.show_pretest((payload['job_id'], 'stop_requested', True, ''))

    def _version_result(self, identifier, dialog, action, payload):
        if action == 'preview':
            yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
            summary = payload['summary']
            current = not self.closing and self.window.selected_project == identifier
            accepted = current and (not summary or
                QMessageBox.question(dialog, '确认查询样机版本', summary, yes | no, no) == yes)
            if not self.closing and self.configuration_editors.get(identifier) is dialog:
                execute = accepted and self.window.selected_project == identifier
                operation = 'configuration_version_execute' if execute else 'configuration_version_cancel'
                self._configuration_submit(operation, identifier,
                    dict(token=dialog.draft.token, confirmation=payload['confirmation']))
            return
        dialog.set_busy(False)
        if action == 'execute':
            dialog.show_version_query(payload)
        elif action == 'cancel':
            dialog.feedback.setText('已取消，未查询样机版本')

    def _push_trial_result(self, identifier, dialog, action, payload):
        if action == 'preview':
            yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
            accepted = (not self.closing and self.window.selected_project == identifier and
                QMessageBox.question(dialog, '确认发送测试消息', payload['summary'], yes | no, no) == yes)
            if not self.closing and self.configuration_editors.get(identifier) is dialog:
                execute = accepted and self.window.selected_project == identifier
                operation = 'configuration_push_execute' if execute else 'configuration_push_cancel'
                self._configuration_submit(operation, identifier,
                    dict(token=dialog.draft.token, confirmation=payload['confirmation']))
            return
        dialog.set_busy(False)
        if action == 'execute':
            dialog.show_push_trial(payload)
        elif action == 'cancel':
            dialog.feedback.setText('已取消，未发送测试消息')

    def _configuration_closed(self, identifier, token, kind='configuration', discard_revision=''):
        self.configuration_editors.pop(identifier, None)
        arguments = dict(token=token)
        if discard_revision:
            arguments['discard_revision'] = discard_revision
        operation = 'configuration_close' if kind == 'configuration' else 'channels_editor_close'
        if self.blocker_review.waiting_for_editor and self.blocker_review.pending[0] == identifier:
            if self._configuration_submit(operation, identifier, arguments) is None:
                self.blocker_review.editor_closed(identifier, False)
        else:
            self.submit(operation, identifier, arguments)

    def _close_editor(self, identifier):
        if identifier in self._configuration_pending:
            self.window.statusBar().showMessage('正在加载配置，请等待后关闭')
            return False
        dialog = self.configuration_editors.get(identifier)
        return dialog is None or dialog.close()

    def _prepare_test(self, operation, tasks=()):
        project = self._current()
        if not self.ready or self.closing or project is None or project.project_id in self._preparing:
            return
        if not (project.can_start or (operation in ('aging.start', 'service_aging.start') and project.parallel_power_available)):
            return
        request = self.submit('prepare_execution', project.project_id, operation, tasks)
        if request is not None:
            self._preparing.add(project.project_id)
            self._prepare_requests[request] = project.project_id
        self._sync_actions()
        return request

    def start_test(self):
        project = self._current()
        if project is not None:
            return self._prepare_test('service_aging.start' if project.project_type == 'service_aging' else 'aging.start')

    def open_single_power(self):
        project = self._current()
        if (not self.ready or self.closing or project is None or not project.can_start
                or project.project_id in self._preparing or self._single_power_request is not None):
            return
        if self._single_power_dialog is not None:
            if self._single_power_dialog.project_id == project.project_id:
                self._single_power_dialog.raise_()
                return
            self._single_power_dialog.close()
        self._single_power_request = self.submit('single_power_options', project.project_id)
        self._sync_actions()

    def _show_single_power(self, result):
        self._single_power_request = None
        project = self._current()
        if self.closing or project is None or project.project_id != result.project_id:
            return
        from src.ui.qt.single_power_dialog import SinglePowerDialog
        dialog = SinglePowerDialog(project, result.payload, self.window)
        self._single_power_dialog = dialog
        dialog.review_requested.connect(lambda target: self._review_single_power(dialog.project_id, target))
        dialog.inventory_requested.connect(self.refresh_resources)
        dialog.finished.connect(lambda _: setattr(self, '_single_power_dialog', None))
        dialog.show()
        self.blocker_review.finish(project.project_id, 'single_power', dialog)

    def _review_single_power(self, identifier, target):
        if identifier != self.window.selected_project:
            self.blocker_review.status('项目已切换，请在目标项目重新核对单次上/下电', identifier,
                                       ReviewTarget('single_power', 'port'))
            return
        self._prepare_test(SINGLE_POWER, target)

    def resume_channel(self, identifier, number):
        project = self._current()
        if (not self.ready or self.closing or project is None or project.project_id != identifier
                or identifier in self._preparing or not any(c.number == number and c.can_resume for c in project.channels)):
            return
        request = self.submit('prepare_execution', identifier, 'aging.resume', (number,))
        if request is not None:
            self._preparing.add(identifier)
            self._prepare_requests[request] = identifier
        self._sync_actions()

    def open_power_log(self, identifier, number, kind):
        if self.ready and not self.closing and any(project.project_id == identifier for project in self.window.projects):
            self.submit('open_power_log', identifier, number, kind)

    def check_environment(self):
        self._prepare_test('network.line_check')

    def open_pipeline(self):
        project = self._current()
        if not self.ready or self.closing or project is None:
            return
        identifier = project.project_id
        dialog = self.pipeline_windows.get(identifier)
        if dialog is None:
            from src.ui.qt.pipeline_dialog import PipelineDialog
            dialog = PipelineDialog(project.name, self.window)
            self.bind_module_window(dialog, identifier, 'pipeline')
            self.pipeline_windows[identifier] = dialog
            dialog.start_requested.connect(lambda tasks: self._start_pipeline(identifier, tasks))
            dialog.configuration_requested.connect(lambda code: self._pipeline_configure(identifier, code))
            dialog.review_requested.connect(lambda target: self.blocker_review.open(identifier, target))
            dialog.refresh_requested.connect(lambda: self._refresh_pipeline(identifier))
            dialog.finished.connect(lambda _: self._forget_pipeline(identifier, dialog))
        dialog.showNormal()
        dialog.raise_()
        self._refresh_pipeline(identifier)

    def _forget_pipeline(self, identifier, dialog):
        if self.pipeline_windows.get(identifier) is dialog:
            self.pipeline_windows.pop(identifier)
        dialog.deleteLater()

    def _refresh_pipeline(self, identifier):
        if identifier not in self._pipeline_pending.values() and not self.closing:
            request = self.submit('pipeline_status', identifier)
            if request is not None:
                self._pipeline_pending[request] = identifier
        self._sync_actions()

    def _start_pipeline(self, identifier, tasks):
        self.window.select_project(identifier)
        self._prepare_test('pipeline.start', tasks)

    def _pipeline_configure(self, identifier, code):
        self.window.select_project(identifier)
        self.pipeline_windows[identifier].hide()
        if code == 'legacy_power_test':
            self.open_configuration()
        elif code == 'serial_terminal':
            self.open_serial()
        else:
            self.open_channels()

    def stop_test(self):
        project = self._current()
        if project is None or not project.can_stop or self.closing:
            return
        queued = ('\n取消等待续跑的通道：' + '、'.join(f'CH{number:02d}' for number in project.resume_waiting)
            if project.resume_waiting else '')
        answer = QMessageBox.question(self.window, '停止测试',
            '请求项目“' + project.name + '”的当前任务安全停止？\n任务：' + project.run_id + queued + '\n将等待原业务收尾完成。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.submit('stop_execution', project.project_id, project.run_id)

    def submit(self, operation, *args):
        assert_gui_thread()
        if self.feishu_repair.dialog is not None and operation != 'feishu_repair_release':
            return None
        try:
            return self.adapter.submit(operation, *args)
        except (ValueError, RuntimeError) as error:
            self.window.statusBar().showMessage(str(error))
            return None

    def new_project(self):
        self.project_wizard.open()

    def open_project_setup(self):
        project = self._current()
        if project is not None:
            self.project_wizard.open(project)

    def open_project(self, path=None):
        if not self.ready or self.closing:
            return
        if not path:
            path, selected = QFileDialog.getOpenFileName(self.window, '打开项目', '', 'DUTPilot 项目 (project.linecheck.json)')
        if path:
            self.submit('open', path)

    def _populate_recent_menu(self):
        self.recent_menu.clear()
        for name, path in self._recent_projects:
            action = self.recent_menu.addAction(str(name).replace('&', '&&'), lambda checked=False, path=path: self.open_project(path))
            action.setToolTip(path)
        if not self._recent_projects:
            self.recent_menu.addAction('暂无最近项目').setEnabled(False)

    def forget_recent_project(self):
        project = self._current()
        if self.ready and not self.closing and project is not None:
            self.submit('forget_recent', project.project_id)

    def import_legacy_project(self):
        if not self.ready or self.closing:
            return
        source = QFileDialog.getExistingDirectory(self.window, '选择旧程序目录或配置目录')
        if not source:
            return
        name, accepted = QInputDialog.getText(self.window, '导入旧项目', '新项目名称')
        if not accepted or not name.strip():
            return
        destination = QFileDialog.getExistingDirectory(self.window, '选择新的空项目文件夹')
        if destination:
            self.submit('import_legacy', source, destination, name.strip())

    def open_imported_connections(self):
        if not self.ready or self.closing or self._imported_connection_request is not None:
            return
        if self._imported_connection_dialog is not None:
            self._imported_connection_dialog.showNormal()
            self._imported_connection_dialog.raise_()
            return
        self._imported_connection_request = self.submit('imported_connection_choices')
        self._sync_actions()

    def _select_imported_connection(self, identity):
        dialog = self._imported_connection_dialog
        if dialog is not None and not self.closing and self._imported_connection_request is None:
            self._imported_connection_request = self.submit('imported_connection_select', identity)
            if self._imported_connection_request is not None:
                dialog.set_busy(True)
                self._sync_actions()

    def _imported_connection_result(self, result):
        if result.identifier != self._imported_connection_request:
            return
        self._imported_connection_request = None
        if self.closing:
            return
        if result.operation == 'imported_connection_choices':
            if result.error:
                self.window.statusBar().showMessage(result.error, 10000)
                return
            from src.ui.qt.imported_connection_dialog import ImportedConnectionDialog
            dialog = ImportedConnectionDialog(result.payload, self.window)
            self._imported_connection_dialog = dialog
            dialog.selection_requested.connect(self._select_imported_connection)
            dialog.finished.connect(lambda _: setattr(self, '_imported_connection_dialog', None))
            dialog.show()
        elif self._imported_connection_dialog is not None:
            dialog = self._imported_connection_dialog
            dialog.set_busy(False)
            if result.error:
                dialog.feedback.setText(result.error)
            else:
                self.window.statusBar().showMessage(result.payload + '接入配置已保存，启用须重启后在本机确认', 10000)
                dialog.accept()

    def open_project_directory(self):
        project = self._current()
        if project is not None and self.ready and not self.closing:
            self.submit('open_project_directory', project.project_id)

    def save_project(self):
        project = self._current()
        if project is not None:
            self.submit('save', project.project_id)

    def rename_project(self):
        project = self._current()
        if project is None:
            return
        name, accepted = QInputDialog.getText(self.window, '重命名项目', '项目名称', text=project.name)
        if accepted and name.strip():
            self.submit('rename', project.project_id, name)

    def duplicate_project(self):
        project = self._current()
        if project is None:
            return
        choice = ''
        if project.dirty:
            answer = QMessageBox.question(self.window, '保存后另存为', '先保存当前项目配置，再创建独立副本？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            choice = 'save'
        path = QFileDialog.getExistingDirectory(self.window, '另存为：选择空项目文件夹')
        if path:
            self.submit('duplicate', project.project_id, path, choice)

    def _close_choice(self, project):
        if not project.dirty:
            return ''
        answer = QMessageBox.question(self.window, '保存项目配置', '项目“' + project.name + '”有未保存草稿，是否保存？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return ('save' if answer == QMessageBox.StandardButton.Yes else
                'discard' if answer == QMessageBox.StandardButton.No else None)

    def close_project(self):
        project = self._current()
        if project is None:
            return
        wizard = self.project_wizard.dialog
        if wizard is not None and wizard.project_id == project.project_id and not wizard.close():
            return
        if not self._close_editor(project.project_id):
            return
        choice = self._close_choice(project)
        if choice is not None:
            operation = 'close'
            if project.active_task_count:
                answer = QMessageBox.question(self.window, '停止并关闭项目',
                    '项目“' + project.name + '”仍有任务。请求安全停止，收尾完成后关闭项目？',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
                operation = 'stop_and_close'
            if self.ai_chat.can_close_case(project.project_id):
                self._remember_tool_windows(project.project_id)
                self.submit(operation, project.project_id, choice)

    def project_menu(self, point):
        index = self.window.navigation.indexAt(point)
        identifier = index.data(Qt.ItemDataRole.UserRole)
        if identifier:
            self.window.select_project(identifier)
        self._sync_actions()
        self.menu.popup(self.window.navigation.viewport().mapToGlobal(point))

    def poll(self):
        assert_gui_thread()
        self.app_update.poll()
        now = time.monotonic()
        if self._last_gui_poll is not None:
            self._gui_gap_peak = max(self._gui_gap_peak or 0, (now - self._last_gui_poll) * 1000)
        self._last_gui_poll = now
        projects, logs, results = self.adapter.take_updates()
        if self.configuration_editors:
            _, leases = self.adapter.device_inventory_snapshot()
            for dialog in tuple(self.configuration_editors.values()):
                if getattr(dialog, 'editor_kind', '') == 'channels':
                    dialog.set_power_claims(leases.entries)
        self._log_batch_peak = max(self._log_batch_peak, len(logs))
        if now >= self._next_health:
            self.window.dashboard.system_health.update_status(self.adapter.health_snapshot(),
                now, self._gui_gap_peak, self._log_batch_peak, projects)
            self._next_health = now + 1
            self._gui_gap_peak = None
            self._log_batch_peak = 0
        self.window.set_projects(projects)
        if logs:
            self.window.logs.append_batch(logs)
        for result in results:
            if self.feishu_repair.handle_result(result):
                continue
            if result.operation in EXTENSION_OPERATIONS:
                if self.extensions_dialog is not None:
                    self.extensions_dialog.handle_result(result)
                continue
            if result.operation in PLATFORM_CONFIG_OPERATIONS:
                if self.platform_configuration_dialog is not None:
                    self.platform_configuration_dialog.handle_result(result)
                continue
            if self.project_wizard.handle_result(result):
                continue
            if result.operation == 'instance_status' or result.operation in GATEWAY_OPERATIONS:
                if self.instance_status_dialog is not None and not self.closing:
                    self.instance_status_dialog.show_result(result)
                continue
            if result.operation in ('remote_scope_read', 'remote_scope_save'):
                if self.remote_scope_dialog is not None and not self.closing:
                    self.remote_scope_dialog.show_result(result)
                continue
            if self.ai_chat.handle_result(result):
                continue
            if self.model_settings.handle_result(result):
                continue
            if result.operation in ('imported_connection_choices', 'imported_connection_select'):
                self._imported_connection_result(result)
                continue
            if (self.aging_history.handle_result(result) or self.log_history.handle_result(result) or self.archived_logs.handle_result(result)
                    or self.channel_history.handle_result(result)):
                continue
            if result.operation in ('open_power_log', 'open_project_directory'):
                self.window.statusBar().showMessage(result.error or result.payload, 7000)
                continue
            if result.operation == 'export_logs':
                self._log_export_pending = False
                message = result.error or f'已导出 {result.payload} 项筛选日志'
                self.window.statusBar().showMessage(message, 7000)
                continue
            if result.operation == 'refresh_inventory':
                self._inventory_finished(result)
                continue
            if result.operation == 'single_power_options':
                self._single_power_request = None
                if not result.error:
                    self._show_single_power(result)
                    continue
                self.blocker_review.finish(result.project_id, 'single_power', None)
            if self.parameter_writer.handle_result(result) or self.onu_query.handle_result(result):
                continue
            observation = self._job_serial_requests.pop(result.identifier, None)
            if observation is not None:
                self._job_serial_result(result, *observation)
                continue
            upgrade = self._upgrade_requests.pop(result.identifier, None)
            if upgrade is not None:
                self._upgrade_result(result, *upgrade)
                continue
            dut = self._dut_requests.pop(result.identifier, None)
            if dut is not None:
                self._dut_result(result, *dut)
                continue
            serial = self._serial_requests.pop(result.identifier, None)
            if serial is not None:
                self._serial_result(result, *serial)
                continue
            if (not result.error and result.project_id in self.pipeline_windows
                    and result.operation in ('configuration_save', 'channels_editor_save', 'serial_directory')):
                self._refresh_pipeline(result.project_id)
            configuration = self._configuration_requests.pop(result.identifier, None)
            if configuration is not None:
                self._configuration_result(result, *configuration)
                continue
            if result.operation == 'prepare_execution':
                self._preparing.discard(self._prepare_requests.pop(result.identifier, result.project_id))
            if result.operation == 'pipeline_status':
                identifier = self._pipeline_pending.pop(result.identifier, '')
                dialog = self.pipeline_windows.get(identifier)
                if dialog is not None and not result.error and not self.closing:
                    dialog.show_status(result.payload)
                    continue
            if result.operation == 'confirm_execution':
                identifier = self._pipeline_pending.pop(result.identifier, '')
                dialog = self.pipeline_windows.get(identifier)
                if dialog is not None and not result.error and not self.closing:
                    dialog.hide()
            if result.error:
                if result.operation == 'refresh':
                    self.window.statusBar().showMessage('自动刷新失败，当前显示上次取得的项目状态。' + result.error, 5000)
                    continue
                if result.operation == 'close_rejected':
                    self.closing = False
                    self.closing_changed.emit(False)
                    self.feishu_repair.cancel_restart()
                    self.parameter_writer.set_closing(False)
                    self.onu_query.set_closing(False)
                    for dialog in self.serial_windows.values():
                        dialog.set_busy(False)
                    for dialog in self.dut_windows.values():
                        dialog.set_busy(False)
                    for dialog in self.upgrade_windows.values():
                        dialog.set_busy(False)
                self.window.statusBar().showMessage(result.error)
                if result.operation == 'initialization_failed':
                    self.window.set_mode_message('项目服务加载失败')
                    self.window.logs.append_batch((LogView(datetime.now().strftime('%H:%M:%S'), 'ERROR', '', '工作区', result.error),))
                if result.operation != 'initialization_failed':
                    self.blocker_review.warning(result, '项目操作未完成')
                continue
            if result.operation == 'ready':
                self.ready = True
                if result.project_id:
                    self.window.select_project(result.project_id)
                self._recent_projects, recent_error = result.payload
                if recent_error:
                    self.window.statusBar().showMessage(recent_error, 10000)
                self.window.set_mode_message('')
                self.window.dashboard.new_button.setToolTip('通过原项目服务创建独立项目')
                self.window.dashboard.open_button.setToolTip('打开原项目格式，不自动恢复设备任务')
                self.window.logs.append_batch((LogView(datetime.now().strftime('%H:%M:%S'), 'INFO', '',
                    '工作区', 'Qt工作区已就绪；测试须核对已保存配置并明确确认'),))
            elif result.operation == 'prepare_execution':
                confirmation = result.payload
                if self.closing or confirmation.project_id != self.window.selected_project:
                    if not self.closing:
                        self.blocker_review.status('项目已切换，本次测试确认未执行，请在目标项目重新操作',
                                                   confirmation.project_id, ReviewTarget('project', 'start'))
                        self.submit('cancel_confirmation', confirmation.project_id, confirmation.token)
                    continue
                title = {'aging.resume': '确认通道续跑', SINGLE_POWER: '确认单次自动上/下电'}.get(
                    confirmation.operation, '确认测试目标与配置')
                answer = QMessageBox.question(self.window, title, confirmation.summary,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if answer == QMessageBox.StandardButton.Yes and not self.closing and confirmation.project_id == self.window.selected_project:
                    request = self.submit('confirm_execution', confirmation.project_id, confirmation.token)
                    if request is not None and confirmation.operation == 'pipeline.start':
                        self._pipeline_pending[request] = confirmation.project_id
                else:
                    self.submit('cancel_confirmation', confirmation.project_id, confirmation.token)
            elif result.operation in RECENT_CHANGES:
                self._recent_projects = result.payload
                if result.operation == 'forget_recent':
                    self.window.statusBar().showMessage('已从最近列表移除，项目文件保留', 7000)
                elif result.project_id:
                    self.window.select_project(result.project_id)
        self._sync_actions()
        self._show_device_inventory()
        opened = {project.project_id for project in projects}
        self.project_wizard.prune(opened)
        for identifier, dialog in tuple(self.pipeline_windows.items()):
            if identifier not in opened or self.closing and self.adapter.closed.is_set():
                dialog.close()
        for identifier in self._pipeline_serial_seen.keys() - opened:
            self._pipeline_serial_seen.pop(identifier)
        if not self.closing:
            for project in projects:
                identifier, run = project.project_id, project.pipeline_serial_run
                if (run and self._pipeline_serial_seen.get(identifier) != run
                        and not any(entry[0] == identifier for entry in self._serial_requests.values())):
                    self._pipeline_serial_seen[identifier] = run
                    self._serial_submit(identifier, 'show', {})
        self.parameter_writer.prune(opened, self.closing and self.adapter.closed.is_set())
        self.onu_query.prune(opened, self.closing and self.adapter.closed.is_set())
        self.log_history.prune(opened)
        self.aging_history.prune(opened)
        self.feishu_repair.poll()
        self.channel_history.poll(projects)
        self.archived_logs.prune(opened)
        self.model_settings.prune(opened)
        self.ai_chat.poll(opened)
        if self._single_power_dialog is not None and (self.closing or self._single_power_dialog.project_id not in opened):
            self._single_power_dialog.close()
        current_batches = {project.project_id: project.serial_observation[1] for project in projects}
        for identifier, dialog in tuple(self.job_serial_windows.items()):
            if current_batches.get(identifier) != dialog.batch or self.closing and self.adapter.closed.is_set():
                dialog.close()
        for identifier in self._job_serial_seen.keys() - opened:
            self._job_serial_seen.pop(identifier)
        for identifier, dialog in tuple(self.upgrade_windows.items()):
            if identifier not in opened or self.closing and self.adapter.closed.is_set():
                dialog.allow_close = True
                dialog.close()
        for identifier, dialog in tuple(self.dut_windows.items()):
            if identifier not in opened or self.closing and self.adapter.closed.is_set():
                dialog._allow_close = True
                dialog.close()
        for identifier, dialog in tuple(self.serial_windows.items()):
            if identifier not in opened or self.closing and self.adapter.closed.is_set():
                dialog._allow_close = True
                dialog.close()
        if (self.closing and self.adapter.closed.is_set() and self.app_update.worker.finish_close()
                and self.adapter.finish_log_close()):
            self.timer.stop()
            self._allow_close = True
            self.window._close_coordinator = None
            self.window.close()
            return
        if self.ready and not self.closing and time.monotonic() >= self._next_refresh:
            self._next_refresh = time.monotonic() + 1
            self.submit('refresh')
        if self.ready and not self.closing and time.monotonic() >= self._serial_next_poll:
            self._serial_next_poll = time.monotonic() + .2
            for identifier, dialog in tuple(self.serial_windows.items()):
                if identifier not in self._serial_pending and not dialog.busy:
                    self._serial_submit(identifier, 'poll', dict(token=dialog.token, active=dialog.active))
        if self.ready and not self.closing and time.monotonic() >= self._dut_next_poll:
            self._dut_next_poll = time.monotonic() + .3
            pending = {item[0] for item in self._dut_requests.values()}
            for identifier, dialog in tuple(self.dut_windows.items()):
                if identifier not in pending and not dialog.busy and not dialog.detaching:
                    self._dut_submit(identifier, 'poll', dict(token=dialog.token))
        if self.ready and not self.closing and time.monotonic() >= self._upgrade_next_poll:
            self._upgrade_next_poll = time.monotonic() + .3
            pending = {key for key, _ in self._upgrade_requests.values()}
            for identifier, dialog in tuple(self.upgrade_windows.items()):
                if identifier not in pending and not dialog.busy and not dialog.detaching:
                    self._upgrade_submit(identifier, 'poll', dict(token=dialog.token))
            self._poll_job_serial(projects)
            self.parameter_writer.poll()
            self.onu_query.poll()

    def request_close(self):
        assert_gui_thread()
        if self.closing or self.feishu_repair.dialog is not None:
            return
        if self.project_wizard.dialog is not None and not self.project_wizard.dialog.close():
            return
        if self.extensions_dialog is not None and not self.extensions_dialog.close():
            return
        if self.platform_configuration_dialog is not None and not self.platform_configuration_dialog.close():
            return
        if self.remote_scope_dialog is not None and not self.remote_scope_dialog.close():
            self.window.statusBar().showMessage('正在保存远程项目范围，请等待实际写入结果', 5000)
            return
        if self._imported_connection_dialog is not None and not self._imported_connection_dialog.close():
            return
        if any(not self._close_editor(project.project_id) for project in self.window.projects):
            return
        active = [project for project in self.window.projects if project.active_task_count]
        if active:
            answer = QMessageBox.question(self.window, '停止任务并退出',
                '仍有测试任务运行。请求安全停止所有当前Qt任务，收尾完成后退出？\n' + '\n'.join(p.name for p in active),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        choices = {}
        for project in self.window.projects:
            choice = self._close_choice(project)
            if choice is None:
                return
            choices[project.project_id] = choice
        if any(not self.ai_chat.can_close_case(identifier) for identifier in choices):
            return
        for identifier in choices:
            self._remember_tool_windows(identifier)
        self.closing = True
        self.closing_changed.emit(True)
        self.app_update.begin_close()
        self.parameter_writer.set_closing(True)
        self.onu_query.set_closing(True)
        for dialog in self.serial_windows.values():
            dialog.set_busy(True)
        for dialog in self.dut_windows.values():
            dialog.set_busy(True)
        for dialog in self.upgrade_windows.values():
            dialog.set_busy(True)
        self.window.set_mode_message('正在等待测试、串口、项目和更新操作收尾…')
        self._sync_actions()
        self.adapter.begin_close(choices, update_logs_pending=self.app_update.worker.pending_work,
                                 selected_project=self.window.selected_project)
