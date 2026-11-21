# Qt AI 模型连接

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 5。

## 审计与迁移

旧 AI 窗口的模型连接页由 `AiDiagnosticsWindow` 装配。它通过 `WorkspaceService.ai_store()` 和 `ProjectDiagnosticStore` 共享账号，通过各项目的设置保存选择。原 `DiagnosticStore` 负责地址、超时、协议和 Token 校验，以及加密密钥绑定和能力指纹失效。模型刷新和测试调用 `DiagnosticModelClient`，使用现有出口 IP 配置和固定的无项目资料样例。Qt 继续使用这些入口。

Qt 主工具栏和项目详情的「AI 模型连接」打开当前项目的配置窗。可以新增、选择、复制和删除共享配置，修改协议、模型 ID、超时、输出和上下文设置。复制生成新账号，保留配置字段，密钥须另行输入。原账号同地址留空时保留密钥。删除提示共享影响并默认否。Windows 输入密钥经原存储加密，模型窗和工作台日志不回显已保存密钥。

出口 IP 从原本机 IPv4 枚举获取，选择时复核网卡可用性，结果先写入界面草稿。模型刷新和测试沿用先保存当前配置再调用原客户端的行为。绑定当前项目和保存快照，后台处理网络请求。全局一次执行一个模型探测，项目任务控制继续处理。项目关闭取消对应请求并跳过迟到结果。程序退出等待原请求收尾。共享配置在请求期间发生身份变化时，旧结果无法更新能力指纹。

## 修改文件

- `src/models/qt_model_settings.py`、`src/services/qt_model_settings.py`、`src/services/qt_workspace_adapter.py`
- `src/ui/qt/model_settings_controller.py`、`src/ui/qt/model_settings_dialog.py`、`src/ui/qt/main_window.py`、`src/ui/qt/project_detail.py`、`src/ui/qt/workspace_controller.py`
- `tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`scripts/verify_baseline.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`
- 工程状态、开发日志、验收基线、能力覆盖、迁移进度和操作员说明

## 验证命令

```powershell
python scripts/run_tests.py test_qt_workspace_adapter test_ai_source_ip test_ai_context_budget test_project_management test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_model_settings_final
```

初测发现原自动导入路径会读取本机旧模型库，影响临时项目空配置断言。已在测试夹具把旧库和案例库固定到临时目录，保留正常启动的原导入行为。后续验证使用合成账号、模型客户端替身和原测试中的本机回环。真实模型供应商和真实设备另行验收。

## 结果与剩余验收

- 104 项相关回归通过。覆盖 Windows 加密写入、留空保留、跨项目共享与选择隔离、陈旧编辑保护、模型容量缓存、连接上下文和退出取消。正常模型请求参数由客户端替身验证。相关回归
- Windows 私有桌面 100%、125%、150% 各通过 65 项，共 195 项。各档管理 1,168 个 Qt 顶层窗口，隔离违规为零。新增用例覆盖项目和工具栏入口、密码遮蔽、刷新、测试、复制及取消删除。三档原生结果 · 150% 实际界面
- 348 份文件编译、338 份源码登记、能力覆盖、GUI 门禁、协议不变量及原业务保全通过。源码检查
- 当前入口已支持模型连接配置。本地会话、诊断目标、报告、审批和远程接入继续按计划迁移。实际模型出站、真实设备、目标电脑与长挂仍待验收。本轮未重跑完整基线或重建 Windows 包。
