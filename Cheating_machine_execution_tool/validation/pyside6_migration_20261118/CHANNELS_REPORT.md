# DUTPilot Qt迁移：通道配置与矩阵/列表交付

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

后续检查点：基本串口终端由下一轮接入，见[串口阶段报告](SERIAL_REPORT.md)。下文保留通道阶段当时的验证与待办。

2026-11-19 已接入[串口与网卡候选分组](RESOURCE_OPTIONS_QT_REPORT.md)及[失败轮次续跑](RESUME_QT_REPORT.md)。

2026-11-18，`feature/pyside6-migration`。本轮按原计划补齐一个垂直模块：Qt通道选择、VLAN/COM/IP/电源绑定，以及实际通道状态矩阵/只读列表。**整体迁移尚未完成，未替换默认Tk入口。** V1.2.10、原构建链和已验收设备业务保持；未提交、打包、运行EXE、连接真实设备或发送消息。

## 审计、布局问题及实现

原Tk在`_ensure_channel_slots`补齐16槽位，但`ChannelConfigStore`只保存已选行；未选绑定只在当前会话保留。原`ChannelCapabilities.prepare/commit`已有COM/VLAN校验、共享管理IP、源IP推导、电源/样机COM冲突检查及事务发布。迁移继续使用这些入口，没有新建另一套序列化或放宽原设备预检。原厂测等隐藏字段也保留。

原Qt只展示配置和通道按钮，没有完整的编辑与列表入口。补齐后原生截图又发现：`QStackedWidget`把隐藏列表的最小高度计入矩阵，造成矩阵区被无关表格撑高。现改为仅由当前页提供尺寸提示；矩阵列数随实际宽度计算、紧凑内边距，未使用绝对坐标或固定主窗口尺寸掩盖问题。表单宽屏按行排列，窄屏自动换行，只纵向滚动，底部操作保持可见。

本轮行为：

- 16个槽位、全选/清除、可编辑VLAN/COM、共享管理IP/电源COM、只读推导源IP；实际本机资源刷新保留已填值和空选择，不配置网络或操作硬件。
- 预览由原校验产生，确认绑定项目版本、所有配置字节和当前会话；两分钟、一次性使用。取消不写盘，保存继续提交原项目版本。
- 只保存已选行；未选绑定在当前项目会话保留，关闭重开按原文件恢复。磁盘外部变化使缓存失效，不覆盖其它写入；提交失败恢复本次草稿，恢复不确定时保留原资源未知保护。
- 同项目通道窗口、六标签窗口和设备任务互斥。切页不改变编辑目标、不停止挂测；文件工作仍由原后台队列处理，没有新增定时器/重复监听。
- `channels.editor.*`仅供gui来源，未扩大模型/远程作用域。使用数据投影调用原`prepare`，批准后才由实际通道服务`commit`，没有复制设备业务。
- 矩阵/列表读取同一冻结通道快照；列表只读、双击查看状态。未启用/未知不伪造正常或零轮次；标明本次任务配置快照，避免与下次运行草稿混淆。

## 修改文件

以下源码路径相对主源码目录，根文档另列：

| 文件 | 改动 |
| --- | --- |
| `src/services/qt_channel_configuration.py`（新） | 16槽位缓存、原校验/存储、预览确认、版本/失败恢复、GUI专用能力 |
| `src/ui/qt/channel_configuration_dialog.py`（新） | 自适应通道表单、只读枚举、选择/保存/重载/关闭 |
| `src/ui/qt/channel_table_model.py`（新） | 只读通道模型、状态色、身份稳定更新 |
| `src/services/qt_execution_adapter.py` | 接入通道服务、完整槽位及任务快照来源 |
| `src/services/qt_configuration_service.py` | 两类编辑器互斥 |
| `src/services/qt_workspace_adapter.py` | 后台操作路由、会话缓存与视图快照 |
| `src/models/workbench_presentation.py` | 编辑器种类和任务快照标签 |
| `src/ui/qt/project_detail.py` | 矩阵/列表、通道配置入口、当前页尺寸提示 |
| `src/ui/qt/workspace_controller.py` | 编辑窗口生命周期、预览/取消/批准/保存、原刷新复用 |
| `src/ui/qt/theme.py` | 通道按钮紧凑内边距 |
| `tests/test_qt_channel_configuration.py`（新） | 16项服务用例 |
| `tests/qt_workbench_probe.py` | 4项原生用例及实际截图/尺寸断言 |
| `scripts/verify_qt_migration.py` | 24个指定原生ID必须实际执行 |
| `scripts/verify_baseline.py` | 3份新增生产源码编译登记、4项关键回归登记 |
| `scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json` | 审查通道GUI入口、更新478动作快照 |
| `validation/pyside6_migration_20261118/verify_channels.py`（新）及本目录证据 | 独立输出本阶段编译/协议/保全结果，保留前轮证据 |
| `line_check_assistant_README.md` | 通道操作、持久化和快照说明 |

