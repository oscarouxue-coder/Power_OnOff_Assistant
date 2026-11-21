# Phase 3｜Qt 单次自动上/下电

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

## 审计与改动

旧版项目窗口显示已勾选通道，允许选择本次电源串口和上电或下电。确认后调用 `turn_on_selected_channels` 或 `turn_off_selected_channels`，按原顺序向指定通道发指令。相邻指令间隔 1 秒。空电源口由操作员确认手动重启。循环挂测有独立入口。

Qt 项目详情的「自动上/下电」现可打开单次操作窗口。默认显示已保存的电源口，支持常用分组及所有检测到的串口。本次选口仅对确认的操作生效。最终确认默认选「否」，绑定项目、配置版本、通道、端口和方向，并在提交时复核。点击取消、配置变化、端口被占用时均不会提交电源命令。

新增的 `power.qt_single` 仅供本机 Qt 控制面调用。它使用原 Job、串口及网卡资源保护，沿用原单次电源服务。项目配置端口和本次选择的端口不同时，两者都纳入占用检查。空端口只记人工重启确认。执行中的短序列由原服务收尾，切页不取消，关闭等待实际收尾。部分写入失败显示结果未知，保留核实前的资源保护。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 服务 | `src/services/qt_single_power.py`、`qt_execution_adapter.py`、`qt_workspace_adapter.py` |
| 界面 | `src/ui/qt/single_power_dialog.py`、`project_detail.py`、`workspace_controller.py` |
| 验证 | `tests/test_qt_execution_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_baseline.py`、`verify_qt_migration.py`、`verify_capability_coverage.py`、`capability_gui_actions.json` |
| 交接 | `PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`CAPABILITY_COVERAGE.md`、`ACCEPTANCE_BASELINE.md`、`.claude/plans/pyside6-migration.md`、`line_check_assistant_README.md`、本报告及迁移进度表 |

## 截图与参考图

改造前的项目详情显示原开关机入口和通道信息。沿用参考稿的项目、通道和状态层级，使用独立的短表单处理选口及方向，最终确认单独弹出。详情页的任务摘要显示本次操作结果。

首次 100% 截图中，实际端口显示在结果和日志，右侧先显示项目配置端口。修订后把「本次电源操作」移至快照顶部。125% 修订后截图可同时查看本次 COM106 和项目配置 COM102。

150% 实际运行截图包含选口与方向、人工重启选项和项目详情结果。此次运行的是单次控制，主体显示原电源服务返回结果和详细日志。长配置面板可纵向滚动。

## 回归与待验收

- `python scripts/run_tests.py test_qt_execution_adapter test_qt_workspace_adapter test_power_supply test_app.CurrentChannelSelectionTests -v` 通过 284 项，覆盖相关执行、工作区、旧电源服务和旧通道选择。相关回归日志
- 原服务与模拟串口验证了上下电各自的原帧、CH01/CH07 顺序、1 秒间隔和串口关闭，并覆盖人工确认、配置漂移、直接调用拦截、他项目占用和部分写入失败后的保护。
- `python scripts/verify_qt_migration.py --output validation/pyside6_migration_20261118/qt_single_power_verified` 每档通过 57 项，125% 和 150% 使用修订后的结果布局。100% 修订后通过同一私有桌面运行器重跑全套 57 项。三档最终证据共 171 项，隔离违规为零。完整套件记录 · 100% 修订后复验 · 100% 修订后截图
- 编译、覆盖、协议与源码保全通过，335 份文件编译、325 份源码登记。未重跑完整基线。

真实电源口和样机的多通道时序、异常断连、资源释放及人工重启流程待现场验收。本轮使用模拟串口，未构建 EXE。原挂测批次的现场、长期和部署验收继续在迁移进度表跟踪。
