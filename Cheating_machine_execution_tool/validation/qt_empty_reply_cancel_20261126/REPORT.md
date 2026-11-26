# Qt 普通聊天无正文取消历史（2026-11-26）

## 范围

原工作区 `feature/pyside6-migration`，HEAD `69887ae5f4dafdf109cb80e7a21cbeafa6f574fb`；开工暂存 0，63 个已跟踪未暂存改动的哈希与 [上一轮收尾快照](../qt_p1_p2_remaining_l0_20261125/workspace-after.json) 一致。负责人批准普通会话本地持久化终态，禁止外部子进程、真实模型、设备、网络、命令及完整门禁。

## 最小差异

[Qt 会话服务](../../src/services/qt_ai_chat.py) 沿用已有 `chat_sessions` JSON，只在原 `_abort_draft` 已实际结束、具有真实本地回复 ID 且无任何正文、状态取消、范围为本地普通问答时保存 `last_empty_reply_cancel`。它保留会话、原用户消息行、本地回复 ID、取消及无正文标记；不复制用户正文，不新建助手消息、协议分组、工具或模型历史，不修改表结构。现有活动区原本仅呈现最近活动，因此本字段只保存最近一条取消回执；新问题或回复使旧回执不得匹配，重复文本仍按不同消息行区分，不回填旧历史或模拟 ID。

历史恢复从原会话 JSON 和实际最新非系统消息核对匹配后投影既有 `ChatActivityView`，并显示「历史记录：没有生成可留存正文」。在途请求、切会话、旧页、不同范围或损坏记录不恢复旧回执。写入失败保留原当次内存终态并反馈本地保存失败，连日志写入异常也不干扰原取消收尾。不改变部分正文已取消的原保存行为、连续诊断补充回执、调用或权限。

## 本轮实际验证

[直接相关测试](../../tests/test_qt_ai_turn_display.py) 以完全合成临时 SQLite、显式假加密对象及不创建后台服务的会话对象，调用原草稿分配、取消收尾、持久存储和 Qt 展示快照方法。不开 Qt 窗口；不启动真实模型、设备或子进程。关库并重开新的 `DiagnosticStore` 及全新展示对象，检查不从原内存获取回复 ID；原用户及协议分组内容保持，不产生助手消息。

| 测试 | 结果 |
| --- | --- |
| 原 ID、关闭/重开、会话隔离、重复及迟到草稿 | 通过 |
| 同正文不同消息行、新问题无 ID、缺失/畸形/错误会话或状态 | 通过 |
| 部分正文原语义、无正文失败及非普通会话不新增持久回执 | 通过 |
| 保存失败与额外日志失败，停止仍收尾、不冒称持久化 | 通过 |
| 既有 Qt 展示和补充回执投影 | 7/7 |
| 既有上下文计算及取消/重开语义 | 6/6 |

单进程使用 `scripts/run_tests.py` 的 `main` 入口，运行 `test_qt_ai_turn_display`、`test_ai_context_usage.UsageMathTests`、`test_ai_context_usage.UsageConversationTests.test_cancel_keeps_completed_usage_and_restart_recovers_it_without_recomputing`、`test_ai_context_usage.UsageConversationTests.test_restart_marks_interrupted_request_cancelled_and_recovers_previous_result`。外部 I/O 否决覆盖 `subprocess.Popen`、`os.system`、socket 建连/发送到目标及外部打开；相关旧测试使用原 Fake 传输。实际输出：

```text
source_compile 2 ok
GUI_TEST_COVERAGE_OK
Ran 17 tests in 2.820s
OK
GUI_RUNTIME_REPORT: {'passed': True, 'managed_windows': 0, 'violations': [], 'isolation': 'offscreen', 'desktop': None}
prohibited_io_calls 0
```

退出码 0；初轮 11 项也通过。未生成过程 PNG。此为 L0 服务/展示投影及同进程数据库重开，不是原生窗口、跨进程、真实模型、设备或长期现场验收。禁止外部子进程，因此不启动原生私有桌面子进程，不绕过其门禁；完整基线未运行。旧记录缺少 ID 仍未知，不宣称实际模型远端派发或采纳。

结束核查：HEAD 与开工相同、暂存 0、已跟踪未暂存仍为 63 个文件；与上一轮保存的 63 个文件哈希比较，只有本报告明确列出的两份源码/测试文件和 `DEVELOPMENT_LOG.md` 变化。未跟踪文件由 391 增至 392，新增本专项报告；链接有效，指定路径 `git diff --check` 退出 0（只有已有换行格式提示）。未提交、打包、删除项目文件或操作真实环境。
