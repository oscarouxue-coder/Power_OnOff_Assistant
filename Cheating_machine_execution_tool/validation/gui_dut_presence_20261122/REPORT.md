# 全业务老化中的 DUT 状态与重启证据

在项目向导勾选「DUT 在线与启动状态」后，现场适配器可向该批次的 JSONL 上报各台 DUT 的观测。工作台以批次 Job 和冻结的 DUT 身份关联数据。上一次出包的记录见[采集接口阶段报告](../gui_aging_feed_20261122/REPORT.md)。

| 输入或事件 | 工作台和历史中的结果 |
|---|---|
| 在线观测 | 显示在线，更新该 DUT 最后一次在线心跳。可以携带启动标识和采样时的设备运行秒数 |
| 明确离线或状态无法判断 | 分别显示离线或未知。保留最近的在线心跳与原始观测时间 |
| 未订阅、断流、观测过期或批次结束 | 显示未接入或未知。重开旧批次只读历史 |
| 同批次同一 DUT 两次有效启动标识不同 | 记录一次已观测的启动变化及首次看到新标识的时间。变化后要有新的运行秒数观测才显示该次启动的运行时长 |
| 一次 Ping 超时或一项业务异常 | 计入对应业务。业务异常与设备离线同时发生时，总览按实际受影响的 DUT 去重 |

向导入口和档案变更在 `src/models/project_profile.py`、`src/ui/qt/project_wizard.py`。采集协议、落库与批次日志分别在 `src/services/aging_observation_source.py`、`service_aging_presence.py`、`service_aging_history.py`、`service_aging_feed.py`。工作台投影和界面在 `src/services/qt_workspace_adapter.py`、`src/ui/qt/test_type_panel.py`、`src/ui/qt/service_aging_history_dialog.py`。老化 CSV 保留源观测时间、接收时间、启动标识、运行秒数和该条观测的启动变化。

37 项[服务及档案回归](services.txt)通过。两项[独立 Windows 窗口用例](ui-smoke.txt)验证逐 DUT 详情、记录钻取和项目切换。本次扩展并登记了 `test_aging_observation_source`、`test_service_aging_feed`、`test_project_profile_store`、`test_qt_workspace_adapter`、`qt_project_wizard_probe`、`qt_typed_status_probe` 的相关用例，更新完整基线和原生迁移清单。

在主源码目录运行 `python scripts/verify_qt_migration.py --output validation/gui_dut_presence_20261122/native`。100%、125%、150% 三档各通过 114 项，各管理 1,937 个窗口，零隔离违规。[三档结果](native/results.json)

现场仍需在同批次对照实际设备心跳、断电离线、采集端断流、重启和设备运行秒数。执行器批次经过的时间与设备开机时长分别记录。现场签认及长期门槛见[验收基线](../../../ACCEPTANCE_BASELINE.md)。
