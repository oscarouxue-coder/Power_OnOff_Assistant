# Qt 检查更新与便携包下载

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 5 与 Phase 8 更新客户端兼容。

## 审计与迁移

原 Tk 窗口从 `AppUpdateService` 获取正式发布信息，交由操作员决定是否下载、保存位置和是否覆盖，后台校验 ZIP 大小、SHA256 和格式。Qt 的全局设置新增「检查更新」，沿用同一服务、兼容附件名和原临时文件保护。当前版本从 Qt 源码版说明或便携 EXE 同目录的 `VERSION_INFO.txt` 读取，识别失败会显示错误。

手动检查后可查看版本、日期、说明和包大小。选择已有 ZIP 时覆盖默认取消，只有原服务校验成功后才可覆盖。成功后可以打开所在文件夹，安装和配置迁移按原手动流程进行。下载状态显示大小与阶段，启动工作台保持离线。

更新线程与项目命令队列独立。关闭更新窗会请求取消，清理完毕前再次打开不会创建重复任务。退出工作台同时等待项目与更新任务收尾。下载检查、校验及取消进入工作区日志。

此前 Qt 顶栏的全局设置为待迁移项。本次保留其位置并启用菜单。更新对话框沿用 Qt 主题，版本和日期分行，底部保留下载与取消入口。参考图未单列更新窗口。[改造前工作台报告](PHASE1_2_REPORT.md) · 更新对话框原生截图，150%

## 修改文件

- `src/services/qt_app_update.py`、`src/services/qt_workspace_adapter.py`
- `src/ui/qt/app_update_dialog.py`、`src/ui/qt/main_window.py`、`src/ui/qt/workspace_controller.py`
- `tests/test_app_update.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`
- 工程状态、开发日志、验收基线、能力覆盖、操作员说明及迁移进度

## 复验命令

```powershell
python scripts/run_tests.py test_app_update test_app_update_ui test_capability_application test_portable_release test_qt_workspace_adapter test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_app_update_verified
```

首轮 150% 界面截图中，按钮文字夹在旧状态宽度内，进度条百分比与细条重叠。最终窗口按最长按钮文案保留宽度，进度百分比显示在状态文字中。

## 验证结果

- 134 项相关回归通过，涵盖原更新服务和窗口、便携交付边界、能力接口、Qt 工作区和版本说明取值。新增测试核对源码和便携目录版号读取，无法识别时返回错误。
- 361 份文件编译、351 份源码登记、能力覆盖、GUI 守卫、原协议及旧核心源码保全检查通过。
- 100%、125%、150% 的完整原生套件各通过 71 项，共 213 项。每档管理 1,206 个顶层 Qt 窗口，隔离违规为零。覆盖下载位置、拒绝覆盖、校验失败保留原 ZIP、成功后打开目录入口，以及退出等待取消后清理。首轮 125% 在既有关闭测试的 Qt 清理路径发生 Windows 原生访问异常，子进程未生成隔离报告。随后在同一源码和私有桌面条件下整档复跑通过，崩溃原因未定位。
- 复验通过后清理 318 份本轮过程截图、日志和结果文件，约 16.0 MiB。保留本报告及 150% 代表截图。

## 待验收范围

更新路径用本地合成 ZIP 和模拟发布响应验证。真实发布、目标机便携版检查及手动配置迁移待验收。本轮未运行完整基线或重建 EXE。必要时可从原 Tk「检查更新」入口执行同一更新服务。
