# 会话 2 集成验收

## 交付状态

本地 Windows Qt 候选包 `qt-20261121-220335-19897b67` 已交付。标准构建的 8 类基线门禁全部通过，编译 383 个文件，373 个源码文件全部登记。全量测试运行 3,267 项，266 项指定回归全部命中。三档原生各通过 100 项。静态验包与最终拷贝哈希均通过。[完整构建日志](build.txt) · [逐项验收表与现场记录](ACCEPTANCE.md)

| 本机交付物 | SHA256 |
| --- | --- |
| [便携 ZIP](../../../dist/qt-20261121-220335-19897b67/DUTPilot_portable.zip) · [同批校验文件](../../../dist/qt-20261121-220335-19897b67/DUTPilot_portable.zip.sha256.txt) | `7311b9dfb77c3154896941f355a6b82d6387f476f54f44878d81b9ce667ca1ac` |
| [便携目录内的 EXE](../../../dist/qt-20261121-220335-19897b67/DUTPilot_portable/DUTPilot.exe) | `e802ec6b819d70c991c43e71fc3a3388d9e71df3bb1f48b142f44c1955de5e76` |

从实际 EXE/PYZ 比对 333 个项目模块与 Qt 启动入口。受保护原业务中，90 个文件符合原始哈希，另 7 项符合已审定的前后哈希。ZIP 完整性、操作员手册、第三方声明、构建信息及两份校验值均已核对，交付目录的 252 个文件逐一校验通过。构建机全程未启动成品 EXE。[静态验包](packaged-sources.json) · [交付核对](delivery.json) · [打包报告](../../../dist/qt-20261121-220335-19897b67/PACKAGING_REPORT.json)

