# Phase 2 · Qt 只读工作台

在主源码目录用项目 Qt 环境执行 `python run_dutpilot_qt.py --workspace`。本次增加总览统计、项目筛选、模板索引、设备缓存入口及全局日志项目筛选。所有业务操作沿用工作台原有服务和确认流程。

| 操作员可核对的场景 | 本次验证 |
|---|---|
| 同一项目有多条任务或异常通道 | 总览按项目 ID 计数。同一快照可同时命中运行和需关注。状态下拉框用于查看计数对应的项目。 |
| 执行中、已结束及重开项目 | 用当前任务注册表、执行器以及有时间记录的项目台账识别状态。旧任务被重新核实时，最近任务 ID、操作名称和开始时间仍对应最近准入记录。 |
| 预测试包含已执行但未校验的命令 | 以该项目和 Job 的原预测试回执标识未校验。当前预测试可显示成功及失败命令条数。缺少回执或缺少某项累计数时保留缺失标记。 |
| 两个同名项目、已关闭项目、无项目归属的日志 | 以完整项目 ID 区分，保留有界缓冲中的历史来源。详情使用自己的日志范围，返回总览恢复原筛选。清屏或切换页面后，已触发的导出仍使用原筛选快照。 |
| 打开模板及设备页面 | 模板索引读取已打开项目的保存版本，以项目 ID 打开详情。设备侧栏复用缓存，只有显式刷新才重新枚举。原项目文件和任务在浏览期间保持原状态。 |

自动化使用临时项目、模拟任务和带隔离守卫的 Windows 私有桌面。逐电源通道的真实占用、DUT 在线状态、目标机人工验收及 24/72 小时挂测仍需现场证据。本次按局部展示及只读投影变更进行专项验证，未运行完整基线或构建交付包。

## 复验

在主源码目录用项目独立 Qt Python 环境运行以下命令。原生回归会在隔离桌面运行 100%、125%、150% 三档。

```powershell
python scripts/run_tests.py test_qt_workspace_adapter test_qt_execution_adapter test_qt_log_history test_workbench_status test_qt_migration_contract -v
python scripts/verify_qt_migration.py --output "$env:TEMP/DUTPilot-Phase2-native"
python scripts/verify_capability_coverage.py
```

五个服务与展示模型测试模块共 124 项通过。编译通过 391 个文件，381 个源码文件均已登记，GUI 动作审查与窗口隔离覆盖均通过。[服务及模型测试记录](verified-services.txt) · [编译与覆盖检查](checks.txt)

首轮在 125% 和 150% 的 1366 × 768 场景发现展开系统状态后裁切项目卡。125% 的实测项目区可见高度为 181，卡片占用高度为 194。总览统计卡上下内边距各从 16 调整到 8，保留通道信息、日志及系统状态面板。原布局断言在三档定向复验中均通过。[首次验证记录](native/results.json)

定稿源码在 Windows 私有桌面以 100%、125%、150% 各通过 108 项，合计 324 次。每档 1,908 个受管 Qt 窗口，缺失用例与隔离违规均为零。[三档原生回执](native-verified/results.json) · [定稿源码及验证入口指纹](verified-inputs.json)

选取三张原生截图供人工比对，均使用临时测试项目。[两项目总览](native-verified/scale-1/real-project-overview.png) · [同名模板来源及各自版本](native-verified/scale-1/saved-project-template-index.png) · [125% 展开健康面板，含模拟写盘失败记录](native-verified/scale-1.25/system-health-overview.png)
