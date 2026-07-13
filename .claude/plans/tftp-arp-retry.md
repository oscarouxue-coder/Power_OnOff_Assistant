# Tftp指令 ARP 失败自动重试

## 背景

用户提供的真实样机日志（2026-07-12）显示 U-Boot 在 TFTP 拉固件过程中偶发 ARP 解析失败：

```
U-Boot> tftp 192.168.1.113:tclinux_allinone
tftp 192.168.1.113:tclinux_allinone
Using eth@1fb59000 device
TFTP from server 192.168.1.113; our IP address is 192.168.1.1
Filename 'tclinux_allinone'.
Load address: 0x81800000
Loading: *
ARP Retry count exceeded; starting again
U-Boot>
```

样机在数十秒内就放弃了 TFTP 并回到 `U-Boot>` 提示符。当前 `send_tftp_command_and_wait` 仅依赖 `wait_for_all(("done", "write"), TFTP_COMMAND_TIMEOUT_SECONDS=1800)`，意味着本次失败会阻塞整整 30 分钟才向主程序报告超时，且没有任何自动补救。

需求：当样机输出 `ARP Retry count exceeded` + `U-Boot>` 时，主程序自动重新发送同一条 tftp 命令，最多 3 次；并把每次重试/成功写入主程序执行日志。

## 设计原则

- 仅作用于 `Tftp指令`（样机主动拉固件）链路；`Tftp Put` 走的是 TFTPy Client 推送，串口看不到 `ARP Retry count exceeded`，不适用。
- 保持现有成功路径语义不变：命中 `done + write` 时立即返回成功。
- 不修改 `Tftp指令` 的传输时序：boot 登录 → TFTPy 服务启动 → 发送 tftp 命令 → 监测 boot 重启。
- 不修改 `build/`、`dist/`、`logs/`、`.venv/`，不自动 commit。

## 用户已确认的设计点

| 选项 | 选择 |
| --- | --- |
| 重试间隔 | 1 秒 |
| 单次超时 | 300 秒（5 分钟，从原 1800 秒下调） |
| 适用范围 | 仅 `Tftp指令` |

## 实现方案

### 1. 新增模块常量

**文件**：`src/services/serial_upgrade_service.py`

```python
TFTP_COMMAND_MAX_RETRIES = 3                  # 最多尝试 3 次
TFTP_ARP_FAILURE_MARKER = "arp retry count exceeded"  # 小写匹配，与 session 内部 lower() 一致
TFTP_RETRY_PROMPT_MARKER = "u-boot>"           # 复用现有小写提示符常量风格
TFTP_COMMAND_POLL_SECONDS = 1.0                # 每秒轮询以便及时发现 ARP 失败
TFTP_COMMAND_RETRY_DELAY_SECONDS = 1.0         # 检测到 ARP 失败后等 1 秒再重发
```

同步把 `TFTP_COMMAND_TIMEOUT_SECONDS` 从 `1800` 调整为 `300`。

### 2. 新增 helper：`_wait_for_tftp_completion_or_arp_failure`

**文件**：`src/services/serial_upgrade_service.py`，`SerialUpgradeController` 内。

不沿用 `wait_for_all` 阻塞 300 秒，而是按 1 秒节奏轮询：

- 每轮先 `wait_for_all(("done", "write"), 0, cursor)` 立即检查历史中是否已完成。
- 紧接着 `peek_since(cursor)` 检查是否出现 `arp retry count exceeded` + `u-boot>`。
- 然后 `wait_for_any(("done", "write", arp_marker, prompt_marker), 1.0, cursor)` 等 1 秒数据。
- 任一模式命中立即返回；总等待上限为 `TFTP_COMMAND_TIMEOUT_SECONDS`（300 秒）。

返回 `(completed: bool, arp_failed: bool)`：
- `completed=True`：检测到 `done + write`，调用方应报告成功。
- `arp_failed=True`：检测到 ARP retry + U-Boot>，调用方可重试。
- 两者皆 False：超时未命中任何标记。

### 3. 重写 `send_tftp_command_and_wait`

**文件**：`src/services/serial_upgrade_service.py` 第 254 行附近。

签名扩展为 `send_tftp_command_and_wait(self, command: str, on_output: Callable[[str], None] | None = None)`，新增可选 `on_output` 回调，与 `restore_factory_if_enabled` 的 `on_command_sent` 一致。

重试循环：

