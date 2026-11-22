# V1.3.0迁移计划逐项进度

当前源码已在「Ai助手」接入实时通道诊断、自动监控与多通道排障。设置与批准限定本机操作员，批次沿用原调度器。[本次专项与原生验证](qt_channel_diagnostics/REPORT.md)

最新本地 [Windows Qt 组合候选包](../../dist/qt-20261121-220335-19897b67/DUTPilot_portable.zip) 已完成两路集成。完整基线 3,267 项，指定 266 项全部命中。三档 Windows 原生各运行 100 项、每档 1,877 个受管窗口，违规为零。两份旧项目及原电源执行器已模拟复验，干净 Windows、真机和长挂待现场验收。[本批报告、截图与校验文件](session2_integration/REPORT.md)

上一批 [Windows Qt 候选包](../../dist/qt-20261121-194426-f1cfb93a/DUTPilot_portable.zip) 包含明确单通道切换、目标澄清及已有串口的被动读取。完整基线通过 3,265 项，264 项指定回归全部命中。Windows 原生界面在 100%、125%、150% 缩放下各通过 100 项，共 300 次。 [测试、截图与验包记录](local_serial_chat/REPORT.md)

各阶段按原计划的完成判据记录如下。

| 原计划验收项 | 当前结论 |
| --- | --- |
| Phase 0 审计及恢复 | 已保存源码、依赖、配置与数据备份，记录初始失败并恢复 Tk 自动化基线，做过备份恢复演练。[原始审计](PHASE0_AUDIT.md) · [恢复记录](restore_result.json) |
| Phase 1 主窗口 | Windows 原生 Qt 窗口已验证卡片、列表、详情和布局，自动化覆盖 100%、125%、150% 缩放。实际显示器与操作员视觉核对待现场。[主窗口与布局](PHASE1_2_REPORT.md) |
| Phase 2 项目工作台 | 已用两份迁移前真实项目的副本执行打开、保存、重开并比对数据。多项目挂测及停止隔离已用模拟电源验证。[兼容性](archived_projects/REPORT.md) · [双项目挂测](parallel_power/REPORT.md) |
| Phase 3 自动开关机 | Qt 调用原执行器。两入口短等待各写全 8 帧，原入口与 Qt 入口各自独立运行原子进程，均写全 16 个模拟通道两轮的 64 帧。已验证串口异常和部分写入上报失败，以及两个项目的停止隔离。[逐帧复验](power_command_receipts/REPORT.md) 单通道、多通道、条件允许时 16 通道的真实设备流程及每台 500 次循环待现场核对。[开关机链路](PHASE3_REPORT.md) · [本轮停止回执](instance_startup/REPORT.md) |
| Phase 4 全业务老化 | 负责人已确认原工程没有持续开机的独立周期检测执行器，本阶段保留待接入。缺少业务检测、异常恢复与连续 7 天运行的证据。[负责人确认的范围](../../../.claude/plans/pyside6-migration.md) |
| Phase 5 其余页面和多项目 | Qt 已按保存的槽位连接网关，可查询、选择本机授权的项目。按负责人确认，本期拒绝业务消息。[明确的本机通道切换](local_target_routing/REPORT.md)已接入 Qt，支持按当前项目配置复用会话及澄清无效目标。[本机单通道会话读取已打开串口](local_serial_chat/REPORT.md)已用模拟驱动验证。本机自然语言目标识别与当前挂测批次的通道证据已接入。该组合候选交付时尚缺的主动诊断、监控与批量排障，已由后续[Qt 通道诊断源码](qt_channel_diagnostics/REPORT.md)接入；该候选的网关仅开放项目控制命令。[本轮对照](session2_integration/REPORT.md)[实例控制命令](qt_gateway_client/REPORT.md) · [同一槽位连续重启及拒绝回执](gateway_boot_receipts/REPORT.md) · [旧设备会话留存分析](archived_device_chats/REPORT.md) Qt 工作台已验证自动开关机任务使用独立资源并行运行，其他设备任务仍按现有准入范围执行。 |
| Phase 6 线程与生命周期 | 已验证原生 UI 线程守卫、关闭等待、迟到回执、工作区崩溃与原子进程存活保护。实际设备的异常退出与资源释放待验。[项目关闭](gateway_project_lifecycle/REPORT.md) · [崩溃恢复](power_owner_exit/REPORT.md) · [串口启动与退出](serial_lifecycle/REPORT.md) · [收尾失败重试](serial_close_worker/REPORT.md) |
| Phase 7 日志与监控 | 已验证分批刷新、来源过滤、主日志分页与旧数据全文对照。24/72 小时的响应性、内存趋势和日志连续性仍待现场。[批量日志](LOG_BATCH_QT_REPORT.md) · [旧日志](project_main_logs/REPORT.md) · [串口取证和内存实测](serial_passive_read/REPORT.md) |
| Phase 8 Windows 打包 | 已通过标准 Qt 环境、完整基线、目录包及 ZIP 静态比对。干净目标电脑上解压、启动、打开旧项目待验。[打包范围](QT_DIRECTORY_BUILD_REPORT.md) |
| Phase 9 完整回归 | 软件回归包括完整基线、三档原生测试、旧数据和模拟电源。真实 DUT、每台 500 次、全业务持续开机 7 天及 24/72 小时性能验收尚未完成。[现场条件与取证](long_run_acceptance/README.md) |

