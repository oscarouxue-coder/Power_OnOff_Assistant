"""GUI snapshots/admission only. Business workers receive a data client, not this object."""
from dataclasses import asdict
from contextlib import contextmanager
from src.services.pipeline_runtime import PipelineChannel, PipelineDispatcher
from src.services.adapter_rename_service import adapter_rename_is_busy


@contextmanager
def _settings_data_assignment(app, domain):
    """Preserve Tcl trace scripts without invoking editor/autosave callbacks."""
    removed = []
    try:
        prefixes = ('upgrade_', 'parameter_', 'power_operation_') if domain == 'upgrade' else ('onu_',)
        for name, variable in vars(app).items():
            if not name.endswith('_var') or not name.startswith(prefixes) or not hasattr(variable, 'trace_info'):
                continue
            for modes, script in variable.trace_info():
                if 'write' in modes:
                    # trace_remove also deletes the registered Python command; the
                    # Tcl operation only detaches it so the exact script survives.
                    variable._tk.call('trace', 'remove', 'variable', variable._name, modes, script)
                    removed.append((variable, modes, script))
        yield
    finally:
        for variable, modes, script in reversed(removed):
            variable._tk.call('trace', 'add', 'variable', variable._name, modes, script)


def gui_business_available(app):
    """Main-thread admission after a modal confirmation; never invokes a device action."""
    if getattr(app, '_capability_reservations', ()):
        app._log('[业务互斥] 独立业务任务仍持有资源，GUI全流程未启动。')
        return False
    return True


class CapabilityUiClient:
    def __init__(self, channel):
        self.channel = channel

    def snapshot(self):
        return self.channel.invoke(self.channel.new_run(), "snapshot")

    def admissible(self, owner, keys):
        return bool(self.channel.invoke(self.channel.new_run(), "admissible", (owner, tuple(keys))))

    def released(self, owner):
        return self.channel.invoke(self.channel.new_run(), "released", (owner,), cleanup=True)

    def onu_snapshot(self):
        return self.channel.invoke(self.channel.new_run(), "onu_snapshot")

    def commit_channels(self, transaction):
        return self.channel.invoke(self.channel.new_run(), 'commit_channels', (transaction,))

    def commit_settings(self, transaction):
        return self.channel.invoke(self.channel.new_run(), 'commit_settings', (transaction,))


