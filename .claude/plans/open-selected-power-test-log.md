# 打开选中通道的开关机运行日志

## 目标

在主界面左侧通道列表中，操作员右键当前行即可打开该通道最新的旧开关机结果日志。

## 范围与不变量

- 仅查询 `Auto_power_on_off_tool/test_results/device_N/device_N_command_results_*.log`，按文件名中的运行时间戳选择最新文件。
- 只调用 Windows 已关联程序打开既有日志；不写入、重命名或清理任何结果文件。
- 不改变通道勾选、配置持久化、开关机测试、程控电源命令或全流程执行语义。
- 找不到日志、定位异常、打开成功和打开失败都记录到主执行日志。

## 实施与验证

1. 在 `src/services/` 新建纯路径查询 service，并覆盖排序、通道隔离和非法通道测试。
2. 在 `line_check_assistant/app.py` 添加右键菜单与主线程打开回调，并覆盖 UI 入口和成功/失败反馈。
3. 将新源文件加入编译清单，加入一项强制回归，更新操作员说明、状态/验收边界与开发日志。
4. 运行 service 与主界面专项测试、`python scripts/verify_baseline.py`、`git diff --check`；不构建 EXE、不执行真实设备命令。
