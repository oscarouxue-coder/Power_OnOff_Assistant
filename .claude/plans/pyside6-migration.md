# DUTPilot PySide6 分阶段迁移

日期：2026-11-18。依据负责人本轮 V1.3.0 迁移计划；替代继续扩展 Tk 视觉还原的方向。

## 两阶段管理原则（2026-11-20 负责人确认）

第一阶段继续按《DUTPilot V1.3.0 — PySide6 GUI 迁移执行计划》推进。沿用当前分阶段实施与证据，覆盖主窗口、多项目、原测试和其它页面、线程与日志、资源与生命周期、Windows 打包，以及自动化、真实设备和长期稳定性验收。测试逻辑、检测周期、结果判据及硬件控制行为继续以原实现为依据。

第一阶段内保持界面和业务服务分离。复用已有 UI 组件并集中管理样式、颜色、字体和图标。分清项目、任务、DUT、通道和业务状态，测试准备继续由可复用业务服务处理。当前迁移照原边界推进，保留后续扩展空间。

第一阶段正式通过完整验收后，先保存 Git 基线，再重新审计代码与《DUTPilot V1.3.x — 统一 GUI 设计规范与架构升级开发计划》的差异。第二阶段才启动 DUT 公共准备、项目创建向导、自动/人工/可选步骤管理、公共与专项流程分离、统一设计规范与组件库、状态模型及图标和进度交互。第二阶段继承第一阶段成果，以增量改造为主。

## 当前边界

- 首先完成 Phase 0 审计和基线；此检查点不批量重写 GUI，不修改设备业务、不删除 Tk、不改默认入口或版本号。
- 原工作区包含 `ui/unified-workbench-phase1` 上未提交的工作台、离屏测试门禁及未完成的布局调整。本轮建立 `feature/pyside6-migration`，原样保留并做仓库外快照；新分支本身不保存未提交内容，不能代替快照。
- 总体说明中的“不需要支持回退”与正文保留 Tk/原产物的要求不一致：不新增产品内的双框架切换/自动回退系统；仍按正文保留 Tk 源码入口和本地基线，禁止提前删除。
- 负责人已确认持续开机全业务老化尚未实现；Phase 4 保持待接入，不把现有 `aging.start` 当作持续开机检测，也不在 GUI 迁移中开发新的检测流程。
- 2026-11-21，原执行器短等待漏帧、串口写失败后仍报成功，均已从旧入口与 Qt 入口复现。负责人确认单独修复本轮完成判定，仅使用模拟电源验证，保留原帧格式、延时和停止保护。执行器现以完整写入为通道开始等待的依据，保留原业务和现场验收范围。[原始对照](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/power_worker_replay/REPORT.md) · [独立修复与复验](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/power_command_receipts/REPORT.md)
- 分阶段提交指阶段性交付；Git 提交/推送和正式打包分别遵守已有授权与门禁，不自动执行。

## Phase 0 交付与放行

审计：[PHASE0_AUDIT.md](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PHASE0_AUDIT.md)。机器清单、GUI 类/窗口清单、依赖元数据、本地备份凭据、基线输出位于同目录。

放行条件：当前源码完整基线通过；隔离源码启动/关闭验证；原始源码/依赖/配置/历史可恢复；已有产物版本证据明确。源码测试、历史产物存在、实际构建、目标电脑及真实设备验收必须分开记录。若基线失败，先处理直接相关问题并重验，不以历史通过结果放行。

2026-11-18本检查点：审计/本地备份/受管原生Tk捕获完成；完整基线exit 1（能力快照陈旧、全量测试Tcl原生中止）；定向14项中13通过、sash拖动1项失败。历史EXE版本与当前源码未建立匹配。Phase 0尚未放行，不进入Qt大规模重写，详细证据和后续直接修复边界见审计末节。

后续实施（同日）：上述自动化阻断已修复，2969项完整基线通过；910份源码/17份SQLite恢复演练通过，未覆盖原目录。独立Qt壳、原生测试隔离、三档缩放与真实项目基础管理已实现，最新文件、截图、完整/专项结果与尚未迁移范围见[阶段1/2报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PHASE1_2_REPORT.md)。默认Tk入口、原业务引擎和本机配置保持；Qt设备启动/停止和其它业务页未接通，不宣称迁移全部完成或现场验收。历史旧产物匹配、Qt打包和目标电脑留到对应交付阶段核验。

