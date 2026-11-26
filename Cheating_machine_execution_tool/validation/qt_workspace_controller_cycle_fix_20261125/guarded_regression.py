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
        code = run_tests.main(['-v', *GROUPS[group]])
        counts = {name: guard.call_count for name, guard in guards.items()}
        print('CLOSE_REGRESSION_DENIED: ' + json.dumps(counts), flush=True)
        return code or int(any(counts.values()))

if __name__ == '__main__':
    sys.exit(main())
