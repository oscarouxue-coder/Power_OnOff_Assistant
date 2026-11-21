# Qt 历史批次结果文件

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 2、6 和 7。

## 审计

原 Qt 任务历史从项目 SQLite 任务库分页读取事件。上一轮接入的通道右键入口绑定本次开关机任务及其当前 WiFi 尝试。工作台重启后，旧任务本身仍有持久记录，但历史页缺少打开所选批次原文件的入口。

原任务库保存完整任务 ID、能力和提交时的通道参数。项目各快照的 `run.json` 保存项目、任务所有者、运行标识和操作类型。失败轮次续跑写在原开关机批次结果目录内，目标仍按原任务通道绑定。

## 实施

在「项目 → 任务历史」选定开关机任务，通过任务选择框右键「查看批次结果文件…」可看到该批次的开关机结果及 WiFi 原文件。全流程任务仅在原参数确实包含开关机子任务时提供文件。点击「打开文件」后由 Windows 关联程序处理。

文件发现复用工作区归档读取线程，读取原任务库和运行记录并仅列出原有通道、原命名的普通日志文件。文件打开时再核验项目、任务 ID、运行记录、所在通道及实际路径。重定向、缺少记录和文件移动会提示。结果浏览和打开保留数据库与日志字节，成功或失败的打开操作写入主执行日志。历史 WiFi 文件仍属于所选历史批次。

## 修改文件

- `src/services/qt_power_logs.py`、`src/services/qt_workspace_adapter.py`、`src/ui/qt/log_history_dialog.py`
- `tests/test_qt_log_history.py`、`tests/qt_workbench_probe.py`
- `scripts/verify_qt_migration.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json` 和能力覆盖文档
- 操作员说明、迁移计划和进度、项目状态、开发记录和验收基线

## 复验命令

```powershell
python scripts/run_tests.py test_qt_log_history test_qt_archived_logs test_qt_log_export test_qt_workspace_adapter test_qt_execution_adapter test_power_test_log_service test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_history_result_verified
```

## 验证

- 150% 原生专项 3 项通过。新增用例关闭原工作台、创建新工作台并重开同一个项目，选中较早批次后检查列表、路径、通道归属、打开反馈及数据库原始字节。测试替换 Windows 实际打开动作，全程没有加载设备执行实例。
- 369 个文件编译、359 个源码登记项、能力覆盖、GUI 守卫、协议与原实现保全检查通过。
- 参考图的历史入口未展示批次文件选择对话框。新增窗口沿用 Qt 列表及底部操作，150% 截图核对批次、通道、文件和「打开文件」「关闭」均可读。
- 98 项专项回归通过。覆盖更早批次、无开关机子任务的全流程、跨批次/通道/项目路径、运行记录变化及打开前复核。
- Windows 私有桌面 100%、125%、150% 各通过 80 项，共 240 项。每档管理 1,765 个 Qt 窗口，隔离违规为零。批次窗口截图实际尺寸为 760×390、950×488 和 1140×585 像素。
- 验证通过且结果入档后，将本轮 346 份截图、测试日志和结果清单移入 Windows 回收站，共约 17.1 MiB。

## 待验收范围

入口适用于能同时核对持久任务与运行快照的记录。缺少任务或快照身份的旧文件仍按原项目目录核对。续跑文件从原批次查看。不同目标机关联程序、真实设备生成文件、长期挂测以及最终完整基线和打包继续待验收。
