# 项目交接状态

Qt 源码工作台新增按项目路由群消息的启动方式。可信测试机直接交换项目目录与成员选择，目标项目沿用原 AI 会话、业务审批和执行服务。原常开网关继续作为回退入口，双机、真实平台和 DUT 待现场验证。[配置与群内操作](Cheating_machine_execution_tool/line_check_assistant_README.md#qt-源码工作台按项目接收群-)

Windows Qt 候选 qt-20261121-194426-f1cfb93a 包含明确单通道切换、目标澄清及已有串口的被动读取。完整基线通过 3,265 项，264 项指定回归全部命中。Windows 原生界面在 100%、125%、150% 缩放下各通过 100 项，共 300 次。 [便携 ZIP](Cheating_machine_execution_tool/dist/qt-20261121-194426-f1cfb93a/DUTPilot_portable.zip) · [本次验证](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/local_serial_chat/REPORT.md)

Windows Qt 候选 qt-20261121-174731-da5a40fa 已修复网关同槽位重启后的回执恢复。完整基线通过 3,261 项，260 项指定用例全部命中。Windows 原生界面在 100%、125%、150% 缩放下各通过 96 项，共 288 次。 [便携 ZIP](Cheating_machine_execution_tool/dist/qt-20261121-174731-da5a40fa/DUTPilot_portable.zip) · [本次验证](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/gateway_boot_receipts/REPORT.md)

旧设备会话阶段的 Windows Qt 候选已包含留存分析、串口被动取证与关闭失败保护。完整基线运行 3,260 项，259 项指定测试全部命中，八类门禁通过。Windows 原生界面在 100%、125%、150% 缩放下各通过 96 项，共 288 次。 [交付 ZIP](Cheating_machine_execution_tool/dist/qt-20261121-171909-88b5a602/DUTPilot_portable.zip) · [复验与待验范围](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/archived_device_chats/REPORT.md)

串口阶段的 Windows 候选已包含被动读取、启动失败清理和关闭失败保护。完整基线运行 3,259 项，258 项指定回归全部命中，八类门禁通过。Windows 原生界面在 100%、125%、150% 缩放下各通过 95 项。 [便携 ZIP](Cheating_machine_execution_tool/dist/qt-20261121-165305-f2c9cfc7/DUTPilot_portable.zip) · [测试报告和现场待验范围](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/serial_lifecycle/REPORT.md)

串口被动诊断的 64 KiB 读取边界已完成源码修正。未启用文件日志时，原驱动仍长期保留收到的全部原始历史。源码复现与测试已归档。[测试报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/serial_passive_read/REPORT.md)

网关阶段的 Windows Qt 候选已按保存的实例槽位接入项目目录与选择。业务消息返回拒绝回执，本地挂测沿用原任务。完整基线运行 3,255 项，254 项指定回归全部命中，八类门禁通过。Windows 原生界面在 100%、125%、150% 缩放下各通过 95 项。 真实平台、目标机、DUT 及长期运行仍待现场。[便携包](Cheating_machine_execution_tool/dist/qt-20261121-161023-3fc3681b/DUTPilot_portable.zip) · [测试及验收范围](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/qt_gateway_client/REPORT.md)

统一网关首条项目列表和客户端部分启动失败已通过线程与回执专项复验。Qt 启动配置继续按阶段接入。[本批源码验证](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/gateway_startup_order/REPORT.md)

原开关机子进程存活保护已进入 [Windows Qt 候选包](Cheating_machine_execution_tool/dist/qt-20261121-150514-03643dce/DUTPilot_portable.zip)。完整基线 3,251 项通过，251 项指定回归均已执行。Windows 原生用例在 100%、125%、150% 三档各通过 95 项，共 285 次。 真实电源与目标电脑验收待现场。[报告及逐帧证据](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/power_owner_exit/REPORT.md)

2026-11-21，[Windows Qt 候选包](Cheating_machine_execution_tool/dist/qt-20261121-143820-20f3c0f3/DUTPilot_portable.zip)已纳入项目主日志与资源监测归档。3,248 项完整基线通过，249 项指定用例全部执行。三档 Windows 原生共 285 次通过。成品入口和 331 个项目模块与源码一致，92 个受保护业务文件保留原哈希，另外 5 个与负责人确认的修正快照一致。整体迁移及现场验收仍待完成。[交付与遗留项](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/project_main_logs/REPORT.md)

2026-11-21，原挂测子进程可在 Qt 主进程异常退出后继续操作模拟电源。重开的工作区保留未知保护，现场不能仅凭 GUI 消失判断挂测已经停止。[原子进程逐帧实测](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/power_owner_exit/REPORT.md)

2026-11-21，[Windows Qt 候选包](Cheating_machine_execution_tool/dist/qt-20261121-141002-8f2876a1/DUTPilot_portable.zip)已纳入独立项目同时开关机及按选中方案保护无线资源的修改。3,247 项完整基线通过，249 项指定用例全部执行。三档 Windows 原生共 285 次通过。成品入口和 331 个项目模块与源码一致，92 个受保护业务文件保留原哈希，另外 5 个与负责人确认的修正快照一致。整体迁移及现场验收仍待完成。[交付与遗留项](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/parallel_power/REPORT.md)

2026-11-21，Qt 工作台已接入独立资源上的多项目自动开关机。模拟原业务子进程验证了两个项目同时运行、跨项目停止请求被拒绝、停止 A 后 B 完成。共享无线接口按选中方案申请租约。现场及其他设备任务并行继续待验。[软件复验](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/parallel_power/REPORT.md)

2026-11-21，[Windows Qt 候选包](Cheating_machine_execution_tool/dist/qt-20261121-131321-f895c473/DUTPilot_portable.zip)已纳入原开关机串口写入回执修正。3,245 项完整基线通过，247 项指定用例全部执行。三档 Windows 原生共 282 次通过。成品入口和 330 个项目模块与源码一致，92 个受保护业务文件保留原哈希，另外 5 个与负责人确认的修正快照一致。整体迁移及现场验收仍待完成。[交付与遗留项](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/power_command_receipts/REPORT.md)

2026-11-21，[Windows Qt 候选包](Cheating_machine_execution_tool/dist/qt-20261121-123123-b69436ef/DUTPilot_portable.zip)已纳入项目回执和平台关闭顺序修正。3,243 项完整基线通过，245 项指定用例全部执行。三档 Windows 原生共 282 次通过。成品入口和 330 个项目模块与源码一致，97 个原业务文件与迁移前的哈希一致。整体迁移及现场验收仍待完成。[交付与遗留项](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/gateway_project_lifecycle/REPORT.md)

**自动开关机原执行器已按负责人确认单独修正，待整机与现场验收。** 短等待两通道两轮已写全 8 帧，模拟串口异常已回传失败。旧版误报及其逐帧记录保留。本批仅使用模拟电源。[修改及验证](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/power_command_receipts/REPORT.md)

2026-11-21，Qt 退出会等待平台连接停止，项目关闭会等待原网关回执持久化。模拟回归覆盖两个项目独立收尾和真实窗口关闭。Qt 自动启动实例客户端和项目会话转发仍待接入。[生命周期阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/gateway_project_lifecycle/REPORT.md)

2026-11-21，[Windows Qt 候选包](Cheating_machine_execution_tool/dist/qt-20261121-120503-1bc9ddf8/DUTPilot_portable.zip)已纳入实例启动设置和开关机停止回执修正。3,240 项完整基线通过，242 项指定用例全部执行。三档 Windows 原生共 282 次通过。成品入口和 330 个项目模块与源码一致，97 个原业务文件与迁移前的哈希一致。整体迁移及现场验收仍待完成。[交付与遗留项](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/instance_startup/REPORT.md)

2026-11-21，Qt 已接入多实例下次启动配置，统一接入客户端及项目转发仍待迁移。原开关机任务的明确停止回执现能正确归入已停止。两个项目的模拟执行器验证了配置快照、停止信号及资源释放隔离。[本轮修改与验收记录](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/instance_startup/REPORT.md)

2026-11-21，[最新 Windows Qt 候选包](Cheating_machine_execution_tool/dist/qt-20261121-110646-bc54506d/DUTPilot_portable.zip)已纳入串口终端的被动诊断快照。3,235 项完整基线、三档 276 次原生回归、328 个成品项目模块比对通过。目标机、硬件及长期挂测仍待验收。[串口诊断阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/serial_diagnostics/REPORT.md)

2026-11-21，包含本机电脑连续诊断的[最新 Windows Qt 候选包](Cheating_machine_execution_tool/dist/qt-20261121-103221-39df2f12/DUTPilot_portable.zip)已通过标准验包。3,233 项完整基线和最终三档 273 次原生回归通过，已核对 16 通道原请求、诊断批次和停止。[本机诊断、构建及现场待验项](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/pc_diagnosis/REPORT.md)

2026-11-21，包含网关签发与实例配对的[Windows Qt 候选包](Cheating_machine_execution_tool/dist/qt-20261121-094840-01ea3a1e/DUTPilot_portable.zip)已完成标准构建。3,232 项基线通过，325 个项目模块的成品代码与源码匹配。16 通道模拟回执通过，目标机启动、真实设备和长期运行待验。[构建、专项验证及剩余业务](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/instance_pairing/REPORT.md)

2026-11-21 Qt 候选新增网关配置与本机启停、登记实例撤销、会话权限与具体操作审批。开关机继续使用原编排器，持续开机全业务老化待接入独立执行源。当前候选的阶段覆盖、模拟测试、构建及现场条件见[迁移总结与测试报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/current_candidate_review/REPORT.md)。

此前候选已通过 3,231 项完整源码回归、267 次三档 Windows Qt 原生验证及标准目录验包。[前次 Windows 验证包](Cheating_machine_execution_tool/dist/qt-20261121-033007-cb5006d8/DUTPilot_portable.zip)留作对照。当前默认入口仍为 Tk。

2026-11-21，VS Code 通过 Ctrl+F5 可启动独立 Qt 源码工作台。本机远程项目范围的写入已接入原授权服务；持久任务历史支持查询整个任务、按匹配事件翻页。模拟验证结果及真实平台待办见[阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/HISTORY_SCOPE_QT_REPORT.md)。

2026-11-21 V1.3.0 Qt 仍处于迁移收尾阶段。负责人确认实验室验收待现场，开关机按每台 500 次验收，全业务老化满 7 天逐项验收。本轮已核对指导书、项目实现和历史 Qt 包。后续从[交接差异与执行记录](docs/GUI_UPGRADE_EXECUTION_PLAN.md)继续。

2026-11-20 负责人确认两阶段开发。当前继续原 V1.3.0 PySide6 迁移，正式验收及 Git 基线保存后再审计 V1.3.x 的公共准备流程、设计规范和架构升级。界面与原业务分离，持续复用现有服务和组件。[阶段管理原则](.claude/plans/pyside6-migration.md)

2026-11-21 Qt 已接入 Tk 工作台的项目快捷键和打开项目目录操作。目录和保存均定位到当前所选项目。[项目菜单验证](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PROJECT_COMMANDS_QT_REPORT.md)

2026-11-21 Qt「任务历史」可以查看旧工作台直接启动的批次。95 项相关回归已通过，包含旧项目重开时的历史隔离和跨批次迟到事件隔离。[旧项目历史](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/LEGACY_RUN_HISTORY_QT_REPORT.md)

2026-11-21 Qt 六个功能弹窗恢复原 Tk 项目保存的宽高，并在关闭时按项目保存。156 项专项和 252 项三档 Qt 原生用例通过。实际系统 DPI 动态切换与实体多屏待现场验收。[窗口尺寸兼容](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/MODULE_WINDOW_SIZES_QT_REPORT.md)

2026-11-21 Qt 通道详情可查看本次开关机批次的重试、失败原因和续跑历史。132 项专项及 249 项三档 Qt 原生用例通过。真实 DUT 重试与长挂仍待现场复验。[通道重试历史](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/CHANNEL_RETRY_HISTORY_QT_REPORT.md)

2026-11-21 Qt AI 会话已恢复原 Markdown 展示、独立最新状态、流式末尾更新及原输入快捷键。3,211 项完整基线和 246 项三档 Qt 原生用例通过。真实模型、输入法、设备和平台待验收。[Qt 会话排版报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/AI_CHAT_PRESENTATION_QT_REPORT.md)

2026-11-20 Qt 实时 AI 日志已复用旧版任务摘要、异常分类及原文归档。181 项专项回归和 243 项三档原生用例通过。真实模型、设备和平台验收继续待办。[AI 实时日志报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/AI_LIVE_LOG_QT_REPORT.md)

2026-11-20 Qt 任务历史可在工作台重启后打开所选开关机批次的结果与 WiFi 文件。98 项专项回归和 240 项三档原生复验通过。实际目标机关联程序和现场输出待验收。[历史批次结果文件](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/HISTORY_RESULT_FILES_QT_REPORT.md)

2026-11-20 Qt 通道矩阵和列表可打开选定通道的开关机运行日志及本次尝试的 WiFi 日志。150 项专项回归和三档共 237 项 Windows 原生用例通过。目标机文件关联和现场输出待验收。[通道日志报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/CHANNEL_LOGS_QT_REPORT.md)

2026-11-20 Qt 实时日志按批次追加并裁剪过期行，原始日志可继续归档读取。四线程 6,000 条短时写盘核对、94 项专项回归和 234 项三档原生复验通过。真实长挂、整机指标和目标机待验收。[实时日志验证](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/LOG_BATCH_QT_REPORT.md)

2026-11-20 Qt DUT 与写参的登录输入按项目即时联动，继续通过写参入口显式保存。103 项专项回归和三档共 231 项 Windows 原生用例通过。真实设备和目标机待验收。[共用登录输入报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PARAMETER_LOGIN_QT_REPORT.md)

2026-11-20 Qt DUT 配置六个页签按项目独立恢复和保存状态区高度。96 项相关回归与 228 项三档原生复验通过。实际系统 DPI 和现场设备待办。[DUT 状态区报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/DUT_STATUS_HEIGHT_QT_REPORT.md)

2026-11-20 Qt 串口终端和 DUT 配置已兼容按项目保存的原窗口偏好。串口关闭时日志目录偏好保存失败仍会释放会话。125 项相关回归和 225 项三档原生复验通过，实际系统 DPI、实体多屏和目标机待验收。[Qt 窗口状态报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/WINDOW_PLACEMENT_QT_REPORT.md)

2026-11-20 Qt AI 诊断加入项目会话管理。多选、改名与批量删除复用原会话库和整批忙碌保护。159 项相关回归和 222 项三档原生用例通过，目标机历史项目待验收。[Qt 排障会话管理](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/AI_SESSION_MANAGER_QT_REPORT.md)

2026-11-20 Qt 通道配置接入原网卡改名与跨项目草稿同步。修复工作台冷启动时更新模块和工作区线程的 Requests 导入竞争。224 项相关回归、15 项冷启动专项与 219 项三档原生复验通过，真实网卡及目标机待验收。[Qt 网卡改名](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/ADAPTER_RENAME_QT_REPORT.md)

2026-11-20 Qt 顶栏「设备管理」可查看网卡 GUID、串口、工作区活动租约和项目通道。113 项相关回归和 216 项三档原生复验通过。目标机验收待办。[Qt 设备管理](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/DEVICE_INVENTORY_QT_REPORT.md)

2026-11-20 Qt 全局设置已接入检查更新、ZIP 保存及校验、取消和退出收尾。134 项相关回归和 213 项三档原生检查通过，真实发布与目标机更新待验收。[Qt 检查更新](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/APP_UPDATE_QT_REPORT.md)

2026-11-20 Qt 本机报告会话已可分析留存材料，支持模型分析、会话内证据检索、文本导入和停止本轮。180 项相关回归和 210 项三档 Windows 原生检查通过。实时采集、设备工具、审批及平台控制面继续迁移，真实模型与现场验收待办。[Qt 留存报告分析](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/AI_REPORT_ANALYSIS_QT_REPORT.md)

2026-11-20 Qt 已接入新旧报告转入项目排查会话，复用原目标快照、同通道关联确认及会话证据。179 项相关回归和 207 项三档 Windows 原生检查通过。[Qt 报告接手迁移记录](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/AI_HANDOFF_QT_REPORT.md)

2026-11-20 Qt 已接入共用案例库和从报告新建草稿，沿用人工确认、共享版本、修订记录、检索启停及删除标记。178 项相关回归和 204 项三档 Windows 原生检查通过。[Qt 共用案例迁移记录](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/AI_CASES_QT_REPORT.md)

2026-11-20 Qt 已接入项目诊断报告和批量管理，复用原报告库、证据、标题和删除保护。158 项相关回归和 201 项三档 Windows 原生检查通过。[Qt 诊断报告迁移记录](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/AI_REPORTS_QT_REPORT.md)

2026-11-20 Qt 已接入项目普通问答和会话历史，复用原模型选择、会话库、证据和流式回复。154 项相关回归和 198 项三档 Windows 原生用例通过。[Qt 普通问答报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/AI_CHAT_QT_REPORT.md)

2026-11-20 Qt 任务历史已接入持久化业务任务现场核实。明确本机确认绑定项目、原任务及版本，复用原结果记录和资源保护。118 项相关回归及三档共 192 项 Windows 原生用例通过。[业务任务核实报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/JOB_REVIEW_QT_REPORT.md)

2026-11-20 Qt 项目菜单已接入本机核实原 GUI 未知保护，沿用原回执和资源规则，保留原结果。131 项相关和覆盖回归、三档 189 项 Windows 原生用例通过。持久化 Job 的独立审阅及现场验收仍待完成。[核实未知任务报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/UNKNOWN_TASK_QT_REPORT.md)

2026-11-20 Qt 总览已接入系统状态，展示现有界面回调、工作区响应、日志写入与积压、任务日志和资源租约。121 项相关及门禁用例通过，Windows 私有桌面三档共 186 项通过，隔离违规为零。持续开机业务探测、现场与长挂验收待完成。[系统状态报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/SYSTEM_HEALTH_QT_REPORT.md)

2026-11-20 Qt 已接入原工作区日志和项目串口文件的归档浏览，后台有界分页，支持本页搜索及导出。42 项相关回归及三档 183 项原生检查通过。写盘健康与长期验收仍待办。[归档日志报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/ARCHIVED_LOGS_QT_REPORT.md)

2026-11-20 已生成首份 Qt V1.3.0 Windows 迁移验证目录包及 ZIP。锁定 Qt 环境完整基线通过，执行 3,185 项与 239 项指定用例。实际 EXE 版本、Qt Windows 插件、关键 DLL、ZIP 一致性与哈希核验通过。目标电脑、真实设备及长期验收仍待办。[Windows Qt 目录包报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/QT_DIRECTORY_BUILD_REPORT.md)

2026-11-20 Qt 已接入导入的钉钉和飞书配置选择，保存复用原加密存储，选中平台保持停用。72 项相关回归、三档 180 项原生用例通过。平台启用和远程控制面仍待迁移及现场验收。[导入接入配置报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/IMPORTED_CONNECTIONS_QT_REPORT.md)

2026-11-20 Qt 六标签窗口已接入按项目和版本加密的页面草稿恢复。原保存校验继续独立。旧 Tk 草稿由原窗口恢复。68 项业务相关回归、28 项验证脚本回归和 177 项三档原生用例通过。[配置草稿恢复报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/EDITOR_RECOVERY_QT_REPORT.md)

2026-11-20 Qt 项目菜单已接入最近项目的按路径打开及从最近列表移除，复用原工作区记录。36 项相关回归和三档共 174 项原生验证通过。配置页面草稿恢复和导入平台配置选择仍待迁移。[最近项目报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/RECENT_PROJECTS_QT_REPORT.md)

2026-11-20 Qt 单次「自动上/下电」已接入本机选口、方向、通道确认及空端口人工重启。原电源服务与 Job 资源保护复用，配置快照优先显示本次端口。三档共 171 项 Windows 原生检查通过，真实电源与样机流程待验收。[单次电源控制报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/SINGLE_POWER_QT_REPORT.md)

2026-11-20 Qt 项目菜单已接入任务历史。按项目和完整任务 ID 只读分页，并可筛选与导出当前历史页。关闭重开项目后仍能查看原记录。90 项相关回归、三档 168 项原生复验通过。工作区旧文本、串口原文统一浏览和系统健康待接入。[任务历史报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/LOG_HISTORY_QT_REPORT.md)

2026-11-20 Qt 日志区已接入项目、当前任务和通道筛选及当前缓冲导出。任务标识由原 Job 事件提供，导出使用本机选定的新 TXT。88 项相关回归和三档 165 项原生复验通过。持久历史分页和系统健康待接入。[日志阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/LOG_SCOPE_QT_REPORT.md)

2026-11-20 Qt 主工具栏已接入「刷新串口/网卡」，与通道窗口共用只读扫描。枚举期间保留任务停止及活动租约，跨项目更新候选时保留编辑草稿。三档 162 项原生复验通过。[工具栏刷新阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/HOST_INVENTORY_QT_REPORT.md)

2026-11-19 Qt 通道配置已接入串口与网卡分组、全量模式和只读刷新。候选变化保留当前输入。300 项相关回归、三档 159 项原生复验及本机只读枚举通过。最近一次完整基线全部通过，运行 3,165 项，包含 239 项指定用例。物理网卡改名待迁移。[候选阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/RESOURCE_OPTIONS_QT_REPORT.md)

2026-11-19 Qt 失败轮次续跑已补齐批次结束后的多通道排队。确认后的请求按顺序复核并取得单通道资源，停止或关闭会取消等待项。191 项相关回归及三档 Windows 原生 Qt 共 156 项通过。现场设备验收待做。[排队阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/RESUME_QUEUE_QT_REPORT.md)

2026-11-19 Qt 已接入失败轮次续跑。原批次运行时复用原会话和控制队列，批次结束后单独获取已确认通道资源。首次阶段的 185 项相关回归及 153 项三档原生用例通过。[续跑阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/RESUME_QT_REPORT.md)

2026-11-19 Qt「消息推送」已接入本机确认后的单次试发，使用当前草稿和已保存项目名，自动识别钉钉或飞书。104 项相关回归及三档 150 项原生用例通过，真实目标群待验收。[消息试发阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PUSH_TRIAL_QT_REPORT.md)

2026-11-19 Qt「项目信息」已接入单通道样机版本查询及只读结果。沿用原 Telnet 登录和查询服务，读取当前窗口草稿，保留 `>` 的登录后命令确认及样机版本基准。119 项相关回归及 Windows 原生 Qt 三档各 49 项通过，真实样机待验收。[版本查询阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/VERSION_QUERY_QT_REPORT.md)

2026-11-19 Qt 测试项页已接入单次预备测试。确认绑定当前项目、已选通道和 Telnet/命令草稿，沿用原执行、检查、日志及停止流程。该阶段 100%、125%、150% 原生 Qt 共 144 项通过，另有 116 项相关回归通过。设备和长期验收待做。[预备测试阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PRETEST_QT_REPORT.md)

2026-11-19 Qt 全流程已接入原三项选择和配置就绪状态，经本机二次确认调用 `pipeline.start`。串口日志使用同一项目终端与日志目录，先逐台尝试再由原编排器运行后续。环境失败中止，停止等待原业务实际收尾。后续三档原生复验通过，现场验收待做。[全流程阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PIPELINE_QT_REPORT.md)

2026-11-19 Qt 样机升级已接入未配置程控电源时的手动重启确认。三种全包模式使用实际通道、空电源口、原预检和原升级任务，确认绑定项目配置与固件。通用能力对无程控电源仍保持原拒绝。三档原生模拟和补图已通过，实机验收待完成。[手动重启阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/FIRMWARE_MANUAL_REPORT.md)

2026-11-19 Qt ONU 已接入 C300/C600 项目配置、连接、模板和查询、注册、当前 PON 批量删除及注册后独立保存 OLT 启动配置。C300 单台注册的可选离线清理重试接入原只读候选查询、SN 复核和重试服务。三档各 5 项原生模拟和补图已通过，实机验收待做。[ONU 阶段证据索引](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/NEXT_ONU_AUDIT.md)

2026-11-19 Qt 写样机参数已接入原参数表导入、生成、目标预检、确认、独立批量执行和停止。串口回退自动展示原会话的只读日志，停止收尾后自动关闭。旧全流程联动和真机复验待做。[写参阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PARAMETER_WRITER_REPORT.md) [串口观察报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PARAMETER_OBSERVATION_REPORT.md)

2026-11-19 Qt 升级日志增量：有程控电源的全包升级自动展示原串口会话的只读输出，逐台状态来自原引擎回调。187 项相关回归通过，2 项默认跳过的本机浏览器用例另行启用并通过。三档 Windows 原生共 114 项通过。任务收尾只关闭自动观察窗。手动重启、旧全流程联动和设备现场验收待做。[阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/FIRMWARE_OBSERVATION_REPORT.md)

2026-11-19 Qt 样机升级增量：页面升级、有程控电源的 Tftp 指令/Tftp Put/Web 网关全包升级和项目升级设置接入。预检与本机确认绑定原固件哈希/真实目标，执行和安全停止走原 `firmware.upgrade` 与 Job。169项相关通过，两项默认跳过的无头浏览器案例另行启用并通过，源码/协议保全通过。三档窗口证据见[样机升级报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/FIRMWARE_REPORT.md)。手动重启、全流程联动及现场待迁移或验收。Tk 默认入口保持。

2026-11-19 Qt 最新检查点：DUT配置六页均接入原查询、配置和任务控制，64项相关、105项三档原生及3,093项完整基线（239指定用例）通过。之后补齐旧目录导入、修正项目凭据读取和TR069缺失字段显示，最新源码75项相关、108项三档原生及源码保全通过，截图见[后续报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/QT_FOLLOWUP_REPORT.md)。现场设备与系统DPI/多屏未验收。下一项为[样机升级](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/NEXT_FIRMWARE_AUDIT.md)，写参、ONU、AI/平台、长挂和Qt打包待实施或复验。默认入口仍为Tk。

最新Qt WiFi检查点（2026-11-19，自动化通过、待现场验收）：两频段所有表单字段、原查询能力、一致回填、双频、SSID递增、原60秒等待/回读/停止接入完成。恢复输入桌面后完整基线3087项和236项指定用例通过，303编译/293登记、505项GUI动作、协议及保全通过；原生33×3=99项和稳定布局复采2×3=6项通过。源码、文件列表、历史失败及实际截图见[WiFi阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/WIFI_REPORT.md)。下方为各轮历史检查点。

WAN当前验证边界：完整基线3071项/232指定回归、原生93项曾在同版源码通过。随后仅修正WAN确认摘要实际UBUS端口及断言，42项相关回归和源码检查通过，但最新原生在GUI创建前因OpenInputDesktop/WinError 5失败；未回退用户桌面。此增量保持“源码已实现、最新原生待恢复桌面复验、真实设备未验收”，不是全部通过。具体版本哈希和错误见本轮WAN报告；整份迁移目标继续。

最新Qt WAN增量（2026-11-18，已实现未现场验收）：原批量查询、共同名称/完整详情、新增/修改/删除、全部WAN字段和原显隐/回填/地址组合规则已接入；共用DUT独立目标/凭据/并发、一次确认/配置/NIC/查询绑定、原Job和资源保护。WAN密码仅给GUI私有回填，实际参数不改，持久任务/日志隐藏；停止等原worker，切页/关窗口不停任务。11项纯展示定义原文共享到models，旧Tk保留导入API，剩余34项定义AST一致，原服务/core不变。42项相关服务与最后三档31×3=93原生通过，宽二列/窄一列、行内完整性和滚动到底访问已验证；完整基线与最终源码结果见[WAN阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/WAN_REPORT.md)。整份计划仍活动，下一步WiFi/语音/TR069；其余模块、真实硬件/长期/部署未完成。未提交、打包、运行EXE、改真实网卡/DUT或外发消息。下方各条为对应历史检查点。

Qt DUT本轮验证汇总：28项相关服务回归（17新DUT）、完整基线3057项/229指定回归通过；随后仅调整新窗口滚动布局及对应原生断言，业务适配哈希不变，最后原生29×3=87项与298编译/288登记、493动作覆盖、协议及九份原DUT边界保全通过。560×460逻辑尺寸三档实际成立、结果可滚动访问。完整基线早于最后这两份UI/测试代码变化，未再次跑全量；版本范围与最终核对见本轮报告。

最新Qt DUT Telnet增量（2026-11-18，已实现未现场验收）：接入真实项目目标、独立选择、原凭据初值/会话草稿、默认取消确认、原批量开启/当前状态查询、1–8并行、逐台结果及原Job安全停止。原准入/项目快照/NIC身份/资源保护保持；关闭窗口和切项目不取消任务，重开仍关联原Job；查询成功不冒充测试健康。仅gui控制面，Qt日志/Job结果不含密码。原DUT service/core/Tk文件不改，最终验证和失败修复见[DUT Telnet阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/DUT_TELNET_REPORT.md)。WAN/WiFi/语音/TR069等后续增量、整个GUI迁移、真实硬件/长期/部署仍未完成；正常挂测仍Tk。未执行真实设备、网卡修改、外部消息、EXE或发布。下方为对应历史检查点。

最新Qt基本串口终端（2026-11-18，已实现未现场验收）：项目详情串口入口、已选VLAN/显式COM标签、打开/停止全部、文本/空回车、危险命令确认、目录恢复/选择、清屏及逐标签确认关闭已接入。原SerialSessionManager/PySerialSession、所有权/控制锁/实际串口参数/文件格式/关闭尾行保持；共享无文件日志时如实提示。仅gui来源，不扩大AI裸串口权限；后台操作与原100ms主线程轮询复用，窗口切换不停止监控，关闭等待实际reader/日志收尾。显示有界、非当前标签缓存、阅读锚点修复、窄窗口与三档截图通过。17项服务、最终原生27×3=81项通过，每档36受管顶层/违规0；296编译/286登记、488动作覆盖/协议及原串口边界字节保全通过。本轮最终完整基线3040项、226项指定回归及全部门禁通过（ALL CHECKS PASSED）；首轮父子编码不一致导致收集失败，统一UTF-8后完整复跑，失败记录保留。未连接真实串口/DUT、发送外部消息、提交、打包或运行EXE。原升级自动开窗/AI联动、窗口几何恢复仍待对应Qt模块；整体迁移、真实系统DPI/多屏/长期及部署未完成，正常挂测仍Tk。文件、前后截图、失败修正及验收边界见[串口阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/SERIAL_REPORT.md)。下方各轮结果为对应历史检查点。

最新Qt通道增量（2026-11-18，已实现未人工验收）：已接入16槽位选择/VLAN/COM/共享管理IP/电源绑定、全选/清除、只读资源刷新和预览确认保存，复用原ChannelCapabilities/ChannelConfigStore及原项目版本；只存已选行，未选绑定保留当前项目会话，不扩大AI/远程权限。通道与六标签编辑、任务互斥；版本冲突不覆盖、提交失败恢复/未知保护。矩阵/只读列表共用实际快照，修复隐藏列表撑高矩阵布局，窄表单自动换行、纵向访问。16项新服务用例及最终109项组合通过；原生24×3=72项最终顺序复验通过，每档30受管顶层/违规0；并发中间轮曾被原COM102资源保护拒绝，失败证据保留。294编译/284登记、478动作覆盖/协议及原业务字节保全通过。本轮未跑完整基线，前轮2981项不是本轮结果。正常测试仍Tk，整套迁移未完成；资源分组过滤/网卡改名/失败续跑、预备测试/版本查询/试发、其它业务页/历史日志/AI平台/可靠性/打包及真实设备/DPI/长挂仍待后续，持续开机老化保持待接入。文件、前后截图、实际验证和差异见[通道阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/CHANNELS_REPORT.md)。未提交、打包、运行EXE或操作真实设备。

最新Qt配置编辑增量（2026-11-18，已实现未人工验收）：六标签QDialog已接入原测试/运行/推送配置存储和项目版本保存，含命令/期望分段增删、默认命令草稿、WiFi网卡只读刷新、密码显隐、重载/保存/关闭；隐藏运行字段、禁用选项值、Telnet反向镜像及重试间隔唯一来源保留。GUI专用configuration.editor.*只接受gui来源，不向AI/远程返回私有值；同项目编辑租约/任务互斥，保存复核版本，暂存序列化及提交失败恢复，恢复失败保留未知保护。原生20项×三档=60项通过，每档23受管顶层/违规0；14项新增服务回归通过，相关156项首轮155通过、1项动作快照待更新，审查更新后覆盖模块3项复验通过；291编译/281源码登记、469动作覆盖、协议及原业务保全通过。本轮未跑完整基线，最近2981项仍为前轮结果。原预备测试/设备版本查询/消息试发、通道配置及其它业务页/历史日志/AI平台/打包仍待后续，不表示整个Phase 5或迁移完成。未操作真实设备、发送消息、提交或打包。文件、实际六标签截图、失败复现与剩余边界见[配置阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/CONFIGURATION_REPORT.md)。

最新Qt开关机接入（2026-11-18，Phase 3代码已实现、未设备验收）：Qt开始/环境检查/停止复用原CapabilityService/Jobs、PipelineOrchestrator及legacy_power_test_service；确认绑定项目、保存版本/全部配置字节、明确通道且两分钟内有效，NIC GUID与原主机资源保护继续准入。页面切换只切视图；任务数据来自原事件，当前测试配置显示runs快照；关闭等待原业务线程/串口实际结束，不接管旧Tk批次，不自动恢复未知历史。11项新服务回归和相关组合共146项通过，原生Qt16项×三档=48项通过、每档14受管顶层/违规0；288编译/278源码登记、覆盖/协议及旧业务字节保全通过。本轮未运行完整基线，最近2981项记录仍为前轮结果。配置编辑、其它业务页面/AI/平台、完整历史/日志导出、Qt打包和系统DPI/真实设备/24–72小时仍待后续；正常挂测仍使用Tk。文件、前后截图、差异和验证见[Phase 3报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PHASE3_REPORT.md)。未提交/打包/运行EXE。

最新Qt迁移检查点（2026-11-18，Phase 1与Phase 2基础管理已实现、待人工验收）：已修复下述初始基线阻断，保留Tk默认入口/原业务，增加独立`run_dutpilot_qt.py --demo`和`--workspace`。Qt工作台含统一主题、虚拟卡片/列表/筛选/排序、详情/16通道快照、只读配置和有界可拖动日志；真实项目新建/打开/保存/重命名/复制/关闭在后台串行复用原WorkspaceService/ProjectStore，保留UUID/revision/草稿/历史格式及本机人工控制。历史未完成只显示待核实，不自动恢复任务，关闭等待文件worker实际退出。当前Qt设备执行、完整配置编辑、其它业务/平台控制面仍未迁移或禁用，持续开机老化保持待接入，不代表整体迁移完成。最终完整基线2981项/211指定回归/287编译/277源码登记及全部覆盖/协议项通过；Qt原生12项×三档=36项通过，每档10受管顶层、违规0；61相关回归、910源码/17 SQLite恢复演练及原162 core/services+31旧业务+10本机配置+app.py字节保全通过。原生捕获不代替人工、真实系统DPI/设备/平台/24–72小时；旧包匹配与Qt打包仍待对应阶段。文件、启动方法和截图见[阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PHASE1_2_REPORT.md)。Qt只装仓库外独立开发环境；未提交/推送/打包/运行EXE，V1.2.10及原构建链保持。下方失败和旧结果保留历史事实。

最新PySide6迁移审计（2026-11-18，Phase 0审计交付、基线未放行）：负责人改为分阶段迁移Qt Widgets，已建立`feature/pyside6-migration`并保留原工作区/Tk入口，仓库外备份910份源码相关文件和1060份配置/历史文件，依赖及旧EXE留存。实际代码确认大部分service可复用，但Tk参数快照/准入/关闭及旧GUI批次接管仍需适配；持续开机老化仍待接入。新跑完整基线exit 1：273份编译/266源码登记/离屏预检及协议项通过，能力快照陈旧，全量unittest出现Tcl_AsyncDelete原生中止；定向14项中13通过、日志sash布局1项失败。不能沿用下方历史全绿记录宣布当前工作区通过。原生Tk临时两项目/16通道私有桌面捕获通过，不代表真实业务/DPI/现场验收；现有09月EXE与当前源码未建立版本匹配。报告/文件/截图/直接修复清单见[Phase 0审计](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PHASE0_AUDIT.md)，代码级阶段表见[迁移计划](.claude/plans/pyside6-migration.md)。本轮未改生产业务、未安装Qt、未实现Qt原型、未提交/推送/打包/运行EXE，V1.2.10保持。

最新GUI测试窗口隔离（2026-11-18，测试设施已实现）：统一入口为`python scripts/run_tests.py ...`和VS Code带“离屏预检”的任务；完整基线新增第八类gui_test_coverage，新增真实Tk测试漏接入会预检失败或被原始构造前的运行时守卫拦截，捕获异常/缺少子进程证据/泄漏作用域仍失败。普通窗口屏幕外映射；原生像素专项在系统核验的非输入私有桌面执行，保留原GetPixel断言、不切换用户桌面。相关组合975项及收尾78项通过，覆盖66个构造位置、38文件编译通过；未运行本轮完整基线，不覆盖下方2940项工作台历史边界。人工目视、VS Code实际任务、实体多屏待确认；只改测试设施与文档，不改产品验收状态、未提交/打包/运行EXE。文件、命令及结果见[本轮报告](Cheating_machine_execution_tool/validation/gui_offscreen_20261118/REPORT.md)及DEVELOPMENT_LOG最新条目。

收尾并发边界（2026-11-18）：下述工作台完整基线完成后，`Cheating_machine_execution_tool/tests/tk_test_windows.py`出现非本轮修改的并发改动，已原样保留；2940项结果不覆盖其后变化，不能作为当前含该改动的整工作区验证结论。详情见本轮Phase 1报告。

最新统一工作台（2026-11-18，Phase 1源码已实现，待Windows验收）：按负责人参考图调整深青色顶栏/侧栏、统计卡片、项目卡片/列表、运行项目分组/搜索、右侧配置摘要与原表单、底部可拖动/折叠日志；复用现有项目、运行、资源及安全退出链路，不改变设备命令、周期、判定、停止或配置快照。通道不同步只展示实际轮次范围，未知不计正常；新工作台日志显示有界，文件记录保留。负责人明确“持续开机全业务老化尚未实现，先保留待接入”，现有aging.start仍是开关机挂测，未创建Probe引擎。审计/代码级方案见[实施计划](.claude/plans/unified-workbench.md)，本轮文件、检查、截图及待验收清单见[Phase 1报告](Cheating_machine_execution_tool/validation/unified_workbench_20261118/PHASE1_REPORT.md)。本轮完整基线2940项测试、201项指定回归、270份编译、266份源码登记、能力覆盖及协议不变量全部通过（ALL CHECKS PASSED）；Windows真实交互、真实DPI、24/72小时及真实设备尚未验收，Phase 2/3未开展。分支ui/unified-workbench-phase1，未提交、推送、打包或运行EXE，V1.2.10不变。

最新本地提交（2026-11-18）：负责人明确要求提交当前全部改动，包含本机网络配置；以“将工具更名为DUTPilot并完善多项目收尾与布局预览”纳入源码、测试、计划、预览及相关文档。本次提交由既有pre-commit使用校验后的CPython3.9.10 x64执行完整基线，失败阻止提交，最终结果见本次钩子输出及DEVELOPMENT_LOG.md。下方各阶段未提交/未运行完整基线记录保留历史事实；Windows及真实模型/平台/DUT验收边界保持，布局预览尚未接入主程序。只提交本地，不推送、不构建或发布，版本V1.2.10及现有EXE保持。

最新产品改名（2026-11-17，源码已实现，待Windows与正式改名包复验）：当前工具名称统一为DUTPilot，后续标准产物为DUTPilot.exe、DUTPilot_portable.zip及对应校验文件；旧配置/AI/案例库路径、源码与构建入口、Windows应用标识和图标保留。新版更新客户端优先新名称并兼容旧附件组合，缺件/混配/校验失败明确报错；旧版首次换版需手动下载。529项相关回归分两组通过，22份Python编译、PowerShell语法及能力覆盖通过；首轮测试导入Mock污染已修正并组合复跑通过。详细文件、命令及既有工作区差异边界见DEVELOPMENT_LOG.md；[实施计划](.claude/plans/dutpilot-rename.md)，验收待办见ACCEPTANCE_BASELINE.md §2.15/§3。本轮未运行完整基线，最近完整记录保留；版本V1.2.10不变，未构建、运行EXE、提交、发布或连接真实平台/DUT，原有多项目及本机配置改动保留。

最新多项目布局预览（2026-11-17）：已按负责人认可的效果图制作独立真实Tk预览，统一顶栏、两行项目卡片及项目标题/紧凑导航；按首版反馈补回“3 环境检查与开关机测试”卡片，保留执行/停止按钮、状态、进度和通道概览，预览右侧可滚动。正常/最小窗口及100%/150%字体模拟四组布局检查、局部编译与差异检查通过，并取得自身窗口原生渲染截图。计划及运行方法见[布局对齐计划](.claude/plans/workspace-layout-alignment.md)，修订标准图见[预览PNG](.claude/plans/workspace-layout-preview.png)。当前等待负责人视觉确认，尚未接入主程序；现有业务、能力覆盖、完整基线和现场验收结论保持。Computer Use连接不可用，字体模拟不等同Windows DPI验收；本轮未提交、打包、发布或连接真实设备。

最新多项目源码收尾（2026-11-17，已实现未验收，未提交）：补齐统一项目状态与AI本地运行摘要、原始输入备份及失败标记、运行身份/快照和移动目录后的状态重载；四项目真实业务编排使用Fake传输自动化验证。预备测试未校验不冒充通过，ONU注册后write失败不被先前成功掩盖，未知仍须本机核实且不重放。按负责人选择移除独立交互验收脚本及专用测试，模拟辅助代码归入tests；人工验收直接在主源码目录执行`python run_line_check_assistant.py`，清单为`validation/multi_project_completion_20261117/ACCEPTANCE_CHECKLIST.md`。上一轮完整基线2916项、201项指定回归、269文件编译/263源码登记、能力覆盖与协议不变量全部通过，464文件哈希一致；此为移除独立入口前的历史结果，本次相关检查与文件清单见DEVELOPMENT_LOG最新条目。本轮只完成源码与验证，V1.2.10不变，不提交、不打包、不发布；可见Windows和真实模型/平台/DUT由负责人按清单确认，原计划不标记为全部验收完成。

最新多项目改造本地提交（2026-11-17）：负责人已确认将本轮63份改动以“实现单实例多项目管理与项目运行隔离”提交一次本地Git；范围包含全部多项目源码、测试、能力清单、计划及文档，原本机配置与受保护目录未修改。本次提交由既有pre-commit使用经校验的CPython3.9.10 x64重新执行完整基线，失败阻断，成功提交即全部门禁通过；实际结果及哈希以本次钩子和Git输出为准，文件清单见DEVELOPMENT_LOG.md。下方“本轮不提交”为对应开发阶段历史事实。仅本地提交，不推送、不打包；Windows可见交互及真实模型/平台/DUT仍待复验，现有EXE未更新。

最新单实例多项目工作区（2026-11-17，源码版，已实现待Windows/平台/设备复验）：默认入口改为一个Tk主窗口与可收起项目侧栏；支持新建、打开、切换、保存、恢复草稿、复制、改名、最近项目和旧配置导入。项目配置、运行快照、日志、会话、权限与停止边界独立；GUI、AI业务及原底层诊断共用跨项目资源保护。模型账户与平台连接统一管理，远程仅路由到本机明确允许的项目，审批/任务不随切换迁移，未知结果不重放。保留便携交付及`--legacy-single-project`回退。四项目并行模拟、真实离屏Tk及相关回归通过；最终冻结完整基线2884项、196项指定回归、262文件编译/258源码登记、能力覆盖及协议不变量全部通过，454文件哈希一致。全部文件与实际验证见DEVELOPMENT_LOG最新条目；现场清单见ACCEPTANCE_BASELINE.md §2.18/§3，使用说明见主源码操作员说明。本轮不提交、打包或运行EXE，不连接真实平台/模型/DUT；现有EXE未更新。

最新全部改动本地提交（2026-11-17）：负责人要求一次提交当前全部68份未忽略文件，备注“完善AI多实例管理、流式回复与多通道版本查询”，包含源码、测试、本机网卡配置、计划及文档。首轮2835项测试中源IP弹窗固定计时测量提前关闭导致1项失败，提交被阻止；修正测试为实际映射及布局后测量，保留宽度断言，27项源IP专项全部通过，不修改生产UI。完整基线由再次提交的现有钩子使用经校验的CPython3.9.10 x64在主源码目录实际执行，失败阻断，成功提交即全部门禁通过，实际结果见本次钩子输出和`DEVELOPMENT_LOG.md`最新条目。下方各轮“未提交/未运行完整基线”为阶段历史事实，本次提交检查以本段为准。仅本地提交，不推送；原Windows/真实模型/平台/DUT待验收边界保持，现有EXE未更新。

最新多实例管理标签页（2026-11-17，源码版，已实现待Windows/真实平台复验）：AI诊断助手“远程管理”右侧增加“多实例管理”，包含本机实例/统一网关；配对、允许通道/注册能力和启动模式经本地确认保存，下一次启动整个程序生效，当前连接和授权不改写。界面可保存网关地址/端口/VPN/WSS/平台与配对范围、启停、生成配对码、列出登记实例并通过右键/操作菜单查看及撤销；网关随主程序运行，隐藏窗口不停，退出异步收尾。CLI复用同一宿主service和数据库，外部CLI不接管停止；直接接入冲突明确拒绝，首批重配用新空闲槽位。配置/授权操作登记为人工控制面，仅提供local/gui只读状态Capability；保留原ASK/Job/未知保护及共享项目INI边界。相关检查和文件见DEVELOPMENT_LOG.md，[本轮计划](.claude/plans/ai-multi-instance-management-tab.md)，操作见主源码操作员说明，现场待办见ACCEPTANCE_BASELINE.md §2.16/§3。本轮不提交、不打包、不运行EXE或连接真实平台/模型/DUT；未运行完整基线，保留最近完整记录，现有EXE未更新。

最新对话流式回复（2026-11-17，源码版，已实现待Windows/真实模型及平台复验）：本地普通问答、排障及连续诊断默认流式；仅更新当前草稿，断流/取消正文标记未完成且不进入模型续接。飞书群/单聊CardKit及钉钉指定群AI卡片默认按条件使用，每卡合并刷新、长回复分段、终态收尾及唯一回复关联；卡片明确不可用降级完整回复，未知投递/重启不自动重发。钉钉现有配置新增可选模板ID，旧配置兼容；权限/模板仍属本地控制面。多实例网关保持完整回复，原工具校验、身份、权限、外发过滤及业务生命周期保持。最终流式40项、上下文36项、出口IP隔离27项通过，20份Python编译通过；组合回归及全仓登记/覆盖收尾仍受同期多实例新增页签及未同步清单影响，详见开发记录，不宣称组合全绿。实际专项结果和文件见DEVELOPMENT_LOG.md及[实施计划](.claude/plans/ai-streaming-replies.md)，现场待办见ACCEPTANCE_BASELINE.md §2.16/§3。本轮未运行完整基线，保留最近完整记录；未提交、打包或外发真实平台消息，EXE未更新。

最新多通道提交与版本查询（2026-11-17，源码版，已实现待Windows/真实模型及平台/多样机复验）：修复批量提交持会话锁等待GUI目标核验导致20秒超时，统一入队绑定批量请求并处理失败/取消/配置变化竞争；旧实现隔离回归稳定失败。明确版本请求复用device.version与原Job/权限，host端点绑定防止准入前静默换设备，逐台失败继续、配置变化或业务取消停止后续；先真实结果表再一次无工具AI说明，模型停止不取消已准入Job，原operation只读恢复不重放。461项组合及26项补充共487项通过（含32项新增专项，收尾32项再次通过）；独立离屏Tk45次提交/心跳小于200ms、13份Python编译及本轮差异检查通过。242份源码登记/能力覆盖为阶段结果，收尾时同期多实例新增UI及清单尚未同步，全仓覆盖/编译登记暂未通过，详见开发记录，不覆盖同期改动。详细边界及历史验证见DEVELOPMENT_LOG.md和[本轮计划](.claude/plans/ai-multichannel-timeout-version-query.md)，现场待办见ACCEPTANCE_BASELINE.md §2.16/§3。保留原未提交改动；未操作真机/真实模型或平台、未提交打包，EXE未更新；完整基线保留最近记录，本轮未运行。

最新新会话菜单（2026-11-17，源码版，已实现待完整Windows交互复验）：发送按钮右键/Alt+↓菜单第一行增加“新会话”，使用当前已保存模型创建并选中空白普通对话，不带入旧目标/材料；保留旧任务、发送模式及未发送草稿，识别期间禁用。共享service提供受控ai.sessions.create，只创建不发送、不切换GUI；能力覆盖同步。实际相关验证见DEVELOPMENT_LOG.md，[实施计划](.claude/plans/ai-new-session-menu.md)和ACCEPTANCE_BASELINE.md §2.16/§3列明边界。本轮未运行完整基线，保留最近完整验证记录；未提交、打包或运行EXE，现有EXE未更新。

最新飞书重连日志去重（2026-11-16，源码版，已实现待完整Windows复验）：持续重连仅显示首次连接失败，正在连接和其它日志不清除去重记忆；真正恢复显示一次，恢复后再次断开/停止重启可重新提示。正常首次连接保持静默，原始重连记录逐条落盘，动态状态和后台重连不变。日志74项、固定SDK离线连接7项、飞书接入64项及能力覆盖3项分进程共148项通过，无跳过；3份Python编译、能力覆盖及差异检查通过。没有新增或改变GUI动作/业务回调，快照仅刷新主窗口118条文件摘要；完整记录见DEVELOPMENT_LOG.md及[实施计划](.claude/plans/feishu-reconnect-log-dedup.md)，待验收见ACCEPTANCE_BASELINE.md §2.16/§3。本轮未运行完整基线，保留最近完整验证记录；未提交、打包、运行EXE或连接真实飞书，现有EXE未更新，上一轮模型出口IP改动保留。

最新模型出口IP（2026-11-16，源码版，已实现待完整Windows/真实模型复验）：模型接入页在连接测试右侧增加本机IPv4选择，默认不指定，按模型配置保存/复制；确定只编辑草稿，保存后统一用于模型列表、两种协议、流式/工具续接及自动诊断。直连和代理均绑定指定源IP，保留原代理/NO_PROXY；失效明确失败，不换出口。空值兼容旧指纹，出口变更清除能力验证并沿用原会话变更规则；晚到结果不覆盖新出口验证或草稿。207项组合回归通过，补充Windows真实绑定探测后27项出口专项通过（与组合回归重叠），12份Python编译、237源码覆盖及能力覆盖/差异检查通过。本机只读枚举58个IPv4，未调用真实模型/设备；能力清单88项（63接入/16部分/5待接入/4人工），新增出口候选可只读查询，配置写入保持本地控制面。完整文件及检查见DEVELOPMENT_LOG.md，操作见主源码操作员说明，现场待办见ACCEPTANCE_BASELINE.md §2.16/§3及[实施计划](.claude/plans/ai-model-source-ip.md)。本轮未运行完整基线，保留最近完整验证记录；未提交、打包或运行EXE，现有EXE未更新。

最新图标修复本地提交（2026-11-16）：负责人要求提交当前全部文件，备注“修复主窗口首次显示图标并完善回归验证”，共7份未忽略源码、测试、说明、计划及状态/验收文档。完整基线由现有提交钩子使用仓库配置的CPython3.9.10 x64在主源码目录实际执行，失败阻断，成功提交即全部门禁通过，最终结果见钩子输出及DEVELOPMENT_LOG.md最新条目。下方各阶段“未提交/未运行完整基线”保留当时事实，本次提交检查以本段为准。完整源码版图标目视仍待按ACCEPTANCE_BASELINE.md §2.17/§3复验；仅本地提交，现有EXE未更新。

最新启动图标修复（2026-11-16，源码版，已实现待完整Windows目视复验）：先设置Tk默认图标再设置主窗口，首次默认设置成功后补充默认刷新以保留子窗口原生小帧继承；窗口首次显示不再以Tk默认羽毛初始化。新增首次激活回归在旧顺序上实际失败，最终29项图标/模拟归档/便携专项全部通过，能力覆盖、两份Python编译及差异检查通过。资源、应用标识、业务入口和窗口生命周期保持；生产环境无新增钩子或定时任务。完整源码版任务栏、最小化恢复、Alt+Tab及串口窗口重开仍待负责人按ACCEPTANCE_BASELINE.md §2.17/§3复验，文件和历史问题见DEVELOPMENT_LOG.md及[本轮计划](.claude/plans/application-icon-first-show.md)。本轮未运行完整基线，保留此前本地提交`72a2f75`的完整门禁记录；未提交、打包、发布或运行EXE，现有EXE未更新。

最新全部改动本地提交（2026-11-16）：本次备注“完善公司AI网关、飞书依赖修复与串口升级交互”，包含当前全部未忽略源码、测试、文档、计划、验证材料和两份本机配置。首轮完整基线的环境缺包及Windows PNG压缩字节差异已定位处理；仓库Git检查显式使用仓库外`%LOCALAPPDATA%/LineCheckAssistant/feishu-repair-validation-py39/Scripts/python.exe`，CPython3.9.10 x64、锁定依赖及pip check均通过，未改当前源码运行环境。15项图标和25项网关专项通过；完整基线由本次提交钩子实际执行，失败阻断，成功提交即全部门禁通过，实际结果见钩子输出及DEVELOPMENT_LOG.md最新条目。下方“本轮未提交/未运行完整基线”保留各阶段当时事实，当前提交检查以本段为准。仅本地提交，原Windows/真实模型/平台/DUT待验收边界保持，现有EXE未更新。

最新串口标签关闭确认（2026-11-16，源码版，已实现待Windows交互复验）：点击所有标签“×”（含未打开串口/已停止）先确认目标VLAN/COM，默认取消；取消/Esc/关闭弹窗保留监控与日志记录，确定后沿用原占用保护、AI清理和异步关闭。整个窗口关闭及自动升级收尾不逐标签确认；AI被动监控关闭仍限其自身所有权，不调用GUI确认回调。专项检查见DEVELOPMENT_LOG.md，待验收见ACCEPTANCE_BASELINE.md §2.3/§3；本轮未运行完整基线，保留最近完整验证记录，未提交或打包，现有EXE未更新。

最新串口按钮调整（2026-11-16，源码版，已实现待Windows交互复验）：移除各串口标签底部「发送」按钮；命令输入框Enter发送及「回车」「清屏」保持，发送成功清空、危险确认及占用保护沿用原逻辑。专项结果见DEVELOPMENT_LOG.md，复验见ACCEPTANCE_BASELINE.md §2.3/§3；串口发送Capability保持pending。本轮未运行完整基线，保留最近完整验证记录；未提交或打包，现有EXE未更新。

最新Boot登录统一（2026-11-16，已实现待Windows源码版/真实样机复验）：按负责人新要求，Tftp Put及web打开网关的传统账号方式在首轮上下电完成后同步复用Tftp指令的`wait_for_boot_login`，三条实际路径使用相同探测、稳定检查、凭据分开发送/回车、游标采样及失败重试。每次探测回车后最多等1秒找用户名，再观察1秒排除提前密码；账号和密码均先发送文本、等1秒再回车，分别最多等30秒密码/20秒Shell，沿用默认600秒外层尝试窗口及乱码补救。前一轮半秒方案已被替代，旧Put方法仅保留兼容；Tftp指令实现、SDMC及传输/收尾保持。相关检查见DEVELOPMENT_LOG.md，待验收见ACCEPTANCE_BASELINE §2.5/§2.6.1/§3；本轮未运行完整基线，保留最近完整记录，现有EXE未更新。

最新飞书SDK按需修复（2026-11-16，源码版，已实现待完整Windows人工复验）：缺包弹窗新增“安装并重启”，原“确定”、Esc和关闭只跳过。仅本机操作员选择后，在当前隔离Python环境按项目锁定清单下载/核验必要wheel、离线安装并验证；活动任务或同环境实例占用时拒绝，不停止任务。安装期间阻止新业务，失败保留程序可重试；成功经原安全退出后等待旧进程真正退出，同解释器/工作目录/业务参数重启一次，不重放飞书绑定或启用。EXE只引导更新完整ZIP，不执行pip。覆盖矩阵现为87项（63接入/15部分/5待接入/4人工），新项为人工安装/重启控制面，AI无调用接口。完整修改文件、专项和隔离环境真实安装结果见[本轮实施记录](validation/feishu_sdk_repair_20261116/IMPLEMENTATION.md)；本轮未运行完整基线，保留最近完整验证记录，未构建/运行EXE或提交，原设备验收结论保持。

公司MiniMax网关接入（2026-11-16，源码版，已实现未完成真实模型验收）：仅授权`http://10.10.120.244:4000`，兼容显式`/v1`及完整Chat Completions路径；复用Bearer/DPAPI/工具能力验证。沿用Windows路由和现有代理，连接失败后有界只读取证，不绑定办公网IP或改系统网络。当前网关TCP可连接，未认证`/chat/completions`请求返回401；探测源IP为`198.18.0.1`、接口`Meta/5`，不据此推定原HTTP实际出口或办公网配置错误。默认AI配置库未找到该网关绑定凭据，两个模型的真实问答/工具续接及完整Windows交互仍待负责人验证。相关检查与修改文件见[本轮记录](validation/company_minimax_20261116/IMPLEMENTATION.md)；本轮未运行完整基线，保留下方最近完整验证记录，现有EXE未更新。

当前Git提交/推送准备（2026-11-16）：负责人授权将当前全部文件合为一次本地提交并推送GitHub，拟备注“完善全功能AI业务接入、多实例网关与串口日志体验”；原pre-commit完整基线门禁保持。fetch确认main已有4个未推送提交，origin是公开仓库；这些提交存在新增Webhook令牌/签名密钥和设备密码，公开推送需先明确凭据处置。此处为准备记录，实际提交/门禁结果以Git及本轮输出为准，不提前声明已推送；各阶段真实验收边界保持。

本阶段最终完整验证（2026-11-16，Full Capability Agent阶段4）：2589项测试、196项指定回归、230项编译/228主源码清单、能力覆盖和全部协议不变量通过，`ALL CHECKS PASSED`；运行前后369份Python文件快照一致。详细历史失败、Tcl测试清理、模块文件和离线指标见下方实施记录；本结果不替代真实Windows/模型/平台/DUT验收。当前矩阵63接入/15部分/5待接入/3人工，全功能目标继续保留。

最新Full Capability Agent阶段4续接（2026-11-16，源码版，已实现未现场验收）：通道勾选/绑定、GUID网卡改名与配置同步、永久升级/双型号ONU配置、默认测试项草稿、通知配置/固定试发、报告接手、案例按版本启停/删除及资源枚举已接入；明确多通道业务走同一原业务请求，保持原诊断流程。当前矩阵86项为63接入/15部分/5待接入/3人工；串口发送/目录、监控及两平台控制面、旧GUI批次接管等继续保留。配置数据桥不调用按钮或窗口生命周期，版本/编辑器/自动保存冲突拒绝；写入失败恢复视图，恢复失败保留保护。新选择不扩大AI设备权限，新增OLT配置不授予OLT执行权限。通道阶段完整2578项/196指定/229编译/227源码与367份快照通过；后续永久选项及Tcl回调修正289项相关检查通过，新的完整检查与文件清单见[本阶段记录](validation/full_capability_agent_20261115/IMPLEMENTATION.md)。保留各模块独立启动回退，不操作真实设备、外发消息、打包或提交；全功能目标尚未全部完成。

最新多实例统一接入首批（2026-11-16，源码版，已实现未现场验收）：独立命令行网关、程序目录外永久instance_id/启动run_id/槽位、DPAPI配对与逐实例撤销、签名WebSocket/心跳/重连、成员实例路由、持久化去重/确认及原request/operation/job关联已接入；源码显式`--gateway-slot`才启用，默认直接钉钉/飞书保持。目标实例复用现有Agent/Capability/权限/Job，远程新会话ASK，不继承本地FULL；跨进程保护覆盖本批共享业务及串口/电源/网卡入口，未知业务保留主机资源隔离。Fake固件链路只启动一次，网关断线/重启不取消已准入任务；Agent入队后确认丢失保守unknown，关联在入队前保存。新增33项专项、组合169/155项通过；最终完整基线2555项、196项指定回归、226文件编译/224主源码登记、能力覆盖及协议不变量全部通过，`ALL CHECKS PASSED`。运行期间另有两份同期AI数据能力文件变化，追加该模块10项通过，本接入代码摘要保持；详细文件、环境、历史失败和未完成项见[本批实现与验证](validation/multi_instance_remote_ai_20261115/IMPLEMENTATION.md)。CLI配对/本地批准已提供，GUI配对页、群内审批、跨实例取消/跨run接手及多通道完整投影仍待后续；真实平台/VPN/Windows/跨用户/DUT未验收。同目录仍共享项目INI，不同项目使用独立目录。不提交、不打包、不操作真机，现有EXE未更新；下方各阶段验证记录保留当时事实。

最新Full Capability Agent阶段3检查点（2026-11-16复核，源码版，已实现未验收）：供电/老化/原三项全流程/失败续跑、写参、DUT、ONU、配置/被动观测/日志、项目数据/模型测试及更新已有受控适配；本地版本化业务模板、任务管理、幂等/未知保护及模块回退已接入。GUI/AI复用原业务，三档权限/来源/范围保持；确认后再次检查占用，模型停止不取消业务。矩阵86项中53接入/15部分/15待接入/3人工，旧GUI批次接管等继续实施。385项相关回归及最终2554项完整基线、196项指定回归、226项编译/224源码清单、覆盖及协议不变量全部通过，363文件源码快照一致。详见[实施与验证](validation/full_capability_agent_20261115/IMPLEMENTATION.md)；这是本阶段检查点，不代表整体完成或现场验收。没有操作真实DUT、构建或更新EXE。

最新串口日志滚动（2026-11-15，源码版，已实现未验收）：每个VLAN/COM显示区增加右侧竖向滚动条并保留长行换行；底部跟随新日志，向上翻阅保持阅读位置，回到底部恢复跟随，各标签独立。追加及5000行裁剪保持存续阅读内容，被裁掉时回到剩余内容起点；采集、写盘及设备命令保持。40项串口窗口专项（含6项新增、Vista/Clam离屏Tk）通过，检查命令及最终结果见DEVELOPMENT_LOG.md；Windows日常源码交互待按ACCEPTANCE_BASELINE.md §2.3/§3复验。未运行完整基线，保留已有完整记录；未打包或提交，现有EXE未更新。

最新多实例远程AI方案修订（2026-11-15，计划与依赖审查，尚未实现）：已合并负责人七项补充要求，采用常开电脑统一网关、各实例本地Agent/Capability/Job执行、跨网VPN接入；永久instance_id与进程启动run_id分离，授权/审批及消息关联绑定具体实例和原任务，完全访问仍由本地现有权限服务验证。依赖审查确认Registry/Service/持久化Job/幂等已有基础，首批升级已有历史验证；供电/老化/DUT工作区适配仍在扩展，覆盖矩阵尚列pending，写参/ONU等继续依赖Full Capability Agent逐项接通。多实例身份/可信轮次关联、槽位隔离及现有资源层跨进程保护列为联调前置；不在网关复制业务工具、任务存储或权限机制。完整修订及Mock/Fake验收矩阵见[实施计划](.claude/plans/multi-instance-remote-ai.md)，依赖交接见[Full Capability Agent台账](.claude/plans/full-capability-agent.md)。本轮仅修改计划/状态/开发记录并检查文档一致性、链接及差异格式，未运行代码测试或完整基线，保留下方已有验证记录；没有网关可部署、没有业务代码变更，不提交/打包或连接真实平台/DUT，现有EXE未更新。

最新全功能Agent首批（2026-11-15，源码版，已实现未验收）：显式能力目录、按需/快捷工具与schema缓存、可信权限/身份桥、独立持久化业务任务和实时资源准入已接入；GUI/AI共用原四条升级引擎的数据分发，模型/对话停止不取消业务，明确业务取消才安全收尾。适配未知须真实用户确认并绑定目标/固件哈希，默认不加刷后登录，未知结果不重放。86项覆盖台账保留73项待接入及人工控制面，首批不代表全功能完成；通用工具迁移/受控扩展尚待后续阶段。改前2430项完整基线通过；本批最终2456项、196项指定回归、201源码编译/清单、能力覆盖及协议不变量全通过。入口见`CAPABILITY_COVERAGE.md`及`.claude/plans/full-capability-agent.md`，文件/实际验证见DEVELOPMENT_LOG.md；不提交、打包或操作真实模型/平台/DUT，现有EXE未更新。

最新本地提交完整验证（2026-11-15，全部工作区改动）：负责人要求将当前全部改动合并为一次本地提交，范围144个文件，包含源码、测试、文档、验证材料及两份本机配置；备注“完善AI执行安全保护、历史监测与排障界面”。首轮完整基线仅Vista/Clam两个旧按钮顺序断言失败，已按既有诊断报告前移需求同步测试期望；42项钉钉专项和完整基线复验通过：2430项测试、196项指定关键回归、189个源码编译/清单覆盖及协议不变量全部通过，`ALL CHECKS PASSED`，实际提交继续由既有钩子复核。下方各轮未提交、未运行完整基线及组合失败说明保留当时事实，当前以本段和DEVELOPMENT_LOG.md最新记录为准。仅本地提交，不推送、打包或发布；Windows/真实模型/平台/DUT待验收边界保持，现有EXE未更新。

最新AI旧历史入口移除（2026-11-15，源码版，已实现未验收）：删除排障工作台“历史”按钮、旧历史窗口及专用读取实现，清理两平台保存提示与编译登记。旧数据库、项目隔离、模型配置和共用案例迁移保持；当前会话、报告与案例仍由原入口管理。156项相关测试、8个文件编译、189个源码编译清单覆盖及登记路径检查通过；Vista/Clam项目隔离窗口与隐藏重开检查通过，完整Windows源码版目视复验见ACCEPTANCE_BASELINE.md §2.16/§3。方案见`.claude/plans/remove-ai-legacy-history.md`，文件和验证方法见DEVELOPMENT_LOG.md。本轮未运行完整基线，保留最近完整记录；未提交、打包或操作真实模型/平台/设备，现有EXE未更新。

最新AI长日志精简（2026-11-15，源码版，已实现未验收）：仅调整现有显示过滤层，串口诊断端口/PnP/驱动JSON压为一行端口与状态摘要，查询/打开错误、占用、冲突和PnP异常保留提示；已知断线长文案缩短，重复未下发说明只显示一次，不合并不同事件、不改变执行状态。已隐藏的正常工具提示继续隐藏，主日志完整原文及现有密钥过滤保持。66项日志专项（含Vista/Clam独立Tk显示/颜色/落盘）、相关编译及附件4行回放通过；附件串口行由23733字符缩为30字符，完整原文落盘一致。验证与文件见DEVELOPMENT_LOG.md；Windows完整程序目视复验见ACCEPTANCE_BASELINE.md §2.16/§3。本轮未运行完整基线，保留最近完整验证记录；未提交、打包或操作真实设备，现有EXE未更新。

最新P0保护与A7监测（2026-11-15，源码版，已实现未现场验收）：A1统一整机/设备/共享资源的本机命令及写入准入，覆盖AI目标子集与下发前转忙；只读分析、历史检索、被动采集和问题报告保留。A2发送前复核Shell，Boot/重新登录/断线/未知结果停止复用且不跨协议重发，cleanup保留占用与会话保护。A7独立60秒只读监测，不改接收、写盘或缓冲机制；8/16路分别真实运行3601.062/3602.078秒，各63份样本，文本序号/摘要和资源收尾通过，原始字节保真明确不接受。history增长73.97/147.92MiB每小时，168小时趋势估计12.14/24.27GiB，未完成该时长验证。新增39项当前专项和60项收尾通过；完成实现时30组777项通过，随后同期UI改动合并后785项中2个子用例因旧按钮顺序断言失败，当前组合未全通过。真实报告、曲线及分批补丁见`validation/harness_p0_a7_20261115/REPORT.md`与`IMPLEMENTATION.md`；8路观测版本边界见`VALIDATION_SCOPE.md`。Windows/真实模型/DUT仍待ACCEPTANCE_BASELINE §2.16/§3复验；A3/A8仅影响矩阵见`AI_HARNESS_COMPATIBILITY.md`。本轮未运行完整基线、未提交或打包，保留下方最近完整记录，现有EXE未更新。

最新本地提交完整验证（2026-11-15，AI功能工作区）：负责人明确确认提交当前全部源码、测试和文档，排除本机配置；共95个文件，提交备注“完善AI连续排障、飞书接入与多样机任务”。标准Git检查入口使用独立CPython3.9.10 x64执行完整`verify_baseline.py`，2382项测试、196项指定关键回归、188个源码编译/清单覆盖及协议不变量全部通过，`ALL CHECKS PASSED`，实际提交继续由既有钩子复核。`config.ini`原修改保留且未纳入；仅本地提交，不推送、打包或发布，现有EXE未更新，既有Windows/真实模型/平台/DUT待验收结论保持。下方未提交和未运行完整基线说明保留各轮当时事实，本轮以本段与DEVELOPMENT_LOG.md最新记录为准。

最新AI连续诊断（2026-11-15，源码版，已实现未验收）：排障工作台发送按钮右键/Alt+↓按需切换连续诊断，仅定位本机或单个设备并给建议；常规/批量/远程及自动监控保留原入口与默认行为。独立有界任务保存计划、带证据引用的观察笔记、实际检查和纠正，支持安全节点接纳补充、重复/无进展收束及两协议流式正文；执行层限制为固定只读工具，完整流结果才入库/执行，停止及重启不自动重放。方案见`.claude/plans/ai-continuous-diagnosis.md`，本轮实际专项结果见DEVELOPMENT_LOG.md；Windows交互、实际模型兼容/诊断质量和DUT复验见ACCEPTANCE_BASELINE.md §2.16/§3。未运行完整基线，保留最近完整记录；未提交、打包或连接真实模型/设备，现有EXE未更新。

最新AI多样机任务（2026-11-15，源码版，已实现未验收）：本地/钉钉/飞书支持明确多个通道、全部、逐台及失败/剩余目标续查，一个父对话展示逐台进度、原始证据与结构化汇总。新增独立编排模块，沿用单目标执行器、串行互斥及三档权限；默认先检查全部再处理异常，检查不扩展为修改，本机共享步骤只执行一次。单台失败继续，共享/清理异常暂停，未知结果不重发，继续不重放已完成阶段；停止整批、重启不自动执行，历史人工选中仅材料分析。实现入口见`.claude/plans/ai-batch-tasks.md`与主源码`src/services/ai_batch_service.py`；本轮实际验证见DEVELOPMENT_LOG.md，Windows、真实模型/平台/三台样机复验见ACCEPTANCE_BASELINE.md §2.16/§3。本轮未运行完整基线，保留最近完整验证记录；未提交、打包或连接真实设备，现有EXE未更新。

最新历史窗口优化（2026-11-15，源码版，已实现未验收）：“重试/失败历史”各通道共用上次关闭宽高，重启后恢复，默认760×440、最小560×300，恢复后居中；关闭按钮、右上角、测试重启及主程序退出统一保存。该窗口作为层级例外保持在主界面上层，仍可操作主界面，切换其它软件不强制置顶；沿用本机尺寸文件与容错，背景统一。66项相关检查通过，完整Windows可见层级、软件切换、最小化/恢复及重启宽高待ACCEPTANCE_BASELINE.md §2.12/§3复验。方案见`.claude/plans/power-test-history-window-state.md`，本轮未运行完整基线，最近完整验证记录保持；不提交、不打包，现有EXE未更新。

最新AI发送反馈（2026-11-15，源码版，已实现未验收）：本地排障工作台发送后先回显用户消息并清空输入，再静默后台识别；复用既有回调记录入库边界，正式记录替换回显，避免同文历史误去重。失败保留原文与新草稿，停止、切换和迟到结果按请求代次处理；原路由、权限及设备执行规则保持。方案见`.claude/plans/ai-chat-immediate-send.md`，本轮实际验证见DEVELOPMENT_LOG.md；完整Windows源码版发送手感及错误/草稿交互待ACCEPTANCE_BASELINE.md §2.16/§3复验。本轮未运行完整基线，保留最近完整验证记录；不提交、不打包、不连接真实模型/设备，现有EXE未更新。

最新AI日志任务摘要（2026-11-15，源码版，已实现未验收）：按负责人追加确认，主界面收起实际命令/登录/逐项正常完成，以及案例初始化、路由/自动授权、已知历史资格、证据列表/统计、重复采集状态和正常连接过程；正常排查只留入队开始与本轮结束，不声称成功。批准、用户反馈、失败/拦截/未知结果、停止和恢复异常保留，执行过通用操作时仍提醒不自动回滚。原始日志71条事件只显示2条；脱敏39条界面事件回放亦收敛为2条，原文完整落盘，两处监控状态及服务/执行流程保持。本轮专项结果见DEVELOPMENT_LOG.md，Windows源码版目视/文件对照待ACCEPTANCE_BASELINE.md §2.16/§3复验；未运行完整基线、未提交/打包或连接真实平台/模型/设备，现有EXE未更新，保留最近完整验证记录。

最新远程管理入口（2026-11-15，源码版，已实现未验收）：AI诊断助手增加第四个Tab“远程管理”，钉钉/飞书两个子页签直接嵌入原接入表单；测试项配置第六页恢复“消息推送”名称并移除AI接入按钮。首次进入创建，切换/隐藏保留草稿；隐藏取消未完成绑定，已启用远程AI/通知及其它任务继续，表单刷新暂停/恢复不重复注册。原配置、确认、通知和首次保存后重启要求保持；钉钉保存同步已打开消息推送页的地址/密钥，其余编辑及未保存提醒保持。方案见`.claude/plans/ai-remote-management-tabs.md`，本轮实际验证见DEVELOPMENT_LOG.md；Windows完整交互待ACCEPTANCE_BASELINE.md §2.11/§2.16/§3复验。本轮未运行完整基线，不提交、不打包、不连接真实平台/模型/设备，现有EXE未更新。下方旧入口名称保留各轮历史记录，当前入口以本段为准。

最新对话目标与会话路由（2026-11-15，源码版，已实现未验收）：本地排障工作台移除目标下拉框/新会话按钮，本地、钉钉、飞书共用对话识别；支持普通问答、本机电脑独立排障及当前已勾选有效设备通道，歧义在对话内追问。优先续接身份/范围/配置/当前批次匹配的会话，明确新建才另开；人工选中的历史会话续聊保持材料分析。切换后原任务与批准保持原会话，新排查沿用现有串行队列；回复按原来源目标发送。本机仅提供本机工具，三类会话的证据、授权及显示隔离。方案与入口见`.claude/plans/ai-conversation-target-routing.md`、`src/services/ai_session_router.py`（主源码目录）；本轮实际专项结果见DEVELOPMENT_LOG.md，Windows完整界面、真实模型/群聊/DUT复验列入ACCEPTANCE_BASELINE.md §2.16/§3。不提交、不打包、不发布，现有EXE未更新。

最新AI默认权限（2026-11-15，源码版，已实现未验收）：本地排障、自动监控、飞书群聊/单聊默认完全访问；首次对旧会话及监控设置一次性迁移，后续手动降级持久保留。本地/飞书/监控偏好独立，钉钉固定默认帮我批准保持。选择与有效授权分离，停止/绑定变化撤销旧授权；有效会话初始化/下一次用户发送或重新启用监控时校验新授权，刷新不重授权，旧操作不重放。监控仍默认关闭，启用确认保留目标/危险操作/信息发送范围。方案见`.claude/plans/ai-full-access-defaults.md`，实际专项检查见DEVELOPMENT_LOG.md；完整Windows、真实飞书/模型/DUT复验见ACCEPTANCE_BASELINE.md §2.16/§3。本轮未运行完整基线，保留最近完整验证记录；不提交、不打包、不发布，现有EXE未更新。

最新飞书回复排版（2026-11-15，源码版，已实现未验收）：AI正文、状态及批准提示统一富文本，支持Markdown及原生代码块；项目/通道/成员独立标题，单段取消[1/1]、多段才编号。仅省略system/recovery精确“本轮恢复状态：无临时修改”消息并推进游标，保留原始记录、恢复结果/风险警告及既有批准语义。长回复按真实请求大小分段、外发凭据及@标签过滤、原测试通知保持。方案见`.claude/plans/feishu-reply-format.md`；本轮实际专项结果见DEVELOPMENT_LOG.md，真实飞书桌面/手机显示及复制待ACCEPTANCE_BASELINE.md §2.16/§3复验。本轮未运行完整基线，保留最近完整验证记录；不提交、不打包、不发布，现有EXE未更新。

最新Webhook自动适配（2026-11-15，源码版，已实现未验收）：远程管理同一组Webhook/密钥按完整地址自动识别钉钉或飞书群自定义机器人，“启用消息推送”及试发/正式通知跟随平台；旧四字段兼容，飞书通知不附远程客户端字段，原飞书AI应用通知独立。方案见`.claude/plans/webhook-auto-platform.md`，实际检查见DEVELOPMENT_LOG.md；Windows可见/真实群签名及@所有人待ACCEPTANCE_BASELINE.md §2.11/§3复验。本轮未运行完整基线，保留最近完整验证记录；不提交、不打包、不发布，现有EXE未更新。

最新飞书AI接入（2026-11-14，源码版，已实现未验收）：远程管理增加飞书应用配置入口，独立群排障、应用可用范围内全员单聊及测试通知开关；与钉钉并行，共用本项目AI工作台及当前共用案例库入口，会话和批准按平台/企业/聊天类型/人员/通道隔离。群绑定本机确认，单聊启用明确确认范围，新会话现按2026-11-15规则默认完全访问并保留后续手动降级；持久化去重后ACK、退出清理及外发过滤保持。正式飞书通知仅发送项目/通道/结果，不含远程客户端信息，保留原钉钉调用及返回语义。实现方案见`.claude/plans/feishu-ai-workspace.md`，配置步骤见操作员说明“飞书 AI 接入与测试通知”；实际专项/依赖检查见DEVELOPMENT_LOG.md。未运行本轮完整基线、不提交、不打包、不发布，现有EXE未更新；Windows可见界面、真实飞书/模型/DUT待验收见ACCEPTANCE_BASELINE.md §2.16/§3，最近完整验证记录保持。

最新共用案例库（2026-11-14，源码版，已实现未验收）：同一Windows用户的全部项目/模型共用独立案例库，旧AI库和项目库只读汇集，保留全部修订、来源报告ID及停用状态；会话、报告、配置和权限继续原隔离。版本校验拦截跨项目覆盖，冲突保留草稿，删除UUID防止迁移/升级复活。标准构建导出同一份案例快照随EXE/ZIP交付，校验数量/哈希及归档一致性，升级只补充新案例；当前本机原库检查为0条，允许空快照。文件与本轮实际检查见DEVELOPMENT_LOG.md，方案见`.claude/plans/shared-ai-cases.md`；完整Windows/异机导入与升级复验见ACCEPTANCE_BASELINE.md §2.16/§3。本轮不提交、打包或发布，未运行完整基线，保留下方最近完整验证记录；现有EXE未更新。

最新提交前完整验证（2026-11-14，钉钉AI排障提交）：负责人要求以“钉钉接入项目 AI 排障工作台”为备注创建本地提交，范围为28个功能、依赖、测试及文档文件；原有本机config.ini通知开关修改保留且不纳入。标准Git检查入口使用独立CPython3.9.10 x64执行完整`verify_baseline.py`，2134项测试、196项指定关键回归、168个源码编译/清单覆盖及协议不变量全部通过，`ALL CHECKS PASSED`；提交仍由既有钩子复核。本轮不推送、打包或发布，完整Windows/真实钉钉/模型/DUT待验收项保持；下方未提交描述保留各轮当时状态，详细证据见DEVELOPMENT_LOG.md。

最新完整验证（2026-11-14，钉钉项目AI排障）：标准独立CPython3.9.10 x64执行`verify_baseline.py`，2134项测试、196项指定关键回归、168个源码编译/清单覆盖及协议不变量全部通过，`ALL CHECKS PASSED`；新增钉钉专项40项。新增websockets 15.0.1后的锁定依赖环境及源码运行时导入检查通过；完整Windows/真实钉钉/模型/DUT仍待负责人按§2.16/§3复验。详细改动、首轮异常与最终验证见DEVELOPMENT_LOG.md；未提交、推送、打包或发布，既有历史完整验证记录保留如下。

最新钉钉项目排障（2026-11-14，源码版，已实现待复验）：每个项目目录绑定独立应用机器人，Stream接收指定群全员文字消息，按成员/通道建立本地可见会话；默认帮我批准，本地可切三档，具体待批准操作支持发起人一次性编号或本地处理。保存接入配置同步测试通知Webhook，保留原开关/@所有人；项目AI库隔离，首次仅复制模型配置/凭据及容量缓存，旧数据库保留；旧历史查看入口已于2026-11-15移除。消息持久化去重、独立通知订阅、后台收发/停止和凭据过滤已接入；计划及回退见`.claude/plans/dingtalk-ai-workspace.md`，操作入口见操作员说明，真实钉钉/完整Windows/模型/DUT待验收见ACCEPTANCE_BASELINE.md §2.16/§3。本轮实际验证结果见DEVELOPMENT_LOG.md；不提交、不打包、不发布，既有EXE未更新。

最新提交前完整验证（2026-11-14，AI能力优化）：负责人要求按已有62个暂存文件创建本地提交，备注“优化ai能力1114”。标准Git检查入口使用独立CPython 3.9.10 x64执行完整`verify_baseline.py`，2094项测试、196项指定关键回归、161个源码编译/清单覆盖及协议不变量全部通过，`ALL CHECKS PASSED`。首次默认环境的临时目录短/长路径断言差异经统一进程临时路径后复验通过，AI操作专项37项通过；详细证据及既有INI空白告警见DEVELOPMENT_LOG.md。提交仍由既有钩子复核；本轮不推送、打包或发布，不新增Windows/真实模型/样机验收结论，下方未提交及未运行完整基线描述保留各轮当时状态。

最新工具栏调整（2026-11-14，源码版，已实现未验收）：原“刷新串口”“刷新网卡”合并为“刷新串口/网卡”，位于管理员状态与检查更新之间，点击后依次调用原串口及网卡刷新入口。原筛选、选择保留、异常处理与日志保持；40项相关检查、3文件局部编译通过，包含Vista/Clam宽窄窗口独立Tk及两种候选模式。完整Windows源码版目视复验见ACCEPTANCE_BASELINE.md §2.1/§3，详细文件及验证命令见DEVELOPMENT_LOG.md。本轮未运行完整基线，保留既有最近完整验证记录；未提交、打包或操作真实设备，现有EXE未更新。

最新监控独立授权（2026-11-14，源码版，已实现未验收）：自动监控原深入采集勾选框原位替换为独立三档权限，默认权限现按2026-11-15规则为完全访问，按权限使用完整工具诊断并按需修复。完全访问须确认所选全部目标和危险操作，授权仅在进程/范围/批次内有效；关闭、主动停止、配置或批次变化、重启失效，保留选择，重新启用时校验新授权。独立监控上下文和报告操作记录复用原风险审查/批准/执行链路，不创建聊天或同步聊天权限；不明结果跨任务重试仍须批准。动态状态提供待批准详情入口，保留占用/停止/临时恢复及原触发节奏，旧deep_enabled不再门控监控。实现、专项结果见DEVELOPMENT_LOG.md及`.claude/plans/ai-monitor-permissions.md`，完整Windows/真实模型/DUT复验见ACCEPTANCE_BASELINE.md §2.16/§3。本轮未运行完整基线，保留既有最近完整验证记录，未提交、打包或操作真实模型/样机。

最新AI列表辨识优化（2026-11-14，源码版，已实现未验收）：排障会话与诊断报告保留下拉框，以本地提取的问题主题开头，附通道/轮次、紧凑时间及状态；模型和完整主题/时间/ID通过悬停查看。下拉及管理窗口单选支持右键重命名，人工名称独立持久化、后台生成不覆盖，管理列表同步主题，删除时清理对应名称。保留正文/上下文、选择/草稿/阅读位置及原报告接手、删除/忙碌保护；不增加模型或设备操作。实现与实际检查见DEVELOPMENT_LOG.md及`.claude/plans/ai-record-list-titles.md`，完整Windows人工复验见ACCEPTANCE_BASELINE.md §2.16/§3；本轮未运行完整基线，保留下方最近完整验证记录，未提交或打包。

最新样机稳定性诊断（2026-11-14，源码版，已实现未验收）：自动诊断/对话排障共用独立只读证据整理，优先首次故障、问题相关原文及最新状态，整理panic/Oops/OOM/watchdog/启动/复位与上下电文本线索，保留来源、片段范围及分离的采集/日志/内核时间；线索不自动升级根因，长文不再仅取尾部。证据检索及人工确认案例/操作员章节改为有效相关命中，主日志记录选证与资料结果。沿用原始材料存储、工具、监控触发、权限/登录、占用和停止边界，不新增串口打开或采集。文件和本轮实际检查见DEVELOPMENT_LOG.md及`.claude/plans/ai-dut-stability-evidence.md`，真实模型效果和样机复验入口见ACCEPTANCE_BASELINE.md §2.16/§3。本轮未运行完整基线，保留下方最近完整验证记录，未提交、打包或访问真实模型/DUT。

最新AI网络诊断（2026-11-14，源码版）：自动诊断与对话排障共用目标网卡只读取证，精确匹配配置别名，区分管理禁用、链路断开、源IP未就绪、身份冲突及查询失败；源IP命中的其它接口仅列候选。PC快照保留完整目标摘要与合法JSON，原命令分别限长/标记失败和截断；已确认源IP不可用且首次Telnet/串口均失败后跳过本轮重复连接，刷新PC环境或下一任务可重查，独立串口/原权限和登录保护保持。专项验证与本机只读脚本检查见DEVELOPMENT_LOG.md，负责人复验入口见ACCEPTANCE_BASELINE.md §2.16/§3及`.claude/plans/ai-pc-network-diagnostics.md`；本轮未运行完整基线，保留下方最近完整验证记录，未提交、打包或访问真实模型/DUT。

最新诊断报告排版（2026-11-14，源码版）：诊断报告保留单页阅读，按浅绿“诊断分析”与浅灰“本地证据”分区；正文复用排障工作台Markdown样式，兼容旧报告独立章节标题，证据等宽原文显示。保留只读复制、刷新位置/选区、切报告回顶部及恢复状态，不改模型、存储或接手/案例/删除流程。91项相关测试（含6项新增排版专项）、2文件局部编译及差异检查通过；Vista/Clam默认及最小窗口独立Tk检查通过，computer-use native pipe不可用，完整Windows人工复验见ACCEPTANCE_BASELINE.md §2.16/§3。本轮未运行完整基线，保留下方最近完整验证记录；未提交、打包或访问真实模型/设备。

最新报告交互优化（2026-11-14，源码版）：移除诊断报告常驻设备下拉框；有目标快照的报告沿用原流程，缺少快照的旧报告点击“继续排查”后才弹出同通道当前设备列表，默认不选、取消优先，选择后保留默认取消的关联确认。无匹配目标保留报告查看，模态交互固定报告来源并由原service复核目标/报告有效性；现有报告删除、案例、权限、历史批次及采集/模型请求规则保持。相关验证见DEVELOPMENT_LOG.md，完整Windows人工复验见ACCEPTANCE_BASELINE.md §2.16/§3；本轮未运行完整基线，保留下方最近完整验证记录，未提交或打包。

最新AI报告管理（2026-11-14，源码版）：诊断报告窗口“从此报告新建案例”右侧新增“删除报告…”入口，独立管理全部历史报告，支持多选删除及清空全部、默认取消确认。仅删除报告，关联会话留存材料/案例及修订/来源ID/原始日志/模型配置保持；排队、生成或清理中的报告整批拒绝，事务失败回滚，确认期间新增报告保留。删除后同步查看窗口并过滤已删除报告的待处理通知；相关验证见DEVELOPMENT_LOG.md，完整Windows人工复验见ACCEPTANCE_BASELINE.md §2.16/§3。本轮未运行完整基线，保留以下最近完整验证记录；未提交、打包或访问真实模型/设备。

最新AI监控状态（2026-11-14，源码版）：主界面开关机测试状态右侧新增AI自动监控状态，与排障工作台同步开关、待测试、监控中及自动诊断排队/执行/收尾；手动聊天隔离，隐藏AI窗口继续同步，关闭监控待清理完成后才显示完全关闭。窄窗口各状态区独立折行，沿用现有监控触发、权限和设备流程；相关验证见DEVELOPMENT_LOG.md，完整Windows人工复验见ACCEPTANCE_BASELINE.md §2.16/§3。本轮未运行完整基线，保留以下最近完整验证记录；未打包、提交或操作真实模型/设备。

最新交付与完整验证（2026-11-13）：[V1.2.10](https://github.com/oscarouxue-coder/Power_OnOff_Assistant/releases/tag/v1.2.10)已按标准独立CPython3.9.10 x64/固定依赖/PyInstaller5.10.1入口构建并公开为GitHub Latest，最终只保留本版Release及ZIP、ZIP SHA256两个附件。完整基线153个源码编译/覆盖、1937项测试（2项既有跳过）、196项指定关键回归及协议不变量通过；实际EXE/PYZ、图标/Tcl/Tk、原生依赖、排除项、ZIP CRC/哈希、149个冻结模块和6份脱敏配置一致性通过。两个附件匿名完整下载及真实源码更新客户端V1.2.9→V1.2.10检查/下载、V1.2.10无更新通过后，删除V1.2.9 Release并保留旧标签/源码历史。本地输出`Cheating_machine_execution_tool/dist/V1.2.10_slim_20261113/`；未运行新EXE、未自动提交/推送本轮版本和文档。前两轮路径比较与焦点断言失败、最终通过证据见DEVELOPMENT_LOG.md；目标电脑启动、真实多串口/长时间、ONU批量删除及AI/模型仍按ACCEPTANCE_BASELINE.md原清单复验，下方“未打包/未发布”保留各轮当时状态。

最新提交前完整验证（2026-11-13，串口大流量优化）：负责人确认本次提交全部现有源码、测试和文档改动，共65个文件，包含串口/全流程修复、ONU批量删除、统一图标、界面说明精简及相关验证证据。标准Git检查入口使用CPython 3.9.10 x64执行完整`verify_baseline.py`，1937项测试、196项指定关键回归、153个源码编译/覆盖及协议不变量全部通过，`ALL CHECKS PASSED`。提交前main与origin/main分歧0/0；备注为“优化串口大流量时导致程序卡死问题”，提交仍由既有钩子复核。证据文件原始空白告警和验证方法见DEVELOPMENT_LOG.md；本轮未打包、发布或新增人工/设备验收结论，下方未提交及未运行完整基线描述保留各轮当时状态。

最新统一图标（2026-11-13，源码版）：主窗口创建前设置稳定任务栏标识，根窗口创建后统一设置主窗口及 Tk 默认图标，子窗口/嵌套/重开自动继承。按负责人追加要求保留图案并提高边缘清晰度，常用尺寸改为原生32位DIB、补齐10种尺寸，避免旧全PNG压缩ICO在当前Tk回退通用文件图标。打包资源与一致性门禁已补齐，独立导出脚本不增加应用依赖；249项相关检查、8文件局部编译及153个源码编译清单覆盖检查通过。原生Windows独立进程已核对4个窗口8个大小图标与文件像素一致及任务栏标识回读，完整程序标题栏/Alt+Tab/任务栏目视因computer-use native pipe不可用仍待负责人确认；后续新包在目标电脑验证，见ACCEPTANCE_BASELINE.md §2.17/§3和`.claude/plans/application-icon.md`。本轮未运行完整基线，保留下方最近完整验证记录；未打包、提交、发布或操作设备，既有发布包未更新。

最新无响应修复（2026-11-13）：在main `0ed92f4`工作区修复串口订阅捕获UI、关闭后Tk引用及全流程后台读Tk/永久等待问题；数据端点、有界非阻塞显示邮箱、主线程变量释放、异步串口收尾、主线程快照、30秒排队失效及停止/退出取消均已接入。关闭完成配置窗口保留失败通道续跑，已准入子任务未收尾不允许新批次，退出轮询真实线程结束再销毁Tk。新增24项行为回归；最终完整基线连续两次ALL CHECKS PASSED：1919项测试、196项指定回归、152个源码编译/覆盖，最后一次86.735秒。独立Windows/Python3.9.10模拟8路100块/秒约256字节持续600秒、100轮窗口/标签GC压力通过，478933条日志8/8完整，1105次Tk变量析构均在主线程，心跳最大0.359秒；8路1000块/秒过载保持有界及原始日志完整。详细差异、数据摘要、失败过程和限制见[无响应修复报告](UNRESPONSIVE_FIX_REPORT.md)；§2.3/§3保留完整Windows人工、真实多串口/长时间及便携版待验收，具体现场StringVar归属/析构触发仍未确认。保留同期ONU/说明/测试隔离修改及用户配置，本轮不打包、不提交、不运行交付EXE或操作设备。

最新界面说明精简（2026-11-13）：按指定截图移除ONU注册三处说明、批量删除确认顶部整块红字，以及DUT顶部和WAN/双频WiFi规则说明；仅隐藏窗口内目标勾选变化时的WAN提醒，保留缓存清理、查询进度/结果/错误、完整删除名单和默认取消，参数/命令/业务流程保持。492项相关测试、2项Vista/Clam独立真实Tk检查及5文件局部编译通过，新增1项WAN空提示缓存清理回归。computer-use的native pipe不可用，完整Windows源码版目视及鼠标键盘复验仍待负责人完成，见ACCEPTANCE_BASELINE.md §2.10/§2.13/§3。未运行完整基线，保留最近一次完整验证记录；未提交、打包、发布或操作真实设备，文件及验证方法见DEVELOPMENT_LOG.md。

最新ONU管理（2026-11-13）：已注册管理支持C300/C600当前PON原生多选和逐台删除；全选/取消全选已按负责人要求移至查询按钮右侧同排，列表行距收紧、仅有结果时显示状态行。默认不选、完整可滚动名单统一确认且默认取消、逐台独立身份复核/no onu/回读；目标失败记录后继续，通信故障或停止结束，未验证结果标记待核实，最终保留逐台结果并要求重新查询。连接/PON变化清空旧名单，无write及全流程自动删除，注册失败清理仍限单台。518项相关测试和11文件局部编译通过，3个ONU新模块已登记；全仓清单检查当时被同期其它功能6个未登记模块拦截，详见DEVELOPMENT_LOG.md。本轮未运行完整基线、提交、打包、发布或操作真实OLT；完整Windows界面与真实C300/C600批量路径待负责人复验，见ACCEPTANCE_BASELINE.md §2.10/§3和`.claude/plans/registered-onu-batch-delete.md`。

最新提交前完整验证（2026-11-13，优化ai功能）：按负责人本地提交并推送GitHub的要求，使用仓库配置的CPython 3.9.10 x64运行标准提交检查入口；完整`verify_baseline.py`报告1857项测试、190项指定关键回归实际执行、142个源码编译/覆盖及全部协议不变量通过，`ALL CHECKS PASSED`。保留现有35个已暂存文件的范围，提交备注为“优化ai功能”，提交时仍由既有钩子复核；本轮验证方法及差异格式提示见DEVELOPMENT_LOG.md。未打包或发布，Windows完整源码版人工复验及真实模型/设备验收边界保持。下方未运行完整基线/未提交描述为各轮当时记录，此前完整验证记录继续保留。

最新DUT日志显示（2026-11-13）：主界面收起明确格式的WiFi原始UBUS回包、WiFi/双频Radio状态、WAN完整信息及语音/TR069完整状态，本次主日志文件完整保存DUT原文，参数仍在DUT窗口查看。实际TX/登录/注销、配置返回结果、关键阶段、成功/跳过/重试/失败和未知格式保持可见；AI显示/原文落盘、开关机WiFi摘要及设备流程保持。46项相关检查通过（日志专项44项，含8项新增DUT回归及Vista/Clam独立真实Tk显示/颜色/落盘；队列和原颜色回归2项），3个Python文件编译与本轮差异检查通过。完整Windows源码版人工目视复核见ACCEPTANCE_BASELINE.md §2.13/§3；文件和方法见DEVELOPMENT_LOG.md及`.claude/plans/dut-main-log-summary.md`。本轮未运行完整基线，保留此前2026-11-13完整1795项验证记录；未提交、打包、发布或操作真实设备，现有交付包不含本轮调整。

最新AI回复排版（2026-11-13）：独立UI模块为新旧AI回复及确认问题显示标题、重点、列表、引用和浅底代码；选中复制可见正文，长路径软折行，代码缩进/空格/空行保留。用户输入、数据库原文、模型上下文、日志、权限和设备流程保持。50项相关检查通过，含Vista/Clam最小窗口、实际剪贴板、会话管理及模拟提问/回答；5个Python文件编译、142个源码的编译清单覆盖和差异检查通过。文件及验证方法见DEVELOPMENT_LOG.md和`.claude/plans/ai-chat-markdown.md`；完整Windows源码版人工复验按ACCEPTANCE_BASELINE.md §2.16/§3待负责人完成。本轮未运行完整基线，保留此前完整验证记录；现有交付包未包含本轮调整。

最新源码日志显示（2026-11-13）：主界面AI日志精简为关键过程与结果，常规模型请求/Token/容量/审查开始隐藏，采集状态与操作JSON使用摘要，实际命令、权限、异常及恢复提示保留；主日志文件继续完整保存经现有模型密钥过滤的AI原文。WiFi等其它日志规则不变。38项相关检查通过，包含Vista/Clam独立真实Tk显示/颜色及完整落盘验证；完整Windows源码版人工目视复核见ACCEPTANCE_BASELINE.md §2.16/§3，文件和方法见DEVELOPMENT_LOG.md及`.claude/plans/ai-main-log-summary.md`。本轮未运行完整基线，保留既有完整验证记录；未提交、打包、发布或操作真实设备。

最新AI源码功能（2026-11-13）：查看待确认操作右侧增加请求批准/帮我批准/完全访问，默认及重授权以2026-11-15权限规则为准并记住偏好。请求批准逐项确认通用操作；帮我批准沿用独立风险审查；完全访问经程序校验授权后跳过独立审查并自动执行，已有目标/占用/文件/停止保护保持。授权仅在内存绑定会话/目标/模型/批次，停止/变化/重启失效，本地/飞书有效会话初始化或下一次发送时可重新校验授权，旧操作不重放；运行、待批准或清理期间禁止切换。自动监控保持关闭默认值及启用范围确认；验证及文件见DEVELOPMENT_LOG.md和`.claude/plans/ai-permission-modes.md`，Windows人工/真实模型/DUT按ACCEPTANCE_BASELINE.md §2.16/§3待负责人复验。本轮未提交、打包或发布，既有完整基线记录保留如下。

最新源码显示与完整验证（2026-11-13，恢复通道列表行距）：保留13号微软雅黑及原文字尺寸，恢复原疏松行距（本机30像素），选中行保持平面原底色。仅替换左侧列表显示组件及入口装配，原业务回调、勾选、配置和设备流程保持。30项相关专项通过，包含新旧控件交互对照、Vista/Clam选中/失焦/重新聚焦实际像素及1200×780、1040×700布局检查；完整`verify_baseline.py`报告1795项测试、190项指定回归、138个源码编译/覆盖及协议不变量全部通过，`ALL CHECKS PASSED`。文件、验证方法和回退入口见DEVELOPMENT_LOG.md及`.claude/plans/channel-list-flat-spacing.md`。本轮未提交、打包或发布；完整Windows源码版人工复验见ACCEPTANCE_BASELINE.md §2.1/§3，原真实设备验收结论保持。此前完整验证记录保留如下。

最新提交前完整验证（2026-11-12，优化通道字号）：1777项测试通过（2项既有可选检查跳过）、190项指定回归实际执行、137个源码编译/覆盖及全部协议不变量通过，`ALL CHECKS PASSED`。提交门禁定位通道字号放大后最小窗口右侧原生勾选框超出6像素，已仅收紧同行三处横向留白；16项相关专项及Vista/Clam两主题1200×780、1040×700独立Tk复验通过，保留输入框宽度、默认值、持久化和设备执行语义。文件及诊断证据见DEVELOPMENT_LOG.md；现有24文件暂存内容以“优化通道字号”备注提交。未打包或发布，Windows完整程序、真实模型/设备验收边界保持，下方未运行完整基线/未提交描述为各轮当时记录。

最新AI输入调整（2026-11-12）：排障工作台Enter发送、Alt+Enter换行并可替换选区，保留Ctrl+Enter及发送按钮；复用原发送/回答入口，失败保留草稿。新增7项真实Tk键盘专项，26项AI界面专项及两个Python文件编译、差异格式和文档一致性检查通过；详见DEVELOPMENT_LOG.md。未运行完整基线，保留此前1758项完整验证记录；未提交、打包或发布，现有V1.2.9包不含本轮修改。Windows完整程序键盘交互按ACCEPTANCE_BASELINE.md §2.16/§3待负责人复验，既有模型/设备验收边界保持。

最新源码调整（2026-11-12）：全流程仅保留三项并移除无人值守选项；原四项独立功能保留。窗口专项、编排器及关联验证与文件清单见DEVELOPMENT_LOG.md。未运行完整基线，保留此前1758项完整验证记录；未打包、提交或发布，现有V1.2.9交付包不含此改动。Windows完整主程序和真实样机复验见ACCEPTANCE_BASELINE.md §2.12/§3。

最新源码显示调整（2026-11-13）：按负责人确认取消会话状态行的鼠标悬停提示，删除弹框、鼠标事件绑定及相关定时任务；“新会话”右侧继续单行显示最新状态及时分秒，字体、颜色、长文本省略及自动更新保持。原始记录、固定上下文区及聊天正文独立刷新保持。25项聊天显示/快捷键专项通过，包含Vista/Clam主题悬停450毫秒无弹框、无新增悬停任务及输入焦点保持；两个Python文件编译和差异检查通过，文件及验证方法见DEVELOPMENT_LOG.md。本轮未运行完整基线，保留2026-11-12最近1777项完整验证记录；未提交、打包或发布，现有V1.2.9发布包不包含本轮改动。完整Windows人工及真实模型/设备仍按ACCEPTANCE_BASELINE.md §2.16/§3待复验。

最新构建与发布（2026-11-12）：[LineCheckAssistant V1.2.9](https://github.com/oscarouxue-coder/Power_OnOff_Assistant/releases/tag/v1.2.9)已公开并设为Latest，仅上传同次构建的完整ZIP及ZIP SHA256。纳入AI排障工作台、监控/报告接手、会话/上下文和工具操作优化及Telnet百分号密码读取修复。标准独立CPython3.9.10 x64/锁定依赖/PyInstaller5.10.1入口构建`Cheating_machine_execution_tool/dist/V1.2.9_slim_20261112/`；完整基线1758项测试、190项指定回归、136个源码编译/覆盖及协议不变量通过，EXE/PYZ/Tcl/Tk/排除项/ZIP/哈希门禁及133个冻结模块（30个AI模块）、6份脱敏配置一致性通过。EXE 18,141,673字节、ZIP 17,828,213字节，完整摘要及回执见DEVELOPMENT_LOG.md。两个附件匿名完整下载及真实源码更新客户端通过后已删除旧V1.2.8 Release及附件，最终只保留V1.2.9，原Git标签/源码历史保持；新标签指向现有远端main，本轮未自动提交/推送版本与发布记录。本机未运行新EXE；目标Windows启动、完整交互及真实模型/设备按ACCEPTANCE_BASELINE.md §2.15/§2.16/§3待负责人复验。下方为此前实现、提交和验证记录。

最新提交验证（2026-11-12）：负责人要求本地提交`优化ai能力2`，纳入当前AI优化、Git环境适配及Telnet密码原文读取修复等29个代码/测试/文档文件；本机`config.ini`、`network_card_ip.ini`、`test_project_config.ini`留在工作区。提交前实际`git hook run pre-commit`返回0、ALL CHECKS PASSED：1758项测试、190项指定回归实际执行、136个源码编译/覆盖及全部协议不变量通过，暂存差异格式检查通过；实际提交继续受同一钩子门禁约束，不绕过检查，仅本地提交、不推送。详情及提交范围见DEVELOPMENT_LOG.md最新条目；下方完整验证结果保留为历史记录，真实设备验收边界保持。

最新开发环境优化（2026-11-12）：Git提交入口自动识别CPython3.9.10 x64，支持各电脑不同路径及本仓库`linecheck.pythonExecutable`覆盖；安装脚本增加`-PythonExecutable`，验证后仅写本机Git配置，无参数保留原值。自动查找跳过Store占位/错误版本，显式配置失效或基线失败均阻止提交且不切环境重试；不自动安装Python/依赖。入口仅在子进程内处理UTF-8及TMPDIR/TEMP/TMP短路径。本机已配置复用已有`.venv_serial_upgrade`，无需修改全局Python或激活环境；跨电脑配置、故障处理及手动入口见根README“跨电脑配置Git提交检查”，文件/失败定位/验证证据见DEVELOPMENT_LOG.md及`.claude/plans/git-hook-python-discovery.md`。保留原暂存内容，未打包、提交、发布或扩展真实设备验收结论；下方较早“本轮未运行完整基线”等描述为历史记录，最新结果以本段及下条为准。

此前完整基线验证（2026-11-12，跨电脑Git入口验收）：实际执行`git hook run pre-commit`，返回0、ALL CHECKS PASSED；1754项测试、190项指定回归实际执行、136个源码编译/覆盖及全部协议不变量通过。21项新增提交环境专项纳入全量运行；首次实际Git环境暴露短路径TMPDIR优先于TEMP/TMP，已在入口补全规范化，保留原业务与测试断言。未创建提交或运行交付EXE。旧完整记录保留如下。

最新源码功能（2026-11-12）：对话排障与诊断与监控已合并为“排障工作台”，保留模型接入/已确认案例。聊天为唯一人工发送入口，监控与报告使用独立非模态窗口；新报告只提示，人工继续排查后才创建绑定报告目标/批次的新会话，等待发送，不自动采集。新报告目标快照、旧报告明确关联、历史批次限制、报告刷新不抢选/阅读位置以及案例来源ID固定已接通。监控范围独立于聊天目标，停止范围、既有执行锁/队列/清理及两类工具权限保持。新增18项工作台专项；实际验证和文件见DEVELOPMENT_LOG.md及.claude/plans/ai-diagnostic-workspace.md。本轮未运行完整基线，保留最近1715项完整验证记录；完整Windows人工、真实模型和样机继续按ACCEPTANCE_BASELINE.md §2.16/§3待复验。未打包、提交或发布。下方旧标签页名称为历史实现记录，当前入口以本段为准。

最新上下文显示精简（2026-11-12）：固定区合并为“上下文容量：1,048,576 Token ｜ 当前上下文用量：5,749（0.55%）”一行，保留进度条并允许窄窗口自动换行；来源、预留/余量说明、输入输出明细与时间隐藏。用量仍为最近一次请求输入加输出，不累加历次请求、不计算草稿，估算加“约”，请求前显示预计输入；未知容量无占比，原异常/过期/待更新状态保持。42项相关专项及4个Python文件编译通过，独立Tk覆盖Vista/Clam、940×660完整窗口、窄窗口换行、会话切换与正文阅读位置/选区；完整Windows人工和真实模型/样机待验收状态保持。文件及验证方法见DEVELOPMENT_LOG.md；未运行完整基线，保留下方最近1715项完整验证记录，未打包、提交或发布。下方较早上下文双行详显描述为此前实现记录，当前展示以本段为准。

最新源码显示调整（2026-11-12）：按负责人要求移除对话排障的批次/通道/模型/采集状态及真实信息发送说明双行提示，删除对应标签与空会话新建提示，不留占位空白。固定上下文用量区、会话列表、聊天正文和操作按钮保留，采集资格、权限确认及主日志规则保持。相关检查与文件清单见DEVELOPMENT_LOG.md；本轮未运行完整基线，保留最近完整验证记录，未打包、提交或发布。完整Windows人工及真实模型/样机验收状态保持。

此前完整基线验证（2026-11-12，本机启动配置提交前）：ALL CHECKS PASSED，1715项测试（2项既有可选检查跳过）、190项指定回归实际执行、134个源码编译/覆盖及协议不变量通过。本机临时目录短路径可能导致PowerShell工作目录文本断言失败，验证/提交进程中将TEMP/TMP解析为完整路径，保留系统设置及原测试不变；失败排查和最终证据见DEVELOPMENT_LOG.md。本轮不扩展真实模型、Windows人工交互或真实DUT验收结论。

最新源码功能（2026-11-12）：按负责人确认，有效对话会话默认开放本机PowerShell/文件读写、当前样机自定义命令及只读串口诊断。独立AI风险审查后普通操作自动执行，首次设备登录、危险或未知操作由操作员批准具体内容；动作/授权指纹及状态持久化，停止/配置变化/新批次/重启不延续待执行授权。Windows Job Object清理本次进程树，设备命令已下发不自动重试或切通道重发，通用操作不自动回滚；风险判断不构成沙箱隔离。自动监控和单次诊断仍保持原工具边界。串口PnP/驱动/内部所有者及原始错误可供AI读取，外部占用者无证据为未知。本轮验证和文件清单见DEVELOPMENT_LOG.md及.claude/plans/ai-full-access.md；真实模型、完整Windows人工与真实样机仍按ACCEPTANCE_BASELINE.md §2.16/§3待负责人复验。未提交、打包或发布，保留既有完整基线记录。

最新源码显示与用量功能（2026-11-12）：对话排障新增固定上下文区，展示容量/来源、最近请求输入输出/合计、估算或接口来源、时间、占比和进度；仅发送/工具交互/回复刷新，不计算草稿。请求前复用完整预算，回复后两协议有效usage优先，否则输入/新增回复均按UTF-8字节保守估算；不累计多次请求，输出预留与5%余量不计入已用，容量未知不显示占比。会话JSON兼容保存最近快照和有界的上一有效用量，失败/取消保留数据并标状态，异常重启修正请求中状态；配置变化后过期，旧会话待下次发送更新。普通容量提示不再入聊天，旧系统容量提示仅隐藏，原始数据及裁剪/失败警告保留；用量独立刷新不重绘正文，最小窗口保留输入/操作区空间。新增15项专项，219项AI测试通过，7个相关源码/测试/门禁文件编译及129个源码编译清单覆盖、差异检查通过；独立Tk验证两主题940×660完整窗口、会话切换、选区/阅读位置和按钮可见。首次最小窗口检查定位底部按钮被正文挤占，已在本轮修正并复验。本轮未运行完整基线，保留此前1634项等完整记录；真实厂商usage语义及完整Windows人工复验见ACCEPTANCE_BASELINE.md §2.16/§3。文件见DEVELOPMENT_LOG.md和.claude/plans/ai-context-status.md；保留已有改动，未打包、发布或提交。

最新源码修改（2026-11-12）：对话排障新旧及重启恢复的有效会话默认允许原有连续查询/有界采集，移除“授权本次会话”“结束授权”及确认框，保留停止本轮；打开会话不发起采集，自动监控仍默认关闭。service统一实时核对批次、目标及模型身份/工具验证，不保存授权标记；旧批次/失效目标只分析材料，模型身份变更需新建，新批次/退出取消旧采集并清理。每次模型请求及超限重试明确当前工具清单、状态/原因和剩余额度，纠正历史“没有工具”的能力判断；主日志显示默认启用/受限原因、真实信息范围及接收方；原对话状态栏已按本日后续显示调整移除。新增6项专项并调整原授权/删除测试，204项AI测试通过，7个相关源码/测试文件编译、差异检查及vista/Clam 940×660独立Tk按钮/布局检查通过；主/后台实时目标查询均验证。本轮未运行完整基线，保留此前1634项等完整验证记录。真实模型调用效果、完整Windows人工及真实DUT按ACCEPTANCE_BASELINE.md §2.16/§3待负责人复验；修改文件见DEVELOPMENT_LOG.md与.claude/plans/ai-chat-default-collection.md。保留已有工作区修改，未打包、发布或提交。

最新源码功能（2026-11-12）：AI对话按模型容量管理上下文，模型接入新增“上下文上限 Token（留空自动）”及来源显示；手填优先，其次按API地址/模型缓存的接口容量，无缓存首次发送自动尝试读取。已知容量不设固定轮数/字符上限，每次请求按完整出站材料UTF-8字节保守估算Token，预留最大输出及5%余量；未知且未填使用最近50轮/100000序列化字符，单条消息仍限32768字符。按完整旧组裁剪，保留当前问题/本轮工具链；服务明确超限时减半旧历史、每条消息最多两次模型请求重试，不重复设备工具。旧配置/会话兼容，容量调整下一轮生效且不改变模型指纹或授权。新增23项专项，198项AI测试通过，9个相关文件编译及127个源码的编译清单覆盖检查通过，独立Tk vista/Clam 940×660布局/保存重载检查通过；本轮未运行完整基线，保留下方此前完整验证记录。真实API、Windows人工及DUT仍按ACCEPTANCE_BASELINE.md §2.16/§3待负责人复验；文件清单见DEVELOPMENT_LOG.md与.claude/plans/ai-model-context-budget.md，保留已有工作区修改，未打包、发布或提交。

开发验证规则更新（2026-11-12）：日常修改默认只做相关检查，纯文档不运行代码测试；完整基线仅在负责人明确要求、提交代码前、标准打包（含 `-CheckOnly`）或已验收功能结构调整时执行。局部行为或显示修改不因涉及已验收功能自动触发完整基线，原复验要求保留。相关检查失败先定位并补充直接相关验证，不自动转为完整基线。本轮仅调整规则文档，未运行完整基线，以下完整验证结果保留为此前记录；执行入口见本页“运行、验证与交接规则”，明细见 DEVELOPMENT_LOG.md。

最新源码优化（2026-11-12）：对话提示词区分普通问答和故障排查；身份/模型/术语等简单问题默认1～3句话，不机械重复目标参数、权限/工具状态、旧故障或邀请，未知简短说明；排障保留必要证据和步骤，要求详细时展开。恢复状态及正式报告格式、授权/工具边界保持。新增3项回归，175项AI专项及完整基线ALL CHECKS PASSED（1634项测试、190项指定回归、126个源码编译/覆盖）。重启源码版后新旧会话后续消息均使用新提示词，真实模型效果按ACCEPTANCE_BASELINE.md §2.16/§3待负责人复验；文件与验证见DEVELOPMENT_LOG.md本轮记录。保留已有工作区改动，未打包、发布或提交。

最新源码功能（2026-11-12）：对话排障新增“管理会话”，支持Ctrl/Shift多选、全选、删除选中及清空点击时列表；永久删除前默认取消确认。选中会话含排查/排队/清理任务时整批拒绝，停止后仍需等待后台结束；单事务删除四张会话表，成功才清除授权，失败回滚。原始日志/导入/抓包文件、报告、案例、模型配置、共享批次证据和恢复记录保留；删除后即时刷新，当前会话删除时清空输入并切换最新剩余会话，全空清除正文并恢复未选会话的上下文区，原新建提示已按本日后续显示调整移除。新增20项专项，172项AI测试通过，完整基线ALL CHECKS PASSED（1631项测试、190项指定回归、126个源码编译/覆盖）；独立Tk的vista/Clam最小窗口检查通过。负责人Windows人工复验列入ACCEPTANCE_BASELINE.md §2.16/§3，文件清单与验证见DEVELOPMENT_LOG.md本轮记录；保留既有对话显示改动，未打包、发布或提交。

最新源码显示优化（2026-11-11）：对话排障的消息标题、会话列表及证据时间显示为`YYYY-MM-DD HH:mm:ss`；用户深蓝/浅蓝、AI深青绿/浅青绿、状态灰、人工问题橙、错误红，配合加粗标题、微软雅黑UI字号及留白/行距区分消息。只调整局部显示，原始时间/正文、协议和存储接口保持；刷新保留历史阅读位置与选区，底部跟随新消息。新增8项显示/独立Tk专项、152项AI专项通过，完整基线ALL CHECKS PASSED（1611项测试、190项指定回归、125个源码编译/覆盖）；文件与验证见DEVELOPMENT_LOG.md本轮记录。完整Windows目视复验按ACCEPTANCE_BASELINE.md §2.16/§3待负责人确认，未打包、发布或提交。

最新源码功能（2026-11-11）：AI诊断新增默认“对话排障”页，支持持续追问/纠正、主动提问并等待人工反馈、一次会话授权后的连续查询/深入采集、文本日志导入、证据查看/检索及本地会话恢复。挂测开始即旁路留存批次/通道事件和准确日志路径，晚打开可关联已有故障；区分故障记录与当前查询。新增路由/地址/ARP/无线状态及源IP/接口限定Ping，资源忙不抢占，目标/模型变更和新批次/重启不沿用授权；原挂测、监控、报告与案例保持。新增42项专项，144项AI测试纳入完整基线ALL CHECKS PASSED（1603项测试、190项指定回归、125个源码编译/覆盖；2项既有可选浏览器检查跳过）；文件与验证见DEVELOPMENT_LOG.md。真实API、完整Windows交互及真实DUT按ACCEPTANCE_BASELINE.md §2.16/§3待负责人复验；未打包、发布或提交。

本机源码运行环境（2026-11-11）：已安装当前用户CPython3.9.10 x64（未修改系统PATH），在仓库根`.venv_serial_upgrade/`按`requirements-build.txt`安装锁定依赖；`.vscode/launch.json`的`LineCheckAssistant`配置显式使用该环境，选择后按F5启动。终端从仓库根运行`.\.venv_serial_upgrade\Scripts\python.exe .\Cheating_machine_execution_tool\run_line_check_assistant.py`，不要依赖WindowsApps的`python`占位程序。环境不纳入Git，换电脑需重新创建。源码入口真实Tk启动检查及完整基线ALL CHECKS PASSED（1561项测试、190项指定回归、120个源码编译/覆盖），不扩展真实设备验收结论；详情见DEVELOPMENT_LOG.md。

最新源码修改（2026-11-11）：按负责人确认，AI诊断全部保留真实网络/设备信息及材料中的账号、密码和令牌，覆盖发送、回复、本地报告及确认案例；仅已登记的模型服务API密钥继续过滤且只用于请求认证。现有监控确认提示及主执行日志写明真实信息范围和接收方，AI登录日志显示实际用户名/密码，提示词区分同子网、默认路由和已验证可达。旧报告占位符无法自动还原，重启源码程序后重新采集。102项AI专项及完整基线ALL CHECKS PASSED（1561项测试、190项指定回归、120个源码编译/覆盖）；文件清单见DEVELOPMENT_LOG.md。§2.16/§3仍待负责人复验，未打包、发布或提交。

最新源码修复（2026-11-10）：AI诊断PC命令输出优先识别UTF-8/BOM并兼容Windows OEM/ANSI代码页，解码后截断并记录编码/返回码/坏字节；本地证据按工具和命令显示实际换行，保留失败、尾部日志、路径及旧报告原文，不修改存储或猜测恢复旧乱码。新增18项回归，96项AI专项及完整基线ALL CHECKS PASSED（1555项测试、190项指定回归、120个源码编译/覆盖）；本机只读验证ipconfig/route为CP936、netsh为UTF-8，三者中文标签正常且无替代字符；用户附件离线重放及真实Tk报告显示/只读/存储不变通过。重启源码程序后重新采集生效，旧报告乱码需重采。完整Windows/API/DUT验收仍按ACCEPTANCE_BASELINE.md §2.16/§3待负责人确认；未打包或提交，文件与验证方法见DEVELOPMENT_LOG.md本轮记录。

最新源码功能与界面统一（2026-11-10）：新增“AI诊断”入口，支持DeepSeek、MiniMax、OpenAI及自定义服务、多账号配置、模型手填/列表刷新、样例连接与工具能力检查、DPAPI凭据、单机报告与人工确认案例。默认关闭本次监控，最终失败或同阶段连续三次异常触发，第四次允许深入；Telnet优先、目标串口回退，共享串口打印可随时被动读取，禁止AI触发DUT重启/上下电/升级/恢复出厂。AI、写样机参数、串口日志、DUT配置及检查更新共用测试项配置浅蓝灰背景，局部派生样式不改变按钮/状态色与勾选语义；新增模块规则已同步AGENTS及开发skill。新增78项离线/真实Tk控件专项及最终完整基线ALL CHECKS PASSED（1537项测试、190项指定回归、119个源码编译/覆盖）；本仓库基线提交钩子已启用。新增云端API及真实DUT路径、完整Windows交互仍待负责人按ACCEPTANCE_BASELINE.md §2.16/§3复验；未读取用户API密钥或调用真实厂商API，未操作设备、不构建、不发布、不提交，既有现场验收结论不扩展。

最新交付（2026-11-09）：[V1.2.8便携包](https://github.com/oscarouxue-coder/Power_OnOff_Assistant/releases/tag/v1.2.8)已公开并设为GitHub Latest，当前仅保留此Release及同次构建的完整ZIP、ZIP SHA256两个附件。纳入近期WiFi摘要/本次日志定位/失败历史/扫描及Ping连接核验重试、ONU查询提速与模板保留、Telnet旧探测移除及凭据置灰；版本说明见包内VERSION_INFO.txt。本地完整产物`Cheating_machine_execution_tool/dist/V1.2.8_slim_20261109/`，EXE 18,133,639字节、ZIP 17,816,828字节。标准独立CPython3.9.10 x64/锁定依赖/PyInstaller5.10.1构建和完整基线ALL CHECKS PASSED（1459项测试、190项关键回归、105个源码编译/覆盖），实际EXE/PYZ、Tcl/Tk四布局、排除项、ZIP CRC/哈希、119个冻结模块及6份脱敏配置核验通过，9份本机配置哈希未变。两个附件GitHub大小/摘要与匿名完整下载一致，匿名源码更新客户端确认V1.2.7发现V1.2.8、同版无更新，并实际下载校验ZIP成功；随后删除V1.2.7 Release及附件，保留标签和源码历史。未在本机运行新EXE、操作设备或自动提交/推送；目标电脑及近期Telnet/ONU/WiFi现场复验仍按ACCEPTANCE_BASELINE.md §2.10/§2.11/§2.12/§2.15/§3待负责人确认。详细证据与文件清单见DEVELOPMENT_LOG.md本轮记录；下方较早交付段落为历史快照，当前以本段为准。

最新源码修改（2026-11-09）：取消Telnet页“是否需要输入密码”及旧客户端额外回车探测；旧INI为1也不生效，加载不写盘，保存兼容键固定0，模型字段及位置参数保留。仅保留“免用户名密码登录”“仅执行上下电”两个是/否下拉，任一为是即禁用用户名/密码输入，两项全否恢复编辑，初始化/重载同步且不清空凭据，免认证失败回退等其它登录/上下电行为保持。新增10项回归，261项界面/配置/旧登录专项及完整基线ALL CHECKS PASSED（1459项测试、190项指定关键回归、105个源码编译/覆盖）；旧客户端单独编译通过。vista/Clam隔离真实Tk四种组合的置灰/恢复、保存重开、凭据保留、只读候选和布局检查通过，Computer Use窗口枚举仍报native pipe不可用，可见交互及真实设备登录待负责人按ACCEPTANCE_BASELINE.md §2.11/§3复验。文件与验证见DEVELOPMENT_LOG.md和.claude/plans/remove-telnet-password-probe.md；6份本机INI及原WiFi修改哈希保持，未打包、操作设备或提交。

最新源码修改（2026-11-09）：Ping阶段连接核验失败纳入每频段原有4次尝试（首次+最多3次重试），扫描/连接/Ping共用次数。等待无线IP、Ping中及末次复核的掉线、身份、频率/频段、认证/加密异常，清理确认后等10秒重新完整测试，不累计旧回复；FIFO、停止及清理失败边界保持。Ping全部无回复和DNS/IP/socket环境异常仍直接结束。三处摘要及历史保留具体原因、次数，恢复只在最终清理确认后记录。新增14项回归并替换1项指定关键测试，116项专项和完整基线ALL CHECKS PASSED（1449项测试、190项指定关键回归、105个源码编译/覆盖）。实现与文件清单见DEVELOPMENT_LOG.md及.claude/plans/wifi-ping-guard-retry.md；新增行为待负责人按ACCEPTANCE_BASELINE.md §2.12/§3复验Windows源码版及真实样机，本轮不升级现场验收结论。未操作真实WiFi、打包或提交，原有配置和未提交修改保留。

最新源码修复（2026-11-09）：“打开本次WiFi连接日志”改为按当前测试批次、通道和执行/续跑尝试定位已成功刷新的准确文件；尚未生成时提示，不再扫描并误开历史文件。无当前批次、未参与通道、文件删除/移动及打开失败分别提示，完成/停止后仍可查看本次文件。新增11项回归，260项日志/续跑/界面专项及完整基线ALL CHECKS PASSED（1432项测试、190项指定关键回归、105个源码编译/覆盖）；vista/Clam隔离真实Tk菜单和后台写入/主线程回调检查通过，提示框与Windows打开调用为拦截验证。Computer Use重试和重置后native pipe不可用，可见鼠标键盘交互仍待负责人复核，见ACCEPTANCE_BASELINE.md §2.12/§3。原连接、重试、停止、设备命令和结果判定保持，本机6份INI哈希未变；未打包、运行EXE或提交。文件清单与验证见DEVELOPMENT_LOG.md和.claude/plans/wifi-current-log.md。

最新源码优化（2026-11-08）：已注册ONU查询改为C300全局状态加按PON批量身份、C600定义列表加按PON批量状态；精确关联并保留原顺序，拒绝时逐台兼容、缺项仅补查，停止/断线/超时直接结束。仅该入口使用独立完整提示符会话，修复C600配置块`>`导致提前返回空列表，公共Telnet文件及注册/删除/write路径保持。新增28项回归，完整基线ALL CHECKS PASSED（1421项测试、190项指定回归、105个源码编译/覆盖）。真实OLT只读比对C300 14台4.562秒降至1.594～1.641秒，C600当前38台10.047秒降至1.891～1.953秒，三次结果全部字段和顺序一致；两组逐台对照均使用同一完整提示符会话。临时配置下真实Tk控件、线程/回调、取消和单选检查通过；Computer Use native pipe不可用，可见鼠标键盘交互和负责人现场复验仍待确认，见ACCEPTANCE_BASELINE.md §2.10/§3。详细记录与入口见DEVELOPMENT_LOG.md、.claude/plans/onu-registered-query-speed.md；未改本机INI、不打包、不提交。

最新源码修复（2026-11-08）：C600“ONU 类型模板”保留手填或下拉选择的现有值，仅去除首尾空白后为空时才带入发现型号；切换或全选ONU不再覆盖TZW-99等模板。复用现有400毫秒自动保存、关闭即时保存和启动加载，INI格式及默认值保持。新增7项回归，218项界面/配置专项及完整基线ALL CHECKS PASSED（1393项测试、190项指定关键回归、104个源码编译/覆盖）。临时配置下真实Tk源码窗口的自动保存、快速关闭重开和独立进程重启检查通过；Windows窗口工具native pipe不可用，可见显示和鼠标键盘交互仍待负责人复验，见ACCEPTANCE_BASELINE.md §2.10/§3。本轮不打包、不发布、不提交，详细记录见DEVELOPMENT_LOG.md。

最新源码修复（2026-11-08）：正式Telnet开关机WiFi重试、最终失败及重试后成功现已进入通道“重试/失败历史”。独立service在原始IPC过滤前提取实际轮次、频段、已知尝试次数、具体原因和错误码；原因与等待按尝试合并，最终失败待非取消的通道结果确认后只记一次，通道失败摘要显示WiFi具体原因。仅最终频段通过事件可记恢复，清理失败/停止不误记成功；续跑保留历史并重置解析、沿用旧消息过滤。新增16项回归及原21项WiFi专项通过，完整基线ALL CHECKS PASSED（1386项测试、190项指定关键回归、104个源码编译/覆盖），6份本机INI哈希保持。详见DEVELOPMENT_LOG.md及.claude/plans/wifi-retry-failure-history.md；Windows窗口实时刷新和真实样机异常/续跑待负责人复验，见ACCEPTANCE_BASELINE.md §2.12/§3。本轮未操作真实WiFi、启动完整主程序、打包或提交。

最新源码修复（2026-11-07）：正式Telnet开关机WiFi及失败续跑在临时连接断开后查询真实接口状态，按0.2秒轮询、连续断开0.5秒、最多5秒确认，确认期间保留FIFO使用权；清理未确认不进入下一频段，也不提前显示通过。扫描失败区分API/异步通知/超时并保留原因码，暂态异常共用原4次/20秒/10秒重试预算，权限/接口/服务及其它未分类API错误立即结束，Ping不重连。停止取消确认及后续动作。新增25项回归，49项连接/Native WLAN专项及17项日志专项通过，完整基线ALL CHECKS PASSED（1370项测试、190项指定关键回归、103个源码编译/覆盖），详见DEVELOPMENT_LOG.md。Test5G1CBA真实恢复、Windows交互和原扫描失败具体原因仍待负责人复核，见ACCEPTANCE_BASELINE.md §2.12/§3；本轮不打包、不操作真实WiFi、不提交，既有摘要和本机配置保留。

最新源码优化（2026-11-07）：正式Telnet开关机测试和失败续跑的主界面、主日志及独立WiFi文件统一使用关键摘要，保留首次双频SSID/明文密码、实际竞争排队与等待、带尝试编号的连接下发、最终连接/Ping合并结果、重试原因和异常；正常查询/扫描/DNS/逐包/清理细节不再落盘。原始IPC仍供历史、进度和结果判断使用，连接/判据/停止/续跑保持。6份既有WiFi日志4779条离线重放生成457条摘要（减少90.4%），三处一致、原文件和配置哈希不变。日志专项31项通过，完整基线ALL CHECKS PASSED（1345项测试、190项指定关键回归、103个源码编译/覆盖），详细结果见DEVELOPMENT_LOG.md；Windows实际显示及真实设备复核仍待确认，见ACCEPTANCE_BASELINE.md §2.12/§3。本轮仅改源码，不打包、不操作设备、不提交。以下2026-11-05/06的完整WiFi过程保存说明是历史快照，当前以本条共用摘要为准。

最新源码功能（2026-11-06）：正式Telnet开关机WiFi日志按通道和执行尝试，独立保存到当前程序`Auto_power_on_off_tool/test_results/device_N/device_N_wifi_微秒时间戳[_resume_尝试编号].log`，首次WiFi消息才创建、排他创建避免覆盖、逐条刷新并在退出时关闭；保存主界面精简前的完整过程及明文SSID/密码。文件故障仅告警一次，设备测试继续；左侧通道列表右键新增“打开本次WiFi连接日志”，定位当前通道最新WiFi文件（含续跑/正在写入），原命令日志入口保持原样。新增23项回归，310项专项及完整基线ALL CHECKS PASSED（1341项测试、190项指定关键回归、102个源码编译/覆盖）；真实无GUI适配器使用假设备，关联打开使用mock。用户日志离线重放521条WiFi消息分别写入通道1/2/7的225/236/60行，明文密码和完整内容保留，详细结果见DEVELOPMENT_LOG.md。Windows实际菜单/关联打开、真实设备及停止/续跑落盘待负责人复核，见ACCEPTANCE_BASELINE.md §2.12/§3。本轮保留上一轮日志精简及本机配置，不迁移历史日志、不打包、不提交、不操作设备。

最新源码优化（2026-11-05）：正式开关机测试及失败续跑的WiFi主界面日志改为摘要，保留首次双频SSID/明文密码、排队及实际等待、连接下发/核验、Ping汇总、重试原因和异常，过程细节继续按原文保存到主日志文件；DUT配置查询保持原样。仅在独立显示模块及主程序日志入口接入，不改连接、判据、停止、续跑或配置。离线重放负责人752行日志：WiFi显示由521行减至135行（减少74.1%），原文752行完整落盘，DNS 9005、4条扫描重试、16条Ping汇总及3条明文凭据摘要均保留。新增13项测试、61项专项和完整基线ALL CHECKS PASSED（1318项测试、190项指定关键回归、101个源码编译/覆盖），详细结果见DEVELOPMENT_LOG.md。Windows日常主界面复核待确认，验收边界见ACCEPTANCE_BASELINE.md §2.12/§3；本轮不打包、不提交、不操作设备。

最新交付（2026-11-05）：[V1.2.7精简便携包](https://github.com/oscarouxue-coder/Power_OnOff_Assistant/releases/tag/v1.2.7)已公开并设为GitHub Latest，当前仅保留此Release，附件仅为同次构建的`LineCheckAssistant_portable.zip`和`LineCheckAssistant_portable.zip.sha256.txt`。包含串口标签单独关闭及全流程串口日志目录同步；本地完整产物位于`Cheating_machine_execution_tool/dist/V1.2.7_slim_20261105/`，EXE 18,114,638字节（17.28MiB），ZIP 17,797,434字节（16.97MiB）。标准独立CPython3.9.10 x64/锁定依赖/PyInstaller5.10.1入口及完整基线ALL CHECKS PASSED（1305项测试、190项指定关键回归、100个源码编译/覆盖）；实际EXE/PYZ、Tcl/Tk、排除项、ZIP CRC/哈希、100个冻结模块与源码及6份脱敏配置核验通过，9份本机配置哈希保持。两个附件GitHub大小/摘要及匿名完整下载校验通过，匿名源码更新客户端确认V1.2.6发现新版、V1.2.7无更新，并实际下载ZIP校验成功；随后删除V1.2.6 Release及附件，保留Git标签和源码历史。未运行新EXE、操作设备或自动提交/推送源码；目标电脑启动、完整交互及串口/WiFi等原待验收项仍待负责人确认，见ACCEPTANCE_BASELINE.md §2.3/§2.15/§3和DEVELOPMENT_LOG.md本轮记录。下方较早“最新交付”等段落为历史快照，以本段为当前交付状态。

最新功能（2026-11-05）：串口日志每个标签右侧增加“×”，单击关闭指定监控及标签，日志保留、其它串口继续工作；未打开/已停止标签可移除，最后标签关闭后窗口保留，可从主入口恢复标签再打开全部。自动升级占用时禁止关闭并提示原因；按独立订阅身份隔离关闭后迟到事件，共用COM只释放本标签监控所有权，主执行日志记录请求/成功/跳过/失败。新增14项回归，33项串口专项及完整基线ALL CHECKS PASSED（1305项测试、190项指定关键回归、100个源码编译/覆盖）；独立Windows Tk默认/Clam主题交互和模拟串口日志落盘通过，日常完整主程序及真实串口待负责人确认。已有目录同步改动保留，本轮不打包、不运行EXE、不提交；文件清单与验证见DEVELOPMENT_LOG.md，验收边界见ACCEPTANCE_BASELINE.md §2.3/§3。

最新修复（2026-11-05）：全流程第6项串口日志目录改为读取串口窗口当前值；首次打开串口窗口前读取有效历史目录，选择新目录后立即刷新已打开且未运行的全流程窗口，执行确认框展示同一目录。取消/失败保持原值，已打开监控不迁移文件或重启。新增10项回归，301项专项及完整基线通过（1291项测试、190项指定关键回归、99个源码编译/覆盖）；已完成Windows源码隔离Tk两窗口交互验证，负责人日常操作复核待确认，既有真实样机验收结论保持。本轮不构建、不运行EXE、不提交，详见DEVELOPMENT_LOG.md和ACCEPTANCE_BASELINE.md §2.3/§3。

后续发布约定（2026-11-05，下一次构建/发布开始执行）：GitHub只上传同次构建的`LineCheckAssistant_portable.zip`及`LineCheckAssistant_portable.zip.sha256.txt`；构建脚本完成提示已区分本地产物和这两个上传路径。本地完整EXE、便携目录、说明/声明、校验文件、构建报告及全部门禁保持，更新客户端与接口不变。先草稿上传并核对大小/SHA256，再设为Latest、匿名完整下载校验并验证源码更新客户端，最后删除旧Release及附件；保留Git标签和源码历史。后续公开说明只提供完整ZIP及ZIP校验文件的下载指引。PowerShell语法及输出预览通过，74项打包/更新专项和完整基线ALL CHECKS PASSED（1281项测试、190项指定关键回归、99个源码编译/覆盖），本机配置和现有V1.2.6交付物哈希不变。此次仅调整脚本提示及发布规范，不重新构建，不改线上V1.2.6六份附件或历史发布记录，不自动提交源码；详细结果见DEVELOPMENT_LOG.md本轮记录。

最新交付（2026-11-05）：[V1.2.6精简便携包](https://github.com/oscarouxue-coder/Power_OnOff_Assistant/releases/tag/v1.2.6)已公开发布并设为GitHub Latest；输出`Cheating_machine_execution_tool/dist/V1.2.6_slim_20261105/`，EXE 18,110,748字节（17.27MiB），ZIP 17,793,176字节（16.97MiB）。包含显示全部网卡/串口、WiFi分别验证频段/双频合一、自动认证、可选无线Ping和通道空白点击修复。标准独立CPython3.9.10 x64/锁定依赖/PyInstaller5.10.1完整基线ALL CHECKS PASSED（1281项测试、190项指定关键回归、99个源码编译/覆盖）；实际EXE/PYZ、Tcl/Tk、排除项、ZIP CRC及哈希通过，99个相关冻结模块与源码一致，6份脱敏配置一致，本机配置未变。六份附件GitHub大小/摘要及匿名完整下载哈希通过，匿名源码更新客户端确认V1.2.5可发现新版、V1.2.6无更新；核验后删除旧V1.2.5 Release及附件，最终仅V1.2.6，保留Git标签和源码历史。未运行新EXE或自动提交/推送源码；目标电脑启动、完整界面及本轮WiFi/无线Ping真实设备复验仍待负责人确认，见ACCEPTANCE_BASELINE.md §2.15/§3及DEVELOPMENT_LOG.md本轮记录。

最新源码优化（2026-11-05）：正式Telnet开关机WiFi增加“分别验证频段 / 双频合一”选择、默认自动认证及高级手动设置；按只读Mapping和样机BSSID识别目标，Native WLAN临时连接不保存或清理用户profile，核对实际身份/频率/认证并连续稳定2秒。可选无线Ping默认关闭，支持IPv4/域名；指定无线接口DNS及源IPv4/出口接口，4包至少1回复通过，连接变化覆盖已有回复。保留FIFO、取消、失败续跑、电源和有线Ping；完整基线ALL CHECKS PASSED（1281项测试、190项指定关键回归、99个源码编译/覆盖；新增53项专项）。已纳入V1.2.6，Windows完整界面、真实双频/多通道及DNS/ICMP无线抓包待负责人复验，详见ACCEPTANCE_BASELINE.md §2.11/§2.12/§3及DEVELOPMENT_LOG.md本轮记录。

最新功能验收（2026-11-04）：负责人确认“显示所有网卡和串口”及勾选框位于样机管理IP输入框右侧的布局实际验证通过，本轮显示与选择功能已确认验收，见ACCEPTANCE_BASELINE.md §2.1和DEVELOPMENT_LOG.md。开关启动默认关闭；开启后网卡列展示全部识别网卡，两处COM列展示本机实际识别的全部串口，关闭恢复原分组且保留选择。实现时11项新增专项及完整基线ALL CHECKS PASSED（1228项测试、180项指定关键回归、92个源码编译/覆盖），1040/1200/1600像素窗口源码Tk布局通过。此次仅同步负责人验收结果，不增加设备执行或EXE交付验收范围；未打包、提交或改动本机配置。

最新源码修复（2026-10-30）：左侧通道列表空白处单击或双击不再选择末行或切换启用状态；有效行及空格键保持原操作。完整基线 ALL CHECKS PASSED（1217项测试、180项指定关键回归、91个源码编译/覆盖）；独立Tk列表鼠标事件验证通过，完整Windows源码界面复验待负责人确认，见 ACCEPTANCE_BASELINE.md §2.1。本轮未打包。

最新交付（2026-10-30）：[V1.2.5精简便携包](https://github.com/oscarouxue-coder/Power_OnOff_Assistant/releases/tag/v1.2.5)已公开发布并设为GitHub Latest；输出`Cheating_machine_execution_tool/dist/V1.2.5_slim_20261030/`，EXE 18,078,211字节（17.24MiB），ZIP 17,760,701字节（16.94MiB）。包含项目名称工具栏显示与正式Telnet测试WiFi排队/停止/续跑优化。标准独立环境及完整基线ALL CHECKS PASSED（1215项测试、180项指定关键回归、91个源码编译/覆盖）；实际EXE/PYZ相关8个模块与源码编译结果一致，Tcl/Tk、排除项、ZIP CRC、6份脱敏配置和哈希通过，本机配置未变。六份附件GitHub大小/摘要及匿名完整下载哈希核验通过，匿名源码更新客户端确认V1.2.4可发现V1.2.5、V1.2.5无更新；完成核验后删除旧V1.2.4 Release及附件，最终只保留V1.2.5，Git标签和源码历史保留。未运行新EXE或自动提交/推送源码；目标电脑启动、完整UI及真实WiFi复验仍待负责人确认，见ACCEPTANCE_BASELINE.md §2.11/§2.12/§3。

最新界面修改与验证（2026-10-30）：工具栏显示“项目信息”已保存的项目名称，不添加“当前项目：”前缀；浅蓝底深蓝加粗、超长省略及悬停完整值。启动/打开配置/重新加载/保存后刷新，保存部分失败回读磁盘；空值或缺文件显示“未设置”，读取异常显示“读取失败”。完整基线ALL CHECKS PASSED（1215项测试、180项指定关键回归、91个源码编译/覆盖）；54项专项通过。源码Tk布局验证100%/125%字体缩放下1040/1200/1600宽度及150%下1200/1600宽度；150%下1040宽度的原DUT按钮压缩在修改前HEAD同样复现，保留为既有限制。负责人完整Windows源码界面复验仍待确认，见ACCEPTANCE_BASELINE.md §2.11/§3。仅源码与文档，不打包、不提交、不改本机配置，发布EXE未包含本次显示功能。

最新源码修改与验证（2026-10-30）：正式Telnet开关机测试WiFi按FIFO通道连续双频排队，排队/连接/重试及只读信息查询可停止；取消独立显示已停止、不推进轮次、不误记WiFi失败，失败续跑首次WiFi阶段重新取信息。主日志保留占用、动作、等待和结果；按负责人补充要求，每次执行/续跑首次读取后明文显示一次双频SSID与密码摘要。保持4次连接、每次约20秒、间隔10秒及原成功判据。完整基线ALL CHECKS PASSED（1204项测试、180项指定关键回归、90个源码编译/覆盖）；3个旧业务修改文件另行py_compile通过。本轮仅源码，已发布V1.2.4不含此改动；Windows源码版/真实双通道仍为已实现未验收，见ACCEPTANCE_BASELINE.md §2.12/§3和DEVELOPMENT_LOG.md本轮记录。保留已有发布工作区改动，不打包、不提交。

最新交付（2026-10-28）：[V1.2.4精简便携包](https://github.com/oscarouxue-coder/Power_OnOff_Assistant/releases/tag/v1.2.4)已公开发布并设为GitHub Latest。输出目录`Cheating_machine_execution_tool/dist/V1.2.4_slim_20261028/`，EXE 18,066,564字节（17.23MiB），ZIP 17,749,031字节（16.93MiB）。纳入正式开关机初始化仅断电已选通道；包内版本和BUILD_INFO说明已同步。标准独立环境、完整基线ALL CHECKS PASSED（1180项测试、173项指定关键回归、89个源码编译/覆盖）以及EXE/PYZ、Tcl/Tk、排除依赖、ZIP/哈希检查通过；实际冻结业务模块确认包含本次初始化行为。六份附件的GitHub大小/摘要和匿名完整下载哈希全部通过，真实匿名源码更新客户端确认V1.2.3发现新版、V1.2.4无更新；随后删除旧Release及附件，最终仅保留V1.2.4 Release，Git标签和源码历史保留。未运行新EXE，V1.2.4目标电脑启动和初始化断电的Windows/真实电源复验仍待负责人确认；未改本机配置或自动提交/推送源码。发布记录和文件清单见DEVELOPMENT_LOG.md本轮条目。

最新验证（2026-10-28）：初始化断电范围修改的149项专项通过；完整门禁ALL CHECKS PASSED（89个源码编译/覆盖、1180项测试、173项指定关键回归及协议不变量），相对上次1173项新增7项。模拟串口确认Telnet/SSH仅发送已选通道关闭帧、初始化先于测试线程、停止/异常阻止继续、续跑跳过初始化；确认框回归核对实际通道列表。本轮文件差异检查通过，原有两份本机INI哈希保持；Windows源码版及真实电源验收仍待负责人确认。

最新修改（2026-10-28）：正式开关机测试初始化仅断电本次已勾选通道，Telnet/SSH均由service逐个发送单通道关闭帧、每帧后等待0.5秒，全部下发完成后启动测试；取消原广播全通道断电，确认框列出实际通道，主日志记录目标、帧及下发完成/停止/失败。初始化中停止或异常不继续、不启动测试、不自动恢复电源；失败通道续跑仍跳过初始化。Windows源码版和真实电源复验待负责人确认，见ACCEPTANCE_BASELINE.md §2.12/§3；本轮仅源码与文档，不打包、不提交，现有本机配置保持。

最新交付（2026-10-17）：[V1.2.3 精简便携包](https://github.com/oscarouxue-coder/Power_OnOff_Assistant/releases/tag/v1.2.3)已替换同版本原大包并设为 GitHub Latest。来源为 `Cheating_machine_execution_tool/dist/V1.2.3_slim_20261017/`，EXE 18,065,376字节（17.23 MiB）、便携ZIP 17,747,305字节（16.93 MiB）；六份附件先以临时名称上传，逐份核对大小/摘要并匿名完整下载校验后，再删除旧附件并恢复固定下载名称，正式链接再次匿名下载核验通过。最终只保留现有V1.2.3 Release，标签和源码历史保留。版本号未变，已有V1.2.3用户需手动下载换包。只读归档/ZIP门禁和完整基线 `ALL CHECKS PASSED`（1173项测试）通过；负责人此前确认的精简包异机正常运行及其它真实设备验收边界保持。本轮未重新构建、运行EXE、修改本机配置或提交/推送源码。

最新打包标准（2026-10-17）：负责人已确认17.23MiB精简包在其它电脑可以正常运行，要求今后每次打包及其它电脑打开工程均按此方式执行。标准入口`Cheating_machine_execution_tool/build_line_check_assistant.ps1`自动准备独立CPython3.9.10 x64环境、安装/检查`requirements-build.txt`固定依赖及PyInstaller5.10.1，强制排除NumPy/OpenBLAS、lxml、PyQt5并禁用UPX；先完整基线再相对路径spec构建，保留实际EXE/PYZ、Tcl/Tk、ZIP和哈希检查。跨电脑执行步骤在根README，硬规则同步AGENTS与开发工作流。异机反馈只确认正常运行，各真实设备专项按原验收边界；没有发布GitHub或提交本轮源码。

跨电脑复现：安装Python3.9.10 x64并完整同步工程；在主源码目录运行`powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1`即可自动准备、校验及构建。推荐按根README用带时间的独立dist/build目录保留旧包。`-BasePython`支持显式Python路径，`-PythonExecutable`支持新的独立环境，`-CheckOnly`只验证不生成EXE；不得调用全局PyInstaller或单独跑spec来绕过标准流程。现有17.23MiB包位置仍为`dist/V1.2.3_slim_20261017/`，本轮未重新打包。

标准入口验证：新增3项环境/可迁移spec回归，专项10项通过；原工程及复制到C盘中文/空格目录的脱敏工程副本均以标准入口`-CheckOnly`通过完整门禁`ALL CHECKS PASSED`（89个源码编译/覆盖、1173项测试、173项指定关键回归及协议不变量）。副本使用全新独立环境，自动查找Python并准备锁定依赖；统一显式UTF-8，防止隔离进程忽略PYTHONUTF8造成GBK/UTF-8不一致。未重新构建或运行EXE，现有EXE/本机INI保持，业务代码未改；实际异机运行结论来自负责人反馈。

最新交付（2026-10-17）：[V1.2.3](https://github.com/oscarouxue-coder/Power_OnOff_Assistant/releases/tag/v1.2.3)已打包并设为GitHub Latest，包含开始前版本校验可选化及Python3.9启动兼容修复。六份附件大小/摘要与匿名完整下载哈希核验通过，源码更新客户端使用已认证真实元数据，以V1.2.2发现新版、V1.2.3不更新；真实便携ZIP匿名下载校验通过后，删除旧V1.2.2 Release及附件，最终仅保留V1.2.3，旧Git标签及源码历史保留。当前出口IP的GitHub匿名API实测HTTP403限流；Latest及版本比较采用已认证元数据，所有附件和源码客户端下载仍为匿名，未向下载/CDN发送凭据。默认dist根目录旧EXE正在运行，本次未结束旧进程，隔离输出为 `Cheating_machine_execution_tool/dist/V1.2.3_20261017/LineCheckAssistant.exe` 与同目录 `LineCheckAssistant_portable.zip`。完整门禁 `ALL CHECKS PASSED`（89个源码编译/覆盖、1168项测试、173项指定关键回归及协议不变量）；EXE/PYZ版本与新增逻辑、Tcl/Tk双布局、ZIP CRC、6份脱敏配置及本机INI未变核验通过。未在本机运行新EXE，目标电脑启动及新增行为Windows/真实样机复验仍待负责人确认；本轮未自动提交或推送源码。

最新功能（2026-10-17）：开关机开始前版本预检及失败通道续跑统一按当前选定方案已保存的三项版本基准判断：去除首尾空白后全空跳过预检、部分填写提示缺少字段并阻止启动、全填沿用严格校验。项目名称不参与判断；跳过时不建立预检连接或发送预检命令，确认摘要及主日志说明跳过；配置严格读取失败、指纹变化、停止及单通道隔离保护保持。新增13项回归，专项120项通过，完整门禁 ALL CHECKS PASSED（89个源码编译/覆盖、1168项测试、173项指定关键回归及协议不变量）。Windows源码版和真实样机新增范围待负责人复验，见 ACCEPTANCE_BASELINE.md §2.12/§3。本轮不打包、不运行EXE、不提交Git，保留已有本机配置与更新兼容性改动。

最新源码启动修复（2026-10-17）：检查更新模型移除Python3.9不支持的dataclass `slots=True`，保留三个数据类的只读约束、字段和默认值。新增1项兼容性回归，更新专项40项及完整门禁 `ALL CHECKS PASSED`（89个源码编译/覆盖、1155项测试、173项指定关键回归及协议不变量）。现有3.9.10虚拟环境已通过主程序导入及真实源码入口/Tk初始化、事件处理和销毁检查；使用临时配置/日志并模拟枚举与权限警告，不构成负责人完整Windows/设备验收。未构建或运行EXE，现有发布包不含本轮源码修复；正常配置下完整交互仍由负责人复验。该虚拟环境另缺xlrd，仅在使用.xls读取前需按requirements.txt补齐。

最新交付（2026-10-16）：[V1.2.2](https://github.com/oscarouxue-coder/Power_OnOff_Assistant/releases/tag/v1.2.2)已打包并设为GitHub Latest，包含网卡命名提示/确认改名、2–254及“非网关地址”提示；EXE、完整脱敏便携ZIP及各自SHA256等六份附件核验通过。新版匿名检查/下载/取消和源码Tk更新窗口联调通过后，已删除旧V1.2.1 Release及附件，当前Release数量为1，Git标签和源码历史保留。每次发布只保留新版及精简公开说明的规则已写入AGENTS.md及开发工作流。本地输出`Cheating_machine_execution_tool/dist/LineCheckAssistant.exe`与`dist/LineCheckAssistant_portable.zip`；未在本机运行新EXE，目标电脑启动和新增网卡真实改名仍待负责人确认。

本轮发布验证：完整门禁`ALL CHECKS PASSED`（89个源码编译/覆盖、1154项测试、173项指定关键回归及协议不变量）；Tk测试循环引用已在主线程释放，消除本轮遇到的异步析构异常。静态EXE/PYZ确认版本、新增改名模块及2–254/非网关提示，双布局Tcl/Tk资源、ZIP CRC、6份脱敏配置、包内外EXE与GitHub摘要一致。公开发布说明不含内部测试数量、源码基准/工作区状态及现场验收声明；内部详情见开发日志。本轮未自动提交或推送源码，保留现有本机INI改动。

最新功能（2026-10-16）：选择非数字结尾网卡时恢复原选择并提供可选重命名；接受后输入名称、确认修改 Windows 网卡，提示及校验范围为2–254，并提示“非网关地址”（仅选址提示，不自动查询/配置网关）。管理员/设备任务空闲检查、后台单次执行、InterfaceGuid回读、超时核实、通道引用/目标预览同步和保存失败提示已实现。既有通道筛选、勾选、只保存启用通道及IP规则保持，改名时保留已有显式或有效历史映射COM。新增范围待负责人完成完整Windows源码版及空闲测试网卡真实改名验收，见 `ACCEPTANCE_BASELINE.md §2.1/§3`；本轮不打包、不运行EXE、不提交Git。

最新网卡改名验证（2026-10-16）：新增44项回归通过，含3项独立Windows Tk模态/居中/后台响应测试；统一门禁 `ALL CHECKS PASSED`（89个源码编译/覆盖、1154项测试、173项指定关键回归及协议不变量）。沙箱内已有Tk测试因无法读取本机`init.tcl`失败，沙箱外同一完整门禁通过，未跳过这些测试。系统改名全部模拟，未在本机实际修改网卡，不构成负责人真实验收；文件清单与复验步骤见开发日志本轮条目。

最新交付与验证（2026-10-16）：V1.2.1已重新打包至 `Cheating_machine_execution_tool/dist/` 并发布 [GitHub Release v1.2.1](https://github.com/oscarouxue-coder/Power_OnOff_Assistant/releases/tag/v1.2.1)，设为Latest；含EXE、完整脱敏便携ZIP和各自SHA256。包内版本、更新模块、Tcl/Tk双布局资源、6份脱敏配置、ZIP完整性及本地/远端哈希检查通过。当前PyInstaller 6.21.0所需`_tcl_data/_tk_data`已补齐，并保留旧`tcl/tk`；未在当前电脑运行新EXE。

检查更新真实联调（2026-10-16）：匿名客户端以V1.1.4发现v1.2.1，V1.2.1/更高版本不提供更新；真实下载取消可清理临时文件。独立源码Tk更新窗口成功检查、显示下载选择、下载公开ZIP并通过SHA256/ZIP/包内版本/EXE哈希比对，V1.2.1显示已是最新版。完整基线 `ALL CHECKS PASSED`（85个源码编译/覆盖、1110项测试、173项指定关键回归及协议不变量）。发布EXE的目标电脑启动、完整主程序交互及负责人现场验收仍待确认（§2.15）。发布标签指向已有c8836c2提交，未修改远端main；本轮版本与打包修正保留在工作区，未自动提交。

最新修复与验证（2026-10-15）：新版预备测试/测试项执行和项目信息查询仅在成功提示符严格为 `>` 时等待新连接历史中的用户名提示，不先发回车，避免 CMS 空用户名错位；`#` 等其它路径、共享 transport 及登录后命令规则保持。新增7项回归，完整门禁 `ALL CHECKS PASSED`（81个源码编译/覆盖、1044项测试、173项指定回归及协议不变量通过）。绑定 VLAN122（192.168.1.122 → 192.168.1.1）实连两个源码登录入口，均收到 `>` 并在发送 `sh` 后观察到 `#`，无 `Login incorrect`；仅为单台 service 诊断证据，Windows UI、完整业务和其它样机待负责人确认，见 `ACCEPTANCE_BASELINE.md §2.11/§3`。未打包，现有 EXE 不含本次修复。

最新完整验证（2026-10-14）：升级停止新增35项回归，统一门禁 `ALL CHECKS PASSED`（81个源码编译/覆盖、1037项测试、173项指定回归及协议不变量通过）；原升级/页面/Web/主界面/全流程专项344项通过（2项浏览器集成默认跳过）。未启动完整应用或操作真实设备，新增功能待Windows源码版和真实样机验收。

最新功能（2026-10-14）：样机升级新增“停止升级”，覆盖页面升级及三种全包升级，直接请求安全停止并与全流程停止双向联动；排队跳过，已开始传输/电源组合安全收尾，停止后不再发起重试、reset、后备上下电或恢复出厂。批次隔离、关闭重开与四类结果统计已补回归。Windows源码版与真实样机新增范围待负责人确认，详见操作员说明与 `ACCEPTANCE_BASELINE.md §2.6.2/§3`。

最新交付（2026-10-13）：V1.1.4已打包至 `Cheating_machine_execution_tool/dist/V1.1.4_20261013/`，包含单文件EXE和完整便携ZIP。因默认dist根目录旧EXE正在运行，未覆盖或结束旧程序；最新包请使用版本目录。包内版本说明、Tcl/Tk资源、最新ONU模块、ZIP/6份脱敏配置及哈希检查通过；完整基线1002项通过。未启动新EXE，目标电脑启动与真实业务验收仍待负责人确认，详见本轮开发记录。

最新界面调整（2026-10-13）：ONU确认执行页已移除顶部目标下拉框和预览目标数/命令数/已校验状态行；单台直接显示命令，多台在同一只读预览内按执行顺序分段标明SN/PON/ONU ID，分段标题不下发。预览/衔接24项及完整1002项基线通过，完整Windows界面仍待负责人目视复验。

最新完整验证（2026-10-13）：C600 VLAN转换及只读预览本轮净增24项（新增30项、替换原17项编辑组件测试为11项只读测试）；ONU专项145项通过，统一门禁 `ALL CHECKS PASSED`（79个源码编译/覆盖、1002项测试、173项指定回归及协议不变量通过）。独立真实Tk组件验证只读状态、文本选择和编辑入口移除；未运行完整应用或操作设备，新增范围待Windows源码版及真实OLT/终端复验。

最新功能（2026-10-13）：测试项配置 Telnet 页补齐“登录后命令”映射，缺键默认 `sh`，保存保留自定义值与空值；新版预执行、执行及版本查询（含开关机/续跑版本预检）仅在成功提示符为 `>` 时发送一次，空值仍回车，发送后等待 1 秒。确认摘要与主日志列明下发行为，预执行等待可停止；旧客户端时序保持。Windows 源码版及真实样机新增范围待负责人复验，详见操作员说明与 `ACCEPTANCE_BASELINE.md §2.11/§2.12/§2.14/§3`。

最新完整验证（2026-10-13）：登录后命令新增39项回归，统一门禁 `ALL CHECKS PASSED`（79个源码编译/覆盖、978项测试、173项指定回归及协议不变量通过）；配置专项25项、共享步骤及三条运行路径专项54项、UI映射/手动确认7项、确认摘要10项通过。独立原生Tk Telnet页构造、字段采集/回填和原生Checkbutton检查通过；未启动完整应用或操作设备，不替代Windows可见界面及真实样机验收。

最新修正（2026-10-12）：开关机测试收到已选通道的明确正常轮次结果后，小卡恢复绿色“正常”（如 `3/5 正常`），满轮次成功显示“已完成”；下一轮和续跑开始恢复运行态，失败历史保留，重复/旧轮次日志不覆盖新异常或最终失败。源码及模拟UI状态回归通过，Windows源码版和真实样机颜色转换待负责人复验，详见 `ACCEPTANCE_BASELINE.md §2.12`。

最新功能（2026-10-13）：C600业务映射支持 `ServiceID,ONU侧VLAN,网络侧VLAN`，兼容旧两列；普通数据及语音335/IPTV600/TR06950均支持一对一转换，资源按网络侧VLAN分层。确认执行页改为逐目标只读预览，移除编辑/校验/恢复入口；确认快照、批量预检、停止/首错和独立write授权保持。新增范围待Windows源码版与真实OLT/终端验收，详见操作员说明与 `ACCEPTANCE_BASELINE.md §2.10/§3`。

最新功能（2026-10-12）：失败通道支持在“通道概览”右键从失败轮次继续，3/5保留3轮并从第4轮执行；支持其它通道运行期间和整次结束后恢复。沿用原配置、目标通道版本预检、确认后仅对该通道上下电，恢复不触发全通道断电；保留失败历史和原全流程结论，停止覆盖续跑。Windows源码版和真实样机路径待负责人复验，详见操作员说明及 `ACCEPTANCE_BASELINE.md §2.12`。

最新修正（2026-10-12）：“重试/失败历史”补充旧工具 Telnet 连接失败等待重连、完整命令执行异常（含 WinError 10054）与 Ping error 信号；按已选通道和当前轮次在主日志去重前记录原文，不改变通道状态或最终判定。代码与专项回归通过，Windows 源码版历史窗口及真实样机异常路径待负责人复验，详见 `ACCEPTANCE_BASELINE.md §2.12` 和本轮开发记录。

最新完整验证（2026-10-12）：正常轮次颜色恢复新增12项回归，统一门禁 `ALL CHECKS PASSED`（77个源码编译、939项测试、173项指定回归及协议不变量通过）；旧业务适配专项27项、通道UI状态专项6项、续跑专项17项通过。自动化不替代Windows界面或真实样机验收。

最新修正（2026-10-12）：正式钉钉通知与手动试发统一使用 `test_project_config.ini [project_info] project_name` 的磁盘已保存值，每次发送重新读取；完成/异常通知标题与正文不再使用旧项目名或固定名称。项目名为空或读取失败时跳过发送并提示。自动推送时机及试发页面凭据语义保持；真实钉钉收信与 Windows 源码版复验待负责人确认。

最新功能（2026-10-11）：测试项配置新增第六页（2026-11-14 更名为“远程管理”），编辑 `config.ini [dingtalk_config]` 四项当前值，接入统一保存、重载和未保存提醒；新增“发送测试消息”按钮，使用页面快照后台单次试发并显示结果，不改变自动发送流程。Windows可见界面、保存重开及真实钉钉收信待负责人确认，既有验收范围不变。

最新变更：2026-09-20修复Web启动超时：SDMC不再将启动日志`## Checking hash(es)`当作Boot提示，浏览器打开前同VLAN出口最长90秒只读确认升级表单，兼容无HTTP头HTML并细分超时日志。VLAN148已只读确认Software update页面及文件框；实际固件升级、多通道及Windows可见界面仍待负责人复验（§2.6.1）。点击提交后固定30秒和原收尾不变。

更新：2026-09-20（补全Web网关升级；既有验收结论保留原范围）。

最新发布构建：2026-09-20，V1.1.3；输出位于主源码目录 `dist/LineCheckAssistant.exe` 和 `dist/LineCheckAssistant_portable.zip`。构建、Tcl/Tk归档、ZIP与哈希核验通过；重新运行统一门禁通过（820项测试，2项浏览器集成测试默认跳过）。未在当前电脑运行新EXE，现场启动及新增业务验收待确认，详见开发日志同日构建记录。

## 项目目标与当前状态

“openWRT老化测试环境搭建助手”（内部工程和发布文件仍使用 `LineCheckAssistant` 标识）是 Windows Tkinter 桌面工具，用于测试环境线路检查、程控电源、串口日志、样机升级、批量写样机参数、ONU 注册、测试项配置和开关机测试。

| 能力 | 当前状态 |
| --- | --- |
| AI诊断与案例库 | 已实现未验收：统一排障工作台、独立监控/报告窗口及报告接手、多厂商、持续对话/主动提问与反馈、证据检索、本机/样机完整工具、独立风险审查及具体操作批准、串口状态诊断、限定出口检查、选择性监控、真实信息报告和人工确认案例；已登记模型服务API密钥过滤，通用执行不构成沙箱隔离。入口为常用工具“AI诊断”，验证和限制见§2.16及开发日志 |
| 主程序检查更新与下载 | 已实现未验收：手动检查GitHub正式版、程序内下载完整便携ZIP、进度/取消、SHA256及打开目录；不自动替换或迁移配置。当前只保留V1.2.10 Release（2026-11-13），ZIP及ZIP SHA256两个附件匿名下载核验和V1.2.9→V1.2.10源码更新检查/实际下载通过；既有下载/取消与源码Tk更新窗口证据保持，发布EXE启动及负责人完整主程序操作待确认，详见§2.15 |
| 样机升级安全停止 | 已实现未验收（2026-10-14）：四种方式安全停止、全流程双向联动、停止/跳过独立统计及线程资源收尾；Windows源码版及真实样机待负责人复验，详见§2.6.2 |
| 全包升级 `web打开网关` | 已实现未验收：独立Edge/Chrome会话，按通道源IP和VLAN接口访问主界面管理IP，自动选文件、单次点击提交、固定30秒后接原90秒观察及恢复出厂选项；兼容两种Boot方式、1–8台并行和全流程入口。本机无头浏览器模拟页已验证1.4MB文件完整提交且网页不变时不重复点击；Windows可见窗口、真实多NIC及样机端到端待验收（§2.6.1） |
| 测试项单次预备测试 | 项目负责人于2026-09-10确认本次功能验收通过：当前测试项页一键执行、每条一次不重试、主日志打印/保存及成功绿色/失败红色。支持未保存页面快照、逐通道执行与停止；多通道隔离、停止、无期望及断连等专项仍待单独现场结果。正式测试重试配置与全流程调度不变（§2.14） |
| Windows免安装发布 | 构建脚本同时生成单文件EXE、完整`dist/LineCheckAssistant_portable/`和可搬运的`dist/LineCheckAssistant_portable.zip`；便携包包含EXE、6个脱敏INI、说明、第三方声明和SHA256。构建时不复制本机凭据、设备/源IP、ONU ID、文件路径或网卡/COM绑定，业务命令模板与C600业务映射保留。首版在目标电脑暴露的`pyi_rth__tkinter`找不到`_MEI/tcl`问题已修复为PyInstaller 5.10.1要求的`tcl/tk`目录，并增加EXE归档强制门禁；2026-08-18项目负责人确认修复包在另一台Windows电脑完整解压后可正常启动使用。此结论只覆盖便携发布与启动，不替代各真实设备业务入口的独立验收 |
| 通道 / 网卡配置、线路 Ping、内置多 VLAN 串口终端 | 通道 / 网卡配置、线路 Ping、程控电源COM与VLAN分组筛选和空COM全网卡展示均已真实样机验收；主界面“通道对应 COM口”按`COM101 → COM1–COM8`、`COM102 → COM9–COM16`分组，保存到`network_card_ip.ini`，写参、全包升级、手动/全流程串口日志和升级附加日志优先使用实际选择，旧配置回退VLAN映射。项目负责人已于2026-08-13确认通道COM选择及串口日志实际选择联动验收通过；串口 Enter 发送已真实样机验收；2026-08-29确认3路以上高频WiFi日志滚动时按钮持续可操作，日志文件名和逐行时间戳符合预期；2026-08-30确认线路 Ping 在网卡已满足时不重复启用/设静态 IP，不满足时按需修复后正常 Ping ；2026-11-05新增串口标签“×”单独关闭，自动升级占用禁止关闭，日志与其它监控保留；14项新增回归及完整基线通过，新增交互与真实串口复验待负责人确认 |
| 程控电源直连（COM101–COM116） | 自动上/下电、同批次 COM 长连接复用、1–8 台并行、空 COM 手动重启确认后继续且不下发电源指令均已真实样机验收 |
| 全包升级 `Tftp指令`、`Tftp Put` | 2026-09-20新增“进入 Boot 方式”：默认账号密码，SDMC每秒发送命令加回车且跳过Boot凭据；配置/确认/两种传输接入已实现，新增范围待Windows及真实样机验收。 两条独立链路的既有两台受控并行均已真实样机验收；样机升级窗口现已移除“串行/并行”执行方式，只保留并行数（1–8，默认2），两条全包链路都固定按该上限完成即补位；本次窗口/调度改动已通过自动化测试，待Windows源码版按需复验。进入 boot 的升级专用上下电仍为断电后 1 秒、上电后 1 秒；2026-08-31两条链路均调整为上电帧后仅稳定 1 秒便开始串口循环回车，不再等待 10 秒或叠加第二个 1 秒。两条链路传输后未观察到 Boot/Bood 时均对当前通道执行后备下电再上电；未勾选恢复出厂时，完成 reset 或后备动作后只等待 3 秒即结束该通道，不再登录最终系统；勾选恢复出厂时才保留 120 秒等待、最终登录和恢复出厂。最终登录现只接受独立 shell 提示符行，错误密码回显中的 `#` / `>` 不会被误判成功或触发恢复出厂。此新增收尾与登录判据行为待 Windows 源码版及真实样机复验。固定 `192.168.1.<VLAN尾号> → 192.168.1.1` 与 4 / 8 台并行边界按原范围确认 |
| 页面升级（UBUS 批量 + 可选恢复出厂） | 网卡准备状态预检复用已真实验收；勾选“恢复出厂”时，实际命令、重启和主执行日志均已现场确认 |
| 批量写样机参数、随机参数表 | 1台与6台独立VLAN telnet路径已真实样机验收；生成窗口首帧刷新以及MAC前6位自定义/后6位随机唯一、普通SN纯数字且总长不超过16位、XPON SN固定12位规则均于2026-08-13通过现场验收；2026-08-30确认用户/工厂模式网卡状态预检复用正常；2/8台端点并行按现场需要补验收 |
| ZTE OLT ONU 注册 | C300/C600已合并到主界面同一入口和统一业务service，窗口默认和最小尺寸均为`1000x900`，按“查询ONU→配置业务→确认执行→已注册管理”四步组织；未注册列表可多选，整批先完成只读ID/SN/PON预检，再按预览顺序逐台注册、最长60秒可停止上线轮询和回读。逐台手填ID按目标保留，同PON重复手填ID拒绝，未单独填写的ID按PON独立分配且本批不重复；C300批量禁用离线ONU清理重试，批量不自动`write`。C600支持两/三列VLAN映射及335/600/50转换，按网络侧分层并配套目标VPort组播转换；确认页改为逐ONU只读预览，生成快照用于执行与回读。新增范围待Windows源码版和真实OLT验收。已注册管理新增当前PON多选逐台删除，目标失败继续、通信故障/停止结束，无write，新增批量删除待Windows与真实OLT复验。全流程会等待注册批次最终结果。单台现场验收结论保持原范围；2026-09-06确认本次C600两台手填3/4与确认执行ID一致的修复验收通过；其余C300/C600多台路径及全流程端到端仍待验收 |
| DUT 配置（UBUS） | 已确认：六Tab布局、连续查询/session注销、网卡按需复用、完整WAN配置、单台2.4G WiFi连续配置/回读及2.4G动态能力下拉；2026-08-29确认独立目标选择、“全选/清除”、SSID递增和双频区域显隐；2026-08-30确认主界面同时选择`vlan112/vlan113`、DUT窗口仅选`vlan112`时，查询与配置绝不访问`vlan113`。其余多台递增统一等待及逐台回读、双频下发/回读、5G、语音/TR069、停止和失败隔离仍按基线范围验收 |
| 主界面布局 | 内容区已删除重复的应用名称与说明，仅保留 Windows 标题栏；“执行日志”标题下的提示行已删除；管理员权限状态位于常用工具栏右侧、“刷新串口”左边。左侧通道列表保持配置、勾选和右键只读打开当前通道`test_results/device_N`中按文件名时间戳最新的开关机结果日志；开关机测试的独立轮次、运行/重试/失败/完成状态改在右侧测试卡可折叠“通道概览”显示，点击小卡可看详情，关注行只列落后或异常通道，总进度继续取最慢通道。该新增交互已通过代码/单元测试，待Windows源码版确认。2026-08-29确认主界面和已打开的二级窗口可互相点击升到前台；必要模态确认继续保持阻塞 |
| 测试项配置编辑器 | 已完成五个Tab、唯一指令重试间隔、旧工具运行参数和WiFi八项映射；“项目信息”页现可使用当前通道与Telnet页参数完成登录后查询 `software_version`、`inner_sw_version` 和 `/proc/version` 编译时间，查询值以可复制的独立只读文本框显示，不覆写或保存到原有三项手动输入框；开关机测试及失败通道续跑按当前方案已保存的三项基准决定预检：全空跳过、部分填写拦截、全填时对相应通道逐项核对，全部一致才执行。固定模板恢复已验收。2026-08-29确认20ms快速刷新带来的加载提速体感，以及第五页仅四项运行参数并可保存、关闭重开恢复；2026-08-30确认`telnet_default_on=1/0`保存后的旧配置镜像/旧工具复选框反向关系、WiFi八项加载/保存、无线网卡刷新及开关机测试真实连接；登录后命令配置和版本预检待Windows源码版及真实样机验证 |
| 全流程执行 | 2026-11-12源码精简为环境线路检查、串口日志、执行开关机测试三项，编号1～3且默认全不勾选；移除四项入口及本次无人值守，四项独立功能和编排器兼容能力保留。串口预启动、环境检查致命失败、串口非致命失败、危险确认、主界面停止/进度保持。原2026-08-29七项窗口交互验收作为历史记录；本轮三项布局、主题、尺寸恢复及真实样机三项端到端待负责人复验，见ACCEPTANCE_BASELINE.md §2.12/§3 |

- C300 ONU 注册现提供机框/槽位/PON筛选和参数化配置：实际仍执行全局未注册查询、在本地筛选目标PON；可编辑 ONU ID、类型模板、T-CONT/DBA及六项ServiceID/VLAN，Service ID派生同号GEM/VPort，配置页同时标明上网/TR069/语音/IPTV分类。当前查询结果可批量勾选，以每个PON独立的非重复ID生成批次；所有目标先预检再逐台执行。默认六业务、显式源IP、危险删除默认关闭和独立write确认不变；批量清理与批量`write`均不支持。2026-08-25已在`gpon-onu_1/2/1:3 / GPONA62D6F48`完成默认SD-41六业务注册及完整回读（第8次working，6条service-port OK/YES，未write且ONU保留在线）；2026-08-30追加确认参数化组合、ID/SN冲突拦截、显式单台删除、`no onu`命令格式和`write`均通过现场验收；多台批量路径未包含在这些现场结论中。
- 2026-08-30项目负责人确认：C300/C600 Windows专项、C600停止/`Access denied`/按PON查询/冲突预检，以及ONU终端语音VLAN335、TR069 VLAN50 DHCP地址和IPTV VLAN600节目均已验收；该结论仅覆盖本次列明的型号、业务与异常路径。
- 2026-09-03新增代码与自动化覆盖：C300/C600 的ONU类型模板、DBA带宽模板均可只读查询并以下拉项“模板名（PON类型值/速率值）”展示，且不显示“PON类型：”“速率：”标签，手动输入仍保留；项目负责人已确认该两类模板查询显示验收通过。机框、槽位、PON全为0时查询整台OLT未注册ONU；现场只读确认两种模板查询命令与输出格式，未注册整机查询仍待单独验收，不以自动化或只读命令验证替代。
- DUT WAN完整快照查询/表单回填、多台一致性判断、IPTV组播VLAN、LAN1–LAN8端口绑定以及新增/修改/删除全套配置已于2026-08-13通过现场验收。
- DUT语音查询现会从VoIPProfile和SIP节点解析DTMF/SIP支持字段，并只读获取标准`Device.Services.VoiceService.1.Capabilities.Codecs.`编码能力表；三个下拉按DUT返回候选更新，当前值保留，缺能力字段时使用兼容候选，配置前由service再次拒绝不支持值。代码与自动化测试已通过，Windows下拉显示和真实样机下发/回读待验收。
- DUT语音和TR069页独立只读查询的连续执行、session注销和网卡复用已于2026-08-13验收。TR069查询现按`Device.ManagementServer.`实际存在字段启用配置控件，缺失项禁用且配置载荷不下发；具体字段准确性、一致参数回填、多台不一致保护以及实际配置下发/回读仍待验收。
- DUT Telnet页连续查询、session注销和窗口布局已于2026-08-13验收；AccessCtrl总开关、LAN规则和TCP23状态准确性及查询全程无set/add仍待专项验收。WAN当前状态复用同批查询结果已随WAN配置整组验收通过。
- DUT配置2.4G/5G WiFi页的窗口布局及连续查询稳定性已于2026-08-13验收；2026-08-14单台2.4G WiFi连续两次修改、60秒稳定等待及回读通过真实DUT验收，仅2.4G的认证、信道、带宽、协议和发射功率五类下拉与DUT实际能力一致通过现场验收。5G使用独立Mapping和Radio能力的代码与自动化测试已通过，但5G动态下拉及实际配置尚未现场验收。设备缺少能力字段时的兜底、目标变化后旧能力清理、2.4G其它参数组合、开放网络、隐藏SSID和双频合一行为仍待验收。
- DUT配置双频合一开启后，当前WiFi页会显示当前频段和另一频段两个射频参数区域；两个频段分别使用各自Mapping/Radio能力选择信道、带宽和协议，公共发射功率候选取两边共同支持值并分别写入两个Radio。查询即使设备当前未开双频也会预读另一Radio；配置确认、实际set和回读均覆盖两套Radio。代码与自动化测试通过，Windows显隐布局及真实双频DUT下发/回读待验收。
- DUT配置2.4G/5G页的“SSID递增”默认关闭且互相独立；开启后要求数字尾缀，按DUT窗口已选目标固定顺序保留位数逐台加1，生成值逐项执行UTF-8 32字节预检，确认框和主日志展示最终映射，查询路径保持只读且不参与递增。多台递增批次先完成全部目标下发，仅在最后成功下发目标下统一执行一次可停止的60秒稳定等待，之后每台重新登录并回读；等待中停止不会把未回读目标误报成功。单台或未开启递增仍逐台等待60秒。自动化测试已通过，Windows显示、并行真实下发/统一等待与逐台回读待验收。
- DUT配置六个Tab字段左对齐、原生勾号、状态高度拖动/恢复、底部提示与按钮保护、窗口宽高保存恢复及20ms快速刷新均于2026-08-13通过现场验收；测试项配置窗口的本次加载提速仍待桌面体感复验。
- DUT配置六个Tab目标表现共享独立选择状态：主界面已勾选通道作为候选，首次默认全选，支持逐台切换及“全选/清除”；配置、Telnet/WAN/WiFi/语音/TR069查询与参数校验都只处理窗口内已选择目标，未选择目标的配置错误不会阻塞本批。目标选择变化会清空旧状态、WAN下拉和动态能力。2026-08-30已用主界面同时勾选`vlan112/vlan113`、DUT窗口仅选`vlan112`完成真实查询与配置，确认不访问`vlan113`。
- 主界面截图中的八个功能入口已统一使用相对主界面的居中算法，主程序位于副屏时按父窗口实际屏幕坐标计算；DUT和测试项配置先居中再执行客户区首帧刷新。串口日志仅在无有效历史位置或历史位置仍为左上角时居中，用户主动移动后的有效位置继续恢复。项目负责人已于2026-08-13确认各功能入口居中显示需求验收通过。
- 主界面已统一监听任意位置点击并执行无强制焦点的窗口升层；写参、ONU注册、样机升级、测试项配置、DUT配置和全流程执行已解除`transient`强制所有者关系，串口日志继续保持原本非模态行为。参数生成、程控电源选择和确认/警告等模态交互保持不变。自动化回归已通过，待Windows源码版逐个窗口确认主界面和二级窗口可双向切换前后层级。
- 最近一次**已记录**的完整回归：见页首最近一条实际包含完整验证结果的源码记录；仅做相关检查或文档修改时保留此前结果，不表述为本轮完整验证。自动化和独立Tk组件检查不替代完整Windows操作或真实设备验收，浏览器集成测试仍按环境开关执行。
- 验收状态与不可破坏规则以 `ACCEPTANCE_BASELINE.md` 为准；本文件不重复保存历史测试数和详细验收证据。

## 继续开发先读什么

1. `README.md`：仓库入口、主源码目录、文档职责和历史目录边界。
2. `AGENTS.md`：开发和 AI 硬规则。
3. `ACCEPTANCE_BASELINE.md`：本次改动涉及功能的状态、不变量、待确认项。
4. `DEVELOPMENT_LOG.md` 顶部最近记录：最近变更和验证结果。
5. 相关 `tests/test_*.py`：既有断言和 mock 约定。

## 关键入口

- `Cheating_machine_execution_tool/run_line_check_assistant.py`：源码启动入口。
- `Cheating_machine_execution_tool/line_check_assistant/app.py`：Tk 主窗口、功能入口和主执行日志。
- `Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`：全包升级流程。
- `Cheating_machine_execution_tool/src/services/sample_parameter_service.py`：批量写参流程。
- `Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`：7 子任务编排。
- `Cheating_machine_execution_tool/src/services/legacy_power_test_service.py`：第7项无 GUI 旧 Start All 适配与 Logs 桥接。
- `Cheating_machine_execution_tool/scripts/verify_baseline.py`：提交前最低回归门禁。
- `Cheating_machine_execution_tool/scripts/create_portable_config.py`：构建免安装包时生成脱敏配置。

## 当前待办与限制

- C600 VLAN转换与只读确认页：需在Windows源码版核对两/三列输入、保存重开、只读选择复制、多台分段展示、指定两个区域移除与参数变化失效；真实OLT核对普通数据、语音、TR069的DHCP/双向通信及IPTV用户VLAN、目标VPort组播转换命令兼容性、持续播放/切台、失败/停止与独立write边界。原现场结论不自动覆盖新增路径。
- 真实样机：全流程执行三项端到端（串口预启动→环境检查→开关机测试，特别核对仅断电已选通道提示、通道映射、旧Logs和停止）。页面升级、ONU注册及DUT独立目标隔离的本轮指定场景均已验收；其余未列明型号/模板/异常路径仍以`ACCEPTANCE_BASELINE.md`待确认项为准。
- 并行边界：全包升级与写参的 4 / 8 台场景按现场需求补验收，不因单元测试自动升级验收状态。
- 全包升级新首轮 boot 时序：`Tftp指令` 与 `Tftp Put` 均需在 Windows 源码版和真实样机确认“上电帧后稳定 1 秒即开始循环回车”；不得以本轮自动化测试替代该现场结论。
- `Tftp Put` 传输后未识别到 Boot/Bood 时的后备重新上下电：需在 Windows 源码版和真实样机确认其当前通道、默认后备时序；勾选恢复出厂时还需确认原 120 秒等待及最终系统登录。
- 两条全包升级路径未勾选恢复出厂时的 3 秒收尾、跳过最终系统登录，以及勾选恢复出厂时保留原 120 秒等待/最终登录/恢复出厂：需在 Windows 源码版和真实样机确认。
- 仅支持 Windows 10/11；设置网卡静态 IP 需管理员权限。
- 免安装ZIP必须完整解压，不能只复制EXE；目标电脑首次运行前需重新填写被脱敏的网卡/COM、设备/源IP、凭据和文件路径。
- 严格区分 `Tftp指令`（样机从本机 TFTPy Server 拉取）与 `Tftp Put`（本机 TFTPy Client 推送到 `192.168.1.1:69`）。
- 多网卡路径必须锁定 VLAN 源 IP；TFTP / Telnet 不得回退 `0.0.0.0`。
- 旧工具 GUI 主文件、旧 EXE、历史升级原型和协议参考目录默认不改；只有全流程“执行开关机测试”允许在独立无 GUI 子进程复用旧工具 `test_case/common/clients` 业务类，不 import / 实例化旧 GUI。其它主程序路径仍不依赖旧业务；`Telnet Enable` 反向关系、COM 同值和 channel 1～16 同步规则保持不变。

## 运行、验证与交接规则

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m pip install -r .\requirements.txt
python .\run_line_check_assistant.py
```

- 日常代码改动：按影响范围执行必要的局部编译、相关专项测试及差异检查，不为低影响修改机械新增测试；追加 `DEVELOPMENT_LOG.md`，并按 `AGENTS.md` 同步状态、验收或操作说明。纯文档修改只检查内容一致性、链接和差异格式，不运行代码测试。
- 完整基线仅在四类情况执行：负责人明确要求完整基线或全量回归；提交代码前；标准打包（包括构建入口的 `-CheckOnly`）；对已验收功能进行搬迁、拆分、重写等结构调整时。触发后在主源码目录运行 `python scripts\verify_baseline.py` 并全部通过。仅修改已验收功能的局部行为或显示不自动触发，原 Windows 源码版或真实样机复验要求保留。
- 负责人只说“检查一下”或“验证修改”时默认相关检查；检查失败先定位问题并补充直接相关验证，失败本身不自动扩大到完整基线。报告列明实际执行的检查，未运行完整基线时明确注明，保留最近一次完整验证记录，不将旧结果表述为本轮结果。
- 渐进式模块化：现有已验收功能默认保持原结构，不因文件过长主动搬迁；新增功能优先落到独立 `src/ui`、`src/services`、`src/core` 或 `src/models` 模块，`line_check_assistant/app.py` 只保留入口装配和 UI 回调。结构调整与业务行为修改默认分轮进行，跨模块搬迁已验收代码前必须取得用户确认。
- 完整基线包含六类检查：编译清单全量编译、源码编译清单完整性、全量单元测试、已验收关键行为测试实际执行、必须命中不变量及必须不出现模式。首次开发环境应运行 `powershell -ExecutionPolicy Bypass -File scripts\install_git_hooks.ps1` 启用提交前门禁；Git hook 与标准构建入口保持完整基线要求。
- 真实样机通过：只有项目负责人提供现场结果后，才能更新 `ACCEPTANCE_BASELINE.md` 状态标签。
- 文档或构建调整：追加开发日志；只有影响当前入口、待办或运行命令时才更新本文件。
- 按负责人要求，`Cheating_machine_execution_tool/Auto_power_on_off_tool/config/` 下所有文件纳入 Git 跟踪，保留现有配置内容；日志、测试结果、`build/`、`dist/` 和 `.claude/settings.local.json` 仍不提交。
