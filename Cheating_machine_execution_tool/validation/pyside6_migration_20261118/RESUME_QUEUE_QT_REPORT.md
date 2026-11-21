# Phase 3｜Qt 批次后失败续跑排队

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

[原续跑阶段](RESUME_QT_REPORT.md)已接入原批次运行中和结束后的续跑。批次结束后，旧入口允许对多个不同的失败通道分别确认，由原会话串行处理。原 Qt 入口在当前续跑完成前挡住了这一操作。

现在可通过原右键菜单逐条确认不同通道。运行概览显示正在续跑的通道和等待顺序。同一通道的重复请求会被拦截。前一条完全释放资源后，工作区复核下一条的项目、批次、轮次、配置和网卡，再通过原 Job 获取本通道的资源。已知失败可以继续处理等候项，结果未知时会取消等候项。

停止确认列出将取消的等待通道。已有任务沿原停止路径收尾。若刷新前显示的是同一串行批次中的上一条任务，停止仍落到当前正在处理的通道。关闭工作区会取消待执行请求。队列只保留在当前进程。原上下电、线程、版本预检、轮次和批次结论继续由原服务处理。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| Qt 控制与数据 | `src/services/qt_power_resume.py`、`qt_execution_adapter.py`、`qt_workspace_adapter.py`、`src/models/workbench_presentation.py`、`src/ui/qt/workspace_controller.py` |
| 测试与覆盖 | `tests/qt_execution_fakes.py`、`test_qt_execution_adapter.py`、`qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`verify_capability_coverage.py`、`capability_gui_actions.json`、本目录 `verify_resume_qt.py` |
| 文档 | 根目录 `DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`CAPABILITY_COVERAGE.md`、`.claude/plans/pyside6-migration.md`、主源码 `line_check_assistant_README.md`、本目录 `MIGRATION_PROGRESS.md`、`NEXT_RESUME_AUDIT.md`、`RESUME_QT_REPORT.md` 和本报告 |

## 窗口对照

等待顺序放在原进度区域，右键操作与停止按钮沿用旧位置。参考图未展示续跑排队状态，当前版本依旧采用条形进度和独立的通道矩阵、日志。下列画面均由模拟项目生成。

- 改造前详情
- 排队中
- 安全停止后
- 150% 缩放下的等待与运行状态

## 验证与待验收

运行 `python validation/pyside6_migration_20261118/verify_resume_qt.py --queue`。模拟回归覆盖 CH07 → CH11 → CH09 的确认顺序、已知失败后继续、结果未知时清队、重复拒绝、逐条独占、续跑切换期间阻止普通启动、旧任务按钮发出的停止、配置及网卡变化拦截。关闭请求在实际收尾之前发出时，即使还有一次工作区刷新也不会开始等候项。另注入「刷新仍读到运行中，后台已完全收尾」场景，检查等待项保留到下一次刷新读到终态。原生新增用例核对等待状态、已确认通道不可重复提交、确认框列出将取消的通道，以及 CH09 未实际执行。

- 191 项相关回归、327 份文件编译、317 份源码登记、能力覆盖、协议和原业务保全检查通过。
- Windows 原生 Qt 在 100%、125%、150% 缩放下各通过 52 项，共 156 项，隔离违规为 0。

阶段结果 · 源码和协议 · 三档原生结果

真实设备的上下电、串口、版本预检和工况仍待负责人验收。本轮沿用 Qt 独立源码入口和旧 Tk 默认入口，未连接真实硬件、重跑完整基线或打包。
