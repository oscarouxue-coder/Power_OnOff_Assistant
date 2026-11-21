# DUTPilot Qt迁移：WAN配置增量

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

2026-11-18，`feature/pyside6-migration`。本轮继续Phase 5，接入DUT WAN查询、新增/修改/删除及全部原字段。源码已实现；最后确认端口文案修正后的原生复验因输入桌面不可读而未完成，不能标记本增量全部验收通过。不是整个DUT模块或整份迁移计划完成；WiFi/语音/TR069、其余模块与部署/现场验收仍待后续，默认正式测试入口仍Tk。

## 审计与保全边界

原`dut_wan_query_service.py`负责网络准备、源IP绑定、查询/登录注销、原重试/停止和批量并发；`common_wan_connection_names/details`负责所有目标的严格共同名称/完整详情。原`dut_advanced_config_service.py`负责请求校验、批量/单台执行和安全停止，`dut_ubus_config.py`生成实际UBUS命令/payload并判断Result。上述业务代码未修改。

旧Tk文件内有纯展示常量、LAN位掩码、WAN规则与回填函数。原文提取11项到`src/models/dut_wan_form.py`，旧模块保留同名导入代理，Qt直接调用共享模型；未搬迁DutConfigWindow类。对Phase 0备份校验哈希后进行AST比对：11项提取定义完全相同，旧Tk剩余34项定义也完全相同；不是把旧Tk文件整体哈希变化隐藏为“文件未改”。原导入身份及不加载Tk的纯模型测试单列验证。

## 已实现

- DUT窗口使用同一套凭据、候选/独立勾选、并发和运行状态，Telnet/WAN之间切换不改目标或停止任务，其余四页保持禁用。
- WAN全字段：新增/修改/删除、共同连接名/索引、桥接/路由、业务类型、业务/组播VLAN、优先级、LAN1–LAN8、MTU、NAT、IPoE/PPPoE、IPv4/IPv6/双栈及动态/静态地址、网关/DNS、PPPoE凭据。密码默认隐藏、可显示；普通短字段限制最大宽度。
- 直接复用原显隐/回填/协议规则：PPPoE MTU1492、IPoE1500；双栈静态组合与PPPoE限制、桥接业务类型和默认绑定、IPTV组播字段；隐藏字段保留原值。查询端口位掩码保留未在LAN1–8展示的位，修改勾选不丢其它绑定。
- 查询只使用窗口已选目标；所有目标成功才产生共同名称，完整详情完全一致才回填，不拿任一台特例当作共同配置。详情不一致仍可选择共同名称删除，修改前动态提示人工核对。
- 修改/删除预览及执行均核对查询ID、目标顺序、凭据、项目配置版本与共同名称；目标/凭据变化清空前端缓存，旧结果不能重新自动填入。配置变化、确认过期、资源冲突、未保存/其它任务均拒绝，准入失败保留上一查询供再次明确操作。
- 开启执行仍是原Job/资源/项目快照和原批量/单台service，不改变UBUS payload、重试、时序或Result判据。确认默认取消，删除明确提示不会自动恢复。密码包含引号/反斜杠时实际下发值保持，Qt日志及持久任务参数/结果隐藏密码；含密码的完整共同详情只存在GUI专用私有回填数据，不给AI/远程。
- 停止等待实际worker安全点，未开始DUT跳过；关闭窗口/切项目/切总览不停原任务。原Qt阶段仍只准入一个设备业务Job，不新增硬件并行能力。
- 宽窗口双列、窄窗口单列，自动计算标签宽度和行最小高度；内容纵向滚动，底部查询/执行/停止/关闭保持可见。不是通过固定坐标或固定大窗口掩盖裁切。

## 修改文件

相对主源码目录：

| 文件 | 本轮用途 |
| --- | --- |
| `src/models/dut_wan_form.py`（新） | 原文共享WAN纯展示规则，无GUI依赖 |
| `src/ui/dut_config_window.py` | 保留旧同名API导入代理；类/其余定义AST不变 |
| `src/ui/qt/dut_wan_panel.py`（新） | 全字段、原规则、共同详情、响应式表单 |
| `src/ui/qt/dut_configuration_dialog.py` | 共用凭据/目标/状态、Tab切换与WAN命令 |
| `src/services/qt_dut_configuration.py` | GUI查询/配置、私有回填缓存、确认绑定、原Job/服务 |
| `src/ui/qt/workspace_controller.py` | 入口说明更新，不新增轮询器 |
| `tests/qt_dut_fakes.py` | 原批量/单台/core payload配模拟物理边界 |
| `tests/test_qt_dut_wan.py`（新） | 14项WAN准入、参数、隐私、取消/停止/失败回归 |
| `tests/qt_workbench_probe.py` | 2项新增强制原生用例、三档布局与截图 |
| `scripts/verify_{baseline,qt_migration,capability_coverage}.py` | 编译与必须执行ID、能力说明 |
| `scripts/capability_gui_actions.json` | GUI动作审核快照 |
| `validation/pyside6_migration_20261118/verify_wan.py`（新） | 原业务保全及共享规则AST等价 |
| `validation/pyside6_migration_20261118/verify_wan_delivery.py`（新） | 顺序UTF-8验证和版本一致证据 |
| 本报告、最终JSON/日志/截图 | 保留本轮验证，不覆盖前轮结果 |
| `validation/pyside6_migration_20261118/NEXT_DUT_AUDIT.md`（新） | 下一WiFi模块的真实代码/时序审计入口，未宣称实现 |
| `line_check_assistant_README.md` | 实际操作与未完成范围 |

