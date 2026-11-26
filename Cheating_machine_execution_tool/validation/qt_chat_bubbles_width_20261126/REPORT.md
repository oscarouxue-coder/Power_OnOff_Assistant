# 聊天气泡窄宽过渡与超长字面文本（2026-11-26）

不重复 [原 17 项](../qt_chat_bubbles_20261126/REPORT.md)。只检查左右布局新增宽度规则的可量化边界及超长不中断内容。原 Qt 格式对象调用测得 viewport 318/319/320/321/340/360px 的可用正文宽度分别为 265/266/231/231/246/261px；加宽 1px 时收窄 35px，非模型或业务问题。

[单一展示修正](../../src/ui/qt/ai_chat_transcript.py) 延续窄窗末端正文限宽，直到宽屏比例计算达到该值，去除 320px 断崖；角色、颜色、文字内容、历史/草稿时序、原换行模式及系统独立状态不变。

[独立探针](long_text_probe.py) 两项：

- 调用真实 QTextBlockFormat 在 280–500px 每个整数宽度，各对用户、助手验证长消息可用宽度单调不减；319→320px 为 266→267，避免反向收窄。
- 合成 40,026 字符的不中断中文、字面 URL 及 ASCII（无真实外部地址访问），以原 `show_messages` 方法和既有记录型游标/文档替身核对窄窗流式片段→完整→终态、宽窗重新展示历史，正文精确相同、用户/AI 各保留一份、无 anchor、系统状态不混入正文、草稿被替换；测量输入最大 300 字，非正文截断。此项是格式/内容投影，不是字形换行实测。

锁定现有 Qt 解释器，原 `scripts/run_tests.py` 单进程仅运行 `long_text_probe.LongTextProbe`，否决子进程、socket 建连/发送目标、外部打开；实际输出：

```text
source_compile 2 ok
GUI_TEST_COVERAGE_OK
test_long_literal_chinese_url_and_ascii_survive_stream_and_history (long_text_probe.LongTextProbe) ... ok
test_long_message_limit_never_shrinks_across_compact_width_transition (long_text_probe.LongTextProbe) ... ok
Ran 2 tests in 0.983s
OK
GUI_RUNTIME_REPORT: {'passed': True, 'managed_windows': 0, 'violations': [], 'isolation': 'offscreen', 'desktop': None}
prohibited_io_calls 0
```

退出 0。未启动真实 Qt 窗口或子进程、不绕过原隔离；实际字形、长 URL 换行后的像素、系统 DPI、原生视觉/操作仍未验。无模型、网络、设备、数据/凭据、CLI/MCP、规则或业务修改。仅显示代码及必要开发记录、专属证据；无 Git 写、提交、完整门禁、打包或删除项目文件。
