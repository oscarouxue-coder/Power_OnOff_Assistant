# 原 Fake 挂测资源断言等待修正专项（2026-11-25）

## 变更边界

已获负责人独立授权。开工 61 个已跟踪未暂存改动与[P1 结束快照](../qt_saved_material_persistence_20261125/workspace-after.json)全部 SHA-256 一致，未发现新并行写入；[开工快照](workspace-before.json)保存路径及哈希。

仅变更 [qt_workbench_probe.py](../../tests/qt_workbench_probe.py) 内 `test_qt_saved_material_error_and_cancel_leave_active_fake_power_job_unchanged` 的原等待条件：

```python
self.wait_for(lambda: self.window.projects[0].state == 'completed'
                      and active_store.idle and not workspace.resources.owners)
```

仍调用原 `wait_for`，原有限超时 6 秒不变，原任务成功、结果项、原事件前缀、末输出、未停止、owners 为空、原历史字节、全部真实 I/O 拒绝断言原样保留。active_store 是原 Fake 任务使用的既有 CapabilityJobs；其 idle 表示原任务 worker 实际已结束，不是模型或设备动作。

测试文件 SHA-256 把这一处改动在内存中精确反向还原后，与开工哈希一致，确认没有其他测试差异。生产和设备/业务规则、引擎、权限、P0/P1 原代码不变。

## 原断言证据与进一步收尾说明

此前[P0 收口审计](../qt_p0_closeout_audit_20261125/REPORT.md)的有界原断言复现：业务 completed 已显示、owners 仍在、can_start=false；约 29.5ms 后原测试立即断言，失败退出 1，随后释放正常。自然运行通过。不是已证实的持久泄漏。

本轮初版只等 completed 和 owners 为空，100% 自然运行通过；100% 延迟时原测试本身也通过（code 0），但专属更强诊断显示 owners 在原 release 完整返回之前已清除，原断言早于 release 返回约 11.549ms（[初版完整时序](timing-held-1.json)、[初版控制台](console-held-1.txt)）。故初版额外诊断退出 1，准确保留；未弱化条件或增加超时，仅在同一处等待补充既有任务线程 idle。此是确保实际资源释放完成的更严格条件。

## 最终有界复验

[独立探针](timing_probe.py)复用原真实 Qt 用户入口和完全合成 `ControlledPipeline`，不改变原测试断言。在有界对照中仅于专属合成 owner release 入口短暂等待 GUI 真正观察到 completed 且资源未释放；最长 2 秒，仅作为诊断调度，不改变原测试 6 秒或业务执行顺序。GUI 实际原开始按钮、既有 can_start 和 parallel_power_available 均为禁用/false，才调用既有本机 start_test 入口核对拒绝。未提交 prepare 请求、Fake 执行调用数未增加；不启动新的业务。

各组均在新的 Windows 原生私有桌面、显式缩放、独立合成临时目录，禁止真实串口、HTTP、socket、外部启动入口。

| 组 | 原测试结果 | 实际占用期间再开工拒绝 | 从 release 入口到 GUI 拒绝 ms | 原 release 返回 ms | 原 worker 返回 ms | 原资源断言执行 ms |
|---|---:|---|---:|---:|---:|---:|
| 100% 自然 | 1/1，4.498s | 未刻意制造窗口 | — | 20.125 | 20.257 | 67.793 |
| 100% 有界延迟 | 1/1，4.331s | 是 | 82.632 | 99.193 | 99.324 | 113.423 |
| 125% 有界延迟 | 1/1，4.471s | 是 | 97.913 | 110.151 | 110.250 | 113.631 |
| 150% 有界延迟 | 1/1，4.318s | 是 | 236.940 | 256.764 | 256.839 | 264.386 |

三档延迟均真实观察到 completed 时 owner_held=true、can_start=false、parallel_available=false、按钮 disabled，原 start_test 返回 None、准备列表与 Fake 调用数不变。随后原 release 正常返回、worker 退出、原 owners 为空断言才执行。三档有界等待远小于 2 秒，原等待未延长。自然运行亦通过。最终四项原 unittest 均退出 0，额外诊断 pass=true，24 个原生受管窗口，隔离违规 0，受保护外部 I/O 调用全 0。

原始证据：

- [100% 自然时序](timing-natural-1-final.json) / [原测试输出](native-natural-1-final.txt)
- [100% 延迟时序](timing-held-1-final.json) / [原测试输出](native-held-1-final.txt)
- [125% 延迟时序](timing-held-1.25-final.json) / [原测试输出](native-held-1.25-final.txt)
- [150% 延迟时序](timing-held-1.5-final.json) / [原测试输出](native-held-1.5-final.txt)

对应 native-*.json 保存原生隔离报告，初版未通过的额外诊断证据保持。测试原字节编译及限定差异格式检查通过。

## 终态及局限

已完成授权的测试等待修正，不把业务结果与资源释放同时性当作契约；实际生产仍拒绝资源未释放时再次开工。短期合成 L0 通过，不能证明真实设备、所有调度、长期现场。P0A 冲突佐证、L1/L2/L3、完整基线尚未开展，本轮无 Git 写、打包、删除或实际用户数据/凭据操作。仅测试一处等待及项目要求的开发记录更新，专属验证目录保留证据，范围外改动校验见[结束快照](workspace-after.json)。
