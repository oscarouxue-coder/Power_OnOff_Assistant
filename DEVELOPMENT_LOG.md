# 开发记录

本文件用于按时间记录每次开发完成的功能、优化、修改、BUG 修复、验证方式和后续待办，方便下一次继续开发，也方便做整体项目概览和管理。

## 记录规则

- 每次完成代码、配置、文档或流程变更后，都在本文件顶部追加一条记录。
- 记录内容应尽量短，但要能说明改动目的、影响范围和验证结果。
- 如果改动会影响项目当前状态或后续入口，同步更新 `PROJECT_STATUS.md`。
- 如果新增或调整用户可见功能，同步更新对应 `README.md`。
- 不记录 `build`、`dist`、`logs`、`.venv` 目录中的生成内容。

## 记录模板

```markdown
## YYYY-MM-DD - 简短标题

- 类型：功能 / 优化 / 修改 / BUG 修复 / 文档 / 构建 / 测试
- 背景：
- 完成内容：
- 修改文件：
- 验证方法：
- 验证结果：
- 后续待办：
```

## 2026-07-12 - 并行 Tftp 指令高频日志不再阻塞 Tk 界面

- 类型：BUG 修复 / 测试 / 文档
- 背景：并行 `Tftp指令` 升级时，多路样机启动日志会高频进入串口终端；原终端每 80ms 逐条 Text 插入并滚动最多 200 次，主执行日志也会一次性清空队列，导致 Tk 主线程长期忙于渲染而显示“未响应”。
- 完成内容：串口终端按 VLAN 合并每轮事件，每 Tab 只插入/滚动一次，并设置 120 条或 10ms 的单轮预算；主执行日志改为每轮最多处理 120 条，积压时立即续跑。串口原始文件日志、升级并行调度、TFTPy 和程控电源时序不变。
- 修改文件：`Cheating_machine_execution_tool/src/ui/serial_terminal.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_serial_terminal.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串口终端、主界面和完整单元测试；真实两台并行 `Tftp指令` 样机验证 UI 响应。
- 验证结果：`python -m py_compile line_check_assistant/app.py src/ui/serial_terminal.py` 通过；串口终端专项 4 项、主界面专项 58 项通过；完整 `python -m unittest discover -s tests -v` 共 150 项通过。
- 后续待办：真实两台独立 VLAN 样机复测并行 `Tftp指令`，确认升级窗口和串口终端在高频启动日志下持续可响应。

## 2026-07-12 - 全包升级并行上限扩到 8 台 + 程控电源 COM 批次内复用

- 类型：功能 / 优化 / 测试 / 文档
- 背景：`Tftp指令` / `Tftp Put` 并行升级上限硬编码为 2 台，无法满足后续多 VLAN 真实样机需求；真实样机日志显示同一批次内程控电源 COM102 在每台样机上下电前后反复 open/close，扩到 8 台后浪费会放大 4 倍。
- 完成内容：`MAX_PARALLEL_UPGRADES = 8` 单一来源常量；`SampleUpgradeSettings` 新增 `parallel_count`（默认 2，存 ini，1–8 区间），Store 读写并加 `clamp_parallel_count` 防御非法值；UI 在执行方式 Combobox 右侧新增 `ttk.Spinbox`（1–8），串行时灰显；`_parallel_tftp_command_upgrade_worker` / `_parallel_tftp_put_upgrade_worker` 接收 `parallel_count` 并钳制后传入 `max_workers`，确认弹窗和状态文案跟随实际并行数。`UpgradePowerCycleCoordinator` 改为持有每条 COM 的长连接 `ProgrammablePowerSupply`，通过 `with UpgradePowerCycleCoordinator() as coordinator` 在两个并行 runner 收尾时统一 `close()`；serial 路径未动。`power_on_service.py` 未改接口，只新增一个供 coordinator 直接复用的入口（最终选择由 coordinator 直接调用 `supply.power_on_channels`）。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/Auto_power_on_off_tool/config/sample_upgrade_settings.ini`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 `python -m py_compile` 关键模块；`python -m unittest discover -s tests -v` 全量；新加 `coordinator` supply 复用与 `close()` 幂等两项断言。
- 验证结果：编译通过；`python -m unittest discover -s tests -v` 共 163 项通过；旧 coordinator 串行化测试改为对 `supply_factory` mock，新增 supply 只 open 一次 / close 幂等 2 项断言。
- 后续待办：真实 2 台、4 台、8 台独立 VLAN / COM 样机分别跑一次 `Tftp指令` 和 `Tftp Put` 并行升级，确认日志中"已打开 / 已关闭程控电源串口"各仅出现一次且 TFTPy 上传无错包；如实验室功率闸容量紧张，再评估在 coordinator 内加错峰 `power_cycle_offset_seconds` 开关（默认 0）。

## 2026-07-12 - Tftp Put 多台串行全包升级真实样机验收通过

- 类型：真实样机验收 / 状态更新
- 背景：Tftp Put 已完成前置下电上电、`UserName` 后 boot 登录、TFTPy 推送和串口终端自动收尾改造，需要确认多台按串行顺序执行时的完整链路。
- 完成内容：用户已完成全包升级 `Tftp Put` 多台串行真实样机验收，结果通过。
- 修改文件：`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：真实样机多台串行升级。
- 验证结果：通过。
- 后续待办：`Tftp指令` 两台并行仍待真实两台独立 VLAN 样机验收。

## 2026-07-12 - 全包升级结束后关闭自动打开的串口终端

- 类型：BUG 修复 / 测试 / 文档
- 背景：全包升级完成后，升级会话已写入 `STATE 串口已关闭` 并释放 COM 口，但本次自动打开的“串口日志记录”窗口仍残留。
- 完成内容：串口终端记录自动升级批次；串行全包升级和并行 `Tftp指令` 均在批次完成并释放会话后延迟 100ms 请求终端收尾。仅升级自动打开的终端会关闭，手动打开的终端保持打开。
- 修改文件：`Cheating_machine_execution_tool/src/ui/serial_terminal.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_serial_terminal.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串口终端、主界面升级流程相关测试、完整单元测试和源码编译检查。
- 验证结果：`python -m py_compile line_check_assistant/app.py src/ui/serial_terminal.py` 通过；串口终端专项 3 项、主界面专项 57 项通过；完整 `python -m unittest discover -s tests -v` 共 148 项通过。
- 后续待办：真实样机验证 `STATE 串口已关闭` 后本次自动打开的串口终端窗口关闭，手动打开的终端不受影响。

## 2026-07-12 - 恢复出厂命令同步到主程序执行日志

- 类型：优化 / 测试 / 文档
- 背景：串口日志可见 `TX firstboot -y;reboot`，但主程序执行日志未体现已实际下发恢复出厂命令，操作员无法在主界面确认危险操作是否执行。
- 完成内容：恢复出厂命令写入串口成功后，向主程序执行日志输出 `TX firstboot -y;reboot`；未启用恢复出厂时不输出该日志。两种全包升级传输方式均复用此日志回调，传输时序不变。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串行升级专项测试、完整单元测试和源码编译检查。
- 验证结果：`python -m py_compile src/services/serial_upgrade_service.py` 通过；串行升级专项 22 项通过；完整 `python -m unittest discover -s tests -v` 共 147 项通过。
- 后续待办：真实样机勾选恢复出厂时确认主程序执行日志出现该 TX 行；未勾选时确认不出现。

## 2026-07-12 - Tftp Put boot 登录不再漏掉同批 ECNT 提示

- 类型：BUG 修复 / 测试 / 文档
- 背景：真实串口日志显示 boot 密码提交后已出现 `ECNT>`，但 Tftp Put 专用登录逻辑在写密码并等待 1 秒后才记录 shell 等待游标，导致 `ECNT>` 落在游标之前而误报“boot 登录后未检测到 shell 提示符”。
- 完成内容：把 Tftp Put 专用 boot 登录的 shell 等待游标提前到 boot 密码写入前；`ecnt>` 已是现有 shell 提示识别项，修复后可匹配同批 `ECNT>` 并继续 TFTPy 传输。未改动 `Tftp指令` 路径。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串行升级专项测试、完整单元测试和源码编译检查。
- 验证结果：`python -m py_compile src/services/serial_upgrade_service.py` 通过；串行升级专项 21 项通过；完整 `python -m unittest discover -s tests -v` 共 146 项通过。
- 后续待办：使用真实 Tftp Put 样机确认 `ECNT>` 后立即进入 TFTPy 传输阶段。

## 2026-07-12 - Tftp Put boot 登录不再漏掉同批 Password 提示

- 类型：BUG 修复 / 测试 / 文档
- 背景：真实串口日志已显示 `UserName: telecomadmin` 后紧接 `Password:`，但 Tftp Put 专用登录逻辑在写用户名并等待 0.3 秒后才记录等待游标，导致同批到达的 `Password:` 落在游标之前而被漏检。
- 完成内容：把 Tftp Put 专用 boot 登录的密码等待游标提前到用户名写入前，确保用户名回显期间或同批数据中的完整 `Password:` 仍可匹配；未改动 `Tftp指令` 路径。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串行升级专项测试、完整单元测试和源码编译检查。
- 验证结果：`python -m py_compile src/services/serial_upgrade_service.py` 通过；串行升级专项 20 项通过；完整 `python -m unittest discover -s tests -v` 共 145 项通过。
- 后续待办：使用真实 Tftp Put 样机确认 `UserName` 后同批 `Password:` 可被识别并继续发送 boot 密码。

## 2026-07-12 - Tftp Put 检测 UserName 后按 boot 凭据登录并保留 TFTPy 上传

