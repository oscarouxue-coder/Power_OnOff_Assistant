# 飞书SDK按需安装与安全重启（2026-11-16）

缺少飞书SDK的源码错误弹窗现提供“安装并重启”和“确定”。安装只由本机操作员主动选择；确定、Esc、关闭及其他飞书错误均不触发安装。EXE只引导更新完整ZIP。

## 实现与边界

- `MissingFeishuSdkError`识别缺包，独立Tk弹窗采用模块背景，默认焦点为确定，沿用父窗口居中。主窗口仅装配安装回调与关闭/重启交接。
- 独立service在主线程预检活动任务，后台执行下载/安装，主线程排空日志及结果。维护准入原子核对正在进入的业务，不持有互斥锁跨越UI或网络等待；原GUI、诊断、会话、意图路由、Capability及数据桥阻止新任务。已有活动任务只拒绝安装，不请求停止。
- 同环境的新源码实例在导入主程序前，以纯标准库核对环境修复互斥量；修复期间拒绝启动，避免进程扫描后又进入新实例。安装不在正常启动时自动触发，EXE跳过该源码检查。
- 仅当前CPython3.9.10 x64隔离虚拟环境可安装，实际解释器固定为`sys.executable`。环境级实例锁及进程核对拒绝同环境占用；Windows虚拟环境的启动器/底层解释器按祖先链识别，已确认的其他虚拟环境不误拦截，未知占用拒绝。
- 从现有`requirements-build.txt`生成临时精确约束，只下载飞书SDK及其必要依赖的wheel；所有实际下载的包名/版本必须在锁定清单中。核对后仅对缺失/版本不符依赖及SDK离线安装，不重新安装已符合版本的其他依赖，不引入新依赖或升级工具链。
- 子进程有超时，不通过Shell执行。主日志包含实际参数列表转换后的命令、阶段和结果；pip原输出可能含索引/代理凭据，界面和主日志只提供固定分类及退出码。安装失败可重试，旧程序保留；安装可能已部分完成时仍须重新验证，失败不自动重启。
- 验证真实SDK导入、整个下载依赖闭包的版本和`pip check`后，复用原主程序安全退出流程。只有主事件循环结束才启动隐藏助手；助手等待原PID/创建时间对应进程真正退出后，同解释器、原工作目录和业务参数启动一次。不会携带debugpy入口参数，不重试绑定/启用或重放操作。
- `remote.feishu_sdk_repair`登记为人工控制面，明确AI不可触发或代确认，未注册AI安装能力。矩阵现87项：63接入、15部分、5待接入、4人工。

## 本轮文件清单

以下路径相对仓库根目录；保留本轮开始前已有的公司MiniMax网关等改动。

新增：

- `.claude/plans/feishu-sdk-repair.md`
- `Cheating_machine_execution_tool/src/models/dependency_repair.py`
- `Cheating_machine_execution_tool/src/core/feishu_dependency_install.py`
- `Cheating_machine_execution_tool/src/core/source_restart.py`
- `Cheating_machine_execution_tool/src/services/feishu_dependency_repair.py`
- `Cheating_machine_execution_tool/src/ui/feishu_dependency_dialog.py`
- `Cheating_machine_execution_tool/src/ui/feishu_dependency_controller.py`
- `Cheating_machine_execution_tool/scripts/restart_source_after_exit.py`
- `Cheating_machine_execution_tool/scripts/source_environment_guard.py`
- `Cheating_machine_execution_tool/tests/test_feishu_dependency_repair.py`
- 本验证目录中的`run_focused.py`、`verify_install.py`、`check_static.py`、本记录，以及专项输出`focused.txt`、最终41项`repair_final.txt`、初轮失败记录`focused_initial.txt`、增加写入保护前的`focused_before_write_guard.txt`、`real_install.txt`和`static.json`。

增量修改：

- `Cheating_machine_execution_tool/src/core/feishu_stream.py`：仅将缺包错误改为专门异常。
- `Cheating_machine_execution_tool/src/services/ai_diagnostic_service.py`
- `Cheating_machine_execution_tool/src/services/ai_conversation_service.py`
- `Cheating_machine_execution_tool/src/services/ai_session_router.py`
- `Cheating_machine_execution_tool/src/services/capability_service.py`：上述四个入口增加维护期间的准入保护，不搬迁原流程。
- `Cheating_machine_execution_tool/src/ui/ai_assistant_controller.py`：装配共享维护准入。
- `Cheating_machine_execution_tool/src/ui/capability_ui_bridge.py`：维护期间拒绝新准入。
- `Cheating_machine_execution_tool/src/ui/feishu_setup_window.py`：缺包分支及可选安装回调，其他错误保持原提示。
- `Cheating_machine_execution_tool/line_check_assistant/app.py`：维护对象、回调装配、GUI准入、关闭保护和事件循环退出后的助手交接。
- `Cheating_machine_execution_tool/run_line_check_assistant.py`：源码加载前的同环境修复检查，不自动安装、不启动业务。
- `Cheating_machine_execution_tool/src/services/capability_catalog.py`
- `Cheating_machine_execution_tool/scripts/capability_gui_actions.json`
- `CAPABILITY_COVERAGE.md`：人工控制面登记及GUI动作审查快照。
- `Cheating_machine_execution_tool/scripts/verify_baseline.py`：登记新增源码和重启脚本编译，不改变完整基线触发条件或协议清单。
- `Cheating_machine_execution_tool/line_check_assistant_README.md`
- `PROJECT_STATUS.md`
- `ACCEPTANCE_BASELINE.md`：§2.16实现边界及§3待人工确认。
- `DEVELOPMENT_LOG.md`

