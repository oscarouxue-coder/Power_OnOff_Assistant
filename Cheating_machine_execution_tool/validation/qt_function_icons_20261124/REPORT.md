# Qt 工作台功能图标核对

2026-11-24。使用当前工作树的主窗口、项目详情、新建向导和模型设置窗口，载入同一组离线项目。改前截图在修改产品源码之前取得。每个缩放批次使用 Windows 原生 Qt、独立临时目录和经过系统核验的非输入桌面。

## 页面审查与调整

| 位置 | 原界面观察 | 处理 |
| --- | --- | --- |
| 顶部工具栏 | 刷新与放大镜的尺寸偏大，「设备管理」像搜索；两个 AI 入口和菜单仅有文字。通用图标的活动色是深青色，和深色栏接近。 | 六个入口配 16 逻辑像素线形图标，依次为刷新、连接、对话、设备、设置和项目。工具栏提供浅色图标、悬停底色、焦点边框和禁用色。沿用原 QAction、菜单、操作文字与提示。 |
| 工具栏窄窗口 | 原生展开控件空间很小，原图上几乎看不到。挂上正式菜单后还能同时看到字符箭头和原生箭头。 | 给展开控件使用双箭头和无障碍名称；菜单仅显示居中的原生指示箭头。键盘可展开工具栏并访问两个菜单。 |
| 总览、侧栏 | 卡片/列表和侧栏总览使用字体符号，原图中网格仅有几个像素。六项统计只有数值和文字。 | 视图切换使用网格和列表图标。统计标签使用文件夹、运行、时钟、完成、警告和问号，数值仍由原快照筛选统计。侧栏项目状态保留原有图形和颜色。 |
| 项目卡、详情、新建向导 | 项目卡的两类挂测仅有文字，详情标题使用通用平行四边形。 | 三处使用同一组电源循环和心跳图标。优先读取 `project_type`，旧快照的空类型键仅回查 `TEST_TYPES` 中完全相同的类型字段。未识别的键和其他任务保留文字。开始图标使用浅色，停止图标匹配原按钮的深红色。 |
| 详情标签、状态和日志 | 详情标签已有独立名称和选中下划线；通道、项目状态有图形及文字。日志级别、筛选、导出和展开已有明确名称。 | 保留原显示和操作顺序。 |
| 向导表单、全局设置菜单、AI 模型设置 | 向导的步骤及操作有明确标题。设置菜单项、连接表单字段和保存按钮文字完整。 | 在向导的两种已知测试类型前显示同款图标；保留字段、菜单项和提交按钮的文字。 |

## 程序截图

每对图采用同一视口、同一快照和同一页。图中六项统计依次为 6、2、1、1、2、0。主窗口请求 1440 × 900，原生 Windows 在较高缩放下按桌面可用区域调整首次展示尺寸；普通总览和详情三档实际 PNG 尺寸为 1440 × 900、1800 × 1061、1925 × 1061。窄窗口固定为逻辑 800 × 520。向导固定为逻辑 810 × 560。

| 对照页 | 100% | 125% | 150% |
| --- | --- | --- | --- |
| 总览 | [改前](before/overview-1.png) · [改后](after/overview-1.png) | [改前](before/overview-1.25.png) · [改后](after/overview-1.25.png) | [改前](before/overview-1.5.png) · [改后](after/overview-1.5.png) |
| 窄窗口总览 | [改前](before/narrow-1.png) · [改后](after/narrow-1.png) | [改前](before/narrow-1.25.png) · [改后](after/narrow-1.25.png) | [改前](before/narrow-1.5.png) · [改后](after/narrow-1.5.png) |
| 开关机详情 | [改前](before/detail-1.png) · [改后](after/detail-1.png) | [改前](before/detail-1.25.png) · [改后](after/detail-1.25.png) | [改前](before/detail-1.5.png) · [改后](after/detail-1.5.png) |
| 新建向导 | [改前](before/wizard-1.png) · [改后](after/wizard-1.png) | [改前](before/wizard-1.25.png) · [改后](after/wizard-1.25.png) | [改前](before/wizard-1.5.png) · [改后](after/wizard-1.5.png) |

