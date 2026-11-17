# 多项目工作区布局对齐（2026-11-17）

## 已确认的实施计划

- 对齐原始`multi-project-preview.svg`及负责人截图红框中的统一顶栏、两行项目卡片、项目标题与紧凑导航。保留侧栏收起及项目菜单切换。
- 灰色工作区底板与白色面板分层；工作区局部主题不再覆盖白色区域，不改变其它模块窗口主题。
- 接入时复用现有项目状态、保存、右键菜单、业务入口和能力service；保持确认、停止、配置及项目隔离语义。
- 保留“3 环境检查与开关机测试”卡片及检查执行、停止、状态、进度和通道概览；顶部导航入口不替代或删除这张卡片。该项由负责人在首版预览反馈中明确，已补回预览。
- 先提供真实Tk预览，取得负责人视觉认可后再接入主程序；预览不会加载配置、启动任务、连接模型/平台/设备。
- 接入后执行布局、项目切换、关闭、状态更新和入口专项回归，审查能力矩阵并更新GUI快照；同步操作说明、状态和验收待办。本轮不提交、不打包、不发布。

## 当前阶段

仅制作独立布局预览`workspace-layout-preview.py`，不修改主程序业务绑定。模拟数据只用于视觉展示；原有配置区域作为布局上下文保留，不将红框范围扩展为运行面板重写。

修订版在配置卡片下方补回运行卡片；预览右侧支持滚动，验证最小窗口和字体放大时运行卡片、按钮及日志仍可到达。仍等待负责人视觉认可。

运行预览（仓库根目录）：

```powershell
python -X utf8 .claude/plans/workspace-layout-preview.py
```

验证布局与生成原生渲染截图：

```powershell
python -X utf8 .claude/plans/workspace-layout-preview.py --check
python -X utf8 .claude/plans/workspace-layout-preview.py --capture .claude/plans/workspace-layout-preview.png
python -X utf8 .claude/plans/workspace-layout-preview.py --capture .claude/plans/workspace-layout-preview-150.png --size 1100x720 --scale 1.5 --show-run-card
```

`--check`使用进程内Tk字体缩放模拟100%/150%，不更改Windows显示设置，不代表真实Windows DPI验收。预览交互仅更新自身模拟状态，不能执行真实业务。