- 类型：BUG 修复 / 测试 / 文档
- 背景：`Tftp Put` 前置下电 + 上电完成后，现场要求以串口 `UserName:` 作为 boot 登录起点，沿用同事 `serial_upgrade.py` 的 boot 凭据交互，而不再先登录最终系统并发送 `reboot`。
- 完成内容：新增仅由 `Tftp Put` 调用的「循环回车等待 `UserName:` → `telecomadmin / nE7jA%5m` 登录 boot」状态机；登录成功后继续复用主程序 `prepare_tftp_network()` 和 TFTPy Client 上传，不调用 Windows `tftp.exe`。保留传输后的 boot 重启检测、最终系统登录及恢复出厂；`Tftp指令` 未调整。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串行升级专项测试、完整单元测试和源码编译检查。
- 验证结果：`python -m py_compile src/services/serial_upgrade_service.py` 通过；串行升级专项 19 项通过；完整 `python -m unittest discover -s tests -v` 共 144 项通过。
- 后续待办：使用真实 `Tftp Put` 样机确认日志顺序为“串口已开启”→等待 1 秒→检测到 `UserName`→boot 登录→TFTPy 上传。

## 2026-07-11 - Tftp Put 开始前先对样机执行下电 + 上电

- 类型：功能 / 程控电源 / 重构 / 测试 / 文档
- 背景：现场反馈 `Tftp Put` 升级时样机经常不是干净的上电状态，需要主程序在开始原有 reboot → boot → TFTP 流程前，先对程控电源对应通道做一次下电 + 上电，确保样机从已知上电状态启动；该需求与现有 `Tftp指令` 链路的「断电再上电」语义一致。
- 完成内容：把 `serial_upgrade_service.py` 中 `_run_tftp_command_with_power_supply` 内联的 `power_on_current_channel` 抽出为模块级 helper `_power_cycle_current_channel()`，复用 `power_on_selected_channels`（串行）或 `UpgradePowerCycleCoordinator`（并行）；`Tftp Put` 分支在打开串口后立即调用该 helper 对 `request.power_serial_port / request.power_channel` 执行下电 + 上电（`wait_seconds=0`，由后续 `login_final_system` 的 900 秒首轮等待兜底样机启动），失败立即返回；`Tftp指令` 链路行为保持不变，仅复用同一 helper。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile` 编译；运行 `test_serial_upgrade_service.py` 及完整单元测试。
- 验证结果：编译通过；`test_serial_upgrade_service.py` 新增 1 项（`test_full_package_upgrade_tftp_put_propagates_power_cycle_failure`），重命名 / 调整 2 项（原 `skips_programmable_power_supply` / `does_not_invoke_power_supply_module` 已不能描述新行为）；完整 `python -m unittest discover -s tests` 共 143 项全部通过。
- 后续待办：真实样机验证 `Tftp Put` 在开始 reboot 之前程控电源下电 + 上电日志与上电时序，并确认主流程未受影响。

## 2026-07-11 - 页面升级前先把网卡设为样机同网段

- 类型：优化 / 重构 / 测试 / 文档
- 背景：现场 `vlan137/138/139` 页面升级前 PC 网卡已启用但 IP 仍为旧配置，与样机管理 IP（如 `192.168.29.1`）不在同一网段，导致 HTTP/HTTPS 登录 UBUS 前路由不通。
- 完成内容：在 `network_ops.py` 抽出 `prepare_network_for_sample()`，封装「启用网卡 → 设置静态 IP → 缓冲 2 秒」的统一流程，原 `run_line_check` 复用同一 helper；`PageUpgradeRequest` 新增 `subnet_mask` 字段（默认 `255.255.255.0`），`run_single_page_upgrade` 在启用网卡之后改用 `prepare_network_for_sample()`，把 PC 静态 IP 切到样机管理 IP 所在网段；`app.py` 把 `ChannelConfig.subnet_mask` 透传给 `PageUpgradeRequest`。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_page_upgrade.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile` 编译主程序、网络与页面升级模块；运行 `test_network_ops.py`、`test_page_upgrade.py`、`test_app.py` 及完整单元测试。
- 验证结果：编译通过；`test_network_ops.py` 新增 6 项（启用网卡 + 静态 IP、启用失败、设 IP 失败、缺 alias、缺 bind_ip、display name 兼容）；`test_page_upgrade.py` 新增/调整 4 项；`test_app.py` 新增 1 项；完整 `python -m unittest discover -s tests` 共 142 项全部通过。
- 后续待办：使用真实 `vlan137/138/139` 复测页面升级，确认 PC 网卡 IP 已切到样机管理 IP 所在网段，且 HTTP/HTTPS 登录一次成功。

## 2026-07-11 - Boot 登录按新提示符逐步提交凭据

- 类型：BUG 修复 / 测试 / 文档
- 背景：现场日志显示 `UserName:` 与 `Password:` 分段到达时，用户名后仍可能使用旧串口缓存中的密码提示符，导致账号密码提交错位。
- 完成内容：Boot 登录仅在完整用户名提示符后发送用户名；用户名回车后重新取串口游标，只接受新到达的完整密码提示符才发送密码；登录结果也从密码回车后的新游标开始等待。
- 修改文件：`src/services/serial_upgrade_service.py`、`tests/test_serial_upgrade_service.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译串行升级服务，运行串行升级及完整单元测试。
- 验证结果：串行升级专项 12 项通过；完整 `python -m unittest discover -s tests -v` 共 124 项通过；新增回归测试确认密码提示符的等待游标晚于用户名回车，不会命中用户名输入前的旧缓存。
- 后续待办：使用真实 `Tftp指令` 样机复测分段 `UserName:` / `Password:` 回显。

## 2026-07-11 - 串口终端目录写入失败改为明确提示

- 类型：BUG 修复 / 测试 / 文档
- 背景：默认 `D:\Serial_Log` 或本机串口终端状态文件不可写时，原逻辑会吞掉异常，操作员无法判断日志或窗口设置未保存。
- 完成内容：默认日志目录创建失败和终端状态文件写入失败均弹出明确错误信息，并提示可通过“浏览…”选择可写日志目录。
- 修改文件：`src/ui/serial_terminal.py`、`tests/test_serial_terminal.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串口终端持久化测试和完整单元测试。
- 验证结果：`python -m py_compile` 通过；完整 `python -m unittest discover -s tests -v` 共 123 项通过；新增测试覆盖默认日志目录创建失败及终端状态文件保存失败时的错误弹窗。
- 后续待办：无。

## 2026-07-11 - 自动上/下电增加下电选择

- 类型：功能 / 测试 / 文档
- 背景：用户要求将“自动上电”扩展为“自动上/下电”，并在二级弹窗中用下拉框选择上电或下电，默认上电。
- 完成内容：工具栏入口改为“自动上/下电”；COM 选择弹窗新增默认“上电”的操作下拉框；下电仅向勾选通道按顺序发送关闭帧、相邻间隔 1 秒，不发送全断电帧。全包升级和 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 均未修改。
- 修改文件：`src/core/power_supply.py`、`src/services/power_on_service.py`、`src/services/__init__.py`、`line_check_assistant/app.py`、`tests/test_power_supply.py`、`tests/test_app.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译主程序和上下电服务；运行完整单元测试；核对旧工具源码哈希未变化。
- 验证结果：编译通过，完整 `python -m unittest discover -s tests -v` 共 111 项通过；单元测试验证下电仅发送所选通道关闭帧、相邻帧间隔 1 秒且不含全断电帧；`Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 哈希未变化。
- 后续待办：在真实程控电源上验收下电操作的关闭帧顺序和 1 秒间隔。

## 2026-07-11 - 取消自动上电后的启动等待

- 类型：优化 / 测试 / 文档
- 背景：用户要求最后一条自动上电开启帧发送后不再额外等待 10 秒。
- 完成内容：主程序自动上电的启动等待改为 0 秒；相邻开启帧的 1 秒间隔保持不变。全包升级及旧工具源码均未修改。
- 修改文件：`line_check_assistant/app.py`、`tests/test_app.py`、`tests/test_power_supply.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译主程序；运行完整单元测试；确认旧工具源码哈希未变化。
- 验证结果：编译通过，完整 `python -m unittest discover -s tests -v` 共 108 项通过；单元测试验证两条开启帧之间仅等待 1 秒、最后一条开启帧后无额外启动等待；`Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 哈希未变化。用户已在真实程控电源完成新自动上电流程验收，结果通过。
- 后续待办：无；全包升级的断电重启流程继续按独立路径验收。

## 2026-07-11 - 自动上电开启帧按通道间隔 1 秒

- 类型：BUG 修复 / 测试 / 文档
- 背景：现场日志显示通道 1-8 的开启帧在同一秒内连续发送；用户确认需要相邻开启指令间隔 1 秒。
- 完成内容：主程序“自动上电”的仅开启路径改为首个通道立即开启、后续每个通道开启前等待 1 秒；全部开启帧完成后再统一等待 10 秒。未改变断电策略、全包升级路径或 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py`。
- 修改文件：`src/core/power_supply.py`、`src/services/power_on_service.py`、`line_check_assistant/app.py`、`tests/test_power_supply.py`、`tests/test_app.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译主程序和上电服务；运行程控电源、主界面与串行升级单元测试；确认旧工具源码哈希未变化。
- 验证结果：待本次改动完成后填写。
- 后续待办：在真实程控电源上确认开启日志相邻时间约为 1 秒。

## 2026-07-11 - 自动上电改为一次性开启勾选通道

- 类型：优化 / 测试 / 文档
- 背景：用户要求主程序“自动上电”确认后一次性开启所有勾选通道，不再先完全断电或按通道逐个断电/上电；同时明确不得影响 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 业务逻辑。
- 完成内容：主程序新增仅开启通道的程控电源服务，连续发送勾选通道的开启帧且不插入关闭帧；自动上电统一等待 10 秒；全包升级原有断电重启路径及旧工具源码均未修改。
- 修改文件：`src/core/power_supply.py`、`src/services/power_on_service.py`、`src/services/__init__.py`、`line_check_assistant/app.py`、`tests/test_power_supply.py`、`tests/test_app.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译主程序和上电服务；运行程控电源、主界面及串行升级相关单元测试；比对旧工具源码未改动。
- 验证结果：`Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 与移动前 Git 版本哈希一致；编译通过，完整 `python -m unittest discover -s tests -v` 共 108 项通过；单元测试验证自动上电只写入全部勾选通道的开启帧，不含全断电或关闭帧，且全包升级仍走原有独立上电服务。
- 后续待办：使用真实程控电源确认多通道开启帧连续下发后，所有勾选通道可同时启动。

