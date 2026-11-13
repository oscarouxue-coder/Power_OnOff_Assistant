# LineCheckAssistant 无响应修复与验证报告

日期：2026-11-13。交付：当前开发源码及回归证据，不构建、不发布、不提交。

## 1. 基线与证据边界

- 实际仓库为本目录，主源码为 `Cheating_machine_execution_tool/`；修复基线 `main` / `0ed92f48fc1dc89e31611d11a0970d2e3bb2f7ca`。
- `v1.2.9` 标签指向 `55fe6a14af65697e68228866b160df9831238142`。当前 main 比标签多两次提交；串口终端和底层传输在修复前与标签相同，全流程及主程序已有后续修改。构建记录说明 V1.2.9 包还包含当时工作区修改，因此标签不能代替完整构建快照。
- 本机缺少记录中的 V1.2.9 冻结归档及构建目录，未重新进行现场 EXE/PYZ 与源码一致性核对。当前修复不能被描述成已验证的 V1.2.9 二进制补丁。
- 工作区同期存在ONU管理、说明文字和测试窗口隔离修改；这些修改保留。`app.py`、测试、验证脚本及文档存在共享文件修改，审查时应按下文功能边界区分。本轮未主动改写本机配置或仓库build/dist/logs/.venv，也没有结束现场进程、启动交付EXE或连接设备。最终核对时发现`network_card_ip.ini`另有新增变化（20:54:55，晚于最终完整门禁结束），来源未确认，保持原样并排除在修复/审查快照外。

## 2. 根因：已确认与未确认

**现场已确认**：串口线程在 `Queue.put` 的内部互斥锁保护区触发 `StringVar` 析构并等待 Tcl 主线程；主线程同时在终端轮询中等待同一 Queue 的锁，形成循环等待。`get_nowait` / `put_nowait` 并不保证内部互斥锁的获取不等待。触发线程的 COM 名称不能证明串口硬件故障。

**源码探针可重复确认**：原订阅闭包捕获整个终端；旧代次失效后回调仍入队；原全流程线程重新构造上下文并调用 UI 输入 getter；原全流程窗口销毁后仍持有 3 个 BooleanVar 和 6 个 StringVar。原 UI 桥接没有关闭/取消完成机制并永久等待 Event。

**仍未确认**：现场具体 StringVar 的业务归属、循环 GC 与最后引用释放的具体触发方式。本轮没有检查现场进程或据模拟结果反推该对象归属；没有独立重演原现场完整死锁。

## 3. 对象所有权和关键差异

### 串口、队列和 Tk 生命周期

- 新 `SerialDelivery` 只持有 VLAN、有效事件、邮箱和数据专用诊断接收器。串口线程不再持有终端窗口、Tk 变量或绑定窗口的方法。
- 每次订阅使用新对象作为代次。主线程关闭先失效旧代次，再退订；回调执行前/观察后检查失效状态，消费者再次验证当前代次，覆盖正在执行与已入队的两种竞争。
- `TkScope` 指定 GUI 主线程所有权；变量显式指定 master，关闭时移除 trace，销毁控件并清空变量和控件引用。全流程窗口清理 FocusIn 和变量/控件字典，串口窗口清理轮询、延迟关闭与 Notebook 回调。
- 轮询捕获窗口scope，进入及重新调度前均验证身份；已退役或执行中跨越关闭/重开的旧轮询不能恢复新窗口定时器。
- 标签释放失败保留标签、恢复新代次订阅，旧代次永久失效。整个窗口的失败关闭允许重试。升级占用保护、共享 COM 所有权、日志命名及完整落盘保持。
- `BoundedMailbox` 保持 2000 条显示容量和已接受事件的 FIFO；满载或互斥锁繁忙时丢弃新增显示事件。GUI 获取锁失败立即让出本次刷新，不进入等待。临界区内不调用 UI/外部回调，清空对象引用在解锁后完成。
- 保留 120 条/10ms 刷新预算、33ms/80ms 调度、每 VLAN 64KiB 待显示缓冲及 5000 行限制。增加累计显示丢弃提示；串口日志在显示入口之前独立完整落盘。
- 最后一个串口所有者使用 `SerialCloseTicket` 异步关闭；关闭中的物理端口保持预留，不允许创建第二个读线程。关闭线程等待读线程结束后才写尾部半行/关闭状态并关闭文件。GUI 只轮询 ticket，不 join 读线程。同步 close 保留给后台调用并支持重入关闭通知。

