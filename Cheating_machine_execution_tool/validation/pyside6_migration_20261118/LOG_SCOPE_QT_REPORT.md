# Phase 7｜Qt 实时日志筛选与导出

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

后续增量已加入[任务历史](LOG_HISTORY_QT_REPORT.md)。下文保留本阶段实施和验证记录。

## 审计与改动

Qt 原窗口已有全局和项目范围、级别、搜索、自动滚动及清空显示。项目与通道模型虽然能容纳任务和通道标识，大部分业务输出只收到八位任务前缀，导出入口也处于禁用状态。现从原 Job 事件订阅完整任务 ID、原事件时间和内容。只有原 `aging`、`history`、`version_item` 结构化事件提供有效的通道字段时，才为记录标注通道。原文本输出路径对其他入口保持有效，原 SQLite 写入、任务状态与设备业务继续沿用原流程。

项目详情可筛选项目全部、当前任务或指定通道。通道范围在已关联任务时跟随该任务，尚未有任务时按项目筛选。日志仍使用有界显示缓冲，筛选组合保留级别与搜索。没有实际变化的过滤结果不重绘。窄窗保留范围、筛选和导出控件，标题悬停显示项目全名。

「导出」保存点击时的筛选快照，即使在选择文件期间切换页面，内容仍与原选择一致。文本包含适用记录的项目 ID、完整任务 ID 和通道。后台先写完整临时文件，再发布到选择的新 `.txt` 路径。其他文件保持，取消文件选择时没有写入。原持久日志仍可用于后续历史接入。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 服务与原事件源 | `src/services/qt_log_export.py`、`qt_execution_adapter.py`、`qt_workspace_adapter.py`、`capability_jobs.py` |
| Qt 界面与动作 | `src/ui/qt/log_panel.py`、`main_window.py`、`workspace_controller.py` |
| 测试与门禁 | `tests/test_qt_log_export.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`verify_baseline.py`、`verify_capability_coverage.py`、`capability_gui_actions.json`、本目录 `verify_phase3.py` |
| 文档 | 操作员说明、根目录 `DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`CAPABILITY_COVERAGE.md`、`.claude/plans/pyside6-migration.md`、本目录进度和阶段报告 |

## 实际截图与参考图

- 改造前的项目日志保留级别、搜索和清空显示，导出处于禁用状态。
- 窄窗通道筛选及导出使用模拟开关机任务，显示 CH01 对应活动及可用导出。
- 参考图以级别色标和行表格显示。当前仍使用可复制和换行的原文本区，数据来自实际事件入口。导出保存当前有界缓冲的筛选记录。完整持久历史、系统监控及告警中心另行验收。

## 验证与剩余工作

- `python scripts/run_tests.py test_qt_log_export test_capabilities test_qt_workspace_adapter test_qt_execution_adapter -v` 通过 88 项。包含新文件写入、目标同名拒绝、写入失败无残留、原任务与资源行为。相关回归日志
- 原生专项通过点击导出、选择路径期间切换页面、项目/任务/通道隔离、缓冲容量和窄窗控件布局。文件选择使用测试夹具，导出实际写入临时项目。
- 三档 Windows 原生 Qt 最终复验在 100%、125%、150% 下各通过 55 项，共 165 项，隔离违规为零。三档结果
- 源码保全及门禁确认原 Job 增加可选日志输出，330 份文件编译、320 份源码登记、协议和能力动作检查均通过。源码检查器首次替换范围同时命中写库和观察回调，缩小到写库一行后复验通过。

下一步从现有项目任务记录及 `capability_jobs.sqlite3` 按需分页读取历史事件。旧工作区纯文本没有可靠任务或通道字段时须标明缺失。当前阶段未操作真实设备、构建 EXE 或重跑完整基线，系统 DPI 和长期挂测待验收。

已用临时库核对历史分页的原结构。按完整 Job ID 和 `id < 上一页边界` 读取可使用原 `job_events_job` 索引。插入更新记录后继续读取旧页，页间保持无重复。只读连接拒绝数据库写入。本轮核对了查询路径，历史浏览入口仍待接入。
