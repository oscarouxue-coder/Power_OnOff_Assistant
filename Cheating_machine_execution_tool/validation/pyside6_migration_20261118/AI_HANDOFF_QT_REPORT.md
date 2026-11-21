# Qt 诊断报告转入排查会话

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 5。

## 审计与迁移

原 Tk「继续排查」调用 `AiConversationService.create_session_from_report`。带目标快照的报告沿用原目标和批次。缺少快照的旧报告需要操作员选择并确认同通道当前目标。报告正文作为历史证据进入项目会话库。没有批次的旧报告沿用 `historical:<报告ID>` 标记。

Qt 在项目报告窗口增加「继续排查」。带快照的报告直接按原服务创建会话。旧报告按项目读取当前已写入的通道及 Telnet 配置，沿用原 VLAN/串口映射和凭据参数。确认窗口默认不选目标，默认按钮为取消。提交时重新核对报告版本、同通道完整目标与模型身份。确认只对原项目和报告有效，且只能使用一次。

接手后打开该项目的会话和留存材料。接手本身不会建立设备连接或请求模型。取消、候选缺失及接手结果写入项目日志。后续增量已接入本机报告留存材料分析，设备主动采集和审批仍从原入口执行。需要回退时可从原 Tk 入口访问同一报告和会话库。[Qt 留存报告分析](AI_REPORT_ANALYSIS_QT_REPORT.md)

此前 Qt 报告窗口提供分析、证据和管理。本增量沿用头部按钮与原对话窗样式。参考设计图未单列旧报告确认弹窗。改造前的报告窗口 · 新版旧报告确认框，150%

## 修改文件

- `src/models/qt_ai_reports.py`、`src/services/qt_ai_reports.py`、`src/services/qt_ai_report_handoff.py`、`src/services/qt_ai_chat.py`、`src/services/qt_workspace_adapter.py`
- `src/ui/qt/ai_report_dialog.py`、`src/ui/qt/ai_chat_controller.py`
- `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`
- 工程状态、开发日志、验收基线、能力覆盖、操作员说明、迁移进度及相邻诊断报告

## 复验命令

```powershell
python scripts/run_tests.py test_qt_workspace_adapter test_ai_case_store test_ai_report_deletion test_ai_report_presentation test_ai_report_target_dialog test_ai_workspace test_ai_conversation test_capability_ai_data test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_ai_handoff_verified
```

## 验证结果

- 179 项相关回归通过，覆盖旧 Tk 和原报告服务、快照目标、旧报告选择、取消、确认失效、跨项目命令、报告改写及无候选时的处理。
- Windows 私有桌面 100%、125%、150% 各通过 69 项，共 207 项。每档管理 1,196 个 Qt 顶层窗口，隔离违规为零。新增原生用例验证默认取消、明确选中旧报告目标、两类报告转入正确项目会话及零发送、零采集。
- 359 份文件编译、349 份源码登记、能力覆盖、GUI 门禁、协议不变量与原核心源码保全检查通过。
- 最终验证通过后清理本增量 310 份过程截图、日志及结果文件，约 15.8 MiB。保留报告与代表性原生截图。

## 待验收范围

Qt 已接入报告转会话，后续仍需迁移设备会话资格、主动采集、工具及人工审批。原样机网络参数、真实模型、实体 DPI/多屏及目标电脑仍待现场验收。本轮使用临时项目和合成报告，未重跑完整基线或重建 Windows 包。
