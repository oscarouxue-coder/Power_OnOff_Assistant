# Phase 3、6｜Qt 主工具栏刷新串口和网卡

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

## 审计与边界

旧 Tk 工作台的组合按钮先调用串口枚举，再调用网卡刷新，同时把网卡身份交给工作区资源登记。Qt 工具栏原有两个禁用占位动作。通道编辑器之前虽能后台读取，仍与项目命令共用工作线程。一项慢枚举可能推迟另一项目的安全停止。

主工具栏新增可用的「刷新串口/网卡」，与通道配置使用同一次本机只读扫描。独立枚举线程先读串口、再读网卡，单项失败仍继续处理另一项。成功的空清单会更新候选，失败的来源继续使用最后一次成功清单。所有打开的通道窗口更新候选，各自的分组模式、选中资源和未保存输入保留。

枚举线程只持有一次请求的结果邮箱。项目线程继续处理项目命令、任务停止和原收尾。重复请求合并，工作区退出可丢弃旧邮箱。只有工作区空闲、没有租约且准入信息未在期间更新时，才将本次身份写入原工作区资源登记。活动任务继续沿用原执行时复核的身份和资源租约。清单更新不会打开串口、改网卡配置或启动任务。

项目数和活动任务数移到状态栏右侧，刷新进度及错误显示在左侧，避免任务状态更新覆盖反馈。执行日志记录只读刷新开始、结果、失败与跳过身份登记。

隔离原生截图显示切换项目的一帧中，已移出布局、等待回收的旧通道卡片和配置摘要叠在新内容上。移除时立即隐藏旧控件，再由 Qt 回收。矩阵按按钮实际内容宽度排布，配置摘要重建时通知滚动区重新计算空间。原生探针在切换当下检查旧控件已不可见，并检查新卡片和字段的内容尺寸。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 服务 | `src/services/qt_host_inventory.py`、`qt_workspace_adapter.py`、`qt_channel_configuration.py`、`qt_onu_query.py` |
| Qt 控件与绑定 | `src/ui/qt/main_window.py`、`workspace_controller.py`、`channel_configuration_dialog.py`、`project_detail.py` |
| 测试与门禁 | `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`verify_baseline.py`、`verify_capability_coverage.py`、`capability_gui_actions.json` |
| 状态和操作说明 | `line_check_assistant_README.md`、根目录 `PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`ACCEPTANCE_BASELINE.md`、`CAPABILITY_COVERAGE.md`、`.claude/plans/pyside6-migration.md`、本目录进度和阶段报告 |

## 前后截图与参考图差异

- 改前主工具栏 · 检测到旧控件重叠的中间截图 · 最终主工具栏及刷新状态 · 未保存草稿中的刷新结果
- 沿用目标稿的顶部全局操作与底部状态位置。工具栏沿用已确认的合并按钮名称。当前状态栏显示真实项目与活动任务数，并在操作后反馈。设备管理、全局设置及参考稿的资源占用总览仍为后续模块。截图中的运行任务和异常使用测试夹具。

## 验证与剩余工作

- `python scripts/run_tests.py test_qt_workspace_adapter test_qt_channel_configuration test_qt_execution_adapter test_resource_options test_capability_coverage test_qt_onu_query -v` 通过 104 项。覆盖并发请求合并、串口先于网卡、枚举时其它项目命令继续、活动租约保留、较旧清单不覆盖新身份、退出丢弃迟到结果，以及原候选模式、配置保存和 ONU 收尾。相关回归日志
- 源码保全、协议与覆盖通过，编译 329 份文件，登记 319 份源码。
- 本机 Windows 在临时空工作区通过同一后台命令识别 70 个网卡和 55 个串口，登记 70 个网卡名称，串口打开和活动租约均为 0。只读验收记录
- 刷新与截图专项通过。125% 的整套复验另外发现 ONU 停止用例在界面尚未收到清理完成时就尝试关闭。现从同一次任务快照计算活动状态和可停止状态，原生用例等待界面显示收尾完成再关闭。原 ONU 查询和停止服务仍走原路径。中间复验记录
- 最终用 `python scripts/verify_qt_migration.py --output validation/pyside6_migration_20261118/qt_host_inventory_accepted` 复验。100%、125%、150% 各执行 54 项并通过，共 162 项，隔离违规为零。最终原生结果

本轮接入尚未由负责人验收的 Qt 工具栏和窗口刷新，旧 Tk 入口仍可使用。本轮未重跑完整基线、执行物理改名、连接样机或构建 EXE。现场任务停止时序、系统 DPI、多显示器及长期稳定性待验收。
