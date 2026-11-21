# Qt 排障会话管理

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 5 AI 诊断。

## 审计与迁移

原 Tk「管理会话」列出当前项目的全部可见会话，支持多选、全选、刷新、改名、删除选中和清空全部。原 `AiConversationService.delete_sessions` 展开批量子会话，与对话发送互斥，并在同一 SQLite 事务中删除本次选定会话的记录。已有 Qt 入口能逐条查看、改名和删除当前会话。[改造前 Qt 会话报告](AI_CHAT_QT_REPORT.md)

Qt 会话列表下方增加「管理会话…」。项目内的表格显示创建时间、标题、目标、模型和状态，打开时默认选中当前会话。可 Ctrl / Shift 多选、全选、取消选择及刷新。单选行可右键改名，沿用原标题服务。旧时间无法按 ISO 格式解析时，表格、悬停全文和确认名单沿用原值。内部批量子会话由父记录管理。任何子会话仍在执行或清理时，父会话同步显示忙碌状态，原服务仍在实际删除前复核。

删除前列出项目和会话，以按下按钮时的 ID 固定范围，默认取消。确认期间新增的会话会保留。沿用原整批忙碌保护和事务，保留原始文件、诊断报告、案例及其它项目数据。删除其它会话时，当前消息分页、阅读位置和输入保留。删除当前会话后，清空旧输入并切换至最新的剩余会话。全部删除时进入空列表。

管理窗沿用现有 Qt 主题和项目工作区刷新。参考总览设计未包含此弹窗。对照改造前单会话菜单和 150% 下的管理窗口，新增表格完整显示五列、两行多选状态、记录数量和底部操作。

## 修改文件

- `src/models/qt_ai_chat.py`、`src/services/qt_ai_chat.py`
- `src/ui/qt/ai_chat_dialog.py`、`src/ui/qt/ai_chat_controller.py`、`src/ui/qt/ai_session_manager_dialog.py`
- `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`
- `scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`
- 能力覆盖、操作员说明、迁移计划和进度、工程状态、开发日志、验收基线

## 复验命令

```powershell
python scripts/run_tests.py test_ai_session_deletion test_ai_conversation test_ai_session_router test_ai_record_titles test_qt_workspace_adapter test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_ai_session_manager_verified
```

## 验证结果

- 159 项相关回归通过，覆盖 Qt 跨项目选择拒绝、批量子会话忙碌时整批保留、事务清理子记录、持久化重开、其它项目和报告保留。首轮新增测试的临时证据缺少原格式必填的 `run_id`，补齐后全组复跑通过。
- 365 份文件编译、355 份源码登记、原协议不变量、能力覆盖和 GUI 守卫检查通过。原 Tk 应用、核心服务和设备配置保全核对通过。
- 150% 原生专项通过。覆盖 Ctrl 多选、改名、取消优先、删除其它会话、当前草稿和滚动位置保留，以及点击清空后才出现的会话仍可查看。
- 最终源码在 Windows 私有桌面的 100%、125%、150% 各通过 74 项，共 222 项。每档管理 1,224 个窗口，隔离违规为零。100% 首轮早于旧时间格式的修正，补跑了该档完整套件。三档画面核对表头、多选和底部按钮，长旧时间在列内省略，悬停和确认窗验证原文保留。
- 相应自动化通过后，清理本轮 435 份截图、测试日志、结果清单和早期验证材料，共约 20.6 MiB，保留本报告。

## 待验收范围

本轮验证只操作临时项目和合成会话。目标机真实 Windows 系统 DPI、多屏及历史数据交互待验收。本轮未运行完整基线或重建 EXE。旧 Tk 会话管理入口可继续使用。