## 2026-07-11 - 统一主程序配置目录到旧工具源码目录

- 类型：重构 / 配置 / 文档 / 测试
- 背景：用户将 `Auto_power_on_off_tool` 移入 `Cheating_machine_execution_tool`，要求所有原先读写同级 `config` 的主程序逻辑统一改为读写 `Auto_power_on_off_tool/config`，并删除旧目录。
- 完成内容：新增统一配置目录解析；主界面通道、ONU 注册和样机升级状态均改写新目录；迁入现有通道配置和本机保存状态，保留旧工具已有的产品配置及原同级配置项；删除原同级 `config` 目录。
- 修改文件：`line_check_assistant/paths.py`、`line_check_assistant/app.py`、`tests/test_paths.py`、`.gitignore`、`Auto_power_on_off_tool/config`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译主程序与路径模块；运行路径和配置存储相关单元测试；确认旧目录不存在且主程序配置路径指向新目录。
- 验证结果：旧目录确认不存在；主程序导入后四个配置路径均指向新目录；迁入的通道配置可解析为 16 个通道、程控电源端口为 `COM105`；`python -m py_compile` 通过，完整 `python -m unittest discover -s tests -v` 共 106 项通过。
- 后续待办：真实设备流程继续以新目录中的 `network_card_ip.ini` 为唯一配置源。

## 2026-07-11 - 主程序内置程控电源直连，移除旧 GUI 上电依赖

- 类型：功能 / 重构 / 测试 / 文档
- 背景：自动上电和全包升级原先启动 `Auto_Power_On_Off_Tool.exe` 并通过 UI Automation 选择 COM、配置和 `Start ALL`，窗口控件状态会造成不稳定；用户提供旧工具源码，要求改为主程序直接控制程控电源。
- 完成内容：从旧源码提取 16 通道程控电源串口协议，新增无界面 `src/core/power_supply.py` 与上电服务；自动上电会二次确认“先关闭全部通道”，再按勾选的 `channel_x` 直接发送关闭/上电帧；全包升级从当前 `channel_x` 传递程控电源通道，写入上电帧后立即开始 boot 监听，重上电也走同一条直连路径；运行时主路径不再调用旧 EXE、PyQt 或 UI Automation。
- 修改文件：`Cheating_machine_execution_tool/src/core/power_supply.py`、`src/services/power_on_service.py`、`src/services/serial_upgrade_service.py`、`src/models/serial_models.py`、`src/core/__init__.py`、`src/services/__init__.py`、`line_check_assistant/app.py`、`tests/test_power_supply.py`、`tests/test_app.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译入口、主界面、直连核心和升级服务；导入主程序与上电服务；运行完整单元测试；检查运行时目录中不再存在旧 GUI 自动化调用。
- 验证结果：编译和导入通过；完整 `python -m unittest discover -s tests -v` 共 105 项通过；新增 5 项程控电源测试验证旧协议帧、全关后指定通道开关顺序、串口关闭、启动等待、非法通道不打开串口，以及全包升级首次上电和重上电均使用当前 `channel_x`。
- 后续待办：在真实程控电源上先验证 `COM` 口与 `19200 8N1` 参数、单通道断电/上电帧和通道映射；确认后再验收多通道自动上电及全包升级中的首次上电、重上电流程。

## 2026-07-11 - 修复主程序 VS Code 源码启动环境

- 类型：BUG 修复 / 配置 / 文档 / 测试
- 背景：用户在 VS Code 运行 `run_line_check_assistant.py` 时，专用 `.venv_serial_upgrade` 缺少主程序新增的 `tftpy`，启动期导入 `src.core.tftp_transport` 后报 `ModuleNotFoundError`；现有 F5 配置也只覆盖独立 `serial_upgrade.py`。
- 完成内容：为 VS Code 新增 `LineCheckAssistant` 调试入口，固定以 `Cheating_machine_execution_tool` 为工作目录；主程序依赖清单补充 `requests` 并在 `.venv_serial_upgrade` 安装 `tftpy==0.8.7`；README 补充首次安装依赖和 VS Code 运行步骤；项目状态同步主程序源码运行入口。
- 修改文件：`.vscode/launch.json`、`Cheating_machine_execution_tool/requirements.txt`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：使用 `.venv_serial_upgrade` 编译入口、主界面和 TFTP 模块；导入 `line_check_assistant.app`；执行 `pip check`；解析 `.vscode/launch.json`；运行 `test_tftp_transport.py`。
- 验证结果：编译通过；`LineCheckAssistant import OK`；`tftpy=0.8.7`；`No broken requirements found.`；`launch.json JSON OK`；`test_tftp_transport.py` 2 项通过。
- 后续待办：用户可在 VS Code 选择 `LineCheckAssistant` 后按 F5 完成界面与现场设备功能验证。

## 2026-07-10 - 主程序内置 pySerial 与 TFTPy 串行升级

- 类型：功能 / 重构 / 测试 / 文档
- 背景：全包升级原先依赖 SecureCRT、Tftpd64 和 Windows TFTP 客户端，串口状态机不可执行测试且多网卡源 IP 不可控。
- 完成内容：新增 `src/models`、`src/core`、`src/services`、`src/ui` 分层；pySerial 接管 VLAN→COM 的收发、状态 marker、终端显示与独占写锁；TFTPy Server 接管设备拉取并仅映射所选固件为 `tclinux_allinone`，TFTPy Client 接管 Put 并绑定当前通道源 IP；内置多通道终端替换占位窗口；保留两种 TFTP 语义、串行顺序、配置隔离、reset/登录/恢复出厂时序；移除旧 Python/VBS 自动化模块和旧实现测试。
- 修改文件：主界面、`src` 新模块、测试、依赖清单、第三方声明、构建脚本、README、PROJECT_STATUS。
- 验证方法：编译检查、完整单元测试、TFTPy 本机高端口上传/下载端到端测试。
- 验证结果：`python -m py_compile` 通过；完整 `python -m unittest discover -s tests -v` 100 项通过。
- 后续待办：在真实设备上分别验收两种传输、恢复出厂、多样机串行、端口占用、串口拔出、UDP 69 防火墙和多 `.1` 网卡源 IP。

## 2026-07-09 - 修复 Tftp Put 恢复出厂提交和 CRT 主窗口残留

- 类型：BUG 修复 / 优化 / 测试 / 文档
- 背景：用户验证 `Tftp Put` 模式在固件传输完成、重启并登录最终系统后，恢复出厂命令停留在 CRT 窗口中未真正下发；同时样机升级收尾只关闭了升级 Tab，SecureCRT 主窗口仍残留。
- 完成内容：恢复出厂逻辑改为发送 `firstboot -y;reboot` 后固定等待 1 秒再发送回车，不再等待命令回显；SecureCRT 升级脚本在关闭当前升级 Tab 后继续请求关闭 SecureCRT 主窗口，收尾日志同步说明 Tab 和主窗口都会由脚本请求关闭。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant/upgrade_cleanup.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/tests/test_tftpd_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、`test_securecrt_automation.py`、`test_tftpd_automation.py` 和完整单元测试。
- 验证结果：编译检查通过；`test_securecrt_automation.py` 16 项全部 OK；`test_tftpd_automation.py` 3 项全部 OK；完整 `python -m unittest discover -s tests -v` 123 项全部 OK。
- 后续待办：用真实 `Tftp Put + 恢复出厂` 样机升级复测，确认串口日志中命令 1 秒后下发并触发恢复出厂重启，且 SecureCRT 主窗口随升级结束关闭。

## 2026-07-08 - 恢复出厂命令发送后延迟关闭 SecureCRT Tab

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户验证勾选“恢复出厂”时，最终系统只成功登录，随后 SecureCRT 升级窗口很快关闭，`firstboot -y;reboot` 可能未完整下发。
- 完成内容：将恢复出厂发送逻辑从 `factoryResetCommand & vbCr` 后立即完成，改为先发送命令文本，等待命令回显或最多 5 秒，随后发送回车并记录 `RESTORE_FACTORY_SENT`，再额外等待 8 秒才写入 `DONE` 并关闭当前升级 Tab；回显未出现时记录 `RESTORE_FACTORY_ECHO_MISSED` 但继续发送回车，避免现场回显差异导致流程卡死。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/securecrt_automation.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、`test_securecrt_automation.py` 和完整单元测试。
- 验证结果：编译检查通过；`test_securecrt_automation.py` 16 项全部 OK；完整单元测试 123 项全部 OK。
- 后续待办：真实样机复测勾选“恢复出厂”时确认串口日志出现 `firstboot -y;reboot` 并触发重启。

## 2026-07-08 - SecureCRT 升级脚本完成后自关闭当前 Tab

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户验证多台样机串行 `Tftp Put` 升级可成功，但收尾日志显示未检测到本次新增 SecureCRT 窗口 PID，导致本轮升级打开的 CRT 窗口没有关闭。
- 完成内容：保留 Python 按本次新增 PID 兜底关闭的安全边界，避免误关用户手动 CRT；同时在 SecureCRT 升级脚本写入 `DONE` 后主动请求关闭当前脚本创建的升级 Tab，若关闭 API 不可用则写入 `SECURECRT_TAB_CLOSE_SKIPPED` 状态，避免因为窗口 PID 识别不到而无法关闭本轮升级 Tab；收尾日志改为说明脚本会自行请求关闭当前升级 Tab。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant/upgrade_cleanup.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/tests/test_tftpd_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、`test_securecrt_automation.py`、`test_tftpd_automation.py` 和完整单元测试。
- 验证结果：编译检查通过；`test_securecrt_automation.py` 16 项全部 OK；`test_tftpd_automation.py` 3 项全部 OK；完整单元测试 123 项全部 OK。
- 后续待办：用真实多台 `Tftp Put` 串行升级确认每台升级完成后当前 CRT Tab 能自动关闭。

## 2026-07-08 - 修复恢复出厂选项显示与确认状态

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户反馈 `Tftp Put` 单台升级成功后，未勾选“恢复出厂”却实际执行了恢复出厂。
- 完成内容：定位为样机升级窗口初始化时“恢复出厂”文字固定显示为未勾选，但底层布尔值会从 `config/sample_upgrade_settings.ini` 读取上次保存状态，可能出现界面显示未勾选而实际请求为开启；改为初始化文本直接按真实保存值生成，并在开始串行升级确认框中明确显示“恢复出厂：开启/关闭”。同时确认 SecureCRT 脚本仅在 manifest 字段为 `"1"` 时发送 `firstboot -y;reboot`。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、`test_app.py`、`test_securecrt_automation.py` 和完整单元测试。
- 验证结果：编译检查通过；`test_app.py` 55 项全部 OK；`test_securecrt_automation.py` 16 项全部 OK；完整单元测试 123 项全部 OK。
- 后续待办：用真实样机再次确认未勾选恢复出厂时不会发送 `firstboot -y;reboot`。

## 2026-07-08 - 收尾只关闭本次启动的 SecureCRT PID

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户反馈升级收尾日志中强制关闭了多个 SecureCRT 进程，其中部分是用户手动打开的其它 CRT 串口窗口。
- 完成内容：定位为 `upgrade_cleanup.py` 按进程名关闭所有 `SecureCRT`，清理范围过宽；改为启动 SecureCRT 前后对比新增窗口句柄并反查真实 PID，单台升级把新增 PID 回传给串行 worker，收尾只按这些精确 PID 关闭本次启动的 SecureCRT，同时继续按精确路径关闭项目目录下的 `tftpd64.exe`；未识别到新增 PID 时保留现有 CRT 会话。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/upgrade_cleanup.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_tftpd_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、SecureCRT PID 获取测试、单台升级 PID 回传测试、串行 worker 收尾传参测试、Tftpd/收尾脚本测试和完整单元测试。
- 验证结果：编译检查通过；完整单元测试 122 项全部 OK。
- 后续待办：真实升级后确认只关闭本次升级启动的 SecureCRT 窗口，不影响用户手动打开的其它 CRT 会话。

## 2026-07-08 - 提前 Tftp Put 进入 boot 敲回车时机

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户实测 `Tftp Put` 模式未成功进入 boot，原因是 SecureCRT 开始循环敲击回车的时间滞后，错过允许进入 boot 的窗口期。
- 完成内容：将 `boot_enter.signal` 从旧工具完整上电流程返回后前移到旧工具输出“已点击 Start ALL”时立即写出，让 SecureCRT 在 Start ALL 后马上每隔 1 秒敲击回车；保留旧软件关闭后的兜底信号，避免旧工具未输出该行时流程卡住。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、`test_sample_upgrade.py` 和完整单元测试，并补充 Start ALL 输出时立即写 boot signal 的回归测试。
- 验证结果：编译检查通过；`test_sample_upgrade.py` 11 项全部 OK；完整单元测试 121 项全部 OK。
- 后续待办：用真实样机复测 `Tftp Put` 进入 boot 时序。

## 2026-07-08 - 接入全包升级 Tftp Put 传输方式

- 类型：功能 / 测试 / 文档
- 背景：用户确认 `Tftp指令` 和 `Tftp Put` 是两种不同的固件传输方式，`Tftp Put` 目标设备 IP 固定为 `192.168.1.1`，需要在样机升级模块中都做适配。
- 完成内容：`全包升级 + Tftp Put` 进入现有多台串行升级流程；单台流程在 SecureCRT 完成 boot 登录后执行 Windows `tftp -i 192.168.1.1 put <升级固件路径>`，不启动 Tftpd64；Put 成功后继续复用现有 boot reset/重新上电、120 秒等待和最终登录确认；SecureCRT manifest 增加传输方式字段，脚本按 `Tftp指令` / `Tftp Put` 分支同步状态。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/securecrt_automation.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、样机升级入口测试、单台升级编排测试、SecureCRT 自动化测试和完整单元测试。
- 验证结果：编译检查通过；`test_app.py` 54 项通过；`test_sample_upgrade.py` 10 项通过；`test_securecrt_automation.py` 16 项通过；完整单元测试 120 项全部 OK。
- 后续待办：用真实样机验收 `全包升级 + Tftp Put`。

## 2026-07-08 - 样机升级 Tftp 文案调整

- 类型：修改 / 测试 / 文档
- 背景：用户要求将样机升级模块中的“Tftp拷贝命令”显示文案改为“Tftp指令”。
- 完成内容：样机升级固件传输方式下拉框、提示文案和确认文案统一显示为“Tftp指令”；保留旧配置值“Tftp拷贝命令”的自动兼容映射，避免已保存本机配置影响串行升级入口。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查和样机升级入口相关单元测试。
- 验证结果：编译检查通过；`test_app.py` 53 项全部 OK。
- 后续待办：无。

## 2026-07-07 - 页面升级前自动启用目标网卡

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户实测 `vlan137`、`vlan138` 页面升级失败，原因为 PC 对应 VLAN 网卡未启用，导致无法登录 UBUS。
- 完成内容：页面升级请求新增目标网卡字段；每台样机执行 UBUS 登录前先调用现有 `enable_adapter()` 启用对应网卡，启用失败则只标记该样机失败并保留日志，其它并行样机继续执行。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_page_upgrade.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行页面升级单元测试、样机升级入口测试、编译检查和完整测试集。
- 验证结果：编译检查通过；`test_page_upgrade.py` 5 项通过；`test_app.py` 52 项通过；完整单元测试 111 项全部 OK。
- 后续待办：用真实 `vlan137`、`vlan138` 复测未启用网卡场景。

## 2026-07-07 - 兼容 UBUS 触发升级 Access denied

- 类型：BUG 修复 / 测试
- 背景：用户实测页面升级时，`vlan139` 在触发 UBUS 升级阶段返回 `Access denied`；后续确认原因是浏览器仍登录样机 Web 管理界面，退出 Web 管理界面后升级成功。
- 完成内容：为 UBUS RPC 错误增加调用点上下文；触发升级命令从单一 `bbfdm.operate` 改为依次尝试 `bbfdm.operate`、`bbfdm.operate(proto=web)` 和 `bbfdm.unauthenticated_operate`，遇到 `Access denied` 时自动尝试下一种兼容方式，并在日志中输出切换过程。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`、`Cheating_machine_execution_tool/tests/test_page_upgrade.py`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行页面升级单元测试、样机升级入口测试、编译检查和完整测试集。
- 验证结果：编译检查通过；`test_page_upgrade.py` 4 项通过；`test_app.py` 52 项通过；完整单元测试 110 项全部 OK。
- 后续待办：页面升级操作前提醒退出样机 Web 管理界面；如后续仍出现 `Access denied`，再根据日志中的 UBUS 调用点排查账号权限或接口差异。

