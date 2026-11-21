# Phase 5｜Qt C300 单台注册离线清理重试

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

后续复验已通过。原生用例现明确选择模拟 OLT 能回读的 ONU ID 3，三档均走完清理、重试、回读及人工选择暂不保存。原产品继续支持自动选择 ONU ID。原生复验

C300 的「配置业务」页加入临时清理选项，默认关闭。选定一台注册目标后，可独立确认只读查询，通过原服务读取目标 PON 的离线候选。查询成功后需明确选择一条带可核实 SN 的记录。窗口、型号、注册目标或业务参数变化后，应重新查询。Qt 的预览和注册确认都列出将被授权的候选接口及 SN。

候选绑定本次查询、项目配置版本、实际注册目标及业务参数。实际注册沿用原不可变命令、整批预检、停止和回读。原服务在 CLI 配置错误后才复核候选状态和身份，符合条件时处理选中的一台并重试原配置一次。C300 的启动配置保存仍在最终验证成功后单独询问。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| Qt 后台编排 | `src/services/qt_onu_registration.py`、`qt_onu_query.py`、`qt_workspace_adapter.py` |
| Qt 界面 | `src/ui/qt/onu_provision_page.py`、`onu_query_dialog.py`、`onu_query_controller.py` |
| 验证与覆盖 | `tests/test_qt_onu_query.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`、根目录 `CAPABILITY_COVERAGE.md`、本目录 `verify_onu_query.py` |
| 文档 | 根目录 `README.md`、`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`.claude/plans/pyside6-migration.md`、主源码目录 `line_check_assistant_README.md`、本目录 `MIGRATION_PROGRESS.md`、`NEXT_ONU_AUDIT.md`、`NEXT_FIRMWARE_AUDIT.md` 及本报告 |

## 窗口对照

参考图展示主工作台的概览和项目详情。本次入口仍在项目详情打开的 ONU 窗口内，清理选项位于业务表单下方，查询和候选选择在启用后出现。此阶段之前的原生画面可用于对照。[旧 Tk ONU 窗口](tk_onu_query/onu-tk-before.png) Qt 业务表单前图

100%、125%、150% 原生执行均在创建窗口前因输入桌面校验中止，独立探测返回 `OpenInputDesktop` 错误 5。改造后画面待采集，候选选择和确认预览已加入原生采图用例。三档原生结果

## 验证及待办

- `python validation/pyside6_migration_20261118/verify_onu_query.py --cleanup` 的联合回归通过 280 项。新增用例通过 Qt 后端调用原 C300 服务及命令解析，底层使用模拟 OLT 会话。覆盖只读查询、取消、范围变化、未确认 SN、批量及 C600 拒绝、注册确认失效、单目标清理一次后重试、SN 改变拒绝删除，以及成功后另行询问保存。相关回归
- 321 文件编译、311 源文件登记、GUI 和能力覆盖、协议不变量及 Tk 与原业务源码保全通过。源码检查
- 待完成 Windows 三档原生后图与交互复验、真实 OLT 现场复验和旧全流程联动。默认入口为 Tk。本轮未重跑完整基线、未连接真实设备、未打包。
