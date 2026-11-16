# 多实例统一接入首批实现与验证

2026-11-15开始实施，2026-11-16继续收尾。源码交付，不提交、不打包，不连接真实平台/模型/DUT或执行真实供电、刷写、写参、ONU操作。

## 已实现

- 程序目录外的随机永久身份、每次启动的run_id、原子槽位申请与持久化配置；同目录槽位分别拥有会话及原业务Job库，不以电脑名作为身份。
- 一次性配对、DPAPI凭据、逐实例撤销、显式本地范围确认；挑战/方向/序号认证的WebSocket，心跳、离线、重连和启动身份校验。
- 网关路由、平台SDK/解析及格式化复用；在线/当前/切换实例、原请求查询；持久化投递与实例收件去重，先接收落盘再确认，不把收到消息当作业务成功。
- 目标实例复核真实来源、槽位/启动、通道与Capability白名单；新会话ASK，不继承本地/飞书FULL。继续通过现有AiConversationService、AiCapabilityAdapter、权限服务、CapabilityService和CapabilityJobs执行，没有第二套业务引擎或Job数据库。
- Windows Global物理资源互斥，COM大小写/编号及电源COM统一；共享业务、底层串口/电源、网卡修改及全流程入口使用保护。统一实例业务使用共用主机资源隔离记录，已下发未知结果不能通过复制程序、新槽位或新请求自动重试，核实继续走原Job的本地审核入口。
- 网关网络线程与实例收件/Agent线程分离；断网不调用业务cancel/begin_close。Fake升级经过真实回环连接、原Agent工具循环、原Capability/Job后只调用一次Fake引擎；重连后回传原Job结果。

## 运行入口

在主源码目录执行`python scripts/run_remote_gateway.py --help`。命令包含serve、pair-code、pair-instance、allow-instance、show-instance和revoke；源码实例使用`python run_line_check_assistant.py --gateway-slot 1`。不加该参数维持原直接接入模式。完整步骤和受保护网络要求见操作员README“多实例统一远程接入”。

配对和allow-instance只能在本地显式操作，网络接口没有发放FULL或伪造平台事件的RPC。平台接收只在明确指定`--platforms`时启动；本轮验证没有启动真实SDK连接。多实例同时运行需使用不同槽位；不同项目建议独立程序目录，同目录仍共享原项目INI。

## 本轮文件清单

以下路径均相对主源码目录，根文档使用`../`。其中Full Capability Agent文件在本轮开始前已有未提交实现，本轮只增量衔接统一来源、任务关联和物理资源保护，未覆盖其它开发内容。

| 分组 | 文件 |
|---|---|
| 新增底层/模型 | `src/core/host_resource_lock.py`、`src/core/remote_gateway_transport.py`、`src/models/remote_gateway.py` |
| 新增独立业务模块 | `src/services/remote_instance_identity.py`、`remote_gateway_store.py`、`remote_instance_service.py`、`remote_gateway_runtime.py`、`remote_gateway_router.py`、`remote_gateway_platforms.py`、`host_resource_fence.py`、`physical_resource_guards.py`（均在src/services下） |
| 现有Agent/Job衔接 | `src/models/ai_session_scope.py`、`src/services/ai_permission_service.py`、`ai_session_router.py`、`ai_conversation_service.py`、`ai_action_service.py`、`ai_capability_adapter.py`、`capability_jobs.py`、`resource_lease_service.py`、`firmware_upgrade_service.py`、`pipeline_orchestrator.py`（后九项在src/services下） |
| 原执行入口保护 | `src/core/serial_transport.py`、`src/core/power_supply.py`、`line_check_assistant/network_ops.py` |
| 装配与可运行入口 | `src/ui/ai_assistant_controller.py`、`line_check_assistant/app.py`、`run_line_check_assistant.py`、新增`scripts/run_remote_gateway.py` |
| 新增测试 | `tests/test_remote_instance_identity.py`、`tests/test_remote_gateway.py`、`tests/test_remote_gateway_agent.py` |
| 检查/覆盖 | `scripts/verify_baseline.py`编译登记；审查并生成`scripts/capability_gui_actions.json`、`../CAPABILITY_COVERAGE.md`，未将未接通业务伪标为完成 |
| 文档 | `line_check_assistant_README.md`、`../DEVELOPMENT_LOG.md`、`../PROJECT_STATUS.md`、`../ACCEPTANCE_BASELINE.md`、两份`../.claude/plans/`实施台账及本报告 |

