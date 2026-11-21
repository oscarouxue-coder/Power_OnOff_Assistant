# Phase 2｜Qt 配置页面草稿恢复

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

## 审计与改动

旧 Tk 配置窗口用控件位置保存页面原始输入。位置与旧控件树及动态命令结构绑定。Qt 六标签窗口沿用原 INI 和项目版本保存，曾只在内存保留控件输入。

Qt 编辑暂停约 0.5 秒后，原工作区后台线程按项目身份、配置版本和字段名称记录页面草稿。草稿保留未输入完毕的数值、空期望段、命令空格和否定选项。恢复副本使用 Windows 当前账号的 DPAPI 加密，保存在项目的 `ui/qt_editor_recovery.json`，通过原子替换写入。保存正式配置依然经原校验和项目提交。

同一项目重新打开配置时，可恢复、明确放弃恢复草稿，或取消打开并保留草稿。恢复只回填编辑窗口，密码仍遮蔽。显式放弃修改、确认重载或成功保存时清理相应 Qt 草稿。旧版本或无法解密的草稿保留并提示，确认重载后可以清除。发现旧 Tk 草稿时提示使用原 Tk 窗口恢复，原文件保留。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 模型及服务 | `src/models/qt_configuration.py`、`src/services/qt_editor_recovery.py`、`qt_configuration_service.py`、`qt_execution_adapter.py`、`qt_workspace_adapter.py` |
| Qt 界面 | `src/ui/qt/configuration_dialog.py`、`workspace_controller.py` |
| 验证 | `tests/test_qt_configuration_service.py`、`tests/qt_workbench_probe.py`、`tests/test_verify_baseline.py`、`tests/test_qt_migration_contract.py`、`scripts/verify_baseline.py`、`verify_qt_migration.py`、`verify_capability_coverage.py`、`capability_gui_actions.json` |
| 交接 | 根目录 `DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`CAPABILITY_COVERAGE.md`、`.claude/plans/pyside6-migration.md`、操作员说明、本报告和迁移进度表 |

## 截图与参考图

改造前的测试项页已有命令区、期望段和保存操作。本次沿用现有六标签布局，在恢复后显示草稿状态，保留原始输入并提醒核对。参考稿的配置入口和信息层级继续沿用。

改造后 150% 配置截图显示恢复的未完成输入和底部状态提示。

## 功能回归

- `python scripts/run_tests.py test_qt_configuration_service test_qt_channel_configuration test_qt_workspace_adapter test_project_workspace -v` 通过 68 项。覆盖 Windows DPAPI 实际加解密、工作区重启后的读取、原 INI 保全、版本漂移、旧 Tk 草稿保留及非本机调用拒绝。相关回归
- 编译清单加入草稿服务后触发 Windows WinError 206。门禁改用 `py_compile -` 的标准输入传递原清单，并用含中文和空格的临时路径验证超过 32,767 字符的清单及最后一个文件的语法错误。
- 首轮 100% 原生通过。125% 超过原 150 秒时限，父脚本在处理字符串形式的部分输出时异常退出。修正输出处理并将每档上限改为 210 秒，所有用例及隔离检查仍须通过。首次截图库保留。
- `python scripts/run_tests.py test_verify_baseline test_qt_migration_contract -v` 通过 28 项。模拟超时回归确认三档均写入失败证据，并保留文本和字节输出。门禁回归
- 源码保全与编译检查通过，编译 336 份文件、登记 326 份源码。
- `python scripts/verify_qt_migration.py --output validation/pyside6_migration_20261118/qt_configuration_recovery_final` 在 100%、125%、150% 下各通过 59 项，共 177 项。全部指定用例均执行，私有桌面隔离违规为零。三档证据

本轮未重跑完整基线、操作真实设备或构建 EXE。旧 Tk 控件位置格式仍由原窗口恢复，导入平台配置选择与 Windows 现场验收仍待办。
