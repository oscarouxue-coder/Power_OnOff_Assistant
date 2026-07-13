# 项目交接状态

更新：2026-07-12

## 项目目标与当前进度

`LineCheckAssistant` 是面向光猫 / 路由器测试的 Windows 桌面工具（Python + Tkinter），提供通道与网卡配置、程控电源、线路 Ping、串口日志、样机升级、OLT ONU 注册。运行平台仅限 Windows。

| 能力 | 状态 |
| --- | --- |
| Tkinter 主界面、配置持久化、线路 Ping、内置串口终端 | 已完成 |
| 程控电源直连（COM101–COM116） | 已真实样机验收 |
| 页面升级（UBUS 批量） | 已完成 |
| 全包升级 `Tftp指令` 串行 / 并行（1–8 台，UI Spinbox） | 已真实样机验收 |
| 全包升级 `Tftp Put` 串行 / 并行（1–8 台，UI Spinbox） | 已真实样机验收 |
| `Tftp指令` ARP Retry count exceeded 自动重试 3 次 | 单元测试通过，待真实样机验收 |
| ZTE OLT ONU 查询、注册、离线 ONU 清理重试 | 已完成 |
| 单元测试 | 169 项通过（2026-07-12） |

## 关键文件

- `Cheating_machine_execution_tool/run_line_check_assistant.py`：源码启动入口。
- `Cheating_machine_execution_tool/line_check_assistant/app.py`：Tk UI、升级入口、后台 worker、状态展示；只调度不实现协议。
- `Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`：升级参数（执行方式、并行数 1–8、固件路径、超级账号、恢复出厂等）持久化到 `Auto_power_on_off_tool/config/sample_upgrade_settings.ini`。
- `Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`page_upgrade.py`、`onu_registration_store.py`、`config_store.py`、`serial_ports.py`、`paths.py`：网卡静态 IP、OLT 操作、UBUS 页面升级、配置存储、串口枚举、路径常量。
- `Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`：全包升级编排；包含 `SerialUpgradeController`（boot 登录、`send_tftp_command_and_wait` 含 ARP 自动重试、`monitor_post_tftp`、`interrupt_boot_with_enter` 等）、`UpgradePowerCycleCoordinator`（同 COM 长连接复用）、`run_single_full_package_upgrade` / `run_parallel_tftp_command_upgrades` / `run_parallel_tftp_put_upgrades`。
- `Cheating_machine_execution_tool/src/core/serial_transport.py`：串口独占会话、单读线程、`vlan_to_serial_port`（固定 `vlan{N} -> COM{N-100}`）、`peek_since` 文本回查、`wait_for_any` / `wait_for_all`、文件日志。
- `Cheating_machine_execution_tool/src/core/tftp_transport.py`：TFTPy Server（严格 VLAN IP 绑定监听与数据 socket）与 Client（上传到 `192.168.1.1:69`）。
- `Cheating_machine_execution_tool/src/core/power_supply.py`：16 通道程控电源协议帧；除非有明确协议验证，禁止修改。
- `Cheating_machine_execution_tool/src/services/power_on_service.py`：分通道自动上下电。
- `Cheating_machine_execution_tool/src/ui/serial_terminal.py`：多 VLAN 串口终端；按 VLAN 分批渲染高频输出，升级自动打开的终端在批次结束后关闭。
- `Cheating_machine_execution_tool/src/models/serial_models.py`：`SerialSettings` / `SerialEvent` / `FullPackageUpgradeRequest`。
- `Cheating_machine_execution_tool/tests/`：单元测试。`line_check_assistant_README.md` 为操作说明。
- `Auto_power_on_off_tool/config/`：运行配置目录；本机凭据与状态文件不提交 Git。
- `DEVELOPMENT_LOG.md`：每次改动的详细记录（背景 / 内容 / 文件 / 验证）。

## 已完成、待完成与当前问题

**已完成**：

- 升级全程使用内置 pySerial、TFTPy、程控电源，不依赖 SecureCRT、Tftpd64 或旧工具 GUI。
- `Tftp指令`（样机拉固件）与 `Tftp Put`（本机 TFTPy Client 推送到样机 `192.168.1.1:69`）两条独立链路，分别有 `TftpServerHandle` / `upload_firmware`。
- `Tftp Put`：前置下电 + 上电 → 等待 1 秒 → 循环回车识别 `UserName:` → 按 `telecomadmin / nE7jA%5m` 登录 boot → TFTPy 推送；已处理 `Password:` / `ECNT>` 与用户名/密码回显同批到达的游标竞态。
- 两种全包升级均支持串行 / 并行（Spinbox 1–8，默认 2，存 ini）；并行完成即补位，单台失败不取消其他样机。`UpgradePowerCycleCoordinator` 持有同 COM 的长连接 `ProgrammablePowerSupply`，批次内 `with` 收尾统一 `close()`。
- `Tftp指令` 链路在样机串口同时出现 `ARP Retry count exceeded` 与 `u-boot>` 提示符时自动重发同一 `tftp` 命令：单次窗口 5 分钟按秒轮询，命中 ARP 模式即 sleep 1 秒后重发，最多 3 次；每次重试与最终成功 / 失败同步写入主程序执行日志。仅 `ARP Retry count exceeded` 但未回到 `U-Boot>`（样机仍卡在 Loading）按普通超时处理，不重试。`Tftp Put` 不涉及。
- boot 登录增加 salvage 分支：用户名回显含 UTF-8 替换符 `�` 时盲发一次密码，命中 shell 提示符（`#` / `>` / `ecnt>` / `u-boot>`）即视为登录成功；`Tftp指令` 与 `Tftp Put` 两条链路对称实现，已真实样机验收。
- 串口终端与主执行日志按 VLAN 分批渲染高频输出，避免 Tk 卡死；原始串口日志仍写入 `D:\Serial_Log`（`DEFAULT_LOG_DIR`）。
- 升级、重启、恢复出厂保留确认弹窗与执行日志；仅实际发出 `firstboot -y;reboot` 时记录 `TX firstboot -y;reboot`。
- 全包升级自动打开的串口终端在批次完成并释放会话后自动关闭；手动打开的终端不受影响。

