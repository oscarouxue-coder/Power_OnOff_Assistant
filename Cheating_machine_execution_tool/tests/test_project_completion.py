"""Project status and pre-conversion backups; temporary inputs, no live devices."""
import hashlib
import gc
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.services.project_store import ProjectStore, atomic_json
from src.services.project_status_service import ProjectStatusService
from src.services.project_runtime import current_run, start_project_thread, report_project_result
import test_project_workspace as _fixture

SOURCE = Path(__file__).resolve().parents[1]


class StatusAndBackupTests(unittest.TestCase):
    def setUp(self):
        gc.collect()  # Retired Tk graphs from earlier GUI fixtures belong to the UI thread.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = ProjectStore(SOURCE)
        self.context = self.store.create(self.root / 'project', '状态项目')
        self.addCleanup(self.store.close, self.context)
        self.status = ProjectStatusService()

    def begin(self, owner='owner'):
        path = self.store.snapshot(self.context)
        self.status.begin(self.context, owner, path, 'fake_operation')
        return path

    def test_result_is_structured_and_durable_after_reopening(self):
        path = self.begin()
        self.status.update('owner', 'running')
        self.status.complete('owner', dict(ok=False, message='success text must not override failure'))
        self.assertEqual('failed', self.status.snapshot(self.context).state)
        other = ProjectStatusService()
        self.assertEqual('failed', other.snapshot(self.context).state)
        self.assertEqual('failed', json.loads((path / 'run.json').read_text(encoding='utf-8'))['state'])

    def test_moved_project_reloads_runtime_paths_without_recreating_old_directory(self):
        self.begin()
        self.status.complete('owner', state='unknown')
        original = self.context.root
        self.store.close(self.context)
        moved = self.root / 'moved-project'
        original.rename(moved)
        reopened = self.store.open(moved)
        try:
            self.assertEqual('unknown', self.status.snapshot(reopened).state)
            self.status.reconcile('owner')
            self.assertFalse(original.exists())
            record = self.status.records['owner']
            self.assertIn(moved, record['_path'].parents)
            self.assertTrue(json.loads(record['_path'].read_text(encoding='utf-8'))['reconciled'])
        finally:
            self.store.close(reopened)

    def test_running_with_unknown_shows_attention_and_never_hides_unknown_count(self):
        self.begin('old')
        self.status.update('old', 'running')
        self.status.complete('old', state='unknown')
        self.begin('new')
        self.status.update('new', 'running')
        value = self.status.snapshot(self.context)
        self.assertEqual(('running', 1, 1), (value.state, value.active_task_count, value.unknown_task_count))
        self.assertIn('!', value.label)
        self.status.complete('new', True)
        self.assertEqual('unknown', self.status.snapshot(self.context).state)
        self.status.reconcile('old', 'stopped')
        self.assertEqual(0, self.status.snapshot(self.context).unknown_task_count)

    def test_interrupted_running_record_becomes_unknown_without_replay(self):
        self.begin()
        self.status.update('owner', 'running')
        restarted = ProjectStatusService()
        self.assertEqual('unknown', restarted.snapshot(self.context).state)
        self.status.complete('owner', False)

    def test_prepared_cancel_is_skipped_not_a_success(self):
        self.begin()
        self.status.finish_unreported('owner')
        self.assertEqual('skipped', self.status.records['owner']['state'])

    def test_late_completion_cannot_resurrect_old_run_or_overwrite_other_project(self):
        self.begin()
        self.status.complete('owner', False)
        self.status.complete('owner', True)
        self.assertEqual('failed', self.status.snapshot(self.context).last_result)
        other = self.store.create(self.root / 'other', '另一个项目')
        try:
            self.assertEqual('idle', self.status.snapshot(other).state)
        finally:
            self.store.close(other)

    def test_thread_context_returns_to_original_run(self):
        self.begin()
        token = current_run.set((self.status, 'owner'))
        try:
            thread = threading.Thread(target=lambda: report_project_result(dict(ok=False)))
            start_project_thread(thread)
        finally:
            current_run.reset(token)
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual('failed', self.status.snapshot(self.context).state)

    def test_status_write_error_is_reported_and_does_not_change_business_result(self):
        self.begin()
        messages = []
        self.status.emit = messages.append
        with patch('src.services.project_status_service.atomic_json', side_effect=OSError('full')):
            self.status.complete('owner', True)
        self.assertEqual('succeeded', self.status.snapshot(self.context).last_result)
        self.assertTrue(messages)

    def test_uncertain_onu_and_unchecked_pretest_cannot_be_reported_as_success(self):
        from src.services.project_status_service import result_state
        self.assertEqual('unknown', result_state(SimpleNamespace(ok=False, outcome_uncertain=True)))
        self.assertEqual('unchecked', result_state(SimpleNamespace(executed=1, unchecked=1, failed=0, device_errors=0)))

    def test_worker_uses_frozen_config_and_ui_callback_returns_to_draft(self):
        from src.models.project_task import task_path, capture_ui_context
        path = self.begin()
        original = self.context.config_dir / 'test_project_config.ini'
        observed = []
        def work():
            observed.append(task_path(original))
            ui = capture_ui_context()
            observed.append(ui.run(task_path, original))
            report_project_result(True)
        token = current_run.set((self.status, 'owner'))
        try:
            thread = threading.Thread(target=work)
            start_project_thread(thread)
        finally:
            current_run.reset(token)
        thread.join(2)
        self.assertEqual([path / 'Auto_power_on_off_tool/config/test_project_config.ini', original], observed)

    def test_gui_reconciliation_preserves_unknown_result_without_inventing_a_verdict(self):
        self.begin()
        self.status.complete('owner', state='unknown')
        self.status.reconcile('owner')
        value = self.status.snapshot(self.context)
        self.assertEqual('unknown', value.last_result)
        self.assertEqual(0, value.unknown_task_count)
        self.assertEqual('idle', value.state)
        self.assertIn('原结果未知', value.detail)

    def test_resume_and_pretest_stopping_remain_visible_after_original_pipeline_finishes(self):
        from src.services.project_execution import project_busy, project_stopping
        cancel = threading.Event(); cancel.set()
        view = SimpleNamespace(power_test_resume_session=SimpleNamespace(is_recovering=True, stop_event=cancel))
        self.assertTrue(project_busy(view))
        self.assertTrue(project_stopping(view))
        view = SimpleNamespace(test_item_pretest_controls=SimpleNamespace(running=True, cancel=cancel))
        self.assertTrue(project_busy(view))
        self.assertTrue(project_stopping(view))

    def test_registration_success_does_not_hide_a_following_write_failure(self):
        from types import MethodType
        from line_check_assistant.app import LineCheckAssistant
        self.begin()
        self.status.update('owner', 'running')
        callbacks = []
        view = SimpleNamespace(onu_cancel_event=threading.Event(), _log=lambda line: None,
            after=lambda delay, callback: callbacks.append(callback), onu_unregistered_selection_vars=(),
            _set_onu_registration_action_buttons_state=lambda state: None,
            _set_onu_query_status=lambda *args: None,
            _onu_save_olt_configuration_worker=lambda *args: report_project_result(False))
        view._complete_onu_register_selected = MethodType(LineCheckAssistant._complete_onu_register_selected, view)
        result = SimpleNamespace(ok=True, message='simulated registration succeeded')
        token = current_run.set((self.status, 'owner'))
        try:
            with patch('line_check_assistant.app.OnuRegistrationService') as factory:
                factory.return_value.register.return_value = result
                LineCheckAssistant._onu_register_selected_worker(view, 'C600', SimpleNamespace(host='fake'), [], None, True)
            self.assertEqual('', self.status.snapshot(self.context).last_result)
            callbacks[0]()
        finally:
            current_run.reset(token)
        for worker in view._background_workers:
            worker.join(2)
        self.assertEqual('failed', self.status.snapshot(self.context).last_result)

    def imported(self, name='imported'):
        config = self.root / 'legacy' / 'Auto_power_on_off_tool' / 'config'
        config.mkdir(parents=True, exist_ok=True)
        original = b'[project_info]\r\nproject_name=original\r\n[custom]\r\nvalue=keep  spaces\r\n'
        (config / 'test_project_config.ini').write_bytes(original)
        context = self.store.create(self.root / name, name, import_directory=config)
        self.addCleanup(self.store.close, context)
        return context, config, original

    def test_import_has_verified_original_bytes_before_conversion(self):
        context, config, original = self.imported()
        backup = self.store.import_backups[context.identity.project_id]
        self.assertEqual(original, (backup / 'config/test_project_config.ini').read_bytes())
        manifest = json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual('complete', manifest['state'])
        self.assertEqual(hashlib.sha256(original).hexdigest(), manifest['files'][0]['sha256'])
        self.assertEqual(original, (config / 'test_project_config.ini').read_bytes())
        self.assertNotEqual(original, (context.config_dir / 'test_project_config.ini').read_bytes())

    def test_backup_failure_stops_before_manifest_conversion(self):
        config = self.root / 'source'; config.mkdir()
        (config / 'test_project_config.ini').write_text('[project_info]\nproject_name=x', encoding='utf-8')
        with patch('src.services.project_import_service.shutil.copy2', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.store.create(self.root / 'failed', 'failed', import_directory=config)
        self.assertFalse((self.root / 'failed/project.linecheck.json').exists())
        manifest = next((self.root / 'failed/backups').rglob('manifest.json'))
        self.assertEqual('failed', json.loads(manifest.read_text(encoding='utf-8'))['state'])

    def test_changed_input_during_backup_stops_conversion(self):
        import shutil
        config = self.root / 'changing'; config.mkdir()
        path = config / 'test_project_config.ini'
        path.write_text('[project_info]\nproject_name=old', encoding='utf-8')
        original_copy = shutil.copy2
        def copy(origin, target):
            result = original_copy(origin, target)
            path.write_text('[project_info]\nproject_name=changed', encoding='utf-8')
            return result
        with patch('src.services.project_import_service.shutil.copy2', side_effect=copy):
            with self.assertRaisesRegex(ValueError, '变化'):
                self.store.create(self.root / 'changed-target', 'test', import_directory=config)
        self.assertFalse((self.root / 'changed-target/project.linecheck.json').exists())

    def test_firmware_in_source_directory_remains_a_reference_not_a_backup_copy(self):
        config = self.root / 'firmware-source'; config.mkdir()
        (config / 'test_project_config.ini').write_text('[project_info]\nproject_name=x', encoding='utf-8')
        (config / 'firmware.bin').write_bytes(b'SIMULATED LARGE FILE')
        context = self.store.create(self.root / 'firmware-import', 'test', import_directory=config)
        try:
            backup = self.store.import_backups[context.identity.project_id]
            manifest = json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))
            self.assertIn('firmware.bin', manifest['excluded_non_configuration'])
            self.assertFalse((backup / 'config/firmware.bin').exists())
        finally:
            self.store.close(context)

    def test_database_snapshot_is_preserved_before_history_sanitization(self):
        history = self.root / 'old-ai'; history.mkdir()
        with sqlite3.connect(str(history / 'diagnostics.sqlite3')) as database:
            database.execute('CREATE TABLE recovery(id TEXT,payload TEXT,state TEXT)')
            database.execute("INSERT INTO recovery VALUES('old','{}','pending')")
        with patch('src.services.ai_project_store.project_directory', return_value=history):
            context, config, _ = self.imported()
            self.store.import_history(context, config.parent.parent)
        backup = self.store.import_backups[context.identity.project_id]
        with sqlite3.connect(str(backup / 'history/diagnostics.sqlite3')) as database:
            self.assertEqual(1, database.execute('SELECT count(*) FROM recovery').fetchone()[0])
        with sqlite3.connect(str(context.history / 'ai/diagnostics.sqlite3')) as database:
            self.assertEqual(0, database.execute('SELECT count(*) FROM recovery').fetchone()[0])

    def test_failed_coordinated_import_cannot_be_opened_as_a_complete_project(self):
        from src.services.workspace_service import WorkspaceService
        service = WorkspaceService(SOURCE, self.root / 'user')
        try:
            source = self.root / 'source'; source.mkdir()
            (source / 'test_project_config.ini').write_text('[project_info]\nproject_name=x', encoding='utf-8')
            with patch.object(service, 'import_connections', side_effect=ValueError('unreadable connection')):
                with self.assertRaises(ValueError):
                    service.import_project(source, self.root / 'failed-import', 'failed')
            with self.assertRaisesRegex(ValueError, '导入未完成'):
                service.projects.open(self.root / 'failed-import')
        finally:
            service.close()


