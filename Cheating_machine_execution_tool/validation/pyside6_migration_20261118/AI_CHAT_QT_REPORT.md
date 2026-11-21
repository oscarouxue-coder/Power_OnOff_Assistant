# Qt 普通问答与项目会话历史

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 5。

## 审计与迁移

旧 Tk 的空白普通问答由 `AiConversationService.create_blank_session` 创建，通过原项目库保存会话与消息，绑定创建时的模型。Qt 同样使用原会话、项目模型存储、上下文预算、模型客户端及流式处理。项目库和共享账号仍采用原格式。材料可能随问题发送给已选供应商，使用前请核对模型设置和材料内容。

主工具栏和项目详情新增「AI 诊断」入口。会话窗支持新建普通问答、停止本轮、查看上下文用量和历史分页。会话右键调用原标题、删除和文本材料服务。已有电脑、设备、批量及平台会话按原目标显示历史。继续这些诊断使用原入口。Qt 普通问答请求的模型工具列表为空。

各项目的窗口、历史和输入独立。新建或切换会话时，窗口保留未发送的文字。关闭会话窗口可重新打开查看在途回复。关闭项目或退出时先取消模型请求，等待原工作线程结束，再关闭项目库。模型和会话读写在后台执行，界面沿用工作台的刷新定时器。

## 修改文件

- `src/models/qt_ai_chat.py`、`src/services/qt_ai_chat.py`、`src/services/qt_workspace_adapter.py`
- `src/ui/qt/ai_chat_controller.py`、`src/ui/qt/ai_chat_dialog.py`、`src/ui/qt/main_window.py`、`src/ui/qt/project_detail.py`、`src/ui/qt/workspace_controller.py`、`src/ui/qt/model_settings_controller.py`
- `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`
- `PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`、`CAPABILITY_COVERAGE.md`、`.claude/plans/pyside6-migration.md`、`MIGRATION_PROGRESS.md`、`line_check_assistant_README.md`

## 验证命令

```powershell
python scripts/run_tests.py test_qt_workspace_adapter test_ai_conversation test_ai_session_router test_ai_session_deletion test_ai_context_budget test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_ai_chat_final
```

原生初测触发了原有上下文预算检查。合成模型的示例容量提高到 65,536 Token 后继续验证。真实模型的配置、预算规则和请求路径沿用原有实现。新增验证使用临时项目和模拟客户端，覆盖会话历史、项目隔离和工作线程收尾。

参考图展示工作台和项目详情。新增会话窗口沿用工作台字体、颜色和按钮样式，左右分栏显示记录和消息，并按可用工作区调整初始大小。此前 Qt 无会话窗口。

## 验证结果

- 154 项相关回归通过。覆盖原模型绑定和项目隔离、旧电脑会话权限、导入材料及保留原始文件、消息分页、停止和关库顺序。
- Windows 私有桌面 100%、125%、150% 各通过 66 项，共 198 项。每档管理 1,174 个 Qt 顶层窗口，隔离违规为零。会话用例验证两个正常入口、发送、流式显示、关闭窗口后重开、切换后的草稿、项目隔离及工作区尺寸约束。100% 完整套件额外补跑，覆盖窗口尺寸和草稿的最终代码。150% 实际截图
- 352 份文件编译、342 份源码登记、能力覆盖、GUI 守卫覆盖、原协议及旧核心源码保全检查通过。
- 确认最终回归通过后，清理本增量的 404 份截图、日志和结果文件，包含已被成功复验替代的失败证据。保留本报告和一张 150% 原生界面截图。

## 待验收范围

Qt 设备目标选择、工具、审批、报告和平台会话入口继续按第一阶段原计划迁移。真实模型连接、实际 DPI 和多屏、真实设备及长挂仍待现场验收。本轮范围为源码及自动化，未重跑完整基线或重建 Windows 包。
