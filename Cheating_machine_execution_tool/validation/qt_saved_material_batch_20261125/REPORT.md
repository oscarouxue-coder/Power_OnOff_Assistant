# Qt 多通道本地留存资料汇总（P0B）

2026-11-25，原工作区 `feature/pyside6-migration`，HEAD `69887ae5f4dafdf109cb80e7a21cbeafa6f574fb`，保留未暂存的 P0A 源码及其[验证报告](../qt_saved_material_summary_20261125/REPORT.md)。本次只实施本地留存资料多选汇总，未调用真实模型、设备、网络或项目资料。

## 开工前 P0A 核对

P0A 已有 `test_material_summary_reads_two_saved_sources_with_exact_scope_and_citations` 和 `test_material_summary_separates_missing_unreadable_and_keeps_other_result`：同一合成项目、批次、CH 下，原两类文件可读与缺少一类或一类读取失败，分别产生 2/0/0、1/1/0、1/0/1 的实际读取/缺失/失败计数，并保留有效引用。原生 `test_qt_saved_material_summary_uses_selected_history_and_discards_late_reads` 核对实际 UI 的资料充分、缺失和读取失败报告。

相互冲突的佐证导致报告变化的独立对照测试未覆盖；原 WiFi 记录等级与 Ping 观察不是同一事实的真假对立，不据此称为冲突测试通过。本轮未重复新增 P0A 佐证测试。原入口和服务仅支持单通道，未见既有多通道汇总，故实施 P0B 最小增量。

## 实际入口与边界

正式 Qt 主界面 → 项目 → 任务历史 → 选择原批次 → 右键「查看批次结果文件…」→ Ctrl 多选同一批次的通道文件 → 右键「汇总所选通道留存资料…」。单选保持原 P0A 行为；多选时不直接打开单个原文件，重新单选即可使用既有「打开文件」。

- 只接受同一明确项目、任务、运行 ID 内 2–16 个不同通道，每通道同类型文件最多显式选一份；未选的另一类型复用 P0A 的已列出文件倒序第一份选择规则。不从其他项目、批次或未选择通道补找。预检全部目标后才读取资料。
- 每通道独立使用现有 `summarize_history_materials`，沿用单份最多 120 行/128 KiB、最多 6 条明确标记、来源文件、原日志时间或未知、页内记录定位、缺失和读取失败，以及对任意路径、WAL 和超大快照的原限制。总报告按通道独立排列；不展开自由原文，不推断设备实时状态或根因。
- 文件部分失败由原单通道报告记数；整通道无法核对另外标记，不清除此前或后续通道的结果。只在完成整个通道核对后保存其报告；取消中断的通道不伪造部分观察、时间或引用。手动取消保留已完成的通道，未完成通道标记取消并停止后续读取。
- 使用原后台历史读取队列，未创建业务执行实例。切项目、切批次（包括切走再切回）、改选或关闭窗口使在途请求作废；只有匹配请求 ID、项目、批次及完整选定目标的回执可以在当前窗口呈现。主执行日志仅记录请求编号、选择数量、阶段及终态计数。

## 实际合成报告

以下由最终服务对临时合成文件实际生成，不是手写计划；正式 Qt 原生用例另行核对相同结构的展示。

- [三通道报告：CH07 完整、CH08 缺失、CH09 读取失败](synthetic-batch-report.txt)。三个通道分别保有证据及独立计数。
- [取消报告：CH07 已完成，CH08/CH09 已取消](synthetic-cancelled-report.txt)。已完成通道的报告保留，未完成通道没有假造引用。

## 验证结果

| 范围 | 实际结果 | 证据 |
| --- | --- | --- |
| 相关服务、能力及 Qt 迁移契约 | 58/58（含 5 项迁移契约） | [日志](service-tests.txt) |
| Windows 原生 100% | 23/23，113 个受管窗口，违规 0 | [日志](native-1.txt) · [隔离](native-1.json) |
| Windows 原生 125% | 23/23，113 个受管窗口，违规 0 | [日志](native-1.25.txt) · [隔离](native-1.25.json) |
| Windows 原生 150% | 23/23，113 个受管窗口，违规 0 | [日志](native-1.5.txt) · [隔离](native-1.5.json) |

新增四项服务用例：

- `test_material_batch_reports_three_channels_independently_and_keeps_valid_results`：完整、缺失、单份失败；原文件/任务库/清单字节不变；来源不串。
- `test_material_batch_rejects_mixed_and_duplicate_scope_before_any_source_read`：不同项目、批次、任务、重复通道、路径及非原通道拒绝，未读取任何结果资料。
- `test_material_batch_cancel_preserves_completed_channel_and_marks_rest_without_read`：已完成一通道、第二通道取消、第三通道不再读取；受理后提前取消也不读取。
- `test_material_batch_whole_channel_failure_does_not_erase_other_channel_results`：中间整通道失败仍保留前后结果；拒绝不匹配的结构化回执。

原生新增 `test_qt_multi_channel_saved_material_summary_preserves_independent_and_cancelled_results` 从实际 Qt 项目任务历史入口，使用 Ctrl 实际选择通道行、既有右键菜单和取消按钮。测试了三通道正常/缺失/读取失败及引用、取消后保留 CH07、切项目来回、直接关闭文件窗口、历史批次变化后切回、另一个批次两通道报告及模拟迟到旧回执。实际未创建业务执行实例，合成任务库、运行清单和原日志字节保持一致。原单通道汇总、历史文件打开、留存报告分析、掉线问答、普通流式终态及连续诊断补充回执均随同原生回归通过。

复验采用锁定 Qt CPython 3.9.10 / PySide6 6.8.3，经 `scripts/run_tests.py` 和 `scripts.gui_test_process.run_gui_child(framework='qt', native_render=True, timeout=180)`，三档 `QT_SCALE_FACTOR` 为 `1`/`1.25`/`1.5`。精确用例 ID 见各日志。补充前置小组合 25 项及初次原生 3 项亦通过；表格为最终相关组合。过程 PNG 生成及清理均为 0。

## 文件和验收边界

本轮仅继续修改原 P0A 文件中的 `src/models/qt_log_history.py`、`src/services/qt_power_logs.py`、`src/services/qt_workspace_adapter.py`、`src/ui/qt/log_history_dialog.py`、`src/services/capability_catalog.py`、`tests/test_qt_log_history.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、GUI 能力机器清单、操作员说明、项目状态、验收基线及开发记录。P0A 原验证及其它已有工作保留。

本轮 L0 合成验证通过，不是实际挂测运行证明；未开展 L1 真实模型、L2 真实设备、L3 长时现场或目标机器实际用户操作，不改变原挂测引擎、业务权限及已有判据。未执行完整基线、全量 Qt 迁移专项、打包、Git 暂存/提交/推送或删除。现有结果仅在本地窗口展示，持久化属后续阶段。