以下六张图额外挂接正式工作区菜单，业务适配器使用 Mock，轮询计时器停用。基础主窗口在上一表单独对照。

| 装配复验 | 100% | 125% | 150% |
| --- | --- | --- | --- |
| 完整工作区工具栏 | [截图](after/workspace-detail-1.png) | [截图](after/workspace-detail-1.25.png) | [截图](after/workspace-detail-1.5.png) |
| 窄窗口展开工具栏 | [截图](after/workspace-narrow-1.png) | [截图](after/workspace-narrow-1.25.png) | [截图](after/workspace-narrow-1.5.png) |

## 文件

- `src/ui/qt/showcase_components.py` 和 `src/ui/qt/theme.py` 提供共用 SVG、暗底图标状态、统计卡及工具栏样式。
- `src/ui/qt/main_window.py`、`src/ui/qt/workspace_controller.py` 设置工具栏、项目菜单和总览导航的图标。
- `src/ui/qt/dashboard.py`、`src/ui/qt/project_detail.py`、`src/ui/qt/project_wizard.py` 在快照和表单上显示相应图标。
- `tests/qt_function_icons_probe.py` 是专项原生探针。本目录的 `verify.py` 按阶段和缩放启动探针。
- `scripts/capability_gui_actions.json` 同步源码指纹。刷新前后比对全仓捕获的动作表达式及各自出现次数，差集为空。刷新基于并行工作树，同时纳入另一会话的 `application.py` 指纹。
- 操作说明见主源码目录的 `line_check_assistant_README.md`，开发记录见仓库根目录的 `DEVELOPMENT_LOG.md`。

## 执行与结果

在主源码目录执行。改前命令只用于当时的源码版本。

```text
python -X utf8 validation\qt_function_icons_20261124\verify.py before
python -X utf8 validation\qt_function_icons_20261124\verify.py after
python -X utf8 -m py_compile src\ui\qt\dashboard.py src\ui\qt\main_window.py src\ui\qt\project_detail.py src\ui\qt\project_wizard.py src\ui\qt\showcase_components.py src\ui\qt\theme.py src\ui\qt\workspace_controller.py tests\qt_function_icons_probe.py validation\qt_function_icons_20261124\verify.py
python -X utf8 scripts\verify_capability_coverage.py --update
python -X utf8 scripts\verify_capability_coverage.py
git diff --check
```

改前各档 1 项通过。改后各档 7 项通过，覆盖标签、动作映射、键盘激活、悬停、焦点、禁用、视图切换、类型回退、菜单、排序、计数与项目身份。每档均由 `run_gui_child(framework='qt', native_render=True)` 启动同一 `scripts/run_tests.py`，原生平台为 `windows`，隔离违规为零。

| 阶段 | 100% | 125% | 150% |
| --- | --- | --- | --- |
| 改前 | [结果](before/checks-1.txt) · [隔离证据](before/isolation-1.json) | [结果](before/checks-1.25.txt) · [隔离证据](before/isolation-1.25.json) | [结果](before/checks-1.5.txt) · [隔离证据](before/isolation-1.5.json) |
| 改后 | [结果](after/checks-1.txt) · [隔离证据](after/isolation-1.json) | [结果](after/checks-1.25.txt) · [隔离证据](after/isolation-1.25.json) | [结果](after/checks-1.5.txt) · [隔离证据](after/isolation-1.5.json) |

局部编译、GUI 能力覆盖及差异格式检查通过。最终测试文本保留两项提示：Qt 将测试用来激活私有桌面窗口的 API 标为弃用，Python 在子进程退出时报告一个对象未回收。两者均未导致用例失败或窗口隔离违规。缩放由各子进程的 `QT_SCALE_FACTOR` 指定，系统显示设置保持原值。本轮范围为离线源码界面；完整基线、打包与真实设备验收未执行。

本目录保留上表引用的 30 张 PNG（12 对及 6 张补充图）。早期复验覆盖同名改后图，额外过程 PNG 为 0 张。
