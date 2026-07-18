# 写样机参数：先 UBUS 启用 telnet 再 TCP 连接

## 背景

用户实际运行批量写样机参数时遇到：

```
批量写参失败
成功 0/1 台。
- VLAN115: VLAN115 telnet 写参启动失败: Telnet 连接失败 192.168.1.1:23
  源 IP 192.168.1.115: timed out
```

现场样机确认未开启 telnetd 监听 23 端口，必须先用 UBUS 打开 telnet 服务。代码注释明确写「端到端 telnet 写参:UBUS 启用 telnet → TelnetSession(未登录)」，但 `make_telnet_factory` 当前实现顺序相反：

```python
session = TelnetSession(r.bind_ip, r.device_host, ...)   # 同步阻塞 15s
emit_to_main(f"{r.vlan} 写参前置：UBUS 启用 telnet 中 ({r.device_host})。")
try:
    ubus_client = UbusHttpClient(...)
    enable_result = enable_telnet_via_ubus(ubus_client, ...)
```

`TelnetSession.__init__` 立刻 `socket.create_connection(..., timeout=15.0)` 同步阻塞连 telnet，而 UBUS 启用访问控制规则还没下发。结果是 telnet 端口还没监听，SYN 丢包，15 秒后 `OSError: timed out` 被包装成 `RuntimeError` 抛给上层弹窗。

## 设计原则

- **最小改动**：只调换现有代码块顺序，不引入新常量、不改 `TelnetSession` / `UbusHttpClient` / `ubus_enable_telnet` / 配置文件 / 测试入口。
- 严格保持 `TelnetSession` 异常封装策略不变；UBUS / telnet 锁源语义不变；单元测试 199 项继续通过。
- 不触动 `build/`、`dist/`、`logs/`、`.venv/`；不调整目录结构、配置格式、函数名、依赖版本。
- 修复后主执行日志自然输出「UBUS 启用 telnet 中 → UBUS 三段日志 → Telnet 已连接」，与 `ACCEPTANCE_BASELINE.md` §2.7 期望的"现场首次确认 UBUS 启用 telnet 总开关 + 规则 enable 三段日志"对齐。
- 不修改 `ACCEPTANCE_BASELINE.md` §2.7 状态标签（仍为「已实现未验收」，需真实样机验收才升级）。

## 涉及范围

| 是否动 | 文件 / 模块 |
| --- | --- |
| ✅ 修改 | `Cheating_machine_execution_tool/line_check_assistant/app.py`（仅 `_sample_parameter_write_worker` 内的 `make_telnet_factory`） |
| ✅ 追加 | `DEVELOPMENT_LOG.md`（按既定模板） |
| ❌ 不动 | `src/core/telnet_transport.py` |
| ❌ 不动 | `src/core/ubus_http_client.py` / `src/core/ubus_enable_telnet.py` |
| ❌ 不动 | `src/services/sample_parameter_service.py` / `src/core/parameter_session.py` |
| ❌ 不动 | `tests/` 任何现有文件（fake session 不走 factory，无需新增/调整） |
| ❌ 不动 | `ACCEPTANCE_BASELINE.md` / `PROJECT_STATUS.md` / `line_check_assistant_README.md` |

## 实现方案

### 1. `line_check_assistant/app.py` — `make_telnet_factory`

把原本「先开 Telnet 后 UBUS」改为「先 UBUS 后 Telnet」，并简化清理分支（UBUS 失败时不再需要回头 close 没创建的 TelnetSession）。

伪代码（仅描述意图，保留现有日志、参数与 `known_secrets`）：

