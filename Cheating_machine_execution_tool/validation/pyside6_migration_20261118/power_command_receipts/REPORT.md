# 自动开关机串口写入回执

本阶段修复 Tk 和 Qt 共用的原执行器。负责人于 2026-11-21 确认了修复范围：通过模拟电源验证，保留原延时、帧格式和停止保护。[修正前的两类成功误报](../power_worker_replay/REPORT.md)

## 修改

| 文件 | 行为 |
| --- | --- |
| [原电源队列](../../../Auto_power_on_off_tool/common/power_on_off.py) | 保留同一个串口消费者、FIFO、原帧和重复动作抑制。通道提交命令后等待该动作的回执。完整写入后才更新通道缓存并唤醒等待者；原 3 秒通电、0.5 秒断电的消费者延时与通道的配置等待可继续并行。 |
| [原串口封装](../../../Auto_power_on_off_tool/common/serilal_client.py) | 检查驱动返回的写入字节数；部分写入与驱动异常均进入失败路径。共享电源串口失败后，当前队列停止写入，等待该队列的通道收到错误。 |
| [Telnet 通道线程](../../../Auto_power_on_off_tool/test_case/powe_on_off_telnet.py)和[SSH 通道线程](../../../Auto_power_on_off_tool/test_case/power_on_off_ssh.py) | 操作员取消排队命令时，通道回传停止。SSH 将电源写入错误与可重试的网络连接异常分别处理。 |
| [原开关机子进程](../../../src/services/legacy_power_test_service.py) | 消费者可直接观察原停止事件。子进程关闭串口前等待消费者退出；原父进程超时保护继续生效。 |
| [队列回归](../../../tests/test_power_command_receipts.py)、[基线清单](../../../scripts/verify_baseline.py)和[Windows 子进程回放](../power_worker_replay/replay.py) | 为提交、写入、缓存更新、取消、短写、通道终态和配置等待建立确定性回归。Windows 回放复用两个正式入口。 |

操作员说明已同步至[使用手册](../../../line_check_assistant_README.md)。此修复不改变 GUI 布局、项目配置、现有帧内容、串口回读方式或全业务持续老化的实现范围。旧 Tk 界面继续可用，两个界面均使用修正后的原执行器。若需要复现旧执行器，可保留前一份[网关阶段候选包及校验值](../gateway_project_lifecycle/REPORT.md)。

## 验证

专项共 100 项通过。受控的模拟串口写入阻塞期间，通道未进入后续步骤；写成后不必再等消费者的 3 秒保护延时即可开始配置等待。第二条排队命令在停止后没有写入。模拟写入 5/6 字节时，缓存保持原值，两个通道都获知错误，端口未追加尝试。[专项运行记录](focused.txt)

初次并行启动多套回放时，独立进程因相同模拟网卡的主机租约互斥而被正确拦截。随后改为顺次运行，各项目继续由原资源保护服务准入。[早期运行记录](normal.txt)

| 最终顺次回放 | 原入口与 Qt 入口结果 |
| --- | --- |
| 1 秒启动、2 秒轮间、两通道各两轮 | 两个入口分别写入 8 帧。每个通道按断、通、断、通顺序完成。[短等待逐帧记录](final-short.json) |
| 10 秒启动及原业务回归 | 两入口各写全 8 帧，均生成两轮原业务结果；Qt 在首条通电后停止，写入 3 帧并保留“已停止”回执；两个 Ping 故障场景各报告通道 3、9 失败。[五场景回放](final-normal.json) |
| Telnet 与 SSH 的电源写入异常 | 分别使用两个入口，拒绝 CH3 的首条通电命令，包括带 WinError 字样的驱动异常。4 个任务均报告两通道失败，只写成初始化的 2 条断电命令。[Telnet](final-serial.json) · [SSH](final-ssh-error.json) |
| Telnet 与 SSH 的电源部分写入 | 模拟驱动只接收 6 字节中的 5 字节。4 个任务均失败，未重复下发命令。[Telnet](final-partial.json) · [SSH](final-ssh-partial.json) |

以上 15 次运行均在原 Windows 子进程内完成。本轮 10 秒配置下，通道 9 首轮通电帧到下一轮断电帧，原入口实测 13.672 秒，Qt 入口实测 13.641 秒。共享串口依次写各通道，实际帧间隔可长于配置值。两种启动配置、两个入口的全部受测通道均在对应帧写成后开始等待，并满足配置等待时间。[逐通道时间](timing.txt) · [可复跑的时间核对](check_timing.py)

另在原 Windows 子进程同时选择 CH1–CH16。实际执行两轮，模拟启动等待 1 秒、轮间等待 2 秒，原串口消费者连续写入 64 帧。16 个通道各自的 4 帧、三次配置等待和最终关闭均逐项核对，无意外外部 I/O；本次在子进程启动后 177.328 秒关闭模拟串口。[16 通道逐帧记录](sixteen.json) · [复验脚本](check_sixteen.py)

