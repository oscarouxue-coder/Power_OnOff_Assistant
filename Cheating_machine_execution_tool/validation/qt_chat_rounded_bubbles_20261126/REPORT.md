# Qt 聊天气泡圆角——离线绘制与展示专项（2026-11-26）

## 最小变更

先核对 [原左右展示](../qt_chat_bubbles_20261126/REPORT.md) 与 [宽度过渡修复](../qt_chat_bubbles_width_20261126/REPORT.md)。原 QTextBlockFormat 的矩形背景本身没有圆角属性，未写不受 Qt 文档支持的 border-radius 或改写聊天文档架构。

[现有 AiChatTranscript](../../src/ui/qt/ai_chat_transcript.py) 新增只读绘制层：每条消息标题保留独立格式标记，按它将原排版的标题/正文块分组，通过 `documentLayout().blockBoundingRect` 和原左右边距计算圆角范围；窗口 paintEvent 先调用 Qt `QPainter.drawRoundedRect`（半径最大 10），结束该 painter 后继续原 QTextEdit 的文本/选择等绘制。去掉原矩形段落底色，保留 Markdown 代码和行内代码字符格式。用户继续浅绿右侧、AI 中性浅灰左侧；相邻同角色分为各自气泡。普通消息标题间距从 9→12px、标题底部 2px；小矩形限制圆角半径。宽度规则、文本位置、原草稿尾部、系统状态、历史、模型及输入流程不改。

只改原展示文件，操作员说明、开发记录与上轮独立探针的颜色断言同步（现在检验真实圆角绘制色和无矩形刷，不把旧矩形断言当作当前实现）。原历史报告保留其当时实际结果。开工 HEAD `69887ae5f4dafdf109cb80e7a21cbeafa6f574fb`、暂存 0、已跟踪未暂存 64、未跟踪 403；展示文件开工哈希 `1ae93b76fd88a70e41c0c57adbae2f597aed5871bafb0351230694274e0d2906`。

## 实际离线证据

[独立新增探针](rounded_bubble_probe.py)：

- 使用真实 PySide6 QImage 和 QPainter 在内存画 84×44 圆角矩形。用户/助手各自中心像素等于指定角色色，四角像素 alpha 均为 0、侧面有着色；系统角色无气泡色，原段落没有矩形刷。不是正式 Qt 窗口截图。
- 合成实际 Qt 块格式及几何，验证连续两个用户消息各自形成独立右侧区域、多块助手消息单独形成左侧区域且覆盖所有正文块，垂直不重叠；原插入方法每消息一标题标记，Markdown 其余块不误合并。该几何为布局投影，不是实际 QTextDocument 或 QWidget 重新测量。

原 4 项左右格式/Markdown/流式投影及 2 项宽度、超长 40,026 字符流式/历史测试随同复验；未重复整套共享业务测试。锁定 Qt 解释器，原 `scripts/run_tests.py` 单进程仅运行上述三类探针，禁止子进程、socket 建连/发送目标、外部打开。实际输出：

```text
source_compile 3 ok
GUI_TEST_COVERAGE_OK
Ran 8 tests in 1.037s
OK
GUI_RUNTIME_REPORT: {'passed': True, 'managed_windows': 0, 'violations': [], 'isolation': 'offscreen', 'desktop': None}
prohibited_io_calls 0
```

退出 0：2 新增、6 原展示定向。QImage 像素确证的是实际圆角绘制机制；真实 Qt 窗口内背景与原生文字的叠加、滚动、选区、字体/DPI、气泡视觉比例尚未实测，不能用 QImage 结果代替这些原生证据。原窗口守卫要求私有桌面子进程，本轮明确禁止，不绕过、不生成截图。未运行完整基线；L1/L2/L3 未开展。未启动真实模型、设备、网络或外部子进程，不读凭据/真实数据，不变工具、业务、挂测、权限或规则，不 Git 写、打包、删除。

收尾：HEAD 与开工一致，暂存 0、已跟踪未暂存仍 64、未跟踪 405（新增本探针与报告）；原有非本次范围跟踪文件无变化。限定差异格式检查退出 0，仅换行提示；报告链接有效。
