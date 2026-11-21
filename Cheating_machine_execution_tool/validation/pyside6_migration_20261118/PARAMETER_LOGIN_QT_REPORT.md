# Qt DUT 与写参共用登录输入

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 5。

## 审计

Tk 的 DUT 配置和写样机参数共用首次登录账号、密码变量，写参设置变更由 Tk 延迟保存至 `sample_upgrade_settings.ini`。迁移前，Qt 两窗从同一项目文件读取，编辑各自独立。DUT 在项目会话里保留输入，Qt 写参通过显式保存提交项目版本。写参确认绑定已保存的配置，DUT 确认绑定当前输入、目标及配置。

## 实现

同项目两个 Qt 窗口现共用本机登录草稿。任一窗口编辑后，另一个窗口即时反映，打开顺序和项目切换不会串用值。DUT 收到凭据变更时将先前查询结果标记失效。请求提交、确认和窗口显示的批次执行期间，共用账号和密码暂时只读，当前任务使用原确认绑定。

Qt 继续通过「写样机参数 → 保存设置」显式提交，保留已保存配置版本和现有写入保护。保存失败时两个窗口继续显示相同草稿，原项目文件由既有保存入口恢复。选择放弃修改时，两窗恢复到已保存的登录输入。标准关闭项目后释放对应内存草稿。旧 Tk 的延迟自动保存仍由旧入口提供。

2026-11-21 负责人确认 Qt 保留上述显式保存，作为与旧 Tk 的已知交互差异验收。目标机和真实设备的复验范围继续按原计划执行。

密码默认隐藏，共用输入不进入主界面日志、确认文本、Job 记录、AI 或远程入口。DUT 窗口目标、并发数及测试选项各自独立，执行仍调用原业务服务。

## 修改文件

- `src/services/qt_dut_configuration.py`
- `src/ui/qt/dut_configuration_dialog.py`、`src/ui/qt/parameter_writer_dialog.py`、`src/ui/qt/parameter_writer_controller.py`、`src/ui/qt/workspace_controller.py`
- `tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`
- `scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json` 和能力覆盖文档
- 操作员说明、迁移计划和进度、项目状态、开发记录与验收基线

## 复验命令

```powershell
python scripts/run_tests.py test_qt_dut_configuration test_qt_dut_wan test_qt_dut_wifi test_qt_dut_voice_tr069 test_qt_parameter_writer test_qt_workspace_adapter test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_parameter_login_verified
```

## 验证

- 103 项专项回归通过，编译、源码登记、能力覆盖、GUI 守卫、协议及原实现保全检查通过。
- 150% 原生专项 3 项通过，覆盖模拟 DUT 实际准入、写参原预检与安全停止、双向同步和跨项目隔离。新增用例验证同一组草稿在两窗回显、保存前文件字节一致、请求期间只读、换凭据后查询结果失效、模拟写盘失败后保留草稿、显式保存与放弃修改。
- 首轮专项出现 DUT 警告、邻接写参用例超时及测试退出时的保存提示。复查确认新增用例留下第二项目未关闭的写参窗口。补齐测试中的关闭和放弃确认，保留异常警告断言。原生专项重跑与最终全套均通过。
- Windows 私有桌面 100%、125%、150% 各通过 77 项，共 231 项。每档管理 1,748 个窗口，隔离违规为零，指定用例无遗漏。
- 截图核对了 DUT 密码显示切换、写参密码默认隐藏以及窄窗底部动作。三档写参窄窗截图为 560×430、700×538 和 840×645 像素。本轮沿用两窗原布局。
- 复验通过并汇总后，将本轮 341 份截图、日志、结果清单和已覆盖的失败证据移入 Windows 回收站，共约 16.9 MiB。

## 待验收范围

本轮是已迁移两窗的交互补齐，参考图未展示其独立窗口。Qt 延续上阶段的显式保存，Tk 自动保存与 Qt 项目版本、安全准入的差异继续保留在进度表。真实 DUT 和写参任务、目标机、最终完整基线及重新打包待验收。
