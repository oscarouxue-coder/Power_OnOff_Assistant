# Phase 5｜Qt 写参串口日志

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

原写参服务为串口回退提供已取得控制权的会话和原日志路径。上一版 Qt 能运行这条业务路径，界面只显示任务日志和逐台结果。本轮将原会话回调接入升级和写参共用的 Qt 只读面板。

- 实际走串口时按 VLAN 和 COM 打开只读窗口。每个通道显示原会话的日志路径，显示有限流和缓冲上限。原事件已标记为敏感的内容不进入新增的只读显示。
- 窗口可提前关闭，原写参继续。停止请求发出后，工厂模式清理期间窗口仍可查看。原批次结束后退订并关闭自动窗口，用户打开的手动串口终端保留。
- Telnet 写参仍使用原文本日志。串口观察仅订阅数据，启动、写入、读回、清理、落盘及资源释放均由原服务负责。迟到回调按项目和批次校验，避免串入新任务。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 只读订阅和原任务接入 | `src/services/qt_serial_observation.py`、`qt_firmware_observation.py`、`qt_firmware_upgrade.py`、`qt_parameter_writer.py`、`capability_parameter_services.py` |
| 窗口和项目状态 | `src/models/workbench_presentation.py`、`src/services/qt_execution_adapter.py`、`qt_workspace_adapter.py`、`src/ui/qt/workspace_controller.py`、`serial_observation_dialog.py`（由原升级日志窗通用化） |
| 回归与能力登记 | `tests/test_qt_parameter_writer.py`、`tests/test_qt_firmware_upgrade.py`、`tests/qt_workbench_probe.py`、`scripts/verify_baseline.py`、`verify_qt_migration.py`、`verify_capability_coverage.py`、`capability_gui_actions.json`、`CAPABILITY_COVERAGE.md`、本目录 `verify_parameter_writer.py` |
| 项目记录 | `PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`ACCEPTANCE_BASELINE.md`、`README.md`、`line_check_assistant_README.md`、`.claude/plans/pyside6-migration.md`、本目录计划与报告 |

## 前后窗口

| 改造前 | 改造后 |
| --- | --- |
| Qt 写参独立窗口，串口输入无专用只读窗口 | 100% 只读串口日志、150% 只读串口日志 |

参考图在项目详情中展示运行日志。本轮保持写参和升级操作页的既有布局，新增的串口输出为独立只读窗口，能与项目工作区和手动终端同时存在。

## 验证与待完成范围

- 192 项相关测试通过。用原应用服务分流到模拟串口执行器，核对两个通道、实际日志路径、批次隔离、敏感事件过滤、原停止清理及只退订观察回调。回归输出
- Windows 原生在 100%、125% 和 150% 缩放下各通过 40 项，共 120 项。每档记录 977 个受管窗口、隔离违规 0。新增写参测试和既有全包升级测试三档均通过。原生证据
- 314 个文件编译、304 个源文件登记通过。共享写参能力层仅允许已审查的本机桥接变更，原执行服务和 Tk 源码对照通过。源码核验
- 旧全流程写参联动、真实设备、真实串口流量及长时间挂测仍待验证。本轮未重跑完整基线，未打包。
