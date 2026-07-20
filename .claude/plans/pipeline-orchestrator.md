# 检查并执行测试 → 全流程管道编排器

## 背景

当前主界面 `line_check_assistant/app.py:431` 的 "检查并执行测试" 按钮实际**只调 `_start_all_checks`**，仅做"已勾选通道 ping 通过性检查"（见 `app.py:3496-3536`），不消费 `test_project_config.ini` 的 `[order]` 段，也不与其他已有功能联动。

`Auto_power_on_off_tool/config/test_project_config.ini` 已被 [test_item_config_store.py](../../Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py) 加载并支持四 Tab 编辑（Q1=A：仅编辑，不接执行），其中：

- `[telnet]` 段 — 12 个字段，含 user/password
- `[order]` 段 — N 条命令 + per-segment 期望（`!A&&B`）+ 每条 retry_times
- `[connect_wifi]` 段 — `enable` + `product_solution`（openwrt 当前唯一）
- `[project_info]` 段 — 项目名称 / 软件版本 / 内部软件版本 / ONU 编译时间（仅编辑器）

老工具 [powe_on_off_telnet.py](../../Cheating_machine_execution_tool/Auto_power_on_off_tool/test_case/powe_on_off_telnet.py) 的「测试项执行」主流程是：

1. 程控电源上下电 → 2. ping → 3. web 启用 telnet → 4. telnet 登录 → 5. 循环 [order] 命令 + fuzzy match + per-command retry → 6. WiFi 连接验证 → 7. 写 per-channel 结果文件

用户希望新工具升级"检查并执行测试"按钮的语义为**全流程管道编排器**：
- 主界面点击"检查并执行测试" → 弹"全流程执行"窗口，6 个子任务多选；
- 每个子任务显示"必填项当前状态"，缺项红字警告；
- 二次确认后按 **1→6 固定顺序** 串行执行；
- 任一子任务失败 → **整个管道停止**，主日志留痕；
- 复用现有功能（自动上/下电、样机升级、写样机参数、ONU注册、串口日志、测试项配置），不重写底层。

用户连接好样机 + 填好所有配置后，一键跑完 6 步全流程。

## 目标行为（与用户对齐后）

| 决策 | 选择 | 来源 |
| --- | --- | --- |
| 入口 | 主界面"检查并执行测试"按钮 | 用户 |
| 子任务勾选 | 弹"全流程执行"窗口，6 个 Checkbutton + 必填项状态表 | 用户 |
| 顺序 | 1→6 固定 | 用户 |
| 失败处理 | 遇到失败停止后续子任务 | 用户 |
| 「串口日志」语义 | 开启 SerialTerminalWindow + 整管道运行期间持续记录 | 用户 |
| 「测试项配置」语义 | 按 [order] 通过 telnet 逐条执行 + fuzzy 匹配 + retry | 用户 |
| per-channel 结果文件 | `Cheating_machine_execution_tool/test_results/` 下（独立于老工具路径） | 用户 |
| 范围 | v1 编排器（无程控电源循环 / 无 N 次迭代 / 无 WiFi 验证 / 串行执行） | 用户首条 |

## 改动总览

