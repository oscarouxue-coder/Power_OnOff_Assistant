# Acceptance Baseline

更新：2026-07-20（新增 §2.12 「全流程执行」管道编排器；状态初始「已实现未验收」）

> 与 `PROJECT_STATUS.md` 的关系：本文按"实现 → 单测 → 真实样机验收"三态罗列验收证据与不变量，作为独立验收基线。`PROJECT_STATUS.md` 保留面向项目的进度叙述；两者冲突时以本文为准。
>
> **状态标签**：
> - **已确认验收**：单元测试通过 + `DEVELOPMENT_LOG.md` 中有"真实样机验收通过"明确字样（且日志可索引到具体日期）。
> - **已实现未验收**：代码与单测通过，但尚无真实样机验收记录。
> - **待确认**：代码或测试入口存在，验收未完成或依据缺失。

## 0. 最小可信回归基线

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m py_compile line_check_assistant\app.py src\ui\serial_terminal.py src\services\serial_upgrade_service.py src\services\sample_parameter_service.py src\core\tftp_transport.py src\core\telnet_transport.py src\core\ubus_http_client.py src\core\ubus_enable_telnet.py src\core\bind_socket.py src\core\parameter_session.py line_check_assistant\network_ops.py
python -m unittest discover -s tests -v
```

预期 `Ran 283 tests ... OK`（2026-07-19 实跑；原 270 → 273（清理失败步骤名标识 3 项）→ 283（本轮新增 10 项：同 OUI 1 + 流水线选项 5 + 持久化 2 + 写样机参数默认并行 1 回归 1 + SSID 末 4 位 MAC 强关联 1））。

## 1. 全局不可破坏规则

### 1.1 入口、运行与打包

- 入口：`Cheating_machine_execution_tool/run_line_check_assistant.py` → `line_check_assistant.app.main()`
- 依赖：`pyserial==3.5` / `tftpy==0.8.7` / `requests>=2.31,<3` / `openpyxl>=3.1,<4` / `xlrd>=2.0,<3`（详见 `requirements.txt`、`THIRD_PARTY_NOTICES.md`）
- 打包：`powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1` → `dist\LineCheckAssistant.exe`
- **构建后不在当前 PC 运行 `dist\LineCheckAssistant.exe`**，仅确认打包成功并报告路径

### 1.2 测试与目录基线

- 全量：`python -m unittest discover -s tests -v` → **283 项全过**（2026-07-19 实跑，对应 `tests/` 下 19 个 unittest 文件）
- 不动 `build/`、`dist/`、`logs/`、`.venv/`

### 1.3 协议不变性自检（grep 必须命中）

- `bbfdm.operate`（页面升级 UBUS 调用形式）
- `0.0.0.0` **不应**出现在并行 TFTP 监听 / 数据 socket 路径
- `tclinux_allinone`（`Tftp指令` 文件名映射）
- `192.168.1.1`（`Tftp Put` 远端固定）
- `vlan{N} -> COM{N-100}` 映射（`vlan_to_serial_port`）
- `MAX_PARALLEL_UPGRADES = 8` 与 `clamp_parallel_count`
- `source_address=(bind_ip, 0)` 应出现在 `TelnetSession`、`UbusHttpClient` 构造路径
- `Device.Firewall.<X_SDMC_>Security.AccessCtrl` 应出现在 `ubus_enable_telnet`

### 1.4 流程隔离与禁止合并

- **`Tftp指令`（样机从本机 TFTPy Server 拉固件）与 `Tftp Put`（本机 TFTPy Client 推固件至 `192.168.1.1:69`）绝不可合并**为同一传输流程
- 不依赖 SecureCRT、Tftpd64、旧 `Auto_Power_On_Off_Tool.exe` 或 UI Automation
- TFTP socket 严禁回退 `0.0.0.0`；客户端必须绑当前通道 VLAN IP
- 升级 / 重启 / 恢复出厂 / 批量写参必须保留确认弹窗 + 主执行日志；新增功能必须输出"关键阶段 / 实际命令 / 成功 / 跳过 / 失败"
- 仅 Windows 10/11；写网卡静态 IP 与执行 EXE 均需管理员权限

### 1.5 主程序入口自检

可分别打开且行为正常：页面升级、全包升级（Tftp指令 / Tftp Put）、写样机参数（默认 telnet 路径）、生成批量样机参数表、ONU 注册、串口日志记录。

---

## 2. 功能验收清单

### 2.1 通道 / 网卡 / Ping

- **状态**：已实现未验收
- **核心行为**：按 VLAN 标识已勾选通道；支持网卡刷新 / 子网配置 / Ping 样机管理 IP；现场配置写 `Auto_power_on_off_tool/config/network_card_ip.ini`
- **边界与异常**：写网卡静态 IP 需管理员权限；源 IP 不可绑时**强提示人工检查 ini**，不回退 `0.0.0.0`
- **禁止破坏**：配置写入位置唯一（不可再新建 `Cheating_machine_execution_tool/config/`）
- **待确认**：现场通道变更 → `network_card_ip.ini` 端到端真实样机验证
- **对应测试**：`tests/test_app.py`、`tests/test_paths.py`

### 2.2 程控电源（COM101-COM116 直连）

- **状态**：已确认验收（直连程控电源 + 自动上电新流程）/ 已实现未验收（自动下电 / 同批次 COM 长连接复用 / 并行 1-8 台）
- **核心验收行为**：
  - 主程序直连程控电源；移除旧 `Auto_Power_On_Off_Tool.exe` / UI Automation
  - 自动上电：相邻开启帧间隔 1 秒、取消末尾 10 秒启动等待 — 现场已验收
  - 自动下电：仅发关闭帧、相邻 1 秒，**不发全断电帧**
  - 同批次程控电源 COM 由 `UpgradePowerCycleCoordinator` 持有长连接（`open` 仅一次，`close()` 幂等）
  - 并行 1-8 台、默认 2 台（`MAX_PARALLEL_UPGRADES=8`、`clamp_parallel_count`）
- **禁止破坏**：
  - 串口参数 **19200 8N1**
  - **不发送全断电帧**
  - **不修改** `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 源码
  - 串口路径 `vlan{N} -> COM{N-100}` 硬编码（未配置化）