此前 [Windows Qt 候选包](../../dist/qt-20261121-174731-da5a40fa/DUTPilot_portable.zip) 已修复网关同槽位重启后的回执恢复。完整基线通过 3,261 项，260 项指定用例全部命中。Windows 原生界面在 100%、125%、150% 缩放下各通过 96 项，共 288 次。 [测试和交付记录](gateway_boot_receipts/REPORT.md)

此前 [Windows Qt 候选包](../../dist/qt-20261121-171909-88b5a602/DUTPilot_portable.zip) 已接入旧批次本机设备会话的留存分析，包含串口被动读取和异常收尾修正。完整基线运行 3,260 项，259 项指定测试全部命中，八类门禁通过。Windows 原生界面在 100%、125%、150% 缩放下各通过 96 项，共 288 次。 [证据和交付文件](archived_device_chats/REPORT.md)

此前 [Windows Qt 候选包](../../dist/qt-20261121-165305-f2c9cfc7/DUTPilot_portable.zip) 已包含被动串口取证、部分启动回收和驱动关闭失败保护。完整基线运行 3,259 项，258 项指定回归全部命中，八类门禁通过。Windows 原生界面在 100%、125%、150% 缩放下各通过 95 项。 [本批测试及交付](serial_lifecycle/REPORT.md)

上一批 [Windows Qt 候选包](../../dist/qt-20261121-161023-3fc3681b/DUTPilot_portable.zip) 已按保存的槽位接入授权项目列表与选择，对业务消息返回确定的拒绝回执。完整基线运行 3,255 项，254 项指定回归全部命中，八类门禁通过。Windows 原生界面在 100%、125%、150% 缩放下各通过 95 项。 [阶段交付与未验项目](qt_gateway_client/REPORT.md)

上一批 [Windows Qt 候选包](../../dist/qt-20261121-150514-03643dce/DUTPilot_portable.zip) 已包含原开关机进程存活保护。完整基线 3,251 项通过，251 项指定回归均已执行。Windows 原生用例在 100%、125%、150% 三档各通过 95 项，共 285 次。 完整迁移仍有第 4、5 阶段的软件缺项和目标机、设备及长挂验收。[本批测试与交付](power_owner_exit/REPORT.md)

负责人确认保留已启动的开关机任务。工作区已按项目接入 Windows 子进程存活核对，原进程退出后仍须本机确认结果。真实设备与长挂待现场。[Phase 6、9 进程中断复验](power_owner_exit/REPORT.md)

2026-11-21 该阶段已验包的 Windows 候选为 `qt-20261121-143820-20f3c0f3`。3,248 项完整基线通过，249 项指定用例全部执行。三档 Windows 原生共 285 次通过。成品入口和 331 个项目模块与源码一致，92 个受保护业务文件保留原哈希，另外 5 个与负责人确认的修正快照一致。[候选包、验包证据及待验范围](project_main_logs/REPORT.md)

