# 写样机参数 多台并行稳定性 — 节奏常量 + 错峰启动

## 背景与根因

用户反馈（2026-07-18）：

> 写样机参数最多并行 8 台，但稳定性欠佳，有时会出现随机某台或多台样机写参失败。

用户猜测（已部分验证）：多台并行时每台样机每条指令发送的间隔过快，样机都反应不过来，主程序误以为命令执行失败。

代码定位（[src/services/sample_parameter_service.py](../Cheating_machine_execution_tool/src/services/sample_parameter_service.py)）：

| 位置 | 现状 | 风险 |
| --- | --- | --- |
| `_write_and_verify` set 后 sleep | 硬编码 `1.0` 秒 | 样机落盘到 nvram/flash 慢时，`get` 在 `set` 还没完成时被样机执行，读回旧值 |
| `_write_and_verify` get 后 wait_for_any | 硬编码 `4.0` 秒 | 8 台并行下，shell 处理 4 秒内回不完 |
| 重试之间 | 无退避 | mismatch → `continue` 立刻再发 `set`，负载越叠越重 |
| 15 项参数之间 | 无间隔 | 30 条命令连续下发，shell 队列压满 |
| 并行 worker 启动 | executor.submit 一次性灌入 | 8 台同 t=0 触发网络准备 + UBUS 4 段 HTTP × 8 + 8 路 telnet login，挤网卡/防火墙 |
| `_login` 提示符/密码回执 | 8 / 8 / 15 秒 | 并行下偏紧，登录阶段也偶发失败 |

## 目标

只调整节奏，不改协议语义。保留"set → 等 → get → 等 marker"的骨架，把过紧的硬编码时间换成可调常量，并加错峰启动。所有改动应：

- 不影响单台 telnet 路径的 1 台真实样机验收（[ACCEPTANCE_BASELINE.md §2.7](../Cheating_machine_execution_tool/ACCEPTANCE_BASELINE.md) 已通过）
- 让既有 249 项单元测试不破
- 给后续 2/4/8 台真实样机并行验收提供更稳健的节奏

## 改动清单

### 1. `Cheating_machine_execution_tool/src/services/sample_parameter_service.py`

新增 7 个模块级常量（在 `PARAMETER_WRITE_RETRIES` 之后），替换 4 处硬编码时间：

```python
# 写参节奏控制（按真实样机经验调整;原硬编码值在 _login / _write_and_verify）
PARAMETER_SETTLE_AFTER_SET_SECONDS = 1.5        # 原硬编码 1.0;set 后等样机落盘再发 get
PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS = 10.0   # 原硬编码 4.0;get 后等 marker 的最长秒数
PARAMETER_RETRY_BACKOFF_SECONDS = 1.5           # 原无;set/get 校验失败后下次重试前的退避
PARAMETER_BETWEEN_PARAMS_SECONDS = 0.5          # 原无;同一台样机 15 项参数之间留缓冲
PARAMETER_LOGIN_PROMPT_TIMEOUT_SECONDS = 10.0   # 原硬编码 8.0;_login 等 prompt / username 的上限
PARAMETER_LOGIN_PASSWORD_TIMEOUT_SECONDS = 20.0 # 原硬编码 15.0;_login 等密码回执的上限
PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS = 0.6# 原无;并行 worker 错峰启动延迟
```

修改 `_login`：

- `session.wait_for_any(("#", ">", "login:", "username:"), 8, cursor)` → `PARAMETER_LOGIN_PROMPT_TIMEOUT_SECONDS`
- `session.wait_for_any(("password:", "passvord:"), 8, username_cursor)` → `PARAMETER_LOGIN_PROMPT_TIMEOUT_SECONDS`
- `session.wait_for_any(("#", ">", "incorrect", "failed"), 15, result_cursor)` → `PARAMETER_LOGIN_PASSWORD_TIMEOUT_SECONDS`

修改 `_write_and_verify`：

