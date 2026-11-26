# Qt 完整工作区剩余循环引用定位（2026-11-25）

## 结论

**本轮确认了服务层修复后完整 Qt 工作区剩余的主要责任引用：WorkspaceController 与 12 个常驻 Python 子控制器之间的直接双向强引用。** 正式 UI 关闭、业务及更新 worker 结束、日志写入器已释放回调、Qt 主窗/控制器/定时器 C++ 对象已 DeferredDelete 销毁后，这些 Python 对象仍然存留，并通过 controller.adapter 及更新日志绑定方法继续持有 adapter 和已关闭 service。

在完全关闭的隔离合成对象上，仅解除 12 个子控制器的反向 `workspace` 引用，不强制逐轮 GC，10/10 轮所有 23 类跟踪对象均不再存留；句柄稳定在 709–710，末次诊断 GC 709→709。完整正式关闭对照同样 10 轮，收尾句柄 733–801，末次额外等待后仍 778，诊断 GC 778→709（69，三个工作区引用组各约 23）。该因果对照比仅观察 GC 前后更有力。

这不是对所有 Windows 内核句柄种类的归因，也不是现场长期无泄漏保证。没有修改任何生产代码或既有测试。

## 方式与隔离

[独立探针](qt_cycle_probe.py) 复用上轮真实 Qt 合成 fixture 与项目原生 Windows 私有桌面隔离守卫，每组新 Qt 子进程，既有 run_tests 入口执行一项综合测试，各 10 轮。临时合成目录，无正式设备、模型、网络、真实配置/凭据及现场数据，所有硬拒绝外部 I/O 入口调用为 0。

- fixture：上轮空工作区测试的 cleanup，它直接停止 timer、关闭 adapter/窗口，未调用更新 executor 的正式关闭流程。
- formal：真实 MainWindow.close → WorkspaceController.request_close/poll，等待窗口关闭、adapter worker 终止且更新 executor 已关闭、timer 已停止、coordinator 清除，然后使用相同 QtTestScope 删除窗口。两个对照均从不创建项目、不打开材料报告。
- window：仅真实 MainWindow，不装配 controller。
- timer-bound / timer-closure：最小 QWidget/QTimer、对象绑定方法或捕获所有者的 lambda，连接、启动、停止并按相同规则销毁。
- backrefs / callback / resource-detach：每轮先运行完整 formal 关闭、scope 清理并验证 C++ 主窗和 controller 已销毁、日志回调已释放；之后仅在已死亡的专属合成 Python 对象上，分别进行单变量引用解除对照。不是生产修复，不在运行中窗口解除引用。

逐轮在关窗前、正常关闭后、释放 fixture 强引用后 Qt 事件泵/DeferredDelete、额外约 250ms 等待后测量；保留正常自动 GC，不逐轮显式 GC。最后处理 Qt 事件 2s+5s，再以诊断显式 GC 和额外 5s 事件处理作对照。计数均仅当前进程：psutil total handles、native threads、RSS、threading.active_count、GetGuiResources 的 GDI/USER、Qt 顶层窗、临时目录被跟踪 Python open/Path.open 文件对象。弱引用只计算存活数；引用图仅记录预先识别的合成对象之间属性名称、对象身份和引用者类型计数（不记录值、业务数据或其他进程内容）。

## 结果

