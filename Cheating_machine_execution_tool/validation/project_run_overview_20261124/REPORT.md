# DUTPilot 运行概览离线复验

2026-11-24，在开关机电脑的原工作区按 `docs/UI界面参考.png` 下半部分调整 Qt 项目详情。运行指标置顶，业务健康与 DUT 状态并排，近期事件跟在状态区下方。参数和资源配置在右侧，空间较小时可折叠。页面继续提供原通道矩阵、列表、VLAN / COM、任务操作和串口日志入口。

开关机进度、轮次、阶段和回执来自现有项目快照。连续老化的计时和最近检测使用原观测记录，健康计数按 DUT 与业务的组合统计。当前快照缺少历史健康序列时，页面显示「暂无业务健康趋势数据」。近期事件最多显示缓冲中的四条结构化项目记录，有当前任务时匹配任务或批次标识，原始串口文本可在原日志入口查看。

## Windows 原生截图

所有截图都来自正常的 Qt `MainWindow` 项目详情入口。窗口标注「离线界面验证 · 模拟数据」。使用 Windows 非输入私有桌面和 `windows` 平台插件，设置 Qt 显示缩放。实际 PNG 均为 **1920 × 1061** 像素。

| Qt 缩放 | 实际窗口逻辑尺寸 | 开关机空闲 | 开关机运行 | 连续老化运行 |
| --- | --- | --- | --- | --- |
| 100% | 1920 × 1061 | [空闲](idle-1.png) | [矩阵](power-running-1.png) | [老化](aging-running-1.png) |
| 125% | 1536 × 849 | [空闲](idle-1.25.png) | [矩阵](power-running-1.25.png) | [老化](aging-running-1.25.png) |
| 150% | 1280 × 707 | [空闲](idle-1.5.png) | [矩阵](power-running-1.5.png) · [列表与近期事件](power-running-list-1.5.png) | [老化](aging-running-1.5.png) |

截图沿用实际项目导航和 Qt 控件，保留开关机圆环与原通道布局。老化页的业务健康和 DUT 状态布局接近参考图，缺失的历史趋势用文字说明。125% 截图默认收起底部项目日志，150% 也收起右侧配置。150% 开关机矩阵下方可滚动到近期事件，补充截图记录了切到列表后的实际效果。

## 检查结果

- 使用锁定的 PySide6 6.8.3，通过 `run_gui_child(..., framework='qt', native_render=True)` 运行 `scripts/run_tests.py`。100%、125%、150% 各通过 13 项，共 39 次，窗口隔离违规为零。覆盖两类任务的空闲和运行、空数据、VLAN / COM 和矩阵列表、事件归属、日志筛选、窄窗和折叠偏好。[原生结果](native-results.json)
- 记录窗口逻辑尺寸、PNG 像素尺寸、缩放、配置及日志可见状态。[100%](geometry-1.json) · [125%](geometry-1.25.json) · [150%](geometry-1.5.json)
- 修改文件局部编译、GUI 能力覆盖清单检查及 `git diff --check` 均通过。能力清单新增一个只读日志刷新绑定，业务入口沿用原有绑定。
- 本轮为源码及隔离模拟验证。完整基线、标准打包、现场设备和长时间运行验收未执行。

## 修改文件

- `src/ui/qt/project_detail.py` 调整指标、状态、事件和右侧配置布局。
- `src/ui/qt/main_window.py` 接入项目详情事件刷新和紧凑窗口日志折叠。
- `src/ui/qt/log_panel.py` 为项目详情提供原日志缓冲的只读事件查询。
- `tests/qt_visual_preview_probe.py` 增加正式窗口的离线验证和截图。
- `scripts/capability_gui_actions.json`、根目录 `CAPABILITY_COVERAGE.md` 同步界面绑定审查。
- `line_check_assistant_README.md`、根目录 `DEVELOPMENT_LOG.md` 记录操作方式与本轮结果。
