# DUTPilot Qt迁移：原型与项目管理阶段交付

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

日期：2026-11-18。分支：`feature/pyside6-migration`。版本仍为V1.2.10；未提交、推送、打包或发布。

本报告保留Phase 1/2当时边界。后续已增加原自动开关机/环境检查与安全停止的Qt适配，最新文件、结果、截图及未完成项见[Phase 3报告](PHASE3_REPORT.md)，下文“设备按钮禁用”等为前轮状态。

## 当前结果

已恢复迁移前自动化基线，完成独立Qt工作台原型，并接入原项目服务的基础生命周期。**整套GUI迁移尚未完成**，Qt中的设备执行、配置编辑、升级/写参/ONU/串口/DUT/AI等仍待逐项接入；正常测试继续使用原Tk入口。持续开机全业务老化仍无独立服务，保持待接入。

原Tk入口没有删除或改为Qt，旧GUI没有嵌入Qt，也没有通过模拟点击复用业务。原产品/数据路径、资源保护、协议和测试引擎保留。

## 阶段0收尾：恢复基线与保护原行为

1. 复现日志分隔条失败，跟踪了Tk的原生sash事件与延迟布局。改用随容器变化的pane首选高度，移除布局回调内同步sash_place；拖动测试执行真实按下/刷新/拖动/释放序列，保留210±5位置断言，并增加按下不跳位、迟到内容不重置用户位置的检查。
2. 新增独立回收fixture，证明上一个unittest案例的已销毁Tk循环引用仍可进入下一项测试。测试入口在下一项测试启动前用主线程GC清理，此时unittest已释放上一案例；避免后续后台线程首次触发回收。此修复属于测试生命周期，不修改产品GC或监控业务。原全量中止最后出现在资源监控用例附近，不据此将监控服务认定为根因。
3. 审查既有app/dashboard/panels未完成布局变化，保持原业务回调与能力状态，更新动作快照。Qt后续信号connect、菜单addAction和UI子目录亦纳入审查。
4. 修复后原Tk完整基线2969项、205项指定回归、273份编译/266源码登记及覆盖/协议项全部通过，见修复基线。初始失败和定向诊断保留在[初始审计](PHASE0_AUDIT.md)及相应日志中，不覆盖历史。
5. 备份恢复演练在新的临时目录验证910份源码哈希、17份SQLite快照quick_check；没有覆盖原数据或运行EXE，见[恢复结果](restore_result.json)。现有09月EXE已留存，但与当前源码的版本匹配仍未建立，不把它当作本轮新构建。

## 阶段1：独立Qt原型

已完成：

- `QMainWindow`、独立入口、深青色工具栏/导航、`QStackedWidget`、水平/垂直`QSplitter`和状态栏。
- 统一设计变量、字体层级、按钮/禁用态、卡片边框、间距与状态色；不改Tk全局主题。
- 四项指标、虚拟化卡片/表格共用模型，单项目使用整行宽度；名称搜索、状态筛选、表格排序、侧栏折叠与项目详情切换。
- 进度/时长/任务ID摘要、16通道矩阵、通道快照对话框、可折叠只读配置摘要；小窗口优先留出运行区域。
- 全局/项目日志过滤、级别/关键词、自动滚动、清空显示、拖动/折叠；显示最多5000条且受1Mi字符预算限制。没有接通的日志导出禁用。
- `--demo`数据只来自独立演示模块，顶栏/状态栏明确演示标识；开始/停止/环境检查及未迁移业务禁用。演示老化页不显示虚构的进度或健康检测。
- Qt原生隔离：QApplication前核验私有桌面、完整加载并保护PySide懒加载的控件构造器、主线程检查、对话框拦截、作用域清理及独立证据。只使用Windows QPA，不回退offscreen插件或当前用户桌面；没有新增跳过或整文件豁免。

原型早期三档9项共27次通过；最终统一重拍/复验增加单实例与真实项目检查，详见下节。以最终图和结果为准。

### 实际截图与参考图差异

截图来自真实Windows Qt Widgets和原生平台插件的`QWidget.grab()`，不是设计图或HTML。抓图均在非输入私有桌面，不切换用户桌面。