| 对照 | 正常收尾总句柄范围/首末 | 最后 7s 等待→诊断 GC 后 | 末轮跟踪对象主动 GC 前 | 测量秒 |
|---|---|---|---|---:|
| 主窗独立 | 707 / 707→707 | 707→707 | 全部为 0 | 43.532 |
| QTimer 绑定方法 | 403–404 / 404→403 | 403→403 | 全部为 0 | 32.329 |
| QTimer lambda 闭包 | 403–404 / 404→403 | 403→403 | 全部为 0 | 32.406 |
| 完整 fixture（非正式 close cleanup） | 733–801 / 733→778 | 778→709 | 3 个完整引用组 | 43.735 |
| 完整正式关闭 | 733–801 / 733→778 | 778→709 | 3 个完整引用组 | 43.453 |
| 正式关闭后仅解除更新绑定日志回调 | 733–801 / 733→778 | 778→709 | 3 个完整引用组 | 44.907 |
| 正式关闭后仅解除 12 个子控制器反向引用 | 709–710 / 710→709 | 709→709 | **10/10 轮全部为 0** | 45.594 |
| 正式关闭后解除 controller.adapter 及更新绑定日志回调 | 713–721 / 713→718 | 718→709 | adapter/service/writer 及 2 个业务 executor 均为 0；3 个 UI 引用组仍存留 | 45.110 |

8 个综合原生测试通过、合计 80 轮，独立进程测量区间合计 331.066s（并非串行实际墙钟时间），208 个经管理窗口，隔离违规 0。每组结束后被跟踪 Python 文件仍打开 0，Python 线程 1，Qt 顶层窗 0。

| 对照 | 最后诊断 GC 前→后 RSS MiB | 最终 GDI/USER | 最终 native/Python 线程 | 已跟踪 Python 文件总数/仍开 |
|---|---:|---|---|---|
| 主窗 | 187.68→187.68 | 18/20 | 10/1 | 0/0 |
| QTimer 绑定 | 124.58→124.58 | 14/19 | 10/1 | 0/0 |
| QTimer 闭包 | 125.26→125.26 | 14/19 | 10/1 | 0/0 |
| 完整 fixture | 196.60→196.60 | 18/20 | 10/1 | 20/0 |
| 完整正式关闭 | 192.81→192.81 | 18/20 | 10/1 | 20/0 |
| 仅更新日志回调解除 | 195.28→192.38 | 18/20 | 10/1 | 20/0 |
| 12 个子控制器反向引用解除 | 191.50→191.52 | 18/20 | 10/1 | 20/0 |
| 两条 adapter 所有权途径解除 | 196.17→193.32 | 18/20 | 10/1 | 20/0 |

GDI/USER 是独立的 GUI 对象计数，不等于全部 Windows 进程句柄种类；native thread 计入库线程，数量不意味着相应类型仍有活动任务。RSS 是工作集，不是分配量。被跟踪 Python 文件不是所有 SQLite/OS 文件句柄。未枚举或查询其它进程/内核对象内容，**无法确认剩余句柄中各具体内核对象的类型**。

## 引用关系（已测量，不仅是源码猜测）

正式关闭后，三者 C++ 包装对象均无效：window、controller、timer；更新 executor shutdown=true、pending_work=false、timer_active=false、coordinator_cleared=true；adapter.closed=true、业务 worker 已退出、service._closed=true，writer 的 report/associate 均已解除。仅 fixture 对照的更新 executor 未执行正式 shutdown，但与正式对照完全相同的句柄序列，故不是本轮增长的必要因素。

关闭后已识别 12 个直接双向边：

`WorkspaceController.<child> → 子控制器.workspace → WorkspaceController`

- blocker_review、project_wizard
- parameter_writer、onu_query
- log_history、aging_history、channel_history、archived_logs
- model_settings、ai_chat
- app_update、feishu_repair

每个都是独立回指。GC 引用者身份确认全部 12 个子控制器字典直接拥有 controller。除此之外：

- controller.window → 已销毁的 MainWindow Python wrapper
- controller.timer → 已销毁的 QTimer wrapper
- controller.adapter → 已关闭 QtWorkspaceAdapter → 已关闭 service、writer、两个线程池
- controller.app_update → QtAppUpdate → _write_log 绑定 adapter.record_update_log

