"""Exercise the two launch routes and the standalone Start callback with temporary projects."""
from contextlib import ExitStack
from copy import copy
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
from src.models.project import PROJECT_FILE
from src.services.project_profile_store import read_project_profile
from src.services.project_store import ProjectStore


def fixture_project(source, root, rows, channels, *, port='COM901'):
    config = source / 'Auto_power_on_off_tool/config'
    config.mkdir(parents=True, exist_ok=True)
    for name in ('config.ini', 'onu_registration.ini', 'sample_upgrade_settings.ini', 'test_project_config.default.ini'):
        (config / name).write_text('[fixture]\n', encoding='utf-8')
    store = ProjectStore(source)
    project = store.create(root, '同名项目', profile=dict(test_type='power_cycle', duts=rows))
    try:
        (project.config_dir / 'config.ini').write_text(
            '[config]\ntest = test_project_config.ini\n[ui_defaults]\nselected_profile = TEST\n', encoding='utf-8')
        ChannelConfigStore(project.config_dir / 'network_card_ip.ini').save(channels, port)
        store.save(project)
        return project.identity
    finally:
        store.close(project)


class StandaloneProjectTests(unittest.TestCase):
    def setUp(self):
        stack = self.stack = ExitStack()
        self.addCleanup(stack.close)
        self.base = Path(stack.enter_context(TemporaryDirectory()))
        self.source = self.base / 'source'
        self.hardware = {label: f'fixture-{label}-{uuid4().hex}' for label in ('A', 'B')}
        for label in ('A', 'B'):
            fixture_project(self.source, self.base / label,
                            [dict(label='CH05', channel=5, hardware_id=self.hardware[label])],
                            [ChannelConfig('channel_5', network_card_ip='192.0.2.5')])
        stack.enter_context(patch('line_check_assistant.paths.resolve_tool_root', return_value=self.source))
        from line_check_assistant import app, pipeline_window
        self.module, self.window_type = app, pipeline_window.PipelineWindow
        stack.enter_context(patch.object(app, 'APP_DIR', self.source))
        stack.enter_context(patch.dict(os.environ, LINECHECK_LEGACY_SINGLE_PROJECT='1'))
        self.error = stack.enter_context(patch.object(app.messagebox, 'showerror'))
        self.warning = stack.enter_context(patch.object(pipeline_window.messagebox, 'showwarning'))
        self.confirm = stack.enter_context(patch.object(pipeline_window.messagebox, 'askyesno', return_value=True))
        statuses = {code: SimpleNamespace(ready=True, summary='fixture', missing=()) for code in pipeline_window.WINDOW_SUBTASK_CODES}
        self.preview = stack.enter_context(patch.object(pipeline_window, 'compute_all_subtask_statuses', return_value=statuses))
        stack.enter_context(patch.object(pipeline_window, 'describe_legacy_power_telnet_post_login', return_value='fixture'))
        self.dispatch = stack.enter_context(patch.object(pipeline_window, 'start_project_thread'))
        self.connect = stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('unexpected I/O')))

    def launch(self, path, *, edit=lambda app: None, after=lambda ctx: None):
        def construct(project_context=None):
            app = SimpleNamespace(workspace=None, project_context=project_context, _pipeline_ui=Mock(),
                                  _prepare_ai_for_device_action=Mock(return_value=True))
            self.app = app
            if project_context:
                app.store = ChannelConfigStore(project_context.config_dir / 'network_card_ip.ini')
                app.channels = app.store.load()
                app.power_serial_port = app.store.load_power_serial_port()
                app.device_ip_var = Mock(get=Mock(return_value=''))
                app._serial_port_for_channel = lambda row: row.serial_port
                app.channel_row_vars = {c.section: dict(enabled=Mock(get=Mock(return_value=c.enabled)),
                                                        vlan=Mock(get=Mock(return_value=c.vlan_name)),
                                                        serial_port=Mock(get=Mock(return_value=c.serial_port)))
                                        for c in app.channels}

            def loop():
                window = self.window_type.__new__(self.window_type)
                window.app = window.project_view = app
                window.window = Mock()
                window._check_vars = {'legacy_power_test': Mock(get=Mock(return_value=True))}
                window._running_thread = None
                for method in ('_set_running_ui', '_update_main_power_test_progress', '_update_main_power_test_status',
                               '_emit_to_main_log'):
                    setattr(window, method, Mock())
                edit(app)
                window._on_start()
                if window._running_thread:
                    after(window._running_thread._args[0])
            app.mainloop = loop
            return app

        with patch.object(self.module, 'LineCheckAssistant', side_effect=construct):
            self.module.main(path)
        self.connect.assert_not_called()

    def test_same_name_same_channel_each_launch_uses_its_own_saved_run(self):
        for label in ('A', 'B'):
            with self.subTest(project=label):
                root = self.base / label
                def verify(ctx):
                    run = ctx.standalone_power_run
                    self.assertEqual(run.root.parent, root / 'runs')
                    profile = run.verify(ctx, ctx.app.power_serial_port)
                    self.assertEqual(profile['duts'][0]['hardware_id'], self.hardware[label])
                    self.assertEqual(profile, read_project_profile(ctx.legacy_tool_root / 'config'))
                    self.assertIn(str(root), self.confirm.call_args.args[1])
                self.launch(root / PROJECT_FILE, after=verify)
                self.dispatch.assert_called_once()
                self.dispatch.reset_mock()
                self.assertFalse(self.app.standalone_power_project.store.opened)
        self.warning.assert_not_called()

    def test_wrong_view_foreign_root_copied_context_and_detached_store_are_rejected(self):
        def replace_context(app):
            app.project_context = copy(app.project_context)
        def detach(app):
            app.standalone_power_project.store.close(app.project_context)
        for edit in (replace_context, detach, lambda a: setattr(a.project_context, 'root', self.base / 'B'),
                     lambda a: setattr(a, '_project_run_root', self.base / 'B'),
                     lambda a: setattr(a.store, 'config_path', self.base / 'B/network_card_ip.ini')):
            with self.subTest(edit=edit):
                self.launch(self.base / 'A', edit=edit)
                self.assert_refused()

    def assert_refused(self):
        self.assertIn('保存后', self.warning.call_args.args[1])
        self.app._prepare_ai_for_device_action.assert_not_called()
        self.preview.assert_not_called()
        self.dispatch.assert_not_called()
        self.warning.reset_mock()

    def test_unsaved_draft_changed_revision_or_in_memory_channel_rejected(self):
        for label, edit in [('A', lambda a: a.standalone_power_project.store.save(a.project_context)),
                            ('A', lambda a: setattr(a.channels[0], 'network_card_ip', '192.0.2.99')),
                            ('B', lambda a: (a.project_context.config_dir / 'different.ini').write_text('[fake]'))]:
            self.launch(self.base / label, edit=edit)
            self.assert_refused()

    def test_unbound_window_and_loose_file_cannot_start(self):
        self.launch(None)
        self.assert_refused()
        loose = self.base / 'A/loose.ini'
        loose.touch()
        self.launch(loose)
        self.error.assert_called_once()
        self.dispatch.assert_not_called()

    def test_confirmation_change_refused_before_dispatch(self):
        def change(*args, **kwargs):
            self.app.standalone_power_project.store.save(self.app.project_context)
            return True
        self.confirm.side_effect = change
        self.launch(self.base / 'A')
        self.warning.assert_called_once()
        self.dispatch.assert_not_called()

    def test_visible_target_change_blocks_before_preview(self):
        self.launch(self.base / 'A', edit=lambda app: app.device_ip_var.get.configure_mock(return_value='192.0.2.99'))
        self.assert_refused()

    def test_saved_scheme_cannot_reference_another_projects_file(self):
        root = self.base / 'A'
        store = ProjectStore(self.source)
        project = store.open(root)
        try:
            (project.config_dir / 'config.ini').write_text(
                '[config]\ntest = ../../B/foreign.ini\n[ui_defaults]\nselected_profile = TEST\n')
            store.save(project)
        finally:
            store.close(project)
        self.launch(root)
        self.assert_refused()

    def test_worker_rechecks_project_and_snapshot_after_confirmation(self):
        from src.services.pipeline_orchestrator import PipelineOrchestrator
        from src.services.physical_resource_guards import PowerAdmissionError
        def verify(ctx):
            ctx.legacy_tool_root = self.base / 'B/Auto_power_on_off_tool'
            with patch('src.services.physical_resource_guards.adapters_ipv4') as inventory, \
                    patch.object(PipelineOrchestrator, '_run_env_check') as business:
                with self.assertRaises(PowerAdmissionError):
                    PipelineOrchestrator(ctx, lambda line: None).run({'env_check', 'legacy_power_test'})
                inventory.assert_not_called()
                business.assert_not_called()
        self.launch(self.base / 'A', after=verify)
        self.dispatch.assert_called_once()

    def test_normal_workspace_routes_selected_path(self):
        with patch.dict(os.environ, LINECHECK_LEGACY_SINGLE_PROJECT='0'), \
                patch('src.services.workspace_service.workspace_data_dir', return_value=self.base), \
                patch('src.core.workspace_instance.WorkspaceInstance') as instance, \
                patch('src.ui.project_workspace.ProjectWorkspace') as workspace:
            workspace.return_value.after_idle.side_effect = lambda fn: fn()
            self.module.main(self.base / 'B')
            workspace.return_value.open_project.assert_called_once_with(self.base / 'B')
            workspace.return_value.mainloop.assert_called_once()
            instance.return_value.close.assert_called_once()

    def test_native_start_button_binds_selected_project_and_rejects_changed_view(self):
        from tk_test_windows import install_offscreen_windows
        install_offscreen_windows(self)
        import tkinter as tk
        from queue import Queue
        from src.services.standalone_power_project import StandalonePowerProject
        binding = StandalonePowerProject.open(ProjectStore(self.source), self.base / 'B')
        self.addCleanup(binding.store.close, binding.context)
        app = tk.Tk()
        self.addCleanup(app.destroy)
        app.workspace = None
        app.standalone_power_project = binding
        app.project_context = binding.context
        app.store = ChannelConfigStore(binding.context.config_dir / 'network_card_ip.ini')
        app.channels = app.store.load()
        app.power_serial_port = app.store.load_power_serial_port()
        app.device_ip_var = tk.StringVar(app, '')
        app.channel_row_vars = {'channel_5': dict(enabled=tk.BooleanVar(app, True), vlan=tk.StringVar(app, ''),
                                                  serial_port=tk.StringVar(app, ''))}
        app._serial_port_for_channel = lambda channel: channel.serial_port
        app._restore_module_window_size = Mock(return_value=(880, 520))
        app._pipeline_ui = Mock()
        app.log_queue = Queue()
        window = self.window_type(app)
        app.update_idletasks()
        window._selection_controls['legacy_power_test'].invoke()
        app.channel_row_vars['channel_5']['enabled'].set(False)
        window._start_button.invoke()
        self.warning.assert_called_once()
        self.dispatch.assert_not_called()
        app.channel_row_vars['channel_5']['enabled'].set(True)
        window._start_button.invoke()
        self.dispatch.assert_called_once()
        ctx = window._running_thread._args[0]
        self.assertEqual(ctx.standalone_power_run.verify(ctx, ctx.app.power_serial_port)['duts'][0]['hardware_id'],
                         self.hardware['B'])
        from src.services.pipeline_orchestrator import PipelineOrchestrator
        from src.services.workspace_resources import WorkspaceResources
        owners = self.base / 'owners'
        query = WorkspaceResources(owners)
        self.addCleanup(query.close)
        query.acquire('offline-query', 'other-project', 'fixture', ['dut:hardware:' + self.hardware['B'].casefold()])
        self.addCleanup(query.release, 'offline-query')
        nic = dict(name='fixture-' + uuid4().hex, guid=str(uuid4()), index=5, up=True,
                   addresses=[('192.0.2.5', 24)])
        with patch('src.services.physical_resource_guards.adapters_ipv4', return_value=[nic]), \
                patch('src.services.physical_resource_guards.host_resource_directory', return_value=owners), \
                patch.object(PipelineOrchestrator, '_run_legacy_power_test') as business:
            window._running_thread.run()
            self.assertIn('PowerAdmissionError', window._run.outcome[1])
            business.assert_not_called()
            self.assertEqual({r.owner_id for r in query.lease_entries()}, {'offline-query'})
        self.connect.assert_not_called()
