# 统一中兴 C300/C600 ONU 注册

## 目标

- 保留 `run_line_check_assistant.py` 单一启动入口和当前项目 UI 风格。
- 将 ONU 注册重构为统一的查询、预检、预览、确认、逐条下发、验证和可停止流程。
- C300 与 C600 使用完全独立的命令生成器和输出解析器，禁止跨型号复用 CLI 字符串。
- 保留现有 C300 已实现边界；C600 写入仅标记为已实现未验收。

## 分层

- `src/models/onu_registration_models.py`：统一连接、发现结果、注册请求、业务映射及结果模型。
- `src/core/zte_olt_telnet.py`：锁定源 IP 的低层 Telnet 会话、逐条命令执行、CLI 错误检测和取消。
- `src/core/zte_c300_onu.py`：仅包含 C300 命令、解析及型号专属策略。
- `src/core/zte_c600_onu.py`：仅包含 C600 命令、解析及型号专属策略。
- `src/services/onu_registration_service.py`：统一多阶段流程和日志编排，通过型号选择对应驱动。
- `line_check_assistant/app.py`：仅收集输入、危险确认、启动线程和显示结果。

## UI

- 现有“ONU注册”入口不变，窗口顶部增加只读 OLT 型号选择。
- C300 保留全局未注册 ONU 查询与既有 SD-41 业务模板。
- C600 增加源 IP、机框/槽位/PON、ONU ID、型号、速率、T-CONT、GEM、VPort 和 ServiceID/VLAN 映射字段。
- 型号切换时更新字段可用状态与说明，不混用另一型号的命令。
- 所有实际命令、阶段、成功、停止和失败写入主执行日志。

## 安全边界

- Telnet 必须绑定显式源 IP；源 IP 缺失或不可绑定时停止，不回退系统默认网卡。
- 实际下发前必须展示命令摘要并二次确认。
- C600 第一条 CLI 错误立即停止，不自动删除或回滚，不自动执行 `write`。
- C300 离线 ONU 删除重试作为型号专属危险策略处理；具体默认和确认方式按项目负责人本轮答复实施。
- `write` 始终在下发完成后独立询问，不自动执行。

## 验证

- C300/C600 命令生成与解析单测。
- 统一 service 的型号路由、预检、取消、错误停止、验证和日志单测。
- 主窗口型号切换、字段映射、确认和线程分发源码回归。
- `python scripts/verify_baseline.py`、`git diff --check`。
- 自动化通过不代表 C300/C600 真实 OLT 写入验收。