```python
last_failure: str | None = None
for attempt in range(1, TFTP_COMMAND_MAX_RETRIES + 1):
    cursor = self.session.cursor()
    if on_output and attempt > 1:
        on_output(f"自动重试 TFTP 命令：第 {attempt}/{TFTP_COMMAND_MAX_RETRIES} 次发送 {command}")
    self.session.send_line(command)

    completed, arp_failed = self._wait_for_tftp_completion_or_arp_failure(
        cursor, TFTP_COMMAND_TIMEOUT_SECONDS
    )
    if completed:
        if on_output and attempt > 1:
            on_output(f"TFTP 命令在第 {attempt} 次尝试时检测到完成标记 done + write。")
        return CommandResult(True, "检测到 TFTP 传输完成标记 done + write。")

    if arp_failed:
        last_failure = (
            f"第 {attempt} 次传输因 ARP Retry count exceeded 失败且样机返回 U-Boot> 提示符"
        )
        if on_output:
            if attempt < TFTP_COMMAND_MAX_RETRIES:
                on_output(f"检测到 {last_failure}，剩余 {TFTP_COMMAND_MAX_RETRIES - attempt} 次自动重试。")
            else:
                on_output(f"检测到 {last_failure}，已达最大重试次数 {TFTP_COMMAND_MAX_RETIDES}。")
        if attempt >= TFTP_COMMAND_MAX_RETRIES:
            break
        self.sleep(TFTP_COMMAND_RETRY_DELAY_SECONDS)
        continue

    return CommandResult(False, "等待样机串口 TFTP 完成标记超时。")

return CommandResult(
    False,
    f"TFTP 命令已重试 {TFTP_COMMAND_MAX_RETRIES} 次仍未成功：{last_failure or '原因未明'}。",
)
```

### 4. 同步调用点

**文件**：`src/services/serial_upgrade_service.py` 第 515 行附近（`_run_tftp_command_with_power_supply`）。

```python
tftp_result = controller.send_tftp_command_and_wait(
    f"tftp {request.tftp_server_ip}:tclinux_allinone",
    on_output=emit,
)
```

让 `emit` 把重试/成功的提示写到主程序执行日志，与现有 `firstboot` 的 `on_command_sent=emit` 一致。

## 测试

**文件**：`tests/test_serial_upgrade_service.py`

- 现有 `test_tftp_command_requires_done_and_write_stage_result` 仍须通过——成功路径不变。
- 新增 `test_tftp_command_retries_on_arp_failure_then_succeeds`：
  - 模拟首次 `wait_for_all` 看到 `done + write`，验证只发 1 次命令、不发第二次。
  - 改为 FakeSession 的 `peek_since` 返回含 `arp retry count exceeded` + `u-boot>` 的文本，验证重试 3 次后仍失败时只写了 3 次 tftp 命令，且 3 次命令之间各 sleep 1 秒。
  - 验证 `on_output` 收到 "检测到 ARP Retry count exceeded ..." 和 "TFTP 命令在第 X 次尝试时检测到完成标记" 等日志。
- 新增 `test_tftp_command_does_not_retry_when_arp_marker_missing`：仅有 `done + write` 不命中重试；仅有 ARP 失败但没 `u-boot>` 不重试；超时但既无 `done` 也无 ARP 模式时不重试。

FakeSession 需要扩展：

```python
class FakeSession:
    def __init__(self, any_results=(), all_result=True, peek_text=""):
        ...
        self.all_result_history = []  # 模拟 wait_for_all 的多轮返回
        self.all_result = all_result   # 初始返回值；若为 list 视为按序返回
```

如果 `all_result` 是 list，则按调用次序弹出一个布尔。这样可以模拟"首次未完成 + 重试时命中 done + write"等序列。

## 文档同步

- `DEVELOPMENT_LOG.md`：在顶部追加 2026-07-12 的"全包升级 Tftp指令 ARP 失败自动重试"条目，列出改动文件、验证方法、测试结果。
- `PROJECT_STATUS.md`：在"已完成"段落同步 Tftp指令 单次超时调整为 5 分钟，并加注 ARP 失败自动重试 3 次。

## 验证方法

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m py_compile src/services/serial_upgrade_service.py
python -m unittest discover -s tests -v
```

预期：全部测试通过（基线 163 项 + 新增 2 项 = 165 项）。

## 风险与限制

- 单次超时从 30 分钟下调到 5 分钟：若样机正常 TFTP 传输慢于 5 分钟，会被误判超时失败。若现场需要可回滚到 1800 秒（仅一处常量）。
- 重试只在 `Tftp指令` 链路生效；Tftp Put 由 TFTPy Client 控制，不主动监听串口 ARP 字样。
- 若样机只输出 `arp retry count exceeded` 但未返回 `U-Boot>`（例如卡在 Loading 状态），不触发自动重试，按普通超时处理。