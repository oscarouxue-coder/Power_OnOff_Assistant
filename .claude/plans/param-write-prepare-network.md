# 写样机参数：开始前启用网卡 + 设置静态 IP

## 背景

用户在多张同网段 VLAN 网卡的环境下跑批量写样机参数：当前 `make_telnet_factory` 仅负责 UBUS 启用 telnet + TelnetSession 创建，没有显式启用对应网卡并把 `channel.network_card_ip` 写入该网卡。

按用户当前在主界面填的"PC 静态 IP"约定（`vlan{N} → 192.168.1.{N}`，由主界面在保存时按 `static_ip_for_vlan(channel.vlan_name, channel.device_manage_ip)` 自动派生并写到 `channel.network_card_ip`），写样机参数开始前应：

1. 启用该通道对应的 VLAN 网卡；
2. 把 `channel.network_card_ip` 设到该网卡上（子网掩码用 `channel.subnet_mask`）；
3. 等待 Windows 把新 IP 注册为可绑地址（避免 `bind_ip` 仍指向旧的或未启用网卡）；
4. 再继续走既有的「UBUS 启用 telnet → TelnetSession → 首次登录 → 工厂模式 → 15 项 set/get → 退出工厂模式」流水线。

100 秒工厂模式网段切换继续由 `make_factory_session_swap` 处理（已就绪），不重复实现。

## 设计原则

- **最小改动**：仅在 `make_telnet_factory` 内增加"启用网卡 + 设置静态 IP + 等可绑"三步；不修改 `SampleParameterWriteRequest`、不修改 `service` 层、不改 `telnet_transport.py` / `ubus_http_client.py` / `ubus_enable_telnet.py`。
- **bind_ip 不变**：继续使用 `channel.network_card_ip`，不引入派生逻辑；用户已经在主界面按 `vlan{N} → 192.168.1.{N}` 约定设置好了。
- **错误隔离**：单台启用/设 IP/等可绑失败 → 该台立即放弃（抛 RuntimeError → worker 捕获并标记 `telnet 写参启动失败`），其它通道继续。
- **关键阶段日志**：保留 `AGENTS.md` 规则 12，emit 主程序执行日志的 `启用网卡 / 设置静态 IP / 等可绑` 三段。
- **不动**：`build/`、`dist/`、`logs/`、`.venv/`；不改 `ACCEPTANCE_BASELINE.md` / `PROJECT_STATUS.md` 状态标签（仍为「已实现未验收」）。
- **不打包**：保持 AGENTS.md 中「构建后不在当前 PC 运行 exe」的规则。

## 涉及范围

| 是否动 | 文件 / 模块 |
| --- | --- |
| ✅ 修改 | `Cheating_machine_execution_tool/line_check_assistant/app.py`（仅 `make_telnet_factory` 内部前置步骤） |
| ✅ 新增 | `Cheating_machine_execution_tool/tests/test_sample_parameter_app.py`（增加 `make_telnet_factory` 前置行为测试） |
| ✅ 追加 | `DEVELOPMENT_LOG.md`（按既定模板） |
| ❌ 不动 | `src/core/telnet_transport.py` / `src/core/ubus_http_client.py` / `src/core/ubus_enable_telnet.py` |
| ❌ 不动 | `src/services/sample_parameter_service.py` / `src/core/parameter_session.py` / `src/models/sample_parameter_models.py` |
| ❌ 不动 | `network_ops.py`（`prepare_network_for_sample` / `enable_adapter` / `set_static_ip` 已就绪） |
| ❌ 不动 | `config_store.py` / `line_check_assistant/config_store.py` |
| ❌ 不动 | `ACCEPTANCE_BASELINE.md` / `PROJECT_STATUS.md` / `line_check_assistant_README.md` |

## 实现方案

### 1. `line_check_assistant/app.py` — `make_telnet_factory` 内前置步骤

在 `make_telnet_factory` 现有结构中，于「`emit_to_main(... UBUS 启用 telnet 中 ...)`」**之前**插入网络准备三步：