**待完成**：

- `Tftp指令` ARP 失败自动重试 3 次的真实样机验收（需现场复现：故意断 TFTPy Server 网络，确认主程序执行日志出现「检测到 ARP Retry count exceeded, 剩余 X 次自动重试」「自动重试 TFTP 命令：第 X/3 次发送...」，并最终命中 `done + write` 或返回 `TFTP 命令已重试 3 次仍未成功...`）。
- 真实 2 台 / 4 台 / 8 台独立 VLAN / COM 样机分别跑一次 `Tftp指令` 与 `Tftp Put` 并行，确认日志中"已打开 / 已关闭程控电源串口"各仅出现一次且 TFTPy 上传无错包。
- 如实验室功率闸容量紧张，再评估在 `UpgradePowerCycleCoordinator` 内加错峰 `power_cycle_offset_seconds` 开关（默认 0）。
- 真实两台独立 VLAN 样机复测并行 `Tftp指令` 高频启动日志下串口终端持续可响应。
- 如有新型号或异常现场日志，再扩展超时、掉线、登录失败与型号差异处理；不要预先改变已验收时序。

**当前限制**：

- 仅支持 Windows；设置网卡 IP 需要管理员权限。
- `vlan_to_serial_port()` 为固定映射 `vlan{N} -> COM{N-100}`，未提供配置化映射；需保证实际 COM 与 VLAN 对应。
- 并行上限固定为 8 台（`MAX_PARALLEL_UPGRADES = 8`），由 UI Spinbox 与 `clamp_parallel_count` 在 1–8 区间限制。
- TFTPy 严格 VLAN IP 绑定遇到 `WSAEADDRNOTAVAIL`（10049）时仍按 `allow_any_fallback` 决定是否回退 `INADDR_ANY`；串行 / `Tftp Put` 默认允许回退，并行 `Tftp指令` (`strict_tftp_bind=True`) 严禁回退。

## 重要技术决策与限制

- 保持 `Tftp指令` 与 `Tftp Put` 分离；后续修复不得将两者合并成同一传输流程。
- `Tftp指令` 并行使用严格 VLAN IP 绑定：TFTPy 监听 socket 与每个会话数据 socket 都必须绑定该 VLAN IP；不可用 `0.0.0.0` 回退掩盖多 VLAN 路由问题。并行 runner 传 `strict_tftp_bind=True`，串行 runner 不传。
- `Tftp Put` 是 TFTPy 客户端，使用每个 VLAN 的 `localip` 作为源地址；不启动本地 TFTP Server。
- 并行时仅共享程控电源 COM 帧受 `UpgradePowerCycleCoordinator` 锁保护；boot 登录、串口、网卡准备、上传、最终登录在各 worker 内并行推进。
- `send_tftp_command_and_wait` 在检测到 `ARP Retry count exceeded` + `u-boot>` 时自动重试 3 次，每次间隔 1 秒；其余超时或仅有 ARP 字样但样机未回到 `U-Boot>` 的场景不重试。该逻辑仅作用于 `Tftp指令`。
- 升级、重启、恢复出厂必须保留确认提示与执行日志；仅实际发出 `firstboot -y;reboot` 时记录 `TX firstboot -y;reboot`。
- 保留目录边界：`src/ui` 仅界面，`src/core` 底层能力，`src/services` 流程编排，`src/models` 数据结构。
- 不修改 `build/`、`dist/`、`logs/`、`.venv/`；不自动提交 Git。开始新工作前先检查并保留已有工作区改动。
- 改完代码默认不自动 commit，等用户说"提交"再执行。

## 运行、测试与继续开发

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m pip install -r .\requirements.txt
python .\run_line_check_assistant.py
python -m py_compile line_check_assistant\app.py src\services\serial_upgrade_service.py
python -m unittest discover -s tests -v
```

- 完整测试当前预期 `Ran 169 tests ... OK`（基线 163 + Tftp指令 ARP 重试新增 6）。
- VS Code 使用 `.vscode/launch.json` 中的 `LineCheckAssistant` 启动项，工作目录应为 `Cheating_machine_execution_tool`。
- 打包命令：`powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1`。打包后不要在当前电脑运行 `dist\LineCheckAssistant.exe`，只确认构建成功并报告路径。
- 每次代码 / 文档 / 测试改动后追加 `DEVELOPMENT_LOG.md`；影响本交接结论（能力、限制、决策、测试数）时同步更新本文件。
- 历史计划与背景：`git log` + `.claude/plans/*.md`（如 `garbled-login-fallback.md` / `parallel-upgrade-to-8.md` / `tftp-arp-retry.md`）。