# Phase 5｜Qt 消息试发

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

## 原入口与迁移边界

旧 Tk 的 `MessagePushTab` 捕获当前页的 Webhook、加签密钥和 @所有人，后台调用 `send_test_message`。项目名来自磁盘配置，试发独立于自动推送开关。原服务自动识别钉钉或飞书，使用固定测试正文，以单次请求发送。超时、回执不明及平台拒绝各有原提示。

Qt 使用同一个 Webhook 输入及原服务。试发前确认项目名、平台和 @所有人，确认数据绑定本次编辑器、项目版本和窗口快照，默认选择取消。试发只读取项目已保存版本中的项目名，传给原服务的临时输入只含该名称。凭据保留在发起窗口的内存快照。成功只表示平台接受，接收结果仍由目标群确认。试发有独立状态和项目日志，等待后台收尾后可关闭，DUT 任务历史、资源和正式推送配置沿用原流程。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 发送调度与模型 | `src/services/qt_push_trial.py`、`qt_configuration_service.py`、`qt_execution_adapter.py`、`qt_workspace_adapter.py`、`src/models/qt_configuration.py`、`workbench_presentation.py` |
| 界面 | `src/ui/qt/configuration_dialog.py`、`workspace_controller.py` |
| 验证 | `tests/test_qt_execution_adapter.py`、`qt_execution_fakes.py`、`qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`verify_baseline.py`、`verify_capability_coverage.py`、`capability_gui_actions.json`、本目录 `verify_push_trial_qt.py` |
| 交付记录 | 根目录 `CAPABILITY_COVERAGE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`ACCEPTANCE_BASELINE.md`、`README.md`、`.claude/plans/pyside6-migration.md`、主源码 `line_check_assistant_README.md`、本目录 `MIGRATION_PROGRESS.md` 和本报告 |

## 运行截图与设计差异

参考图主要展示总览和运行详情。消息推送仍在六标签配置窗口，统一使用原表单卡片、宽度上限和凭据显隐。试发按钮紧邻推送表单，发送状态与保存操作共用窗口底部区域。150% 窄窗口中按钮和平台结果可见，原生测试检查无需横向滚动。

- 改造前消息推送
- 改造后试发入口
- 150% 窄窗口的模拟结果

## 验证与待验收

- 104 项相关回归通过。两个适配器使用原请求构造并拦截实际 HTTP，检查平台、签名输入、固定正文、已保存项目名、广播范围和单次请求。覆盖取消、过期确认、已保存配置变化、外部来源拒绝、凭据保护、未知结果与退出等待。
- Windows 原生专项以模拟传输验证按钮、默认取消、遮盖凭据、Escape/关闭防护、事件循环响应、成功反馈与窄窗口。
- Windows 原生 Qt 在 100%、125%、150% 显式缩放下各通过 50 项，共 150 项，隔离违规为 0。326 份编译、316 份源码登记、原业务保全与能力覆盖通过。

验证入口为 `python validation/pyside6_migration_20261118/verify_push_trial_qt.py`。阶段结果 · 源码保全 · 原生复验

真实群投递、现场操作与 Windows 实际系统 DPI 待验收。本轮为源码增量，未发送真实消息、重跑完整基线或打包。默认入口仍为 Tk，持续开机全业务老化维持待接入。下一项审计和迁移原失败轮次续跑。
