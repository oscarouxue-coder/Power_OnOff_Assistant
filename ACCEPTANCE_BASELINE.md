# ACCEPTANCE_BASELINE（验收基线）

更新：2026-07-15（基于 `AGENTS.md`、`PROJECT_STATUS.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`、`requirements.txt`、`THIRD_PARTY_NOTICES.md` 与 `tests/` 下 14 个 unittest 文件）

> 与 `PROJECT_STATUS.md` 的关系：本文件按"实现 → 单测 → 真实样机验收"三态生成证据矩阵，作为独立验收基线；`PROJECT_STATUS.md` 保留面向项目的进度叙述。本文件不替代 `DEVELOPMENT_LOG.md`。

## 0. 阅读顺序与判定规则

- 只记录有源码、`tests/*.py` 单测、`README`/`DEVELOPMENT_LOG`/`PROJECT_STATUS` 任一文档中至少一项明确依据的功能。
- **已确认验收**：单元测试通过，且在 `DEVELOPMENT_LOG.md` 中出现"真实样机验收通过 / 用户已在真实样机完成 ... 验收"明确字样，并经用户核实。
- **已实现但未确认验收**：代码与单元测试通过，但未在 `DEVELOPMENT_LOG.md` 找到明确真实样机验收记录。
- **待确认**：仅有代码或测试入口，未安排或未完成真实样机验收。
- "未明确确认"绝不自动判为"已验收"。

## 1. 通用运行、测试与打包

- 入口：`Cheating_machine_execution_tool/run_line_check_assistant.py` → `line_check_assistant.app.main()`
- 依赖：`pyserial==3.5` / `tftpy==0.8.7` / `requests>=2.31,<3` / `openpyxl>=3.1,<4` / `xlrd>=2.0,<3`
- 三方清单：`THIRD_PARTY_NOTICES.md`（pySerial BSD-3、TFTPy MIT、openpyxl MIT、xlrd BSD）
- 测试基线：**`python -m unittest discover -s tests -v` → 184 项全部通过（2026-07-15 实跑）**
- 打包：`powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1`
- 唯一配置目录：`Auto_power_on_off_tool/config/{network_card_ip.ini, sample_upgrade_settings.ini, onu_registration.ini}`；顶层 `Cheating_machine_execution_tool/config/` 已删除
- **已确认验收**：源码运行入口、依赖清单、单元测试 184 项通过（编译 + 单测即足够，未要求真实样机）
- **兼容性约束**：构建后不在当前 PC 运行 `dist\LineCheckAssistant.exe`；不动 `build/`/`dist/`/`logs/`/`.venv/`

## 2. 通道配置 / 网卡 / Ping

- **已实现但未确认验收**：读写真实化（基于 `tests/test_app.py`、`tests/test_paths.py`），通道列表、网卡刷新、子网配置、Ping 样机管理 IP
- **待确认**：现场通道变更联动 `network_card_ip.ini` 的端到端真实样机验证
- **回归检查点**：`tests/test_paths.py`、`tests/test_app.py` 中通道配置相关断言；`grep` `network_card_ip.ini` 关键字确认写入路径唯一
- **兼容性约束**：写网卡静态 IP 需要管理员权限；现场操作员需以管理员启动 PowerShell 或打包后的 EXE

## 3. 程控电源（COM101-COM116 直连）

- **已确认验收**：
  - 主程序直连程控电源，移除旧 GUI（`Auto_Power_On_Off_Tool.exe` / UI Automation 调用）
  - 自动上电相邻开启帧间隔 1 秒、取消末尾 10 秒启动等待，且现场已验收自动上电新流程
- **已实现但未确认验收**：
  - 自动下电（仅发关闭帧、相邻 1 秒，不发全断电帧）
  - 同批次程控电源 COM 由 `UpgradePowerCycleCoordinator` 持有长连接（`open` 仅一次，`close()` 幂等）
  - 并行 1-8 台、默认 2 台（`MAX_PARALLEL_UPGRADES=8`、`clamp_parallel_count`）
- **待确认**：4 台、8 台独立 VLAN/COM 场景下 COM 长连接复用效果、并行上电对功率闸容量的实测
- **兼容性约束**：19200 8N1；不修改 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 源码（哈希未变）；不发送全断电帧
- **回归检查点**：`tests/test_power_supply.py`、`tests/test_app.py`、`tests/test_serial_upgrade_service.py`；手动核对旧工具源码哈希

