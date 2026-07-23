# Project Notes

- After rebuilding the latest `dist\LineCheckAssistant.exe`, do not run it on the current PC. Only verify that packaging completed successfully and report the output path to the user.

## 仓库边界

- 仓库根目录：`F:\Aouxue\Power_OnOff_Assistant`；主源码与运行目录：`Cheating_machine_execution_tool`。
- 根目录 `README.md` 是人和 AI 的导航入口；操作员说明固定为 `Cheating_machine_execution_tool/line_check_assistant_README.md`，不要臆造其它 README 路径。
- 本文件中的相对 `src/`、`tests/`、`scripts/` 路径均以主源码目录为准；从仓库根执行命令前必须先 `cd Cheating_machine_execution_tool`。

## 项目背景

这是一个 Windows 桌面应用，用于辅助光猫/路由器测试工程师完成测试环境搭建、设备连通性检查、样机升级、串口日志查看、Ping 检测等工作。

主要用户是网络通信产品软件测试工程师，要求界面简单、操作稳定、日志清晰。

## 技术选型原则

本项目暂不固定具体技术栈。

1. 目标平台：Windows 10/11
2. 交付形式：普通用户可双击运行的桌面应用
3. 主要功能：设备连通性检测、Ping、SSH、Telnet、串口、样机升级、日志查看、测试结果导出
4. 用户特点：非专业开发人员也要能使用
5. 开发要求：易维护、易打包、易调试、适合后续接入 AI Agent
6. 优先考虑：稳定性、开发效率、打包便利性、生态成熟度

在没有得到用户确认前，不要直接创建大规模代码。

## 目录规则

- `Cheating_machine_execution_tool/src/ui`：只放界面代码
- `Cheating_machine_execution_tool/src/core`：放 ping、ssh、telnet、串口、升级等底层能力
- `Cheating_machine_execution_tool/src/services`：放完整业务流程编排
- `Cheating_machine_execution_tool/src/models`：放数据结构
- `Cheating_machine_execution_tool/src/utils`：放工具函数
- `Cheating_machine_execution_tool/Auto_power_on_off_tool/config`：当前程序使用的本机配置文件
- `Cheating_machine_execution_tool/logs`：运行日志，不提交 Git
- `Cheating_machine_execution_tool/tests`：测试代码
- `Cheating_machine_execution_tool/scripts`：运行和打包脚本

## 开发规则

1. 不要把业务逻辑直接写在 UI 文件里。
2. UI 只负责显示、输入和调用 service。
3. 单个底层能力放到 core。
4. 多步骤流程放到 services。
5. **新增功能 / Bug 修复若影响已验收功能边界 / 真实样机验收 → 必须同步更新对应文档。** `PROJECT_STATUS.md` 只写当前状态与交接入口；`ACCEPTANCE_BASELINE.md` 只写不变量和验收结论；用户可见行为写入 `Cheating_machine_execution_tool/line_check_assistant_README.md`。详细同步矩阵见 `.claude/skills/line-check-dev/SKILL.md §3`。
6. 修改代码后，必须说明改了哪些文件。
7. 修改代码后，必须给出验证方法。
8. 不要改动 `build`、`dist`、`logs`、`.venv` 目录。
9. 不要随意删除已有功能。
10. 涉及设备登录、升级、重启等危险操作时，必须加确认提示和日志记录。
11. 每次完成的功能、优化、修改、BUG 修复、文档、构建或测试调整，都必须追加记录到 `DEVELOPMENT_LOG.md`；如果影响项目概览或后续入口，同步更新 `PROJECT_STATUS.md`；**真实样机验收或破坏 / 补全验收状态时，同步更新 `ACCEPTANCE_BASELINE.md §2.x 状态标签与 §3 待确认清单**。实施者负责本轮同步，真实样机结论只能依据项目负责人提供的现场结果。
12. 每个新增功能点都必须在主程序执行日志输出关键阶段、实际命令下发、成功、跳过或失败提示，便于操作员核对真实执行结果。
13. **提交代码前必须在主源码目录运行 `python scripts/verify_baseline.py` 且全部通过** —— 这是拦截破坏已验收功能（`ACCEPTANCE_BASELINE §0 / §1.3 / §1.4`）的最低门禁。脚本封装 4 类检查：① 全量 py_compile ② 全量 unittest（解析 `Ran N tests`）③ §1.3 必须命中不变量 grep ④ §1.3 / §1.4 必须不出现模式 grep。任一失败 exit 1，不可绕开。
14. 详细工作流（改动分类 → 文档同步矩阵、真实样机验收流程、完成一次改动标准动作清单）见 `.claude/skills/line-check-dev/SKILL.md`。

## 验收不变量（来自 `ACCEPTANCE_BASELINE.md §1.3 / §1.4`，不可破坏）

> **本章节是 `scripts/verify_baseline.py` 中 `MUST_EXIST` / `MUST_NOT_EXIST` 的可读副本**。改这里必须同步改脚本里的清单；改脚本里的清单也必须同步改这里。

### 必须命中（grep 必须找到）

| 字符串 | 含义 | 搜索范围 |
| --- | --- | --- |
| `bbfdm.operate` | 页面升级 UBUS 调用形式 | `Cheating_machine_execution_tool/src/` |
| `tclinux_allinone` | `Tftp指令` 文件名映射 | `Cheating_machine_execution_tool/src/` |
| `192.168.1.1` | `Tftp Put` 远端固定 | `Cheating_machine_execution_tool/src/` |
| `vlan_to_serial_port` | `vlan{N} -> COM{N-100}` 映射 | `Cheating_machine_execution_tool/src/`、`line_check_assistant/` |
| `MAX_PARALLEL_UPGRADES = 8` | 并行上限 | `Cheating_machine_execution_tool/src/` |
| `clamp_parallel_count` | 并行数钳制 | `Cheating_machine_execution_tool/src/`、`line_check_assistant/` |
| `source_address=(bind_ip, 0)` | 锁源 IP（TelnetSession / UbusHttpClient 构造路径） | `Cheating_machine_execution_tool/src/`、`line_check_assistant/` |
| `Device.Firewall.<X_SDMC_>Security.AccessCtrl` | UBUS 启用 telnet 协议 | `Cheating_machine_execution_tool/src/` |

### 必须不出现（grep 必须找不到）

| 字符串 | 含义 | 限制范围 |
| --- | --- | --- |
| `0.0.0.0` | 严禁在并行 TFTP 监听 / 数据 socket 路径回退 INADDR_ANY | `Cheating_machine_execution_tool/src/core/tftp_transport.py`, `Cheating_machine_execution_tool/src/core/telnet_transport.py` |
