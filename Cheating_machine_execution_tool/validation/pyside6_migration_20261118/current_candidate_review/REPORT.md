# DUTPilot V1.3.0 Windows Qt 候选版迁移总结与测试报告

2026-11-21。在现有 `feature/pyside6-migration` 工作区上继续实施。启动文件为 `run_dutpilot_qt.py`，原 Tk 入口为 `run_line_check_assistant.py`。下表覆盖附件的全部十个阶段。现场和长期试验尚无本候选的验收结论。

## Windows 交付物

[完整便携 ZIP](../../../dist/qt-20261121-033007-cb5006d8/DUTPilot_portable.zip) · [SHA256 文件](../../../dist/qt-20261121-033007-cb5006d8/DUTPilot_portable.zip.sha256.txt) · [目录内 EXE](../../../dist/qt-20261121-033007-cb5006d8/DUTPilot_portable/DUTPilot.exe) · [标准验包报告](../../../dist/qt-20261121-033007-cb5006d8/PACKAGING_REPORT.json)

ZIP 大小 55,367,579 字节，SHA256 为 `59083acf5d26e07d793571a222608c3b181fc40ae0316454825887619db19adc`。完整解压后，目标机从 `DUTPilot_portable\DUTPilot.exe` 启动。按照项目要求，本机通过源码运行 Qt 原生用例，新 EXE 仅做静态验证。

标准构建退出 0，Windows x64 GUI、PE 产品版本 1.3.0、Qt 平台插件及依赖、脱敏模板、目录与 ZIP 的 247 个文件和校验值均已核对。另从实际 EXE 的 PYZ 解出 299 个项目模块，逐个与当前源码编译的代码对象比对，全部一致。另有一个 `src.utils` 命名空间占位条目，其模块类型和空代码已核实。包含原挂测编排器及本轮的 Qt 控制面。[成品与源码比对](packaged-source-check.json)

## 各阶段结果

| 阶段 | 当前实现与本轮证据 | 剩余条件 |
|---|---|---|
| 0 代码审计与基线 | 从 Qt 命令、原能力注册、管道和旧执行器逐层核对。重新在临时目录恢复 910 个源码文件并校验 17 个 SQLite 快照。97 份原业务及底层 Python 文件的 SHA256 与迁移前备份一致，覆盖原工具、`src/core`、电源测试服务、编排器及工作区资源管理。见[源码比对清单](source-check.json)及[原审计和目录清单](../PHASE0_AUDIT.md)。 | 原版实际操作和新版对照可使用实验室项目副本与现有 Tk 入口。 |
| 1 Qt 主窗口 | Windows Qt Widgets 工作台提供导航、总览、项目详情与日志分栏。详情窄于 850 逻辑像素时动作移到第二行。私有桌面原生专项检查了窄宽两种情况下四个按钮均在可视区域。 | 实体显示器切换、系统 DPI 与操作员目视。 |
| 2 多项目工作台 | 继续使用原工作区服务打开、保存和关联项目。相同配置值从项目草稿切到当前任务快照时，标题同步切换。项目、执行适配、旧引擎与多项目隔离专项共 116 项通过。[运行记录](power-project.txt) | 目标机用实际项目副本打开、保存、重开。 |
| 3 自动开关机挂测 | `aging.start → legacy_power_test → PipelineOrchestrator._run_legacy_power_test → run_legacy_power_test`。Qt 消费原任务事件，停止走原任务取消及收尾。上述专项覆盖模拟通道、确认、停止持锁、冲突和跨批次迟到事件。[开关机阶段报告](../PHASE3_REPORT.md) | 单、多、可用时 16 通道，对照实际电源帧、上下电时间、DUT 成败和逐台 500 轮。 |
| 4 全业务老化 | 仓库部分只有指导书及演示项。原能力注册将 `aging.start` 绑定到开关机测试。先前审计和负责人记录均说明尚无持续开机的独立执行服务。 | 需要原执行器及真实状态接口，或另立项实现并验收检测业务。当前没有可核验的周期、异常恢复、业务成功率或持续 7 天的数据。 |
| 5 其它业务及控制面 | 既有串口、升级、写参、ONU、DUT 六页和 AI 留存记录等覆盖见[逐项进度](../MIGRATION_PROGRESS.md)。本轮增加会话权限查询、人工审批、网关实例详情及撤销、按已存配置启停网关和网关配置编辑。[控制面原生专项](control-native.txt) | Qt 实时诊断的目标和执行器桥、远程平台与新实例配对等仍有覆盖差异。审批结果取决于原执行器实际产生的待确认请求。模拟请求验证了界面和决定服务适配。 |
| 6 线程及生命周期 | 网关管理在单独后台线程串行执行，工作区仍受理普通命令。退出等待已受理操作、原管理服务关闭和资源收尾。重复操作拒绝，过期对话框回执按请求标识丢弃。 | 现场网关断连、实际驱动慢关闭和长时间运行。 |
| 7 日志与性能 | 使用现有持久日志和有界显示缓存。工作区专项含四线程日志突发、界面队列拥塞、日志写入失败及恢复。网关与会话查询记录开始、结果或失败。 | 实际数日的日志完整性、异常持续时间及内存/响应记录。[长挂取证步骤](../long_run_acceptance/README.md) |
| 8 Windows 打包 | 使用原标准入口的 Qt 目录式构建、独立 CPython 3.9.10 x64 与锁定的 PySide6-Essentials 6.8.3。产物和实际检查结果见本报告的构建记录。 | 无开发环境的目标 Windows 电脑启动、既有项目打开、组件许可的正式发行复核。 |
| 9 综合回归 | 软件侧使用独立项目、模拟服务及 Windows 私有桌面。实际执行结果见下方记录。 | DUT、OLT、串口、电源、远程平台、24/72 小时与更长挂测均待现场。本次无正式发布或默认入口切换。 |

