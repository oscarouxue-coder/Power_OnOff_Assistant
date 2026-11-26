"""Product business inventory, including all not-yet-connected modules. Never counts private helpers."""

# id | user operation | GUI callback | existing implementation | resources | risk | registered capability
# Variants are separate rows when the user can independently request them.
_ROWS = """
channels.refresh|刷新串口/网卡|_refresh_resources|serial_inventory/network_adapter|host|read|
channels.list|查询通道配置/状态|_collect_ai_targets|ChannelConfigStore|configuration|read|channels.list
channels.select|通道勾选/全选/清除|_set_all_channels_enabled|ChannelConfigStore|configuration|modify|
channels.configure|通道VLAN/COM/IP/电源绑定|_persist_config|ChannelConfigStore|configuration|modify|
network.rename|网卡重命名|_on_adapter_renamed|AdapterRenameService|adapter/configuration|dangerous|
network.line_check|环境线路检查|_start_all_checks|run_line_check|adapter/channel|modify|
power.on|自动上电|_launch_power_on|turn_on_selected_channels|power/channel|dangerous|
power.off|自动下电|_launch_power_on|turn_off_selected_channels|power/channel|dangerous|
pipeline.start|所选三项全流程|_start_all_checks|PipelineOrchestrator|device/wifi/power|dangerous|
aging.start|启动老化/开关机测试|_start_all_checks|run_legacy_power_test|device/wifi/power|dangerous|
aging.stop|停止测试|_stop_power_test|PipelineOrchestrator.request_stop|job|dangerous|
aging.resume|失败轮次续跑|_show_power_test_channel_detail|PowerTestResumeSession.submit|device/wifi/power|dangerous|
aging.status|通道进度和重试失败历史|_show_power_test_channel_detail|PowerTestResumeSession|job|read|
logs.power|本次开关机结果日志|_open_selected_power_test_log|latest_power_test_result_log|file|read|
logs.wifi|本次WiFi日志/连接历史|_open_selected_power_test_wifi_log|current_wifi_log|file|read|
config.telnet|Telnet配置/登录后命令|_build_test_item_telnet_tab|TestItemConfigStore|configuration|modify|
config.commands|测试项/预期分段/重试配置|_build_test_item_order_tab|TestItemConfigStore|configuration|modify|
config.defaults|恢复默认测试项|_build_test_item_order_tab|TestItemConfigStore|configuration|modify|
pretest.start|执行预备测试|_capture_pretest_request|run_pretest|device|dangerous|
pretest.stop|停止预备测试|_capture_pretest_request|PretestControls|job|dangerous|
config.runtime|开关机运行参数|_build_test_item_ui_defaults_tab|LegacyUiDefaultsStore|configuration|modify|
config.wifi|WiFi测试配置|_build_test_item_wifi_tab|TestItemConfigStore|configuration|modify|
config.project|项目信息和版本基准|_build_test_item_project_info_tab|TestItemConfigStore|configuration|modify|
device.version|查询当前样机版本|_start_project_info_query|query_device_project_info|adapter/device|modify|
config.reload_save|配置保存/重新加载|_open_test_item_config|TestItemConfigStore|configuration|modify|
notifications.config|消息推送配置|_open_test_item_config|MessagePushConfigService|configuration|modify|
notifications.test|发送测试消息|_open_test_item_config|send_test_message|external|dangerous|
firmware.full_command|全包Tftp指令升级|_start_full_package_upgrade|run_parallel_tftp_command_upgrades|device/serial/adapter/power/tftp|dangerous|firmware.upgrade
firmware.full_put|全包Tftp Put升级|_start_full_package_upgrade|run_parallel_tftp_put_upgrades|device/serial/adapter/power/tftp|dangerous|firmware.upgrade
firmware.full_web|全包Web网关升级|_start_full_package_upgrade|run_parallel_web_gateway_upgrades|device/serial/adapter/power/browser|dangerous|firmware.upgrade
firmware.page|页面UBUS升级|_start_page_upgrade|run_page_upgrade_batch|device/adapter|dangerous|firmware.upgrade
firmware.stop|安全停止升级|_stop_sample_upgrade|UpgradeStopControl|job|dangerous|cancel_job
firmware.settings|升级选项保存|_save_sample_upgrade_settings|SampleUpgradeSettingsStore|configuration|modify|
parameters.generate|生成参数表|_open_parameter_generator|generate_parameter_records|file|modify|
parameters.preflight|导入/预检参数表|_refresh_parameter_preflight|preflight_parameter_targets|file|read|
parameters.write|批量写样机参数|_start_sample_parameter_write|run_parallel_sample_parameter_writes|device/serial/adapter|dangerous|
parameters.stop|停止写参|_cancel_sample_parameter_write|cancel_event|job|dangerous|
onu.connection|OLT登录测试|_on_onu_telnet_test_clicked|OnuRegistrationService.test_connection|olt|dangerous|
onu.unregistered|查询未注册ONU|_on_onu_query_unregistered_clicked|query_unregistered|olt/pon|dangerous|
onu.templates|查询业务模板|_on_onu_template_query_clicked|query_templates|olt|dangerous|
onu.settings|连接/PON/ID/业务配置|_save_onu_registration_config|OnuRegistrationStore|configuration|modify|
onu.preview|生成只读命令预览|_on_onu_preview_clicked|build_preview|configuration|read|
onu.register|单台/批量ONU注册|_on_onu_register_selected_clicked|OnuRegistrationService.register|olt/pon/onu|dangerous|
onu.cleanup_query|查询C300离线清理候选|_on_c300_cleanup_candidates_clicked|query_c300_cleanup_candidates|olt/pon|dangerous|
onu.cleanup_retry|明确单台清理后重试|_on_onu_register_selected_clicked|OnuRegistrationService.register|olt/pon/onu|dangerous|
onu.registered|查询已注册ONU|_on_onu_manage_query_clicked|query_registered_candidates|olt/pon|dangerous|
onu.delete|删除选中ONU|_on_onu_manage_delete_clicked|OnuBatchDeleteService.delete|olt/pon/onu|dangerous|
onu.save|保存OLT配置write|_onu_save_olt_configuration_worker|save_configuration|olt|dangerous|
onu.stop|停止ONU操作|_on_onu_stop_clicked|cancel_event|job|dangerous|
dut.telnet_query|查询Telnet状态|_query_dut_telnet_status|run_dut_status_query_batch|adapter/device|modify|
dut.telnet_enable|开启Telnet|_start_dut_telnet_enable|run_dut_telnet_enable_batch|adapter/device|dangerous|
dut.wan_query|查询WAN|_query_dut_wan_connections|run_dut_wan_query_batch|adapter/device|modify|
dut.wan_add|新增WAN|_start_dut_wan_config|run_dut_advanced_config_batch|adapter/device|dangerous|
dut.wan_modify|修改WAN|_start_dut_wan_config|run_dut_advanced_config_batch|adapter/device|dangerous|
dut.wan_delete|删除WAN|_start_dut_wan_config|run_dut_advanced_config_batch|adapter/device|dangerous|
dut.wifi2_query|查询2.4G WiFi|_query_dut_wifi_2g_status|run_dut_status_query_batch|adapter/device|modify|
dut.wifi2_config|配置2.4G WiFi|_start_dut_wifi_2g_config|run_dut_advanced_config_batch|adapter/device|dangerous|
dut.wifi5_query|查询5G WiFi|_query_dut_wifi_5g_status|run_dut_status_query_batch|adapter/device|modify|
dut.wifi5_config|配置5G WiFi|_start_dut_wifi_5g_config|run_dut_advanced_config_batch|adapter/device|dangerous|
dut.voice_query|查询语音|_query_dut_voice_status|run_dut_status_query_batch|adapter/device|modify|
dut.voice_config|配置语音|_start_dut_voice_config|run_dut_advanced_config_batch|adapter/device|dangerous|
dut.tr069_query|查询TR069|_query_dut_tr069_status|run_dut_status_query_batch|adapter/device|modify|
dut.tr069_config|配置TR069|_start_dut_tr069_config|run_dut_advanced_config_batch|adapter/device|dangerous|
dut.stop|停止DUT配置/查询|_stop_dut_telnet_enable|stop_event|job|dangerous|
serial.open|打开指定/全部串口日志|_open_serial_log_module|SerialSessionManager.acquire_monitor|serial|modify|
serial.close|停止监控/关闭标签|_open_serial_log_module|SerialSessionManager.release|serial|modify|
serial.send|串口文本/回车发送|_open_serial_log_module|SerialTerminal.send|serial/device|dangerous|
serial.read|被动串口日志|_open_serial_log_module|read_serial_log|serial|read|read_serial_log
serial.status|实时串口状态|_open_serial_log_module|read_serial_status|serial|read|read_serial_status
serial.directory|串口日志目录|_on_serial_log_directory_changed|SerialTerminal|configuration|modify|
ai.profiles|模型配置增改复制删除选择|_open_ai_assistant|DiagnosticStore|configuration|modify|
ai.source_ip|模型出口IP枚举与设置|_open_ai_assistant|list_source_ips / DiagnosticStore|configuration|modify|
ai.models_test|模型列表/连接测试|_open_ai_assistant|DiagnosticClient|external|modify|
ai.conversation|对话/连续诊断/停止/进展|_open_ai_assistant|AiConversationService|conversation|modify|existing_interaction
ai.evidence|文本导入/证据检索|_open_ai_assistant|AiEvidenceContext|file|read|read_test_evidence
ai.sessions|会话查询/重命名/删除清空|_open_ai_assistant|DiagnosticStore|data|modify|
ai.sessions_create|创建空白新会话|_open_ai_assistant|AiConversationService.create_blank_session|conversation|modify|ai.sessions.create
ai.reports|报告查询/重命名/删除清空|_open_ai_assistant|DiagnosticStore|data|modify|
ai.continue_report|报告接手排查|_open_ai_assistant|create_session_from_report|conversation|modify|
ai.cases|案例创建/修订/启停/删除|_open_ai_assistant|SharedCaseStore|data|modify|
ai.case_confirmation|人工确认根因及复测|_open_ai_assistant|confirm_case|human_control|manual|local_confirmation
ai.monitor|监控设置/启停/状态|_open_ai_assistant|AiMonitorService|monitor|modify|
ai.permissions|权限切换/批准/拒绝|_open_ai_assistant|AiPermissionService|human_control|manual|local_confirmation
remote.dingtalk|钉钉配置/启停/绑定/取消|_configure_dingtalk_remote|DingTalkRemoteService|external/configuration|modify|
remote.feishu|飞书配置/启停/绑定/取消/试发|_configure_feishu_remote|FeishuRemoteService|external/configuration|modify|
remote.feishu_sdk_repair|安装飞书SDK并重启源码|_install_feishu_sdk|FeishuDependencyRepair|python-environment/process|manual|local_confirmation
remote.binding_confirm|群身份绑定确认|_build_ai_remote_management|remote.confirm_binding|human_control|manual|local_confirmation
remote.instances|多实例接入状态|_open_ai_assistant|RemoteInstanceManagement.status|configuration|read|remote.instances.status
remote.instance_configuration|实例配对/启动模式/本地范围|_open_ai_assistant|RemoteInstanceManagement|human_control|manual|local_confirmation
remote.gateway_configuration|网关配置/启停/配对码/撤销|_open_ai_assistant|RemoteGatewayHost|human_control|manual|local_confirmation
updates.check|检查更新|_build_ui|AppUpdateService.check_for_update|external|read|
updates.download|下载更新/取消|_build_ui|AppUpdateService.download_update|external/file|modify|
"""


