# Qt 功能窗口尺寸兼容

2026-11-21，V1.3.0 迁移 Phase 3 和 Phase 5。

## 审计与迁移

原 Tk 在项目 `ui/module_windows.json` 的 `window_sizes` 下分别记忆全流程、测试项配置、样机升级、写样机参数、ONU 注册和通道重试历史的窗口宽高。串口与 DUT 配置已有各自的 Qt 迁移路径。以上六个 Qt 弹窗此前每次按默认大小打开。

Qt 打开项目时由已有工作区后台读取原六个键。打开弹窗时按当前屏幕可用区域恢复宽高，窗口初始位置沿用现有恢复逻辑。缺少有效宽高使用各窗自己的默认尺寸。关闭弹窗、关闭项目、退出工作台时记录最终尺寸并通过原偏好保存队列合并写入。每个项目独立。Tk 可继续读取同一格式，其他模块键和值保留。关闭时保存失败记日志，仍由原工作区完成关闭及业务收尾。

六个入口仍调用同一套原配置和业务服务。尺寸记录不参与配置版本、测试快照和执行准入。

## 修改文件

- `src/services/qt_window_state.py`、`src/services/qt_workspace_adapter.py`
- `src/ui/qt/workspace_controller.py`、`src/ui/qt/parameter_writer_controller.py`、`src/ui/qt/onu_query_controller.py`、`src/ui/qt/channel_history_dialog.py`
- `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`
- 能力覆盖、操作员说明、项目状态、验收基线、阶段计划、迁移进度和开发记录
- 49 份历史验证报告中的清理说明恢复为正常 UTF-8 文本，原测试记录和结论保留。

## 前后界面核对

150% 缩放下，改造前的全流程窗口按默认 570×355 逻辑像素打开，截图为 855×533 像素。改造后的模拟项目恢复 862×515，截图为 1293×773 像素。核对三项执行选择、配置入口和底部操作均可见。改造后的测试项配置使用 875×610 逻辑像素，滚动区与底部保存按钮仍可用，密码保持遮蔽。实测图来自 Windows 私有桌面上的临时项目。参考图主要展示工作台，独立窗口沿用目前的 Qt 主题。

## 复验命令

~~~powershell
python scripts/run_tests.py test_window_size_state test_qt_workspace_adapter test_qt_configuration_service test_qt_firmware_upgrade test_qt_parameter_writer test_qt_onu_query test_qt_execution_adapter test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_module_window_sizes_verified
~~~

## 验证结果

- 156 项专项回归通过。Tk 状态保存函数生成的记录可由 Qt 读入，Qt 保存结果仍可由 Tk 读取。核对多个窗口合并保存、损坏尺寸回退、跨项目隔离及已关闭项目的迟到回调保护。
- 150% Windows 原生专项通过，管理 11 个 Qt 窗口，隔离违规为零。六个窗口的恢复、调整、子窗重开、项目关闭及程序退出均使用真实 Qt 控件验证。
- 373 个文件编译、363 项源码登记、能力覆盖、GUI 守卫、原协议和业务保全检查通过。
- Windows 原生套件在 100%、125%、150% 缩放各通过 84 项，共 252 项。每档记录 1,789 个受管窗口，Windows 私有桌面隔离违规为零。三档测试项配置截图分别为 875×610、1094×763、1313×915 像素。

## 待验收

核实三档结果、原生隔离记录、专项回归和源码检查后，已将本轮 365 份过程文件移入 Windows 回收站，共 18,575,510 字节。可使用上述命令重新生成截图和验证输出。

目标电脑的实际系统 DPI 切换与实体多屏仍待复验。本轮为 Qt 窗口偏好增量，未重新打包或运行完整源码基线。真实设备和长期挂测继续按第一阶段原计划验收。