## 分阶段代码落点

| 阶段 | 直接边界 / 新文件计划 | 复用入口 | 完成证据 |
| --- | --- | --- | --- |
| 1 | `run_dutpilot_qt.py`；`src/ui/qt/{application,main_window,theme,demo_data,dashboard,project_detail,log_panel}.py`；必要时局部懒加载 `src/ui/__init__.py` | 不接真实执行；演示明确标记；不实例化 Tk | 独立环境精确锁定、退出/切页/缩放、私有桌面截图、Qt 离屏保护证据 |
| 2 | `src/services/qt_workspace_adapter.py`、`src/ui/qt/project_model.py`、项目对话框 | WorkspaceService / ProjectStore / ProjectStatusService / workbench_status_service | 旧项目副本打开/保存/切换/关闭、真实状态一致、恢复/未知保护 |
| 3 | `src/services/qt_execution_adapter.py`、`src/ui/qt/power_test.py`、通道 model | CapabilityService / CapabilityJobs / PipelineProjection / PipelineOrchestrator / 原 legacy_power_test_service | Fake 等价、取消/异常/资源冲突/切页；负责人真实上下电时序与长挂复验 |
| 4 | 仅维护待接入显示及来源说明 | 无持续开机检测服务可迁移 | 不虚构健康度、周期、成功率；独立业务实现另立项 |
| 5a | `src/ui/qt/{serial_terminal,dut_config}.py` | SerialSessionManager / DUT services | 原监控所有权、日志留存/跟随/关闭、Fake 与原验收范围 |
| 5b | Qt 配置、升级、写参、ONU 页面，逐个垂直边界交付 | 原 stores / FirmwareUpgradeValidation / 参数与ONU受控服务 | 字段/默认值/确认/预览/保存/取消/命令等价，能力覆盖不虚报 |
| 5c | Qt AI、权限/审批/模型、远程平台、全局设置 | 原 AI 服务、可信身份/授权、平台池 | 各人工控制面与 pending 单列；不模拟旧窗口按钮 |
| 6 | Qt 队列/Signal桥、订阅 token、主线程断言与退出协调器，随前述阶段逐步建立 | 原 Python 线程 / stop event / job 生命周期 | 乱序、重复/迟到事件、销毁重建、关闭等待、无重复线程/订阅 |
| 7 | Qt 有界日志 model / 批量追加 / 持久化关联适配 | 文件日志 / Job events / BoundedMailbox / transport monitor | 项目/run/通道隔离、积压可观测、告警不静默丢弃、高负载 Fake |
| 8 | 标准 `build_line_check_assistant.ps1` 增加受控 Qt 配置，单独依赖锁和审计 | 原环境/完整基线/归档/ZIP/哈希门禁 | 先目录包，Qt DLL/qwindows插件/许可核验、目标电脑验收；本机不运行新EXE |
| 9 | 分阶段回归表汇总 | 现有全部验收不变量/专项 | Windows DPI 100/125/150%、原设备范围、24/72小时、交付验收后才默认Qt |

以上文件为审计后的计划路径，不代表已创建或业务已接通。适配器不得复制既有项目库、Job表或资源锁。

## 不变行为和接口约束

- 服务不接受 QWidget/Tk Variable/窗口回调；输入是冻结配置数据、可信 Authority 和资源范围，输出是 job_id / 状态快照 / 事件。
- GUI Start 仅提交受控请求；观察真实任务确认后显示运行。Stop 显示请求中，等服务终态，不能点击即判完成。
- 页面隐藏/切换只取消显示订阅，应用级控制器拥有项目和任务；不能取消业务或关闭共享串口。
- 原任务取消 token 与模型停止 token 分离；原未知保护、身份/权限/资源二次预检、幂等和配置快照保留。
- UI 刷新使用主线程队列/Qt Signal；主线程不执行设备、网络或大量文件操作。100–500ms 仅是待测显示预算，不改测试周期。
- 原 GUI 批次和 Capability Job 不是同一控制面；未接管批次只能如实显示，不给无效停止按钮。新旧 GUI 使用同一应用实例/主机锁，原 GUI 退出后才切换业务入口。
- 不把 Tk 控件嵌入 Qt，不泵送 Tk mainloop，不创建隐藏 Tk 程序当服务端。独立演示原型无硬件入口，不取得真实项目写锁。
- 回归涉及已验收业务结构调整时执行完整基线；Qt GUI 测试先扩展现有隔离门禁覆盖构造/线程/销毁，禁止将 Tk-only 通过当作 Qt 已受管。