Phase 6、9 已从 Qt 确认入口及原执行器直接入口复现工作区异常退出后仍有两帧写入模拟电源。Qt 重启会阻止再次启动，但现场须核对旧进程是否仍在运行。[两条入口的进程与电源证据](power_owner_exit/REPORT.md)

2026-11-21 该阶段已验包的 Windows 候选为 `qt-20261121-141002-8f2876a1`。3,247 项完整基线通过，249 项指定用例全部执行。三档 Windows 原生共 285 次通过。成品入口和 331 个项目模块与源码一致，92 个受保护业务文件保留原哈希，另外 5 个与负责人确认的修正快照一致。[候选包、验包证据及待验范围](parallel_power/REPORT.md)

Phase 2、7、8、9 已用迁移前备份中的两份实际项目验证 Qt 源码打开、保存与重开。四条旧工作台记录在重开后保留两条成功和两条未知，旧配置版本及运行快照内容核对通过。主执行日志与资源监测的 24 个文件可从项目归档窗口翻页，Qt 归档接口已逐行核对 980 行原文。目标机部署仍待验。[实际项目兼容性报告](archived_projects/REPORT.md) · [旧主日志复验](project_main_logs/REPORT.md)

Phase 2、3 和 6 已接入独立项目在原工作台同时启动开关机、分别停止及独立释放资源。Qt 准入和原物理资源协调器均已通过模拟验证。[两个工作台项目与真实子进程](parallel_power/REPORT.md)

Phase 6、9 的进程中断复验已覆盖两个模拟任务同时运行时异常退出、重开后保留未知、单独核实其中一项及取消再次准备。恢复过程未重放硬件动作，另一项目的保护继续有效。[独立进程复验](parallel_power/process-interruption.json)

2026-11-21 当时已验包的 Windows 候选为 `qt-20261121-131321-f895c473`。3,245 项完整基线通过，247 项指定用例全部执行。三档 Windows 原生共 282 次通过。成品入口和 330 个项目模块与源码一致，92 个受保护业务文件保留原哈希，另外 5 个与负责人确认的修正快照一致。[候选包、验包证据及待验范围](power_command_receipts/REPORT.md)

2026-11-21 当时已验包的 Windows 候选为 `qt-20261121-123123-b69436ef`。3,243 项完整基线通过，245 项指定用例全部执行。三档 Windows 原生共 282 次通过。成品入口和 330 个项目模块与源码一致，97 个原业务文件与迁移前的哈希一致。[候选包、验包证据及待验范围](gateway_project_lifecycle/REPORT.md)

**Phase 3 已修正原执行器的两类成功误报。** 短等待的原入口和 Qt 入口均写全 8 帧，模拟串口异常后任务报告失败。真实电源和 DUT 仍待现场验收。[原始失败](power_worker_replay/REPORT.md) · [修正后验证](power_command_receipts/REPORT.md)

Phase 3 新增[Windows 原执行子进程对照](power_worker_replay/REPORT.md)。原入口与 Qt 入口均运行旧通道线程、指令队列和计时逻辑，已核对虚拟电源逐帧记录、原结果文件和真实子进程的停止收尾。DUT 实机、物理电源时序和长期试验仍待现场。

Phase 5/6 已修正原网关接收与收件箱处理重叠时的提前关闭，以及 Qt 在平台仍运行时的退出顺序。模拟原生窗口和双项目回执证据见[网关与项目关闭](gateway_project_lifecycle/REPORT.md)。该批次尚未接入实例客户端自动启动。最新候选已开放项目控制命令，业务转发及现场验收仍待完成。

2026-11-21 当时已验包的 Windows 候选为 `qt-20261121-120503-1bc9ddf8`。3,240 项完整基线通过，242 项指定用例全部执行。三档 Windows 原生共 282 次通过。成品入口和 330 个项目模块与源码一致，97 个原业务文件与迁移前的哈希一致。[候选包、验包证据及待验范围](instance_startup/REPORT.md)

