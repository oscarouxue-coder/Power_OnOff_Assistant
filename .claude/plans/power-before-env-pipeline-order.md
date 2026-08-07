# 全流程电源优先顺序调整

## 目标

将全流程执行的固定顺序由“环境线路检查 → 自动上/下电”调整为“自动上/下电 → 环境线路检查”，其余 3–7 子任务顺序不变。

## 范围

- 调整 `SUBTASK_CODES` 与 `SUBTASK_LABELS` 的前两项。
- 保留环境线路检查的致命失败语义，但明确其发生在自动上/下电之后。
- 保持默认只勾选环境线路检查。
- 同步顺序守门测试、操作说明、验收基线、项目状态和开发记录。

## 验证

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m unittest discover -s tests -p "test_pipeline_orchestrator.py" -v
python scripts\verify_baseline.py
```
