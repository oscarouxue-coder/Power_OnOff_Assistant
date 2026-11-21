# GUI 文件与类清单

由 `audit_inventory.py` 静态生成；构造点不等于独立窗口数量。间接导入、动态工厂与运行时行为仍需逐模块验证。

| 文件 | 类及定义行 | 窗口构造位置 | Var / 定时器 / 绑定 |
| --- | --- | --- | --- |
| `line_check_assistant/app.py` | LineCheckAssistant:376 | Toplevel:1388, Toplevel:1806, Toplevel:2193, Toplevel:3794, Toplevel:4731, Toplevel:7818, Toplevel:8221, Tk:379 | 125 / 46 / 57 |
| `line_check_assistant/pipeline_window.py` | PipelineWindow:72 | Toplevel:81 | 0 / 0 / 2 |
| `src/ui/adapter_rename_dialog.py` | AdapterRenameDialog:40 | Toplevel:52 | 2 / 2 / 3 |
| `src/ui/ai_action_approval.py` | AiActionApproval:11 | Toplevel:47 | 0 / 0 / 1 |
| `src/ui/ai_assistant_controller.py` | AiAssistantController:14 | — | 0 / 4 / 0 |
| `src/ui/ai_chat_markdown.py` | MarkdownLine:8 | — | 0 / 0 / 0 |
| `src/ui/ai_chat_panel.py` | AiChatPanel:41 | Toplevel:313 | 0 / 2 / 4 |
| `src/ui/ai_chat_status.py` | AiChatStatus:23 | — | 0 / 0 / 1 |
| `src/ui/ai_context_status.py` | AiContextStatus:6 | — | 1 / 0 / 1 |
| `src/ui/ai_diagnostic_task_control.py` | DiagnosticTaskControl:9 | Toplevel:70 | 0 / 0 / 2 |
| `src/ui/ai_diagnostics_window.py` | AiDiagnosticsWindow:20 | Toplevel:57 | 7 / 1 / 9 |
| `src/ui/ai_monitor_status.py` | AiMonitorStatusRow:26 | — | 0 / 0 / 1 |
| `src/ui/ai_monitor_window.py` | AiMonitorWindow:13 | Toplevel:39 | 9 / 0 / 4 |
| `src/ui/ai_multi_instance_tab.py` | MultiInstanceTab:14 | Toplevel:304 | 11 / 2 / 7 |
| `src/ui/ai_permission_control.py` | AiPermissionControl:8 | — | 0 / 0 / 1 |
| `src/ui/ai_record_presentation.py` | RecordTitleDialog:57, AiRecordActions:89 | Toplevel:153 | 0 / 2 / 5 |
| `src/ui/ai_remote_management_tab.py` | RemoteManagementTab:7 | — | 0 / 0 / 0 |
| `src/ui/ai_report_manager.py` | AiReportManager:12 | Toplevel:19 | 1 / 0 / 1 |
| `src/ui/ai_report_target_dialog.py` | AiReportTargetDialog:9 | Toplevel:13 | 0 / 0 / 5 |
| `src/ui/ai_reports_window.py` | AiReportsWindow:19 | Toplevel:42 | 0 / 0 / 2 |
| `src/ui/ai_session_manager.py` | AiSessionManager:13 | Toplevel:20 | 1 / 0 / 1 |
| `src/ui/ai_source_ip_dialog.py` | SourceIpDialog:10 | Toplevel:13 | 1 / 0 / 3 |
| `src/ui/app_update_dialog.py` | _UpdateTask:47, AppUpdateDialog:66 | Toplevel:101 | 2 / 5 / 4 |
| `src/ui/application_icon.py` | — | — | 0 / 0 / 0 |
| `src/ui/capability_management.py` | CapabilityManagement:13 | Toplevel:27, Toplevel:141 | 1 / 4 / 3 |
| `src/ui/channel_list.py` | ChannelList:5 | — | 0 / 0 / 6 |
| `src/ui/closable_notebook.py` | ClosableNotebook:9 | — | 0 / 0 / 2 |
| `src/ui/dingtalk_setup_window.py` | DingTalkSetupWindow:8 | Toplevel:13 | 3 / 2 / 2 |
| `src/ui/dut_config_window.py` | WanFormRules:438, DutConfigWindow:538 | Toplevel:566 | 63 / 3 / 11 |
| `src/ui/feishu_dependency_controller.py` | FeishuDependencyController:53 | Toplevel:81 | 1 / 3 / 1 |
| `src/ui/feishu_dependency_dialog.py` | MissingFeishuSdkDialog:9 | Toplevel:12 | 0 / 0 / 3 |
| `src/ui/feishu_setup_window.py` | FeishuSetupWindow:11 | Toplevel:17 | 3 / 2 / 2 |
| `src/ui/message_push_tab.py` | MessagePushTab:9 | — | 2 / 3 / 1 |
| `src/ui/module_theme.py` | — | — | 0 / 0 / 1 |
| `src/ui/onu_command_editor.py` | OnuCommandEditor:23 | — | 1 / 0 / 0 |
| `src/ui/onu_registered_list.py` | RegisteredOnuList:10 | Toplevel:113 | 2 / 0 / 8 |
| `src/ui/power_test_resume_menu.py` | — | — | 0 / 1 / 1 |
| `src/ui/project_dialogs.py` | — | — | 0 / 0 / 0 |
| `src/ui/project_editor_recovery.py` | EditorRecovery:10 | — | 0 / 5 / 1 |
| `src/ui/project_name_badge.py` | ProjectNameBadge:26 | Toplevel:64 | 0 / 2 / 6 |
| `src/ui/project_status_tooltip.py` | ProjectStatusTooltip:6 | Toplevel:30 | 0 / 2 / 2 |
| `src/ui/project_view_frame.py` | ProjectViewFrame:11 | — | 0 / 4 / 3 |
| `src/ui/project_workspace.py` | ProjectWorkspace:18 | Toplevel:382, Toplevel:483, Toplevel:511, Toplevel:523 | 8 / 3 / 11 |
| `src/ui/serial_terminal.py` | SerialTerminalWindow:52 | Toplevel:118 | 0 / 6 / 3 |
| `src/ui/test_item_pretest_controls.py` | PretestControls:16 | — | 0 / 2 / 0 |
| `src/ui/wifi_test_controls.py` | WifiTestControls:9 | — | 4 / 0 / 1 |
| `src/ui/window_paint.py` | — | — | 0 / 3 / 1 |
| `src/ui/workbench_dashboard.py` | WorkbenchDashboard:9 | — | 3 / 0 / 4 |
| `src/ui/workbench_panels.py` | ScrollColumn:56, WorkbenchPanels:94 | — | 1 / 0 / 8 |
