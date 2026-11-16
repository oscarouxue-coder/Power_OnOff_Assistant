# Full Capability Agent 阶段实施记录

## 本阶段范围

2026-11-16阶段4续接：当前机器矩阵63接入/15部分/5待接入/3人工。下文53/15/15/3及2554项是阶段3历史检查点（日志另存`stage3_full_baseline.log`），不用于声称后续源码通过。新增共享边界和本轮检查见末尾。

2026-11-15，源码版，已实现但未进行完整Windows、真实模型/平台/DUT验收。本记录只描述全功能Agent阶段；工作区同时存在的网关及串口滚动改动保留，不据本阶段宣称那些功能已验收。完整基线检查当时整个工作区。

六项补充要求已经合并到`.claude/plans/full-capability-agent.md`。当前覆盖矩阵为86项：53项已接入、15项部分接入、15项待接入、3项人工控制面。这是阶段台账，不能称为全部业务已完成或用分组数冒充最终覆盖率。

## 实现与回退边界

| 边界 | 主要文件（相对主源码目录） | 复用和实际限制 |
|---|---|---|
| 目录/权限/任务 | `src/models/capabilities.py`, `src/services/capability_registry.py`, `capability_service.py`, `capability_jobs.py`, `resource_lease_service.py`, `capability_metrics.py`, `ai_capability_adapter.py`, `capability_scope_service.py` | 受信任来源、三档权限、内部校验/实时准入；DB锁及资源锁不跨Tk等待；持久化幂等、未知结果隔离，不自动重放 |
| 升级 | `src/services/firmware_upgrade_service.py`, `firmware_upgrade_validation_service.py`及`line_check_assistant/app.py`原worker代理 | 原四条引擎；Boot/指令/重试/等待/恢复默认不改；GUI/AI采集请求等价，固件私有副本及内容摘要；原日志投影阶段不作为新刷写判据；默认不额外登录回读 |
| 供电/挂测/DUT | `src/services/capability_device_services.py` | 原电源服务、PipelineOrchestrator、版本预检、原WiFi/判据、预备测试及DUT配置服务。恢复仅同进程/同身份最近原批次；原程序没有通用暂停接口，不虚构 |
| 参数表/写参 | `src/services/capability_parameter_services.py`, `sample_parameter_application_service.py`及app原worker兼容代理 | 共用原生成/预检及写参流水线；工厂IP派生、UBUS/二次登录/命令/重试/并行默认保持。绑定实际表SHA256和内存记录，不在队列中换表；输出暂限工作区 |
| ONU | `src/services/capability_onu_services.py` | 原注册/命令快照、查询及删除身份回读；显式SN/接口选择，首次OLT/PON独立本地审核；write独立整机授权，不隐含在注册/删除中 |
| 配置/观测/更新 | `src/services/capability_configuration_service.py`, `capability_observation_service.py`, `capability_update_service.py` | 原store按revision合并、保留秘密/空串，编辑器打开拒绝覆盖；被动监控只释放自己的所有权；WiFi只读当前尝试；原更新检查/校验，只下载ZIP不运行 |
| 本机/文件/项目数据 | `src/services/controlled_host_service.py`, `controlled_file_service.py`, `capability_ai_data_service.py` | 固定只读查询/锁源端口探测、受控产物；原会话/报告存储和原批次删除保护；模型测试由原客户端产生结果，不由AI自报；模型密钥不输出 |
| 本地受控扩展 | `src/services/capability_extension_service.py`, `src/ui/capability_management.py`, `ai_diagnostic_task_control.py`, `ai_diagnostics_window.py` | JSON声明式模板只调用正式业务；真实本地审阅版本/摘要/schema/范围/次数/有效期；不可自我批准、反射任意函数或执行任意代码，尚不是通用Shell等价替代或系统沙箱 |
| GUI桥/双向互斥 | `src/ui/capability_ui_bridge.py`, `ai_assistant_controller.py`, `line_check_assistant/app.py`, `pipeline_window.py`, `src/ui/test_item_pretest_controls.py`, `src/services/adapter_rename_service.py` | 只采集数据/主线程显示。GUI确认后及真正设运行标志前再准入；Agent也检查旧GUI查询/预备测试/续跑状态；模型停止不取消合法业务 |
| 既有保护/门禁 | `src/services/ai_action_service.py`, `ai_permission_service.py`, `ai_conversation_service.py`, `ai_session_router.py`, `ai_monitor_service.py`, `ai_debug_service.py`, `src/models/ai_actions.py`, `scripts/verify_baseline.py`, `verify_capability_coverage.py`, `capability_gui_actions.json` | A1/A2保持；来源变化使旧grant失效。A7仍仅监测，不改缓冲/归档。GUI动作及辅助函数变化需审查快照；待接入条目不删除 |

