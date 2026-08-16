# 项目交接状态

更新：2026-08-14（扩展5G WiFi、语音与TR069动态能力）。

## 项目目标与当前状态

`LineCheckAssistant` 是 Windows Tkinter 桌面工具，用于测试环境线路检查、程控电源、串口日志、样机升级、批量写样机参数、ONU 注册、测试项配置和开关机测试。

| 能力 | 当前状态 |
| --- | --- |
| 通道 / 网卡配置、线路 Ping、内置多 VLAN 串口终端 | 通道 / 网卡配置、线路 Ping、程控电源COM与VLAN分组筛选和空COM全网卡展示均已真实样机验收；主界面“通道对应 COM口”按`COM101 → COM1–COM8`、`COM102 → COM9–COM16`分组，保存到`network_card_ip.ini`，写参、全包升级、手动/全流程串口日志和升级附加日志优先使用实际选择，旧配置回退VLAN映射。项目负责人已于2026-08-13确认通道COM选择及串口日志实际选择联动验收通过；线路 Ping 网卡准备按需复用待现场回归；串口 Enter 发送已真实样机验收；串口日志文件名和逐行时间戳待目视确认 |
| 程控电源直连（COM101–COM116） | 自动上/下电、同批次 COM 长连接复用、1–8 台并行、空 COM 手动重启确认后继续且不下发电源指令均已真实样机验收 |
| 全包升级 `Tftp指令`、`Tftp Put` | 两条独立链路均已真实样机验收；共用的 TFTP 网卡准备已改为状态预检、按需修复并继续等待源 IP 可绑定，本次优化待现场回归；4 / 8 台并行仍可按现场需要补验收 |
| 页面升级（UBUS 批量 + 可选恢复出厂） | 升级已实现；网卡准备已接入状态预检复用；勾选恢复出厂及本次网卡复用的真实样机验收待完成 |
| 批量写样机参数、随机参数表 | 1台与6台独立VLAN telnet路径已真实样机验收；生成窗口首帧刷新以及MAC前6位自定义/后6位随机唯一、普通SN纯数字且总长不超过16位、XPON SN固定12位规则均于2026-08-13通过现场验收；写参用户/工厂模式网卡状态预检复用待现场回归；2/8台端点并行待现场需要时补验收 |
| ZTE OLT ONU 注册 | 已实现未验收，需覆盖现场 Access denied、删除离线 ONU、重注册场景 |
| DUT 配置（UBUS） | 2026-08-13已现场验收：六Tab布局、连续查询/session注销、网卡按需复用及完整WAN配置。2026-08-14新增验收：单台2.4G WiFi连续两次修改，每次下发后等待60秒稳定并完成回读，第二轮`Device.WiFi.Radio.`超时BUG已解决；仅2.4G的认证、信道、带宽、协议和发射功率五类下拉按DUT实际能力动态加载通过现场验收。5G独立动态能力、语音DTMF/SIP/编码动态候选及TR069实际字段约束已实现并通过自动化测试，待真实DUT验收。仍待验收：设备缺能力字段时的兜底与目标变化清理、Telnet状态准确性、2.4G其它参数组合、5G WiFi、语音/TR069实际配置、主动Access denied、1/8台并行、停止及单台失败隔离 |
| 主界面布局 | 内容区已删除重复的应用名称与说明，仅保留 Windows 标题栏；“执行日志”标题下的“运行步骤、检查结果和异常信息”提示行也已删除；管理员权限状态已移动到常用工具栏右侧、“刷新串口”左边，成功/危险颜色语义及两个刷新按钮顺序保持不变；待 Windows 桌面目视确认 |
| 测试项配置编辑器 | 已完成五个Tab、唯一指令重试间隔、旧工具运行参数和WiFi八项映射；固定模板恢复已验收。“测试项配置”和“DUT配置”已在保留120ms/360ms验收刷新兜底的基础上增加20ms快速刷新，并使用已知窗口尺寸直接居中，避免显示前强制完成整棵控件树布局；原客户区完整绘制已由项目负责人完成Windows桌面验收（2026-08-12），本次加载提速待桌面体感复验 |
| 全流程执行 | 已实现未验收：现有7个子任务，打开窗口时全部默认不勾选，由操作员按本次需要明确选择；已移除“测试项配置（[order] 执行）”。二次确认并启动线程后自动隐藏全流程配置窗口，运行期间不重新弹出，完成/失败状态经主程序 UI 任务队列回收并把提示挂到主界面，不再由后台线程调用隐藏窗口 `after()`；主入口与停止按钮同时核对线程真实状态，后台已结束时自动清除残留运行态。主界面“环境检查与开关机测试”卡片使用加粗彩色徽标实时显示未运行、执行、停止和最终状态，其中“正在执行”为深绿色底白字；“停止测试”按钮继续复用同一编排器停止事件。进度条在全流程启动时重置，子任务7开始后按本次 `config.ini [ui_defaults] number_of_tests` 设置总轮次并显示“当前/总轮次”；多通道按最慢通道的已完成轮次推进，停止/失败保留现场进度，全部成功显示满格。“执行开关机测试”为第7项，勾选后在独立无 GUI 子进程复用旧 Start All 的 Telnet/SSH、程控电源和通道业务；主执行日志保留操作员信号、关键 logger 结果、警告/错误、实际电源帧及最终结论，过滤底层 INFO 噪声，合并2秒内重复日志以及不限时长的连续同文日志；“IP登录成功”在单次运行内按 IP 只显示第一次，可正确处理多个 IP 交替输出；“通道开始第 N 次测试”正文以绿色显示；旧英文网卡 Ping 成功日志按当前方案 `request_url` 转换为“Ping 成功：源网卡 IP → 目标样机 IP”；旧结果文件中的“通道N下挂的设备在第M次测试时正常”完整行也实时桥接为 `[旧工具Logs][INFO]`，原结果文件保持不变。全部通道结束后才返回结果；初始化会先全通道断电，启动前有明确危险确认。串口日志预启动、子任务1后120秒等待及既有失败边界保持不变；待桌面交互和真实样机验证 |