```python
def make_telnet_factory(request):
    def factory(r):
        if not r.bind_ip or not r.device_host:
            raise RuntimeError(f"{r.vlan} 切 telnet 路径但 bind_ip / device_host 为空")

        # === 新增: 开始前启用对应通道的网卡 + 设置静态 IP ===
        adapter_alias = self._adapter_alias_for_vlan(r.vlan)
        subnet_mask = self._subnet_mask_for_vlan(r.vlan)
        if adapter_alias and r.bind_ip:
            emit_to_main(f"{r.vlan} 写参前置：准备网络 {adapter_alias}（{r.bind_ip} / {subnet_mask or '255.255.255.0'}）。")
            network_result = prepare_network_for_sample(
                adapter_alias,
                r.bind_ip,
                subnet_mask,
                on_output=emit_to_main,
                sleep_fn=time.sleep,
            )
            if not network_result.ok:
                emit_to_main(f"{r.vlan} 写参前置：网络准备失败：{network_result.message}")
                raise RuntimeError(f"{r.vlan} 网络准备失败：{network_result.message}")
            if not _wait_for_bindable_ip(r.bind_ip, timeout_seconds=15.0):
                emit_to_main(f"{r.vlan} 写参前置：{r.bind_ip} 仍未成为可绑地址,放弃本台。")
                raise RuntimeError(f"{r.vlan} 网络准备后 {r.bind_ip} 仍不可绑")

        log_path = DEFAULT_LOG_DIR / f"sample_parameter_{r.vlan}_{r.bind_ip}.log"
        emit_to_main(f"{r.vlan} 写参前置：UBUS 启用 telnet 中 ({r.device_host})。")
        # ... 既有的 UBUS + TelnetSession 流程保持不变 ...
    return factory
```

关键点：

- **位置**：放在「`r.bind_ip / r.device_host` 校验之后、`enable_telnet_via_ubus` 之前」。理由：UBUS + TelnetSession 都依赖 `bind_ip` 可绑，必须先把网卡准备到位；同时不与现有「`准备网络 → UBUS → Telnet`」三段日志顺序冲突。
- **复用现有 helper**：`self._adapter_alias_for_vlan` / `self._subnet_mask_for_vlan` 已在 `app.py:572-578` 定义，无需新增。
- **复用现有工具**：`prepare_network_for_sample`（`network_ops.py:745-783`）+ `wait_for_bindable_ip`（`bind_socket.py:47-66`）已就绪，直接调用即可。
- **失败行为**：任一步失败抛 `RuntimeError`，被 `_sample_parameter_write_worker` 现有的 `except Exception as exc` 接住，记录 `telnet 写参启动失败：{exc}`。其它通道继续（既有的 `ThreadPoolExecutor` 并行调度隔离）。
- **缺字段兜底**：`adapter_alias` 或 `bind_ip` 为空时跳过该步骤（保持现状，避免对未配置通道的硬错误；这种情况既有的 `_start_sample_parameter_write` 工厂校验已经会拒绝）。
- **关键阶段日志顺序对齐 `ACCEPTANCE_BASELINE.md` §2.7**：
  ```
  VLANxxx 写参前置：准备网络 vlan101（192.168.1.101 / 255.255.255.0）。
  检查并启用网卡：vlan101
  已启用网卡 vlan101
  设置 vlan101 静态 IP：192.168.1.101（255.255.255.0）
  已设置 vlan101 为 192.168.1.101
  VLANxxx 写参前置：UBUS 启用 telnet 中 (192.168.1.1)。
  VLANxxx UBUS: ...
  VLANxxx UBUS 启用 telnet <action>: <message>
  STATE Telnet 已连接
  VLANxxx 写参：使用 Telnet 会话（绑定源 IP 192.168.1.101）
  ```

### 2. `tests/test_sample_parameter_app.py` — 新增测试

当前该文件仅 1 项 `_parameter_channel_ports` 测试。新增针对 `make_telnet_factory` 前置步骤的 4 项单元测试（用 `Mock` 替代 `enable_telnet_via_ubus` / `TelnetSession` / `prepare_network_for_sample` / `wait_for_bindable_ip`，断言调用顺序、参数与失败传播）：

| # | 名称 | 断言要点 |
| --- | --- | --- |
| 1 | `test_make_telnet_factory_prepares_network_before_ubus` | mock 顺序必须为 `prepare_network_for_sample(vlan_alias, bind_ip, subnet_mask) → wait_for_bindable_ip(bind_ip) → enable_telnet_via_ubus → TelnetSession` |
| 2 | `test_make_telnet_factory_raises_when_prepare_network_fails` | `prepare_network_for_sample` 返回 `ok=False` → factory 抛 RuntimeError，不调用后续步骤 |
| 3 | `test_make_telnet_factory_raises_when_bindable_times_out` | `wait_for_bindable_ip` 返回 False → factory 抛 RuntimeError，不调用 UBUS/TelnetSession |
| 4 | `test_make_telnet_factory_skips_network_step_when_adapter_alias_empty` | `adapter_alias` 为空 → 不调用 `prepare_network_for_sample` / `wait_for_bindable_ip`，继续走 UBUS/TelnetSession（保持向后兼容） |

实现思路：构造 `LineCheckAssistant` 实例（复用现有 `SampleParameterAppTests` 风格），stub 出 `_adapter_alias_for_vlan` / `_subnet_mask_for_vlan` / `prepare_network_for_sample` / `wait_for_bindable_ip` / `enable_telnet_via_ubus` / `TelnetSession`，调用 `make_telnet_factory(request)(request)` 后断言 `mock_calls` 顺序与参数。

