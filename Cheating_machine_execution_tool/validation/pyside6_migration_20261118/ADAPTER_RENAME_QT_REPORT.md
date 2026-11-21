# Qt 网卡改名与项目通道同步

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 3 通道配置与 Phase 6 资源保护。

## 审计与迁移

原 Tk 通道选择会撤回没有数字尾号的候选，并提供 Windows 网卡改名。原服务校验管理员权限及新名称末尾的 2–254 数字，下发一次 Windows 系统改名并回读同一 GUID。回读成功后更新源通道、所有已打开项目中的同名引用和 PC 源 IP 推导，保留原有效 COM。此前 Qt 通道页可以查看候选，「设备管理」可以查看 GUID 和占用。[改造前通道配置](CHANNELS_REPORT.md) · [设备管理](DEVICE_INVENTORY_QT_REPORT.md)

Qt 通道候选列表沿用同一触发方式。输入新名称后，本机确认窗列出源网卡、新名称、接口 GUID、受影响项目及通道，默认取消。确认过期、项目配置变化、目标 GUID 改变、管理员权限不足或任务运行时均会拦截。改名前先关闭其它项目的配置窗口，未保存输入按原关闭提示处理，项目本身可以保持打开。当前窗口的未提交输入继续保留。

改名、回读和项目同步在现有后台工作区队列执行。确认时租用新旧名称及 GUID，通过回读后同步通道草稿、工作区身份登记和设备管理。沿用原规则只持久化启用通道，保留有效 COM 和其它字段。各项目仍经既有保存操作提交配置版本，正在使用的批次快照保持原配置。配置外的设备 IP、串口和上下电均不会受本操作控制。

写盘部分失败时报告受影响项目，保留未知结果保护；系统已确认改名的情况下，不自动改回，也不再发送改名。操作员现场核对系统和项目配置后，通过原「核实未知任务」入口记录依据。新增入口仅供本机 GUI；原通用能力与旧 Tk 入口继续可用。

参考图未单列改名弹窗。复用通道配置现有下拉列表和 Qt 确认对话框，保留原页面布局。

## 工作台冷启动修复

原生复验中的既有工作台关闭用例在初始化期间崩溃。用同一隔离入口缩小到四个用例后，看到崩溃前抛出 `ImportError`。创建工作区时，更新控制器与工作区线程并发首次加载 Requests，更新控制器读取到部分初始化的 `requests.adapters`。现从主线程在工作区线程启动前加载更新控制器依赖，启动仍沿用仅在操作者请求时检查更新的流程。保留原生隔离、窗口清理和退出断言。

## 修改文件

- `src/services/qt_adapter_rename.py`、`src/services/qt_channel_configuration.py`、`src/services/qt_execution_adapter.py`、`src/services/qt_workspace_adapter.py`
- `src/ui/qt/channel_configuration_dialog.py`、`src/ui/qt/workspace_controller.py`
- `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`
- `scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`
- 能力覆盖、操作员说明、迁移进度、工程状态、开发日志和验收基线

## 复验命令

```powershell
python scripts/run_tests.py test_qt_channel_configuration test_channel_config test_adapter_rename test_capability_channels test_qt_workspace_adapter test_qt_migration_contract test_capability_coverage test_app_update test_app_update_ui test_qt_execution_adapter -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_adapter_rename_postfix
```

## 验证结果

- 224 项相关回归通过，覆盖通道、网卡改名、检查更新、工作台命令及原任务执行适配器。新增回归模拟了确认后 GUID 替换、另一项目文件变化、系统改名成功但另一项目草稿写入失败。前两种情况均未下发。部分成功时只下发一次，失败项目保留原草稿，新旧名称和 GUID 持久保护仍有效。
- 364 份文件编译、354 份源码登记、原协议不变量、能力覆盖及 GUI 守卫检查通过。源码保全核对原 Tk 应用、旧执行路径、核心服务和本机配置。
- 原生用例通过实际 Qt 下拉列表触发，模拟输入及确认。取消时保留两项目草稿。确认时两个项目同步新别名，源项目保留原 VLAN 推导的 COM，另一项目保留显式 COM。目视比对改前通道报告和改后界面，名称、样机 COM 和 PC 源 IP 在原位置，未提交的管理 IP 输入仍在界面。
- 修复后在 150% 缩放的独立私有桌面冷启动 3 次。每次 5 项启动、关闭、手动检查更新及隔离守卫用例通过，隔离违规为零。
- 修复后的完整套件在 100%、125%、150% 各通过 73 项，共 219 项。每档 1,219 个受管窗口，隔离违规为零。复核了 100% 和 150% 的最终画面，网卡名、原 COM 与两行反馈均完整可见。
- 三档、冷启动专项和源码检查通过后，清理本轮 684 份截图、测试日志、结果清单和早期失败及中断批次证据，共约 31.8 MiB。验证结论保留在本报告。

## 待验收范围

自动化使用模拟网卡身份和系统改名执行器。实际 Windows 管理员操作、设备关联、配置保存再重开，以及长时间挂测仍需现场验证。本轮未运行完整基线或重建 EXE，旧 Tk 操作入口保留。
