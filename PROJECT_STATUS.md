# 项目交接状态

更新：2026-08-09（DUT WAN 查询完整信息回填）。

## 项目目标与当前状态

`LineCheckAssistant` 是 Windows Tkinter 桌面工具，用于测试环境线路检查、程控电源、串口日志、样机升级、批量写样机参数、ONU 注册、测试项配置和开关机测试。

| 能力 | 当前状态 |
| --- | --- |
| 通道 / 网卡配置、线路 Ping、内置多 VLAN 串口终端 | 通道 / 网卡配置、线路 Ping、COM 分组筛选和空 COM 全网卡展示均已真实样机验收；本次线路 Ping 的网卡准备已接入状态预检复用，代码与单测通过、待现场回归；串口 Enter 发送已真实样机验收；串口原始日志文件名已统一为 `vlan_COM_YYYYMMDD.log`，每个落盘行统一以 `YYYY-MM-DD_HH:MM:SS` 开头，均待 Windows 桌面目视确认；其余终端高频场景仍按验收基线跟踪 |
| 程控电源直连（COM101–COM116） | 自动上/下电、同批次 COM 长连接复用、1–8 台并行、空 COM 手动重启确认后继续且不下发电源指令均已真实样机验收 |
| 全包升级 `Tftp指令`、`Tftp Put` | 两条独立链路均已真实样机验收；共用的 TFTP 网卡准备已改为状态预检、按需修复并继续等待源 IP 可绑定，本次优化待现场回归；4 / 8 台并行仍可按现场需要补验收 |
| 页面升级（UBUS 批量 + 可选恢复出厂） | 升级已实现；网卡准备已接入状态预检复用；勾选恢复出厂及本次网卡复用的真实样机验收待完成 |
| 批量写样机参数、随机参数表 | 1 台与 6 台独立 VLAN telnet 路径已真实样机验收；用户模式和工厂模式切网均已接入状态预检复用并继续等待可绑定，本次优化待现场回归；2 / 8 台端点并行待现场需要时补验收 |
| ZTE OLT ONU 注册 | 已实现未验收，需覆盖现场 Access denied、删除离线 ONU、重注册场景 |
| DUT 配置（UBUS） | 已实现未验收：Notebook 包含“Telnet配置”“WAN配置”“语音配置”“TR069配置”四页，均使用主界面已勾选 DUT、共享明文 UBUS 凭据、1–8 并行（默认1）、逐台状态、停止和失败隔离；WAN 支持新增/修改/按明确索引删除、路由/桥接、IPoE/PPPoE、IPv4/IPv6/IPv4+IPv6 双栈及静态地址组合，并已按真实创建规则联动字段显隐、IPoE/PPPoE默认MTU 1500/1492、桥接业务类型及端口绑定、动态/静态和双栈有效组合，service会二次拒绝非法组合；修改/删除使用“查询现有 WAN”只读下拉，单台显示本机连接，多台只显示所有目标名称完全一致的共同连接，失败/停止/目标变化/WAN配置后不会沿用旧列表；已补设备端UBUS session注销，避免连续第二次查询因上一轮会话残留返回Access denied；语音覆盖 SIP 基础/服务器/账号/编码/DigitMap；TR069 覆盖 ACS、周期 Inform、连接请求、证书、回读和可选手动 Inform。WAN/语音/TR069页的6个选择框已统一改为原生勾选框，选中显示“✓”、未选为空框；每台先只读检查 VLAN 网卡启用状态及 IPv4/前缀，完全匹配时跳过重复启用和静态 IP 设置，仅修复不满足项，状态读取失败则回退完整准备，随后仍确认源 IP 可绑定并以独立 `UbusHttpClient` 锁源执行；Windows布局、连续两次WAN查询、网卡复用日志、WAN联动、勾号外观和真实样机协议兼容性待验收 |
| 主界面布局 | 内容区已删除重复的应用名称与说明，仅保留 Windows 标题栏；“执行日志”标题下的“运行步骤、检查结果和异常信息”提示行也已删除；管理员权限状态已移动到常用工具栏右侧、“刷新串口”左边，成功/危险颜色语义及两个刷新按钮顺序保持不变；待 Windows 桌面目视确认 |
| 测试项配置编辑器 | 已完成五个 Tab；“指令重试间隔”的唯一配置源为 `config.ini [other_config]`，`test_project_config.ini [order]` 只保存测试命令；“开关机运行参数”动态编辑 `config.ini [ui_defaults]`；WiFi 页已完整映射主控、2.4G/5G、方案、认证、加密和指定无线网卡共8项，并由全流程子任务7无 GUI旧业务真实读取；固定模板恢复 `[order]` 不残留手动命令、点击后无需移动鼠标即完整绘制窗口，均已完成 Windows 桌面确认；WiFi 新页交互与真实连接待确认 |
| 全流程执行 | 已实现未验收：现有7个子任务，打开窗口时全部默认不勾选，由操作员按本次需要明确选择；已移除“测试项配置（[order] 执行）”。二次确认并启动线程后自动隐藏全流程配置窗口，运行期间不重新弹出，完成/失败状态经主程序 UI 任务队列回收并把提示挂到主界面，不再由后台线程调用隐藏窗口 `after()`；主入口与停止按钮同时核对线程真实状态，后台已结束时自动清除残留运行态。主界面“环境检查与开关机测试”卡片使用加粗彩色徽标实时显示未运行、执行、停止和最终状态，其中“正在执行”为深绿色底白字；“停止测试”按钮继续复用同一编排器停止事件。进度条在全流程启动时重置，子任务7开始后按本次 `config.ini [ui_defaults] number_of_tests` 设置总轮次并显示“当前/总轮次”；多通道按最慢通道的已完成轮次推进，停止/失败保留现场进度，全部成功显示满格。“执行开关机测试”为第7项，勾选后在独立无 GUI 子进程复用旧 Start All 的 Telnet/SSH、程控电源和通道业务；主执行日志保留操作员信号、关键 logger 结果、警告/错误、实际电源帧及最终结论，过滤底层 INFO 噪声，合并2秒内重复日志以及不限时长的连续同文日志；“IP登录成功”在单次运行内按 IP 只显示第一次，可正确处理多个 IP 交替输出；“通道开始第 N 次测试”正文以绿色显示；旧英文网卡 Ping 成功日志按当前方案 `request_url` 转换为“Ping 成功：源网卡 IP → 目标样机 IP”；旧结果文件中的“通道N下挂的设备在第M次测试时正常”完整行也实时桥接为 `[旧工具Logs][INFO]`，原结果文件保持不变。全部通道结束后才返回结果；初始化会先全通道断电，启动前有明确危险确认。串口日志预启动、子任务1后120秒等待及既有失败边界保持不变；待桌面交互和真实样机验证 |

- DUT WAN 查询已从“只取连接名”扩展为一次读取 IP Interface、Ethernet/VLAN、PPP、Bridge、DHCP、DNS、NAT 的完整快照；选择下拉项会同步当前 WAN 表单。单台直接回填，多台仅在同名 WAN 的完整参数一致时回填，不一致时保留名称但提示人工核对。该行为代码与自动化测试已通过，真实样机字段兼容性和 Windows 界面待验收。
- DUT配置四个 Tab 的字段名称已统一左对齐，公共字段和WAN单独的“现有连接名/索引”均受回归测试保护；Windows桌面目视效果待验收。
- 最近一次**已记录**的完整回归：2026-08-09，`python scripts/verify_baseline.py` 全绿，记录为 549 项单元测试（49 个当前主程序源码文件编译覆盖、67 个强制基线测试均实际执行）。该数字是历史验证记录；下一次代码改动后必须以新实跑结果更新本文件和开发日志。
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
