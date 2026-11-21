# Phase 5｜Qt 全包升级日志与逐台状态

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

## 审计和实现

原全包升级引擎已经回调已打开的串口会话、原日志路径及逐台开始和完成事件。上一版 Qt 只在结束后显示结果，分派时也未接收会话回调，因此缺少升级期间的日志和状态。

- 确认并接纳任务后，Qt 为本批建立只读订阅。按原确认、项目和 VLAN 隔离。切换项目、迟到回调和过期批次不能串用日志。
- 原串口就绪后自动打开 Qt 窗口，按实际 VLAN/COM 分页。屏幕有界缓冲，过滤原事件标记为敏感的内容，保留原日志落盘路径及采集语义。窗口可提前关闭，升级继续。原批次结束后收起自动窗口，已有手动终端保留。
- 全包升级逐台显示原回调状态。页面升级使用原引擎提供的完成回调。最终结论仍来自原任务结果。原升级引擎持有并释放串口和控制权，沿用已存在的任务轮询和安全停止。

## 修改范围

| 范围 | 文件 |
| --- | --- |
| 原回调和只读订阅 | `src/services/qt_firmware_observation.py`、`src/services/qt_firmware_upgrade.py` |
| 工作区接口 | `src/services/qt_execution_adapter.py`、`src/services/qt_workspace_adapter.py`、`src/models/workbench_presentation.py` |
| 窗口及生命周期 | `src/ui/qt/firmware_log_dialog.py`、`src/ui/qt/workspace_controller.py` |
| 回归 | `tests/test_qt_firmware_upgrade.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、本目录 `verify_firmware_qt.py` |
| 编译与能力登记 | `scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`、仓库根 `CAPABILITY_COVERAGE.md` |
| 项目记录 | `README.md`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`、`.claude/plans/pyside6-migration.md`、本目录 `MIGRATION_PROGRESS.md`、`NEXT_FIRMWARE_AUDIT.md`、`NEXT_PARAMETER_AUDIT.md` |

## 原生截图

| 观察内容 | 改造前 | 改造后 |
| --- | --- | --- |
| 逐台状态 | 原 Qt 全包页 | 全包任务运行中 |
| 串口联动 | 原 Qt 分派器未订阅全包串口 | 100% 只读日志、150% 只读日志 |

参考设计将运行摘要放在项目详情主区。本轮升级状态仍位于现有独立升级窗口。自动只读日志使用独立窗口，保留同屏手动终端及升级控制。截图使用隔离工程和模拟设备，长路径在 150% 缩放下可以换行。

## 实际回归与剩余范围

- 相关回归运行 189 项，187 项通过，2 项本机浏览器用例按默认配置跳过。随后显式启用这 2 项并通过，范围限本机模拟网关。浏览器测试测试覆盖原会话、日志文件路径、敏感标记过滤、窗口关闭后原任务继续、晚到回调和批次隔离。测试输出
- Windows 私有桌面在 100%、125%、150% 缩放下各通过 38 项，共 114 项。每档记录 970 个受管窗口，隔离违规 0。原生用例经真实 Qt 工作区操作有程控电源的 Tftp Put 模拟任务，核对自动日志、逐台更新、退出订阅及手动终端保留。三档证据
- 310 个文件编译、300 个源文件编译清单、能力覆盖与协议保全通过。阶段备份中的 162 个原 core/service 文件、38 个旧入口配套 Python 文件、7 个本地配置及原 Tk app 内容一致。源码检查
- 待迁移无程控电源时的人工重启、旧全流程联动及后续独立业务模块。真实设备、多台真实串口压力与长时间挂测仍待现场验证。本轮未重跑完整基线，未打包。