class CompletionGuiTests(unittest.TestCase):
    add = _fixture.ProjectWorkspaceTests.add

    def setUp(self):
        gc.collect()
        _fixture.ProjectWorkspaceTests.setUp(self)

    def close(self):
        _fixture.ProjectWorkspaceTests.close(self)
        self.root = None
        self.service = None
        gc.collect()

    def test_sidebar_and_local_query_share_status_without_looking_at_current_project(self):
        a, b = self.add('A'), self.add('B')
        owner = self.root.admit_operation(a, '_run_checks')
        self.service.status.update(owner, 'running')
        self.service.status.complete(owner, False)
        self.root.select_project(b.project_context.identity.project_id)
        self.root.next_status = 0
        self.root.after_cancel(self.root._poll_id)
        self.root._poll()
        projects = {p['project_id']: p for p in self.service.list_projects()}
        self.assertEqual('failed', projects[a.project_context.identity.project_id]['state'])
        self.assertEqual('失败', self.root.tree.item(a.project_context.identity.project_id, 'values')[0])
        self.assertEqual('idle', projects[b.project_context.identity.project_id]['state'])
        self.root.status_tooltip.row = a.project_context.identity.project_id
        self.root.status_tooltip.show()
        self.assertIsNotNone(self.root.status_tooltip.popup)
        self.root.status_tooltip.hide()

    def test_late_after_callback_keeps_original_task_identity(self):
        a, b = self.add('A'), self.add('B')
        owner = self.root.admit_operation(a, '_run_checks')
        token = current_run.set((self.service.status, owner))
        try:
            a.after(0, lambda: report_project_result(False))
        finally:
            current_run.reset(token)
        self.root.select_project(b.project_context.identity.project_id)
        self.root.update()
        self.assertEqual('failed', self.service.status.snapshot(a.project_context).state)
        self.assertEqual('idle', self.service.status.snapshot(b.project_context).state)

    def test_gui_unknown_preserves_resource_guard_until_explicit_local_review(self):
        a = self.add('未知结果')
        a.channels[0].enabled = True
        a.channels[0].adapter_alias = a.channels[0].vlan_name = 'simulated999'
        a._rebuild_channel_config_rows()
        self.root.save_project(a)
        owner = self.root.admit_operation(a, '_run_checks')
        self.service.status.update(owner, 'running')
        self.service.status.complete(owner, state='unknown')
        self.root.track_operation(a, owner)
        self.root.tickets[owner]['started'] -= 1
        self.root.after_cancel(self.root._poll_id)
        self.root._poll()
        self.assertIn(owner, dict(self.service.resources.unknown_gui()))
        from src.services.power_worker_lifetime import ACTIVE, CapabilityError
        with patch.dict(self.service.status.records[owner], operation='_on_start'), \
                patch('src.services.power_worker_lifetime.power_worker_notice', return_value=ACTIVE):
            with self.assertRaisesRegex(CapabilityError, ACTIVE):
                self.service.resolve_gui_unknown(owner, '模拟执行器仍在运行')
            self.assertIn(owner, dict(self.service.resources.unknown_gui()))
            self.assertFalse((self.service.directory / 'reconciliations').exists())
        self.service.resolve_gui_unknown(owner, 'simulated-only local evidence')
        self.service.refresh_status(a.project_context)
        self.assertEqual(0, self.service.status.snapshot(a.project_context).unknown_task_count)
        self.assertEqual('unknown', self.service.status.snapshot(a.project_context).last_result)

    def test_modal_result_handoff_keeps_lease_until_decision_returns(self):
        from src.services.project_runtime import project_result_handoff
        view = self.add('确认归属')
        owner = self.root.admit_operation(view, '_run_checks')
        self.service.status.update(owner, 'running')
        self.root.track_operation(view, owner)
        self.root.tickets[owner]['started'] -= 1
        @project_result_handoff
        def confirmation():
            self.root.after_cancel(self.root._poll_id)
            self.root._poll()
            self.assertIn(owner, self.root.tickets)
            self.assertNotIn(owner, dict(self.service.resources.unknown_gui()))
            report_project_result(True)
        token = current_run.set((self.service.status, owner))
        try:
            confirmation()
        finally:
            current_run.reset(token)
        self.assertFalse(self.service.status.is_held(owner))

    def test_new_project_timer_does_not_inherit_another_project_modal_run(self):
        a, b = self.add('A'), self.add('B')
        owner = self.root.admit_operation(a, '_run_checks')
        token = current_run.set((self.service.status, owner))
        try:
            b.after(0, lambda: report_project_result(False))
        finally:
            current_run.reset(token)
        self.root.update()
        self.assertEqual('', self.service.status.snapshot(a.project_context).last_result)
        self.assertEqual('', self.service.status.snapshot(b.project_context).last_result)

    def test_four_real_gui_workers_keep_identity_through_switch_and_save(self):
        from copy import deepcopy
        from project_validation_fixtures import Gate, ValidationSandbox, active_fixture
        from src.services.upgrade_stop_service import UpgradeStopControl
        views = [self.add('GUI ' + str(index)) for index in range(4)]
        gates = [Gate() for _ in views]
        with ValidationSandbox():
            try:
                for index, (view, gate) in enumerate(zip(views, gates)):
                    channel = deepcopy(view.channels[0])
                    channel.enabled = True
                    channel.vlan_name, channel.adapter_alias = 'vlan101', 'simulated' + str(index)
                    channel.network_card_ip, channel.device_manage_ip = '192.0.2.' + str(index + 1), '192.0.2.254'
                    token = active_fixture.set((gate, UpgradeStopControl(), lambda line: None))
                    try:
                        with patch.object(view, '_validate_channels', return_value=''):
                            view._run_checks([channel])
                    finally:
                        active_fixture.reset(token)
                self.assertTrue(all(gate.entered.wait(3) for gate in gates))
                for view in views:
                    self.root.select_project(view.project_context.identity.project_id)
                    self.root.save_project(view)
                self.assertTrue(all(view.running for view in views))
            finally:
                for gate in gates:
                    gate.proceed.set()
            deadline = time.monotonic() + 4
            while any(view.running for view in views) and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
        self.assertFalse(any(view.running for view in views))
        self.assertTrue(all(self.service.status.snapshot(view.project_context).last_result == 'succeeded' for view in views))
        self.assertFalse(self.errors)


if __name__ == '__main__':
    unittest.main()