## 验证

- 首个身份模块6项通过，随后补跨进程GUI底层入口“下发前拒绝”和不同本机数据区身份隔离，共8项。
- 网关/协议/配置/平台Fake模块18项通过；真实回环WebSocket包含配对、认证、转发、确认、撤销与重放拒绝。
- Agent端到端模块最终7项，覆盖默认ASK、原本地FULL隔离、Fake升级一次、断线/恢复、未知结果新消息仍不重做、越权、实例拒绝的确认及Agent已入队但确认丢失时保守unknown。请求—会话关联在Agent入队前落盘，重启保留此关联，不把未知状态说成未执行。
- 第一组组合169项通过：新增模块、原串口、电源、网卡、全流程及Capability；后续直接相关155项通过，含完整基线结构、停止及离屏UI/静态源码回归。
- 新增三模块最终33项专项全部通过（身份8、网关18、Agent端到端7）。边界补充前完整基线`baseline_final.txt`为2554项通过；入队确认边界补充后的`baseline_confirmed_20261116.txt`为**2555项、196项指定回归、226编译/224主源码登记及能力覆盖/协议不变量全部通过**，`ALL CHECKS PASSED`。不复用旧2456项记录。
- 收尾摘要覆盖364份源码/测试/脚本。本接入新增及衔接代码摘要未变；运行期间同期`src/services/capability_ai_data_service.py`及`tests/test_capability_ai_data.py`发生变化，另外运行该模块10项全部通过，未覆盖或回退其内容。`source_hashes_before_final.json`、`source_hashes_after_final.json`及`source_hash_check.json`保留差异证据，不将整个并行工作区称为完全静止快照。
- 运行完整基线使用独立CPython3.9.10、`PYTHONUTF8=1`及`PYTHONIOENCODING=utf-8`，TEMP/TMP临时规范到当前用户LocalApplicationData/Temp，退出后恢复环境；不更改系统或项目配置。新增入口同时通过编译及`--help`检查。

早期检查的失败证据保留：`baseline.txt`为父/子Python输出编码不一致导致读取失败；`baseline_utf8.txt`为之后一轮全量输出，包含入口脚本编译清单分类、无通道测试替身、短/长TEMP路径差异，以及同期源码变化导致的inspect/GUI快照失败。相应修正后在新进程跑直接相关回归，不降低原业务断言。串口/电源/网卡均为Fake或冲突前拦截，未下发真实设备命令。

## 剩余边界与下一阶段

- 本批提供CLI配对和源代码显式启动，没有新增GUI配对/范围管理页；审批在目标实例本地完成。群内审批编号、跨实例业务取消、明确原任务的跨run查询/接手流程还须接入。
- Fake端到端以单通道固件升级为首条；多实例多人压力、跨用户/跨Windows会话、业务批量任务的完整投影和长时间回传需补专项。不能将原单实例Capability测试等同于这些场景已验收。
- 需在受认可VPN/WSS、真实钉钉/飞书及Windows界面验证；单应用的其它电脑旧Stream须停用，否则平台自身随机投递无法由此网关兜底。未宣称端到端消息恰好一次，平台回复不确定时记录unknown、允许查原请求，不重做业务。
- 旧GUI已启动任务的全面接管、其它底层/旧工具的覆盖继续按Full Capability Agent矩阵推进；本批的系统锁/资源隔离不能替代实际驱动、网卡标识及设备现场验证。
- 主机隔离记录仅是资源保护，业务真相仍在原Job库。常规unknown需回原槽位走本地核实；崩溃恰好发生在资源准入与Job落盘之间的孤立保护记录、凭据撤销后的重配/热轮换等恢复体验需下一批补齐，禁止自动清除未知保护。
