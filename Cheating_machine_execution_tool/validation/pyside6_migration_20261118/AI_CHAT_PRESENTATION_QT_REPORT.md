# Qt AI 会话排版、状态与流式显示

2026-11-21，DUTPilot V1.3.0 第一阶段，原计划 Phase 5 和 Phase 6。

## 审计

Tk 对话将助手 Markdown 正文、用户原文和最新系统状态分别显示。同一会话流式回复时只替换当前回复区。Enter 与 Ctrl+Enter 走原发送入口，Alt+Enter 插入换行。Qt 此前在回复变化时重设整个纯文本区，将系统状态混入正文，输入框沿用控件默认键行为。

## 实施

将原 Markdown 解析提取为 Tk 与 Qt 共用的纯函数。Qt 用原片段展示标题、加粗、列表、引用和行内或多行代码，用户正文继续显示原文。原规则保留未支持标记，链接、图片和 HTML 直接显示为文字。Tk 渲染和原解析定义的语法树均一致。

当前会话的最新系统状态在正文之外显示，并随实际记录更新。读取历史页时继续使用当前会话最新状态；上下文容量仍在独立容量区。流式更新和末尾追加正式回复时，只更新末尾区域，保留已读正文、选区和滚动位置。切换会话或读取不同历史页时重新显示对应内容。快捷键沿用当前 Qt 发送入口及准入规则。

## 修改文件

- `src/utils/ai_chat_markdown.py`、`src/ui/ai_chat_markdown.py`、`src/ui/qt/ai_chat_transcript.py`、`src/ui/qt/ai_chat_dialog.py`
- `src/models/qt_ai_chat.py`、`src/services/qt_ai_chat.py`
- `tests/qt_workbench_probe.py`、`tests/test_qt_workspace_adapter.py`
- `scripts/verify_baseline.py`、`scripts/verify_qt_migration.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json` 和能力覆盖文档
- 操作员说明、迁移计划和进度、项目状态、开发记录和验收基线

## 复验命令

```powershell
python scripts/verify_baseline.py
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_chat_format_verified
```

## 已核对

- 150% 原生专项 3 项通过。首轮新用例未像实际控制器一样解除忙碌状态，键盘断言未触发，补齐测试装配后通过。核对 Markdown、原样链接与标记、独立状态、流式更新和最终回复追加时保留选区、快捷键、原普通问答与报告会话。
- 原解析与 Tk 渲染的 9 个定义语法树一致。372 个文件编译、362 个源码登记项、能力覆盖、GUI 守卫、原协议及业务实现保全检查通过。
- 锁定 CPython 3.9.10 环境执行标准完整基线，3,211 项测试全部通过，覆盖 239 项指定用例，脚本返回 `ALL CHECKS PASSED`。新回归核对了用户翻阅消息时，独立状态仍取最新非容量系统记录。
- 单独从 Qt 环境导入共享解析和会话排版模块，确认未载入 Tk。
- Windows 私有桌面 100%、125%、150% 各通过 82 项，共 246 项。每档管理 1,773 个窗口，隔离违规为零。三档对话截图为 940×640、1175×800 和 1410×935 像素，150% 高度受桌面可用区域约束。
- 验证通过并汇总后，将本轮 356 份截图、测试日志、结果清单和早期失败证据移入 Windows 回收站，共约 17.7 MiB。
- 150% 截图核对标题、加粗、代码、状态与底部输入。参考图没有 AI 对话独立窗口，继续使用 Qt 项目窗口现有主题和布局。

## 待验收范围

本轮用脱敏样例、模拟流式回复和原生按键事件验证。实际 Windows 输入法、真实模型、设备和平台仍待现场验收。全量迁移及现场验收完成后再构建最终交付包。
