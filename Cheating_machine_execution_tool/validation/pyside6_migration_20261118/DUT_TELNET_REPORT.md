# DUTPilot Qt迁移：DUT Telnet增量

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

后续增量已继续接入WAN，见[WAN阶段报告](WAN_REPORT.md)；下方是本轮Telnet检查点的历史范围和结果。

2026-11-18，`feature/pyside6-migration`。继续Phase 5，交付原DUT配置中的Telnet开启与当前状态查询垂直链路；不是整个DUT模块、Phase 5或GUI迁移完成。Tk默认入口保留，持续开机全业务老化保持负责人明确的待接入状态。

## 代码审计与实施边界

原`src/ui/dut_config_window.py`拥有六个Tk标签、目标选择、公共凭据输入和结果显示；`app.py`收集请求、确认、启动线程并消费队列。实际Telnet开启、重试、TCP验证和安全点在`dut_config_service.py`，只读状态查询、登录注销在`dut_status_query_service.py`；原`DeviceCapabilities`已经有资源准入、运行快照和Job包装。

新Qt服务直接复用两个原批量/单台服务，通过原`DeviceCapabilities._job`、CapabilityJobs和工作区资源保护执行。只新增数据适配，不调用旧Tk回调、不创建隐藏Tk、不更改原service/core。Qt适配器的原准入检查和网卡身份复核提取为同文件小方法，供开关机和DUT共用；原开关机适配回归仍须执行。

本轮保留：原网卡按需准备和源IP绑定、UBUS AccessCtrl协议、TCP 23判据、原重试/延时、默认1和最大8的单批并行、逐台失败隔离、停止后不再派发未开始DUT及等待已进入调用的安全点。Qt仍只准入一个设备业务任务，不扩展跨项目硬件并发。

## 已接入行为

- 详情“DUT配置”打开当前项目Qt窗口，只加载候选，不连接设备。独立勾选、全选/清除，只有选中目标参与预检与执行；空目标、缺字段、重复VLAN和错误IP拒绝。
- 账号/密码初值读取原`parameter_initial_*`，密码默认隐藏并可显示；当前项目窗口会话保存输入草稿，关闭重开不丢已填值，不自动改写原配置文件。与尚未迁移写参页的跨窗口联动仍待后续接入。
- 开启和查询都显示实际项目、目标、源/目标IP、并发数的默认取消确认；查询不写DUT参数，但原流程会准备本机网卡/IP，因此同样说明并确认。确认两分钟内一次有效，复核全部配置/项目版本、网卡GUID、历史未知/资源和其它任务；配置变化不执行。
- 原Job负责实际运行、快照、停止、记录和资源释放，窗口只消费后台纯数据。逐台结果和原Telnet AccessCtrl/规则/TCP状态分别展示，查询完成不代表测试健康度正常，不伪造轮次进度。
- 停止显示实际请求状态并等待原worker退出；切页、切项目或关闭DUT显示窗口不取消任务。重新打开回到原Job；项目/应用安全退出仍请求停止并等待实际收尾。
- 运行期间目标沿本次任务快照，外部草稿变化不重标运行目标。选择或候选变化清空旧状态展示，旧任务结果保留在原记录；新目标不沿用旧查询结论。
- `dut.editor.*`只供GUI，AI/钉钉/飞书来源拒绝。密码不进入确认摘要、Job参数/结果和Qt主执行日志；原service打印的实际命令及关键阶段经仅隐藏凭据值后保留。原Tk日志/明文规则未修改。
- 复用主控制器100ms定时器，300ms有在途保护的显示轮询；不新增原设备线程、UI监听或窗口定时器。所有控件更新在主线程，文件/设备操作在原队列和Job中。

## 修改文件

相对主源码目录：

| 文件 | 用途 |
| --- | --- |
| `src/services/qt_dut_configuration.py`（新） | GUI能力、目标与确认、原Job/服务、凭据过滤和窗口数据 |
| `src/ui/qt/dut_configuration_dialog.py`（新） | 布局、目标勾选、显隐、结果、执行/停止/关闭 |
| `src/services/qt_execution_adapter.py` | 共享原准入与NIC检查、DUT任务状态与安全退出 |
| `src/services/qt_workspace_adapter.py` | 后台DUT命令和结果、跨项目单任务准入、静默显示轮询 |
| `src/ui/qt/{project_detail,workspace_controller}.py` | 入口、每项目窗口、异步确认和原轮询复用 |
| `tests/qt_dut_fakes.py`（新） | 原批量/单台service配模拟网络、UBUS、TCP边界 |
| `tests/test_qt_dut_configuration.py`（新） | 服务准入、原调用、停止/异常/会话/权限专项 |
| `tests/qt_workbench_probe.py` | 取消/批准、原生窗口、切页、关闭重开、停止与响应测试 |
| `scripts/{verify_baseline,verify_qt_migration,verify_capability_coverage}.py` | 编译、必须执行ID、能力解释 |
| `scripts/capability_gui_actions.json` | 审核更新GUI动作快照 |
| `validation/pyside6_migration_20261118/verify_dut_telnet.py`（新） | 源码门禁与原DUT边界字节比对 |
| `validation/pyside6_migration_20261118/verify_dut_delivery.py`、`MIGRATION_PROGRESS.md`（新） | 顺序验证编排和完整计划逐项进度 |
| `line_check_assistant_README.md` | Qt实际操作与边界 |