| 改动 | 新增 / 修改 | 落点 | 关键约束 |
| --- | --- | --- | --- |
| 6 子任务必填项枚举 | 新增 | `src/services/pipeline_orchestrator.py` | 不引入新配置 store；只读现有 store + main UI 状态 |
| 管道编排器 service | 新增 | `src/services/pipeline_orchestrator.py` | 6 个子任务 method；固定 1→6 顺序；遇异常 raise 停管道 |
| 测试项执行 service | 新增 | `src/services/test_item_execution_service.py` | 单条命令：send → 读回 → fuzzy match；per-command retry_times；interval 间隔；per-channel 结果文件 |
| fuzzy_match runner | 新增 | `src/core/fuzzy_match_runner.py` | 移植老工具 [fuzzy_match.py](../../Cheating_machine_execution_tool/Auto_power_on_off_tool/common/fuzzy_match.py) 的 per-segment `!A&&B` 语义，**不改老工具**（AGENTS.md 硬规则） |
| 全流程执行窗口 | 新增 | `line_check_assistant/pipeline_window.py` | 6 行 Checkbutton + 必填项状态表 + 配置链接 + 开始/取消；二次确认弹框 |
| 主界面入口改造 | 修改 | `line_check_assistant/app.py` | `检查并执行测试` 按钮改为弹"全流程执行"窗口；旧 `_start_all_checks` 重命名为 `_run_ping_check`（保留 ping 入口）或合并到子任务 0 之前的预检 |
| 样机参数表路径持久化 | 修改 | `line_check_assistant/sample_upgrade_settings_store.py` | 新增 `parameter_table_path` 字段，pipeline 写参子任务直接读取 |
| 自动上/下电 operation 持久化 | 修改 | `line_check_assistant/sample_upgrade_settings_store.py` | 新增 `power_operation` 字段（"up" / "down"），pipeline 上下电子任务直接读取 |
| 单测 | 新增 | `tests/test_pipeline_orchestrator.py` `tests/test_test_item_execution_service.py` `tests/test_fuzzy_match_runner.py` | mock 外部 IO；保护子任务依赖 / 失败传播 / fuzzy 边界 |
| 文档同步 | 修改 | `DEVELOPMENT_LOG.md` `PROJECT_STATUS.md` `ACCEPTANCE_BASELINE.md` `line_check_assistant_README.md` | 新功能走 SKILL §3 文档矩阵 |

## 实现方案

### 1. 子任务必填项枚举（`src/services/pipeline_orchestrator.py`）

每个子任务定义一个 dataclass：

```python
@dataclass(frozen=True)
class SubTaskStatus:
    name: str                # 窗口显示名
    code: str                # 主日志前缀
    ready: bool              # True = 必填项齐全
    summary: str             # 单行摘要（绿色或红字）
    missing: tuple[str, ...] # 缺项字段名（红字）
    config_target: str       # 「去配置」按钮跳哪个已有窗口
```

枚举函数（按子任务）：

1. `evaluate_power_cycle(store, channels)` —
   - 必填：`power_serial_port`（已有 main UI）、`power_operation`（up/down，待新增持久化）
   - 摘要：`COM={port} / 操作={op} / {N 通道} 通道已勾选`
   - config_target：主界面"程控电源串口" + 跳"自动上/下电"窗口

2. `evaluate_sample_upgrade(store, channels)` —
   - 必填：`upgrade_type` ∈ {页面, 全包}、`firmware_path`、`superuser`/`superuser_password`
   - 页面模式额外：`restore_factory` (bool)
   - 全包模式额外：`tftp_transfer` ∈ {Tftp指令, Tftp Put}、`parallel_count` 1-8
   - 摘要：`升级方式={方式} / 固件={basename} / 凭据={user}`

3. `evaluate_sample_parameter_write(store, channels)` —
   - 必填：`parameter_table_path`（待新增持久化）、`superuser`/`superuser_password`、`parameter_parallel_count` (默认 1)
   - 可选：`parameter_clear_parameters`、`parameter_exit_aging` (bool)
   - 摘要：`参数表={basename or 未选} / 超级用户={user} / 写参并行={N} / 选项=…`

4. `evaluate_onu_registration(store)` —
   - 必填：`olt_ip`、`olt_username`、`olt_password`
   - 摘要：`OLT={ip} / 用户={user} / 密码=(已设置)`

5. `evaluate_serial_terminal(channels, log_dir)` —
   - 必填：≥ 1 个已勾选通道
   - 摘要：`终端数={N} / 日志目录={path}`

6. `evaluate_test_item_execution(config, store)` —
   - 必填：`test_project_config.ini` 存在；`[telnet].user` / `[telnet].password` 非空；`[order].items` 非空
   - 摘要：`ini={存在/缺失} / [order]={N} 条 / Telnet 凭据={已填/未填}`

### 2. fuzzy_match runner（`src/core/fuzzy_match_runner.py`）

**移植**老工具 [fuzzy_match.py](../../Cheating_machine_execution_tool/Auto_power_on_off_tool/common/fuzzy_match.py) 的 per-segment `!A&&B` 语义：

```python
def match_expected(result: str, expected: str) -> bool:
    """per-segment && + per-segment ! 否定；空段跳过。
    
    移植自老工具 fuzzy_match.py（Fuzzy_Match + Fuzzy_Match_01）。
    不实现 IPv6 特殊分支（老工具中仅 tcapi get WanInfo_Entry 用到，不在新工具范围）。
    """
    for negate, segment in _split_expected(expected):
        if not segment:
            continue
        if negate:
            if re.search(segment, result):
                return False
        else:
            if segment not in result:
                return False
    return True
```

