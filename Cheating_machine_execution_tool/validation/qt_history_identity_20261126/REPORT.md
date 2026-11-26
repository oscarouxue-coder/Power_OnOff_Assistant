# Qt 历史列表、所选身份及详情——合成专项（2026-11-26）

## 审计边界

此前提出的「第 1 条、详情 101」只作为线索。在本仓库相关状态、开发记录及阶段报告中没有定位到与该句对应的确切原始测试或栈，不据此认定故障存在。

实际源代码区分四类列表：[Qt 会话服务](../../src/services/qt_ai_chat.py) 会话列表全量读取，消息每页 120 条；[Qt 诊断报告](../../src/services/qt_ai_reports.py) 显式 `reports(limit=None)`，没有列表翻页入口；[任务历史](../../src/services/qt_log_history.py) 每页 50 个任务、日志每页 60 条；[已保存留存报告](../../src/services/qt_power_logs.py) 每批最多 64 个保存记录、整批读取而非分页，超限拒绝。不能把后三者的不同上限称为统一分页。界面使用实际 ID 或报告对象，不凭显示名称、行号推断身份。

## 直接合成证据

[独立探针](history_identity_probe.py) 使用锁定 Qt 开发解释器、临时 SQLite/文件和既有合成夹具，调用实际本地服务、控制器回执判断和相关 Qt 显示方法；将组合框、列表、文本控件替换成明确的纯内存显示替身，不创建窗口或工作台。没有模型、网络、设备、外部命令和子进程。未修改生产路径或既有测试。

| 用例 | 实际覆盖 | 结果 |
| --- | --- | --- |
| `test_conversation_list_past_100_and_paged_messages_keep_selected_id` | 125 个同名会话另加 3 个原夹具会话，两个指定会话各 123 条合成消息；最新 120 条、旧页 3 条、按 ID 切换会话并返回，旧代次快照被现有 UI 判断拒绝 | 通过 |
| `test_report_list_over_100_exact_id_detail_and_closed_window_late_response` | 同项目 125 个同名诊断报告，各 ID 持有独立合成正文；首项、编号 100 的指定项、刷新保留原选中及详情 ID，旧窗口迟到/重复响应被控制器丢弃 | 通过 |
| `test_task_pages_select_actual_first_id_and_batch_reports_do_not_cross` | 同项目 103 个任务，每页 50，实际第一页/下一页/返回/选择第二项，详情事件的项目/任务 ID 精确对应；另一个项目同任务 ID 不混入；旧请求复送与源代次变化时迟到结果作废。两个原批次分别保存 64 与 2 个合成报告，同一批 64 项保存时间/通道标签完全相同而报告 ID 各异，超过上限拒绝；切批次后旧报告回执不显示，独立记录正文与定位一致，禁止原日志重读 | 通过 |

最终单进程 `scripts/run_tests.py` 的 `main(['history_identity_probe.HistoryIdentityProbe','-v'])` 仅运行上述三项。静态 GUI 覆盖预检正常，禁止 `subprocess.Popen`、`os.system`、socket 建连/发送目标以及外部打开。实际输出：

```text
GUI_TEST_COVERAGE_OK
test_conversation_list_past_100_and_paged_messages_keep_selected_id (history_identity_probe.HistoryIdentityProbe) ... ok
test_report_list_over_100_exact_id_detail_and_closed_window_late_response (history_identity_probe.HistoryIdentityProbe) ... ok
test_task_pages_select_actual_first_id_and_batch_reports_do_not_cross (history_identity_probe.HistoryIdentityProbe) ... ok
Ran 3 tests in 6.064s
OK
GUI_RUNTIME_REPORT: {'passed': True, 'managed_windows': 0, 'violations': [], 'isolation': 'offscreen', 'desktop': None}
prohibited_io_calls 0
```

退出码 0。首轮误按整个探针模块发现测试，导入的两个原 `TestCase` 别名也被 unittest 收集，输出中已有 11 项原显示测试及 21 项旧历史测试通过，随即中断（退出 1，无完整汇总或最终 I/O 计数）；不能把它们计作本轮新增验证，也未重复执行无正文取消历史分页探针。已把夹具改为模块引用并以明确新增类复验，最终只计上述 3 项。没有外部操作，首轮亦设置相同 I/O 否决。

## 结论与限制

未在合成读取和显示投影层复现列表身份与详情错配，因此不修生产代码。组合框替身模拟标准首项成为当前项，不能代替真实 Qt 控件的选中、信号顺序、焦点及布局；这些原生实际行为仍待独立许可后在原私有桌面验证。未执行完整门禁，未形成 L1/L2/L3 结论。

工作区开工 HEAD `69887ae5f4dafdf109cb80e7a21cbeafa6f574fb`、`feature/pyside6-migration`、暂存 0、已跟踪变更 63、未跟踪 394；原 63 文件哈希与上一轮相同。仅新增本探针和本报告，未写 Git、打包或删除项目文件。
