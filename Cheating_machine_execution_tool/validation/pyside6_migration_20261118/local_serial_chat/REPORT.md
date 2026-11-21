

# Qt 本机通道会话读取已有串口

在同一临时项目、同一模拟驱动和同一通道下，原串口读取器能取得已接收的标记，Qt 模型当时只有询问用户与检索留存证据两个入口。[对照脚本](check_serial_chat.py) · [接入前](before.json)

独立源码副本接入后，模拟模型通过原有的 read_serial_log 请求取得该标记，输出进入同一会话的证据库。原监控仍持有串口。设备写入、物理串口打开及外部请求均为 0。模型提供其他端口参数、工具调用时项目目标已经变化或请求未开放工具的情况均在隔离专项中验证。[隔离联动](isolated-after.json) · [异常用例](isolated-negative.txt) · [正式源码复验](after.json)

[Qt 会话](../../../src/services/qt_ai_chat.py)在每次给模型提供工具和执行读取前复核本机来源、模型资格、批次及项目目标。读取沿用[原串口读取器](../../../src/services/ai_serial_client.py)和[本项目执行服务](../../../src/services/qt_execution_adapter.py)已有的管理器。每次最多读 64 KiB。工具清单允许询问用户、检索留存材料和被动读取本通道已打开的串口。报告、旧批次及远程来源不会取得这一入口。

涉及[原会话工具清单入口](../../../src/services/ai_conversation_service.py)、[工作区装配](../../../src/services/qt_workspace_adapter.py)、[会话状态模型](../../../src/models/qt_ai_chat.py)、[Qt 窗口](../../../src/ui/qt/ai_chat_dialog.py)、[工作区专项](../../../tests/test_qt_workspace_adapter.py)、[原生专项](../../../tests/qt_workbench_probe.py)及两份验证清单。本轮也包含[单通道选择与复用](../local_target_routing/REPORT.md)。

本阶段复用既有 Qt 会话的输入框、发送按钮和权限窗口。与原计划的主工作台布局相比，仅会话状态增加串口可读范围。真实 Windows 源码窗口的 125% 截图可读到通道 7、模型回复及模拟接收标记。[125% 窗口](native-smoke/ai-passive-serial.png) 原 Tk 启动方式继续可用。[切换与回退](../../../line_check_assistant_README.md)

## Windows 后台刷新与文件共享

串行首轮中，125% 的旧报告用例等待详情时看到了 PermissionError。150% 的手动重启确认用例本身结束，但窗口守卫捕获一个未接管的「项目操作未完成」弹框，仍判失败。当时两处错误提示均未记录触发操作的文件路径。单独重复旧报告 15 次、手动重启用例 12 次均通过。[首轮原生记录](native-initial/results.json) · [旧报告复验](report-handoff-repeat.txt) · [手动重启复验](manual-upgrade-repeat.txt)

使用 Windows 文件共享模式独占临时项目的配置，再等待工作台正常的一秒自动刷新，可独立复现 PermissionError 和会阻塞工作台的模态提示。释放文件后，下次自动刷新成功。[Windows 文件占用复现](locked-refresh-before.txt) 此复现确定了自动刷新遇到文件占用时的行为；首轮两例的具体文件占用来源未能还原。

[Qt 工作台控制器](../../../src/ui/qt/workspace_controller.py)已将自动刷新失败反馈到状态栏和原执行日志。操作员可以看到上次取得的项目状态，工作台下一次自动刷新继续读取。人工打开项目等命令仍显示原失败提示。原生回归同时检查这两类反馈，窗口守卫继续启用。[修正后的真实文件占用与原生回归](locked-refresh-after.txt)

## 独立源码与模拟资源

第二轮共享目录的 125% 用例收到具体的“模拟网卡被其他进程占用”回执。核对进程树发现同机另一套原生回归也在运行，并使用同名测试网卡。另一开发任务期间还增加了不同的跨项目远程路由。本次保留其工作区文件，以本轮先前保存的源码副本作为候选来源。[共享目录结果](native-shared/results.json) · [候选源码边界](source-isolation.json)

与上一已验包候选逐模块核对，332 个既有打包模块中只有本次通道切换、被动串口及自动刷新涉及的 10 个模块变更。候选沿用原网关实现。独立工作树保留此前的验证门禁和本轮新增用例；另一开发任务自己的新增模块与专属回归属于其工作树。本次不对另一开发任务作发布或验收判断。

[模拟夹具](../../../tests/qt_execution_fakes.py)为每个原生验证进程使用独立的模拟设备锁命名空间。资源键及实际 Windows 互斥仍由原实现处理，同一验证进程内的工作台共同使用该模拟设备组。已用独立子进程实测同组拒绝第二次占用、不同组可独立持有、释放后可重新取得。生产路径与正式跨进程资源回归继续使用原系统锁。[跨进程校验脚本](check_fixture_mutex.py) · [结果](fixture-mutex.json)

