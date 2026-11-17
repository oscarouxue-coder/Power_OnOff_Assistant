from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from tk_test_windows import OffscreenTkWindows
from src.services.workspace_service import WorkspaceService
from src.ui.project_workspace import ProjectWorkspace
from src.models.project_task import project_task_scope


SOURCE = Path(__file__).resolve().parents[1]


class ProjectWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='工作区 test ')
        self.addCleanup(self.temporary.cleanup)
        self.windows = OffscreenTkWindows()
        self.windows.__enter__()
        self.addCleanup(self.windows.__exit__, None, None, None)
        self.patches = [patch('line_check_assistant.app.' + name, return_value=[]) for name in
                        ('list_adapter_display_names', 'list_prolific_ports', 'list_serial_port_names')]
        self.patches += [patch('line_check_assistant.app.LineCheckAssistant._show_startup_warnings'),
                         patch('src.services.remote_instance_management.selected_gateway_slot', return_value=None),
                         patch('src.services.transport_history_monitor.TransportHistoryMonitor')]
        for context in self.patches:
            value = context.start()
            self.addCleanup(context.stop)
        value.return_value.idle = True
        self.service = WorkspaceService(SOURCE, Path(self.temporary.name) / 'user')
        self.root = ProjectWorkspace(SOURCE, service=self.service)
        self.errors = []
        self.root.report_callback_exception = lambda kind, error, trace: self.errors.append(error)
        self.addCleanup(self.close)

    def close(self):
        for view in tuple(self.root.views.values()):
            view._on_app_close()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.root.update()
            if not self.root.views:
                break
            time.sleep(.02)
        self.service.begin_close()
        self.root.destroy()
        for context in tuple(self.service.projects.opened.values()):
            self.service.projects.close(context)
        self.service.close()

    def add(self, name):
        context = self.service.projects.create(Path(self.temporary.name) / name, name)
        self.root._add_project(context)
        view = self.root.current_view()
        self.assertTrue(self.root.save_project(view))
        return view

    def test_four_views_share_one_tk_root_and_keep_their_own_configuration(self):
        views = [self.add('项目 ' + str(n)) for n in range(4)]
        for n, view in enumerate(views):
            self.assertIs(view.winfo_toplevel(), self.root)
            self.assertEqual(view.store.config_path.parent, view.project_context.config_dir)
            view.upgrade_username_var.set('simulated-' + str(n))
            self.root.save_project(view)
        for n, view in enumerate(views):
            self.assertEqual(view.sample_upgrade_settings_store.load().username, 'simulated-' + str(n))
        self.root.update()
        self.windows.assert_offscreen()
        self.assertFalse(self.errors)

    def test_collapsing_sidebar_and_switching_does_not_cancel_running_project(self):
        a, b = self.add('A'), self.add('B')
        a.power_test_running = True
        try:
            self.root.toggle_sidebar()
            self.root.select_project(a.project_context.identity.project_id)
            self.root.select_project(b.project_context.identity.project_id)
            self.assertTrue(a.power_test_running)
            self.assertFalse(self.root.sidebar.winfo_manager())
            self.root.toggle_sidebar()
            self.assertEqual(self.root.sidebar.winfo_manager(), 'pack')
        finally:
            a.power_test_running = False

    def test_closing_background_project_keeps_current_selection(self):
        a, b = self.add('A'), self.add('B')
        self.root.select_project(a.project_context.identity.project_id)
        b._on_app_close()
        self.root.update()
        self.assertIs(self.root.current_view(), a)

    def test_admitted_configuration_path_stays_fixed_after_save_and_switch(self):
        from line_check_assistant.test_item_config_store import TestItemConfigStore
        a, b = self.add('A'), self.add('B')
        snapshot = self.service.projects.snapshot(a.project_context)
        store = TestItemConfigStore(a.project_context.config_dir / 'test_project_config.ini')
        barrier = threading.Barrier(2)
        def run():
            with project_task_scope(a.project_context.working_root, snapshot):
                barrier.wait(timeout=3)
                barrier.wait(timeout=3)
                return store.load().project_info.project_name
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(run)
            barrier.wait(timeout=3)
            self.service.projects.rename(a.project_context, 'A新名称')
            self.root.select_project(b.project_context.identity.project_id)
            barrier.wait(timeout=3)
            self.assertEqual(future.result(timeout=3), 'A')
        self.assertEqual(store.load().project_info.project_name, 'A新名称')

    def test_pending_callback_of_closed_view_cannot_modify_another_project(self):
        a, b = self.add('A'), self.add('B')
        called = []
        a.after(10, lambda: called.append('a'))
        a._on_app_close()
        time.sleep(.02)
        self.root.update()
        self.assertEqual(called, [])
        self.assertIs(self.root.current_view(), b)
        self.assertFalse(self.errors)

    def test_four_admitted_fake_runs_and_stopping_one_preserves_the_other_three(self):
        views = [self.add('并行 ' + str(n)) for n in range(4)]
        owners = []
        for n, view in enumerate(views):
            view.channels[0].enabled = True
            view.channels[0].vlan_name = 'simulated' + str(n)
            view._rebuild_channel_config_rows()
            self.assertTrue(self.root.save_project(view))
            owner = self.root.admit_operation(view, '_run_checks')
            self.assertIsNotNone(owner)
            owners.append(owner)
            view.running = True
            self.root.track_operation(view, owner)
        try:
            self.assertEqual(len(self.service.resources.owners), 4)
            for entry in self.root.tickets.values():
                entry['started'] -= 1
            views[0].running = False
            self.root.select_project(views[2].project_context.identity.project_id)
            self.root.after_cancel(self.root._poll_id)
            self.root._poll()
            self.assertNotIn(owners[0], self.service.resources.owners)
            self.assertTrue(all(view.running for view in views[1:]))
            self.assertEqual(len(self.service.resources.owners), 3)
        finally:
            for view in views:
                view.running = False

    def test_cancelled_application_close_does_not_discard_an_earlier_project_draft(self):
        a, b = self.add('A'), self.add('B')
        for view in (a, b):
            view.upgrade_username_var.set('unsaved-' + view.project_context.identity.name)
            self.root.flush_draft(view)
        with patch('src.ui.project_workspace.messagebox.askyesnocancel', side_effect=[False, None]):
            self.root.close_application()
        self.assertFalse(self.root.closing)
        self.assertEqual(a.sample_upgrade_settings_store.load().username, 'unsaved-A')
        self.assertTrue(self.root.is_dirty(a))
        self.assertTrue(self.root.is_dirty(b))

    def test_view_construction_failure_releases_project_lease(self):
        context = self.service.projects.create(Path(self.temporary.name) / 'failed', 'failed')
        self.root.view_factory = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('simulated view failure'))
        with self.assertRaisesRegex(RuntimeError, 'simulated view failure'):
            self.root._add_project(context)
        self.assertNotIn(context.identity.project_id, self.service.projects.opened)
        self.assertNotIn(context.identity.project_id, self.service.projects.leases)
        self.assertFalse(self.root.views)

    def test_invalid_editor_input_is_recovered_without_committing_or_executing(self):
        view = self.add('恢复草稿')
        original_revision = view.project_context.identity.revision
        view._open_test_item_config()
        recovery = view._project_editor_recovery
        spin = next(widget for widget in recovery.widgets().values() if widget.winfo_class() == 'TSpinbox')
        recovery.dialog.setvar(spin.cget('textvariable'), 'not-a-number')
        recovery.flush()
        recovery.dialog.destroy()
        view.test_item_config_window = None
        view.test_item_pretest_controls = None
        with patch('line_check_assistant.app.messagebox.askyesno', return_value=True):
            view._open_test_item_config()
        recovered = view._project_editor_recovery
        self.assertTrue(any(widget.get() == 'not-a-number' for widget in recovered.widgets().values()
                            if widget.winfo_class() == 'TSpinbox'))
        with patch('line_check_assistant.app.messagebox.showerror'), patch('src.ui.project_workspace.messagebox.showerror'):
            self.assertFalse(self.root.save_project(view))
        self.assertEqual(view.project_context.identity.revision, original_revision)
        self.assertTrue(recovered.path.exists())
        self.assertFalse(self.service.resources.owners)

    def test_two_real_ai_controllers_share_models_but_not_conversations_or_business_storage(self):
        from src.services.ai_case_store import SharedCaseStore
        a, b = self.add('AI A'), self.add('AI B')
        root = Path(self.temporary.name)
        with patch('src.services.ai_project_store.default_ai_data_dir', return_value=root / 'legacy'), \
                patch('src.services.ai_case_store.open_shared_cases', side_effect=lambda emit: SharedCaseStore(root / 'cases')):
            a._open_ai_assistant(show=False)
            b._open_ai_assistant(show=False)
        ai_a, ai_b = a.ai_assistant, b.ai_assistant
        self.assertIs(ai_a.service.store.models, ai_b.service.store.models)
        self.assertIsNot(ai_a.conversation, ai_b.conversation)
        self.assertNotEqual(ai_a.capabilities.jobs.directory, ai_b.capabilities.jobs.directory)
        self.assertIs(ai_a.capabilities.resources.coordinator, self.service.resources)
        self.assertIs(ai_b.capabilities.resources.coordinator, self.service.resources)
        self.assertIn('workspace.projects.list', [v['capability_id'] for v in ai_a.capabilities.registry.list()])
        self.assertFalse(self.service.remote_projects)
        self.assertTrue(all(pool.transport is None for pool in self.service.platforms.values()))
        from src.services.workspace_platforms import PooledLease
        starts = []
        class Transport:
            def __init__(self, *args, **kwargs):
                self.idle = False
            def start(self):
                starts.append('started')
            def begin_close(self):
                self.idle = True
        for pool in self.service.platforms.values():
            pool.transport_factory, pool.lease_factory = Transport, PooledLease
        self.service.set_remote_projects([a.project_context.identity.project_id, b.project_context.identity.project_id])
        for kind in ('dingtalk', 'feishu'):
            config = self.service.platform_config(kind)
            value = config.load()
            if kind == 'dingtalk':
                value.update(enabled=True, isolated=True, client_id='fake-client', client_secret='fake-secret',
                    robot_code='fake-bot', group='fake-group', corp='fake-corp', webhook='https://example.invalid/hook')
            else:
                value.update(enabled=True, isolated=True, group_enabled=True, app_id='fake-app', app_secret='fake-secret',
                             group='fake-group', corp='fake-corp')
            config.save(value)
            remote = ai_a.remote if kind == 'dingtalk' else ai_a.feishu_remote
            self.assertIsNotNone(remote)
            self.service._synchronize_remote(kind, remote, value)
            self.service.synchronize_platforms()
            self.assertEqual(len(self.service.platforms[kind].members), 2)
            value['enabled'] = False
            if kind == 'feishu':
                value['group_enabled'] = False
            config.save(value)
            self.service.synchronize_platforms()
            self.assertFalse(self.service.platforms[kind].members)
        self.assertEqual(starts, ['started', 'started'])
        self.assertFalse(self.service._platform_errors)

    def test_verified_adapter_rename_updates_other_project_draft_without_committing_saved_revision(self):
        from src.models.network_adapter import AdapterIdentity, AdapterRenameResult
        a, b = self.add('A'), self.add('B')
        for view in (a, b):
            view.channels[0].enabled = True
            view.channels[0].vlan_name = view.channels[0].adapter_alias = 'simulated101'
            view._rebuild_channel_config_rows()
            self.root.save_project(view)
        revision = b.project_context.identity.revision
        result = AdapterRenameResult(True, 'fake verified', (AdapterIdentity('simulated102', '{fake-guid}'),))
        self.root.synchronize_adapter_names(a, 'simulated101', 'simulated102', result)
        self.assertEqual(b.channels[0].vlan_name, 'simulated102')
        self.assertEqual(b.project_context.identity.revision, revision)
        self.assertTrue(self.root.is_dirty(b))


if __name__ == '__main__':
    unittest.main()
