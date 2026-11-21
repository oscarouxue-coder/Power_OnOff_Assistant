# DUTPilot V1.2.10 UI视觉与布局专项（2026-11-18）

## 审计结论与问题清单

当前使用标准Tkinter、ttk/Clam和已有ChannelList等局部组件，不更换框架。ProjectWorkspace持有唯一Tk及项目Frame；业务页面仍复用LineCheckAssistant。现有WorkspaceService/ProjectStatusService及workbench_status_service提供真实状态，本轮不改变计数/判定规则、任务或资源管理。

1. WorkbenchPanels固定300px侧栏，外层配置Canvas与HorizontalConfig内层Canvas均按控件自然宽度扩张；原横排电源/IP表单和两组通道表装入侧栏，必然横滚。应让滚动内容宽度跟随视口，将现有表单改为纵向紧凑布局，不靠横滚保底。
2. 配置通道列表固定360px高，原主页面控件自然宽度仍影响侧栏；应取消无意义高度，用纵向滚动承载原控件，配置值和回调保持。
3. 导航通过place计算逐项坐标和手工高度；改为独立行容器+Grid换行，避免共享列约束和绝对坐标。
4. 日志pane固定220px且stretch=never，短运行卡片上方会出现大面积空白。应按实际内容和容器可用高度分配初始分隔位置，拖动后尊重用户选择。
5. 卡片列数仅width//350，不限制于实际项目数；单项目只用约1/3宽。应同时考虑项目数和字体测量得到的最小卡片宽度。
6. 主题颜色/字号/按钮在app、shell、dashboard重复定义；建立工作台局部Design Tokens和派生样式，避免覆盖其它已验收模块全局主题。
7. Telnet表单固定32字符标签列、输入sticky=ew，且仅输入列有权重；短文本无限拉伸。13行单列在150%下易超窗，需两组表单和纵向滚动，字段/trace/capture/load/禁用规则不改。
8. 配置弹窗先pack可扩展Notebook再pack底部按钮，底部空间缺少保护；须先保留按钮区，再分配页签区域。密码现有可见状态变量初值False，但Entry初始没有show，标签还标明文；按本轮明确要求初始隐藏，保留原切换和密码值。

## 分阶段文件清单

- 阶段一：`src/ui/workbench_panels.py`（Grid换行、单向滚动、响应式分栏/日志）、`src/ui/workbench_dashboard.py`（自适应卡片）、`line_check_assistant/app.py`（仅表单装配、原控件布局）、相关离屏布局回归。
- 阶段二：新增`src/ui/workbench_theme.py`（局部tokens/样式），修改shell/dashboard/panels/app的工作台样式装配；编译清单登记。
- 阶段三：新增`src/ui/config_form_layout.py`（配置弹窗纯UI布局），局部调整Telnet及配置窗口装配、按钮/Notebook派生样式；保留所有字段、默认值、保存确认和回调。
- 验证支持：`tests/workbench_visual_probe.py`用于受保护私有桌面上的实际源码窗口渲染；通过现有run_gui_child返回独立隔离证据，不闪用户桌面、不启动DUT。新增/扩展专项测试通过`python scripts/run_tests.py ...`；不改既有GUI隔离设施。
- 文档/门禁：审查并更新GUI动作快照、CAPABILITY_COVERAGE、编译清单；同步开发日志/操作说明/交接与待验收边界。阶段报告、前后截图及当前源文件回退包保存到`validation/ui_visual_20261118/`。

## 不变范围与验证

不新增多项目业务、Probe引擎、暂停/重置/并行或设备命令；全业务老化仍未实现，按已确认边界待接入。不会把创建时间当有效运行时间，不会伪造健康、异常或资源数据。界面只读取现有真实状态，未支持的字段保持未知/无数据。所有测试使用临时目录/Fake，原保存/停止/确认/身份/资源路径保留。

每阶段先捕获修改前窗口，再修改、专项回归并捕获修改后窗口；使用1920×1080、1480×900、1100×720及100%/150%进程内字体模拟，检查单项目、多项目、16通道、配置展开及Telnet弹窗。字体模拟不冒充真实Windows DPI，短时回归不替代长期挂测或设备验收。需要完整基线时使用仓库校验的隔离CPython3.9.10 x64入口，保留新增第八类GUI门禁。既有未提交工作及测试设施全部保留，不自动提交/打包/发布。