## 4. 串口日志 / 多 VLAN 终端

- **已确认验收**：
  - 命令输入框支持 Enter 发送（2026-07-15）：非空等价「发送」、空字符串等价「回车」；自动升级占用与危险命令二次确认仍生效 — 用户已线下样机验证通过
- **已实现但未确认验收**：
  - 多 Tab、`vlan{N} -> COM{N-100}` 固定映射、按 VLAN 合并后只渲染当前 Tab，48 KiB 屏幕缓冲、33ms 节流
  - 危险命令（`reboot`/`reset`/`firstboot`/`tftp`/`upgrade`）二次确认
  - 默认日志目录不可写 / 终端状态文件不可写时显式提示
- **待确认**：3 路以上高频 WiFi 日志压测；现场观察高频滚动下按钮是否持续可点
- **兼容性约束**：原始终端文件由后台串口线程完整写入磁盘；屏幕缓冲超过 64 KiB 仅合并展示
- **回归检查点**：`tests/test_serial_terminal.py` 8 项；现场监控下手动验证 Enter 触发发送

## 5. 串口传输核心

- **已实现但未确认验收**：
  - pySerial 独占会话、单读线程、状态 marker、`peek_since` 调试接口
- **兼容性约束**：串口→VLAN 映射硬编码，未配置化
- **回归检查点**：`tests/test_serial_transport.py`

## 6. 全包升级 - `Tftp指令`（设备拉取固件）

- **已确认验收**：
  - 多台样机串行真实样机（2026-07-11）
  - 两台受控并行真实样机（2026-07-12）
  - `ARP Retry count exceeded` 自动重试 3 次（2026-07-12 + 2026-07-13 三项现场验收合并记录）
  - **串口乱码盲发密码补救登录（`peek_since` salvage 路径）** — 用户已确认真实样机验收通过
- **已实现但未确认验收**：
  - 并行上限扩展到 8 台、Spinbox 调整
  - 高频 `Tftp指令` 日志不再阻塞 Tk 主线程
- **待确认**：4 台、8 台独立 VLAN/COM 真实样机端到端（含程控电源长连接复用、日志仅有一次 `已打开 / 已关闭程控电源串口`）
- **兼容性约束**：必须严格绑定当前 VLAN IP（监听 socket 与 RRQ 数据 socket），禁止回退 `0.0.0.0`；固件映射为 `tclinux_allinone`；不开外部 CRT/Tftpd 进程
- **回归检查点**：`tests/test_serial_upgrade_service.py`、`tests/test_tftp_transport.py`、`tests/test_serial_transport.py`；高并发时 `manual_writable` 仅在控制器释放后切回

## 7. 全包升级 - `Tftp Put`（主机推固件）

- **已确认验收**：
  - 多台串行真实样机（2026-07-12）
  - 两台受控并行真实样机（2026-07-12）
- **已实现但未确认验收**：
  - 开始前对程控电源下电 + 上电（与 `Tftp指令` 复用 `_power_cycle_current_channel`）
  - 检测 `UserName:` 后按 boot 凭据登录；`Password:` 同批覆盖由 `cursor` 前移修复
  - 上传失败/超时不影响后续 batch
- **待确认**：4 台、8 台并行真实样机；`Tftp Put` 现场回显差异（如 `ECNT>` 大小写）下的最终登录时序
- **兼容性约束**：客户端必须绑当前通道 VLAN IP；远端固定 `192.168.1.1:69`；**不与 `Tftp指令` 合并**
- **回归检查点**：`tests/test_serial_upgrade_service.py` 中 `Tftp Put` salvage / 同批 `ECNT>` / `Password:` 测试

## 8. 全包升级 - 通用时序与收尾

- **已确认验收**：
  - 恢复出厂命令实际下发 → 主程序执行日志输出 `TX firstboot -y;reboot`（2026-07-12）
  - **升级结束后关闭自动打开的串口终端，手动打开不受影响** — 用户已确认真实样机验收通过
- **已实现但未确认验收**：
  - `Tftp指令` / `Tftp Put` 升级链路均复用主执行日志的 TX 输出
- **兼容性约束**：保留确认弹窗 + 主执行日志；`finally` 中关闭会话与电源长连接
- **回归检查点**：`tests/test_app.py` 中自动打开/手动打开终端的差异化断言

