# 项目主执行日志与资源监测归档

旧 Tk 项目由[主程序](../../../line_check_assistant/app.py)创建 `line_check_YYYYMMDD_HHMMSS.log`，由[资源监测器](../../../src/services/transport_history_monitor.py)写入 `resource_monitor/transport_history_YYYYMMDD_HHMMSS_ffffff.jsonl`。原来的 Qt 归档窗口只提供工作区和串口来源。现在可从「项目 → 归档日志… → 项目主日志」按时间选择原文件，翻页、搜索和导出本页。打开窗口时绑定当前项目。

## 已核对的行为

- 从迁移前真实备份的临时副本打开两个项目。A 包含 3 个主执行日志和 3 个资源监测文件，共 152 行。B 包含 9 个主执行日志和 9 个资源监测文件，共 828 行。经 Qt 工作区命令队列读取全部原文，在项目保存和重开后重复读取，逐行对照 UTF-8 原件，行序、文本和项目归属均一致。原文件哈希保持一致，外部通信和实体串口调用为零。[脱敏计数](old-projects.json) · [复验脚本](../archived_projects/check_archived_projects.py)
- 文件读取沿用原归档分页器，保留替换文件与旧游标检查。新增来源只接受项目下对应目录和原写入器的命名格式。越界路径、无关文件和放错目录的文件被拒绝。归档、导出和业务覆盖专项 9 项通过。[专项输出](focused.txt)
- 新入口复用原归档窗的文件下拉框、后台读取、日志面板、按页筛选及本机导出。原生用例切换工作区、项目串口、资源监测与主执行日志，读取 132 行测试日志的最新和更早页。截图只含模拟日志。

## 修改文件

[归档读取](../../../src/services/qt_archived_logs.py)、[工作区调度与执行日志](../../../src/services/qt_workspace_adapter.py)、[归档窗口](../../../src/ui/qt/archived_logs_dialog.py)、[服务专项](../../../tests/test_qt_archived_logs.py)、[原生操作测试](../../../tests/qt_workbench_probe.py)、[能力清单生成](../../../scripts/verify_capability_coverage.py)、[动作清单](../../../scripts/capability_gui_actions.json)及[操作员说明](../../../line_check_assistant_README.md)。本阶段仅使用文件副本与模拟数据。

三档原生截图保留了主日志翻页的显示结果。[100%](native/scale-1/archived-project-main.png) · [125%](native/scale-1.25/archived-project-main.png) · [150%](native/scale-1.5/archived-project-main.png)

## 标准 Windows 候选包

3,248 项完整基线通过，249 项指定用例全部执行。三档 Windows 原生共 285 次通过。成品入口和 331 个项目模块与源码一致，92 个受保护业务文件保留原哈希，另外 5 个与负责人确认的修正快照一致。目录与 ZIP 的 245 份文件已比对，验包逐一核对 39 个 PySide6/shiboken6 原生文件导入的 Qt6 DLL。ZIP 共 55,357,664 字节，SHA256 为 `5a62b80014b761cc5cba63a5f361fa0fff6359cc0a27561512c06d04dbc3d369`。

[Windows 便携 ZIP](../../../dist/qt-20261121-143820-20f3c0f3/DUTPilot_portable.zip) · [SHA256](../../../dist/qt-20261121-143820-20f3c0f3/DUTPilot_portable.zip.sha256.txt) · [构建与全量回归](build.txt) · [成品源码比对](packaged-sources.json) · [验包明细](../../../dist/qt-20261121-143820-20f3c0f3/PACKAGING_REPORT.json)

本机仅静态核对新 EXE。目标机独立启动、实体多屏、真实 DUT 及长期挂测待现场验证。

399 张过程截图已移入回收站。保留报告引用的三档主日志截图各一张。
