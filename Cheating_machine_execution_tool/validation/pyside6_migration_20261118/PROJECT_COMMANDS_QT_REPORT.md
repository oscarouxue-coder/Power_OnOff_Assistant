# Qt 项目菜单和主窗口快捷键

2026-11-21，V1.3.0 Phase 2 增量。

## 入口和行为

原 Tk 工作台在主窗口绑定 Ctrl+N、Ctrl+O、Ctrl+S，通过「打开项目目录」调用 Windows 打开当前项目根目录。Qt 已有新建、打开和保存菜单，但缺少对应快捷键和目录入口。

Qt 现在将三个快捷键绑定到同一组菜单动作，沿用原有项目名称输入、文件选择、保存和禁用条件。项目菜单也可从左侧导航的右键菜单打开。目录命令在操作时固定所选项目 ID，由工作线程取得已打开项目的根目录并调用 Windows 资源管理器。目录已变化或工作区正在关闭时显示失败原因。

## 运行截图核对

在 150% 缩放的同一 Windows 私有桌面验证环境中，修改前的菜单没有快捷键提示。修改后右侧显示 Ctrl+N、Ctrl+O、Ctrl+S，「打开项目目录」位于「另存为独立项目」下方。改造前后的菜单截图均逐项核对。参考图展示主工作台，未提供菜单展开状态。

## 回归与复跑

在临时目录创建项目 A 和 B，关闭 A，然后通过 Ctrl+O 重新打开 A。核对目录请求与保存操作均指向 A。在子窗口按 Ctrl+S 时，主窗口未收到第二次保存请求。测试替换了 Windows 资源管理器调用、名称输入及文件选择对话框；Qt 菜单、键盘事件、文件保存和项目工作线程实际运行。

~~~powershell
python scripts/run_tests.py test_qt_workspace_adapter test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_project_commands_confirmed
~~~

- 本轮专项回归通过 47 项，覆盖 Windows 拒绝打开目录和所选项目已关闭两种失败路径。150% 单项原生测试通过，隔离违规为零。能力清单、74 个 GUI 构造点的隔离检查及修改文件编译通过。
- 最终复用同一工作树的标准原生套件 `handoff_20261121_final/native`。100%、125%、150% 各通过 86 项，共 258 项。每档管理 1,800 个 Qt 窗口，隔离违规为零。已逐项核对菜单、旧项目历史、串口关闭和全流程收尾的用例结果。
- 第二批在 100%、125%、150% 均实际执行了项目菜单和快捷键用例，三档该项均通过。菜单截图可辨认三组快捷键和当前项目目录入口，文字未裁切。第二批 150% 档的模拟串口关闭用例超时，工作树修订了该用例的释放顺序和断言，最终三档均通过。
- 首批 100% 档与另一组使用相同模拟网卡标识的回归有时间重叠，两项用例报告资源保护冲突。125% 档的 85 项用例运行成功，但旧测试激活窗口的方法会在用例名称与通过标记之间打印弃用警告，导致必跑清单无法核实。测试已改为请求窗口激活并等到窗口确实拥有焦点，保留原窗口隔离与必跑清单检查；修正后的单项原生复验和首批 150% 档通过。
- 第二批 100% 档通过。125% 档的全流程串口预启动用例在环境检查反馈出现后立即检查线程空闲，即时断言失败。原 Job 先发布终态，再释放资源并退出。测试现在使用原有六秒上限等待线程退出，并继续核对串口路径和窗口关闭状态。生产端时序与资源检查保留。
- 完整源码基线和 Windows 打包未在本轮重跑，目标电脑的资源管理器实际弹出仍待核对。

## 修改文件

验证结论归档后，项目菜单和旧运行历史两项增量的 737 份过程文件已移入回收站，含早期失败批次。可用本报告的命令重新生成截图与用例输出。

- `src/ui/qt/workspace_controller.py` 和 `src/services/qt_workspace_adapter.py` 实现项目菜单绑定、目录定位和操作反馈。
- `tests/qt_workbench_probe.py` 和 `scripts/verify_qt_migration.py` 将跨项目及子窗口键盘操作纳入必跑项。`tests/test_qt_workspace_adapter.py` 验证后台失败能返回给操作员。
- `scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json` 和 `CAPABILITY_COVERAGE.md` 登记本机项目菜单操作。
- 操作员说明、项目状态、迁移进度和开发记录同步本次变更。