- **对应测试**：`tests/test_power_supply.py`、`tests/test_app.py`、`tests/test_serial_upgrade_service.py`

### 2.3 串口日志 / 多 VLAN 终端

- **状态**：已确认验收（命令输入框回车发送，2026-07-15）/ 已实现未验收（其余）
- **核心验收行为**：
  - 命令输入框 Enter 发送 — 非空等价「发送」+ 自动清空；空字符串等价「回车」；自动升级占用与危险命令（`reboot` / `reset` / `firstboot` / `tftp` / `upgrade`）二次确认仍生效
  - 多 Tab、`vlan{N} -> COM{N-100}` 固定映射、按 VLAN 合并后只渲染当前 Tab；33ms 节流渲染
  - 屏内缓冲上限 48 KiB（工作缓冲）；全局缓冲超 64 KiB 触发合并展示
  - 默认日志目录不可写 / 终端状态文件不可写时显式提示
- **禁止破坏**：自动升级占用的 Tab 手动发送（含 Enter）被锁定；危险命令二次确认；原始终端文件由后台串口线程完整写入磁盘
- **待确认**：3 路以上高频 WiFi 日志压测；现场观察高频滚动下按钮是否持续可点
- **对应测试**：`tests/test_serial_terminal.py`

### 2.4 全包升级 - `Tftp指令`（设备拉取固件）

- **状态**：已确认验收
- **核心验收行为**：
  - 多台样机串行真实样机（2026-07-11）
  - 两台受控并行真实样机（2026-07-12）
  - `ARP Retry count exceeded` 自动重试 3 次（2026-07-12 + 2026-07-13 合并记录）
  - 串口乱码盲发密码补救登录（`peek_since` salvage 路径） — 见 §3.2 待核对
- **边界与异常**：高并发时 `manual_writable` 仅在控制器释放后切回
- **禁止破坏**：
  - 监听 socket 与 RRQ 数据 socket 严格绑当前 VLAN IP，禁止回退 `0.0.0.0`
  - 固件名固定 `tclinux_allinone`
  - 不开外部 CRT / Tftpd 进程
- **待确认**：4 台、8 台独立 VLAN / COM 真实样机端到端（含程控电源长连接复用、日志仅有一次"已打开 / 已关闭程控电源串口"）
- **对应测试**：`tests/test_serial_upgrade_service.py`、`tests/test_tftp_transport.py`、`tests/test_serial_transport.py`

### 2.5 全包升级 - `Tftp Put`（主机推固件）

- **状态**：已确认验收
- **核心验收行为**：
  - 多台样机串行真实样机（2026-07-12）
  - 两台受控并行真实样机（2026-07-12）
  - 开始前对程控电源下电 + 上电（与 `Tftp指令` 复用 `_power_cycle_current_channel`）；检测 `UserName:` 后按 boot 凭据登录；`Password:` 同批覆盖由 `cursor` 前移修复；上传失败 / 超时不影响后续 batch
