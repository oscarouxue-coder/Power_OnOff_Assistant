# Qt 共用案例库与人工确认

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 5。

## 审计与迁移

原 Tk「已确认案例」使用 `AiDiagnosticService` 和 `SharedCaseStore` 保存人工确认条目。库按 Windows 用户共享。原服务核对标题、实际原因、处理方法、复测结果和适用范围，保存修订历史，依据版本防止并发覆盖。停用的条目退出检索，删除留下原快照去重标记。Qt 调用同一项目服务和共用库。

从「AI 诊断 → 已确认案例」可浏览、新建、修订、停用或启用检索以及删除。报告管理菜单也可从当前报告启动新草稿，固定所属项目和来源报告。五项字段由操作员填写，保存需本机确认。跨项目编辑冲突会显示原服务反馈并保留当前输入，刷新后可再次核对。切换条目、更换草稿或关闭窗口前可取消放弃未保存修改。关闭项目和退出应用也先核对未保存字段。

原 Qt 会话窗此前没有案例入口。新增窗沿用现有主题，左侧列表显示检索状态，右侧显示报告来源和对齐后的五项字段。窗口按可用工作区调整初始尺寸。参考设计图未单列案例窗口。

## 修改文件

- `src/models/qt_ai_cases.py`、`src/services/qt_ai_cases.py`、`src/services/qt_ai_chat.py`、`src/services/qt_workspace_adapter.py`
- `src/ui/qt/ai_case_dialog.py`、`src/ui/qt/ai_chat_controller.py`、`src/ui/qt/ai_chat_dialog.py`、`src/ui/qt/ai_report_dialog.py`、`src/ui/qt/workspace_controller.py`
- `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`
- 工程状态、开发日志、验收基线、能力覆盖、操作员说明、迁移进度和相邻诊断报告

## 复验命令

```powershell
python scripts/run_tests.py test_qt_workspace_adapter test_ai_case_store test_ai_report_deletion test_ai_report_presentation test_ai_report_target_dialog test_ai_workspace test_ai_conversation test_capability_ai_data test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_ai_cases_verified
```

首轮原生冒烟中，测试退出时保留了一个陈旧版本草稿，测试清理尝试打开未适配的确认框。守卫按预期判失败。随后将确认应答纳入测试清理，并增加显式关闭项目时的草稿确认覆盖。

## 验证结果

- 178 项相关回归通过。覆盖原 Tk 案例和报告、报告来源按项目读取、共享案例版本冲突、启停检索、修订记录及删除后重复导入。
- Windows 私有桌面 100%、125%、150% 各通过 68 项，共 204 项。每档管理 1,188 个 Qt 顶层窗口，隔离违规为零。覆盖从报告新建、默认取消、共享读取、旧版本拒绝后保留输入、关闭项目确认、停用和删除。150% 原生截图
- 358 份文件编译、348 份源码登记、能力覆盖、GUI 门禁、原协议及原核心源码保全检查通过。
- 最终复验通过后清理过程截图、日志、结果和已被替代的初次失败证据，共 309 份，约 15.8 MiB。保留本报告及一张 150% 原生截图。

## 待验收范围

案例由临时 SQLite 和合成数据验证。实际系统 DPI、多屏、旧案例数据及目标机快照导入待现场复验。设备诊断、审批、工具和平台控制面继续按第一阶段推进。本轮未重跑完整基线或重建 Windows 包。需要回退时可从原 Tk 入口访问同一案例库。
