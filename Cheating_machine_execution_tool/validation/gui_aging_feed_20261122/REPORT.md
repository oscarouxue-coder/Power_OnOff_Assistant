# 全业务老化现场采集接入口

负责人确认已有测试架和采集接口，本轮先实现工具端逻辑，设备及平台协议留到现场逐项适配。Qt 向导保存每项业务的采集来源。确认启动后，工作区按真实 Job 创建公开的批次映射；工具只读取该批次所选 DUT 和业务的观测。操作步骤、字段及 IPTV 示例见[操作员说明](../../line_check_assistant_README.md#接入现场采集结果)。

| 场景 | 已实现和验证的行为 |
|---|---|
| 新旧项目 | 向导中先勾选业务，再在对应来源下拉框选择「现场采集」。既有项目保留原人工检查与绑定网卡 Ping，切换类型、恢复草稿、保存和重开均保留相应选择。 |
| 采集端交接 | `history/aging-input/<job_id>.plan.json` 给出项目、批次、DUT、硬件标识及选中业务。相同计划可重试，已有冲突文件保留。工作台给出可复制的 `.jsonl` 输入路径。 |
| 核对现场结果 | 按源时间接受新鲜观测，记录事件 ID、源时间、接收时间和结果。每个 DUT/业务单独计算，重复、错批次和越过时间窗的上报无法产生有效检查。断流期间有效观测时长停止累计。 |
| 故障与恢复 | 半行等下一次追加，单行过长或损坏后可继续读取正常记录。轮换及截断开启新读取区段，持久去重保留。文件缺失、清单冲突都允许其他来源继续运行。 |
| 历史与交接 | 新旧项目均能查看和导出历史。现场自动采样与人工日检、期末证据分别记录。当前工具可消费外部采集端提供的对应事实；DUT 自身开机周期、连续通话与视频播放质量仍需现场采集端的证据。 |

## 软件验证

正式工作区执行以下命令，30 项通过。专项覆盖真实临时项目、正式确认和停止、采集文件、历史 SQLite 及 CSV。另在独立 Windows 私有桌面核对向导，两项用例在 100%、125%、150% 各通过，两项合计每档 13 个受管窗口，零违规。[专项输出](focused.txt)

```powershell
python scripts/run_tests.py test_aging_observation_source test_service_aging_feed test_service_aging test_project_profile_store test_qt_execution_adapter.QtExecutionAdapterTests.test_field_collector_uses_the_confirmed_job_manifest_and_deduplicates_reports test_qt_execution_adapter.QtExecutionAdapterTests.test_continuous_monitor_confirm_stop_and_history_use_the_selected_project_job -v
```

实现主要涉及[采集契约与文件读取](../../src/services/aging_observation_source.py)、[轮询与错误恢复](../../src/services/service_aging_feed.py)、[运行任务](../../src/services/service_aging.py)、[历史与导出](../../src/services/service_aging_history.py)、[项目档案](../../src/models/project_profile.py)、[向导](../../src/ui/qt/project_wizard.py)、[工作台状态](../../src/ui/qt/test_type_panel.py)和[批次历史界面](../../src/ui/qt/service_aging_history_dialog.py)。能力覆盖、编译清单和原生必跑用例同步更新。[验证输入指纹](source-inputs.json)

## 本次候选包与验证

最终输入包含 646 份源码、测试、构建入口和说明。标准 Qt 构建的完整基线通过 3,334 项测试和 270 项指定回归，编译 411 个文件，覆盖 401 个源码文件。Windows 原生在 100%、125%、150% 各通过 113 项，每档 1,936 个受管窗口，违规数均为零。[完整基线及构建输出](build.txt) · [三档原生结果](native/results.json)

产品版本为 1.3.0，本地候选目录为 `qt-v13x-feed-20261122`。完整便携 ZIP 为 55,573,869 字节，SHA256 为 `4e68afe5e1a620902e7d8178f40e8c427e26f5db1e43a1306bd71e1c86ccdf9a`。从成品 PYZ 对照了 362 个项目模块与源码，核对 Qt 启动入口、包内操作说明、ZIP CRC 和校验文件。本机只做静态验包。[便携 ZIP](../../dist/qt-v13x-feed-20261122/DUTPilot_portable.zip) · [SHA256](../../dist/qt-v13x-feed-20261122/DUTPilot_portable.zip.sha256.txt) · [静态比对](package-proof.json)

## 现场待办

按具体机架确定 DUT 映射、采集端时间基准和业务成功条件，再核对真实正常、异常、断流与恢复。语音连续 48 小时、LAN Ping 48 小时及丢包率、常温业务老化 7 天，以及开关机每台 500 轮均需按实际运行留证。目标 Windows 启动、24/72 小时无人值守资源曲线按[原阶段报告](../gui_upgrade_execution_20261122/REPORT.md)追踪。