Qt 项目准备和确认入口也已用 CH1–CH16 各执行两轮，原子进程写全 64 帧，在 177.203 秒关闭模拟串口。逐通道已核对配置等待、原回执和最终资源释放。该场景在完整基线释放其测试机租约后运行。[Qt 16 通道逐帧记录](sixteen-qt.json) · [执行结果](sixteen-qt.txt)

另令虚拟驱动在首条通电写入内一直阻塞，再从原入口请求停止。原父进程保留 10 秒宽限，10.25 秒后返回“用户停止，旧业务子进程已终止”，业务结果为失败且该子进程已退出。阻塞前只写成两帧初始化断电。被终止的进程无法提供驱动关闭回执，实体电源状态仍须由操作员核实。[阻塞停止的原始记录](blocked-stop.json) · [复验脚本](check_blocked_stop.py)

在主源码目录使用标准 Qt 构建环境的 Python，依次运行 `power_worker_replay/replay.py` 的 `--short-wait`、`--serial-failure`、`--partial-write`、`--ssh --serial-failure`、`--ssh --partial-write` 和无额外选项六种情况。每次用 `--output` 指定独立的 JSON。真实硬件回读和两种协议的真实网络登录按现场范围验收。

最终成品核对使用一份固定的[五项修改前后 SHA256](reviewed-sources.json)。[验包脚本](../instance_pairing/check_candidate.py)逐项检查迁移前源码、候选中实际 PYZ 字节码和修正后源码，其余 92 个受保护文件仍按原哈希核对。

[五个业务文件的独立差异](reviewed.patch)可用于审阅或回退。在仓库根使用 Git 对这份补丁执行反向应用的只读检查，已确认补丁匹配现有源码。此次检查没有恢复旧行为。

用修正后的源码和清单验证上一候选时，验包器在原电源模块处检出真实 PYZ 字节码差异并返回 1。[修正前包的反向验证](pre-fix-package-negative.txt)

首次标准打包在全量 unittest 阶段被拦截。Windows 事件记录确认基线测试进程在 ntdll.dll 中发生 0xc0000005，最后一条输出为本机回环网关测试，进程尚未给出测试结论。新增队列测试改为只临时设置导入路径，避免在后台线程存在时还原整个 Python 模块表。现有证据不足以将这次原生崩溃归因于某个业务模块。[首次失败的门禁](build-crash.txt) · [匹配测试进程的 Windows 事件](windows-crash.json)

开启 Python 故障堆栈记录后，用标准测试入口连续两次重跑新增队列测试、回环网关及网关代理专项，每次 27 项全部通过。随后使用相同固定环境和原构建入口重新执行完整基线。[第一次 27 项](crash-recheck-1.txt) · [第二次 27 项](crash-recheck-2.txt)

实际电源输出、真实启动与断电时序、单/多通道、条件允许时 16 通道、每台 500 轮及长期稳定性待现场验收。当前结果只对模拟串口、软件等待和业务回执负责。

## Windows 三档窗口验证

100%、125%、150% 缩放各通过 94 项，合计 282 次。下表保留挂测执行中和收到停止回执的真实 Qt 源码窗口截图；界面用例的模拟服务与前述真实子进程回放分别取证。[三档测试结果](native/results.json)

| 缩放 | 运行中 | 已停止 |
| --- | --- | --- |
| 1 | [运行窗口](native/scale-1/power-test-running.png) | [停止回执](native/scale-1/power-stopped-receipt.png) |
| 1.25 | [运行窗口](native/scale-1.25/power-test-running.png) | [停止回执](native/scale-1.25/power-stopped-receipt.png) |
| 1.5 | [运行窗口](native/scale-1.5/power-test-running.png) | [停止回执](native/scale-1.5/power-stopped-receipt.png) |

三档各记录 1,848 个受管理窗口，隔离守卫无违规。核对 Git 状态与报告引用后，396 张生成截图中 390 张已移入回收站，保留运行中与停止回执共 6 张。

## 标准 Windows 候选包

3,245 项完整基线通过，247 项指定用例全部执行。三档 Windows 原生共 282 次通过。成品入口和 330 个项目模块与源码一致，92 个受保护业务文件保留原哈希，另外 5 个与负责人确认的修正快照一致。目录与 ZIP 的 245 份文件已比对，验包逐一核对 39 个 PySide6/shiboken6 原生文件导入的 Qt6 DLL。ZIP 共 55,352,542 字节，SHA256 为 `b06eb78f96b20706aae1b74e12ed2c3b0629cda2c71ad0bca7c4c33faedea6de`。

[Windows 便携 ZIP](../../../dist/qt-20261121-131321-f895c473/DUTPilot_portable.zip) · [SHA256](../../../dist/qt-20261121-131321-f895c473/DUTPilot_portable.zip.sha256.txt) · [构建与全量回归](build.txt) · [成品源码比对](packaged-sources.json) · [验包明细](../../../dist/qt-20261121-131321-f895c473/PACKAGING_REPORT.json)

本机仅静态核对新 EXE。目标机独立启动、实体多屏、真实 DUT 及长期挂测待现场验证。