## 9. 页面升级 - UBUS 批量

- **已实现但未确认验收**：
  - 启用目标 VLAN 网卡 + 切换 PC 到样机管理 IP 网段（`prepare_network_for_sample`）
  - HTTP/HTTPS `ubus` 登录、上传固件、调用 `Device.DeviceInfo.X_SDMC_Upgrade()`
  - 升级状态轮询与重启上线等待
  - `Access denied` 兼容三种 RPC：`bbfdm.operate` / `bbfdm.operate(proto=web)` / `bbfdm.unauthenticated_operate`
  - 升级后 UBUS `Device.FactoryReset()`（`proto=web`）；关闭时输出"恢复出厂：关闭，跳过"
- **待确认**：
  - 真实样机勾选"恢复出厂"时日志依次出现「升级成功 → 重新登录成功 → `TX UBUS Device.FactoryReset()` → 已下发」
  - 未勾选时只出现"恢复出厂：关闭，跳过"
  - `vlan137/138/139` 升级前网卡切换后 HTTP/HTTPS 一次登录成功
- **兼容性约束**：`PageUpgradeRequest.restore_factory` 已落地，但仅在升级成功 + 重启 + 重新登录成功后调用；不提前 `logout` 复用已验证会话
- **回归检查点**：`tests/test_page_upgrade.py`（含 `restore_factory`、`exit` 回退策略）、`tests/test_app.py`（UBUS 调用点上下文）、`tests/test_network_ops.py`

## 10. 批量写样机参数

- **已实现但未确认验收**：
  - 参数表 `VLAN` 列与已勾选通道匹配
  - 传输层已切到 Telnet（仅限写样机参数），按 `ChannelConfig.network_card_ip` 强绑定 PC 源 IP；多张同网段网卡不会命中错误样机
  - 前置阶段通过本机自写的 UBUS HTTP 客户端（不复用 `SdmcUbusLib`）按 `SdmcUbusLibEnableTelnet.Enable_telnet` 同协议打开 `Device.Firewall.<X_SDMC_>Security.AccessCtrl` 的 LAN-telnet 规则（含 Device.IP.Interface.1 → lan 回退）
  - 业务时序：`ppctl clear → FACTORY_MODE=1 → firstboot -yr → 等待 100s → 二次登录 → set/get → FACTORY_MODE=0 → firstboot -yr`；并行 1-8 台（默认 2）
  - 取消时停止后续命令并尝试退出工厂模式
- **待确认**：
  - 2 / 4 / 8 台独立 VLAN 真实样机验收（VLAN/MAC 对应、`set/get` 读回校验、取消清理、退出工厂模式后的重启、日志脱敏、UBUS 启用 telnet 与 telnet 登录衔接时序）
  - 现场首次确认 UBUS 启用 telnet 总开关、规则 enable 三段日志
- **兼容性约束**：
  - 参数值不允许双引号/回车/换行；密码类字段在终端与日志脱敏
  - 源 IP 不可绑时强提示人工检查 `network_card_ip.ini`，不回退 `0.0.0.0`
  - 串口路径保留作 transport 配置回退入口；所有其他功能（页面升级 / 全包升级 / 串口终端）继续走原有路径，不受本节改动影响
- **回归检查点**：`tests/test_sample_parameter_service.py`（4 项既有断言）、`tests/test_telnet_transport.py`（6 项）、`tests/test_ubus_http_client.py`（9 项）、`tests/test_sample_parameter_table.py`、`tests/test_sample_parameter_app.py`

## 11. 随机参数表生成

- **已实现但未确认验收**：按已勾选 VLAN 生成 `.xlsx` 表，导出后自动加载并预检（不自动下设备）；MAC/SN/SSID 唯一；密码类字段明文显示
- **待确认**：生成后与第 10 节"批量写样机参数"联动真实样机验收
- **兼容性约束**：导入兼容旧表共用 `WiFi Password` / `Country code` 列
- **回归检查点**：`tests/test_sample_parameter_table.py`

## 12. ONU 注册（ZTE OLT）

