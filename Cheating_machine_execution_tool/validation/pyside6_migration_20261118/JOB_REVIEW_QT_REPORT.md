# Qt 持久化业务任务现场核实

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 5 / 6。

## 审计与迁移边界

旧 `CapabilityManagement.reconcile()` 从原任务读取可信操作身份和目标通道，经本机审阅后调用 `CapabilityJobs.resolve_unknown()`。该服务记录现场结论、保留原结果字段并处理持久化资源保护。它和「核实未知任务…」的普通 GUI 保护记录是两个现有入口。

Qt 在所选项目的「任务历史」中提供按需入口。打开历史仍使用只读 SQLite 连接。右键选中任务执行「现场核实结果…」后，后台核对任务确实来自该项目的原库。若历史记录仍标记为运行或等待，在此明确操作后，由原运行时获取任务库独占租约并按既有规则将中断记录置为未知。仍有实际工作线程的任务不能核实。

对话框显示完整任务编号、项目和通道。选择现场结论、填写依据并通过默认「否」的本机确认后，后台消费一次性确认并复核原记录版本，调用相同的 `CapabilityJobs.resolve_unknown()`。原服务记录 `succeeded`、`failed` 或 `not_executed` 依据，现有 `not_executed` 对应任务终态 `failed` 的规则继续生效。成功后更新任务历史、项目摘要及已缓存的任务状态。依据保留在原任务结果内，主日志记录步骤但省略依据正文。一次核实不派发设备命令，也不向 AI 或远程平台注册额外权限。

## 修改文件

- `src/models/qt_log_history.py`、`src/services/qt_log_history.py`、`src/services/qt_job_review.py`、`src/services/qt_execution_adapter.py`、`src/services/qt_workspace_adapter.py`
- `src/ui/qt/job_review_dialog.py`、`src/ui/qt/log_history_dialog.py`、`src/ui/qt/workspace_controller.py`
- `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`
- 操作员说明、开发日志、项目状态、验收基线、能力覆盖、迁移计划与进度表

## 验证命令

```powershell
python scripts/run_tests.py test_qt_workspace_adapter test_qt_execution_adapter test_qt_log_history test_qt_migration_contract test_project_completion test_project_management test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_job_review_final
```

## 结果与剩余验收

- 串行复验通过 118 项。覆盖中断记录的原恢复路径、选定任务尚在收尾、跨项目、取消与重复提交、审阅期间原记录变化、只解除指定任务的保护，以及依据和原结果字段保留。专项回归
- Windows 私有桌面 100%、125%、150% 各通过 64 项，共 192 项。每档管理 1,163 个 Qt 顶层窗口，隔离违规为零。新增用例验证从项目历史右键打开、默认否、写入后刷新及无任务重放。三档结果 · 150% 实际界面
- 344 份文件编译、334 份源码登记、能力覆盖、窗口预检、协议不变量、原 Tk 和设备服务保全通过。源码检查
- 中间轮并行专项发生模拟网卡资源锁冲突，125% 原生套件另出现两个既有用例的提示窗守卫报错。最终改为串行执行，相关用例均通过。清理 579 份重复截图及被最终复验替代的过程文件，保留本次最终证据。
- 小窗口效果沿用 Qt 任务历史及系统缩放相应布局。真实异常退出、原无保护或未完成旧 GUI 历史、设备和长挂仍需现场核验。本轮未执行完整基线或重建 Windows 验证包。
