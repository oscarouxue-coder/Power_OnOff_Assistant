# Qt 总览系统状态

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

2026-11-20，DUTPilot V1.3.0 第一阶段，原迁移计划 Phase 7。

## 审计与改动

| 展示项 | 来源和边界 |
| --- | --- |
| 界面与工作区 | 现有 100 ms Qt 更新回调的采样间隔，以及后台工作区命令循环的最近响应时间。界面回调恢复后可观察此前的间隔峰值。 |
| 消息积压 | 当前工作区命令队列的待取数、既有容量、最近采样段移交给界面的日志批量峰值，以及从有界移交缓冲淘汰的累计条数。原工作区文件继续沿原路径追加。 |
| 工作区日志写入 | 最近一次 `workspace.log` 追加写入和关闭文件的结果及本次会话的失败累计。写入失败保留原主日志报错。指标范围为工作区文件追加。串口原始文件及磁盘持久性另行验证。 |
| 测试任务 | 已打开项目快照中原有的运行或恢复数、需要关注数，以及此工作区上次收到带任务 ID 的日志时间。持续开机检测当前没有独立运行时来源，业务心跳和最近探测时间继续待接入。 |
| 工作区资源占用 | 只读采样原租约。串口和程控电源按归一资源键汇总，网卡别名和 GUID 去重，其他项按占用键计数。锁忙保留上次样本，超过三秒标记采样滞后。 |
| 串口 / 网卡枚举 | 从已有手动刷新返回结果读取完成时间与失败状态。启动后尚未执行该刷新时显示暂无记录。 |

工作区状态与项目异常分别呈现。界面复用原主线程轮询，工作区使用现有后台循环采样。原任务、检测周期、判据、上下电和资源准入服务沿原路径执行。面板宽屏展开，窄屏初始收起，展开后有限高度内可纵向滚动，保留用户拖动日志分栏后的选择。

## 文件

- 显示数据和观测采样见 `src/models/workbench_presentation.py`、`src/services/qt_workspace_adapter.py`。
- 总览、界面更新、布局与配色见 `src/ui/qt/system_health_panel.py`、`dashboard.py`、`main_window.py`、`workspace_controller.py`、`theme.py`。
- 运行回归与验证入口见 `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`。
- 人工只读入口覆盖见 `scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json` 和仓库根 `CAPABILITY_COVERAGE.md`。同步阶段计划、进度表、项目状态、验收基线、开发记录和操作员说明。

## 截图与差异

- 改造前 150% 总览
- 改造后 150% 常规窗口 · 小窗口默认收起 · 小窗口展开

参考图中的系统卡片按控制服务、数据库和网络列出健康状态。现版使用工作区实际可观测的数据。测试截图使用临时工作区、模拟枚举与故障注入。窄窗口手动展开时，项目卡片和状态详情靠纵向滚动查看，实时日志标题也会受工具条宽度限制。长挂中响应、CPU、内存、日志写入与外设收尾仍需现场验证。

## 验证

在主源码目录使用各自的锁定环境执行。

```powershell
python scripts/run_tests.py test_qt_workspace_adapter test_qt_archived_logs test_qt_log_export test_qt_log_history test_qt_execution_adapter test_qt_serial_terminal test_qt_migration_contract -v
python scripts/run_tests.py test_workbench_status test_verify_baseline test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_system_health_release_check
```

- `scripts/run_tests.py` 组合回归通过 89 项，涵盖工作区、归档、导出、任务历史、执行适配器、串口和迁移契约。510 条突发记录完整写入，本轮超过显示上限的 10 条有累计记录。模拟追加失败及恢复、网卡别名去重、锁占用期间工作区响应以及枚举失败和恢复均通过。相关回归
- 原工作台状态、编译/测试门禁及业务覆盖 32 项通过。341 个文件编译、331 个源码项登记、协议不变量与原业务保全通过。门禁回归 · 源码保全
- 三档 Windows 私有桌面布局专项通过。依据实际字号与系统状态高度重新分配日志分栏空间，常规窗口可见完整单项目卡片及全部系统状态。小窗口展开后可纵向查看全部字段。100% · 125% · 150%
- 补足卡片完整可见断言后的首轮整套复验中，100% 与 150% 通过。125% 的系统状态用例通过，既有原生窗口映射用例报错，随后整套超过 210 秒上限。同一源码最终复验通过后，已清理这轮的过程截图、文本和结果清单。
- 同一源码最终串行复跑退出 0。100%、125%、150% 各通过 62 项，共 186 项。每档 Windows 私有桌面管理 1,151 个 Qt 顶层窗口，隔离违规为零。各档输出含常规总览及窄窗收起和展开截图。最终原生复验

本轮完成源码专项验证。完整基线和既有 Windows 验证包见[目录包报告](QT_DIRECTORY_BUILD_REPORT.md)。AI 诊断、远程平台及其余待迁移入口按原阶段推进。真实设备、目标电脑和长期挂测仍待验收。
