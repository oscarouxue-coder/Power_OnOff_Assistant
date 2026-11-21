# Phase 5 · 串口诊断快照

2026-11-21，串口诊断快照已纳入 Windows PySide6 候选包。完整解压后，目标机从 `DUTPilot_portable\DUTPilot.exe` 启动。[便携 ZIP](../../../dist/qt-20261121-110646-bc54506d/DUTPilot_portable.zip) · [SHA256 校验文件](../../../dist/qt-20261121-110646-bc54506d/DUTPilot_portable.zip.sha256.txt)

Qt 串口终端的通道输出区提供「查看串口诊断快照…」。操作员可以在其他任务持有控制权时，查看程序内的监控与控制所有者、关闭状态、最近一次打开失败、程控电源端口冲突和本次采集的近期接收数据。

## 原业务调用链

旧 Tk 的 `AiSerialBridge._status` 读取 `SerialSessionManager.diagnostic_state`，补充打开错误与当前电源端口。旧诊断客户端通过 `existing_session` 检查已打开会话的串口参数，由 `cursor` 和 `peek_since` 读取最近 65,536 字节。Qt 重用这条被动读取路径。窗口令牌、项目、通道和端口约束本次请求；关闭中的窗口或已变更的端口会拒绝旧请求。

终端的清屏只影响显示。快照读取后固定显示采集时间和当时的数据，后续的驱动输出继续进入原终端及串口日志。主执行日志记录读取结果，串口正文仅在快照中显示。未打开的端口直接返回原提示。端口参数不匹配时，仍能查看程序内所有者和具体原因。

## 核验

标准脚本 `build_line_check_assistant.ps1 -Gui Qt` 使用锁定的 CPython 3.9.10 x64，通过完整基线及标准验包。共执行 3,235 项回归，其中 239 项指定测试全部命中。另从实际 EXE 读取入口和 PYZ，328 个项目模块与构建输入源码一致，包括本轮全部五个业务及界面模块。复核了包内操作手册、ZIP CRC 和外部 SHA256 文件。ZIP 共 55,383,324 字节，SHA256 为 `07a8121aa4f1aba69f69b9deb486ebc25bd515d69a31b58490df4fbd562feeb9`。按仓库要求未在构建机运行新 EXE，独立目标机启动待验。[完整基线与构建原文](build.txt) · [验包结果](../../../dist/qt-20261121-110646-bc54506d/PACKAGING_REPORT.json) · [成品代码比对](packaged-sources.json)

Windows 私有桌面在 100%、125% 和 150% 显式 Qt 缩放下各通过 92 项原生用例，共 276 次。每档核验 1,839 个受管窗口，无缺失用例和隔离违规。97 个受保护原业务文件与迁移前登记哈希一致。[三档原始结果](native/results.json)

- 使用原串口会话管理器、原接收线程及队列模拟驱动运行 21 项串口专项，全部通过。新增用例核对了未打开、令牌过期、映射变化、打开失败及恢复、共享所有者、不同波特率、超出 64 KiB 的历史和重复读取。检查了读取后的待显示输出、模拟驱动写入次数及主日志。[服务测试记录](services.txt)
- Windows 私有桌面的专项通过。从通道右键菜单清屏后打开快照，验证控制所有者、历史数据、只读窗口、后续输出与快照隔离，以及关闭终端时的窗口回收。[窗口专项记录](focused.txt)

## 界面核对

窗口使用项目现有的 Qt 文本区、标签与弹窗布局，操作位于原通道右键菜单。三档原生截图均可见采集时间、共享所有者及留存数据，采集时的项目、通道和 COM 位于系统窗口标题。本阶段未提供单独的诊断快照目标设计稿。[100% 窗口图](native/scale-1/serial-diagnostic-snapshot.png) · [125% 窗口图](native/scale-1.25/serial-diagnostic-snapshot.png) · [150% 窗口图](native/scale-1.5/serial-diagnostic-snapshot.png)

## 实施文件

本次三档原生运行共生成 387 张 PNG。核对 Git 跟踪状态与报告引用后，将 384 张过程图移入回收站，保留上面三张窗口截图及全部测试记录。

- `src/services/ai_serial_client.py` 为原客户端和 Qt 提供同一被动读取函数。`qt_serial_terminal.py` 记录实际打开失败并注册 GUI 只读能力。`qt_workspace_adapter.py` 将请求交给当前项目执行器。
- `src/ui/qt/serial_terminal_dialog.py` 增加通道菜单和快照窗口。`workspace_controller.py` 校验回复所属窗口及端口。
- `tests/test_qt_serial_terminal.py`、`tests/qt_workbench_probe.py` 和 `scripts/verify_qt_migration.py` 登记服务与原生回归。`scripts/verify_capability_coverage.py`、GUI 动作清单及根目录能力覆盖说明记录本机只读入口。
- 已同步操作员手册、阶段进度、项目状态、验收基线和开发记录。Tk 入口和开关机执行路径保留。

## 验收边界

短时模拟还测得一项长期运行时需要观察的原有行为。用队列驱动向同一会话分八批送入 8 MiB ASCII，每批读取一次快照，八次都是 65,536 字符，串口发送次数为零。底层原会话持续保留了 8,388,608 字节接收历史。`PySerialSession.cursor` 与等待匹配接口依赖这个历史位置。现场长挂应同时记录串口吞吐量、会话存续时间和进程内存；现有证据只覆盖上述短时模拟。[逐批数据](history-probe.json) · [复验脚本](probe_serial_history.py)

本阶段覆盖操作员主动查看已打开串口的近期数据。模型会话自动关联设备与串口、远程控制面其余入口、实体串口共享、真实样机、持续开机全业务老化与长期稳定性仍分别待验或待接入。