关键变化示意（省略无关代码，非独立可应用补丁）：

```diff
- def receive(event):
-     self.events.put_nowait((vlan, event, token))
+ delivery = SerialDelivery(vlan, self.events, diagnostic_data_receiver)
+ item['event_token'] = delivery

- self.manager.release(owner, port)  # GUI 中可能 join 读线程
+ ticket = self.manager.release(owner, port, wait=False)
+ # GUI 轮询完成后清理标签；关闭期间禁止重新打开同一端口。
```

### 全流程数据快照与取消

- 主线程在确认后生成通道、参数、ONU、COM 和目录快照。后台入口为独立 `run_pipeline`，不再是绑定窗口的方法；上下文的 app 接口替换为数据专用 `PipelineClient`。
- GUI 处理器仅存在于 GUI 控制器和主线程本地注册表，后台 channel 不可达这些处理器。主线程查询可原地执行，避免 GUI 自己等待自己。
- 请求携带动作代码、参数和运行代次，区分排队、执行中、准入、完成、失败、取消、过期。排队上限默认 30 秒，可通过控制器/channel 构造参数配置；只约束尚未执行的请求。
- 关闭、停止、队列忙和超时释放等待方；队列中的旧请求领取前再次校验。人工确认后的升级、写参、ONU 注册及上/下电启动前重新检查准入。已准入操作沿用原安全停止机制，不重发、不把请求取消表述为已撤销设备动作。
- 子任务的完成模型在异常和未启动时完成，并清除旧兼容所有权标记。已准入子任务未收尾时禁止重启下一批；普通完成窗口关闭不取消已完成批次的失败通道续跑令牌。
- 编排最终结果保存在独立运行模型，由主线程领取，不会因显示/请求队列满而丢失。跨线程错误只包含类型与消息，接收方新建异常，不传 GUI traceback。
- AI 串口 bridge 同样拆分 GUI 处理器和数据客户端；迟到状态恢复还验证订阅代次。取消与资源领取竞争时，未交付的串口 lease 会释放，保留原监控所有者。

```diff
- target=self._run_pipeline_thread
- # 后台重新读取 Tk 输入，并提交 action 闭包后 completed.wait()
+ target=run_pipeline
+ args=(main_thread_snapshot, selected, data_channel, run, data_log_sink)
+ # worker 只提交动作代码/数据；取消、关闭和排队超时结束等待。
```

### 应用退出

- 先阻止新增相关任务、取消 UI 请求并请求现有任务停止，再保持 GUI 轮询处理安全收尾。
- 主程序登记原有后台线程的句柄，退出轮询实际 `is_alive()`，避免仅靠提前清除的运行标志销毁 Tk；没有新增设备任务或后台 wrapper 业务流程。
- 串口关闭、后台线程及恢复任务结束后才销毁根窗口，不在 GUI 中同步 join 等待 GUI 的线程。
- 不修改 Tkinter 析构实现，不关闭全局 GC，不增加 GC 阈值或把吞异常当作生命周期修复。

## 4. 本轮文件

所有下列源码路径均相对 `Cheating_machine_execution_tool/`：

