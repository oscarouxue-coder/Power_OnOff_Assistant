# Phase 2｜Qt 选择导入的接入配置

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

## 审计与改动

旧 Tk 界面沿用 `WorkspaceService.connection_candidates` 和 `use_connection`。原导入流程保存钉钉和飞书候选，关闭接入及飞书群聊、单聊和通知开关。选择候选时由原平台存储解密并重新加密到当前工作区，沿用连接占用检查。

Qt 项目菜单新增「选择导入的接入配置…」。窗口默认未选中，可按平台和来源标签选择，凭据留在后台原存储。点击「选择并保存」后，复核候选来源、候选配置及当前工作区配置摘要。原服务加载候选后再次核对摘要、停用状态和应用身份，随后走原保存入口。候选或当前配置如有变化，重新打开窗口确认。选择成功时，界面提示重启后在本机确认启用。

此操作只保存所选平台配置，远程项目允许范围继续独立管理。未选择候选、取消、占用拦截及版本变化均保留已有配置。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 服务 | `src/services/workspace_service.py`、`qt_imported_connections.py`、`qt_workspace_adapter.py` |
| 界面 | `src/ui/qt/imported_connection_dialog.py`、`workspace_controller.py` |
| 验证 | `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_baseline.py`、`verify_qt_migration.py`、`verify_capability_coverage.py`、`capability_gui_actions.json`、本目录的 `verify_phase3.py` |
| 交接 | 根目录 `DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`CAPABILITY_COVERAGE.md`、`.claude/plans/pyside6-migration.md`、操作员说明、本报告和迁移进度表 |

## 截图与参考图

改造前的旧项目导入结果显示 Qt 工作台及项目菜单入口。本次将配置选择集中在同一菜单，使用独立短表单，沿用参考稿中工作台与项目管理的层级。

150% 选择窗口截图展示临时候选的来源标签、停用提示和保存操作。

## 验证与待办

- `python scripts/run_tests.py test_qt_workspace_adapter test_project_workspace test_project_completion test_workspace_platforms -v` 通过 72 项，覆盖双平台加密存储、候选变更、占用拦截、远程范围和原导入回归。相关回归
- 源码保全脚本按迁移前备份验证，原 `use_connection` 仅新增 Qt 专用的可选保存前复核。旧 Tk 调用仍走原有分支。编译 338 份文件、登记 328 份源码。源码保全与编译
- `python scripts/verify_qt_migration.py --output validation/pyside6_migration_20261118/qt_imported_connections_final` 在 100%、125%、150% 下各通过 60 项，共 180 项。Windows 私有桌面隔离违规为零。三档证据

实际接入平台和远程控制面仍按原计划单独迁移及验收。本轮使用临时配置和模拟凭据，未重跑完整基线或构建 EXE。
