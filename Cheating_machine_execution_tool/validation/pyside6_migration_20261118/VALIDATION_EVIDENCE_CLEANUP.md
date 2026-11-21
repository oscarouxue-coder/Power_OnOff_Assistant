# 开发验证证据清理

2026-11-21。按负责人确认的保留周期，开发批次的自动验证结论已写入阶段报告后，可清理截图、日志和机器结果清单。失败证据在对应范围复验通过后清理。现场验收继续按迁移进度表记录。

## 本次结果

- 已移入 Windows 回收站 2,601 份文件，共 105.4 MiB，含 1,815 张截图、407 份文本输出和 379 份 JSON 输出。
- Qt 迁移目录 2,585 份，统一工作台目录 10 份，GUI 隔离目录 6 份。
- 将 51 份记录中指向已清理文件的 Markdown 链接改为文字。各阶段的测试结论、历史失败原因、复跑命令与人工验收事项见原报告。[迁移进度](MIGRATION_PROGRESS.md) · [统一工作台](../unified_workbench_20261118/PHASE1_REPORT.md) · [GUI 隔离检查](../gui_offscreen_20261118/REPORT.md)
- 保留备份凭据、源码清单、构建元数据、旧 Tk 对照资料和 Git 跟踪的验收清单。实际设备、目标电脑和长期挂测依现行验收流程登记。
- 本次复核已有通过记录及文件状态。最近一次完整源码基线的 3,211 项和三档原生 246 项仍以原报告为准。[最近验证](AI_CHAT_PRESENTATION_QT_REPORT.md)

## 已核对的 Qt 三档批次

以下 53 个批次各档结果均为通过，未缺指定用例。记录的隔离方式为 Windows 私有桌面，各档 Qt 隔离违规为零。每格依次为通过用例数和受管 Qt 窗口数，各历史批次包含重复用例。

| 批次 | 100% | 125% | 150% |
| --- | ---: | ---: | ---: |
| qt_archived_logs_final | 61 / 1148 | 61 / 1148 | 61 / 1148 |
| qt_channels_acceptance_serial | 24 / 30 | 24 / 30 | 24 / 30 |
| qt_channels_first | 24 / 30 | 24 / 30 | 24 / 30 |
| qt_configuration_acceptance | 20 / 23 | 20 / 23 | 20 / 23 |
| qt_configuration_recovery_final | 59 / 1080 | 59 / 1080 | 59 / 1080 |
| qt_configuration_review | 20 / 23 | 20 / 23 | 20 / 23 |
| qt_directory_source_native | 60 / 1085 | 60 / 1085 | 60 / 1085 |
| qt_dut_telnet_acceptance | 29 / 41 | 29 / 41 | 29 / 41 |
| qt_dut_telnet_final | 29 / 41 | 29 / 41 | 29 / 41 |
| qt_dut_telnet_layout_verified | 29 / 41 | 29 / 41 | 29 / 41 |
| qt_dut_telnet_verified | 29 / 41 | 29 / 41 | 29 / 41 |
| qt_firmware_final_verified | 37 / 966 | 37 / 966 | 37 / 966 |
| qt_firmware_observation_verified | 38 / 970 | 38 / 970 | 38 / 970 |
| qt_firmware_verified | 37 / 966 | 37 / 966 | 37 / 966 |
| qt_followup_verified | 36 / 963 | 36 / 963 | 36 / 963 |
| qt_host_inventory_accepted | 54 / 1009 | 54 / 1009 | 54 / 1009 |
| qt_host_inventory_verified | 54 / 1009 | 54 / 1009 | 54 / 1009 |
| qt_imported_connections_final | 60 / 1085 | 60 / 1085 | 60 / 1085 |
| qt_job_review_final | 64 / 1163 | 64 / 1163 | 64 / 1163 |
| qt_log_history_verified | 56 / 1066 | 56 / 1066 | 56 / 1066 |
| qt_log_scope_accepted | 55 / 1010 | 55 / 1010 | 55 / 1010 |
| qt_model_settings_final | 65 / 1168 | 65 / 1168 | 65 / 1168 |
| qt_onu_query_verified | 41 / 979 | 41 / 979 | 41 / 979 |
| qt_parameter_observation_final | 40 / 977 | 40 / 977 | 40 / 977 |
| qt_parameter_writer_final | 39 / 973 | 39 / 973 | 39 / 973 |
| qt_parameter_writer_verified | 39 / 973 | 39 / 973 | 39 / 973 |
| qt_phase2 | 12 / 10 | 12 / 10 | 12 / 10 |
| qt_phase3_acceptance | 15 / 13 | 15 / 13 | 15 / 13 |
| qt_phase3_final | 14 / 12 | 14 / 12 | 14 / 12 |
| qt_phase3_final_acceptance | 16 / 14 | 16 / 14 | 16 / 14 |
| qt_phase3_release_checks | 16 / 14 | 16 / 14 | 16 / 14 |
| qt_pretest_verified | 48 / 997 | 48 / 997 | 48 / 997 |
| qt_push_trial_verified | 50 / 1001 | 50 / 1001 | 50 / 1001 |
| qt_recent_projects_verified | 58 / 1075 | 58 / 1075 | 58 / 1075 |
| qt_resource_options_final | 53 / 1007 | 53 / 1007 | 53 / 1007 |
| qt_resource_options_verified | 53 / 1007 | 53 / 1007 | 53 / 1007 |
| qt_resume_queue_verified | 52 / 1005 | 52 / 1005 | 52 / 1005 |
| qt_resume_verified | 51 / 1003 | 51 / 1003 | 51 / 1003 |
| qt_serial_acceptance | 27 / 36 | 27 / 36 | 27 / 36 |
| qt_serial_final_acceptance | 27 / 36 | 27 / 36 | 27 / 36 |
| qt_serial_verified | 27 / 36 | 27 / 36 | 27 / 36 |
| qt_single_power_verified | 57 / 1072 | 57 / 1072 | 57 / 1072 |
| qt_system_health_final | 62 / 1151 | 62 / 1151 | 62 / 1151 |
| qt_system_health_release_check | 62 / 1151 | 62 / 1151 | 62 / 1151 |
| qt_unknown_task_verified | 63 / 1156 | 63 / 1156 | 63 / 1156 |
| qt_version_verified | 49 / 999 | 49 / 999 | 49 / 999 |
| qt_voice_tr069_verified | 35 / 962 | 35 / 962 | 35 / 962 |
| qt_wan_geometry | 31 / 185 | 31 / 185 | 31 / 185 |
| qt_wan_layout | 31 / 185 | 31 / 185 | 31 / 185 |
| qt_wan_review | 31 / 45 | 31 / 45 | 31 / 45 |
| qt_wan_verified | 31 / 185 | 31 / 185 | 31 / 185 |
| qt_wifi_final | 33 / 511 | 33 / 511 | 33 / 511 |
| qt_wifi_settled | 2 / 136 | 2 / 136 | 2 / 136 |

通道数据、确认和执行行为的详细验收按相应报告。已覆盖的早期问题包括模拟资源冲突、Windows 输入桌面预检失败、测试夹具问题，以及配置对话框关闭后的资源释放。历史问题的原因和改动记录仍在各阶段报告中。

## 复跑入口

从主源码目录运行 Qt 原生套件时，输出目录使用本次验证专用目录。历史 Tk 检查使用完整基线或阶段报告中的专项入口。

~~~powershell
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_recheck
~~~
