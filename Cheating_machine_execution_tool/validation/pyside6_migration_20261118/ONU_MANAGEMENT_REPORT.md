# Phase 5｜Qt 已注册 ONU 管理

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

本轮在现有「已注册 ONU」页增加当前 PON 的已注册 ONU 多选和删除。按查询表的顺序列出并处理所选行。确认窗口列出接口、SN、型号和状态，默认焦点为「取消」。确认有效性绑定原项目、配置版本、OLT、PON 及本次查询结果。

旧 Tk 的 `OnuBatchDeleteService` 继续负责逐台身份核对、实际删除及回读。Qt 使用确认时冻结的接口和 SN，避免根据可能变化的接口列表重建目标。单目标失败、缺 SN、通信异常与停止继续走原分支，逐台结果在原表格显示。无法确认设备结果时保留原资源保护。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| Qt 业务接入 | `src/services/qt_onu_management.py`、`qt_onu_query.py`、`qt_execution_adapter.py`、`qt_workspace_adapter.py` |
| Qt 窗口 | `src/ui/qt/onu_query_dialog.py`、`onu_query_controller.py` |
| 回归和能力门禁 | `tests/test_qt_onu_query.py`、`tests/qt_workbench_probe.py`、`scripts/verify_baseline.py`、`scripts/verify_qt_migration.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`、根目录 `CAPABILITY_COVERAGE.md`、本目录 `verify_onu_query.py` |
| 文档 | 根目录 `README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`ACCEPTANCE_BASELINE.md`、`.claude/plans/pyside6-migration.md`、主源码目录 `line_check_assistant_README.md`、本报告与本目录进度、后续审计 |

## 窗口对照

参考图展示工作台概览和详情布局。本轮调整位于项目详情打开的 ONU 独立窗口。新增确认名单使用只读可滚动文本，保留现有查询表及窗口主题。以下是已有原生流程的前图。[旧 Tk ONU 窗口](tk_onu_query/onu-tk-before.png) 上一阶段 Qt 查询窗口

本轮 100%、125%、150% 在创建窗口前均因无法验证 Windows 输入桌面终止。会话处于 Active，本机探测仍收到 `OpenInputDesktop` 错误 5。交互窗口备用入口返回 Computer Use native pipe 不可用。确认窗口和结果表的原生后图待采，窄窗布局待复验。原生用例已登记为三档门禁所需用例。首轮结果 原生复验结果

## 已验证

- `python validation/pyside6_migration_20261118/verify_onu_query.py --management` 的相关回归阶段通过 220 项，覆盖目标变化、拒绝确认、逐台成功和失败、通信中断、未验证结果与资源保护。传输使用模拟 OLT。相关回归
- 320 文件编译、310 源文件登记、能力覆盖、协议不变量和原业务保全通过。原 Tk 主模块、ONU 驱动和原 ONU 服务保持原实现。源码检查

待办包括原生截图与交互验收、C300 离线清理重试、原独立 OLT 启动配置保存及两种 OLT 的实机复验。默认入口仍为 Tk。本轮未重跑完整基线、未接触设备、未打包。
