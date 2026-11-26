# P0 与两轮生命周期修复收口审计（2026-11-25）

## 1. 原 Fake 挂测完成后的资源断言：有界因果对照

**结论：已证明原测试存在“界面显示任务完成”比“资源所有权释放完毕”更早被观察到的可达时序；未证明持久资源泄漏或实际设备业务错误。** 首次 125%/150% 两次无测时失败的确切线程调度没有原始时序数据，不能追溯完全相同根因，但本轮复现同一断言且提供明确解释。没有改变原测试或生产逻辑。

生产只读证据：

- [capability_jobs.py](../../src/services/capability_jobs.py) 190–228：原 runner 返回后，先记 project_status 终态、任务库终态及末事件，再在 finally 资源 release，最后移除控制对象。业务结果终态不等于整个后台线程退出。
- [qt_execution_adapter.py](../../src/services/qt_execution_adapter.py) 655–667、693–712、773–789：从实际任务库终态映射 completed；是否允许新开工另由 idle、closing 等已有条件限制。
- [qt_workspace_adapter.py](../../src/services/qt_workspace_adapter.py) 1434–1437 及 [workspace_controller.py](../../src/ui/qt/workspace_controller.py) 1308–1328：工作区发布项目快照，GUI 原轮询接收。
- [workspace_resources.py](../../src/services/workspace_resources.py) 410–425：原 owners 移除、持久状态和 guard 正常释放。原断言检查的是当前任务 owners，不是所有常驻通道登记 registrations。
- [qt_workbench_probe.py](../../tests/qt_workbench_probe.py) 6521–6533：原测试释放 Fake 正常完成信号，等待 UI state==completed，核对成功结果/事件前缀，再立即断言 owners 为空；没有独立等待资源释放。

[专属 timing_probe.py](timing_probe.py) 两次独立 Windows 私有桌面 125% 合成运行，保留原测试名称及断言；第一轮只观察，第二轮仅在专属 Fake 资源 release 入口等待原断言观察完毕，最长 2 秒，未改变原代码顺序或已存在业务/权限，随后原 release 正常执行。实际第二轮额外等待约 29.8ms（非等待满 2 秒）。全部真实网络、串口、外部进程及外部打开保护入口调用为 0；各 6 个受管窗口，隔离违规 0。两次即止，未无限重跑。

以下以各自 resource_release_enter 时间为 0 ms（负数为之前，非业务总工期）：

| 事件 | 无人为等待 ms | 有界等待 ms |
|---|---:|---:|
| 项目状态 succeeded 持久更新返回 | -760.392 | -773.907 |
| 原资源释放入口 | 0.000 | 0.000 |
| 实际任务库读取 succeeded | +315.617 | +1.044 |
| 工作区发布 completed 快照 | +318.053 | +2.358 |
| GUI 首次观察 completed | +440.212 | +28.975 |
| 原 owners 为空断言 | +440.893 | +29.454 |
| 原资源释放返回 | +11.829 | +56.436 |
| 原任务 worker 返回 | +11.897 | +56.510 |

- 自然运行：原断言时 owners 为空，GUI completed 且 can_start=true；unittest 1/1，4.364s，退出码 0。[原输出](native-natural.txt) / [时序](timing-natural.json)。
- 有界复现：任务库 succeeded、GUI completed、active_tasks=0，但 owner_held=true 且 can_start=false；原断言 `self.assertFalse(workspace.resources.owners)` 失败。随后原 release 返回时 owner_held=false，worker 正常退出。原 unittest 1 项、3.838s、失败 1、退出码 1 保留，未改写为通过。[失败原输出](console-held.txt) / [时序](timing-held.json)。

因此测试对结果终态与资源完全收尾的同时性作了超出当前实现契约的隐含假设；受控对照已证明这种观测差异足以解释同一失败机制，并且本次资源安全准入仍未放开。不能据此证明所有外部生产设备路径均正确，也不能把先前失败追溯断言为相同具体调度。**当前不修改。** 若负责人认可该测试意图是“结果已完成且最终在有界时间内已安全释放”，可另行批准只将等待条件明确区分任务结果与资源释放，仍保留原成功/输出/历史数据及最终 owners 为空断言，并核对释放前不可再次开工。若产品定义坚持一显示 completed 就必须已经释放资源，则属于独立业务展示契约决策，不能擅自重排原资源释放或测试引擎。

## 2. P0A–D 当前代码和历史 L0 证据

本轮只进行了上述两次对照及只读代码核对；以下历史专项数值不是本轮重新执行次数，也不能相加等同完整基线。

