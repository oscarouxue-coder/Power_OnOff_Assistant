# 无正文取消历史分页——独立合成补证（2026-11-26）

## 本次范围

不重复此前 [17 项定向测试](../qt_empty_reply_cancel_20261126/REPORT.md)。只补之前未独立确认的真实数据库重开与历史分页组合：已保存的最后一次取消可在最新页恢复，浏览较早的分页不能显示当前问题的回复编号，再回最新页仍是同一个编号。当前会话最近系统提示仍遵循原显示规则，本次只核对活动及上下文投影，不改旧页语义。

[独立探针](receipt_pagination_probe.py) 复用既有纯本地合成夹具，创建超过实际分页上限的历史消息、一个已分配真实本地回复 ID 的无正文取消；正常关闭临时 SQLite 后新建 store 和会话对象，验证最新页有原 ID、旧页无活动 ID 和当前用量、返回最新页恢复精确原 ID，保存回执、原消息及代次保持一致。未创建窗口、工作区、后台模型服务或外部进程；没有真实数据或凭据。

## 实际结果

使用原 `scripts/run_tests.py` 的单进程入口仅执行 `receipt_pagination_probe.ReceiptPaginationProbe.test_saved_empty_cancel_is_current_page_only_after_real_store_reopen`，原覆盖预检生效，否决 `subprocess.Popen`、`os.system`、socket 建连/发送目标及外部打开。实际输出：

```text
GUI_TEST_COVERAGE_OK
test_saved_empty_cancel_is_current_page_only_after_real_store_reopen (receipt_pagination_probe.ReceiptPaginationProbe) ... ok
Ran 1 test in 1.345s
OK
GUI_RUNTIME_REPORT: {'passed': True, 'managed_windows': 0, 'violations': [], 'isolation': 'offscreen', 'desktop': None}
prohibited_io_calls 0
```

退出 0。此为直接 L0 合成服务/展示快照证据，不是 Qt 原生窗口、跨进程、真实模型、真实设备或长期现场验收。

## 完整回归与工作区

本次开工仍是 `feature/pyside6-migration`，HEAD `69887ae5f4dafdf109cb80e7a21cbeafa6f574fb`，暂存 0，已跟踪未暂存 63、未跟踪 392；所有 63 个文件相对上一轮修复结束哈希一致。只读检查 `validation` 中晚于上一轮报告的文本证据，开工未发现更新；未找到最新 3,473 项完整回归的原始 `Ran 3473 tests` 及失败汇总。同一路 [原报告](../power_channel_sharing_20261125/REPORT.md) 依旧记录 6 失败、14 错误，不能确认精确栈、不能把旧通过记录当作最新完整门禁。未重跑完整门禁。

本次未修改生产代码、既有测试、共享文档、规则、引擎或权限。新增仅独立探针及本报告，无 Git 写、打包、删除项目文件或真实外部操作。