**整份计划仍在实施。** Qt 工作台和主要业务页面已接入，默认入口保留 Tk。Windows 候选需在目标机完整解压后运行。源码通过独立 Qt 环境的 `run_dutpilot_qt.py --workspace` 进入工作区。[源码运行方法](../../../README.md) · [操作员手册](../../line_check_assistant_README.md)

**业务及数据兼容性。** 项目仍由原项目服务管理，任务使用已保存配置的运行快照。开关机复用原执行子进程，Qt 通过任务服务收集逐通道回执并请求安全停止。已保留审批、资源占用和模拟电源帧记录。真实电源输出待现场采集。保留旧入口与备份恢复路径，当前候选的真实硬件结论仍需负责人现场提供。[原始审计与恢复](PHASE0_AUDIT.md) · [开关机复验](power_command_receipts/REPORT.md) · [未知任务核实](power_owner_exit/REPORT.md)

2026-11-21，Qt 已接入原启动模式和实例允许范围的人工确认与保存。原开关机服务的停止回执经过两项目模拟复核。[实例配置与挂测停止报告](instance_startup/REPORT.md)

2026-11-21，Phase 5 串口终端的本机诊断快照已纳入 Windows 候选包，可从指定项目的通道读取已打开会话的近期输出及占用状态。完整基线 3,235 项、三档原生 276 次通过。当时的验证只覆盖串口终端。[终端阶段报告](serial_diagnostics/REPORT.md) 后续的[本机会话读取验证](local_serial_chat/REPORT.md)已从项目 AI 窗口覆盖同一被动读取器。

多实例启动链复核：原工作区在创建时读取下一次启动槽位，在 `WorkspaceService.register_controller` 收到项目控制器后才装配网关运行时。生产代码中当前调用点位于 Tk 的 `src/ui/ai_assistant_controller.py`。Qt 项目执行器虽已创建本项目能力服务，尚未接入这段注册。后续启动模式迁移须同时核对保存后的重启、项目本地批准范围及关闭时的连接回收；配对成功只证明身份已登记。

Phase 5 的本机电脑连续诊断已纳入最新 Windows 候选包，复用原模型工具资格、真实挂测批次和只读范围。可补充问题、停止本轮及重开证据。常规电脑修复与设备诊断、串口联动、远程平台控制面仍待接入。[本机诊断与 Windows 交付报告](pc_diagnosis/REPORT.md)

2026-11-21，Phase 8 已生成包含本机实例配对的 Windows 候选包。Phase 3 新增全选 16 通道的模拟回归，复核保存参数、原任务快照、逐通道失败及迟到消息。真实时序、目标电脑和长期运行继续待验。[最新交付与验证](instance_pairing/REPORT.md)

2026-11-21，Phase 5 的本机网关签发、实例槽位读取与确认兑换已接入 Qt 源码。旧启动模式配置、平台连接及实时诊断仍有待迁移项。[配对阶段记录](instance_pairing/REPORT.md)

本轮按最新附件核对 Phase 0–9。受保护核心源码、Qt 详情、会话审批、本机网关配置与生命周期的最新证据以及剩余控制面差异，见[当前候选迁移总结与测试报告](current_candidate_review/REPORT.md)。

2026-11-21，Qt 持久化任务历史支持跨页筛选，远程可访问项目的本机确认和保存已接入原服务。自动化覆盖与现场待办见[本轮增量报告](HISTORY_SCOPE_QT_REPORT.md)。

2026-11-21 交接复核发现串口部分关闭重试、每通道执行阶段和更新界面日志写盘三处差异。本轮软件结果与现场条件分列在[统一 GUI 升级执行记录](../../../docs/GUI_UPGRADE_EXECUTION_PLAN.md)；Phase 9 的进程采样及证据要求见[长挂验收](long_run_acceptance/README.md)。