## 本轮文件与回归边界

- `src/ui/qt/project_detail.py` 调整详情页自适应布局、配置来源标题。配置参数、能力注册及开关机执行器沿用原实现。
- `src/models/qt_ai_chat.py`、`src/services/qt_ai_chat.py`、`src/ui/qt/ai_chat_controller.py`、`src/ui/qt/ai_chat_dialog.py` 增加原权限状态与具体操作审批。保存偏好、当前有效模式、取证资格分别呈现。批准和拒绝均复核当前操作编号、指纹，并交给原决定服务重新检查任务、资格和内容。
- `src/services/qt_workspace_adapter.py`、`src/ui/qt/workspace_controller.py`、`src/ui/qt/instance_status_dialog.py`、`src/ui/qt/gateway_config_dialog.py` 接入原本机网关管理。保存时再次读取配置以防覆盖期间的变化。停止和撤销各有人工确认，实例用完整 ID 绑定。后端继续使用原端点、证书、成员范围和所有者检查。
- `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py` 覆盖窗口缩放、配置来源、旧权限偏好、过期指纹、关闭审批、不同行的同名实例、全群确认取消以及模拟网关启停。编译和能力清单见 `scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json` 及根目录 `CAPABILITY_COVERAGE.md`。
- 操作员说明在 `line_check_assistant_README.md`，交接在根目录 `PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md` 和本目录报告。原设计参照与之前的 Windows 对照见[主窗口阶段报告](../PHASE1_2_REPORT.md)。本轮在窄窗口调整了动作位置，真实系统缩放与最新设计的负责人目视仍待完成。

## 验证记录

开工时首次指定了不存在的资源测试模块。改用仓库实际存在的 `test_multi_project_business_validation` 后，重新运行全部四个模块，116 项通过。恢复检查读取原备份到临时目录，原始配置及数据库未被覆盖。

现有 Tk V1.2.10 便携 ZIP 的版本说明、完整 CRC、目录内外 EXE 字节及两份 SHA256 记录均已核对。旧 EXE 没有可读的 Windows ProductVersion 字段，版本依据来自包内 VERSION_INFO。该归档可供回退，异机实际运行使用独立现场记录。[旧包核对结果](tk-archive.json)

