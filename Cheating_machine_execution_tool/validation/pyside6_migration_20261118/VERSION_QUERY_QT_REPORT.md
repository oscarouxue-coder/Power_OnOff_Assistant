# Phase 5｜Qt 样机版本查询

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

## 原入口和迁移边界

旧 Tk 用主窗口当前通道与配置窗口的 Telnet 草稿锁源登录。成功提示符为 `>` 时，先确认该草稿中的登录后命令。原服务依次读取 `/etc/config/deviceinfo` 和 `/proc/version`，返回软件版本、内部软件版本和 ONU 软件编译时间。三项结果只供查看，正式测试仍按手动保存的基准值判定。通用 `device.version` 读取已保存参数，不能直接承担本机草稿查询。

Qt 的项目信息页从当前项目已启用的通道中选择一台。只有一条时自动选中，多条时由操作员点选。查询锁定该通道和当前 Telnet 草稿，保持原 `>` 确认及其它提示符直接查询的行为，经原 `device.version` Job 和 `query_device_project_info` 执行。准入前复核项目、网卡、配置版本和窗口身份。查询期间可以切换项目，关闭配置窗口和退出须等待查询收尾。读取完成后在原窗口只读显示，并注明结果来源通道。配置文件、手填版本基准和自动开关机预检判据保持原样。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 请求与快照 | `src/services/qt_version_query.py`、`qt_execution_adapter.py`、`qt_workspace_adapter.py`、`src/models/qt_configuration.py`、`workbench_presentation.py` |
| 界面 | `src/ui/qt/configuration_dialog.py`、`workspace_controller.py` |
| 验证 | `tests/test_qt_execution_adapter.py`、`qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`verify_baseline.py`、`verify_capability_coverage.py`、`capability_gui_actions.json`、本目录 `verify_version_qt.py` |
| 交付记录 | 根目录 `CAPABILITY_COVERAGE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`ACCEPTANCE_BASELINE.md`、`README.md`、`.claude/plans/pyside6-migration.md`、主源码 `line_check_assistant_README.md`、本目录 `MIGRATION_PROGRESS.md` 和本报告 |

## 截图与设计差异

参考图展示总览和项目详情。项目信息属于其配置子窗口，继续采用统一标签和卡片样式。第一次 150% 截图显示，查询按钮位于表单底部时需要滚动，已将其上移到通道选择旁。基准值放在上方，只读结果单独成组。窄窗口可纵向滚动到结果和动作。

- 改造前项目信息
- 改造后查询入口
- 查询结果
- 150% 缩放的窄窗口

## 验证与待验收

- 119 项相关测试通过。替换物理会话，原登录、只读命令和结果解析实际执行。验证草稿与通道冻结、取消与失效、`#` 路径、端口 0 兼容、失败反馈及收尾资源保护。
- 325 份编译、315 份源码登记、原业务、协议和能力覆盖检查通过。首次覆盖清单生成后补入 Escape 收尾保护，清单校验因动作变化提示更新。审查更新后，覆盖检查重跑通过。
- Windows 原生 Qt 在 100%、125%、150% 显式缩放下各通过 49 项，共 147 项。三档均通过私有桌面核验，隔离违规为 0。
- 本轮使用 `python validation/pyside6_migration_20261118/verify_version_qt.py`。原生测试包含 `>` 确认取消、`#` 无二次确认、Escape 及关闭保护、独立结果字段、默认尺寸动作可见及窄窗口可用性。

阶段结果 · 源码保全 · 原生复验

真实样机查询和错误分支仍待现场验收，系统实际 DPI、多屏及长期挂测待整体验收。本轮未重跑完整基线或打包。默认入口仍为 Tk，持续开机全业务老化维持待接入。下一项迁移配置窗口的消息试发。