根文档：`.claude/plans/pyside6-migration.md`、`README.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`、生成的`CAPABILITY_COVERAGE.md`。前轮`CONFIGURATION_REPORT.md`只增加后续导航，历史结果保留。原Tk app.py、原ChannelCapabilities/ChannelConfigStore、原设备执行模块无本轮改动；原工作区其它差异保留。

## 前后截图与实际验收

截图通过原受管Windows私有桌面捕获，未切换到用户输入桌面。主窗口演示数据有明确标记；编辑器使用独立临时项目；运行控制使用Fake，不是现场测量。

| 场景 | 改前 | 改后 |
| --- | --- | --- |
| 详情及矩阵 | 上一阶段1366详情 | 紧凑矩阵1366、1920详情 |
| 隐藏列表影响高度 | 首次新增列表后截图 | 当前页尺寸提示修复后 |
| 通道编辑 | 改前Qt无该窗口，无对应截图 | 1100窗口、620窄窗口、150%窄窗口 |
| 通道列表 | 改前Qt无该视图 | 1366列表、1000列表 |
| 总览与配置保留 | 前轮总览 | 本轮总览、Telnet |
| 原任务链 | Phase3运行 | 本轮Fake运行、安全停止 |

已核对：深青导航与主题延续；详情优先显示轮次/运行；16槽位自适应矩阵与列表身份一致；表单窄屏无横向滚动、底部操作可见；100/125/150%显式Qt缩放均执行。真实系统DPI、实体多屏及人工键鼠验收未完成。

与目标图剩余差异：进度仍为原横向条，未增加圆环/趋势装饰；小窗口会纵向滚动，配置摘要可收起；告警中心/真实系统健康摘要、全业务探针趋势和部分工具栏/页面尚未接入，不填假监控数据。当前详情仍有可继续压缩的留白，未为填充留白添加无业务依据的面板。通道资源分组过滤、网卡物理改名及失败通道续跑未由本轮迁移。

## 实际验证结果

| 范围 | 本轮结果 |
| --- | --- |
| 新服务专项 | 16项通过，包含旧序列化/隐藏字段、只选目标、未选值会话保留、清空电源、无效值、取消/过期/重放、外部版本、任务/编辑互斥、GUI来源、失败恢复/未知、文件锁准入失败释放 |
| 最终相关组合 | 109项全部通过，含新通道、六标签、执行、项目、原通道/设备及覆盖/基线检查器；0真实GUI窗口/违规0 |
| 原生Qt最终复验 | 24项×三档=72项全部通过，每档30受管顶层，违规0；全部指定ID执行，Windows QPA/核验私有桌面 |
| 源码与门禁 | 294份编译、284份源码登记、能力/GUI覆盖及全部协议项通过，478动作快照已审查更新 |
| 原业务保全 | 与Phase0备份相比162份原core/services、38份旧工具Python、7份非Python配置及1份原Tk app.py字节一致（脚本列明范围）；不是整个工作区与Git无差异 |
| 完整基线 | 本轮新增独立Qt模块与尚未验收的Qt适配器，未搬迁已验收Tk/设备引擎；未触发/未运行完整基线，前轮2981项保留为历史结果 |
| 现场及交付 | 未操作硬件、发送消息、构建/运行EXE、提交或发布；真实设备/长期和部署未验收 |
| 文档与差异 | `git diff --check`通过，暂存区为空；本阶段日志条目与导航/报告本地链接检查通过，历史开发日志条目不纳入本次链接修复范围 |

保留失败证据：并发复验在100%档被原主机保护拒绝`serial:com102`，未到达Fake引擎；错误提示触发未模拟原生warning，守卫也正确记录失败。该轮与109项服务回归同时运行、使用相同模拟资源，125/150%随后通过。没有削弱锁或忽略守卫；停止并发后以相同源码顺序运行完整三档专项，72项全部通过。首次`qt_channels_first`也为72项通过，随后根据截图改善布局再复验，不能将中间失败轮描述为通过。

复验命令（主源码目录，已验证的标准CPython3.9用于相关测试；原生脚本自动使用仓库外锁定Qt环境）。两条含任务的测试依次运行：

```powershell
python scripts/run_tests.py test_qt_channel_configuration test_qt_configuration_service test_qt_execution_adapter test_qt_workspace_adapter test_qt_migration_contract test_capability_channels test_channel_config test_capability_devices test_capability_coverage test_verify_baseline -v
python scripts/verify_qt_migration.py --output validation/pyside6_migration_20261118/qt_channels_acceptance_serial
python validation/pyside6_migration_20261118/verify_channels.py
```

## 后续范围

本轮完成通道编辑及查看，未把整套迁移标记完成。六标签原预备测试/草稿版本查询/消息试发仍待执行控制接入；串口、DUT、样机升级、写参、ONU、AI/平台、旧目录导入/远程管理、完整历史/日志导出与可靠性/Qt打包仍待逐模块实现。持续开机全业务老化按负责人决定保持待接入，不能把现有开关机循环当作该功能。正常挂测仍使用原Tk；人工/真实系统DPI/设备相同配置与时序、24/72小时、目标电脑交付继续待负责人验收。