| 界面 | 改造前Tk | 当前Qt（明确演示） | 剩余差异 |
| --- | --- | --- | --- |
| 总览 | [Tk总览](tk_baseline/overview-1366x768-1-2.png) | Qt宽屏总览、常见窗口 | 已接近参考图的区域/颜色/卡片层级；图标、圆形进度、细部字重/间距仍不同。少量项目时空余面积用于可调整日志，不补虚假监控 |
| 详情/16通道 | [Tk详情](tk_baseline/detail-1366x768-1-2.png) | Qt详情 | 核心摘要/矩阵与配置分栏已有；设备操作未接通，功能标签尚不是已迁移的执行页面 |
| 较小窗口/150% | [Tk早期模拟记录](../ui_visual_20261118/before/) | Qt详情150% | 窄窗口默认折叠配置、可按需展开；实体多屏/系统DPI切换及人工交互仍待复验 |
| 全业务老化 | 无独立实现 | 待接入页 | 无检测引擎/健康度/最近检测时间；不以开关机业务冒充 |
| 配置弹窗 | [原Telnet窗口](tk_baseline/telnet-1366x768-1-2.png) | 本阶段仅配置摘要 | 六标签完整QDialog、显密/保存、原字段校验仍属后续迁移 |

Qt显式缩放测试使用`QT_SCALE_FACTOR=1/1.25/1.5`，属于Windows原生插件下的缩放模拟，不等于修改并验收Windows系统显示设置。1920×1080环境的原生窗口受系统工作区/标题栏限制，100%捕获客户区实际为1920×1061；150%约1280×707逻辑像素，详见每档geometry JSON。1366×768按DPR取整记录实际尺寸，不将请求尺寸伪装成捕获结果。

## 阶段2：真实项目基础管理

已接入真实文件服务：

- 新建/打开/保存/重命名/另存为独立项目/关闭；项目菜单及侧栏右键保留常用操作的可发现性。
- `QtWorkspaceAdapter`在单一后台线程串行调用原`WorkspaceService`、`ProjectStore`、`ProjectStatusService`和配置store；UI只提交命令、消费不可变快照。
- 原`project.linecheck.json` format_version=1、UUID、revision、draft/revisions/runs/history与配置值继续使用。无第二套项目数据库、资源锁或测试调度器。
- 有界命令准入/结果保留、刷新合并、有界显示日志；正常刷新静默，不每秒打印成功日志。项目动作的开始、成功/失败有执行记录，成功事件关联真实project_id；原服务的无结构日志仍标为全局项目管理，不强行猜测来源。
- 历史非终态不显示为活任务；已勾选通道显示未采集/未知，不当成RUNNING/PASS。未配置的DUT、轮次、成功次数、运行时长显示缺失值，不补演示数据。
- dirty草稿关闭前明确保存/放弃/取消；文件工作实际结束才关闭窗口。加载失败的新项目释放原写入lease，保留文件供核对。
- 新旧GUI复用原`WorkspaceInstance(workspace_data_dir())`；已有Tk工作区接收打开请求后，新Qt入口不建立第二个主窗口/控制链。不注册AI/网关/平台或新增硬件任务权限。

真实接入截图：两个真实临时项目。这里项目由原ProjectStore创建和保存，数据来自临时项目文件；没有真实DUT。它与演示总览的运行数/进度不同，正是因为没有测试任务。

复用模块：`WorkspaceService`、`ProjectStore`、`ProjectContext`、`ProjectStatusService`、`ChannelConfigStore`、`workbench_status_service.TASK_NAMES`、`WorkspaceInstance`、原资源/未知保护。未调用`aging.start`、串口/电源、升级/写参/ONU/DUT执行服务。项目管理仍沿用原`projects.*`的本机人工控制边界，没有伪造AI能力准入。

本阶段尚未完整覆盖旧项目管理控制面：旧配置目录导入、全部历史检索、远程项目授权/多实例管理、配置编辑器恢复及各业务的Qt控制仍待后续。此处是基础项目管理垂直模块通过，不宣称整个Phase 2或软件迁移已全部验收。

## 修改文件

仅以下为本检查点修改/新增；同一工作区中更早的改动继续保留，不据Git总差异认领为本轮实现。