此前的[完整源码基线](AI_CHAT_PRESENTATION_QT_REPORT.md)执行 3,211 项，覆盖 239 项指定用例。同一阶段的[三档 Qt 原生复验](LEGACY_RUN_HISTORY_QT_REPORT.md)通过 258 项。[Windows Qt 目录验证包](QT_DIRECTORY_BUILD_REPORT.md)对应此前 3,185 项构建基线。正式验包、现场与长期验收继续待办。

依据负责人附件《DUTPilot V1.3.0 — PySide6 GUI迁移执行计划》，2026-11-18。此表保留完整目标，代码/自动化完成与现场验收分列；不能以当前已实现子集改写完成标准。

本表对应第一阶段。待完整验收及 Git 基线保存后，再审计第二阶段的统一 GUI 设计规范与架构升级。[阶段管理原则](../../../.claude/plans/pyside6-migration.md)

| 原计划要求 | 当前证据 | 未完成及完成所需证据 |
| --- | --- | --- |
| Phase 0：目录/窗口/依赖/Tk耦合/任务取消/资源/兼容/修改清单审计 | [审计](PHASE0_AUDIT.md)、仓库外备份和恢复演练。Tk 发布包内 175 个项目代码对象均与 V1.2.10 标签一致，其中 121 个与迁移前工作区备份一致。[静态比对](current_candidate_review/tk-archive-sources.json) | 还原迁移前开发现场应使用备份源码和数据。目标电脑的实际构建与启动仍须现场核验 |
| Phase 1：Qt Widgets壳/主题/自适应/侧栏折叠/日志分栏 | [1/2报告](PHASE1_2_REPORT.md)、每轮原生1920/1366及三档Qt缩放截图 | Windows真实系统DPI切换/实体多屏/负责人目视 |
| Phase 2：原格式项目管理、卡片/列表/搜索/筛选/排序、状态、详情 | 原WorkspaceService/ProjectStore，新建/打开/旧配置导入/保存/改名/复制/关闭、切换、[最近项目](RECENT_PROJECTS_QT_REPORT.md)、[Qt 配置页面草稿恢复](EDITOR_RECOVERY_QT_REPORT.md)与[导入平台配置选择](IMPORTED_CONNECTIONS_QT_REPORT.md) | [旧工作台直接启动的运行记录](LEGACY_RUN_HISTORY_QT_REPORT.md)已支持分页浏览。[实际旧项目与单项目配置导入](archived_projects/REPORT.md)已在本机源码复验。旧 Tk 页面草稿仍从原窗口恢复，目标电脑上的实际项目及部署待验收 |
| Phase 3：原自动开关机/环境检查、确认/停止、16通道、原配置 | [开关机](PHASE3_REPORT.md)、[六页配置](CONFIGURATION_REPORT.md)、[通道](CHANNELS_REPORT.md)、[三项全流程](PIPELINE_QT_REPORT.md)、[单次预备测试](PRETEST_QT_REPORT.md)、[样机版本查询](VERSION_QUERY_QT_REPORT.md)、[消息试发](PUSH_TRIAL_QT_REPORT.md)、[失败轮次续跑](RESUME_QT_REPORT.md)、[批次后排队](RESUME_QUEUE_QT_REPORT.md)、[资源候选分组](RESOURCE_OPTIONS_QT_REPORT.md)、[工具栏刷新](HOST_INVENTORY_QT_REPORT.md)、[单次自动上/下电](SINGLE_POWER_QT_REPORT.md)、[网卡改名与通道同步](ADAPTER_RENAME_QT_REPORT.md)。复用原编排器和业务服务，已通过[16 通道模拟](instance_pairing/REPORT.md)、[原业务停止回执复核](instance_startup/REPORT.md)、[原队列逐帧回执复验](power_command_receipts/REPORT.md)与[双项目独立运行](parallel_power/REPORT.md) | 网卡改名待现场验收。真实单/多/16通道、故障、上下电时序与长期验收 |
| Phase 4：持续开机全业务老化 | 真实代码未发现独立持续开机检测服务；负责人此前明确“尚未实现，先保留待接入” | 保持待接入，不改写成轮次型aging.start，也不在GUI迁移内发明检测逻辑。最终报告必须注明此既定业务缺口 |
| Phase 5：串口终端 | [串口报告](SERIAL_REPORT.md)，原会话、控制锁、落盘、手动确认和关闭收尾。[全包升级自动串口观察](FIRMWARE_OBSERVATION_REPORT.md)、[原全流程预启动](PIPELINE_QT_REPORT.md)、[窗口状态恢复](WINDOW_PLACEMENT_QT_REPORT.md)及[手动读取已打开会话快照](serial_diagnostics/REPORT.md)已接入 | AI Debug 联动、实际显示器变化和真实高频串口验收 |
| Phase 5：DUT配置 | [Telnet](DUT_TELNET_REPORT.md)、[WAN](WAN_REPORT.md)、[WiFi](WIFI_REPORT.md)、[语音/TR069](VOICE_TR069_REPORT.md)六页使用原服务/Job、独立目标、查询/配置/确认/停止。[DUT 外窗宽高](WINDOW_PLACEMENT_QT_REPORT.md)和[各页状态区](DUT_STATUS_HEIGHT_QT_REPORT.md)已兼容原项目状态。[与写参共用登录输入](PARAMETER_LOGIN_QT_REPORT.md)即时联动 | 负责人于 2026-11-21 确认 Qt 保留显式保存，作为与旧 Tk 延迟自动保存的已知差异验收。真实设备与目标机待复验 |
| Phase 5：样机升级、写参、ONU | [样机升级](FIRMWARE_REPORT.md)已接入页面与三种全包模式，含[逐台状态和自动串口日志](FIRMWARE_OBSERVATION_REPORT.md)和[无程控电源时的手动重启](FIRMWARE_MANUAL_REPORT.md)。[写参](PARAMETER_WRITER_REPORT.md)已接入参数表、独立批量任务和[串口回退的自动只读日志](PARAMETER_OBSERVATION_REPORT.md)。[ONU](NEXT_ONU_AUDIT.md) 已接入配置、查询、注册、批量删除、独立保存及 C300 单台离线清理重试。三项全流程按现行 Tk 入口保留串口、环境检查和开关机。手动重启和 ONU 的 6 项原生模拟用例三档通过 | 真实样机、OLT 和现场线程收尾验证 |
| Phase 5：AI诊断、模型/权限、远程平台、多实例/全局与其它工具 | [AI 模型连接](MODEL_SETTINGS_QT_REPORT.md)复用原共享账号、项目选择、加密及模型探测。[Qt 普通问答](AI_CHAT_QT_REPORT.md)复用原会话及项目历史。[Qt 会话排版](AI_CHAT_PRESENTATION_QT_REPORT.md)恢复原 Markdown、状态与流式显示。[Qt 诊断报告](AI_REPORTS_QT_REPORT.md)接入原报告、证据、标题和批量删除保护。[Qt 共用案例](AI_CASES_QT_REPORT.md)接入人工确认、报告来源、版本和检索状态。[Qt 报告接手](AI_HANDOFF_QT_REPORT.md)接入新旧报告转入原会话。[Qt 留存报告分析](AI_REPORT_ANALYSIS_QT_REPORT.md)接入本机报告提问、证据检索和停止。[Qt 实时 AI 日志](AI_LIVE_LOG_QT_REPORT.md)复用原摘要和原文归档 | 已接入[远程项目范围的本机确认与保存](HISTORY_SCOPE_QT_REPORT.md)。已接入[会话权限查看、具体操作审批与网关管理](current_candidate_review/REPORT.md)和[本机实例配对](instance_pairing/REPORT.md)。[本机电脑连续诊断](pc_diagnosis/REPORT.md)与[下次启动配置](instance_startup/REPORT.md)已接入。本机自然语言目标识别、已有串口的被动读取和当前通道证据已通过模拟复验，Qt 网关客户端已验证项目列表和选择。后续源码已接入主动查询、异常监控及逐通道批量调度。[源码验证](qt_channel_diagnostics/REPORT.md)本批网关限项目控制。[组合候选证据](session2_integration/REPORT.md)真实模型连接、设备和平台待现场确认 |
| Phase 6：主线程桥接/事件限流/订阅代次/安全退出/重启未知保护 | 工作区后台队列、单个主定时器、项目/任务代次、原Job/串口票据、[独立的只读枚举](HOST_INVENTORY_QT_REPORT.md)、[原 GUI 未知保护](UNKNOWN_TASK_QT_REPORT.md)及[持久化业务任务现场核实](JOB_REVIEW_QT_REPORT.md) | 原未完成历史、后续模块覆盖、整机可靠性报告及现场验收 |
| Phase 7：项目/run/通道日志、级别/搜索/跟随/导出/清屏/历史按需/持久化 | 有界工作区日志和独立原串口文件、批量显示/跟随/清屏、[实时筛选与导出](LOG_SCOPE_QT_REPORT.md)、[持久任务历史分页与本页导出](LOG_HISTORY_QT_REPORT.md)、[完整任务的跨页筛选](HISTORY_SCOPE_QT_REPORT.md)、[工作区与项目串口原文](ARCHIVED_LOGS_QT_REPORT.md)、[系统状态及写入/积压观察](SYSTEM_HEALTH_QT_REPORT.md)、[满载增量显示与四线程 6,000 条短时写盘](LOG_BATCH_QT_REPORT.md)、[打开通道结果与本次 WiFi 文件](CHANNEL_LOGS_QT_REPORT.md)、[按历史任务打开原批次文件](HISTORY_RESULT_FILES_QT_REPORT.md) | 未留有项目或运行归属的旧文件由原目录核对。持续开机业务检测独立来源、实机持续高负载与 24/72 小时验收待完成 |
| 多项目兼容：状态/配置/日志/停止隔离，冲突保护 | 原项目UUID/快照/Job/资源；模拟切换和冲突保护已有证据。[两个独立项目执行器](instance_startup/REPORT.md)验证停止 A 时 B 保有自身租约并正常结束 | [工作台中的独立自动开关机](parallel_power/REPORT.md)已验证并行启动及停止隔离。其他设备任务的并行组合与物理现场仍待复验 |
| Phase 8：独立固定依赖、标准目录包、Qt 插件/DLL/资源/无控制台 | 标准入口已冻结 [Qt 验证目录包](QT_DIRECTORY_BUILD_REPORT.md)，完整基线、Windows GUI PE、Qt 插件、关键业务 PYZ、目录/ZIP 字节、哈希和许可文件通过静态核对 | 标准构建首次遇到压缩文件占用，已切换 Qt ZIP 实现并验证同一冻结结果。目标 Windows 清洁环境实际启动与发布前组件许可核对待办 |
| Phase 8：名称/版本/图标/应用数据、配置历史/备份兼容 | 实际 EXE 产品版本 1.3.0、DUTPilot 图标及便携模板已验证。源码启动契约核对双击路径、便携目录及单实例转发。[Qt 检查更新](APP_UPDATE_QT_REPORT.md)接入原检查、确认下载和校验收尾 | 目标电脑运行、数据迁移复验、真实发布下载与最终发行仍待验收 |
| Phase 9：全部界面/数据/任务控制/Mock覆盖 | 分阶段报告与各轮完整基线、强制三档Qt原生ID、截图 | 所有剩余页面与旧数据场景、故障/异常退出/多任务完整回归，不能用当前窄范围通过代替 |
| Phase 9：真实设备/24h/72h/更长挂测、内存/CPU/线程/响应/日志/调度/结果/资源 | 尚无本次Qt迁移真实验收证据 | 等负责人确认硬件范围/现场执行；结果未到不得写通过；短时Mock只证明自动化覆盖范围 |
| 最终切换：功能全量、现场/长挂、独立EXE/数据兼容后默认Qt，保留Tk | 当前默认仍Tk，未提前切换 | 按原计划全部条件逐项取证后再切默认，保留旧入口，不自动删除旧源码或把包装成功等同部署成功 |

