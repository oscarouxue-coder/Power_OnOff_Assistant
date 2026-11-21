# GUI测试窗口隔离与覆盖门禁验证（2026-11-18）

本轮仅调整测试设施、测试接入、VS Code任务和开发文档，未修改产品src/或主程序业务代码。保留统一工作台等同期改动；test_project_workspace.py、test_workbench_panels.py仅规范化窗口保护。版本和EXE不变，未提交、打包、发布或访问真实设备/平台/模型。

## 运行方式

在主源码目录执行`python scripts/run_tests.py discover -s tests -v`、`python scripts/run_tests.py 测试ID -v`；独立检查为`python scripts/verify_gui_test_coverage.py`。VS Code从“运行任务”选择带“离屏预检”的全量/指定测试任务。旧unittest命令不属于强制预检入口。

静态AST检查先于测试导入，检查构造/别名/子类/继承夹具/安装顺序/条件分支/上下文及可识别的Python子进程。动态Tk调用由运行时守卫在原始构造前拦截；即使异常被捕获、或unittest显示OK，违规仍使入口退出非零。每项结束拒绝并清理泄漏作用域。原生确认/文件对话框须Mock。GUI子进程必须经run_gui_child返回独立证据，报告丢失/失败/窗口数为零均失败。

## 实际结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 42个相关模块组合 | Ran 975 tests / OK，168.069秒；主进程482个受管窗口，违规0 | related_modules.json、related_tests.txt |
| 最终门禁/工具/基线入口/身份锁/原生像素复查 | Ran 78 tests / OK，7.177秒；31个受管窗口，违规0 | final_checks.txt |
| discovery模式 | Ran 21 tests / OK，3.964秒 | discovery.txt |
| 单个方法入口 | 原生像素专项Ran 1 test / OK，0.679秒 | single_test.txt |
| 最终AST覆盖检查 | 66个GUI构造位置，exit 0 | coverage.txt |
| 本轮Python局部编译 | 38份通过 | 下方文件清单 |
| 源码编译清单完整性 | 266份源码已登记；仅调用check_py_compile_inventory | 本轮命令输出 |
| VS Code任务 | JSON解析、process参数/工作目录/当前解释器/输入ID配置核对通过 | .vscode/tasks.json |
| 差异格式 | git diff --check通过；新增文件另检查尾随空格/结尾换行 | 本轮命令输出 |

最终78项包括静态/运行时门禁21项、离屏工具7项、基线脚本23项、身份/资源锁8项和通道列表19项；是收尾复查，不与975项相加冒充唯一测试数。期间追加了命名GUI子进程、未解析脚本、未包装模块子进程、跨测试同名脚本绑定、零测试拒绝等反向检查。

首轮972项组合有6个像素子场景失败：屏幕外GetDC/GetPixel返回无效值，PrintWindow也不能给出等价控件像素。保留原GetPixel、焦点与Vista/Clam六组颜色断言，改为下述隔离桌面子进程后通过。首次STARTUPINFO.lpDesktop绑定没有实际生效，被系统身份核验拦截；改为子进程显式SetThreadDesktop。随后补充伪造桌面测试暴露Windows错误消息的子进程编码不一致，统一UTF-8后收尾检查通过。已有Tk销毁阶段ThemeChanged提示仍可能出现在组合日志，不构成越界且未放宽断言。

## 原生像素测试的私有桌面适配

仅原生像素专项使用run_gui_child(native_render=True)：父进程CreateDesktopW；子进程在导入Tk前OpenDesktopW/SetThreadDesktop；通过GetThreadDesktop、OpenInputDesktop、GetUserObjectInformationW确认所在桌面名称匹配且不同于输入桌面；每次映射/配置与退出再次核对。测试不调用SwitchDesktop，完成后父进程关闭桌面句柄，失败不回退到用户桌面、不跳过断言。普通GUI测试继续保持屏幕外真实映射。

微软接口说明：[SetThreadDesktop](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setthreaddesktop)、[CreateDesktopW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-createdesktopw)。本轮验证依据为实际系统身份报告和原生像素断言，不把文档说明代替实测。

## 边界与待复核

本轮未执行完整verify_baseline.py，不覆盖此前统一工作台2940项完整基线的历史边界。此次新增第八类gui_test_coverage及4项指定回归ID，完整基线触发条件保持。产品验收§2/§3不升级。