根文档同步`README.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`、`.claude/plans/pyside6-migration.md`和生成的`CAPABILITY_COVERAGE.md`。其它既有工作区差异保留，不算作本轮改动。

## 原生截图与参考图差异

改前Qt DUT入口禁用，独立Qt窗口不存在：上轮详情，不能虚构独立Qt窗口的改前截图。模拟项目明确命名，实际Windows QPA运行在核验非输入私有桌面，未切换用户桌面。

| 场景 | 改前/中间检查 | 最终 |
| --- | --- | --- |
| 宽窗口1000×740 | Qt窗口原先不存在；目标区偏矮的首个可运行版本 | 两行目标完整显示，100%、150% |
| 窄窗口560×460 | 被最小高度撑到约550的版本、实际尺寸记录 | 100%、150% |
| 窄窗口结果可达 | 原版本窗口被撑大，未证明请求尺寸成立 | 125%滚动到底部、150% |

沿参考图统一青色、卡片/字号层级；布局使用Qt Layout、纵向可调分栏和滚动，底部操作始终可见。DUT独立窗口并无参考图中的对应稿，不宣称像素完全一致；其余五个DUT标签保持禁用与待接入说明，不以外观窗口冒充完整业务迁移。

## 验证记录

- 28项相关服务回归通过，包含17项新DUT和11项原开关机适配回归。使用真实原批量/单台服务和Job/资源，替换网络准备、UBUS客户端/启用及TCP探测物理边界；覆盖目标/并发、确认取消/一次性/过期/配置变化、旧凭据草稿、NIC、失败未知、不重放、共享准入拒绝后的旧结果、停止等待、关闭重开及非当前任务识别。未连接真实设备。首轮23项为增补保护用例前的记录。
- 本轮完整基线通过：3057项测试、229项指定回归实际执行，298份编译、288份源码登记、493动作覆盖、GUI测试保护与全部协议不变量通过，`ALL CHECKS PASSED`、exit 0。顺序执行记录保留原生/完整基线/源码三阶段结果。
- 完整基线后仅修改新Qt DUT窗口的纵向滚动容器及对应原生尺寸/可达性断言两份代码。没有再次运行完整基线；基线时文件哈希与最终布局检查区分这两版，不将前版完整编译记录冒充最后布局源码。业务适配/原服务/任务逻辑保持相同；最后布局执行完整三档原生及源码门禁。
- 最后布局的强制29项×3档=87项原生验证全部通过，实际窗口尺寸与请求一致：100%为560×460像素、125%为700×575、150%为840×690，结果区可滚动访问，底部按钮可见。见本轮最后原生记录。原有串口、配置、通道、开关机和工作台强制用例均保留，不加跳过，不绕过私有桌面/主线程守卫。Qt显式缩放不是实际Windows系统DPI切换或实体多屏验收。
- 最后源码检查通过：298份编译、288份登记、493动作覆盖、GUI预检及协议不变量通过；162原core/services、38旧业务Python、7本机非Python配置及app.py与Phase 0备份一致，另明确比对DUT UI/模型/服务/core及原能力适配九份边界均一致。
- 本轮最终核对通过：基线后只有上述两份UI/原生测试代码变化，业务适配哈希保持；三档尺寸、87原生及原业务保全均通过。文档链接检查及`git diff --check`通过，暂存区为空。完整计划与仍缺证据见[迁移逐项进度](MIGRATION_PROGRESS.md)。

复验命令（主源码目录，标准仓库外Python；native与原业务Mock按顺序）：

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
python scripts/run_tests.py test_qt_dut_configuration test_qt_execution_adapter -v
python scripts/verify_qt_migration.py --output validation/pyside6_migration_20261118/本次原生目录
python scripts/verify_baseline.py
python validation/pyside6_migration_20261118/verify_dut_telnet.py
```

已保留失败：`qt_dut_telnet_first`在三档发现复选框测试点击了控件空白，改为实际indicator；`qt_dut_telnet_review`随后抓出Qt“No”枚举非零、被当成真值的实际取消路径错误。生产代码已改成明确比较Yes，保留“取消后原服务零调用”断言，不删除或放宽。均为模拟边界，未对真实网卡、串口或DUT执行操作。

截图复核发现原`qt_dut_telnet_final`虽已有87项通过，但测试只检查内部按钮，没有断言窗口确实保持请求高度；560×460被撑到约550。添加内容滚动容器以及实际宽高/滚动到底可访问结果的断言，后续截图独立保存，不把早先绿色结果当成最终小窗口通过。PowerShell首个服务测试日志对unittest正常stderr附加NativeCommandError，进程仍exit0/28项OK，已转UTF-8保留；完整门禁使用整个进程树UTF-8及subprocess明确收集，不更改原测试解码或保护。

## 后续与人工边界

继续接入WAN/WiFi/语音/TR069全部查询、编辑、能力约束、递增/双频、确认与原批量执行；随后升级、写参、ONU、AI/平台、全局工具、完整历史/日志/可靠性和Qt标准构建部署。完整计划保持活动，不能以本增量替代整个目标。

本轮不执行真实硬件或长期挂测、不启动EXE、不提交/发布。正常挂测继续Tk。真实Telnet状态准确性、1/8台异常/并行、实际网卡/设备调用与退出、安全停止、系统DPI/多屏及24–72小时仍需负责人确认；原Tk现场验收标签不升级为Qt通过。
