# Qt 工作区反复重建句柄专项定位（2026-11-25）

## 结论与边界

本轮为独立 L0 合成对照，不改生产源码。空工作区不创建项目、不运行本地报告，仍有每轮 25 个系统总句柄在正常关窗、丢弃 fixture 引用及 Qt 事件处理后继续存留；显式诊断性 Python GC 后全部 25 个差值消失。仅 adapter 的对照出现 22–23 个相同性质差值，独立 WorkspaceService 有 7 个，独立 MainWindow 和 WorkspaceResources 没有相同规模的 GC 释放差值。各组经过 GC 的收尾计数在各自稳定区间内。

进一步在不逐轮显式 GC、保留正常自动 GC 的 30 轮空工作区中，句柄数呈阶梯上涨及自动回落。最后只等待并处理事件 7 秒没有继续释放，末次完整 GC 后 25 个句柄释放，先前仍存留的 8 类组件弱引用全部失效。因此最有证据支持的是工作区 Python 组件引用环导致的资源延迟回收；不能证明每个原始 Win32 句柄类型，也不能断言此前 751→1500 的每个句柄都由这一因素产生。**本次没有证明永久泄漏，也没有证明长期无泄漏。**

## 历史对照（本轮未重跑）

[P0 短时重复报告](../qt_p0_local_repeat_20261125/REPORT.md)：整套工作区含报告的 30 次重建总句柄 751→1500、RSS 308.65→325.74 MiB；原清理后 Python 线程 1。该过程未逐轮强制 GC。一工作区一固定报告窗口正常/取消报告各 60 份的对照为 753→770 个总句柄（采样范围 766–783），关闭后 751；RSS 406.45→410.27 MiB。说明有必要分离工作区重建与报告读取因素。本轮独立进程初始条件及 Qt 加载程度不同，不要求不同测试的绝对总数相等。

## 本轮方法

[独立探针](handle_probe.py) 以六个新 Qt 子进程分别执行一项综合测试，通过既有 run_tests 及 run_gui_child(framework='qt', native_render=True) 在受核验的非输入 Windows 私有桌面运行，使用合成临时 fixture；不访问现场数据、实际设备、模型、网络、凭据或第三方进程。只测当前进程，测试内受保护 HTTP、网络、串口、外部进程和打开外部文件入口调用均为零。未改变原有守卫。

每组都有初始 QWidget 预热；空工作区使用正式 QtProjectWorkspaceTests fixture 的创建/清理，window 仅构造 MainWindow，adapter 使用现有 QtWorkspaceAdapterTests fixture；service、resources 使用各自临时对象，均不运行报告或真实挂测。前五组各 20 轮；每轮采样 ready、正常 close/cleanup、丢弃 fixture 引用并处理 Qt DeferredDelete/事件约 50ms、诊断性 GC 后再处理事件、等待/泵约 250ms。末尾再处理约 2s、5s。第六组 30 轮不逐轮显式 GC，正常自动 GC 仍启用，最后再处理事件 2s+5s 后才显式 GC、再处理事件 5s。弱引用只记录存活对象数量。

计数使用当前进程 psutil num_handles/num_threads/memory_info().rss、threading.active_count、GetGuiResources 的 GDI/USER、QApplication.topLevelWidgets，及合成目录内被测试探针跟踪的 Python open/Path.open 文件对象（未跟踪所有 SQLite 或系统文件句柄）。总句柄不等于文件句柄；GDI/USER 为独立计数，不能用于准确计算剩余类别。RSS 是工作集，不是私有分配总量；原生线程数包含运行库线程，不能仅凭数量推断线程类型。

## 20 轮逐组对照

| 组 | 实际轮数 | 第 1 轮清理后→GC/等待 | 第 20 轮清理后→GC/等待 | 每轮 GC 差值 | 收尾稳定范围 | 测量秒 |
|---|---:|---:|---:|---:|---:|---:|
| 空工作区 | 20 | 735→710 | 734→709 | 25 | 709–710 | 41.688 |
| 仅 MainWindow | 20 | 708→708 | 707→707 | 0 | 707–708 | 41.860 |
| 仅 adapter | 20 | 420→398 | 419→397 | 22–23 | 397–398 | 35.938 |
| 仅 WorkspaceService | 20 | 405→398 | 404→397 | 7 | 397–398 | 30.281 |
| 仅 WorkspaceResources | 20 | 400→398 | 399→397 | 0（普通事件泵已释放 2） | 397–398 | 29.719 |

各组初始总句柄为 398；主窗口首次加载后形成约 707–708 的稳定基线，不能将这个加载差值当成每轮增长。五组各一项综合原生测试均通过。不同组并非可简单相加的独立句柄类别。

| 组 | 首次等待 RSS→最终 RSS（MiB） | 最终 GDI / USER | 最终原生 / Python 线程 | 已跟踪文件 / 仍打开 | 最终 Qt 顶层窗 |
|---|---:|---:|---:|---:|---:|
| 空工作区 | 218.30→224.01 | 18 / 20 | 10 / 1 | 40 / 0 | 0 |
| 仅 MainWindow | 214.32→217.19 | 18 / 20 | 10 / 1 | 0 / 0 | 0 |
| 仅 adapter | 154.68→156.00 | 14 / 18 | 9 / 1 | 40 / 0 | 0 |
| 仅 WorkspaceService | 156.77→156.88 | 14 / 18 | 9 / 1 | 0 / 0 | 0 |
| 仅 WorkspaceResources | 155.98→155.80 | 14 / 18 | 9 / 1 | 0 / 0 | 0 |