def business_catalog():
    connected = {"power.on": "power.on", "power.off": "power.off", "network.line_check": "network.line_check",
        "pipeline.start": "pipeline.start", "aging.start": "aging.start", "aging.resume": "aging.resume",
        "aging.stop": "cancel_job", "aging.status": "get_job_status", "pretest.start": "pretest.start",
        "pretest.stop": "cancel_job", "device.version": "device.version", "dut.telnet_query": "dut.telnet.query",
        "dut.telnet_enable": "dut.telnet.enable", "dut.wan_query": "dut.wan.query", "dut.wan_add": "dut.wan.configure",
        "dut.wan_modify": "dut.wan.configure", "dut.wan_delete": "dut.wan.configure", "dut.wifi2_query": "dut.wifi_2g.query",
        "dut.wifi2_config": "dut.wifi_2g.configure", "dut.wifi5_query": "dut.wifi_5g.query", "dut.wifi5_config": "dut.wifi_5g.configure",
        "dut.voice_query": "dut.voice.query", "dut.voice_config": "dut.voice.configure", "dut.tr069_query": "dut.tr069.query",
        "dut.tr069_config": "dut.tr069.configure", "dut.stop": "cancel_job",
        "parameters.preflight": "parameters.preflight", "parameters.generate": "parameters.generate",
        "parameters.write": "parameters.write", "parameters.stop": "cancel_job",
        "onu.connection": "onu.connection", "onu.unregistered": "onu.unregistered", "onu.templates": "onu.templates",
        "onu.preview": "onu.preview", "onu.register": "onu.register", "onu.cleanup_query": "onu.cleanup_query",
        "onu.cleanup_retry": "onu.register", "onu.registered": "onu.registered", "onu.delete": "onu.delete", "onu.save": "onu.save",
        "onu.stop": "cancel_job", "serial.open": "serial.monitor.open", "serial.close": "serial.monitor.close",
        "serial.status": "serial.status", "logs.power": "logs.power", "logs.wifi": "logs.wifi",
        "config.telnet": "configuration.telnet.patch", "config.commands": "configuration.order.patch",
        "config.runtime": "configuration.runtime.patch", "config.wifi": "configuration.connect_wifi.patch",
        "config.project": "configuration.project_info.patch", "config.reload_save": "configuration.read",
        "updates.check": "updates.check", "updates.download": "updates.download",
        "ai.profiles": "ai.profiles.list", "ai.source_ip": "ai.source_ip.list / ai.profiles.list", "ai.models_test": "ai.models.query / ai.models.test",
        "ai.sessions": "ai.sessions.list/read/rename/delete", "ai.reports": "ai.reports.list/read/rename/delete",
        "ai.cases": "ai.cases.query / ai.cases.set_active / ai.cases.delete", "ai.evidence": "ai.evidence.import / read_test_evidence",
        'ai.continue_report': 'ai.reports.continue', 'notifications.config': 'notifications.read / notifications.patch',
        'notifications.test': 'notifications.test', 'config.defaults': 'configuration.defaults.prepare', 'channels.refresh': 'resources.refresh',
        'channels.select': 'channels.select', 'channels.configure': 'channels.configure', 'network.rename': 'network.rename',
        'firmware.settings': 'settings.read / firmware.settings.patch', 'onu.settings': 'settings.read / onu.settings.patch'}
    result = []
    pending_reasons = {
        'channels.refresh': '枚举只读原语已开放；主界面候选项刷新/保留选择的数据回写适配未完成',
        'channels.select': '主界面选择会实时保存并影响会话范围，需原子配置/身份刷新适配，不能从模型自行扩大目标授权',
        'channels.configure': '需同步行草稿、派生IP、选中通道持久化及授权失效，尚未提取可回退事务边界',
        'network.rename': '现有身份回读服务可复用；尚缺配置引用/GUI草稿的原子同步及不确定结果恢复适配',
        'config.defaults': 'GUI当前只恢复到未保存草稿；不能把读模板直接保存磁盘冒充等价恢复',
        'notifications.config': '需保留编辑器草稿并共用平台识别/密钥保存和运行通知源，尚未完成适配',
        'notifications.test': '需绑定负责人确认的外发目的地；本轮未开放发送接口，也未实际外发',
        'firmware.settings': '运行时升级参数已开放；永久选项需与两个窗口的自动保存草稿同步，尚未适配',
        'onu.settings': '执行使用当前GUI配置；永久PON/连接配置需同步双型号草稿、预览失效及新增OLT范围审阅',
        'serial.send': '任意文本发送涉及Shell/Boot控制；必须复用A2及已审阅执行模板，不能增加裸串口写入后门',
        'serial.directory': '当前工作区监控输出可用；主串口窗口保存目录及正在打开日志的归属适配待完成',
        'ai.continue_report': '原报告接手服务保留；尚需可信来源/目标及历史材料身份的受控适配',
        'ai.monitor': 'Tk 与 Qt 复用本地监控授权和逐操作审批；Qt 通道诊断与批量范围由操作员确认，Agent 不得自行签发或扩大范围',
        'remote.dingtalk': '远程业务调用已校验真实来源；接入配置/启停及AI卡片模板仍属本地授权控制面，尚需专用适配；流式为已有会话的显示投影',
        'remote.feishu': '远程业务调用已校验真实来源；接入配置/启停及卡片权限仍属本地授权控制面，尚需专用适配；流式为已有会话的显示投影',
    }
    for row in _ROWS.strip().splitlines():
        identifier, name, gui, service, resources, risk, capability = row.split("|")
        capability = connected.get(identifier, capability)
        manual = capability == "local_confirmation"
        old_jobs = ("firmware.stop", "aging.stop", "aging.status", "pretest.stop", "dut.stop", "parameters.stop", "onu.stop")
        partial = identifier in old_jobs + ("ai.evidence", "ai.conversation", "ai.profiles", "ai.source_ip", "ai.cases", "parameters.generate", "serial.close", "config.reload_save", "updates.download")
        result.append(dict(feature_id=identifier, name=name, gui_file="line_check_assistant/app.py", gui_entry=gui,
            service=service, resources=resources.split("/"), risk=risk, capability_id=capability,
            status="manual_control" if manual else "partial" if partial else "connected" if capability else "pending",
            reason="仅本机缺包弹窗由操作员选择安装；修改运行环境并重启，AI不可触发或代确认" if identifier == 'remote.feishu_sdk_repair' else
                   "接入配置、配对、范围、启停及撤销仅本机操作员确认；AI不能生成配对码或自授权" if identifier in ('remote.instance_configuration', 'remote.gateway_configuration') else
                   "必须由真实操作员确认，AI可准备材料但不能自我批准" if manual else
                   "仅受控接口发起的任务可按job_id查询/取消；旧GUI独立批次未接管" if identifier in old_jobs else
                   "关闭自己取得的被动监控，不关闭其它GUI标签/所有权" if identifier == "serial.close" else
                   "支持按域读取/合并保存及默认命令草稿；GUI编辑器草稿和整套重载尚未接管" if identifier == "config.reload_save" else
                   "原更新服务校验及取消共用；AI仅下载到受控工作区，任意目标目录授权待接入" if identifier == "updates.download" else
                   "生成规则共用，当前AI仅保存受控工作区；任意输出目录授权尚待接入" if identifier == "parameters.generate" else
                   "仅查询模型元数据；模型/密钥配置写入与选择仍须本地控制面，尚未开放自动化适配" if identifier == "ai.profiles" else
                   "共用本机IPv4枚举及已保存配置；设置/保存仍为本地模型配置控制面，AI写入尚未开放" if identifier == "ai.source_ip" else
                   "可查询/按版本启停/删除；新增和内容修订中的根因/复测确认保留真实人工控制面" if identifier == "ai.cases" else
                   "明确版本请求共用受控多通道Job；逐台失败继续、先真实结果后一次AI说明；不重放，现场验收待确认" if identifier == "device.version" else
                   "已有受控接口，真实Windows/模型/DUT验收另列" if capability else pending_reasons[identifier]))
        group = identifier.split('.')[0]
        tests = ('test_capability_settings.py',) if identifier in ('firmware.settings', 'onu.settings') else (
            ('test_capabilities.py', 'test_capability_upgrade_equivalence.py') if group == 'firmware' else (
            ('test_capability_channels.py',) if identifier in ('channels.select', 'channels.configure', 'network.rename') else
            ('test_capability_onu.py',) if group == 'onu' else ('test_capability_ai_data.py',) if group == 'ai' else
            ('test_capability_application.py',) if group in ('config', 'logs', 'serial', 'updates', 'notifications') else ('test_capability_devices.py',)))
        result[-1]['tests'] = list(tests) if capability and not manual else []
        if identifier == 'remote.feishu_sdk_repair':
            result[-1].update(gui_file='src/ui/qt/feishu_repair_dialog.py', gui_entry='open',
                              tests=['test_feishu_dependency_repair.py', 'test_qt_workspace_adapter.py',
                                     'qt_workbench_probe.py'])
        if identifier == 'remote.instances':
            result[-1]['tests'] = ['test_remote_instance_management.py']
        if identifier == "device.version":
            result[-1]['tests'].extend(('test_ai_version_query.py', 'test_ai_multichannel_dispatch.py'))
    project_actions = (
        ('projects.list', '查询已打开项目', '_update_menu', 'workspace.projects.list'),
        ('projects.create', '新建项目', 'new_project', ''),
        ('projects.open', '打开或切换项目', 'open_project', ''),
        ('projects.save', '保存项目及页面草稿', 'save_project', ''),
        ('projects.duplicate', '另存为独立项目', 'duplicate_project', ''),
        ('projects.rename', '重命名项目', 'rename_project', ''),
        ('projects.import', '备份并导入旧配置及历史', 'import_project', ''),
        ('projects.close', '安全关闭项目', 'close_project', ''),
        ('projects.forget', '从最近列表移除', 'forget_project', ''),
        ('projects.remote_scope', '本机确认远程项目范围', 'remote_project_range', ''),
        ('projects.resolve_unknown', '本机核实GUI未知任务', 'resolve_unknown', ''),
        ('projects.imported_connection', '选择导入的接入配置', 'imported_connection', ''),
    )
    for identifier, name, entry, capability in project_actions:
        result.append(dict(feature_id=identifier, name=name, gui_file='src/ui/project_workspace.py', gui_entry=entry,
            service='WorkspaceService / ProjectStore', resources=['project', 'configuration'], risk='read' if capability else 'manual',
            capability_id=capability or 'local_confirmation', status='connected' if capability else 'manual_control',
            reason='仅local/gui查询项目身份和状态；不切换目标、不扩大权限' if capability else
                   '涉及本地目录所有权、配置版本、运行生命周期或远程授权，限本机操作员；AI不可模拟GUI或自行确认',
            tests=['test_project_management.py', 'test_project_workspace.py', 'test_workspace_platforms.py',
                   'test_project_completion.py', 'test_multi_project_business_validation.py']))
    local_workflows = (
        ('remote.platform_direct', '本机启停钉钉和飞书直连排障', 'platform_configuration_dialog.py', 'change_direct',
         'QtDirectPlatforms / WorkspacePlatformPool / 原平台服务', 'local_confirmation',
         '启用要求本机授权项目，进入已绑定群或飞书企业单聊，实时核对原平台身份和权限。',
         ['test_qt_workspace_adapter.py']),
        ('remote.feishu_automatic_notifications', '启停飞书挂测通知', 'platform_configuration_dialog.py', 'change_notifications',
         'QtFeishuNotifications / FeishuNotificationService', 'local_confirmation',
         '使用已绑定群和保存的项目名称，停用会阻止后续自动通知。',
         ['test_qt_workspace_adapter.py', 'qt_workbench_probe.py']),
        ('jobs.local_safe_stop', '本机请求选中任务安全停止', 'log_history_dialog.py', '_request_stop',
         'QtJobControl / CapabilityJobs', 'local_confirmation',
         '仅接受本进程当前项目内的活跃任务，选定任务独立收尾。',
         ['test_qt_workspace_adapter.py']),
        ('extensions.review', '本机审阅登记或启停受控扩展', 'controlled_extensions_dialog.py', 'import_template',
         'QtControlledExtensions / CapabilityExtensions', 'local_confirmation',
         '绑定项目与审阅哈希，继承目标操作原授权与资源范围。',
         ['test_qt_workspace_adapter.py', 'qt_workbench_probe.py']),
        ('remote.platform_credentials', '本机编辑钉钉或飞书应用配置', 'platform_configuration_dialog.py', 'save',
         'QtPlatformConfiguration / RemoteConfigStore / FeishuConfigStore', 'local_confirmation',
         '只保存平台应用配置，凭据交由原加密存储，保存后保持停用。',
         ['test_qt_workspace_adapter.py', 'qt_workbench_probe.py']),
        ('remote.platform_binding', '本机开始、确认或取消机器人群绑定', 'platform_configuration_dialog.py', 'change_binding',
         'QtPlatformConfiguration / WorkspacePlatformPool / 原平台服务', 'local_confirmation',
         '只启用临时群绑定连接，确认当前项目及群身份，结束后回收连接。',
         ['test_qt_workspace_adapter.py', 'qt_workbench_probe.py']),
        ('remote.feishu_trial', '向绑定群发送一条飞书测试消息', 'platform_configuration_dialog.py', 'start_trial',
         'QtPlatformConfiguration / FeishuNotificationService', 'local_confirmation',
         '先确认已保存项目和群 ID，再调用原固定消息队列。平台受理和群收到分别核对。',
         ['test_qt_workspace_adapter.py']),
        ('projects.model_presets', '保存和应用产品型号模板', 'project_wizard_controller.py', '_save_preset',
         'QtProjectWizardService / ProjectModelPresets', 'local_confirmation', '操作员选择已保存版本并确认跨项目共享的型号方案',
         ['test_qt_workspace_adapter.py', 'qt_project_wizard_probe.py']),
        ('projects.test_profile', '创建或恢复测试项目档案', 'project_wizard_controller.py', '_save',
         'ProjectStore / QtProjectWizardService', 'local_confirmation', '仅本机选择目录、测试类型和测试计划',
         ['test_project_profile_store.py', 'qt_project_wizard_probe.py']),
        ('service_aging.start', '开始持续供电业务老化', 'workspace_controller.py', 'start_test',
         'QtServiceAging / ServiceAging', 'service_aging.start', '仅 GUI，可追溯到本次确认的项目、DUT 和资源',
         ['test_qt_execution_adapter.py', 'test_service_aging.py']),
        ('service_aging.record', '记录现场观察、日检或期末检查', 'test_type_panel.py', '_record',
         'QtServiceAging / ServiceAging', 'service_aging.record', '仅 GUI，本机操作人提供实际观测和结果',
         ['test_service_aging.py']),
        ('service_aging.history', '查看及导出指定批次业务证据', 'service_aging_history_dialog.py', '_export',
         'ServiceAgingHistory', 'local_confirmation', '仅本机选择项目、批次和导出文件',
         ['test_service_aging.py', 'qt_project_wizard_probe.py']),
        ('service_aging.channel_evidence', '查看所选 DUT 或普通聊天明确 CH 的掉线证据', 'ai_chat_controller.py', 'open_evidence',
         'read_channel_evidence / ServiceAgingHistory', 'service_aging.channel_evidence',
         '仅本机 GUI 在冻结的项目、批次和通道内读取已有观测。普通聊天通过 _send_chat_evidence 核对明确 CH，带请求编号的结果仅当前窗口显示；停止本轮仅取消该本地读请求',
         ['test_qt_channel_evidence.py', 'qt_channel_evidence_probe.py']),
        ('history.material_summary', '汇总选定批次通道的本地留存结果文件', 'log_history_dialog.py', '_request_summary',
         'summarize_history_materials / summarize_history_materials_batch / qt_power_logs', 'history.material_summary',
         '仅本机 GUI 从同一已核对历史批次选择一至十六个原通道，逐通道复用既有有界只读能力；原文正文不展开，不提供模型或远端能力',
         ['test_qt_log_history.py', 'qt_workbench_probe.py']),
        ('history.material_report_save', '保存当前已生成的本地历史报告', 'log_history_dialog.py', '_request_save_report',
         'save_material_report / qt_power_logs', 'history.material_report_save',
         '仅本机 GUI 明确保存已核对批次的生成回执，不接受任意正文、路径或重跑，不提供模型或远端能力',
         ['test_qt_log_history.py', 'qt_workbench_probe.py']),
        ('history.material_reports', '查看选定历史批次已保存报告', 'log_history_dialog.py', '_request_saved_reports',
         'read_material_reports / qt_power_logs', 'history.material_reports',
         '仅本机 GUI 在所选项目任务及原运行范围中查看保存的历史报告，不读取原资料或执行任务',
         ['test_qt_log_history.py', 'qt_workbench_probe.py']),
    )
    for identifier, name, filename, entry, service, capability, reason, tests in local_workflows:
        result.append(dict(feature_id=identifier, name=name, gui_file='src/ui/qt/' + filename, gui_entry=entry,
                           service=service, resources=(['project', 'configuration'] if identifier.startswith('remote.')
                                                       else ['project', 'run']), risk='manual', capability_id=capability,
                           status='manual_control', reason=reason, tests=tests))
    return result
