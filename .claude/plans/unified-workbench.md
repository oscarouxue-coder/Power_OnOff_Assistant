# DUTPilot 统一工作台：代码审计与分阶段实施

审计日期：2026-11-18。起点：`5b36f59`，原工作区干净；隔离分支：`ui/unified-workbench-phase1`。本计划依据负责人本轮提供的《统一工作台 UI 重构与多项目管理实施计划》，本轮实施 Phase 1；完成后先做 Windows 人工验收，再决定后续阶段。

## Phase 0：实际架构

| 边界 | 实际模块与调用关系 | 结论 |
|---|---|---|
| 主入口 | `run_line_check_assistant.py` → `line_check_assistant.app.main()` → `WorkspaceInstance` → `ProjectWorkspace` | 默认已经是单实例多项目；`--legacy-single-project` 保留 |
| 主窗口 | `src/ui/project_workspace.py`：一个 Tk、项目菜单、Treeview、content、100ms poll；每项目一个 `LineCheckAssistant(ProjectViewFrame)` | 切换使用 pack/pack_forget；不能销毁后台项目 |
| 项目页面 | `line_check_assistant/app.py::_build_ui`：工具栏、ChannelList、配置表、运行卡片、Text 日志 | 直接复用；不搬迁设备命令或重建业务页面 |
| 功能入口 | `_launch_power_on`、`_open_upgrade_module`、`_open_sample_parameter_writer`、`_open_onu_registration_module`、`_open_serial_log_module`、`_open_dut_config_module`、`_open_ai_assistant` | 现有项目局部入口；打开模块后仍由既有业务服务执行 |
| GUI任务 | `project_execution.project_operation` → `ProjectWorkspace.admit_operation` → 资源准入、配置快照、状态 begin → 既有 worker | 不使用按钮模拟，不建立第二套调度器 |
| 任务关联 | `project_runtime.current_run`、`start_project_thread`、`project_result_handoff`、`report_project_result` | worker与UI确认保留原运行身份；延迟结果不复活终态 |
| 状态 | `ProjectStatusService`、`ProjectStatus`、`WorkspaceService.refresh_status/list_projects` | 真实结构化结果 + 活动任务；运行中的异常用 `!` 保留；成功结果目前聚合为 idle + last_result=succeeded，展示层应明确最近结果，不篡改枚举 |
| AI能力 | `CapabilityRegistry`、`CapabilityService`、`CapabilityJobs` | 已有注册、权限/参数检查、SQLite任务、取消及事件；不能将登记当业务已接入 |
| 资源 | `WorkspaceResources`、`ResourceLeaseService`、`HostResourceLock`、`HostResourceFence`、`physical_resource_guards` | 已有主机资源保护、网卡GUID/别名关联、串口/电源/OLT/传输资源及未知栅栏；本轮不改变资源粒度 |
| 项目持久化 | `ProjectIdentity/ProjectContext`、`ProjectStore`、`project_task_scope/ScopedConfigPath` | UUID、draft/revisions/runs/history已存在；INI/JSON/SQLite各沿用，不切cwd、不覆盖旧配置 |
| 生命周期 | `ProjectViewFrame.after/destroy`、`_on_app_close`、`ProjectWorkspace.close_project/close_application` | 回调随项目清理；关闭等待原安全停止；切页不得调用这些入口 |
| 日志/线程 | `log_queue` → 主线程 `_drain_log_queue` → `_log` → Text + 文件；主循环每tick有限消费；串口使用原管理器/队列 | 保留文件和显示摘要链路，不重新显示已隐藏的正常消息；显示折叠不停止采集 |
| 打包 | `build_line_check_assistant.ps1`、相对路径spec、`verify_slim_package.py` | 固定CPython3.9.10/PyInstaller5.10.1；新增UI模块登记编译；本轮不构建、不运行EXE |

### 现状与目标的差距

多项目数据层和受控并行基础已经存在，不能照计划重新开发。缺口是默认总览、项目搜索/滚动导航、项目局部紧凑工具导航、运行状态优先、配置折叠、日志高度拖动/折叠。当前状态服务没有完整通道级事件快照、统一PRECHECK/BLOCKED和每任务标准进度，不可为了卡片填满字段推测或补造数据。现有通道矩阵及轮次数据只在真实上下电任务启动后出现，继续复用。

旧布局预览为独立模拟Tk，尚未接入；本轮以负责人新的整体布局要求为依据，不把旧预览模拟数值带入主程序。模块背景继续遵守AGENTS规则20的`#eef2f5`，内容卡片使用白色，保留青绿色和既有状态色。

## Phase 1：逐文件方案