```python
def make_telnet_factory(request):
    def factory(r):
        if not r.bind_ip or not r.device_host:
            raise RuntimeError(f"{r.vlan} 切 telnet 路径但 bind_ip / device_host 为空")
        log_path = DEFAULT_LOG_DIR / f"sample_parameter_{r.vlan}_{r.bind_ip}.log"

        emit_to_main(f"{r.vlan} 写参前置：UBUS 启用 telnet 中 ({r.device_host})。")
        ubus_client = UbusHttpClient(r.bind_ip, r.device_host, ubus_port=r.ubus_port)
        try:
            try:
                enable_result = enable_telnet_via_ubus(
                    ubus_client,
                    r.initial_username,
                    r.initial_password,
                    on_log=lambda ev: emit_to_main(f"{r.vlan} UBUS: {ev.message}"),
                    sleep_fn=lambda _seconds: None,
                    sleep_after_seconds=0.0,
                )
            finally:
                ubus_client.close()
        except Exception as exc:
            emit_to_main(f"{r.vlan} 写参前置：UBUS 启用 telnet 失败：{exc}")
            raise

        emit_to_main(f"{r.vlan} UBUS 启用 telnet {enable_result.action}: {enable_result.message}")
        return TelnetSession(
            r.bind_ip,
            r.device_host,
            log_path=log_path,
            known_secrets=(r.initial_password,),
        )
    return factory
```

关键点：
- `TelnetSession(...)` 现在移到最后，构造成功即返回给 `run_single_sample_parameter_write`，让 `run_parameter_write_pipeline` 内部的 `_login` 接力首次登录。
- 失败清理简化：UBUS 失败时 TelnetSession 尚未创建，无需 `try: session.close()` 兜底。
- 关键阶段日志顺序对齐 `ACCEPTANCE_BASELINE.md` §2.7：①UBUS 启用 telnet 中 → ②UBUS 三段流程消息 → ③UBUS 启用 telnet `action`: `message` → ④Telnet `STATE Telnet 已连接`（由 `TelnetSession.__init__` 内部 _emit）。

### 2. `DEVELOPMENT_LOG.md`

按 `[DEVELOPMENT_LOG.md:13-25](DEVELOPMENT_LOG.md#L13-L25)` 模板在顶部追加一条 `## 2026-07-15 - 写样机参数 TCP 连接挪到 UBUS 启用 telnet 之后`：

- **类型**：BUG 修复
- **背景**：用户在 VLAN115（IP 192.168.1.115）写参失败，错误为 `Telnet 连接失败 192.168.1.1:23 源 IP 192.168.1.115: timed out`，原因是 `make_telnet_factory` 先同步建 TCP 连接、后 UBUS 启用 telnet 访问控制规则，与文件顶部注释相反。
- **完成内容**：把 `make_telnet_factory` 调整为 UBUS 启用 telnet（在 `enable_telnet_via_ubus` 内部走总开关 get/set、规则遍历、add 规则、add lan 回退四段）→ 创建 `TelnetSession`；UBUS 失败时无需清理已不存在的 Telnet 连接；其余传输流程不变。
- **修改文件**：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`。
- **验证方法**：`python -m py_compile Cheating_machine_execution_tool/line_check_assistant/app.py`；`python -m unittest discover -s Cheating_machine_execution_tool/tests -v`。
- **验证结果**：py_compile 通过；199 项单测全过。
- **后续待办**：用户真实样机验收：先以 VLAN115 单台验证日志依次出现「写参前置：UBUS 启用 telnet 中 → UBUS 三段消息 → UBUS 启用 telnet added_iface/already_present: ... → Telnet 已连接 → 首次登录 → ppctl clear → 工厂模式 → 15 项 set/get 读回 → 退出工厂模式」；验证通过后再扩展到 2/4/8 台并行。

## 验证

按照 `ACCEPTANCE_BASELINE.md` §0 最小可信回归基线：

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m py_compile line_check_assistant\app.py
python -m unittest discover -s tests -v
```

- 期望：`Ran 199 tests ... OK`（与基线一致，未新增/调整任何测试）。
- 不打包（保持 AGENTS.md 中「构建后不在当前 PC 运行 exe」的规则）。

## 风险与边界

| 风险 | 说明 |
| --- | --- |
| 修改面广 | 仅 `app.py` 内一个内部函数；其余函数行为不变 |
| 并发安全 | UBUS + Telnet 同属一条 factory，单台串行；多台并行通过 `ThreadPoolExecutor` 隔离 |
| 日志刷屏 | UBUS 三段均已逐条 emit，与现状相同 |
| 现有 199 项测试 | fake session 走串口路径，未触达 factory，无回归 |
| 后续真实样机验收 | 状态标签仍为「已实现未验收」，确认 telnet 真机顺序对、读回校验无误后再升 |
