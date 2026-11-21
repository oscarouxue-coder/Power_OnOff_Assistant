# Phase 5｜Qt 全包升级手动重启

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

后续已补采 100%、125%、150% Windows 原生模拟用例及画面。真实样机验收待做。三档复验结果 · 150% 准备页 · 150% 手动确认

原 Tk 窗口会在列出固件、实际样机和传输参数后，要求操作员确认样机已手动重启。三种原全包引擎接收空程控电源口，并在各自分支中处理这一状态。

现在 Qt 全包预检在无程控电源时显示「手动重启」，保留原网卡、源地址、样机串口、固件 SHA256 和恢复出厂检查。独立确认框默认取消，操作员确认「已重启，继续升级」后，再核对项目、网卡和固件，沿用原升级 Job 与三种分派。手动确认可等待操作员完成重启，取消、关闭窗口或配置变化会使确认失效。共用的通用能力保留无电源时的拒绝，原能力参数仍无人工重启标志。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 本机预检及任务入口 | `src/services/qt_firmware_upgrade.py`、`firmware_upgrade_validation_service.py`、`capability_service.py` |
| Qt 界面 | `src/ui/qt/firmware_upgrade_dialog.py`、`workspace_controller.py` |
| 验证与覆盖 | `tests/test_qt_firmware_upgrade.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`、根目录 `CAPABILITY_COVERAGE.md`、本目录 `verify_firmware_qt.py`、`verify_phase3.py` |
| 文档 | 根目录 `README.md`、`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`.claude/plans/pyside6-migration.md`、主源码目录 `line_check_assistant_README.md`、本目录 `NEXT_FIRMWARE_AUDIT.md`、`MIGRATION_PROGRESS.md` 及本报告 |

## 窗口对照

参考图展示主工作台的概览与详情，样机升级仍在项目详情打开的独立窗口中。手动重启沿用同一项目表单，确认使用可滚动的只读目标清单和默认取消按钮。上一阶段 Qt 全包升级页

100%、125%、150% 原生运行均在创建窗口前因输入桌面隔离校验中止，Windows `OpenInputDesktop` 返回错误 5。改造后窗口和确认图待补采，原生用例已加入两张采图。三档原生结果

## 验证及待办

- `python validation/pyside6_migration_20261118/verify_firmware_qt.py --manual-restart` 运行 232 项相关回归，230 项通过，2 项默认跳过的本机模拟网关浏览器用例已单独启用并通过。用例覆盖三种全包模式、空电源口、原通道与资源、取消、配置及固件失效、安全停止，以及标准接口和远程入口拒绝。相关回归 本机浏览器证据
- 321 文件编译、311 源文件登记、GUI 与能力覆盖、协议不变量通过。源文件对照逐项核对两处授权桥接增量，原 Tk、升级引擎、网卡、串口、电源及引擎时间参数未改。源码检查
- 待核验三档原生、真实样机重启后进入 Boot 的时点及实机完整流程。下一阶段继续原三项全流程的 Qt 操作入口与安全停止联动。本轮未重跑完整基线、连接真实设备或打包。
