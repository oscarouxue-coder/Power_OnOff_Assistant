# DUTPilot PySide6 迁移：Phase 0 代码审计与基线

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

日期：2026-11-18。范围：当前真实工作区，而非仅 HEAD。产品仍为 V1.2.10；V1.3.0 是迁移目标，尚未发布。

后续进展：本文保留初次审计和失败时点。之后已修复基线阻断并交付Qt原型/真实项目基础管理，见[阶段1/2报告](PHASE1_2_REPORT.md)；不要把本文末节的初始失败当作最新检查结果。

本检查点先交付审计与可追踪基线，不批量重写 GUI。Qt 原型和各业务垂直模块分别实施、运行和验收。当前检查结果见末节；不能将本文中的计划路径当作已接入的能力。

## 1. 起点与保存情况

起点分支 `ui/unified-workbench-phase1`，HEAD `5b36f59dad916959dc1b17418f3c46be39250b71`。新分支 `feature/pyside6-migration` 从该 HEAD 创建，原有未提交修改和未跟踪文件保持。暂存区未新增内容，未提交或推送。

工作区不等于原发行版：既有工作台、测试门禁和上一轮中断的 Tk 布局调整尚未提交。尤其 `workbench_panels.py` 的日志拖动断言在上一轮收尾未通过，不能用此前 2940 项历史通过结果代替当前基线。本轮先记录并实测，不擅自清理其它改动。

本地备份目录见 [backup_receipt.json](backup_receipt.json)，位于仓库外 `%LOCALAPPDATA%/LineCheckAssistant/migration-backups/20261118-095226`：

- `source.zip`：910 份源码、测试、配置相关文件；逐文件 SHA256 与 `source_manifest.json` 一致，ZIP CRC 通过。包含当前未提交源码；`worktree.patch`、`index.patch` 补充 Git 差异。忽略受保护输出、环境、验证截图与日志目录，这些不是源码归档内容。
- `dependencies.json`：标准隔离环境实际 Python 和全部已安装 distribution 名称/版本；原 `requirements*.txt`、spec、构建脚本已在源码归档中。没有安装、卸载或升级原环境依赖。
- `data.zip`：1060 份文件，覆盖兼容配置、工作区、最近项目所指向的有效目录、本机项目/AI/案例库、主机未知资源保护记录、现有结果与日志目录。SQLite 用只读连接调用在线 backup API，不直接复制活动 WAL；每个数据库和普通文件为各自时间点快照，不声称跨所有项目事务一致。归档 CRC 通过，文件备份失败 0。实际根目录/存在性/文件计数留在本地 `PRIVATE_DATA_INDEX.json`，避免将配置和凭据写进仓库报告。
- `artifacts/LineCheckAssistant.exe`：保留现有 63,275,835 字节历史产物副本，SHA256 `4fe10a51db918b50942759c5425866fad6659fe765e58f5a7ceece38f7d6c014`。其时间为 2026-09-20，**不能证明它对应当前 V1.2.10 工作区**。本轮没有运行它，没有重建 EXE。

备份含本机配置及可能的凭据，只保存在本机，不作为发布附件。一次备份的临时 SQLite 连接未关闭导致 Windows 临时文件清理失败；修正为显式 closing 后重新完整备份，以上凭据只引用最终成功结果。

## 2. 实际目录与 GUI 清单

```text
仓库根
├── AGENTS.md / README.md / PROJECT_STATUS.md / ACCEPTANCE_BASELINE.md
├── DEVELOPMENT_LOG.md / CAPABILITY_COVERAGE.md / .claude/plans
└── Cheating_machine_execution_tool
    ├── run_line_check_assistant.py       当前正式源码入口（保留）
    ├── line_check_assistant             Tk 主装配、原配置 stores、全流程窗口
    │   ├── app.py                      8685 行；ProjectViewFrame 子类
    │   ├── pipeline_window.py          557 行；全流程设置与 Tk 启停控制
    │   └── packaging_specs/LineCheckAssistant.spec
    ├── src/ui                          Tk 页面、窗口、桥接、局部主题
    │   └── project_workspace.py        783 行；Tk 根、多项目装配和部分准入/退出协调
    ├── src/services                    已有流程、Capability、Jobs、项目与资源服务
    ├── src/core                        串口/电源/网络/Telnet/TFTP/锁/平台基础能力
    ├── src/models / src/utils
    ├── Auto_power_on_off_tool          兼容配置及稳定旧测试类，不迁移旧 UiCase
    ├── Page_upgrade / SdmcUbusLib / ZteTitanOnuProvisioner  现有协议/业务资产
    ├── tests / scripts / assets / validation
    └── build / dist / logs / .venv      受保护输出/环境，本轮不修改
```