## 2026-07-07 - 接入 UBUS 页面批量升级

- 类型：功能 / 测试 / 文档
- 背景：用户提供同事的 `ubus_upgrade_gui.py` / `ubus_upgrade.py`，要求将已验证的 UBUS 批量页面升级能力合并到现有“样机升级”的“页面升级”功能中。
- 完成内容：新增页面升级业务模块，支持绑定本机 IP、HTTP/HTTPS 登录 UBUS、上传固件、触发升级、查询状态和等待重启上线；“页面升级”按钮改为按已勾选通道并行执行 UBUS 批量升级；保留“全包升级 + Tftp拷贝命令”现有串行流程。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_page_upgrade.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、页面升级单元测试、样机升级入口单元测试和完整测试集。
- 验证结果：编译检查通过；`test_page_upgrade.py` 2 项通过；`test_app.py` 52 项通过；完整单元测试 108 项全部 OK。
- 后续待办：使用真实样机验证页面升级的单台、多台并行和失败日志表现。

## 2026-07-07 - 配置 serial_upgrade.py 的 VS Code 运行环境

- 类型：配置 / 文档 / 测试
- 背景：用户希望直接在 VS Code 中运行 `Cheating_machine_execution_tool/test_boot_upgrade/serial_upgrade.py`。
- 完成内容：新增 VS Code 默认解释器与调试入口；新增 `test_boot_upgrade/requirements.txt`；将专用本地 Python 环境加入忽略列表；更新 `serial_upgrade` 使用指南和项目状态。
- 修改文件：`.vscode/settings.json`、`.vscode/launch.json`、`.gitignore`、`Cheating_machine_execution_tool/test_boot_upgrade/requirements.txt`、`Cheating_machine_execution_tool/test_boot_upgrade/使用指南.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：创建本地 Python 环境，安装 `pyserial`、`selenium`、`webdriver-manager`、`openpyxl`；运行编译检查和依赖导入检查。
- 验证结果：`python -m py_compile serial_upgrade.py` 通过；`serial`、`selenium`、`webdriver_manager`、`openpyxl` 导入通过。
- 后续待办：首次选择“页面升级”时，若 `webdriver-manager` 下载 Edge WebDriver 被网络或证书拦截，需要按现场网络环境处理。

## 2026-07-03 - 兼容旧工具 exe 新文件名

- 类型：优化 / 测试 / 文档
- 背景：用户将旧开关机工具从 `Auto_Power_On_Off_Tool(2).exe` 改名为 `Auto_Power_On_Off_Tool.exe`，要求程序只按 `Auto_Power_On_Off_Tool` 关键字识别。
- 完成内容：新增旧工具路径解析函数，查找根目录下文件名包含 `Auto_Power_On_Off_Tool` 且后缀为 `.exe` 的旧工具，优先使用 `Auto_Power_On_Off_Tool.exe`，兼容原 `(2)` 文件名；主程序自动上电和样机升级流程共用解析后的旧工具路径。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/paths.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_paths.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\paths.py`、`python -m unittest discover -s tests -p test_paths.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_paths.py` 3 项全部 OK；完整单元测试 103 项全部 OK。
- 后续待办：无。

