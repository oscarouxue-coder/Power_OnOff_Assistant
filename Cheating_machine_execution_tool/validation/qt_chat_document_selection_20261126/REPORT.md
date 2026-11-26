# Qt 聊天实际内存文档选区与纯文本片段（2026-11-26）

此前 [气泡专项](../qt_chat_rounded_bubbles_20261126/REPORT.md) 与 [四状态样本](../qt_passive_four_state_samples_20261126/REPORT.md) 使用记录型游标，未验证真实文档选区。本轮确认现有 PySide6 支持在无任何 QCore/QGui/QApplication 的情况下创建 QTextDocument、禁用其布局，并使用真实 QTextCursor 和 QTextDocumentFragment。此路径没有 QWidget、窗口、系统剪贴板或原生像素，不涉及原被拒窗口守卫，不重跑旧测试。

[独立探针](selection_probe.py) 绑定原 `AiChatTranscript` 的正文插入、历史/流式更新、窄宽重排方法，使用真实 QTextDocument（`setLayoutEnabled(False)`）、真实 QTextCursor 及无窗口的尺寸/滚动替身。手工合成中文、emoji/组合字符、用户字面 Markdown、CRLF 与助手标题/粗体/代码/字面链接，系统提示独立。实际核对：

- `document.toPlainText()` 保留可见正文与角色标题，用户 CRLF 按 Qt 文档原规则规范为换行；AI Markdown 按原可见格式，不冒称复制原 Markdown 标记。
- 实际 `document.find()` 选中含 emoji/组合字符的同一子串，`selectedText()` 和 `selection().toPlainText()` 均精确等于可见选区；跨全文 `QTextCursor.select(Document)` 的纯文本片段等于 `document.toPlainText()`。
- 同一真实选区在 720→180→900 格式重排、两次草稿变化及最终未完成正文追加后仍保持原文字；旧草稿无重复，历史前缀、最终文本及实际文档角色起始标记顺序一致。

原 `scripts/run_tests.py` 单进程仅运行 `selection_probe.DocumentSelectionProbe`，外部子进程、socket 建连/发送及外部打开均设为禁止。实际输出：

```text
GUI_TEST_COVERAGE_OK
test_real_memory_cursor_selection_and_plain_text_through_reflow_and_stream (selection_probe.DocumentSelectionProbe) ... ok
Ran 1 test in 0.890s
OK
GUI_RUNTIME_REPORT: {'passed': True, 'managed_windows': 0, 'violations': [], 'isolation': 'offscreen', 'desktop': None}
prohibited_io_calls 0
```

退出 0。未发现局部显示缺陷，没有修改生产代码或既有测试。真实鼠标拖选、键盘复制、系统剪贴板、字形与 DPI/实际窗口视觉仍未验收；不声称 QTextDocumentFragment 等于系统剪贴板实测。无子进程、真实模型、设备、网络、凭据、CLI/MCP、执行链路、权限、业务或完整门禁。