**单测**（`tests/test_fuzzy_match_runner.py`）：

- 单段肯定：in / not in
- 单段否定：re.findall / not findall
- 多段 `&&` 全肯定
- 多段 `&&` 全否定
- 混合 `!A&&B&&!C`
- 空段 `!&&A&&` 跳过空段
- IPv6 边界（不实现 → 显式 false + 文档说明）
- 长 result 性能（≥ 10 KiB 不退化）

### 3. 测试项执行 service（`src/services/test_item_execution_service.py`）

```python
@dataclass(frozen=True)
class TestItemRunRequest:
    channel: ChannelConfig
    order: OrderConfig
    telnet: TelnetSettings
    retry_interval_seconds: int        # from [order].command_fail_retry_interval_time
    log_path: Path                     # per-channel 结果文件


@dataclass(frozen=True)
class TestItemRunResult:
    channel_section: str
    total: int                         # [order] 命令条数
    passed: int
    failed: int
    log_path: Path


def run_test_item_execution(req: TestItemRunRequest, emit: Callable[[str], None]) -> TestItemRunResult:
    """按 [order] 顺序执行 telnet 命令 + fuzzy 匹配 + per-command retry。
    
    单台样机的执行流程（与写参流水线共用网络/telnet 前置）：
      1. prepare_network(channel.adapter_alias, channel.network_card_ip, ...)
      2. TelnetSession(bind_ip, device_host, port=telnet.port)
      3. 登录：按 telnet.input_user_flag / input_password_flag / login_success_flag
      4. for item in order.items:
           send_line(item.command)
           读回 (sleep 1-3s + read_very_eager 等到 1s 静默)
           if not match_expected(result, item.expected):
             sleep(retry_interval_seconds)
             retry up to item.retry_times
         emit 主日志
      5. close telnet + 写 per-channel 结果文件
      6. 返回 TestItemRunResult
    """
```

**关键实现细节**：

- **TelnetSession 复用** — 不再独立写 telnet 客户端；用 `src/core/telnet_transport.py:TelnetSession`，登录阶段按 `telnet.input_user_flag` / `input_password_flag` / `login_success_flag` 调 `wait_for_any` + `send_line`。
- **写参前置重用** — 启用网卡 + 切静态 IP 用 `network_ops.prepare_network_for_sample`；与样机参数写共用（避免重复代码）。
- **读回策略** — 仿老工具 `execute_read_until`：先 `read_very_eager` 清残留；send_line → 循环 `read_very_eager` 直到 "连续 1 秒无新数据" 视为完成；总超时 `= item.retry_times * 5s`。
- **重试策略** — 每条命令独立重试 `retry_times` 次；每次重试前 `sleep(retry_interval_seconds)`；命中后立刻进入下一条；最后重试仍失败 → 标记失败但**不抛**，让编排器决定是否继续。
- **结果文件格式** — `Cheating_machine_execution_tool/test_results/device_{section}_command_results_{YYYYMMDD_HHMMSS}.log`，每行：
  ```
  [2026-07-20 15:30:45] === 通道 channel_2 (VLAN115) 开始测试 ===
  [2026-07-20 15:30:45] TX /userfs/bin/ponmgr gpon get info
  [2026-07-20 15:30:46] RX ... <command result> ...
  [2026-07-20 15:30:46] MATCH OK 期望: 'ONU State: O5'
  [2026-07-20 15:30:46] === 通道 channel_2 (VLAN115) 全部完成：9/9 匹配 ===
  ```
- **并行** — 串行（与 sample_parameter 默认并行 1 一致；测试项执行无 UBUS 抢网卡问题但仍保持最稳）。

**单测**（`tests/test_test_item_execution_service.py`）：

- 单条命令：发送 + 读回 + 匹配成功
- 单条命令：匹配失败 → 重试 N 次 → 全部失败 → 不抛
- 单条命令：匹配失败 → 重试第 K 次成功
- 多段 `!A&&B`：边界用例
- 网络准备失败：抛 RuntimeError
- telnet 登录失败：抛 RuntimeError
- per-channel 结果文件路径正确 + 内容含主日志期望字段
- 主日志按 `[order]` 顺序输出 N 条 TX / 读回 / 匹配结果

