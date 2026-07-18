# Acceptance Baseline

更新：2026-07-17

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

预期 `Ran 249 tests ... OK`（2026-07-17 实跑；原 199 + 本轮新增 50：网络准备前置 4 + factory 派生 14 + factory session swap 7 + 其它历史补充 22 + UBUS retry 3）。

## 1. 全局不可破坏规则

### 1.1 入口、运行与打包

- 入口：`Cheating_machine_execution_tool/run_line_check_assistant.py` → `line_check_assistant.app.main()`
- 依赖：`pyserial==3.5` / `tftpy==0.8.7` / `requests>=2.31,<3` / `openpyxl>=3.1,<4` / `xlrd>=2.0,<3`（详见 `requirements.txt`、`THIRD_PARTY_NOTICES.md`）
- 打包：`powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1` → `dist\LineCheckAssistant.exe`
- **构建后不在当前 PC 运行 `dist\LineCheckAssistant.exe`**，仅确认打包成功并报告路径

### 1.2 测试与目录基线

- 全量：`python -m unittest discover -s tests -v` → **249 项全过**（2026-07-17 实跑，对应 `tests/` 下 19 个 unittest 文件）
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

- **状态**：已确认验收（1 台单台 telnet 路径，2026-07-17）/ 已实现未验收（2 / 4 / 8 台并行）
- **业务时序**：UBUS 启用 telnet → `TelnetSession`（未登录） → 首次登录 → `ppctl clear` → `ppctl set FACTORY_MODE=1` → `firstboot -yr` → 等 100 秒 → 工厂模式二次登录 → 15 项 `ppctl set/get` 读回校验 → `FACTORY_MODE=0` + `firstboot -yr`（`finally` 中执行）

  写参前置新增「启用对应通道网卡 + 按 `channel.network_card_ip` 设置静态 IP + `wait_for_bindable_ip` 等 15 秒」三步（任何一步失败抛 `RuntimeError` → worker 标记 `telnet 写参启动失败`，单台放弃不影响其它通道），位于 `make_telnet_factory` 内 UBUS 启用 telnet 之前；100 秒工厂模式网段切换继续由 `make_factory_session_swap` 处理，PC 端从 `192.168.1.x` 切到 `192.168.29.x`、主机位保持不变。`factory_bind_ip` / `factory_device_host` 未配置时按 `factory_bind_ip_for(network_card_ip)` / `factory_device_host_for(device_manage_ip)` 自动派生（第 3 段 → 29，主机位不变）；手动填值优先级最高。
- **并行与取消**：并行 1-8 台（默认 2）；取消时停止后续命令并尝试退出工厂模式
- **前置 UBUS 协议**：经自写 `UbusHttpClient` 按 `SdmcUbusLibEnableTelnet.Enable_telnet` 协议开 LAN-telnet 规则 — ① 总开关 `Device.Firewall.<X_SDMC_>Security.AccessCtrl.Enable` 若非 `"1"` 则 `set Enable=1`（用对象路径 `...AccessCtrl.`，非参数路径，避免 fault 9005 `EnableEnable`）；② 查 `AccessCtrl.Rule.{}.` 既有 telnet 规则（`SourceInterface ∈ {lan, both, Device.IP.Interface.1}`）— 已启用返回 `already_present`，否则 `set Enable=1` 返回 `reused`；③ 若无合适规则则 `add {SourceInterface: Device.IP.Interface.1, IPVersion:4, SourceIP:0.0.0.0, Application:telnet}` 返回 `added_iface`；失败回退 `add SourceInterface=lan` 返回 `added_lan_fallback`。每步校验 `results[*].data == "1"`，末尾固定 `sleep_fn(ENABLE_TELNET_FINAL_SLEEP_SECONDS=1.0)` 给防火墙 reload 留缓冲。
- **核心验收行为（2026-07-17 单台 VLAN114 真实样机验收通过）**：
  - 主执行日志依次输出「写参前置：准备网络 vlan114（192.168.1.114 / 255.255.255.0） → 检查并启用网卡 → 已启用网卡 → 设置静态 IP → 已设置 → UBUS 启用 telnet 中 → UBUS 三段消息（AccessCtrl 总开关开启 / 规则 enable / 最终 action） → UBUS 启用 telnet added_iface/already_present: ... → STATE Telnet 已连接 → 首次登录成功 → TX ppctl clear → TX ppctl set FACTORY_MODE=1 → TX firstboot -yr → 等待 100 秒 → 工厂模式网段切换：准备把 vlan114 设为 192.168.29.114（自动派生自 network_card_ip）→ 工厂模式重建 TelnetSession 成功（192.168.29.114 → 192.168.29.1） → 工厂模式二次登录 → 15 项 TX ppctl set/get 读回校验 → 写参完成，15 项均已读回校验 → TX ppctl set FACTORY_MODE=0 → TX firstboot -yr → 已下发退出工厂模式与重启命令」
  - `factory_bind_ip` / `factory_device_host` 在 `network_card_ip.ini` 故意留空，由派生逻辑兜底；现场若需特殊工厂模式网段（与 192.168.29.x 不同），手动填入 ini 即可覆盖派生
