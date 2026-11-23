# DUTPilot Qt 界面改版预览

2026-11-23，完成总览工作台、自动开关机详情和全业务老化详情的首批独立预览，待负责人确认样式。

首批后续接入与验证见[正式源码工作台集成报告](../gui_visual_workbench_20261123/REPORT.md)。本页保留首版评审记录。

## 打开交互预览

在主源码目录运行：

```powershell
python run_dutpilot_qt.py --visual-preview
```

在顶栏选择「当前版」或「改版预览」，再切换三页。两版复用现有 Qt 工作台和同一组内存快照，模拟六个项目及其日志。起停确认只在预览中显示反馈，预览入口与项目路径、网关配置和正式工作区互斥。

## 前后对照

宽屏在 100% 缩放、1440 × 900 逻辑尺寸的预览窗口采集。截图展示窗口中的完整工作台区域。150% 窄屏使用 800 × 520 逻辑尺寸。

| 页面 | 当前版 | 改版预览 | 150% 窄屏 |
| --- | --- | --- | --- |
| 总览工作台 | [截图](overview-before.png) | [截图](overview-after.png) | [截图](overview-after-narrow.png) |
| 自动开关机 | [截图](power-before.png) | [截图](power-after.png) | [截图](power-after-narrow.png) |
| 全业务老化 | [截图](aging-before.png) | [截图](aging-after.png) · [业务检查与日检](aging-after-observations.png) | [截图](aging-after-narrow.png) |

总览将项目类型、名称、状态和进度分行呈现，默认收起系统详情并显示资源占用摘要。开关机将完成轮次、异常阶段和圆环放在首屏，通道卡片显示状态、轮次和最近阶段。老化将监测时长、业务健康和逐台 DUT 观测分区，保留来源、未知与未接入。小窗口默认收起侧栏和日志，可通过现有控件展开。

## 验证范围

首轮私有桌面检查发现模拟资源字段位置错误，修正后继续核对布局。窄屏截图暴露统计卡裁切和日志正文空间过小，加入紧凑布局后重新检查。

使用锁定的 Qt 解释器和 `run_gui_child(..., framework='qt', native_render=True)` 在 Windows 私有桌面执行 `scripts/run_tests.py qt_visual_preview_probe qt_typed_status_probe -v`。覆盖两版宽窄窗口、同一批次的轮次、失败重试、业务状态和日志范围，以及预览切换、列表筛选、模拟停止默认取消和窄屏日志重新展开。[100%](native-1.txt) · [125%](native-1.25.txt) · [150%](native-1.5.txt) · [隔离结果](results.json)

三档各通过 4 项专项，隔离违规为零。局部编译、6 项入口及迁移契约测试、能力覆盖检查通过。本批为预览验证，完整基线沿用之前的独立候选记录。

本批保留 10 张需要人工评审的截图。正式三页接入及后续业务窗口按预览确认结果分批实施。

## 本批改动

- 预览入口与界面使用 `run_dutpilot_qt.py`、`src/ui/qt/application.py`、`src/ui/qt/visual_preview.py` 和 `src/ui/qt/visual_preview_data.py`。
- 回归与登记使用 `tests/qt_visual_preview_probe.py`、`tests/test_qt_migration_contract.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py` 和 `scripts/capability_gui_actions.json`。
- 交接记录同步根目录 `CAPABILITY_COVERAGE.md`、`PROJECT_STATUS.md` 和 `DEVELOPMENT_LOG.md`。
