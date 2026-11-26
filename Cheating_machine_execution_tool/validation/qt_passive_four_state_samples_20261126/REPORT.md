# 四类手写合成记录被动展示验证（2026-11-26）

只使用手工编写、与任何真实输出或外部应用无关的静态消息。原 [聊天布局验证](../qt_chat_rounded_bubbles_20261126/REPORT.md) 覆盖 Markdown、流式及角色，但未独立覆盖四种历史状态与 emoji/组合字符、LF/CRLF、无末尾换行的组合，因此仅新增该项。没有 ZCode 连接、导入、解析或执行能力，也没有任何生产修改。

[专属探针](passive_samples_probe.py) 将两条连续用户消息及四条连续助手消息按原角色排列：完整回复、失败保留正文、取消部分正文、旧记录未知。用原 Qt 普通活动投影核对前三类现有状态和真实样本本地 ID；未知不构造请求 ID、使用独立手写未知状态提示。原文字展示方法使用真实 Qt 字符/块格式与记录型游标替身，验证：

- 中文、emoji 序列（女程序员及笑脸）、组合 `e` 加重音各 5 次完整保留；用户 LF/CRLF 字面正文、AI CRLF 代码载荷及无末尾换行的末行存在。
- 正常闭合代码按既有 Markdown 删除标记并保持代码文字，未闭合代码围栏按现有规则显示字面量；HTML 图片标签及 URL/链接字面原文保留，所有字符格式均不是 anchor，未激活链接。
- 四个状态与正文分开；失败或取消仍展示对应的原部分正文，未知不冒充取消或完成；两个相邻用户和四个相邻助手按原顺序各有一个气泡起始标记，未合并、未重排或修改输入消息。

原 `scripts/run_tests.py` 单进程入口仅运行 `passive_samples_probe.PassiveFourStateSamplesProbe`，禁子进程、socket 建连/发送及外部打开。实际结果：

```text
GUI_TEST_COVERAGE_OK
test_four_handwritten_states_preserve_unicode_literal_content_and_order (passive_samples_probe.PassiveFourStateSamplesProbe) ... ok
Ran 1 test in 0.893s
OK
GUI_RUNTIME_REPORT: {'passed': True, 'managed_windows': 0, 'violations': [], 'isolation': 'offscreen', 'desktop': None}
prohibited_io_calls 0
```

退出 0。此证据仅为既有本地被动展示投影，不是实际 Qt 窗口的字形、emoji、组合字符选区、CRLF 剪贴板或像素验收；也不是 ZCode 接入、协议或实际结果验证。没有启动子进程、模型、设备、网络、CLI/MCP、通用工具或任何真实操作，无真实数据/凭据、Git、权限、引擎或生产改动。
