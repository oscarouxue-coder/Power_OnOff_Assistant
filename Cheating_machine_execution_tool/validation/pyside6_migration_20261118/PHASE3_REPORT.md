# DUTPilot Qt迁移：自动开关机受控链路接入

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

日期：2026-11-18。分支`feature/pyside6-migration`，版本V1.2.10保持。此轮是Phase 3的命令、状态与安全退出垂直模块，**整体迁移尚未完成，Phase 3尚未通过真实设备验收**。不提交、不推送、不打包、不运行EXE。

后续六标签配置编辑已接入，最新配置字段/保存/截图及剩余执行面见[配置阶段报告](CONFIGURATION_REPORT.md)。下文配置编辑待迁移等内容保留为Phase 3当时边界。

## 实际完成

- 项目详情“开始测试”提交既有`aging.start`，“环境检查”提交既有`network.line_check`；仍是原`CapabilityService → CapabilityJobs → PipelineProjection → PipelineOrchestrator → legacy_power_test_service`。没有复制设备控制代码、隐藏Tk窗口或模拟旧按钮。
- 先使用原管道的配置就绪检查，再由本机操作员确认项目、明确通道、VLAN/网卡/COM、轮次及等待参数。确认一次有效、两分钟过期，绑定项目版本及全部草稿/保存配置字节；确认期间配置变化拒绝。真实NIC身份读取后，原主机GUID资源保护、幂等、未知结果和任务配置快照继续生效。
- Qt只提交本机GUI身份、绑定明确通道；没有新增AI或远程权限，不建立替代项目库、任务表或资源锁。其它项目使用相同物理资源仍被原协调器拒绝；当前Qt控制面一次只准入一个设备任务，即使物理目标不同，也须等前一任务实际收尾，硬件并行另待验证。
- 任务运行、停止中、终态、轮次和逐通道状态来自原任务与结构化事件。未收到通道事件前保留未知，不将勾选当运行；无法证明的成功次数不填0或虚构统计。当前配置摘要和通道绑定读取该次runs快照，外部草稿修改不会把正在执行的目标换名。
- 停止只请求当前Qt准入的原任务，保持“停止中”直至业务实际结束；不接管旧Tk/远程批次。关闭活动项目及退出须明确停止，后台等待线程与串口收尾后才释放项目、任务存储和工作区。页面切换不取消任务。
- 显示刷新保留模型身份、导航选择/折叠状态；配置摘要不因每秒运行时间变化反复销毁重建。通道正常、失败、重试及未知使用相应颜色，运行时按钮状态来自服务快照。

## 文件清单

| 文件（相对主源码目录） | 变化 |
| --- | --- |
| `src/services/qt_execution_adapter.py` | 新增无GUI的确认、原任务准入、事件投影、安全停止/清理 |
| `src/services/qt_workspace_adapter.py` | 串行接入测试命令、run配置快照、关闭等待；写盘日志串行保护 |
| `src/models/workbench_presentation.py` | 增加可启动/可停止、当前阶段展示字段 |
| `src/ui/qt/workspace_controller.py` | 确认/取消、环境检查、开始/停止、关闭操作接入 |
| `src/ui/qt/project_detail.py` | 控件状态、运行阶段、通道颜色、配置复用 |
| `src/ui/qt/main_window.py` | 活动任务导航、刷新选择保持、真实状态栏 |
| `src/ui/qt/dashboard.py` | 相同项目身份更新数据，不重置模型 |
| `src/ui/qt/theme.py` | 共用运行/停止中/终态状态样式 |
| `tests/test_qt_execution_adapter.py` | 11项新服务回归，原任务/资源/快照真实，物理执行替换 |
| `tests/test_qt_workspace_adapter.py` | 增加不同物理资源仍串行准入、活动项目不提前关闭和安全收尾后释放的回归 |
| `tests/qt_execution_fakes.py` | 仅临时目录的测试配置、受控模拟执行器 |
| `tests/qt_workbench_probe.py` | 新增本机取消、配置变化拒绝、开始/切页/停止/退出及刷新保持测试 |
| `scripts/verify_qt_migration.py` | 强制执行全部16项原生用例，三档缩放 |
| `scripts/verify_baseline.py` | 登记新服务编译及4项关键回归ID，不改变触发条件和协议清单 |
| `scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json` | 审查真实Qt入口、更新446动作快照；104项业务状态不虚增 |
| `validation/pyside6_migration_20261118/verify_phase3.py` | 编译/登记/协议/覆盖及原业务字节保全的可重复检查 |

另同步根目录`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`、`.claude/plans/pyside6-migration.md`及操作员`line_check_assistant_README.md`。原服务、协议、旧测试业务和本机配置未改写；Git中此前的Tk/测试工作区改动保留。

