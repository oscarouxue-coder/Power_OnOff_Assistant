# Phase 5｜Qt 批量写样机参数

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

项目详情中的「写样机参数」入口已启用。Qt 复用原参数表生成、加载和预检，支持按当前项目通道筛选目标。加载的表格路径会保存到原项目配置。账号、密码和批次选项通过「保存设置」提交项目版本，保留同一文件里的升级设置。

确认使用实际表格内容、项目版本和通道。界面显示每个 VLAN、COM、表格行和 MAC，并保留原九步写参顺序及两个可选动作。改表或改项目配置后需要重新确认。执行仍由原 `parameters.write` 任务准入，使用原 Telnet/UBUS 或串口路径、读回校验和取消清理。窗口在当前批次结束前保留，重开后可查看逐台结果。

## 文件

| 范围 | 文件 |
| --- | --- |
| 原任务桥接 | `src/services/capability_parameter_services.py` 增加本机已确认表格的可选入口。原外部参数结构、设备执行和取消流程沿用。 |
| 项目控制面 | `src/services/qt_parameter_writer.py`、`src/services/qt_execution_adapter.py`、`src/services/qt_workspace_adapter.py` |
| Qt 界面 | `src/ui/qt/parameter_writer_dialog.py`、`src/ui/qt/parameter_writer_controller.py`、`src/ui/qt/workspace_controller.py`、`src/ui/qt/project_detail.py` |
| 回归和截图 | `tests/test_qt_parameter_writer.py`、`tests/qt_workbench_probe.py`、`tests/workbench_visual_probe.py`、`scripts/verify_qt_migration.py` |
| 登记和验证 | `scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`、仓库根 `CAPABILITY_COVERAGE.md`、本目录 `verify_parameter_writer.py`、`verify_phase3.py`、`verify_wifi.py` |
| 项目文档 | 仓库根 `PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`、`README.md`、`.claude/plans/pyside6-migration.md`、主源码目录 `line_check_assistant_README.md` 及本目录两份进度和审计文档 |

## 实际窗口

| 场景 | 截图 |
| --- | --- |
| 旧 Tk 写参和预检 | [改造前](tk_parameter_writer/parameters-tk-before.png) |
| Qt 首次登录、通道和预检 | 760×660、560×430、150% 缩放 |
| 原任务返回逐台清理结果 | 停止后的结果 |

参考图将常用运行状态留在项目详情。写参维持原独立窗口，在项目页增加导航入口。顶部表单限制短输入宽度，较矮窗口可滚动配置区，底部保留操作和预检结果。截图使用隔离工程及模拟参数表。

## 验证及未完成项

- 127 项相关测试已通过，含原参数表规则、写参服务、旧操作入口、资源准入和 Qt 适配。模拟任务核验取消后零执行、表格和项目版本变更拒绝、部分失败、共用项目管理 IP 回落、停止清理及重开结果。测试输出
- Windows 原生在 100%、125%、150% 缩放下各通过 39 项，共 117 项。每档记录 973 个受管窗口，隔离违规 0。写参路径经项目详情入口、真实 Qt 控件和模拟任务验证。三档证据
- 最新写参界面在三档缩放各复验一次，验证选中已不存在的参数表时提示错误并保留原路径。三个用例全部通过。复验证据
- 313 个文件编译通过，303 个源文件纳入清单。协议与能力登记通过。备份对照将共享写参适配器的本机增量逆向还原后匹配原文件，其余纳入比对的原业务、本地配置和 Tk 应用均匹配。源码检查
- 串口回退仍调用原写参服务。后续阶段已补上自动只读窗口，证据见[串口观察报告](PARAMETER_OBSERVATION_REPORT.md)。旧全流程写参及现场真实网卡、样机、并发和停止待验证。本轮未重跑完整基线及构建发行物。