## 2026-07-03 - ONU注册 清理离线 ONU 后重新注册

- 类型：BUG 修复 / 安全提示 / 测试 / 文档
- 背景：用户反馈原有 ONU 替换方式会替换到与新发现 ONU 不同 PON 口的旧 ONU，正确流程应删除不在线 ONU 后重新注册新 ONU。
- 完成内容：ONU 注册新增配置失败后不再执行 `registration-method sn 新SN` 复用旧 ONU 配置；改为查询 `show gpon onu state`，筛选已注册但不在线 ONU，优先删除和新 ONU 同 PON 口的不在线 ONU，再删除其它 PON 口不在线 ONU，删除后重新下发新 ONU 注册模板；注册确认提示同步说明该删除和重试行为。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_network_ops.py` 24 项全部 OK；完整单元测试 100 项全部 OK；新增回归覆盖新增配置失败后查询离线 ONU、优先删除同 PON 口离线 ONU、再删除其它 PON 口离线 ONU，并确认不再下发 `registration-method sn 新SN`。
- 后续待办：无。

## 2026-07-02 - 优化 ONU注册 长状态栏显示

- 类型：UI / 优化 / 测试 / 文档
- 背景：用户反馈 ONU注册 窗口中查询/注册状态栏显示不完整，长注册结果会在右侧被截断。
- 完成内容：将 ONU注册 查询/注册状态栏改为支持自动换行的多行状态框，增加垂直内边距并改为左上对齐；绑定状态框宽度变化，动态更新换行宽度，避免长 SN 或长注册结果被截断。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`，并执行 ONU注册 长状态文本布局探针。
- 验证结果：编译检查通过；`test_app.py` 49 项全部 OK；布局探针确认状态栏 `anchor=nw`、`pady=4`、`wraplength=640`。
- 后续待办：无。

## 2026-07-02 - ONU注册 注册后确认保存 OLT 配置

- 类型：功能 / 安全提示 / 测试 / 文档
- 背景：用户要求新 ONU 注册完成后弹出提示，询问是否保存 OLT 最新配置；用户确认保存时执行 `write` 写入启动配置。用户进一步验证确认这台 OLT 需要先退出全局模式，不能在 `ZXAN(config)#` 下执行 `write`。
- 完成内容：新增 OLT 配置保存底层能力，保存时独立登录 OLT，若检测到 `config` 或 `config-if` 提示符则循环执行 `exit` 直到回到执行模式，再执行 `write`；ONU 注册成功后弹窗询问是否保存，用户确认后异步执行保存并显示/记录保存结果，用户取消则只记录暂不保存。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_network_ops.py` 24 项全部 OK；`test_app.py` 49 项全部 OK；完整单元测试 100 项全部 OK；新增测试覆盖 `ZXAN(config)# exit -> ZXAN# write`、`ZXAN(config-if)# exit -> ZXAN(config)# exit -> ZXAN# write` 和注册成功后确认/取消保存两种 UI 分支。
- 后续待办：无。

## 2026-07-02 - 微调 ONU注册 密码小眼睛和开始注册按钮位置

- 类型：UI / 优化 / 测试
- 背景：用户反馈 ONU注册 窗口中密码小眼睛需要往右边移一点，“开始注册”按钮需要往左边移一点。
- 完成内容：将 ONU注册 密码输入框容器横跨右侧一列，让小眼睛按钮更靠右显示；收窄“取消全选”和“开始注册”之间的横向间距，使“开始注册”按钮整体更靠左。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`，并执行 ONU注册 布局探针确认密码容器跨列、按钮 padding 生效。
- 验证结果：编译检查通过；`test_app.py` 47 项全部 OK；布局探针显示密码容器 `columnspan=2`，小眼睛按钮右侧打包，开始注册按钮保持左对齐且横向 padding 已收窄。
- 后续待办：无。

## 2026-07-02 - ONU注册 新增配置失败后复用旧 ONU 配置

- 类型：功能 / 安全提示 / 测试 / 文档
- 背景：用户确认复用旧 ONU 配置的正确命令为进入已注册 ONU 接口后执行 `registration-method sn 新SN`，并要求“开始注册”优先使用新增 ONU 业务配置；如果新增配置过程中业务命令报错，则改用复用旧 ONU 配置的方式让新 ONU 上线。
- 完成内容：ONU 注册底层流程在新增配置命令失败时不再直接退出，而是切回执行模式查询 `show gpon onu state`，自动选择已注册但未在线的 ONU（例如 OMCC 非 enable 或 Phase 非 working），重新进入全局模式后执行 `interface gpon-onu_旧ONU接口` 与 `registration-method sn 新SN`；注册确认提示同步说明该 fallback 会替换旧 ONU 的认证 SN；结果状态会区分“新增配置成功”和“新增配置失败后复用旧 ONU 配置”。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_network_ops.py` 21 项全部 OK；`test_app.py` 47 项全部 OK；完整单元测试 95 项全部 OK；新增测试已模拟 `service Internet gemport 1 vlan 200` 返回错误后自动执行 `show gpon onu state`、选择离线旧 ONU 并下发 `registration-method sn 新SN`。
- 后续待办：如后续需要由用户手动指定要复用的旧 ONU 口，可在 ONU注册列表旁增加“旧 ONU 口选择”或“自动/手动复用”模式。

## 2026-07-02 - ONU注册 接入开始注册功能

- 类型：功能 / UI / 测试 / 文档
- 背景：用户要求在已查询出的未注册 ONU 列表基础上实现“开始注册”功能，用于将勾选的 ONU 注册上线。
- 完成内容：新增 ONU 注册底层 Telnet 下发能力，按已确认的 ZTE OLT / SD-41 模板生成 `interface gpon-olt`、`interface gpon-onu`、业务 VLAN、`pon-onu-mng` 等配置命令；ONU注册窗口新增“开始注册”按钮，仅对勾选 ONU 生效，执行前二次确认，执行中禁用相关按钮，完成后在状态栏显示结果并写入运行日志；注册不会自动保存 OLT 配置，完成后提示重新查询确认上线。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 “开始注册”按钮和勾选列表 Tk 探针。
- 验证结果：编译检查通过；`test_app.py` 47 项全部 OK；`test_network_ops.py` 19 项全部 OK；完整单元测试 93 项全部 OK；ONU注册 UI 探针通过。`test_network_ops.py` 首次在普通沙箱遇到 Windows ACL 读权限错误，已按规则提权重跑并通过。
- 后续待办：如需要将 OLT 配置保存为启动配置，可在后续增加独立确认后的保存按钮或注册完成后的保存选项。

## 2026-07-02 - ONU注册 未注册 ONU 列表增加选择框

- 类型：UI / 功能 / 测试 / 文档
- 背景：用户要求在查询到的未注册 ONU 列表中，每个 ONU 前面都加选择框，方便后续决定要注册哪些 ONU，并增加全选和取消全选按钮。
- 完成内容：查询结果状态栏改为显示查询摘要；未注册 ONU 明细改为复选框列表，每行包含接口、SN 和状态；新增“全选”和“取消全选”按钮，查询到结果后启用，无结果或查询失败时禁用并清空旧选择。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 复选框渲染探针。
- 验证结果：编译检查通过；`test_app.py` 43 项全部 OK；`test_network_ops.py` 15 项全部 OK；完整单元测试 85 项全部 OK；ONU注册 复选框渲染探针通过。
- 后续待办：注册流程接入时读取用户勾选的 ONU 列表并执行注册。

## 2026-07-02 - ONU注册 查询所有 PON 口未注册 ONU

- 类型：功能 / UI / 测试 / 文档
- 背景：用户要求点击 ONU注册 的“开始查询”时，把 OLT 所有 PON 口下未注册的 ONU 都显示出来。
- 完成内容：新增 `show gpon onu uncfg` 只读查询能力，登录 OLT 后查询所有 PON 口未注册 ONU 并解析接口、SN 和状态；“开始查询”按钮改为异步查询流程，查询中禁用按钮，完成后在查询状态栏显示全部结果并写入运行日志。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`，并用真实 OLT 执行只读查询函数。
- 验证结果：编译检查通过；`test_app.py` 42 项全部 OK；`test_network_ops.py` 15 项全部 OK；完整单元测试 84 项全部 OK；真实 OLT 只读查询返回 3 个未注册 ONU。
- 后续待办：后续接入注册配置时，基于查询出的接口和 SN 做选择/填充。

## 2026-07-02 - ONU注册 连通性测试后登录 OLT 并进入全局模式

- 类型：功能 / UI / 测试 / 文档
- 背景：用户要求点击 ONU注册 的连通性测试后，如果 Telnet 连通性通过，则直接使用界面填写的用户名和密码登录 OLT，并在登录成功后下发 `configure terminal` 进入全局模式；登录状态需要显示在状态栏。
- 完成内容：新增 OLT Telnet 登录和进入全局模式的底层能力；连通性测试按钮现在会先确认该操作，再测试 Telnet 23 端口，连通后登录 OLT 并下发 `configure terminal`；OLT IP 右侧仍只显示 Telnet 连通性结果，登录和全局模式结果显示在查询入口下方状态栏，并写入运行日志。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_app.py` 41 项全部 OK；`test_network_ops.py` 13 项全部 OK；完整单元测试 81 项全部 OK。
- 后续待办：用真实 OLT 确认具体登录提示符和全局模式提示符，如设备提示符与当前通用解析不同，再按实际提示符细化解析。

