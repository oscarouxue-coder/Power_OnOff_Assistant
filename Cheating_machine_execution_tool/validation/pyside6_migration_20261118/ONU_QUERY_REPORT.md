# Phase 5｜Qt ONU 配置与查询

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

项目详情已启用 ONU 查询入口。C300、C600 单独保存连接与发现范围，并兼容原项目的 `onu_registration.ini`。保存后可以测试连接、查询 ONU 类型及 DBA 模板、发现未注册 ONU，以及查询当前 PON 下的已注册 ONU。界面掩码显示密码，并按实际返回展示发现型号、模板、类型及状态。

每次查询从已保存配置取得型号、OLT、源地址和目标范围，先由本机操作员确认，再使用原 ONU 服务与任务执行。确认只绑定本次读取，取消、变更项目或配置后不能沿用。整机未注册发现和单 PON 已注册查询沿用原边界。C300 先整机发现，再筛选目标 PON。停止继续等待原查询任务释放资源。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| ONU 项目配置、授权与任务 | `src/services/qt_onu_query.py`、`src/services/qt_execution_adapter.py`、`src/services/qt_workspace_adapter.py` |
| 项目详情和窗口 | `src/ui/qt/onu_query_dialog.py`、`src/ui/qt/onu_query_controller.py`、`src/ui/qt/project_detail.py`、`src/ui/qt/workspace_controller.py` |
| 回归、编译及能力登记 | `tests/test_qt_onu_query.py`、`tests/qt_workbench_probe.py`、`tests/workbench_visual_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`、仓库根 `CAPABILITY_COVERAGE.md`、本目录 `verify_onu_query.py` |
| 交接与操作手册 | 仓库根 `README.md`、`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`.claude/plans/pyside6-migration.md`、主源码目录 `line_check_assistant_README.md`、本目录进度及后续审计 |

## 前后截图

| 改造前 | 改造后 |
| --- | --- |
| [旧 Tk 查询页](tk_onu_query/onu-tk-before.png) | Qt C300 未注册发现、Qt C600 DBA 查询窄窗口、C600 窄窗口 150% |

参考稿将全局导航留在项目详情。ONU 入口沿用独立业务窗口，项目名称、当前型号、连接配置、查询结果及停止按钮在窗口内可见。本次截图使用模拟 OLT，查询阶段按未注册、已注册及模板组织。后续业务配置和注册确认仍需接入。

## 验证与待完成范围

- 129 项相关测试通过。经原项目存储和 ONU 任务，验证了双型号配置与旧业务字段保留、保存失败回滚、取消和旧确认拒绝、源 IP 和 PON 传递、临时授权回收及停止。测试输出
- 317 个文件编译、307 个源文件登记通过。协议、覆盖清单和原业务保全通过。原 ONU 能力、设备协议及 Tk GUI 未改动。源码核验
- 首轮原生运行发现查询按钮调用的参数重名，已修复。查询回归也等待原 Job 收尾后再操作后续控件，覆盖了终态与资源释放的间隔。首轮证据
- 修复后运行 `python validation/pyside6_migration_20261118/verify_onu_query.py --retry`。100%、125% 和 150% Windows 原生各 41 项，共 123 项通过。每档记录 979 个受管窗口，隔离违规 0。原生证据
- 多选、逐台 ID、业务参数、只读命令预览及原注册任务在后续阶段接入。[注册阶段报告](ONU_REGISTRATION_REPORT.md) 精确删除和独立保存仍待迁移。本轮未操作真实 OLT，未重跑完整基线，未打包。