## 每阶段交付

文件清单、真实完成能力/复用模块、命令与结果、Windows 源码原生截图（演示水印/真实数据分开）、与参考图差异、未完成问题/风险、旧入口与快照可用性。没有执行的现场检查明确写待验证，不把模拟测试升级为真实验收。

## DUT Telnet本轮边界

2026-11-19 ONU 检查点已接入双型号配置及查询、多选和逐台 ID、业务配置、只读预览、原注册任务、当前 PON 精确删除、验证后的独立 OLT 保存及 C300 单台离线清理重试。Windows 原生补图、真实 OLT 和旧全流程联动待验证或迁移。[ONU 证据索引](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/NEXT_ONU_AUDIT.md)

2026-11-19 批量写参检查点已接入原参数表、预检、本机确认、独立批量任务及停止。127 项相关和 117 项三档 Windows 原生回归通过。后续已接入原串口回退的自动只读日志。旧全流程联动及真实设备验收待做。[写参报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PARAMETER_WRITER_REPORT.md) [串口观察报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PARAMETER_OBSERVATION_REPORT.md)

2026-11-19样机升级检查点：原页面和有程控电源的 Tftp指令/Tftp Put/Web 全包路径及项目升级设置接入。原预检、固件绑定、资源和停止保持。相关171项含两项另行启用的本机浏览器用例均通过，原生111项通过。旧手动重启与全流程联动待补。随后已接入自动串口与逐台状态，187 项相关及 114 项 Windows 原生通过。见[升级日志阶段报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/FIRMWARE_OBSERVATION_REPORT.md)。见[样机升级报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/FIRMWARE_REPORT.md)。

2026-11-19 无程控电源的三种 Qt 全包升级已接入原手动重启确认。原通用能力的默认准入继续拒绝。原生与真机待复验，旧三项全流程待迁移。[手动重启阶段报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/FIRMWARE_MANUAL_REPORT.md)

2026-11-19 Qt 三项全流程已接入原编排器、同项目串口终端、配置/目标确认、日志和安全停止。设备与原生待复验，后续接独立预备测试和其它原控制入口。[全流程阶段报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PIPELINE_QT_REPORT.md)

2026-11-19 Qt 单次预备测试已接入原服务、当前编辑草稿确认、主日志与安全停止。Windows 测试隔离直接核验私有桌面的输入状态。[预备测试阶段报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PRETEST_QT_REPORT.md)

2026-11-19 Qt 项目信息已接入使用 Telnet 草稿的单通道版本查询。原确认、只读结果及正式测试版本基准独立保留。[版本查询阶段报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/VERSION_QUERY_QT_REPORT.md)

2026-11-19 Qt 消息推送已接入本机确认、已保存项目名和当前推送草稿，复用原钉钉与飞书试发服务。三档原生及模拟传输复验通过。[消息试发阶段报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PUSH_TRIAL_QT_REPORT.md)

2026-11-19 Qt 失败轮次续跑接入运行中与批次后两条路径，保持原会话判据、版本预检和原批次结论。[续跑阶段报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/RESUME_QT_REPORT.md)

2026-11-19 Qt 已补齐批次后多失败通道按确认顺序续跑，逐条检查配置和资源，停止清除未启动队列。[排队阶段报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/RESUME_QUEUE_QT_REPORT.md)

2026-11-19 Qt 通道配置已接入旧版串口/网卡分组与临时全量显示。仅提取原候选纯函数，两套入口共用。刷新失败分别保留上次清单，切换与刷新保持当前草稿。[候选阶段报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/RESOURCE_OPTIONS_QT_REPORT.md)