- `if not _wait_cancellable(1, cancel, sleep_fn):` → `if not _wait_cancellable(PARAMETER_SETTLE_AFTER_SET_SECONDS, cancel, sleep_fn):`
- `marker = session.wait_for_any((...), 4, cursor)` → `marker = session.wait_for_any((...), PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS, cursor)`
- `marker is None` 分支末尾加 `_wait_cancellable(PARAMETER_RETRY_BACKOFF_SECONDS, cancel, sleep_fn)`
- mismatch 分支（`if actual_for_compare == expected` else）末尾加同样的 retry backoff
- 函数成功 / 失败返回前各加一次 `_wait_cancellable(PARAMETER_BETWEEN_PARAMS_SECONDS, cancel, sleep_fn)`
  - 成功路径：`emit(f"{vlan} {label} 写入并读回校验成功（第 {attempt} 次）。")` 之后
  - 失败路径：retry loop 结束之后、return False 之前

`run_parallel_sample_parameter_writes` 新增可选形参：

```python
def run_parallel_sample_parameter_writes(
    requests, session_manager, parallel_count=2, on_output=None, on_session_ready=None,
    cancel_event=None, sleep_fn=time.sleep,
    startup_stagger_seconds: float = PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS,
):
```

并把现有 `dict comprehension` 的 `executor.submit` 改为按 `index` 错峰：

```python
futures = {}
for index, request in enumerate(items):
    if index > 0 and startup_stagger_seconds > 0:
        sleep_fn(startup_stagger_seconds)
    future = executor.submit(
        run_single_sample_parameter_write, request, session_manager,
        on_output, on_session_ready, cancel, sleep_fn,
    )
    futures[future] = index
```

### 2. `Cheating_machine_execution_tool/line_check_assistant/app.py`

`_sample_parameter_write_worker` 内 telnet / serial 两侧并行 executor 都改为按 index 错峰提交。serial 路径继续走 `run_parallel_sample_parameter_writes(startup_stagger_seconds=...)`，telnet 路径本地把 dict comprehension 改为 for-loop：

```python
with ThreadPoolExecutor(max_workers=min(parallel_count, len(telnet_requests)), ...) as executor:
    telnet_futures = {}
    for offset, req in enumerate(telnet_requests):
        if offset > 0:
            time.sleep(PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS)
        future = executor.submit(
            run_single_sample_parameter_write, req,
            self.serial_session_manager, emit_to_main, None,
            cancel_event, time.sleep,
            make_telnet_factory(req), make_factory_session_swap(req),
        )
        telnet_futures[future] = telnet_indices[offset]
    for future in as_completed(telnet_futures):
        ...
```

在 worker 顶部（与现有 `UBUS_ENABLE_TELNET_*` 常量同级）新增：

```python
PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS = 0.6
```

或直接 `from src.services.sample_parameter_service import PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS` 复用同一来源常量。

### 3. 新增测试 `Cheating_machine_execution_tool/tests/test_sample_parameter_pacing.py`

- `test_login_uses_new_prompt_timeout`：FakeSession 记录 `wait_for_any` 的 `timeout_seconds` 形参，断言 prompt / password_prompt 都用 `PARAMETER_LOGIN_PROMPT_TIMEOUT_SECONDS`，result 用 `PARAMETER_LOGIN_PASSWORD_TIMEOUT_SECONDS`
- `test_write_and_verify_uses_settle_and_get_timeout`：FakeSession 记录 `wait_for_any` 与 sleep_fn 调用次数；断言 sleep_fn 至少被调用 1 次且时长 ≈ `PARAMETER_SETTLE_AFTER_SET_SECONDS`；`wait_for_any` 的 timeout = `PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS`
- `test_write_and_verify_retries_with_backoff_on_mismatch`：FakeSession 在第 1 次 mismatch 后第 2 次成功；断言两次之间 sleep 时长 ≈ `PARAMETER_RETRY_BACKOFF_SECONDS`
- `test_write_and_verify_sleeps_between_params_after_failure`：同一参数 3 次都 mismatch；函数返回前 sleep 时长 ≈ `PARAMETER_BETWEEN_PARAMS_SECONDS`
- `test_write_and_verify_sleeps_between_params_after_success`：第 1 次成功；成功后 sleep 时长 ≈ `PARAMETER_BETWEEN_PARAMS_SECONDS`
- `test_run_parallel_writes_staggers_startup`：构造 3 个 request 列表 + sleep_fn 记录列表；调用 `run_parallel_sample_parameter_writes(..., startup_stagger_seconds=0.05)`；断言 sleep_fn 第二次调用约 0.05、第三次约 0.10、第一次调用约 0.0
- `test_run_parallel_writes_zero_stagger_does_not_sleep`：`startup_stagger_seconds=0` 时 sleep_fn 不被 `run_parallel_sample_parameter_writes` 调用