源码回退入口为 `python run_line_check_assistant.py`。先在当前入口确认任务结束、资源释放，再使用旧项目备份副本。干净目标机启动、真机、实体平台和长挂仍待负责人现场记录。[会话 1 交接](../session1_diagnostics/REPORT.md) · [现场交接](ACCEPTANCE.md#现场交接)

## 共同起点

只读参考目录为 `%LOCALAPPDATA%\LineCheckAssistant\qt-source\local-intent-26b1c43f`，集成目录为同级 `session2-integration-20261121`。复制包含未跟踪输入及根文档，排除 Git 元数据、缓存和编译产物，逐文件比较 2,786 份内容一致。原记录的 697 项输入集合 SHA256 为 `9e70315bcf225e66bee859cb028ca509c16daa958097acca9bec4c7791e6feb7`。[复制凭据](copy-check.json)

参考目录的原生 100%、125%、150% 各通过 100 项。参考构建的基线运行 3,266 项，4 项网卡测试失败，其中一项明确报 `adapter:vlan107` 被占用；未产生该次静态验包回执。本轮单独复跑该类 10 项通过。上一批本地 ZIP 哈希与其 sidecar 相符。[接管时核对](reference-status.json) · [网卡复跑](network.txt)

## 页面与旧项目

从 Qt 工作台的项目菜单打开两份迁移前备份的临时副本，依次打开样机升级、写参、ONU、串口、DUT 和配置编辑器，等待编辑器实际释放后保存、关闭和重开。在 Windows 私有桌面完成，217 个受管窗口，守卫违规为零。另经项目服务逐份核对 revisions、runs、原通道及 24 个主日志/资源监测文件的 980 行，旧工作区日志 72 行。旧归档 SHA256 前后一致，物理串口和外部 I/O 计数为零。[窗口回放](archived-window.txt) · [测试脚本](check_archived_window.py) · [旧项目回执](old-projects.json)

同一副本以 `scripts/run_tests.py` 运行 `test_qt_configuration_service`、`test_qt_dut_configuration`、`test_qt_dut_voice_tr069`、`test_qt_dut_wan`、`test_qt_dut_wifi`、`test_qt_serial_terminal`、`test_qt_parameter_writer`、`test_qt_onu_query`、`test_qt_log_history`、`test_qt_log_export`、`test_qt_firmware_upgrade`，148 项通过。默认值、保存、确认取消、目标变动、异常、停止和日志的逐页证据见[验收表](ACCEPTANCE.md)及[本轮专项](pages.txt)。

从“项目 → 归档日志”读取一份可向前翻页的日志，模拟文件轮转移走，再按“刷新文件”。旧窗口清空原文和游标后，“更早日志”仍可点击。本轮在文件列表刷新后先重置游标，再更新按钮状态。对同一入口增加回归，检查最新/更早按钮和显示内容。修改 `src/ui/qt/archived_logs_dialog.py`、`tests/qt_workbench_probe.py`、操作员手册。该修改沿用原读取服务、导出及过滤绑定。[修正前](before-refresh.txt) · [修正后](after-refresh.txt)

## 原执行器回放

在同一测试机依次运行 `power_command_receipts/check_sixteen.py` 的默认和 `--qt` 模式，再经 `power_worker_replay/replay.py` 模拟串口抛错、短写。两个入口各运行 16 通道、两轮、64 帧，逐通道检查写入后的原等待时间。双项目从工作台分别接入两路模拟电源，先停止的项目回报停止，另一项目继续至完成。[原入口](sixteen-direct.json) · [Qt 入口](sixteen-qt.json) · [写入异常](serial-error.json) · [短写](short-write.json) · [双项目独立停止](parallel-stop.json)

工作区异常退出后，重开项目显示未知。原进程存活期间，窗口和服务均拒绝提前解除保护；进程退出后，等操作员确认结论才释放。[本轮进程回执](owner-exit.json)

补跑日志、通道、项目关闭、跨项目冲突、全流程和更新等 127 项通过。修正归档窗口时，覆盖登记中该文件的 6 项源码哈希变化，逐项比对确认操作表达式、回调和权限相同，更新登记后通过。[专项输出](workspace-checks-corrected.txt) · [覆盖变化](coverage-review.json)

共享工作区已包含独立的跨实例转发工作。集成副本沿用共同起点的网关范围；共享区内保留同期入口、传输、路由和测试。按相对路径记录了当时的差异和两端哈希。原生验证期间，共享工作区又新增了“AI 诊断”入口改名为“Ai助手”的独立改动。该改动保留在共享工作区，交付包采用双会话冻结清单中的界面名称。[验证期间的工作区状态](shared-status-during-native.txt) · [差异清单](shared-workspace-differences.json)

## 两路源码合并

会话 1 首次交接含 15 个新增或变更文件。应用前核对共同指纹和各文件哈希。操作员手册及原生工作台用例各保留双方差异，其余交接文件与发送方逐字节一致。新增的 `qt_power_evidence.py` 进入编译清单，本机证据隔离回归进入必跑清单。组合副本的 840 个源码、构建资源、旧业务输入和测试文件均有 SHA256。工具链为 CPython 3.9.10 x64、PySide6-Essentials/Shiboken6 6.8.3、PyInstaller 5.10.1。[合并凭据](merge.json) · [输入和版本](combined-inputs.json)

在组合源码上重放已知差异，原会话和 Qt 从同一诊断批次的通道 3 各取到 16 条记录，逐条相符，重复选择未增写。取消本机目标识别后，两个模拟通道仍完成原有 8 帧。项目网关受理列表和选择，拒绝远程读串口和停止。主动设备采集、监控及批量会话调度仍待接入。[逐条对照](combined-evidence.txt) · [挂测联动](combined-power-intent.txt) · [网关收据](combined-gateway.txt) · [批量会话与实时诊断范围](combined-scope.txt)

会话 1 最终交接另包含两个测试夹具的资源锁隔离。在该次交接前后比对 840 个输入，差异仅在 `test_ai_version_query.py` 与 `test_remote_gateway_agent.py`。最终交接共 17 个文件。组合副本保留原网关范围及双方的归档日志与通道证据修正。可在共同起点依次应用[会话 1 补丁](../session1_diagnostics/session1.patch)和[会话 2 补丁](session2.patch)，按[最终输入清单](final-inputs.json)复核。[两次指纹差异](input-revision.json)。用 `git -c core.autocrlf=false apply` 依次应用两份补丁后，逐字节复现了全部 840 个最终输入。[补丁复验](patch-replay.json)

首轮组合专项中，WiFi 的一个模拟用例被宿主资源保护拒绝使用 `serial:com1`。同批生产与页面代码在模拟台架释放后重跑 148 项通过。原生旧项目与归档轮转联合专项通过 2 项，221 个受管窗口。[首次回执](combined-pages.txt) · [整组复验](combined-pages-serial.txt) · [原生旧项目](combined-archived-window.txt)

第一次组合原生批次在三档各运行 100 项并通过。运行期间收到上述两项夹具更新，打包前的指纹复核检出这两份测试文件已变化，并在启动构建前结束该作业。本批保留三档原始文字记录，最终成品另以固定指纹重新验证。[首次原生批次](native/results.json)

第二批通过 100% 和 125%。150% 的 100 项中，DUT 状态区高度用例在后台原子替换 `ui/dut.json` 时读取文件，Windows 返回 `PermissionError`。保留该次失败记录。修正后的用例在原保存函数成功返回后由同一工作线程读取磁盘 JSON，再核对每个标签的高度、重开后的大小和未知字段。150% 单项通过。最终指纹额外包含这一份原生测试文件的修改。[150% 首次错误](native-final/scale-1.5/tests.txt) · [同一入口修正后](height-150.txt)

## 最终 Windows 原生验证

最终输入集合 SHA256 为 `f91d2bf1af28881d0b72a591717bce6ed4c64a1b4f365f2a98a73a201210b77c`。三个独立 Windows 非输入桌面各执行全部 100 项指定原生用例，各记录 1,877 个受管窗口。缺失用例和隔离违规均为零。共享工作区的归档轮转与 150% DUT 高度用例也分别通过。[三档守卫记录](native-release/results.json) · [共享区归档](shared-archive.txt) · [共享区高度](shared-height-150.txt)

| 显式缩放 | 归档目录清空后的反馈 | DUT 状态区高度 | 当前批次证据 |
| --- | --- | --- | --- |
| 100% | [归档窗口](native-release/scale-1/archived-empty-after-refresh.png) | [DUT 配置](native-release/scale-1/dut-status-height-small.png) | [通道证据](native-release/scale-1/ai-current-power-evidence.png) |
| 125% | [归档窗口](native-release/scale-1.25/archived-empty-after-refresh.png) | [DUT 配置](native-release/scale-1.25/dut-status-height-small.png) | [通道证据](native-release/scale-1.25/ai-current-power-evidence.png) |
| 150% | [归档窗口](native-release/scale-1.5/archived-empty-after-refresh.png) | [DUT 配置](native-release/scale-1.5/dut-status-height-small.png) | [通道证据](native-release/scale-1.5/ai-current-power-evidence.png) |

截图中的项目和通道使用测试数据。归档窗口在没有文件时清空原文，保留可用的刷新与关闭入口。目标机实体显示器上的系统 DPI 和视觉核对列在现场表中。

三批本轮原生验证生成 1,286 张过程图。报告保留上表 9 张交付截图，1,277 张已移入回收站。独立集成副本另回收 589 张会话 1 的临时交接副本图，保留其正式报告引用的 3 张。[首批及交接副本清理](cleanup-initial.json) · [失败复验与最终批次清理](cleanup-release.json)

### 复验入口

在集成副本的 `Cheating_machine_execution_tool` 打开 PowerShell。旧项目回放读取迁移前备份凭据，使用临时目录。原生套件和占用同一模拟台架的作业依次执行。

```powershell
$stage = 'validation/pyside6_migration_20261118'
$output = "$stage/session2_integration"
$py = Join-Path $env:LOCALAPPDATA 'LineCheckAssistant/qt-build-py39/Scripts/python.exe'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = (Get-Location).Path + ';' + (Join-Path (Get-Location) 'tests')
& $py "$stage/session1_diagnostics/check_power_parity.py"
& $py "$stage/session1_diagnostics/check_phase5_scope.py"
& $py "$stage/local_chat_intent/check_intent_during_power.py"
& $py "$stage/local_chat_intent/check_gateway_chat.py" --expect-bridge --gateway
& $py "$stage/local_chat_intent/check_selection.py" --case natural
& $py "$stage/local_chat_intent/check_selection.py" --case current
& $py "$stage/local_chat_intent/check_pc_preference.py"
& $py "$stage/archived_projects/check_archived_projects.py" --output "$output/recheck-archived.json"
& $py -c "import os, sys; from tk_test_windows import run_gui_child; r = run_gui_child([sys.executable, 'scripts/run_tests.py', 'validation.pyside6_migration_20261118.session2_integration.check_archived_window.ArchivedWindowTests.test_copied_projects_in_workspace', '-v'], framework='qt', native_render=True, cwd=os.getcwd(), timeout=120, capture_output=True, text=True, encoding='utf-8'); print(r.offscreen_report); sys.exit(r.returncode)"
& $py "$stage/power_command_receipts/check_sixteen.py" --output "$output/recheck-direct.json"
& $py "$stage/power_command_receipts/check_sixteen.py" --qt --output "$output/recheck-qt.json"
& $py scripts/run_tests.py test_ai_session_router test_qt_workspace_adapter test_qt_execution_adapter -v
& $py scripts/verify_capability_coverage.py
& $py scripts/verify_qt_migration.py --python $py --output "$output/recheck-native"
powershell -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1 -Gui Qt
& $py "$stage/instance_pairing/check_candidate.py" "dist/qt-20261121-220335-19897b67" --reviewed-changes "$stage/serial_close_worker/reviewed-sources.json"
```
