# Phase 3｜Qt 失败轮次续跑

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

[原代码审计](NEXT_RESUME_AUDIT.md)

运行概览的通道矩阵和列表支持右键「重新开始（从失败轮次继续）」，也可从有资格的通道快照进入。确认框列出项目、唯一通道、完成轮数与下一轮，默认取消。Qt 使用原会话判定资格，并绑定本次运行、阶段、配置、网卡和操作员会话。原批次在确认期间进入下一阶段时需重新确认。

正在运行的原批次使用原会话和设备子进程控制队列。若已提交的续跑恰逢原进程退出，Qt 原 Job 继续持有相关资源并等待原会话收尾。原批次彻底结束后，通过独立 `aging.resume` Job 取得单通道资源，继续使用原版本预检、`PowerTestResumeSession.submit`、失败轮次和停止路径。原任务结论保留，详情页同时显示续跑状态和原回调产生的轮次进度。旧 Tk 和通用能力沿用原入口。

本阶段批次结束后的 Qt 入口一次准入一个通道。后续已补齐多个失败通道等待。[排队阶段报告](RESUME_QUEUE_QT_REPORT.md)

## 修改文件

| 范围 | 文件 |
| --- | --- |
| Qt 后台与数据 | `src/services/qt_power_resume.py`、`qt_execution_adapter.py`、`capability_device_services.py`、`src/models/workbench_presentation.py` |
| 界面 | `src/ui/qt/project_detail.py`、`workspace_controller.py` |
| 回归与覆盖 | `tests/qt_execution_fakes.py`、`test_qt_execution_adapter.py`、`qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`verify_baseline.py`、`verify_capability_coverage.py`、`capability_gui_actions.json`、本目录 `verify_resume_qt.py`、`verify_phase3.py` |
| 交接与说明 | 根目录 `PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`ACCEPTANCE_BASELINE.md`、`CAPABILITY_COVERAGE.md`、`README.md`、`.claude/plans/pyside6-migration.md`、主源码 `line_check_assistant_README.md`、本目录 `MIGRATION_PROGRESS.md`、`NEXT_RESUME_AUDIT.md` 和本报告 |

## 窗口对照

右键菜单沿用 Windows Qt 样式，常驻按钮数保持原样。沿用详情页现有条形进度、矩阵／列表与配置栏，续跑反馈放在进度卡的小字区域。参考图使用环形指标和更紧凑的整体密度，详情页的视觉差距仍在。截图来自模拟设备项目。

首轮原生截图发现进度从个位数升到 100% 时，标签宽度未跟上文本变化。按当前字体的实际宽度分配空间，并在原用例增加完整文本宽度检查。发现裁切时的截图

- 改造前项目详情
- 右键续跑菜单
- 续跑完成后的项目详情
- 150% 缩放详情

## 复验结果

- 185 项相关测试通过，包含原续跑及初始化、原编排、项目任务保护和 Qt 控制面。模拟覆盖原队列只提交一次、退出竞争后单通道回退、原资源直至停止收尾、未改变原批次结论、采集后续回调，以及拒绝阶段／配置／网卡变化和外部来源。
- 327 份编译、317 份源码登记、协议和能力覆盖检查通过。源码保全核对旧 Tk、原续跑、电源业务和受检配置；共享编排适配只包含 Qt 使用的生命周期接点及之前已审查的串口预启动接点。
- 原生测试从矩阵和列表进入续跑，复核取消、目标、轮次、按钮可用状态、原始结论和恢复进度。包含隔离 Windows 截图。
- 修复进度标签宽度后，100%、125%、150% 原生 Qt 各通过 51 项，共 153 项，隔离违规为 0。三档均记录最终截图。
- `python validation/pyside6_migration_20261118/verify_resume_qt.py`。阶段结果 · 源码保全及协议 · 原生复验

真实设备上的续跑、串口和电源时序、版本预检、WiFi 及长期场景待负责人验收。独立 Qt 源码和旧 Tk 入口保留。本轮未操作真实硬件、重跑完整基线或打包。
