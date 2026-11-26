# 已保存报告全部损坏——离线补证（2026-11-26）

此前 [P1 服务/Qt](../qt_saved_material_persistence_20261125/REPORT.md) 与 [跨进程原生](../qt_p1_p2_remaining_l0_20261125/REPORT.md) 已验有效+损坏并存、无报告的其他项目；未找到全部损坏且有效数为零的独立展示投影，因此只补该边界。

[独立探针](all_corrupt_probe.py) 创建同一临时项目的三个合成批次（有效、两份全部损坏、没有保存目录），调用原 `read_material_reports`，确认分别为 `1/0`、`0/2`、`0/0`（有效/无法读取）。两份损坏为独立创建的截断 JSON 和错误摘要文件，原字节未改变。同一 display 替身先执行真实 `SavedMaterialReportsDialog._show_report` 展示有效原 ID/正文，传入空选中后真实方法清空正文；禁止源资料读取的断言调用 0。此为本地读取+显示方法，不声称原生窗口信号已执行。实际新窗口的反馈字符串按源代码显示「已保存 0 份；无法读取 2 份」，原生显示仍待独立验证。

原 `scripts/run_tests.py` 单进程入口，仅运行 `all_corrupt_probe.AllCorruptSavedReportsProbe.test_all_corrupt_batch_has_no_report_or_stale_detail`。外部进程、socket 建连/发送目标和外部打开均设为禁止。实际结果：

```text
GUI_TEST_COVERAGE_OK
test_all_corrupt_batch_has_no_report_or_stale_detail (all_corrupt_probe.AllCorruptSavedReportsProbe) ... ok
Ran 1 test in 1.039s
OK
GUI_RUNTIME_REPORT: {'passed': True, 'managed_windows': 0, 'violations': [], 'isolation': 'offscreen', 'desktop': None}
prohibited_io_calls 0
```

退出 0；仅 L0 本地合成读取+显示投影。没有生产/既有测试或共享文档改动，没有外部子进程、真实模型、设备、网络、用户数据/凭据、Git 写、打包或完整门禁。未复现需要修代码的缺陷。