- **禁止破坏**：
  - 客户端必须绑当前通道 VLAN IP
  - 远端固定 `192.168.1.1:69`
  - **不与 `Tftp指令` 合并**
- **待确认**：4 台、8 台并行真实样机；现场回显差异（如 `ECNT>` 大小写）下的最终登录时序
- **对应测试**：`tests/test_serial_upgrade_service.py`（含 `Tftp Put` salvage / 同批 `ECNT>` / `Password:` 测试）

### 2.6 全包升级 - 通用时序与收尾

- **状态**：已确认验收（升级结束关闭自动打开串口终端）/ 已实现未验收（TX 输出复用主执行日志）
- **核心验收行为**：
  - 升级结束后关闭**自动打开**的串口终端；手动打开的不受影响
  - `Tftp指令` / `Tftp Put` 升级链路均复用主执行日志的 TX 输出
- **禁止破坏**：保留确认弹窗 + 主执行日志；`finally` 中关闭会话与电源长连接
- **对应测试**：`tests/test_app.py`（自动打开 / 手动打开终端的差异化断言）

### 2.7 批量写样机参数（默认走 telnet 路径）

- **状态**：已确认验收（1 台单台 telnet 路径，2026-07-17；6 台独立 VLAN 并行 telnet 路径，2026-07-19；流水线下发命令由可选 Checkbutton 控制：`ppctl clear` 与 `AGING_STATE=1` 默认关闭、勾选才下发、关闭时主日志输出"关闭，跳过"，2026-07-19 6 台真实样机验收通过；默认并行数 1 / 确认框 9 步自然顺序 / 清理失败步骤名标识 同步验收通过）/ 已实现未验收（2 / 8 台端点并行；2026-07-19 用 6 台覆盖了原计划 2 / 4 / 8 区间中段代表性场景）
- **业务时序**：UBUS 启用 telnet → `TelnetSession`（未登录） → 首次登录 → 1. 进入工厂模式（`ppctl set FACTORY_MODE=1`）→ 2. `firstboot -yr` → 3. 等待 100 秒 → 4. 工厂模式二次登录 → 5.（可选 `ppctl set AGING_STATE=1`）→ 6.（可选 `ppctl clear`）→ 7. 15 项 `ppctl set/get` 读回校验 → 8. 退出工厂模式（`ppctl set FACTORY_MODE=0`）→ 9. `firstboot -yr`（`finally` 中执行第 8/9 步）

  写参前置新增「启用对应通道网卡 + 按 `channel.network_card_ip` 设置静态 IP + `wait_for_bindable_ip` 等 15 秒」三步（任何一步失败抛 `RuntimeError` → worker 标记 `telnet 写参启动失败`，单台放弃不影响其它通道），位于 `make_telnet_factory` 内 UBUS 启用 telnet 之前；100 秒工厂模式网段切换继续由 `make_factory_session_swap` 处理，PC 端从 `192.168.1.x` 切到 `192.168.29.x`、主机位保持不变。`factory_bind_ip` / `factory_device_host` 未配置时按 `factory_bind_ip_for(network_card_ip)` / `factory_device_host_for(device_manage_ip)` 自动派生（第 3 段 → 29，主机位不变）；手动填值优先级最高。
