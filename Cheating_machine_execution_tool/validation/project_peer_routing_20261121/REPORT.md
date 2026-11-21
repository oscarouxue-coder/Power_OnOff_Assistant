# 群机器人按项目路由的源码验证

## 交付行为

每台测试电脑运行一个 Qt 工作台。钉钉或飞书把群 @ 送到其中一台，接收方按成员身份查询可信实例上已授权的项目。项目所有者在交付和业务准入时复核项目、通道与会话权限。来源消息、请求 ID、项目本次开放标识和实例本次启动标识共同限制重放。成员切换项目后仍可用原请求 ID 查本人回执。

实例使用已配置的 VPN 或 WSS 通信。双方先用独立的对端密钥验证身份，再交换目录、成员选择或业务请求。在线查询读取当时的项目状态；后台同步的目录用于掉线判断。正常退出前同步消息去重记录和成员选择。不能核实项目状态时回复待确认，避免重复执行业务。配置、回退和命令示例见[操作员说明](../../line_check_assistant_README.md#qt-源码工作台按项目接收群-)。

## 验证范围

- 两个临时实例使用真实回环 WebSocket、不同实例 ID 和独立 SQLite 数据库。模拟机器人只向 B 送消息；检查 A 与 B 的收件记录、结果、回执归属和重复消息。
- Qt 工作区打开临时项目，原会话进入请求批准模式。版本查询须经操作员决定，使用模拟 DUT 返回版本，结果经原 Job 和回执服务投影。模拟平台和模型均不使用外部服务。
- 离线、项目同进程关闭再打开、消息时间早于本次开放、同名和成员权限变化分别检查。转交成功但回执丢失时保持待确认。并发收到同一条消息只准入一次。
- 真实机器人及两台 Windows 电脑通过局域网 WSS 或 VPN 的联调、真实模型和 DUT 仍待现场验证。现场确认前保留统一网关作为回退入口。本轮交付源码。

## 双机现场验收

两台电脑均使用配置好的项目路由模式，关闭原统一网关。A 打开并授权“甲”和“丙”，B 打开并授权“乙”。钉钉、飞书分别用同一个群机器人完成以下操作。

| 群内操作 | 现场核对 |
| --- | --- |
| 成员一发送 `@机器人 项目 甲 查询通道1版本` | 在接收实例日志查到请求 ID。仅 A 的甲项目出现对应会话和审批，经本机批准后，原群收到甲的结果。 |
| 成员二选择乙，成员一继续追问 | 成员一的追问回到甲，成员二的会话留在乙。成员一显式切换到丙后，其后续消息进入丙。 |
| 关闭甲，群内再次明确指定甲，然后重开甲 | 群内收到一次离线反馈。重开后旧问题没有创建会话或任务，重新发送的新问题可以处理。 |
| 停止 A 的工作台，在 B 继续访问乙 | 乙照常处理。A 正常退出后 B 可回复甲的离线状态，通信故障时按可核实的状态回复。 |

## 验证结果

在主源码目录通过 `scripts/run_tests.py` 运行，91 项相关回归通过，包含接入平台、原统一网关、工作区、本机审批、版本查询和设备任务。另行运行 12 项双实例路由用例全部通过，包含成员切换到另一个项目后，较早的消息才到达的情形。[相关回归输出](focused.txt) · [逐项路由结果](peer-tests.txt)

首轮完整基线有一项模拟设备升级用例失败，断言发现升级引擎调用次数为零。首轮 Qt 原生批次在 100% 缩放遇到模拟网卡被占用，125% 和 150% 通过。设备升级用例已在上述 91 项回归中通过。

最终完整基线 `python scripts/verify_baseline.py` 八类检查全部通过。运行 3,278 项单元测试，268 项指定用例全部命中，385 个文件通过编译。[完整基线输出](baseline.txt)

最终 Windows Qt 原生批次在 100%、125%、150% 下各通过 101 项，共 303 次。每档都实际运行了项目路由状态窗口用例，指定用例缺失数和隔离违规数均为零。[三档结果与原生桌面隔离记录](native-results.json)

复验通过并记录后，首轮及最终批次分别将 420 张临时 PNG 移入回收站，共 840 张。三档文字输出和桌面隔离结果已保留。

## 改动文件

| 范围 | 文件 |
| --- | --- |
| 对端传输与路由 | `src/core/project_peer_transport.py`、`src/services/project_peer_router.py`、`src/services/project_peer_runtime.py` |
| 入口和项目生命周期 | `run_dutpilot_qt.py`、`scripts/run_remote_gateway.py`、`src/services/qt_workspace_adapter.py`、`src/services/workspace_gateway.py`、`src/services/workspace_service.py` |
| 平台、会话和权限 | `src/services/remote_gateway_platforms.py`、`src/services/remote_instance_service.py`、`src/services/remote_instance_management.py`、`src/services/qt_ai_chat.py`、`src/services/ai_conversation_service.py`、`src/services/ai_session_router.py`、`src/services/ai_version_query_service.py` |
| 状态窗口及验证 | `src/ui/qt/instance_status_dialog.py`、`tests/test_project_peer_routing.py`、`tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_baseline.py`、`scripts/verify_qt_migration.py` |
| 使用与交接 | 操作员说明、根目录的项目状态、验收基线、开发记录和本报告 |