图见 [正式关闭逐轮数据](metrics-formal.json) 中 closed_graph.edges、closed_graph.referrers_by_type、formal_close、component_refs_alive；[反向引用解除](metrics-backrefs.json) 和 [两条 adapter 路径解除](metrics-resource-detach.json) 为因果证据。后者即使完整 UI 引用组继续保留，也使 adapter/service/writer 弱引用归零，额外诊断 GC 仅减少 9（约 3/组），支持大部分总句柄延迟经 UI 的 adapter 所有权传播；不把 20+3 算作不同内核类别。

仅更新日志回调解除没有改善完整引用图，所以不是单点责任或足够修复。单独主窗、QTimer 绑定方法及闭包对照均不留存；完整销毁后已测量直接 Python 回指仍存在，不能把本次问题归咎于定时器仍运行或泛化为所有 Qt signal 连接泄漏。未证明任何具体 C++ 信号实现永远不会泄漏。

## 与历史材料报告的边界

本轮 5 种完整 workspace 对照均为**空工作区，未运行任何材料报告**；log_history 等只是常驻子控制器之一。并且 [上一轮服务修复验收](../qt_workspace_handle_fix_20261125/FINAL_REPORT.md) 的固定报告窗口 60 轮为 753→770，关闭后 749，工作线程和被追踪文件均结束。原材料复合场景工作区反复重建中仍有阶段性 23–24 个/轮延迟回收。本轮空工作区直接重复了这种所有权关系，没有证据指向新材料报告读写本身。

## 建议最小修复顺序（仅待审，不实施）

1. 保持现有业务关闭、资源恢复、活跃任务等待、窗口关闭失败/拒绝路径、会话保存及更新最后一条日志原语义。不得在 begin_close 或 worker 尚在运行时解除任何子控制器引用。
2. 优先仅审查上述 12 个常驻子控制器的终态所有权，由 WorkspaceController 已有合法关闭路径、在所有 UI 子窗口及可能的回调已完成/失效后，一次性解除不再有用途的反向 workspace 引用；使用明确清单，而非遍历清空任意对象属性。本轮实验证明这一组边足以让空工作区回收，暂不需要修改 adapter/service/logger、日志业务或全局信号连接。具体安全挂点必须先验证 Qt 子控件/queued signal 的生命周期，不应简单地搬到 close request、业务 closed 事件或定时器尚未停止时。尤其本轮诊断清除是在 C++ 窗口已销毁之后，不能把它无条件提前到实际窗口仍存活的生产时点。
3. 若需保留可访问的 closed controller 供关闭状态/测试查询，应在具体验证中明确终态调用语义。不得用生产强制 GC、任意 signal.disconnect、清空 adapter 属性或修改 active callback 作为替代；两条 adapter 途径解除只是归因对照，并非推荐生产修改。
4. 保护原有真实 Qt 用户关窗、活跃 Fake 挂测、关闭被拒后继续使用、延期的末条日志、报告迟到和重复关闭路径，再复用本轮正式关窗重复及上一轮含材料的组合验收，三档原生缩放和无逐轮 GC 回收。若正常终态无法保证 UI callback 已完成，停下报告并先审该边界；不扩大至挂测引擎、业务权限或通用重构。

## 证据与工作区保持

[汇总](aggregate.json) 包含全部资源采样、每组计数和状态；[探针](qt_cycle_probe.py) 及 `metrics-*.json`、`summary-*.json`、`native-*.txt/json` 保留原始证据。正式 [native](native-formal.json) 和反向引用解除 [native](native-backrefs.json) 均为 verified private desktop，不使用 offscreen 替代原生。

[工作区前](workspace-before.json) / [后](workspace-after.json)：HEAD 69887ae5f4dafdf109cb80e7a21cbeafa6f574fb、暂存 0、追踪变更 61，快照中全部已有追踪文件 SHA-256 未变。每组服务/UI/原测试/守卫文件 15 个前后哈希一致。无生产修改、无 Git 写/提交/推送、打包或删除，仅本目录专属合成证据；没有生成过程 PNG。L0 短期合成定位，不是 L1 模型/L2 设备/L3 长期现场验收，不执行完整门禁。