## 验证方法

以下在仓库根目录执行；仅准备仓库外的专用测试环境，不调用标准打包入口、不构建EXE。

```powershell
$repairPython = Join-Path $env:LOCALAPPDATA 'LineCheckAssistant\feishu-repair-validation-py39\Scripts\python.exe'
powershell -NoProfile -ExecutionPolicy Bypass -File .\Cheating_machine_execution_tool\scripts\prepare_build_environment.ps1 -BasePython '<本机CPython3.9.10 x64的python.exe>' -EnvironmentDirectory (Split-Path -Parent (Split-Path -Parent $repairPython))
& $repairPython -B -X utf8 .\validation\feishu_sdk_repair_20261116\verify_install.py
& $repairPython -B -X utf8 .\validation\feishu_sdk_repair_20261116\run_focused.py
& $repairPython -B -X utf8 .\validation\feishu_sdk_repair_20261116\run_focused.py --repair-only
& $repairPython -B -X utf8 .\validation\feishu_sdk_repair_20261116\check_static.py
```

`verify_install.py`有专用环境路径及隔离校验，拒绝修改其他环境；只在该测试环境卸载SDK后执行真实修复。`run_focused.py`规范化Windows短TEMP路径、采用离屏Tk，SDK不存在或相关测试跳过均拒绝通过；对操作员配置目录的写入及原子替换设置进程内保护。

## 实际结果与历史问题

- 相关组合626项通过，当时含新增37项；真实SDK的7项离线Protobuf/ACK/生命周期检查实际执行，无跳过。随后补充同环境新实例启动保护及源码入口验证，最终41项新增专项通过。Vista/Clam两主题的两个按钮、确定/关闭行为及背景通过；在真实Windows子进程中以假入口验证等待原PID退出后仅启动一次，不启动实际主程序。最终41项见`repair_final.txt`，不将626项组合表述为包含后续4项。
- 仓库外隔离环境准备后`BUILD_ENVIRONMENT_OK`及`pip check`通过。模拟缺包后，真实下载15种受锁定约束的SDK/必要依赖wheel，仅重新安装缺失的SDK；真实导入、闭包版本及依赖一致性全部通过，输出`REAL_FEISHU_REPAIR_OK`。未更改当前源码运行环境的依赖。
- 21个相关Python文件局部编译、235份主源码登记、GUI覆盖及差异检查结果记录在`static.json`；这不等于完整基线，本轮未运行完整基线，保留项目现有最近完整记录。
- 新增源码入口保护后，以同一隔离解释器在主源码目录执行`python -B -X utf8 -c "import sys,unittest; sys.path.insert(0,'tests'); suite=unittest.defaultTestLoader.loadTestsFromNames(['test_verify_baseline','test_portable_release']); result=unittest.TextTestRunner(verbosity=1).run(suite); sys.exit(not result.wasSuccessful())"`，30项编译门禁自身及便携交付专项通过，没有运行完整基线或构建/启动EXE。
- 首轮新增27项中，重启命令断言混用Windows短/长临时路径，改为规范化期望路径后通过；初次625项组合有4失败/4错误，原因是新增回调直接读取旧Tk测试宿主不存在的方法，改为延迟调用原主程序入口，单独10项远程管理回归及之后组合通过，不删除或放宽原断言。
- 开发期间`network_card_ip.ini`和`sample_upgrade_settings.ini`出现本轮需求以外的同期变更，来源未确证；保留当前文件，不还原或纳入本轮实现。最终专项增加操作员配置写入保护，差异格式检查排除本轮不涉及的本机配置目录，避免改动其原有空值格式。

## 待确认

负责人重启源码程序后，按操作员说明人工核对完整缺包弹窗、安装进度、错误重试、任务占用拒绝及实际主程序安全重启。离屏Tk、真实SDK离线、隔离环境安装和假入口重启不替代完整Windows/真实飞书/模型/DUT验收。本轮未操作真实设备或外发消息，未构建、运行EXE、提交、推送或发布。
