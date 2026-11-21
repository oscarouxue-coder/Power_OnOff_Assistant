# DUTPilot Qt 迁移：语音与 TR069

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

2026-11-19，`feature/pyside6-migration`。Phase 5 的 DUT 配置窗口已接入语音和 TR069，连同此前的 Telnet、WAN、2.4G/5G WiFi，共六个配置页。正式设备测试仍使用 Tk。自动化覆盖与现场验收分别记录。

## 审计和实现

按[实施前代码审计](NEXT_VOICE_TR069_AUDIT.md)确认原配置模型、表单初值、查询能力和设备服务位置。迁移复用 `run_dut_status_query_batch`、`run_dut_advanced_config_batch`、原 UBUS 语音/TR069 回读及原 Job 资源保护。老 Tk 的语音/TR069 表单类保留，三个纯展示函数原文移到共享模块，由 Tk 和 Qt 一同导入。累计19项定义原文共享，原 Tk 剩余26项定义 AST 一致。

- 语音包括线路索引、SIP 启用、显示名、认证、代理、注册服务器、DTMF、SIP 模式、DigitMap 及五个编码。查询使用所选线路，原顺序与允许重复的编码保留。只在所有已选设备成功且完整状态一致时回填，设备能力由本机查询提取。
- TR069 包括 ACS、周期 Inform、HTTP 连接请求、证书及配置后手动 Inform。设备报告部分能力时，只启用对应字段，未提供能力时沿用原兼容规则。原查询不会勾选手动 Inform，支持时保留本次动作选择，不支持时按原界面清除。先按原业务下发及回读，手动 Inform 继续等待原结果和停止点。
- 两页共用项目目标、凭据、并行参数、一次确认、版本/NIC复核、任务状态、停止与窗口生命周期。保留登录和业务密码的本机私有回填，默认隐藏。确认、任务持久参数、公开结果和日志过滤密码、ACS URL 内嵌登录信息，模拟验证实际 values 完整传到原 UBUS 调用。
- 宽窗两列，窄窗一列，通过纵向滚动访问参数和结果，底部操作始终在窗口内。复用已有主线程刷新和工作线程，没有新增定时器或日志订阅。

## 修改文件

相对主源码目录：

| 文件 | 用途 |
| --- | --- |
| `src/models/dut_voice_tr069_form.py` | 原状态回填、能力候选和表单初值 |
| `src/ui/dut_config_window.py` | 保留旧同名导入和类的所有定义 |
| `src/services/qt_dut_voice_tr069.py` | 配置投影、设备能力、私有状态及确认信息 |
| `src/services/qt_dut_configuration.py` | 注册语音/TR069本机动作，调用原服务和Job |
| `src/ui/qt/dut_voice_tr069_panel.py` | 两页自适应表单和密码显隐 |
| `src/ui/qt/dut_configuration_dialog.py`、`src/ui/qt/workspace_controller.py` | 标签、目标、动作、日志和结果的窗口装配 |
| `tests/qt_voice_tr069_fakes.py`、`tests/test_qt_dut_voice_tr069.py` | 模拟物理边界，使用实际原服务和编排验证业务 |
| `tests/qt_workbench_probe.py` | 两项真实Windows GUI驱动、截图及布局边界 |
| `scripts/verify_baseline.py`、`scripts/verify_qt_migration.py` | 编译清单和必须执行用例 |
| `scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json` | GUI真实接入动作审查 |
| `validation/pyside6_migration_20261118/verify_wifi.py`、`verify_voice_tr069.py` | 累计共享定义/原业务保全及顺序验收 |

同步开发日志、项目交接、验收基线、能力矩阵、计划、迁移进度及操作员说明。[下一升级增量审计](NEXT_FIRMWARE_AUDIT.md)单列现有引擎和手动重启流程。

## 验证和截图

在主源码目录用标准仓库外 CPython 运行 `python validation/pyside6_migration_20261118/verify_voice_tr069.py`，依次执行专项、源码、三档原生、完整基线。独立 Qt 解释器由原生验证脚本启动。

- 64项相关回归通过，包含6项新语音/TR069用例及58项WiFi、WAN、Telnet和开关机适配回归。测试沿原 code/query 流程，替换物理网络、UBUS和等待边界。
- 源码保全通过。306份编译、296份源码登记、协议不变量、GUI/能力覆盖、原core/services及旧业务配置字节保全。累计19项提取定义和26项未移动定义 AST 相同。
- 三档原生共35×3=105项通过，每档962个受管窗口，违规0。两页检查实际默认取消、原字段、能力禁用、密码显隐和任务调用，同时覆盖总览、开关机、配置、通道、串口及前序DUT页。
- 完整基线通过，3,093项测试及239项指定用例全部执行，各编译、协议、资源和覆盖门禁通过。顺序记录和代码检查点对应本阶段源码。随后项目导入、凭据读取和状态文案的验证单列在[后续报告](QT_FOLLOWUP_REPORT.md)。

| 场景 | 改后原生图 |
| --- | --- |
| 语音 1000×740 双列表单 | 100% |
| 语音 560×460 单列表单 | 100% |
| TR069 1000×740 双列与设备能力禁用 | 100% |
| TR069 560×460 单列表单 | 100% |

改造前DUT窗口中两页尚禁用。参考图没有独立语音/TR069弹窗。现有 Qt 模块使用相同配色、按钮层级、紧凑输入和滚动方式。表单较长时需要纵向查看目标与结果；原窗口几何恢复，以及写参模块共享输入编辑仍待后续。Windows显式 Qt 缩放和模拟项目属于自动化证据，实际系统 DPI、多屏、设备读写、停止、1/8台异常隔离及长期运行仍待负责人验收。
