# Qt 旧项目导入与 DUT 配置显示修正

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

2026-11-19。紧接[语音和TR069阶段](VOICE_TR069_REPORT.md)的完整基线，本轮补齐旧项目导入并修正两处影响实际操作的行为。

- 从工作台「项目 → 导入旧配置目录…」选择旧程序或配置目录、新名称以及独立的空目标目录。使用原 `WorkspaceService.import_project` 备份原始输入、核对哈希、转换配置和历史、登记新项目。导入在原项目后台线程运行，完成后选中新项目。源与目标重叠时在写入前拒绝。旧项目和历史任务保留，已导入的平台配置沿原流程保持禁用，实际启用待单独确认。
- 原 Qt 执行适配器误把通道配置文件路径传给 `SampleUpgradeSettingsStore`，导致 DUT 窗口读不到已保存的写参初始凭据。改为读取当前项目的 `sample_upgrade_settings.ini`。独立回归先在旧代码复现空账号，再核对读回正确字段、两个配置文件字节一致及无设备调用。
- TR069查询结果将设备未报告的 ACS、周期 Inform 和间隔显示为「未报告」，保留原查询模型、配置能力、下发顺序和结果判定。设备明确返回已停用时才显示「停用」。此处只调整结果呈现。

相对主源码目录，变更 `src/services/qt_workspace_adapter.py`、`src/ui/qt/workspace_controller.py`、`src/services/qt_execution_adapter.py`、`src/ui/qt/dut_configuration_dialog.py`。验证包括 `tests/test_qt_workspace_adapter.py`、`tests/test_qt_dut_configuration.py`、`tests/qt_workbench_probe.py`，更新了 Qt 必跑清单、能力覆盖脚本与快照，新增 `validation/pyside6_migration_20261118/verify_qt_followup.py`。同步开发日志、项目状态、验收、能力、计划与操作员文档。

验证入口为 `python validation/pyside6_migration_20261118/verify_qt_followup.py`。75项相关回归、306个文件编译、296份源码登记、509个GUI动作审查及原业务保全通过。三档 Windows 原生共36×3=108项通过，每档963个受管窗口、违规0。见顺序结果和原生详情。本轮未复跑完整基线。3,093项完整基线对应此前DUT六页检查点。

改前项目菜单无旧目录导入，DUT结果中缺失字段可能显示为停用或空白。实测图中，导入后新项目被选中，日志列有备份和校验结果；窄窗中缺失字段显示为「未报告」，底部操作保持可见。总览沿用当前布局，入口位于项目菜单。系统DPI、多屏、真实DUT和长期运行待现场验收。改前总览 · 改后导入总览 · 改前TR069结果 · 改后TR069结果
