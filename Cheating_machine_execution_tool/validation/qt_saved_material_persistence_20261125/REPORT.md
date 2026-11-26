# P1：Qt 本地留存报告保存与恢复（2026-11-25）

## 差异审计及范围

开工只读检查：P0 `HistoryMaterialSummary`、`HistoryMaterialBatchSummary` 真实生成结果此前仅显示在批次结果文件窗口，关闭/改选即失去本次显示，没有该类报告存盘和按原任务恢复的路径。原 AI 会话/报告库（DiagnosticStore reports、QtAiReports）有会话和模型报告持久化，但与纯本地、已核对的历史留存文件报告不是同一类型；不复用模型会话、传输或已有报告记录，不改其权限和业务语义。

开工 61 个已跟踪未暂存改动与 [P0 收口快照](../qt_p0_closeout_audit_20261125/workspace-after.json) 全部 SHA-256 一致，目标 adapter、历史服务、模型、历史 UI、测试及相关工程文档哈希均已复核。没有并行写入冲突证据。使用现有项目历史目录、原 atomic_json 持久方式、原工作区历史读取队列和 GUI-only CapabilityRegistry；不新增架构框架、依赖、引擎、命令、网络、模型调用或设备操作能力。

## 实际入口及结果

1. 正式 Qt 主窗口选择明确项目，打开任务历史，选择原历史任务和批次结果文件。
2. 用既有单/多通道汇总入口生成实际报告。在范围未改变、未取消且有已核对结果时，右键「保存本次留存报告」。适配器仅接受当前项目最近一次实际生成回执的请求 ID 和完整选定 target，不接收 UI 编辑正文或用户传入路径；对保存时项目、任务、原运行 ID 和历史记录再次核对。非终态、无有效生成回执或过期请求拒绝。
3. 关闭结果窗、任务历史窗乃至项目后，可在重新打开原项目任务历史选择原任务，右键「查看已保存留存报告…」。真正读取本地保存记录，不重新执行汇总、不打开原日志文件。不需要原日志现在仍可读（但仍必须有可核对原任务/历史批次身份）。报告保留生成时历史状态、历史更新时间、生成/保存时间、原项目/任务/批次/通道、来源文件及页内记录定位和观察、缺失/无法读取/未知。不会把某条 Ping 或 WiFi 等级解释成当前在线/故障根因。

持久化只在项目 `history/material_reports/<scope digest>/<独立 report ID>.json` 固定范围内发生，用户不输入路径。以精确项目/任务/run 绑定记录，每批次最多 64 份、有界目录和文件大小、独立记录 ID、产生时间及摘要校验；不存在目录或报告时返回空、不制造记录，破损记录计为无法读取且不掩盖有效记录。同一回执重复保存拒绝，不自动删除/覆盖旧报告。校验摘要用于发现损坏，不是对拥有本地磁盘写权限者的密码学真实性保证。P0 原报告文段已经是受限投影，保存的只是生成快照（不保存自由原文/凭据、模型输入或任务执行指令）。

取消或失效的请求不在新范围显示。选择变化、关闭、切项目取消等待；保存中若原已提交的本地原范围写入在取消前完成，保留原范围真实已保存记录（不删除回滚），但迟到回执不切到新范围；保存前取消不写文件。主动保存成功可再次查看，保存失败可原地重试，不自动重跑数据读取。

实际合成样例由原服务生成、存盘并再次读取：[saved-example.json](saved-example.json)。验证包含三个通道、原文件缺失/失败、独立引用，原材料字节不变、恢复时源资料读取调用 0，原自由正文的合成标记未进入保存快照。[样例探针](report_example.py)。

## 实际验证

| 验证 | 最终结果 | 原始证据 |
|---|---|---|
| 原历史服务（含 2 项新增）+ 5 个直接相关无子进程迁移契约 | 26/26，4.623s | [定向服务输出](service-tests-scoped.txt) |
| Windows 非输入私有桌面 100% | 3/3，11.492s，29 个受管窗口，违规 0 | [日志](native-regression-1.txt) · [隔离](native-regression-1.json) |
| Windows 非输入私有桌面 125% | 3/3，10.801s，29 个受管窗口，违规 0 | [日志](native-regression-1.25.txt) · [隔离](native-regression-1.25.json) |
| Windows 非输入私有桌面 150% | 3/3，10.894s，29 个受管窗口，违规 0 | [日志](native-regression-1.5.txt) · [隔离](native-regression-1.5.json) |
| 局部静态 | 8 个 Python 文件原始字节编译、能力覆盖和差异格式检查通过 | 实际命令输出；既有换行提示非错误 |