[GUI_INVENTORY.md](GUI_INVENTORY.md) 列出 GUI 依赖文件中的类、定义行及 Tk/Toplevel 构造位置；[source_inventory.json](source_inventory.json) 包含每个文件的导入、类、变量/定时器/绑定位置。复现：主源码目录执行 `python -X utf8 validation/pyside6_migration_20261118/audit_inventory.py`，只做 AST 读取，不导入产品、不创建窗口。

当前活动应用扫描范围为 `src/`、`line_check_assistant/` 和启动文件，共 267 份 Python 文件、61,694 行；其中 49 份具有直接 GUI 依赖，38 处显式 Tk/Toplevel 等构造，252 处 Tk Variable 构造，110 处 after/after_idle/after_cancel 调用，202 处事件/变量跟踪/窗口协议绑定。这些是静态位置数，不是运行实例数或完整耦合数；`PipelineUiController` 等通过 app 协议耦合而没有 Tk import 的对象仍在下表单列。

另有兼容旧工具 UI（`Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py`、`UI/`、`test_case/Onu_config.py`）不属于当前 Tk 主程序，也不应把它迁成新 Qt 主窗口。实际执行链只复用旧测试类；原服务在独立子进程安装无 GUI 的 PyQt5 信号桩，不能因为源码含 PyQt5 字样就加入真实 PyQt5 依赖或替换它的线程模型。

## 3. 入口、窗口和刷新关系（已确认）

`run_line_check_assistant.py` 处理项目参数、兼容单项目、网关槽位与源码环境检查，调用 `line_check_assistant.app.main()`。默认先取得 `WorkspaceInstance` 单实例保护，再创建 `ProjectWorkspace` 并运行 Tk mainloop；兼容参数 `--legacy-single-project` 仍创建旧单项目入口。

多项目 `ProjectWorkspace._add_project()` 为每个已打开项目实例化 `LineCheckAssistant`；`select_project()` 只 pack_forget/pack，任务和页面对象不销毁。工作区 `_poll()` 每 100ms 消费事件和关闭/准入收尾，约 500ms 聚合状态；每项目另有主日志 200ms 空闲/积压立即续排、pipeline 与 DUT 队列 50ms drain 等。Qt 应替换显示调度和窗口所有权，不能为每次切页复制这些线程/监听器。

| GUI / 协调模块 | 现有职责与耦合 | 迁移处理 |
| --- | --- | --- |
| `app.py` / `ProjectViewFrame` | Tk Variable、配置采集/校验、按钮状态、模块装配、after 上下文传播和销毁 | 不搬运整个 self 对象；按模块输入/命令/事件协议接入 Qt |
| `project_workspace.py` | 导航/卡片之外，还持有准入票据、配置快照、资源释放、dirty 与安全退出 | 这些协调不是单纯换皮；应用级 adapter 先等价保护，再替换其 GUI 调用 |
| `pipeline_window.py` / `src/ui/pipeline_ui.py` | 选项和确认、创建 run、主线程 dispatcher、子模块完成回传、停止等待 | 保留服务编排；Qt 请求/结果桥替代窗口生命周期与旧回调 |
| `capability_ui_bridge.py` | `snapshot()` 调用 `_capture_current_channel()`、读变量/窗口状态；admissible/commit 需要 Tk dispatcher | Capability 本身不依赖 Tk，但当前注入的桥不是无头服务，必须提供 Qt 数据宿主 |
| `serial_terminal.py` | Tk Notebook/Text、队列批量渲染、跟随与裁剪、共享 session 监控所有权 | 复用 manager/传输/落盘，重建 Qt 展示及订阅生命周期 |
| `dut_config_window.py` | 表单、查询结果回显、并发确认与 app 事件队列 | 复用 DUT service；冻结输入后提交，不从 worker 读取 QWidget |
| `ai_assistant_controller.py`、chat/monitor/report/session/approval 等 | 服务之外还持有 Tk 页面、审批/权限和目标选择、定时回显 | 单独迁移人工控制面，保留原可信身份、审批和会话取消边界 |
| `src/ui/__init__.py` | 顶层直接导出串口/DUT 窗口，会在导入 UI 包时带入 Tk 模块 | Phase 1 如需在此包下新增 Qt，先做最小兼容懒加载并覆盖原导出测试，不能把导入等同创建窗口 |
| `module_theme.py` / `window_paint.py` / `tk_lifecycle.py` | ttk styles、原生 Checkbutton、窗口居中与 TkScope | Qt 新设计 tokens/QSS/Layout 独立实现；旧 Tk 样式与勾选语义保持 |