## 2026-07-02 - 调整 ONU注册 状态显示和窗口默认尺寸

- 类型：UI / 优化 / 文档 / 测试
- 背景：用户要求 ONU注册 模块中 OLT IP 右侧的连通性状态只显示 Telnet 状态，其它状态信息显示在“查询未注册的ONU”下方；同时默认宽减少 1cm、默认高减少 3cm。
- 完成内容：将 ONU注册 状态分为 Telnet 连通性状态和查询状态两块；Telnet 结果仍显示在 OLT IP 右侧，查询未注册 ONU 的占位/后续状态显示在查询入口下方；窗口默认尺寸从 `934x694` 调整为 `896x580`，最小尺寸从 `874x644` 调整为 `836x530`。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 窗口尺寸和状态分区探针。
- 验证结果：编译检查通过；`test_app.py` 41 项全部 OK；完整单元测试 79 项全部 OK；ONU注册 窗口尺寸和状态分区探针通过。
- 后续待办：无。

## 2026-07-02 - 加大 ONU注册 窗口尺寸

- 类型：UI / 优化 / 文档 / 测试
- 背景：用户要求将 ONU注册 模块界面的长宽都加大 3cm。
- 完成内容：将 ONU注册 窗口默认尺寸从 `820x580` 调整为 `934x694`，最小尺寸从 `760x530` 调整为 `874x644`，按 96 DPI 折算长宽各增加约 3cm；同步更新 README 和项目状态说明。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`，并执行 ONU注册 窗口尺寸探针。
- 验证结果：编译检查通过；`test_app.py` 40 项全部 OK；ONU注册 窗口尺寸探针通过。
- 后续待办：无。

## 2026-07-02 - 修复启动配置解析失败

- 类型：BUG 修复 / 配置 / 测试
- 背景：项目源码启动时报 `configparser.ParsingError`，原因是 `config/network_card_ip.ini` 中 `channel_14` 的 `adapter_alias` 行被截断为无效的 `adapter_al`。
- 完成内容：补全 `channel_14` 的 `adapter_alias`、`network_card_ip`、`device_manage_ip`、`subnet_mask` 配置项，恢复 INI 文件合法结构。
- 修改文件：`Cheating_machine_execution_tool/config/network_card_ip.ini`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\run_line_check_assistant.py .\line_check_assistant\app.py .\line_check_assistant\config_store.py`，并用 `ChannelConfigStore` 加载配置。
- 验证结果：配置解析恢复正常，源码入口不再因 `network_card_ip.ini` 解析错误而退出。
- 后续待办：如需要使用打包版启动，需要重新生成 `dist\LineCheckAssistant.exe`。

## 2026-07-02 - 新增 ONU注册 功能入口

- 类型：功能 / UI / 文档 / 测试
- 背景：用户要求在主界面“常用工具”中增加“ONU注册”功能入口，并保持软件界面风格一致。
- 完成内容：在常用工具栏新增 `ONU注册` 按钮；新增同风格独立占位窗口，展示 OLT 连接、ONU 标识、注册方式、注册状态等后续流程入口；窗口当前不登录设备、不修改配置、不执行注册操作。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py` 和 `python -m unittest discover -s tests -p test_app.py -v`。
- 验证结果：编译检查通过；`test_app.py` 28 项全部 OK。
- 后续待办：后续明确 ONU 注册协议、OLT 登录方式、SN/LOID 字段和注册校验规则后，再接入实际业务流程。

## 2026-07-02 - 完善 ONU注册 窗口表单和 Telnet 连通性测试

- 类型：功能 / UI / 测试 / 文档
- 背景：用户要求将 ONU注册 窗口中的占位项改为可输入表单：OLT IP 默认 `172.18.18.151`，支持 Telnet 连通性测试；ONU标识改为用户名和密码；注册方式改为查询未注册的ONU并提供开始查询按钮。
- 完成内容：新增 OLT IP、用户名、密码输入框；新增连通性测试按钮，调用底层 Telnet 23 端口连接检查；新增查询未注册 ONU 的开始查询入口占位；保持窗口配色、间距和按钮样式与现有界面一致。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_app.py` 31 项全部 OK；`test_network_ops.py` 11 项全部 OK；完整单元测试 63 项全部 OK。
- 后续待办：明确 OLT 登录提示符、查询未注册 ONU 的 Telnet 命令和解析规则后，再接入实际查询流程。

## 2026-07-02 - 保存 ONU注册 输入框上次关闭状态

- 类型：功能 / 配置 / 测试 / 文档
- 背景：用户要求 ONU注册 中所有输入框填写的信息都能保存上一次关闭时的信息，并明确默认 OLT IP 也要恢复上次关闭状态。
- 完成内容：新增 ONU 注册配置存储模块；OLT IP、用户名、密码会自动保存到本机 `config/onu_registration.ini`，关闭 ONU 窗口或直接关闭主程序时会立即保存；首次没有历史配置时才使用默认 OLT IP `172.18.18.151`；新增 `.gitignore` 规则避免本机凭据配置进入 Git。
- 修改文件：`.gitignore`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/onu_registration_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\onu_registration_store.py`、`python -m unittest discover -s tests -v`，并执行窗口关闭持久化探针。
- 验证结果：编译检查通过；完整单元测试 68 项全部 OK；窗口关闭持久化探针通过。
- 后续待办：后续接入真实 ONU 查询流程时，继续复用该本机配置作为默认连接信息。

## 2026-07-02 - 保存样机升级窗口上次关闭状态

- 类型：功能 / 配置 / 测试 / 文档
- 背景：用户补充说明其它功能模块也要保存上一次关闭时的状态，例如样机升级模块。
- 完成内容：新增样机升级设置存储模块；保存升级方式、固件传输方式、恢复出厂选项、超级用户名、密码和固件路径；关闭样机升级窗口或直接关闭主程序时立即保存；新增 `.gitignore` 规则避免本机样机升级输入状态进入 Git。
- 修改文件：`.gitignore`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\onu_registration_store.py .\line_check_assistant\sample_upgrade_settings_store.py`、`python -m unittest discover -s tests -v`，并执行样机升级关闭后重新打开的临时配置探针。
- 验证结果：编译检查通过；完整单元测试 72 项全部 OK；样机升级关闭后重新打开探针通过。
- 后续待办：后续如“写样机参数”“串口日志”等模块增加真实输入框，也按同一模式保存到本机配置文件并加入 Git 忽略。

## 2026-07-02 - 调整 ONU注册 连通性结果显示位置

- 类型：UI / 文档 / 测试
- 背景：用户要求将 OLT IP 的连通性测试结果显示到 OLT IP 输入框右侧、连通性测试按钮左侧的位置。
- 完成内容：移除 ONU注册 窗口底部状态行，将 Telnet 连通性测试结果改为显示在 OLT IP 输入框和连通性测试按钮之间的内联结果框。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 窗口初始化探针。
- 验证结果：编译检查通过；`test_app.py` 36 项全部 OK；完整单元测试 72 项全部 OK；ONU注册 窗口初始化探针通过。
- 后续待办：无。

## 2026-07-02 - ONU注册 密码框增加小眼睛切换

- 类型：UI / 测试 / 文档
- 背景：用户要求 ONU注册 模块的密码输入框增加小眼睛，可点击切换明文和密文显示。
- 完成内容：ONU注册 密码输入框改为带小眼睛按钮的组合控件；点击小眼睛可在 `*` 密文和明文显示之间切换，行为与样机升级密码框保持一致。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 密码小眼睛切换探针。
- 验证结果：编译检查通过；`test_app.py` 37 项全部 OK；完整单元测试 73 项全部 OK；ONU注册 密码小眼睛切换探针通过。
- 后续待办：无。

## 2026-07-02 - 修复样机升级配置后无法关闭窗口

- 类型：BUG 修复 / 配置 / 测试
- 背景：用户反馈样机升级模块填写升级配置后，点击关闭无法关闭，主界面也无法关闭，表现像卡死。
- 完成内容：定位为保存本机配置时 `ConfigParser` 默认插值会把密码或路径中的 `%` 当成特殊语法并抛异常，导致关闭回调未执行 `destroy()`；将 ONU注册 和 样机升级 的本机配置存储改为 `RawConfigParser`，支持保存 `%` 等普通字符；关闭 ONU注册、样机升级窗口和主窗口时，即使保存异常也会继续关闭窗口。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/onu_registration_store.py`、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_store.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\sample_upgrade_settings_store.py .\line_check_assistant\onu_registration_store.py`、`python -m unittest discover -s tests -v`，并执行包含 `%` 密码/路径的样机升级关闭回归探针。
- 验证结果：编译检查通过；完整单元测试 76 项全部 OK；包含 `%` 密码/路径的关闭回归探针通过。
- 后续待办：无。

## 2026-07-02 - ONU注册 Telnet 连通性结果增加状态颜色

- 类型：UI / 测试 / 文档
- 背景：用户要求 Telnet 连通性测试通过或失败时，用不同颜色区分结果。
- 完成内容：ONU注册 的内联连通性结果框增加颜色状态；测试中显示警告色，测试通过显示绿色，测试失败或未输入 OLT IP 显示红色。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 状态颜色探针。
- 验证结果：编译检查通过；`test_app.py` 40 项全部 OK；完整单元测试 78 项全部 OK；ONU注册 状态颜色探针通过。
- 后续待办：无。

## 2026-06-27 - 多台串行全包 Tftp 升级验收通过