2026-11-19 Qt 主工具栏已接入「刷新串口/网卡」。两处入口共享扫描及状态，慢枚举独立于项目命令和任务停止，活动租约继续由原任务维护。[工具栏刷新报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/HOST_INVENTORY_QT_REPORT.md)

2026-11-20 Qt「设备管理」复用只读枚举、工作区活动租约及项目通道快照。网卡改名按原目标、GUID 确认及跨项目同步流程独立迁移。[Qt 设备管理](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/DEVICE_INVENTORY_QT_REPORT.md)

2026-11-20 Qt 通道配置接入原网卡改名。本机确认固定接口 GUID 和打开项目的受影响通道。后台复用原 Windows 改名与回读，按原字段规则同步草稿，失败时从原未知结果入口核实。[Qt 网卡改名](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/ADAPTER_RENAME_QT_REPORT.md)

2026-11-20 Phase 7 已接入工作区实时项目、任务和通道筛选，以及有界缓冲的筛选结果导出。原事件库的历史分页、旧文本和独立串口文件仍待整合。[日志阶段报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/LOG_SCOPE_QT_REPORT.md)

2026-11-20 Phase 7 已增量接入项目任务历史，原业务库按需分页，当前页可筛选与保存。工作区纯文本、独立串口原文和系统健康待后续。[任务历史报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/LOG_HISTORY_QT_REPORT.md)

2026-11-20 Phase 3 已接入单次「自动上/下电」。当前项目版本、已勾选通道、本次串口和方向随本机确认冻结，调度复用原 Job 与资源保护。单次动作复用原电源服务，空电源口记录人工重启确认。配置快照优先显示实际动作及端口。[单次电源控制报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/SINGLE_POWER_QT_REPORT.md)

2026-11-20 Phase 2 已接入「最近项目」和「从最近列表移除」，使用原工作区列表、项目打开和移除服务。窗口以后台快照填充菜单。[最近项目报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/RECENT_PROJECTS_QT_REPORT.md)

2026-11-20 Phase 2 已接入 Qt 六标签原始输入的恢复草稿。草稿按项目和配置版本加密，恢复须本机选择，正式保存走原校验。旧 Tk 控件位置格式由原窗口恢复。[配置草稿恢复报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/EDITOR_RECOVERY_QT_REPORT.md)

2026-11-20 Phase 2 已接入「选择导入的接入配置」。复用原候选和加密存储，保存前复核当前平台配置及停用状态。启用与远程访问范围继续独立确认。[导入接入配置报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/IMPORTED_CONNECTIONS_QT_REPORT.md)

2026-11-20 Phase 8 已建立标准入口 `-Gui Qt` 并生成 Windows 迁移验证目录包。完整基线及实际归档通过。目标 PC 运行、系统 DPI、现场业务与公开分发条件仍分别验收。[Windows Qt 目录包报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/QT_DIRECTORY_BUILD_REPORT.md)

2026-11-20 Phase 7 加入工作区和项目串口归档原文的只读分页浏览。文件查询独立于设备操作队列，搜索和导出限当前页。缺失的级别、任务或通道归属保留原状。系统健康及长期积压仍待后续验证。[归档日志报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/ARCHIVED_LOGS_QT_REPORT.md)

2026-11-20 Phase 7 总览接入只读系统状态。现有 Qt 回调和工作区命令循环提供响应样本，并展示原任务日志、工作区写入结果、显示积压和资源租约。实际业务心跳与最近探测时间依赖后续数据源。长挂压测和设备验收按原计划执行。[系统状态报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/SYSTEM_HEALTH_QT_REPORT.md)

2026-11-20 Phase 5 / 6 接入本机「核实未知任务」。复用原工作区的 GUI 保护记录及核实服务，保留原结果和证据。旧任务先打开所属项目，启动守卫读取原核实标记。持久化 Job 的独立审阅、现场设备及整机可靠性验收继续待办。[核实未知任务报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/UNKNOWN_TASK_QT_REPORT.md)