class CapabilityUiBridge:
    def __init__(self, app):
        self.app = app
        self.channel = PipelineChannel()
        self.client = CapabilityUiClient(self.channel)
        self.dispatcher = PipelineDispatcher(self.channel)
        self.reservations = set()
        self.channel_configuration = None
        self.settings_configuration = None
        self.app._capability_reservations = self.reservations
        self.dispatcher.handlers.update(snapshot=lambda request: self._snapshot(),
                                        onu_snapshot=lambda request: asdict(self.app._current_onu_registration_config()),
                                        admissible=self._admissible,
                                        commit_channels=self._commit_channels,
                                        commit_settings=self._commit_settings,
                                        released=lambda request: self.reservations.discard(request.args[0]))

    def _snapshot(self):
        self.app._capture_current_channel()
        editor = getattr(self.app, 'test_item_config_window', None)
        session = getattr(self.app, 'power_test_resume_session', None)
        wifi_logs = {str(n): str(session.current_wifi_log(n) or '') for n in session.completed} if session else {}
        def opened(name):
            window = getattr(self.app, name, None)
            return bool(window is not None and window.winfo_exists())
        return dict(channels=[asdict(c) for c in self.app.channels],
                    current_wifi_logs=wifi_logs,
                    configuration_editor_open=bool(editor is not None and editor.winfo_exists()),
                    upgrade_settings=asdict(self.app._current_sample_upgrade_settings()),
                    upgrade_editor_open=opened('upgrade_window') or opened('parameter_writer_window'),
                    onu_editor_open=opened('onu_registration_window'),
                    upgrade_autosave_pending=getattr(self.app, 'sample_upgrade_save_after_id', None) is not None,
                    onu_autosave_pending=getattr(self.app, 'onu_save_after_id', None) is not None,
                    power_serial_port=self.app._selected_power_serial_port(),
                    serial_log_dir=str(self.app._serial_log_directory()),
                    device_ip=self.app.device_ip_var.get().strip())

    def _reflect_settings(self, domain, values):
        """Assign data only. Editors must be closed before this host transaction."""
        timer = 'sample_upgrade_save_after_id' if domain == 'upgrade' else 'onu_save_after_id'
        try:
            with _settings_data_assignment(self.app, domain):
                self._assign_settings(domain, values)
        finally:
            # Variable traces can schedule autosave even if a later assignment fails.
            pending = getattr(self.app, timer, None)
            if pending is not None:
                self.app.after_cancel(pending)
                setattr(self.app, timer, None)

    def _assign_settings(self, domain, values):
        from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings
        from line_check_assistant.onu_registration_store import OnuRegistrationConfig
        if domain == 'upgrade':
            names = dict(upgrade_mode='upgrade_mode', transfer_method='upgrade_transfer',
                boot_entry_method='upgrade_boot_entry', parallel_count='upgrade_parallel_count',
                restore_factory='upgrade_restore_factory', username='upgrade_username', password='upgrade_password',
                firmware_path='upgrade_firmware')
            for key, value in values.items():
                variable = getattr(self.app, names.get(key, key) + '_var')
                variable.set(value)
            self.app.sample_upgrade_settings = SampleUpgradeSettings(**values)
        else:
            for key, value in values.items():
                if key in ('c300_services', 'c600_services') or key.startswith(('c300_', 'c600_')) and key.split('_', 1)[1] in (
                        'olt_ip', 'source_ip', 'username', 'password'):
                    continue
                name = 'onu_family_var' if key == 'olt_family' else 'onu_' + key + '_var'
                getattr(self.app, name).set(value)
            self.app.onu_connection_profiles = {family: {key: values[family.lower() + '_' + key]
                for key in ('olt_ip', 'source_ip', 'username', 'password')} for family in ('C300', 'C600')}
            self.app.onu_registration_config = OnuRegistrationConfig(**values)
            self.app.onu_preview_ready = False
            self.app.onu_registered_candidates = ()
            self.app.onu_registered_query_context = None
            self.app.onu_c300_cleanup_candidates = ()
            if hasattr(self.app, 'onu_c300_cleanup_candidate_var'):
                self.app.onu_c300_cleanup_candidate_var.set('')

    def _commit_settings(self, request):
        if self.settings_configuration is None or getattr(self.app, '_app_closing', False) or not request.admit():
            raise RuntimeError('永久选项数据适配未就绪或请求已取消，未保存')
        prepared = request.args[0]
        try:
            onu = asdict(self.app._current_onu_registration_config()) if prepared['domain'] == 'onu' else None
            return self.settings_configuration.commit(prepared, self._snapshot(), onu, self._reflect_settings)
        except Exception as exc:
            if getattr(exc, 'code', '') == 'settings_rollback_failed':
                self.reservations.add('configuration-unknown')
                self.app._log('[永久选项] 视图恢复未完成，保留资源保护，请本地核对并重启。')
            raise

    def _reflect_channels(self, state):
        from line_check_assistant.config_store import ChannelConfig
        self.app.channels = [ChannelConfig(**c) for c in state['channels']]
        self.app.power_serial_port = state['power_serial_port']
        self.app.power_serial_var.set(state['power_serial_port'])
        self.app.device_ip_var.set(state['device_ip'])
        if 'adapter_options' in state:
            self.app.adapters = list(state['adapter_options'])
        self.app._rebuild_channel_config_rows()
        for index in range(len(self.app.channels)):
            self.app._refresh_channel_list_item(index)
        self.app._load_current_channel()

    def _commit_channels(self, request):
        if self.channel_configuration is None or getattr(self.app, '_app_closing', False):
            raise RuntimeError('通道数据适配未就绪或正在退出，未保存')
        if not request.admit():
            raise RuntimeError('通道提交请求已取消，未保存')
        try:
            result = self.channel_configuration.commit(request.args[0], self._snapshot(), self._reflect_channels)
        except Exception as exc:
            # A failed rollback render must not permit commands against a stale view.
            if (getattr(exc, 'code', '') == 'channel_view_rollback_failed' or
                    [asdict(c) for c in self.app.channels] != request.args[0]['before']['channels']):
                self.reservations.add('configuration-unknown')
                self.app._log('[通道配置] 视图恢复未完成，保留资源保护，请重启源码程序核对原配置。')
            raise
        try:
            self.app._refresh_upgrade_targets()
            assistant = getattr(self.app, 'ai_assistant', None)
            if assistant is not None:
                assistant.service.configure(assistant.service.profile, self.app._collect_ai_targets())
        except Exception:
            self.reservations.add('configuration-unknown')
            self.app._log('[通道配置] 磁盘保存成功，目标/显示刷新失败；保留保护，请重启源码程序核对。')
            return dict(state='saved_refresh_failed')
        return result

    def _admissible(self, request):
        gate = vars(self.app).get('_source_maintenance_gate')
        if gate is not None and gate.active:
            return False
        owner = request.args[0]
        if 'device-business' not in request.args[1]:
            return not getattr(self.app, '_app_closing', False)
        if getattr(self.app, "_app_closing", False) or self.app._ai_target_busy(None) or adapter_rename_is_busy(self.app):
            return False
        assistant = getattr(self.app, "ai_assistant", None)
        if assistant is not None:
            # Do not cancel the requesting conversation. Require temporary diagnostics to be cleaned first.
            diagnostic = assistant.service
            with diagnostic.lock:
                if any(getattr(executor, "transport", None) is not None for executor in diagnostic.executors.values()):
                    return False
        if not request.admit():
            return False
        self.reservations.add(owner)
        # The dispatcher discards admission if a close/cancel wins before result delivery.
        return _Admission(self.reservations, owner)

    def poll(self):
        self.dispatcher.poll(16)

    def close(self):
        self.channel.close()
        self.dispatcher.poll(32)
        self.dispatcher.dispose()


class _Admission:
    def __init__(self, reservations, owner):
        self.reservations, self.owner = reservations, owner

    def discard(self):
        self.reservations.discard(self.owner)
