# Capability Coverage Matrix

本表由 scripts/verify_capability_coverage.py 生成；登记、自动化验证和现场验收分别判断。

业务清单 120 项；已有接口 66 项；部分接入 16 项；待接入 5 项；人工控制面 33 项。
现有诊断/交互接口不代表该组所有管理动作已开放；部分接入见限制列，不将分组数字称为最终覆盖率。

| 功能ID | GUI业务 | 真实入口 | 业务实现 | AI接口 | 状态/限制 | 资源/风险 | 自动化测试入口 |
|---|---|---|---|---|---|---|---|
| channels.refresh | 刷新串口/网卡 | _refresh_resources | serial_inventory/network_adapter | resources.refresh | connected：已有受控接口，真实Windows/模型/DUT验收另列 | host/read | test_capability_devices.py；Windows/真实模型及设备待验收 |
| channels.list | 查询通道配置/状态 | _collect_ai_targets | ChannelConfigStore | channels.list | connected：已有受控接口，真实Windows/模型/DUT验收另列 | configuration/read | test_capability_devices.py；Windows/真实模型及设备待验收 |
| channels.select | 通道勾选/全选/清除 | _set_all_channels_enabled | ChannelConfigStore | channels.select | connected：已有受控接口，真实Windows/模型/DUT验收另列 | configuration/modify | test_capability_channels.py；Windows/真实模型及设备待验收 |
| channels.configure | 通道VLAN/COM/IP/电源绑定 | _persist_config | ChannelConfigStore | channels.configure | connected：已有受控接口，真实Windows/模型/DUT验收另列 | configuration/modify | test_capability_channels.py；Windows/真实模型及设备待验收 |
| network.rename | 网卡重命名 | _on_adapter_renamed | AdapterRenameService | network.rename | connected：已有受控接口，真实Windows/模型/DUT验收另列 | adapter/configuration/dangerous | test_capability_channels.py；Windows/真实模型及设备待验收 |
| network.line_check | 环境线路检查 | _start_all_checks | run_line_check | network.line_check | connected：已有受控接口，真实Windows/模型/DUT验收另列 | adapter/channel/modify | test_capability_devices.py；Windows/真实模型及设备待验收 |
| power.on | 自动上电 | _launch_power_on | turn_on_selected_channels | power.on | connected：已有受控接口，真实Windows/模型/DUT验收另列 | power/channel/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| power.off | 自动下电 | _launch_power_on | turn_off_selected_channels | power.off | connected：已有受控接口，真实Windows/模型/DUT验收另列 | power/channel/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| pipeline.start | 所选三项全流程 | _start_all_checks | PipelineOrchestrator | pipeline.start | connected：已有受控接口，真实Windows/模型/DUT验收另列 | device/wifi/power/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| aging.start | 启动老化/开关机测试 | _start_all_checks | run_legacy_power_test | aging.start | connected：已有受控接口，真实Windows/模型/DUT验收另列 | device/wifi/power/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| aging.stop | 停止测试 | _stop_power_test | PipelineOrchestrator.request_stop | cancel_job | partial：仅受控接口发起的任务可按job_id查询/取消；旧GUI独立批次未接管 | job/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| aging.resume | 失败轮次续跑 | _show_power_test_channel_detail | PowerTestResumeSession.submit | aging.resume | connected：已有受控接口，真实Windows/模型/DUT验收另列 | device/wifi/power/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| aging.status | 通道进度和重试失败历史 | _show_power_test_channel_detail | PowerTestResumeSession | get_job_status | partial：仅受控接口发起的任务可按job_id查询/取消；旧GUI独立批次未接管 | job/read | test_capability_devices.py；Windows/真实模型及设备待验收 |
| logs.power | 本次开关机结果日志 | _open_selected_power_test_log | latest_power_test_result_log | logs.power | connected：已有受控接口，真实Windows/模型/DUT验收另列 | file/read | test_capability_application.py；Windows/真实模型及设备待验收 |
| logs.wifi | 本次WiFi日志/连接历史 | _open_selected_power_test_wifi_log | current_wifi_log | logs.wifi | connected：已有受控接口，真实Windows/模型/DUT验收另列 | file/read | test_capability_application.py；Windows/真实模型及设备待验收 |
| config.telnet | Telnet配置/登录后命令 | _build_test_item_telnet_tab | TestItemConfigStore | configuration.telnet.patch | connected：已有受控接口，真实Windows/模型/DUT验收另列 | configuration/modify | test_capability_application.py；Windows/真实模型及设备待验收 |
| config.commands | 测试项/预期分段/重试配置 | _build_test_item_order_tab | TestItemConfigStore | configuration.order.patch | connected：已有受控接口，真实Windows/模型/DUT验收另列 | configuration/modify | test_capability_application.py；Windows/真实模型及设备待验收 |
| config.defaults | 恢复默认测试项 | _build_test_item_order_tab | TestItemConfigStore | configuration.defaults.prepare | connected：已有受控接口，真实Windows/模型/DUT验收另列 | configuration/modify | test_capability_application.py；Windows/真实模型及设备待验收 |
| pretest.start | 执行预备测试 | _capture_pretest_request | run_pretest | pretest.start | connected：已有受控接口，真实Windows/模型/DUT验收另列 | device/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| pretest.stop | 停止预备测试 | _capture_pretest_request | PretestControls | cancel_job | partial：仅受控接口发起的任务可按job_id查询/取消；旧GUI独立批次未接管 | job/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| config.runtime | 开关机运行参数 | _build_test_item_ui_defaults_tab | LegacyUiDefaultsStore | configuration.runtime.patch | connected：已有受控接口，真实Windows/模型/DUT验收另列 | configuration/modify | test_capability_application.py；Windows/真实模型及设备待验收 |
| config.wifi | WiFi测试配置 | _build_test_item_wifi_tab | TestItemConfigStore | configuration.connect_wifi.patch | connected：已有受控接口，真实Windows/模型/DUT验收另列 | configuration/modify | test_capability_application.py；Windows/真实模型及设备待验收 |
| config.project | 项目信息和版本基准 | _build_test_item_project_info_tab | TestItemConfigStore | configuration.project_info.patch | connected：已有受控接口，真实Windows/模型/DUT验收另列 | configuration/modify | test_capability_application.py；Windows/真实模型及设备待验收 |
| device.version | 查询当前样机版本 | _start_project_info_query | query_device_project_info | device.version | connected：明确版本请求共用受控多通道Job；逐台失败继续、先真实结果后一次AI说明；不重放，现场验收待确认 | adapter/device/modify | test_capability_devices.py, test_ai_version_query.py, test_ai_multichannel_dispatch.py；Windows/真实模型及设备待验收 |
| config.reload_save | 配置保存/重新加载 | _open_test_item_config | TestItemConfigStore | configuration.read | partial：支持按域读取/合并保存及默认命令草稿；GUI编辑器草稿和整套重载尚未接管 | configuration/modify | test_capability_application.py；Windows/真实模型及设备待验收 |
| notifications.config | 消息推送配置 | _open_test_item_config | MessagePushConfigService | notifications.read / notifications.patch | connected：已有受控接口，真实Windows/模型/DUT验收另列 | configuration/modify | test_capability_application.py；Windows/真实模型及设备待验收 |
| notifications.test | 发送测试消息 | _open_test_item_config | send_test_message | notifications.test | connected：已有受控接口，真实Windows/模型/DUT验收另列 | external/dangerous | test_capability_application.py；Windows/真实模型及设备待验收 |
| firmware.full_command | 全包Tftp指令升级 | _start_full_package_upgrade | run_parallel_tftp_command_upgrades | firmware.upgrade | connected：已有受控接口，真实Windows/模型/DUT验收另列 | device/serial/adapter/power/tftp/dangerous | test_capabilities.py, test_capability_upgrade_equivalence.py；Windows/真实模型及设备待验收 |
| firmware.full_put | 全包Tftp Put升级 | _start_full_package_upgrade | run_parallel_tftp_put_upgrades | firmware.upgrade | connected：已有受控接口，真实Windows/模型/DUT验收另列 | device/serial/adapter/power/tftp/dangerous | test_capabilities.py, test_capability_upgrade_equivalence.py；Windows/真实模型及设备待验收 |
| firmware.full_web | 全包Web网关升级 | _start_full_package_upgrade | run_parallel_web_gateway_upgrades | firmware.upgrade | connected：已有受控接口，真实Windows/模型/DUT验收另列 | device/serial/adapter/power/browser/dangerous | test_capabilities.py, test_capability_upgrade_equivalence.py；Windows/真实模型及设备待验收 |
| firmware.page | 页面UBUS升级 | _start_page_upgrade | run_page_upgrade_batch | firmware.upgrade | connected：已有受控接口，真实Windows/模型/DUT验收另列 | device/adapter/dangerous | test_capabilities.py, test_capability_upgrade_equivalence.py；Windows/真实模型及设备待验收 |
| firmware.stop | 安全停止升级 | _stop_sample_upgrade | UpgradeStopControl | cancel_job | partial：仅受控接口发起的任务可按job_id查询/取消；旧GUI独立批次未接管 | job/dangerous | test_capabilities.py, test_capability_upgrade_equivalence.py；Windows/真实模型及设备待验收 |
| firmware.settings | 升级选项保存 | _save_sample_upgrade_settings | SampleUpgradeSettingsStore | settings.read / firmware.settings.patch | connected：已有受控接口，真实Windows/模型/DUT验收另列 | configuration/modify | test_capability_settings.py；Windows/真实模型及设备待验收 |
| parameters.generate | 生成参数表 | _open_parameter_generator | generate_parameter_records | parameters.generate | partial：生成规则共用，当前AI仅保存受控工作区；任意输出目录授权尚待接入 | file/modify | test_capability_devices.py；Windows/真实模型及设备待验收 |
| parameters.preflight | 导入/预检参数表 | _refresh_parameter_preflight | preflight_parameter_targets | parameters.preflight | connected：已有受控接口，真实Windows/模型/DUT验收另列 | file/read | test_capability_devices.py；Windows/真实模型及设备待验收 |
| parameters.write | 批量写样机参数 | _start_sample_parameter_write | run_parallel_sample_parameter_writes | parameters.write | connected：已有受控接口，真实Windows/模型/DUT验收另列 | device/serial/adapter/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| parameters.stop | 停止写参 | _cancel_sample_parameter_write | cancel_event | cancel_job | partial：仅受控接口发起的任务可按job_id查询/取消；旧GUI独立批次未接管 | job/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| onu.connection | OLT登录测试 | _on_onu_telnet_test_clicked | OnuRegistrationService.test_connection | onu.connection | connected：已有受控接口，真实Windows/模型/DUT验收另列 | olt/dangerous | test_capability_onu.py；Windows/真实模型及设备待验收 |
| onu.unregistered | 查询未注册ONU | _on_onu_query_unregistered_clicked | query_unregistered | onu.unregistered | connected：已有受控接口，真实Windows/模型/DUT验收另列 | olt/pon/dangerous | test_capability_onu.py；Windows/真实模型及设备待验收 |
| onu.templates | 查询业务模板 | _on_onu_template_query_clicked | query_templates | onu.templates | connected：已有受控接口，真实Windows/模型/DUT验收另列 | olt/dangerous | test_capability_onu.py；Windows/真实模型及设备待验收 |
| onu.settings | 连接/PON/ID/业务配置 | _save_onu_registration_config | OnuRegistrationStore | settings.read / onu.settings.patch | connected：已有受控接口，真实Windows/模型/DUT验收另列 | configuration/modify | test_capability_settings.py；Windows/真实模型及设备待验收 |
| onu.preview | 生成只读命令预览 | _on_onu_preview_clicked | build_preview | onu.preview | connected：已有受控接口，真实Windows/模型/DUT验收另列 | configuration/read | test_capability_onu.py；Windows/真实模型及设备待验收 |
| onu.register | 单台/批量ONU注册 | _on_onu_register_selected_clicked | OnuRegistrationService.register | onu.register | connected：已有受控接口，真实Windows/模型/DUT验收另列 | olt/pon/onu/dangerous | test_capability_onu.py；Windows/真实模型及设备待验收 |
| onu.cleanup_query | 查询C300离线清理候选 | _on_c300_cleanup_candidates_clicked | query_c300_cleanup_candidates | onu.cleanup_query | connected：已有受控接口，真实Windows/模型/DUT验收另列 | olt/pon/dangerous | test_capability_onu.py；Windows/真实模型及设备待验收 |
| onu.cleanup_retry | 明确单台清理后重试 | _on_onu_register_selected_clicked | OnuRegistrationService.register | onu.register | connected：已有受控接口，真实Windows/模型/DUT验收另列 | olt/pon/onu/dangerous | test_capability_onu.py；Windows/真实模型及设备待验收 |
| onu.registered | 查询已注册ONU | _on_onu_manage_query_clicked | query_registered_candidates | onu.registered | connected：已有受控接口，真实Windows/模型/DUT验收另列 | olt/pon/dangerous | test_capability_onu.py；Windows/真实模型及设备待验收 |
| onu.delete | 删除选中ONU | _on_onu_manage_delete_clicked | OnuBatchDeleteService.delete | onu.delete | connected：已有受控接口，真实Windows/模型/DUT验收另列 | olt/pon/onu/dangerous | test_capability_onu.py；Windows/真实模型及设备待验收 |
| onu.save | 保存OLT配置write | _onu_save_olt_configuration_worker | save_configuration | onu.save | connected：已有受控接口，真实Windows/模型/DUT验收另列 | olt/dangerous | test_capability_onu.py；Windows/真实模型及设备待验收 |
| onu.stop | 停止ONU操作 | _on_onu_stop_clicked | cancel_event | cancel_job | partial：仅受控接口发起的任务可按job_id查询/取消；旧GUI独立批次未接管 | job/dangerous | test_capability_onu.py；Windows/真实模型及设备待验收 |
| dut.telnet_query | 查询Telnet状态 | _query_dut_telnet_status | run_dut_status_query_batch | dut.telnet.query | connected：已有受控接口，真实Windows/模型/DUT验收另列 | adapter/device/modify | test_capability_devices.py；Windows/真实模型及设备待验收 |
| dut.telnet_enable | 开启Telnet | _start_dut_telnet_enable | run_dut_telnet_enable_batch | dut.telnet.enable | connected：已有受控接口，真实Windows/模型/DUT验收另列 | adapter/device/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| dut.wan_query | 查询WAN | _query_dut_wan_connections | run_dut_wan_query_batch | dut.wan.query | connected：已有受控接口，真实Windows/模型/DUT验收另列 | adapter/device/modify | test_capability_devices.py；Windows/真实模型及设备待验收 |
| dut.wan_add | 新增WAN | _start_dut_wan_config | run_dut_advanced_config_batch | dut.wan.configure | connected：已有受控接口，真实Windows/模型/DUT验收另列 | adapter/device/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| dut.wan_modify | 修改WAN | _start_dut_wan_config | run_dut_advanced_config_batch | dut.wan.configure | connected：已有受控接口，真实Windows/模型/DUT验收另列 | adapter/device/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| dut.wan_delete | 删除WAN | _start_dut_wan_config | run_dut_advanced_config_batch | dut.wan.configure | connected：已有受控接口，真实Windows/模型/DUT验收另列 | adapter/device/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| dut.wifi2_query | 查询2.4G WiFi | _query_dut_wifi_2g_status | run_dut_status_query_batch | dut.wifi_2g.query | connected：已有受控接口，真实Windows/模型/DUT验收另列 | adapter/device/modify | test_capability_devices.py；Windows/真实模型及设备待验收 |
| dut.wifi2_config | 配置2.4G WiFi | _start_dut_wifi_2g_config | run_dut_advanced_config_batch | dut.wifi_2g.configure | connected：已有受控接口，真实Windows/模型/DUT验收另列 | adapter/device/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| dut.wifi5_query | 查询5G WiFi | _query_dut_wifi_5g_status | run_dut_status_query_batch | dut.wifi_5g.query | connected：已有受控接口，真实Windows/模型/DUT验收另列 | adapter/device/modify | test_capability_devices.py；Windows/真实模型及设备待验收 |
| dut.wifi5_config | 配置5G WiFi | _start_dut_wifi_5g_config | run_dut_advanced_config_batch | dut.wifi_5g.configure | connected：已有受控接口，真实Windows/模型/DUT验收另列 | adapter/device/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| dut.voice_query | 查询语音 | _query_dut_voice_status | run_dut_status_query_batch | dut.voice.query | connected：已有受控接口，真实Windows/模型/DUT验收另列 | adapter/device/modify | test_capability_devices.py；Windows/真实模型及设备待验收 |
| dut.voice_config | 配置语音 | _start_dut_voice_config | run_dut_advanced_config_batch | dut.voice.configure | connected：已有受控接口，真实Windows/模型/DUT验收另列 | adapter/device/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| dut.tr069_query | 查询TR069 | _query_dut_tr069_status | run_dut_status_query_batch | dut.tr069.query | connected：已有受控接口，真实Windows/模型/DUT验收另列 | adapter/device/modify | test_capability_devices.py；Windows/真实模型及设备待验收 |
| dut.tr069_config | 配置TR069 | _start_dut_tr069_config | run_dut_advanced_config_batch | dut.tr069.configure | connected：已有受控接口，真实Windows/模型/DUT验收另列 | adapter/device/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| dut.stop | 停止DUT配置/查询 | _stop_dut_telnet_enable | stop_event | cancel_job | partial：仅受控接口发起的任务可按job_id查询/取消；旧GUI独立批次未接管 | job/dangerous | test_capability_devices.py；Windows/真实模型及设备待验收 |
| serial.open | 打开指定/全部串口日志 | _open_serial_log_module | SerialSessionManager.acquire_monitor | serial.monitor.open | connected：已有受控接口，真实Windows/模型/DUT验收另列 | serial/modify | test_capability_application.py；Windows/真实模型及设备待验收 |
| serial.close | 停止监控/关闭标签 | _open_serial_log_module | SerialSessionManager.release | serial.monitor.close | partial：关闭自己取得的被动监控，不关闭其它GUI标签/所有权 | serial/modify | test_capability_application.py；Windows/真实模型及设备待验收 |
| serial.send | 串口文本/回车发送 | _open_serial_log_module | SerialTerminal.send | 待接入 | pending：任意文本发送涉及Shell/Boot控制；必须复用A2及已审阅执行模板，不能增加裸串口写入后门 | serial/device/dangerous | 待接入/人工控制，无执行验收 |
| serial.read | 被动串口日志 | _open_serial_log_module | read_serial_log | read_serial_log | connected：已有受控接口，真实Windows/模型/DUT验收另列 | serial/read | test_capability_application.py；Windows/真实模型及设备待验收 |
| serial.status | 实时串口状态 | _open_serial_log_module | read_serial_status | serial.status | connected：已有受控接口，真实Windows/模型/DUT验收另列 | serial/read | test_capability_application.py；Windows/真实模型及设备待验收 |
| serial.directory | 串口日志目录 | _on_serial_log_directory_changed | SerialTerminal | 待接入 | pending：当前工作区监控输出可用；主串口窗口保存目录及正在打开日志的归属适配待完成 | configuration/modify | 待接入/人工控制，无执行验收 |
| ai.profiles | 模型配置增改复制删除选择 | _open_ai_assistant | DiagnosticStore | ai.profiles.list | partial：仅查询模型元数据；模型/密钥配置写入与选择仍须本地控制面，尚未开放自动化适配 | configuration/modify | test_capability_ai_data.py；Windows/真实模型及设备待验收 |
| ai.source_ip | 模型出口IP枚举与设置 | _open_ai_assistant | list_source_ips / DiagnosticStore | ai.source_ip.list / ai.profiles.list | partial：共用本机IPv4枚举及已保存配置；设置/保存仍为本地模型配置控制面，AI写入尚未开放 | configuration/modify | test_capability_ai_data.py；Windows/真实模型及设备待验收 |
| ai.models_test | 模型列表/连接测试 | _open_ai_assistant | DiagnosticClient | ai.models.query / ai.models.test | connected：已有受控接口，真实Windows/模型/DUT验收另列 | external/modify | test_capability_ai_data.py；Windows/真实模型及设备待验收 |
| ai.conversation | 对话/连续诊断/停止/进展 | _open_ai_assistant | AiConversationService | existing_interaction | partial：已有受控接口，真实Windows/模型/DUT验收另列 | conversation/modify | test_capability_ai_data.py；Windows/真实模型及设备待验收 |
| ai.evidence | 文本导入/证据检索 | _open_ai_assistant | AiEvidenceContext | ai.evidence.import / read_test_evidence | partial：已有受控接口，真实Windows/模型/DUT验收另列 | file/read | test_capability_ai_data.py；Windows/真实模型及设备待验收 |
| ai.sessions | 会话查询/重命名/删除清空 | _open_ai_assistant | DiagnosticStore | ai.sessions.list/read/rename/delete | connected：已有受控接口，真实Windows/模型/DUT验收另列 | data/modify | test_capability_ai_data.py；Windows/真实模型及设备待验收 |
| ai.sessions_create | 创建空白新会话 | _open_ai_assistant | AiConversationService.create_blank_session | ai.sessions.create | connected：已有受控接口，真实Windows/模型/DUT验收另列 | conversation/modify | test_capability_ai_data.py；Windows/真实模型及设备待验收 |
| ai.reports | 报告查询/重命名/删除清空 | _open_ai_assistant | DiagnosticStore | ai.reports.list/read/rename/delete | connected：已有受控接口，真实Windows/模型/DUT验收另列 | data/modify | test_capability_ai_data.py；Windows/真实模型及设备待验收 |
| ai.continue_report | 报告接手排查 | _open_ai_assistant | create_session_from_report | ai.reports.continue | connected：已有受控接口，真实Windows/模型/DUT验收另列 | conversation/modify | test_capability_ai_data.py；Windows/真实模型及设备待验收 |
| ai.cases | 案例创建/修订/启停/删除 | _open_ai_assistant | SharedCaseStore | ai.cases.query / ai.cases.set_active / ai.cases.delete | partial：可查询/按版本启停/删除；新增和内容修订中的根因/复测确认保留真实人工控制面 | data/modify | test_capability_ai_data.py；Windows/真实模型及设备待验收 |
| ai.case_confirmation | 人工确认根因及复测 | _open_ai_assistant | confirm_case | local_confirmation | manual_control：必须由真实操作员确认，AI可准备材料但不能自我批准 | human_control/manual | 待接入/人工控制，无执行验收 |
| ai.monitor | 监控设置/启停/状态 | _open_ai_assistant | AiMonitorService | 待接入 | pending：Tk 与 Qt 复用本地监控授权和逐操作审批；Qt 通道诊断与批量范围由操作员确认，Agent 不得自行签发或扩大范围 | monitor/modify | 待接入/人工控制，无执行验收 |
| ai.permissions | 权限切换/批准/拒绝 | _open_ai_assistant | AiPermissionService | local_confirmation | manual_control：必须由真实操作员确认，AI可准备材料但不能自我批准 | human_control/manual | 待接入/人工控制，无执行验收 |
| remote.dingtalk | 钉钉配置/启停/绑定/取消 | _configure_dingtalk_remote | DingTalkRemoteService | 待接入 | pending：远程业务调用已校验真实来源；接入配置/启停及AI卡片模板仍属本地授权控制面，尚需专用适配；流式为已有会话的显示投影 | external/configuration/modify | 待接入/人工控制，无执行验收 |
| remote.feishu | 飞书配置/启停/绑定/取消/试发 | _configure_feishu_remote | FeishuRemoteService | 待接入 | pending：远程业务调用已校验真实来源；接入配置/启停及卡片权限仍属本地授权控制面，尚需专用适配；流式为已有会话的显示投影 | external/configuration/modify | 待接入/人工控制，无执行验收 |
| remote.feishu_sdk_repair | 安装飞书SDK并重启源码 | open | FeishuDependencyRepair | local_confirmation | manual_control：仅本机缺包弹窗由操作员选择安装；修改运行环境并重启，AI不可触发或代确认 | python-environment/process/manual | test_feishu_dependency_repair.py, test_qt_workspace_adapter.py, qt_workbench_probe.py；Windows/真实模型及设备待验收 |
| remote.binding_confirm | 群身份绑定确认 | _build_ai_remote_management | remote.confirm_binding | local_confirmation | manual_control：必须由真实操作员确认，AI可准备材料但不能自我批准 | human_control/manual | 待接入/人工控制，无执行验收 |
| remote.instances | 多实例接入状态 | _open_ai_assistant | RemoteInstanceManagement.status | remote.instances.status | connected：已有受控接口，真实Windows/模型/DUT验收另列 | configuration/read | test_remote_instance_management.py；Windows/真实模型及设备待验收 |
| remote.instance_configuration | 实例配对/启动模式/本地范围 | _open_ai_assistant | RemoteInstanceManagement | local_confirmation | manual_control：接入配置、配对、范围、启停及撤销仅本机操作员确认；AI不能生成配对码或自授权 | human_control/manual | 待接入/人工控制，无执行验收 |
| remote.gateway_configuration | 网关配置/启停/配对码/撤销 | _open_ai_assistant | RemoteGatewayHost | local_confirmation | manual_control：接入配置、配对、范围、启停及撤销仅本机操作员确认；AI不能生成配对码或自授权 | human_control/manual | 待接入/人工控制，无执行验收 |
| updates.check | 检查更新 | _build_ui | AppUpdateService.check_for_update | updates.check | connected：已有受控接口，真实Windows/模型/DUT验收另列 | external/read | test_capability_application.py；Windows/真实模型及设备待验收 |
| updates.download | 下载更新/取消 | _build_ui | AppUpdateService.download_update | updates.download | partial：原更新服务校验及取消共用；AI仅下载到受控工作区，任意目标目录授权待接入 | external/file/modify | test_capability_application.py；Windows/真实模型及设备待验收 |
| projects.list | 查询已打开项目 | _update_menu | WorkspaceService / ProjectStore | workspace.projects.list | connected：仅local/gui查询项目身份和状态；不切换目标、不扩大权限 | project/configuration/read | test_project_management.py, test_project_workspace.py, test_workspace_platforms.py, test_project_completion.py, test_multi_project_business_validation.py；Windows/真实模型及设备待验收 |
| projects.create | 新建项目 | new_project | WorkspaceService / ProjectStore | local_confirmation | manual_control：涉及本地目录所有权、配置版本、运行生命周期或远程授权，限本机操作员；AI不可模拟GUI或自行确认 | project/configuration/manual | test_project_management.py, test_project_workspace.py, test_workspace_platforms.py, test_project_completion.py, test_multi_project_business_validation.py；Windows/真实模型及设备待验收 |
| projects.open | 打开或切换项目 | open_project | WorkspaceService / ProjectStore | local_confirmation | manual_control：涉及本地目录所有权、配置版本、运行生命周期或远程授权，限本机操作员；AI不可模拟GUI或自行确认 | project/configuration/manual | test_project_management.py, test_project_workspace.py, test_workspace_platforms.py, test_project_completion.py, test_multi_project_business_validation.py；Windows/真实模型及设备待验收 |
| projects.save | 保存项目及页面草稿 | save_project | WorkspaceService / ProjectStore | local_confirmation | manual_control：涉及本地目录所有权、配置版本、运行生命周期或远程授权，限本机操作员；AI不可模拟GUI或自行确认 | project/configuration/manual | test_project_management.py, test_project_workspace.py, test_workspace_platforms.py, test_project_completion.py, test_multi_project_business_validation.py；Windows/真实模型及设备待验收 |
| projects.duplicate | 另存为独立项目 | duplicate_project | WorkspaceService / ProjectStore | local_confirmation | manual_control：涉及本地目录所有权、配置版本、运行生命周期或远程授权，限本机操作员；AI不可模拟GUI或自行确认 | project/configuration/manual | test_project_management.py, test_project_workspace.py, test_workspace_platforms.py, test_project_completion.py, test_multi_project_business_validation.py；Windows/真实模型及设备待验收 |
| projects.rename | 重命名项目 | rename_project | WorkspaceService / ProjectStore | local_confirmation | manual_control：涉及本地目录所有权、配置版本、运行生命周期或远程授权，限本机操作员；AI不可模拟GUI或自行确认 | project/configuration/manual | test_project_management.py, test_project_workspace.py, test_workspace_platforms.py, test_project_completion.py, test_multi_project_business_validation.py；Windows/真实模型及设备待验收 |
| projects.import | 备份并导入旧配置及历史 | import_project | WorkspaceService / ProjectStore | local_confirmation | manual_control：涉及本地目录所有权、配置版本、运行生命周期或远程授权，限本机操作员；AI不可模拟GUI或自行确认 | project/configuration/manual | test_project_management.py, test_project_workspace.py, test_workspace_platforms.py, test_project_completion.py, test_multi_project_business_validation.py；Windows/真实模型及设备待验收 |
| projects.close | 安全关闭项目 | close_project | WorkspaceService / ProjectStore | local_confirmation | manual_control：涉及本地目录所有权、配置版本、运行生命周期或远程授权，限本机操作员；AI不可模拟GUI或自行确认 | project/configuration/manual | test_project_management.py, test_project_workspace.py, test_workspace_platforms.py, test_project_completion.py, test_multi_project_business_validation.py；Windows/真实模型及设备待验收 |
| projects.forget | 从最近列表移除 | forget_project | WorkspaceService / ProjectStore | local_confirmation | manual_control：涉及本地目录所有权、配置版本、运行生命周期或远程授权，限本机操作员；AI不可模拟GUI或自行确认 | project/configuration/manual | test_project_management.py, test_project_workspace.py, test_workspace_platforms.py, test_project_completion.py, test_multi_project_business_validation.py；Windows/真实模型及设备待验收 |
| projects.remote_scope | 本机确认远程项目范围 | remote_project_range | WorkspaceService / ProjectStore | local_confirmation | manual_control：涉及本地目录所有权、配置版本、运行生命周期或远程授权，限本机操作员；AI不可模拟GUI或自行确认 | project/configuration/manual | test_project_management.py, test_project_workspace.py, test_workspace_platforms.py, test_project_completion.py, test_multi_project_business_validation.py；Windows/真实模型及设备待验收 |
| projects.resolve_unknown | 本机核实GUI未知任务 | resolve_unknown | WorkspaceService / ProjectStore | local_confirmation | manual_control：涉及本地目录所有权、配置版本、运行生命周期或远程授权，限本机操作员；AI不可模拟GUI或自行确认 | project/configuration/manual | test_project_management.py, test_project_workspace.py, test_workspace_platforms.py, test_project_completion.py, test_multi_project_business_validation.py；Windows/真实模型及设备待验收 |
| projects.imported_connection | 选择导入的接入配置 | imported_connection | WorkspaceService / ProjectStore | local_confirmation | manual_control：涉及本地目录所有权、配置版本、运行生命周期或远程授权，限本机操作员；AI不可模拟GUI或自行确认 | project/configuration/manual | test_project_management.py, test_project_workspace.py, test_workspace_platforms.py, test_project_completion.py, test_multi_project_business_validation.py；Windows/真实模型及设备待验收 |
| remote.platform_direct | 本机启停钉钉和飞书直连排障 | change_direct | QtDirectPlatforms / WorkspacePlatformPool / 原平台服务 | local_confirmation | manual_control：启用要求本机授权项目，进入已绑定群或飞书企业单聊，实时核对原平台身份和权限。 | project/configuration/manual | test_qt_workspace_adapter.py；Windows/真实模型及设备待验收 |
| remote.feishu_automatic_notifications | 启停飞书挂测通知 | change_notifications | QtFeishuNotifications / FeishuNotificationService | local_confirmation | manual_control：使用已绑定群和保存的项目名称，停用会阻止后续自动通知。 | project/configuration/manual | test_qt_workspace_adapter.py, qt_workbench_probe.py；Windows/真实模型及设备待验收 |
| jobs.local_safe_stop | 本机请求选中任务安全停止 | _request_stop | QtJobControl / CapabilityJobs | local_confirmation | manual_control：仅接受本进程当前项目内的活跃任务，选定任务独立收尾。 | project/run/manual | test_qt_workspace_adapter.py；Windows/真实模型及设备待验收 |
| extensions.review | 本机审阅登记或启停受控扩展 | import_template | QtControlledExtensions / CapabilityExtensions | local_confirmation | manual_control：绑定项目与审阅哈希，继承目标操作原授权与资源范围。 | project/run/manual | test_qt_workspace_adapter.py, qt_workbench_probe.py；Windows/真实模型及设备待验收 |
| remote.platform_credentials | 本机编辑钉钉或飞书应用配置 | save | QtPlatformConfiguration / RemoteConfigStore / FeishuConfigStore | local_confirmation | manual_control：只保存平台应用配置，凭据交由原加密存储，保存后保持停用。 | project/configuration/manual | test_qt_workspace_adapter.py, qt_workbench_probe.py；Windows/真实模型及设备待验收 |
| remote.platform_binding | 本机开始、确认或取消机器人群绑定 | change_binding | QtPlatformConfiguration / WorkspacePlatformPool / 原平台服务 | local_confirmation | manual_control：只启用临时群绑定连接，确认当前项目及群身份，结束后回收连接。 | project/configuration/manual | test_qt_workspace_adapter.py, qt_workbench_probe.py；Windows/真实模型及设备待验收 |
| remote.feishu_trial | 向绑定群发送一条飞书测试消息 | start_trial | QtPlatformConfiguration / FeishuNotificationService | local_confirmation | manual_control：先确认已保存项目和群 ID，再调用原固定消息队列。平台受理和群收到分别核对。 | project/configuration/manual | test_qt_workspace_adapter.py；Windows/真实模型及设备待验收 |
| projects.model_presets | 保存和应用产品型号模板 | _save_preset | QtProjectWizardService / ProjectModelPresets | local_confirmation | manual_control：操作员选择已保存版本并确认跨项目共享的型号方案 | project/run/manual | test_qt_workspace_adapter.py, qt_project_wizard_probe.py；Windows/真实模型及设备待验收 |
| projects.test_profile | 创建或恢复测试项目档案 | _save | ProjectStore / QtProjectWizardService | local_confirmation | manual_control：仅本机选择目录、测试类型和测试计划 | project/run/manual | test_project_profile_store.py, qt_project_wizard_probe.py；Windows/真实模型及设备待验收 |
| service_aging.start | 开始持续供电业务老化 | start_test | QtServiceAging / ServiceAging | service_aging.start | manual_control：仅 GUI，可追溯到本次确认的项目、DUT 和资源 | project/run/manual | test_qt_execution_adapter.py, test_service_aging.py；Windows/真实模型及设备待验收 |
| service_aging.record | 记录现场观察、日检或期末检查 | _record | QtServiceAging / ServiceAging | service_aging.record | manual_control：仅 GUI，本机操作人提供实际观测和结果 | project/run/manual | test_service_aging.py；Windows/真实模型及设备待验收 |
| service_aging.history | 查看及导出指定批次业务证据 | _export | ServiceAgingHistory | local_confirmation | manual_control：仅本机选择项目、批次和导出文件 | project/run/manual | test_service_aging.py, qt_project_wizard_probe.py；Windows/真实模型及设备待验收 |
| service_aging.channel_evidence | 查看所选 DUT 或普通聊天明确 CH 的掉线证据 | open_evidence | read_channel_evidence / ServiceAgingHistory | service_aging.channel_evidence | manual_control：仅本机 GUI 在冻结的项目、批次和通道内读取已有观测。普通聊天通过 _send_chat_evidence 核对明确 CH，带请求编号的结果仅当前窗口显示；停止本轮仅取消该本地读请求 | project/run/manual | test_qt_channel_evidence.py, qt_channel_evidence_probe.py；Windows/真实模型及设备待验收 |
| history.material_summary | 汇总选定批次通道的本地留存结果文件 | _request_summary | summarize_history_materials / summarize_history_materials_batch / qt_power_logs | history.material_summary | manual_control：仅本机 GUI 从同一已核对历史批次选择一至十六个原通道，逐通道复用既有有界只读能力；原文正文不展开，不提供模型或远端能力 | project/run/manual | test_qt_log_history.py, qt_workbench_probe.py；Windows/真实模型及设备待验收 |
| history.material_report_save | 保存当前已生成的本地历史报告 | _request_save_report | save_material_report / qt_power_logs | history.material_report_save | manual_control：仅本机 GUI 明确保存已核对批次的生成回执，不接受任意正文、路径或重跑，不提供模型或远端能力 | project/run/manual | test_qt_log_history.py, qt_workbench_probe.py；Windows/真实模型及设备待验收 |
| history.material_reports | 查看选定历史批次已保存报告 | _request_saved_reports | read_material_reports / qt_power_logs | history.material_reports | manual_control：仅本机 GUI 在所选项目任务及原运行范围中查看保存的历史报告，不读取原资料或执行任务 | project/run/manual | test_qt_log_history.py, qt_workbench_probe.py；Windows/真实模型及设备待验收 |

