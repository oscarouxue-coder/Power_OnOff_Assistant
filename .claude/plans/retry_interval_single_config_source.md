# 指令重试间隔单一配置源

## 目标

- “测试项配置 → 测试项 → 指令重试间隔”只保存到 `config.ini [other_config]`。
- `test_project_config.ini [order]` 只保留测试命令，不再保存该全局参数。
- 页面加载和全流程执行继续获得同一个重试间隔值。

## 实施

1. `TestItemConfigStore` 从同目录 `config.ini [other_config]` 加载重试间隔，保存测试项目时只把该值写入 `config.ini`。
2. 序列化 `[order]` 时不再输出 `command_fail_retry_interval_time`；加载旧文件时忽略残留同名键，避免把它误识别为命令。
3. 从当前测试项目配置和默认模板中删除同名键，避免“恢复默认”重新带回。
4. 更新配置存储测试、强制基线测试 ID、操作说明、验收基线、状态和开发日志。
5. 运行专项测试与 `python scripts/verify_baseline.py`。

## 不变边界

- UI 字段、默认值 60 秒和全流程失败重试语义不变。
- `[order]` 命令、`retry_times_N`、Telnet/WiFi/项目信息保存格式不变。
- 不修改旧工具 GUI 主文件。