- **并行与取消**：并行 1-8 台（默认 1；2026-07-19 用户要求默认串行更稳，多台并发易撞 UBUS HTTP / telnet login / NIC；Spinbox 仍允许 1–8 现场上调；升级窗口的 `parallel_count` 默认仍为 2，互不影响）；取消时停止后续命令并尝试退出工厂模式
- **节奏常量（2026-07-18 P2 缓解）**：默认 `src/services/sample_parameter_service.py` 顶部 7 个常量，按现场经验统一调整；`_login` prompt/password_prompt 用 `PARAMETER_LOGIN_PROMPT_TIMEOUT_SECONDS=10.0`、password_result 用 `PARAMETER_LOGIN_PASSWORD_TIMEOUT_SECONDS=20.0`；`_write_and_verify` set 后 sleep `PARAMETER_SETTLE_AFTER_SET_SECONDS=1.5`、get 等 marker 用 `PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS=10.0`、mismatch/marker=None 后退避 `PARAMETER_RETRY_BACKOFF_SECONDS=1.5`、成功/失败末尾 BETWEEN_PARAMS=`0.5`；并行 worker 错峰 `PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS=0.6`。若 8 台并行仍偶发失败，优先上调 `PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS=15.0` 与 `PARAMETER_RETRY_BACKOFF_SECONDS=2.5`。
- **前置 UBUS 协议**：经自写 `UbusHttpClient` 按 `SdmcUbusLibEnableTelnet.Enable_telnet` 协议开 LAN-telnet 规则 — ① 总开关 `Device.Firewall.<X_SDMC_>Security.AccessCtrl.Enable` 若非 `"1"` 则 `set Enable=1`（用对象路径 `...AccessCtrl.`，非参数路径，避免 fault 9005 `EnableEnable`）；② 查 `AccessCtrl.Rule.{}.` 既有 telnet 规则（`SourceInterface ∈ {lan, both, Device.IP.Interface.1}`）— 已启用返回 `already_present`，否则 `set Enable=1` 返回 `reused`；③ 若无合适规则则 `add {SourceInterface: Device.IP.Interface.1, IPVersion:4, SourceIP:0.0.0.0, Application:telnet}` 返回 `added_iface`；失败回退 `add SourceInterface=lan` 返回 `added_lan_fallback`。每步校验 `results[*].data == "1"`，末尾固定 `sleep_fn(ENABLE_TELNET_FINAL_SLEEP_SECONDS=1.0)` 给防火墙 reload 留缓冲。
- **核心验收行为（2026-07-19 6 台独立 VLAN110–VLAN115 真实样机并行验收通过，含可选项化 + 默认并行 1）**：
  - 6 个 worker 通过 `PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS=0.6` 错峰启动，避免同 t=0 把 NIC / 防火墙挤爆；UBUS 启用 telnet 4 段日志按样机独立给出，没有交错串行。
  - 6 台全部完成 `TelnetSession`（按 VLAN `bind_ip` 锁源）→ 首次登录 → （按主界面 Checkbutton 状态）`AGING_STATE=1` / `ppctl clear` → `FACTORY_MODE=1` + `firstboot -yr` → 等 100 秒 → 工厂模式网段切换（192.168.1.{N} → 192.168.29.{N}，`factory_bind_ip`/`factory_device_host` 自动派生）→ 工厂模式二次登录 → 15 项 `ppctl set/get` 读回校验通过 → `FACTORY_MODE=0` + `firstboot -yr`（`finally` 清理成功，主执行日志出现"已下发退出工厂模式与重启命令"）。
  - 「清空参数」勾选时 6 台 `TX ppctl clear` 全部出现在主执行日志；关闭时 6 台主日志均出现"清空参数：关闭，跳过"且设备 ppctl 表保持未清空。「退出老化」勾选时 6 台 `TX ppctl set AGING_STATE=1` 全部出现在主执行日志；关闭时 6 台主日志均出现"退出老化：关闭，跳过"。
  - 默认并行 1 时 6 台变为串行（每台完整 9 步自然顺序），主执行日志依次出现 `开始批量写样机参数：6 台，并行上限 1` 与每台写参的完整 9 步；Spinbox 现场调到 2 / 4 仍能正常并行。
  - 6 台未触发 `bind_ip == device_host` 配置冲突预检（vlan110/111 已修过 device_manage_ip）；也未触发"清理失败步骤名消失"问题（每台清理失败若发生，会精确显示是 FACTORY_MODE=0 还是 firstboot -yr 触发的）。
  - 覆盖了原计划 2 / 4 / 8 台区间的中段代表性场景（4 段 UBUS HTTP 抢网卡、6 个 telnet session 并发登录、错峰启动对 NIC / 防火墙压力的缓解效果都得到验证）；2 台 / 8 台端点如现场需要再补验收。
- **核心验收行为（2026-07-17 单台 VLAN114 真实样机验收通过）**：
  - 主执行日志依次输出「写参前置：准备网络 vlan114（192.168.1.114 / 255.255.255.0） → 检查并启用网卡 → 已启用网卡 → 设置静态 IP → 已设置 → UBUS 启用 telnet 中 → UBUS 三段消息（AccessCtrl 总开关开启 / 规则 enable / 最终 action） → UBUS 启用 telnet added_iface/already_present: ... → STATE Telnet 已连接 → 首次登录成功 → TX ppctl clear → TX ppctl set FACTORY_MODE=1 → TX firstboot -yr → 等待 100 秒 → 工厂模式网段切换：准备把 vlan114 设为 192.168.29.114（自动派生自 network_card_ip）→ 工厂模式重建 TelnetSession 成功（192.168.29.114 → 192.168.29.1） → 工厂模式二次登录 → 15 项 TX ppctl set/get 读回校验 → 写参完成，15 项均已读回校验 → TX ppctl set FACTORY_MODE=0 → TX firstboot -yr → 已下发退出工厂模式与重启命令」
  - `factory_bind_ip` / `factory_device_host` 在 `network_card_ip.ini` 故意留空，由派生逻辑兜底；现场若需特殊工厂模式网段（与 192.168.29.x 不同），手动填入 ini 即可覆盖派生