- DUT WAN完整快照查询/表单回填、多台一致性判断、IPTV组播VLAN、LAN1–LAN8端口绑定以及新增/修改/删除全套配置已于2026-08-13通过现场验收。
- DUT语音查询现会从VoIPProfile和SIP节点解析DTMF/SIP支持字段，并只读获取标准`Device.Services.VoiceService.1.Capabilities.Codecs.`编码能力表；三个下拉按DUT返回候选更新，当前值保留，缺能力字段时使用兼容候选，配置前由service再次拒绝不支持值。代码与自动化测试已通过，Windows下拉显示和真实样机下发/回读待验收。
- DUT语音和TR069页独立只读查询的连续执行、session注销和网卡复用已于2026-08-13验收。TR069查询现按`Device.ManagementServer.`实际存在字段启用配置控件，缺失项禁用且配置载荷不下发；具体字段准确性、一致参数回填、多台不一致保护以及实际配置下发/回读仍待验收。
- DUT Telnet页连续查询、session注销和窗口布局已于2026-08-13验收；AccessCtrl总开关、LAN规则和TCP23状态准确性及查询全程无set/add仍待专项验收。WAN当前状态复用同批查询结果已随WAN配置整组验收通过。
- DUT配置2.4G/5G WiFi页的窗口布局及连续查询稳定性已于2026-08-13验收；2026-08-14单台2.4G WiFi连续两次修改、60秒稳定等待及回读通过真实DUT验收，仅2.4G的认证、信道、带宽、协议和发射功率五类下拉与DUT实际能力一致通过现场验收。5G使用独立Mapping和Radio能力的代码与自动化测试已通过，但5G动态下拉及实际配置尚未现场验收。设备缺少能力字段时的兜底、目标变化后旧能力清理、2.4G其它参数组合、开放网络、隐藏SSID和双频合一行为仍待验收。
- DUT配置六个Tab字段左对齐、原生勾号、状态高度拖动/恢复、底部提示与按钮保护、窗口宽高保存恢复及20ms快速刷新均于2026-08-13通过现场验收；测试项配置窗口的本次加载提速仍待桌面体感复验。
- 主界面截图中的八个功能入口已统一使用相对主界面的居中算法，主程序位于副屏时按父窗口实际屏幕坐标计算；DUT和测试项配置先居中再执行客户区首帧刷新。串口日志仅在无有效历史位置或历史位置仍为左上角时居中，用户主动移动后的有效位置继续恢复。项目负责人已于2026-08-13确认各功能入口居中显示需求验收通过。
- 最近一次**已记录**的完整回归：2026-08-14，`python scripts/verify_baseline.py`全绿，记录为609项单元测试（52个当前主程序源码文件编译覆盖、112个强制基线测试均实际执行）；本轮覆盖WiFi连续配置、2.4G/5G独立动态能力、语音DTMF/SIP/编码能力、TR069字段约束、目标变化清理及配置预检回归。
- 验收状态与不可破坏规则以 `ACCEPTANCE_BASELINE.md` 为准；本文件不重复保存历史测试数和详细验收证据。

