# Qt 工作台的多项目自动开关机

原任务要求两个项目的配置、运行状态、日志和停止请求分别归属各自项目，共用硬件时由业务服务阻止冲突。此前两套执行器的隔离已有模拟验证，但 Qt 工作区仍在另一个项目运行时禁用“开始测试”。

## 原入口与修改

| 文件 | 修改及复用范围 |
| --- | --- |
| [Qt 工作区](../../../src/services/qt_workspace_adapter.py)、[项目执行器](../../../src/services/qt_execution_adapter.py)、[通道续跑](../../../src/services/qt_power_resume.py) | 工作区在准备和确认时分别核对其他项目实际仍在运行的任务及待续跑批次。独立的自动开关机任务可以同时向原服务申请资源，确认仍绑定本项目的一次性令牌。其他设备业务继续按既有准入规则执行。 |
| [项目显示数据](../../../src/models/workbench_presentation.py)、[项目详情](../../../src/ui/qt/project_detail.py)、[工作台控制器](../../../src/ui/qt/workspace_controller.py) | 当另一个项目正在自动开关机时，当前项目可使用原“开始测试”入口。环境检查、单次上下电与全流程继续遵守各自的前置条件。 |
| [项目资源](../../../src/services/project_execution.py)、[原 Tk 项目入口](../../../src/ui/project_workspace.py)、[设备业务服务](../../../src/services/capability_device_services.py) | 原执行器从选中方案读取 WiFi 开关。此前资源服务只读固定的默认文件。现在通过原请求解析器核对选中方案，并在实际任务快照进入编排器前再次核对无线资源。配置无法解析时保守预留无线接口，业务预检继续给出原配置错误。 |
| [服务测试](../../../tests/test_qt_execution_adapter.py)、[工作区测试](../../../tests/test_qt_workspace_adapter.py)、[原生窗口](../../../tests/qt_workbench_probe.py) | 覆盖无线主机占用、跨项目启动、切换、停止与异步收尾。新增指定用例纳入[全量基线](../../../scripts/verify_baseline.py)和[三档原生验证](../../../scripts/verify_qt_migration.py)。 |

项目原有的电源与串口名称归一化、网卡别名和 GUID、Windows 主机互斥及未知任务保护继续由原服务处理。配置、运行目录、会话和停止事件仍由各项目持有。项目设置、帧、延时、轮次、测试结果判据、GUI 布局均沿用。操作入口见[使用手册](../../../line_check_assistant_README.md)。

## 软件验证

- 首次标准构建在完整基线终止。3,247 项中能力清单一致性测试失败，同一差异也触发能力覆盖门禁。逐项比较当前源码和清单后，差异仅为 Tk 项目入口同一文件的 SHA256，39 项动作表达式与回调完全一致。按项目规则更新清单，再次运行覆盖检查和 3 项能力专项通过。[首次构建输出](build-initial.txt) · [专项复验](coverage-recheck.txt)
- 第二次标准构建通过了能力清单检查，旧 Tk 多通道提交专项测得最大心跳间隔 422 毫秒，超过其 200 毫秒门槛，完整基线终止。保持原测试、阈值和实现，使用受控测试入口单独连续运行三次均通过。单次超时的确切原因仍未定位。[第二次构建输出](build-heartbeat.txt) · [第一次专项](heartbeat-1.txt) · [第二次专项](heartbeat-2.txt) · [第三次专项](heartbeat-3.txt)

- 自动开关机准备时无需 WiFi，而落盘快照启用 WiFi 时，原编排器调用次数为零，任务记为失败并释放资源。[快照变化专项](snapshot-wifi.txt)

- 项目 A 占用主机 WiFi，B 的默认方案关闭 WiFi，选中方案开启 WiFi。修正前 B 的启动请求被错误放行。修正后 B 在执行器启动前收到占用错误；释放 A 的资源后 B 正常取得无线租约。该回归同时检查 Tk 入口生成的资源集合。[修正前失败](wifi-before.txt) · [修正后通过](wifi-after.txt)
- Qt 工作区、项目执行器和 Tk 项目入口专项共 68 项通过。用模拟编排器启动两个不同电源的项目，A 停止并关闭后，B 仍运行且只保留 B 的租约。每个项目使用自己的运行快照。[专项结果](focused.txt)
- Windows 私有桌面上的真实 Qt 窗口可分别开始 A 和 B，在总览看到两项运行，切回 A 请求停止并返回 B 查看完成结果。[原生操作专项](native-focused.txt)
- 另用 Qt 工作区命令队列发起两次本机确认，实际启动两个原 Windows 子进程，分别运行 CH3、CH9。两个子进程使用不同虚拟电源、进程 ID 和各自项目的运行目录。用 B 请求停止 A 的任务被拒绝。从 A 正确停止后，A 只写了初始化断电及首轮通电，B 保有自身租约，按断、通、断、通写完两轮。两个串口均关闭，所有租约释放，意外外部 I/O 为零。[逐帧证据](dual-children.json) · [执行输出](dual-children.txt) · [复验脚本](check_parallel_workers.py)