每个增量报告记录修改文件、实际功能、复用服务、测试结论、前后界面核对、参考图差异和回退范围。相应自动验证通过且结论已入报告后，可以清理开发批次生成的截图、日志、结果清单和已被通过批次覆盖的失败证据。完整汇总须覆盖此表全部行。[本次清理与三档批次汇总](VALIDATION_EVIDENCE_CLEANUP.md)

Phase 3 和 Phase 7 在通道详情和右键菜单接入本次重试／失败历史。原事件按当前开关机批次和通道读取，最新页随原重试及续跑事件更新。现场重试和长挂证据继续按原计划验收。[通道重试历史](CHANNEL_RETRY_HISTORY_QT_REPORT.md)

Phase 3 和 Phase 5 已接入六个原项目功能窗口的尺寸记忆，覆盖全流程、测试项配置、样机升级、写样机参数、ONU 注册和通道重试历史。[窗口尺寸兼容](MODULE_WINDOW_SIZES_QT_REPORT.md)

Phase 2 的 Qt 项目菜单现已接入原工作台的新建、打开、保存快捷键和当前项目目录入口。项目目录按命令发起时的项目 ID 查找，子窗口拥有焦点时主窗口快捷键不触发。[项目菜单测试与复跑](PROJECT_COMMANDS_QT_REPORT.md)

