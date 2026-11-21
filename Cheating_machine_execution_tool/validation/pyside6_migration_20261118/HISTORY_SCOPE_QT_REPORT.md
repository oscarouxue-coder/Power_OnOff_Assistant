# Qt 任务历史搜索与远程项目范围

2026-11-21。覆盖原迁移计划的 Phase 2、5、6 和 7。此报告对应当前源码候选。

## 业务行为

- 「任务历史」原先只能筛选屏幕中的一页。现在输入仍可即时预筛本页，回车或点击「查询任务日志」会按所属项目、完整任务 ID、通道、级别和关键词查询全部事件。关键字按 Unicode 大小写折叠进行字面匹配，百分号和下划线也按原字符匹配。查询先筛选再按事件 ID 分页，每页最多 60 条。超长正文返回有界节选，关键词位于末尾时显示命中处。浏览和导出复用原只读数据库、可取消的后台读取及本页导出路径。[历史窗口实测截图](history_scope_final_native/scale-1/task-history-older-page.png)
- 旧 Tk 的本机授权窗口通过 `WorkspaceService.set_remote_projects` 保存远程项目范围。Qt 的「项目」和「设置」菜单现共用该服务。打开和刷新只读。确认框列出所有新增、撤销的项目名及完整 ID，默认为取消。已关闭项目的旧授权在确认清单中单列。保存前复核已打开的项目对象、项目名和原授权集合，同一个 ID 关闭重开也要求重新核对。已受理任务及平台撤销行为沿用原服务。[范围窗口实测截图](history_scope_final_native/scale-1/remote-project-scope.png)
- VS Code 首选启动项使用 `run_dutpilot_qt.py --workspace`。截图复现了 `LOCALAPPDATA` 在调试器解析时为空的路径错误。现在从 VS Code 的用户主目录定位独立解释器，给子进程设置本机数据路径。已在 Administrator 用户环境中先清空原变量，使用已安装的 debugpy 调起 `--help`，再核对工作台参数、Qt 6.8.3 及原工作区路径。真实用户按键启动待反馈。Tk 与串口升级仍有各自的启动项。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 事件投影、分页和页面 | `src/models/qt_log_history.py`、`src/services/qt_log_history.py`、`src/ui/qt/log_history_dialog.py` |
| 项目范围 | `src/services/qt_remote_project_scope.py`、`src/services/qt_workspace_adapter.py`、`src/ui/qt/remote_project_scope.py`、`src/ui/qt/workspace_controller.py` |
| 验证与能力覆盖 | `tests/test_qt_log_history.py`、`tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json` 和根目录 `CAPABILITY_COVERAGE.md` |
| 操作和交接 | 根目录 `.vscode/launch.json`、`README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`，主源码目录 `line_check_assistant_README.md` 及同目录迁移进度表 |

## 测试记录

在主源码目录运行以下命令。服务回归使用临时项目与模拟平台。原生回归运行在受核验的 Windows 私有桌面。

```powershell
python scripts/run_tests.py test_qt_log_history test_qt_log_export test_qt_workspace_adapter test_workspace_gateway test_capability_coverage -v
python scripts/verify_capability_coverage.py
python scripts/verify_qt_migration.py --output validation/pyside6_migration_20261118/history_scope_final_native
```

- 服务组合最终通过 62 项。覆盖跨页、同名项目隔离、超长原文、权限变更、拒绝旧确认、单项目重开、已撤销路由和授权文件写入。窗口隔离预检识别 74 个构造点（新增窗口复验结果以最终门禁为准）。[专项原文](history_scope_services.txt)
- 首轮组合有一项模拟会话测试在释放模拟模型前同步等候关闭完成。修正用例后，依次核对停止、收尾期间项目仍打开、真实关闭回执及重开历史。初次 Qt 全套的搜索回车还触发了对话框默认操作。现在在搜索框消费该按键；复验覆盖按按钮、按回车、翻页及导出。
- 已核对 100% 实测截图。两窗在约 680 像素宽时均能访问底部操作。完整 ID 可悬停查看，保存确认列出完整 ID。原参考图未给这两个弹窗的逐像素稿。

## 验收边界

开关机沿用原执行入口。本轮以 Git 对照确认 `src/core`、`legacy_power_test_service.py`、`pipeline_orchestrator.py` 和旧挂测目录相对当前 HEAD 无工作树差异。持续供电的全业务老化仍缺独立执行与检测来源。两类现场挂测、真实平台登录及路由、清洁目标机启动和长期稳定性均待人工验收。整套迁移状态见[逐项进度](MIGRATION_PROGRESS.md)。