| 范围 | 文件 |
| --- | --- |
| 入口/依赖 | `run_dutpilot_qt.py`、`requirements-qt.txt`、`scripts/setup_qt_environment.ps1` |
| Qt视图 | `src/ui/qt/__init__.py`、`application.py`、`main_window.py`、`theme.py`、`demo_data.py`、`dashboard.py`、`project_detail.py`、`log_panel.py`、`workspace_controller.py` |
| 数据/适配 | `src/models/workbench_presentation.py`、`src/services/qt_workspace_adapter.py` |
| 兼容/原Tk布局 | `src/ui/__init__.py`（保持原导出的懒加载）、`src/ui/workbench_panels.py`、`tests/test_workbench_panels.py` |
| 测试设施 | `scripts/run_tests.py`、`scripts/run_gui_child.py`、`scripts/qt_test_guard.py`、`scripts/verify_gui_test_coverage.py`、`scripts/verify_qt_migration.py`、`tests/tk_test_windows.py` |
| 回归用例 | `tests/test_gui_test_coverage.py`、`tests/test_qt_migration_contract.py`、`tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`tests/fixtures/{tk_gc_lifecycle_probe,qt_guard_probe}.py` |
| 门禁/覆盖 | `scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`、根`CAPABILITY_COVERAGE.md` |
| 文档 | 根`README.md`、`AGENTS.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`、`.claude/skills/line-check-dev/SKILL.md`、`.claude/plans/pyside6-migration.md`、主源码`line_check_assistant_README.md`、`THIRD_PARTY_NOTICES.md` |
| 证据 | 本目录阶段报告、`verify_restore.py`、恢复/保全JSON、原生截图/geometry/测试日志、完整基线及专项输出 |

所有源码相对路径均以主源码目录为准。新源文件已纳入编译清单；动作覆盖扩展到Qt子目录、信号和菜单，443项快照经过审查；业务目录仍104项（66 connected /16 partial /5 pending /17 manual），不能把该全产品后端矩阵称为Qt页面覆盖率。

## 实际验证

| 检查 | 命令 / 结果 |
| --- | --- |
| 阻断修复与回归 | `scripts/run_tests.py test_gui_test_coverage test_tk_test_windows test_workbench_panels test_transport_history_monitor -v`：43项通过；原项目/面板/监控35项通过；相关6项通过 |
| 本批相关组合 | `scripts/run_tests.py test_qt_migration_contract test_qt_workspace_adapter test_gui_test_coverage test_capability_coverage test_workbench_panels test_project_workspace -v`：61项通过，26受管Tk窗口/违规0；日志 |
| Qt原生终验 | `python scripts/verify_qt_migration.py --output validation/pyside6_migration_20261118/qt_phase2`：12项×3档=36项，全部指定ID实际执行，Windows QPA，每档10受管顶层/违规0；结果及各档tests.txt |
| Qt依赖 | 6.8.3 Essentials + 同版shiboken，Windows轮子SHA256锁定；独立Qt开发环境补原固定项目服务依赖，`pip check`/版本核对通过；原Tk环境未装Qt |
| 保护原代码/配置 | [保全比对](preservation_checks.json)：162份原core/services、31份旧测试业务、10份本机配置及原app.py全部与迁移前快照逐文件相同 |
| 备份恢复 | [恢复检查](restore_result.json)：910源码哈希、17 SQLite快照通过；没有覆盖原目录/运行EXE |
| 完整基线 | 本批因兼容导出结构调整执行原完整门禁：2981项测试、211项指定回归、287份编译、277份源码登记、能力/GUI覆盖和协议项全部通过，`ALL CHECKS PASSED`、exit 0；日志 |

失败尝试也保留：首轮Qt线程负向探针发现PySide懒加载导致只拦到已加载构造器，现先加载全部导出类型再安装保护；定向复验能够在错误线程进入Qt原生构造前拒绝。真实项目UI测试首轮QTest.qWait阻碍Python文件worker进展，改为主线程processEvents并显式释放测试等待的GIL，未改产品执行/业务等待时间。能力覆盖在语义审查后更新，不放宽断言、不增加跳过。最初PyPI元数据请求超时后用已下载轮子生成SHA锁，独立环境按锁核对；没有升级原构建工具链。

## 运行与后续边界

从仓库根可执行：

```powershell
& "$env:LOCALAPPDATA\LineCheckAssistant\qt-dev-py39\Scripts\python.exe" .\Cheating_machine_execution_tool\run_dutpilot_qt.py --demo
& "$env:LOCALAPPDATA\LineCheckAssistant\qt-dev-py39\Scripts\python.exe" .\Cheating_machine_execution_tool\run_dutpilot_qt.py --workspace
```

其它电脑先按操作员说明准备独立环境，不复制虚拟环境。Qt环境当前只用于源码开发，不能替代标准构建入口。Qt许可/插件/DLL/目录包/目标电脑验证仍属Phase 8；没有Qt EXE可发布，也没有宣称当前PyInstaller与Qt组合已完成部署验收。

下一垂直模块是原自动上下电业务的Qt命令/确认/任务事件适配与Fake等价回归，之后由负责人验证真实时序。全业务老化保持待接入；其它模块、完整配置QDialog、全链路日志导出/历史/持久化关联和资源仪表仍待原服务逐项接入。线程桥、退出安全、未知保护必须随每项接入验证，不等最后统一补。

尚未验收：负责人正常桌面键鼠/实体多屏、Windows系统100/125/150%切换、真实设备/模型/平台、24/72小时挂测、Qt打包及无开发环境目标电脑。当前源码测试和原生捕获不能替代这些结论。回到Tk只需关闭Qt源码入口并使用原启动脚本；若需要文件级恢复，原仓库外快照与恢复演练仍可用。不要直接覆盖正在使用的SQLite或未知任务保护文件。