2026-11-20 Phase 5 / 6 在 Qt 任务历史接入持久化 Job 的独立现场核实。明确的本机确认绑定项目、完整任务身份、原记录版本、结论和依据。复用原结果写入、资源保护和进程中断恢复。现场设备及整机可靠性验收继续待办。[业务任务核实报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/JOB_REVIEW_QT_REPORT.md)

负责人允许在对应自动验证通过后清理 `validation/` 中的开发过程截图、测试日志、结果清单和已通过复验替代的失败材料。清理前将命令、结果和未验收事项写入阶段报告，清理时同步处理相关链接。当前验收或交付仍需的证据可保留。

2026-11-20 Phase 5 接入 Qt AI 模型连接。复用原项目和工作区模型存储、凭据加密、出口选择、模型列表及连接测试。验证和剩余诊断模块见[AI 模型连接报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/MODEL_SETTINGS_QT_REPORT.md)。

2026-11-20 Phase 5 接入 Qt 普通问答与项目会话历史。复用原模型选择、会话库、上下文预算和流式回复。设备、电脑及平台会话可查阅历史，目标、工具、审批、报告和平台控制面继续按原计划推进。[Qt 普通问答报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/AI_CHAT_QT_REPORT.md)

2026-11-20 Phase 5 接入 Qt 诊断报告浏览、证据、重命名和批量管理。删除经本机确认及原服务整批复核。[Qt 诊断报告迁移记录](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/AI_REPORTS_QT_REPORT.md)

2026-11-20 Phase 5 接入 Qt 共用案例库和人工确认，复用五项真实核实字段、原报告来源、共享版本、修订和删除标记。[Qt 共用案例迁移记录](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/AI_CASES_QT_REPORT.md)

2026-11-20 Phase 5 接入 Qt 报告转入项目排查会话。快照报告沿用原目标，旧报告确认同通道当前目标。[Qt 报告接手迁移记录](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/AI_HANDOFF_QT_REPORT.md)

2026-11-20 Phase 5 接入 Qt 留存报告分析。沿用原会话发送、证据检索和停止，支持本机报告会话分析。设备实时采集、审批、工具和远程控制继续迁移。[Qt 留存报告分析](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/AI_REPORT_ANALYSIS_QT_REPORT.md)

2026-11-20 Phase 5 / 8 接入 Qt 全局设置的检查更新。沿用原版本比较、正式附件、ZIP/SHA256 和手动安装，下载线程独立于项目命令，退出等待更新清理。[Qt 检查更新](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/APP_UPDATE_QT_REPORT.md)

2026-11-19检查点：DUT配置六页均已接入，语音/TR069的64项相关、105项原生及3,093项完整基线通过。旧目录导入、凭据读取及TR069缺失字段显示为后续局部验证范围。[DUT报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/VOICE_TR069_REPORT.md) · [后续报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/QT_FOLLOWUP_REPORT.md) · [下一步样机升级审计](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/NEXT_FIRMWARE_AUDIT.md)。

WiFi检查点：恢复输入桌面后，58相关、33×3原生和2×3稳定布局复采及3087项完整基线（236项指定）通过。累计16/29项AST等价，现场设备、系统DPI和长期待验收。报告、失败记录及截图见[WiFi报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/WIFI_REPORT.md)。

WiFi本轮：2.4G/5G完整字段、索引查询、主/peer Radio、共享双频开关、原真实能力/兜底、SSID递增及普通/统一稳定等待路径；直接复用原DUT查询/批量/单台/core服务。仅原文共享纯WiFi映射/候选函数和常量，保留Tk导入及类AST，设置/默认值/时序/命令/判据不改。设备能力由本机查询缓存派生，不接受客户端伪造supported字段；完整含密码状态仅GUI回填，持久结果/日志去除密钥。沿原DUT确认/Job/停止，模拟覆盖apply→原等待→verify及停止未校验。当前输入桌面WinError 5，原生和涉及其的完整门禁未通过前不放行/提交/打包；仍可做源码、Fake和原Tk非像素回归，恢复桌面后补全部强制原生与完整基线。

WAN本轮代码与截图、共享规则11/34项AST保全、原Job/服务及验证结果见[WAN阶段报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/WAN_REPORT.md)。整体迁移与实际设备验收仍未完成；下一步为WiFi/语音/TR069。默认Tk、原协议与原构建环境保持。

