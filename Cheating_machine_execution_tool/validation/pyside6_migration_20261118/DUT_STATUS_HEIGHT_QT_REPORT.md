# Qt DUT 配置各页状态区高度

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 5。

## 审计与迁移

原 Tk 窗口按项目在 `ui/dut.json` 的 `current_status_heights` 中记录六个页签的状态区行数。缺少记录时用 4 行，拖动范围为 2–16 行。旧 Qt 窗口虽有分隔条，但六页沿用当前高度，重开仅恢复[外窗宽高](WINDOW_PLACEMENT_QT_REPORT.md)。

Qt 现按当前字体的行高恢复 Telnet、WAN、2.4G WiFi、5G WiFi、语音和 TR069 各自的行数。拖动结束后合并保存。缩小窗口时，当前页的行数随可用空间收敛，顶部页签和底部查询、执行、停止、关闭按钮继续可用。长表单可以纵向滚动。关闭 DUT 窗口、项目或工作台时沿用原窗口偏好保存流程。

状态区和外窗偏好可独立写入。工作区线程按项目合并偏好，沿用原子写入，保留同文件的其它字段。Qt 继续使用原 DUT 业务服务与任务资源保护。窗口状态仅存布局偏好。

## 修改文件

- `src/models/qt_window_placement.py`、`src/services/qt_window_state.py`、`src/services/qt_workspace_adapter.py`
- `src/ui/qt/dut_configuration_dialog.py`、`src/ui/qt/workspace_controller.py`
- `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`
- `scripts/verify_qt_migration.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`
- 能力覆盖、操作员说明、迁移计划和进度、项目状态、开发记录与验收基线

## 复验命令

```powershell
python scripts/run_tests.py test_qt_dut_configuration test_qt_dut_wan test_qt_dut_wifi test_qt_dut_voice_tr069 test_qt_workspace_adapter test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_dut_status_verified
```

## 验证结果

- 96 项相关回归通过，覆盖旧数据读取、项目隔离、只写布局行数时不覆盖外窗、合并写入及写入失败处理。
- 编译 368 个文件、358 个源码登记项、能力覆盖、GUI 守卫、原协议及既有实现保全检查通过。
- 150% Windows 原生专项 2 项通过。首轮旧断言仍要求缩小窗口后保存原 9 行。再次检查实际几何后，改为核对当前状态区的行数及像素高度、外窗尺寸和未操作页的原值。
- Windows 私有桌面在 100%、125%、150% 各通过 76 项，共 228 项。每档管理 1,539 个窗口，隔离违规为零，必跑用例无遗漏。
- 核对窄窗截图的六个页签、状态区分隔条、纵向滚动和底部按钮。三档截图实际像素分别为 560×460、700×575 和 840×690，与 560×460 的逻辑窗口一致。
- 对应复验通过后，将本轮 341 份截图、测试日志、结果清单和首轮失败证据移入 Windows 回收站，共约 16.8 MiB。

## 待验收范围

参考图没有独立的 DUT 配置窗口。本轮核对既有 Qt 表单、分隔条、滚动区域和底部动作的实际显示。窄窗的长表单仍需纵向滚动。实际系统 DPI 动态切换、实体多屏、目标机和真实 DUT 操作继续待验收。本轮以源码和模拟验证为限，最终完整基线和重新打包在后续验收执行。

当轮审计发现 Qt 两窗已能读取已保存凭据，打开窗口间的即时联动待迁移。后续已接入[同项目共用登录输入](PARAMETER_LOGIN_QT_REPORT.md)。
