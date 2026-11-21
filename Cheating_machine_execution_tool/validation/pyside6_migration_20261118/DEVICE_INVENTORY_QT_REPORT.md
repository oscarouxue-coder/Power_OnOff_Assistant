# Qt 设备管理与项目通道

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 3 与 Phase 5。

## 审计与迁移

此前工具栏已经可以只读刷新串口和网卡，通道窗口只消费候选名称，顶栏「设备管理」尚未接入。[改造前工作台记录](HOST_INVENTORY_QT_REPORT.md)

「设备管理」现在可以查看三个标签页。网卡显示当前读取的名称、系统状态和接口 GUID，串口显示本机枚举结果，项目通道显示已打开项目的选择、绑定与配置来源。网卡和串口分别显示最近成功读取的时间，读取失败时保留上次成功结果。租约列使用工作区活动租约，网卡匹配优先使用 GUID，仅匹配名称时明确标注。项目通道从已有配置或批次快照读取。

窗口沿用参考图的顶栏入口和项目原有主题。参考图没有给出设备管理弹窗，本次采用三个只读标签页。复用现有后台只读刷新与工作区定时器，窗口只有一个实例。项目任务续跑、设备指令和资源准入仍由原执行服务负责。

原 Tk 网卡改名还包括未绑定目标确认、Windows GUID 回读和多项目配置引用更新。Qt 本轮先迁移身份与占用查看。改名及其系统变更后同步失败分支继续独立跟踪。

## 修改文件

- `src/models/qt_device_inventory.py`、`src/services/qt_workspace_adapter.py`
- `src/ui/qt/device_inventory_dialog.py`、`src/ui/qt/main_window.py`、`src/ui/qt/workspace_controller.py`
- `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`
- `scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`
- `CAPABILITY_COVERAGE.md`、操作员说明、迁移计划与进度、工程状态、开发日志和验收基线

## 复验命令

```powershell
python scripts/run_tests.py test_qt_channel_configuration test_channel_config test_adapter_rename test_capability_channels test_qt_workspace_adapter test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_device_inventory_verified
```

## 验证结果

- 113 项相关回归通过，覆盖旧通道配置、网卡改名服务与资源保护，以及 Qt 设备快照独立保留最近成功结果。363 份文件编译、353 份源码登记、原协议不变量、能力覆盖及 GUI 守卫检查通过。
- 100%、125%、150% 的 Windows 私有桌面原生套件各通过 72 项，共 216 项。每档管理 1,211 个窗口，隔离违规为零。设备管理用例验证了窗口复用、部分刷新失败后保留网卡、租约释放后的显示更新及关闭后利用已有读取结果。核对 100% 和 150% 的截图，三个页签和刷新按钮可见，合成的接口 GUID 与占用项目名称完整显示。
- 100% 首轮在既有工作台关闭用例的 Qt 清理路径发生访问异常，未生成隔离报告。在同一源码及相同隔离条件下整档复跑通过。较早的 150% 单项首轮也缺少隔离报告，随后单项及整档通过。两次异常的根因未确定。
- 三档、专项和源码检查通过后，清理本轮 322 份过程文件，包括截图、测试日志、结果清单和首轮失败证据，共约 16.1 MiB。复验结果保留于本报告。

## 待验收范围

设备管理自动化使用模拟网卡和串口。待在目标机核对实际枚举、资源映射、Windows 系统 DPI 与多屏。本轮未运行完整基线或重建 EXE。原网卡改名继续由 Tk 入口执行，真实设备与长挂验收仍待完成。
