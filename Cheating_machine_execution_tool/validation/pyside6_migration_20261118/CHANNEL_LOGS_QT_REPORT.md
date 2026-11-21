# Qt 通道结果日志和本次 WiFi 日志

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 3 和 Phase 7。

## 审计

原 Tk 的通道右键菜单支持打开开关机结果和当前尝试的 WiFi 文件。开关机结果通过 `latest_power_test_result_log` 在项目当前结果目录按文件名选择。WiFi 通过 `PowerTestResumeSession.current_wifi_log` 定位当前尝试。原版本只向 Windows 文件关联提交路径。Qt 在此之前只有失败续跑、实时日志及归档入口。

## 实施

Qt 项目详情的通道矩阵与列表共用右键菜单。菜单记录发起时的项目与通道。项目工作线程在操作时按已知的最近开关机任务绑定运行快照，复用原结果文件选择规则。尚无本工作台开关机批次时，可打开原项目草稿目录内已有的通道结果文件。

WiFi 需绑定同一已提交的开关机批次及原服务提供的当前尝试。当前尝试未产出、文件移走、路径重定向或关联程序失败时，状态栏与执行日志反馈。该入口不会用历史 WiFi 扫描结果补空。Windows 只收到已校验的项目、批次及通道目录中的 `.log` 路径。定位及打开在工作区线程进行，运行文件字节保持原样。

本地操作员入口复用原 `logs.power` 和 `logs.wifi` 对应的定位语义。现有 AI / 远程日志读取权限及受控入口继续沿用，Windows 文件关联操作由本地 GUI 触发。

## 修改文件

- `src/services/qt_power_logs.py`、`src/services/qt_power_resume.py`、`src/services/qt_execution_adapter.py`、`src/services/qt_workspace_adapter.py`
- `src/ui/qt/project_detail.py`、`src/ui/qt/workspace_controller.py`
- `tests/test_qt_execution_adapter.py`、`tests/qt_workbench_probe.py`
- `scripts/verify_baseline.py`、`scripts/verify_qt_migration.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json` 和能力覆盖文档
- 操作员说明、迁移计划和进度、项目状态、开发记录及验收基线

## 复验命令

```powershell
python scripts/run_tests.py test_qt_execution_adapter test_qt_workspace_adapter test_power_test_log_service test_power_test_resume test_power_test_wifi_logs test_capability_application test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_channel_log_verified
```

## 验证

- 150% 原生专项 2 项通过。矩阵与表格的上下文菜单均命中正确项目与通道。当前尝试变更、项目切换、真实任务生命周期及已有续跑入口使用模拟边界验证。
- 编译 369 个文件、359 个源码登记项、能力覆盖、GUI 守卫、协议与原实现保全检查通过。
- 参考图展示矩阵和实时日志，未展示通道上下文菜单。本轮使用原 Qt 菜单，150% 截图核对三项文字均可见。
- 150 项专项回归通过。覆盖草稿结果、当前快照优先、原文件名顺序、当前文件缺失时保留提示、系统打开失败反馈和原文件字节一致。
- Windows 私有桌面 100%、125%、150% 各通过 79 项，共 237 项。每档管理 1,755 个 Qt 窗口，隔离违规为零。三档菜单截图分别为 216×81、265×98 和 314×117 像素。
- 验证通过且结论入档后，将本轮 343 份截图、日志和结果清单移入 Windows 回收站，共约 17.2 MiB。

## 剩余验收

Windows 文件关联调用用替身捕获，实际目标机关联程序、真实挂测输出和长挂仍待验收。本轮操作者入口与原行为一致地使用当前批次和草稿结果位置。后续已加入[按历史任务打开所选运行快照文件](HISTORY_RESULT_FILES_QT_REPORT.md)。最终完整基线和重新打包在后续验收执行。