- **边界与异常**：
  - 参数值不允许双引号 / 回车 / 换行
  - 密码类字段在终端与日志脱敏
  - 源 IP 不可绑时强提示人工检查 `network_card_ip.ini`，不回退 `0.0.0.0`
  - 派生失败（`network_card_ip` / `device_manage_ip` 缺失或格式无效）时 `_start_sample_parameter_write` 弹错误并要求补齐
  - **`ppctl clear` 与 `ppctl set AGING_STATE=1` 选项化（2026-07-19）**：两个命令不再默认下发；`SampleParameterWriteRequest` 新增 `clear_parameters` / `exit_aging` 两个 `bool` 字段（默认 `False`），由主界面 Checkbutton「清空参数」/「退出老化」控制。勾选后，工厂模式二次登录成功时分别下发对应命令；未勾选时主执行日志输出 `清空参数：关闭，跳过` / `退出老化：关闭，跳过`，不实际下发命令。顺序固定为「退出老化 → 清空参数 → 15 项 ppctl set/get」。两个字段状态持久化到 `sample_upgrade_settings.ini`（`parameter_clear_parameters` / `parameter_exit_aging`），旧 ini 兼容回退 False。需在 6 / 8 台真实样机上回归确认现场是否符合"勾选才下发"的语义。
  - **配置冲突（2026-07-18）**：`bind_ip == device_host`（PC 静态 IP 与样机管理 IP 相同）→ PC 把自己作为目标连接，必然 timed out。`_start_sample_parameter_write` 预检命中即弹「样机 IP 配置冲突」并阻止 worker 启动；同时 `TelnetSession._open_socket` / `UbusHttpClient._post` 在 `bind_ip == device_host` 时，错误消息附加 hint 提示操作员去 `network_card_ip.ini` 修 `device_manage_ip`（典型值 192.168.1.1）。
  - **退出工厂模式清理失败（2026-07-19）**：`finally` 清理块把 `ppctl set FACTORY_MODE=0` 与 `firstboot -yr` 拆为两个独立 `try/except`，第 1 步失败也会尝试第 2 步（best-effort）。两步的 TX 主程序执行日志都必然出现（`_send_stage` 内部 `emit` 在 `send_line` 之前），失败消息明确包含 step 名（`FACTORY_MODE=0 下发失败：…` / `firstboot -yr 下发失败：…`），多条失败用「；」拼接，便于操作员分辨是哪一步触发的"Telnet 连接已关闭"。
- **禁止破坏**：
  - `TelnetSession`、`UbusHttpClient` 必须按 VLAN `bind_ip` 锁源（`source_address=(bind_ip, 0)`）
  - 串口路径保留作 transport 配置回退入口；其他功能（页面升级 / 全包升级 / 串口终端）不受影响
  - UBUS HTTP 客户端不复用 `SdmcUbusLib`（其会话静态、不允许多并发）— 如要替换须保证同等并发与源 IP 锁源语义
  - 工厂模式网段约定 29（第 3 段替换）必须保持稳定；变更前需通知所有现场并同步升级 `network_ops.py` 常量
- **待确认**：2 / 8 台端点独立 VLAN 真实样机并行验收（VLAN/MAC 对应、`set/get` 读回校验、取消清理、退出工厂模式后的重启、日志脱敏、UBUS 启用 telnet 与 telnet 登录衔接时序；2026-07-19 已用 6 台覆盖了 2 / 4 / 8 区间中段代表性场景）
- **对应测试**：`tests/test_sample_parameter_service.py`、`tests/test_telnet_transport.py`、`tests/test_ubus_http_client.py`、`tests/test_ubus_enable_telnet.py`、`tests/test_sample_parameter_table.py`、`tests/test_sample_parameter_app.py`、`tests/test_channel_config.py`、`tests/test_regression_sleep_fn.py`、`tests/test_network_ops.py`

### 2.8 随机参数表生成（`.xlsx`）