兼容性修复还包括`src/services/physical_resource_guards.py`对原callback-only管道上下文的支持，以及编译门禁将两个网关/启动脚本单列为额外编译入口；主源码限定目录断言保持。既有Telnet测试在服务器发送提示前用Event协调cursor，保留原3秒边界和断言，避免竞态造成偶发假失败。

启动模块开关、依赖及整体回退见操作员README的“AI正式业务能力”。先安全结束活动业务，再重启回退；保留数据库/日志/证据，不在任务中热卸载或删除未知记录。旧GUI批次暂未接入新job查询/取消，这一限制持续列在矩阵。

## 验证

- 改前完整基线2430项、196项指定回归通过，A1/A2源码与专项已修复；A7仍是只读观测。既有旧按钮顺序断言在改前基线已通过，不作为本轮缺口。
- 新增专项位于`tests/test_capabilities.py`, `test_capability_devices.py`, `test_capability_onu.py`, `test_capability_extensions.py`, `test_capability_application.py`, `test_capability_ai_data.py`, `test_capability_upgrade_equivalence.py`, `test_capability_coverage.py`。全部使用临时目录、Mock/Fake模型/串口/供电/OLT/更新客户端及离屏Tk，不对真实设备发送操作。
- 385项相关回归通过，含原app、升级安全停止、管道、预备测试、编译门禁及新任务/权限专项。四方式×两Boot方式×恢复选项的实际GUI请求与Agent数据请求一致；模型中断、已提交后停止、文件替换、来源/目标变化、并发幂等、线程启动失败、进程重启未知隔离、本地审阅及回退均有专项。
- 首轮完整基线2550项，1失败/1错误，详见`full_baseline_attempt1.log`：新增跨进程包装器不兼容原最小Fake上下文、网关脚本位置不满足原源码编译目录断言。已在实现/编译清单修复，未放宽断言；上述385项包含修复后回归。
- 最终完整基线：2554项测试、196项指定回归、226项编译（224主源码及2脚本）、覆盖门禁及全部协议不变量通过，`ALL CHECKS PASSED`。2026-11-16复核当前363个Python文件与`source_after.json`一致。入口`run_baseline.ps1`调用原标准检查及独立CPython3.9.10 x64；前一轮2552项检查已通过，但网关7个文件在运行期间变化，保留`full_baseline_attempt2.log`后重新执行，未将旧快照充当最终源码结果。
- 完整日志及指标不含模型prompt或真实设备凭据。本轮没有构建/运行EXE、提交、发布或真实模型/平台/DUT验收，本机配置文件没有修改。

## 效率与资源指标

运行`measure_offline.py`可复现实测，最新数据保存`offline_metrics.json`。记录schema冷/缓存时间、50个Fake任务提交/总耗时、成功率、线程/句柄/RSS、真实对话队列的Fake HTTP次数/工具次数/首次正文/总耗时及模拟挂测在元数据/日志压力下的推进。

离线快捷升级使用2次Fake模型HTTP请求、1次工具调用、0次发现工具调用，明确单通道路由0次模型调用。50次Fake升级50次成功；schema缓存与短任务、线程/句柄等具体数值以JSON为准，不把本机调度抖动归因于架构，也不以小镜像/空引擎时长代表真实刷机速度。

首次正文从进入对话队列计时；意图路由单独记录，独立风险审查纳入模型计数；业务任务耗时另记，不把“返回job_id”算成设备成功。真实模型/远程平台、长时间8/16路挂测及真实设备成功率仍未测，不能据此宣称已经比旧版真实环境更快。

## 下一阶段仍需完成

阶段3曾保留通道/配置/通知/报告等15项待接入。阶段4已补齐其中10项；当前仍需受控串口发送与目录、监控及两平台接入控制面5项，以及旧GUI任务接管、模型配置写入/选择、输出目录授权、受控命令等价迁移等15项部分接入。不能用模拟按钮、通用Shell、登记空handler或不实“无法自动化”结论消除这些条目。全功能改造尚未全部完成。

## 2026-11-16 阶段4续接