VS Code任务未在编辑器中实际点击运行；桌面无闪烁的人工目视、实体多屏均待负责人复核。坐标/映射/原生窗口框及私有桌面身份检查已自动化通过，不能表述成人工验收。防护范围为统一入口与已适配Tk路径，绕过入口或故意绕过构造守卫的任意原生/其他GUI框架不声称自动受保护。

## 本轮文件

  - `.claude/plans/gui-test-offscreen-gate.md`
  - `.claude/skills/line-check-dev/SKILL.md`
  - `.vscode/tasks.json`
  - `AGENTS.md`
  - `README.md`
  - `ACCEPTANCE_BASELINE.md`
  - `DEVELOPMENT_LOG.md`
  - `PROJECT_STATUS.md`
  - `Cheating_machine_execution_tool\scripts\run_gui_child.py`
  - `Cheating_machine_execution_tool\scripts\run_tests.py`
  - `Cheating_machine_execution_tool\scripts\verify_baseline.py`
  - `Cheating_machine_execution_tool\scripts\verify_gui_test_coverage.py`
  - `Cheating_machine_execution_tool\tests\fixtures\gui_guard_probe.py`
  - `Cheating_machine_execution_tool\tests\serial_lifecycle_stress.py`
  - `Cheating_machine_execution_tool\tests\test_adapter_rename.py`
  - `Cheating_machine_execution_tool\tests\test_ai_actions.py`
  - `Cheating_machine_execution_tool\tests\test_ai_chat_markdown.py`
  - `Cheating_machine_execution_tool\tests\test_ai_chat_presentation.py`
  - `Cheating_machine_execution_tool\tests\test_ai_context_budget.py`
  - `Cheating_machine_execution_tool\tests\test_ai_context_usage.py`
  - `Cheating_machine_execution_tool\tests\test_ai_conversation.py`
  - `Cheating_machine_execution_tool\tests\test_ai_integration.py`
  - `Cheating_machine_execution_tool\tests\test_ai_monitor_status.py`
  - `Cheating_machine_execution_tool\tests\test_ai_multichannel_dispatch.py`
  - `Cheating_machine_execution_tool\tests\test_ai_report_target_dialog.py`
  - `Cheating_machine_execution_tool\tests\test_ai_session_deletion.py`
  - `Cheating_machine_execution_tool\tests\test_ai_session_router.py`
  - `Cheating_machine_execution_tool\tests\test_ai_workspace.py`
  - `Cheating_machine_execution_tool\tests\test_app_update_ui.py`
  - `Cheating_machine_execution_tool\tests\test_application_icon.py`
  - `Cheating_machine_execution_tool\tests\test_capability_extensions.py`
  - `Cheating_machine_execution_tool\tests\test_channel_list.py`
  - `Cheating_machine_execution_tool\tests\test_gui_test_coverage.py`
  - `Cheating_machine_execution_tool\tests\test_main_log_filter.py`
  - `Cheating_machine_execution_tool\tests\test_message_push_config.py`
  - `Cheating_machine_execution_tool\tests\test_onu_command_editor.py`
  - `Cheating_machine_execution_tool\tests\test_project_name_badge.py`
  - `Cheating_machine_execution_tool\tests\test_project_workspace.py`
  - `Cheating_machine_execution_tool\tests\test_remote_instance_identity.py`
  - `Cheating_machine_execution_tool\tests\test_resource_options.py`
  - `Cheating_machine_execution_tool\tests\test_tk_lifecycle_process.py`
  - `Cheating_machine_execution_tool\tests\test_tk_test_windows.py`
  - `Cheating_machine_execution_tool\tests\test_verify_baseline.py`
  - `Cheating_machine_execution_tool\tests\test_wifi_test_controls.py`
  - `Cheating_machine_execution_tool\tests\test_workbench_panels.py`
  - `Cheating_machine_execution_tool\tests\tk_test_windows.py`
  - `Cheating_machine_execution_tool/validation/gui_offscreen_20261118/REPORT.md`
  - `Cheating_machine_execution_tool/validation/gui_offscreen_20261118/related_modules.json`
  - `Cheating_machine_execution_tool/validation/gui_offscreen_20261118/related_tests.txt`
  - `Cheating_machine_execution_tool/validation/gui_offscreen_20261118/coverage.txt`
  - `Cheating_machine_execution_tool/validation/gui_offscreen_20261118/discovery.txt`
  - `Cheating_machine_execution_tool/validation/gui_offscreen_20261118/single_test.txt`
  - `Cheating_machine_execution_tool/validation/gui_offscreen_20261118/final_checks.txt`