- **状态**：已确认验收（2026-07-19 6 台独立 VLAN110–VLAN115 真实样机验收通过：同批 MAC 前 6 位 OUI 固定 + 2.4G / 5G SSID 后缀取本机 MAC 末 4 位十六进制 + 「SN/GPON SN 随机后缀长度」label 与 SSID 解耦）
- **核心行为**：按已勾选 VLAN 生成 `.xlsx` 表，导出后自动加载并预检（**不自动下设备**）；MAC 同批前 6 位（OUI）固定、后 6 位（NIC 标识）每台唯一；SN、GPON SN 每行唯一（随机后缀）；2.4G / 5G SSID 后缀取本机 MAC 末 4 位十六进制（同一行两个 SSID 共享后缀）；密码类字段明文显示（操作员核对需要）
- **兼容性约束**：导入兼容旧表共用 `WiFi Password` / `Country code` 列
- **2026-07-19 同 OUI 改动（已确认验收）**：自动生成时一次性随机生成 3 字节 OUI（保留本地管理 bit1=1 + 单播 bit0=0 的位设置），每条记录只随机生成后 3 字节 NIC 标识并拼接；同批 N 条记录的 MAC 前 6 位完全一致。6 台真实样机验收：6 条记录的 MAC 前 6 位字符串完全相同，后 3 字节每台唯一；样机端能正确识别。
- **2026-07-19 SSID 末 4 位 MAC 强关联（已确认验收）**：2.4G / 5G SSID 后缀不再随机生成，改为 `mac.replace(":", "")[-4:]` 取本机 MAC 末 4 位十六进制（大写），便于操作员把同一行 SSID 与本机 MAC 一眼对应。例：`MAC=CA:7A:85:18:B0:E8` → 2.4G SSID = `ssid_24_prefix` + `B0E8`；5G SSID = `ssid_5_prefix` + `B0E8`（共享同一后缀）。6 台真实样机验收：6 条记录的 2.4G / 5G SSID 后缀全部等于各自 MAC 末 4 位，且同一行两个 SSID 互相一致；样机端能正确识别。
- **2026-07-19 label 优化（已确认验收）**：生成窗口输入框 label 从 "随机后缀长度" 改为 "SN/GPON SN 随机后缀长度"，与 SN/GPON SN 两个字段字面对齐，避免操作员误以为该字段也控制 2.4G / 5G SSID 长度。
- **对应测试**：`tests/test_sample_parameter_table.py`

### 2.9 页面升级 - UBUS 批量

- **状态**：已实现未验收
- **核心行为**：
  - 启用目标 VLAN 网卡 + 切换 PC 到样机管理 IP 网段（`prepare_network_for_sample`）
  - HTTP/HTTPS `ubus` 登录、上传固件、调用 `Device.DeviceInfo.X_SDMC_Upgrade()`
  - 升级后 UBUS `Device.FactoryReset()`（`proto=web`）；关闭时输出"恢复出厂：关闭，跳过"
- **禁止破坏**：
  - `Access denied` 兼容三种 RPC：`bbfdm.operate` / `bbfdm.operate(proto=web)` / `bbfdm.unauthenticated_operate`
  - `PageUpgradeRequest.restore_factory` 已落地；只可在**升级成功 + 重启 + 重新登录成功**之后调用
  - 不提前 `logout` 复用已验证会话
- **待确认**：真实样机勾选"恢复出厂"时日志依次出现「升级成功 → 重新登录成功 → `TX UBUS Device.FactoryReset()` → 已下发」；未勾选时只出现"恢复出厂：关闭，跳过"；`vlan137/138/139` 升级前网卡切换后 HTTP/HTTPS 一次登录成功
- **对应测试**：`tests/test_page_upgrade.py`（含 `restore_factory`、`exit` 回退策略）、`tests/test_app.py`、`tests/test_network_ops.py`

### 2.10 ZTE OLT ONU 注册

- **状态**：已实现未验收
- **核心行为**：
  - 未注册 ONU 复选列表 + 全选 / 取消全选
  - SD-41 模板下发（`interface gpon-olt`、`gpon-onu`、业务 VLAN、`pon-onu-mng`）
  - 新增业务配置失败时改用「删除已注册但不在线 ONU → `registration-method sn 新SN`」复用旧 ONU
  - 注册完成后询问保存 OLT 配置（先退出 `ZXAN(config)#` / `config-if`，再 `write`）
- **禁止破坏**：注册不自动保存 OLT 配置；窗口默认尺寸 896x580；本机凭据不入 Git
- **待确认**：现场 OLT `Access denied`、新增配置失败、删除 / 重注册三类实际表现与提示文案
- **对应测试**：`tests/test_network_ops.py`（含离线 ONU 优先同 PON 删除）、`tests/test_app.py`

### 2.11 输入持久化与启动 / 打包

