# Phase 3｜Qt 三项全流程

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

后续复验已通过。预备测试阶段修复 Windows 私有桌面核验，三项全流程用例在 100%、125%、150% 原生 Qt 套件中均通过。原生复验

Qt 项目详情新增「全流程…」入口。环境线路检查、串口日志和开关机测试默认全不勾选，按原配置评估就绪状态。执行确认列出实际项目、通道、顺序、串口目录和开关机版本预检条件。确认后收起配置窗口，项目详情继续显示原任务状态并支持安全停止。

同一 `pipeline.start` 任务把已确认的通道送入原 `PipelineOrchestrator`。选中串口日志时，任务等待项目后台工作线程逐个尝试打开冻结配置中的串口，使用现有终端共享会话、实际 COM 和日志目录。已打开的终端继续保持。未领取的预启动在停止或等待超时后失效。串口失败按原规则记录并继续，环境失败终止后续，开关机初始化时序和结果判据沿用原服务。Qt 显示原子任务结果，普通能力调用及远程入口继续使用其原投影。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 配置、后台、任务投影 | `src/models/workbench_presentation.py`、`src/services/qt_execution_adapter.py`、`qt_pipeline_serial.py`、`qt_workspace_adapter.py`、`qt_serial_terminal.py`、`capability_device_services.py` |
| Qt 界面 | `src/ui/qt/pipeline_dialog.py`、`project_detail.py`、`workspace_controller.py` |
| 验证与覆盖 | `tests/test_qt_execution_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`、根目录 `CAPABILITY_COVERAGE.md`、本目录 `verify_pipeline_qt.py`、`verify_phase3.py` |
| 文档 | 根目录 `README.md`、`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`.claude/plans/pyside6-migration.md`、主源码目录 `line_check_assistant_README.md`、本目录 `MIGRATION_PROGRESS.md` 及本报告 |

## 窗口对照

参考图提供项目详情与核心执行摘要。本次在既有项目详情操作区增加全流程入口，任务选择和就绪信息放在独立窗口，运行状态继续显示在详情页。此前 Qt 项目详情 1366×768 原生截图

100%、125%、150% 原生运行均在窗口创建前因输入桌面校验中止，WinError 5。原生用例覆盖默认未选、取消、串口预启动和任务完成，登记了选择窗口与完成状态两张后图，待补采。三档原生结果

## 验证及待办

- `python validation/pyside6_migration_20261118/verify_pipeline_qt.py` 的联合回归通过 155 项。新增验证覆盖串口预启动先于环境、部分串口失败继续、环境失败中止以及确认、停止和日志目录失效。测试通过真实 Job、原编排器和原串口管理器运行，设备侧为模拟。相关回归
- 323 文件编译、313 源文件登记以及 GUI、能力覆盖与协议不变量通过。源文件对照单独核对共享任务投影新增的 Qt 回调，原 Tk、编排器及设备业务代码保持原实现。源码检查
- 待完成新版原生补图、现场串口与通道映射、真实设备的失败和安全停止路径复验。独立预备测试、版本查询、失败续跑及整体迁移仍在后续。默认入口仍为 Tk，本轮未重跑完整基线、操作真实设备或打包。
