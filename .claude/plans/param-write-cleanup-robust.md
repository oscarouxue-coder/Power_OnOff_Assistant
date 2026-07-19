# 写样机参数 — 退出工厂模式清理失败时仍要发出 firstboot -yr

## 背景

用户线下 6 台真实样机跑批量写参，主执行日志在 VLAN112 上抓到一段有歧义的输出：

```
13:27:52  VLAN112 TX ppctl set XPON_SN='XPOND8AIKI54'（XPON SN，第 2/3 次）
13:27:53  VLAN112 TX ppctl get XPON_SN（读取 XPON SN）
13:27:53  VLAN112 TX ppctl set FACTORY_MODE=0
13:27:53  VLAN112 写参：退出工厂模式清理失败：Telnet 连接已关闭：192.168.29.1:23
13:27:53  VLAN112 写参：请人工确认设备已退出工厂模式。
```

清理阶段本应依次下发 `FACTORY_MODE=0` 和 `firstboot -yr`，但日志直接跳到"退出工厂模式清理失败"，**`TX firstboot -yr` 这一行消失了**。操作员无法判断：
- `firstboot -yr` 到底有没有尝试过；
- 是哪一步（`FACTORY_MODE=0` 还是 `firstboot -yr`）触发"连接已关闭"；
- 设备实际处于 `FACTORY_MODE=0` 但未重启的"半退出"状态，还是要再人工补一条 `firstboot -yr`。

## 当前代码

