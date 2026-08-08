# 全流程第 8 子任务：执行开关机测试

## 目标

- 全流程新增默认不勾选的 `8. 执行开关机测试`。
- 勾选后执行旧工具 `Start All` 对应的开关机测试业务，但不创建、不显示 PyQt GUI，也不启动旧 EXE。
- 旧工具原 `Logs` 的普通、警告、错误信号实时转发到新工具主执行日志。

## 实现边界

1. `src/services/legacy_power_test_service.py` 负责配置预检、独立子进程、旧业务类调用、日志协议、完成/失败和停止清理。
2. 独立子进程只导入旧工具 `test_case` / `common` / `clients` 业务模块；禁止 import 或实例化 `Auto_Power_On_Off_Tool.UiCase`，避免 GUI 和 Tk/Qt 事件循环混用。
3. 配置继续复用 `Auto_power_on_off_tool/config/config.ini`、`test_project_config.ini`、`network_card_ip.ini`；通道范围以新工具当前已勾选通道为准。
4. 子任务 8 为致命同步子任务：所有通道完成才算成功；任一通道失败则全流程失败。用户点击“停止”时先请求旧业务停止，超时后只终止本次专用子进程。
5. 保留旧逻辑的上/下电、启动等待、循环次数、Telnet/SSH、指令执行、WiFi、邮件/钉钉等既有行为；主执行日志不转发可能包含密码的旧内部 logger，只转发原 GUI `show_signal*` 内容和新适配层阶段日志。

## 验证

- service：配置解析、消息转发、成功/失败、停止、禁止 GUI 主入口。
- orchestrator：8 项状态/顺序、子任务 8 调 service、失败传播。
- window：8 行布局、默认不勾选、确认顺序。
- `python scripts/verify_baseline.py` 全绿。
- 真实样机：确认无旧 GUI/EXE，主日志实时出现旧 Logs，所有已勾选通道完成/失败状态准确。