### 4. 管道编排器 service（`src/services/pipeline_orchestrator.py`）

```python
@dataclass(frozen=True)
class PipelineRequest:
    enabled_subtasks: set[str]         # 6 个子任务 code
    channels: list[ChannelConfig]
    power_operation: str               # "up" / "down"
    power_serial_port: str
    upgrade_settings: SampleUpgradeSettings
    onu_registration: OnuRegistrationConfig
    test_project_config: TestProjectConfig
    serial_log_dir: Path


class PipelineOrchestrator:
    def __init__(self, request: PipelineRequest, emit: Callable[[str], None]):
        self.req = request
        self.emit = emit
        self._stop = threading.Event()
    
    def run(self) -> dict[str, Any]:
        """按 1→6 顺序执行勾选子任务；遇异常 raise 停管道。
        
        返回: {subtask_code: result_dict or error_dict}
        """
        results: dict[str, Any] = {}
        for code in PIPELINE_ORDER:        # ["power_cycle", "sample_upgrade", ...]
            if code not in self.req.enabled_subtasks:
                continue
            if self._stop.is_set():
                self.emit(f"[管道] 已请求停止，跳过子任务 {code}")
                break
            self.emit(f"[管道] === 开始子任务 {SUBTASK_LABELS[code]} ===")
            try:
                result = self._run_subtask(code)
                results[code] = {"ok": True, "result": result}
            except Exception as exc:
                self.emit(f"[管道] 子任务 {code} 失败：{exc}")
                results[code] = {"ok": False, "error": str(exc)}
                if code != "serial_terminal":     # 串口日志不算致命
                    raise
        return results
    
    def request_stop(self) -> None:
        self._stop.set()
    
    def _run_subtask(self, code: str):
        if code == "power_cycle":
            return self._run_power_cycle()
        elif code == "sample_upgrade":
            return self._run_sample_upgrade()
        elif code == "sample_parameter_write":
            return self._run_sample_parameter_write()
        elif code == "onu_registration":
            return self._run_onu_registration()
        elif code == "serial_terminal":
            return self._run_serial_terminal()
        elif code == "test_item_execution":
            return self._run_test_item_execution()
```

**复用现有子任务**：

- `power_cycle` → 现有 `_direct_control_power_supply`（主程序里"自动上/下电"按钮的实现路径）
- `sample_upgrade` → 现有 `_start_page_upgrade` / `_start_full_upgrade`（按 `upgrade_type` 分发）
- `sample_parameter_write` → 现有 `_start_sample_parameter_write`（复用 9 步自然顺序）
- `onu_registration` → 现有 `_open_onu_registration` 路径里的 `query_unregistered_onus` + `register_unregistered_onus`（**仅跑查询 + 自动注册所有未注册 ONU**；不让用户中途点）
- `serial_terminal` → 现有 `SerialTerminalWindow` + `serial_session_manager`；管道运行期间 keep open
- `test_item_execution` → 新建 service（本 plan 第 3 节）

**单测**（`tests/test_pipeline_orchestrator.py`）：

- 6 子任务全部勾选 → 按 1→6 顺序执行（mock 验证调用顺序）
- 仅勾选子任务 N → 仅执行 N（其它跳过）
- 子任务 3 失败 → 4/5/6 不执行
- 子任务 5（串口）失败 → 6 仍执行（不算致命）
- `request_stop()` 在子任务中间 → 后续子任务跳过
- 主日志输出含 `=== 开始子任务 ===` / `=== 结束子任务 ===` / 失败行
- 各子任务必填项校验：缺项时主日志明确指出

### 5. 全流程执行窗口（`line_check_assistant/pipeline_window.py`）