后续WAN增量审计：原dut_wan_query_service的共同名称/完整详情交集、dut_advanced_config_service的校验/批量执行原样复用。仅将旧Tk文件中纯WAN展示常量/位掩码/表单规则/回填函数原文提取到src/models/dut_wan_form.py，旧模块保留导入代理；不搬迁DutConfigWindow类和业务服务。新Qt独立WAN表单接入全部字段、原双栈/桥接/IPTV/PPPoE联动、LAN绑定和未知位保留；共享独立目标/凭据/并发/确认/Job停止。查询缓存绑定项目配置、目标、凭据；目标变化失效，只有共同完整详情回填，密码不进持久结果/日志。实施原AST等价、专项、原Tk及三档Qt原生，按此受验收UI迁移触发完整基线。真实网络/DUT操作不执行。

继续Phase 5：真实代码确认原DUT批量开启/状态查询已在独立service，Qt新增独立数据适配和窗口，复用原DeviceCapabilities._job、CapabilityJobs、项目快照和主机资源保护。实现独立目标选择/1–8并行、原凭据初值和会话草稿、一次确认/版本与NIC复核、逐台Telnet结果、停止及窗口关闭/重开；查询成功不冒充测试健康，目标变化清空旧显示。凭据不进入Qt确认/Job参数/显示日志；GUI专用能力不扩展AI/远程权限。仅抽取Qt适配器自己的准入/NIC小方法供复用，原Tk和core/services不搬迁。按已验收DUT界面迁移范围执行专项、三档原生截图与完整基线；无真实设备/网卡操作，现场验收保持待确认。文件、失败定位、最终测试和下一增量见[DUT Telnet报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/DUT_TELNET_REPORT.md)。其它五个DUT标签及整个计划保持未完成。

2026-11-20 Phase 5 接入 Qt 排障会话管理。复用项目会话列表、标题、原整批删除事务和忙碌校验。确认固定操作者看到的会话范围，删除其它会话时保留当前阅读位置及输入。[Qt 排障会话管理](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/AI_SESSION_MANAGER_QT_REPORT.md)

2026-11-20 Phase 5 接入 Qt 串口终端和 DUT 配置的项目窗口状态。读取原 Tk 串口几何与 DUT 宽高，根据当前屏幕恢复。正常关闭和项目退出采用同一项目后台保存路径。[Qt 窗口状态报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/WINDOW_PLACEMENT_QT_REPORT.md)

2026-11-20 Phase 5 补齐 Qt DUT 六页状态区高度。与原项目的逐页行数兼容，拖动后按项目保存，窄窗保留底部操作。Windows 三档原生复验通过，目标机和设备仍待现场验收。[DUT 状态区报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/DUT_STATUS_HEIGHT_QT_REPORT.md)

2026-11-20 Phase 5 接入 Qt DUT 与写参共用登录输入。两窗按项目同步草稿，复用写参显式保存和原任务确认。三档原生复验通过。旧 Tk 自动保存差异及现场复验保留在进度表。[共用登录输入报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PARAMETER_LOGIN_QT_REPORT.md)

2026-11-20 Phase 6 和 Phase 7 实时日志改为增量文档编辑。满缓冲持续批次、原筛选导出和四线程突发原文写盘已自动复验，长时间响应、真实串口和控制行为继续待现场验证。[实时日志验证](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/LOG_BATCH_QT_REPORT.md)

2026-11-20 Phase 3 和 Phase 7 在 Qt 通道上下文菜单接入原结果文件、本次尝试 WiFi 日志打开。三档自动化通过，实际 Windows 文件关联与现场结果待复验。[通道日志报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/CHANNEL_LOGS_QT_REPORT.md)

2026-11-20 Phase 2、6 和 7 支持从所选持久任务查看对应原批次的结果和 WiFi 文件，重建工作台后按原运行身份加载。三档自动化通过，旧文件缺少身份记录及现场复验仍登记待办。[历史批次结果文件](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/HISTORY_RESULT_FILES_QT_REPORT.md)

