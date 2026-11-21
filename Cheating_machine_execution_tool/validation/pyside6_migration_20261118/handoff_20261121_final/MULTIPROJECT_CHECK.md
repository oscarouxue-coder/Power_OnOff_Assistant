# Qt 多项目准入、停止与退出核查

2026-11-21。第一阶段当前允许同时打开多个项目。项目 A 的设备任务运行或收尾时，即使项目 B 使用独立的串口、网卡和电源，Qt 工作区仍会拒绝 B 启动第二个设备任务。底层资源服务已经支持两个项目同时持有互不重叠的租约。交接时应分别核对这两层。

| 入口与实际检查 | 结果 |
|---|---|
| `QtWorkspaceAdapterTests.test_qt_serial_admission_and_project_close_wait_for_safe_stop`，使用实际临时项目、Qt 工作区工作线程和原任务服务，设备引擎为 ControlledPipeline | 1 项通过，1.664 秒。A 的 CH01 与 B 的 CH08 使用独立资源。A 启动后，B 的准备请求被拒绝，B 的 `can_start` 为假，只执行一次引擎。直接关闭 A 被拦截，请求停止后 A 及其租约仍在；释放模拟引擎的停止等待后 A 才关闭，B 保持打开，租约为空 |
| `test_project_completion.StatusAndBackupTests` 的迟到完成、预备取消、中断重开、活动与未知并存、保留未知结果的核实用例 | 5 项通过，1.348 秒。已结束任务的迟到结果不能改写既有结论或其它项目；中断重开标记未知，已取消的准备记录为跳过，核实记录保留原结果。两轮测试均报告 0 个 GUI 窗口和 0 项隔离违规 |
| 直接使用原 `WorkspaceResources`、SQLite fence 和主机锁；每个测试网卡的别名、GUID 均随机生成。两个项目使用独立临时工作区数据库中的不同所有者 | 5 个断言组通过。A、B 同时持有各自网卡；B 申请 A 的同 GUID 被拒绝并返回 `resource_busy`。A 以结果未知释放后 B 自己的租约仍在，B 重用 A 的网卡收到 `host_result_unknown`。关闭服务并从原数据库重开后仍会拒绝，显式核实原所有者后才允许重用 |

独立资源的 Qt 用例通过 `scripts/run_tests.py` 的 `main` 运行并通过 GUI 离屏预检。在该测试进程中只替换模拟网卡名、GUID 和串口编号，避免与同时进行的原生批次争抢固定的 Fake 资源名。实际资源锁实现、准入判断和测试断言均保留。另核对[同批相关回归日志](related.txt)，其中 `test_other_project_cannot_acquire_same_physical_resources`、`test_stop_waits_for_engine_and_keeps_resources`、`test_unknown_result_remains_fenced_and_no_automatic_retry` 均为通过。

在独占的模拟回归时段，可从主源码目录用原固定测试资源重跑以下用例。

```powershell
python scripts/run_tests.py -v test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_qt_serial_admission_and_project_close_wait_for_safe_stop
python scripts/run_tests.py -v test_project_completion.StatusAndBackupTests.test_late_completion_cannot_resurrect_old_run_or_overwrite_other_project test_project_completion.StatusAndBackupTests.test_prepared_cancel_is_skipped_not_a_success test_project_completion.StatusAndBackupTests.test_interrupted_running_record_becomes_unknown_without_replay test_project_completion.StatusAndBackupTests.test_running_with_unknown_shows_attention_and_never_hides_unknown_count test_project_completion.StatusAndBackupTests.test_gui_reconciliation_preserves_unknown_result_without_inventing_a_verdict
```

当前全流程、升级、写参、ONU、DUT 等入口仍有跨项目设备任务的准入限制。恢复原计划中的多项目并行前，需要在软件侧覆盖独立资源并发、共享端口/网卡/OLT 冲突、停止其中一项、进程异常退出与持久保护。负责人确认可用的独占测试架后，再验实际物理映射、单/多/16 通道、设备时序及 24/72 小时运行。上述模拟测试只证明所列软件路径，本轮现场状态为待现场。