2026-11-21 补核了归档与源码的对应关系。使用锁定的 CPython 3.9.10 读取旧 EXE 内嵌入口和 PYZ，依据仓库路径匹配出 175 个项目代码对象。与 Git 标签 `v1.2.10`（`b7e7111f`）比较，175 个均一致。用迁移前收据核验仓库外 `source.zip` 后比较相同的 175 项，其中 121 项一致，54 项有差异，包括程序入口、Tk 主窗口和旧开关机编排服务。旧 EXE 可用于回到发布版。恢复迁移前开发现场须使用 Phase 0 源码和数据备份；本次只静态读取产物。[逐模块比较](tk-archive-sources.json) · [可复验脚本](check_tk_archive_sources.py)

首次三档 Qt 运行期间继续开发了控制面，125% 档在 210 秒总限时到期时仍在执行 WiFi 用例。该批证据用于诊断。候选验收使用最终源码单独复跑的完整批次。

控制面源码工作包括三个独立检查点。首先模拟服务核对保存偏好与有效模式。随后用原项目工作区和模拟网关验证慢启动期间仍能处理项目命令、重复操作遭拒、旧配置变化时保存失败。最后在 Windows 私有桌面核对操作编号与指纹、关闭审批、同名实例撤销、保存配置、全群确认的取消路径。原生专项第一次手工调用填错测试类名；改用实际类 `QtProjectWorkspaceTests` 后，两项完整专项通过。

退出时，工作区先向原开关机任务请求安全停止，再等待网关工作及资源释放。临时项目同时运行模拟开关机和一个受阻的模拟网关启动，已观察到原停止事件、收尾前的资源占用及结束后的释放。独立模拟还确认网关关闭阻塞期间工作区保留，原关闭仅执行一次。[两项并发回归](gateway-regression.txt) · [网关关闭回执](gateway-close.json)

最终候选以仓库外的本地源码 ZIP 保存。共 703 个文件，含 691 份已列出 SHA256 的源码、测试、构建输入。ZIP 已检验 CRC，并逐文件验证这 691 份内容。路径及哈希保存在[本地快照索引](source-check.json)。当前 Git 分支上原有未提交文件和既有暂存内容保留，交接使用阶段报告与候选快照。

收尾验证中，原生测试与单独运行的退出专项在同一台主机短时争用模拟程控电源资源 `serial:com102`。原资源锁拒绝了尚未取得所有权的通道日志测试，100% 档失败，125% 和 150% 各完成 89 项。保留该批完整结果，并以独占回归时段重新跑三档。未修改原设备资源键、锁或失败断言。[资源冲突批次](final-native/results.json)

独占复跑由同一个正式 Qt 验证脚本依次执行。100%、125%、150% 各 89 项通过，共 267 次执行。三个 Windows 私有桌面均记录 1,823 个受管窗口，全部指定测试命中，隔离违规为零。[三档完整结果](isolated-native/results.json) · [按阶段和缩放查看截图](WINDOWS_SCREENS.md)

截图交付覆盖 22 个场景、每个场景三档缩放，共保留 66 张。核对目录、Git 跟踪和报告引用后，将此次三批验证生成的其余 1,043 张过程 PNG 移入回收站。各批原生测试文本、隔离报告及历史阶段目录继续保留。

## 非硬件复跑

最终标准构建在锁定 Qt 环境下先运行全部源码基线。378 份文件编译通过，368 份源码完成编译清单覆盖，3,231 项单元测试通过，239 项指定基线用例全部执行，GUI 能力/离屏覆盖和协议不变量均通过。该结果包含同一工作区退出期间的模拟开关机与慢网关回归。[最终构建与基线原文](final-build.txt)

在主源码目录使用下列入口。Qt 原生测试使用项目准备的独立环境，由测试守卫在 Windows 非输入桌面创建真实 Qt 窗口。正式包构建脚本自带环境、源码基线和实际归档检查。

```powershell
python scripts/run_tests.py test_qt_workspace_adapter test_qt_execution_adapter test_legacy_power_test_service test_multi_project_business_validation -v
python scripts/verify_qt_migration.py --output "$env:TEMP\DUTPilot-qt-repeat"
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1 -Gui Qt
```