## 继续开发先读什么

1. `README.md`：仓库入口、主源码目录、文档职责和历史目录边界。
2. `AGENTS.md`：开发和 AI 硬规则。
3. `ACCEPTANCE_BASELINE.md`：本次改动涉及功能的状态、不变量、待确认项。
4. `DEVELOPMENT_LOG.md` 顶部最近记录：最近变更和验证结果。
5. 相关 `tests/test_*.py`：既有断言和 mock 约定。

## 关键入口

- `Cheating_machine_execution_tool/run_line_check_assistant.py`：源码启动入口。
- `Cheating_machine_execution_tool/line_check_assistant/app.py`：Tk 主窗口、功能入口和主执行日志。
- `Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`：全包升级流程。
- `Cheating_machine_execution_tool/src/services/sample_parameter_service.py`：批量写参流程。
- `Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`：7 子任务编排。
- `Cheating_machine_execution_tool/src/services/legacy_power_test_service.py`：第7项无 GUI 旧 Start All 适配与 Logs 桥接。
- `Cheating_machine_execution_tool/scripts/verify_baseline.py`：提交前最低回归门禁。

## 当前待办与限制

- 真实样机：页面升级恢复出厂、ONU 注册异常路径、全流程执行 7 子任务端到端（特别核对第7项全断电提示、通道映射、旧 Logs 和停止）。
- 并行边界：全包升级与写参的 4 / 8 台场景按现场需求补验收，不因单元测试自动升级验收状态。
- 仅支持 Windows 10/11；设置网卡静态 IP 需管理员权限。
- 严格区分 `Tftp指令`（样机从本机 TFTPy Server 拉取）与 `Tftp Put`（本机 TFTPy Client 推送到 `192.168.1.1:69`）。
- 多网卡路径必须锁定 VLAN 源 IP；TFTP / Telnet 不得回退 `0.0.0.0`。
- 旧工具 GUI 主文件、旧 EXE、历史升级原型和协议参考目录默认不改；只有全流程子任务7允许在独立无 GUI 子进程复用旧工具 `test_case/common/clients` 业务类，不 import / 实例化旧 GUI。其它主程序路径仍不依赖旧业务；`Telnet Enable` 反向关系、COM 同值和 channel 1～16 同步规则保持不变。

## 运行、验证与交接规则

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m pip install -r .\requirements.txt
python .\run_line_check_assistant.py
python scripts\verify_baseline.py
```

- 业务代码改动：实施者必须运行回归门禁、追加 `DEVELOPMENT_LOG.md`，并按 `AGENTS.md` 同步状态、验收或操作说明。
- 已验收功能改动：除全量单测与协议不变量外，`verify_baseline.py` 还会确认关键行为测试实际执行、且新增主程序 Python 文件没有漏出编译清单；首次开发环境应运行 `powershell -ExecutionPolicy Bypass -File scripts\install_git_hooks.ps1` 启用提交前门禁。
- 真实样机通过：只有项目负责人提供现场结果后，才能更新 `ACCEPTANCE_BASELINE.md` 状态标签。
- 文档或构建调整：追加开发日志；只有影响当前入口、待办或运行命令时才更新本文件。
- 不提交本机配置、日志、测试结果、`build/`、`dist/` 或 `.claude/settings.local.json`。
