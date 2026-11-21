# Qt 串口与 DUT 窗口状态

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 5 的窗口状态兼容。

## 审计与迁移

Tk 串口终端从项目 `ui/serial.json` 读取窗口大小、位置和日志目录。Tk DUT 配置从 `ui/dut.json` 读取窗口宽高，并在同一文件保存状态区高度。旧 Qt 窗口已沿用串口日志目录，打开时仍使用各自默认尺寸。[改造前串口报告](SERIAL_REPORT.md) · [改造前 DUT 报告](DUT_TELNET_REPORT.md)

Qt 串口终端优先恢复项目的 Qt 位置与尺寸，首次迁移时读取原 Tk 几何字符串。Qt 位置写入 `qt_geometry`，原 `geometry` 和 `log_dir` 可由 Tk 继续使用。DUT 配置共享原 `window_size`，合并保存时保留旧状态区高度和其它字段。偏好按项目独立，使用已有项目后台线程读取和原子写入。

若历史位置已落在屏幕外，窗口在主窗口所在屏幕的可用区域重新定位。较大历史尺寸会按当前可用区域和窗口最小尺寸收敛。缺少有效历史状态时，界面沿用原默认打开行为。正常关闭子窗口、关闭项目及退出工作区均采集尺寸。串口正常关闭仍等待原收尾。窗口状态写入失败记录警告，原关闭流程继续。Qt 只保存窗口偏好，样机连接、监控启停、凭据及测试参数沿用原逻辑。

复查发现旧 Qt 串口关闭在写日志目录偏好失败时，会跳出关闭流程并保留打开的串口。关闭分支现在记录偏好保存失败后继续释放自己的会话，并等待原日志落盘。主动更换日志目录时仍要求保存成功，失败时保留原目录。

参考总览图未给出这两个独立窗口。本轮沿用原 Qt 控件。150% 原生复验使用模拟通道，核对恢复后的串口标签、目录、输入区及 DUT 页签、目标和底部操作。

## 修改文件

- `src/models/qt_window_placement.py`、`src/services/qt_window_state.py`、`src/services/qt_workspace_adapter.py`、`src/services/qt_serial_terminal.py`
- `src/ui/qt/window_placement.py`、`src/ui/qt/workspace_controller.py`
- `tests/test_qt_workspace_adapter.py`、`tests/test_qt_serial_terminal.py`、`tests/qt_workbench_probe.py`
- `scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`
- 能力覆盖、操作员说明、迁移计划和进度、工程状态、开发日志、验收基线

## 复验命令

```powershell
python scripts/run_tests.py test_serial_terminal test_qt_serial_terminal test_qt_dut_configuration test_qt_workspace_adapter test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_window_placement_verified
```

## 验证结果

- 125 项相关回归通过，涵盖旧状态读取、项目隔离、合并写入、写入失败仍关闭，以及原串口和 DUT 流程。新增模拟串口用例验证偏好写入失败后全部监控释放，而原目录更换失败继续保留当前目录。
- 368 份文件编译、358 份源码登记、能力覆盖、GUI 守卫和协议检查通过。原 Tk 应用、核心设备服务及本机配置保全核对通过。
- 150% 原生专项验证 Tk 状态恢复、串口重开、DUT 随项目关闭后记录尺寸、屏幕外位置回退，以及工作区退出时保存独立项目状态。测试拦截实际串口打开。
- 首轮 150% 套件发现无历史状态时自动收敛影响了五个 DUT 默认布局用例。恢复逻辑改为只处理有效保存状态，沿用原默认行为。用相同原生隔离入口和原断言整档复跑，150% 已通过 75 项。
- 最终源码在 Windows 私有桌面 100%、125%、150% 各通过 75 项，共 225 项。每档管理 1,332 个窗口，隔离违规为零。100% 与 125% 在最后一次修正后各整档复跑。三档截图像素尺寸与复验中的逻辑宽高一致，目视核对串口标签、日志目录、DUT 目标和底部按钮。
- 对应验证通过后，清理本轮 759 份截图、测试日志、结果清单和首次失败证据，共约 36.5 MiB，保留本报告。

## 待验收范围

本轮覆盖串口终端的尺寸与位置，以及 DUT 配置外窗宽高。DUT 单页状态区高度键保留供原 Tk 使用。实际 Windows 系统 DPI 动态切换、实体多屏和目标机旧项目待验收。本轮为源码和模拟验证，最终完整基线和重新打包待后续验收。
