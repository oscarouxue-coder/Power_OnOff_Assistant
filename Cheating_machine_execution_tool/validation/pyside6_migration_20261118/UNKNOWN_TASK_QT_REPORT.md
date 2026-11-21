# Qt 本机核实未知任务

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 5 和 Phase 6。

## 原入口与迁移边界

Tk 的「核实未知任务…」从 `WorkspaceResources.unknown_gui()` 读取 GUI 保护记录。旧任务可能在异常退出后仍持有资源保护。`WorkspaceService.resolve_gui_unknown()` 保存本机核实依据，经原 OS 锁和资源保护逻辑解除所选记录，随后在原运行记录写入核实标记，保留 `unknown` 结果。Qt 复用这些查询与写入入口。

Qt 经现有工作区队列读取记录并提交核实。操作员选择指定记录，填写依据，再通过默认「否」的确认框复核完整记录 ID。后台复核 ID 和标签，旧版带所属项目 ID 的记录需先打开项目以加载其运行记录。若运行记录仍处于未完成状态，原保护保留。依据只进入现有核实回执，主日志保留操作结果。提交期间窗口保留，待后台返回后才允许退出。成功后立即刷新状态，Qt 启动前检查识别已核实的历史 `unknown` 记录。原测试调度和设备命令沿原路径执行。

当前条目对应旧 GUI 保护、Qt 通道和配置保存产生的 GUI 保护。持久化 `CapabilityJobs` 的未知结果由旧 `CapabilityManagement.reconcile()` 独立处理，沿原 `CapabilityJobs.resolve_unknown()` 核对可信操作身份、通道和现场结果。该 Qt 审阅入口待迁移。缺少 GUI 保护记录或仍处于准备、排队状态的历史记录继续保守拦截，归入后续异常退出复验。

## 文件

- Qt 对话框和入口见 `src/ui/qt/unknown_task_dialog.py`、`src/ui/qt/workspace_controller.py`。
- 后台排队、原服务绑定和状态守卫见 `src/services/qt_workspace_adapter.py`、`src/services/qt_execution_adapter.py`、`src/services/qt_configuration_service.py`。
- 回归测试和门禁登记见 `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`。
- 同步项目状态、验收基线、开发记录、业务覆盖、迁移计划及进度表、操作员说明。

## 验证

在主源码目录使用锁定环境执行。

```powershell
python scripts/run_tests.py test_qt_workspace_adapter test_qt_execution_adapter test_qt_migration_contract test_qt_configuration_service test_project_completion test_project_management -v
python scripts/run_tests.py test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_unknown_task_verified
```

- 128 项相关回归通过。临时工作区重启后，原保护继续阻止执行。项目未打开、记录标签变化、空白依据、依据写入失败及重复请求均被拦截。成功后核对原回执、运行记录仍为未知、其它项目记录仍在、关开项目后标记仍生效。相关回归
- 150% Windows 私有桌面单项通过。验证空列表、默认「否」、同一记录绑定、确认后状态刷新及原任务结果保留。初测结果
- 能力覆盖专项通过 3 项。342 份文件编译、332 份源码登记、GUI 窗口隔离预检、协议不变量及原业务保全通过。源码检查
- Windows 私有桌面三档正式测试退出 0。100%、125%、150% 各通过 63 项，共 189 项。每档管理 1,156 个 Qt 顶层窗口，隔离违规为零。三档结果

## 截图与剩余验收

- 150% 源码运行时状态。核实前 · 填写依据 · 核实后
- 参考图以总览和项目详情为主。核实窗从项目菜单按需打开，沿用当前 Qt 字体和控件样式。截图使用模拟的中断记录。
- 本轮未重跑完整基线或 Windows 打包。实际异常退出后的人工核实、真实设备路径及长挂仍待验收。