根目录同步README、PROJECT_STATUS、ACCEPTANCE_BASELINE、DEVELOPMENT_LOG、CAPABILITY_COVERAGE、迁移计划及同目录MIGRATION_PROGRESS。既有其它工作区改动保留，不算作本轮修改；未暂存或提交。

## 前后截图与视觉检查

此前Qt WAN页禁用：上轮DUT窗口，无可工作的Qt WAN页改前截图。

| 场景 | 中间检查 | 最终证据 |
| --- | --- | --- |
| 宽窗口信息密度 | 单列过长 | 1000×740双列 |
| 窄窗口 | 早期行内控件压缩 | 560×460，150% |
| 最后状态可达 | 早期仅验证外窗口尺寸，不足以证明内部完整 | 窄窗口滚动到底 |

所有截图为核验非输入私有桌面上的Windows QPA源码窗口，使用明确模拟项目、Fake网络/UBUS，无真实硬件操作或切换用户桌面。主题、边框、按钮层级沿统一Qt设计变量；参考图没有独立WAN编辑窗口，不宣称像素级对应。窄窗口长表单需要纵向滚动，目标/结果区在其后，执行按钮固定可见；其它四个DUT页和旧几何恢复仍未迁移。

## 测试与失败记录

最终统一命令（主源码目录，仓库外标准CPython3.9.10，整个进程树UTF-8）：

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
python validation/pyside6_migration_20261118/verify_wan_delivery.py
```

编排依次执行新WAN/原Telnet/原开关机适配相关测试、源码/协议/GUI覆盖及原AST检查、原生三档全部指定用例、完整基线。两组模拟设备测试不并发，不跳过/绕过原资源保护。完整基线因原已验收UI的纯展示规则迁移而触发；不把前轮3057项当作本轮结果。

- 完整基线通过：3071项测试、232项指定回归实际执行，300编译/290登记、499动作覆盖、GUI覆盖/运行守卫及全部协议不变量通过，`ALL CHECKS PASSED`/exit 0。顺序记录对应当时同版源码，未操作真实硬件。
- 当时原生31×3=93项全部通过，每档受管顶层185/违规0。包括原工作台、开关机、配置、通道、串口、DUT和2项新增WAN用例，字段联动/共同回填/实际payload/取消/切页停止及宽窄行内完整性。上表截图来自这版，不能宣称它们验证了之后的端口文案。
- 基线后仅将确认摘要中WAN沿用的TCP 23改为请求实际UBUS端口，并在既有WAN用例中增加摘要端口断言。基线时哈希与当前核对确认仅服务摘要和对应测试两份代码变化；将摘要块还原后整份服务文件哈希精确匹配基线，业务下发/判定/资源逻辑没有变化。没有再次运行完整基线。
- 端口修正后42项相关回归通过：14新WAN、17原Qt DUT、11原开关机适配。包含真实原批量/单台/core payload、JSON转义密码原样下发及隐藏、资源拒绝保留私有查询。初次29项为增补两项和纳入11项开关机前的历史范围。
- 最后源码/AST检查通过：300编译/290登记、499动作覆盖、GUI/协议；162原core/services、38旧业务Python、7份非Python本机配置及app.py字节不变；11提取定义和旧Tk剩余34定义AST一致。Tk导入同一模型API且纯模型不加载Tk的测试通过。
- **最后原生复验未完成**：复验记录中服务/源码通过，但原生三档均在创建GUI前失败，`Cannot verify current input desktop`。系统只读探针确认`OpenInputDesktop`失败、WinError 5；不能据此判断确切是锁屏、断开会话还是其它桌面权限状态。守卫未放宽，也未回退可见用户桌面。恢复可交互桌面后，运行`python scripts/verify_qt_migration.py --output validation/本次新目录`补齐新证据；当前阶段验收仍为false，原93项只覆盖文案修正前版本。
- 收尾核对：`wan_document_checks.json`的108条文档链接无缺失，`git diff --check`通过、暂存区为空；当前代码哈希未再变化，原DUT业务模型字节仍与备份一致。`wan_final_checks.json`保留`stage_acceptance_passed=false`，不把文档/源码通过当成原生复验通过。

保留中间失败/不足：`qt_wan_first`在确认前被原参数校验拒绝，截图显示Fake完整WAN缺VLAN优先级，回填为空；补齐真实完整样本的优先级0，并增加确认前调用原校验断言，未弱化生产校验。`qt_wan_review`三档93项通过，但单列表单过长；改双列后`qt_wan_layout`虽绿色，截图仍暴露行内控件被压扁。按实际最小高度/不重复换行分配空间、统一标签列并增加每个可见控件落在其行内的几何断言，`qt_wan_geometry`三档通过；最终又补齐结果滚动可达性和同列缩放/反馈行重算后完整顺序复验。旧截图和失败保留，不以窗口外框正确代替内容质量。

## 后续与现场边界

下一增量继续2.4G/5G WiFi、语音、TR069；[下一模块审计](NEXT_DUT_AUDIT.md)已确认原SSID递增/双频/能力字段和60秒稳定路径，未实现新的检测引擎。随后原升级、写参、ONU、AI/平台/全局/其它工具，完整日志历史、可靠性和Qt构建部署，见[完整进度表](MIGRATION_PROGRESS.md)。持续开机老化按负责人确认保持待接入，不改造成上下电循环或虚构检测结果。

真实WAN查询/修改/删除、目标网络和源IP、设备差异、1/8台异常隔离/安全停止及长期/系统DPI/目标电脑部署仍待负责人确认。原Tk现场验收不自动授予Qt。本轮不操作真实设备/网卡，不发外部消息，不打包、运行EXE或发布；正常挂测继续Tk。
