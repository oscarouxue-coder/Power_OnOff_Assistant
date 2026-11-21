# Qt 诊断报告浏览与管理

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 5。

## 原入口与迁移

原 Tk 报告窗口使用项目报告库、`AiRecordTitles` 和 `format_diagnostic_evidence`，批量管理委托 `AiDiagnosticService.delete_reports()`。Qt 从项目「AI 诊断」打开独立报告窗，通过同一项目库和业务服务浏览全部历史、切换分析和本地证据、重命名、删除选中及清空。刷新保留正在看的报告和仍存在的选中项。

永久删除确认默认取消，列出项目、数量及报告条目。确认期间新增的报告留在库中。原服务持锁复核排队、生成和清理状态，其中任一报告仍在使用时整批拒绝。标题改动只写本地展示名。删除保留已有会话、材料、案例、原始日志和模型配置。关闭会话窗后报告窗仍可使用，关闭所属项目时关闭对应报告窗。

此前 Qt 会话窗只有普通问答入口。参考图覆盖总览和项目详情，新增报告窗沿用同一主题和分栏布局，按可用工作区调整初始尺寸。分析以纯文本显示 Markdown 原文，证据沿用原格式化规则。旧 Tk 窗口继续提供格式化版和报告接手、案例确认。150% 原生截图

## 修改文件

- `src/models/qt_ai_reports.py`、`src/services/qt_ai_reports.py`、`src/services/qt_ai_chat.py`、`src/services/qt_workspace_adapter.py`
- `src/ui/qt/ai_report_dialog.py`、`src/ui/qt/ai_chat_dialog.py`、`src/ui/qt/ai_chat_controller.py`
- `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`
- 工程状态、开发日志、验收基线、能力覆盖、操作员说明及迁移进度

## 复验命令

```powershell
python scripts/run_tests.py test_qt_workspace_adapter test_ai_report_deletion test_ai_report_presentation test_ai_report_target_dialog test_ai_workspace test_ai_conversation test_capability_ai_data test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_ai_reports_verified
```

## 验证结果

- 158 项相关回归通过，覆盖项目库读取和标题持久化、同 ID 跨项目隔离、忙碌报告拒绝整批删除、删除后原会话和材料仍可读取、原 Tk 报告和能力接口。
- Windows 私有桌面 100%、125%、150% 各通过 67 项，共 201 项。每档管理 1,180 个 Qt 顶层窗口，隔离违规为零。新增用例覆盖项目报告入口、正文和证据、列表切换及刷新、重命名、默认取消、确认期间新增、另一项目同 ID 记录和窗口收尾。
- 355 份文件编译、345 份源码登记、能力覆盖、GUI 门禁、原协议及原核心源码保全检查通过。
- 对应验证通过后，清理 304 份过程截图、测试日志和结果文件，约 15.6 MiB。保留以上验证摘要与一张 150% 原生截图。

## 待验收范围

实际系统 DPI、多屏、真实模型与设备仍待验收。本增量使用临时项目库及模拟报告，未重跑完整基线或重建 Windows 包。后续增量已接入案例确认和报告转会话。[Qt 共用案例迁移记录](AI_CASES_QT_REPORT.md) · [Qt 报告接手迁移记录](AI_HANDOFF_QT_REPORT.md)
