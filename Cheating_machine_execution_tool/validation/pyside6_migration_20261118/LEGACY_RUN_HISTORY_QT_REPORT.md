# Qt 任务历史中的旧工作台运行记录

2026-11-21，V1.3.0 迁移 Phase 2 和 Phase 7。

## 旧项目兼容

旧 Tk 工作台直接启动测试时，项目服务在 `runs/<run_id>/run.json` 中记录项目、运行 ID、操作及结果。原 Qt 工作台已在项目总览显示记录数量和最近一次状态。「任务历史」读取独立的业务任务数据库；只有旧 GUI 记录的项目此前在该页显示为空。

现在可在原「任务历史」窗口切换「来源」。旧工作台记录按已打开的项目 ID 和原 GUI 所有者筛选。读取复用原项目状态服务已经载入的记录。创建时间相同时以所有者 ID 排定顺序，每页最多 50 条。切换来源会立即清除上一来源的行，正在读取的旧页返回后，由当前来源重新加载。原业务任务与事件继续使用项目自己的 Job 库。

表格保留原记录的运行 ID、操作、配置版本、结果和起止时间。保存的准备、排队、运行、停止请求等未终结记录显示为待核实；原服务在重开时已经归为未知的记录按未知结果展示。已核实的未知记录保留原结果。浏览历史只读，不发起设备操作。

## 修改文件

| 文件 | 变更 |
| --- | --- |
| `src/models/qt_log_history.py`、`src/services/qt_log_history.py` | 旧 GUI 运行行、状态显示和双键分页 |
| `src/services/qt_workspace_adapter.py` | 按项目在已有归档后台读取并返回分页结果 |
| `src/ui/qt/log_history_dialog.py` | 来源选择、只读表格、翻页和迟到结果处理 |
| `tests/test_qt_log_history.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py` | 服务回归和必须执行的 Windows 原生用例 |
| `scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`、`CAPABILITY_COVERAGE.md` | 登记本机历史浏览入口 |
| `line_check_assistant_README.md` | 操作员查看旧运行记录的入口和状态说明 |

## 复验方法

从主源码目录执行。服务测试覆盖同时间戳翻页、页间插入、跨项目隔离、业务任务去重、未知状态和只读语义。原生用例创建含两份旧运行记录的临时项目并关闭重开，在没有 Job 数据库的情况下切换两种来源，人工延迟一次后台读取，核对旧结果不会填入当前页。用例复查原记录字节及数据库路径。

~~~powershell
python scripts/run_tests.py test_qt_log_history test_qt_workspace_adapter test_capability_coverage -v
python scripts/verify_capability_coverage.py
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_project_commands_confirmed
~~~

## 验收状态

集成后 95 项专项回归通过。Windows 私有桌面 150% 单项复验通过，管理 5 个窗口。最终标准原生批次 `handoff_20261121_final/native` 在 100%、125%、150% 各通过 86 项，每档管理 1,800 个 Qt 窗口，隔离违规为零。

实测截图中六列可见，长运行 ID 和配置版本省略显示，可悬停读取全文。起止时间、成功及已核实的未知结果可直接辨认，翻页按钮位于底部。参考图只展示工作台和项目详情，未提供历史窗口展开画面。现场仍需以实际迁移项目核对运行 ID、配置版本、起止时间和原结果。