## GUI动作审查

当前审查快照包含 845 个按钮/菜单/绑定/变量回调。新增或改变入口会使门禁失败。
界面辅助动作（窗口显隐/滚动/复制/显密/清屏等）不计业务覆盖；动态控件须结合运行测试复核。
Qt 拦截提示的「前往确认」是本机定位动作，使用原请求项目与结构化目标打开配置、对象或任务视图。保存、执行和人工批准继续使用原业务入口及权限检查。

## 当前阶段

固件升级与基础设施是首批；待接入条目保持，不能将首批通过表述为Full Capability Agent已经完成。
暂停/恢复不是已存在的通用测试接口；SSH目前属于旧挂测路径。原始字节归档及A7有界缓冲不在本轮。

## Qt迁移入口审查

Qt信号connect、菜单addAction及子目录界面纳入动作快照。Qt项目新建/打开/旧配置导入/保存/重命名/复制/关闭复用WorkspaceService与ProjectStore，沿用projects.*的manual_control边界。旧导入执行原备份、配置和历史转换，启用平台与远程项目范围仍须在原入口重新确认。
独立组件展示页（--showcase）中的控件只操作窗口内的示例数据。该预览没有项目上下文或业务绑定，属于本机展示交互。
工作台改版预览（--visual-preview）以同一组模拟快照对比当前版与改版。切页、确认和日志筛选属于本机展示交互，模拟起停只显示窗口反馈。
高频业务窗口评审从独立工作台预览打开。串口、升级、DUT、测试项和通道配置窗口使用示例快照，窗口交互不接入真实项目或业务控制器。
持续供电老化的本机向导可将已选业务配置成现场采集来源。service_aging.start 绑定保存的计划与本批 DUT，按清单读取本地观测文件；人工检查仍走 service_aging.record。
Qt自动开关机、环境检查与三项全流程复用aging.start、network.line_check及pipeline.start，通过原CapabilityService、Jobs和资源准入。全流程本机明确选择三项，复用Qt串口终端逐个预启动已确认通道，日志目录和工序绑定项目。停止只取消当前Qt准入的原任务，不接管旧GUI批次。
Qt单次自动上/下电通过仅本机界面可用的power.qt_single和一次确认令牌绑定项目、通道、所选电源口及方向，沿用原Jobs资源准入和单次电源服务。空电源口仅记录人工重启确认。通用power.on/off仍使用项目配置电源口。
Qt最近项目沿用 projects.open 与 projects.forget 的本机人工控制面。菜单使用原工作区最近记录，移除仅改记录文件，项目仍保持打开。新建、打开、保存快捷键复用原菜单动作。打开项目目录仅由本机操作员触发，按所选已打开项目定位目录。
Qt选择导入的接入配置沿用 projects.imported_connection 本机人工控制面。只展示来源标签，保存前复核候选、当前配置和停用状态，沿用原加密存储和连接占用保护。
Qt任务历史保留原结果、事件和原有核实依据，可对本进程运行中的原任务请求安全停止。Tk 兼容入口保留 projects.resolve_unknown 和 jobs.resolve_unknown。
Qt工作台、本机 AI 和项目群内明确发起的业务复用同一资源准入。程序确认旧进程已退出及相关锁已释放后自动清理旧占用。新请求继续走原权限、审批和业务确认，同一请求仍关联原任务。
Qt任务历史可以分页查看旧工作台运行记录。只读取已打开项目的原 GUI 运行记录，历史页没有设备控制操作，业务任务和事件继续使用原项目 Job 库。
Qt AI 模型连接复用 ai.profiles、ai.source_ip、ai.models_test 对应的原共享模型存储、项目选择、出口枚举与模型客户端。本机配置编辑及加密密钥写入只出现在人工控制面。连接测试仅调用原无项目资料样例，Qt 未扩大模型、DUT 或远程权限。
Qt Ai助手复用原 AiConversationService、项目会话持久化和证据服务。普通问答无工具，报告会话可分析留存材料。本机电脑连续诊断复用原只读工具、PcConversationExecutor 与原停止机制，沿用模型工具资格及项目会话约束。创建和切换会话是本机人工操作。Qt 本机通道诊断由 diagnostics.qt.configure 核对操作员、目标与策略，监控和多通道排查复用 AiMonitorService 和 AiBatchService。
Qt 实时 AI 日志复用既有主界面摘要规则，在显示交接缓冲前压缩已知正常过程并保留可辨识异常。工作区归档仍保存原服务已过滤模型密钥的原文。显示处理不授予采集、执行或远程权限。
Qt AI 会话与 Tk 共用原 Markdown 展示解析，链接和未支持标记保持为文字。会话状态与正文独立刷新。Enter / Ctrl+Enter 复用现有发送入口，Alt+Enter 插入换行；模型与设备权限沿用原入口。
Qt 排查进展沿用当前项目及所选会话的留存记录，使用与 Tk 共用的只读展示逻辑。查看进展属于本地人工查阅，不启动诊断和采集。
Qt 会话权限查询由本机操作员发起，通过原会话权限服务核对偏好、有效模式和取证资格，归入人工控制面。
Qt 网关登记实例、本机网关启停及撤销沿用原管理服务。具体操作审批复核所选项目会话、操作编号与指纹后调用原决定服务。两项均为本机人工控制面。
一次性配对码的签发、复制和兑换仅供本机人工操作。通过原网关与实例管理服务复核已保存的成员范围及实例槽位；不登记为 AI 或远程可执行能力。
Qt 管理会话属于本机人工控制面。重命名使用原标题服务，批量删除提交操作者确认时固定的项目会话 ID。沿用原 AiConversationService 的忙碌拦截、子会话管理和删除事务；模型和远程工具不提供此界面控制入口。
Qt 诊断报告复用 ai.reports 对应的项目报告库、标题服务、删除保护和原报告接手服务。批量删除复核确认名单。旧报告由本机确认同通道目标并复核当前快照，接手只创建留存会话，主动诊断通过本机确认的当前通道会话进入。
Qt 已确认案例沿用 ai.cases 的共享库、版本检查和启停/删除服务。从报告仅关联来源，新增和修订需操作者填写五项事实并本机确认，属于 ai.case_confirmation 人工控制面。
Qt 全局设置检查更新使用 updates.check / updates.download 对应的原 AppUpdateService。交互下载由本机选择 ZIP 位置及确认覆盖，沿用原 HTTPS、校验和临时文件保护。下载完成可打开目录，安装仍为人工操作。
Qt 设备管理复用 resources.refresh 的只读主机枚举，并显示已有通道和资源保护记录。逐 DUT 的 ADB 标识由本机向导声明，租约使用冻结的配置。
Qt 网卡改名从通道选择触发，channels.editor.rename_* 只供本机 GUI。确认绑定网卡 GUID、项目通道草稿及新名称，复用原单次 Windows 改名和回读，复核后同步所有打开项目。确认未知时保留原资源保护。本机 AI 和远程的 network.rename 权限未扩大。
Qt失败轮次续跑以原PowerTestResumeSession判定通道资格。aging.qt_resume.confirm仅限本机逐条确认。运行中复用原批次，结束后按确认顺序逐条复核并由aging.resume任务取得原通道资源。安全停止或关闭时取消等待项，等待项不自动恢复。沿用原提交、版本预检、控制队列和停止服务。保留原批次结论及其他通道进度。
Qt六标签配置编辑复用TestItemConfigStore、LegacyUiDefaultsStore、MessagePushConfigService和原项目版本保存；configuration.editor.*仅gui来源，私有字段不返回AI/远程。保存复核版本与任务占用。预备测试使用本机pretest.editor.*确认的当前测试项和Telnet草稿，经原Job和单次服务执行，关闭先停并等待收尾。version.editor.*绑定单一通道和当前Telnet草稿，经原Job及样机版本服务查询，只读显示。notifications.editor.*仅供本机确认当前Webhook、广播选项和已保存项目名后，经原服务单次试发；不授予AI或远程草稿发送权限。
Qt六标签页面恢复草稿由本机configuration.editor.checkpoint保存，按项目和版本加密。恢复或清除需本机选择。恢复只回填窗口，沿用现有保存校验和准入。
Qt通道编辑通过channels.editor.*仅gui来源预览/确认，数据投影复用原ChannelCapabilities.prepare/commit及ChannelConfigStore，仍只写已选通道；补齐16槽位不代表设备正在运行。主工具栏和通道编辑器共用本机只读串口/网卡枚举，串行读取独立于项目控制队列，保留选择和失败来源的上次清单。工作区空闲时核对身份登记，活动租约由原任务和准入服务维护。常规保存只提交授权范围内的配置；矩阵/列表共用实际快照。
主界面环境配置中的旧 DUT 绑定、移出本批和通道 DUT 信息编辑仅供本机操作员使用。它们随 channels.editor.preview/save 核对并同版提交，保留原历史和资源范围。
Qt串口窗口通过serial.terminal.*仅gui来源共享原SerialSessionManager/PySerialSession：显示不打开COM，监控/手动发送/停止由后台执行，危险命令本机确认；关闭只释放自己的所有权，升级控制锁及实际收尾保护保留。显示缓冲有界，原日志独立落盘。诊断快照通过serial.terminal.diagnostics读取原会话的近期接收数据及程序内占用状态。升级和写参串口路径已接入本机自动只读观察，模型会话实时串口联动待接入。
Qt 串口和 DUT 的窗口状态由当前项目的本机界面保存，复用原 UI 状态文件。包含尺寸、位置和 DUT 各页状态区高度。保存偏好不调用设备执行、AI 或远程控制能力。
Qt 的全流程、测试项配置、样机升级、写样机参数、ONU 注册和通道重试历史沿用当前项目原 module_windows.json 的宽高记录。窗口偏好通过已有后台工作线程合并保存。
Qt日志范围根据实际项目、完整Job ID和原结构化通道字段筛选。实时批次仅追加匹配行及移除超出显示上限的记录。导出由本机文件选择发起，使用触发时的筛选快照，只写入用户选定的新TXT，原日志、任务和AI访问范围保持。
Qt 通道右键菜单打开开关机结果日志或本次 WiFi 日志。定位沿用 latest_power_test_result_log / current_wifi_log，只将已校验的项目日志路径交给 Windows 文件关联。本机打开动作不授予 AI 或远程桌面操作能力，日志读取仍由原受控入口处理。
Qt 通道详情和右键菜单允许本机分页查看当前开关机批次的原重试/失败事件及续跑记录。按项目、任务和授权通道绑定，只读任务库，沿用原业务状态和原因。
Qt 运行概览的成功、失败和当前异常卡片是本机只读展示入口，使用当前项目与任务的已发布快照。点击打开详情并记录查阅结果，属于界面操作。
Qt 任务历史的批次结果文件仅供本机操作员。使用原任务库、项目运行快照和原通道范围定位，浏览不读取正文，打开交给 Windows 文件关联。历史 WiFi 文件保持所选批次归属，不登记为当前尝试或扩大 AI / 远程权限。
Qt任务历史通过本机只读窗口预筛当前页，并可按通道、级别、关键词查询选定项目的完整任务事件。按匹配记录分页，导出只写用户选定的新TXT。
Qt 项目和设置菜单的多实例接入状态复用 remote.instances.status 的 RemoteInstanceManagement.status 只读服务。打开或刷新只读取当前状态。
Qt 下次启动配置属于本机人工控制面。槽位和已保存的范围由原 RemoteInstanceManagement 读取。操作员明确选择通道与业务能力后，使用当前项目实际注册的远程能力复核，并由原服务保存待重启配置。
Qt 项目和设置菜单共用 projects.remote_scope 本机人工控制面。按完整项目 ID 显示新增和撤销，以默认取消确认；后台复核已打开项目身份及原范围后调用 WorkspaceService.set_remote_projects。AI 和平台没有授权编辑入口。
Qt归档日志是本机人工阅读入口。工作区原文、当前项目串口、主执行日志和资源监测文件按页只读。筛选导出沿用现有本机保存方式，不授予 AI 或远程访问。
Qt系统状态面板只读展示工作区响应、日志写入、显示积压、任务日志和现有资源租约。展开与收起只影响显示，不新增业务能力。
工作台的全局统计和日志按项目 ID 筛选。侧栏项目、历史和设置复用原有操作及权限。测试模板仅导航到已打开的源项目，设备侧栏读取缓存，显式刷新沿用原资源枚举。
Qt DUT六页通过dut.editor.*仅gui来源接入原查询/配置服务和任务资源管理。本机确认、版本/NIC/查询绑定与安全停止统一；私有字段只供本机回填，任务结果和日志隐藏密码。WiFi原能力/SSID递增/双频/60秒等待、语音线路/编码顺序、TR069能力过滤和手动Inform均沿用原服务。真实设备验收另列。
Qt样机升级通过firmware.editor.*本机界面控制，任务和执行仍使用firmware.upgrade和原四套引擎。项目升级选项沿用原配置文件和项目版本，编辑凭据仅在本机GUI回填。固件哈希、网卡、安全停止及只读串口观察使用原任务链。缺少程控电源时由Qt本机确认已手动重启；通用能力参数和原远程准入保持。
Qt写样机参数通过parameters.editor.*本机入口，沿用原参数表预检、生成、受控parameters.write任务及停止。表格、目标及项目版本绑定于本机确认；本机选定路径另存和项目凭据保持本地，外部来源的文件输出与写参范围不扩大。DUT 和写参共用当前项目的本机登录草稿，凭据走原写参显式保存，仅本机显示。串口路径沿原回调，使用和升级共用的只读观察逻辑。Telnet仍使用任务文本日志。
Qt ONU 通过onu.editor.*本机入口接入双型号配置、查询、注册、当前PON精确删除及独立保存OLT启动配置。C300单台注册的可选离线清理先只读查询，临时确认绑定本次候选接口和SN，执行由原服务复核仍离线及身份后仅重试一次。保存按原双型号策略，权限绑定原操作和整台OLT，任务结果可独立核对。
AI及其余未迁移控制面仍待实施；本表connected表示既有共享后端能力，不表示所有Qt页面已完成。独立Qt原生验证使用scripts/verify_qt_migration.py，原Tk完整基线不能代替该验证。