2026-11-20 Phase 5、6 和 7 将原 AI 实时日志摘要接入 Qt，主实时区保留任务关键节点和异常，归档写入经原服务过滤的原文。三档自动化通过，真实模型和平台验收待办。[AI 实时日志报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/AI_LIVE_LOG_QT_REPORT.md)

2026-11-21 Phase 5、6 补齐 Qt AI 会话 Markdown、独立状态和流式位置保留。标准完整基线和三档原生验证通过，目标机输入法、真实模型和平台待现场复验。[Qt 会话排版报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/AI_CHAT_PRESENTATION_QT_REPORT.md)

2026-11-21 Phase 3、7 接入原开关机通道的重试和失败历史。使用原业务任务事件按项目、批次和通道分页，当前批次的续跑保持原关联。真实 DUT 重试和长期挂测继续待验收。[通道重试历史报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/CHANNEL_RETRY_HISTORY_QT_REPORT.md)

2026-11-21 Phase 3、5 兼容六个功能弹窗的 Tk 项目尺寸状态。Qt 使用原文件和已有偏好保存队列，三档原生与 Tk 兼容回归通过。系统 DPI 动态切换和实体多屏待现场验收。[窗口尺寸兼容](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/MODULE_WINDOW_SIZES_QT_REPORT.md)

2026-11-21 Phase 2、7 接入项目菜单快捷键、项目目录和原 GUI 的运行记录，Phase 9 补充同一通道两批作业的迟到事件回归。自动验证使用临时项目及模拟设备。[项目菜单](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PROJECT_COMMANDS_QT_REPORT.md) · [运行记录](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/LEGACY_RUN_HISTORY_QT_REPORT.md) · [批次隔离](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PHASE9_LATE_BATCH_QT_REPORT.md)

## 串口模块本轮边界

继续Phase 5首个串口模块：新增无GUI的Qt串口终端适配和独立QDialog，直接共享当前项目原SerialSessionManager/PySerialSession、SerialSettings、SerialDelivery及BoundedMailbox，不搬迁或修改已验收Tk/传输代码。展示项目当前已选VLAN/显式COM（缺省沿旧映射），打开全部、停止全部、手动文本/空回车、危险命令二次确认、清屏、逐标签确认关闭和目录恢复/选择。后台负责打开/写入/关闭与文件，界面仅消费有界数据；保留共享所有权/升级控制锁、异步关闭票据、尾行落盘、迟到订阅隔离、上翻暂停跟随。GUI专用能力不扩展AI裸串口权限；同项目窗口跨切页保留，退出等实际收尾。原升级自动开窗、DUT及AI页面仍待各自模块接入，不以本轮宣称Phase 5完成。使用Fake驱动/原管理器验证，不操作真实串口。局部专项和三档受管原生截图，不改原构建环境、默认入口或版本号。

串口轮检查点：基本终端及原管理器/实际参数/所有权/日志/确认控制已接入，17项服务及最终原生27×3=81项通过（每档36受管顶层/违规0），296编译/286登记/488动作覆盖/协议/原业务及原串口UI/传输字节保全通过。本轮完整基线3040项、226项指定回归及全部门禁通过，首轮父子编码收集失败已统一UTF-8完整复跑，失败记录保留；文件、前后图、关闭与阅读锚点修正见[串口阶段报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/SERIAL_REPORT.md)。原升级自动开窗/AI联动、几何恢复、DUT等其它页面及现场/长期/部署仍待后续。

## 已交通道配置与展示

继续负责人原计划，补齐Qt通道选择/VLAN/COM/管理IP/电源绑定及矩阵/只读列表切换。审计确认原Tk补齐16槽位、管理IP共享并从VLAN推导源IP、磁盘只存已选通道。保持这些规则和原ChannelCapabilities.prepare/commit、ChannelConfigStore序列化，不改已验收源服务；通过数据投影调用旧校验。未选绑定仅保留当前项目会话内存，项目关闭/重开沿旧存储规则。GUI专用编辑租约与六标签/任务互斥；预览绑定配置版本及一次性确认，保存提交原项目版本、失败恢复/未知保护。资源刷新只读枚举，不重命名/改IP/开串口/发电源命令，不扩大AI/远程或物理并行权限。新增独立service/UI模块，原Tk/引擎保持；局部专项+原生三档截图验证，不将此模块称为整套迁移完成。