配置窗口 `app.py:_open_test_item_config` 实际有 Telnet、测试项、WiFi、项目信息、运行参数、消息推送六类标签；表单创建和数据收集同处方法内，底层 store 可复用。当前固定最小尺寸和控件宽度不直接复制到 Qt。密码/Token 不进入新增 Qt 日志；原值、含义、保存 schema 和确认语义不变。旧模块允许显示的本地敏感信息需逐字段审查，不能把“复用日志”理解为新界面无过滤转发。

## 4. 原样复用范围与需要抽离的接口

| 范围 | 可复用的真实实现 | 需要适配/验证的部分 |
| --- | --- | --- |
| 项目 | `models/project.py` 的 ProjectIdentity/ProjectContext；`project_store.py` create/open/save/snapshot；`workspace_service.py` | 大文件/历史导入放后台，主线程只提交/更新 model；WorkspaceService 的 controller 协议/注册与关闭须新宿主 |
| 状态 | `ProjectStatusService`、`workbench_status_service.workbench_projects` | 旧 workbench 通道输入来自 view；Qt 从实际 run/job 事件取值。未知≠正常、选择≠运行，不按旧状态文件恢复 RUNNING |
| 任务/授权 | `CapabilityRegistry` / `CapabilityService` / `CapabilityJobs`、Scope、trusted authority | 替换注入的 snapshot/admissible/commit/released；GUI确认仍保留。不能构造万能身份绕开受控入口 |
| 资源 | `WorkspaceResources` / `ResourceLeaseService` / `HostResourceFence` / `HostResourceLock`、`WorkspaceInstance` | 保留相同物理 key/GUID、主机目录/实例 key；库存未就绪拒绝、未知保留；禁止 Qt 独立锁库 |
| 开关机 | `PipelineOrchestrator`、`PipelineProjection`、`PowerTestResumeSession`、`legacy_power_test_service`，原业务子进程 | UI 无关 projection 已支持环境检查/串口日志/legacy 三项；原 GUI 其它全流程步骤不因此自动可用 |
| 升级/写参/ONU | `FirmwareUpgradeValidation`/dispatch、`sample_parameter_service`、ONU 各 service 与受控 capabilities | Qt 保留预览/确认、目标绑定、并发钳制、实际锁源 IP、停止安全边界与未知结果处理 |
| 串口/电源/网络/WiFi | `SerialSessionManager`、serial_transport、power_supply、power_on_service、telnet_transport、WiFi scheduler/services | 原参数、命令、超时/重试/间隔不改；协议层不引入 Qt 类型 |
| 配置 | `config_store.py`、`test_item_config_store.py`、`legacy_ui_defaults_store.py`、升级/ONU stores、受控配置事务 | Qt 对话框构建 DTO，不重复定义默认值或重写 INI。保留未保存输入/编辑器互斥、资产相对路径 |
| 日志/历史 | Job SQLite/events、原结果/WiFi/串口日志、主日志过滤、`TransportHistoryMonitor`、项目/AI stores | UI缓冲有界，持久化仍走原写入链；项目/run/通道 ID 关联；不是所有旧文件都有结构化 level/run_id，无法归属时标未知 |

