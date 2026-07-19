# 写样机参数 — MAC 前缀同批固定 + 清空参数可选 + 退出老化选项

## 背景

用户在 `ACCEPTANCE_BASELINE.md` §2.7 / §2.8 的基础上提出 3 项改动：

1. **同批生成参数表的 MAC 前 6 位（OUI）固定**：现在 `generate_parameter_records` 每条记录独立生成一个随机 MAC（`_unique_local_mac` 每次都重新跑 `secrets.token_bytes(6)`），导致同一批 N 条记录的 MAC 完全不同。用户希望同批 MAC 的前 3 字节（OUI）一致，后 3 字节唯一（典型场景：N 张同型号样机使用同一 OUI，最后 3 字节区分）。
2. **`ppctl clear` 由可选项控制**：现在 [src/services/sample_parameter_service.py:258-260](Cheating_machine_execution_tool/src/services/sample_parameter_service.py#L258-L260) 在工厂模式二次登录成功后无条件下发 `ppctl clear`。这是破坏性操作（清空 ppctl 表），用户希望默认不勾选，需要操作员明确勾选才下发。
3. **新增「退出老化」选项**：勾选后在工厂模式二次登录成功后、`ppctl clear` 之前下发 `ppctl set AGING_STATE=1`。语义由设备固件定义：选项名 `退出老化` 对应命令 `ppctl set AGING_STATE=1`，由用户现场经验确认。

## 改动总览

| 改动 | 落点 | 行为变化 |
| --- | --- | --- |
| MAC OUI 同批固定 | `src/core/sample_parameter_table.py` | 同批记录前 3 字节一致；后 3 字节仍随机唯一 |
| `ppctl clear` 可选 | `SampleParameterWriteRequest` + service 流水线 | 默认不下发；勾选才下发 |
| 「退出老化」可选 | `SampleParameterWriteRequest` + service 流水线 | 默认不下发；勾选才下发 |
| UI 入口 | `line_check_assistant/app.py` 写样机参数窗口 | 2 个 `Checkbutton`；状态持久化到 `sample_upgrade_settings.ini` |
| 持久化 | `line_check_assistant/sample_upgrade_settings_store.py` | 新增 `parameter_clear_parameters`、`parameter_exit_aging` |
| 测试 | `tests/test_sample_parameter_*.py` | 改旧测（补 `clear_parameters=True`）+ 加新测（同 OUI、两个新选项的开关组合） |

## 实现方案

### 改动 1 — MAC OUI 同批固定（`src/core/sample_parameter_table.py`）

把 OUI 的生成时机从"每条记录"挪到"整批"，`_unique_local_mac` 改为接收 3 字节 OUI。

```python
def generate_parameter_records(vlans, template):
    ...
    seen_mac: set[str] = set()
    # 同批 MAC 前 3 字节（OUI）固定,后 3 字节唯一（每台样机一段 NIC 标识）。
    # 一次性生成 OUI,保持本地管理 + 单播的 bit 设置
    # （首字节 bit1=1 本地管理 / bit0=0 单播,等价于原 _unique_local_mac 的处理）。
    mac_oui = bytearray(secrets.token_bytes(3))
    mac_oui[0] = (mac_oui[0] & 0xFE) | 0x02
    for index, vlan in enumerate(normalized_vlans, start=2):
        ...
        values["MAC"] = _unique_local_mac(mac_oui, seen_mac)


def _unique_local_mac(oui: bytearray, seen: set[str]) -> str:
    for _ in range(1000):
        nic = bytearray(secrets.token_bytes(3))
        raw = bytes(oui) + bytes(nic)
        value = ":".join(f"{item:02X}" for item in raw)
        if value not in seen:
            seen.add(value)
            return value
    raise RuntimeError("随机 MAC 生成碰撞次数过多，请重新生成。")
```

不引入 `ParameterGenerationTemplate` 的新字段——OUI 由程序随机生成,与现有 SN/XPON SN/SSID 后缀生成风格一致；用户要求"前 6 位相同"未要求可配置。

### 改动 2 — `SampleParameterWriteRequest` 新增 2 字段

[src/models/sample_parameter_models.py:52-66](Cheating_machine_execution_tool/src/models/sample_parameter_models.py#L52-L66)：

```python
@dataclass(frozen=True)
class SampleParameterWriteRequest:
    vlan: str
    serial_port: str
    initial_username: str
    initial_password: str
    values: Mapping[str, str]
    bind_ip: str = ""
    device_host: str = ""
    ubus_port: int = 80
    factory_bind_ip: str = ""
    factory_device_host: str = ""
    # 写参流水线可选行为：
    #   clear_parameters=True → 工厂模式二次登录成功后下发 ppctl clear(默认 False,避免误清空)
    #   exit_aging=True      → 二次登录成功后下发 ppctl set AGING_STATE=1(默认 False,正常老化测试默认关闭)
    clear_parameters: bool = False
    exit_aging: bool = False
```

两个字段默认 `False`,与用户"勾选才下发"的语义一致,也是从当前默认行为（无条件 `ppctl clear`）的**破坏性变更**——需要同步更新现有断言 `ppctl clear` 必现的测试。

### 改动 3 — `run_parameter_write_pipeline` 条件化下发

[src/services/sample_parameter_service.py:255-261](Cheating_machine_execution_tool/src/services/sample_parameter_service.py#L255-L261) 的"二次登录成功 → ppctl clear → 15 项写参"段改为：

```python
if not _login(session, FACTORY_USERNAME, FACTORY_PASSWORD, cancel, sleep_fn):
    return SampleParameterItemResult(request, False, f"{request.vlan} 写参失败：工厂模式二次登录失败。")
# 二次登录成功后,按用户选项决定是否下发两个准备命令。
# 顺序：退出老化 → 清空参数 → 15 项 ppctl set/get。
# 两者都关闭时主执行日志分别输出「关闭，跳过」,与项目规则 12 「成功 / 跳过」一致。
if getattr(request, "exit_aging", False):
    _send_stage(session, "ppctl set AGING_STATE=1", False, emit, request.vlan)
    emit(f"{request.vlan} 写参：已下发退出老化命令。")
else:
    emit(f"{request.vlan} 写参：退出老化：关闭，跳过。")
if getattr(request, "clear_parameters", False):
    _send_stage(session, "ppctl clear", False, emit, request.vlan)
else:
    emit(f"{request.vlan} 写参：清空参数：关闭，跳过。")
written = 0
...
```

关键不变量：
- 两个新命令都在"工厂模式二次登录成功"之后、"15 项 ppctl set"之前；与既有"先退出老化再清空再写新值"的语义一致。
- `getattr(request, "exit_aging", False)` / `getattr(request, "clear_parameters", False)` 兜底,避免对旧 `SampleParameterWriteRequest` 实例（不带这俩字段）抛 `AttributeError`——防御性写法,与上轮"派生 IP 失败兜底"风格一致。
- 关闭时不发命令但 emit 一行"关闭，跳过"主程序执行日志,操作员一眼能看出"为什么没有发"。
- 失败语义与既有"步骤名嵌入错误消息"风格一致；如果 `ppctl clear` / `AGING_STATE=1` 失败,会通过 `_send_stage` 抛 `RuntimeError`,被外层 `except Exception` 接住并返回 `SampleParameterItemResult(ok=False, message="VLANxxx 写参异常：...")`,操作员从消息可分辨"是哪一步触发的失败"。
- `finally` 清理块不动；退出工厂模式的 `FACTORY_MODE=0` + `firstboot -yr` 仍然 best-effort。

### 改动 4 — `SampleUpgradeSettings` 新增 2 字段 + 持久化

[line_check_assistant/sample_upgrade_settings_store.py:33-46](Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py#L33-L46)：

```python
@dataclass
class SampleUpgradeSettings:
    ...
    parameter_initial_username: str = ""
    parameter_initial_password: str = ""
    # 写样机参数两个新增可选项的持久化字段,与 parameter_initial_* 同级存到 sample_upgrade_settings.ini。
    parameter_clear_parameters: bool = False
    parameter_exit_aging: bool = False
```

`load` / `save` 同步读写这两个 key（`parser.getboolean` / `"1" if x else "0"`），与 `restore_factory` 同款。

### 改动 5 — UI 增加 Checkbutton + 透传到 Request

[line_check_assistant/app.py](Cheating_machine_execution_tool/line_check_assistant/app.py) 三处：

1. **`__init__`**（紧跟 `parameter_initial_password_var` 之后）新增实例级 `BooleanVar`：
   ```python
   self.parameter_clear_parameters_var = BooleanVar(value=self.sample_upgrade_settings.parameter_clear_parameters)
   self.parameter_exit_aging_var = BooleanVar(value=self.sample_upgrade_settings.parameter_exit_aging)
   ```
   并加入 `_bind_sample_upgrade_autosave` 的 trace_add 列表。

2. **写样机参数窗口**（紧跟 `credential_row` 之后,新建 `option_row`）：两个 `Checkbutton`：
   ```python
   option_row = ttk.Frame(container)
   option_row.pack(fill="x", pady=(0, 8))
   ttk.Checkbutton(option_row, text="清空参数", variable=self.parameter_clear_parameters_var).pack(side="left")
   ttk.Checkbutton(option_row, text="退出老化", variable=self.parameter_exit_aging_var).pack(side="left", padx=(16, 0))
   ```
   不放在 `credential_row` 是因为它已经较满,新行保持可读。

3. **`_start_sample_parameter_write`** 构造 `SampleParameterWriteRequest` 时透传：
   ```python
   requests = [
       SampleParameterWriteRequest(
           ...,
           clear_parameters=bool(self.parameter_clear_parameters_var.get()),
           exit_aging=bool(self.parameter_exit_aging_var.get()),
       )
       for target in preflight.targets
   ]
   ```
   并把确认框文案按实际选中状态动态化（避免描述与实际不符）：
   ```python
   actions = []
   if self.parameter_exit_aging_var.get():
       actions.append("下发退出老化命令（ppctl set AGING_STATE=1）")
   if self.parameter_clear_parameters_var.get():
       actions.append("下发 ppctl clear")
   actions.append("进入工厂模式（FACTORY_MODE=1 + firstboot -yr）")
   actions.append("等待 100 秒")
   actions.append("二次登录")
   actions.append("写入并读回校验全部 15 项参数")
   actions.append("退出工厂模式（FACTORY_MODE=0 + firstboot -yr）")
   summary = "每台会依次：" + " → ".join(actions) + "。\n\n是否继续？"
   messagebox.askyesno("确认批量写样机参数", f"将并行写入 {len(preflight.targets)} 台样机（最多 {parallel_count} 台）：\n{target_text}\n\n{summary}", ...)
   ```

4. **`_current_sample_upgrade_settings`** 把两个 BooleanVar 也带进 dataclass：
   ```python
   return SampleUpgradeSettings(
       ...,
       parameter_clear_parameters=bool(self.parameter_clear_parameters_var.get()),
       parameter_exit_aging=bool(self.parameter_exit_aging_var.get()),
   )
   ```

### 改动 6 — 测试

#### 6.1 `tests/test_sample_parameter_table.py`：新增同 OUI 测试

```python
def test_generate_records_share_same_mac_oui_within_batch(self):
    records = generate_parameter_records(
        ["vlan101", "vlan102", "vlan103", "vlan104", "vlan105"], template()
    )
    # 同一批 5 条记录的 MAC 前 3 字节（OUI）必须一致
    ouis = {":".join(record.values["MAC"].split(":")[:3]) for record in records}
    self.assertEqual(len(ouis), 1, f"OUI should be unified within batch, got {ouis}")
    # 后 3 字节（NIC 标识）必须唯一
    nics = {":".join(record.values["MAC"].split(":")[3:]) for record in records}
    self.assertEqual(len(nics), 5)
    # 首字节 bit1=1(本地管理)bit0=0(单播)不变
    first_octet = int(next(iter(ouis)).split(":")[0], 16)
    self.assertEqual(first_octet & 0x01, 0)
    self.assertEqual(first_octet & 0x02, 0x02)
    # MAC 字符串全列还保持不变
    self.assertEqual(len({record.values["MAC"] for record in records}), 5)
```

既有的 `test_generate_records_are_unique_and_local_unicast` 只断言 MAC 全列唯一 + 首字节位正确,与新行为完全兼容,不需要改。

#### 6.2 `tests/test_sample_parameter_service.py`：现有断言 `ppctl clear` 必现的用例补 `clear_parameters=True`

需要改的用例（每个 `SampleParameterWriteRequest(...)` 末尾加 `clear_parameters=True`）：
- `test_write_reads_back_all_values_and_displays_plaintext`（第 91 行）
- `test_failed_readback_retries_then_reports_failure_and_cleans_up`（第 109 行）
- `test_ppctl_clear_runs_after_factory_relogin_not_before`（第 135 行）
- `test_factory_session_swap_new_session_is_used_for_second_login`（第 206 行）
- `test_cleanup_emits_both_tx_lines_even_when_firstboot_fails`（第 290 行）
- `test_cleanup_reports_factory_mode_failure_when_step_one_fails`（第 337 行）
- `test_cleanup_success_log_unchanged_when_both_steps_succeed`（第 391 行）

`test_factory_session_swap_returns_none_abandons_before_second_login` / `test_factory_session_swap_exception_reports_failure` / `test_cancel_before_start_does_not_enter_factory_mode` 不需要改（它们在二次登录前就放弃,不会到达 `ppctl clear` / `AGING_STATE` 阶段）。

#### 6.3 `tests/test_sample_parameter_service.py`：新增 `clear_parameters` / `exit_aging` 行为测试

新类 `SampleParameterPipelineOptionTests`：

1. `test_clear_parameters_default_off_does_not_send_ppctl_clear`：不传 `clear_parameters`,断言 `ppctl clear` 不在 writes 里；断言主执行日志含"清空参数：关闭，跳过"。
2. `test_clear_parameters_on_sends_ppctl_clear`：传 `clear_parameters=True`,断言 `ppctl clear` 出现一次,断言不含"清空参数：关闭，跳过"。
3. `test_exit_aging_on_sends_aging_state_before_clear_and_writes`：传 `exit_aging=True, clear_parameters=True`,断言 writes 顺序：`AGING_STATE=1` → `ppctl clear` → 15 项 `ppctl set` → `FACTORY_MODE=0`；主日志含"已下发退出老化命令"。
4. `test_exit_aging_off_skips_aging_state`：不传 `exit_aging`,断言 `AGING_STATE` 不在 writes 里；主日志含"退出老化：关闭，跳过"。
5. `test_both_options_off_skips_both_commands`：两个都关闭,断言 `ppctl clear` / `AGING_STATE` 都不下发,15 项 `ppctl set/get` 仍然全部走完并成功。

#### 6.4 `tests/test_app.py`：`test_current_sample_upgrade_settings_*` 两个用例 mock 补齐

`test_current_sample_upgrade_settings_reads_all_inputs`（第 443 行）和 `test_current_sample_upgrade_settings_normalizes_legacy_tftp_copy_label`（第 475 行）的 `SimpleNamespace(...)` 各加 2 个 mock：
```python
parameter_clear_parameters_var=Mock(get=Mock(return_value=True)),
parameter_exit_aging_var=Mock(get=Mock(return_value=False)),
```
然后更新期望 `SampleUpgradeSettings(...)` 加 `parameter_clear_parameters=True, parameter_exit_aging=False`。

#### 6.5 `tests/test_sample_upgrade_settings_store.py`：新增持久化往返测试

参照既有的 `test_save_and_load_preserves_parameter_initial_credentials` 加 1 项 `test_save_and_load_preserves_parameter_clear_and_exit_aging`,验证两个新字段独立存读；再加 1 项 `test_load_missing_parameter_clear_and_exit_aging_keys_defaults_to_false` 验证旧 ini 兼容回退。

#### 6.6 `tests/test_sample_parameter_app.py`：现有 mock 无需改

`_make_request` 默认不带 `clear_parameters` / `exit_aging`（默认 False 即可），现有的 `_start_sample_parameter_write` bind_conflict / 网络预检 / UBUS 重试 测试都不会触发这两个字段。`_sample_parameter_write_worker` 的网络预检 / UBUS 重试用例也无需改——它们 mock 了 `run_single_sample_parameter_write`,流水线下游根本不跑。

### 改动 7 — 文档同步

- **`DEVELOPMENT_LOG.md`**：顶部追加一条 `2026-07-19 - 写样机参数 MAC 同批 OUI 固定 + 清空参数可选 + 退出老化选项`,按模板写明类型 / 背景 / 完成内容 / 修改文件 / 验证方法 / 验证结果 / 后续待办。注明"已实现未验收,待真实样机回归"。
- **`line_check_assistant_README.md`**：在"写样机参数"段落追加：
  - 生成参数表：同批 MAC 前 6 位（OUI）固定。
  - 写样机参数窗口新增「清空参数」「退出老化」两个 Checkbutton,默认关闭;勾选后会在工厂模式二次登录成功后下发对应命令;关闭时主执行日志输出 "关闭,跳过"。
- **`PROJECT_STATUS.md`**：表格的"批量写样机参数"行追加"含可选 ppctl clear / AGING_STATE=1,同批 MAC OUI 固定"；测试基线从 273 → 新数（先跑测试后再回填）。
- **`ACCEPTANCE_BASELINE.md` §2.7**：在"边界与异常"段标注"`ppctl clear` 与 `AGING_STATE=1` 现已可选(默认关闭),由主界面 Checkbutton 控制"；"核心验收行为"段提及"6 台验收的现场数据基于旧默认(`ppctl clear` 必发,`AGING_STATE` 不发),新行为待现场回归"；状态行加注"已实现未验收(选项化 + MAC 同 OUI 改动)"。
- **`AGENTS.md`**：无需改动(没有破坏既有规则)。

## 关键不变量

- 主程序入口、运行/打包方式不变（依然 `python .\run_line_check_assistant.py` / `build_line_check_assistant.ps1`）。
- 路径 `vlan{N} -> COM{N-100}` 硬编码不变。
- 升级 / 重启 / 恢复出厂 / 工厂模式进入与退出 仍是确认弹窗 + 主执行日志 + `finally` 清理。
- `Tftp指令` 与 `Tftp Put` 仍隔离；TFTP 仍绑 VLAN IP 不回退 `0.0.0.0`。
- `source_address=(bind_ip, 0)` 锁源不变。
- 现有 273 项单测中除改动 6.2 / 6.4 / 6.5 列出的几条需要小改,其余保持原状;目标新增 ~6 项。

## 不做的事

- **不**把 MAC OUI 暴露到 `ParameterGenerationTemplate` 或生成窗口 UI（用户未要求可配置）。
- **不**改 `_login` / `_write_and_verify` / `_send_stage` / `_wait_cancellable` 内部细节。
- **不**改 `finally` 清理块（既有两步独立 try/except 已验收）。
- **不**改 `_open_parameter_generator` 的字段顺序（与本次无关）。
- **不**做自动 commit（按项目记忆 `git-commit-on-request.md`）。
- **不**改既有 7 个节奏常量或 `MAX_PARALLEL_UPGRADES=8`。

## 验证方法

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m py_compile src/models/sample_parameter_models.py src/core/sample_parameter_table.py src/services/sample_parameter_service.py line_check_assistant/sample_upgrade_settings_store.py line_check_assistant/app.py
python -m unittest discover -s tests -v
```

期望：`Ran N tests ... OK`，其中 `N >= 273 + 1(同OUI) + 5(新选项) + 2(持久化) = 281`。

## 后续待办（落到 `DEVELOPMENT_LOG.md`）

- 用户线下真实样机回归：① 同批生成表的 MAC 前 6 位确实是同一字符串；② 关闭「清空参数」后主执行日志出现 `ppctl clear` 消失 / "清空参数：关闭，跳过"，设备 ppctl 表不被清空；③ 勾选「退出老化」后主执行日志依次出现 `TX ppctl set AGING_STATE=1 → 15 项 ppctl set/get → 退出工厂模式`；④ 关闭「退出老化」后主执行日志出现"退出老化：关闭，跳过"；⑤ 6 台并行（默认配置）仍稳定。
- 用户线下真实样机确认后，把 `ACCEPTANCE_BASELINE.md` §2.7 状态从"已实现未验收（选项化 + MAC 同 OUI 改动）"升到"已确认验收"，同步更新 `PROJECT_STATUS.md` 测试基线数字。