[src/services/sample_parameter_service.py:286-294](Cheating_machine_execution_tool/src/services/sample_parameter_service.py#L286-L294) 的 `finally` 块：

```python
finally:
    if entered_factory:
        try:
            _send_stage(session, "ppctl set FACTORY_MODE=0", False, emit, request.vlan)
            _send_stage(session, "firstboot -yr", False, emit, request.vlan)
            emit(f"{request.vlan} 写参：已下发退出工厂模式与重启命令。")
        except Exception as exc:
            emit(f"{request.vlan} 写参：退出工厂模式清理失败：{exc}")
            emit(f"{request.vlan} 写参：请人工确认设备已退出工厂模式。")
```

`_send_stage` 先 `emit` 再 `send_line`（[sample_parameter_service.py:390-392](Cheating_machine_execution_tool/src/services/sample_parameter_service.py#L390-L392)）；按代码契约，理论上 `TX firstboot -yr` 应该已经 emit 到主执行日志。但与 `TelnetSession.write`（[src/core/telnet_transport.py:139-153](Cheating_machine_execution_tool/src/core/telnet_transport.py#L139-L153)）配合时，如果 `self._closed=True`，整个调用栈会在 `_send_stage` 内 `send_line` 处抛 `RuntimeError`，异常被外层 `try/except` 捕获后只输出一行"清理失败"，没有 step 名区分，操作员无法辨别"是 FACTORY_MODE 触发的还是 firstboot 触发的"，也无法判断 firstboot 这步有没有真的被尝试。

## 优化目标

期望的清理日志（失败场景）：

```
13:27:53  VLAN112 TX ppctl set FACTORY_MODE=0
13:27:53  VLAN112 TX firstboot -yr                            ← 必须出现
13:27:53  VLAN112 写参：退出工厂模式清理失败：firstboot -yr 下发失败：Telnet 连接已关闭：192.168.29.1:23
13:27:53  VLAN112 写参：请人工确认设备已退出工厂模式。
```

成功场景保持不变（两步都发成功 + 收尾提示）。

## 实现方案

### 改动 1 — `src/services/sample_parameter_service.py` `finally` 清理块

把两步拆成两个独立 `try/except`，每一步单独记录自己的失败，最后汇总报告：

```python
finally:
    if entered_factory:
        # 退出工厂模式需要两步：1) FACTORY_MODE=0 关掉标志 2) firstboot -yr 触发实际重启。
        # 两步独立 try/except：第 1 步失败也要尝试第 2 步（设备已断电/重置场景下
        # best-effort），并把失败步骤名嵌入错误消息，避免日志只能看到
        # "Telnet 连接已关闭" 而无法分辨是 FACTORY_MODE 还是 firstboot 触发的。
        cleanup_failures: list[str] = []
        try:
            _send_stage(session, "ppctl set FACTORY_MODE=0", False, emit, request.vlan)
        except Exception as exc:
            cleanup_failures.append(f"FACTORY_MODE=0 下发失败：{exc}")
        try:
            _send_stage(session, "firstboot -yr", False, emit, request.vlan)
        except Exception as exc:
            cleanup_failures.append(f"firstboot -yr 下发失败：{exc}")
        if cleanup_failures:
            emit(f"{request.vlan} 写参：退出工厂模式清理失败：{'；'.join(cleanup_failures)}")
            emit(f"{request.vlan} 写参：请人工确认设备已退出工厂模式。")
        else:
            emit(f"{request.vlan} 写参：已下发退出工厂模式与重启命令。")
```

关键不变量：
- `FACTORY_MODE=0` 失败不会阻止 `firstboot -yr` 的尝试和日志（best-effort）。
- `firstboot -yr` 失败不会吞掉 `FACTORY_MODE=0` 的成功上下文。
- `_send_stage` 内部 `emit` 在 `send_line` 之前调用，所以主执行日志里 `TX firstboot -yr` 这一行必然出现（即使 `send_line` 抛异常）。
- 成功路径日志、流程、调用方契约全部不变。

### 改动 2 — `tests/test_sample_parameter_service.py` 新增 3 项单测

`FakeSession` 已经支持任意 `send_line` 抛异常（直接 `raise` 即可），不需要新 mock。

1. `test_cleanup_emits_both_tx_lines_even_when_firstboot_fails`
   - 构造一个 `send_line` 在收到 `firstboot -yr` 时抛 `RuntimeError("Telnet 连接已关闭：192.168.29.1:23")` 的 FakeSession；
   - 走成功流水线（其他步骤全部 OK）；
   - 断言主执行日志依次出现 `TX ppctl set FACTORY_MODE=0` 和 `TX firstboot -yr`；
   - 断言失败日志含 `firstboot -yr 下发失败` 与 `请人工确认设备已退出工厂模式`；
   - 断言失败消息**不**含 `已下发退出工厂模式与重启命令`。

2. `test_cleanup_reports_factory_mode_failure_when_step_one_fails`
   - 构造一个 `send_line` 在收到 `ppctl set FACTORY_MODE=0` 时就抛异常的 FakeSession；
   - 跑流水线，断言主执行日志出现 `TX ppctl set FACTORY_MODE=0`、出现 `FACTORY_MODE=0 下发失败`；
   - 断言**仍尝试**了 `firstboot -yr`：日志里也有 `TX firstboot -yr`，并且若 firstboot 也失败则两条失败都被报告（用 `；` 分隔）。

3. `test_cleanup_success_log_unchanged_when_both_steps_succeed`
   - 现状回归测试，断言成功路径里 `已下发退出工厂模式与重启命令` 仍然出现，且 `FACTORY_MODE=0` 与 `firstboot -yr` 都在 writes 里（与现有 `test_factory_session_swap_new_session_is_used_for_second_login` 的契约对齐）。

### 改动 3 — 文档

- [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md) 顶部追加 2026-07-19 的本次记录（按既有 YYYY-MM-DD - 标题 / 类型 / 背景 / 完成内容 / 修改文件 / 验证方法 / 验证结果 / 后续待办 模板）。
- [PROJECT_STATUS.md](PROJECT_STATUS.md) §「已完成」中"批量写样机参数（…）"行的"已 1 台真实样机验收"后**不动**（本次只改清理失败的日志清晰度，不改业务时序）。
- [ACCEPTANCE_BASELINE.md](ACCEPTANCE_BASELINE.md) §2.7 "边界与异常"小节追加一段："退出工厂模式清理失败：两步独立 try/except；`firstboot -yr` 失败会在主执行日志明确标识为 `firstboot -yr 下发失败：…`，操作员可分辨是哪一步触发的连接已关闭"。

## 验证方法

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m py_compile src\services\sample_parameter_service.py tests\test_sample_parameter_service.py
python -m unittest discover -s tests -v
```

预期 `Ran N tests ... OK`，N = 270（基线）+ 本轮新增 3 = **273**。

## 修改文件

- `Cheating_machine_execution_tool/src/services/sample_parameter_service.py`（清理 finally 块拆 try/except）
- `Cheating_machine_execution_tool/tests/test_sample_parameter_service.py`（新增 3 项单测）
- `DEVELOPMENT_LOG.md`（追加 2026-07-19 记录）
- `PROJECT_STATUS.md`（必要时同步）
- `ACCEPTANCE_BASELINE.md`（§2.7 边界与异常小节补充一段）

## 不改的东西

- 不动业务时序（仍然 `FACTORY_MODE=0` → `firstboot -yr` 这个顺序）。
- 不动 `run_single_sample_parameter_write` 串口路径。
- 不动 `_send_stage` 内部顺序（emit 在 send_line 之前这一契约保持）。
- 不动 `ACCEPTANCE_BASELINE.md` §2.7 中"待真实样机验收 2/4/8 台并行"的结论。
- 不动 `DEVELOPMENT_LOG.md` 既有 270 项测试基线记录。