所有轮后台收尾断言满足；共 125 个受管窗口、守卫违规 0。五组完整指标见 [aggregate-controls.json](aggregate-controls.json) 和各 `metrics-{empty,window,adapter,service,resources}.json`、`summary-*.json`、`native-*.txt/json`。

## 30 轮正常自动 GC 对照

测试通过（1 项综合原生测试，65.055s；子进程测量区间 78.234s，91 个受管窗口、守卫违规 0）。每轮正常关闭及等待后总句柄为 731–859，第一轮 735，第 24 轮达到 859，第 25 轮自动回落至 734，第 30 轮 731；第 1、11、21 轮收尾仍存留组件组数分别为 1、4、5。每组包括 window、controller、adapter、workspace_service、workspace_resources、log_writer、history_executor、gateway_executor；测试 case 自身已无弱引用存活。

| 最后收尾阶段 | 总句柄 | 每类组件弱引用存活 | 原生/Python 线程 | GDI/USER | RSS MiB | Qt 顶层窗 | 已跟踪文件仍打开 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 第 30 轮正常清理及等待 | 731 | 1 | 7/1 | 18/20 | 228.98 | 0 | 0 |
| 额外事件泵 2s | 731 | 1 | 7/1 | 18/20 | 229.55 | 0 | 0 |
| 再事件泵 5s（GC 前） | 731 | 1 | 7/1 | 18/20 | 229.55 | 0 | 0 |
| 显式 GC 后再事件泵 5s | 706 | 0 | 7/1 | 18/20 | 229.55 | 0 | 0 |

显式 GC 返回 3666（回收 Python 对象数，不是句柄数），释放最后 25 个总句柄，但 RSS 未明显下降。60 个被跟踪 Python 文件均已关闭、无法跟踪的文件对象 0。没有逐轮显式 GC 的空工作区在自动 GC 下出现回落，不能把此次增长称为线性永久泄漏；空 fixture 仍不等同含报告的历史复合场景。

实际证据：[30 轮逐项数据](metrics-empty-deferred.json)、[末次回收和归档摘要](summary-empty-deferred.json)、[原生测试输出](native-empty-deferred.txt)、[隔离记录](native-empty-deferred.json)。全部六组共 130 轮，六项综合测试通过，子进程测量区间合计 257.720s、216 个受管窗口，违规 0。

## 最可能责任边界，待审

代码只读观察（行号为本轮检出）：

- [qt_workspace_adapter.py](../../src/services/qt_workspace_adapter.py) 154–155：adapter 持有 writer，writer 持有绑定方法及捕获 adapter 的关联回调；1606–1611：adapter 持有 service，service 及两个子组件的 emit 回指 adapter。1872–1882：现有关闭路径收尾执行器及 writer，但未见明确解除上述回指。
- [workspace_event_log.py](../../src/services/workspace_event_log.py) 108–126、173–176：存储 report/associate，close 等待写线程，但未见解除存储的回调。
- [workspace_service.py](../../src/services/workspace_service.py) 115–117、159–167：platform/resource 回调捕获 service；522–531：关闭 model/pool/gateway/resources。service 单独重现 7 个延迟回收差值。
- [workspace_resources.py](../../src/services/workspace_resources.py) 409–416：关闭 lease reader 和 fence DB；独立对照未重现 GC 延迟。单凭这些代码不能认定某个类或方法产生哪种内核句柄。

建议后续只评审 adapter/service 的结束态引用所有权：在原有工作线程、日志写入、关窗回调及资源释放已确认完成后，核查可否解除已失效的双向绑定和闭包。优先从 adapter 与 writer/service 的回指开始，必要时再细化 service 内回指。不得提前切断仍需的回调或修改挂测引擎、关闭协议及业务语义，不能以每次强制 GC 掩盖生命周期问题。用原入口重复空工作区、原正常关闭及取消/迟到回归和含报告复合对照验证；后者 GC 收尾也需实测。本轮没有执行该修复，具体补丁待审。

## 工作区及验收状态

本轮只新增本验证目录专属证据与探针；每组 11 个涉及源码/原测试/守卫的 SHA-256 前后一致。HEAD、分支、索引不变（69887ae5f4dafdf109cb80e7a21cbeafa6f574fb，feature/pyside6-migration，暂存 0）。工作区其他并行修改仍在：开始追踪修改 50，结束 51；快照中 7 条路径在期间发生变化（未由本探针写入），详见 [workspace-before.json](workspace-before.json) 和 [workspace-after.json](workspace-after.json)。未覆盖、回退或修改这些文件，没有 Git 写入、打包、删除或完整门禁。

本轮只支持合成短期 L0 资源定位；L1 真实模型、L2 实际设备、L3 长期现场均未开展；不能替代完整回归或长期验收。
