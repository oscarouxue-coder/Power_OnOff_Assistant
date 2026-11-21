# Phase 7｜Qt 任务历史

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

## 审计与改动

原业务任务和事件保存在项目自己的 `history/ai/business/capability_jobs.sqlite3`。任务用完整 Job ID 关联事件。原项目运行快照有独立的 ID，历史窗口使用实际事件库的任务 ID。原实时日志缓冲不跨工作区重启。

项目菜单提供「任务历史…」。打开项目后可以查询持久任务，切换任务后按日期查看该任务的事件。后台按任务游标读取，用事件 ID 向更早记录翻页。任务和事件分别每页最多 50 和 60 条。新事件追加时可继续翻旧页，点击「最新日志」回到新记录。运行中的任务继续走原执行和停止服务。

查询使用现有项目上下文和 SQLite 只读连接，只读取任务摘要与原日志事件。源数据库缺失时返回空历史，不创建新库。项目与窗口各自绑定，迟到结果不会回填重开的窗口。只有结构化事件提供可靠通道时才标注通道。

历史任务若留有运行、等待或停止中的旧状态，界面标注「记录为…」。项目运行概览仍负责显示当前任务状态。

历史窗口复用实时日志的级别、搜索、通道筛选和新 TXT 导出。过滤作用于当前页。过长记录标明当前显示范围，原库保存完整记录。导出包含已有的项目、完整任务与通道标识。源库请求、结果和操作身份等字段不进入历史界面。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 数据与服务 | `src/models/qt_log_history.py`、`src/services/qt_log_history.py`、`qt_execution_adapter.py`、`qt_workspace_adapter.py`、`qt_log_export.py` |
| Qt 界面 | `src/ui/qt/log_history_dialog.py`、`log_panel.py`、`workspace_controller.py` |
| 验证 | `tests/test_qt_log_history.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`verify_baseline.py`、`verify_capability_coverage.py`、`capability_gui_actions.json` |
| 交接 | 根目录 `PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`CAPABILITY_COVERAGE.md`、`ACCEPTANCE_BASELINE.md`、`.claude/plans/pyside6-migration.md`、操作员说明、本目录报告和进度表 |

## 截图与参考图

- 改造前的实时日志显示实时过滤器。原界面没有独立的任务历史窗口。
- 改造后的任务历史显示模拟项目重开后的 CH07 历史页。当前入口位于项目菜单，历史使用独立可滚动窗口，并沿用参考稿中的任务与事件层级。

## 验证与待办

- `python scripts/run_tests.py test_qt_log_history test_qt_log_export test_capabilities test_qt_workspace_adapter test_qt_execution_adapter -v` 执行 90 项，全部通过。覆盖原 SQLite、跨项目和任务隔离、页边界、空库、长记录及原临时文本导出。相关回归
- 原生用例验证关闭并重开原项目后读取历史，翻页和筛选可组合，从另一项目导出原窗口的快照时仍保持项目与任务范围。对比数据库文件字节，确认查看及导出没有改写原库。
- Windows 原生 Qt 在 100%、125%、150% 下各通过 56 项，共 168 项，隔离违规为零。三档证据
- 源码保全、编译与协议门禁通过，333 份文件编译、323 份源码登记，覆盖原 Job 和原业务边界。

旧工作区纯文本、独立串口原文的统一浏览以及系统健康仍待接入。本轮未执行设备命令、重跑完整基线或构建 EXE。