| 项 | 实际存在的功能 / 代码 | 已有历史合成验收 | 缺口、状态 |
|---|---|---|---|
| P0A | [qt_power_logs.py](../../src/services/qt_power_logs.py) 单通道只读两类留存资料；[qt_workspace_adapter.py](../../src/services/qt_workspace_adapter.py) 独立历史请求；[log_history_dialog.py](../../src/ui/qt/log_history_dialog.py) 项目/任务/运行/通道范围实际报告、引用、观察及未知 | [P0A 证据](../qt_saved_material_summary_20261125/REPORT.md)：G0 40 项服务、18 项原生；最终服务 49 项、迁移契约 5、三档原生各 20。实际可读、缺失及读失败分别呈现并保留源字节 | **真正相互冲突的同一事实佐证改变报告**未有独立验证；不把 Ping 与 WiFi 等级差异当成冲突。不是实时/root-cause/任意资料工作流 |
| P0B | 同一明确历史批次多选通道、独立结果及部分失败；qt_power_logs 内固定 `_MATERIAL_READ_WORKERS=2` 队列；项目/任务/运行/选择匹配、取消/迟到作废 | [多通道](../qt_saved_material_batch_20261125/REPORT.md) 58 项相关、三档各 23；[真实双文件重叠](../qt_saved_material_parallel_20261125/REPORT.md) 59 项相关、三档各 5，双读取阻塞和实际文件关闭证据 | 同批次选定留存文件、非通用代理；缺失与失败独立。不从其他项目/运行补数据 |
| P0C | 同一正式 Qt 入口由原后台历史读取队列负责读取、取消和窗口回执；原业务执行独立，无报告触发设备业务 | [在途 Fake 组合](../qt_saved_material_active_fake_20261125/REPORT.md) 三档各 1 原生；后续并发及两轮生命周期回归原用例亦验证实际 Fake 持续运行、结果/输出/资源在报告失败/取消中保持并正常结束。本轮自然 1/1、受控时序同一断言失败 1/1 | 原完成/资源释放观测时序缺口见第 1 节；没有真实设备通过结论，不改测试以隐藏失败 |
| P0D | [ai_diagnostic_task.py](../../src/services/ai_diagnostic_task.py)、[ai_store.py](../../src/services/ai_store.py) 的本地消息/会话/轮次/请求关联及补充回执表，原传输观察和 [qt_ai_chat.py](../../src/services/qt_ai_chat.py) 投影 | [补充回执历史证据](../qt_chat_channel_evidence_20261125/REPORT.md#连续诊断补充实际派发回执p0-后续)：268 项相关、三档各 21；后续 P0B 三档各 23 含原生补充复验。五态、同文不同 ID、裁剪、迟到快照、取消/跨会话及持久化核对 | 原“已带入下一次请求”仅证明该完整条目随原请求派发尝试且获有效响应的本地观察，不等于已被模型采纳或推理；L1 未验收 |

此前普通 Qt 本地明确 CH 掉线证据及正文/事件状态展示也已实现；[专项](../qt_chat_channel_evidence_20261125/REPORT.md) 保留明确项目/运行/通道边界，原文和事件区别、旧状态拒绝、正常聊天/原按钮及历史出口；历史最终状态展示 189 项相关、三档各 22。未扩设备、网络、模型调用能力或通用执行工作流。

## 3. 两轮已批准生命周期修复

| 范围 | 历史实际修复与验收 | 目前结论 |
|---|---|---|
| adapter/service/writer | [服务层修复及证据](../qt_workspace_handle_fix_20261125/FINAL_REPORT.md)，只在合法业务关闭并完成末条归档后解除失效回指；独立 adapter、WorkspaceService 各 20 轮正常释放，末次额外 GC 397→397；历史 61 项、160 轮、三档原生相关通过 | 服务终态修复仍在当前代码；未提前释放延期日志、失败归档或活跃任务 |
| UI controller 12 个反向引用 | [只读定位](../qt_workspace_controller_cycle_audit_20261125/REPORT.md) 80 轮；[最终修复](../qt_workspace_controller_cycle_fix_20261125/REPORT.md) 原正常任务收尾、更新末条日志、窗口及子 QObject 真销毁后才解除无效引用。历史 44 项最终通过、126 轮：空工作区 30/30 为 706–710、终 GC 706→706；含报告 30/30 为 708–721、23 类弱引用正常归零；固定窗口 60 轮 753→770、关闭后 749；实际 app loop/显式销毁各 3 轮 | 已确认的引用循环消除于 L0；报告复合组末次额外 GC 708→703 的 **5 个未知总句柄仅为现有记录**，类别及根因未知，未进一步研究或推定。不能宣称所有资源永久无泄漏 |

没有生产强制 GC，也没有把短时重复视为长期现场。两轮修复均保持原关闭拒绝、活跃任务、安全收尾、延期日志、失败反馈和重复关闭路径；第二轮首次并行时两档原 Fake 断言失败，串行原断言各通过，今日进一步有界复现详见第 1 节。

## 4. 全量门禁及验收状态

- L0：完成上述定向代码及 Synthetic/Fake 行为、窗口隔离和资源证据；已明确真正冲突佐证与原结果/登记释放观测时序的验证缺口，5 个未知句柄不作归因。
- L1 真实模型、L2 实际设备、L3 长时间/现场运行均未开展；操作员自己的 Qt 工作台显示阅读和现场验收尚待。用户的本地分析不含通用执行工作流、命令、模型工具或真实外部访问。
- [完整基线前置](../qt_saved_material_active_fake_20261125/baseline-preflight.txt)：测试发现会包含真实本机回环 TCP/UDP、WebSocket、浏览器等用例，窗口隔离不能证明全部 I/O 为 Fake。本次按明确要求不运行完整门禁、不更改或绕过。后续必须先明确已冻结对应并行工作区、允许的真实/隔离边界及完整门禁前置，在规定原入口实际运行且通过后才有本工作区全量结论；原提交 3,444 项通过仅历史。不得以专项或跳过代替提交/打包的原门禁。

## 5. Git 与其他工作保护

本轮只读 Git 及合成验证目录写入，不修改生产/现有测试/共享文档，不暂存、提交、推送、打包或删除；无真实数据、凭据、模型、设备或网络。工作区快照见 [开工](workspace-before.json)、[收尾](workspace-after.json)。原有验收与并行修改未回退或覆盖。本轮新增文件均位于本专属验证目录。

实际收尾：分支 `feature/pyside6-migration`，HEAD `69887ae5f4dafdf109cb80e7a21cbeafa6f574fb`；暂存 0；已跟踪未暂存变更 61 文件，当前未跟踪 293 文件（开工 283，新增 10 文件全部本专属目录，包含首尾快照）。所有 61 个开工已修改文件收尾 SHA-256 一致，未见范围外新修改。