通道轮交付结果：16项新服务及109项相关组合通过，原生Qt24×3=72项最终顺序复验通过、每档30受管顶层/违规0，294编译/284登记/478动作覆盖/协议/旧业务保全通过。截图发现隐藏列表撑高矩阵，已按当前页尺寸提示修复并重跑三档；中间并发复验COM102资源冲突失败如实保留，未削弱资源保护。详细文件、前后图、实际命令及剩余差异见[通道阶段报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/CHANNELS_REPORT.md)。本轮未搬迁已验收业务、未跑完整基线、未操作真实设备或打包；人工/真实DPI/设备及其它阶段未完成。

## 本轮配置编辑垂直模块

按负责人继续执行计划的授权，先补齐Phase 5的六标签QDialog，解除Phase 3只能回Tk改测试参数的限制。新模型/服务/Qt窗口独立增加，不搬迁原Tk或修改旧store。共享TestItemConfigStore、LegacyUiDefaultsStore、MessagePushConfigService及原WiFi验证，保存继续提交原项目版本；保留隐藏运行字段、密码、关闭选项值、Telnet反向同步、重试间隔唯一来源及保存不发送消息。GUI专用控制能力仅接受gui来源，不向AI返回私有配置。编辑租约与任务准入互斥，重读/保存检查版本；暂存序列化、提交失败恢复与未知保护。六标签字段/动态命令分段/默认草稿/保存取消/重载本轮实现，预备测试、设备版本查询、试发及远程接入等执行按钮若未迁移保持显式待接入，不把基本编辑器当作整个Phase 5已完成。使用原受管Windows私有桌面核对100/125/150%和实际截图；原设备引擎不改，按局部相关回归验证。

本轮结果：六标签及原存储/项目版本保存、默认草稿、WiFi只读刷新已实现，14项新增服务回归、原生Qt20×3=60项与291编译/281登记/覆盖/协议/保全通过；相关156项仅快照更新失败已修复并复验3项。关闭回调漏调QDialog基类导致finished未发出及租约未释放的问题已修正，保留失败记录并用关闭重开用例验证。无Tk搬迁、未触发完整基线；人工/实际系统DPI/设备及其它模块继续待后续。见[配置阶段报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/CONFIGURATION_REPORT.md)。

## Phase 3 本轮执行边界

继续实现自动开关机与环境检查的Qt垂直链路：新增数据适配器复用CapabilityService/Jobs、原PipelineOrchestrator；确认绑定项目、已保存配置哈希和明确通道，确认过期或配置变化拒绝执行。任务事件仅映射显示，不新增判据、设备指令、时序或检测项。页面切换不触发取消；关闭项目须先明确停止并等待任务线程、串口管理器真正退出，再释放项目与工作区。原Tk/引擎不搬迁，未迁移功能保持禁用。补充Fake编排器专项和受管原生Qt截图/三档测试；完整基线仅按既有触发条件执行。配置编辑器、其它模块、Qt打包及真实设备长挂仍分别待后续阶段，不将此垂直模块视为整体完成。

本轮结果：上述Qt链路及配置快照显示已实现，146项相关回归、48项受管原生Qt测试与源码/覆盖/协议/旧业务保全检查通过。原业务不搬迁，本轮未触发完整基线；最近2981项结果保留为前轮。Phase 3仍待负责人真实设备/长期时序验收，详见[Phase 3报告](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PHASE3_REPORT.md)。

2026-11-21，负责人明确主进程意外退出时保留已经启动的原开关机任务。重开的工作区须按项目核对原子进程，存活或核对失败时拒绝解除保护，退出后仍须本机核实结果。[模拟复验](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/power_owner_exit/REPORT.md)

2026-11-21，负责人确认 Qt 候选现在开放网关项目控制命令，业务消息明确拒绝，待业务会话与原审批链完整接入后再扩展。重开工作区沿用已配对槽位、原成员与本地项目授权。[Qt 控制命令证据](../../Cheating_machine_execution_tool/validation/pyside6_migration_20261118/qt_gateway_client/REPORT.md)