- 类型：测试 / 项目状态
- 背景：用户反馈“全包 + Tftp 命令传输 + 多台串行升级”验收通过，今日开发到此结束。
- 完成内容：记录真实设备验收结论，并同步项目状态，将多台串行升级标记为已验收通过。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`
- 验证方法：用户在真实设备上验收“全包 + Tftp 命令传输 + 多台串行升级”流程。
- 验证结果：验收通过。
- 后续待办：后续再评估多台并发 TFTP 传输/并发升级，以及不同项目/型号和异常场景补强。

## 2026-06-27 - 升级收尾自动关闭 SecureCRT 和 Tftpd64

- 类型：优化 / 测试 / 文档
- 背景：用户要求在打印“已恢复 network_card_ip.ini 中用户选择的完整通道配置。”时，同步关闭升级过程中打开的串口工具，例如 SecureCRT 和 Tftpd64。
- 完成内容：新增升级收尾清理逻辑；多台串行升级恢复完整通道配置后，自动关闭 SecureCRT 进程和项目目录下的 `tftpd64.exe`；关闭过程输出到升级日志。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/upgrade_cleanup.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_tftpd_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\upgrade_cleanup.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_tftpd_automation.py -v` 和完整 `python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；完整 `python -m unittest discover -s tests -v` 57 项全部 OK。
- 后续待办：真实升级完成后确认 SecureCRT/Tftpd64 能被自动关闭，且不会影响需要保留的人工 SecureCRT 会话。

## 2026-06-27 - 上电等待时间改为每通道 10 秒

- 类型：修改 / 测试 / 文档
- 背景：用户要求把上电等待从 5 秒改为 10 秒。
- 完成内容：升级流程中每台样机调用旧开关机工具后的等待时间改为 10 秒；主界面“自动上电”按启用通道数每通道 10 秒计算等待时间；同步 README 和项目状态说明。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\sample_upgrade.py` 和 `python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；完整 `python -m unittest discover -s tests -v` 55 项全部 OK。
- 后续待办：使用真实设备确认 10 秒上电等待是否足够稳定。

## 2026-06-27 - 按当前通道临时改写 network_card_ip.ini 实现真实串行上电

- 类型：BUG 修复 / 功能 / 测试 / 文档
- 背景：用户指出旧开关机工具会按 `network_card_ip.ini` 从上往下逐台上电；如果配置里同时保留多台样机，旧工具 `Start ALL` 仍会操作多个通道，导致新软件内部串行不等于真实串行上电。
- 完成内容：多台串行升级开始时保存用户选择的完整通道快照；每台升级前写入 `network_card_ip.ini` 只保留当前通道；当前通道升级完成后再写入下一台；串行结束或失败后恢复完整通道配置。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py` 和 `python -m unittest discover -s tests -p test_app.py -v`。
- 验证结果：编译检查通过；完整 `python -m unittest discover -s tests -v` 55 项全部 OK。
- 后续待办：使用真实多台样机验证旧工具每次只给当前 `network_card_ip.ini` 中保留的通道上电。

## 2026-06-27 - 修复串行升级提示 VLAN 与实际上电顺序不一致

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户验收发现勾选 `vlan137`、`vlan138`、`vlan139` 后，界面提示正在升级 `vlan137`，但旧工具实际先启动的是 `VLAN139` 上电。
- 完成内容：多台串行升级不再按 VLAN 数字排序，而是按主界面通道顺序生成升级队列，让确认提示、状态栏和旧工具实际上电顺序保持一致。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py` 和 `python -m unittest discover -s tests -p test_app.py -v`。
- 验证结果：编译检查通过；`test_app.py` 26 项全部 OK；完整 `python -m unittest discover -s tests -v` 55 项全部 OK。
- 后续待办：继续用真实多台样机验证主界面通道顺序与旧工具上电顺序是否完全一致；如仍有偏差，需要进一步接入旧工具单通道选择/上电能力。

## 2026-06-27 - 实现多台样机串行 Tftp 拷贝升级

- 类型：功能 / 测试 / 文档
- 背景：用户要求开始实现多台串行升级，在单台样机已验证通过的基础上扩展到多个已勾选通道。
- 完成内容：全包升级 + Tftp 拷贝命令支持选择多个目标 VLAN，启动前确认，按主界面通道顺序逐台复用单台升级流程；某台失败时停止后续样机并提示失败信息。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\sample_upgrade.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_sample_upgrade.py -v`。
- 验证结果：编译检查通过；`test_app.py` 26 项通过；`test_sample_upgrade.py` 5 项通过；完整 `python -m unittest discover -s tests -v` 55 项全部 OK。
- 后续待办：使用真实多台样机验证串行升级流程；后续再评估并发 TFTP 传输/并发升级。

## 2026-06-27 - 单台样机 Tftp 拷贝升级和复位流程验证通过

- 类型：测试 / 项目状态
- 背景：用户反馈单台样机通过 Tftp 拷贝命令和复位功能已经验证通过。
- 完成内容：记录真实设备验证结论，并同步项目状态，明确单台样机“全包升级 + Tftp 拷贝命令 + reset/重新上电后登录确认”流程已通过验证。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`
- 验证方法：用户在真实单台样机上执行 Tftp 拷贝命令和复位流程。
- 验证结果：单台样机流程验证通过。
- 后续待办：继续完善多台样机、不同项目/型号和异常失败场景的流程验证。

## 2026-06-27 - 调整 boot reset 后登录等待时间

- 类型：修改 / 测试 / 文档
- 背景：用户要求检测到 SecureCRT 已发送 reset 后，以及未检测到 reset 重新上电后，主流程都固定等待 120 秒再登录样机系统。
- 完成内容：将 boot reset 分支和重新上电分支的登录前等待时间从 180 秒改为 120 秒，并更新界面日志文案、README 描述和单元测试期望。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\sample_upgrade.py` 和 `python -m unittest discover -s tests -p test_sample_upgrade.py -v`。
- 验证结果：`python -m py_compile .\line_check_assistant\sample_upgrade.py` 通过；`python -m unittest discover -s tests -p test_sample_upgrade.py -v` 通过，5 项测试 OK。
- 后续待办：无。

## 2026-06-27 - 新增开发记录机制

- 类型：文档 / 项目管理
- 背景：用户要求后续每次完成的功能、优化、修改、BUG 修复等都记录下来，方便继续开发和整体管理。
- 完成内容：新增统一开发记录文件，约定每次变更后的记录格式和同步规则。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`AGENTS.md`
- 验证方法：检查文档结构和链接入口。
- 验证结果：已建立可持续追加的开发记录入口。
- 后续待办：后续每次任务完成后，按模板在本文件顶部追加记录。
## 2026-07-11 - 修复 Boot 首轮提示符导致账号密码错位

- 类型：BUG 修复 / 串口时序 / 测试 / 文档
- 背景：真实升级日志显示，程控电源上电后的首轮 `UserName:` / `Password:` 过渡输出可能被当作有效登录提示，导致账号和密码在第一阶段提前写入，后续重试才成功。
- 完成内容：程控电源流程改为在电源动作返回并等待 1 秒后才放行 boot 登录线程；用户名提示符命中后增加仅接收串口的 1 秒稳定窗口，若用户名提交前已经收到 `Password:` / `Passvord:` 则丢弃整轮，不发送任何凭据；用户名回车后仍使用新游标等待本轮密码提示符。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：`python -m unittest discover -s tests -p test_serial_upgrade_service.py -v`、`python -m unittest discover -s tests -v`；真实设备需复测 `Tftp指令` 的首次上电进入 boot。
- 验证结果：串口升级专项 13 项通过；完整 `python -m unittest discover -s tests -v` 共 125 项通过。新增回归覆盖“首轮 UserName/Password 同时出现时不发送账号密码”；后续真实设备首次上电进入 boot 验证已通过。

## 2026-07-11 - Boot 首轮登录错位真实样机验证通过

- 类型：真实设备验收 / 项目状态
- 背景：修复上电初期 `UserName:` / `Password:` 过渡输出造成账号、密码错位后，需要确认实际样机首轮进入 boot 的登录行为。
- 完成内容：用户已确认该问题解决，首次 Boot 登录不再出现账号或密码错位。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`
- 验证方法：用户在真实样机使用 `Tftp指令` 的首次上电进入 boot 流程验证。
- 验证结果：通过。
## 2026-07-11 - 全包升级断电重启不再关闭全部程控电源通道

- 类型：流程优化 / 程控电源 / 测试 / 文档
- 背景：全包升级当前通道断电再上电时，日志仍先发送 `55 00 AD 00 00 AD` 全部断电帧；用户要求去除该操作。
- 完成内容：`power_on_selected_channels()` 保留当前升级通道的关闭帧、断电间隔和开启帧，移除“关闭全部程控电源通道”帧；主界面自动上/下电和 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 的业务逻辑未改动。
- 修改文件：`Cheating_machine_execution_tool/src/core/power_supply.py`、`Cheating_machine_execution_tool/src/services/power_on_service.py`、`Cheating_machine_execution_tool/tests/test_power_supply.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行程控电源专项测试和完整单元测试；真实样机观察全包升级首次/重新上电日志。
- 验证结果：程控电源专项 8 项通过；完整 `python -m unittest discover -s tests -v` 共 125 项通过。真实样机需确认日志不再出现 `关闭全部程控电源通道：55 00 AD 00 00 AD`。

## 2026-07-11 - 全包升级 Tftp指令 多台样机串行验收通过

