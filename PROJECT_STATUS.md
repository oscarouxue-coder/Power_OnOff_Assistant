# 项目交接状态

更新：2026-08-13（复杂配置窗口加载提速）。

## 项目目标与当前状态

`LineCheckAssistant` 是 Windows Tkinter 桌面工具，用于测试环境线路检查、程控电源、串口日志、样机升级、批量写样机参数、ONU 注册、测试项配置和开关机测试。

| 能力 | 当前状态 |
| --- | --- |
| 通道 / 网卡配置、线路 Ping、内置多 VLAN 串口终端 | 通道 / 网卡配置、线路 Ping、程控电源COM与VLAN分组筛选和空COM全网卡展示均已真实样机验收；主界面通道表已增加独立“通道对应 COM口”选择，按`COM101 → COM1–COM8`、`COM102 → COM9–COM16`分组，选择保存到`network_card_ip.ini`，写参、全包升级、手动/全流程串口日志和升级附加日志优先使用实际选择，旧配置回退VLAN映射，代码与单测通过、待Windows和真实串口验收；本次线路 Ping 网卡准备按需复用待现场回归；串口 Enter 发送已真实样机验收；串口日志文件名和逐行时间戳待目视确认 |
| 程控电源直连（COM101–COM116） | 自动上/下电、同批次 COM 长连接复用、1–8 台并行、空 COM 手动重启确认后继续且不下发电源指令均已真实样机验收 |
| 全包升级 `Tftp指令`、`Tftp Put` | 两条独立链路均已真实样机验收；共用的 TFTP 网卡准备已改为状态预检、按需修复并继续等待源 IP 可绑定，本次优化待现场回归；4 / 8 台并行仍可按现场需要补验收 |
| 页面升级（UBUS 批量 + 可选恢复出厂） | 升级已实现；网卡准备已接入状态预检复用；勾选恢复出厂及本次网卡复用的真实样机验收待完成 |
| 批量写样机参数、随机参数表 | 1 台与 6 台独立 VLAN telnet 路径已真实样机验收；用户模式和工厂模式切网均已接入状态预检复用并继续等待可绑定，本次优化待现场回归；2 / 8 台端点并行待现场需要时补验收 |
| ZTE OLT ONU 注册 | 已实现未验收，需覆盖现场 Access denied、删除离线 ONU、重注册场景 |
| DUT 配置（UBUS） | 已实现未验收：Notebook 包含“Telnet配置”“WAN配置”“2.4G WiFi配置”“5G WiFi配置”“语音配置”“TR069配置”六页，均使用主界面已勾选 DUT、共享明文 UBUS 凭据、1–8 并行（默认1）、逐台状态、停止和失败隔离；WAN 支持新增/修改/按明确索引删除、路由/桥接、IPoE/PPPoE、IPv4/IPv6/IPv4+IPv6 双栈及静态地址组合，并已按真实创建规则联动字段显隐、IPoE/PPPoE默认MTU 1500/1492、桥接业务类型及端口绑定、动态/静态和双栈有效组合，service会二次拒绝非法组合；修改/删除使用“查询现有 WAN”只读下拉，单台显示本机连接，多台只显示所有目标名称完全一致的共同连接，失败/停止/目标变化/WAN配置后不会沿用旧列表；WiFi两页覆盖SSID索引、名称/密码、信道/带宽、启用/隐藏、认证加密、协议、功率、最大接入数、WMM和双频合一，查询先解析厂商Mapping与真实实例路径，配置后回读，双频合一同步SSID/AP安全参数但保持两个Radio独立；已补设备端UBUS session注销，避免连续第二次查询因上一轮会话残留返回Access denied；语音覆盖 SIP 基础/服务器/账号/编码/DigitMap；TR069 覆盖 ACS、周期 Inform、连接请求、证书、回读和可选手动 Inform。WAN、WiFi、语音、TR069共22个选择框均使用原生勾选框，选中显示“✓”、未选为空框；每台先只读检查 VLAN 网卡启用状态及 IPv4/前缀，完全匹配时跳过重复启用和静态 IP 设置，仅修复不满足项，状态读取失败则回退完整准备，随后仍确认源 IP 可绑定并以独立 `UbusHttpClient` 锁源执行；Windows布局、连续查询、网卡复用日志、WAN/WiFi联动、勾号外观和真实样机协议兼容性待验收 |
| 主界面布局 | 内容区已删除重复的应用名称与说明，仅保留 Windows 标题栏；“执行日志”标题下的“运行步骤、检查结果和异常信息”提示行也已删除；管理员权限状态已移动到常用工具栏右侧、“刷新串口”左边，成功/危险颜色语义及两个刷新按钮顺序保持不变；待 Windows 桌面目视确认 |
| 测试项配置编辑器 | 已完成五个Tab、唯一指令重试间隔、旧工具运行参数和WiFi八项映射；固定模板恢复已验收。“测试项配置”和“DUT配置”已在保留120ms/360ms验收刷新兜底的基础上增加20ms快速刷新，并使用已知窗口尺寸直接居中，避免显示前强制完成整棵控件树布局；原客户区完整绘制已由项目负责人完成Windows桌面验收（2026-08-12），本次加载提速待桌面体感复验 |
| 全流程执行 | 已实现未验收：现有7个子任务，打开窗口时全部默认不勾选，由操作员按本次需要明确选择；已移除“测试项配置（[order] 执行）”。二次确认并启动线程后自动隐藏全流程配置窗口，运行期间不重新弹出，完成/失败状态经主程序 UI 任务队列回收并把提示挂到主界面，不再由后台线程调用隐藏窗口 `after()`；主入口与停止按钮同时核对线程真实状态，后台已结束时自动清除残留运行态。主界面“环境检查与开关机测试”卡片使用加粗彩色徽标实时显示未运行、执行、停止和最终状态，其中“正在执行”为深绿色底白字；“停止测试”按钮继续复用同一编排器停止事件。进度条在全流程启动时重置，子任务7开始后按本次 `config.ini [ui_defaults] number_of_tests` 设置总轮次并显示“当前/总轮次”；多通道按最慢通道的已完成轮次推进，停止/失败保留现场进度，全部成功显示满格。“执行开关机测试”为第7项，勾选后在独立无 GUI 子进程复用旧 Start All 的 Telnet/SSH、程控电源和通道业务；主执行日志保留操作员信号、关键 logger 结果、警告/错误、实际电源帧及最终结论，过滤底层 INFO 噪声，合并2秒内重复日志以及不限时长的连续同文日志；“IP登录成功”在单次运行内按 IP 只显示第一次，可正确处理多个 IP 交替输出；“通道开始第 N 次测试”正文以绿色显示；旧英文网卡 Ping 成功日志按当前方案 `request_url` 转换为“Ping 成功：源网卡 IP → 目标样机 IP”；旧结果文件中的“通道N下挂的设备在第M次测试时正常”完整行也实时桥接为 `[旧工具Logs][INFO]`，原结果文件保持不变。全部通道结束后才返回结果；初始化会先全通道断电，启动前有明确危险确认。串口日志预启动、子任务1后120秒等待及既有失败边界保持不变；待桌面交互和真实样机验证 |

