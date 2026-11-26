# Qt 聊天左右布局——纯本地展示专项（2026-11-26）

## 变更内容

[AiChatTranscript](../../src/ui/qt/ai_chat_transcript.py) 沿用现有 QTextEdit、QTextCursor 和共享 Markdown 解析器，不增聊天窗口、执行能力或依赖。按真实消息角色确定段落边距与现有主题背景：用户右侧、助手左侧、其他角色中性。标题和正文对应同一消息的测量宽度；短消息收紧，宽屏限制为可用宽度约 76%，窄幅提高至 88%，长文本使用原生文字换行模式（允许无断点长词换行）。块内仍左对齐，Markdown 代码和列表保留原字号/字体/底色与缩进，在窄窗口约束额外缩进。动态窗口缩放按已保存的块格式属性重新计算边距，仅格式更新，不重新写文字或变更原草稿边界。系统提示仍在原独立状态区域，普通、补充、历史、本地证据及流式/取消正文沿原角色和时序。

生产代码仅此一份 Qt 显示文件；操作员说明及开发记录同步。没有改变模型发送、历史存储、工具、授权、设备、网络、执行引擎或输入行为。开工 `feature/pyside6-migration`，HEAD `69887ae5f4dafdf109cb80e7a21cbeafa6f574fb`、暂存 0、已跟踪未暂存 63、未跟踪 399；之前 63 个文件的哈希与上一轮结束一致。目标文件原哈希 `85882e6db50b34a67e60a7926b36a9d40b5c67b508134fd21e845267dfa6817b`。

## 定向验证

[独立探针](bubble_projection_probe.py) 使用实际 PySide6 的 QTextBlockFormat/QTextCharFormat 类型、原展示方法和记录型 cursor/document 替身（不创建 Qt 窗口）：

- 40/120/240/320/720/1000 像素的格式宽度，左右镜像边距、短消息右侧定位、长消息有可用正文宽度、原主题颜色、左对齐及窄窗缩进限制。
- 900→180→900 格式重排往返，正文、角色、Markdown 缩进和草稿边界不变。
- 用户 600 字长文本、字面 Markdown/HTML，助手标题、粗体、代码、链接、图片字面量及本地证据保持；无 anchor/链接执行。
- 普通历史、连续补充、系统提示独立、增量流式替换、保留未完成正文及切会话，旧正文前缀和顺序保持。

锁定 Qt 开发解释器单进程经 `scripts/run_tests.py` 执行 `bubble_projection_probe.ChatBubbleProjectionProbe` 和 `test_ai_chat_markdown`；子进程、外部打开、socket 建连/发送目标均设为禁止。初轮 16 项通过；最终重排测试增加后为以下实际结果：

```text
source_compile 2 ok
GUI_TEST_COVERAGE_OK
Ran 17 tests in 1.081s
OK
GUI_RUNTIME_REPORT: {'passed': True, 'managed_windows': 2, 'violations': [], 'isolation': 'offscreen', 'desktop': None}
prohibited_io_calls 0
```

退出 0。4 项为新增 Qt 格式/展示投影，13 项为既有共享 Markdown 回归（其中两项原 Tk 离屏窗口，非 Qt 原生）。分辨率数字是格式宽度参数，不是实际系统 DPI 或像素截图，不能声称已经核对实际气泡像素、原生拖动、滚动/选区或字形渲染。原 `QtTestScope` 要求 `run_gui_child(framework='qt', native_render=True)`；本轮禁止外部子进程，不绕过，也未生成 PNG。后续若另行许可，仅用真实 Qt 私有桌面的原聊天专项检查同角色气泡实际左右位置、宽窄窗口换行/代码、流式时滚动选区和历史切换。未运行完整基线、L1/L2/L3；无真实模型、设备、网络、凭据、Git 写及打包。

收尾核查：HEAD 不变、暂存 0、已跟踪未暂存从 63 增至 64（仅新增 transcript 路径），未跟踪从 399 增至 401（独立探针和报告）；原 63 个文件范围内只有明确的操作员说明和开发记录更新，其余 61 文件哈希一致。指定路径差异格式检查退出 0，只有换行提示，报告链接有效。
