# 全流程移除 `[order]` 执行子任务

## 目标

- 从“全流程执行”界面和编排器中移除原第7项“测试项配置（[order] 执行）”。
- 原第8项“执行开关机测试”顺延为第7项，界面保持连续编号。
- 主界面“测试项配置”编辑器、INI 保存和独立测试项执行 service 源码保持不变。

## 实施范围

1. `pipeline_orchestrator.py`：移除 `test_item_execution` 的状态评估、调度入口和上下文依赖，7 个子任务按 1→7 编排。
2. `pipeline_window.py`：不再为全流程加载测试项目配置，更新7项说明和危险提示编号。
3. 回归测试与基线门禁：断言列表中不存在 `test_item_execution`，旧开关机任务编号为7，并更新强制基线测试 ID。
4. 同步操作说明、当前状态、验收基线和开发记录。

## 验证

- 执行全流程编排器和窗口专项测试。
- 执行 `python scripts\verify_baseline.py`。
- 执行 `git diff --check`。