### 3. `DEVELOPMENT_LOG.md` — 新增记录

按 `[DEVELOPMENT_LOG.md:13-25](DEVELOPMENT_LOG.md#L13-L25)` 模板在顶部追加一条 `## 2026-07-15 - 写样机参数开始前启用对应通道网卡 + 设置静态 IP`：

- **类型**：功能 / 测试
- **背景**：批量写样机参数时，多张同网段 VLAN 网卡可能被禁用或 IP 未生效，导致 UBUS / Telnet 锁源失败；用户要求开始前先启用对应网卡并按 `network_card_ip` 设置静态 IP，等可绑后再走 UBUS → Telnet；100 秒工厂模式网段切换继续走既有 `make_factory_session_swap`。
- **完成内容**：
  1. **`line_check_assistant/app.py`** —— `make_telnet_factory` 在「`r.bind_ip / r.device_host` 校验后、UBUS 启用 telnet 之前」插入 3 步：`self._adapter_alias_for_vlan(r.vlan)` + `self._subnet_mask_for_vlan(r.vlan)` 取字段；`prepare_network_for_sample(adapter_alias, r.bind_ip, subnet_mask, on_output=emit_to_main, sleep_fn=time.sleep)`；`wait_for_bindable_ip(r.bind_ip, timeout_seconds=15.0)`。任一失败抛 `RuntimeError`，被 worker `except Exception` 捕获并标记 `telnet 写参启动失败`，其它通道不受影响。缺字段（`adapter_alias` 或 `bind_ip`）时跳过该步骤（保持向后兼容）。
  2. **测试** —— `tests/test_sample_parameter_app.py` 新增 4 项：调用顺序、`prepare_network_for_sample` 失败传播、`wait_for_bindable_ip` 超时传播、缺 `adapter_alias` 跳过。
- **修改文件**：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_app.py`、`DEVELOPMENT_LOG.md`。
- **验证方法**：`python -m py_compile line_check_assistant/app.py`；`python -m unittest discover -s tests -v`。
- **验证结果**：`py_compile` 通过；新增 4 项；与既有 `ACCEPTANCE_BASELINE.md` §0 基线（199 项）合并后约 **203 项全过**（与开发日志历史数据 + 4 一致）。
- **后续待办**：用户真实样机验收 —— 主执行日志期待出现「`VLANxxx 写参前置：准备网络 vlan101（192.168.1.101 / 255.255.255.0）` → 检查并启用网卡 → 已启用网卡 → 设置静态 IP → 已设置 → `UBUS 启用 telnet 中` → UBUS 三段 → `STATE Telnet 已连接` → 后续写参时序」，确认 `network_card_ip` 与样机管理 IP 在同一 /24 子网；若 `prepare_network_for_sample` 失败日志明确显示对应 VLAN 与原因，按提示核对 `adapter_alias` 或管理员权限。

## 验证

按照 `ACCEPTANCE_BASELINE.md` §0 最小可信回归基线：

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m py_compile line_check_assistant\app.py
python -m unittest discover -s tests -v
```

- 期望：原 199 项 + 新增 4 项 = 约 **203 项** 全过（注：基线本身在 `DEVELOPMENT_LOG.md` 最新记录中已是 228 项；以实际跑出的 `Ran N tests ... OK` 为准，本次新增 4 项是肯定项）。
- 不打包（保持 AGENTS.md 中「构建后不在当前 PC 运行 exe」的规则）。
- 真实样机验收后才考虑升级 `ACCEPTANCE_BASELINE.md` §2.7 标签。

## 风险与边界

| 风险 | 说明 |
| --- | --- |
| 多线程 netsh | 每台样机的 `prepare_network_for_sample` 在自己的 factory 闭包内执行，对应各自的 adapter；并发调用是独立网卡，安全。 |
| 管理员权限 | `netsh interface ip set address` 需要管理员权限；AGENTS.md 与 `PROJECT_STATUS.md` 已声明"仅 Windows + 需管理员权限"，不是新增约束。失败信息会通过 `prepare_network_for_sample.message` 透传到主日志。 |
| 现有 199 项测试 | 既有测试均用 fake session 走串口路径或直接构造 `SampleParameterWriteRequest`，不触达 `make_telnet_factory`；`test_app.py` 中 `parameter_initial_username/password` mock 已就位，本次只新增 4 项针对 factory 前置步骤的测试，不修改既有断言。 |
| 真实样机验收 | 状态标签仍为「已实现未验收」，需现场跑通后才升。 |
| 与工厂模式网段切换的衔接 | 100 秒后的 `make_factory_session_swap` 仍按 `request.factory_bind_ip` 切到 29 网段；本步骤仅处理初始用户模式网段（`network_card_ip`），两者不冲突。 |