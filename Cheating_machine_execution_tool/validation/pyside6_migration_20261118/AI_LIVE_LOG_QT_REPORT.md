# Qt 实时 AI 日志摘要与原文归档

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 5、6 和 7。

## 审计

旧 Tk 实时日志已通过 `main_log_filter` 摘要 AI 过程。原服务过滤模型密钥后的记录保留在主日志文件。Qt 在此前直接将同一条记录交给实时缓冲和工作区原文文件。频繁的正常模型请求因而会占用实时缓冲。

## 实施

Qt 从显示交接缓冲之前应用旧规则。正常请求、成功回执、用量与已知采集过程按旧规则收起。排查开始和结束保留简明摘要。待核实、失败、解析失败及生产者明确发出的警告和错误继续可见。由原规则识别的状态参与 Qt 级别筛选和颜色显示。结束摘要保留普通信息级别。嵌套 AI 前缀的设备回显和其它业务原样进入原显示路径。

显示投影沿用原记录的项目、任务、通道和时间。工作区文件继续保存原服务已过滤模型密钥的原文，归档可查看。显示缓冲的淘汰统计仍只计算达到容量时实际被移除的条目。日志格式化函数无界面状态，可由现有日志生产线程调用。原会话、模型、采集、执行和权限入口继续沿用。

## 修改文件

- `src/ui/qt/log_presentation.py`、`src/ui/qt/log_panel.py`、`src/ui/qt/workspace_controller.py`、`src/services/qt_workspace_adapter.py`
- `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`
- `scripts/verify_baseline.py`、`scripts/verify_qt_migration.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json` 和能力覆盖文档
- 操作员说明、迁移计划和进度、项目状态、开发记录及验收基线

## 复验命令

```powershell
python scripts/run_tests.py test_main_log_filter test_ai_conversation test_qt_workspace_adapter test_qt_archived_logs test_qt_log_export test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_ai_log_verified
```

## 已核对

- 按 39 行旧日志结构回放脱敏样例，实时区保留开始和结束两条摘要。额外追加 550 条已知常规模型消息，未增加显示缓冲淘汰，也未挤掉异常状态、未知格式、设备原样回显或明确错误；逐条核对原文仍在工作区文件。
- 150% 私有桌面专项 3 项通过。核对实时日志摘要、级别筛选、待核实橙色格式、归档原文及增量刷新。参考图使用表格式实时日志，Qt 继续沿用现有文本区。150% 截图核对可见的待核实、失败和结束状态。
- 181 项专项回归通过，涵盖原 Tk 日志规则、原 AI 会话、Qt 显示缓冲、归档和导出。370 个文件编译、360 个源码登记、能力覆盖、GUI 守卫、协议和原实现保全检查通过。
- Windows 私有桌面在 100%、125%、150% 各通过 81 项，共 243 项。每档管理 1,769 个窗口，隔离违规为零。三档截图尺寸为 1366×768、1708×960、1925×1061 像素，150% 受桌面可用区域约束。
- 验证通过并汇总后，将本轮 349 份截图、测试日志和结果清单移入 Windows 回收站，共约 17.5 MiB。

## 待验收范围

本轮使用模拟日志与离线回放。真实模型、采集、设备或平台操作由后续现场验收确认，远程控制面继续按原计划逐项迁移。完整基线和最终打包继续待办。
