# 项目交接状态

更新：2026-07-13

## 项目目标与当前实现进度

`LineCheckAssistant` 是 Windows Tkinter 桌面工具，用于配置测试通道、自动上/下电、线路 Ping、串口日志、样机升级、批量写样机参数和 OLT ONU 注册。

| 能力 | 当前状态 |
| --- | --- |
| 通道/网卡配置、线路 Ping、内置多 VLAN 串口终端 | 已完成 |
| 程控电源直连（COM101–COM116） | 已真实样机验收 |
| 页面升级（UBUS 批量 + 可选恢复出厂） | 升级已完成；恢复出厂待真实样机验收 |
| 全包升级 `Tftp指令`、`Tftp Put`（串行/并行 1–8 台） | 已真实样机验收 |
| `Tftp指令` ARP Retry count exceeded 自动重试 3 次 | 已真实样机验收 |
| 批量写样机参数（VLAN 表匹配、并行、set/get 校验） | 代码与单元测试通过，待真实样机验收 |
| 随机批量参数表生成（`.xlsx`） | 单元测试通过 |
| ZTE OLT ONU 查询、注册、离线 ONU 清理重试 | 已完成 |
| 单元测试 | 182 项通过（2026-07-13） |

## 关键文件及其作用

- `Cheating_machine_execution_tool/run_line_check_assistant.py`：源码启动入口。
- `Cheating_machine_execution_tool/line_check_assistant/app.py`：Tk 主界面、各功能窗口、后台 worker 与主执行日志。
- `Cheating_machine_execution_tool/src/core/serial_transport.py`：串口独占会话、单读线程、固定 `vlan{N} -> COM{N-100}` 映射。
- `Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`：全包升级、boot 登录、ARP 重试、并行调度、程控电源协调。
- `Cheating_machine_execution_tool/src/core/tftp_transport.py`：TFTPy Server/Client；并行设备拉取时严格绑定 VLAN IP。
- `Cheating_machine_execution_tool/src/services/sample_parameter_service.py`：批量写参预检、工厂模式流程、`set/get` 校验、取消清理与并行调度。
- `Cheating_machine_execution_tool/src/core/sample_parameter_table.py`：Excel/CSV/XLS 参数表读取、规范 `.xlsx` 导出、随机参数生成。
- `Cheating_machine_execution_tool/src/models/sample_parameter_models.py`：15 项标准写参字段、记录、请求和结果模型。
- `Cheating_machine_execution_tool/src/ui/serial_terminal.py`：多 VLAN 终端与高频日志节流渲染。
- `Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`：UBUS 页面升级与升级后恢复出厂。
- `Cheating_machine_execution_tool/tests/`：单元测试；`line_check_assistant_README.md`：操作说明。

## 已完成、待完成和当前问题

**已完成**：

- 主程序全包升级使用内置 pySerial、TFTPy 和程控电源，不依赖 SecureCRT、Tftpd64 或旧工具 GUI。
- `Tftp指令` 是样机从本机 TFTPy Server 拉取固件；`Tftp Put` 是本机 TFTPy Client 向样机 `192.168.1.1:69` 推送固件，两条链路均已真实验收。
- 并行升级最大 8 台、默认 2 台；同 COM 程控电源批次内复用长连接，串口终端仅重绘当前 Tab，避免高频日志卡死 UI。
- 批量写参可按参数表 `VLAN` 匹配已勾选通道，预检重复/缺失 VLAN、重复 COM、MAC 和危险字符；写入前二次确认，标准流程为 `ppctl clear → FACTORY_MODE=1 → firstboot -yr → 等待 100 秒 → 二次登录 → set/get → FACTORY_MODE=0 → firstboot -yr`。随机生成表只导出/加载预检，不自动下发。

**待完成**：

- 真实样机验收页面升级“恢复出厂”。
- 真实 2/4/8 台独立 VLAN/COM 验收批量写参：确认 VLAN/MAC 对应、读回校验、取消后的工厂模式清理与重启、日志脱敏。

**当前问题/限制**：

- 仅支持 Windows；设置网卡 IP 需要管理员权限。
- 串口映射固定为 `vlan{N} -> COM{N-100}`，未配置化；批量写参参数值不允许双引号、回车或换行。
- 新增的写参密码输入框和随机参数表生成窗口均按操作员要求明文显示；下发记录、串口终端和文件日志仍脱敏。
- 现场若出现新型号、登录异常或网络异常，应先保留日志并扩展对应分支，不预先改变已验收时序。

## 重要技术决策与限制

- 严格保持 `Tftp指令` 与 `Tftp Put` 分离，禁止合并为同一传输流程。
- 并行 `Tftp指令` 的监听 socket 和 RRQ 数据 socket 都必须绑定当前 VLAN IP，不能回退 `0.0.0.0`；`Tftp Put` 不启动本地 TFTP Server。
- 升级、重启、恢复出厂、批量写参均必须保留确认提示和主执行日志；新增功能必须记录关键阶段、实际命令、成功、跳过或失败。
- 页面升级恢复出厂只能发生在升级成功、设备重启且独立 UBUS session 重新登录成功之后。
- 保持分层：`src/ui` 只放界面，`src/core` 放底层能力，`src/services` 放流程编排，`src/models` 放数据结构。
- 不修改 `build/`、`dist/`、`logs/`、`.venv/`；开始新工作前先保留现有工作区改动，默认不自动提交 Git。

## 运行、测试和继续开发的方法

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m pip install -r .\requirements.txt
python .\run_line_check_assistant.py
python -m py_compile line_check_assistant\app.py src\services\serial_upgrade_service.py src\services\sample_parameter_service.py
python -m unittest discover -s tests -v
```

- 当前全量测试预期：`Ran 182 tests ... OK`。
- VS Code 使用 `.vscode/launch.json` 的 `LineCheckAssistant`，工作目录为 `Cheating_machine_execution_tool`。
- 打包：`powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1`；构建后不要在当前 PC 运行 `dist\LineCheckAssistant.exe`，仅确认构建成功并报告路径。
- 每次代码、测试或文档改动后追加 `DEVELOPMENT_LOG.md`；影响本文件结论时同步更新本文件。