```python
class PipelineWindow:
    """弹窗：6 子任务 Checkbutton + 必填项状态表 + 配置链接 + 开始/取消。"""
    
    SUBTASK_ROWS = [
        # (code, label, sub_window_method, default_checked)
        ("power_cycle", "1. 自动上/下电", "_open_power_control", True),
        ("sample_upgrade", "2. 样机升级", "_open_sample_upgrade", False),
        ("sample_parameter_write", "3. 写样机参数", "_open_sample_parameter_writer", False),
        ("onu_registration", "4. ONU 注册", "_open_onu_registration", False),
        ("serial_terminal", "5. 串口日志（管道期间持续记录）", "_open_serial_terminal", True),
        ("test_item_execution", "6. 测试项配置（[order] 执行）", "_open_test_item_config", False),
    ]
    
    def __init__(self, parent: LineCheckAssistant):
        self.parent = parent
        self._check_vars: dict[str, BooleanVar] = {}
        self._status_labels: dict[str, ttk.Label] = {}
        ...
    
    def _build(self) -> None:
        """6 行 + 底部开始/取消。"""
        for code, label, _, default in self.SUBTASK_ROWS:
            var = BooleanVar(value=default)
            self._check_vars[code] = var
            ttk.Checkbutton(row, text=label, variable=var, command=self._refresh_status).grid(...)
            status = ttk.Label(row, text="...", style="Hint.TLabel")
            self._status_labels[code] = status
            ttk.Button(row, text="去配置", command=...).grid(...)
        self._refresh_status()    # 启动时计算
    
    def _refresh_status(self) -> None:
        """按当前勾选状态 + 各 store + main UI 状态，计算每行必填项摘要。"""
        statuses = compute_all_subtask_statuses(self.parent)
        for code, status in statuses.items():
            label = self._status_labels[code]
            label.config(text=status.summary, foreground=("green" if status.ready else "red"))
            if status.missing:
                label.config(text=f"{status.summary} | 缺: {', '.join(status.missing)}")
    
    def _on_start(self) -> None:
        """二次确认 + 启动 worker。"""
        # 1. 收集勾选子任务
        # 2. 校验所有勾选子任务 ready=True（否则弹错误）
        # 3. messagebox.askyesno 二次确认（含勾选清单 + 各子任务状态）
        # 4. 后台线程跑 PipelineOrchestrator.run()
        # 5. 主执行日志实时输出 worker 输出
```

**UI 细节**：

- 窗口大小 `720x520`；modal（`transient(parent)` + `grab_set()`）
- 6 行用 `ttk.Frame` + grid；每行 4 列：`Checkbutton` / `Label`（摘要） / `去配置`按钮 / 隐藏的 `missing` Label
- 「去配置」按钮调 parent 的对应子窗口（`parent._open_*`），不重启 pipeline 窗口
- 底部：`[开始执行]`（主按钮）+ `[取消]`（关闭窗口）
- 启动后：勾选 + 按钮禁用，主执行日志进入实时输出；完成/失败后弹消息框，按钮恢复

### 6. 主界面入口改造（`line_check_assistant/app.py`）

- `_start_all_checks` → 改为 `_open_pipeline_window`（只做弹窗）：
  ```python
  def _start_all_checks(self) -> None:
      """点击后弹「全流程执行」窗口；具体子任务在窗口内勾选。"""
      if self.pipeline_window is not None and self.pipeline_window.winfo_exists():
          self.pipeline_window.deiconify()
          self.pipeline_window.lift()
          return
      self.pipeline_window = PipelineWindow(self)
  ```
- `self.pipeline_window` 加入 `__init__` 的 None 初始化
- 旧 ping 检查逻辑（`_run_checks` / `_check_worker`）保留作为子任务 1（自动上/下电）内部调用的一部分（ping 是上电后必做的步骤），不删除
- 不影响其它按钮（"自动上/下电"独立按钮、"检查当前通道"等保留）

### 7. 持久化字段新增

**`line_check_assistant/sample_upgrade_settings_store.py`**：

- `SampleUpgradeSettings` 新增字段：
  - `power_operation: str = "up"`（"up" 或 "down"）
  - `parameter_table_path: str = ""`
- `_load_sample_upgrade_settings` / `_dump_sample_upgrade_settings` 同步
- 老 ini 兼容（缺字段回退默认）

### 8. 测试项执行子任务与现有 write-parameter 的边界

测试项执行（sub-task 6）与写样机参数（sub-task 3）**共用 TelnetSession 协议 + 网络前置**，但：

| 维度 | 写样机参数 | 测试项执行 |
| --- | --- | --- |
| 协议 | UBUS 启用 telnet → 工厂模式 | 直接 telnet（设备已就绪） |
| 命令 | 15 项 ppctl set/get | [order] 任意命令 |
| 期望 | set/get 一致性 | fuzzy 匹配 |
| 重试 | per-item 3 次 | per-command `retry_times` |
| 退出工厂模式 | 必做 | 不做 |
| 工厂模式网段切换 | 必做 | 不做 |

