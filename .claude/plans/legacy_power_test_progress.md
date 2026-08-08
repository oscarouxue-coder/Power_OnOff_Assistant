# 开关机测试轮次进度展示

## 目标

- 主界面“环境检查与开关机测试”进度条显示无 GUI 开关机测试的真实轮次进度。
- 总次数使用本次启动时从 `Auto_power_on_off_tool/config/config.ini [ui_defaults]` 读取的 `number_of_tests`。
- 多通道并行时，以所有已选通道均完成的最小轮次作为总体已完成进度，避免提前显示 100%。

## 分层方案

- `src/services/legacy_power_test_service.py`：从旧结果文件桥接的每轮正常结论中解析通道与完成轮次，聚合总体进度，通过可选回调上报。
- `src/services/pipeline_orchestrator.py`：把 service 的进度回调安全投递到 Tk 主线程。
- `line_check_assistant/app.py`：维护进度数值与 `当前/总数` 文案，只负责展示。
- `tests/`：覆盖配置总次数、单/多通道聚合、主线程委派、数值钳制及状态重置。

## 状态边界

- 启动全流程时进度重置；进入开关机测试时显示 `0/number_of_tests`。
- 每轮正常结论到达后推进；停止或失败保留最后已完成轮次，成功保持满格。
- 未勾选“执行开关机测试”时不伪造开关机轮次。

## 验证

- `python -m unittest discover -s tests -p "test_legacy_power_test_service.py" -v`
- `python -m unittest discover -s tests -p "test_pipeline_orchestrator.py" -v`
- `python -m unittest discover -s tests -p "test_app.py" -v`
- `python scripts/verify_baseline.py`
- `git diff --check`

## 完成状态

- 已完成真实轮次聚合、仅上下电模式兼容、Tk 主线程投递、主界面展示和回归保护。
- 完整基线通过：42 个源码文件编译、489 项单元测试、32 个强制基线测试。
