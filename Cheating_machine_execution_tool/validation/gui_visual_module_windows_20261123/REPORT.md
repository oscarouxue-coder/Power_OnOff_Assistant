# 高频业务窗口集中评审

2026-11-23，串口日志、样机升级、DUT 配置、测试项配置、通道配置已生成独立评审稿。两版使用同一组模拟快照和现有 Qt 业务窗口控件。

在主源码目录运行 `python run_dutpilot_qt.py --visual-preview`，点顶部「业务窗口预览…」，按窗口下拉框切换，再选择「当前版」或「改版预览」。

| 窗口 | 当前版 | 改版 | 150% 窄窗 |
| --- | --- | --- | --- |
| 串口日志 | [截图](serial-before.png) | [截图](serial-after.png) | [截图](serial-after-narrow.png) |
| 样机升级 | [截图](upgrade-before.png) | [截图](upgrade-after.png) | [截图](upgrade-after-narrow.png) |
| DUT 配置 | [截图](dut-before.png) | [截图](dut-after.png) | [截图](dut-after-narrow.png) |
| 测试项配置 | [截图](configuration-before.png) | [截图](configuration-after.png) | [截图](configuration-after-narrow.png) |
| 通道配置 | [截图](channels-before.png) | [截图](channels-after.png) | [截图](channels-after-narrow.png) |

串口稿区分连接、日志、输入和失败提示。升级稿分出固件和参数、目标通道、逐台结果及底部操作。DUT 六页统一表单、结果和底部动作，测试项和通道继续使用原有字段及窗口底部操作区域。交互评审可切换标签和查看表单，所有数据来自预置样例，窗口与工作区控制器隔离。

Windows 私有桌面按 100%、125%、150% 运行 `scripts/run_tests.py qt_module_visual_preview_probe -v`，三档均通过。经评审入口检查五组真实窗口的前后版、DUT 六个标签、失败状态、密码遮蔽、16 槽位、只读来源及 640 × 520 窄窗内操作可达。[三档结果](presentation-results.json)

预览布局和模拟快照位于 `module_visual_preview.py`、`visual_preview.py`、`visual_preview_data.py`，回归位于 `qt_module_visual_preview_probe.py`。保留 15 张正式评审用截图。五个窗口待集中确认后接入正式界面。
