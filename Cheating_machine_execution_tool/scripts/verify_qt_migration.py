"""Mandatory native Qt migration checks, using the separate locked Qt environment."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    'test_browse_inspections_and_switch_projects_without_dispatch_or_writes',
    'test_hidden_toolbar_recovers_from_view_menu_and_window_shortcut',
    'test_dut_form_construction_only_shows_the_owned_dialog',
    'test_module_selection_remains_neutral_while_power_is_pending',
    'test_failed_navigation_rejects_before_query_even_for_same_name',
    'test_ui_requires_batch_and_selected_dut',
    'test_toolbar_primary_action_keeps_normal_chat_route',
    'test_ambiguous_frozen_map_rejects_before_submit',
    'test_retry_while_cancelled_reader_is_still_exiting',
    'test_same_channel_other_project_discards_inflight_answer',
    'test_stop_retry_and_late_delivery_use_only_new_request',
    'test_late_result_after_batch_switch_is_discarded',
    'test_chat_uses_explicit_channel_with_real_send_and_literal_evidence',
    'test_chat_missing_ambiguous_sparse_and_expired_stay_local',
    'test_chat_switch_away_and_back_discards_old_receipt_and_keeps_new_query',
    'test_chat_discards_result_after_batch_binding_changes',
    'test_chat_keeps_identity_ordinary_and_continuous_diagnosis_routes',
    'test_chat_stop_button_cancels_only_local_read_and_retry_discards_late_receipt',
    'test_chat_requires_matching_structured_receipt_before_marking_complete',
    'test_chat_reader_failure_never_displays_a_completed_stage',
    'test_sidebar_actions_follow_only_the_rendered_project',
    'test_new_project_previews_and_creates_only_the_confirmed_named_child',
    'test_failed_creation_reports_the_stage_and_allows_correcting_the_same_inputs',
    'test_new_project_rejects_conflicts_invalid_paths_and_late_directory_claim',
    'test_old_draft_requires_reselecting_parent_and_cancel_does_not_create',
    'test_qt_wizard_recovers_legacy_draft_and_uses_main_start_confirmation',
    'test_qt_wizard_saves_selected_field_feed_sources_and_keeps_legacy_defaults',
    'test_main_channel_entry_reuses_saved_configuration_and_keeps_old_dut_history',
    'test_qt_model_presets_derive_saved_plans_and_apply_to_recovered_creation_drafts',
    'test_qt_device_resource_details_follow_real_leases_and_unresolved_protection',
    'test_qt_aging_history_pages_and_exports_only_the_bound_batch',
    'test_qt_switch_preserves_reported_progress_and_separates_health_sources',
    'test_qt_dut_presence_displays_explicit_device_evidence_and_history',
    'test_qt_structured_archive_filters_identity_pages_and_drops_late_receipts',
    'test_progress_animation_reuses_transitions_and_stops_when_hidden',
    'test_project_status_is_consistent_across_navigation_cards_table_and_detail',
    'test_component_showcase_progress_states_controls_and_native_layout',
    'test_qt_monitor_confirms_only_checked_project_channels',
    'test_qt_manual_update_uses_verified_download_and_waits_for_cancel_cleanup',
    'test_qt_device_management_shows_readonly_inventory_and_active_workspace_leases',
    'test_qt_ai_report_dialog_follows_up_on_retained_material',
    'test_qt_reopens_local_device_chat_from_an_older_power_run',
    'test_qt_ai_report_handoff_confirms_legacy_target_without_sending',
    'test_qt_ai_case_confirmation_keeps_source_and_shared_revision',
    'test_qt_ai_report_confirmation_binds_the_project_and_report_ids',
    'test_qt_ai_chat_sends_and_reopens_original_persisted_history',
    'test_qt_reopened_chat_displays_only_its_saved_context_usage_as_history',
    'test_qt_ordinary_reply_event_cancelled_without_body_keeps_request_identity',
    'test_qt_chat_switches_to_configured_local_channel_without_model_or_device',
    'test_qt_chat_reads_only_the_open_project_serial_monitor',
    'test_qt_periodic_refresh_reports_read_failure_without_blocking_other_actions',
    'test_pc_continuous_diagnosis_uses_local_scope_and_keeps_query_evidence',
    'test_qt_supplement_receipts_survive_late_snapshots_and_only_confirm_next_transport',
    'test_qt_session_manager_confirms_exact_batch_and_keeps_other_chat_input',
    'test_qt_model_settings_use_shared_store_and_original_client',
    'test_qt_history_shows_interrupted_job_without_a_review_action',
    'test_qt_reopens_after_stale_resource_without_reviewing_verdict',
    'test_qt_system_health_shows_live_observations_and_collapses',
    'test_qt_archived_logs_pages_original_workspace_and_serial_text_with_local_export',
    'test_qt_imported_connection_uses_confirmed_local_choice_without_connecting',
    'test_qt_instance_status_refresh_close_and_late_reply',
    'test_qt_peer_status_shows_project_routing_and_its_instance',
    'test_qt_instance_pairing_issues_expires_and_confirms_selected_slot',
    'test_qt_instance_startup_save_requires_local_scope_and_survives_reopen',
    'test_qt_remote_scope_confirm_binds_project_ids_and_cancel_preserves_grants',
    'test_qt_configuration_recovers_raw_editor_input_and_confirmed_discard',
    'test_qt_recent_menu_reopens_project_and_forgets_without_closing',
    'test_qt_single_power_uses_selected_port_and_requires_local_confirmation',
    'test_qt_c300_cleanup_lookup_and_confirmation_reuse_original_retry',
    'test_qt_onu_save_keeps_c300_prompt_and_c600_explicit_option',
    'test_qt_onu_registered_delete_follows_confirmed_batch_and_shows_each_result',
    'test_qt_onu_batch_registration_uses_readonly_preview_and_confirmed_ids',
    'test_qt_onu_profiles_discovery_and_stop_from_project_details',
    'test_qt_parameter_serial_observation_waits_for_stop_and_leaves_manual_terminal',
    'test_qt_parameter_window_real_preflight_cancel_and_safe_stop',
    'test_qt_dut_and_parameter_writer_share_project_login_draft',
    'test_live_logs_apply_batches_at_capacity_without_rebuilding_document',
    'test_global_log_filter_pins_project_identity_across_navigation_and_close',
    'test_qt_navigation_opens_saved_template_sources_and_cached_devices',
    'test_overview_metrics_and_filter_follow_project_identity_and_latest_evidence',
    'test_qt_full_upgrade_logs_are_readonly_and_close_with_engine',
    'test_qt_full_upgrade_without_power_requires_manual_restart_acknowledgement',
    'test_qt_firmware_preview_cancel_and_safe_stop_survive_window_reopen',
    'test_qt_legacy_import_menu_uses_original_backup_and_selects_new_project',
    'test_qt_voice_preserves_queried_line_and_original_ordered_codec_write',
    'test_qt_tr069_capability_fields_keep_manual_action_separate_from_query',
    'test_qt_wifi_actual_caps_dual_sync_password_and_responsive_forms',
    'test_qt_wifi_confirm_increment_switch_and_stop_preserve_unverified_state',
    'test_qt_wan_query_shared_details_rules_and_actual_modify_payload',
    'test_qt_wan_different_details_invalidation_switch_and_safe_stop',
    'test_qt_dut_confirmation_query_and_responsive_layout',
    'test_qt_dut_close_switch_reopen_and_stop_wait_for_original_job',
    'test_existing_workspace_receives_open_request_without_second_gui',
    'test_forwarded_project_activates_existing_workspace',
    'test_feishu_sdk_repair_is_opt_in_and_requests_safe_close',
    'test_qt_history_requests_safe_stop_only_after_local_confirmation',
    'test_qt_controlled_extension_preview_starts_unchecked_and_approves_only_reviewed_hash',
    'test_qt_feishu_automatic_notifications_require_local_confirmation',
    'test_platform_credential_dialog_masks_secret_and_saves_only_after_confirmation',
    'test_native_adapter_maps_real_windows_widget',
    'test_qt_repairs_restart_only_after_worker_and_single_instance_are_closed',
    'test_native_adapter_rejects_missing_scope_wrong_thread_and_dialog',
    'test_close_waits_for_actual_worker_cleanup',
    'test_native_new_project_dialog_calls_original_store_and_switches_without_tasks',
    'test_background_thread_cannot_update_presentation',
    'test_cards_table_search_and_navigation_share_identity',
    'test_form_wheel_scrolls_without_editing_values',
    'test_demo_metrics_keep_task_and_health_distinct',
    'test_log_buffer_is_bounded_and_event_loop_stays_responsive',
    'test_qt_log_scopes_and_export_keep_the_exact_job_channel_and_frozen_selection',
    'test_qt_reopens_original_task_history_and_pages_with_project_isolation',
    'test_qt_legacy_run_history_reopens_without_a_job_database',
    'test_project_switch_keeps_snapshots_and_filters_logs',
    'test_responsive_layout_and_native_captures',
    'test_single_card_uses_available_width_and_logs_are_draggable',
    'test_qt_start_switch_stop_and_exit_wait_for_original_job',
    'test_qt_disjoint_project_power_starts_and_stop_is_project_scoped',
    'test_qt_operator_stop_waits_for_original_process_receipt',
    'test_qt_pipeline_choices_prestart_original_serial_terminal_before_environment',
    'test_qt_resume_matrix_list_confirmation_and_after_run_progress',
    'test_qt_postrun_resume_shows_waiting_and_cancels_remaining_channels',
    'test_qt_declined_confirmation_never_starts_a_job',
    'test_qt_configuration_changed_during_confirmation_blocks_dispatch',
    'test_qt_blocker_review_opens_original_project_and_marks_missing_dut_channels',
    'test_qt_blocker_review_waits_for_existing_editor_and_focuses_runtime_field',
    'test_qt_blocker_review_locates_module_controls_without_dispatch',
    'test_qt_blocker_review_keeps_current_project_when_original_is_gone',
    'test_live_refresh_preserves_navigation_selection_and_config_controls',
    'test_qt_six_configuration_tabs_save_and_reopen_original_values',
    'test_qt_pretest_freezes_editor_draft_and_closing_requests_safe_stop',
    'test_qt_version_query_binds_one_channel_and_fills_only_read_only_fields',
    'test_qt_push_trial_uses_confirmed_draft_and_reports_platform_acceptance',
    'test_qt_configuration_cancel_and_reload_keep_original_files',
    'test_qt_configuration_save_remains_bound_when_switching_projects',
    'test_qt_configuration_save_busy_close_keeps_event_loop_responsive',
    'test_channel_matrix_and_list_share_the_same_snapshots',
    'test_qt_channel_editor_preview_cancel_save_and_small_layout',
    'test_qt_channel_resources_filter_and_refresh_without_editing_the_draft',
    'test_qt_toolbar_refresh_updates_another_projects_editor_without_delaying_stop',
    'test_qt_channel_editor_stays_bound_across_project_switch_and_close',
    'test_qt_channel_candidate_rename_confirms_and_keeps_unsaved_fields',
    'test_qt_saved_channel_selection_drives_original_job_targets',
    'test_qt_serial_manual_send_confirmation_and_responsive_layout',
    'test_qt_serial_close_worker_refusal_keeps_live_output_until_retry',
    'test_qt_serial_shared_owner_close_confirmation_and_control_lock',
    'test_qt_serial_passive_snapshot_after_display_clear',
    'test_qt_serial_window_minimize_and_pin_preserve_live_session',
    'test_qt_serial_scrollbar_menu_uses_chinese_and_scrolls',
    'test_qt_serial_scroll_project_switch_and_exit_wait_for_reader',
    'test_qt_tool_windows_restore_project_geometry_and_save_on_parent_close',
    'test_qt_module_windows_restore_legacy_sizes_and_save_through_project_lifecycle',
    'test_qt_project_menu_shortcuts_and_directory_follow_selected_project',
    'test_qt_dut_status_height_restores_adjusts_and_saves_each_tab',
    'test_qt_channel_log_menu_preserves_project_and_current_wifi_attempt',
    'test_qt_channel_history_follows_original_batch_and_after_run_resume',
    'test_qt_history_result_files_open_selected_snapshot_after_workspace_restart',
    'test_qt_saved_material_summary_uses_selected_history_and_discards_late_reads',
    'test_qt_saved_material_report_reopens_exact_history_without_source_read',
    'test_qt_multi_channel_saved_material_summary_preserves_independent_and_cancelled_results',
    'test_qt_saved_material_error_and_cancel_leave_active_fake_power_job_unchanged',
    'test_qt_live_ai_log_is_summarized_and_archived_original_stays_readable',
    'test_qt_chat_formats_markdown_preserves_selection_and_uses_original_shortcuts',
)


# Includes interpreter/desktop startup and native window captures for every case.
# Individual operation and shutdown deadlines remain enforced within each test.
NATIVE_TIMEOUT_SECONDS = 30 + 4 * len(REQUIRED)


def missing_native_cases(output):
    # unittest writes the case prefix before executing the test. A Python warning
    # may sit between that prefix and the outcome on the same stream.
    completed = set(re.findall(
        r'^(test_\w+) \([^\n)]+\) \.\.\. (?:[^\n]*Warning:[^\n]*\n(?:[ \t][^\n]*\n)*)*ok$',
        output, re.M))
    return [name for name in REQUIRED if name not in completed]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    interpreter = args.python or Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'LineCheckAssistant/qt-dev-py39/Scripts/python.exe'
    if not interpreter.is_file():
        parser.error('Qt interpreter missing; run scripts/setup_qt_environment.ps1 -WithBusinessDependencies')
    from verify_gui_test_coverage import check
    errors = check(ROOT)
    if errors:
        print('\n'.join(errors))
        return 1
    sys.path.insert(0, str(ROOT))
    from scripts.gui_test_process import run_gui_child
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for scale in ('1', '1.25', '1.5'):
        directory = output / ('scale-' + scale)
        directory.mkdir(exist_ok=True)
        env = dict(os.environ, QT_SCALE_FACTOR=scale, QT_QPA_PLATFORM='windows',
                   DUTPILOT_QT_CAPTURE_DIRECTORY=str(directory), PYTHONFAULTHANDLER='1')
        try:
            result = run_gui_child([str(interpreter), str(ROOT / 'scripts/run_tests.py'), 'qt_workbench_probe',
                                    'qt_project_wizard_probe', 'qt_typed_status_probe', 'qt_channel_evidence_probe',
                                    'qt_aging_inspection_probe', '-v'],
                framework='qt', native_render=True, cwd=str(ROOT), timeout=NATIVE_TIMEOUT_SECONDS,
                capture_output=True, text=True, encoding='utf-8', env=env)
            text = result.stdout + '\n' + result.stderr
            (directory / 'tests.txt').write_text(text, encoding='utf-8')
            count = re.search(r'Ran (\d+) tests', text)
            missing = missing_native_cases(text)
            passed = result.returncode == 0 and count and int(count[1]) == len(REQUIRED) and not missing
            results.append(dict(scale=scale, passed=bool(passed), tests=int(count[1]) if count else 0,
                                missing=missing, evidence=result.offscreen_report))
        except (AssertionError, OSError) as error:
            (directory / 'tests.txt').write_text(str(error), encoding='utf-8')
            results.append(dict(scale=scale, passed=False, error=str(error)))
        except subprocess.TimeoutExpired as error:
            output_so_far = '\n'.join(stream.decode('utf-8', errors='replace') if isinstance(stream, bytes) else stream
                                      for stream in (error.stdout, error.stderr) if stream)
            message = f'Qt native suite exceeded {error.timeout} seconds'
            (directory / 'tests.txt').write_text(output_so_far + '\n' + message, encoding='utf-8')
            results.append(dict(scale=scale, passed=False, error=message))
        print('QT_NATIVE_SCALE', scale, 'PASS' if results[-1]['passed'] else 'FAIL', flush=True)
    (output / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if all(row['passed'] for row in results) else 1


if __name__ == '__main__':
    sys.exit(main())