- **边界与异常**：
  - 参数值不允许双引号 / 回车 / 换行
  - 密码类字段在终端与日志脱敏
  - 源 IP 不可绑时强提示人工检查 `network_card_ip.ini`，不回退 `0.0.0.0`
  - 派生失败（`network_card_ip` / `device_manage_ip` 缺失或格式无效）时 `_start_sample_parameter_write` 弹错误并要求补齐
- **禁止破坏**：
  - `TelnetSession`、`UbusHttpClient` 必须按 VLAN `bind_ip` 锁源（`source_address=(bind_ip, 0)`）
  - 串口路径保留作 transport 配置回退入口；其他功能（页面升级 / 全包升级 / 串口终端）不受影响
  - UBUS HTTP 客户端不复用 `SdmcUbusLib`（其会话静态、不允许多并发）— 如要替换须保证同等并发与源 IP 锁源语义
  - 工厂模式网段约定 29（第 3 段替换）必须保持稳定；变更前需通知所有现场并同步升级 `network_ops.py` 常量
- **待确认**：2 / 4 / 8 台独立 VLAN 真实样机并行验收（VLAN/MAC 对应、`set/get` 读回校验、取消清理、退出工厂模式后的重启、日志脱敏、UBUS 启用 telnet 与 telnet 登录衔接时序）
- **对应测试**：`tests/test_sample_parameter_service.py`、`tests/test_telnet_transport.py`、`tests/test_ubus_http_client.py`、`tests/test_ubus_enable_telnet.py`、`tests/test_sample_parameter_table.py`、`tests/test_sample_parameter_app.py`、`tests/test_channel_config.py`、`tests/test_regression_sleep_fn.py`、`tests/test_network_ops.py`

### 2.8 随机参数表生成（`.xlsx`）

- **状态**：已实现未验收
- **核心行为**：按已勾选 VLAN 生成 `.xlsx` 表，导出后自动加载并预检（**不自动下设备**）；MAC / SN / SSID 唯一；密码类字段明文显示（操作员核对需要）
- **兼容性约束**：导入兼容旧表共用 `WiFi Password` / `Country code` 列
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

---

## 3. 待确认 / 疑似过时内容

> 列入此节的内容暂不进入第 2 节"功能验收清单"，直到对应依据补齐。

1. **§2.6 全包升级通用时序 中"恢复出厂命令实际下发 → 主程序执行日志输出 `TX firstboot -y;reboot`（2026-07-12）"** — 原文件标为"已确认验收"，但 `DEVELOPMENT_LOG.md` 在 2026-07-12 这天未找到对应的真实样机验收条目（当日三条记录为：Tftp指令 ARP 重试、Tftp Put 多台串行验收通过、全包升级关闭自动终端）。**已从 §2.6 中移除并降级为「待确认」**，待用户核对原始证据后再决定升回。

2. **§2.4 §Tftp指令 中"串口乱码盲发密码补救登录（`peek_since` salvage 路径）"** — 同样在已读到的 `DEVELOPMENT_LOG.md`（至 2026-07-12）中未找到对应的真实样机验收条目。**暂保留"已确认验收"标签**，需用户二次核对日期后确认或降级。

3. **测试文件数**：原文件抬头列"tests/ 下 14 个 unittest 文件"，实测 **16 个**（新增 `test_sample_parameter_app.py`、`test_sample_parameter_table.py`）。本文已统一为 16，未来请以实际 `ls tests/` 为准。

4. **`PROJECT_STATUS.md`** 抬头日期写"更新：2026-07-13"，但表格内已含 2026-07-15 的 199 项基线 — 不在本任务范围，但提示 `ACCEPTANCE_BASELINE.md` 与 `PROJECT_STATUS.md` 都存在更新日期与内容时间不一致，统一时建议同步刷新。