- DUT WAN 查询已从“只取连接名”扩展为一次读取 IP Interface、Ethernet/VLAN、PPP、Bridge、DHCP、DNS、NAT 的完整快照；选择下拉项会同步当前 WAN 表单。单台直接回填，多台仅在同名 WAN 的完整参数一致时回填，不一致时保留名称但提示人工核对。该行为代码与自动化测试已通过，真实样机字段兼容性和 Windows 界面待验收。
- DUT WAN 的 IPTV 业务已增加可选“组播 VLAN ID”：仅 IPTV 显示，填写时校验 1–4094，路由/桥接均以 `MulticastVLANID` 下发；非 IPTV 隐藏并忽略旧值，现有 WAN 查询可从 `X_SDMC_Multicast_VLANID` 等兼容字段回填。代码与自动化测试已通过，Windows 界面和真实样机下发/回填待验收。
- DUT WAN 端口绑定已由原始位掩码输入改为LAN1–LAN8原生多选框；查询值会反向勾选，多选自动生成 `PortBind` 位掩码，修改保留非LAN旧位而新增不继承。代码与自动化测试已通过，Windows界面布局和真实样机下发待验收。
- DUT语音SIP模式在原有 `SIP/UDP/TCP/TLS` 基础上增加 `IMSSIP`，UI和service共用 `SIP/IMSSIP/UDP/TCP/TLS` 允许值，选择结果原样写入 `X_SDMC_SIPMode`，未知模式下发前拒绝。代码与自动化测试已通过，Windows下拉显示和真实样机IMSSIP下发/回读待验收。
- DUT语音和TR069页已增加独立只读状态查询及“当前状态”展示区：语音按当前线路读取账号、服务器、DTMF、SIP模式、DigitMap和5项编码，TR069读取ManagementServer参数；逐台展示，全部目标参数一致才自动同步表单，不一致/失败不覆盖，目标变化或配置后使旧状态失效。查询复用网卡预检、锁源IP、并行/停止/失败隔离和设备session注销，不执行配置set。代码与自动化测试已通过，Windows布局与真实ONT字段兼容性待验收。
- DUT Telnet页已增加“查询当前Telnet”和“当前状态”区，只读获取AccessCtrl总开关、LAN Telnet规则并锁源探测TCP 23，严禁查询时set/add；WAN页复用现有WAN查询结果逐台展示连接名称、模式、业务类型和VLAN，不额外重复查询。当前六个Tab均有当前状态区，目标变化或对应配置后旧状态失效。代码与自动化测试已通过，Windows布局与真实ONT兼容性待验收。
- DUT配置已增加独立“2.4G WiFi配置”和“5G WiFi配置”页：包含SSID索引、名称、密码、信道、带宽、启用、隐藏、认证/加密、协议、功率、最大接入数、WMM和双频合一；查询从设备Mapping解析真实Radio/AP/SSID实例并同步当前表单，配置使用多路径set并回读。双频合一只同步两端SSID/AP/安全参数，不覆盖另一频段Radio。代码与自动化测试已通过，Windows布局、真实ONT Mapping/字段和双频合一行为待验收。
- DUT配置六个 Tab 的字段名称已统一左对齐，公共字段和WAN单独的“现有连接名/索引”均受回归测试保护；Windows桌面目视效果待验收。
- DUT配置六个Tab的“当前状态”区域已统一增加拖动高度调节条，每页独立限制2–16行；底部“已加载 N 台目标 DUT”提示和“刷新/查询/停止/执行/关闭”按钮栏现组成统一受保护区域，以最高布局优先级从Tab底部预留完整高度，再由状态区和目标表格使用剩余空间，并继续按底部区域实际位置动态校正状态高度。拖动、窗口显示和Tab切换都不会允许提示或按钮被压缩、裁切或遮挡。有效高度写入本机`~/.aouxue_dut_config.json`并逐页恢复，历史高度不安全时自动降低并保存。代码与自动化测试已通过，Windows桌面六页的最大拖动、底部区域完整显示和关闭重开恢复待验收。
- DUT配置窗口关闭时会把实际宽高保存到同一`~/.aouxue_dut_config.json`，再次打开自动恢复；窗口尺寸和六页状态高度合并保存、互不覆盖，非法值回退默认1530×880，过小或超过当前屏幕的历史尺寸自动收敛。代码与自动化测试已通过，Windows桌面调整、关闭重开及分辨率变化待验收。
- “测试项配置”和“DUT配置”继续使用标准`Toplevel`自然映射；已知窗口宽高直接参与居中计算，不在弹出前为读取尺寸同步刷新整棵复杂控件树。映射后先在20ms执行快速1像素宽度脉冲，并保留120ms和360ms两次已验收兜底，触发Windows`WM_SIZE/WM_PAINT`整体重绘；复用窗口同样刷新，DUT状态高度仍在空闲阶段校正。项目负责人已于2026-08-12完成原绘制方案Windows桌面验收，本次提速待桌面体感复验。
- 主界面截图中的八个功能入口已统一使用相对主界面的居中算法，主程序位于副屏时按父窗口实际屏幕坐标计算；DUT和测试项配置先居中再执行客户区首帧刷新。串口日志仅在无有效历史位置或历史位置仍为左上角时居中，用户主动移动后的有效位置继续恢复。项目负责人已于2026-08-13确认各功能入口居中显示需求验收通过。
- 最近一次**已记录**的完整回归：2026-08-13，`python scripts/verify_baseline.py`全绿，记录为588项单元测试（52个当前主程序源码文件编译覆盖、103个强制基线测试均实际执行）；本轮新增通道COM分组、持久化及写参/全包升级/串口日志实际选择链路回归。复杂窗口原客户区完整绘制已于2026-08-12现场验收，本轮加载提速仍待桌面体感复验。
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
