# 全包升级扩到 8 台并行 + 程控电源 COM 复用优化

## 背景

- 当前全包升级（`Tftp指令` / `Tftp Put`）并行上限硬编码为 2 台，见 [line_check_assistant/app.py:81](Cheating_machine_execution_tool/line_check_assistant/app.py#L81)、[app.py:1279](Cheating_machine_execution_tool/line_check_assistant/app.py#L1279)、[app.py:1294](Cheating_machine_execution_tool/line_check_assistant/app.py#L1294)、[app.py:1422](Cheating_machine_execution_tool/line_check_assistant/app.py#L1422)、[app.py:1475](Cheating_machine_execution_tool/line_check_assistant/app.py#L1475)。
- 真实样机日志显示（2026-07-12 20:46）程控电源 COM102 在两个 VLAN 之间反复 open/close：
  ```
  20:46:01 [vlan115] 已打开程控电源串口：COM102，19200 8N1。
  ...
  20:46:06 [vlan115] 已关闭程控电源串口：COM102。
  20:46:06 [vlan114] 已打开程控电源串口：COM102，19200 8N1。
  ...
  20:46:10 [vlan114] 已关闭程控电源串口：COM102。
  ```
  这是 `UpgradePowerCycleCoordinator.power_on_channel` 每次调用都通过 `power_on_selected_channels` 新建 `ProgrammablePowerSupply` 实例造成的（[power_on_service.py:41](Cheating_machine_execution_tool/src/services/power_on_service.py#L41) → [power_supply.py:106](Cheating_machine_execution_tool/src/core/power_supply.py#L106)）。
- 扩到 8 台后，该 open/close 模式会被放大 4 倍，纯属浪费；同时程控电源 COM 锁的"入门费"也累积得更明显。

## 目标

1. 并行上限改为可配置（1–8），默认 2 保持当前体验，存 ini；UI 暴露 Spinbox。
2. 一次并行批次的程控电源 COM 只 open 一次、close 一次；中途各 VLAN 上下电帧只复用已打开的连接。
3. 全部回归 + 真实多台样机验收。

## 涉及文件

| 文件 | 用途 |
|---|---|
| [src/core/power_supply.py](Cheating_machine_execution_tool/src/core/power_supply.py) | 已有 `ProgrammablePowerSupply`，API 满足复用，不动 |
| [src/services/power_on_service.py](Cheating_machine_execution_tool/src/services/power_on_service.py) | 新增"接收已打开 supply、直接写帧"的入口函数 |
| [src/services/serial_upgrade_service.py](Cheating_machine_execution_tool/src/services/serial_upgrade_service.py) | 改造 `UpgradePowerCycleCoordinator` 持有 supply；新增 `close()`；并行 runner try/finally 收尾 |
| [line_check_assistant/app.py](Cheating_machine_execution_tool/line_check_assistant/app.py) | 加 `MAX_PARALLEL_UPGRADES=8` 常量；UI 加 Spinbox；4 处 "2" 改常量或读 `parallel_count` |
| [line_check_assistant/sample_upgrade_settings_store.py](Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py) | `SampleUpgradeSettings` 新增 `parallel_count: int = 2`；load/save 处理 |
| [Auto_power_on_off_tool/config/sample_upgrade_settings.ini](Cheating_machine_execution_tool/Auto_power_on_off_tool/config/sample_upgrade_settings.ini) | 新增 `parallel_count = 2` 行 |
| [tests/test_app.py](Cheating_machine_execution_tool/tests/test_app.py) | 6 处 "并行（最多 2 台）" mock 跟随新文案；新增 Spinbox 相关用例 |
| [tests/test_sample_upgrade_settings_store.py](Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py) | 新增 `parallel_count` 持久化用例 |
| [tests/test_serial_upgrade_service.py](Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py) | 新增 coordinator supply 复用断言 |
| [line_check_assistant_README.md](Cheating_machine_execution_tool/line_check_assistant_README.md) | 第 16 行 "最多同时运行两台" → 新上限 + 配置说明 |
| [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md) | 追加新条目 |

## 实现细节

### A. UI 与配置层

1. `app.py` 新增常量：
   ```python
   MAX_PARALLEL_UPGRADES = 8
   DEFAULT_PARALLEL_COUNT = 2
   ```
   并把现有 `UPGRADE_EXECUTION_PARALLEL = "并行（最多 2 台）"` 改为：
   ```python
   UPGRADE_EXECUTION_PARALLEL = f"并行（最多 {MAX_PARALLEL_UPGRADES} 台）"
   ```
2. UI 在执行方式 Combobox 旁边加一个 `ttk.Spinbox`，范围 1–8，绑定 `IntVar`：
   - 行内紧跟 `upgrade_execution_combo` 右侧或下一行；
   - `state="readonly"` 避免手动输入非法值；
   - 当执行方式 = 串行时灰显（`state="disabled"`）。
3. `SampleUpgradeSettings` 新增字段 `parallel_count: int = DEFAULT_PARALLEL_COUNT`；`SampleUpgradeSettingsStore.load/save` 处理 `parallel_count`（用 `getint` + fallback，保存时校验 1 ≤ n ≤ MAX_PARALLEL_UPGRADES，越界回退到默认值）。
4. `_current_sample_upgrade_settings` 把 `parallel_count=self.upgrade_parallel_count_var.get()` 写入。
5. `_start_serial_tftp_copy_upgrade` 里的两处 `max_workers=2`：
   - 串行模式：传 `max_workers=1`（行为不变，保持首错即停）。
   - 并行模式：传 `max_workers=self.upgrade_parallel_count_var.get()`，并钳制到 `[1, MAX_PARALLEL_UPGRADES]`。
6. `_normalize_upgrade_execution_mode` 已有，保持不变；执行方式只决定"串行 / 并行"，并行数从 Spinbox 取。
7. UI 文案更新：
   - "并行（最多 2 台，完成即补位）" → `f"并行（最多 {MAX_PARALLEL_UPGRADES} 台，可调并行数，完成即补位）"`。
   - "准备并行升级 N 台样机（最多 2 台）" → `f"准备并行升级 N 台样机（最多 {parallel_count} 台）"`，使用实际传入的并行数。
   - 确认弹窗文案同上一条。

### B. 程控电源 COM 复用

1. `power_on_service.py` 新增一个低层入口，不创建新 supply：
   ```python
   def power_cycle_channel_with_supply(
       supply: ProgrammablePowerSupply,
       channel: int,
       *,
       wait_seconds: float = 0,
       on_output: Callable[[str], None] | None = None,
       on_channel_powered: Callable[[int], None] | None = None,
       sleep_fn: Callable[[float], None] = time.sleep,
       monotonic_fn: Callable[[], float] = time.monotonic,
   ) -> CommandResult:
       """对已打开的 supply 写一对断电 + 上电帧 + 启动等待。
       supply 生命周期由调用方负责（coordinator 持有）。"""
   ```
   内部直接 `supply.power_on_channels([channel], on_channel_powered=on_channel_powered)`，复用 [power_supply.py:99](Cheating_machine_execution_tool/src/core/power_supply.py#L99) 的逻辑。

2. `serial_upgrade_service.py:56` 改造 `UpgradePowerCycleCoordinator`：
   ```python
   class UpgradePowerCycleCoordinator:
       def __init__(self, ...):
           self._locks: dict[str, threading.Lock] = {}
           self._supplies: dict[str, ProgrammablePowerSupply] = {}
           self._locks_guard = threading.Lock()
       
       def _get_or_open_supply(self, port: str, on_output) -> ProgrammablePowerSupply:
           with self._locks_guard:
               supply = self._supplies.get(port)
               if supply is None:
                   supply = ProgrammablePowerSupply(port, on_output=on_output)
                   supply.open()
                   self._supplies[port] = supply
               return supply
       
       def power_on_channel(self, serial_port, channel, *, wait_seconds, on_output=None, on_channel_powered=None):
           port = serial_port.strip().upper()
           with self._locks_guard:
               lock = self._locks.setdefault(port, threading.Lock())
           with lock:
               supply = self._get_or_open_supply(port, on_output)
               started = self._monotonic()
               # 注意：这里 on_output 已经绑定到 supply，再传给 power_cycle_channel_with_supply 会重复
               # 因此把 supply 的 _on_output 暂时替换，或在 power_cycle_channel_with_supply 内部不再二次 emit
               result = power_cycle_channel_with_supply(
                   supply, channel,
                   wait_seconds=wait_seconds,
                   on_channel_powered=on_channel_powered,
                   sleep_fn=self._sleep,
                   monotonic_fn=self._monotonic,
               )
           return result
       
       def close(self):
           with self._locks_guard:
               supplies = list(self._supplies.values())
               self._supplies.clear()
           for supply in supplies:
               try:
                   supply.close()
               except Exception:
                   pass
   ```
   
   **关键点**：`ProgrammablePowerSupply._on_output` 只在 open/close 时被 emit 一次；中间帧的日志由 `power_on_channels` 内部 `_write_frame` 通过 `_emit` 走。coordinator 把同一个 `on_output` 传给 supply 即可，避免重复日志。

3. 两个并行 runner（`run_parallel_tftp_command_upgrades`、`run_parallel_tftp_put_upgrades`）用 try/finally 包裹：
   ```python
   coordinator = UpgradePowerCycleCoordinator()
   try:
       with ThreadPoolExecutor(...) as executor:
           ...
   finally:
       coordinator.close()
   ```

4. 串行路径 (`_serial_tftp_copy_upgrade_worker` / `run_single_full_package_upgrade`) 不走 coordinator，**不修改**，行为保持不变。

### C. 测试

1. `test_serial_upgrade_service.py`：
   - 新增 `test_parallel_*_coordinator_reuses_supply`：mock `ProgrammablePowerSupply`，断言 N 个 worker 之间 `open()` 只调用 1 次、`close()` 只在 `coordinator.close()` 调用 1 次。
   - 现有 2 台并行的断言 (`max(peak_active) == 2`) 保留，新加 `max_workers=4` 的烟雾测试（如果现有调度器无 max_workers 上限相关 assertion，可不补）。

2. `test_app.py`：
   - 把 6 处 mock 的 `"并行（最多 2 台）"` 跟随新文案（仍为常量，测试用模块属性访问或保留原字符串模板）。
   - 新增 `test_current_sample_upgrade_settings_includes_parallel_count` 断言新字段。
   - 新增 `test_parallel_worker_uses_configured_parallel_count`：mock Spinbox var get 返回 4，断言传入 `max_workers=4`。

3. `test_sample_upgrade_settings_store.py`：
   - 新增 round-trip 用例覆盖 `parallel_count` 字段。

### D. 文档

1. `line_check_assistant_README.md` 第 16 行：
   > `Tftp指令` 和 `Tftp Put` 的并行模式最多同时运行两台
   → 
   > `Tftp指令` 和 `Tftp Put` 的并行模式可在执行窗口通过 Spinbox 调整 1–8 台（默认 2），存于 `sample_upgrade_settings.ini` 的 `parallel_count`。一次并行批次的程控电源 COM 只在首台上下电前打开、最后台完成后关闭。

2. `DEVELOPMENT_LOG.md` 顶部追加新条目（仿 [DEVELOPMENT_LOG.md:694](DEVELOPMENT_LOG.md#L694) 格式）：
   - 标题：`全包升级并行上限扩到 8 台 + 程控电源 COM 批次内复用`
   - 背景、变更内容、验证方法、后续待办。

## 验证步骤

1. `python -m unittest discover -s Cheating_machine_execution_tool/tests -v` —— 全部通过。
2. 编译检查（项目根目录已有 `build_line_check_assistant.ps1`）。
3. 真实样机 2 台、4 台、8 台各跑一轮：
   - 比对日志：第二批后只看到 1 次"已打开程控电源串口"、1 次"已关闭程控电源串口"。
   - 确认 8 台并发下，TFTPy 上传无明显错包、串口不丢帧。
   - 错开上电时间，错开 1–2 秒（如果实验室功率闸容量受限，可加 coordinator 内 `power_cycle_offset_seconds`，**默认 0**，按需打开）。

## 不做的事

- 不引入额外硬件抽象层或多电源支持（超 8 台再考虑）。
- 不改串行路径，避免行为漂移。
- 不改 TFTPy、network_card_ip.ini、Auto_Power_On_Off_Tool。
- 不动 sample_upgrade_settings.ini 已存在的字段顺序（仅追加）。

## 风险点

- **`ProgrammablePowerSupply` 多线程安全**：当前 API 没有显式 lock，但 coordinator 的 lock 已经串行化所有写帧动作，理论上安全。新增单测覆盖并发场景。
- **异常时 supply 残留**：coordinator.close() 必须走 finally 路径；N 个 worker 中途报错也要保证收尾。
- **TFTPy server 监听线程**：与本改动无关，但扩到 8 台后实测可能暴露。