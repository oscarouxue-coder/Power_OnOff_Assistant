# Qt 留存报告会话分析

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 5。

## 审计与迁移

原 `AiConversationService` 对历史报告复用项目会话、锁定模型、上下文预算和停止处理。模型通过工具能力验证后，历史会话可在本次会话的留存证据中检索，也可向用户询问。主动采集资格另行判断。

Qt 中本机报告会话可继续提问、导入文本材料、查看证据和停止本轮。报告转入时仍仅建会话，操作员点击「发送」后才请求已配置的模型。报告会话使用原快照与留存历史，Qt 不读取当前批次证据、不开放设备或本机执行。模型未经工具能力验证时直接分析已有材料，验证通过后继续使用原会话内证据检索及询问。普通问答仍无工具；非本机、非报告的旧诊断会话仍可阅读。

界面标记「仅分析留存材料」，输入提示与当前范围一致。旧会话创建消息中关于按需采集的提示在 Qt 报告会话中以中性文本显示，原记录保留。布局沿用原 Qt 会话分栏。参考图未单列报告分析窗口。改造前的普通问答窗口 · 新版留存报告分析，150%

## 修改文件

- `src/models/qt_ai_chat.py`、`src/services/qt_ai_chat.py`
- `src/ui/qt/ai_chat_dialog.py`、`src/ui/qt/ai_chat_controller.py`
- `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`
- 工程状态、开发日志、验收基线、能力覆盖、操作员说明、迁移进度及报告接手记录

## 复验命令

```powershell
python scripts/run_tests.py test_qt_workspace_adapter test_ai_case_store test_ai_report_deletion test_ai_report_presentation test_ai_report_target_dialog test_ai_workspace test_ai_conversation test_capability_ai_data test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_ai_report_analysis_final
```

## 验证结果

- 180 项相关回归通过。新增模拟模型用例验证报告入会话前不触发请求、留存证据可跨回合检索、越界设备请求被拒绝、不读取实时上下文，并验证平台会话仍不能从本机入口发送。
- 359 份文件编译、349 份源码登记、能力覆盖、GUI 门禁、协议不变量和原核心源码保全检查通过。
- 首轮 125% 的新增分析用例通过，既有报告管理用例在程序化选择报告后等待重命名时超时。复验改为点击实际列表行，并校验单选状态。
- 最终 Windows 私有桌面 100%、125%、150% 各通过 70 项，共 210 项。每档管理 1,201 个 Qt 顶层窗口，隔离违规为零。新增原生用例覆盖转入后手动发送、问答显示、留存范围提示及停止流式回复。
- 复验通过后清理本增量 624 份过程截图、日志和结果文件，约 31.9 MiB，包含首轮已由成功复验替代的证据。保留报告及代表性截图。

## 待验收范围

本轮使用模拟模型和临时项目。真实供应商请求、旧项目材料和实际 DPI 待现场复核。设备实时诊断、审批、工具和远程平台继续迁移。需回退时可从原 Tk 入口访问同一项目会话。本轮未运行完整基线或重建 Windows 包。