| 子系统 | 文件 |
| --- | --- |
| 数据端点/邮箱（新增） | `src/models/serial_delivery.py`、`src/utils/bounded_mailbox.py` |
| 生命周期/GUI 桥（新增） | `src/ui/tk_lifecycle.py`、`src/ui/pipeline_ui.py` |
| 后台客户端（新增） | `src/services/pipeline_runtime.py`、`src/services/ai_serial_client.py`、`src/services/serial_diagnostic_receiver.py` |
| 串口 | `src/core/serial_transport.py`、`src/ui/serial_terminal.py` |
| 全流程/主程序 | `line_check_assistant/pipeline_window.py`、`line_check_assistant/app.py`、`src/services/pipeline_orchestrator.py` |
| 诊断接线 | `src/ui/ai_serial_bridge.py`、`src/ui/ai_assistant_controller.py`、`src/services/ai_diagnostic_service.py` |
| 新回归/压力 | `tests/test_ui_lifecycle_runtime.py`、`tests/test_tk_lifecycle_process.py`、`tests/serial_lifecycle_stress.py` |
| 既有回归调整 | `tests/test_serial_terminal.py`、`tests/test_serial_transport.py`、`tests/test_pipeline_window.py`、`tests/test_ai_actions.py`、`tests/test_ai_integration.py` |
| 门禁 | `scripts/verify_baseline.py`（新增模块登记、6 个必须执行回归 ID、失败保留断言栈；不放宽门禁） |

另更新根开发记录、状态、验收边界、本报告、操作员说明及 `.claude/plans/v129-unresponsive-fix.md`。最终测试复用同期加入的 `tests/tk_test_windows.py` 屏幕外工具，须保留该辅助文件；这不是产品代码变更。

审查命令：在仓库根运行 `git diff --stat`、`git diff -- Cheating_machine_execution_tool/src/core/serial_transport.py Cheating_machine_execution_tool/src/ui/serial_terminal.py Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`，新文件直接打开。`app.py` 等共享文件还有同期用户改动，不能把整份 diff 全部归为本轮修复。

[源码审查快照](validation/unresponsive_20261113/source_review.diff)展开上述相关源码/测试的新文件及相对HEAD差异。共享文件保留同期用户修改，因此这是审查材料，不是可独立应用的本轮补丁；不包含本机配置文件。

## 5. 实际验证

环境：Windows、CPython 3.9.10 x64，仓库现有 `.venv_serial_upgrade/Scripts/python.exe`。所有串口由测试工厂替换，写命令在压力 fixture 中直接断言禁止；没有真实串口、电源或设备操作。

| 检查 | 条件 | 结果 |
| --- | --- | --- |
| 修改前专项 | 原串口、全流程、停止相关 160 项 | 通过，约 2.7 秒；不是修复后结果 |
| 扩展专项 | 串口/全流程/AI/生命周期共 447 项 | 通过，64.600 秒；之后新增边界另经专项和最终基线验证 |
| 十分钟模拟 | 8 路 × 100 块/秒 × 约256字节，100轮窗口/标签/GC压力 | 600.062秒，478,933条记录；心跳最大0.359秒；邮箱峰值1419/2000，待显示字符峰值458091/524288 |
| 对象与资源 | 上述十分钟模拟 | 1105次变量析构均在主线程；关闭的全流程对象残留0；结束后读/关闭/模拟线程残留0；订阅峰值8，定时回调稳定 |
| 内存 | 校正当前仍保留的串口历史缓存，预热后均值比较 | 增加1,874,233.8字节（约1.79MiB），低于10MiB门槛；未修改既有原始历史缓存语义 |
| 显示过载 | 8路 × 1000块/秒，8轮关闭重开 | 8.093秒，62,845条；显示丢弃56,151条，邮箱峰值2000；心跳最大0.313秒 |
| 日志完整性 | 输入序号逐行核对及输入/输出摘要，含分块CRLF | 十分钟与过载均8/8一致；显示丢弃没有改变落盘数据 |
| 最终短程 | 8路，8轮，包含整窗关闭及屏幕外辅助器 | 5.141秒，3,940条，97次主线程析构；心跳最大0.157秒；11个受管窗口无屏幕内违规 |
| 最终完整门禁 | `python -X utf8 scripts/verify_baseline.py` | 连续两次ALL CHECKS PASSED；最终1919项测试、196项必须执行回归、152个源码编译/清单覆盖及全部协议不变量；最后一次86.735秒 |

本轮新增24项行为回归；最终代码还补充了真实线程退出、已准入子任务收尾、关闭完成配置窗口保留续跑、整窗关闭失败重试和旧轮询失效等边界，这些由专项与最终门禁验证。十分钟结果针对独立真实Tk的串口接收/窗口GC路径（窗口隐藏），不表示已进行十分钟可见界面重绘或真实设备业务测试。