## 改造前后与视觉验收

下列均为真正创建的Windows Qt窗口捕获，使用经系统核验的非输入私有桌面，不切换用户桌面。执行截图明确标记**模拟设备验证**：真实临时项目、原任务服务，只有物理执行器被替换，不代表DUT现场结果。

| 场景 | 本轮前 | 本轮后 |
| --- | --- | --- |
| 详情布局/操作 | Phase 2详情，设备按钮禁用 | 模拟运行：原任务、68/100轮、通道和run配置 |
| 停止等待 | 尚无Qt控制链 | 安全收尾前仍显示停止中 |
| 大窗口总览 | Phase 2总览 | 本轮总览 |
| 小窗口详情 | Phase 2详情 | 本轮1366布局 |
| 三档缩放 | 前轮12项/档 | 125%、150%，本轮16项/档 |
| 全业务老化 | 待接入 | 继续待接入，无虚构探针和趋势 |

与负责人最新参考图的剩余差异：总览还没有完整告警中心/系统健康卡；详情采用共用的运行概览/开关机展示，尚未完成全部专属功能页、通道矩阵/列表切换、失败轮次续跑的Qt控制面及六标签配置编辑。通道数和空白按真实已配置数量呈现，不填假通道。成功次数没有可靠的累计事件来源时显示未知；不将轮次或通道数改名为成功次数。图标/环形进度、全业务探针/健康趋势及全部业务模块尚未达到参考图完成态。

运行中的主要状态、摘要、通道、配置与日志没有横向裁切；右侧配置内容较多时允许垂直滚动。截图的1920请求受Windows可用工作区限制，部分高度为1061；显式Qt缩放不是实际Windows系统DPI切换验收。

## 验证命令与结果

以下从主源码目录执行，`$qtPython`为仓库外独立开发环境`$env:LOCALAPPDATA\LineCheckAssistant\qt-dev-py39\Scripts\python.exe`。

```powershell
& $qtPython -X utf8 scripts/run_tests.py test_qt_execution_adapter test_qt_workspace_adapter test_qt_migration_contract test_capability_devices test_capability_extensions test_pipeline_orchestrator test_power_test_resume test_verify_baseline test_capability_coverage -v
& $qtPython -X utf8 scripts/verify_qt_migration.py --output validation/pyside6_migration_20261118/qt_phase3_final_acceptance
& $qtPython -X utf8 validation/pyside6_migration_20261118/verify_phase3.py
git diff --check
```

| 检查 | 实际结果 |
| --- | --- |
| 相关回归 | 146项通过，含11项新服务测试；2个受管Tk窗口/违规0 |
| 原生Qt | 16项×3档=48项通过，全部指定ID实际执行，每档14受管顶层/违规0；Windows QPA，系统核验私有桌面 |
| 源码门禁 | 288份编译、278主源码登记、能力/GUI覆盖及协议项通过 |
| 原实现保全 | 对Phase 0备份哈希检查：162份原core/services、38份旧工具Python、7份非Python配置、原Tk app.py均字节一致；这是该脚本明示的文件集合，不代替所有设备验收 |
| 完整基线 | 本轮新增独立适配并修改尚未验收的Qt页面，未搬迁原已验收业务；未触发/未运行完整基线。最近2981项是前轮结果，不表述为本轮全量通过 |
| 差异 | `git diff --check`通过；没有提交、构建、外发消息或真实设备操作 |

历史失败保留：首轮原生新增用例缺少测试夹具的`app`引用，三档各1项错误，修正测试夹具后全部通过（`qt_phase3`）；最初相关回归命令将现有`test_power_test_resume`写成不存在的`test_power_test_resume_service`，报告1项导入错误，修正命令后119项及最终146项通过。没有放宽断言、跳过用例或改变原业务来消除失败。

## 尚未完成

- Phase 3的负责人真实设备验收：相同配置下单/多通道正常完成、主动停止、DUT/串口/电源异常、真实时序及长挂；只有Fake/Mock验证，不升级旧验收结论。
- Qt完整配置编辑、通道列表/失败续跑控制面、其它业务页、AI/平台、完整告警/历史/日志导出和资源摘要仍待逐项迁移。
- 持续开机全业务老化尚无独立业务服务，按负责人既有答复保留待接入，不借GUI迁移新增检测引擎。
- 实际系统DPI100/125/150%、实体多屏、24/72小时运行、Qt许可/插件/DLL/标准打包及无开发环境目标电脑待验收。

正常挂测继续原Tk入口。Qt源码启动方式保持`run_dutpilot_qt.py --workspace`；`--demo`始终没有硬件执行入口。整体迁移完成前不切换默认入口。
