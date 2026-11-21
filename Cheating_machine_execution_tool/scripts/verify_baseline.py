"""项目级回归基线检查脚本(Q1=A 的工程兑现)。

封装 `ACCEPTANCE_BASELINE.md §0 / §1.3 / §1.4` 的全部检查,作为提交前必跑的最低门禁
(参见 `AGENTS.md` 规则 13 与 `.claude/skills/line-check-dev/SKILL.md §5 / §11`)。

执行 8 类检查:
1. **py_compile**: 全量 `src/` + `line_check_assistant/` 下的关键模块能编译
2. **compile_inventory**: `src/` / `line_check_assistant/` 的每个 Python 源文件都必须纳入编译清单
3. **unittest**: 全量测试通过,且能解析 `Ran N tests` 行(防止静默 0 项 / 误报 OK)
4. **required_baseline_tests**: 已验收关键行为的指定测试 ID 必须实际执行
5. **must_exist**: §1.3 的 8 条协议不变量必须在指定目录下命中
6. **must_not_exist**: §1.3 / §1.4 的禁止模式(`0.0.0.0` 等)不能在指定文件的**代码行**中出现
   (跳过注释 / 文档字符串,避免反向语义误报)
7. **capability_coverage**: 新增/改变GUI业务动作必须审查，业务覆盖清单不能遗漏或虚报。
8. **gui_test_coverage**: GUI测试离屏覆盖预检，失败不启动测试；运行时严格守卫保留失败退出码。

退出码: 0 全部通过 / 1 任一失败。

设计要点:
- **单一来源**: `MUST_EXIST` / `MUST_NOT_EXIST` / `PY_COMPILE_FILES` 三个常量在本文件;
  `AGENTS.md` 中同名章节是可读副本,改任何一处都必须同步另一处。
- **跨平台**: 纯 Python + 标准库,Windows / Linux / macOS 直接可跑。
- **可测试**: 核心检查函数是纯函数,接受 `project_root: Path`,用 `tempfile.TemporaryDirectory`
  构造临时源码即可单元测试(参见 `tests/test_verify_baseline.py`)。
- **不引入新依赖**: 仅用 `subprocess` / `pathlib` / `re` / `sys`。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, NamedTuple


# 匹配三引号字符串(文档字符串 / 长字符串),用于在 grep 时跳过。
_DOCSTRING_PATTERN = re.compile(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', re.MULTILINE)


class CheckResult(NamedTuple):
    """单条检查结果。"""

    name: str
    passed: bool
    detail: str = ""

    def render(self) -> str:
        marker = "OK  " if self.passed else "FAIL"
        suffix = f" - {self.detail}" if self.detail else ""
        return f"  [{marker}] {self.name}{suffix}"


# 1. py_compile 文件清单(以 `ACCEPTANCE_BASELINE.md §0` + 当前 `src/` / `line_check_assistant/`
#    下全部 .py 为准;新增 .py 后必须手工补到本列表)。
PY_COMPILE_SCRIPT_FILES: tuple[str, ...] = ('scripts/run_remote_gateway.py', 'scripts/restart_source_after_exit.py', 'scripts/source_environment_guard.py', 'run_line_check_assistant.py', 'scripts/run_tests.py', 'scripts/run_gui_child.py', 'scripts/verify_gui_test_coverage.py', 'scripts/qt_test_guard.py', 'scripts/verify_qt_migration.py', 'run_dutpilot_qt.py')
PY_COMPILE_FILES: tuple[str, ...] = (
    'src/models/workbench_presentation.py',
    'src/ui/qt/__init__.py',
    'src/ui/qt/application.py',
    'src/ui/qt/main_window.py',
    'src/ui/qt/theme.py',
    'src/ui/qt/demo_data.py',
    'src/ui/qt/dashboard.py',
    'src/ui/qt/system_health_panel.py',
    'src/ui/qt/project_detail.py',
    'src/ui/qt/pipeline_dialog.py',
    'src/ui/qt/log_panel.py',
    'src/ui/qt/log_presentation.py',
    'src/ui/qt/log_history_dialog.py',
    'src/ui/qt/channel_history_dialog.py',
    'src/ui/qt/archived_logs_dialog.py',
    'src/ui/qt/imported_connection_dialog.py',
    'src/ui/qt/instance_status_dialog.py',
    'src/ui/qt/instance_pairing_dialog.py',
    'src/ui/qt/instance_startup_dialog.py',
    'src/services/qt_instance_startup.py',
    'src/ui/qt/gateway_config_dialog.py',
    'src/ui/qt/remote_project_scope.py',
    'src/ui/qt/unknown_task_dialog.py',
    'src/ui/qt/job_review_dialog.py',
    'src/ui/qt/model_settings_dialog.py',
    'src/ui/qt/model_settings_controller.py',
    'src/ui/qt/ai_chat_dialog.py',
    'src/ui/qt/ai_chat_transcript.py',
    'src/ui/qt/ai_chat_controller.py',
    'src/ui/qt/ai_report_dialog.py',
    'src/ui/qt/ai_case_dialog.py',
    'src/ui/qt/app_update_dialog.py',
    'src/ui/qt/device_inventory_dialog.py',
    'src/ui/qt/single_power_dialog.py',
    'src/ui/qt/workspace_controller.py',
    'src/services/qt_workspace_adapter.py',
    'src/services/qt_window_state.py',
    'src/services/qt_imported_connections.py',
    'src/services/qt_remote_project_scope.py',
    'src/services/qt_execution_adapter.py',
    'src/services/qt_editor_recovery.py',
    'src/services/qt_pipeline_serial.py',
    'src/services/qt_pretest.py',
    'src/services/qt_version_query.py',
    'src/services/qt_push_trial.py',
    'src/services/qt_power_resume.py',
    'src/services/qt_power_logs.py',
    'src/services/qt_configuration_service.py',
    'src/models/qt_configuration.py',
    'src/models/qt_log_history.py',
    'src/models/channel_resource_options.py',
    'src/ui/qt/configuration_dialog.py',
    'src/services/qt_channel_configuration.py',
    'src/services/qt_adapter_rename.py',
    'src/services/qt_host_inventory.py',
    'src/services/qt_log_export.py',
    'src/services/qt_log_history.py',
    'src/services/qt_job_review.py',
    'src/services/qt_model_settings.py',
    'src/models/qt_model_settings.py',
    'src/models/qt_ai_chat.py',
    'src/services/qt_ai_chat.py',
    'src/ui/qt/ai_session_manager_dialog.py',
    'src/models/qt_ai_reports.py',
    'src/services/qt_ai_reports.py',
    'src/services/qt_ai_report_handoff.py',
    'src/services/qt_app_update.py',
    'src/models/qt_device_inventory.py',
    'src/models/qt_window_placement.py',
    'src/models/qt_ai_cases.py',
    'src/services/qt_ai_cases.py',
    'src/services/qt_archived_logs.py',
    'src/services/qt_single_power.py',
    'src/services/qt_serial_terminal.py',
    'src/services/qt_dut_configuration.py',
    'src/services/qt_firmware_upgrade.py',
    'src/services/qt_firmware_observation.py',
    'src/services/qt_serial_observation.py',
    'src/services/qt_parameter_writer.py',
    'src/services/qt_onu_query.py',
    'src/services/qt_onu_management.py',
    'src/services/qt_onu_registration.py',
    'src/services/qt_onu_save.py',
    'src/ui/qt/serial_observation_dialog.py',
    'src/ui/qt/parameter_writer_dialog.py',
    'src/ui/qt/parameter_writer_controller.py',
    'src/ui/qt/onu_query_dialog.py',
    'src/ui/qt/onu_provision_page.py',
    'src/ui/qt/onu_query_controller.py',
    'src/ui/qt/firmware_upgrade_dialog.py',
    'src/models/dut_wan_form.py',
    'src/models/dut_wifi_form.py',
    'src/services/qt_dut_wifi.py',
    'src/models/dut_voice_tr069_form.py',
    'src/services/qt_dut_voice_tr069.py',
    'src/ui/qt/dut_voice_tr069_panel.py',
    'src/ui/qt/dut_wifi_panel.py',
    'src/ui/qt/dut_wan_panel.py',
    'src/ui/qt/dut_configuration_dialog.py',
    'src/ui/qt/serial_terminal_dialog.py',
    'src/ui/qt/window_placement.py',
    'src/ui/qt/channel_configuration_dialog.py',
    'src/ui/qt/channel_table_model.py',
    "src/core/workspace_instance.py",
    "src/models/project.py",
    "src/models/project_task.py",
    "src/models/project_status.py",
    "src/services/project_status_service.py",
    "src/services/project_runtime.py",
    "src/services/project_import_service.py",
    "src/ui/project_status_tooltip.py",
    "src/services/project_ai_store.py",
    "src/services/project_diagnostic_transport.py",
    "src/services/project_execution.py",
    "src/services/power_worker_lifetime.py",
    "src/services/project_store.py",
    "src/services/workspace_gateway.py",
    "src/core/project_peer_transport.py",
    "src/services/project_peer_router.py",
    "src/services/project_peer_runtime.py",
    "src/services/workspace_platforms.py",
    "src/services/workspace_resources.py",
    "src/services/workspace_service.py",
    "src/ui/project_dialogs.py",
    "src/ui/project_editor_recovery.py",
    "src/ui/project_view_frame.py",
    "src/ui/project_workspace.py",
    "src/ui/workbench_dashboard.py",
    "src/ui/workbench_panels.py",
    "src/ui/form_wheel.py",
    "src/services/workbench_status_service.py",

    "src/core/ai_reply_cards.py",
    "src/services/ai_reply_stream_service.py",
    "src/core/ai_source_ip.py",
    "src/ui/ai_source_ip_dialog.py",
    "src/models/dependency_repair.py",
    "src/core/feishu_dependency_install.py",
    "src/core/source_restart.py",
    "src/services/feishu_dependency_repair.py",
    "src/ui/feishu_dependency_dialog.py",
    "src/ui/feishu_dependency_controller.py",
    "src/core/host_resource_lock.py",
    "src/core/remote_gateway_transport.py",
    "src/models/remote_gateway.py",
    "src/services/remote_instance_identity.py",
    "src/services/host_resource_fence.py",
    "src/services/physical_resource_guards.py",
    "src/services/remote_gateway_store.py",
    "src/services/remote_instance_service.py",
    "src/services/remote_gateway_runtime.py",
    "src/services/remote_gateway_host.py",
    "src/services/remote_instance_management.py",
    "src/services/remote_gateway_router.py",
    "src/services/remote_gateway_platforms.py",
    "src/services/controlled_host_service.py",
    "src/services/capability_configuration_service.py",
    "src/services/capability_observation_service.py",
    "src/services/capability_update_service.py",
    "src/services/capability_ai_data_service.py",
    "src/services/capability_notification_service.py",
    "src/services/capability_channel_service.py",
    "src/services/capability_settings_service.py",
    "src/services/ai_business_batch_route.py",
    "src/ui/capability_management.py",
    "src/services/capability_extension_service.py",
    "src/services/capability_onu_services.py",
    "src/services/capability_scope_service.py",
    "src/services/capability_parameter_services.py",
    "src/services/sample_parameter_application_service.py",
    "src/services/capability_device_services.py",
    "src/services/capability_catalog.py",
    "src/models/capabilities.py",
    "src/services/capability_registry.py",
    "src/services/resource_lease_service.py",
    "src/services/capability_metrics.py",
    "src/services/capability_jobs.py",
    "src/services/capability_service.py",
    "src/services/controlled_file_service.py",
    "src/services/firmware_upgrade_service.py",
    "src/services/firmware_upgrade_validation_service.py",
    "src/services/ai_capability_adapter.py",
    "src/ui/capability_ui_bridge.py",
    "src/core/transport_observation.py",
    "src/services/transport_history_monitor.py",
    "src/ui/channel_list.py",
    "src/ui/module_theme.py",
    "src/ui/application_icon.py",
    "src/models/ai_diagnostics.py",
    "src/models/ai_conversation.py",
    "src/models/ai_actions.py",
    "src/models/ai_permissions.py",
    "src/models/ai_session_scope.py",
    "src/ui/ai_remote_management_tab.py",
    "src/ui/ai_multi_instance_tab.py",
    "src/services/ai_session_router.py",
    "src/services/ai_batch_service.py",
    "src/services/ai_version_query_service.py",
    "src/models/ai_batch.py",
    "src/services/ai_pc_conversation.py",
    "src/services/ai_permission_service.py",
    "src/ui/ai_permission_control.py",
    "src/core/ai_local_executor.py",
    "src/core/ai_serial_diagnostics.py",
    "src/services/ai_action_service.py",
    "src/services/ai_monitor_service.py",
    "src/ui/ai_action_approval.py",
    "src/core/ai_network_probe.py",
    "src/core/ai_pc_network.py",
    "src/services/ai_evidence_context.py",
    "src/services/ai_evidence_analysis.py",
    "src/services/ai_conversation_service.py",
    "src/services/ai_context_budget.py",
    "src/services/ai_context_usage.py",
    "src/services/ai_diagnostic_task.py",
    "src/core/ai_stream.py",
    "src/ui/ai_diagnostic_task_control.py",
    "src/ui/ai_context_status.py",
    "src/ui/ai_chat_panel.py",
    "src/ui/ai_chat_markdown.py",
    "src/ui/ai_chat_status.py",
    "src/ui/ai_session_manager.py",
    "src/core/ai_client.py",
    "src/core/ai_gateway_network.py",
    "src/core/ai_credentials.py",
    "src/core/ai_debug_transport.py",
    "src/services/ai_store.py",
    "src/services/ai_case_store.py",
    "src/models/dingtalk_remote.py",
    "src/core/dingtalk_stream.py",
    "src/services/ai_project_store.py",
    "src/services/dingtalk_remote_store.py",
    "src/services/dingtalk_remote_service.py",
    "src/ui/dingtalk_setup_window.py",
    "src/services/ai_record_titles.py",
    "src/ui/ai_record_presentation.py",
    "src/services/ai_trigger_service.py",
    "src/services/ai_event_adapter.py",
    "src/services/ai_debug_service.py",
    "src/services/ai_diagnostic_service.py",
    "src/ui/ai_diagnostics_window.py",
    "src/ui/ai_monitor_window.py",
    "src/ui/ai_monitor_status.py",
    "src/ui/ai_reports_window.py",
    "src/ui/ai_report_manager.py",
    "src/ui/ai_report_target_dialog.py",
    "src/ui/ai_serial_bridge.py",
    "src/ui/ai_assistant_controller.py",
    "src/utils/ai_redaction.py",
    "src/utils/ai_chat_markdown.py",
    "src/utils/ai_output.py",
    # line_check_assistant 包
    "line_check_assistant/__init__.py",
    "line_check_assistant/app.py",
    "line_check_assistant/config_store.py",
    "line_check_assistant/legacy_ui_defaults_store.py",
    "line_check_assistant/network_ops.py",
    "line_check_assistant/onu_registration_store.py",
    "line_check_assistant/old_tool_automation.py",
    "line_check_assistant/old_tool_config.py",
    "line_check_assistant/packaging_hooks/hook-_tkinter.py",
    "line_check_assistant/packaging_hooks/pre_find_module_path/hook-tkinter.py",
    "line_check_assistant/page_upgrade.py",
    "line_check_assistant/paths.py",
    "line_check_assistant/pipeline_window.py",
    "line_check_assistant/sample_upgrade_settings_store.py",
    "line_check_assistant/serial_ports.py",
    "line_check_assistant/subprocess_window.py",
    "line_check_assistant/test_item_config_store.py",
    # src 包
    "src/__init__.py",
    "src/config.py",
    "src/core/__init__.py",
    "src/core/github_release_client.py",
    "src/core/network_adapter.py",
    "src/core/serial_inventory.py",
    "src/models/network_adapter.py",
    "src/services/adapter_rename_service.py",
    "src/ui/adapter_rename_dialog.py",
    "src/models/app_update.py",
    "src/services/app_update_service.py",
    "src/ui/app_update_dialog.py",
    "src/ui/project_name_badge.py",
    "src/ui/serial_terminal.py",
    "src/ui/tk_lifecycle.py",
    "src/ui/pipeline_ui.py",
    "src/utils/bounded_mailbox.py",
    "src/models/serial_delivery.py",
    "src/services/pipeline_runtime.py",
    "src/services/serial_diagnostic_receiver.py",
    "src/services/ai_serial_client.py",
    "src/ui/closable_notebook.py",
    "src/ui/dut_config_window.py",
    "src/ui/window_paint.py",
    "src/ui/window_size_state.py",
    "src/services/pipeline_orchestrator.py",
    "src/services/dut_config_service.py",
    "src/services/dut_advanced_config_service.py",
    "src/services/dut_status_query_service.py",
    "src/services/dut_wan_query_service.py",
    "src/services/device_project_info_service.py",
    "src/services/legacy_power_test_service.py",
    "src/services/power_test_wifi_service.py",
    "src/services/power_test_wifi_history_service.py",
    "src/services/power_test_resume_service.py",
    "src/ui/power_test_resume_menu.py",
    "src/services/power_test_log_service.py",
    "src/services/onu_batch_registration_service.py",
    "src/services/onu_batch_delete_service.py",
    "src/models/onu_batch_delete.py",
    "src/ui/onu_registered_list.py",
    "src/services/onu_registration_service.py",
    "src/services/onu_command_edit_service.py",
    "src/ui/onu_command_editor.py",
    "src/services/power_on_service.py",
    "src/services/sample_parameter_service.py",
    "src/services/serial_upgrade_service.py",
    "src/services/upgrade_stop_service.py",
    "src/models/upgrade_stop.py",
    "src/services/test_item_execution_service.py",
    "src/services/test_item_pretest_service.py",
    "src/services/telnet_post_login_service.py",
    "src/services/telnet_post_login_confirmation_service.py",
    "src/models/test_item_pretest_models.py",
    "src/ui/test_item_pretest_controls.py",
    "src/ui/message_push_tab.py",
    "src/models/feishu_remote.py",
    "src/core/feishu_client.py",
    "src/core/feishu_stream.py",
    "src/services/feishu_remote_store.py",
    "src/services/feishu_remote_service.py",
    "src/services/feishu_notifications.py",
    "src/services/feishu_output.py",
    "src/ui/feishu_setup_window.py",
    "src/core/dingtalk_robot.py",
    "src/core/webhook_target.py",
    "src/core/feishu_robot.py",
    "src/services/message_push_config_service.py",
    "src/core/bind_socket.py",
    "src/core/dut_ubus_config.py",
    "src/core/dut_wifi_config.py",
    "src/core/fuzzy_match_runner.py",
    "src/core/parameter_session.py",
    "src/core/power_supply.py",
    "src/core/sample_parameter_table.py",
    "src/core/serial_transport.py",
    "src/core/telnet_transport.py",
    "src/core/tftp_transport.py",
    "src/core/ubus_enable_telnet.py",
    "src/core/ubus_http_client.py",
    "src/core/wifi_interfaces.py",
    "src/core/wifi_target_reader.py",
    "src/core/windows_wifi.py",
    "src/core/wireless_ip.py",
    "src/core/wireless_ping.py",
    "src/models/wifi_test_models.py",
    "src/services/wifi_connection_service.py",
    "src/services/power_test_wifi_log_service.py",
    "src/ui/wifi_test_controls.py",
    "src/ui/main_log_filter.py",
    "src/utils/wifi_log_summary.py",
    "src/core/zte_c300_onu.py",
    "src/core/zte_c600_onu.py",
    "src/core/zte_olt_telnet.py",
    "src/core/zte_olt_registered_query.py",
    "src/models/onu_registration_models.py",
    "src/models/sample_parameter_models.py",
    "src/models/dut_config_models.py",
    "src/models/serial_models.py",
    "src/models/boot_entry.py",
    "src/services/sdmc_boot_entry.py",
    "src/services/web_gateway_upgrade_service.py",
    "src/core/gateway_browser.py",
    "src/core/gateway_proxy.py",
    "src/core/gateway_cdp.py",
    "src/models/__init__.py",
    "src/services/__init__.py",
    "src/ui/__init__.py",
)

# 关键已验收行为的回归用例。全量 unittest 必须实际执行这些 ID，避免测试文件或
# 用例在重构时被静默删除 / 改名而使已验收边界失去保护。
REQUIRED_BASELINE_TEST_IDS: tuple[str, ...] = (
    'test_gui_test_coverage.GuiRuntimeTests.test_retired_interpreter_is_collected_on_runner_main_thread',
    'test_gui_test_coverage.GuiCoverageTests.test_qt_and_tk_require_their_own_scopes',
    'test_qt_migration_contract.QtMigrationContractTests.test_existing_ui_exports_keep_their_identity',
    'test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_original_project_lifecycle_preserves_values_and_identity',
    'test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_old_running_and_queued_history_never_starts_hardware',
    'test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_unconfirmed_dirty_close_keeps_worker_and_data_until_explicit_choice',
    'test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_project_gateway_close_waits_for_receipts_and_workbench_waits_for_client',
    'test_workspace_gateway.WorkspaceGatewayTests.test_close_waits_for_receipt_after_agent_worker_finishes',
    'test_workspace_gateway.WorkspaceGatewayTests.test_client_first_poll_sees_attached_project_and_start_failure_drains_worker',
    'test_workspace_gateway.WorkspaceGatewayTests.test_unready_receipt_is_not_replayed_after_project_controller_attaches',
    'test_workspace_gateway.WorkspaceGatewayTests.test_exports_only_proven_current_boot_receipts_and_keeps_legacy_rows',
    'test_project_peer_routing.ProjectPeerTests.test_platform_received_on_b_only_a_executes_once_and_returns_version',
    'test_project_peer_routing.ProjectPeerTests.test_closed_offline_reopened_never_replays',
    'test_project_peer_routing.ProjectPeerTests.test_lost_receipt_and_concurrent_duplicate',
    'test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_peer_mode_delivers_version_through_project_chat_and_local_approval',
    'test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_configured_gateway_restart_routes_project_controls_over_loopback',
    'test_workspace_gateway.WorkspaceGatewayTests.test_failed_incoming_receipt_releases_only_its_own_project',
    'test_qt_execution_adapter.QtExecutionAdapterTests.test_original_orchestrator_receives_original_request_and_callbacks',
    'test_qt_execution_adapter.QtExecutionAdapterTests.test_config_changes_or_expiration_prevent_dispatch',
    'test_qt_execution_adapter.QtExecutionAdapterTests.test_stop_waits_for_engine_and_keeps_resources',
    'test_qt_execution_adapter.QtExecutionAdapterTests.test_disjoint_project_power_jobs_keep_separate_snapshots_stops_and_leases',
    'test_qt_execution_adapter.QtExecutionAdapterTests.test_power_failure_after_stop_request_preserves_original_failure',
    'test_remote_instance_management.ManagementTests.test_startup_write_failure_restores_previous_pending_scope',
    'test_qt_execution_adapter.QtExecutionAdapterTests.test_unknown_result_remains_fenced_and_no_automatic_retry',
    'test_qt_configuration_service.QtConfigurationTests.test_six_domains_save_through_original_stores_and_commit_project_revision',
    'test_qt_configuration_service.QtConfigurationTests.test_external_change_blocks_save_and_reload_returns_new_revision',
    'test_qt_configuration_service.QtConfigurationTests.test_project_commit_failure_restores_original_draft_bytes',
    'test_qt_configuration_service.QtConfigurationTests.test_failed_rollback_keeps_unknown_protection',
    'test_qt_channel_configuration.QtChannelConfigurationTests.test_selected_only_save_matches_original_serializer_and_derives_ips',
    'test_qt_channel_configuration.QtChannelConfigurationTests.test_failed_commit_does_not_undo_another_writer',
    'test_qt_channel_configuration.QtChannelConfigurationTests.test_failed_restore_keeps_unknown_fence',
    'test_qt_channel_configuration.QtChannelConfigurationTests.test_editors_and_task_admission_are_mutually_exclusive',
    'test_qt_serial_terminal.QtSerialTerminalTests.test_manual_text_empty_enter_and_control_lock_never_replay',
    'test_qt_dut_configuration.QtDutConfigurationTests.test_original_services_receive_selected_requests_parallelism_and_safe_logs',
    'test_qt_dut_voice_tr069.QtDutVoiceTr069Tests.test_voice_query_uses_line_and_private_caps_block_unsupported_write',
    'test_qt_dut_voice_tr069.QtDutVoiceTr069Tests.test_tr069_query_capabilities_filter_original_payload_and_inform',
    'test_qt_dut_voice_tr069.QtDutVoiceTr069Tests.test_tr069_manual_inform_stop_keeps_worker_until_safe_point',
    'test_qt_dut_wifi.QtDutWifiTests.test_shared_maps_keep_original_exports_and_exact_tk_defaults',
    'test_qt_dut_wifi.QtDutWifiTests.test_increment_batch_preserves_order_one_shared_wait_and_verified_outcomes',
    'test_qt_dut_wifi.QtDutWifiTests.test_stopped_shared_wait_never_reports_applied_but_unverified_as_success',
    'test_qt_dut_wifi.QtDutWifiTests.test_real_query_caps_block_unsupported_values_and_client_cannot_forge_lists',
    'test_qt_dut_wan.QtDutWanTests.test_modify_calls_original_payload_with_selected_targets_and_unmodified_password',
    'test_qt_dut_wan.QtDutWanTests.test_old_target_credentials_and_invented_name_cannot_use_a_cached_query',
    'test_qt_dut_wan.QtDutWanTests.test_shared_model_has_no_tk_import_and_original_exports_are_identical',
    'test_qt_dut_configuration.QtDutConfigurationTests.test_stop_keeps_resource_ownership_until_original_worker_returns',
    'test_qt_dut_configuration.QtDutConfigurationTests.test_window_close_and_reopen_preserve_live_job_and_reject_old_token',
    'test_qt_serial_terminal.QtSerialTerminalTests.test_open_all_preserves_original_log_name_timestamps_and_tail_on_close',
    'test_qt_serial_terminal.QtSerialTerminalTests.test_closing_one_monitor_keeps_other_owner_and_rejects_stale_delivery',
    'test_gui_test_coverage.GuiCoverageTests.test_missing_fixture_and_import_only_fail',
    'test_gui_test_coverage.GuiCoverageTests.test_late_or_conditional_installation_fails',
    'test_gui_test_coverage.GuiRuntimeTests.test_caught_missing_scope_fails_before_native_constructor',
    'test_verify_baseline.GuiTestGateIntegrationTests.test_coverage_failure_prevents_test_start',
    "test_project_completion.StatusAndBackupTests.test_import_has_verified_original_bytes_before_conversion",
    "test_project_completion.StatusAndBackupTests.test_worker_uses_frozen_config_and_ui_callback_returns_to_draft",
    "test_multi_project_business_validation.MultiProjectBusinessTests.test_four_projects_execute_every_business_kind_with_isolated_commands_and_results",
    "test_multi_project_business_validation.MultiProjectBusinessTests.test_stopping_one_real_job_does_not_cancel_or_release_the_other_three",
    "test_power_worker_lifetime.PowerWorkerLifetimeTests.test_two_project_events_release_only_after_last_owner_exits",
    "test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_persisted_job_review_binds_original_job_and_releases_only_its_protection",
    "test_project_completion.CompletionGuiTests.test_gui_unknown_preserves_resource_guard_until_explicit_local_review",
    "test_ui_lifecycle_runtime.MailboxTests.test_consumer_and_producer_never_wait_for_busy_mutex",
    "test_ui_lifecycle_runtime.PipelineRuntimeTests.test_expired_request_never_executes_later",
    "test_ui_lifecycle_runtime.PipelineRuntimeTests.test_actual_upgrade_entry_rejects_cancel_after_confirmation",
    "test_ui_lifecycle_runtime.PipelineRuntimeTests.test_main_exit_polls_serial_completion_without_join_or_destroying_early",
    "test_tk_lifecycle_process.TkLifecycleProcessTests.test_eight_readers_gc_close_reopen_and_complete_logs",
    "test_serial_transport.SerialTransportTests.test_async_close_waits_for_inflight_callback_and_reserves_port",
    "test_qt_serial_terminal.QtSerialTerminalTests.test_passive_reader_limits_bytes_at_read_time_during_driver_burst",
    "test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_old_local_device_session_accepts_retained_evidence_only",
    "test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_explicit_local_channel_routes_from_send_and_preserves_report_and_project_scope",
    "test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_local_natural_target_routing_cancels_late_results_and_rechecks_project",
    "test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_local_channel_passive_serial_rechecks_binding_and_never_writes",
    "test_serial_transport.SerialTransportTests.test_open_failure_releases_driver_log_and_port_before_retry",
    "test_serial_transport.SerialTransportTests.test_driver_close_error_fences_normal_release_and_failed_start_rollback",
    "test_serial_transport.SerialTransportTests.test_close_thread_failure_keeps_control_and_bulk_shutdown_can_retry",
    "test_serial_transport.SerialTransportTests.test_workspace_release_failure_completes_ticket_and_preserves_port_fence",
    "test_qt_serial_terminal.QtSerialTerminalTests.test_driver_failure_reaches_terminal_without_discarding_other_channel",
    "test_wifi_connection_service.ConnectionServiceTests.test_same_ssid_requires_both_actual_bssids_and_pings_each_band",
    "test_wifi_connection_service.ConnectionServiceTests.test_unified_mode_runs_once_even_when_saved_band_flags_off",
    "test_wifi_connection_service.ConnectionServiceTests.test_other_dut_with_same_ssid_never_passes_and_keeps_retry_budget",
    "test_wifi_connection_service.ConnectionServiceTests.test_wrong_band_during_ping_retries_in_shared_budget_without_false_success",
    "test_wifi_connection_service.ConnectionServiceTests.test_native_scheduler_keeps_reservation_across_ping",
    "test_wifi_connection_service.TargetReaderTests.test_missing_mapping_is_not_replaced_by_fixed_indices",
    "test_wireless_ping.WirelessPingTests.test_four_packets_bind_wireless_source_and_interface_and_report_statistics",
    "test_wireless_ping.WirelessPingTests.test_wireless_unreachable_does_not_use_reachable_wired_interface",
    "test_wireless_ping.DnsTests.test_dns_pending_cancellation_retains_buffers_until_completion",
    "test_wifi_test_controls.WifiControlsTests.test_native_checks_mode_switch_preserves_band_selections",
    "test_tftp_transport.TftpTransportTests.test_server_binds_transfer_data_socket_to_listening_vlan_ip",
    "test_tftp_transport.TftpTransportTests.test_upload_binds_requested_source_ip_and_uses_requested_remote_name",
    "test_serial_upgrade_service.SerialUpgradeControllerTests.test_login_boot_salvages_after_garbled_username_echo",
    "test_power_supply.PowerSupplyTests.test_controller_turns_on_all_requested_channels_one_second_apart_without_powering_off",
    "test_power_supply.PowerSupplyTests.test_empty_power_serial_port_skips_power_operation_without_opening_port",
    "test_sample_parameter_service.SampleParameterPipelineOptionTests.test_clear_parameters_default_off_does_not_send_ppctl_clear",
    "test_sample_parameter_service.SampleParameterPipelineOptionTests.test_both_options_off_skips_both_commands",
    "test_pipeline_orchestrator.PipelineRunOrderTests.test_run_all_seven_subtasks_in_order",
    "test_pipeline_orchestrator.PipelineRunOrderTests.test_serial_prestart_and_env_check_completion_skip_120_second_wait",
    "test_app.CurrentChannelSelectionTests.test_unattended_pipeline_parameter_completion_is_logged_without_a_dialog",
    "test_device_project_info_service.DeviceProjectInfoQueryServiceTests.test_query_reads_all_requested_fields",
    "test_pipeline_window.BuildContextRegressionTests.test_pipeline_defaults_to_no_selected_subtasks",
    "test_app.CurrentChannelSelectionTests.test_power_test_progress_uses_configured_total_and_clamps_value",
    "test_legacy_power_test_service.LegacyPowerTestServiceTests.test_cycle_progress_uses_slowest_selected_channel",
    "test_legacy_power_test_service.LegacyPowerTestServiceTests.test_cycle_start_confirms_previous_cycle_for_power_only_mode",
    "test_test_item_config_store.TestItemConfigStoreTests.test_save_and_load_round_trip",
    "test_legacy_power_test_service.LegacyPowerTestServiceTests.test_headless_onu_config_uses_all_wifi_profile_fields",
    "test_power_test_wifi.SchedulerTests.test_fifo_keeps_both_bands_together",
    "test_power_test_wifi.SchedulerTests.test_waiting_cancel_removes_ticket_without_connecting",
    "test_power_test_wifi.ConnectorTests.test_four_attempts_and_original_wait_budget",
    "test_power_test_wifi.IntegrationTests.test_real_wifi_stage_cancel_skips_ping_notifications_and_completion",
    "test_power_test_wifi.IntegrationTests.test_sensitive_telnet_read_never_logs_or_saves_response",
    "test_power_test_resume.ResumeTests.test_wifi_cancelled_channel_remains_cancelled_after_detach",
    "test_legacy_power_initialization.SelectedPowerInitializationTests.test_wifi_cancel_has_separate_result_and_ready_messages",
    "test_power_command_receipts.PowerCommandReceiptTests.test_receipt_after_write_and_stop_discards_next_channel",
    "test_power_command_receipts.PowerCommandReceiptTests.test_partial_write_latches_failure_without_repower_or_cached_success",
    "test_qt_execution_adapter.QtExecutionAdapterTests.test_selected_wifi_profile_reserves_host_before_a_power_job",
    "test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_qt_serial_admission_and_project_close_wait_for_safe_stop",
    "test_wifi_interfaces.WifiInterfaceTests.test_names_are_trimmed_deduplicated_and_keep_discovery_order",
    "test_network_ops.PrepareNetworkForSampleTests.test_reads_adapter_enabled_state_and_ipv4_prefix",
    "test_network_ops.PrepareNetworkForSampleTests.test_reuses_ready_adapter_without_enable_or_set",
    "test_network_ops.EnableAdapterTests.test_line_check_enables_adapter_before_setting_ip_and_ping",
    "test_serial_upgrade_service.SerialUpgradeControllerTests.test_prepare_tftp_network_waits_for_bindable_ip_before_strict_server",
    "test_page_upgrade.PageUpgradeTests.test_single_page_upgrade_prepares_network_on_same_subnet_before_login",
    "test_sample_parameter_app.SampleParameterAppNetworkPreflightTests.test_factory_prepares_network_before_ubus",
    "test_test_item_execution_service.TestItemExecutionSingleCommandTests.test_single_command_match_success",
    "test_dut_config_service.DutConfigServiceTests.test_single_success_prepares_network_enables_ubus_and_probes_port",
    "test_dut_config_service.DutConfigServiceTests.test_batch_stop_does_not_start_later_requests",
    "test_dut_ubus_config.DutUbusConfigTests.test_build_dual_stack_static_ipv4_and_dhcpv6_payload",
    "test_dut_ubus_config.DutUbusConfigTests.test_build_iptv_multicast_vlan_is_optional_and_ignored_by_other_services",
    "test_dut_ubus_config.DutUbusConfigTests.test_query_wan_connection_names_filters_non_wan_and_sorts_by_index",
    "test_dut_ubus_config.DutUbusConfigTests.test_query_wan_connections_parses_complete_ipoe_snapshot",
    "test_dut_ubus_config.DutUbusConfigTests.test_query_wan_connections_parses_iptv_multicast_vlan",
    "test_dut_ubus_config.DutUbusConfigTests.test_query_wan_connections_parses_pppoe_dual_stack_static_fields",
    "test_dut_ubus_config.DutUbusConfigTests.test_voice_config_sets_server_account_codecs_and_reads_back",
    "test_dut_ubus_config.DutUbusConfigTests.test_tr069_config_sets_plaintext_credentials_and_verifies_readback",
    "test_dut_ubus_config.DutUbusConfigTests.test_voice_status_query_reads_selected_line_servers_mode_and_codecs",
    "test_dut_ubus_config.DutUbusConfigTests.test_tr069_status_query_maps_management_server_without_manual_inform_action",
    "test_dut_advanced_config_service.DutAdvancedConfigServiceTests.test_single_wan_success_prepares_network_logs_in_and_closes_client",
    "test_dut_advanced_config_service.DutAdvancedConfigServiceTests.test_iptv_multicast_vlan_is_optional_but_validated_when_present",
    "test_dut_advanced_config_service.DutAdvancedConfigServiceTests.test_voice_sip_mode_accepts_imssip_and_rejects_unknown_values",
    "test_dut_wan_query_service.DutWanQueryServiceTests.test_single_query_prepares_network_logs_real_get_and_closes_client",
    "test_dut_wan_query_service.DutWanQueryServiceTests.test_consecutive_queries_release_previous_device_session",
    "test_dut_wan_query_service.DutWanQueryServiceTests.test_common_names_requires_every_target_and_exact_name_match",
    "test_dut_wan_query_service.DutWanQueryServiceTests.test_common_details_requires_identical_snapshot_on_every_target",
    "test_dut_status_query_service.DutStatusQueryServiceTests.test_single_voice_query_reuses_network_logs_out_and_returns_settings",
    "test_dut_status_query_service.DutStatusQueryServiceTests.test_single_telnet_query_uses_readonly_status_result_and_logs_out",
    "test_dut_status_query_service.DutStatusQueryServiceTests.test_consecutive_status_queries_release_previous_device_session",
    "test_dut_status_query_service.DutStatusQueryServiceTests.test_common_settings_requires_every_target_success_and_exact_match",
    "test_dut_status_query_service.DutStatusQueryServiceTests.test_single_wifi_query_passes_band_and_ssid_index_without_setting",
    "test_dut_wifi_config.DutWifiConfigTests.test_query_resolves_vendor_mapping_and_never_sets",
    "test_dut_wifi_config.DutWifiConfigTests.test_configure_dual_band_sets_independent_radios_and_common_power",
    "test_dut_wifi_config.DutWifiConfigTests.test_apply_and_verify_can_share_one_batch_settle_wait",
    "test_dut_advanced_config_service.DutAdvancedConfigServiceTests.test_wifi_validation_covers_band_rules_security_and_extra_fields",
    "test_dut_advanced_config_service.DutAdvancedConfigServiceTests.test_wifi_ssid_sequence_preserves_numeric_width_and_settings",
    "test_dut_advanced_config_service.DutAdvancedConfigServiceTests.test_wifi_ssid_sequence_rejects_missing_suffix_and_utf8_overflow",
    "test_dut_advanced_config_service.DutAdvancedConfigServiceTests.test_increment_batch_waits_once_on_last_target_then_verifies_each_dut",
    "test_dut_advanced_config_service.DutAdvancedConfigServiceTests.test_increment_batch_stop_during_shared_wait_does_not_claim_success",
    "test_dut_advanced_config_service.DutAdvancedConfigServiceTests.test_dual_band_wifi_validates_each_radio_and_common_power",
    "test_telnet_transport.TelnetSessionTests.test_probe_binds_requested_source_ip_and_closes_immediately",
    "test_ubus_enable_telnet.EnableTelnetViaUbusTests.test_operation_logs_include_real_paths_and_plaintext_password",
    "test_ubus_enable_telnet.EnableTelnetViaUbusTests.test_status_query_only_gets_rules_and_probes_without_set_or_add",
    "test_ubus_http_client.UbusHttpClientTests.test_logout_releases_device_session_and_clears_local_reference",
    "test_ubus_http_client.UbusHttpClientTests.test_close_best_effort_logs_out_active_session_once",
    "test_app.CurrentChannelSelectionTests.test_dut_config_window_is_extensible_and_dispatches_through_service",
    "test_app.CurrentChannelSelectionTests.test_dut_target_selection_preserves_manual_clear_and_selects_new_targets",
    "test_app.CurrentChannelSelectionTests.test_dut_target_selection_is_shared_by_every_tab",
    "test_app.CurrentChannelSelectionTests.test_dut_target_selection_click_and_bulk_actions_update_shared_state",
    "test_app.CurrentChannelSelectionTests.test_selected_dut_requests_follow_window_selection_without_changing_main_targets",
    "test_app.CurrentChannelSelectionTests.test_wifi_advanced_requests_increment_ssid_in_selected_target_order",
    "test_app.CurrentChannelSelectionTests.test_dual_band_wifi_choices_keep_radios_independent_and_power_common",
    "test_app.CurrentChannelSelectionTests.test_dut_config_and_query_entrypoints_use_window_target_selection",
    "test_app.CurrentChannelSelectionTests.test_start_dut_config_requires_a_window_selected_target",
    "test_app.CurrentChannelSelectionTests.test_voice_and_tr069_tabs_query_current_status_and_map_common_values",
    "test_app.CurrentChannelSelectionTests.test_telnet_and_wan_tabs_also_show_current_status_without_duplicate_wan_query",
    "test_app.CurrentChannelSelectionTests.test_status_display_only_applies_settings_when_batch_has_safe_common_value",
    "test_app.CurrentChannelSelectionTests.test_dut_option_checkbuttons_use_native_checkmark_indicator",
    "test_app.CurrentChannelSelectionTests.test_dut_form_field_names_are_left_aligned_in_every_tab",
    "test_app.CurrentChannelSelectionTests.test_wifi_tabs_cover_required_fields_query_and_form_mapping",
    "test_app.CurrentChannelSelectionTests.test_dut_current_status_heights_round_trip_and_clamp_invalid_values",
    "test_app.CurrentChannelSelectionTests.test_dut_current_status_drag_resizes_and_persists_each_tab",
    "test_app.CurrentChannelSelectionTests.test_dut_current_status_resize_stops_before_bottom_actions_are_clipped",
    "test_app.CurrentChannelSelectionTests.test_dut_window_size_round_trip_preserves_status_and_fits_screen",
    "test_app.CurrentChannelSelectionTests.test_complex_config_windows_use_standard_toplevel_lifecycle",
    "test_app.CurrentChannelSelectionTests.test_clicking_main_window_lifts_it_without_forcing_widget_focus",
    "test_app.CurrentChannelSelectionTests.test_non_modal_feature_windows_do_not_stay_transient_above_main",
    "test_app.CurrentChannelSelectionTests.test_toplevel_client_refresh_pulses_and_restores_geometry",
    "test_app.CurrentChannelSelectionTests.test_center_toplevel_uses_parent_screen_coordinates",
    "test_app.CurrentChannelSelectionTests.test_toolbar_feature_windows_use_shared_centering",
    "test_app.CurrentChannelSelectionTests.test_wan_form_rules_hide_irrelevant_fields_and_apply_protocol_mtu",
    "test_app.CurrentChannelSelectionTests.test_wan_address_modes_follow_supported_dual_stack_combinations",
    "test_app.CurrentChannelSelectionTests.test_wan_lan_port_multiselect_maps_masks_and_preserves_non_lan_bits",
    "test_app.CurrentChannelSelectionTests.test_iptv_multicast_vlan_field_is_conditional_and_mapped",
    "test_app.CurrentChannelSelectionTests.test_voice_sip_mode_options_include_ont_imssip_without_removing_existing_modes",
    "test_app.CurrentChannelSelectionTests.test_wan_existing_connections_use_readonly_query_dropdown",
    "test_app.CurrentChannelSelectionTests.test_wan_connection_snapshot_maps_to_current_form_values",
    "test_app.CurrentChannelSelectionTests.test_selecting_existing_wan_replaces_stale_form_values",
    "test_dut_advanced_config_service.DutAdvancedConfigServiceTests.test_pppoe_static_ipv6_and_invalid_dual_stack_pair_are_rejected",
    "test_pipeline_window.BuildContextRegressionTests.test_pipeline_confirmation_does_not_call_numbered_items_pipelines",
    "test_pipeline_window.BuildContextRegressionTests.test_main_stop_request_uses_existing_orchestrator_stop_event",
    "test_app.CurrentChannelSelectionTests.test_main_card_shows_power_test_status_and_stop_button",
    "test_app.CurrentChannelSelectionTests.test_power_test_status_styles_are_prominent_and_state_specific",
    "test_pipeline_window.BuildContextRegressionTests.test_pipeline_start_hides_configuration_window_after_thread_starts",
    "test_app.CurrentChannelSelectionTests.test_main_header_copy_is_removed_and_admin_status_moves_to_toolbar",
    "test_pipeline_window.BuildContextRegressionTests.test_pipeline_thread_dispatches_completion_through_main_ui_queue",
    "test_pipeline_window.StartAllChecksRegressionTests.test_start_all_checks_recovers_stale_running_status",
    "test_app.CurrentChannelSelectionTests.test_pipeline_serial_logs_show_then_open_all",
    "test_app.CurrentChannelSelectionTests.test_power_serial_port_limits_channel_com_options_to_its_eight_port_group",
    "test_app.CurrentChannelSelectionTests.test_channel_com_column_is_readonly_and_uses_grouped_options",
    "test_app.CurrentChannelSelectionTests.test_parameter_and_serial_log_targets_use_saved_channel_com_selection",
    "test_channel_config.ChannelConfigFactoryModeFieldsTests.test_save_round_trip_preserves_factory_fields",
    "test_serial_terminal.SerialTerminalPersistenceTests.test_serial_log_path_includes_vlan_port_and_open_date",
    "test_serial_terminal.SerialTerminalPersistenceTests.test_attach_upgrade_keeps_explicit_channel_port_in_terminal_tab",
    "test_serial_upgrade_service.SerialUpgradeControllerTests.test_full_package_upgrade_tftp_put_runs_full_flow_after_power_cycle",
    "test_serial_transport.SerialTransportTests.test_log_file_prefixes_every_serial_line_and_joins_split_rx_chunks",
    "test_pipeline_orchestrator.PipelineRunOrderTests.test_fatal_subtask_failure_raises_pipeline_error",
    "test_test_item_config_store.TestItemConfigStoreTests.test_save_writes_retry_interval_only_to_legacy_other_config",
    "test_sample_parameter_table.SampleParameterTableTests.test_generated_xpon_sn_is_fixed_12_chars_with_upper_hex_last_8",
    "test_sample_parameter_table.SampleParameterTableTests.test_generated_xpon_sn_rejects_prefix_that_is_not_exactly_4_chars",
    "test_sample_parameter_table.SampleParameterTableTests.test_generated_sn_is_numeric_and_total_length_does_not_exceed_16",
    "test_sample_parameter_table.SampleParameterTableTests.test_generated_sn_rejects_non_numeric_prefix_or_total_over_16",
    "test_sample_parameter_table.SampleParameterTableTests.test_generate_records_use_custom_mac_prefix_and_unique_hex_suffix",
    "test_sample_parameter_table.SampleParameterTableTests.test_generate_records_reject_invalid_hex_or_multicast_mac_prefix",
    "test_app.CurrentChannelSelectionTests.test_parameter_generator_labels_xpon_sn_fixed_format_and_sn_length_separately",
    "test_app.CurrentChannelSelectionTests.test_parameter_generator_has_custom_hex_mac_prefix_field",
    "test_app.CurrentChannelSelectionTests.test_parameter_generator_centers_and_refreshes_client_area_after_layout",
    "test_legacy_power_test_service.LegacyPowerTestServiceTests.test_parent_forwards_legacy_logs_and_waits_for_result",
    "test_legacy_power_test_service.LegacyPowerTestServiceTests.test_service_does_not_import_or_construct_old_gui_entry",
    "test_legacy_power_test_service.LegacyPowerTestServiceTests.test_power_frame_is_rendered_in_execution_log_format",
    "test_legacy_power_test_service.LegacyPowerTestServiceTests.test_result_file_success_line_is_forwarded_without_changing_file",
    "test_power_test_log_service.PowerTestLogLookupTests.test_latest_log_is_selected_by_filename_timestamp",
    "test_pipeline_orchestrator.LegacyPowerTestDispatchTests.test_legacy_power_test_delegates_to_headless_service",
    "test_onu_registration_service.DriverTests.test_c300_uses_underscore_interface_and_confirmed_fixed_template",
    "test_onu_registration_service.DriverTests.test_c300_precheck_uses_targeted_id_and_global_sn_queries",
    "test_onu_registration_service.DriverTests.test_c300_verification_parses_registration_transport_and_services",
    "test_onu_registration_service.DriverTests.test_c600_uses_hyphen_interfaces_and_vport_context",
    "test_onu_registration_service.DriverTests.test_c600_rejects_internet_resource_ids_that_collide_with_fixed_layers",
    "test_onu_registration_service.DriverTests.test_c600_verification_rejects_wrong_vport_and_missing_igmp_receive_port",
    "test_onu_registration_service.DriverTests.test_c600_mvlan_verification_requires_fixed_vlan_600",
    "test_onu_registration_service.DriverTests.test_c600_precheck_uses_exact_id_and_global_sn_queries",
    "test_onu_registration_service.DriverTests.test_c600_requires_vlan_600_when_mvlan_is_fixed",
    "test_onu_registration_service.DriverTests.test_c600_auto_speed_omits_real_speed_command_and_verification",
    "test_onu_registration_service.ServiceTests.test_c600_register_runs_global_precheck_readiness_and_full_verification",
    "test_onu_registration_service.ServiceTests.test_c600_allows_explicit_independent_write",
    "test_onu_registration_service.ServiceTests.test_c600_offline_after_config_is_not_reported_success",
    "test_onu_registration_service.ServiceTests.test_batch_completes_all_prechecks_before_first_provision_command",
    "test_onu_batch_registration_service.BatchRequestBuildTests.test_assigns_distinct_ids_per_pon_and_keeps_discovery_suggestions",
    "test_onu_registration_service.ServiceTests.test_c300_failure_does_not_delete_when_cleanup_not_authorized",
    "test_onu_registration_service.ServiceTests.test_c300_authorized_cleanup_deletes_only_selected_same_pon_onu_and_retries",
    "test_onu_registration_service.ServiceTests.test_cleanup_candidate_query_returns_only_same_pon_with_identity",
    "test_onu_registration_service.TelnetBindingTests.test_session_binds_explicit_source_ip",
    "test_app.CurrentChannelSelectionTests.test_main_onu_ui_uses_service_without_importing_standalone_c600_gui",
    "test_app.CurrentChannelSelectionTests.test_onu_window_reserves_bottom_rows_without_maximizing",
    "test_app.CurrentChannelSelectionTests.test_onu_options_and_active_ui_use_native_checkmark_indicator",
    "test_app.CurrentChannelSelectionTests.test_c600_success_without_write_selection_does_not_save",
    "test_app.CurrentChannelSelectionTests.test_c600_success_with_write_selection_starts_save_worker",
    "test_app.CurrentChannelSelectionTests.test_c300_register_passes_only_explicit_cleanup_interface",
    "test_app.CurrentChannelSelectionTests.test_c600_discovery_defaults_speed_command_to_auto",
    "test_app.CurrentChannelSelectionTests.test_onu_input_change_clears_stale_c300_cleanup_candidates",
    "test_app.CurrentChannelSelectionTests.test_current_onu_registration_config_ignores_destroyed_services_text",
    "test_onu_registration_service.DriverTests.test_c600_registered_query_lists_all_states",
    "test_onu_registration_service.DriverTests.test_c600_registered_delete_commands_target_one_onu",
    "test_onu_registration_service.ServiceTests.test_query_registered_candidates_lists_all_with_identity",
    "test_onu_registration_service.ServiceTests.test_delete_registered_onu_rechecks_identity_and_verifies_after",
    "test_onu_registration_service.ServiceTests.test_delete_registered_onu_rejects_when_sn_changed",
    "test_app.CurrentChannelSelectionTests.test_onu_registered_manage_tab_and_danger_button_present",
    "test_app.CurrentChannelSelectionTests.test_onu_manage_delete_clicked_confirms_and_starts_worker",
    "test_pipeline_window.BuildContextRegressionTests.test_build_context_uses_saved_onu_config_after_services_text_is_destroyed",
    "test_onu_registration_store.OnuRegistrationStoreTests.test_save_and_load_preserves_dual_olt_settings",
    "test_portable_release.PortableReleaseConfigTests.test_portable_config_removes_secrets_and_machine_bindings",
    "test_portable_release.PortableReleaseConfigTests.test_destination_cannot_replace_live_source_config",
    "test_portable_release.PortableReleaseConfigTests.test_nonempty_destination_is_refused_without_deleting_existing_files",
    "test_portable_release.PortableReleaseBuildScriptTests.test_tkinter_hook_uses_runtime_expected_tcl_and_tk_roots",
    "test_portable_release.PortableReleaseBuildScriptTests.test_build_script_creates_directory_zip_hash_and_never_launches_exe",
)

# 2. 必须命中(§1.3 / §1.4) - (pattern, 搜索目录组)
MUST_EXIST: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bbfdm.operate", ("src/", "line_check_assistant/")),
    ("tclinux_allinone", ("src/",)),
    ("192.168.1.1", ("src/",)),
    ("vlan_to_serial_port", ("src/", "line_check_assistant/")),
    ("MAX_PARALLEL_UPGRADES = 8", ("src/", "line_check_assistant/")),
    ("clamp_parallel_count", ("src/", "line_check_assistant/")),
    ("source_address=(bind_ip, 0)", ("src/", "line_check_assistant/")),
    ("Device.Firewall.<X_SDMC_>Security.AccessCtrl", ("src/",)),
)

# 3. 必须不出现(§1.3 / §1.4) - (pattern, 限制文件列表)
MUST_NOT_EXIST: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("0.0.0.0", ("src/core/tftp_transport.py", "src/core/telnet_transport.py")),
)


def _glob_py_files(project_root: Path, dirs: Iterable[str]) -> list[Path]:
    """在 `dirs` 下递归收集所有 `.py` 文件。目录不存在时静默跳过。"""
    files: list[Path] = []
    for d in dirs:
        base = project_root / d
        if not base.exists():
            continue
        files.extend(sorted(base.rglob("*.py")))
    return files


def _is_code_line(line: str) -> bool:
    """判断是否为代码行(排除纯注释行)。

    用于 `must_not_exist` 避开反向语义注释(如「不回退 0.0.0.0」)导致的误报。
    """
    return not line.lstrip().startswith("#")


def _strip_docstrings(content: str) -> str:
    """把三引号字符串(文档字符串 / 长字符串)替换为同长度的空白,保留行号。

    行内 `\n` 保留为空行,其余字符替换为空格。这样后续 grep `pattern in content`
    时,文档字符串里出现的禁止字符串(如「不回退 0.0.0.0」)不会触发误报。
    """
    def replace_with_whitespace(match: re.Match) -> str:
        text = match.group(0)
        return "".join("\n" if c == "\n" else " " for c in text)

    return _DOCSTRING_PATTERN.sub(replace_with_whitespace, content)


def _code_lines(content: str) -> list[tuple[int, str]]:
    """返回 (行号 1-based, 行内容) 列表,跳过文档字符串 + 纯注释行。"""
    stripped = _strip_docstrings(content)
    return [
        (idx + 1, line)
        for idx, line in enumerate(stripped.splitlines())
        if _is_code_line(line)
    ]


def run_py_compile(project_root: Path) -> CheckResult:
    """对 `PY_COMPILE_FILES` 全部运行 `python -m py_compile`。"""
    files = [str(project_root / f) for f in (*PY_COMPILE_FILES, *PY_COMPILE_SCRIPT_FILES)]
    missing = [f for f in files if not Path(f).exists()]
    if missing:
        return CheckResult(
            "py_compile",
            False,
            f"missing files: {', '.join(Path(m).name for m in missing)}",
        )
    # Windows CreateProcess has a command-line size limit. py_compile accepts
    # the same explicit file list over stdin and still reports all failures.
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "py_compile", "-"],
        input="\n".join(files) + "\n" if files else "",
        capture_output=True,
        encoding="utf-8",
        cwd=str(project_root),
    )
    if proc.returncode == 0:
        return CheckResult("py_compile", True, f"{len(files)} files compiled")
    return CheckResult("py_compile", False, (proc.stderr or proc.stdout).strip().splitlines()[-1] if (proc.stderr or proc.stdout) else "unknown error")


def check_py_compile_inventory(project_root: Path) -> CheckResult:
    """保证新增主程序 Python 文件不会漏出 `PY_COMPILE_FILES`。"""
    discovered = {
        str(path.relative_to(project_root)).replace("\\", "/")
        for path in _glob_py_files(project_root, ("src/", "line_check_assistant/"))
    }
    declared = set(PY_COMPILE_FILES)
    undeclared = sorted(discovered - declared)
    if undeclared:
        return CheckResult(
            "compile_inventory",
            False,
            f"source files missing from PY_COMPILE_FILES: {', '.join(undeclared)}",
        )
    return CheckResult("compile_inventory", True, f"{len(discovered)} source files covered")


def missing_required_baseline_tests(unittest_output: str) -> list[str]:
    """从 verbose unittest 输出中找出未执行的关键回归用例。"""
    executed_test_ids = set()
    for test_name, qualified_name in re.findall(
        r"(?m)^(test_\w+) \(([\w.]+)\)", unittest_output
    ):
        # Python 3.12 在括号内显示 module.Class.method；旧版只显示 module.Class。
        test_id = qualified_name if qualified_name.endswith(f".{test_name}") else f"{qualified_name}.{test_name}"
        executed_test_ids.add(test_id)
    return [
        test_id
        for test_id in REQUIRED_BASELINE_TEST_IDS
        if test_id not in executed_test_ids
    ]


def check_required_baseline_tests(unittest_output: str) -> CheckResult:
    """输出关键已验收行为测试的实际执行结果。"""
    missing = missing_required_baseline_tests(unittest_output)
    if missing:
        return CheckResult(
            "required_baseline_tests",
            False,
            f"not executed: {', '.join(missing)}",
        )
    return CheckResult(
        "required_baseline_tests",
        True,
        f"{len(REQUIRED_BASELINE_TEST_IDS)} required tests executed",
    )


def run_unittest(project_root: Path) -> tuple[CheckResult, str]:
    """运行全量单测，并返回 verbose 输出供关键测试执行检查复用。"""
    proc = subprocess.run(
        [sys.executable, "scripts/run_tests.py", "discover", "-s", "tests", "-v"],
        capture_output=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
        cwd=str(project_root),
    )
    output = proc.stdout + proc.stderr
    match = re.search(r"Ran (\d+) tests?", output)
    if proc.returncode != 0:
        # Preserve assertion/traceback evidence, rather than only FAILED totals.
        tail = output[-16000:].strip()
        return CheckResult("unittest", False, f"non-zero exit; tail: {tail}"), output
    if match is None:
        return (
            CheckResult(
                "unittest",
                False,
                f"could not parse 'Ran N tests' from output; tail: {output[-200:]}",
            ),
            output,
        )
    return CheckResult("unittest", True, f"Ran {match.group(1)} tests"), output


def check_must_exist(project_root: Path) -> list[CheckResult]:
    """逐条检查 `MUST_EXIST` pattern 是否在指定目录下命中。"""
    results: list[CheckResult] = []
    for pattern, dir_groups in MUST_EXIST:
        files = _glob_py_files(project_root, dir_groups)
        found_in: list[str] = []
        for f in files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if pattern in content:
                found_in.append(str(f.relative_to(project_root)))
        if found_in:
            results.append(
                CheckResult(
                    name=f"must_exist: {pattern}",
                    passed=True,
                    detail=f"hit in {found_in[0]}" + (f" (+{len(found_in) - 1})" if len(found_in) > 1 else ""),
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"must_exist: {pattern}",
                    passed=False,
                    detail=f"not found in {','.join(dir_groups)}",
                )
            )
    return results


def check_must_not_exist(project_root: Path) -> list[CheckResult]:
    """逐条检查 `MUST_NOT_EXIST` pattern 是否在限制文件的**代码行**中出现。

    跳过纯注释行(以 `#` 开头)以避免反向语义注释(例如「不回退 0.0.0.0」)误报。
    """
    results: list[CheckResult] = []
    for pattern, file_paths in MUST_NOT_EXIST:
        bad_locations: list[str] = []
        for fp in file_paths:
            full = project_root / fp
            if not full.exists():
                continue
            try:
                content = full.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line_no, line in _code_lines(content):
                if pattern in line:
                    bad_locations.append(f"{fp}:{line_no}")
                    break  # 每个文件只报一次,避免重复
        if bad_locations:
            results.append(
                CheckResult(
                    name=f"must_not_exist: {pattern}",
                    passed=False,
                    detail=f"found in code lines: {','.join(bad_locations)}",
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"must_not_exist: {pattern}",
                    passed=True,
                    detail=f"absent from code lines of {','.join(file_paths)}",
                )
            )
    return results


def collect_results(project_root: Path) -> list[CheckResult]:
    """串联所有基线检查,返回完整结果列表。"""
    results: list[CheckResult] = []
    results.append(run_py_compile(project_root))
    results.append(check_py_compile_inventory(project_root))
    from verify_capability_coverage import check as check_capability_coverage
    coverage_errors = check_capability_coverage(project_root)
    results.append(CheckResult("capability_coverage", not coverage_errors,
                               "; ".join(coverage_errors) if coverage_errors else "GUI actions and business inventory reviewed"))
    from verify_gui_test_coverage import check as check_gui_test_coverage
    gui_errors = check_gui_test_coverage(project_root)
    results.append(CheckResult('gui_test_coverage', not gui_errors,
                               '; '.join(gui_errors) if gui_errors else 'GUI test ownership preflight passed'))
    if gui_errors:
        results.append(CheckResult('unittest', False, 'not run: GUI test coverage preflight failed'))
        results.extend(check_must_exist(project_root))
        results.extend(check_must_not_exist(project_root))
        return results
    unittest_result, unittest_output = run_unittest(project_root)
    results.append(unittest_result)
    if unittest_result.passed:
        results.append(check_required_baseline_tests(unittest_output))
    results.extend(check_must_exist(project_root))
    results.extend(check_must_not_exist(project_root))
    return results


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    print(f"Project root: {project_root}")
    print()

    results = collect_results(project_root)
    for r in results:
        print(r.render())

    print()
    failed = [r for r in results if not r.passed]
    if failed:
        print(f"FAILED: {len(failed)} check(s) failed")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    # The packaging entry uses Python isolated mode. Resolve sibling checks
    # from this script rather than relying on cwd, PYTHONPATH or site-packages.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