- 类型：真实设备验收 / 项目状态
- 背景：主程序的 `全包升级 + Tftp指令` 采用程控电源按当前通道逐台执行，需要确认多台样机的串行升级完整流程。
- 完成内容：用户确认多台样机串行升级验收通过；`Tftp指令` 流程标记为真实样机已验收。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`
- 验证方法：用户在真实设备执行“样机升级 → 全包升级 → Tftp指令”的多台样机串行升级。
- 验证结果：通过。
## 2026-07-11 - 全包升级 Tftp指令 支持两台受控并行

- 类型：功能 / 并行编排 / 程控电源 / 测试 / 文档
- 背景：用户要求在已验收的多台样机串行 `Tftp指令` 流程基础上，提供最多两台样机并行升级；主程序已不再使用旧工具 GUI，因此升级过程不应逐台改写 `network_card_ip.ini`。
- 完成内容：样机升级窗口新增持久化的“串行 / 并行（最多 2 台）”选择，默认串行且仅对 `Tftp指令` 生效；并行模式完成即补位，单台失败不取消其它样机。新增共享电源协调器，仅串行化同一 COM 口的关闭/开启帧，将每台启动等待移到锁外；每台 TFTP 服务严格绑定各自 VLAN IP，不允许回退到 `0.0.0.0`。串行和并行全包升级均不再临时改写 `network_card_ip.ini`；`Tftp Put`、自动上/下电和 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 保持原逻辑。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`line_check_assistant/sample_upgrade_settings_store.py`、`src/core/tftp_transport.py`、`src/services/serial_upgrade_service.py`、`src/services/__init__.py`、相关单元测试、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行升级设置、TFTP、串行升级服务、主界面专项测试及完整单元测试；真实设备以两台独立 VLAN、相同 Boot IP 的样机验证。
- 验证结果：编译检查通过；完整 `python -m unittest discover -s tests -v` 共 130 项通过。新增严格双 IP 同端口 TFTP 监听、两台并行上限/失败继续、电源 COM 互斥与不改写升级配置的回归覆盖；真实两台并行升级待验收。
## 2026-07-11 - 并行 TFTP 严格绑定前等待 VLAN IP 就绪

- 类型：BUG 修复 / 网络时序 / 测试 / 文档
- 背景：两台并行 `Tftp指令` 日志显示，`netsh` 已成功设置 VLAN139/VLAN138 的静态 IP，但约 1 秒后严格 TFTP 预检仍报告 IP 不可绑定；这是 Windows 刚配置网卡地址时地址注册尚未完成造成的时序问题。
- 完成内容：设置静态 IP 后改为每 0.5 秒验证一次可绑定性，最长等待 15 秒；就绪后再启动严格绑定的 TFTP 服务。超时仅报告该 VLAN 的网卡 IP/重复 IP/驱动问题，仍不回退到 `0.0.0.0`，避免多 VLAN 同 Boot IP 的回包错路由。
- 修改文件：`Cheating_machine_execution_tool/src/core/tftp_transport.py`、`src/core/__init__.py`、`src/services/serial_upgrade_service.py`、相关单元测试、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 TFTP、串行升级服务专项测试和完整单元测试；真实设备重新执行两台并行 `Tftp指令`。
- 验证结果：专项 25 项通过；完整 `python -m unittest discover -s tests -v` 共 133 项通过。真实设备待复测。
## 2026-07-11 - 并行 TFTP 数据 socket 固定绑定 VLAN IP

- 类型：BUG 修复 / 多网卡路由 / 测试 / 文档
- 背景：两台样机的 UDP 69 服务都已成功监听，但只有一台开始传输。定位到 TFTPy 在收到 RRQ 后会创建未绑定本地 IP 的数据传输 socket；当多张 VLAN 网卡面对相同 Boot IP `192.168.1.1` 时，Windows 会把数据回包路由到其中一张网卡。
- 完成内容：在主程序 TFTP 包装层替换 TFTPy 的会话上下文工厂。每个监听线程创建传输数据 socket 时，强制绑定该服务的 VLAN IP 和随机本地端口；不修改虚拟环境中的第三方源码。这样监听帧和后续固件数据帧均从同一 VLAN IP 返回样机。
- 修改文件：`Cheating_machine_execution_tool/src/core/tftp_transport.py`、`tests/test_tftp_transport.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：模拟 RRQ，断言 TFTPy 新建的数据 socket 绑定监听 VLAN IP；运行完整单元测试；真实设备执行两台并行 `Tftp指令`。
- 验证结果：TFTP 专项 9 项通过；完整 `python -m unittest discover -s tests -v` 共 134 项通过。真实两台并行传输待复测。
## 2026-07-12 - 全包升级 Tftp Put 支持两台受控并行

- 类型：功能 / 并行编排 / 程控电源 / 测试 / 文档
- 背景：`Tftp Put` 已完成多台串行真实样机验收；需要在不触碰 `Tftp指令` 调度和传输逻辑的前提下，提供两台受控并行升级能力。
- 完成内容：新增仅接受 `Tftp Put` 请求的并行服务入口，固定最多两台、完成即补位、单台失败不中止其它样机并按输入顺序汇总。每个 worker 仍使用 TFTPy Client 将固件推送至隔离 VLAN 内的 `192.168.1.1`，共享程控电源 COM 的开关帧由现有协调器串行化。升级窗口现对 `Tftp Put` 显示“串行 / 并行（最多 2 台）”，新增独立 UI worker、状态汇总、VLAN 日志和自动串口终端收尾；`Tftp指令` 的 worker、严格服务端绑定和传输流程未改动。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/src/services/__init__.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行编译检查、串行升级服务专项测试、主界面专项测试和完整单元测试；真实两台独立 VLAN / COM 样机执行并行 `Tftp Put`。
- 验证结果：`python -m py_compile line_check_assistant/app.py src/services/serial_upgrade_service.py src/services/__init__.py` 通过；串行升级服务专项 24 项、主界面专项 60 项通过；完整 `python -m unittest discover -s tests -v` 共 154 项通过。
- 后续待办：真实两台独立 VLAN / COM 样机验收并行 `Tftp Put`，确认两路上传可同时推进且程控电源开关帧不交叠。

## 2026-07-12 - 全包升级 Tftp指令 / Tftp Put 两台并行真实样机验收通过

- 类型：真实样机验收 / 状态更新
- 背景：`Tftp指令` 两台并行和 `Tftp Put` 两台并行此前都是“代码完成，待真实两台验收”，需要把状态收口到已验收。
- 完成内容：用户已用两台不同 VLAN/COM 的真实样机验收 `Tftp指令` 并行和 `Tftp Put` 并行，结果通过。同步将 `PROJECT_STATUS.md` 中两项标记为“已真实两台验收”，移除“待两台真实验收”相关待办，删除“`Tftp Put` 并行仍是代码和单测验证”的限制项。
- 修改文件：`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：真实两台不同 VLAN/COM 样机分别执行 `Tftp指令` 并行和 `Tftp Put` 并行升级。
- 验证结果：通过。
- 后续待办：继续按现有约束观察新型号或异常现场日志，再扩展超时、掉线、登录失败与型号差异处理；不要预先改变已验收时序。

## 2026-07-12 - 串口乱码盲发密码补救登录真实样机验收通过

- 类型：真实样机验收 / 状态更新
- 背景：先前在 `_login_boot` 与 `login_tftp_put_boot_after_username` 增加的 salvage 分支（回显含 UTF-8 替换符 `�` → 盲发密码 → 等 shell 提示符）已通过单元测试（160 项），需要现场复现 UART 损坏场景验证命中率。
- 完成内容：用户已在真实样机上验证该 salvage 方案，结果通过。同步在 `PROJECT_STATUS.md` 的"已完成"中追加该能力的真实样机验收条目。
- 修改文件：`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：真实样机复现 UART 输出损坏场景,触发用户名回显和 `Password:` 提示符均为乱码,确认 salvage 命中并进入 shell。
- 验证结果：通过。
- 后续待办：继续按现有约束观察新型号或异常现场日志,再扩展其他场景;不要预先改变已验收时序。

## 2026-07-12 - 串口乱码时盲发密码补救登录

- 类型：BUG 修复 / 异常现场补强 / 测试 / 文档
- 背景：现场日志显示一台样机的 UART 输出损坏：`UserName:` 被切成 `U` + `serName:`、`RX C�H�`、`RX C!���ݽɑ�` 等乱码；`Password:` 提示符也是乱码。`_login_boot` 与 `login_tftp_put_boot_after_username` 都在等待完整 `Password:` 提示符，超时后只能重试或放弃，但 UART 输入正常时样机实际已接受账号。
- 完成内容：新增 `PySerialSession.peek_since(cursor)` 读取从游标开始的解码文本（不消费历史）；新增模块级常量 `GARBLED_REPLACEMENT_MARKER` 与辅助函数 `_looks_like_garbled_response()` 检测 UTF-8 替换符 `�`；新增 `SerialUpgradeController._try_login_after_garbled_username()`，在 `_login_boot`（Tftp指令）和 `login_tftp_put_boot_after_username`（Tftp Put）的 `Password:` 超时分支中：当回显含 `�` 时盲发一次密码，等待 shell 提示符（`#` / `>` / `ecnt>` / `u-boot>`）作为登录成功；salvage 失败不影响原重试或失败路径。完整 `UserName:` / `Password:` 提示符到达时仍走原路径，不改变已验收时序。
- 修改文件：`Cheating_machine_execution_tool/src/core/serial_transport.py`、`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_transport.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile src/core/serial_transport.py src/services/serial_upgrade_service.py`；运行 `tests/test_serial_upgrade_service.py`、`tests/test_serial_transport.py` 及完整单元测试。
- 验证结果：编译通过；新增 6 项用例覆盖 `peek_since` 基础行为、Tftp指令 salvage 成功 / 失败重试 / 干净超时无 salvage、Tftp Put salvage 成功 / 干净超时无 salvage；完整 `python -m unittest discover -s tests -v` 共 160 项通过。后续现场用已知会让响应乱码的串口线复测,确认命中并进入 shell,真实样机验收通过。
- 后续待办：继续按现有约束观察新型号或异常现场日志,再扩展其他场景;不要预先改变已验收时序。

## 2026-07-12 - 精简项目交接状态文档

- 类型：文档 / 交接
- 完成内容：重写 `PROJECT_STATUS.md`，仅保留项目目标与实现进度、关键文件、已完成与待验收项、技术限制，以及运行/测试/继续开发命令；同步当前全量测试基线为 154 项。
- 修改文件：`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证结果：已核对源码入口、升级服务、串口/TFTP 核心文件与当前测试基线；未改动业务代码。
