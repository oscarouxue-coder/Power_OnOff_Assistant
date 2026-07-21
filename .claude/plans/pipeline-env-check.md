# 「全流程执行」新增「环境线路检查」子任务

## 背景

用户在主界面点击「检查并执行测试」→ 弹「全流程执行」窗口,目前 6 个子任务(1→6)按固定顺序串行执行。
2026-07-20 反馈:在最前面(1. 自动上/下电 之前)需要增加一项「环境线路检查」,作为整个管道的预校验门。

**用户决策(AskUserQuestion 已确认):**
1. **检查范围**:Ping + 必填项预校验(更严格)。复用现有 `run_line_check()` + `ChannelConfig` 的 `vlan_name / adapter_alias / network_card_ip / device_manage_ip` 校验。
2. **失败处理**:致命失败 → 终止后续子任务。
3. **去配置按钮**:调起现有网络配置页(主界面顶部 VLAN / IP 区)。app 暂无专用 `_open_network_config()` 方法,需新增一个最小占位实现。

## 目标

- SUBTASK_CODES 从 6 项扩到 7 项,「环境线路检查」放在首位,1→6 编号顺延。
- 必填项:`≥1 已勾选通道` + 每通道 `vlan_name / adapter_alias / network_card_ip / device_manage_ip` 全部非空(复用 `_validate_channels()` 校验逻辑)。
- 执行逻辑:逐通道 ping + 网络准备(同旧 `_check_worker`),全部通过才算成功。
- 默认勾选(开箱即用)。
- 致命失败(默认,与其他子任务同款)。
- 「去配置」按钮路由到新增的 `_open_network_config()` 占位方法。

## 设计要点

### 1. SUBTASK_CODES 顺序调整

```python
SUBTASK_CODES: Tuple[str, ...] = (
    "env_check",                # ← 新增,排首位
    "power_cycle",              # 原 1 → 新 2
    "sample_upgrade",           # 原 2 → 新 3
    "sample_parameter_write",   # 原 3 → 新 4
    "onu_registration",         # 原 4 → 新 5
    "serial_terminal",          # 原 5 → 新 6
    "test_item_execution",      # 原 6 → 新 7
)
```

但用户在意「编号」是 UI 显示,不是 SUBTASK_CODES 的位置——SUBTASK_CODES 是定序的真正源头,UI label 要同步从「1. 自动上/下电」改成「2. 自动上/下电」,以此类推。

```python
SUBTASK_LABELS: dict[str, str] = {
    "env_check": "1. 环境线路检查",
    "power_cycle": "2. 自动上/下电",
    "sample_upgrade": "3. 样机升级",
    "sample_parameter_write": "4. 写样机参数",
    "onu_registration": "5. ONU 注册",
    "serial_terminal": "6. 串口日志（管道期间持续记录）",
    "test_item_execution": "7. 测试项配置（[order] 执行）",
}

SUBTASK_CONFIG_TARGETS: dict[str, str] = {
    "env_check": "_open_network_config",   # ← 新增占位
    "power_cycle": "_open_power_control",
    ...
}
```

### 2. 必填项评估 `_summarize_env_check`

```python
def _summarize_env_check(ctx: PipelineContext) -> SubTaskStatus:
    """1. 环境线路检查:每通道 vlan_name / adapter_alias / network_card_ip / device_manage_ip 非空。"""
    app = ctx.app
    channels = ctx.enabled_channels
    if not channels:
        return SubTaskStatus(
            code="env_check",
            ready=False,
            summary="0 通道已勾选",
            missing=("已勾选通道",),
        )
    missing_per_channel: list[str] = []
    bad_channels: list[str] = []
    for channel in channels:
        bad: list[str] = []
        if not channel.vlan_name.strip():
            bad.append("VLAN")
        if not channel.adapter_alias.strip():
            bad.append("网卡")
        if not channel.network_card_ip.strip():
            bad.append("PC 静态 IP")
        if not channel.device_manage_ip.strip():
            bad.append("样机管理 IP")
        if bad:
            bad_channels.append(f"{channel.section}({'/'.join(bad)})")
    summary = f"{len(channels)} 通道已勾选"
    if bad_channels:
        summary += f" / 缺配置:{', '.join(bad_channels)}"
    return SubTaskStatus(
        code="env_check",
        ready=not bad_channels,
        summary=summary,
        missing=tuple(f"通道 {bc} 缺配置" for bc in bad_channels),
    )
```