- **状态**：已实现未验收
- **核心行为**：
  - 升级方式 / 固件路径 / 恢复出厂 / 超级凭据 / 并行数 → `Auto_power_on_off_tool/config/sample_upgrade_settings.ini`
  - OLT IP / 用户名 / 密码 → `Auto_power_on_off_tool/config/onu_registration.ini`
  - 串口终端窗口位置 + 日志目录 → `~/.aouxue_serial_terminal.json`
  - VS Code `.vscode/launch.json` 中 `LineCheckAssistant` 入口以 `Cheating_machine_execution_tool` 为工作目录；`.venv_serial_upgrade` 配套 `tftpy==0.8.7`
  - 打包脚本非交互式；`.spec` 落 `line_check_assistant/packaging_specs`
- **禁止破坏**：
  - 本机配置文件不入 Git
  - INI 转义（含 `%`）不得再触发 `ConfigParser` 内插崩溃
  - 开发使用 `.venv_serial_upgrade`，不污染全局或 `.venv`
- **对应测试**：`tests/test_sample_upgrade_settings_store.py`、`tests/test_onu_registration_store.py`

### 2.12 「全流程执行」管道编排器（主界面「检查并执行测试」按钮升级）

- **状态**：已实现未验收
- **核心行为**：
  - 主界面「检查并执行测试」按钮按下后弹出「全流程执行」窗口（替代旧实现的「直接跑 ping 检查」）
  - 6 个子任务（1→6 固定顺序）：
    1. **自动上/下电**（默认勾选）—— 调 `power_on_service.power_on_selected_channels` / `turn_off_selected_channels` 同步执行；必填项：程控电源 COM + 上/下电（`sample_upgrade_settings.ini` 新增 `power_operation`）+ ≥1 已勾选通道
    2. **样机升级**（默认不勾）—— 调主程序既有 `_start_page_upgrade` / `_start_tftp_command_upgrade` / `_start_tftp_put_upgrade`（异步起线程 + 弹确认框）；必填项：升级方式 / 固件 / 超级用户凭据 / Tftp 指令或 Put
    3. **写样机参数**（默认不勾）—— 调主程序既有 `_start_sample_parameter_write`（异步起线程 + 弹确认框）；必填项：参数表路径（`sample_upgrade_settings.ini` 新增 `parameter_table_path`）+ 写参首次登录账号 / 密码
    4. **ONU 注册**（默认不勾）—— 调主程序既有 `_on_onu_query_clicked` + `_on_onu_register_clicked`（异步起线程 + 弹确认框）；必填项：OLT IP / 用户名 / 密码
    5. **串口日志（管道期间持续记录）**（默认勾选）—— 调主程序既有 `_open_serial_log_module` 打开 `SerialTerminalWindow`；**非致命**（打开失败不阻塞后续）
    6. **测试项配置（[order] 执行）**（默认勾选）—— 调新 `test_item_execution_service.run_test_item_execution` 同步执行（每台串行）；按 `[order]` 顺序逐条 telnet 下发 + per-segment fuzzy 匹配（`!A&&B`）+ 每条命令 `retry_times` 次重试（间隔 `command_fail_retry_interval_time` 秒）；per-channel 结果文件写到 `Cheating_machine_execution_tool/test_results/device_{section}_command_results_{YYYYMMDD_HHMMSS}.log`
  - 每行右侧实时显示「必填项当前状态」（绿色就绪 / 红色「缺: 字段1, 字段2」），「去配置」按钮跳到主程序对应子窗口
  - 「开始执行」走「必填项未就绪警告 + 全流程执行确认」二次确认后启动后台线程
  - 任一「致命」子任务抛异常 → 整个管道停止，弹错误框；串口日志失败只记结果不阻塞
  - 「停止」按钮：编排器在当前子任务结束后终止后续子任务
- **核心验收行为（2026-07-20 单测全过，真实样机待验收）**：
  - 全量 374 项单测（313 → +18 fuzzy + 14 test_item + 26 pipeline + 3 settings）全过；`scripts/verify_baseline.py` `ALL CHECKS PASSED`（29 个 .py 编译 + 374 项单测 + 8 条 MUST_EXIST + 1 条 MUST_NOT_EXIST 全绿）
  - per-segment fuzzy 语义与老工具 `common/fuzzy_match.py` 一致：`!段A&&段B` 拆为 `[(True,"段A"), (False,"段B")]`；肯定段 `in` 子串匹配、否定段 `re.escape(segment)` 搜索；空段跳过；老工具 `tcapi get WanInfo_Entry` IPv6 特殊分支不移植
  - 测试项执行 service 复用 `TelnetSession` 协议（按 VLAN `bind_ip` 锁源 `source_address=(bind_ip, 0)`，不绑直接抛错不回退 `0.0.0.0`）；登录阶段按 `telnet.input_user_flag` / `input_password_flag` / `login_success_flag` 三段等
  - per-channel 结果文件路径生成 `Cheating_machine_execution_tool/test_results/device_{section}_command_results_{YYYYMMDD_HHMMSS}.log`（用户决策：与老工具 `Auto_power_on_off_tool/test_results/` 分离）
  - 编排器 6 子任务调度顺序与失败传播：1→6 固定、致命失败抛 `PipelineError`、串口日志失败只记结果不阻塞、用户点「停止」时 `request_stop` 在当前子任务结束后终止后续
