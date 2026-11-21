# Phase 2｜Qt 最近项目

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

## 审计与改动

旧 Tk 工作区在项目菜单中按 `WorkspaceService.recent` 的既有顺序列出最近项目。菜单项使用原保存路径打开项目，「从最近列表移除」按当前项目目录调用 `WorkspaceService.forget`。记录存放在工作区的 `recent_projects.json`。

Qt 工作台沿用该记录和原项目打开入口。后台工作线程在启动时，以及会更新最近记录的项目操作完成后，向界面交付列表快照。菜单打开时读取该快照，提示显示完整路径，重名项目可按路径区分。点击记录会打开或选中对应项目，不会自动启动持久历史中的任务。

通过项目菜单移除当前项目会更新原最近列表，项目仍保持打开。目录、配置和历史文件保留。列表损坏时沿用原读取提示，启动时保留原文件，仍可手动打开项目。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 后台适配 | `src/services/qt_workspace_adapter.py` |
| 界面 | `src/ui/qt/workspace_controller.py` |
| 回归与覆盖 | `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json` |
| 交接 | 根目录 `DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`CAPABILITY_COVERAGE.md`、`.claude/plans/pyside6-migration.md`、操作员说明、本报告、迁移进度表 |

## 截图与参考图

前一版 Qt 工作台的项目管理集中在顶部「项目」入口。本轮新增条目收在这一菜单中，沿用原 Tk 的操作路径和现有 Qt 工作台层级。参考稿侧栏展示当前工作区项目，最近项目作为按需菜单访问，侧栏继续显示实际已打开的项目。

150% 原生菜单截图取自临时项目，展示原最近顺序及含 `&` 的项目名。

## 验证与待办

- `python scripts/run_tests.py test_qt_workspace_adapter test_project_workspace -v` 通过 36 项，核对原文件、项目重新打开、重命名后排序、移除时保留项目文件、损坏列表和原 Tk 项目管理。相关回归日志
- 源码保全、编译、覆盖和协议检查通过，335 份文件完成编译，325 份源码完成登记核对。
- `python scripts/verify_qt_migration.py --output validation/pyside6_migration_20261118/qt_recent_projects_verified` 在 100%、125%、150% 下各通过 58 项，共 174 项。私有桌面隔离违规为零。三档证据

配置页面草稿恢复、导入平台配置选择和现场验收仍在迁移总表跟踪。本轮未重跑完整基线或构建 EXE。