> FakeSession 用现有 `_test_sample_parameter_service.py` 的模式；sleep_fn 既可以是 `sleeps.append` 列表，也可以是 mock；`wait_for_any` 不再只返回第一个 marker，而是根据测试需要返回 marker 或 None。

### 4. 文档

- `Cheating_machine_execution_tool/DEVELOPMENT_LOG.md` 顶部追加一条 2026-07-18 记录：
  - 类型：性能优化 / 测试
  - 背景：用户反馈 8 台并行稳定性欠佳
  - 完成内容：列出 7 个常量与对应旧硬编码值；说明 `_login` / `_write_and_verify` / `run_parallel_sample_parameter_writes` / app.py telnet executor 4 处改动
  - 修改文件：`sample_parameter_service.py`、`app.py`、`tests/test_sample_parameter_pacing.py`（新）
  - 验证方法：`python -m py_compile` + `python -m unittest discover -s tests -v`
  - 验证结果：249 + N 项全过（N 为新增测试数）
  - 后续待办：用户真实样机 2/4/8 台并行验收，确认主执行日志节奏常量生效 + 无随机失败

- `Cheating_machine_execution_tool/ACCEPTANCE_BASELINE.md §2.7 边界与异常` 末尾追加一行：

  > 并行稳定性节奏常量：`PARAMETER_SETTLE_AFTER_SET_SECONDS=1.5`、`PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS=10.0`、`PARAMETER_RETRY_BACKOFF_SECONDS=1.5`、`PARAMETER_BETWEEN_PARAMS_SECONDS=0.5`、`PARAMETER_LOGIN_PROMPT_TIMEOUT_SECONDS=10.0`、`PARAMETER_LOGIN_PASSWORD_TIMEOUT_SECONDS=20.0`、`PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS=0.6`；默认值统一在 `src/services/sample_parameter_service.py` 顶部，按现场经验统一调整。

- `Cheating_machine_execution_tool/PROJECT_STATUS.md` 待完成项中追加：「2026-07-18 已为 2/4/8 台并行写入节奏常量化（set 后 settle、get 超时、退避、参数间隔、登录超时、错峰启动）；真实样机并行验收待运行。」

## 不动什么

- TFTP / 全包升级 / 串口终端 / 页面升级 / ONU 注册 —— 都不动
- 协议不变性：`Tftp指令` 与 `Tftp Put` 分离、`vlan{N}->COM{N-100}` 映射、`MAX_PARALLEL_UPGRADES=8`、`source_address=(bind_ip, 0)` 锁源 —— 全部保留
- `bind_socket.py`、`ubus_http_client.py`、`ubus_enable_telnet.py` —— 不动
- 不新建数据库 / 配置 schema / 持久化字段 —— 全部从代码常量读取
- 不修改 `build/`、`dist/`、`logs/`、`.venv/` 目录
- 不自动 commit —— 等用户发"提交"

## 风险与回滚

- 风险：默认值若偏保守，会拉长 8 台并行的总耗时（预计 +10~30 秒）。属于"用时间换稳定性"，与用户期望一致。
- 回滚：7 个常量都是模块级 top-level，把数值改回原硬编码即可一行级回退，不影响调用方。

## 验证步骤

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m py_compile src\services\sample_parameter_service.py line_check_assistant\app.py
python -m unittest discover -s tests -v
```

预期：完整跑通 249 + 新增测试数（预计 6 项），全部 PASS。