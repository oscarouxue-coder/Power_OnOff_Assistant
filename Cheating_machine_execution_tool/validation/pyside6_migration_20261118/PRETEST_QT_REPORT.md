# Phase 3｜Qt 单次预备测试

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

## 审计与实现

原 Tk「测试项」页从当前编辑窗口捕获命令和 Telnet 参数，使用项目已选通道，复用 `prepare_pretest_request` / `run_pretest` 按通道逐条执行。每条只执行一次。取消确认时没有业务下发，停止后等待连接与日志收尾。通用 `pretest.start` 从已保存配置取值，直接从 Qt 调用会遗漏未保存的输入。

Qt 使用 `pretest.editor.*` 绑定本机项目、编辑窗口、磁盘配置和已选通道。确认框列出实际源和目标、命令数以及登录后行为。确认后用内存草稿、原 Job 及原执行器启动。有效期、配置和网卡身份会重新校验。运行时编辑区锁定，关闭请求触发安全停止并等待收尾。任务摘要保留成功、失败、未校验、未执行和设备异常；原结果和日志保存在项目任务中。

Windows 隔离测试改为通过 `GetThreadDesktop` 获取测试线程桌面，并使用 `GetUserObjectInformationW` 同时核验桌面名称与 `UOI_IO`。Windows 报告该桌面不接收输入后才初始化 Qt/Tk；API 调用失败、名称不符和接收输入均视为隔离失败。[Microsoft Win32 文档](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getuserobjectinformationw)

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 工作台适配 | `src/services/qt_pretest.py`、`qt_execution_adapter.py`、`qt_workspace_adapter.py`、`src/models/workbench_presentation.py` |
| Qt 界面 | `src/ui/qt/configuration_dialog.py`、`workspace_controller.py`、`log_panel.py` |
| 能力及测试 | `scripts/verify_baseline.py`、`verify_capability_coverage.py`、`capability_gui_actions.json`、`verify_qt_migration.py`、`tests/test_qt_execution_adapter.py`、`qt_workbench_probe.py`、`tk_test_windows.py`、`test_gui_test_coverage.py`、本目录 `verify_pretest_qt.py` |
| 交付记录 | 根目录 `CAPABILITY_COVERAGE.md`、`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`README.md`、`.claude/plans/pyside6-migration.md`、主源码 `line_check_assistant_README.md`、本目录 `MIGRATION_PROGRESS.md`、`PIPELINE_QT_REPORT.md`、`ONU_CLEANUP_REPORT.md` 和本报告 |

## 运行截图与设计差异

Qt 测试配置沿用六标签结构和统一主题。预备测试入口位于测试项列表下方，停止动作和摘要位于窗口底部。参考图描绘总览与项目详情，未提供对话框内部样式。列表只有一条命令时，下方仍留出纵向滚动空间，整体配置窗口尺寸沿用六标签阶段。

- 改造前测试项截图
- 改造后可执行截图
- 停止后摘要截图
- 125% 停止摘要 · 150% 停止摘要

同轮演示截图中，1366×768 总览用三列，第二行纵向滚动。参考图的五项指标、四列项目卡、最近告警与系统健康分区仍有差异。详情页使用条形进度和右侧配置栏，参考图使用环形进度与更紧凑的状态汇总。小窗口通道矩阵的文字余量仍需复核。持续开机检测没有可用于填充参考图健康指标的独立数据源。总览截图 详情截图

## 回归结果

- 116 项相关测试通过，覆盖原预备测试、Qt 配置与任务边界、项目结果，以及隔离桌面成功、伪造身份、输入状态不可核验等情形。
- 324 份编译、314 份源码登记、原业务保全及能力/协议审计通过。原预备测试服务、Telnet 传输与旧 Tk 主程序继续复用。
- Windows 原生 Qt 在 100%、125%、150% 显式缩放下各通过 48 项，共 144 项。三档均核验了私有桌面和 Windows 平台插件，记录的隔离违规为 0。三项全流程、全包手动重启及 C300 离线清理等此前受阻用例在本轮具备原生证据。三档测试结果
- Windows 原生三档验证曾因 `OpenInputDesktop` 返回 WinError 5 在窗口创建前中止。改用系统直接核验后第一轮达到原 90 秒时限，随后按每档 150 秒重跑。C300 原演练的自动选 ID 与模拟 OLT 固定 ID 3 不一致。用例现显式选择并核对 ID 3，原产品默认选择仍为自动。首轮完整结果

可通过现有隔离测试入口运行 `python validation/pyside6_migration_20261118/verify_pretest_qt.py`。输出见阶段结果、相关回归、源码保全和能力检查。

## 待验收

真实设备上的 Telnet、回显、停止和多通道隔离待验。系统实际 DPI、多屏、长时间挂测与完整迁移验收仍待完成。本轮为源码交付，未重跑完整基线或打包。默认启动仍为 Tk，持续开机全业务老化维持待接入。下一项迁移「查询当前样机版本」。
