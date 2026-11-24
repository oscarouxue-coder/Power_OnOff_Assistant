# DUTPilot 总览工作台原生前后对照

2026-11-24，参照 `docs/UI界面参考.png` 上半部分调整正式 Qt 总览。默认顺序依次显示运行中、需关注、其他活动项目及其余项目。相同优先级沿用原项目顺序，列表表头可以手动排序。六项统计沿用原有项目 ID 和状态口径，搜索、筛选和项目入口沿用原控件。

开关机卡片和列表展示已有百分比、完成轮次和当前阶段。卡片只为有效进度绘制进度条。全业务老化展示持续监测快照中的时长、健康与最近检测，没有时长或业务观测时明确提示。业务健康计数按已有 DUT 与业务观测组合统计。现有系统状态和实时日志区域仍可操作。

## BEFORE 与 AFTER

改动前先运行 Windows 原生隔离截图。两阶段使用同一 `MainWindow.dashboard` 页面、同一截图脚本与同一份离线快照。截图顶栏注明「离线界面验证 · 模拟数据」。夹具包含七个项目，其中两个项目同名且 ID 不同，并包括两类运行、等待、待核实、完成、空闲和无业务观测。[模拟快照](fixture.json) · [源码指纹与改前隔离记录](before-capture.json) · [改后隔离记录](after-capture.json)

每组前后图的窗口像素尺寸、Qt 缩放、页面外视口、视图模式、导航和日志显示状态一致。截图固定了相同的日志分隔位置。总览内部卡片、列表和统计区尺寸随布局变化，记录在对照数据中。[逐组几何、项目 ID 顺序和哈希](comparison.json)

| Qt 缩放和窗口 | 截图像素 | 总览外视口逻辑尺寸 | 卡片 BEFORE / AFTER | 列表 BEFORE / AFTER |
| --- | --- | --- | --- | --- |
| 100% 宽窗 | 1920 × 1061 | 1663 × 832 | [改前](before-wide-cards-1.png) · [改后](after-wide-cards-1.png) | [改前](before-wide-list-1.png) · [改后](after-wide-list-1.png) |
| 125% 宽窗 | 1920 × 1061 | 1279 × 619 | [改前](before-wide-cards-1.25.png) · [改后](after-wide-cards-1.25.png) | [改前](before-wide-list-1.25.png) · [改后](after-wide-list-1.25.png) |
| 150% 宽窗 | 1920 × 1061 | 1023 × 477 | [改前](before-wide-cards-1.5.png) · [改后](after-wide-cards-1.5.png) | [改前](before-wide-list-1.5.png) · [改后](after-wide-list-1.5.png) |
| 150% 窄窗 | 1350 × 825 | 868 × 408 | [改前](before-narrow-cards-1.5.png) · [改后](after-narrow-cards-1.5.png) | [改前](before-narrow-list-1.5.png) · [改后](after-narrow-list-1.5.png) |

150% 窄窗下，首排完整并列运行中的开关机、运行中的老化和待核实项目。列表为进展和观测预留两行，较长的名称与内容可悬停查看。模拟截图中的新建和打开按钮由隔离演示禁用，正式按钮通过临时工作区单列复验。

## 回归结果

- 通过 `run_gui_child(framework='qt', native_render=True)` 与 `scripts/run_tests.py` 逐档执行。100%、125%、150% 各通过 16 项，覆盖同名按 ID、项目快照更新、默认优先级、手动排序、筛选、卡片与列表打开详情和选择、空数据、窄窗首排、既有详情和日志。[100%](focused-1.txt) · [125%](focused-1.25.txt) · [150%](focused-1.5.txt) · [隔离记录](focused-results.json)
- 正式「打开项目…」和「新建项目」按钮在临时工作区三档各通过 1 项。实际打开并选中合成项目，打开向导后取消。三档共 51 次专项测试，无窗口隔离违规。[文件入口验证](file-entry-results.json)
- 局部编译、GUI 能力覆盖和差异格式检查通过。完整基线、打包、现场数据复验和长挂验收未执行。

## 修改文件

- `src/ui/qt/dashboard.py` 调整总览的默认排序、卡片和列表展示。
- `tests/qt_visual_preview_probe.py` 增加总览行为、数据缺失和窄窗原生测试。
- `scripts/capability_gui_actions.json` 更新总览界面源码指纹。
- `line_check_assistant_README.md`、根目录 `PROJECT_STATUS.md` 和 `DEVELOPMENT_LOG.md` 同步操作及验证记录。
