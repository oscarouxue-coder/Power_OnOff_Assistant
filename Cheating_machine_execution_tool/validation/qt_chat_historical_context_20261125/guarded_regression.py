"""Run narrowly selected existing tests with synthetic roots and no live I/O."""
from contextlib import ExitStack
from pathlib import Path
import json
import os
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tests'), str(ROOT)]
WRITER = 'test_workspace_event_log.WorkspaceEventLogTests.'
ADAPTER = 'test_qt_workspace_adapter.QtWorkspaceAdapterTests.'
GUI = 'qt_workbench_probe.QtProjectWorkspaceTests.'
GROUPS = {
    'context-service': ['test_qt_ai_turn_display'] + [
        'test_ai_context_usage.UsageMathTests.' + name for name in (
        'test_both_protocols_use_input_plus_output_without_summing_billing_metadata',
        'test_missing_or_malformed_usage_estimates_both_sides_including_tool_arguments',
        'test_zero_usage_is_valid_and_reserves_are_not_used_tokens',
        'test_failed_retries_keep_one_previous_completed_snapshot')] + [
        'test_ai_context_usage.UsageConversationTests.' + name for name in (
        'test_cancel_keeps_completed_usage_and_restart_recovers_it_without_recomputing',
        'test_restart_marks_interrupted_request_cancelled_and_recovers_previous_result',
        'test_old_session_unknown_capacity_and_budget_failure_do_not_invent_actual_usage')],
    'context-native': [GUI + name for name in (
        'test_qt_reopened_chat_displays_only_its_saved_context_usage_as_history',
        'test_qt_ai_chat_sends_and_reopens_original_persisted_history',
        'test_qt_ordinary_reply_event_cancelled_without_body_keeps_request_identity',
        'test_qt_supplement_receipts_survive_late_snapshots_and_only_confirm_next_transport',
    )],
    'p1-service': ['test_qt_log_history'] + [
        'test_qt_migration_contract.QtMigrationContractTests.' + name for name in (
        'test_workspace_startup_failure_reports_existing_instance',
        'test_frozen_and_source_default_to_workspace_and_keep_explicit_previews',
        'test_missing_qt_forwards_arguments_once_or_reports_setup',
        'test_native_verification_keeps_timeout_diagnostics_and_checks_every_scale',
        'test_display_unknowns_are_not_defaulted_to_normal_or_zero')],
    'p1-native': [GUI + name for name in (
        'test_qt_saved_material_report_reopens_exact_history_without_source_read',
        'test_qt_saved_material_summary_uses_selected_history_and_discards_late_reads',
        'test_qt_multi_channel_saved_material_summary_preserves_independent_and_cancelled_results',
    )],
    'resource': ['test_project_management.ProjectManagementTests.' + name for name in (
        'test_power_channel_registration_rejects_overlap_and_releases_on_close',
        'test_existing_conflicting_project_opens_without_owning_conflicting_channel',
        'test_stale_channel_claim_clears_only_after_project_and_worker_exit',
    )],
    'service': [WRITER + name for name in (
        'test_daily_rollover_restart_filters_original_text_and_stable_keyset_paging',
        'test_blocked_disk_keeps_admission_bounded_and_close_waits_for_both_archives',
        'test_unconfirmed_final_archive_does_not_release_callback_ownership',
        'test_one_sink_failure_preserves_original_and_two_sink_failure_reports_on_recovery',
        'test_empty_and_invalid_queries_never_create_files',
    )] + [ADAPTER + name for name in (
        'test_health_tracks_actual_log_failure_and_recovery_separately_from_task_logs',
        'test_update_worker_can_log_after_business_close_and_window_waits_for_disk',
        'test_close_workspace_interrupts_active_sql_scan_and_settles_each_read_once',
        'test_unconfirmed_dirty_close_keeps_worker_and_data_until_explicit_choice',
        'test_session_restores_only_open_projects_in_order_and_remembers_empty_dashboard',
        'test_session_write_failure_keeps_last_clean_exit_and_releases_projects',
        'test_display_backlog_limits_preserve_the_workspace_file',
    )],
    'native': [GUI + name for name in (
        'test_close_waits_for_actual_worker_cleanup',
        'test_closed_workbench_releases_owner_refs_only_after_qt_disposal',
        'test_closed_workbench_retains_owner_refs_when_final_archive_unconfirmed',
        'test_qt_configuration_save_busy_close_keeps_event_loop_responsive',
        'test_qt_manual_update_uses_verified_download_and_waits_for_cancel_cleanup',
        'test_qt_saved_material_error_and_cancel_leave_active_fake_power_job_unchanged',
        'test_qt_multi_channel_saved_material_summary_preserves_independent_and_cancelled_results',
        'test_qt_saved_material_summary_uses_selected_history_and_discards_late_reads',
    )] + ['qt_workbench_probe.QtNativeGuardTests.test_qt_repairs_restart_only_after_worker_and_single_instance_are_closed'],
}