直接 import 扫描在 `src/services` 未发现 Tk/UI import，但这不足以证明所有注入对象无 GUI：PipelineContext.app、Capability snapshot 回调和 Workspace controllers 是必须追踪的运行时依赖。

## 5. 启动、停止与取消的实际链路

### Tk 原 GUI 开关机

主界面 `_start_all_checks()` → `PipelineWindow` → `_on_start()`（`@project_operation`）→ `workspace.admit_operation()`（保存状态检查、资源准入、任务配置快照、status.begin）→ 原选项/确认 → 主线程一次性 deepcopy 配置 → `PipelineClient`/`PipelineRun` → `start_project_thread` → `run_pipeline` → `PipelineOrchestrator.run` → `_run_legacy_power_test` → 原版本预检/配置指纹 → `run_legacy_power_test` → 旧测试子进程和原电源/通信类。

事件经 `PipelineChannel`/`PipelineDispatcher` 回到 Tk 主线程更新通道/历史/状态。主界面 `_stop_power_test()` → 恢复 session.stop 或 `PipelineWindow.request_stop()` → 原 stop/cancel token 和子模块停止 → 等原安全收尾；`project_result_handoff`、worker 活性及状态记录决定最终释放，不是按钮一按就完成。

### Capability 开关机

`CapabilityService.execute('aging.start', args, authority)` → `DeviceCapabilities._pipeline(... ('legacy_power_test',))` → `_job()` → `CapabilityJobs.start()`（身份、幂等、资源、配置快照、二次预检）→ 数据型 `PipelineProjection` → **同一个** `PipelineOrchestrator`/legacy 引擎。取消走 `jobs.cancel(job_id, authority)` → 原 stop control，返回 `stop_requested`；worker 返回真实终态才释放。重启的非终态 job 转 unknown，不重放硬件动作。

### 其它业务

升级：Tk 输入/确认 → `_start_page_upgrade` 或 `_start_full_package_upgrade` → `_launch_upgrade_run`/原 UpgradeRun/stop control → 原 dispatch/协议 service → 主线程结果回传。Capability 已有 `firmware.upgrade` 入口，不能通过 Qt 调用 `_open_upgrade_module()` 来启动。

写参：`_start_sample_parameter_write` 冻结请求 → `_sample_parameter_write_worker` → 原 batch service；取消为 `parameter_cancel_event`。ONU：原预览/目标校验 → `_on_onu_register_selected_clicked`/对应 worker → 原 service；停止 `onu_cancel_event`。查询、批量删除/保存配置保留各自风险确认，不能合并成无差别“运行”。

AI：模型/本轮对话停止与独立业务 Job 停止分离；Qt 不能把聊天停止广播为所有项目停止。

**已确认缺口**：能力矩阵当前 104 项中 connected 66、partial 16、pending 5、manual 17。`aging.stop/status` 等 partial 明确仅接管受控接口发起的 Job，旧 GUI 独立批次尚未接管；模型/权限/远程平台人工控制面并未全部服务化。此事实决定 Qt 应先接真实受控服务，不能把原 GUI 的批次号假装成可取消 job_id，也不能宣布所有功能已迁移。

## 6. 线程、资源与长期运行风险

以下为代码确认的迁移风险；除测试明确复现外，不声称已发生真实设备故障。

1. 部分 worker 仍调用 `self.after(...)` 投递 UI，UI 对象释放和退出等待与 Tk 循环有关。Qt 必须使用数据队列/Signal，不复制此调用方式，也不把 QWidget 传给原 worker。
2. 原 GUI 的 busy/stopping、ticket 完成和资源释放由工作区轮询协调；若仅重写画面会漏掉收尾、dirty、UNKNOWN 保护。Qt controller 的生命周期必须长于页面。
3. 资源准入有内存所有权、主机锁、持久化未知 fence 和物理 GUID 规范化，不能只在按钮层禁用；新旧入口共用实例与主机保护。未完成注册库存时拒绝新硬件任务。
4. 原主日志队列、Tk after、每项目 monitor/平台 pool 的所有权需逐项核查；Qt 不能在 page show 重复创建。订阅 token、generation/run_id 和取消后的迟到消息必须测试。
5. 日志已有显示裁剪/批量刷新，并不代表所有文件轮转或所有生产队列都已长期有界。保持原业务写入；Qt 可视缓存/背压另行压测，告警不得静默丢弃。
6. `WorkspaceService.list_projects/status.snapshot` 和 dirty/hash、某些 SQLite/文件操作目前在 Tk 轮询里调用。Qt 需区分轻量快照和耗时文件操作，不能原样放入高频 QTimer。
7. 持续开机全业务老化没有独立执行入口，负责人已明确尚未实现。它不是 GUI 迁移可填补的业务缺口；健康度/过期/异常持续时间没有可信数据时显示未接入，不构造虚假监控。
8. 新增 Qt 不意味着原业务可跨更多项目并发、同 DUT 可同时上下电/持续老化，所有原占用与未知约束保持。

