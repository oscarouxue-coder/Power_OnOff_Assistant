# Phase 5｜Qt 注册后保存 OLT 启动配置

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

C300 完整注册验证后显示独立确认，默认「否」。C600 在「配置业务」的保存选项默认关闭，选中时只读预览和最终确认注明保存范围是整台 OLT。只有原注册与回读成功，且未停止，才可继续保存。

Qt 工作区原有后台轮询在注册任务释放资源后驱动后续保存。任务绑定原操作标识、已保存项目版本、OLT 型号、主机、源 IP 和连接指纹。它通过整 OLT 的独立授权调用原 `OnuRegistrationService.save_configuration`，使用新的 exec 会话和原 120 秒等待。切换当前项目时，已确认的 C600 保存仍归原项目。配置变化、任务冲突、退出或拒绝时记录保存未启动。

注册和保存各有任务记录。保存开始后回执超时、停止等待或其它原因导致结果无法确认时，界面保留待核实和资源保护。保存任务以原操作 ID 去重，不自动重试，也不在程序重启后补发。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| Qt 后台编排 | `src/services/qt_onu_save.py`、`qt_onu_registration.py`、`qt_onu_query.py`、`qt_execution_adapter.py`、`qt_workspace_adapter.py` |
| Qt 界面 | `src/ui/qt/onu_provision_page.py`、`onu_query_dialog.py`、`onu_query_controller.py` |
| 验证与覆盖 | `tests/test_qt_onu_query.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`、根目录 `CAPABILITY_COVERAGE.md`、本目录 `verify_onu_query.py` |
| 文档 | 根目录 `README.md`、`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`.claude/plans/pyside6-migration.md`、主源码目录 `line_check_assistant_README.md`、本目录进度、审计及本报告 |

## 窗口对照

参考图展示总览和项目详情。本次变更位于项目详情打开的 ONU 独立窗口。C600 的保存选项在业务配置页预览按钮上方，C300 在注册回读完成后打开确认。之前的界面已取得实际原生截图。Qt 配置业务前图 Qt 注册预览前图

100%、125%、150% 的复验均因 Windows 输入桌面访问失败在创建窗口前中止，系统探测返回 `OpenInputDesktop` 错误 5。新版 C300 确认、C600 选项和保存结果的原生后图仍待采集。三个画面均已加入原生用例采图路径。原生执行结果

## 验证及待办

- `python validation/pyside6_migration_20261118/verify_onu_query.py --save` 的相关回归通过 238 项，覆盖 C300 独立确认、取消与失效、C600 默认关闭及明确选中、回读失败和停止、跨项目准入保护、保存超时或停止及防重。执行原保存服务时使用模拟会话，核对命令和 120 秒等待参数。相关回归
- 321 文件编译、311 源文件登记及能力覆盖、协议不变量、原 Tk 和 ONU 业务保全检查通过。源码检查
- C300 离线清理重试的 Qt 入口、Windows 原生证据及双型号实机验收待完成。本轮未运行完整基线、未连接真实 OLT、未打包。