因此两个子任务**不可合并**；测试项执行 service 独立新建。

### 9. 测试基线

- 现有 313 项 + 新增 ≈ 25-30 项（fuzzy ≈ 10 + test_item_execution ≈ 12 + pipeline ≈ 10）
- `verify_baseline.py` 必须 ALL CHECKS PASSED（含 py_compile + 全部 unittest + §1.3/§1.4 grep）

## 改动文件清单

| 路径 | 改动 |
| --- | --- |
| `Cheating_machine_execution_tool/src/core/fuzzy_match_runner.py` | 新增 |
| `Cheating_machine_execution_tool/src/services/test_item_execution_service.py` | 新增 |
| `Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py` | 新增 |
| `Cheating_machine_execution_tool/src/services/__init__.py` | 新增 re-export（与既有模式一致） |
| `Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py` | 新增 |
| `Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py` | 新增 2 字段（power_operation, parameter_table_path） |
| `Cheating_machine_execution_tool/line_check_assistant/app.py` | `_start_all_checks` 改为弹窗；新增 `self.pipeline_window`；不删 `_run_checks` |
| `Cheating_machine_execution_tool/tests/test_fuzzy_match_runner.py` | 新增（≈ 10 项） |
| `Cheating_machine_execution_tool/tests/test_test_item_execution_service.py` | 新增（≈ 12 项） |
| `Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py` | 新增（≈ 10 项） |
| `Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py` | 加 2 项：power_operation / parameter_table_path 持久化 |
| `Cheating_machine_execution_tool/line_check_assistant_README.md` | 「检查并执行测试」段重写为「全流程执行」说明 |
| `Cheating_machine_execution_tool/PROJECT_STATUS.md` | 能力矩阵行更新；「已完成」段新增「全流程执行编排器」条目 |
| `Cheating_machine_execution_tool/ACCEPTANCE_BASELINE.md` | 新增 §2.12「全流程执行编排器」；状态初始「已实现未验收」 |
| `Cheating_machine_execution_tool/DEVELOPMENT_LOG.md` | 顶部追加本轮条目（按 SKILL §4 模板） |
| `Cheating_machine_execution_tool/scripts/verify_baseline.py` | `PY_COMPILE_FILES` 追加 3 个新文件路径 |

## 验证方法

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool

# 1. py_compile 全量（含新文件）
python -m py_compile `
  src\core\fuzzy_match_runner.py `
  src\services\test_item_execution_service.py `
  src\services\pipeline_orchestrator.py `
  line_check_assistant\pipeline_window.py `
  line_check_assistant\sample_upgrade_settings_store.py `
  line_check_assistant\app.py

# 2. 完整单测（应 Ran ~343 tests ... OK，原 313 + 新增 30）
python -m unittest discover -s tests -v

# 3. verify_baseline 门禁（强制）
python scripts\verify_baseline.py     # 应 ALL CHECKS PASSED, exit 0
```

## 验收要求（不破坏既有不变量）

- `AGENTS.md` §1.3 8 条 MUST_EXIST grep 全部命中
- `AGENTS.md` §1.4 `0.0.0.0` 在 `src/core/tftp_transport.py` / `src/core/telnet_transport.py` 仍不出现
- `Auto_Power_On_Off_Tool.py` 等老工具源码**不改**（AGENTS.md 硬规则）
- `build/` `dist/` `logs/` `.venv/` **不改**
- `verify_baseline.py` 全绿
- 真机验收：本轮不强制（用户首条要求"实现"，未要求验收；状态标签 = 已实现未验收）

## 后续待办（不在本轮范围）

- 真实样机跑通全流程（6 子任务各 1 通道 → 各 6 通道）
- 编排器多通道并行（按子任务 1-8 现场上调）
- WiFi 验证子任务（openwrt 方案 SSID 连接）
- test_number 循环 + 每轮程控电源上下电
- 钉钉/邮件上报
- 取消信号跨子任务传播（当前 `request_stop` 已埋点，但子任务内部未必响应）
- 编写 `.claude/skills/line-check-dev/` 下的 pipeline 详细 SKILL 文档