| 文件（相对主源码目录） | 动作 | 责任 |
|---|---|---|
| `src/ui/workbench_dashboard.py` | 新增 | 只读总览与空工作区入口，读取统一项目列表/状态，不维护任务计数 |
| `src/ui/workbench_panels.py` | 新增 | 可滚动配置区域、配置折叠、日志折叠及可拖动分隔线；不保存业务值、不执行任务 |
| `src/services/workbench_status_service.py` | 新增 | 只读已有运行记录/通道快照；轮次不同步时显示范围，不虚构百分比或正常结果 |
| `src/ui/project_workspace.py` | 局部修改 | 品牌顶栏、总览/项目导航、搜索、滚动条、全局状态；复用所有项目管理方法 |
| `line_check_assistant/app.py` | 局部装配 | 项目详情局部工具导航、运行卡片先于配置；原控件与变量、回调、输入校验不变 |
| `tests/test_project_workspace.py` | 补充 | 总览/详情切换、搜索/折叠、不停后台任务、状态来源、关闭清理 |
| `tests/test_workbench_panels.py` | 新增 | 原生Tk布局、小窗口/字体放大、滚动到达、折叠后控件和日志保留 |
| `tests/test_workbench_status.py` | 新增 | 不同通道轮次、明确正常/失败、老化能力真实含义及异常历史时间 |
| `src/ui/module_theme.py` | 局部修改 | 工作台可选保留项目/卡片局部样式，其它模块默认行为不变 |
| `scripts/verify_baseline.py` | 登记 | 新增源码编译路径，不改变协议grep或既有测试门禁 |
| `scripts/capability_gui_actions.json`、根`CAPABILITY_COVERAGE.md` | 审查更新 | 总览/搜索/折叠/滚动是界面辅助动作；原项目人工控制面及业务能力继续复用 |
| 根`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、操作员README | 同步 | 实施结果、入口、Windows待验收范围 |

新UI接口：WorkbenchDashboard.render(projects)、WorkbenchPanels.toggle_config/toggle_log；数据从现有WorkspaceService单向进入UI。ProjectWorkspace现有500ms状态轮询同时刷新侧栏/总览/详情状态；不增加后台订阅、线程或UI轮询器。只读适配以PowerTestResumeSession.request.channels限定批次范围，不能把旧页面保留的其它批次通道合并；无法确认批次归属时不展示合并轮次。

### 参考图对齐（负责人本轮补充）

- 使用深青色顶栏/侧栏、浅色工作区、白色卡片和青绿色操作层级；显示真实版本V1.2.10，不照抄示意图v1.3.0。
- 总览提供统计卡片、项目卡片/列表切换及工作区事件抽屉；视图偏好单独写入workspace/workbench_ui.json，不混入项目INI。
- 运行中/其它项目分组、搜索及滚动；隐藏侧栏仍可通过菜单切换。
- 项目详情工具入口保持原回调；运行卡片/原通道矩阵居中、配置摘要在右、日志在下。点击“编辑配置”展开原参数表与通道选择，保留原列表宽度，双向滚动保证VLAN/COM信息可达。
- 不提供尚未受控实现的继续运行、重置任务、全业务老化启动、资源等待队列或日志任务筛选；不会用示意图数据填充产品。全局刷新保留原“刷新串口/网卡”合并操作和权限提示，历史窗口/AI/升级/ONU等原入口保持。
- 开关机各通道轮次不一致时卡片显示范围；只在轮次及目标都相同时显示比例。正常/失败数量只来自明确通道结果，未知不算正常；显示“开始于”，不冒充累计有效运行时长。
- 本轮总览事件是工作区真实事件，详情日志是原项目执行日志；完整跨项目/任务/通道日志查询及导出仍属后续阶段，不能把工作区事件称为所有设备原始日志。

### 验证与回退

- 修改前：`python -X utf8 -m unittest discover -s tests -p test_project_workspace.py`，11项通过（本轮实际执行）。
- 修改后：新布局与项目专项、主程序/能力相关回归、编译、能力覆盖、差异检查；本次属于需求触发的主窗口结构调整，必须执行`python scripts/verify_baseline.py`。
- 临时目录及Fake传输验证配置隔离、运行/停止状态；不连接串口、电源、DUT、模型或平台。
- Windows源码人工验收：首页、所有入口、保存/重开、运行中切页、停止中切页、异常标识、最小尺寸与DPI、日志拖动/折叠、退出；未有负责人结果前保留待验收。
- 分支仅含UI和对应文档/测试，业务服务/协议与数据格式不变；可切回`main`恢复原源码。无自动提交、推送、打包或发布。

## 后续阶段门槛

Phase 2先核验已有多项目能力，补项目卡片/列表视图和偏好持久化、任务/通道标准快照、日志项目/任务/通道/等级筛选、历史展示；删除/归档需先定义生命周期规则。不得改写原状态枚举或把已勾选当运行。旧配置继续显式非破坏导入，不能自动覆盖历史数据。

Phase 3先独立评审资源粒度与真实并行路径，复用现有服务；已有四项目Fake测试不是现场并行验收。仍需负责人真实设备确认正常/失败/取消释放、停止A不影响B、源IP和设备命令、关闭安全收尾。

## 长期挂测补充审计（2026-11-18）

负责人补充《多项目长期挂测工作台架构补充方案》，并明确回复：**持续开机的全业务老化尚未实现，先保留待接入状态**。这是本轮实现与后续设计边界；不新增可点击的虚假启动入口。

### 七项审计结论

1. **全业务老化循环/调度**：当前不存在已实现的持续开机Probe调度器。`capability_device_services.py` 中 `aging.start` → `_pipeline(..., ('legacy_power_test',))` → `PipelineOrchestrator`，仍是循环上下电。`only_power_off_on` 表示跳过业务检查、只上下电，不是持续开机；不能据名称推导双引擎。旧特殊型号的命令集内循环也不能当通用Probe引擎。
2. **开关机任务/通道**：`LegacyPowerTestRequest/Result` 描述旧业务输入/结论；`PowerTestResumeSession`拥有自己的run_id、attempts、completed、failed/cancelled/ready/busy。`accepts()`与observe核对运行及续跑编号，避免旧事件污染。`legacy_power_test_service`提取原有日志的通道轮次/阶段，`_overall_completed_cycle`取所有选定通道最小已完成轮次，不能当每通道相同进度。`app.py`既有通道字典与矩阵展示轮次/阶段/历史，继续保留。未新增Probe采样时，不显示成功率、健康数量或有效时长。
3. **统一项目接入**：两种测试类型逻辑区分。现有开关机沿用project_operation/CapabilityJobs准入、项目配置快照与原业务服务；后续持续监测必须新增独立请求及受控service入口，再接项目/运行标识和只读快照；不能复用窗口回调驱动、不能靠控件启用状态推导执行状态。
4. **独占资源**：现有WorkspaceResources实际规范化串口、电源COM、网卡GUID/别名、OLT/PON、WiFi主机、TFTP端点，HostResourceLock及持久未知栅栏共同保护。本轮保留当前较保守的电源COM/网卡占用粒度，不擅自放宽到电源通道。未来同DUT持续监测与上下电互斥需要稳定DUT身份；不得只用同名项目或默认IP判断。组合测试需要另行定义计划内断电协同策略。
5. **日志/历史/异常**：主日志文件、各通道结果/WiFi日志、PowerTestResumeSession历史、ProjectStatusService的runs/*/run.json、CapabilityJobs SQLite任务/事件、TransportHistoryMonitor JSONL及资源趋势均可复用。现有重试/失败历史不是完整“触发/持续/恢复/人工确认”告警模型；异常日志不能替代Probe事实。UI显示可裁剪，文件不能随清屏删除；轮转策略另行定义，不能悄悄清历史。
6. **实际线程链路**：每项目旧业务独立子进程，通道线程，multiprocessing消息队列 →父进程service回调 →主程序after/队列回主线程；AI用JobContext事件与原投影。ProjectViewFrame捕获运行上下文、销毁时撤销自身after。工作台复用500ms状态刷新，不创建测试调度器。切页只pack_forget，不关闭、停止或重建项目。
7. **可靠性缺口**：主Text原无行数/字符上限，本轮仅给新工作台加入有界显示和自动滚动控制；原文件写入和隐藏/摘要保持。旧子进程停止宽限及结果排空已用monotonic，部分旧Telnet稳定等待仍用time.time（`clients/telnet_client.py`的只读命令等待），系统改时风险需专项修复与回归，不能趁UI调整改变时序。现有状态updated_at不是业务心跳，进程存在/串口会话打开均不能推出DUT健康。没有完整持久Probe、有效运行时长、STABLE/STALE指标及恢复告警；异常重启现有unknown及资源栅栏保留，不自动恢复电源操作或把未知映射成功。UI有界不代表消息队列、所有底层历史都已完成容量治理，后续须压测确认。

### 修订阶段与文件清单

- **A / Phase 0**：本节完成审计与清单；只读旧业务，不修改`Auto_Power_On_Off_Tool.py`、旧检测周期、命令/阈值、PASS/FAIL。
- **B / Phase 1**：本轮实现布局、只读总览、原开关机卡片/矩阵、独立可折叠日志及有界显示；全业务老化以“待接入”真实边界记录，不展示绿色占位卡。Windows人工验收通过前不进入C。
- **C / Phase 2**：先新增`src/models/monitoring_snapshot.py`（建议名，尚未创建）、`src/services/workbench_status_service.py`（建议名）做纯数据适配，定义Project→Run→Channel/DUT→Probe身份、时间戳和数据可用性；未知/过期展示独立于测试判定。新Probe服务、事件存储和告警模型另行设计后再实施。统一run状态需版本化映射，保留unknown/unchecked，不能直接替换已持久枚举。
- **D / Phase 3**：稳定DUT资源身份、同DUT两类任务冲突、独立DUT准入/取消/释放，在既有保护之上扩展；不提前开放硬件并行。
- **E**：Fake覆盖超时/离线/恢复/异常中断/日志洪峰/切页/旧事件/冲突，再由负责人做24h、72h及更长挂测，观察内存、句柄、队列、磁盘、结果完整性。短时自动化、离屏Tk和字体模拟不等于长期Windows或真实设备验收。