- **已实现但未确认验收**：
  - 未注册 ONU 复选列表 + 全选/取消全选
  - SD-41 模板下发（`interface gpon-olt`、`gpon-onu`、业务 VLAN、`pon-onu-mng`）
  - 新增业务配置失败时改用"删除已注册但不在线 ONU → `registration-method sn 新SN`"复用旧 ONU
  - 注册完成后询问保存 OLT 配置（先退出 `ZXAN(config)#`/`config-if`，再 `write`）
- **待确认**：现场 OLT `Access denied`、新增配置失败、删除/重注册三类实际表现与提示文案
- **兼容性约束**：注册不会自动保存 OLT 配置；窗口默认尺寸 `896x580`；本机凭据不入 Git
- **回归检查点**：`tests/test_network_ops.py`（含离线 ONU 优先同 PON 删除）、`tests/test_app.py`（ONU 注册 UI）

## 13. 输入持久化与窗口几何

- **已实现但未确认验收**：
  - `Auto_power_on_off_tool/config/sample_upgrade_settings.ini` 保存升级方式、固件路径、恢复出厂、超级凭据、并行数等
  - `Auto_power_on_off_tool/config/onu_registration.ini` 保存 OLT IP/用户名/密码
  - `~/.aouxue_serial_terminal.json` 保存串口终端窗口位置 + 日志目录
- **兼容性约束**：本机配置文件不入 Git；修复了 `%` 触发 `ConfigParser` 内插崩溃
- **回归检查点**：`tests/test_sample_upgrade_settings_store.py`、`tests/test_onu_registration_store.py`

## 14. 启动 / 调试环境

- **已实现但未确认验收**：VS Code `.vscode/launch.json` 中 `LineCheckAssistant` 入口以 `Cheating_machine_execution_tool` 为工作目录；`.venv_serial_upgrade` 配套 `tftpy==0.8.7`
- **兼容性约束**：开发使用 `.venv_serial_upgrade`，不污染全局或 `.venv`
- **回归检查点**：手动以 F5 启动主程序并能选择 `.venv_serial_upgrade` 解释器

## 15. 打包与第三方

- **已实现但未确认验收**：`build_line_check_assistant.ps1` 生成 `dist\LineCheckAssistant.exe`；`.spec` 落 `line_check_assistant/packaging_specs`
- **兼容性约束**：不要在当前 PC 运行最新生成的 EXE，仅确认打包成功并报告路径
- **回归检查点**：打包脚本非交互式检查；`.spec` 文件存在

## 16. 已知兼容性 / 现场限制

- 仅支持 Windows 10/11；写网卡静态 IP 需管理员
- 串口→VLAN 映射硬编码，未配置化
- 批量写参字段禁止双引号/回车/换行
- 自动升级占用的 Tab 手动发送（含 Enter）被锁定
- 真实异常（新型号 / 登录异常 / 网络）应保留日志并扩展对应分支，不应预先改变已验收时序
- 底层两个 TFTP 链路严禁合并为同一传输流程

## 17. 最小可信回归基线（无真实样机时的最低门槛）

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m py_compile line_check_assistant\app.py src\ui\serial_terminal.py src\services\serial_upgrade_service.py src\services\sample_parameter_service.py src\core\tftp_transport.py src\core\telnet_transport.py src\core\ubus_http_client.py src\core\ubus_enable_telnet.py src\core\bind_socket.py src\core\parameter_session.py
python -m unittest discover -s tests -v
```

- 预期：`Ran 199 tests ... OK`（基线 184 + telnet 6 + ubus_http_client 9）
- 协议不变性自检（应全部命中）：
  - `bbfdm.operate`（页面升级 UBUS）
  - `0.0.0.0` 不应出现在并行 TFTP 监听 / 数据 socket 路径
  - `tclinux_allinone`（Tftp指令 文件名映射）
  - `192.168.1.1`（Tftp Put 远端固定）
  - `vlan{N} -> COM{N-100}` 映射公式（`vlan_to_serial_port`）
  - `MAX_PARALLEL_UPGRADES = 8`、`clamp_parallel_count`
  - `source_address=(bind_ip, 0)` 应出现在 `TelnetSession`、`UbusHttpClient` 构造路径
  - `Device.Firewall.<X_SDMC_>Security.AccessCtrl` 协议应出现在 `ubus_enable_telnet`
- 入口自检：可分别打开"页面升级""全包升级（Tftp指令/Tftp Put）""写样机参数（默认走 telnet 路径）""生成批量样机参数表""ONU注册""串口日志记录"窗口