## 复验入口

从独立候选的主源码目录使用项目锁定的 Qt 解释器运行。原生窗口在非输入桌面完成测试。标准构建脚本内执行完整基线及静态验包。

```powershell
$qtPython = Join-Path $env:LOCALAPPDATA 'LineCheckAssistant\qt-build-py39\Scripts\python.exe'
& $qtPython scripts/run_tests.py test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_local_channel_passive_serial_rechecks_binding_and_never_writes
$evidence = Join-Path $env:TEMP ('DUTPilot-Qt-verify-' + [guid]::NewGuid().ToString('N'))
& $qtPython scripts/verify_qt_migration.py --python $qtPython --output $evidence
powershell -ExecutionPolicy Bypass -File build_line_check_assistant.ps1 -Gui Qt
```

本机留有[独立源码入口](C:/Users/Administrator/AppData/Local/LineCheckAssistant/qt-source/local-channel-0d686fd9/Cheating_machine_execution_tool/run_dutpilot_qt.py)。本轮源码、验证脚本、构建规格及手册共 697 个纳入指纹计算的文件，集合 SHA256 为 77579b16d205ec3b9a6abf5b254b671c4fe62741af691426cb6f6e62699c314d。正式验包另行对比每个已打包项目模块。

独立工作树首次构建时，工作区测试文件夹带了另一开发任务新加入的「跨项目接收版本查询并执行」用例。基线因候选不含该功能而失败，标准脚本阻止了打包。随后从先前保存的本轮测试源文件恢复整份工作区测试，逐行核对两份文件的唯一区别为后来插入的该项测试。旧入口、原指定回归和本次单通道与串口回归继续运行。原生套件和候选产品源码在此过程中一致。[首次独立构建记录](build-initial-isolated.txt) · [两次源码指纹和测试来源](source-isolation.json)

## Windows 验证与候选包

107 项相关测试通过。完整基线通过 3,265 项，264 项指定回归全部命中。Windows 原生界面在 100%、125%、150% 缩放下各通过 100 项，共 300 次。 三档原生测试与标准打包基线已按顺序执行。[专项结果](focused.txt) · [三档原生结果](native/results.json) · [完整基线与构建记录](build.txt)

Windows 源码窗口从发送入口切换到通道 7，并将模拟驱动已收到的标记写入本会话。保留三档原生截图。[100%](native/scale-1/ai-passive-serial.png) · [125%](native/scale-1.25/ai-passive-serial.png) · [150%](native/scale-1.5/ai-passive-serial.png)

静态验包核对 Windows 入口、332 个项目模块、操作员手册和 ZIP 完整性。97 个受保护业务文件中，90 个保留原始哈希，7 个与已记录的修正快照一致。ZIP 为 55,366,605 字节，SHA256 为 `180642fc5714b6b54134c99c1f5bd5bf2409518ec7ad3204f37323bc36966449`。候选从独立源码目录按标准脚本构建，构建机未运行新 EXE。[核对记录](packaged-sources.json) · [便携 ZIP](../../../dist/qt-20261121-194426-f1cfb93a/DUTPilot_portable.zip) · [SHA256 文件](../../../dist/qt-20261121-194426-f1cfb93a/DUTPilot_portable.zip.sha256.txt)

真实串口、受测设备每台 500 次开关机、持续开机 7 天、24/72 小时稳定性及干净目标机部署仍待验。全业务持续开机执行器按负责人决定另行接入。本期网关对非项目控制消息明确回绝。其余设备实时诊断与通用自然语言选目标仍在迁移。[各阶段总表](../MIGRATION_PROGRESS.md)

## 同一份交付源码的业务复验

本机通道 7 会话读取已有模拟串口时，网关的项目列表、切换项目均返回完成，远程读串口和停止任务均返回拒绝。模型和网关出口使用模拟服务，串口写入、真实串口打开和外部请求均为零。[并发回执](gateway-chat.json)

模拟电源运行中，远程停止返回拒绝，重复投递保留原回执。原子进程继续持有资源，两个通道各写完两轮断电和通电，共 8 帧后正常结束。[逐帧记录](final-power.json)

两个迁移前的真实项目副本通过打开、保存、重开核对。原有 2 条成功、2 条未知记录及 72 行旧工作台日志均可读取。备份文件哈希保持一致。[旧项目核对](archived-projects.json)

明确指定通道 7 时，Qt 和旧路由均可直接选择目标，Qt 无需请求模型。对于“请把排查对象换到七号测试位”，旧路由通过一次模拟意图判定选到通道 7，Qt 仍进入通用会话。该项继续列在 Phase 5。[明确通道](selection-current.json) · [自然语言差异](selection-natural.json)

阶段报告完成后，已将 1,248 张过程 PNG 移入回收站，报告引用的 4 张 Windows 原生截图保留。