- **边界与异常**：
  - 必填项未就绪时弹「必填项未就绪」警告询问是否继续（不强阻，便于操作员知情决策）
  - 关闭窗口时若管道运行中弹「全流程执行正在进行」二次确认
  - 异步子任务（2/3/4）由主程序既有 worker 完成，编排器不阻塞等待；失败传播靠用户点击确认 + 主程序 worker 异常冒泡
- **禁止破坏**：
  - `TelnetSession` 协议（按 VLAN `bind_ip` 锁源）必须复用，不重写 telnet 客户端
  - 子任务 1/5/6 调既有 service，不绕过主程序中间层
  - 子任务 2/3/4 调主程序既有 `_start_*` 方法，弹确认框由操作员点「是」（与单功能窗口一致）
  - `0.0.0.0` 不出现在 telnet / tftp 路径（与 §1.4 一致）
  - AGENTS 硬规则：不修改老工具 `Auto_Power_On_Off_Tool.py` 源码；fuzzy 逻辑从老工具 `fuzzy_match.py` 移植而非直接 import
- **待确认**：
  - Windows 桌面真实交互：弹窗 / Checkbutton / 二次确认 / 必填项状态刷新
  - 真实样机端到端跑通 6 子任务全流程：上下电 → 升级 → 写参 → ONU 注册 → 串口日志（持续）→ [order] 执行
  - 异常场景：2/3/4 异步子任务失败传播（当前靠主程序 worker 异常冒泡 + 用户观察主执行日志；是否需要 polling + 状态轮询机制待定）
- **对应测试**：
  - `tests/test_fuzzy_match_runner.py`（18 项：单段 / 多段 / 否定 / 混合 / 空段 / re.escape / IPv6 边界 / 性能）
  - `tests/test_test_item_execution_service.py`（14 项：单条匹配 / 失败重试 / 重试成功 / per-segment !A&&B / 无期望默认通过 / 多条顺序 / 网络准备失败 / 登录失败 / 结果文件创建 / session finally 关闭 / build_log_path / 常量）
  - `tests/test_pipeline_orchestrator.py`（26 项：6 子任务状态评估 / run 顺序 / 致命失败抛 PipelineError / 串口失败不阻塞 / request_stop 阻止后续 / 6 个子任务 statuses 完整性 / 必填项 missing 标记）
  - `tests/test_sample_upgrade_settings_store.py`（+3 项：power_operation / parameter_table_path 持久化 / power_operation 非法值回退 `up`）
  - `tests/test_app.py`（+1 项：`_current_sample_upgrade_settings` 透传 2 个新字段）

---

## 3. 待确认 / 疑似过时内容

> 列入此节的内容暂不进入第 2 节"功能验收清单"，直到对应依据补齐。

1. **§2.6 全包升级通用时序 中"恢复出厂命令实际下发 → 主程序执行日志输出 `TX firstboot -y;reboot`（2026-07-12）"** — 原文件标为"已确认验收"，但 `DEVELOPMENT_LOG.md` 在 2026-07-12 这天未找到对应的真实样机验收条目（当日三条记录为：Tftp指令 ARP 重试、Tftp Put 多台串行验收通过、全包升级关闭自动终端）。**已从 §2.6 中移除并降级为「待确认」**，待用户核对原始证据后再决定升回。

2. **§2.4 §Tftp指令 中"串口乱码盲发密码补救登录（`peek_since` salvage 路径）"** — 同样在已读到的 `DEVELOPMENT_LOG.md`（至 2026-07-12）中未找到对应的真实样机验收条目。**暂保留"已确认验收"标签**，需用户二次核对日期后确认或降级。

3. **测试文件数**：原文件抬头列"tests/ 下 14 个 unittest 文件"，实测 **16 个**（新增 `test_sample_parameter_app.py`、`test_sample_parameter_table.py`）。本文已统一为 16，未来请以实际 `ls tests/` 为准。

4. **`PROJECT_STATUS.md`** 抬头日期写"更新：2026-07-13"，但表格内已含 2026-07-15 的 199 项基线 — 不在本任务范围，但提示 `ACCEPTANCE_BASELINE.md` 与 `PROJECT_STATUS.md` 都存在更新日期与内容时间不一致，统一时建议同步刷新。