## 7. 配置、数据和新旧入口兼容

沿用 `project.linecheck.json` format_version=1 和 UUID/revision 校验；项目 `draft/Auto_power_on_off_tool/config`、`revisions/<revision>`、`runs/<run>`、history/logs 不迁移目录、不修改 CWD。新建继续使用原脱敏模板；保存继续原 revision/原子写入；任务继续冻结配置快照。兼容单项目仍走原目录。窗口尺寸和Qt展示偏好单独存储，不覆写旧 Tk 窗口几何数据。

不建立新项目数据库或 Job 表；不通过“打开历史”隐式启动旧业务。AI/模型库、DPAPI 加密身份和本机路径保持，跨机器恢复需要原有导入/重新绑定方式，不承诺复制密文即可通用。

Phase 1 新入口计划 `run_dutpilot_qt.py --demo`，只加载明确标记的演示数据，不创建真实执行链。默认 Tk 启动入口和 `--legacy-single-project` 保持。Phase 2/3 才接同一 `WorkspaceInstance` 与资源服务；如果 Tk 已运行，则转交/拒绝而不是启动第二个无保护 Qt 控制器。正式 Qt 不嵌入 Tk，不运行 Tk mainloop。

## 8. 依赖、DPI、打包与许可审计

当前标准为隔离 CPython 3.9.10 x64、`requirements-build.txt`、PyInstaller 5.10.1/hooks-contrib 2023.2，脚本固定入口和归档/ZIP门禁保持。现有环境不安装 PySide6；单独候选开发环境与独立锁文件在 Phase 1 建立。新增 PySide6 是明确的新依赖，不能复用原 17.23MiB 结论，也不能绕过标准脚本直接交付临时 pyinstaller 包。

已联网核对官方资料和发布元数据，保存在 [qt_package_metadata.json](qt_package_metadata.json)：