两项新增服务测试实测：

- `test_saved_material_report_exact_scope_round_trip_without_source_reread`：真实合成多通道报告读取、缺失、独立读取失败、保存/读回、时间/状态/引用、原字节不变、重复 ID 不覆盖、跨项目拒绝、另一批次无记录、防除源材料重新读取。
- `test_saved_material_report_cancel_failure_and_corrupt_record_are_independent`：保存前取消、写失败未生成报告、有效记录和损坏记录独立、读取取消。原 P0 19 项历史测试保留。

新增正式原生 `test_qt_saved_material_report_reopens_exact_history_without_source_read`：通过实际项目/任务选择、结果文件右键汇总/保存，先模拟原子写入失败再成功重试；仅可保存已有报告，查看确认来源时间、引用、缺失及非实时说明；切另一历史批次得到空；关闭历史窗及项目、重新打开原项目后从原任务读回完全相同正文，禁止源重读；跨项目切换后返回实际先前恢复页的迟到 Fake 回执，核对 stop、原范围和旧窗口不显示；原合成文件不改、业务执行实例未创建。另两项原生为原 P0 单/多通道真实入口和迟到隔离，原断言未弱化。本轮未调整 P0C 挂测资源等待断言。

初轮原生新夹具误假设任务列表顺序，已改为显式选定准确任务；第二轮/第三轮迟到采样 fixture 错用未导入 Event，最终改作延迟交付已经实际恢复的原结构化页并核对原范围/取消信号。原两项 P0 原生同时通过，保留 [首次后续失败记录](native-retry-console-1.txt)、[第二次失败](native-retry2-console-1.txt)、[最终100%](native-retry3-console-1.txt)。最终三个档位均通过。服务初次 21 项历史模块通过；为扩大定向迁移契约核对曾执行 27 项，其中原与本功能无关的 `test_ui_package_no_longer_eagerly_imports_tk` 需要实际 Python 子进程，被严格保护拒绝（[保留失败输出](service-tests-final.txt)，退出 1）。不修改/绕过保护，最终明确只运行 5 个无实际子进程的相关契约，并未宣称全部契约模块通过。最终服务和各原生测试受保护的网络/串口/外部进程/外部打开调用均 0。没有完整基线、真实运行环境或 EXE 验收。过程 PNG 生成 0。

## 变更文件与工作区保护

- [qt_log_history.py](../../src/models/qt_log_history.py)：本地历史报告快照与查看页模型。
- [qt_power_logs.py](../../src/services/qt_power_logs.py)：受限本地快照保存、读回、大小/数量、作用域和损坏验证，GUI-only 独立服务登记。
- [qt_workspace_adapter.py](../../src/services/qt_workspace_adapter.py)：准确生成回执缓存、原历史队列保存与查看、状态/取消/真实保存结果、项目关闭清理。
- [log_history_dialog.py](../../src/ui/qt/log_history_dialog.py)：两个原菜单按需操作、保存状态与只读历史报告查看窗口。
- [capability_catalog.py](../../src/services/capability_catalog.py)、[机器 GUI 清单](../../scripts/capability_gui_actions.json)、[覆盖文档](../../../CAPABILITY_COVERAGE.md)：明确人为 GUI-only，未暴露模型、远程或通用执行能力。
- [历史服务测试](../../tests/test_qt_log_history.py)、[原生专项](../../tests/qt_workbench_probe.py)、[验收登记](../../scripts/verify_qt_migration.py)；操作员说明、PROJECT_STATUS、DEVELOPMENT_LOG。

[结束快照](workspace-after.json) 与 P0 收口前快照比较仅上述 13 个明确范围追踪文件发生字节变化，其他 48 个原已修改文件哈希不变；原工作区分支 feature/pyside6-migration、HEAD 69887ae5f4dafdf109cb80e7a21cbeafa6f574fb、暂存 0、追踪变更仍 61。未改已批准生命周期修复的 controller/application/logger/service 终态逻辑，也未改资源等待、测试引擎、业务规则或任何其他并行改动。

仅 L0 合成专项通过，保存和恢复实际项目关闭/重开已测，实际用户工作台手工阅读和整机长期运行未开展。P0A 真正相互冲突佐证与 P0C 原断言等待时序缺口不因 P1 关闭。完整基线、L1 真实模型、L2 设备、L3 长期现场均未执行；无 Git 写操作、打包、删除或实际用户项目/凭据访问。
