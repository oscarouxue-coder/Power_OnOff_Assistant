# DUTPilot GUI 升级复验

2026-11-23 核查原设计规范的 Phase 0–7，更新候选包和现场证据的对照记录。逐 DUT 工作台在只有计时变化时保留表格及选中项，收到新观测时更新通道和业务状态。

## 已执行的检查

- 更新前，当前工作区使用标准 `build_line_check_assistant.ps1 -CheckOnly`。锁定的 Qt 环境、3,366 项完整基线和 273 项指定回归通过。
- 增强原生用例 `test_qt_switch_preserves_reported_progress_and_separates_health_sources`。原实现的单元格对象在计时变化时被重建，新增断言复现了差异。更新后验证计时、表格及选择保持、新观测和业务汇总，原生私有桌面专项共 2 项通过，隔离违规为零。
- 对修改的源码和原生测试执行 `py_compile`，通过 `scripts/verify_capability_coverage.py --update` 同步能力清单。现场采样脚本用自建临时进程复跑 3 项，通过。
- 快照使用同一个锁定 Qt 解释器执行 `scripts/verify_qt_migration.py --python <锁定解释器> --output <验证目录>`。100%、125%、150% 三档各通过 117 项，每档 1,956 个受管窗口，指定用例全部命中，隔离违规为零。[三档结果](native/results.json)
- 原生阶段结束后移入回收站 447 张本轮过程截图，保留三档结果、布局 JSON 和原始测试输出。11 月 22 日通过的 Qt 入口批次同时完成同范围的 447 张过程截图清理。

## 标准候选包

同一份源码快照通过 `build_line_check_assistant.ps1` 构建 Qt V1.3.0。最终完整基线运行 3,366 项，273 项指定回归全部命中。成品使用 Windows x64 GUI 入口，实际 EXE/PYZ 的 364 个项目模块、Qt 入口和操作员说明全部与构建输入匹配。ZIP 有 246 个文件，目录内容、CRC 及 EXE 和 ZIP 的 SHA256 均核对通过。[标准构建日志](build.txt) · [静态成品证明](package-proof.json)

便携候选位于下列独立目录。本机仅静态核验成品。

```text
C:\Users\Administrator\AppData\Local\LineCheckAssistant\gui-release-candidates\gui-guidelines-20261123-l4dy20ok\Cheating_machine_execution_tool\dist\gui-guidelines-20261123
```

使用 `DUTPilot_portable.zip` 和同目录的 `DUTPilot_portable.zip.sha256.txt`。本候选 ZIP 为 55,594,884 字节，SHA256 为 `bfe5050bb12bf073841d2e730312e68d372b72b0002a9ee22e8e92eb3a0dea16`。

## 现场验收

本地现场材料含 `watch_process.ps1`、`FIELD_RECORD.md` 和此候选 ZIP 的 SHA256 校验文件。材料 ZIP 为 4,586 字节，SHA256 为 `7ecc7f762f6b2563ac7375a1ff62dee8a35eef3de75485d08e2c073bfcd4f0d4`。材料已检查内容与 CRC，在带空格和中文的解压目录用自建进程验证 6 项采样行为。候选 ZIP 继续使用上节版本。[现场验收材料 ZIP](DUTPilot_field_acceptance.zip) · [记录表](../pyside6_migration_20261118/long_run_acceptance/FIELD_RECORD.md)

2026-11-23，项目负责人回复「现场验收通过」。按本批 V1.3.0 候选的交接范围登记，包括目标 Windows 启动、旧项目、系统 DPI 和多屏，逐 DUT 开关机 500 轮，语音及 LAN 48 小时专项，常温全业务老化 7 天，以及 24/72 小时无人值守。本次依据为负责人确认，批次编号、实测数值和原始日志以各现场记录为准。[现场交接及证据清单](../../../docs/GUI_UPGRADE_EXECUTION_PLAN.md#v13x-现场验收交接)