注:此处**不**做 ping(那是执行时才做的)。状态评估只校验字段完整性。

### 3. 执行 `_run_env_check`

```python
def _run_env_check(self) -> None:
    """1. 环境线路检查:复用 network_ops.run_line_check() 逐通道 ping。

    致命失败:任一通道 ping 不通 → 整个管道停止(网络不通则后续子任务均无意义)。
    """
    from line_check_assistant.network_ops import run_line_check
    channels = self.ctx.enabled_channels
    if not channels:
        raise RuntimeError("已勾选通道为空,无法执行环境线路检查")
    total = len(channels)
    passed = 0
    failed: list[str] = []
    for index, channel in enumerate(channels, start=1):
        if self.ctx.stop_event.is_set():
            self.emit(f"[环境检查] 已请求停止,跳过 {channel.section}")
            break
        self.emit(
            f"[环境检查] ({index}/{total}) {channel.section} "
            f"VLAN={channel.vlan_name} 网卡={channel.adapter_alias} "
            f"PC IP={channel.network_card_ip} → 样机 {channel.device_manage_ip}"
        )
        try:
            result = run_line_check(
                channel.adapter_alias,
                channel.network_card_ip,
                channel.subnet_mask,
                channel.device_manage_ip,
            )
        except Exception as exc:  # 网络准备本身就可能抛(网卡不存在等)
            self.emit(f"[环境检查] {channel.section} 启动失败:{exc}")
            failed.append(channel.section)
            continue
        if result.ok:
            passed += 1
            self.emit(f"[环境检查] {channel.section} 通过:{result.message}")
        else:
            failed.append(channel.section)
            self.emit(f"[环境检查] {channel.section} 失败:{result.message}")
            if result.output.strip():
                for line in result.output.strip().splitlines():
                    self.emit(f"    {line}")
    if failed:
        raise RuntimeError(f"环境线路检查失败:{len(failed)}/{total} 通道不通 ({', '.join(failed)})")
    self.emit(f"[环境检查] 完成:{passed}/{total} 通道全部 ping 通")
```

需要把 `_run_env_check` 加进 `_run_subtask` 的 dict。

### 4. 默认勾选调整

