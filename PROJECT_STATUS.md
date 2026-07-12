# 项目交接状态

更新：2026-07-12

## 项目目标与进度

`LineCheckAssistant` 是面向光猫/路由器测试的 Windows 桌面工具，提供通道与网卡配置、程控电源、线路检查、样机升级、串口日志、OLT ONU 注册。

| 能力 | 当前状态 |
| --- | --- |
| Tkinter 主界面、配置持久化、线路 Ping、内置串口终端 | 已完成 |
| 程控电源直连（COM101–COM116） | 已真实样机验收 |
| 页面升级（UBUS 批量） | 已完成 |
| 全包升级 `Tftp指令` 串行 | 已真实样机验收 |
| 全包升级 `Tftp指令` 两台并行 | 代码完成，待真实两台验收 |
| 全包升级 `Tftp Put` 串行 | 已真实多台验收 |
| 全包升级 `Tftp Put` 两台并行 | 代码完成，待真实两台验收 |
| ZTE OLT ONU 查询、注册、离线 ONU 清理重试 | 已完成 |
| 单元测试 | 154 项通过（2026-07-12） |

## 关键文件

- `Cheating_machine_execution_tool/run_line_check_assistant.py`：源码启动入口。
- `Cheating_machine_execution_tool/line_check_assistant/app.py`：Tk UI、升级入口、后台 worker 与状态展示；UI 不承载底层协议实现。
- `Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`：全包升级编排、boot 登录、电源协调、串行与两种并行调度。
- `Cheating_machine_execution_tool/src/core/serial_transport.py`：串口会话独占、单读线程、VLAN 到 COM 映射、文件日志。
- `Cheating_machine_execution_tool/src/core/tftp_transport.py`：TFTPy Client/Server、VLAN IP 绑定和上传。
- `Cheating_machine_execution_tool/src/core/power_supply.py`：16 通道程控电源协议帧；除非有明确协议验证，不修改。
- `Cheating_machine_execution_tool/src/ui/serial_terminal.py`：多 VLAN 串口终端；高频输出分批渲染，自动打开的升级终端在批次结束后关闭。
- `Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`page_upgrade.py`：网卡静态 IP/OLT 操作、UBUS 页面升级。
- `Cheating_machine_execution_tool/tests/`：单元测试；`line_check_assistant_README.md` 为操作说明。
- `Auto_power_on_off_tool/config/`：运行配置目录；本机凭据和状态文件不提交 Git。

## 已完成、待完成与当前问题

已完成：

- 升级全程使用内置 pySerial、TFTPy 和程控电源，不依赖 SecureCRT、Tftpd64 或旧工具 GUI。
- `Tftp指令` 与 `Tftp Put` 是两条独立链路：前者由样机拉取本机 TFTPy Server 文件，后者由本机 TFTPy Client 推送到样机固定地址 `192.168.1.1:69`。
- `Tftp Put`：前置下电/上电，等待 1 秒后循环回车，识别 `UserName:`，按 boot 凭据登录，再上传；已处理同批 `Password:`、`ECNT>` 提示的游标竞态。
- 两种全包升级均可选择串行或最多两台并行；并行完成即补位、单台失败不取消其他样机，共享程控电源 COM 写帧串行化。
- 高频串口/执行日志采用分批渲染，用户已反馈并行 `Tftp指令` 不再导致主界面卡死；原始串口日志仍写入 `D:\Serial_Log`。

待完成：

- 用两台不同 VLAN、不同 COM 的真实样机验收 `Tftp指令` 并行和 `Tftp Put` 并行，重点确认并发传输、电源帧不交叠、失败隔离、终端自动关闭。
- 如有新型号或异常现场日志，再扩展超时、掉线、登录失败与型号差异处理；不要预先改变已验收时序。

当前限制：

- 仅支持 Windows；设置网卡 IP 需要管理员权限。
- `vlan_to_serial_port()` 为固定映射 `vlan{N} -> COM{N-100}`，未提供配置化映射；需保证实际 COM 与 VLAN 对应。
- 并行上限固定为 2 台；不要擅自提升。
- `Tftp Put` 并行仍是代码和单测验证，不能表述为真实样机验收通过。

## 重要技术决策与限制

- 保持 `Tftp指令` 与 `Tftp Put` 分离；后续修复不得将两者合并成同一传输流程。
- `Tftp指令` 并行使用严格 VLAN IP 绑定，TFTPy 的监听 socket 与会话数据 socket 都必须绑定该 VLAN IP；不可用 `0.0.0.0` 回退掩盖多 VLAN 路由问题。
- `Tftp Put` 是 TFTPy 客户端，使用每个 VLAN 的 `localip` 作为源地址；不启动本地 TFTP Server。
- 并行时仅共享程控电源 COM 帧受锁保护；boot、串口、网卡准备、上传、最终登录应在各 worker 内并行推进。
- 升级、重启、恢复出厂必须保留确认提示与执行日志。仅实际发出 `firstboot -y;reboot` 时记录 `TX firstboot -y;reboot`。
- 保留目录边界：`src/ui` 仅界面，`src/core` 底层能力，`src/services` 流程编排，`src/models` 数据结构。
- 不修改 `build/`、`dist/`、`logs/`、`.venv/`；不自动提交 Git。开始新工作前先检查并保留已有工作区改动。

## 运行、测试与继续开发

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m pip install -r .\requirements.txt
python .\run_line_check_assistant.py
python -m py_compile line_check_assistant\app.py src\services\serial_upgrade_service.py
python -m unittest discover -s tests -v
```

- 完整测试当前预期为 `Ran 154 tests ... OK`。
- VS Code 使用 `.vscode/launch.json` 中的 `LineCheckAssistant` 启动项，工作目录应为 `Cheating_machine_execution_tool`。
- 打包命令：`powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1`。打包后不要在当前电脑运行 `dist\LineCheckAssistant.exe`，只确认构建成功并报告路径。
- 每次代码、文档或测试改动后追加 `DEVELOPMENT_LOG.md`；影响本交接结论时同步更新本文件。
