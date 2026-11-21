# Qt 通道重试与失败历史

2026-11-21，V1.3.0 迁移 Phase 3 和 Phase 7。

## 原版行为与 Qt 缺口

原 Tk 通道详情使用非模态窗口展示本次重试、失败、重试后成功与续跑。原开关机服务从 IPC 解析原因，随同轮次和状态交给编排器。现有业务任务投影已将原字段写入当前开关机 Job 的历史事件。改造前，Qt 通道详情仅显示状态和轮次，结构化历史只能在任务日志里查找。

## 实施

通道矩阵和列表共用右键入口，通道快照同步展示原状态的具体原因。已在当前批次准入的通道可打开只读非模态历史。窗口绑定项目、原开关机批次和通道，包含原批次结束后续跑写入的事件。切换主窗口项目时保留原绑定，开启新一轮挂测或关闭该项目时关闭旧窗口。重新打开项目后可通过现有任务历史查阅原任务事件。

归档读取线程以只读方式打开原任务库，先按任务、通道和事件类型筛选，再取 60 条。用事件 ID 向前翻页。工作区复用已有刷新，最新页收到本通道新事件才更新，较早页保持在当前阅读位置。原程控电源、串口、WiFi、检测时序、停止和结果判定沿用现有执行链路。

## 修改文件

- 展示数据及只读查询。`src/models/workbench_presentation.py`、`src/models/qt_log_history.py`、`src/services/qt_log_history.py`
- 工作区派发、批次和通道核对。`src/services/qt_execution_adapter.py`、`src/services/qt_workspace_adapter.py`
- Qt 通道入口、弹窗及接线。`src/ui/qt/project_detail.py`、`src/ui/qt/channel_history_dialog.py`、`src/ui/qt/workspace_controller.py`
- 回归和门禁。`tests/test_qt_log_history.py`、`tests/qt_execution_fakes.py`、`tests/qt_workbench_probe.py`、`scripts/verify_baseline.py`、`scripts/verify_qt_migration.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`、能力覆盖文档
- 操作员说明、阶段计划、迁移进度、项目状态、验收基线及开发记录

## 界面核对

复核上一增量的 150% 原生右键菜单截图，改造前只有「重新开始（从失败轮次继续）」「打开开关机运行日志」和「打开本次 WiFi 连接日志」。改造后，菜单新增「查看本次重试/失败历史…」。已查看三档通道历史原生截图，尺寸分别为 740×380、925×475 和 1110×570 像素。通道标题、批次标识、轮次和原错误详情可读，分页和关闭控件位于窗口底部。参考图展示项目详情主界面，历史窗口沿用 Qt 现有组件和主题。

## 复验命令

~~~powershell
python scripts/run_tests.py test_qt_log_history test_qt_execution_adapter test_qt_workspace_adapter test_power_test_wifi_history test_power_test_resume test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_channel_history_verified
~~~

## 验证结果

- 132 项专项回归通过。新分页用例核对跨项目、批次、通道及历史页边界，验证读取前后任务数据库字节一致。
- 150% 原生专项通过，管理 5 个窗口，隔离违规为零。模拟覆盖运行中重试和失败、其它通道过滤、切换项目、原批次结束后续跑及新批次关闭旧窗口。首次专项在第二批模拟启动时替换了构造器，既有能力实例仍引用初次构造的工厂。修正测试夹具后通过。
- 373 份文件编译、363 项源码登记、能力覆盖、GUI 守卫、协议不变量及原实现保全检查通过。原 162 份核心与业务模块、38 份旧业务文件、7 份本机配置及原 Tk 入口通过保全检查。
- Windows 私有桌面 100%、125%、150% 各通过 83 项，共 249 项。各档管理 1,778 个 Qt 窗口，隔离违规为零。
- 验证和前后界面核对结束后，将本轮 354 份临时截图、测试输出及结果清单移入 Windows 回收站，共约 17.5 MiB。

## 待验收

本轮未触发完整基线和打包。历史窗口的尺寸记忆已在后续增量接入。[窗口尺寸兼容](MODULE_WINDOW_SIZES_QT_REPORT.md)

现场仍需核对实际系统 DPI、DUT 的 WiFi 或其它重试原因、恢复后结果及长期挂测时的界面响应。持续开机全业务老化仍按负责人确认保留待接入。
