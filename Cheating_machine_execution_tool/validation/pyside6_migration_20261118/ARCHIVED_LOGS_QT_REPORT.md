# Phase 7｜工作区与串口归档日志

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

## 审计与改动

旧 Tk 工作区将事件原文附加到 `workspace.log`，Qt 也向该文件追加文本。旧串口终端按 VLAN、COM 和打开日期命名文件，逐行记录时间、接收或发送方向和原文。文件没有统一的级别、任务和通道 ID。

Qt 项目菜单新增「归档日志…」。工作区来源按固定路径只读打开 `workspace.log`。打开项目后也可查看其默认串口日志目录，及当前已保存、以该项目 ID 结尾的自选目录。串口文件沿用既有命名，并显示来源目录。公共目录及早先更换且已失去项目归属的路径需要操作员从原文件位置核对。

读取走独立后台通道，每页最多 120 行、128 KiB。旧页游标记录文件身份和字节位置，尾部追加不会移动上一页边界。文件被替换或截短时提示重新读取最新页。超长行按 UTF-8 字符边界分段。原文件保持不变。

搜索和导出使用当前页，导出写入用户指定的新 TXT。界面和导出保留原始消息文本，对没有结构化字段的文件不推断级别、任务或通道。原有结构化任务历史继续通过「任务历史…」查询。

同一时刻只运行一个归档读取。关闭项目或工作区可丢弃迟到结果，慢速文件读取不会占用原任务控制队列。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 模型和文件服务 | `src/models/qt_log_history.py`、`workbench_presentation.py`、`src/services/qt_archived_logs.py`、`qt_workspace_adapter.py`、`qt_log_export.py` |
| Qt 界面 | `src/ui/qt/archived_logs_dialog.py`、`log_panel.py`、`workspace_controller.py` |
| 验证 | `tests/test_qt_archived_logs.py`、`tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`verify_baseline.py`、`verify_capability_coverage.py`、`capability_gui_actions.json` |
| 交接 | 根目录项目状态、开发日志、验收基线、能力覆盖和迁移计划，操作员说明、本报告和迁移进度表 |

## 截图与参考图

改造前的全局实时日志位于工作台底部。归档窗复用相同的日志文本、搜索和导出界面，通过顶部菜单按需进入。归档来源及翻页操作集中在同一窗口。

150% 改造后截图显示实际文件名称、原行时间和收发标记。

## 验证

- `python scripts/run_tests.py test_qt_archived_logs test_qt_log_export test_qt_log_history test_qt_workspace_adapter test_qt_serial_terminal -v` 通过 42 项。覆盖追加后的分页、替换文件、长行、原项目范围、当前页原文导出、慢速读取和退出。专项回归
- 源码保全、编译、协议与覆盖通过，编译 340 份文件，登记 330 份源码。
- `scripts/verify_qt_migration.py` 在 100%、125%、150% 下各执行并通过 61 项，共 183 项。Windows 私有桌面隔离违规为零。三档结果

持久日志写入健康、积压状态及实际长期挂测验收仍在原迁移计划。此增量只读原有文件。本轮未重跑完整基线或重建 EXE。