首次独立子进程探针遗漏了 Qt 主窗口定时提交的刷新请求，读到的页面快照停在“停止中”。按原控制器行为周期性请求进度快照后复跑通过。[首次探针记录](dual-before-timer.txt)

另外让两个项目各自占用一套 16 通道模拟电源和独立的网卡、串口，两套电源都用 CH1–CH16。两个原 Windows 子进程同时工作，两轮后均由原服务报告完成。每个项目写入 64 帧，共 128 帧。逐个通道核对断、通、断、通的实际字节及 1、2、1 秒的原配置等待调用；未发现缺失、重复和跨项目帧。另一次单独停止 A 的回归也通过。[双 16 通道逐帧及等待记录](dual-16.json) · [运行输出](dual-16.txt) · [独立停止复跑](dual-stop-repeat.json)

## 验收边界

另在独立 Windows 进程运行两项已准入的模拟挂测，在两项均运行时让测试进程直接退出。重新启动工作区并打开原临时项目，两项实时状态均为“结果未知”，各自保有原资源保护及 Job 身份，活动任务数为零。持久任务历史保留退出前最后记录的“运行中”。两个项目重新准备均被拒绝。用模拟现场证据单独核实 A 的失败后，A 可重新准备，取消后没有调用执行器；B 仍为未知并保持保护。新进程共调用模拟执行器零次。该试验覆盖 Windows 进程退出后的软件恢复，现场 DUT 的实际状态仍需人工核实。[异常退出与重开证据](process-interruption.json) · [复验脚本](check_process_interruption.py)

三档 Windows 私有桌面分别以 100%、125%、150% 运行 95 项原生测试，合计 285 次，指定用例无遗漏，隔离守卫无违规。每档均实测两个项目同时显示运行中，并可分别切换、停止。[原生测试结果](native/results.json) · [100% 总览](native/scale-1/parallel-power-projects.png) · [125% 总览](native/scale-1.25/parallel-power-projects.png) · [150% 总览](native/scale-1.5/parallel-power-projects.png)

实际设备、物理电源时序、实体无线接口争用、目标 Windows 电脑及长时间并行仍待现场验证。持续开机全业务老化依赖独立检测执行器。新旧界面使用同一个原开关机引擎，前一版本的[逐帧修复候选包](../power_command_receipts/REPORT.md)可用于对照与回退。

## 本机复验方法

从主源码目录运行，下列命令使用模拟电源及临时项目，原进程退出试验只终止探针自行创建的进程。备份兼容性试验读取 [Phase 0 收据](../backup_receipt.json)所指的本机归档。

```powershell
$qtPython = Join-Path $env:LOCALAPPDATA 'LineCheckAssistant/qt-build-py39/Scripts/python.exe'
$checks = 'validation/pyside6_migration_20261118'
& $qtPython -X utf8 "$checks/parallel_power/check_parallel_workers.py" --full-banks --output "$env:TEMP/dutpilot-dual-16.json"
& $qtPython -X utf8 "$checks/parallel_power/check_parallel_workers.py" --output "$env:TEMP/dutpilot-dual-stop.json"
& $qtPython -X utf8 "$checks/parallel_power/check_process_interruption.py" --output "$env:TEMP/dutpilot-process-reopen.json"
& $qtPython -X utf8 "$checks/archived_projects/check_archived_projects.py" --output "$env:TEMP/dutpilot-project-compatibility.json"
```

## 标准 Windows 候选包

3,247 项完整基线通过，249 项指定用例全部执行。三档 Windows 原生共 285 次通过。成品入口和 331 个项目模块与源码一致，92 个受保护业务文件保留原哈希，另外 5 个与负责人确认的修正快照一致。目录与 ZIP 的 245 份文件已比对，验包逐一核对 39 个 PySide6/shiboken6 原生文件导入的 Qt6 DLL。ZIP 共 55,356,337 字节，SHA256 为 `f8a73f246ce2c44f2318e6b368b3c53dfcebcb7385be918592abbde0f4fb43b3`。

[Windows 便携 ZIP](../../../dist/qt-20261121-141002-8f2876a1/DUTPilot_portable.zip) · [SHA256](../../../dist/qt-20261121-141002-8f2876a1/DUTPilot_portable.zip.sha256.txt) · [构建与全量回归](build.txt) · [成品源码比对](packaged-sources.json) · [验包明细](../../../dist/qt-20261121-141002-8f2876a1/PACKAGING_REPORT.json)

本机仅静态核对新 EXE。目标机独立启动、实体多屏、真实 DUT 及长期挂测待现场验证。

验包完成后核对了 Git 状态和报告引用。三档共生成 399 张过程截图，其中 396 张已移入回收站，保留本报告链接的三张并行总览。三档各 1,851 个受管理窗口没有隔离违规。