[pipeline_window.py:130](../../Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py#L130):

```python
# 旧
default_checked = code in {"power_cycle", "serial_terminal", "test_item_execution"}
# 新:加 env_check
default_checked = code in {"env_check", "power_cycle", "serial_terminal", "test_item_execution"}
```

### 5. 主程序占位 `_open_network_config`

[line_check_assistant/app.py](../../Cheating_machine_execution_tool/line_check_assistant/app.py) 新增一个方法(放在 `_open_power_control` 旁边):

```python
def _open_network_config(self) -> None:
    """「全流程执行」窗口中「环境线路检查」行的「去配置」按钮入口(2026-07-20 新增)。

    网络配置目前内嵌在主界面顶部 VLAN / IP 区,没有独立子窗口。
    这里:最小化全流程执行窗口 + 把主界面拉到前台 + emit 一行提示,
    操作员在主界面顶部左侧「网络配置」卡片编辑 VLAN / 网卡 / PC IP / 样机 IP。
    """
    if self.pipeline_window is not None and self.pipeline_window.winfo_exists():
        self.pipeline_window.withdraw()  # 隐藏(不销毁),下次「检查并执行测试」会再拉起
    self.deiconify()
    self.lift()
    self.focus_force()
    self._log("请在主界面顶部 VLAN / 网卡 / IP 卡片编辑网络配置;完成后再次点击「检查并执行测试」。")
```

### 6. PipelineContext 可选:加 ping 超时配置

考虑过加 `ping_timeout_seconds` 到 `PipelineContext`,但现有 `run_line_check()` 的 `settle_seconds=2.0` 是写死的,且改动会涉及 `network_ops` 接口签名。**v1 范围内不引入**,沿用现有 `run_line_check` 默认参数;后续如需可调,另开一轮。

## 实施步骤

按依赖顺序串行:

1. **`pipeline_orchestrator.py`**:
   - `SUBTASK_CODES` 加 `env_check` 在首位。
   - `SUBTASK_LABELS` 加 `"env_check": "1. 环境线路检查"`,其余 5 个 key 的 label 编号 1→2 ... 5→6 ... 6→7。
   - `SUBTASK_CONFIG_TARGETS` 加 `"env_check": "_open_network_config"`。
   - 加 `_summarize_env_check()` 函数 + 注册到 `_SUMMARIZERS`。
   - 加 `_run_env_check()` 方法 + 加进 `_run_subtask` dict。
2. **`app.py`**:
   - 新增 `_open_network_config()` 占位方法(放在 `_open_power_control` 旁边)。
3. **`pipeline_window.py`**:
   - `_build_row` default_checked 加 `env_check`。
4. **`tests/test_pipeline_orchestrator.py`**:
   - 已有 26 项测试中,所有涉及 label 编号、必填项的测试需更新(枚举从 6 → 7)。
   - 新增 `env_check` 评估测试(`≥1 通道 / 缺 VLAN / 缺 IP / 全齐`)。
   - 新增 `_run_env_check` 执行测试(全通过 / 任一失败抛 PipelineError / stop_event 中断)。
5. **`tests/test_pipeline_window.py`**:
   - 静态断言: `_build_row` 的 default_checked 包含 `env_check`(可选,如不引入也能保留 2 项)。
6. **`scripts/verify_baseline.py`**:
   - 不需要改(没有新文件、新 grep 不变)。
7. **文档同步**:
   - `DEVELOPMENT_LOG.md` 新增一条「环境线路检查子任务」条目。
   - `PROJECT_STATUS.md` 能力矩阵行更新(6 → 7 子任务)。
   - `ACCEPTANCE_BASELINE.md` §2.12 更新(7 个子任务 + 致命失败规则)。
   - `line_check_assistant_README.md` 「全流程执行窗口」段:6 → 7 子任务、新增「环境线路检查」描述。

## 不在范围内(v1 之后再说)

- ping 超时 / 重试次数配置(沿用 `run_line_check` 默认)。
- 并行 ping 多通道(目前顺序)。
- 把网络配置做成独立子窗口(目前占位)。
- 「环境检查」非致命化选项(目前固定致命,与 1/2/3/4/7 一致)。

## 验证方法

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m py_compile src\services\pipeline_orchestrator.py line_check_assistant\pipeline_window.py line_check_assistant\app.py
python -m unittest discover -s tests -p "test_pipeline_orchestrator.py" -v
python -m unittest discover -s tests -p "test_pipeline_window.py" -v
python scripts\verify_baseline.py
```

预期:
- py_compile OK。
- `test_pipeline_orchestrator.py` 原 26 + 新增 ≥ 4 项全绿。
- `test_pipeline_window.py` 2 项仍 OK。
- `verify_baseline.py` `ALL CHECKS PASSED`(376 + 新增 → ≥ 380 项单测全绿)。

## 风险与回滚

- 风险:`SUBTASK_LABELS` 编号 1→2 ... 6→7 是大量 UI 文案改动,但都是机械替换;若漏改某处,UI 显示会不一致——靠测试断言编号串守门。
- 回滚:本轮全部代码改动可在一个 git commit 内回滚;不动 AGENTS.md / 既有测试断言 / 旧工具源码。
- 既有用户截图里 `1. 自动上/下电` 会变成 `2. 自动上/下电`,需在 `CHANGELOG` / 内部沟通里告知。