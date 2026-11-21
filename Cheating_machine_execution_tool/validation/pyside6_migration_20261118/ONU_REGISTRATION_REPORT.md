# Phase 5｜Qt ONU 目标与注册

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

C300 和 C600 可从本次未注册发现中的实际 SN/PON 勾选一台或多台。在「配置业务」中为各台手填 ONU ID，或让原分配规则使用发现建议及起始 ID。业务表单保留原型号字段、模板和 VLAN 映射规则，项目中通过「保存业务参数」保存。

命令由原校验器生成，确认页只读且可以复制。修改目标或业务参数会清空旧确认。确认提交时再次核对项目版本、本次发现、实际目标、业务参数和所有目标 PON。整机发现可以选跨 PON 目标，执行授权逐个绑定实际 PON。任务调用原注册服务，沿用整批预检、逐台配置、上线回读和协作停止。启动后如果失败或停止且结果无法确认，Qt 标为待核实并保留资源保护。

## 文件

| 范围 | 文件 |
| --- | --- |
| 项目业务表单和原任务接入 | `src/services/qt_onu_registration.py`、`src/services/qt_onu_query.py`、`src/services/qt_execution_adapter.py`、`src/services/qt_workspace_adapter.py` |
| 目标、业务和确认窗口 | `src/ui/qt/onu_provision_page.py`、`src/ui/qt/onu_query_dialog.py`、`src/ui/qt/onu_query_controller.py` |
| 回归与门禁 | `tests/test_qt_onu_query.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`、`CAPABILITY_COVERAGE.md`、本目录 `verify_onu_query.py` |
| 交接和操作手册 | `README.md`、`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`line_check_assistant_README.md`、`.claude/plans/pyside6-migration.md`、本目录进度、查询报告及后续审计 |

## 窗口对照

上一阶段只提供查询和结果浏览。改造前的 Qt ONU 查询

本轮沿现有 ONU 独立窗口增加业务配置和确认执行页。目标和业务采用可调整分栏，长参数表及长命令使用纵向滚动。参考工作台在主详情中保留模块入口，具体配置和执行仍在独立窗口。配置业务 逐台只读命令预览

## 回归及待接入范围

- 195 项相关测试通过，涵盖 C300 单台停止和取消、C600 逐台 ID、跨 PON、重复 ID 拦截、保存及预览失效、原业务命令计划和 VLAN 转换规则。回归结果
- 319 文件编译、309 源文件登记通过。原 ONU 驱动、服务及 Tk 源码保全检查通过。源码证据
- 首轮原生测试遗漏了关闭窗口时的保存提示，已补上测试中的明确选择。首轮 150% 套件还发生过超时，恢复输入桌面验证后按相同隔离要求复验。首轮原生输出
- 最新代码的 ONU 查询及注册原生专项在 100% 和 125% 各通过 2 项，隔离复核通过。150% 的两项用例断言通过，退出时隔离复核失败。保持桌面连接后重跑，100% 的 42 项完整原生套件断言通过但隔离复核失败，125% 和 150% 在初始化时无法验证桌面。最后一次 150% 专项重试的预检返回 Windows 错误 5。完整三档原生验收仍待复验。专项证据 完整套件重试 150% 预检输出
- C300 显式离线候选的清理重试、已注册 ONU 删除和 OLT 启动配置保存仍待迁移。原服务支持的真实设备阶段均需负责人复验。本轮使用模拟设备，未打包，未重跑完整基线。