原始数据与来源清单：[十分钟数据](validation/unresponsive_20261113/stress.json)、[过载数据](validation/unresponsive_20261113/overload.json)、[最终短程数据](validation/unresponsive_20261113/final_smoke.json)、[源码及日志摘要](validation/unresponsive_20261113/source_and_log_manifest.json)、[最终完整门禁](validation/unresponsive_20261113/baseline.txt)。清单记录当前源码SHA256和临时原始模拟日志位置/大小/摘要，不能代替构建或现场二进制匹配证明。

复跑（从主源码目录，临时目录建议先 resolve 为长路径并设置 TEMP/TMP/TMPDIR）：

```powershell
..\.venv_serial_upgrade\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_ui_lifecycle_runtime.py
..\.venv_serial_upgrade\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_tk_lifecycle_process.py
..\.venv_serial_upgrade\Scripts\python.exe -X utf8 tests\serial_lifecycle_stress.py --seconds 600 --cycles 100 --rate 100 --report "$env:TEMP\linecheck_recheck\stress.json"
..\.venv_serial_upgrade\Scripts\python.exe -X utf8 tests\serial_lifecycle_stress.py --seconds 8 --cycles 8 --rate 1000 --report "$env:TEMP\linecheck_overload_recheck\overload.json"
..\.venv_serial_upgrade\Scripts\python.exe -X utf8 scripts\verify_baseline.py
```

压力程序由父进程设置时长+90秒超时，超时只终止并回收自己创建的测试子进程；可能阻塞的锁/重入测试也有独立子进程时限。未杀死任何已有进程。

中间检查记录：第一次完整基线失败定位为退出重复调用stop，已修正；另一次1914项门禁报1失败而旧脚本只保存末尾摘要，当时工作区存在同期测试修改，未获得该次断言栈，不能确定归因。随后带完整失败栈的1916项检查通过；最终源码两次1919项门禁通过，新门禁失败时保留16KB末尾日志以包含断言栈。最初AI专项还有Windows短路径/长路径断言差异，规范测试临时目录后通过。中间完整单测输出含既有Tk主题/已失效after命令和本地TFTP重传诊断，保留在验证目录供复查，不将这些输出或模拟结果升级为现场结论。

本轮源码/测试/文档差异格式、25份源码及测试摘要、报告链接和三份模拟结果检查通过。全工作区`git diff --check`另报上述新增配置空值行尾空格，未清理或回退该配置，不将全工作区差异格式检查表述为通过。

## 6. 验收与回退

- **已通过回归**：有界非阻塞显示、线程归属、旧代次失效、异步串口收尾、UI取消/异常/超时及资源竞争、失败/停止/完成窗口边界、完整模拟日志。
- **压力测试未复现**：上述约十分钟离线输入和GC压力未出现现场死锁。这不是“彻底修复全部无响应”的证明。
- **人工验证尚未执行**：完整主程序Windows交互、真实多串口连续运行、停止/续跑和现场退出；需负责人复验。独立Tk自动化不是人工验收。
- **结构边界**：本轮分离串口订阅、新全流程和AI串口客户端的UI持有关系；其它既有业务worker没有整体搬迁，退出时保留GUI并轮询它们实际结束。其完整交互仍需按原业务范围复验，不声称全仓所有历史线程路径均已重写或现场问题已彻底排除。
- **便携版未验证**：本轮不构建、不改版本号、不覆盖旧包或配置；源码通过不代表PyInstaller版通过。后续构建必须另用标准脚本、独立新输出目录、固定工具链和全部门禁，当前电脑不运行新EXE。
- **回退**：本轮没有交付新包，旧V1.2.9及配置保留。源码回退仅撤销本报告列出的自身功能改动；共享文件逐hunk处理，不对整个工作区运行 reset/restore，以免丢失同期用户修改。先停止模拟进程并保存diff，不能用回退源码自动结束现场进程。