- `capability_notification_service.py`：原MessagePushConfigService合并保存，保留未提供凭据；本地审核目的地/密钥/提醒范围摘要。禁用不要求再次批准旧目的地；固定试发异步共用原发送器，无实际外发、不自动重试。
- `capability_ai_data_service.py`及原`ai_conversation_service.py`：报告接手绑定当前内容版本、真实来源和目标，旧报告缺目标必须本地审核关联；新会话沿用当前有效权限，不继承历史FULL。案例显式启停及按版本删除共用原库，根因/复测确认仍人工。列表沿用原人工标题。
- `capability_configuration_service.py`及`controlled_host_service.py`：原默认模板生成未保存items草稿，保留当前全局重试间隔；原资源枚举不打开COM、不占用挂测设备资源。
- `ai_business_batch_route.py`及原router/batch/conversation：明确多通道业务走同一原业务会话，避免误入逐设备诊断；不额外调用路由/诊断模型，不改变原诊断批次。Fake两通道升级只启动一次两请求引擎，实际2次模型HTTP、1次业务工具、0次发现/路由/诊断规划调用。
- `capability_channel_service.py`、`config_store.py`、`adapter_rename_service.py`及GUI数据桥/控制器/app：版本化选择/绑定、新范围本地审阅、不会扩大调用者设备权限；共享原serializer、IP派生和工厂字段，文件互斥/临时文件原子发布。GUI只采集/渲染数据，不调用按钮或窗口生命周期。原GUID回读引擎改名，GUID变化拒绝；改名后配置同步失败保留unknown，绝不自动改回或重发。主线程发布失败恢复旧视图，无法恢复则保留资源保护待本地核对。
- 独立启动模块新增`channels,notifications`；新模块位于既有开关内，可与原业务分开回退。机器矩阵新增8个完整接口行，仍保留全部7pending、15partial。
- 相关检查：通知/配置/报告等439项通过，多通道业务/原路由权限等246项通过。通道新9项全部通过，原channel_config/resource_options/app组合通过；原adapter_rename共44项单独通过。合跑293项时仅原居中断言失败：离屏包装器将父子窗口均强制移动到同一坐标，破坏其中心差；按原模块运行44项全绿，未修改产品窗口或放宽断言。完整基线正在按标准入口复核，结果以后续追加记录为准。

永久选项续接：新增`src/services/capability_settings_service.py`及`tests/test_capability_settings.py`，增量修改原`sample_upgrade_settings_store.py`、`onu_registration_store.py`、app及GUI数据桥/控制器/能力service。共用原模型和serializer，按当前GUI及文件版本合并，编辑器/待保存时拒绝；临时文件原子发布及同进程/跨进程配置互斥。读取省略密码，未提供字段保留；新ONU连接/PON需本地审阅，但不授予执行或write权限。编辑器Tcl写回调仅在数据渲染时临时解除后精确恢复，不调用过期窗口，ONU旧预览/查询缓存失效；后续正常GUI操作仍触发原回调。发布失败恢复旧数据，回退渲染失败保留资源保护。

永久选项最新相关289项通过，其中11项新测试涵盖原GUI数据收集一致、实际Tcl写回调解除/恢复、自动保存排空、后台RPC只在owner线程提交、来源/参数拒绝、新配置不授权OLT、凭据变化使旧范围失效、发布失败和提交前冲突。首轮新增Tcl测试替身Mock缺`__name__`，修正为真实函数并捕获回调异常，消除假阳性。通道阶段完整2578项/196指定/229编译/227源码清单和367份快照通过，日志`stage4_channels_baseline.log`、`stage4_channels_source.json`保留。永久选项前一完整2588项已通过，但运行中补充了Tcl保护，源码摘要检测到2文件变化，日志留存`stage4_settings_before_trace_fix.log`，不能当作最终版本通过。

2026-11-16离线重测：50个Fake升级50成功；schema缓存中位0.0304ms，提交中位4.7244ms，Fake任务总耗时中位30.7366ms。实际对话队列2次Fake模型HTTP/1次工具/0失败，首次正文0.016s、整轮0.063s；无发现和明确单通道路由模型调用。线程4→4、句柄182→182，关闭后183，不能据单次快照宣称无句柄泄漏；RSS增加1011712字节。模拟挂测基线33ticks/0.5093s，元数据/日志压力1717轮时32ticks/0.5002s，线程5→5、句柄189→189；模型停止后继续推进。与短时调度有关，不能据此推断真实长期性能或已优于旧版。原始值在`offline_metrics.json`；真实模型/平台/8或16路长期挂测仍待验收。

后续完整检查一次进程异常退出，未产生`Ran N tests`汇总或具体失败断言，原因为未确认，日志`stage4_settings_process_exit.log`保留，不记通过。排查新增Tcl测试的生命周期，补充owner线程解除全部真实Variable回调、取消计时、清空fixture及GC，并用弱引用断言确认两个解释器已释放；不修改产品权限或原测试断言。清理代码首次误把Mock视为Variable，收紧为实际类型；随后42项设置/网关/应用/通道组合及18项设置/网关组合均通过且无回调错误。最终完整结果另记，不将推测的退出原因表述为已确定。

最终完整结果（2026-11-16）：标准`run_baseline.ps1`/`scripts/verify_baseline.py`检查全部通过：2589项测试、196项指定回归、230文件编译/228主源码清单、能力覆盖及全部协议不变量，`ALL CHECKS PASSED`，exit 0。`source_before.json`与`source_after.json`的369份Python文件一致；后续只同步文档/验证材料，最终源码再次与该快照核对。最终日志`full_baseline.log`。当前63接入/15部分/5待接入/3人工，不标为总体完成；没有真实设备、消息外发、EXE构建/运行或Git提交。