Phase 2 和 Phase 7 可以在「任务历史」按项目翻阅旧 Tk 工作台直接启动的运行记录。旧项目没有 Job 数据库也可读取，已核实的未知结果保留原含义。Phase 9 新增同项目同通道连续两批的迟到事件回归。95 项专项已通过。[旧工作台运行历史](LEGACY_RUN_HISTORY_QT_REPORT.md) · [跨批次事件复验](PHASE9_LATE_BATCH_QT_REPORT.md)

2026-11-21 核对仍待迁移的项目菜单操作。原 Tk 的「远程可访问项目」只列已打开项目，用户确认后由共享服务保存授权范围、撤销对应会话路由并保留已准入任务。「多实例 / 统一网关」另有实例配对、网关设置、启停、状态和撤销操作。原 AI 控制器向工作区注册时可启动已配置的网关连接。首次审计时 Qt 工作区仅接入本机项目管理和导入配置选择。现已补入远程项目授权、本机网关管理和实例配对，接入真实平台仍依赖控制器注册及其运行时。[原项目菜单](../../src/ui/project_workspace.py) · [工作区服务](../../src/services/workspace_service.py) · [原多实例页面](../../src/ui/ai_multi_instance_tab.py)

Phase 5 的项目会话管理已接入多选、改名、刷新与批量删除。确认固定当前项目的会话名单，忙碌或清理中的子会话沿用原整批拦截。清空当前列表时保留确认期间新增的记录。[Qt 排障会话管理](AI_SESSION_MANAGER_QT_REPORT.md)