- [Qt for Python 6.8 官方入门](https://doc.qt.io/qtforpython-6.8/gettingstarted.html)列 Python 3.9+，建议独立环境。
- [PySide6 6.8.3 元数据](https://pypi.org/pypi/PySide6/6.8.3/json)、[6.9.3](https://pypi.org/pypi/PySide6/6.9.3/json)、[6.10.0](https://pypi.org/pypi/PySide6/6.10.0/json)均给出 `>=3.9,<3.14` 和 cp39-abi3-win_amd64 wheel。不能仅看未固定版本的当前入门页就断言所有 6.10 不兼容 Python3.9；也不能据 wheel 存在就宣布当前构建工具组合通过。Phase 1 对选定精确版本运行导入、QPA、退出和插件专项后才写入锁。
- Qt Widgets 原型仅需 Core/Gui/Widgets；可评估 Essentials + 同版本 shiboken，是否需要 Addons 按真实模块决定，不引入 QML/WebView。原子进程的 PyQt5 headless stubs 保持，不加入真实 PyQt5。
- [PyInstaller 5.10.1 官方变更记录](https://pyinstaller.org/en/v5.10.1/CHANGES.html)有 PySide6 hook，但**不证明**该旧 hooks 与候选 Qt wheel/插件完全兼容。Phase 8 单独验证标准入口的 Qt配置、qwindows.dll、DLL/插件/中文路径/源码重启与目标电脑，不自动升级工具链。
- [Qt for Python 官方许可证入口](https://doc.qt.io/qtforpython-6/licenses.html)与[商业/社区发行说明](https://doc.qt.io/qtforpython-6/commercial/index.html)列 LGPLv3/GPLv3/商业许可。分发前按实际 wheel、Qt 模块和动态 DLL 组合保存 license/notices、第三方清单及所需源码/替换说明；当前仅做依赖审计，未完成分发合规验收。

Qt Layout/SizePolicy/QSplitter 处理伸缩，QSS 只负责局部视觉；基于系统 DPI，按 1920×1080、1366×768 和100/125/150%分别验证逻辑与物理尺寸，不能把字号乘数截图称为真实 Windows DPI 验收。

## 9. 修改清单和迁移依赖顺序

本轮新增审计工具/报告/计划与记录，不改生产测试服务。完整分阶段文件表及不变行为见 [迁移实施计划](../../../.claude/plans/pyside6-migration.md)。

依赖顺序：基线 → 独立 Qt 壳/主题/离屏保护 → 原项目数据与 model → 原 Capability 快照/确认/准入适配 → 开关机垂直模块 → 配置/串口/DUT/升级/写参/ONU/AI逐项 → 集中线程/日志压力与打包 → 负责人设备/长期验收 → 默认入口切换。持续开机老化保持待接入，不阻塞已存在功能的 GUI 迁移，也不虚报整个目标已实现。

Phase 1 演示必须清晰标识，状态徽标不能显示为已连接真实设备或“系统正常”。Phase 2 真实总览的空值/未知保留，不能继续演示占位。新 GUI 的所有业务按钮逐项审查能力矩阵，Qt-only 布局测试也要独立受管，现有 Tk 静态门禁不能当作 Qt 覆盖证据。

## 10. 回归与恢复清单

| 检查边界 | 自动化入口/目标 | 仍需真实验证 |
| --- | --- | --- |
| 项目/数据 | `test_project_management`、`test_project_completion`、`test_project_workspace`、`test_multi_project_business_validation`；临时副本 roundtrip/只读历史/dirty/快照 | Windows项目对话框/数据恢复/正常关闭 |
| 资源/身份/任务 | `test_capability_devices`、`test_capability_channels`、`test_ai_resource_guard`、`test_remote_instance_identity`；跨项目/进程冲突、未知/幂等、停止 | 原硬件范围和同机双入口保护 |
| 开关机 | `test_pipeline_orchestrator`、`test_pipeline_window`、`test_legacy_power_test_service`、`test_power_test_resume`、`test_legacy_power_initialization`、WiFi专项 | 单/多/16通道、真实上下电时序、异常停止、长挂 |
| 升级/写参/ONU/DUT | 既有各 service/app/equivalence 专项、capability专项及协议 grep | 原已验收对应现场范围，不擅自升级结论 |
| GUI线程/日志 | 隔离受管创建、主线程断言、迟到/乱序/高速日志、销毁重建、重复订阅、退出等待 | 实际DPI、实体多屏、人工键盘/鼠标、24/72小时 |
| 打包 | 原标准构建入口、完整基线、EXE/PYZ/便携ZIP/哈希/Qt插件专项 | 无开发环境目标电脑；本机不运行新EXE |

CLI统一 `python scripts/run_tests.py <模块或ID> -v`；GUI子进程通过现有 `run_gui_child(..., timeout=...)` 的私有非输入桌面，不在当前桌面闪窗。未实现 Qt 的测试保护前，不将无窗口/offscreen 插件截图冒充 Windows 原生交互验收。

恢复方式：退出新旧入口并等真实任务收尾；将 `source.zip` 解到**新的空目录**，核对 source_manifest，恢复原锁定依赖后从 Tk 源码入口运行；用 `data.zip` 的本地索引恢复到副本做打开/roundtrip，核对后再按操作员文档恢复指定配置。不得直接覆盖运行中的 SQLite、未知任务保护或唯一数据副本，不用 `git reset --hard` 丢弃当前其它改动。现有 Git HEAD 和工作区 patch 补充溯源，不能只切分支期待未提交改动自动消失。

## 11. 本检查点实际验证与放行状态

**结论：代码审计、分支与本地备份已交付；Phase 0 基线未放行，Phase 1 尚未开始。** 未创建 Qt 页面、未安装 Qt、未接入真实业务、未新增硬件操作、未构建/运行 EXE。

本轮执行的完整基线命令为 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_git_pre_commit.ps1`，由现有包装只运行标准解释器下的 `scripts/verify_baseline.py`，不做 Git 提交。日志 baseline_before.txt 已统一为 UTF-8，exit 1：

- 全量编译 273 份、源码登记 266 份、GUI 离屏静态门禁和协议必须/禁止项通过。
- `capability_coverage` 失败：记录 415 个 GUI 动作，当前 413 个；差异文件为 `app.py`、`workbench_dashboard.py`、`workbench_panels.py`，正是上一轮未完成 Tk 布局调整范围。可读矩阵同时陈旧。只读差异见 [capability_delta.json](capability_delta.json)；本轮没有为使门禁变绿而直接刷新快照，connected/partial/pending/manual 数保持。
- 全量 unittest 原生中止：输出最后位于 `test_transport_history_monitor.HistoryMonitorTests.test_main_close_waits_for_monitor_without_joining_on_ui_thread`，出现 `Tcl_AsyncDelete: async handler deleted by the wrong thread`。**最后显示的测试不等于已确认根因所在**；可能涉及前序 Tk 对象回收/后台线程，需要专门定位，不能直接归咎监控服务。没有完整 `Ran N tests`/成功汇总，未获得本轮指定关键 ID 全部执行的可信结果，不能计为全量通过。

直接相关诊断使用同一解释器经 `scripts/run_tests.py test_workbench_panels test_transport_history_monitor -v`：14 项中 13 项通过、1 项失败，详见 focused_diagnostics.txt。失败为 `test_small_window_scrolls_to_existing_controls_and_logs_resize`，真实 sash 返回 265，期望 210±5。该进程未复现 Tcl 原生中止；3 个真实窗口受管、窗口违规 0。单次定向通过监控用例不能排除全量顺序/回收问题，没有放宽或跳过原断言。

本轮通过 `run_gui_child(... native_render=True, timeout=90)` 在系统核验的非输入私有桌面运行原真实 Tk 控件，两临时项目、16 通道模拟，1366×768；创建、切页、配置弹窗、渲染及清理通过，无回调错误，受管顶层窗口 2、违规 0。记录见 tk_render_result.txt 与 [geometry](tk_baseline/geometry-1366x768-1-2.json)。没有连接设备；Source Preview / SIMULATED 为临时注入数据，所有数值仅用于布局基线。

| 本轮 Tk 原生捕获 | 观察到的参考图差异 |
| --- | --- |
| [总览](tk_baseline/overview-1366x768-1-2.png) | 深青导航已有，但顶部操作层偏高、卡片偏高、信息顺序和字重/指标密度仍不同 |
| [16通道详情](tk_baseline/detail-1366x768-1-2.png) | 状态摘要层级弱、右侧摘要长行折断、日志正文仅83px；通道需纵向滚动 |
| [展开配置](tk_baseline/config-1366x768-1-2.png) | 视口244px、内容宽244px，无外层横向扩张；16通道配置纵向内容2739px，空间利用仍待Qt重排 |
| [Telnet配置](tk_baseline/telnet-1366x768-1-2.png) | 标签/短字段与长字段宽度不统一、空白偏大，密码初始显示和切换须按新需求核对 |

本轮是审计，没有视觉修改，所以这四张是**当前 Tk 基线**，没有“Qt改造后”截图。私有桌面截图不代表人工交互、真实DPI或设备验收。此前更多修改前/阶段截图留在相邻 `../ui_visual_20261118/before/`、`../ui_visual_20261118/stage1/`。

进入 Phase 1 前：先以独立修复批次定位原生中止、修正 sash 拖动、审查 GUI 动作语义后更新能力快照并重跑完整基线；另核实现有可交付产物版本/匹配证据，不能把09月旧包当作当前原版。恢复演练在新空目录/数据副本完成，不覆盖当前唯一数据。原 Windows/真实设备/24–72小时待验收清单保持，未升级任何验收标签。
