# 项目交接状态

更新：2026-07-24（通道 / 网卡 / Ping 与程控电源全部当前场景已真实样机验收）。

## 项目目标与当前状态

`LineCheckAssistant` 是 Windows Tkinter 桌面工具，用于测试环境线路检查、程控电源、串口日志、样机升级、批量写样机参数、ONU 注册和测试项执行。

| 能力 | 当前状态 |
| --- | --- |
| 通道 / 网卡配置、线路 Ping、内置多 VLAN 串口终端 | 通道 / 网卡配置、线路 Ping、COM 分组筛选和空 COM 全网卡展示均已真实样机验收；串口 Enter 发送已真实样机验收，其余终端高频场景仍按验收基线跟踪 |
| 程控电源直连（COM101–COM116） | 自动上/下电、同批次 COM 长连接复用、1–8 台并行、空 COM 手动重启确认后继续且不下发电源指令均已真实样机验收 |
| 全包升级 `Tftp指令`、`Tftp Put` | 两条独立链路均已真实样机验收；4 / 8 台并行仍可按现场需要补验收 |
| 页面升级（UBUS 批量 + 可选恢复出厂） | 升级已实现；勾选恢复出厂的真实样机验收待完成 |
| 批量写样机参数、随机参数表 | 1 台与 6 台独立 VLAN telnet 路径已真实样机验收；2 / 8 台端点并行待现场需要时补验收 |
| ZTE OLT ONU 注册 | 已实现未验收，需覆盖现场 Access denied、删除离线 ONU、重注册场景 |
| 测试项配置编辑器 | 已完成；Windows 桌面真实交互仍待确认 |
| 全流程执行管道 | 已实现未验收：7 子任务按 1→7 串行，自动上/下电在前、环境线路检查为第 2 个致命步骤；待桌面交互和真实样机全流程验证 |

- 最近一次**已记录**的完整回归：2026-07-24，`python scripts/verify_baseline.py` 全绿，记录为 412 项单元测试。该数字是历史验证记录；下一次代码改动后必须以新实跑结果更新本文件和开发日志。
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
- `Cheating_machine_execution_tool/scripts/verify_baseline.py`：提交前最低回归门禁。

## 当前待办与限制

- 真实样机：页面升级恢复出厂、ONU 注册异常路径、全流程执行 7 子任务端到端。
- 并行边界：全包升级与写参的 4 / 8 台场景按现场需求补验收，不因单元测试自动升级验收状态。
- 仅支持 Windows 10/11；设置网卡静态 IP 需管理员权限。
- 严格区分 `Tftp指令`（样机从本机 TFTPy Server 拉取）与 `Tftp Put`（本机 TFTPy Client 推送到 `192.168.1.1:69`）。
- 多网卡路径必须锁定 VLAN 源 IP；TFTP / Telnet 不得回退 `0.0.0.0`。
- 旧工具、历史升级原型和协议参考目录默认不改，除非先确认主程序依赖关系。

## 运行、验证与交接规则

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m pip install -r .\requirements.txt
python .\run_line_check_assistant.py
python scripts\verify_baseline.py
```

- 业务代码改动：实施者必须运行回归门禁、追加 `DEVELOPMENT_LOG.md`，并按 `AGENTS.md` 同步状态、验收或操作说明。
- 真实样机通过：只有项目负责人提供现场结果后，才能更新 `ACCEPTANCE_BASELINE.md` 状态标签。
- 文档或构建调整：追加开发日志；只有影响当前入口、待办或运行命令时才更新本文件。
- 不提交本机配置、日志、测试结果、`build/`、`dist/` 或 `.claude/settings.local.json`。