串口与网卡候选已按原规则接入 Qt 通道配置。主工具栏、通道窗口与设备管理共用只读扫描。设备管理展示接口 GUID、活动租约和项目通道绑定。[资源候选阶段报告](RESOURCE_OPTIONS_QT_REPORT.md) · [工具栏刷新报告](HOST_INVENTORY_QT_REPORT.md) · [Qt 设备管理](DEVICE_INVENTORY_QT_REPORT.md)。网卡改名已接入通道候选选择，实机和版本保存后重开待验证。

Phase 7 已启用实时缓冲导出和持久任务分页。工作区历史文本仅存时间、项目 ID 和消息，后续整合时对缺少的级别、任务或通道如实显示。

Phase 3 的单次「自动上/下电」已接入 Qt。启动前核对本次电源口、方向和已选通道。空电源口走手动重启确认。程控操作使用原 `turn_on_selected_channels` 或 `turn_off_selected_channels`，保留原顺序、间隔和收尾。项目配置保存、通用电源能力和挂测批次分别留在各自入口。[本轮报告](SINGLE_POWER_QT_REPORT.md) · 旧入口和模拟串口回归

Phase 5、6 的共享网关已修正启动时第一条项目列表遗漏当前项目及线程部分启动失败时的资源归属。Qt 自动挂接项目会话仍待完成。[启动顺序与模拟复验](gateway_startup_order/REPORT.md)