def main():
    group = sys.argv[1]
    with tempfile.TemporaryDirectory(prefix='workspace-close-regression-') as temporary, ExitStack() as scope:
        fixture_root = Path(temporary).resolve()
        local, roaming = fixture_root / 'local', fixture_root / 'roaming'
        local.mkdir()
        roaming.mkdir()
        scope.enter_context(patch.dict(os.environ, LOCALAPPDATA=str(local), APPDATA=str(roaming),
                                       TEMP=str(fixture_root), TMP=str(fixture_root), TMPDIR=str(fixture_root)))
        previous = tempfile.tempdir
        tempfile.tempdir = str(fixture_root)
        scope.callback(setattr, tempfile, 'tempdir', previous)
        guards = {endpoint: scope.enter_context(patch(endpoint, side_effect=AssertionError('live I/O forbidden')))
                  for endpoint in (
                      'requests.sessions.Session.request', 'serial.Serial', 'socket.create_connection',
                      'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyname_ex', 'socket.gethostbyaddr',
                      'socket.socket.connect', 'socket.socket.connect_ex', 'socket.socket.send', 'socket.socket.sendall',
                      'socket.socket.sendto', 'socket.socket.bind', 'socket.socket.listen', 'socket.socket.accept',
                      'subprocess.Popen', 'os.startfile')}
        scope.enter_context(patch('src.core.network_adapter.read_adapter_identities', return_value=()))
        scope.enter_context(patch('src.core.serial_inventory.list_serial_port_names', return_value=[]))
        scope.enter_context(patch('src.services.remote_instance_management.selected_gateway_slot', return_value=None))
        import run_tests
        if group in ('baseline', 'after'):
            from qt_workbench_probe import QtProjectWorkspaceTests
            from src.models.ai_diagnostics import ProviderProfile
            from src.services.ai_case_store import open_shared_cases
            import threading

            class HistoricalContextBaseline(QtProjectWorkspaceTests):
                def test_saved_usage_is_not_shown_after_project_reopen(self):
                    with patch('src.services.ai_project_store.default_ai_data_dir', return_value=self.root / 'legacy-chat'), \
                         patch('src.services.ai_case_store.open_shared_cases',
                               side_effect=lambda emit: open_shared_cases(emit, root=self.root / 'chat-cases')):
                        root = self.root / 'historical-context'
                        self.controller.submit('create', root, '合成历史用量')
                        self.wait_for(lambda: len(self.window.projects) == 1 and self.window.ai_chat_action.isEnabled())
                        project = self.window.selected_project
                        self.controller.adapter._service.models.save_profile(
                            ProviderProfile(model='fixture-context', context_tokens=65536), 'synthetic-context-key')
                        self.window.ai_chat_action.trigger()
                        chat = self.controller.ai_chat
                        self.wait_for(lambda: project in chat.windows and not chat.windows[project].busy)
                        dialog = chat.windows[project]
                        dialog.new_button.click()
                        self.wait_for(lambda: dialog.view and dialog.view.selected and not dialog.busy)
                        chosen = dialog.view.selected
                        snapshot = dict(identity=dict(capacity=65536), state='completed', basis='reply',
                            source='api', input_tokens=12, output_tokens=3, total_tokens=15,
                            updated='2026-11-25T10:00:00+08:00')
                        store = self.controller.adapter._model_settings.stores[project]
                        store.update_chat(chosen, context_usage=snapshot)
                        dialog.close()
                        self.wait_for(lambda: project not in chat.windows)
                        self.controller.submit('close', project, 'discard')
                        self.wait_for(lambda: not self.window.projects)
                        self.controller.submit('open', root)
                        self.wait_for(lambda: self.window.selected_project == project and self.window.ai_chat_action.isEnabled())
                        self.window.ai_chat_action.trigger()
                        self.wait_for(lambda: project in chat.windows and not chat.windows[project].busy)
                        dialog = chat.windows[project]
                        if dialog.view.selected != chosen:
                            row = next(i for i, view in enumerate(dialog.view.sessions) if view.identifier == chosen)
                            dialog.sessions.setCurrentRow(row)
                            self.wait_for(lambda: dialog.view.selected == chosen and not dialog.busy)
                        actual = self.controller.adapter._model_settings.stores[project].chat(chosen)['context_usage']
                        self.assertEqual(actual, snapshot)
                        self.assertFalse(dialog.view.running)
                        observed = dict(persisted_usage_present=True, saved_source=actual['source'],
                                        saved_counts=[actual['input_tokens'], actual['output_tokens'], actual['total_tokens']],
                                        displayed=dialog.usage.text(), running=dialog.view.running)
                        (Path(__file__).resolve().parent / (group + '-observation.json')).write_text(
                            json.dumps(observed, ensure_ascii=False, indent=2), encoding='utf-8')
                        if group == 'baseline':
                            self.assertEqual(dialog.usage.text(), '本轮暂无可核对的模型请求与用量')
                        else:
                            self.assertIn('已保存历史用量（非当前请求）', dialog.usage.text())
                            self.assertIn('接口返回：输入 12，输出 3，合计 15 Token', dialog.usage.text())
            globals()['HistoricalContextBaseline'] = HistoricalContextBaseline
            selected = ['__main__.HistoricalContextBaseline.test_saved_usage_is_not_shown_after_project_reopen']
        else:
            selected = GROUPS[group]
        code = run_tests.main(['-v', *selected])
        counts = {name: guard.call_count for name, guard in guards.items()}
        print('CLOSE_REGRESSION_DENIED: ' + json.dumps(counts), flush=True)
        return code or int(any(counts.values()))

if __name__ == '__main__':
    sys.exit(main())
