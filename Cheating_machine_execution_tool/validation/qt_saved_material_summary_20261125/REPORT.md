# Qt 本地留存资料汇总（G0 / P0A）

2026-11-25，原源码基准 `69887ae5f4dafdf109cb80e7a21cbeafa6f574fb`，分支 `feature/pyside6-migration`。本轮仅 L0 合成验证；未提交、打包或使用实际项目资料、模型、设备和外部网络。

## 实际入口与结果

正式 Qt 主窗口选中项目 → 项目 → 任务历史 → 选择原开关机任务（或含开关机的原全流程任务） → 任务框右键「查看批次结果文件…」 → 选中一个文件 → 文件列表右键「汇总所选通道留存资料…」。原「打开文件」入口保留。

- 请求明确绑定项目 ID、任务 ID、运行 ID、原通道与文件名；选中行决定通道和一份文件，列表中同通道另一类型按原倒序的第一份作为第二份资料，无则明确缺失。不能传入目录，也不会补找其他通道或批次的文件。
- 复用原历史任务/运行快照/通道核对与归档末页读取。每份至多 120 行、128 KiB，最多展示 6 条明确标记；更早、未完整写入或跨页长行如实提示。独立普通文件读取成功、缺失及读失败分别计数，失败不掩盖另一份已有结果。意外 WAL 格式历史库在 SQLite 打开前拒绝，运行清单最多读取 256 KiB，避免附加文件及无界读取。
- 仅投影原开关机日志的明确 Ping 通标记和 WiFi 已知记录头中的原时间、通道、轮次和等级。原文自由正文不展开；等级并非测试结论，Ping 并非当前设备在线的证明。没有时间或无明确标记则显示未知；故障原因和当前状态不推断。
- 引用 `文件名@页首字节偏移:页内行号` 是本次读取位置，不是原日志中不存在的持久事件 ID。源文件的原历史和已保存材料不更改。
- 使用原后台历史读取队列和本次专属取消信号。取消、选定范围变化、切项目、关闭文件窗口后，迟到回执作废。只对精确请求、项目、任务、快照、通道和选中字面文件名匹配的结构化结果显示报告。主执行日志记录请求阶段和计数，不记录原文正文。无挂测控制或模型入口变更。

[实际合成服务报告正文](synthetic-report.txt) 由最终服务对两份临时合成文件生成（非手写示例）；正式 Qt 测试另行核对界面中呈现的相同结构及内容。

## 前置 G0

在修改前，用锁定 Qt CPython 3.9.10 / PySide6 6.8.3 实际运行：

- 40 项服务测试通过：`test_qt_channel_evidence`、`test_qt_ai_turn_display`、`test_qt_log_history`、`test_qt_archived_logs` 及 8 项工作区范围/关闭/取消/留存报告和无执行回放的指定用例。
- 100% Windows 私有桌面 18 项原生通过，76 个受管窗口，隔离违规为 0：原 `qt_channel_evidence_probe` 全部及原历史跨项目、留存报告入口。G0 原始终端结果在本轮测试输出中；未生成过程图片。

## 最终相关复验

| 范围 | 结果 | 证据 |
| --- | --- | --- |
| 相关服务组合 | 49/49 | [最终日志](service-tests-final.txt) |
| Qt 迁移契约 | 5/5 | [日志](migration-contract.txt) |
| Windows 原生 100% | 20/20，93 个受管窗口，违规 0 | [日志](native-final-1.txt) · [隔离](native-final-1.json) |
| Windows 原生 125% | 20/20，93 个受管窗口，违规 0 | [日志](native-final-1.25.txt) · [隔离](native-final-1.25.json) |
| Windows 原生 150% | 20/20，93 个受管窗口，违规 0 | [日志](native-final-1.5.txt) · [隔离](native-final-1.5.json) |
| 局部编译、能力覆盖、GUI 预检 | 8 个 Python 文件编译通过；覆盖检查通过 | 测试输出、能力清单 |

新增 5 项服务用例，覆盖两份实际合成日志、引用、跨项目/批次/通道/文件路径拒绝、缺少资料、模拟读取失败、末页限制、截断行处理、取消前和两份资料之间取消、拒绝 WAL 及超大运行清单。原始合成文件、快照与任务库在查询前后字节一致；意外 WAL 夹具原字节与目录内容未变化。补强前 48 项及三档原生通过记录仍保留，表格为补强后最终结果。

原生新增 `test_qt_saved_material_summary_uses_selected_history_and_discards_late_reads` 经过真实项目、任务历史、批次结果文件菜单和汇总操作。核对两份 CH07 源记录和引用、CH08 缺文件、单份读取失败后仍有另一份报告、原文模拟敏感标记未进入正文、取消并重查、切项目来回、关闭窗口以及延迟回执作废。原业务执行单例未因这次读取创建；合成任务库、快照和日志字节保持。原单通道普通问答、留存报告分析、历史文件打开和项目历史范围用例同时通过。

复验从主源码目录经 `scripts/run_tests.py`；原生使用 `scripts.gui_test_process.run_gui_child(framework='qt', native_render=True, timeout=180)`，`QT_SCALE_FACTOR` 分别为 `1`、`1.25`、`1.5`，精确用例 ID 见日志。未运行全套 Qt 迁移验证脚本或完整基线，本次原生为直接相关专项；完整基线最近记录仍以原提交为准。过程 PNG 生成、清理均为 0。

## 范围与尚待验收

此为 P0A 的最小留存文件汇总，不是跨任意资料的通用分析，不包括多通道批处理、持久化报告或真实模型推理。已有报告浏览、聊天、补充回执和挂测引擎保持。用户实际 Windows 源码界面的阅读复核尚待；L1 真实模型、L2 实际设备、L3 长期现场均未开展，不能由本轮 L0 代替。

修改的源码、测试和登记均限于本地历史读取/展示：`src/models/qt_log_history.py`、`src/services/qt_power_logs.py`、`src/services/qt_workspace_adapter.py`、`src/services/capability_catalog.py`、`src/ui/qt/log_history_dialog.py`、`tests/test_qt_log_history.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/capability_gui_actions.json`，以及根 `CAPABILITY_COVERAGE.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md` 和操作员说明。
