# 开发记录

本文件用于按时间记录每次开发完成的功能、优化、修改、BUG 修复、验证方式和后续待办，方便下一次继续开发，也方便做整体项目概览和管理。

## 2026-09-01 - 未恢复出厂的全包升级改为 3 秒传输后收尾

- 类型：全包升级流程调整 / 测试 / 文档
- 背景：项目负责人要求两条全包升级路径在未勾选“恢复出厂”时，不再等待最终系统启动或登录；传输后完成 `reset` 或后备重新上电后，短暂等待即可结束当前通道。
- 完成内容：`Tftp指令` 与 `Tftp Put` 均在传输后继续观察 90 秒 `Boot/Bood`；识别到时仍延迟 1 秒发送 `reset`，未识别到时仍对当前通道执行后备下电再上电。未勾选恢复出厂时，两种动作后均只等待 3 秒，记录“跳过最终系统登录”并将当前通道标记成功；勾选恢复出厂时保持原 120 秒等待、最终系统登录和恢复出厂时序。后备上下电默认时序、首轮入 boot 的 1 秒/1 秒时序、TFTP 传输方式和并行边界均未改动。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 `tests/test_serial_upgrade_service.py` 专项测试、`python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：`tests/test_serial_upgrade_service.py` 专项 39 项通过；以本机端口绑定权限运行 `python scripts/verify_baseline.py` 全绿，59 个源码文件编译、742 项单元测试、172 项强制基线测试及协议不变量均通过。未运行 EXE，未连接真实样机。
- 后续待办：在 Windows 源码版及真实样机分别确认两条路径的 `reset` / 后备重新上电后 3 秒结束、无最终系统登录，以及勾选恢复出厂后的原收尾链路。

## 2026-09-01 - Tftp Put 传输后未自动复位时改为后备重新上电

- 类型：全包升级流程调整 / 程控电源 / 测试 / 文档
- 背景：`Tftp Put` 上传完成后未在串口观察到 `Boot/Bood` 时，原逻辑只等待 120 秒再登录最终系统；项目负责人要求与 `Tftp指令` 的传输后复位逻辑一致。
- 完成内容：`Tftp Put` 保持既有本机 TFTPy Client 上传、源 IP 绑定、首次进入 boot 的 1 秒/1 秒上下电时序和并行机制不变。上传后观察 90 秒：检测到 `Boot/Bood` 仍延迟 1 秒下发 `reset` 并等待 120 秒；未检测到时，已配置程控电源则仅对当前通道执行一次后备下电再上电、等待 120 秒后再登录最终系统。后备上下电刻意保持普通默认时序，不复用首轮进入 boot 的 1 秒/1 秒专用时序；未配置程控电源时记录跳过后备上电。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 `tests/test_serial_upgrade_service.py` 专项测试、`python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：`tests/test_serial_upgrade_service.py` 专项 39 项通过；以本机端口绑定权限运行 `python scripts/verify_baseline.py` 全绿，59 个源码文件编译、742 项单元测试、172 项强制基线测试及协议不变量均通过。受限环境直接运行全量测试时，两个既有 TFTP 监听测试因 UDP 69 `WinError 10013` 报错；以本机权限复跑后通过。未运行 EXE，未连接真实样机。
- 后续待办：在 Windows 源码版及真实样机分别确认 Tftp Put 未出现 `Boot/Bood` 时的当前通道后备上下电、120 秒等待和最终系统登录；自动化通过不替代现场验收。

## 2026-08-31 - 通道历史改为独立滚动窗口

- 类型：界面优化
- 背景：通道重试/失败历史嵌入主界面会挤压通道概览，且当前状态摘要被固定宽度换行。
- 完成内容：点击通道小卡改为复用一个非模态、可滚动的独立历史窗口；窗口仅显示当前点击通道的本次历史，并在打开期间随新事件刷新。主界面不再嵌入历史文本框，只保留不换行的当前摘要。
- 修改文件：
  - `Cheating_machine_execution_tool/line_check_assistant/app.py`
  - `Cheating_machine_execution_tool/tests/test_app.py`
  - `Cheating_machine_execution_tool/line_check_assistant_README.md`
  - `PROJECT_STATUS.md`
  - `ACCEPTANCE_BASELINE.md`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行 `python -m unittest discover -s tests -p test_app.py -v`、`python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：主界面专项 `test_app.py` 189 项通过；`python scripts/verify_baseline.py` 已通过，`git diff --check` 无空白错误。未构建或运行 EXE，未连接真实设备。
- 后续待办：Windows 源码版确认独立窗口首次显示、滚动、关闭后重开和主界面摘要单行显示。

## 2026-08-31 - 保留通道重试与失败历史

- 类型：功能
- 背景：操作员需要在主界面通道概览中点击任一通道，查看本次开关机测试完整且独立的重试/失败明细，不能因后续重试成功或主日志精简而丢失。
- 完成内容：旧工具原始日志在精简和去重前提取通道重试、重试后成功和最终失败事件，并随所属测试轮次安全投递到 Tk 主线程；主界面按通道仅在内存中保存本次历史，点击小卡后以下方可滚动区域按发生顺序显示。重新启动测试只清空本次选中通道的历史，不改变重试策略、设备命令、确认、停止、旧结果日志或持久化配置。
- 修改文件：
  - `Cheating_machine_execution_tool/src/services/legacy_power_test_service.py`
  - `Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`
  - `Cheating_machine_execution_tool/line_check_assistant/app.py`
  - `Cheating_machine_execution_tool/tests/test_legacy_power_test_service.py`
  - `Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`
  - `Cheating_machine_execution_tool/tests/test_app.py`
  - `Cheating_machine_execution_tool/line_check_assistant_README.md`
  - `PROJECT_STATUS.md`
  - `ACCEPTANCE_BASELINE.md`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行三个专项 unittest、`python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：专项 `test_legacy_power_test_service.py` 16 项、`test_pipeline_orchestrator.py` 47 项、`test_app.py` 188 项均通过；`python scripts/verify_baseline.py` 已通过，`git diff --check` 无空白错误。未构建或运行 EXE，未连接真实设备；Windows 源码版/真实样机异常路径仍待确认。
- 后续待办：Windows 源码版确认小卡点击后的滚动历史布局，以及真实样机确认多通道重试、重试后成功和最终失败三种事件。

## 2026-08-31 - 收紧通道概览空白间距

- 类型：优化
- 背景：项目负责人确认通道概览没有落后或异常通道时，空白“关注”标签仍占用一行，造成摘要和通道小卡之间出现无意义留白。
- 完成内容：无关注内容时直接隐藏该标签，并重新排列通道小卡和详情；出现落后、重试或失败项时才显示“关注”行，展开/收起和状态语义不变。
- 修改文件：
  - `Cheating_machine_execution_tool/line_check_assistant/app.py`
  - `Cheating_machine_execution_tool/tests/test_app.py`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行主界面专项测试、`python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：主界面专项 `Ran 186 tests ... OK`；以本机权限运行完整门禁，59 个源码文件编译、737 项单元测试、172 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`；`git diff --check` 无空白错误。未构建或运行 EXE，未连接真实设备。
- 后续待办：Windows源码版确认正常、落后和失败三种状态下概览卡片的垂直间距。

## 2026-08-31 - 合并通道概览折叠入口

- 类型：优化
- 背景：项目负责人确认通道概览标题与右侧独立“收起/展开”按钮分离后视觉不够紧凑。
- 完成内容：将标题和折叠操作合并为左侧无边框入口“通道概览（收起/展开）”，保留原有点击折叠语义、状态文字和通道概览内容。
- 修改文件：
  - `Cheating_machine_execution_tool/line_check_assistant/app.py`
  - `Cheating_machine_execution_tool/tests/test_app.py`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行主界面专项测试、`python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：主界面专项 `Ran 186 tests ... OK`；以本机权限运行完整门禁，59 个源码文件编译、737 项单元测试、172 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`；`git diff --check` 无空白错误。未构建或运行 EXE，未连接真实设备。
- 后续待办：Windows源码版确认折叠入口在不同显示缩放下的对齐和可点击性。

## 2026-08-31 - 增加开关机通道概览

- 类型：功能
- 背景：多通道开关机测试的轮次可能不一致；原先把重试/失败状态着色在左侧配置列表会干扰通道配置与选择。项目负责人确认将运行态集中显示在主界面测试卡。
- 完成内容：① 旧 Start All 日志桥接新增每个已选通道的独立完成轮次与当前阶段回传，编排器继续在 Tk 主线程更新界面；② 主界面测试卡新增可折叠“通道概览”、当前轮完成数量、运行/重试/失败汇总、仅含落后/异常项的关注行，以及可点击的通道详情小卡；③ 左侧通道列表恢复为配置、勾选和结果日志入口，不再以运行态着色；④ 总进度继续按最慢通道的已完成轮次计算，停止、失败和最终逐通道结论保持原有语义。
- 修改文件：
  - `.claude/plans/power-test-channel-overview.md`
  - `Cheating_machine_execution_tool/src/services/legacy_power_test_service.py`
  - `Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`
  - `Cheating_machine_execution_tool/line_check_assistant/app.py`
  - `Cheating_machine_execution_tool/tests/test_legacy_power_test_service.py`
  - `Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`
  - `Cheating_machine_execution_tool/tests/test_app.py`
  - `Cheating_machine_execution_tool/line_check_assistant_README.md`
  - `PROJECT_STATUS.md`
  - `ACCEPTANCE_BASELINE.md`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行开关机 service、全流程编排与主界面专项单测，再执行 `python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：开关机 service 专项 `Ran 15 tests ... OK`、全流程编排专项 `Ran 47 tests ... OK`、主界面专项 `Ran 186 tests ... OK`；以本机权限运行完整门禁，59 个源码文件编译、737 项单元测试、172 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`；`git diff --check` 无空白错误。未构建或运行 EXE，未连接真实设备。
- 后续待办：Windows源码版以不同进度的多通道测试，确认概览展开/收起、关注行、点击详情、左侧列表不变色及停止/失败后的保留显示；真实样机结论由项目负责人提供后更新验收状态。

## 2026-08-31 - 开关机测试逐通道重试状态与结束汇总

- 类型：交互优化 / 旧 Start All 日志桥接 / 测试 / 文档。
- 完成内容：① 旧 Telnet/SSH 指令的每次可继续验证失败会回传“通道、指令、当前次数、总次数”，主执行日志显示黄色，左侧对应通道改为黄色；② 重试后该指令验证成功会即时改为绿色并记录重试成功；③ 重试耗尽会保留完整指令和验证次数、以红色日志和红色通道显示；④ 旧业务每个通道完成都会回传最终成功/失败，全部通道结束后的提示逐行显示实际结论，不再只显示失败通道编号；⑤ 保持失败通道隔离、其余通道继续、危险全断电确认和全流程致命失败边界不变。
- 修改文件：`Auto_power_on_off_tool/clients/telnet_client.py`、`Auto_power_on_off_tool/clients/ssh.py`、`Auto_power_on_off_tool/test_case/powe_on_off_telnet.py`、`Auto_power_on_off_tool/test_case/power_on_off_ssh.py`、`src/services/legacy_power_test_service.py`、`src/services/pipeline_orchestrator.py`、`line_check_assistant/app.py`、`line_check_assistant/pipeline_window.py`、相关单元测试及本轮状态文档。
- 验证方法：在 `Cheating_machine_execution_tool` 执行开关机 service、全流程编排、全流程窗口和主界面专项单测，再执行 `python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：`py_compile` 通过；开关机 service 专项 `Ran 14 tests ... OK`、全流程编排专项 `Ran 47 tests ... OK`、全流程窗口专项 `Ran 31 tests ... OK`、主界面专项 `Ran 184 tests ... OK`；`git diff --check` 无空白错误。完整基线已执行：59 个源码文件编译、编译清单和全部协议不变量通过；全量 734 项单测仅 2 项既有 TFTP 绑定用例因当前环境禁止绑定 UDP 69（`WinError 10013`）报错，非本轮开关机改动路径，故未将完整基线误报为全绿；未构建或运行 EXE，未连接真实样机。
- 后续待办：Windows 源码版选择多通道并人为触发“重试后成功”和“重试耗尽”各一次，确认左侧黄/绿/红切换、日志字体颜色和逐通道结束提示；真实样机结论由项目负责人提供后更新验收状态。

## 2026-08-31 - 打开选中通道的开关机日志

- 类型：功能 / 测试 / 文档
- 背景：项目负责人需要在主界面左侧选中通道后，通过右键直接查看该通道本次最新的开关机运行日志，例如通道2的`device_2_command_results_20260831002652.log`。
- 完成内容：① 新增独立service，仅在`Auto_power_on_off_tool/test_results/device_N/`匹配当前通道的`device_N_command_results_*.log`，按文件名时间戳选择最新文件；② 左侧通道列表右键先同步鼠标所在行，再提供“打开本次开关机运行日志”；③ 仅调用Windows关联程序打开既有文件，不读取后改写、重命名或清理结果日志，不触发电源/设备/全流程操作；④ 成功、未找到、定位失败和打开失败均写入主执行日志；⑤ 新增通道隔离、时间戳排序、非法编号、菜单入口和打开/未找到反馈回归，并加入编译清单和强制基线测试。
- 修改文件：
  - `.claude/plans/open-selected-power-test-log.md`
  - `Cheating_machine_execution_tool/src/services/power_test_log_service.py`
  - `Cheating_machine_execution_tool/src/services/__init__.py`
  - `Cheating_machine_execution_tool/line_check_assistant/app.py`
  - `Cheating_machine_execution_tool/tests/test_power_test_log_service.py`
  - `Cheating_machine_execution_tool/tests/test_app.py`
  - `Cheating_machine_execution_tool/scripts/verify_baseline.py`
  - `Cheating_machine_execution_tool/line_check_assistant_README.md`
  - `ACCEPTANCE_BASELINE.md`
  - `PROJECT_STATUS.md`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在`Cheating_machine_execution_tool`执行`python -m unittest discover -s tests -p test_power_test_log_service.py -v`、`python -m unittest discover -s tests -p test_app.py -v`、`python scripts/verify_baseline.py`与`git diff --check`。
- 验证结果：新增日志定位专项`Ran 3 tests ... OK`；主界面专项`Ran 183 tests ... OK`；以本机权限运行完整门禁，59个源码文件编译、731项单元测试、172项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`。初次沙箱执行受UDP 69端口权限限制导致两项既有TFTP测试无法绑定，并出现一项既有Telnet首包并发竞争；以本机权限重跑全绿。未构建或运行EXE，未连接真实设备。
- 后续待办：Windows源码版右键通道2，确认只打开该通道最新日志、没有日志时提示明确，且不开启设备或电源操作；无需真实设备命令。

## 2026-08-31 - 开关机测试启动前逐台版本预检

- 类型：功能 / 安全预检 / 测试 / 文档
- 背景：项目负责人要求执行全流程子任务7“执行开关机测试”前，先核对全部已勾选通道的实际软件版本、内部软件版本和 ONU 软件编译时间，只有全部与“项目信息”手动填写的基准一致才允许开始。
- 完成内容：① 复用锁源 Telnet 只读查询，对实际选中测试方案的 `[project_info]` 三项手动基准逐台比对；② 三项基准任一为空时直接拦截，不查询、不执行；③ 任一通道查询失败或任一字段不一致时，主执行日志列出通道与期望/实际差异，并作为致命失败终止全流程；④ 只有全部通道三项一致后，才调用旧 Start All；版本预检失败路径绝不下发全通道断电帧或启动旧业务；⑤ 增加三项字段差异、全部已勾选通道逐台核对、差异拦截与空基准拦截回归。
- 修改文件：
  - `Cheating_machine_execution_tool/src/services/device_project_info_service.py`
  - `Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`
  - `Cheating_machine_execution_tool/src/services/__init__.py`
  - `Cheating_machine_execution_tool/tests/test_device_project_info_service.py`
  - `Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`
  - `Cheating_machine_execution_tool/line_check_assistant_README.md`
  - `ACCEPTANCE_BASELINE.md`
  - `PROJECT_STATUS.md`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行版本查询、全流程编排专项测试，再执行 `python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：版本查询专项 `Ran 3 tests ... OK`、全流程编排专项 `Ran 47 tests ... OK`、旧 Start All 专项 `Ran 13 tests ... OK`；以本机权限运行完整门禁，58 个源码文件编译、724 项单元测试、171 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`。未构建或运行 EXE，未连接真实样机。
- 后续待办：Windows源码版勾选多台、仅选择子任务7，分别确认全匹配后才出现旧 Start All 启动日志，以及字段不一致/查询失败/基准为空时只显示版本预检失败且没有电源帧；真实样机结论待项目负责人确认。

## 2026-08-31 - 更新主界面工具名称

- 类型：界面文案 / 文档 / 测试
- 背景：项目负责人将本工具名称调整为“openWRT老化测试环境搭建助手”。
- 完成内容：主界面 Windows 标题栏及操作员说明已统一为新名称；内容区仍不重复显示应用名称，既有功能、配置和执行语义均不变。
- 修改文件：
  - `Cheating_machine_execution_tool/line_check_assistant/app.py`
  - `Cheating_machine_execution_tool/tests/test_app.py`
  - `Cheating_machine_execution_tool/line_check_assistant_README.md`
  - `ACCEPTANCE_BASELINE.md`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行主程序专项测试、`python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：主程序专项 `Ran 179 tests ... OK`；以本机权限运行完整门禁，58 个源码文件编译、724 项单元测试、171 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`。未构建或运行 EXE，未连接或操作真实设备。
- 后续待办：Windows源码版确认标题栏显示新名称；无需执行真实设备命令。

## 2026-08-30 - 项目信息查询结果支持鼠标复制

- 类型：交互优化 / 测试 / 文档
- 背景：项目负责人需要将“查询当前样机版本”得到的软件版本、内部软件版本和 ONU 软件编译时间直接复制，用于其它工具或记录。
- 完成内容：① 查询结果由不可编辑的只读文本框显示，手动输入框仍独立保留；② 结果文本可用鼠标拖拽选择后按 Ctrl+C 复制；③ 每项结果右键提供“复制全部”，直接复制该字段完整内容到系统剪贴板；④ 复制不改变查询结果、手动配置、保存状态或 INI。
- 修改文件：
  - `Cheating_machine_execution_tool/line_check_assistant/app.py`
  - `Cheating_machine_execution_tool/tests/test_app.py`
  - `Cheating_machine_execution_tool/line_check_assistant_README.md`
  - `ACCEPTANCE_BASELINE.md`
  - `PROJECT_STATUS.md`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行主程序专项测试，再执行 `python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：主程序专项 `Ran 178 tests ... OK`；以本机权限运行完整门禁，58 个源码文件编译、719 项单元测试、171 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`。未构建或运行 EXE，未连接真实样机。
- 后续待办：Windows源码版确认三项只读文本可拖拽选择、右键“复制全部”准确写入剪贴板，且不能编辑或影响上方手动输入框；真实样机只读查询结论待项目负责人确认。

## 2026-08-30 - 项目信息查询结果与手动版本字段分离

- 类型：交互优化 / 测试 / 文档
- 背景：项目负责人要求“查询当前样机版本”得到的软件版本、内部软件版本和 ONU 软件编译时间必须独立展示，不允许手动修改，并保留原有三项手动输入框；查询不能覆写手动配置。
- 完成内容：① “项目信息”页保留项目名称及三项版本信息的可手动编辑输入框和既有保存语义；② 新增“当前样机查询结果（只读）”区域，展示三项 Telnet 查询结果；③ 查询成功只更新该只读区域，不再标记配置为待保存，也不覆写或写入手动输入框；④ 查询仍只下发 `cat /etc/config/deviceinfo`、`cat /proc/version`，不改变设备；⑤ 操作员说明、项目状态与验收不变量同步为独立只读展示边界。
- 修改文件：
  - `Cheating_machine_execution_tool/line_check_assistant/app.py`
  - `Cheating_machine_execution_tool/tests/test_app.py`
  - `Cheating_machine_execution_tool/line_check_assistant_README.md`
  - `ACCEPTANCE_BASELINE.md`
  - `PROJECT_STATUS.md`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行主程序专项测试，再执行 `python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：主程序专项 `Ran 178 tests ... OK`；以本机权限运行完整门禁，58 个源码文件编译、719 项单元测试、171 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`。初次沙箱全量测试因 UDP 69 绑定被拒绝出现既有两项 TFTP `WinError 10013`，以本机权限重跑通过；未构建或运行 EXE，未连接真实样机。
- 后续待办：Windows源码版用当前通道连接测试样机，核对三项查询值仅出现在只读区域，手动输入框内容和保存结果均不变；真实样机只读查询结论待项目负责人确认。

## 2026-08-30 - 加宽主界面测试通道列表

- 类型：优化
- 背景：主界面左侧“选择测试通道”列表宽度不足，已启用通道的 VLAN / COM 信息尾部被截断，操作员无法完整核对目标。
- 完成内容：① 将主界面通道列表由 26 个字符宽度扩大为 34 个字符宽度；② 保持通道勾选、双击切换、当前行选择、配置保存和执行目标语义不变；③ 增加布局回归测试，并同步操作员说明和验收基线。
- 修改文件：
  - `Cheating_machine_execution_tool/line_check_assistant/app.py`
  - `Cheating_machine_execution_tool/tests/test_app.py`
  - `Cheating_machine_execution_tool/line_check_assistant_README.md`
  - `ACCEPTANCE_BASELINE.md`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行主程序专项测试，再执行 `python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：主程序专项 `Ran 178 tests ... OK`；以正常主机权限运行完整门禁，58 个源码文件编译、719 项单元测试、171 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`。未构建或运行 EXE，未执行真实设备命令。
- 后续待办：Windows源码版核对 `channel_N  VLANxxx / COMxx` 在主界面列表中完整显示；不需要重新执行真实设备命令。

## 2026-08-30 - 跳过无人值守写参完成提示

- 类型：BUG 修复
- 背景：用户现场执行全流程无人值守时，子任务4“写样机参数”虽然跳过了启动确认，但完成后仍弹出“批量写参完成”提示框，阻塞后续子任务。
- 完成内容：① 全流程无人值守启动写参时设置仅本次有效的完成提示抑制标记；② 批量写参完成后，无人值守路径把成功或失败汇总写入主执行日志，不显示中间完成/失败提示框，再通知编排器继续或按失败终止；③ 手动写参保持原有完成提示；④ 写参未启动或完成后均清除该标记，避免影响后续手动操作；⑤ README、项目状态、验收基线和强制回归测试同步更新。
- 修改文件：
  - `Cheating_machine_execution_tool/line_check_assistant/app.py`
  - `Cheating_machine_execution_tool/tests/test_app.py`
  - `Cheating_machine_execution_tool/scripts/verify_baseline.py`
  - `Cheating_machine_execution_tool/line_check_assistant_README.md`
  - `ACCEPTANCE_BASELINE.md`
  - `PROJECT_STATUS.md`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行主程序、全流程编排和窗口专项测试，再执行 `python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：主程序专项 `Ran 177 tests ... OK`、全流程编排与窗口专项 `Ran 74 tests ... OK`；以正常主机权限运行完整门禁，58 个源码文件编译、718 项单元测试、171 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`。未构建或运行 EXE，未执行真实样机流程。
- 后续待办：Windows源码版以无人值守勾选子任务4及后续子任务，确认写参结束不弹“批量写参完成”、日志保留结果且能继续；真实样机全流程端到端验收仍待项目负责人确认。

## 2026-08-30 - 跳过环境检查后的任务等待

- 类型：优化
- 背景：用户补充要求：全流程子任务2“环境线路检查”执行完成后不需要等待120秒，应直接开始下一项。
- 完成内容：① 将环境线路检查加入子任务间隔例外，成功后直接进入下一项；② 串口日志预启动例外保持不变；③ 自动上/下电及其余非例外子任务之间仍固定等待120秒，末项仍不等待，停止事件仍可中断等待；④ 总确认文案、操作员说明、项目状态、验收基线和强制回归用例同步更新。
- 修改文件：
  - `Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`
  - `Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`
  - `Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`
  - `Cheating_machine_execution_tool/tests/test_pipeline_window.py`
  - `Cheating_machine_execution_tool/scripts/verify_baseline.py`
  - `Cheating_machine_execution_tool/line_check_assistant_README.md`
  - `ACCEPTANCE_BASELINE.md`
  - `PROJECT_STATUS.md`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行全流程编排与窗口专项测试，再执行 `python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：全流程编排与窗口专项 `Ran 74 tests ... OK`；以正常主机权限运行完整门禁，58 个源码文件编译、717 项单元测试、170 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`。未构建或运行 EXE，未执行真实样机流程。
- 后续待办：Windows源码版选择“环境线路检查”和至少一个后续任务，确认环境检查成功后直接开始下一项；真实样机全流程端到端验收仍待项目负责人确认。

## 2026-08-30 - 新增样机版本只读查询

- 类型：功能
- 背景：用户要求在“测试项配置 → 项目信息”保留既有输入框，并通过 Telnet 获取样机的软件版本、内部软件版本和 ONU 软件编译时间后覆写对应输入框。
- 完成内容：① 新增锁源 Telnet 只读查询 service，登录后只下发 `cat /etc/config/deviceinfo` 与 `cat /proc/version`；② 从 `software_version`、`inner_sw_version` 和 `/proc/version` 中解析并回填三项输入框；③ 查询使用主界面当前选中通道的 PC 静态 IP / 样机管理 IP 和 Telnet 页当前参数，不自动保存、不下发配置、重启或升级命令；④ 主执行日志记录连接、登录、实际只读命令、成功或失败。
- 修改文件：
  - `Cheating_machine_execution_tool/src/services/device_project_info_service.py`
  - `Cheating_machine_execution_tool/line_check_assistant/app.py`
  - `Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`
  - `Cheating_machine_execution_tool/scripts/verify_baseline.py`
  - `Cheating_machine_execution_tool/tests/test_device_project_info_service.py`
  - `Cheating_machine_execution_tool/tests/test_app.py`
  - `Cheating_machine_execution_tool/line_check_assistant_README.md`
  - `ACCEPTANCE_BASELINE.md`
  - `PROJECT_STATUS.md`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行样机版本查询和主程序专项测试，再执行 `python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：样机版本查询专项 `Ran 2 tests ... OK`、主程序专项 `Ran 176 tests ... OK`；以正常主机权限运行完整门禁，58 个源码文件编译、717 项单元测试、170 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`。未连接样机，未构建或运行 EXE。
- 后续待办：Windows源码版用当前通道连接测试样机，核对三项输入框回填、日志、失败提示和保存/重开；真实样机只读查询结论待项目负责人确认。

## 2026-08-30 - 跳过串口预启动等待

- 类型：优化
- 背景：用户明确要求全流程子任务间隔中的“6. 串口日志（全流程期间持续记录）”仅预启动，不应在完成预启动后额外等待120秒。
- 完成内容：① 串口日志预启动结束后立即开始下一子任务；② 其余相邻已选子任务仍固定等待120秒，最后一项后不等待；③ 总确认摘要、强制基线用例、操作员说明和验收基线同步为该例外。
- 修改文件：
  - `Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`
  - `Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`
  - `Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`
  - `Cheating_machine_execution_tool/tests/test_pipeline_window.py`
  - `Cheating_machine_execution_tool/scripts/verify_baseline.py`
  - `Cheating_machine_execution_tool/line_check_assistant_README.md`
  - `ACCEPTANCE_BASELINE.md`
  - `PROJECT_STATUS.md`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行全流程编排和窗口专项测试，再执行 `python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：全流程编排与窗口专项 `Ran 74 tests ... OK`；以正常主机权限运行完整门禁，57 个源码文件编译、713 项单元测试、169 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`。未构建或运行 EXE，未执行真实样机流程。
- 后续待办：Windows源码版勾选串口日志及至少两项后续任务，确认串口打开后立即进入下一任务、后续任务之间仍等待120秒；真实样机全流程端到端验收仍待项目负责人确认。

## 2026-08-30 - 统一全流程子任务间隔

- 类型：优化
- 背景：原全流程仅在子任务1“自动上/下电”后等待120秒；用户要求每个已选子任务完成后均等待120秒，再开始下一项。
- 完成内容：① 将等待约束扩展到每一对相邻已选子任务，串口日志预启动同样纳入实际执行顺序；② 最后一项后不等待；③ 120秒等待继续复用停止事件，点击“停止测试”会立即跳过后续任务；④ 总确认摘要、操作员说明、项目状态和验收基线同步更新。
- 修改文件：
  - `Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`
  - `Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`
  - `Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`
  - `Cheating_machine_execution_tool/tests/test_pipeline_window.py`
  - `Cheating_machine_execution_tool/scripts/verify_baseline.py`
  - `Cheating_machine_execution_tool/line_check_assistant_README.md`
  - `ACCEPTANCE_BASELINE.md`
  - `PROJECT_STATUS.md`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行全流程编排和窗口专项测试，再执行 `python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：全流程编排与窗口专项 `Ran 74 tests ... OK`；以正常主机权限运行完整门禁，57 个源码文件编译、713 项单元测试、169 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`。未构建或运行 EXE，未执行真实样机流程。
- 后续待办：Windows源码版按至少3项已选子任务核对每一段等待提示、120秒间隔和停止行为；真实样机全流程端到端验收仍待项目负责人确认。

## 2026-08-30 - 移除无人值守升级完成阻塞

- 类型：BUG 修复
- 背景：全流程已勾选“本次无人值守”并完成总确认后，样机升级仍在完成回调无条件弹出“样机升级完成”提示框，导致成功的升级结果无法自动进入下一子任务。
- 完成内容：① 将全流程一次性无人值守授权延续至页面升级、`Tftp指令`、`Tftp Put` 的完成回调；② 无人值守时把成功、部分失败或启动失败结果写入主执行日志，不显示中间升级结果提示框；③ 成功后立即回传完成事件继续下一子任务，失败仍以原结果回传终止全流程；④ 普通单独样机升级的完成/失败弹窗保持不变。
- 修改文件：
  - `Cheating_machine_execution_tool/line_check_assistant/app.py`
  - `Cheating_machine_execution_tool/tests/test_app.py`
  - `Cheating_machine_execution_tool/line_check_assistant_README.md`
  - `PROJECT_STATUS.md`
  - `ACCEPTANCE_BASELINE.md`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行 `python -m unittest discover -s tests -p test_app.py -v`，再执行 `python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：专项回归 `Ran 174 tests ... OK`；以正常主机权限运行完整门禁，57 个源码文件编译、712 项单元测试、169 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`。未构建或运行 EXE，未执行真实样机升级。
- 后续待办：Windows源码版勾选“本次无人值守”执行全包升级，确认完成日志出现且不弹“样机升级完成”，随后子任务继续；真实样机全流程端到端验收仍待项目负责人确认。

## 2026-08-30 - 同步八项真实验收结论

- 类型：真实样机验收 / 文档同步
- 背景：项目负责人确认通道 Ping、两条全包升级、页面升级、批量写参、ONU终端业务与注册专项、测试项配置以及DUT独立目标隔离均已按指定范围完成现场验收。
- 完成内容：① 通道 Ping 在网卡已满足时不重复启用或设置静态 IP，不满足时可按需修复后正常 Ping；② `Tftp指令`与`Tftp Put`各实测一次，网卡复用正常，进入 boot 前断电/上电均为1秒且稳定；③ 页面升级网卡按需复用、勾选恢复出厂后的实际命令、重启及日志通过；④ 批量写参用户/工厂模式网卡预检复用通过；⑤ ONU 语音VLAN335、TR069 VLAN50 DHCP地址和IPTV VLAN600现场业务/节目通过；⑥ C300参数化/冲突/删除/`no onu`/`write`、C600停止/`Access denied`/按PON查询/冲突预检及两型号Windows专项通过；⑦ `telnet_default_on`反向镜像、WiFi八项、网卡刷新和子任务7真实连接通过；⑧ 主界面选择`vlan112/vlan113`而DUT窗口仅选`vlan112`时，查询和配置不访问`vlan113`。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：依据项目负责人于2026-08-30提供的真实样机与Windows现场验收结果；本轮未修改业务代码、未构建或运行EXE。
- 验证结果：上述指定范围均标记为已确认验收；全包升级和写参的4/8台并行仅保留为按现场需要补验收，未由本轮单次实测扩大覆盖面。
- 后续待办：继续按`ACCEPTANCE_BASELINE.md`处理全流程7子任务端到端及各章节未列入本轮的多台、异常和新型号场景。

## 2026-08-30 - 固定样机升级并行调度

- 类型：优化
- 背景：用户要求样机升级不再提供串行执行方式，也不保留执行方式设置框，只显示并行数设置。
- 完成内容：① 删除升级窗口的“执行方式”下拉框和串行分支；② `Tftp指令` 与 `Tftp Put` 均按保存的并行数（1–8，默认2）完成即补位执行；③ 不再读写旧 `execution_mode` 配置项，已有 INI 中该字段会被忽略并在下次保存时移除；④ 确认框、README、状态与验收边界同步为仅显示并行数。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行升级设置存储、主程序专项测试及 `python scripts\verify_baseline.py`。
- 验证结果：升级设置存储专项 15 项、主程序专项 173 项、全流程编排专项 43 项均通过；在可绑定 TFTP UDP 69 的环境执行完整门禁通过，57 个源码文件编译、711 项单元测试、169 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`。未连接或写入样机，未构建或运行 EXE。
- 后续待办：Windows源码版确认升级窗口仅显示并行数；按现场需要复验两条全包升级链路的 2 / 4 / 8 台并行边界。

## 2026-08-30 - 全包升级固定使用 192.168.1.0/24

- 类型：流程修复
- 背景：主界面“样机管理 IP”或通道已保存的 PC 静态 IP 使用非 `.1` 网段时，全包升级可能将 TFTP 网卡准备到错误网段，无法与固定 `192.168.1.1` 的 boot/TFTP 端点完成传输。
- 完成内容：① `Tftp指令` 与 `Tftp Put` 共用全包升级专用地址计算，忽略主界面样机管理 IP 和已保存 PC 静态 IP；② 固定将每条 VLAN 网卡准备为 `192.168.1.<VLAN尾号>`，例如 `VLAN139 -> 192.168.1.139`；③ 确认框和主执行日志逐台显示 `PC 固定地址 → 样机 192.168.1.1`；④ 页面升级、写参和线路 Ping 的地址策略不变，运行时仍不改写 `network_card_ip.ini`。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行主程序专项测试及 `python scripts\verify_baseline.py`；需在测试样机上分别验证 `Tftp指令` 和 `Tftp Put`。
- 验证结果：主程序专项 `tests/test_app.py` 为 174 项通过；提升权限后完整门禁通过，57 个源码文件编译、711 项单元测试、169 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`。项目负责人于2026-08-30确认：主界面/通道配置为非 `.1` 网段时，全包升级固定切换到 `192.168.1.<VLAN尾号> → 192.168.1.1` 并可正常完成升级。未构建或运行 EXE。
- 后续待办：网卡按需复用细节及 4 / 8 台并行仍按现场需要继续验收。

## 2026-08-29 - 全流程升级和写参的本次无人值守授权

- 类型：流程优化 / 安全确认优化
- 背景：全流程执行时，样机升级和写样机参数会分别弹出确认框，必须人工点击后才会继续，无法在已复核全部风险后无人值守执行。
- 完成内容：① 全流程窗口新增默认关闭的 Windows 原生“本次无人值守”勾选框，不写入 INI；② 总确认框在启用时列出当前升级方式、传输方式、固件、并行数、恢复出厂，以及参数表、参数并行数、清空参数和退出老化；③ 仅将一次性授权传给样机升级和写参入口，跳过这两项的二次确认；ONU 注册及其它子任务继续保持原确认语义；④ 无人值守下发现已选任务缺项，或全包升级未配置程控电源 COM 口，均在启动前拒绝，失败、停止和既有重试逻辑不变；⑤ 主执行日志记录授权和实际跳过的确认。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行编排器、全流程窗口、写参入口和主程序专项测试，并执行 `python scripts\verify_baseline.py` 完整门禁。
- 验证结果：专项回归已通过：编排器 43 项、全流程窗口 30 项、写参入口 17 项、主程序 173 项；提升权限后完整门禁通过，57 个源码文件编译、710 项单元测试、169 项强制基线测试及协议不变量均通过，`ALL CHECKS PASSED`。本轮未连接或写入样机，未构建或运行 EXE。
- 后续待办：Windows源码版核对勾选框默认值、总确认摘要、仅第3/4项跳过确认、缺项/无COM拦截和关闭后不保留；在测试样机上再确认无人值守升级、写参成功和失败后的终止边界。

## 2026-08-29 - 保存写参并行数

- 类型：BUG 修复
- 背景：写样机参数窗口每次打开都会重新创建并行数变量并固定为默认值 1，操作员关闭窗口后无法恢复上次使用的并行数。
- 完成内容：① 在 `sample_upgrade_settings.ini` 的 `[sample_upgrade]` 段新增独立 `parameter_parallel_count`；② 写参窗口改用主程序实例级变量，恢复旧配置时缺键回退默认 1，非法值钳制到 1–8；③ 修改数值后自动保存，关闭写参窗口及关闭主程序时再次保存；④ 全包升级的 `parallel_count` 保持独立且不受影响。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行写参配置存储、主程序专项测试与 `python scripts\verify_baseline.py`。
- 验证结果：`python -m unittest discover -s tests -p test_sample_upgrade_settings_store.py -v` 为 `Ran 14 tests ... OK`；`python -m unittest discover -s tests -p test_app.py -v` 为 `Ran 169 tests ... OK`；本机权限下 `python scripts\verify_baseline.py` 通过，57 个源码文件编译、703 项单元测试、169 项强制基线测试均通过，`ALL CHECKS PASSED`。普通受限环境的两项既有 TFTP UDP 69 绑定测试会因 `WinError 10013` 失败，非本轮改动导致。
- 后续待办：Windows 源码版打开“写样机参数”，修改并行数后关闭再打开，确认恢复上次有效值；不涉及真实设备写入。

## 2026-08-29 - 补充Windows桌面验收结论

- 类型：Windows桌面验收 / 状态更新
- 背景：项目负责人确认主界面与二级窗口层级、ONU注册窗口、DUT配置、测试项配置、全流程窗口和串口终端的本轮指定交互均验收通过。
- 完成内容：① 主界面与已打开二级窗口可互相点击升到前台；② ONU注册普通`1000x900`四步布局、底部按钮、Windows原生勾号、C300/C600文案与切换；③ DUT独立目标选择、“全选/清除”、SSID递增和双频区域显隐；④ 测试项配置加载提速体感及第五页四项运行参数保存重开；⑤ 全流程首次7项全不勾选、状态刷新、确认框、主界面状态徽标和进度条；⑥ 3路以上高频WiFi串口日志滚动时按钮可操作，日志文件名和逐行时间戳。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：依据项目负责人2026-08-29提供的Windows桌面验收结果。
- 验证结果：上述指定Windows桌面交互已确认验收；未扩大为未覆盖的真实DUT下发、ONU业务、全流程端到端、停止或异常路径结论。
- 后续待办：按`ACCEPTANCE_BASELINE.md §2.3 / §2.10 / §2.12 / §2.13`保留的真实设备、端到端、停止和异常场景继续验收。

## 2026-08-26 - 确认C300注册流程验收

- 类型：真实样机验收 / 状态更新
- 背景：项目负责人确认「中兴C300注册流程验收OK」。
- 完成内容：将 C300 默认SD-41单台流程升级为已确认验收：按PON发现/选择、ID/SN预检、默认六业务下发、working轮询、完整只读回读和默认不write；同步限定参数化组合、write、删除命令、Windows界面与终端业务效果仍为待验收。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：依据2026-08-25现场`gpon-onu_1/2/1:3 / GPONA62D6F48`默认模板完整日志与项目负责人2026-08-26确认。
- 验证结果：C300默认注册流程已确认验收；不扩大到未覆盖场景。
- 后续待办：Windows源码版验收参数页与分类提示；参数化组合、write、删除命令及语音/TR069/IPTV终端业务仍按现场需要验证。

## 2026-08-25 - 验证C300默认业务注册

- 类型：真实样机验收 / 状态更新
- 背景：项目负责人授权在 C300 `1/2/1` 注册一台查询到的未注册ONU，验证默认SD-41六业务模板是否可行。
- 完成内容：① 只读发现`gpon-onu_1/2/1:3 / GPONA62D6F48`；② 预检空ONU ID与SN后注册默认模板；③ 第8次上线轮询进入working；④ 回读身份、状态、T-CONT、6个GEM/VPort、6条service-port、远端业务和MVLAN 600，均匹配；⑤ 未执行write，ONU保留在线。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`。
- 验证方法：显式源IP `172.18.18.40` 连接 C300 `172.18.18.151`，执行全局未注册查询、ID/SN预检、默认注册、最长60秒上线轮询和全部只读回读。
- 验证结果：真实OLT默认模板注册与回读通过；未执行write。完整基线提升权限后通过，57个源码文件编译、702项单元测试、169项强制基线测试全部通过，`ALL CHECKS PASSED`。本轮未构建或运行EXE。
- 后续待办：在Windows源码版确认分类提示、参数页和执行日志；继续确认语音/TR069地址、IPTV节目及参数化组合，write须另行确认。

## 2026-08-25 - 修正C300查询PON范围传递

- 类型：BUG 修复
- 背景：C300 查询页填写`1/2/1`，主执行日志却显示按默认`gpon-olt_1/1/1`筛选。
- 完成内容：查询线程改为 C300/C600 均传递当前界面构造的 `OnuDiscoveryScope`，不再让 C300 回退默认范围；新增 `1/2/1` 传参回归用例。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m unittest discover -s tests -p test_app.py -v`；`python scripts\verify_baseline.py`。
- 验证结果：主界面专项 `Ran 169 tests ... OK`；完整基线提升权限后通过，57个源码文件编译、702项单元测试、169项强制基线测试全部通过，`ALL CHECKS PASSED`。
- 后续待办：Windows源码版确认 C300 查询日志显示 `gpon-olt_1/2/1`；真实注册验收不在本次范围。

## 2026-08-25 - 参数化C300按PON注册流程

- 类型：功能 / 优化
- 背景：需要让 C300 的查询和配置业务体验与 C600 四步流程对齐，同时保持两类 OLT 的命令体系隔离。
- 完成内容：① C300 全局未注册查询后按机框/槽位/PON筛选；② 配置页支持 ONU ID、类型模板、T-CONT/DBA、六项业务映射；③ 每项业务的 Service ID 派生同号 GEM/VPort，默认六业务、危险删除、write及停止边界不变；④ 预检和只读回读按输入参数动态核验。
- 修改文件：`src/core/zte_c300_onu.py`、`src/services/onu_registration_service.py`、`line_check_assistant/app.py`、`line_check_assistant/onu_registration_store.py`、相关测试与本文档。
- 验证方法：`python -m unittest discover -s tests -p test_app.py -v`；`python -m unittest discover -s tests -p test_onu_registration_service.py -v`；`python scripts\verify_baseline.py`。
- 验证结果：主界面专项168项、ONU service专项37项、ONU配置存储专项5项均通过；完整基线提升权限后通过，57个源码文件编译、701项单元测试、169项强制基线测试全部通过，`ALL CHECKS PASSED`。
- 后续待办：Windows源码版核对C300参数页和PON筛选；在测试ONU/维护窗口内先做可变参数的只读命令确认，再由项目负责人决定是否执行真实注册验收。

## 2026-08-25 - 修复C300未注册ONU点击选择

- 类型：BUG 修复
- 背景：C300 查询到未注册 ONU 后，操作员点击列表项，后续步骤仍判定为未选择，无法继续配置或预览。
- 完成内容：① 在共享 ONU 选择回调中同步设置被点击行的选择变量；② 保持单选、C600 自动回填和既有按钮刷新逻辑不变；③ 新增 C300 点击选择回归用例。
- 修改文件：
  - `Cheating_machine_execution_tool/line_check_assistant/app.py`
  - `Cheating_machine_execution_tool/tests/test_app.py`
  - `DEVELOPMENT_LOG.md`
- 验证方法：`python -m unittest discover -s tests -p test_app.py -v`；`python scripts\verify_baseline.py`。
- 验证结果：主程序专项 `Ran 167 tests ... OK`；完整基线在提升权限后通过，57 个源码文件编译、699 项单元测试、169 个强制基线测试均通过，`ALL CHECKS PASSED`。普通权限环境不能绑定 UDP 69，导致两项既有 TFTP 用例报 `WinError 10013`，不影响提升权限下的完整门禁结论。
- 后续待办：在 Windows 源码版复验 C300 查询结果点击后可进入配置业务与命令预览；真实 C300 注册验收仍按既有计划单独进行。

## 2026-08-25 - 调整ONU注册窗口尺寸

- 类型：修改
- 背景：项目负责人先将ONU注册窗口调整为`1200x1000`，随后根据实际显示效果确定最终宽高为`1000x900`，要求同步所有关联文件。
- 完成内容：① 将ONU注册窗口最终默认尺寸和最小尺寸统一为`1000x900`；② 同步更新窗口布局回归断言；③ 同步操作员说明、验收基线和当前项目状态；④ 保持窗口布局结构、ONU配置、注册、验证、write及清理逻辑不变。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在`Cheating_machine_execution_tool`执行`python -m unittest discover -s tests -p "test_app.py"`及`python scripts\verify_baseline.py`；完整门禁因TFTP测试需临时绑定本机UDP 69在沙箱外执行。
- 验证结果：主界面166项通过；完整门禁`ALL CHECKS PASSED`，57个当前源码文件编译覆盖、698项单元测试及169个强制基线测试全部通过，协议不变量检查全绿。本轮未构建或运行EXE。
- 后续待办：在Windows源码版打开ONU注册窗口，目视确认默认/最小尺寸为`1000x900`，四步分页及底部危险提示、状态和操作按钮显示完整。

## 2026-08-25 - 明确区分ONU型号与类型模板

- 类型：界面文案优化 / 语义修复
- 背景：ONU注册“配置业务”页原字段显示为“ONU 型号”，但该值实际用于C600命令`onu <ID> type <模板> sn <SN>`，语义应为OLT中的ONU类型模板；同时查询未注册ONU得到的`model`才是设备发现型号。
- 完成内容：① C600配置字段改为“ONU 类型模板”，增加说明：默认带入查询到的ONU型号、可按OLT实际兼容模板修改；② 未注册查询结果继续显示“型号”，已注册与清理候选改为显示“类型模板”；③ 模板名称校验和回读不一致错误同步使用“ONU 类型模板”措辞；④ 保留内部`onu_type/c600_onu_type`配置键、INI兼容、自动带入、命令生成、注册/write/清理流程不变；⑤ 补充界面、校验和候选显示回归，并同步操作说明、验收不变量与交接状态。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/core/zte_c600_onu.py`、`Cheating_machine_execution_tool/src/models/onu_registration_models.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在`Cheating_machine_execution_tool`执行`python -m unittest discover -s tests -p "test_onu_registration_service.py"`、`python -m unittest discover -s tests -p "test_app.py"`及`python scripts\verify_baseline.py`；完整门禁因TFTP测试需临时绑定本机UDP 69在沙箱外执行。
- 验证结果：ONU注册36项、主界面166项均通过；完整门禁`ALL CHECKS PASSED`，57个当前源码文件编译覆盖、698项单元测试及169个强制基线测试全部通过，协议不变量检查全绿。本轮未登录或修改OLT/ONU，未构建或运行EXE。
- 后续待办：在Windows源码版打开ONU注册页，确认查询结果仍显示物理“型号”，配置页显示“ONU 类型模板”及说明，已注册/清理候选显示“类型模板”，且`1000x800`窗口无文字裁切。

## 2026-08-25 - 优化C300未注册ONU展示与预检查

- 类型：优化 / BUG 修复
- 背景：C300全局`show gpon onu uncfg`实机只返回`OnuIndex / Sn / State`，导致列表无法像C600一样展示辅助信息；同时只读核查确认原指定PON预检查命令`show gpon onu uncfg gpon-olt_1/2/1`返回`%Error 20202: Invalid input ... Invalid parameter`。
- 完成内容：① C300发现结果增加`注册类型:SD-41（配置模板）`与`PON类型:GPON（根据接口推断）`，明确区分配置值/接口推断与OLT真实探测值；② 注册前未注册复核改用实机支持的全局查询，继续按目标ONU接口与SN精确匹配，其余ID/SN冲突检查、注册、清理及write边界不变；③ 补充C300显示字段、C600原显示不变和新预检查命令的回归断言；④ 同步操作员说明、验收不变量和当前交接状态。
- 修改文件：`Cheating_machine_execution_tool/src/models/onu_registration_models.py`、`Cheating_machine_execution_tool/src/core/zte_c300_onu.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在`Cheating_machine_execution_tool`执行`python -m unittest discover -s tests -p test_onu_registration_service.py -v`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_tftp_transport.py -v`及`python scripts\verify_baseline.py`；TFTP专项与完整门禁因需临时绑定本机UDP 69在沙箱外执行。
- 验证结果：ONU注册36项、主界面166项、TFTP 9项均通过；完整门禁`ALL CHECKS PASSED`，57个当前源码文件编译覆盖、698项单元测试及169个强制基线测试全部通过，协议不变量检查全绿。实机只读查询已确认C300原始字段及无效指定PON命令，本轮未进入配置模式、未注册/删除ONU、未执行`write`。
- 后续待办：Windows源码版目视确认C300列表文字完整显示；按既有待办完成C300真实注册、冲突拦截、上线轮询、完整回读、显式删除和`write`验收。

## 2026-08-24 - 补充渐进式模块化开发规则

- 类型：文档 / 优化
- 背景：`line_check_assistant/app.py` 已承载较多窗口与状态，但项目已有多项 Windows 和真实样机验收结论。项目负责人担心一次性拆分会影响已验收功能，要求先优化开发规则，后续按“新增功能从独立模块开始、既有功能小步整理”的方式执行。
- 完成内容：① 在 `AGENTS.md` 增加已验收功能默认结构冻结、新功能独立分层、结构调整与业务行为分轮、小步可回退四条硬规则；② 在 `line-check-dev` 工作流补充渐进式模块化实施边界，禁止仅为减行主动搬迁已验收代码，并要求跨模块拆分前取得用户确认、先补特征测试；③ 在 `PROJECT_STATUS.md` 交接规则登记后续开发入口，明确 `app.py` 只保留入口装配和 UI 回调。
- 修改文件：`AGENTS.md`、`.claude/skills/line-check-dev/SKILL.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：执行 `git diff --check`，并核对四份文档中的规则表述、职责边界和文档同步范围。
- 验证结果：`git diff --check` 通过；差异仅包含4份规则/交接文档共27行新增，未修改业务代码、测试、验收标签或操作员行为，未构建或运行 EXE。
- 后续待办：后续新增功能按独立模块落位；现有已验收代码仅在明确需求触发时按单一功能边界小步整理，大范围拆分仍需项目负责人另行确认。

## 2026-08-24 - 统一ONU选中态为标准勾号

- 类型：BUG 修复 / 界面规范
- 背景：项目负责人在ONU注册页勾选“启用 SN 双重绑定”和“完整验证成功后执行 write”时，Clam主题把选中态显示为叉号，要求修复并把今后所有选中态统一为标准“✔”。
- 完成内容：① 将ONU页剩余的3个`ttk.Checkbutton`（C300危险删除、C600 SN双重绑定、C600 write）替换为Windows原生`Checkbutton`，统一白色选中底色和标准勾号；② 保留原BooleanVar、默认值、write仅本次授权、危险删除回调和预览失效语义；③ 新增回归同时核对3个ONU控件，并扫描`src/`与`line_check_assistant/`全部Python源码，禁止再次引入`ttk.Checkbutton`；④ 将“所有新增或修改的布尔选择控件均显示标准勾号”写入项目开发规则、操作员说明和验收基线。
- 修改文件：`AGENTS.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p test_app.py -v`和`python scripts/verify_baseline.py`；完整基线在允许绑定本机UDP 69端口的环境运行。
- 验证结果：主程序166项全部`OK`；完整基线57个源码文件编译覆盖、698项单元测试、169项强制测试全部通过，最终`ALL CHECKS PASSED`；活动业务源码扫描未发现`ttk.Checkbutton(`。
- 后续待办：在Windows源码版打开ONU注册页，目视确认上述3个选项未选为空框、选中显示标准勾号且文字和底色无错位。本轮未构建或运行EXE。

## 2026-08-24 - 对齐C600业务VPort并补齐IGMP

- 类型：BUG 修复 / 真实样机验收 / 状态更新
- 背景：项目负责人在NP7287XGS创建Internet 171、TR069 50、Voice 335和IPTV 600四条WAN后，只有Internet取得地址。只读登录C600确认ONU为working/config success、相关VLAN均存在并在上联放通，但旧代码虽然把业务拆到GEM 1/2/3/4，却把全部service-port配置在VPort 1；实机`show gpon onu vport`显示VPort N与GEM N为1:1，因此只有GEM1路径匹配。旧完整验证只检查service-port为OK/YES，没有核对VPort列，也没有配置IPTV IGMP receive-port。
- 完成内容：① C600业务计划同时派生VLAN→GEM与VLAN→VPort，上网使用可编辑且必须相等的GEM/VPort，语音335固定2、组播600固定3、TR069 50固定4，并拒绝上网资源与固定ID冲突；② 配置命令按VPort分组进入四个`interface vport-...:<ID>`上下文，VLAN 600补齐`igmp fast-leave enable`、`igmp version v2`和`igmp mvlan 600 / receive-port`；③ 完整回读新增service-port实际VPort校验及IGMP配置校验，旧式“全部VPort 1”即使状态OK/YES也会失败；④ UI把字段明确为“上网VPort”并显示GEM/VPort 1:1及IPTV IGMP提示；⑤ 新回归加入强制基线；⑥ 项目负责人授权精确删除并重注册`SDMC176D42AA`，全程未执行write。
- 修改文件：`.claude/plans/c600_vport_gem_alignment.md`、`Cheating_machine_execution_tool/src/core/zte_c600_onu.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：执行ONU service专项、主程序专项、相关文件`py_compile`和`python scripts\verify_baseline.py`；真实C600先查询并唯一匹配`gpon_onu-1/1/5:1 / SDMC176D42AA`，删除前再次回读身份，删除后确认baseinfo为空及第2次未注册查询发现目标，再用修正版完成注册、上线、collection/service-port/detail-info/MVLAN回读和四个业务VLAN的MAC表查询。
- 验证结果：ONU service 36项、主程序165项均`OK`；完整基线57个源码文件编译、697项单测、168项强制测试全部通过，`ALL CHECKS PASSED`。真实ONU第4次轮询进入XGS-PON working，9条service-port分别位于VPort 1/2/3/4且全部OK/YES，VPort 3的IGMP receive-port回读成功；WAN MAC `A2:C3:B4:66:1C:BB/BD/BE/BC`分别在VLAN 171/335/600/50的VPort 1/2/3/4动态学习，证明OLT二层路径已对齐。ONU保持在线，本轮未执行write；该结果不替代ONU页面语音/TR069实际DHCP地址和IPTV节目验收。
- 后续待办：项目负责人刷新ONU WAN页面，确认Voice 335与TR069 50是否取得预期地址；根据现场IPTV设计确认VLAN 600是路由DHCP还是纯组播桥接并验证节目。确认后再决定是否在C600执行write保存当前运行配置；Windows源码版复验四VPort/IGMP预览和write选项。

## 2026-08-24 - 优化C600业务分层并验证write

- 类型：优化 / BUG 修复 / 真实样机验收
- 背景：项目负责人要求把C600的多业务从单一T-CONT/GEM改为上网、语音、组播和TR069分层，上网DBA模板改为`WT-10G`，并增加由操作员决定是否执行的`write`选项；同时授权注册一台未注册ONU完成真实写入验证，验证后清理现场并保存清理结果。
- 完成内容：① C600按VLAN生成四层资源：上网使用可编辑主资源（默认T-CONT 1/GEM 1/`WT-10G`），语音335固定T-CONT 2/GEM 2/`DBA_FONE`，组播600固定T-CONT 3/GEM 3/`DBA_IPTV`，TR069 50固定T-CONT 4/GEM 4/`DBA_TR069`；只创建实际用到的资源并拒绝上网ID与固定2/3/4冲突；② 配置和完整回读校验均按VLAN核对对应GEM，不再把9组业务全部放入GEM 1；③ C600界面增加“完整验证成功后执行 write（危险，仅本次有效）”，默认关闭且每次重开窗口复位，预览、最终确认和日志明确显示本次选择；④ 选择write时，只在ONU进入working且完整只读验证成功后启动独立保存会话；⑤ 修复C600保存会话发送无效`end`以及30秒不足以等待进度点的问题，改为在ZXAN#直接执行`write`并最长等待120秒；⑥ 同步操作员说明、验收基线、项目状态、强制基线测试和实施计划。
- 修改文件：`.claude/plans/c600_layered_business_and_write.md`、`Cheating_machine_execution_tool/src/core/zte_c600_onu.py`、`Cheating_machine_execution_tool/src/services/onu_registration_service.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/onu_registration_store.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_service.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行ONU service、ONU配置store、主程序三组专项单元测试；执行`python scripts\verify_baseline.py`；真实C600经`172.33.5.35 → 172.18.18.152`发现未注册ONU、精确ID/SN预检、注册NP7287XGS、上线轮询、四组配置回读、write、身份复核后删除、ID/SN释放确认、再次write和重新发现确认。
- 验证结果：ONU service 35项、配置store 5项、主程序165项均`OK`；完整基线门禁57个源码文件编译覆盖、696项单元测试、167个强制基线测试全部通过，最终`ALL CHECKS PASSED`。真实ONU `SDMC176D42AA`使用ONU ID 1在第5次轮询进入XGS-PON working，四个T-CONT/GEM、9组service、全部service-port OK/YES、config success和MVLAN 600均回读一致。首次write持续输出进度点并超过旧30秒等待，结果不可判定；修复后最终清理状态write约41秒返回`............[OK].`。测试ONU已精确删除，ID/SN为空并重新出现在未注册列表；另一台未注册ONU及既有ONU均未处理，现场清理结果已保存。
- 后续待办：在Windows源码版目视复验C600分层预览、write默认关闭、关闭重开复位、勾选后确认文案和执行日志；补充C600停止/Access denied专项以及C300真实注册、删除和write验收。本轮未构建或运行EXE。

## 2026-08-19 - 调整升级入 boot 上下电时序

- 类型：修改
- 背景：项目负责人要求将样机全包升级进入 boot 前的程控电源“断电后等待 1.5 秒、上电后等待 3 秒”均调整为 1 秒。本次范围仅限进入 boot 的首次上下电，不改变普通自动上/下电或 `Tftp指令` 传输后备用 repower 的默认时序。
- 完成内容：① `ProgrammablePowerSupply.power_on_channels` 与 `power_on_selected_channels` 增加可选的断电/上电等待参数，默认值仍为 1.5 秒/3 秒；② `Tftp指令` 和 `Tftp Put` 在进入 boot 前显式传入 1 秒/1 秒，串行与并行 coordinator 一致；③ 主执行日志新增当次上下电时序提示；④ 回归保护默认电源时序、升级专用 1 秒/1 秒、并行传递以及传输后 repower 仍使用普通默认值；⑤ 同步操作员说明、验收基线和项目状态。
- 修改文件：`src/core/power_supply.py`、`src/services/power_on_service.py`、`src/services/serial_upgrade_service.py`、`tests/test_power_supply.py`、`tests/test_serial_upgrade_service.py`、`line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile src/core/power_supply.py src/services/power_on_service.py src/services/serial_upgrade_service.py tests/test_power_supply.py tests/test_serial_upgrade_service.py`；`python -m unittest discover -s tests -p test_power_supply.py -v`；`python -m unittest discover -s tests -p test_serial_upgrade_service.py -v`；`python scripts\verify_baseline.py`。
- 验证结果：电源专项 10 项、串口升级专项 38 项全部通过；完整基线门禁全绿，57 个当前主程序源码文件编译覆盖、694 项单元测试、164 个强制基线测试均实际执行，`ALL CHECKS PASSED`。
- 后续待办：真实样机分别用 `Tftp指令` 和 `Tftp Put` 确认 1 秒/1 秒时序仍能稳定进入 boot；现场结论由项目负责人提供后再更新验收状态。

## 2026-08-18 - 已注册管理改为可删除任意状态 ONU

- 类型：优化 / 需求调整
- 背景：项目负责人要求「已注册管理」从「只允许删除离线/非 working ONU」改为「可删除任意状态的已注册 ONU（含在线 working）」。
- 完成内容：① C300 `parse_registered_candidates` 不再过滤 non-working，列出目标 PON 下全部已注册 ONU；② C600 `parse_onu_state_non_working` 改为 `parse_onu_state_label`，只取状态标签、不做在线/离线过滤；③ service 查询列出全部已注册 ONU，删除流程移除「非 working 状态复核」，仅保留 baseinfo 接口/SN 身份复核 + 删除后回读；④ UI 提示与删除确认弹窗改为明示「含在线 working、删除在线 ONU 会中断业务」，加强危险警示；⑤ 同步更新 driver/service/UI 测试与强制基线、文档（`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、操作员说明）。
- 修改文件：`src/core/zte_c300_onu.py`、`src/core/zte_c600_onu.py`、`src/services/onu_registration_service.py`、`line_check_assistant/app.py`、`tests/test_onu_registration_service.py`、`scripts/verify_baseline.py`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：相关文件 `py_compile`、`python -m unittest discover -s tests -p test_onu_registration_service.py -v`、`python scripts/verify_baseline.py`。
- 验证结果：ONU service 专项 34 项通过（移除 1 项「在线 ONU 拒绝删除」，删除在线 ONU 已由「删除并回读验证」用例覆盖）。
- 后续待办：真实样机确认 C300/C600 `no onu` 删除命令格式；现场复验删除在线 working ONU 的二次确认与中断业务提示。

## 2026-08-18 - 修正已注册管理查询命令（改用 OLT 已确认命令）

- 类型：BUG 修复
- 背景：项目负责人现场执行 C300「已注册管理」查询，`show gpon onu state gpon-olt_1/1/1`（按 PON 不带 ONU ID）返回 `%Error 20202: Invalid input detected at '^' marker.Invalid parameter`，确认 C300 不支持按 PON 过滤的 state 查询格式。项目负责人要求：以后先确认 OLT 实际支持的命令再做对应改动，不凭空假设命令格式。
- 完成内容：① C300 已注册查询改用已确认的全局 `show gpon onu state`（不带参数），解析时再按目标 PON 过滤，与既有 `query_c300_cleanup_candidates` 一致；② C600 查询同样修正：改用参考工具 `ZteTitanOnuProvisioner` 已实机确认的 `show running-config-interface <pon>` 查已注册列表，再逐台用真实注册轮询已确认的 `show gpon onu state <pon> <id>` 判定离线/非 working；③ service 的查询与删除前状态复核分型号走对应已确认命令；④ UI 确认弹窗的命令文本同步修正；⑤ 更新 driver/service/测试与 `ACCEPTANCE_BASELINE.md` 待确认项。
- 修改文件：`src/core/zte_c300_onu.py`、`src/core/zte_c600_onu.py`、`src/services/onu_registration_service.py`、`line_check_assistant/app.py`、`tests/test_onu_registration_service.py`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：相关文件 `py_compile`、`python -m unittest discover -s tests -p test_onu_registration_service.py -v`。
- 验证结果：ONU service 专项 35 项全部通过。
- 后续待办：真实样机确认 C300/C600 的 `no onu` 删除命令格式（两型号删除均为「已实现未验收」，未确认真实输出）；现场复验 C300 全局 state 查询与 C600 running-config-interface 查询、逐台 state 判定的实际输出。

## 2026-08-18 - 新增 ONU 已注册管理（查询已注册 ONU 并显式删除离线/非 working ONU）

- 类型：功能
- 背景：项目负责人要求在 ONU 注册模块增加「查询目标 PON 口已注册的 ONU，然后可以选择删除指定 ONU」。经确认，范围定为 C300 与 C600 均支持、只允许删除离线/非 working 的 ONU、采用独立入口。这放宽了 C600 原有的「永不删除」验收边界，改为「不自动删除，仅操作员在已注册管理入口显式选择一台离线/非 working ONU 后允许删除」。
- 完成内容：① 新增 `RegisteredOnu` 模型与 `OnuOperationResult.registered_onus` 字段；② C300/C600 各自新增 `build_registered_query_command`（`show gpon onu state <pon>`）、`parse_registered_candidates`（仅保留目标 PON 下离线/非 working 项）、`build_delete_identity_command`（删除前 baseinfo 身份复核）、`build_delete_commands`（仅一条 `no onu`）与 `deleted_if_baseinfo_empty`（删除后回读）；③ service 新增 `query_registered_candidates`（只读查询 + 逐候选补 SN/型号）与 `delete_registered_onu`（删除前状态/接口/SN 三重复核 → 只删这一台 → 删除后回读确认，全程逐条错误停止、可停止、不写 write）；④ ONU 窗口新增第 4 个分页「已注册管理」，含目标机框/槽位/PON、查询按钮、单选下拉、红色危险删除按钮与二次确认，型号切换联动 C600 scope 并清空旧候选；⑤ 新增 driver/service/UI 回归并纳入强制基线；⑥ 同步 `ACCEPTANCE_BASELINE.md §2.10`（C600 删除边界、四步分页、待确认命令格式）、`PROJECT_STATUS.md`、操作员说明。
- 修改文件：`src/models/onu_registration_models.py`、`src/models/__init__.py`、`src/core/zte_c300_onu.py`、`src/core/zte_c600_onu.py`、`src/services/onu_registration_service.py`、`line_check_assistant/app.py`、`tests/test_onu_registration_service.py`、`tests/test_app.py`、`scripts/verify_baseline.py`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行相关文件 `py_compile`、`python -m unittest discover -s tests -p test_onu_registration_service.py -v`、`python -m unittest discover -s tests -p test_app.py`，随后执行 `python scripts/verify_baseline.py` 全绿。
- 验证结果：ONU service 专项 35 项、主程序专项 164 项均通过；完整基线门禁预期全绿（含新增 8 条强制基线测试）。
- 后续待办：真实样机确认 `show gpon onu state <pon>`（不带 ONU ID 的按 PON 查询格式）与 C600 `no onu` 删除命令的实际输出格式，并分别复验 C300/C600 已注册管理的查询、单选、二次确认、身份复核、删除与回读；Windows 四步分页布局待桌面目视确认。现场结论由项目负责人提供后再更新验收状态。

## 2026-08-18 - 确认便携版目标机启动

- 类型：真实样机验收 / 状态更新
- 背景：修复PyInstaller Tcl/Tk资源目录并重新生成便携ZIP后，项目负责人在另一台电脑删除旧目录、重新解压并启动新包，反馈“可以正常使用了”。
- 完成内容：① 将修复后便携包在目标Windows电脑正常启动和基本使用登记为已确认验收；② `PROJECT_STATUS.md`与`ACCEPTANCE_BASELINE.md §2.11`同步移除该启动复验待办；③ 验收范围仅覆盖完整解压后的程序启动与正常进入使用状态，不扩大为ONU注册、升级、写参、串口或其它真实设备业务的整体验收。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`。
- 验证方法：项目负责人在目标Windows电脑使用修复后的`LineCheckAssistant_portable.zip`完成现场启动复验；文档更新后在主源码目录执行`python scripts/verify_baseline.py`与`git diff --check`。
- 验证结果：目标电脑不再出现`pyi_rth__tkinter`/Tcl目录错误，修复后便携版可正常使用；自动化基线仍为679项单元测试、57个源码文件编译覆盖、157个强制基线测试全部通过。
- 后续待办：各业务入口仍按原状态分别验收；便携发布后续构建继续由EXE归档门禁保护`tcl\init.tcl`和`tk\tk.tcl`。

## 2026-08-18 - 修正免安装版Tk启动失败

- 类型：BUG 修复 / 构建
- 背景：项目负责人在另一台电脑完整解压并启动首次便携ZIP时，程序在主界面出现前报`Failed to execute script 'pyi_rth__tkinter'`和`Tcl data directory ...\_MEI...\tcl not found`。旧构建只检查PE头、ZIP、哈希与配置脱敏，没有核对PyInstaller内部资源目录，因此未拦住这个启动前故障。
- 完成内容：① 读取PyInstaller 5.10.1实际`pyi_rth__tkinter`确认运行时固定查找`sys._MEIPASS/tcl`和`sys._MEIPASS/tk`；② 用旧EXE归档清单确认自定义hook错误地把同一批资源放在`_tcl_data/_tk_data`，根因与现场报错一致；③ 自定义hook改为按当前`_tkinter.TCL_VERSION/TK_VERSION`采集，并放入准确的`tcl/tk`根目录，源目录缺失时构建直接失败；④ 构建脚本新增EXE归档门禁，必须实际命中`tcl\init.tcl`和`tk\tk.tcl`才允许生成便携目录/ZIP；⑤ 增加hook目录契约和构建门禁回归并纳入强制基线，重新构建发布包且未在当前电脑启动EXE。
- 修改文件：`.claude/plans/portable_tkinter_runtime_fix.md`、`Cheating_machine_execution_tool/line_check_assistant/packaging_hooks/hook-_tkinter.py`、`Cheating_machine_execution_tool/build_line_check_assistant.ps1`、`Cheating_machine_execution_tool/tests/test_portable_release.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：用`PyInstaller.utils.cliutils.archive_viewer -l`分别检查旧/新EXE内部目录，执行`python -m unittest discover -s tests -p test_portable_release.py -v`、`python scripts/verify_baseline.py`和`powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1`；构建后只读复核归档目录、ZIP清单、PE/哈希和脱敏配置，不运行EXE。
- 验证结果：旧EXE实际只有`_tcl_data/_tk_data`；修复后归档明确包含`tcl\init.tcl`和`tk\tk.tcl`，旧错误根目录均不存在，构建门禁通过。发布专项5项`OK`；完整门禁679项单元测试、57个源码文件编译覆盖、157个强制基线测试、8条MUST_EXIST和1条MUST_NOT_EXIST全部通过。新ZIP含11个条目与6个脱敏INI，EXE记录哈希一致，SHA256为`636FCA061E2D14A5C988CB5567728EE0CA0C2D24CB26B7C0BF505152C20C30F8`；按项目边界未在当前电脑运行EXE。
- 后续待办：项目负责人在目标电脑删除旧解压目录，重新复制并完整解压新ZIP，启动确认不再出现`pyi_rth__tkinter`/Tcl目录错误；启动结果确认前保持“目标电脑运行待复验”，不升级为已验收。

## 2026-08-18 - 生成脱敏免安装发布包

- 类型：构建 / 发布优化
- 背景：项目负责人需要把当前程序带到另一台电脑运行，要求按建议提供完整免安装目录并避免复制本机运行配置。原脚本只生成单文件EXE，程序离开当前目录后缺少`Auto_power_on_off_tool/config`，且直接复制现有配置会泄露凭据、路径和硬件绑定。
- 完成内容：① 新增独立脱敏脚本，固定生成6个运行INI并整体替换便携配置目录，清空OLT/DUT/升级账号密码、OLT/源IP、ONU ID、钉钉/远程控制/邮件、固件和参数表路径、项目身份、网卡、串口与无线网卡绑定，保留测试命令和C600业务映射；② 构建脚本在原单文件EXE之外生成`LineCheckAssistant_portable`完整目录和同名ZIP，随包放置操作说明、第三方声明和EXE SHA256，并限制递归清理只能位于`dist`；③ 构建原生失败码、预期文件和ZIP存在性都改为显式失败；④ 增加脱敏值不泄漏、当前配置目录不可覆盖、便携结构和构建脚本不得启动EXE的回归并纳入强制基线；⑤ 实际完成最新版构建，未在当前电脑运行任何新EXE。
- 修改文件：`.claude/plans/portable_release_bundle.md`、`Cheating_machine_execution_tool/build_line_check_assistant.ps1`、`Cheating_machine_execution_tool/scripts/create_portable_config.py`、`Cheating_machine_execution_tool/line_check_assistant/packaging_assets/PORTABLE_README.txt`、`Cheating_machine_execution_tool/line_check_assistant/packaging_specs/LineCheckAssistant.spec`、`Cheating_machine_execution_tool/tests/test_portable_release.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行便携版专项测试、`python scripts/verify_baseline.py`和`powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1`；构建后只读检查PE头、目录/ZIP清单、记录哈希与实际SHA256一致性，并将当前运行INI的受保护值与便携INI全文交叉扫描。
- 验证结果：便携版专项4项`OK`；完整门禁678项单元测试、57个源码文件编译覆盖、156个强制基线测试、8条MUST_EXIST和1条MUST_NOT_EXIST全部通过；EXE为有效`MZ`头，ZIP包含11个条目，6类脱敏检查全部为True，SHA256为`F57567E6A62CD8116B225874E7B1574E7E2A10C75921EBE27A63EBA50974C9D9`。生成`dist/LineCheckAssistant_portable.zip`（62,785,324字节）和完整目录；按项目边界未运行EXE，因此不把构建检查视为另一台Windows电脑的启动或真实业务验收。
- 后续待办：在目标Windows 10/11电脑完整解压ZIP，以管理员身份启动；按`PORTABLE_README.txt`重新配置网卡/VLAN/源IP、COM、各业务凭据和文件路径，再完成主界面、保存/重开和实际所需业务入口的现场验收。

## 2026-08-18 - 修正C600速率下发并完成实机验证

- 类型：BUG 修复
- 背景：项目负责人要求直接使用一台未注册ONU走完当前C600注册与业务逻辑并修复现场问题。首次真实执行中，ONU ID/SN预检和注册成功，但NP7287XGS在ONU接口下拒绝自动生成的`real-speed xgspon`，返回`%Error 230240: Not support this function.`；detail-info显示该型号无需此命令便会自动进入XGS-PON。
- 完成内容：① C600发现结果中的Speed Mode改为能力信息，选中ONU后速率设置统一默认为`auto`，命令预览、配置和验证均省略`real-speed`；操作员仍可明确选择xgspon/xgpon/gpon作为其它型号的手工覆盖；② 新安装/缺省配置的C600速率默认值同步改为`auto`，已有手工值继续保留；③ 增加发现默认auto、auto不生成/不验证real-speed、界面选中回填auto及store缺省回归，两项关键行为加入强制基线；④ 使用同一台真实NP7287XGS从未注册状态再次执行完整service，精确ID/SN预检、9组业务、SN双重绑定、MVLAN 600、7次OffLine/syncMib/working轮询和四组解析全部成功；⑤ 按项目负责人明确授权删除测试ONU，删除前复核身份，删除后确认ID/SN为空且第5次查询重新回到未注册列表；另一台未注册ONU未处理，全程未执行`write`。
- 修改文件：`.claude/plans/c600_live_registration_validation.md`、`Cheating_machine_execution_tool/src/core/zte_c600_onu.py`、`Cheating_machine_execution_tool/line_check_assistant/onu_registration_store.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_service.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行ONU service/driver、主程序、配置store专项测试与`python scripts/verify_baseline.py`；真实C600从未注册发现开始执行完整service并核对实际TX/返回，成功后以精确身份保护删除测试ONU，再查询baseinfo、全OLT SN和未注册列表确认清理。
- 验证结果：ONU service/driver专项27项、主程序专项157项、配置store专项5项均`OK`；真实C600完整service返回`已完成 1 个 C600 ONU 注册配置和只读验证（未执行 write）`，最终清理三项确认全部通过；完整基线门禁674项单元测试通过，57个源码文件编译覆盖、152个强制基线测试实际执行，最终`ALL CHECKS PASSED`。本次证明C600 service与实际命令链，不替代Windows三步UI、停止及Access denied专项验收。
- 后续待办：项目负责人在Windows源码版查询C600未注册ONU，确认选中NP7287XGS后速率设置为`auto`、预览无`real-speed`，再按现场需要复验UI注册；补充停止和Access denied专项场景。C300真实注册边界保持待验收。

## 2026-08-18 - 修复全流程读取已销毁ONU控件

- 类型：BUG 修复
- 背景：项目负责人现场发现打开并关闭ONU注册窗口后，“全流程执行”7个子任务全部显示`invalid command name ...!text`。根因是Tk `Text`已随ONU窗口销毁，但Python属性仍存在；全流程构建共享上下文时，当前ONU配置读取只判断`hasattr`便调用该失效控件的`get()`，上下文失败后同一异常被显示到全部7行。此前基线测试分别Mock了当前ONU配置方法或始终存活的Text，没有覆盖跨窗口销毁生命周期，属于强制基线覆盖缺口。
- 完成内容：① 当前ONU配置只在C600业务映射Text仍存活时读取窗口值，控件已销毁或发生Tk生命周期异常时改用最近保存的内存配置；② ONU配置保存成功后同步更新主程序`onu_registration_config`缓存，确保关闭窗口后的全流程读取最新值；③ 增加失效Text单元回归和全流程真实调用主程序配置方法的跨模块回归，并继续计算全部7项状态；④ 两项新回归纳入强制基线，避免再次用整体Mock绕过故障路径。
- 修改文件：`.claude/plans/pipeline_destroyed_onu_widget.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p test_app.py`、`python -m unittest discover -s tests -p test_pipeline_window.py`、真实Tk销毁控件`winfo_exists()`检查、`python scripts/verify_baseline.py`与`git diff --check`；Windows源码版按“打开ONU注册→关闭→打开全流程→刷新状态”复验7行状态。
- 验证结果：主程序专项156项、全流程窗口专项29项均`OK`；真实Tk销毁后的Text返回`winfo_exists=0`；完整基线门禁672项单元测试通过，57个源码文件编译覆盖、150个强制基线测试实际执行，8条MUST_EXIST与1条MUST_NOT_EXIST均通过，最终`ALL CHECKS PASSED`。自动化与Tk生命周期检查不替代项目负责人Windows界面复验。
- 后续待办：项目负责人在当前Windows源码版依次打开并关闭ONU注册窗口，再打开全流程执行或点击“刷新状态”，确认7项分别显示自身真实就绪/缺项状态且不再出现`invalid command name`；现场结论确认后再更新验收状态。

## 2026-08-18 - 收紧ONU注册现场安全边界

- 类型：优化
- 背景：结合真实OLT中“配置存在但ONU仍离线”、C300离线记录可能跨PON并存、C600命令空结果以`%Error`返回以及两型号使用不同管理网卡的情况，需要进一步防止误删、误判上线、冲突漏检和连接资料串用。
- 完成内容：① C300危险清理改为先只读查询目标PON离线候选并由操作员明确选择一台，授权不持久化；连接、目标或参数变化会清空旧候选，配置失败后再次核对该ONU仍为同PON离线候选且接口/SN未变化，只允许生成一条目标`no onu`，禁止批量或跨PON删除；② C600下发前使用精确baseinfo和全OLT SN查询检查冲突，只在对应只读命令中接受无记录`%Error`，同时要求ServiceID/VLAN映射包含VLAN 600；③ 两种OLT下发后增加最长60秒、可响应停止的working轮询，配置存在但离线不再误报成功；④ C600完整解析collection、终端换行service-port、detail-info和MVLAN四组真实格式，逐项核对身份、T-CONT/GEM/VPort、业务状态、working/config success和MVLAN 600；⑤ C300/C600分别保存OLT IP、锁定源IP和登录资料，型号切换不再串用另一型号资料；⑥ 增加危险候选UI、身份复核、冲突空结果、离线状态、真实换行解析、上线轮询、双配置资料及VLAN/MVLAN一致性回归并纳入强制基线。
- 修改文件：`.claude/plans/onu_registration_safety_followup.md`、`Cheating_machine_execution_tool/src/models/onu_registration_models.py`、`Cheating_machine_execution_tool/src/models/__init__.py`、`Cheating_machine_execution_tool/src/core/zte_c300_onu.py`、`Cheating_machine_execution_tool/src/core/zte_c600_onu.py`、`Cheating_machine_execution_tool/src/services/onu_registration_service.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/onu_registration_store.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_service.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行相关源码`py_compile`、ONU service/driver专项、主程序专项、配置持久化专项、`python -m unittest discover -s tests`、`python scripts/verify_baseline.py`与`git diff --check`；真实OLT只使用此前已完成的只读命令核查，本轮未下发配置、删除或`write`。
- 验证结果：ONU注册service/driver专项26项、主程序专项155项、配置持久化专项5项均`OK`；全量与完整基线门禁均为670项单元测试通过，57个源码文件编译覆盖、148个强制基线测试实际执行，8条MUST_EXIST与1条MUST_NOT_EXIST均通过，最终`ALL CHECKS PASSED`。自动化测试和只读命令核查不替代Windows界面及真实注册写入验收。
- 后续待办：Windows源码版确认分型号连接资料、C300离线候选查询/单选/清空及普通窗口布局；真实C300覆盖显式单台清理前后二次身份变化、上线轮询与完整验证，真实C600覆盖精确冲突、VLAN/MVLAN 600、离线超时、四组解析、停止和Access denied。现场结论由项目负责人提供后再更新验收状态。

## 2026-08-18 - 强化C300注册并补齐C600 MVLAN

- 类型：功能
- 背景：项目负责人要求C300改为一次只注册一台，并参照C600增加准确的ONU ID/SN冲突检查和下发后验证；同时确认C600也必须固定配置MVLAN 600。旧C300仅检查未注册表和状态表，C600业务VLAN 600也不等同MVLAN，原两条路径均缺少对应完整保护。
- 完成内容：① 从指定源IP登录真实C300，以一台已注册在线ONU和空ID/空SN样例核对`baseinfo/state/detail-info/tcont/gemport/vport/service-port/remote-onu service/mvlan/by sn`的命令与返回格式，全程未修改设备；② C300下发前按目标PON确认ONU仍未注册、ONU ID为空并做全OLT SN查重，下发后逐项核对身份/ready/working/config success/SN Bind、1G T-CONT、六个active GEM、六个1:1 VPort、固定六组业务及MVLAN 600；③ C300/C600界面统一单选，移除可见“全选”，UI和service双层强制一次一台；④ C300默认连接改为`172.18.18.151`经`172.18.18.40`，C600已知默认保持`172.18.18.152`经`172.33.5.35`，仅在空值或已知默认值间随型号联动；⑤ 登录真实C600确认当前样本无MVLAN数据、查询命令有效以及`pon-onu-mng`上下文支持`mvlan <1-4094>`，随后在C600配置序列加入固定`mvlan 600`并增加独立回读判定；⑥ 新增真实输出格式、冲突、完整验证、两型号单台限制、默认源IP和C600 MVLAN回归并纳入强制基线。
- 修改文件：`.claude/plans/c300_single_registration_verification.md`、`Cheating_machine_execution_tool/src/core/zte_c300_onu.py`、`Cheating_machine_execution_tool/src/core/zte_c600_onu.py`、`Cheating_machine_execution_tool/src/services/onu_registration_service.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/onu_registration_store.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_service.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行相关源码`py_compile`、ONU service/driver专项、配置持久化专项、主程序专项、`python scripts/verify_baseline.py`与`git diff --check`；真实OLT部分仅执行针对性查询和CLI帮助，不执行注册、删除或`write`。
- 验证结果：ONU注册service/driver专项19项、配置持久化专项5项、主程序专项151项均`OK`；完整基线门禁659项单元测试通过，57个源码文件编译覆盖、140个强制基线测试实际执行，8条MUST_EXIST与1条MUST_NOT_EXIST均通过，最终`ALL CHECKS PASSED`。真实C300/C600命令格式已完成非写入核查，自动化测试和命令核查不替代真实注册写入及Windows界面验收。
- 后续待办：Windows源码版确认C300/C600均为单选、型号切换后的默认源IP和三步布局；分别使用真实未注册ONU完成C300冲突拦截/完整下发后验证/删除授权/write及C600包含`mvlan 600`的完整注册、MVLAN回读、停止、Access denied和不自动write验收。

## 2026-08-17 - 保护ONU窗口底部区域

- 类型：BUG 修复
- 背景：ONU注册窗口在普通尺寸下，危险提示、状态栏和“关闭/停止”只有最大化后才能完整显示。原因是Notebook在底部控件之前按自然请求高度占位，且命令预览Text未指定高度、默认请求约24行，剩余空间不足时后布局的底部区域被裁切。
- 完成内容：① 保留项目负责人当前设置的`1000x800`默认和最小尺寸；② 顶层标题、说明、连接区、Notebook、危险提示、状态栏和按钮区改为固定七行`grid`；③ 只给Notebook所在行伸缩权重，底部三行始终优先保留请求高度；④ 命令预览Text显式限制为8行初始高度；⑤ 新增普通窗口不依赖最大化、Notebook不再使用顶层`pack`、底部固定行及预览高度回归并纳入强制基线。
- 修改文件：`.claude/plans/onu_registration_step_tabs.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p test_app.py -v`、`python scripts/verify_baseline.py`与`git diff --check`。
- 验证结果：主程序专项149项`OK`；完整基线门禁651项单元测试通过，57个源码文件编译覆盖、136个强制基线测试实际执行，8条MUST_EXIST与1条MUST_NOT_EXIST均通过，最终`ALL CHECKS PASSED`。自动化测试不替代Windows普通窗口目视验收。
- 后续待办：Windows源码版以`1000x800`普通窗口打开ONU注册，逐页确认危险提示、状态栏和“关闭/停止”完整显示，无需最大化。

## 2026-08-17 - 重排ONU注册三步流程

- 类型：优化
- 背景：现有ONU注册分页按内容分类，C600需要在连接页、参数页和预览页之间反复切换；项目负责人确认按“查询ONU → 配置业务 → 确认执行”的使用顺序重排。
- 完成内容：① OLT型号、OLT IP、锁定源IP、凭据、登录测试和连接状态移到三页上方持续显示；② 第一页集中查询条件、发现结果和选择，C600机框/槽位/PON不再放在参数页，C300保持多选/全选并由“下一步”推进，C600改用单选、隐藏全选且选中后直接进入第二步；③ 第二页按型号切换C300固定模板/危险删除开关和C600完整业务参数；④ 第三页集中显示OLT、目标、安全策略摘要、完整命令和唯一注册按钮，并提供返回修改；⑤ 未选择ONU不能进入配置，型号、连接、目标或参数变化后旧预览清空并禁用注册，必须重新生成；⑥ 查询/执行状态、停止和关闭移到分页外持续可见；⑦ 新增三步结构、步骤推进、预览摘要和失效保护回归，并将三步UI结构纳入强制基线。
- 修改文件：`.claude/plans/onu_registration_step_tabs.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p test_app.py -v`、`python scripts/verify_baseline.py`与`git diff --check`。
- 验证结果：主程序专项148项`OK`；完整基线门禁650项单元测试通过，57个源码文件编译覆盖、135个强制基线测试实际执行，8条MUST_EXIST与1条MUST_NOT_EXIST均通过，最终`ALL CHECKS PASSED`。自动化测试不替代Windows桌面和真实OLT验收。
- 后续待办：Windows源码版确认`896x580`下全局连接区、三个步骤、C300/C600条件内容、命令预览、状态栏和底部按钮完整可见；真实OLT注册验收边界保持不变。

## 2026-08-17 - 统一C600显示名称

- 类型：修改 / UI命名 / 文档
- 背景：项目负责人确认主程序中的`C600/TITAN`统一简称为`C600`，避免操作员将同一台OLT理解为两个型号。
- 完成内容：① 主界面ONU注册说明和参数区标题统一显示`C600`；② C600驱动显示名称改为“中兴 C600”，内部型号值和C600专属命令路由保持不变；③ 操作说明、验收边界和实施计划同步采用C600名称；④ 增加主界面不再显示`TITAN`及驱动显示名回归断言；原始C600参考工具目录及内部包名不改动。
- 修改文件：`.claude/plans/unified_zte_onu_registration.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/core/zte_c600_onu.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_service.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行ONU注册service专项、主程序专项、`python scripts/verify_baseline.py`与`git diff --check`。
- 验证结果：ONU注册service专项13项、主程序专项144项均`OK`；完整基线门禁646项单元测试通过，57个源码文件编译覆盖、134个强制基线测试实际执行，8条MUST_EXIST与1条MUST_NOT_EXIST均通过，最终`ALL CHECKS PASSED`。自动化测试不替代Windows桌面和真实OLT验收。
- 后续待办：Windows源码版确认ONU注册窗口只显示`C600`，不再出现`C600/TITAN`或`TITAN`别名。

## 2026-08-17 - 统一C300与C600 ONU注册

- 类型：功能
- 背景：项目负责人将C600注册参考工具合入仓库，要求不复用其独立GUI，而是在`run_line_check_assistant.py`启动的当前主界面“ONU注册”入口同时支持中兴C300与C600；两台OLT业务阶段相近，但查询、接口命名、service-port位置和验证命令格式不同，必须严格隔离。
- 完成内容：① 新增统一ONU连接、发现结果、注册请求、业务映射和操作结果模型；② 新增必须绑定显式源IP的中兴OLT Telnet核心，支持登录、逐条命令、分页、首条CLI错误停止、取消和失败后安全退出；③ C300与C600分别实现独立driver，C300保留`gpon-olt_`/`gpon-onu_`及SD-41固定模板，C600使用`gpon_olt-`/`gpon_onu-`/`vport-`、按PON发现、ONU ID/SN冲突检查、动态ServiceID/VLAN和三组只读验证；④ 统一service编排查询、预检、下发和验证，C300离线ONU删除重试改为默认关闭的独立危险选项，未授权时首错停止且不下发`no onu`，C600始终不删除、不自动write；⑤ 现有`896x580` ONU窗口改为“连接与发现/C600参数/命令预览”分页，增加OLT型号、源IP、C600完整参数、预览和停止，主程序不导入或启动C600独立GUI；⑥ C300成功后保留独立write确认，C600完成后只提示现场手工决定；⑦ 扩展本机`onu_registration.ini`持久化并让全流程必填状态检查显式源IP；⑧ 新增双driver、锁源、路由、预检、危险删除开关、C600禁止write、UI和持久化回归并纳入强制基线。
- 修改文件：`.claude/plans/unified_zte_onu_registration.md`、`Cheating_machine_execution_tool/src/models/onu_registration_models.py`、`Cheating_machine_execution_tool/src/models/__init__.py`、`Cheating_machine_execution_tool/src/core/zte_olt_telnet.py`、`Cheating_machine_execution_tool/src/core/zte_c300_onu.py`、`Cheating_machine_execution_tool/src/core/zte_c600_onu.py`、`Cheating_machine_execution_tool/src/services/onu_registration_service.py`、`Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/onu_registration_store.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_service.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_store.py`、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p test_onu_registration_service.py -v`、`python -m unittest discover -s tests -p test_onu_registration_store.py -v`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_pipeline_orchestrator.py -v`、`python -m unittest discover -s tests -v`、`python scripts/verify_baseline.py`和`git diff --check`。
- 验证结果：ONU driver/service专项13项、配置持久化5项、主程序144项、全流程状态42项均`OK`；全量646项单元测试通过；完整基线门禁57个源码文件编译覆盖、134个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过，最终`ALL CHECKS PASSED`。自动化测试不替代Windows桌面和真实C300/C600 OLT验收。
- 后续待办：Windows源码版确认`896x580`三分页布局、型号切换、C600参数/预览和停止；真实C300确认默认不删除、显式授权删除重试及独立write；真实C600确认按PON发现、冲突预检、完整T-CONT/GEM/VPort/业务配置、三组验证、停止、Access denied及不自动write。现场结论由项目负责人提供后再更新验收状态。

## 2026-08-17 - 增加双频独立射频配置

- 类型：功能
- 背景：2.4G与5G支持的信道、信道带宽和协议不同；原“启用双频合一”只同步SSID/AP/安全参数并仅修改当前Tab Radio，无法在一次操作中明确配置另一频段。项目负责人确认采用两套独立射频参数，发射功率归为公共参数。
- 完成内容：① WiFi模型增加另一频段Radio参数和能力快照；② 查询当前2.4G或5G时均分别解析`X_SDMC_Mapping_2G/5G`并预读两个Radio，状态区显示两套参数；③ 当前页勾选双频合一后显示另一频段射频区域，2.4G与5G的信道、带宽和协议使用各自DUT能力独立选择，取消后隐藏另一组并只配置当前Radio；④ 发射功率在双频时取两个Radio共同支持候选并分别下发到两边，界面字段简化显示为“发射功率(%)”；⑤ core分别写入并回读两个Radio，SSID、启用/隐藏、认证密码、最大接入数和WMM继续作为公共参数同步；⑥ service在下发前分别校验两套射频能力、另一频段完整性和公共功率一致性；⑦ 确认框与主日志展示两套最终射频参数；⑧ 更新强制基线并保留单台60秒稳定等待、SSID递增批次统一等待及只读查询不set等既有边界。
- 修改文件：`.claude/plans/dut_wifi_dual_radio_fields.md`、`Cheating_machine_execution_tool/src/models/dut_config_models.py`、`Cheating_machine_execution_tool/src/models/__init__.py`、`Cheating_machine_execution_tool/src/core/dut_wifi_config.py`、`Cheating_machine_execution_tool/src/services/dut_advanced_config_service.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_dut_wifi_config.py`、`Cheating_machine_execution_tool/tests/test_dut_advanced_config_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p test_dut_wifi_config.py -v`、`python -m unittest discover -s tests -p test_dut_advanced_config_service.py -v`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_dut_status_query_service.py -v`、`python scripts\verify_baseline.py`与`git diff --check`；Windows源码版分别在2.4G和5G页切换双频合一，核对另一射频组显隐、两套动态候选、确认内容、实际下发和双频回读。
- 验证结果：WiFi core专项7项、DUT高级配置service专项22项、主程序专项141项、DUT状态查询专项7项全部`OK`；完整基线门禁627项单元测试通过，52个源码文件编译覆盖、128个强制基线测试实际执行，8条MUST_EXIST与1条MUST_NOT_EXIST均通过，最终`ALL CHECKS PASSED`。自动化测试不替代Windows桌面和真实双频DUT验收。
- 后续待办：Windows确认勾选后另一频段射频区域完整显示且底部状态/目标/按钮不被挤压；真实DUT分别从2.4G页和5G页执行双频配置，确认两套Radio按独立参数下发、公共功率写入两边并全部回读成功，取消双频时另一Radio保持不变。现场结论由项目负责人提供后再更新验收状态。

## 2026-08-16 - 合并WiFi递增批次稳定等待

- 类型：优化
- 背景：多台DUT开启SSID递增后，原流程每台样机都在`bbfdm.set`后独立等待60秒，批次耗时随目标数线性增加。项目负责人要求仅最后一台等待60秒，同时必须保留各台配置结果查询。
- 完成内容：① core将WiFi“下发”和“回读校验”拆为独立协议切片，原`configure_wifi`继续组合为单台下发、等待60秒、回读的已验收时序；② service仅对“多台且开启SSID递增”启用批次两阶段编排，先完成全部目标下发，再把唯一一次可停止的60秒稳定等待记在最后成功下发目标日志下，最后逐台重新准备网络、登录并回读；③ 下发失败目标不进入回读且不阻断其它目标，等待期间停止会把已下发但未回读目标标记停止，不误报成功；④ 单台设置和未开启递增的批量设置保持每台各自等待60秒；⑤ 主界面确认框与主日志明确提示本批等待策略；⑥ 新增分阶段协议、仅等待一次、最后目标日志归属、逐台回读、等待中停止及入口透传回归，并纳入强制基线。
- 修改文件：`.claude/plans/dut_wifi_increment_shared_settle.md`、`Cheating_machine_execution_tool/src/core/dut_wifi_config.py`、`Cheating_machine_execution_tool/src/services/dut_advanced_config_service.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_dut_wifi_config.py`、`Cheating_machine_execution_tool/tests/test_dut_advanced_config_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p test_dut_wifi_config.py -v`、`python -m unittest discover -s tests -p test_dut_advanced_config_service.py -v`、`python -m unittest discover -s tests -p test_app.py -v`、`python scripts\verify_baseline.py`与`git diff --check`；Windows真实DUT勾选多台并开启SSID递增，核对仅最后一台出现一次60秒等待且等待后每台均完成回读。
- 验证结果：WiFi core专项7项、DUT高级配置service专项21项、主程序专项140项全部`OK`；完整基线门禁625项单元测试通过，52个源码文件编译覆盖、126个强制基线测试实际执行，8条MUST_EXIST与1条MUST_NOT_EXIST均通过，最终`ALL CHECKS PASSED`。自动化测试不替代多台真实DUT时序验收。
- 后续待办：Windows真实DUT覆盖2/4/8台递增下发，确认仅最后成功下发目标显示并执行一次60秒等待、每台回读结果正确；再验证统一等待期间停止和单台下发/回读失败隔离。现场结论由项目负责人提供后再更新验收状态。

## 2026-08-16 - 支持点击主界面切换到前方

- 类型：功能 / UI窗口层级 / 回归测试 / 文档
- 背景：打开DUT配置等二级功能窗口后，Windows因`transient(main)`所有者关系始终让二级窗口压住主界面；项目负责人要求点击主界面任意位置即可让主界面最前显示，同时保持二级窗口继续打开。
- 完成内容：① 主窗口统一绑定自身及子控件的鼠标按下事件并执行`lift()`，不调用`focus_force()`，避免抢走操作员刚点击的输入控件焦点；② 写样机参数、ONU注册、样机升级、测试项配置、DUT配置和全流程执行解除相对主界面的`transient`强制所有者关系，串口日志延续已有非模态行为；③ 二级窗口不关闭、不重建，再次点击原功能入口仍复用窗口并升到前方；④ 生成批量参数表、选择程控电源以及确认/警告等必须先处理的模态交互继续保留`transient + grab`，不允许绕过必要输入或危险确认；⑤ 增加主界面点击升层、不强制焦点、六类非模态窗口层级及两类模态边界回归，并纳入强制基线。
- 修改文件：`.claude/plans/main_window_click_raise.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p test_app.py`、相关源码`py_compile`、`python scripts\verify_baseline.py`与`git diff --check`；Windows源码版逐个打开DUT配置、样机升级、写样机参数、ONU注册、测试项配置、全流程执行和串口日志，点击主界面空白/输入框/按钮区域确认主界面升到前方，再点击功能入口确认原窗口恢复前方且状态未丢失。
- 验证结果：主程序专项140项全部`OK`；完整基线门禁621项单元测试通过，52个源码文件编译覆盖、123个强制基线测试实际执行，8条MUST_EXIST与1条MUST_NOT_EXIST均通过，最终`ALL CHECKS PASSED`。自动化测试不替代Windows桌面层级验收。
- 后续待办：Windows桌面逐个确认上述非模态窗口与主界面可双向切换前后层级；同时确认生成参数表、程控电源选择和危险确认仍保持模态阻塞。现场结论由项目负责人提供后再更新验收状态。

## 2026-08-16 - 增加DUT WiFi SSID递增

- 类型：功能 / DUT配置 / WiFi / 批量目标 / 回归测试 / 文档
- 背景：多台DUT同时配置WiFi时需要各自使用连续且唯一的SSID。项目负责人确认采用数字尾缀递增：第一台使用输入值，后续按DUT窗口已选目标固定顺序加1，并要求执行前逐台预览。
- 完成内容：① 2.4G与5G页分别增加默认关闭、互不影响的原生“SSID递增”勾选项和实时规则提示；② service按已选目标数生成逐台不可变`DutWifiSettings`，保留数字尾缀宽度且不修改原始表单参数；③ 开启时拒绝没有数字尾缀的名称，不自动追加数字；逐项按UTF-8校验32字节上限，任一超限整批不下发；④ 主程序按DUT窗口目标表固定顺序冻结逐台SSID，请求确认框和主执行日志明确展示`通道/VLAN → 最终SSID`，并行补位和单台重试复用相同请求；⑤ 双频合一继续以每台最终SSID同步两个频段，查询功能保持只读且不参与递增；⑥ 增加尾缀位宽、中文UTF-8超限、关闭兼容、逐台请求顺序和UI/预览/日志接线回归，并纳入强制基线。
- 修改文件：`.claude/plans/dut_wifi_ssid_increment.md`、`Cheating_machine_execution_tool/src/services/dut_advanced_config_service.py`、`Cheating_machine_execution_tool/src/services/__init__.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_dut_advanced_config_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p test_dut_advanced_config_service.py`、`python -m unittest discover -s tests -p test_app.py`、相关源码`py_compile`、`python scripts\verify_baseline.py`与`git diff --check`；Windows源码版在2.4G/5G页分别使用`Aouxue_001`勾选递增，对多台已选DUT执行并核对确认框、主日志、实际下发和回读。
- 验证结果：DUT高级配置service专项18项、主程序专项138项全部`OK`；完整基线门禁619项单元测试通过，52个源码文件编译覆盖、121个强制基线测试实际执行，8条MUST_EXIST与1条MUST_NOT_EXIST均通过，最终`ALL CHECKS PASSED`。自动化测试不替代Windows桌面和真实DUT验收。
- 后续待办：Windows桌面确认两个WiFi页勾选框默认值、互相独立及提示显示；真实DUT覆盖连续SSID逐台下发/回读、双频合一、并行失败/重试映射不变，以及非法尾缀和32字节超限均不产生设备写操作，现场结论由项目负责人提供后再更新验收状态。

## 2026-08-16 - DUT配置窗口增加独立目标选择

- 类型：功能 / DUT配置 / 批量目标 / 回归测试 / 文档
- 背景：主界面需要同时保持多台样机启用，但操作员可能只想在DUT配置窗口查询或修改其中一台。例如主界面同时勾选vlan112和vlan113时，需要允许DUT窗口本批只处理vlan112。
- 完成内容：① 六个DUT Tab的目标表增加共享“选择”列及“全选/清除”，首次加载默认继承主界面全部候选，在任一Tab逐台切换会同步到其它Tab；② 刷新相同候选保留手动取消，新加入候选默认选中，主界面移除的候选自动删除；③ Telnet启用、WAN配置、2.4G/5G WiFi配置、语音/TR069配置及全部只读查询统一只收集窗口内已选目标，确认框、参数校验和批次统计使用同一范围；④ 未选目标的配置错误不再阻塞已选目标，窗口未选任何目标时明确提示再次勾选；⑤ 目标选择变化后旧WAN下拉、当前状态和DUT动态能力立即失效，批次运行期间禁止修改目标；⑥ 新增选择继承、跨Tab同步、请求过滤、入口接线、空选择拦截及未选错误隔离回归，并纳入强制基线。
- 修改文件：`.claude/plans/dut_config_target_selection.md`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p test_app.py`、`python -m py_compile line_check_assistant\app.py src\ui\dut_config_window.py`、`python scripts\verify_baseline.py`与`git diff --check`；Windows源码版主界面同时勾选vlan112/vlan113，打开DUT配置后取消vlan113，分别执行查询和配置并核对日志只出现vlan112。
- 验证结果：主程序专项测试137项全部`OK`；完整基线门禁615项单元测试通过，52个源码文件编译覆盖、118个强制基线测试实际执行，8条MUST_EXIST与1条MUST_NOT_EXIST均通过，最终`ALL CHECKS PASSED`。自动化测试不替代Windows桌面和真实DUT验收。
- 后续待办：Windows桌面确认六页选择列显示、逐台点击和“全选/清除”同步；真实DUT按主界面vlan112/vlan113均勾选、窗口只选vlan112的场景，确认所有配置与查询都不访问vlan113，现场结论由项目负责人提供后再更新验收状态。

## 2026-08-14 - 扩展DUT动态能力范围

- 类型：功能
- 背景：项目负责人纠正此前验收范围：按DUT能力动态加载只在2.4G WiFi完成现场验收；5G WiFi、语音和TR069仍需要实现并分别验收。
- 完成内容：① 将验收记录严格收窄为仅2.4G WiFi五类下拉通过，5G不再误列为已验收；② 明确5G查询使用独立`X_SDMC_Mapping_5G`、5G Radio及自己的认证/信道/带宽/协议/功率能力，补独立回归防止复用2.4G候选；③ 语音模型增加DTMF、SIP模式和编码能力，查询VoIPProfile/SIP支持字段及标准`Device.Services.VoiceService.1.Capabilities.Codecs.`，查询后动态更新三个下拉，service按同一DUT能力再次预检；④ TR069查询记录`Device.ManagementServer.`实际存在字段，缺失参数在界面禁用，配置载荷同步裁剪，设备未返回手动Inform能力时拒绝选择；⑤ 切换DUT或多台参数/能力不一致时清除语音、TR069和WiFi旧能力，避免拿任意一台覆盖整批。
- 修改文件：`.claude/plans/dut_dynamic_capabilities_5g_voice_tr069.md`、`Cheating_machine_execution_tool/src/models/dut_config_models.py`、`Cheating_machine_execution_tool/src/core/dut_ubus_config.py`、`Cheating_machine_execution_tool/src/services/dut_advanced_config_service.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_dut_ubus_config.py`、`Cheating_machine_execution_tool/tests/test_dut_advanced_config_service.py`、`Cheating_machine_execution_tool/tests/test_dut_wifi_config.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录分别执行四个相关测试文件及`python scripts\verify_baseline.py`；Windows真实DUT分别查询5G WiFi、语音和TR069，核对候选/可配置字段后执行下发与回读。
- 验证结果：针对性测试14项、15项、6项与131项全部`OK`；完整基线门禁609项单元测试通过，52个源码文件编译覆盖、112个强制基线测试实际执行，最终`ALL CHECKS PASSED`。
- 后续待办：真实DUT验收5G五类下拉和实际配置、语音DTMF/SIP/编码能力与实际下发回读、TR069缺失字段禁用及实际下发回读；自动化测试不替代现场验收。

## 2026-08-14 - 验收WiFi动态能力下拉

- 类型：真实样机验收 / 状态更新
- 背景：项目负责人在Windows源码版连接真实DUT，确认2.4G WiFi参数下拉按DUT实际能力动态加载验收通过。
- 完成内容：① 将仅2.4G页的认证/加密模式、信道、信道带宽、WiFi协议类型和发射功率五类下拉按DUT实际能力动态加载更新为已确认验收；② 认证/加密模式与DUT管理页面一致，仅显示`None`、`WPA2-Personal`和`WPA3-Personal-Transition`三项；③ 本次不包含5G，也不扩大为设备缺能力字段兜底、目标变化清理、WiFi实际下发或其它配置组合验收。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：项目负责人在Windows源码版连接真实DUT，查询WiFi状态后核对五类只读下拉与DUT管理页面实际支持能力一致；在主源码目录执行`python scripts\verify_baseline.py`。
- 验证结果：项目负责人确认“2.4G按DUT实际能力动态加载”验收通过（2026-08-14）；完整基线门禁604项单元测试通过，最终`ALL CHECKS PASSED`。
- 后续待办：继续验收设备缺少能力字段时的兜底、目标变化后旧能力清理、2.4G其它参数组合、5G实际配置、开放网络、隐藏SSID、双频合一及并行异常场景。

## 2026-08-14 - 按DUT能力加载WiFi候选

- 类型：BUG 修复
- 背景：DUT管理页面的认证/加密模式实际只有`None`、`WPA2-Personal`、`WPA3-Personal-Transition`三项，但工具固定展示五项；信道、带宽、协议和发射功率也应以当前DUT实际能力为准，避免操作员选择设备不支持的值。
- 完成内容：① WiFi状态模型增加认证模式和发射功率能力列表，保留已有信道、带宽和协议能力；② 从AP Security `ModesSupported`解析认证候选，从Radio `X_SDMC_ChannelsSupported`及`X_SDMC_ModeBWMap`解析信道/带宽/协议，从`TransmitPowerSupported`及四个厂商兼容名称解析功率；③ 查询成功后五个只读下拉按DUT返回顺序更新，当前实际值缺失时仍保留，单项未返回能力才使用原分频段兜底；④ 目标变化后清除上一台DUT的动态候选并提示重新查询；⑤ 配置预检使用当前下拉携带的DUT能力列表，既允许设备实际支持的厂商值，也拒绝不在该设备能力列表中的值；⑥ 补设备三项认证模式、标准/厂商功率字段、五类动态候选、缺字段兜底及能力约束回归。
- 修改文件：`Cheating_machine_execution_tool/src/models/dut_config_models.py`、`Cheating_machine_execution_tool/src/core/dut_wifi_config.py`、`Cheating_machine_execution_tool/src/services/dut_advanced_config_service.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_dut_wifi_config.py`、`Cheating_machine_execution_tool/tests/test_dut_advanced_config_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p test_dut_wifi_config.py -v`、`python -m unittest discover -s tests -p test_dut_advanced_config_service.py -v`、`python -m unittest discover -s tests -p test_app.py -v`及`python scripts\verify_baseline.py`；Windows现场选择同一DUT，分别点击2.4G/5G“查询当前…”，核对五类下拉与DUT管理页面一致。
- 验证结果：针对性测试5项、14项与129项全部`OK`；完整基线门禁604项单元测试通过，最终`ALL CHECKS PASSED`。动态下拉的真实DUT/Windows显示仍待现场确认。
- 后续待办：现场确认截图中的DUT查询后认证下拉仅显示三项，并核对信道、带宽、协议、功率；再覆盖设备缺少`TransmitPowerSupported`时的兜底表现。

## 2026-08-14 - 验收WiFi连续两次配置

- 类型：真实样机验收 / 状态更新
- 背景：项目负责人在同一真实DUT上复验连续两次修改WiFi配置，确认此前第二轮读取`Device.WiFi.Radio.`超时的问题已经解决。
- 完成内容：① 将单台DUT的2.4G WiFi连续两次配置、每次下发后等待60秒稳定并完成回读更新为已确认验收；② 仅确认本次连续下发时序，不扩大为5G、2.4G其它参数组合、开放网络、隐藏SSID、双频合一或多台并行验收；③ 同步项目交接状态与DUT配置验收基线。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：项目负责人在Windows源码版连接同一真实DUT，连续执行两次2.4G WiFi修改，核对每轮下发、60秒稳定等待及回读结果；在主源码目录执行`python scripts\verify_baseline.py`。
- 验证结果：项目负责人确认“连续下发两次修改wifi配置会报错”BUG已解决，即单台2.4G WiFi连续两次配置真实样机验收通过（2026-08-14）；完整基线门禁600项单元测试通过，最终`ALL CHECKS PASSED`。
- 后续待办：继续验收5G WiFi、2.4G其它参数组合、开放网络、隐藏SSID、双频合一、1/8台并行、停止及单台失败隔离。

## 2026-08-14 - 修正WiFi连续配置超时

- 类型：BUG 修复
- 背景：真实DUT第一次2.4G WiFi配置、回读成功后立即再次执行，第二轮可完成登录与Mapping读取，但读取`Device.WiFi.Radio.`时出现`UBUS HTTP 请求失败 192.168.1.1:80：timed out`。WiFi set返回后设备Radio仍可能在后台重载，原流程却立即回读并过早宣告本轮成功。
- 完成内容：① 按真实DUT稳定时间将WiFi set成功后的可停止等待设为60秒，再执行回读并宣告成功，避免下一轮撞上Radio重载窗口；② 将HTTP连接层超时单独标记为`UbusTransportError`并立即丢弃异常连接；③ WiFi只读get遇到该瞬时连接错误时等待1秒、重建连接并仅重试1次，set/operate等写操作不自动重发；④ 查询与配置service均复用可响应停止事件的等待函数；⑤ 新增连续两次配置、Radio读取瞬时超时和异常连接丢弃回归。
- 修改文件：`Cheating_machine_execution_tool/src/core/ubus_http_client.py`、`Cheating_machine_execution_tool/src/core/dut_wifi_config.py`、`Cheating_machine_execution_tool/src/services/dut_advanced_config_service.py`、`Cheating_machine_execution_tool/src/services/dut_status_query_service.py`、`Cheating_machine_execution_tool/tests/test_ubus_http_client.py`、`Cheating_machine_execution_tool/tests/test_dut_wifi_config.py`、`Cheating_machine_execution_tool/tests/test_dut_advanced_config_service.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p test_ubus_http_client.py -v`、`python -m unittest discover -s tests -p test_dut_wifi_config.py -v`、`python -m unittest discover -s tests -p test_dut_advanced_config_service.py -v`、`python -m unittest discover -s tests -p test_dut_status_query_service.py -v`及`python scripts\verify_baseline.py`。
- 验证结果：针对性测试分别为16、5、13、7项，全部`OK`；基线门禁52个源码文件编译通过、600项单元测试通过、112个强制基线测试实际执行，不变量检查通过，最终`ALL CHECKS PASSED`。
- 后续待办：在同一真实DUT上连续执行至少两次2.4G WiFi配置，确认每轮日志均出现“等待 WiFi 参数生效并稳定：60 秒”且下发、回读成功；再按需复验5G WiFi。自动化测试不能替代真实Radio重载时序验收。

## 2026-08-13 - 验收参数表与DUT四组功能

- 类型：真实样机验收 / 状态更新
- 背景：项目负责人完成实际验收并明确确认四组功能通过：①批量样机参数表生成规则；②DUT配置窗口布局；③DUT连续查询和网卡复用；④WAN配置。
- 完成内容：① 将普通SN纯数字及16位上限、XPON SN固定12位、MAC前6位自定义/后6位随机十六进制、非法输入提示及SSID-MAC关联更新为已确认验收；② 将DUT六Tab左对齐/原生勾号、状态高度和底部按钮保护、窗口尺寸恢复及快速刷新更新为已确认验收；③ 将连续Telnet/WAN/WiFi/语音/TR069查询、设备session注销和DUT专用网卡四类按需准备路径更新为已确认验收；④ 将WAN完整查询回填、新增/修改/删除、协议和字段联动、端口绑定、IPTV组播VLAN及多台共同WAN更新为已确认验收；⑤ WiFi实际配置、语音/TR069实际配置、Telnet状态准确性、主动Access denied、1/8台并行、停止和单台失败隔离继续保留待验收。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：由项目负责人在Windows源码版及真实DUT环境按待验收清单逐项操作并核对界面、生成结果、设备状态与主执行日志。
- 验证结果：上述四组功能由项目负责人确认实际验收通过（2026-08-13）；本轮仅同步验收状态，未修改程序代码。
- 后续待办：继续验收DUT WiFi、语音/TR069、Telnet状态准确性及其它尚未覆盖的专项功能。

## 2026-08-13 - 验收批量参数生成窗口首帧修复

- 类型：真实样机验收 / 状态更新
- 背景：项目负责人在Windows源码版复验“生成批量样机参数表”窗口首帧修复后明确反馈“可以了”。
- 完成内容：将该窗口相对父窗口居中及20/120/360ms客户区尺寸刷新从“已实现未验收”更新为“已确认验收”；SN、XPON SN和MAC新生成规则仍保持待Windows实际生成表验收，不随本次窗口显示结论升级状态。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：由项目负责人在Windows源码版打开“生成批量样机参数表”，现场确认窗口无需移动鼠标即可正常完整显示。
- 验证结果：项目负责人确认窗口透明首帧修复验收通过（2026-08-13）；本轮仅同步验收状态，未修改程序代码。
- 后续待办：继续现场验收普通SN、XPON SN和用户自定义MAC前缀的实际表格生成结果。

## 2026-08-13 - 修复批量参数生成窗口透明首帧

- 类型：BUG 修复 / UI / 测试 / 文档
- 背景：项目负责人反馈“生成批量样机参数表”窗口再次出现与此前DUT配置相同的问题：首次打开只显示透明窗口，必须移动鼠标后内容才完整绘制。
- 完成内容：① 定位该窗口虽然使用标准`Toplevel`，但控件创建完成后没有接入DUT配置/测试项配置已验证的客户区尺寸刷新；② 在全部输入行和按钮创建后，按已知`680×750`尺寸相对“写样机参数”父窗口居中；③ 调用公共`schedule_toplevel_client_refresh`，在映射后20/120/360ms分别执行可恢复的一像素宽度脉冲，触发Windows客户区整树重绘；④ 保持自然映射，不增加`withdraw`、同步`update()`或`after(0)`，首次成功刷新写入主执行日志；⑤ 增加布局完成后居中、刷新调用顺序、父窗口和已知尺寸接线、禁止旧阻塞方案的源码回归，并加入强制基线。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p "test_app.py"`、`python scripts/verify_baseline.py`和`git diff --check`。
- 验证结果：主界面126项专项测试通过；强制基线全绿（52个当前主程序`.py`编译、编译清单完整、597项单测、112个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows源码版连续多次打开“生成批量样机参数表”，确认每次直接完整显示、无需移动鼠标，并核对居中、无闪烁和尺寸不漂移。现场结论由项目负责人提供后更新验收状态。

## 2026-08-13 - 增加批量参数表MAC前缀输入

- 类型：功能 / 优化 / UI / 测试 / 文档
- 背景：项目负责人要求“写样机参数 → 生成批量参数表”增加MAC生成规则行，由用户自定义MAC前6位，后6位随机生成十六进制；随后明确要求用户输入不符合十六进制时必须提示错误。
- 完成内容：① 参数生成模板增加`mac_prefix`字段，生成窗口新增“MAC 前6位（十六进制）”输入行，默认`020000`；② 核心层兼容`A2B3C4`、`A2:B3:C4`、`A2-B3-C4`三种输入形式，去掉分隔符后严格校验6位ASCII十六进制，并校验首字节为单播地址；长度错误、非十六进制和组播前缀均在保存前明确拒绝；③ 用户前缀统一输出为大写冒号格式，每台追加唯一的3字节随机十六进制后缀；④ 保持同批MAC前缀一致、完整MAC唯一及2.4G/5G SSID取各自MAC末4位的已验收关联；⑤ 成功日志增加MAC生成规则，新增自定义前缀、分隔/小写兼容、随机后缀、非法输入和UI接线测试并纳入强制基线。
- 修改文件：`.claude/plans/sample_parameter_mac_prefix.md`、`Cheating_machine_execution_tool/src/models/sample_parameter_models.py`、`Cheating_machine_execution_tool/src/core/sample_parameter_table.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_table.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p "test_sample_parameter_table.py"`、`python -m unittest discover -s tests -p "test_app.py"`、`python scripts/verify_baseline.py`和`git diff --check`。
- 验证结果：参数表11项、主界面125项专项测试通过；强制基线全绿（52个当前主程序`.py`编译、编译清单完整、596项单测、111个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows源码版输入有效自定义MAC前缀生成多台记录，核对前6位一致、后6位随机唯一及SSID末4位关联；再分别输入非十六进制、长度错误和组播前缀，核对错误提示。现场结论由项目负责人提供后更新验收状态。

## 2026-08-13 - 限制批量参数表普通SN格式

- 类型：功能 / 优化 / UI / 测试 / 文档
- 背景：项目负责人在XPON SN固定格式完成后继续明确普通SN规则：SN使用纯数字，字符总长上限为16位，前缀长度加随机后缀长度超过16位时必须提示错误。
- 完成内容：① 普通SN前缀必须为ASCII纯数字，随机后缀改为仅从`0-9`生成，同批继续保持唯一；② SN前缀与随机后缀长度合计最多16位，超过上限时提示实际前缀长度和后缀长度，前缀为空、含非数字字符或后缀长度不在1–16时也明确拒绝；③ 默认SN前缀改为`12345678`、默认后缀长度保持8，默认生成恰好16位，合计小于16位的有效纯数字配置仍允许生成；④ 界面字段改为“SN 前缀（纯数字）”和“SN 随机后缀长度（总长≤16）”，成功日志同步说明SN与XPON SN两套规则；⑤ 增加纯数字、16位默认值、短配置、同批唯一、非数字和17位越界回归，并加入强制基线；XPON SN固定12位规则、MAC和SSID已验收行为保持不变。
- 修改文件：`.claude/plans/sample_parameter_sn_format.md`、`Cheating_machine_execution_tool/src/core/sample_parameter_table.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_table.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p "test_sample_parameter_table.py"`、`python -m unittest discover -s tests -p "test_app.py"`、`python scripts/verify_baseline.py`和`git diff --check`。
- 验证结果：参数表9项、主界面124项专项测试通过；强制基线全绿（52个当前主程序`.py`编译、编译清单完整、593项单测、108个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows源码版使用默认值生成并核对`SN`列为16位纯数字；分别输入非数字前缀、前缀与后缀合计17位确认错误提示，再使用合计小于16位的纯数字配置确认正常生成。现场结论由项目负责人提供后更新验收状态。

## 2026-08-13 - 固定批量参数表XPON SN格式

- 类型：功能 / 优化 / UI / 测试 / 文档
- 背景：项目负责人要求“写样机参数 → 生成批量参数表”的XPON SN固定为12位，且后8位必须使用十六进制形式；最初口述为SN，随后明确纠正为XPON SN。
- 完成内容：① XPON SN改为严格4位可编辑前缀（默认`XPON`）加8位唯一大写十六进制后缀（仅`0-9/A-F`），同批保持唯一，前缀非4位时明确拒绝；② 为兼容既有参数表和写参流程，生成结果继续写入`GPON SN`列；③ 普通SN恢复并保留原有可编辑前缀（默认`TESTSN`）和1–32位可调随机后缀，不受XPON SN固定规则影响；④ 生成窗口字段改为“XPON SN 前缀（固定 4 位）”和“SN 随机后缀长度”，成功、生成失败和保存失败继续写入主执行日志；⑤ 新增长度、字符集、同批唯一性、非法前缀、普通SN独立后缀长度及UI接线回归，并纳入强制基线。
- 修改文件：`.claude/plans/sample_parameter_sn_format.md`、`Cheating_machine_execution_tool/src/core/sample_parameter_table.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_table.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行参数表与主界面专项`unittest`、`python scripts/verify_baseline.py`和`git diff --check`。
- 验证结果：参数表7项、主界面124项专项测试通过；强制基线全绿（52个当前主程序`.py`编译、编译清单完整、591项单测、106个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows源码版打开生成窗口，使用4位与非4位XPON SN前缀分别生成；核对导出表`GPON SN`列为12位、后8位仅大写十六进制且同批唯一，非4位前缀被明确拒绝，同时普通SN后缀长度仍可独立调整。现场结论由项目负责人提供后更新验收状态。

## 2026-08-13 - 验收通道COM与串口日志联动

- 类型：真实样机验收 / 状态更新
- 背景：项目负责人完成新增“通道对应 COM口”以及串口日志使用用户实际选择COM的现场复验，并明确反馈“验收OK”。
- 完成内容：① 将通道COM分组候选、逐通道选择、实时保存和旧配置兼容从待确认更新为已确认验收；② 将串口日志按通道实际选择COM打开及Tab映射更新为已确认验收；③ 保留写参、全包升级、全流程串口日志和升级附加日志共用同一显式COM优先边界。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：由项目负责人在Windows源码版选择通道COM并打开串口日志，现场核对分组候选、配置保持和实际打开串口。
- 验证结果：项目负责人确认验收通过（2026-08-13）；本轮仅更新验收状态，未修改程序代码。
- 后续待办：无；后续串口映射改动必须继续通过通道COM持久化、升级和串口日志强制基线。

## 2026-08-13 - 增加通道对应COM口选择

- 类型：功能 / UI / 配置 / 串口 / 回归测试 / 文档
- 背景：项目负责人要求主界面通道配置表增加“通道对应COM口”选择列，并像VLAN候选一样按程控电源分组；随后明确要求串口日志实际打开用户为通道选择的COM口。
- 完成内容：① 新增程控电源到样机串口的每组8口候选：`COM101 → COM1–COM8`、`COM102 → COM9–COM16`，后续按当前六组顺延，程控电源为空时展示`COM1–COM48`；② 通道表增加“通道对应 COM口”只读下拉列，切换程控电源只刷新VLAN/COM候选，不清空已保存值，选择后写入`network_card_ip.ini`各通道`serial_port`并记录主日志；③ `ChannelConfigStore`兼容读写新字段，历史配置缺字段时不改写文件、运行期回退原`vlan{N} → COM{N-100}`；④ 写参目标预检、全包升级串口控制、手动串口日志、全流程“打开全部”和自动升级附加日志均优先使用用户实际选择，串口Tab标题与日志文件名同步实际COM；⑤ 新增候选分组、UI接线、配置往返、旧配置兼容、写参/日志目标、升级串口和附加日志回归，并加入强制基线。
- 修改文件：`.claude/plans/channel_serial_port_mapping.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/config_store.py`、`Cheating_machine_execution_tool/src/models/serial_models.py`、`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/src/ui/serial_terminal.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_channel_config.py`、`Cheating_machine_execution_tool/tests/test_serial_terminal.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行相关专项`unittest`、Windows源码界面探针、`python scripts/verify_baseline.py`与`git diff --check`。
- 验证结果：专项测试通过；Windows源码界面探针在当前`COM102`配置下确认候选严格为`COM9`–`COM16`，`channel_8/VLAN113`兼容显示`COM13`、`channel_9/VLAN112`兼容显示`COM12`，两个实际Combobox的候选和值一致；`python scripts/verify_baseline.py`全绿（52个当前主程序`.py`编译、编译清单完整、588项单测、103个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows主界面切换`COM101/COM102`核对两列候选，给通道选择一个不同于VLAN默认推导的COM，关闭重开后确认保持；分别打开手动串口日志、全流程串口日志和一次全包升级，确认Tab、实际串口及日志文件名全部一致。现场结论由项目负责人提供后更新验收状态。

## 2026-08-13 - 验收各功能入口居中显示

- 类型：Windows桌面验收 / 状态更新
- 背景：项目负责人完成各功能入口居中显示复验，并明确反馈“各个功能入口居中显示的需求OK了”。
- 完成内容：将主界面“检查并执行测试”“自动上/下电”“样机升级”“写样机参数”“ONU注册”“串口日志”“DUT配置”和“测试项配置”的相对主界面居中显示从待确认更新为已确认验收；保留DUT/测试项配置先居中后刷新、串口日志有效手动位置优先恢复等既有边界。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：由项目负责人从源码版逐入口打开窗口，现场确认居中显示效果。
- 验证结果：项目负责人确认需求验收通过（2026-08-13）；本轮只更新验收状态，未修改程序代码。
- 后续待办：无；后续窗口位置相关改动必须继续通过强制基线中的居中坐标与入口接线测试。

## 2026-08-13 - 优化复杂配置窗口加载速度

- 类型：性能优化 / UI / 回归测试 / 文档
- 背景：项目负责人反馈“DUT配置”和“测试项配置”虽然已解决透明客户区，但点击后的窗口加载仍有些慢。Windows源码计时显示首次点击回调约为测试项配置171.8ms、DUT配置89.5ms，其中弹出前的通用居中会同步刷新父子窗口布局，分别占约15ms和6ms；已验收客户区首次尺寸刷新原本最早在映射后120ms执行。
- 完成内容：① 通用居中函数增加可选目标宽高；测试项配置使用固定960×940，DUT配置使用本机状态恢复后的实际目标宽高直接计算位置，不再为获取复杂子窗口尺寸调用其`update_idletasks()`；父窗口已映射且尺寸有效时也不再重复刷新，只有父窗口仍为1px时才按原方式刷新后读取；其它普通窗口仍沿用实际尺寸优先的原居中逻辑；② 客户区尺寸刷新增加映射后20ms快速脉冲，同时完整保留120ms、360ms两次现场已验收兜底；③ 强化专项测试，校验快速刷新时机、三次几何恢复、已知尺寸路径不刷新父子窗口布局以及两个复杂窗口接线；④ 保持标准`Toplevel`生命周期、DUT状态高度空闲校正、复用刷新和窗口尺寸记忆不变。
- 修改文件：`.claude/plans/complex_window_load_performance.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/ui/window_paint.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_app.py`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p test_app.py`、Windows源码计时探针、`python scripts/verify_baseline.py`与`git diff --check`。
- 验证结果：主界面119项专项测试通过；同一Windows源码环境优化后首次点击回调为测试项配置154.4ms、DUT配置69.0ms，较优化前171.8ms/89.5ms分别缩短约10%/23%。按回调结束后首个尺寸脉冲计算，预计首轮强制刷新由约291.8ms/209.5ms提前到174.4ms/89.0ms；`python scripts/verify_baseline.py`全绿（52个当前主程序`.py`编译、编译清单完整、582项单测、98个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过），`git diff --check`无空白错误。
- 后续待办：从VS Code运行源码版，分别点击“测试项配置”和“DUT配置”，确认打开体感加快，同时客户区仍直接完整显示，无透明、闪烁、位置漂移或尺寸变化；现场结论由项目负责人提供后更新验收状态。

## 2026-08-12 - 统一功能窗口居中

- 类型：优化 / UI / 回归测试 / 文档
- 背景：项目负责人反馈主界面截图中的功能入口点击后，新窗口均默认出现在屏幕左上角，希望改为在屏幕中间弹出。
- 完成内容：① 在`src/ui/window_paint.py`新增相对父窗口实际屏幕坐标的通用居中函数，兼容主界面位于副屏的场景，并明确优先使用窗口已生效的实际尺寸、仅在实际尺寸仍为1px时回退控件期望尺寸；② 接入全流程执行、自动上/下电选择、样机升级、写样机参数、ONU注册、测试项配置和DUT配置首次创建路径；③ DUT和测试项配置先居中再执行已验收的客户区尺寸脉冲，避免刷新后回到左上角；④ 串口日志无历史位置或历史位置为`+0+0`时居中，用户主动移动后的其它有效历史位置继续恢复；⑤ 新增居中坐标、副屏坐标、实际尺寸优先、八个入口接线、自动上/下电移除硬编码位置估算及串口位置兼容回归，并加入强制基线。
- 修改文件：`.claude/plans/center_feature_windows.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/src/ui/window_paint.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/src/ui/serial_terminal.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_serial_terminal.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p "test_app.py" -v`、`python -m unittest discover -s tests -p "test_serial_terminal.py" -v`、`python -m unittest discover -s tests -p "test_pipeline_window.py" -v`、`python scripts\verify_baseline.py`与`git diff --check`。
- 验证结果：主界面119项、串口日志11项、全流程28项专项测试通过；Windows源码坐标探针确认写参、升级、ONU、测试项、DUT、全流程和串口日志窗口的`actual`均与按主界面计算的`expected`中心坐标完全一致；`python scripts\verify_baseline.py`全绿（52个当前主程序`.py`编译、编译清单完整、582项单测、98个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows桌面逐个点击截图中的八个功能入口，确认新窗口位于当前主界面中央；把主程序移动到副屏后再验证一次。现场结论由项目负责人提供后更新验收状态。

## 2026-08-12 - 验收复杂窗口首帧

- 类型：真实样机验收 / 状态更新
- 背景：项目负责人在Windows桌面复验映射后120ms/360ms的可恢复1像素客户区尺寸刷新，并明确反馈“可以了，验收OK”。
- 完成内容：① 将“测试项配置”客户区首帧从待确认更新为已确认验收；② 将“DUT配置”六个Tab客户区首帧从待确认更新为已确认验收；③ 固化验收边界为打开后直接完整显示、无需移动鼠标且窗口尺寸位置无异常。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：从VS Code运行源码版，分别打开“测试项配置”和“DUT配置”，观察Windows标题栏出现后客户区是否自动完整绘制，并确认无需移动鼠标触发。
- 验证结果：项目负责人现场确认两个窗口均显示正常，本问题验收通过（2026-08-12）；同版本此前已通过`python scripts\verify_baseline.py`（52个源码文件、579项单测、96个强制基线测试）。
- 后续待办：本透明客户区首帧问题无；DUT其它尚未验收的设备配置功能继续按各自待确认清单验收。

## 2026-08-12 - 修复复杂配置窗口透明首帧

- 类型：BUG 修复 / UI / Windows绘制 / 回归测试 / 文档
- 背景：项目负责人现场反馈“测试项配置”和“DUT配置”点击后只出现透明客户区，需要移动鼠标才完整显示；样机升级、写样机参数和ONU注册不受影响。透明预布局/原生重绘、Git提交`93b33aae`历史隐藏构建以及仅改标准`Toplevel`生命周期均经现场复验确认无效；最新照片明确显示原生标题栏已绘制、Tk客户区未完成首帧提交。
- 完成内容：① 使用源码探针确认两窗口无`WS_EX_LAYERED`、DWM未cloaked，原生客户区尺寸分别为960×940和1598×880，并抓取到300ms后的完整客户区像素，排除真实透明属性和控件构建失败；② 保留标准`Toplevel`生命周期，在映射后的120ms和360ms分别执行一次1像素宽度脉冲，通过Windows`WM_SIZE/WM_PAINT`强制整棵子控件树重新布局和提交，随后立即恢复原尺寸与位置；③ 首次创建和复用显示均接入，主日志分别输出`[测试项配置]/[DUT配置] 已触发客户区首帧尺寸刷新`，便于确认当前源码已运行；④ DUT状态高度继续在空闲阶段校正，尺寸脉冲不改变窗口尺寸记忆；⑤ 新增两次刷新时机、几何脉冲/恢复、只记录一次及两个窗口接线回归，并加入强制基线。
- 修改文件：`.claude/plans/window_first_paint_reliability.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/ui/window_paint.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p "test_app.py" -v`、`python scripts\verify_baseline.py`与`git diff --check`。
- 验证结果：主界面117项专项测试通过；Windows源码探针确认两次脉冲后测试项配置保持`960x940+0+0`、DUT保持`1598x880+0+0`；`python scripts\verify_baseline.py`全绿（52个当前主程序`.py`编译、编译清单完整、579项单测、96个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。自动化与像素探针不能替代项目负责人照片所示客户区首帧的现场验收。
- 后续待办：Windows桌面连续多次首次打开及复用显示“测试项配置”“DUT配置”，确认窗口直接完整显示、无透明客户区且无需移动鼠标；现场结论由项目负责人提供后再更新验收状态。

## 2026-08-09 - 增加DUT窗口宽高记忆

- 类型：功能 / DUT配置 / UI状态 / 回归测试 / 文档
- 背景：DUT配置已经可以记忆六个Tab的当前状态高度，但窗口本身每次打开仍使用固定宽高；项目负责人要求同时保持上次关闭时的窗口宽度和高度。
- 完成内容：① 在现有`~/.aouxue_dut_config.json`增加`window_size.width/height`，窗口构建时先读取并恢复宽高，关闭前读取实际尺寸并原子保存；② 保持最小尺寸1530×880，历史值超过当前屏幕时按当前屏幕收敛，缺失、损坏或非法值回退默认1530×880；③ 重构本机UI状态写入为“读取现有JSON后合并字段”，拖动状态区或保存窗口尺寸均不会覆盖另一类状态；④ 增加尺寸往返、跨屏幕收敛、非法回退、状态高度兼容及构建/销毁调用回归，并纳入强制基线。
- 修改文件：`.claude/plans/dut_window_size_persistence.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p "test_app.py" -v`、`python scripts\verify_baseline.py`与`git diff --check`。
- 验证结果：主界面117项专项测试通过；`python scripts\verify_baseline.py`全绿（51个当前主程序`.py`编译、编译清单完整、579项单测、94个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows桌面调整DUT配置窗口宽高并关闭，重新打开确认恢复上次尺寸；更换分辨率或显示器后确认窗口自动收敛且底部提示和按钮仍完整显示。现场结论由项目负责人提供后再更新验收状态。

## 2026-08-09 - 保护DUT底部操作按钮

- 类型：BUG修复 / DUT配置 / UI布局 / 回归测试 / 文档
- 背景：DUT配置六个Tab的“当前状态”虽然已有2–16行固定范围，但不同Tab的表单高度不同，向下拖动过多仍可能把底部“刷新/查询/停止/执行/关闭”按钮裁切或完全遮挡。
- 完成内容：① 首版事后测量在真实Tk布局中仍可能先压缩后创建的按钮栏；现将Telnet及其余五个Tab的“已加载 N 台目标 DUT”提示和操作栏组成统一底部区域，按`side=bottom`放到Tab布局队列首位，先预留提示行与按钮的完整请求高度，再让状态区和目标表格使用剩余空间；② 拖动时仍在2–16行范围内逐级检查当前Tab、窗口、底部区域及按钮栏边界，并要求两层实际高度均不小于请求高度，继续增高会遮挡或压缩提示/按钮时自动停在最后一个安全高度；③ 窗口首次显示、再次显示和Tab切换后重新校正当前页，自动保存有效高度；④ 回归锁定Telnet独立底部区、其余五页共用底部区均使用底部优先布局，并覆盖请求16行但只能安全容纳10行、按钮栏被压缩和底部提示区被压缩三类边界。
- 修改文件：`.claude/plans/dut_current_status_height.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p "test_app.py" -v`、`python scripts\verify_baseline.py`与`git diff --check`。
- 验证结果：主界面116项专项测试通过；`python scripts\verify_baseline.py`全绿（51个当前主程序`.py`编译、编译清单完整、578项单测、93个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows桌面逐页向下拖动Telnet、WAN、2.4G WiFi、5G WiFi、语音和TR069当前状态区，确认达到安全上限后停止且“已加载 N 台目标 DUT”提示与整排底部按钮均完整可见；关闭重开并逐页切换，确认历史高度恢复后仍不会遮挡底部区域。现场结论由项目负责人提供后再更新验收状态。

## 2026-08-09 - 增加DUT状态区高度记忆

- 类型：功能 / DUT配置 / UI状态 / 回归测试 / 文档
- 背景：DUT配置六个Tab的“当前状态”文本区固定为4行，内容较多时只能依赖滚动条，操作员无法按现场需要扩大显示区；项目负责人要求开放高度调整，并在再次打开DUT配置窗口时恢复上次关闭的高度。
- 完成内容：① 统一`_build_current_status_area()`在六页当前状态区底部增加“↕ 拖动调整当前状态高度”调节条，按住上下拖动即可改变文本显示行数；② 每个Tab独立记忆高度，范围收敛为2–16行，避免缩到不可用或挤占整页；③ 新增本机状态文件`~/.aouxue_dut_config.json`，窗口构建时加载，拖动结束和窗口销毁时原子保存；④ 文件不存在、JSON损坏、未知字段、非法值和越界值均安全忽略或收敛，不影响窗口打开/关闭和DUT业务；⑤ 增加状态往返、异常回退、范围限制、逐Tab独立记忆和拖动持久化回归，并加入强制基线。
- 修改文件：`.claude/plans/dut_current_status_height.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行`python -m unittest discover -s tests -p "test_app.py" -v`、`python scripts\verify_baseline.py`与`git diff --check`。
- 验证结果：主界面115项专项测试通过；`python scripts\verify_baseline.py`全绿（51个当前主程序`.py`编译、编译清单完整、577项单测、92个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows桌面分别拖动Telnet、WAN、2.4G WiFi、5G WiFi、语音、TR069当前状态区，确认上下拖动手感、2–16行边界和目标表格让位；关闭并重开DUT配置窗口，确认六页分别恢复各自高度。现场结论由项目负责人提供后再更新验收状态。

## 2026-08-09 - 增加DUT 2.4G与5G WiFi配置

- 类型：功能 / DUT配置 / WiFi / UBUS / 查询回填 / 回归测试 / 文档
- 背景：DUT配置已有Telnet、WAN、语音和TR069，但无法直接查询或批量修改ONT的2.4G/5G无线参数。项目负责人要求增加两个独立WiFi Tab，并覆盖名称、密码、信道、带宽、双频合一、启用/隐藏、加密、协议、功率及实际常用扩展项。
- 完成内容：① Notebook增加“2.4G WiFi配置”“5G WiFi配置”，表单覆盖SSID索引、名称、密码、信道、带宽、启用、隐藏、认证/加密模式、协议类型、发射功率、最大接入数、WMM和双频合一；② 2.4G/5G分别使用自己的信道、带宽和协议候选值，开放模式隐藏且不下发密码，加密模式校验8–63字符或64位十六进制密钥，所有开关继续使用原生勾号；③ 新增独立WiFi core，先读取`X_SDMC_Mapping_2G/5G`和Radio/AP/SSID节点，将Mapping列表位置转换为真实`X_SDMC_Instance`路径，再查询SSID/AP/Security/Radio与双频状态；④ 配置按真实路径一次多路径set并回读校验，双频合一同步两个频段对应SSID的名称、启用/隐藏、认证密码、最大接入数和WMM，Radio信道/带宽/协议/功率只修改当前Tab；⑤ 两页接入现有网卡按需准备、锁源UBUS、1–8并行、停止、失败隔离与session注销，查询逐台展示，只有全部目标成功且状态完全一致才同步表单；⑥ 主执行日志输出Mapping与节点实际get、解析路径、完整set paths、回读、成功/跳过/失败和批次汇总；⑦ 增加Mapping解析、只读查询、双频合一、开放密码隔离、字段校验、service分发、状态查询和UI映射回归并纳入强制基线。
- 修改文件：`.claude/plans/dut_wifi_tabs.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/models/dut_config_models.py`、`Cheating_machine_execution_tool/src/models/__init__.py`、`Cheating_machine_execution_tool/src/core/dut_wifi_config.py`、`Cheating_machine_execution_tool/src/services/dut_advanced_config_service.py`、`Cheating_machine_execution_tool/src/services/dut_status_query_service.py`、`Cheating_machine_execution_tool/src/services/__init__.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_dut_wifi_config.py`、`Cheating_machine_execution_tool/tests/test_dut_advanced_config_service.py`、`Cheating_machine_execution_tool/tests/test_dut_status_query_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行DUT WiFi core、DUT配置/查询service和主界面专项测试，再执行`python scripts\verify_baseline.py`与`git diff --check`。
- 验证结果：DUT相关专项51项、主界面113项通过；`python scripts\verify_baseline.py`全绿（51个当前主程序`.py`编译、编译清单完整、575项单测、90个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows桌面目视两个WiFi页完整布局、下拉框和8个新增勾选框；真实ONT分别查询2.4G/5G主SSID，核对Mapping实际实例、所有字段回填、开放/加密、隐藏、信道/带宽/协议/功率下发回读；再开启双频合一，确认SSID/AP安全参数同步且两个Radio配置不互相覆盖，并覆盖连续查询、1/8台并行、停止和单台失败隔离。现场结论由项目负责人提供后再更新验收状态。

## 2026-08-09 - 补齐Telnet与WAN状态展示

- 类型：功能
- 背景：语音和TR069页已有只读查询及当前状态区，Telnet和WAN页尚未统一。项目负责人要求Telnet配置和WAN配置Tab也增加当前状态展示。
- 完成内容：① 增加Telnet只读状态模型和core查询，读取AccessCtrl总开关、LAN Telnet规则并锁源探测TCP 23，端口关闭作为状态展示而非查询异常，全流程不执行set/add；② 扩展统一状态查询service支持Telnet的网卡预检、锁源登录、重试、session注销、并行、停止和失败隔离；③ Telnet页增加“查询当前Telnet”和逐台当前状态区；④ WAN页增加当前状态区，直接展示现有WAN查询同批结果中的连接名、模式、业务类型和VLAN，不重复查询；⑤ 四页状态在目标变化或对应配置后失效；⑥ 增加Telnet只读边界、service注销和Telnet/WAN UI展示回归并纳入强制基线。
- 修改文件：`.claude/plans/dut_telnet_wan_current_status.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/models/dut_config_models.py`、`Cheating_machine_execution_tool/src/models/__init__.py`、`Cheating_machine_execution_tool/src/core/ubus_enable_telnet.py`、`Cheating_machine_execution_tool/src/services/dut_status_query_service.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_ubus_enable_telnet.py`、`Cheating_machine_execution_tool/tests/test_dut_status_query_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行Telnet UBUS、状态查询service和主界面专项测试，再执行 `python -m unittest discover -s tests`、`python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：Telnet UBUS 19项、状态查询service 6项、主界面112项专项测试通过；全量568项单测通过；`python scripts/verify_baseline.py` 全绿（50个当前主程序`.py`编译、编译清单完整、568项单测、85个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows桌面确认Telnet/WAN当前状态区布局；真实ONT验证Telnet总开关/规则/TCP23组合、WAN连接摘要、连续查询、1/8台并行、Access denied、停止和单台失败隔离。现场结论由项目负责人提供后再更新验收状态。

## 2026-08-09 - 增加语音TR069状态查询

- 类型：功能
- 背景：DUT配置的语音和TR069页只有配置下发及配置后回读，操作员无法在执行前独立查询ONT当前参数。项目负责人要求两个Tab都增加查询当前状态并展示当前状态的能力。
- 完成内容：① core增加指定SIP线路的账号、服务器、DTMF、SIP模式、DigitMap、5项编码及ManagementServer完整只读解析，兼容直接字段、对象嵌套和实例列表返回；② 新增统一状态查询service，复用网卡状态预检、源IP可绑等待、锁源UBUS、1–8并行、登录/查询整体重试、停止/失败隔离和设备session注销；③ 语音、TR069页分别增加“查询当前语音”“查询当前TR069”按钮和“当前状态”逐台展示区；④ 单台或全部目标参数一致时同步当前表单，多台不一致或失败时不使用任意一台覆盖；TR069手动Inform动作不参与查询回填；⑤ 目标变化和对应配置执行后使旧状态失效，主日志记录实际get路径、完整状态、成功/失败、注销和批次汇总；⑥ 增加只读命令、字段映射、连续查询注销、多台一致性、停止和UI安全回填回归并纳入强制基线。
- 修改文件：`.claude/plans/dut_voice_tr069_status_query.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/models/dut_config_models.py`、`Cheating_machine_execution_tool/src/models/__init__.py`、`Cheating_machine_execution_tool/src/core/dut_ubus_config.py`、`Cheating_machine_execution_tool/src/services/dut_status_query_service.py`、`Cheating_machine_execution_tool/src/services/__init__.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_dut_ubus_config.py`、`Cheating_machine_execution_tool/tests/test_dut_status_query_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行语音/TR069 UBUS、状态查询service、DUT高级配置、WAN查询和主界面专项测试，再执行 `python -m unittest discover -s tests`、`python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：UBUS配置13项、状态查询service 5项、DUT高级配置11项、WAN查询5项、主界面111项专项测试通过；全量565项单测通过；`python scripts/verify_baseline.py` 全绿（50个当前主程序`.py`编译、编译清单完整、565项单测、82个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows桌面确认两个查询按钮、当前状态区滚动展示和表单回填布局；真实ONT分别验证SIP/IMSSIP线路字段、ManagementServer返回字段、密码是否明文可读、连续两次查询、1/8台并行、多台参数不一致、Access denied、停止及查询后再配置。现场结论由项目负责人提供后再更新验收状态。

## 2026-08-09 - 增加IMSSIP模式

- 类型：修改
- 背景：ONT Web的SIP模式支持 `IMSSIP`，工具原下拉只有 `SIP/UDP/TCP/TLS`。项目负责人明确要求保留现有模式并在此基础上增加ONT支持的IMSSIP。
- 完成内容：① 语音service增加统一 `VOICE_SIP_MODE_OPTIONS`，顺序为 `SIP/IMSSIP/UDP/TCP/TLS`；② 语音Tab的“SIP 模式”下拉改为复用该唯一选项源，默认值仍为SIP；③ service增加二次校验，5个已知模式均允许，未知值在设备操作前拒绝；④ 底层继续把选择值原样写入 `Device.Services.VoiceService.1.SIP.X_SDMC_SIPMode`，未改变服务器、账号、编码、DigitMap和回读流程；⑤ 增加IMSSIP实际set参数、现有模式保留、未知值拒绝和UI选项回归并纳入强制基线。
- 修改文件：`.claude/plans/dut_voice_sip_mode_options.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/src/services/dut_advanced_config_service.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_dut_advanced_config_service.py`、`Cheating_machine_execution_tool/tests/test_dut_ubus_config.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录分别执行主界面、DUT高级配置service和UBUS配置专项测试，再执行 `python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：主界面109项、DUT高级配置service 11项、UBUS配置11项专项测试通过；`python scripts/verify_baseline.py` 全绿（49个当前主程序`.py`编译、编译清单完整、556项单测、75个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows桌面确认SIP模式下拉依次显示SIP、IMSSIP、UDP、TCP、TLS；真实样机选择IMSSIP执行，确认主日志实际set参数及SIP路径回读均符合ONT。现场结论由项目负责人提供后再更新验收状态。

## 2026-08-09 - 改用LAN端口多选

- 类型：优化
- 背景：WAN查询到ONT Web绑定LAN4时，工具显示原始位掩码8，协议值正确但操作员不易直观看出实际端口。项目负责人要求改为LAN端口多选，并提出兼容不止4个LAN口的设备。
- 完成内容：① WAN页“端口绑定位掩码”文本框替换为两行LAN1–LAN8原生勾选框；② LAN1–LAN8分别映射1、2、4、8、16、32、64、128，多选自动按位合并，底层 `DutWanSettings.port_bind` 与UBUS `PortBind` 协议保持不变；③ 查询现有WAN时把位掩码反向勾选，例如8只勾LAN4、129勾LAN1和LAN8；④ bridge未选择时继续默认LAN1；⑤ 修改现有WAN时保留WiFi等界面未展示的非LAN旧位，切换新增时清除这些不可见旧位，避免误带入新连接；⑥ LAN端口和既有DUT选择项全部继续使用原生勾选框，选中显示“✓”；⑦ 增加位掩码双向映射、1–8口、多选及非LAN位保留回归并纳入强制基线。
- 修改文件：`.claude/plans/dut_wan_lan_port_multiselect.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p test_app.py`、`python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：主界面108项专项测试通过；`python scripts/verify_baseline.py` 全绿（49个当前主程序`.py`编译、编译清单完整、554项单测、72个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows桌面确认LAN1–LAN8两行布局和勾号外观；真实样机查询LAN4绑定确认仅LAN4勾选，分别验证LAN1+LAN4下发9、LAN5–LAN8位掩码、bridge默认LAN1及修改现有含非LAN绑定的WAN。现场结论由项目负责人提供后再更新验收状态。

## 2026-08-09 - 增加IPTV组播VLAN

- 类型：功能
- 背景：DUT配置的WAN页已经支持IPTV业务，但新增/修改时缺少IPTV涉及的组播VLAN参数，也无法从现有IPTV WAN快照回填该字段。项目负责人要求补齐该业务规则。
- 完成内容：① WAN设置模型和现有连接快照增加 `multicast_vlan_id`；② 业务类型为IPTV时，路由和桥接表单均显示可选“组播 VLAN ID”，留空表示不单独配置，填写时service二次校验1–4094；③ 新增/修改IPTV时以整数 `MulticastVLANID` 写入完整UBUS payload，非IPTV即使残留旧值也保持空值、不误下发；④ 现有WAN查询兼容解析 `X_SDMC_Multicast_VLANID`、`X_SDMC_MulticastVLANID` 等设备字段并同步回填，查询摘要日志增加组播VLAN；⑤ 增加路由/桥接下发、可选值与非法值校验、非IPTV隔离、查询解析、UI显隐和表单映射回归，纳入强制基线。
- 修改文件：`.claude/plans/dut_wan_iptv_multicast_vlan.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/src/models/dut_config_models.py`、`Cheating_machine_execution_tool/src/core/dut_ubus_config.py`、`Cheating_machine_execution_tool/src/services/dut_advanced_config_service.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_dut_ubus_config.py`、`Cheating_machine_execution_tool/tests/test_dut_advanced_config_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录分别执行WAN core、DUT高级配置service、主界面专项测试，再执行 `python scripts/verify_baseline.py` 与 `git diff --check`。
- 验证结果：WAN core 11项、DUT高级配置service 10项、主界面107项专项测试通过；`python scripts/verify_baseline.py` 全绿（49个当前主程序`.py`编译、编译清单完整、553项单测、71个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows桌面选择IPTV，确认路由/桥接均显示组播VLAN且非IPTV立即隐藏；真实样机分别验证留空、填写有效值、查询现有IPTV回填，以及主日志实际 `MulticastVLANID` payload。现场结论由项目负责人提供后再更新验收状态。

## 2026-08-09 - 统一DUT字段名称左对齐

- 类型：修改
- 背景：DUT配置的WAN页字段名称在各自网格单元内采用右对齐，操作、现有连接、业务VLAN、接入方式和IP协议等标签视觉起点不一致；项目负责人要求四个Tab的内容名称统一向左对齐。
- 完成内容：① 公共 `_field()` 创建的所有字段标签统一设置 `anchor="w"` 与 `sticky="w"`，一次覆盖WAN、语音、TR069的普通字段和语音编码字段；② 单独创建的WAN“现有连接名/索引”标签同步左对齐；③ Telnet页原有标签已经按左侧顺序排列，复选框也已使用 `sticky="w"`，保持不变；④ 输入框、下拉框、字段显隐、复选框状态和业务执行逻辑均未改动；⑤ 新增整窗源码回归，禁止字段标签恢复 `sticky="e"` / `anchor="e"`，并纳入强制基线。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行字段左对齐专项测试、`python scripts\verify_baseline.py` 与 `git diff --check`。
- 验证结果：字段左对齐专项测试通过；`python scripts\verify_baseline.py` 全绿（49个当前主程序`.py`编译、编译清单完整、549项单测、67个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows桌面打开Telnet、WAN、语音、TR069四页，目视确认所有字段名称左边缘一致，重点确认WAN首行和980×680最小窗口未发生遮挡。

## 2026-08-09 - DUT WAN查询完整信息回填

- 类型：功能完善 / WAN查询 / 界面联动
- 背景：真实样机已能查询到 `3_INTERNET_R_VID_172` 等现有 WAN 名称，但下拉选中后表单仍保留新增页的 TR069、VLAN 46 等旧值。项目负责人要求把查询到的现有 WAN 完整信息同步展示到当前 WAN 表单。
- 完成内容：① WAN只读查询从单一路径连接名扩展为一次多路径 `bbfdm.get`，覆盖IP Interface、Ethernet/VLAN、PPP、Bridge、DHCPv4/v6、DNS和NAT，不导入旧 `SdmcUbusLib`共享Session；② 新增现有WAN快照模型，解析连接索引、业务类型、VLAN/优先级、路由/桥接、端口绑定位掩码、IPoE/PPPoE、IPv4/IPv6/双栈、动态/静态、MTU、NAT、静态地址/网关/DNS和PPPoE凭据，设备字段缺失时仅对连接名中明确编码的索引/业务/模式/VLAN作安全回退；③ 查询下拉默认选择第一项，切换任一连接立即替换当前表单并清空上一连接遗留的地址/PPPoE文本，继续复用既有字段显隐和WAN规则；④ 单台直接回填完整快照，多台仍只显示名称完全一致的共同WAN，并且只有所有目标的完整快照也一致时才自动回填；参数不同则保留名称供删除选择，修改前明确提示人工核对；⑤ 主日志记录实际多路径查询和每条WAN的业务/VLAN/模式/接入摘要；⑥ 增加IPoE IPv4、PPPoE双栈静态、批量详情一致性、表单映射和旧值清理回归，全部纳入强制基线。
- 修改文件：`.claude/plans/dut_wan_detail_prefill.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/core/dut_ubus_config.py`、`Cheating_machine_execution_tool/src/models/dut_config_models.py`、`Cheating_machine_execution_tool/src/models/__init__.py`、`Cheating_machine_execution_tool/src/services/dut_wan_query_service.py`、`Cheating_machine_execution_tool/src/services/__init__.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_dut_ubus_config.py`、`Cheating_machine_execution_tool/tests/test_dut_wan_query_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行WAN core、查询service、主界面专项测试，再执行 `python scripts\verify_baseline.py` 与 `git diff --check`。
- 验证结果：`python scripts\verify_baseline.py` 全绿（49个当前主程序`.py`编译、编译清单完整、548项单测、66个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：真实样机重新查询 `3_INTERNET_R_VID_172`，确认业务类型为INTERNET、VLAN为172且其余设备字段正确；依次切换IPoE/PPPoE、桥接、IPv6/双栈、静态地址连接，确认旧字段被替换/清空；多台场景覆盖同名同参数自动回填与同名不同参数不回填。现场结论由项目负责人提供后再更新验收状态。

## 2026-08-09 - 释放DUT UBUS会话

- 类型：BUG 修复
- 背景：真实样机同一通道第一次“查询现有 WAN”成功，第二次 `session.login` 虽成功，但 `bbfdm.get Device.IP.Interface.` 连续返回 `Access denied`。日志表明第一轮只关闭了本机HTTP连接，未释放设备端UBUS session。
- 完成内容：① `UbusHttpClient` 记录成功登录的session并新增 `logout()`，按项目协议参考下发 `bbfdm.unauthenticated_operate command=Device.X_SDMC_Login.logout()` 和当前 `SessionId`；② `close()` 对仍存在的session执行best-effort注销后再关闭本机连接，使DUT Telnet、高级配置和写参前置等共用调用也不会继续积累会话；③ WAN查询每次成功、失败或重试结束前显式注销，主日志记录注销TX、成功或可忽略失败；④ 注销失败不覆盖原查询结果，但本机连接仍会关闭；⑤ 新增设备只允许一个活动session的连续两次查询回归，并将显式注销、关闭兜底和连续查询纳入强制基线。
- 修改文件：`.claude/plans/dut_ubus_session_cleanup.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/src/core/ubus_http_client.py`、`Cheating_machine_execution_tool/src/services/dut_wan_query_service.py`、`Cheating_machine_execution_tool/tests/test_ubus_http_client.py`、`Cheating_machine_execution_tool/tests/test_dut_wan_query_service.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行UBUS客户端、WAN查询service、DUT service和写参应用专项测试，再执行 `python scripts\verify_baseline.py` 与 `git diff --check`。
- 验证结果：UBUS客户端15项、WAN查询service4项、DUT service23项、写参应用16项专项测试通过；`python scripts\verify_baseline.py` 全绿（49个当前主程序`.py`编译、编译清单完整、543项单测、61个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：真实样机对同一DUT连续点击至少两次“查询现有 WAN”，确认两次均成功，每轮均出现注销TX和“UBUS 会话已注销”，不再出现第二次 `Access denied`；通过后再更新验收状态。

## 2026-08-09 - 公共网卡准备按需复用

- 类型：性能优化 / 公共网络准备
- 背景：DUT WAN 等配置以及线路检查、升级、写参等多个流程都会重复启用目标 VLAN 网卡、重设相同静态 IP 并等待稳定，即使网卡已经满足要求也不例外。项目负责人要求统一先查询当前配置，满足时直接使用。
- 完成内容：① 公共网络准备能力新增可选只读预检，通过 `Get-NetAdapter` 与 `Get-NetIPAddress` 一次获取目标网卡启用状态、IPv4 和前缀；② 已启用且目标地址/前缀完全匹配时跳过启用、静态 IP 设置和两次稳定等待；③ 已启用但地址不符时只设置 IP，禁用但地址已正确时只启用，其余不满足项按需修复；④ 查询失败、无结果或解析失败时回退原完整启用和静态 IP 设置流程；⑤ 线路检查、页面升级、全包升级 TFTP 网卡、写参用户/工厂模式切网、测试项执行、DUT Telnet/WAN/语音/TR069 配置与“查询现有 WAN”全部开启复用；⑥ TFTP、写参和 DUT 等原有源 IP 可绑定确认保持不变，Ping、HTTP/UBUS、Telnet、TFTP 后续成功判据不变；⑦ TFTP 独立准备改为复用公共能力，但 `Tftp指令` 与 `Tftp Put` 两条传输链路不合并；⑧ 主执行日志明确输出检查、复用、跳过、修复或回退结果，并将各生产调用路径纳入强制基线。
- 修改文件：`.claude/plans/dut_network_prepare_reuse.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/src/services/test_item_execution_service.py`、`Cheating_machine_execution_tool/src/services/dut_config_service.py`、`Cheating_machine_execution_tool/src/services/dut_advanced_config_service.py`、`Cheating_machine_execution_tool/src/services/dut_wan_query_service.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_page_upgrade.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_app.py`、`Cheating_machine_execution_tool/tests/test_test_item_execution_service.py`、`Cheating_machine_execution_tool/tests/test_dut_config_service.py`、`Cheating_machine_execution_tool/tests/test_dut_advanced_config_service.py`、`Cheating_machine_execution_tool/tests/test_dut_wan_query_service.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行网络准备、全包升级、页面升级、写参、测试项执行及 DUT service 专项测试，再执行 `python scripts\verify_baseline.py` 与 `git diff --check`。
- 验证结果：上述专项共125项通过；`python scripts\verify_baseline.py` 全绿（49个当前主程序`.py`编译、编译清单完整、540项单测、58个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows 管理员环境分别验证网卡已完全满足、已启用但地址不符、禁用但地址正确、状态读取失败四类日志与实际耗时；真实样机依次回归线路 Ping、页面升级、`Tftp指令`、`Tftp Put`、写参用户/工厂模式切网、测试项执行及 DUT UBUS/WAN 查询与配置。真实样机结论由项目负责人提供后再更新验收状态。

## 2026-08-09 - 增加现有WAN查询下拉

- 类型：功能
- 背景：WAN修改/删除原来要求操作员手工填写现有连接名或索引。项目负责人要求查询到现有WAN后以下拉列表展示，降低索引输入和误操作风险。
- 完成内容：① “现有连接名/索引”改为只读Combobox，并在旁边增加“查询现有 WAN”按钮；② 新增只读 `bbfdm.get Device.IP.Interface.` 协议解析，过滤LAN、透传和非数字前缀接口，按WAN数字索引排序；③ 新增独立查询service，每台仍执行网络准备、等待源IP可绑、独立锁源UBUS登录重试、查询、关闭client，支持1–8并行、停止和失败隔离；④ 单台显示本机连接，多台只展示所有目标名称完全一致的共同WAN，不按相同数字索引合并不同业务；⑤ 任一目标失败/停止不生成下拉列表，目标集合变化或执行WAN配置后清空旧列表；⑥ 主执行日志记录明文login、实际get路径、每台连接列表和共同连接汇总；⑦ 新增core、service、UI主线程回收和批量安全边界回归并纳入强制基线。
- 修改文件：`.claude/plans/dut_wan_connection_query.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/core/dut_ubus_config.py`、`Cheating_machine_execution_tool/src/models/dut_config_models.py`、`Cheating_machine_execution_tool/src/models/__init__.py`、`Cheating_machine_execution_tool/src/services/dut_wan_query_service.py`、`Cheating_machine_execution_tool/src/services/__init__.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_dut_ubus_config.py`、`Cheating_machine_execution_tool/tests/test_dut_wan_query_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行WAN core、查询service和主界面专项测试，再执行`python scripts/verify_baseline.py`与`git diff --check`。
- 验证结果：WAN core专项7项、查询service专项3项、主界面专项103项通过；`python scripts/verify_baseline.py`全绿（49个当前主程序`.py`编译、编译清单完整、536项单测、51个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows桌面和真实样机确认单台/多台查询响应结构、只读下拉宽度、共同连接展示、查询失败与目标变化清空，以及选择后修改/删除正确连接。真实样机结论由项目负责人提供后再更新验收状态。

## 2026-08-09 - WAN配置按真实新建规则联动展示

- 类型：功能完善 / WAN配置 / 界面联动 / 预检
- 背景：WAN配置原先固定展示所有字段，选择IPoE仍显示PPPoE账号密码，动态地址仍显示静态地址项，MTU和双栈组合也未随接入协议收敛。项目负责人要求严格按实际新建WAN规则展示和约束。
- 完成内容：① 新增纯表单规则和地址组合收敛函数，操作、路由/桥接、IPoE/PPPoE、IPv4/IPv6/双栈及动态/静态选择均实时联动字段显隐；② 新增隐藏索引、修改显示索引、删除仅保留索引；③ 桥接隐藏路由/IP字段，业务类型限定IPTV/INTERNET/OTHER，端口绑定为0时回填LAN1位掩码1；④ IPoE隐藏PPPoE凭据并回填MTU 1500，PPPoE显示凭据并回填MTU 1492，MTU仍允许按设备需要在有效范围调整；⑤ DHCP/SLAAC/DHCPv6隐藏静态地址项，静态才展示完整地址；⑥ IPoE双栈只允许DHCP+SLAAC、DHCP+DHCPv6、静态+静态，PPPoE只允许动态地址组合；⑦ service新增桥接业务类型、PPPoE静态IPv6和非法双栈组合二次预检；⑧ 表单下方显示当前组合说明并补充强制基线回归。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/src/services/dut_advanced_config_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_dut_advanced_config_service.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行主界面和DUT高级配置service专项测试、`python scripts/verify_baseline.py`、`git diff --check`。
- 验证结果：主界面专项101项、DUT高级配置service专项9项通过；`python scripts/verify_baseline.py`全绿（48个当前主程序`.py`编译、编译清单完整、530项单测、47个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows桌面逐项切换WAN操作、模式、接入方式、IP协议和地址方式，核对字段显隐、MTU及提示文案；真实样机覆盖允许组合的新增/修改/删除。真实样机结论由项目负责人提供后再更新验收状态。

## 2026-08-09 - 统一 DUT 选择框勾号显示

- 类型：BUG 修复
- 背景：DUT配置的WAN、语音和TR069页使用`ttk.Checkbutton`，当前Clam主题把选中态绘制为叉号，容易被操作员理解为错误或未启用。项目负责人要求所有DUT Tab选择框选中时显示勾号。
- 完成内容：① 新增统一原生选择框构造方法，使用白色选择区和标准Windows勾号；② 替换“启用 NAT”“启用 SIP 账号”“启用周期 Inform”“启用 HTTP 连接请求”“启用证书”“配置后手动 Inform”共6个选择框；③ 保持原BooleanVar、默认开关状态、禁用/恢复控制和配置执行语义不变；④ 增加静态回归，禁止DUT页重新使用Clam叉号样式。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行`python -m py_compile src\ui\dut_config_window.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python scripts\verify_baseline.py`、`git diff --check`。
- 验证结果：主界面专项99项通过；`python scripts/verify_baseline.py`全绿（48个当前主程序`.py`编译、编译清单完整、525项单测、44个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows桌面打开WAN、语音和TR069页，逐一勾选6个选择框，确认选中显示“✓”、未选为空框；该目视确认不由单元测试替代。

## 2026-08-09 - 扩展 DUT WAN语音TR069配置

- 类型：功能
- 背景：项目负责人要求在现有 DUT 配置 Notebook 中继续增加 WAN、语音和 TR069 Tab，并确认 WAN 首版必须包含静态 IPv4、IPv6、IPv4/IPv6 双栈以及修改、删除现有 WAN。
- 完成内容：① DUT 窗口扩展为 Telnet/WAN/语音/TR069 四个 Tab，共享主界面目标、明文 UBUS 凭据、1–8 并行、停止和失败隔离，同一时间只运行一个批次；② 新增每台独立、锁定 VLAN 源 IP 的高级 DUT service，统一执行网络准备、可绑定检查、UBUS 登录重试、功能下发、结果回收和 client 关闭；③ WAN 通过登录态 `Device.X_SDMC_CreateWAN()` 支持新增/修改/按明确索引删除、router/bridge、IPoE/PPPoE、IPv4/IPv6/IPv4+IPv6 双栈，IPv4 DHCP/静态和 IPv6 SLAAC/DHCPv6/静态，删除不提供全删或模糊匹配；④ 语音设置 SIP 基础、服务器、账号、5项编码和DigitMap并回读；⑤ TR069设置并回读ManagementServer，支持可选手动Inform及停止；⑥ 主日志输出明文login、实际UBUS method/path/input及逐台成功/跳过/失败和批次汇总；⑦ 增加payload、校验、单台流程、并行停止、UI分层与客户端operate/optional回归，并纳入强制基线。
- 修改文件：`.claude/plans/dut_config_wan_voice_tr069.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/core/dut_ubus_config.py`、`Cheating_machine_execution_tool/src/core/ubus_http_client.py`、`Cheating_machine_execution_tool/src/models/dut_config_models.py`、`Cheating_machine_execution_tool/src/models/__init__.py`、`Cheating_machine_execution_tool/src/services/dut_advanced_config_service.py`、`Cheating_machine_execution_tool/src/services/__init__.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_dut_advanced_config_service.py`、`Cheating_machine_execution_tool/tests/test_dut_ubus_config.py`、`Cheating_machine_execution_tool/tests/test_ubus_http_client.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行 DUT UBUS协议、高级service、HTTP客户端、原DUT Telnet和主界面专项单测，再执行 `python scripts/verify_baseline.py`、`git diff --check`。
- 验证结果：新增 DUT UBUS协议6项、高级service6项、HTTP客户端13项、原DUT Telnet service10项和主界面98项专项测试通过；`python scripts/verify_baseline.py` 全绿（48个当前主程序`.py`编译、编译清单完整、524项单测、43个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows桌面确认四个Tab在1180×780默认窗口及980×680最小窗口完整绘制；真实样机分别验证WAN新增/修改/删除和IPv4/IPv6/双栈组合、语音回读、TR069回读/手动Inform、1/8台并行、停止与单台失败隔离。真实样机结论由项目负责人提供后再更新验收状态。

## 2026-08-08 - 实现 DUT 批量开启 Telnet

- 类型：功能
- 背景：主界面“DUT配置”原来只有占位窗口。项目负责人要求参考写样机参数的 UBUS 能力，对主界面已勾选 DUT 批量开启 Telnet；随后确认 DUT 页未来还会增加其它功能，且项目密码无需保护、允许明文显示。
- 完成内容：① DUT 窗口改为可扩展 Notebook，首个 Tab 为“Telnet配置”，后续功能可追加独立 Tab；② 目标表展示通道/VLAN/网卡/PC IP/样机 IP/状态，账号密码与写参首次登录凭据共享且明文显示；③ 新增 DUT 请求/结果模型和独立 service，单台按“准备网络→等源 IP 可绑→UBUS AccessCtrl 开 Telnet→锁源验证 TCP 23”执行；④ 1–8 并行默认1，单台失败隔离，动态提交使停止后不再启动后续 DUT；⑤ UBUS 首次失败后重试3次，端口探测3次，每次 client 确保关闭；⑥ 新增严格 `source_address=(bind_ip, 0)` 端口探测，不回退任意地址；⑦ UBUS 日志补齐明文 login 与实际 `bbfdm get/set/add` 路径/参数，Access denied 给出退出 Web 管理页提示；⑧ UI 结果通过主线程队列回收，运行中锁定输入/刷新/关闭并提供停止；⑨ 补齐 service、源绑定、真实 UBUS 日志、UI 共享凭据/并发/停止回归并加入强制基线；⑩ 同步密码明文验收口径。
- 修改文件：`.claude/plans/dut_config_enable_telnet.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/core/parameter_session.py`、`Cheating_machine_execution_tool/src/core/telnet_transport.py`、`Cheating_machine_execution_tool/src/core/ubus_enable_telnet.py`、`Cheating_machine_execution_tool/src/models/dut_config_models.py`、`Cheating_machine_execution_tool/src/models/__init__.py`、`Cheating_machine_execution_tool/src/services/dut_config_service.py`、`Cheating_machine_execution_tool/src/services/__init__.py`、`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/src/ui/__init__.py`、`Cheating_machine_execution_tool/tests/test_dut_config_service.py`、`Cheating_machine_execution_tool/tests/test_telnet_transport.py`、`Cheating_machine_execution_tool/tests/test_ubus_enable_telnet.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`。
- 验证方法：在主源码目录执行 DUT service、Telnet、UBUS、主界面专项 `unittest discover`，再执行 `python -m unittest discover -s tests -v`、`python scripts/verify_baseline.py`、`git diff --check`。
- 验证结果：DUT service 10项、Telnet 10项、UBUS开启Telnet 18项、主界面97项专项测试通过；全量单测509项通过；`python scripts/verify_baseline.py` 全绿（46个当前主程序`.py`编译、编译清单完整、509项单测、40个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows 桌面确认 DUT 窗口首次完整绘制、Tab/表格/按钮与明文凭据；真实样机依次覆盖 already_present、reused、added_iface、lan 回退、禁用网卡自动启用、Access denied、1/8台并行、停止及单台失败隔离。真实样机结论由项目负责人提供后再更新验收状态。

## 2026-08-08 - 精简 DUT Telnet 成功状态

- 类型：界面优化 / 回归测试
- 完成内容：DUT 配置 → Telnet配置的目标表在成功后固定显示“成功：Telnet 已开启并验证可用”，不再在表格中重复展示源 IP、目标 IP、端口和规则动作；完整信息继续写入主执行日志。
- 修改文件：`Cheating_machine_execution_tool/src/ui/dut_config_window.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：执行主界面专项测试及 `python scripts/verify_baseline.py`、`git diff --check`。
- 验证结果：主界面专项 98 项通过；`python scripts/verify_baseline.py` 全绿（46 个源码文件编译、510 项单测、40 个强制基线测试均通过）。

## 2026-08-08 - 完整映射 WiFi 连接参数

- 类型：功能 / 测试项配置 / WiFi / 无 GUI 旧业务 / 回归测试 / 文档
- 背景：新工具“测试项配置 → WiFi”原来只编辑 `enable` 和 `product_solution`，全流程无 GUI 开关机测试则把2.4G/5G、WPA2-PSK、AES和不指定无线网卡写死，未完整覆盖旧“WIFI 连接参数”窗口。项目负责人要求把旧页功能映射到新工具 WiFi Tab。
- 完成内容：① `[connect_wifi]` 从2项扩展为8项：主控、2.4G、5G、ONU方案、认证、加密、指定无线网卡、网卡名称；② 新 WiFi Tab 全部使用中文标签及旧窗口候选值，支持“刷新无线网卡”并对成功、无网卡和异常记录主日志/弹窗；③ 新增 pywifi 接口枚举 core，名称去空、去重且保留发现顺序；④ 老测试方案缺新键时兼容回退为2.4G/5G开启、WPA2-PSK、AES、不指定网卡；⑤ 当前配置与默认模板补齐新键；⑥ 无 GUI请求和 `HeadlessOnuConfig` 逐项映射，不再写死；⑦ 主控关闭时执行日志明确跳过，指定网卡开启但名称为空时启动前拦截，运行电脑不存在所选网卡时明确失败且不回退；⑧ 保存确认框显示频段、认证、加密和网卡选择；⑨ 增加配置往返、默认兼容、接口枚举、请求加载、空网卡拦截和旧业务映射回归并加入强制基线。
- 修改文件：`.claude/plans/test_item_wifi_full_mapping.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/Auto_power_on_off_tool/config/test_project_config.ini`、`Cheating_machine_execution_tool/Auto_power_on_off_tool/config/test_project_config.default.ini`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`、`Cheating_machine_execution_tool/src/core/wifi_interfaces.py`、`Cheating_machine_execution_tool/src/services/legacy_power_test_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_test_item_config_store.py`、`Cheating_machine_execution_tool/tests/test_wifi_interfaces.py`、`Cheating_machine_execution_tool/tests/test_legacy_power_test_service.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：在主源码目录执行测试项配置 store、无线网卡枚举、旧工具无 GUI 服务、主界面4组专项 `unittest discover`，再执行 `python scripts/verify_baseline.py`、`git diff --check`。
- 验证结果：测试项配置 store 21项、无线网卡枚举1项、旧工具无 GUI服务13项、主界面93项专项测试均通过；`python scripts/verify_baseline.py` 全绿（43个当前主程序`.py`编译、编译清单完整、492项单测、35个强制基线测试实际执行、8条MUST_EXIST与1条MUST_NOT_EXIST均通过）。
- 后续待办：Windows 桌面打开 WiFi Tab，确认8项布局、保存/重载和“刷新无线网卡”；随后用小轮次真实运行子任务7，分别验证2.4G only、5G only、双频、指定网卡和不存在网卡失败提示。真实样机结论由项目负责人提供后再更新验收状态。

## 2026-08-08 - 展示开关机测试轮次进度

- 类型：功能 / 全流程执行 / 开关机测试 / 主界面 / 回归测试 / 文档
- 背景：主界面“环境检查与开关机测试”已有确定型进度条，但它只服务于历史线路检查通道计数，无 GUI 开关机测试运行时不会变化。项目负责人要求按 `Auto_power_on_off_tool/config/config.ini` 的 `number_of_tests` 总次数和当前测试进度动态展示。
- 完成内容：① 子任务7启动时使用本次从 `config.ini [ui_defaults]` 加载到请求中的 `number_of_tests` 设置进度总轮次并显示 `0/总轮次`；② 从旧结果文件的“通道N下挂的设备在第M次测试时正常”结论解析真实完成轮次；③ `only_power_off_on` 不写正常结论时，以进入第 N 轮确认前 N-1 轮完成，最终成功再补齐满格；④ 单通道逐轮推进，多通道按所有已选通道的最小完成轮次推进，避免快通道让进度提前满格；⑤ 进度通过编排器既有 UI 队列回到 Tk 主线程，不从后台线程直接操作控件；⑥ 全流程启动时重置为“等待开始”，停止/失败保留最后进度，全部成功强制显示满格；⑦ 主界面进度条右上方增加“开关机测试进度：当前/总轮次”文字；⑧ 增加轮次解析、仅上下电模式、跨通道聚合、数值钳制、状态重置及主线程委派回归，并将关键用例加入强制基线。
- 修改文件：`.claude/plans/legacy_power_test_progress.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/src/services/legacy_power_test_service.py`、`Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_legacy_power_test_service.py`、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：在主源码目录执行 4 组相关专项 `unittest discover`、`python scripts/verify_baseline.py`、`git diff --check`。
- 验证结果：旧工具无 GUI 服务 11 项、全流程编排器 41 项、主界面 93 项、全流程窗口 28 项专项测试均通过；`python scripts/verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、489 项单测、32 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面用 `number_of_tests` 小值（建议 3）运行单通道和双通道，确认主界面依次显示 `0/3 → 1/3 → 2/3 → 3/3`，双通道不会因单个快通道提前推进；真实样机结论由项目负责人提供后再更新验收状态。

## 2026-08-08 - 全流程默认不选择任何子任务

- 类型：行为调整 / 全流程执行 / 防误操作 / 回归测试 / 文档
- 背景：全流程窗口原先会自动勾选“环境线路检查”。项目负责人要求打开窗口时不默认勾选任何子任务，所有设备相关动作都由操作员按本次测试需要明确选择。
- 完成内容：① 取消“环境线路检查”的默认选中特例；② 现有 7 个子任务首次打开时统一为空框；③ 保留手动勾选、必填项状态、二次确认、串口日志预启动、子任务1后120秒等待、停止事件和执行顺序；④ 增加统一的默认状态入口及覆盖全部 7 个子任务的回归断言；⑤ 将该用例纳入强制基线，防止后续再次引入自动勾选；⑥ 同步操作员说明、验收基线、项目状态和实施计划。
- 修改文件：`.claude/plans/pipeline_default_no_selection.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_pipeline_window.py" -v`、`python scripts/verify_baseline.py`、`git diff --check`。
- 验证结果：全流程窗口 28 项专项测试通过；`python scripts/verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、484 项单测、29 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面首次打开“全流程执行”，目视确认 7 行均为空框；再手动勾选任一子任务确认状态刷新和二次确认仍正常。真实桌面结论由项目负责人提供后再更新验收状态。

## 2026-08-08 - 串口原始日志逐行增加时间戳

- 类型：功能 / 串口日志 / 底层传输 / 回归测试 / 文档
- 背景：项目负责人要求所有落盘的串口打印每一行都自动增加 `年月日_时分秒` 前缀，例如 `2026-08-08_19:12:10 打印内容`。原实现按串口读取块写日志，一个读取块包含多行时只有第一行前有旧格式时间戳，半行分包也无法按逻辑行处理。
- 完成内容：① 串口磁盘日志格式统一为 `YYYY-MM-DD_HH:MM:SS RX/TX/STATE/ERROR 内容`；② RX 增加按行缓冲，一个读取块含多行时逐行加时间戳，同一行跨多个读取块时先拼接再只加一次；③ TX 多行、STATE 和 ERROR 同样逐行加时间戳；④ TX/状态/错误到达或串口关闭前安全写出尚未换行的 RX 残留；⑤ 增加日志写锁，避免读取线程与发送线程同时写文件时互相穿插；⑥ 时间戳只写入磁盘文件，不修改串口原始字节历史、界面事件文本和升级标记判断；⑦ 首次专项测试发现遗漏 `re` 导入导致读取线程退出，补齐后复测通过；⑧ 新增跨块 CRLF/LF、末尾残留和多行 TX/STATE 回归并纳入强制基线。
- 修改文件：`.claude/plans/serial_log_line_timestamps.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/src/core/serial_transport.py`、`Cheating_machine_execution_tool/tests/test_serial_transport.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_serial_transport.py" -v`、`python scripts\verify_baseline.py`、`git diff --check`。
- 验证结果：串口传输 5 项专项测试通过；`python scripts\verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、484 项单测、28 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面查看新生成的串口日志，确认连续设备打印、多行同包和无换行末尾内容均按 `YYYY-MM-DD_HH:MM:SS` 逐行记录；真实样机结论由项目负责人提供后再更新验收状态。

## 2026-08-08 - 串口日志文件名增加日期

- 类型：优化 / 串口日志 / 文件命名 / 回归测试 / 文档
- 背景：串口终端原始日志当前按 `vlan名_COM口.log` 保存，项目负责人要求在原格式后增加年月日，示例为 `vlan112_COM12_20260808.log`，便于按日期归档和查找。
- 完成内容：① 新增统一的串口日志路径生成函数，格式固定为 `<vlan>_<COM>_<YYYYMMDD>.log`；② 日期取打开串口监控时的本机日期；③ `open_monitor()` 统一调用该入口，因此手动打开、“打开全部”和全流程预启动均使用相同格式；④ 同一天重新打开相同 VLAN/COM 使用同名文件，下一日期打开生成新文件名；⑤ Tab 显示、VLAN→COM 映射、日志目录、串口参数和原始日志写入保持不变；⑥ 新增固定日期命名回归并纳入强制基线。
- 修改文件：`.claude/plans/serial_log_daily_filename.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/src/ui/serial_terminal.py`、`Cheating_machine_execution_tool/tests/test_serial_terminal.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_serial_terminal.py" -v`、`python scripts\verify_baseline.py`、`git diff --check`。
- 验证结果：串口终端 10 项专项测试通过；`python scripts\verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、483 项单测、27 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面打开 `vlan112 / COM12`，确认状态栏路径和日志目录中的文件名为当日 `vlan112_COM12_YYYYMMDD.log`，且串口内容持续正常追加。

## 2026-08-08 - 修正交替 IP 登录日志去重

- 类型：BUG 修复 / 执行日志 / 旧业务适配 / 回归测试 / 文档
- 背景：上一版只合并相邻且同文的旧日志；真实运行按 `192.168.1.113 → 192.168.1.112 → 192.168.1.113 → 192.168.1.112` 交替输出“登录成功”时，相同 IP 中间隔着另一个 IP，仍会重复显示。
- 完成内容：① 增加对 `<IP>登录成功` 的精确识别；② 在单次开关机测试运行期间按 IP 记录已显示结果，同一 IP 无论是否与其它 IP 交替，都只显示第一次；③ 不同 IP 各保留一条，避免丢失各通道首次登录结果；④ 下一次重新启动开关机测试会创建新的去重集合，不影响新一轮结果；⑤ 保留其它日志的既有2秒去重和连续同文去重；⑥ 回归测试关闭2秒时间去重并模拟 `105 → 106 → 105 → 106`，确认最终只显示105和106各一条。
- 修改文件：`.claude/plans/legacy_power_log_noise_reduction.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/src/services/legacy_power_test_service.py`、`Cheating_machine_execution_tool/tests/test_legacy_power_test_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_legacy_power_test_service.py" -v`、`python scripts\verify_baseline.py`、`git diff --check`。
- 验证结果：旧工具无 GUI 服务 8 项专项测试通过；`python scripts\verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、482 项单测、26 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：真实运行确认 `113/112/113/112` 最终只显示113和112各一条；真实样机结论由项目负责人提供后再更新验收状态。

## 2026-08-08 - 强化开关机测试状态显示

- 类型：优化 / 主界面状态 / 视觉层级 / 回归测试 / 文档
- 背景：主界面“开关机测试状态：正在执行”沿用 9 号灰色提示文字，项目负责人现场反馈存在感太低，不便于操作员快速确认当前是否仍在测试。
- 完成内容：① 状态文字改为独立状态徽标，统一使用 11 号粗体和 `14×8` 内边距；② “正在执行”使用深绿色底白字高对比样式；③ 未运行、正在停止、已完成、已停止、执行失败分别使用灰、警告黄、成功绿、灰和危险红颜色语义；④ 状态变化时同步切换徽标样式，原状态文案、停止按钮启停和全流程业务逻辑保持不变；⑤ 新增六状态样式映射和高对比运行态回归，并加入强制基线。
- 修改文件：`.claude/plans/main_power_test_status_stop_control.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_app.py" -v`、`python scripts\verify_baseline.py`、`git diff --check`。
- 验证结果：主界面 91 项专项测试通过；`python scripts\verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、482 项单测、26 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面目视确认“正在执行”深绿色徽标足够醒目，较长的“正在停止（等待当前子任务安全退出）”在当前窗口宽度下完整显示。

## 2026-08-08 - 合并连续重复的旧工具日志

- 类型：BUG 修复 / 执行日志 / 旧业务适配 / 回归测试 / 文档
- 背景：真实运行中连续出现两条相同的 `[旧工具Logs][INFO] 192.168.1.112登录成功`，两次到达间隔略超过原有 2 秒时间去重窗口，导致新工具执行日志重复显示同一结果。
- 完成内容：① 保留既有 2 秒短时去重，同时增加“连续可见旧日志”去重；② 同级同文旧日志只要连续出现，无论相隔多久均只显示第一条；③ 出现其它可见旧日志或执行阶段日志后重置连续判定，下一轮相同登录结果仍可正常显示；④ 不修改旧工具登录、Telnet/SSH 或 logger 业务；⑤ 回归测试主动关闭 2 秒时间窗口并连续投递两条相同登录成功日志，确认仍只输出一次。
- 修改文件：`.claude/plans/legacy_power_log_noise_reduction.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/src/services/legacy_power_test_service.py`、`Cheating_machine_execution_tool/tests/test_legacy_power_test_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_legacy_power_test_service.py" -v`、`python scripts\verify_baseline.py`、`git diff --check`。
- 验证结果：旧工具无 GUI 服务 8 项专项测试通过；`python scripts\verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、481 项单测、25 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：真实运行确认连续两条同 IP“登录成功”只显示一次，同时下一测试轮开始后仍能显示该轮新的登录成功结果。

## 2026-08-08 - 中文化旧工具 Ping 成功结果

- 类型：优化 / 执行日志 / 旧业务适配 / 回归测试 / 文档
- 背景：旧工具会输出 `The network card with IP 192.168.1.112 has been pinged`，只能看出源网卡，不能直观看出实际 Ping 目标和结果；项目负责人要求改为清晰的 Ping 成功日志。
- 完成内容：① 不修改旧工具 Ping 业务，在新工具旧日志适配层精确识别该英文成功行；② 从当前测试方案、当前 Telnet/SSH 通信段的 `request_url` 提取旧业务实际使用的目标样机 IP；③ 新工具统一显示为 `[旧工具Logs][INFO] Ping 成功：源网卡 192.168.1.112 → 目标样机 192.168.1.1`，英文原文不再重复透传；④ 无法提取目标 IP 时仍明确显示源网卡已连通目标样机，不伪造固定地址；⑤ 其它旧工具日志、过滤、去重和真实 Ping 行为保持不变；⑥ 扩展既有强制基线测试，覆盖目标地址加载、中文转换及英文原文消失。
- 修改文件：`.claude/plans/legacy_power_log_noise_reduction.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/src/services/legacy_power_test_service.py`、`Cheating_machine_execution_tool/tests/test_legacy_power_test_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_legacy_power_test_service.py" -v`、`python scripts\verify_baseline.py`、`git diff --check`。
- 验证结果：旧工具无 GUI 服务 8 项专项测试通过；`python scripts\verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、481 项单测、25 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：真实开关机测试中确认源网卡 `192.168.1.112/113` 成功 Ping 当前测试方案目标时，新工具日志显示各自“源网卡 → 目标样机 → 成功”结果。真实样机结论由项目负责人提供后再更新验收状态。

## 2026-08-08 - 修复全流程结束后运行状态残留

- 类型：BUG 修复 / Tk 主线程 / 全流程状态 / 停止控制 / 回归测试 / 文档
- 背景：项目负责人现场日志先出现“开关机测试：当前全流程仍在执行或停止中”，随后点击停止又出现“当前没有正在执行的全流程”，说明后台编排器已经结束，但隐藏全流程窗口后的完成回调没有稳定清理主界面运行状态，造成状态与真实线程互相矛盾。
- 根因：`PipelineWindow._run_pipeline_thread()` 在后台线程中通过已隐藏 `Toplevel.after()` 安排完成/失败回调；窗口隐藏后该跨线程 Tk 调度不可靠，而 worker 的 `finally` 已先清空 `_orchestrator`，最终形成“主界面仍是运行态、停止入口却找不到编排器”。
- 完成内容：① 完成和失败回调统一改走主程序既有 `pipeline_ui_task_queue / _invoke_pipeline_ui_action`，由 Tk 主线程执行状态回收和结果提示；② 后台线程不再调用隐藏窗口的 `after()`；③ 新增 `PipelineWindow.is_running()` 返回线程真实存活状态；④ 主入口看到运行态时先核对真实线程，线程已结束则自动恢复“未运行”并允许重新显示配置窗口；⑤ 停止按钮发现无可停止编排器但仍残留运行态时也自动恢复，避免矛盾日志继续重复；⑥ lambda 显式捕获完成结果/异常，避免异常变量离开 `except` 后失效；⑦ 新增主线程队列回调、主入口残留恢复和停止按钮残留恢复回归，并把前两项纳入强制基线。
- 修改文件：`.claude/plans/main_power_test_status_stop_control.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_pipeline_window.py -v`、`python scripts\verify_baseline.py`、`git diff --check`。
- 验证结果：主界面 90 项、全流程窗口 28 项专项测试通过；`python scripts\verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、481 项单测、25 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面重新执行一次“自动上/下电”全流程，确认结束后主界面及时显示“已完成”、停止按钮禁用，再次点击“检查并执行测试”可重新显示配置窗口，且不再出现两条矛盾提示。真实样机结论由项目负责人提供后再更新验收状态。

## 2026-08-08 - 删除执行日志说明行

- 类型：优化 / 主界面布局 / 回归测试 / 文档
- 背景：项目负责人要求删除主界面“执行日志”标题下方的“运行步骤、检查结果和异常信息”描述。
- 完成内容：① 删除该提示标签，缩短日志卡片顶部占用；② “执行日志”标题、“清空日志”按钮、日志文本框、日志样式和写入逻辑保持不变；③ 扩展上一轮主界面精简强制回归，明确禁止该文案重新出现。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p test_app.py -v`、`python scripts\verify_baseline.py`、`git diff --check`。
- 验证结果：主界面 89 项专项测试通过；`python scripts\verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、478 项单测、23 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面确认“执行日志”标题下方直接显示日志框，不再有提示行。

## 2026-08-08 - 精简主界面顶部并移动管理员状态

- 类型：优化 / 主界面布局 / 权限状态 / 回归测试 / 文档
- 背景：项目负责人在截图中要求删除内容区顶部重复显示的“开关机测试环境搭建助手”和“配置测试通道、完成自动上/下电并检查全部线路”，并把右上角管理员权限状态移动到常用工具栏右侧的空白位置。
- 完成内容：① 删除主界面内容区独立 header 和两行重复文案，Windows 标题栏名称保持不变；② 管理员权限检测逻辑不变，将状态标签移动到常用工具栏；③ 利用右侧 `pack` 顺序把状态放在“刷新串口”左侧，“刷新串口 / 刷新网卡”的视觉顺序保持不变；④ 管理员权限已就绪继续使用绿色成功样式，权限不足继续使用红色危险样式和原提示；⑤ 新增布局回归，锁定文案删除、权限状态位置、刷新按钮顺序与颜色语义，并纳入强制基线。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p test_app.py -v`、`python scripts\verify_baseline.py`、`git diff --check`。
- 验证结果：主界面 89 项专项测试通过；`python scripts\verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、478 项单测、23 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面确认内容区顶部两行文案已消失，管理员权限状态位于截图标注的常用工具栏空白区域，且刷新串口、刷新网卡按钮仍完整可见。真实桌面结论由项目负责人提供后再更新验收状态。

## 2026-08-08 - 全流程启动后自动隐藏配置窗口

- 类型：优化 / 全流程窗口 / 主界面状态 / 回归测试 / 文档
- 背景：项目负责人确认采用“隐藏”方式：全流程执行界面点击“开始执行”后应自动隐藏，执行期间由主界面状态与停止按钮承接操作。
- 完成内容：① 完成必填项检查和二次确认后，严格先启动后台编排线程，再 `withdraw()` 隐藏全流程配置窗口；② 主执行日志明确提示配置窗口已隐藏、应在主界面查看状态或停止；③ 执行期间再次点击“检查并执行测试”只输出当前仍在执行的提示，不重新显示配置窗口；④ 流程结束后再次点击才重新显示并复用原窗口；⑤ 完成、部分失败和异常提示均改以主界面为父窗口，避免隐藏父窗口导致提示不可见；⑥ 保留项目负责人手动调整后的按钮文案“停止测试”，同步修正日志与当前行为文档；⑦ 新增启动后隐藏、执行中禁止重显和结果弹窗父窗口回归，并把隐藏时序测试纳入强制基线。
- 修改文件：`.claude/plans/main_power_test_status_stop_control.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_pipeline_window.py -v`、`python scripts\verify_baseline.py`、`git diff --check`。
- 验证结果：主界面 88 项、全流程窗口 26 项专项测试通过；首次完整基线因回归仍硬编码旧按钮文案而失败，保留当前“停止测试”并同步断言后，`python scripts\verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、477 项单测、22 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面点击“开始执行”并完成确认，确认全流程配置窗口自动隐藏、主界面状态变为“正在执行”；执行中再次点击主入口不应重新弹窗，结束后再次点击应正常显示原配置窗口。真实样机结论由项目负责人提供后再更新验收状态。

## 2026-08-08 - 移动停止按钮并显示开关机状态

- 类型：功能 / 主界面状态 / 全流程停止控制 / 回归测试 / 文档
- 背景：项目负责人要求在主界面“环境检查与开关机测试”卡片的空白位置显示当前是否正在执行开关机测试，并将全流程弹窗中的停止按钮移动到该区域，命名为“停止开关机测试”。
- 完成内容：① 主界面新增“开关机测试状态”，覆盖未运行、正在执行、正在停止、已完成、已停止和执行失败；② 主界面新增“停止开关机测试”按钮，只有正在执行时启用，发出停止请求后立即禁用并显示“等待当前子任务安全退出”；③ 停止按钮继续委派给当前 `PipelineOrchestrator.request_stop()`，没有复制第二套停止逻辑；旧 Start All 子任务继续直接接收同一停止事件，其它子任务保持既有安全停止边界；④ 全流程弹窗移除原停止按钮，开始、正常完成、异常失败和操作员停止均同步刷新主界面；⑤ 停止期间阻止再次新建全流程窗口，按钮刚启用但后台编排器尚未完成创建时也会记住停止请求并在就绪后立即下发；⑥ 顺带修正操作员说明中已移除 `[order]` 子任务的残留描述；⑦ 新增主界面布局、状态按钮联动、停止委派、启动竞态、弹窗按钮移除和生命周期回归，并将主入口与停止事件两项纳入强制基线。
- 修改文件：`.claude/plans/main_power_test_status_stop_control.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_pipeline_window.py -v`、`python scripts\verify_baseline.py`、`git diff --check`。
- 验证结果：主界面 88 项、全流程窗口 23 项专项测试通过；`python scripts\verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、474 项单测、21 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面启动一次全流程，确认主界面状态依次显示“正在执行 → 已完成”；再次运行并点击主界面“停止开关机测试”，确认显示“正在停止 → 已停止”，且全流程弹窗不再显示停止按钮。真实样机结论由项目负责人提供后再更新验收状态。

## 2026-08-08 - 修正每轮正常结果真实路径匹配

- 类型：BUG 修复 / 执行日志 / 旧业务适配 / 回归测试 / 文档
- 背景：项目负责人真实运行确认，新工具执行日志没有出现 `[旧工具Logs][INFO] 2026-08-08 15:37:41.904434: 通道9下挂的设备在第1次测试时正常`。复查旧 Telnet/SSH 源码确认真实结果文件位于 `test_results/device_9/device_9_command_results_*.log`，上一版错误地只匹配了直接位于 `test_results` 下的模拟路径，导致现场文件写入未被捕获。
- 完成内容：① 结果文件识别改为严格匹配旧工具真实的 `test_results/device_N/device_N_command_results_*.log` 两层目录；② 同时校验目录通道号与文件名设备号一致，避免扩大拦截范围；③ 回归测试改用真实嵌套目录结构，并继续验证分段写入只转发一次、原文件字节不变；④ 强制基线继续锁定该真实路径回归。
- 修改文件：`.claude/plans/legacy_cycle_success_log_bridge.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/src/services/legacy_power_test_service.py`、`Cheating_machine_execution_tool/tests/test_legacy_power_test_service.py`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p test_legacy_power_test_service.py -v`、`python scripts\verify_baseline.py`、`git diff --check`。
- 验证结果：旧工具无 GUI 服务 8 项专项测试通过；首次完整基线出现1项未复现的偶发失败，随后单独全量 467 项测试通过，再次执行 `python scripts\verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、467 项单测、19 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：请项目负责人再次用真实通道运行至少一轮，确认新工具执行日志实时出现对应正常结论；现场结论确认后再更新验收状态。

## 2026-08-08 - 桥接旧工具每轮正常结果日志

- 类型：功能 / 执行日志 / 旧业务适配 / 回归测试 / 文档
- 背景：旧工具会把 `2026-08-08 15:37:41.904434: 通道9下挂的设备在第1次测试时正常` 这类单轮正常结论只写入 `test_results/device_*_command_results_*.log`，既有 signal/logger 桥接无法捕获，因此新工具执行日志看不到该关键结果。
- 完成内容：① 在旧 Start All 无 GUI 专用子进程中增加窄范围结果文件转发器，仅识别目标 `device_*_command_results_*.log` 的二进制写入；② 支持一行被多次分段写入，只有完整匹配“通道N下挂的设备在第M次测试时正常”后才转发一次；③ 新工具执行日志按 `[旧工具Logs][INFO] 原始完整行` 展示；④ 始终先完成旧文件写入再转发，保留原文件字节内容和旧业务逻辑；⑤ 无关文件及不匹配内容不转发，子进程退出时恢复原始文件打开函数；⑥ 将原文件不变且结果成功转发的测试加入强制基线。
- 修改文件：`.claude/plans/legacy_cycle_success_log_bridge.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/src/services/legacy_power_test_service.py`、`Cheating_machine_execution_tool/tests/test_legacy_power_test_service.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p test_legacy_power_test_service.py -v`、`python scripts\verify_baseline.py`、`git diff --check`。
- 验证结果：旧工具无 GUI 服务 8 项专项测试通过；`python scripts\verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、467 项单测、19 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面勾选子任务7并用真实程控电源与样机运行至少一轮，确认新工具执行日志实时出现对应 `[旧工具Logs][INFO]` 正常结论，同时旧 `test_results` 结果文件内容仍完整；真实样机结论由项目负责人提供后再更新验收状态。

## 2026-08-08 - 移除全流程测试项执行子任务

- 类型：修改 / 全流程编排 / UI 列表 / 回归测试 / 文档
- 背景：项目负责人明确不再需要全流程中的原第7项“测试项配置（[order] 执行）”，要求从子任务列表去除。
- 完成内容：① 从 `SUBTASK_CODES`、显示标签、去配置映射、状态计算和执行分发表中完整移除 `test_item_execution`，不是仅隐藏界面行；② 删除全流程上下文对 `test_project_config.ini` 的加载和 `TestProjectConfig` 依赖；③ 原第8项“执行开关机测试”顺延为第7项，危险操作提示和全部当前文档同步改为子任务7；④ 全流程窗口由8行调整为7行并相应缩短默认高度，串口日志预启动、子任务1后120秒等待、失败传播和默认仅勾选环境检查均保持不变；⑤ 主界面的“测试项配置”五 Tab 编辑器、INI 保存及既有独立 service 源码保持不变；⑥ 回归测试明确断言全流程状态和执行类中不存在 `test_item_execution`，7项编号连续且全选执行顺序正确；⑦ 强制基线测试 ID 从“全部8项”更新为“全部7项”。
- 修改文件：`.claude/plans/remove_pipeline_order_subtask.md`、`README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`、`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_pipeline_orchestrator.py" -v`、`python -m unittest discover -s tests -p "test_pipeline_window.py" -v`、`python scripts\verify_baseline.py`、`git diff --check`。
- 验证结果：全流程编排器 41 项、全流程窗口 19 项专项测试通过；`python scripts\verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、465 项单测、18 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面打开“全流程执行”，确认列表仅显示连续编号1～7，不再出现“测试项配置（[order] 执行）”，原“执行开关机测试”显示为第7项；真实样机结论由项目负责人提供后再更新验收状态。

## 2026-08-08 - 精简旧工具日志并高亮轮次开始

- 类型：优化 / UI 日志 / 旧业务适配 / 回归测试 / 文档
- 背景：全流程子任务8会把旧工具 Logs 与 logger 输出汇总到新工具主执行日志，底层配置路径、原始命令回显及重复上报导致日志过多；项目负责人同时要求形如 `[旧工具Logs][INFO] *******通道 【9】 开始第2次测试*******` 的轮次开始日志使用绿色字体。
- 完成内容：① 在新工具执行日志标签选择器中精确识别旧工具“通道开始第 N 次测试”INFO 日志并复用绿色成功标签，不扩大到其它普通 INFO；② 在 `legacy_power_test_service` 桥接层增加精简策略，不修改旧工具源码和执行逻辑；③ `show_signal*` 操作员日志继续保留，logger 的 WARNING / ERROR 全部保留，INFO 只保留登录、连接、Ping、WiFi、重试、测试完成等关键结果；④ 配置路径、原始命令回显、串口状态等底层 INFO 不再写入新工具主执行日志；⑤ logger 与 signal 在 2 秒内上报的同级同文日志只显示一次；⑥ 实际程控电源帧、子任务阶段和最终成功/失败不参与过滤；⑦ 增加高亮、来源过滤、关键结果保留、错误保留和重复合并回归测试。
- 修改文件：`.claude/plans/legacy_power_log_noise_reduction.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/services/legacy_power_test_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_legacy_power_test_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_app.py" -v`、`python -m unittest discover -s tests -p "test_legacy_power_test_service.py" -v`、`python scripts\verify_baseline.py`。
- 验证结果：主界面 85 项、旧工具无 GUI 服务 6 项专项测试通过；`python scripts\verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、467 项单测、18 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面勾选全流程子任务8，确认轮次开始正文为绿色，主日志量明显减少，警告/错误、电源帧和最终结论仍完整可见；真实样机结论由项目负责人提供后再更新验收状态。

## 2026-08-08 - 收敛指令重试间隔配置源

- 类型：修改 / 配置持久化 / 回归测试 / 文档
- 背景：项目负责人要求“测试项配置 → 测试项 → 指令重试间隔（秒，全局）”只保存到 `Auto_power_on_off_tool/config/config.ini`，并删除 `test_project_config.ini` 中重复的 `command_fail_retry_interval_time`。
- 完成内容：① 将 `config.ini [other_config] command_fail_retry_interval_time` 定为唯一持久化位置，页面加载、保存和全流程测试项执行都使用该值；② `test_project_config.ini [order]` 序列化时只保存测试命令，加载历史文件时忽略残留同名键且不覆盖 `config.ini`；③ 从当前 `test_project_config.ini` 和默认模板 `test_project_config.default.ini` 删除重复键，避免“恢复默认”重新带回；④ “恢复默认”只恢复测试命令并明确保留当前重试间隔；⑤ 保存确认和主执行日志明确说明重试间隔仅写入 `config.ini [other_config]`；⑥ 将“只写 config.ini、不写测试项目文件”的用例纳入强制基线。
- 修改文件：`.claude/plans/retry_interval_single_config_source.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/Auto_power_on_off_tool/config/test_project_config.ini`、`Cheating_machine_execution_tool/Auto_power_on_off_tool/config/test_project_config.default.ini`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/legacy_ui_defaults_store.py`、`Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`、`Cheating_machine_execution_tool/src/services/test_item_execution_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_legacy_ui_defaults_store.py`、`Cheating_machine_execution_tool/tests/test_test_item_config_store.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：编译三个相关源码；执行 `test_test_item_config_store.py`、`test_legacy_ui_defaults_store.py`、`test_app.py`；核对三个实际 INI；执行 `python scripts/verify_baseline.py` 和 `git diff --check`。
- 验证结果：配置存储 21 项、旧配置存储 5 项、主界面 84 项专项测试通过；实际文件核对仅 `config.ini` 保留 `command_fail_retry_interval_time = 60`，当前及默认测试项目配置均无该键，加载仍得到 60 秒；完整基线全绿（42 个源码文件编译、465 项单测、18 个强制基线测试、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面修改重试间隔并保存，确认重开页面仍显示新值，`config.ini [other_config]` 更新，而 `test_project_config.ini [order]` 只保留测试命令。

## 2026-08-08 - 全流程新增子任务8“执行开关机测试”

- 类型：全流程功能 / 旧业务无 GUI 适配 / 程控电源危险操作 / Logs 桥接 / 回归门禁 / 文档
- 完成内容：① 全流程新增默认不勾选的第8项“执行开关机测试”，保持串口日志预启动及其余子任务1→8相对顺序；② 新增 `legacy_power_test_service`，在 Windows `spawn` 独立子进程中直接复用旧 `PowerOnOffTelnet` / `PowerOnOffSsh`、程控电源和通道业务，不启动旧 EXE，不 import / 实例化 `Auto_Power_On_Off_Tool.py` GUI 主类；③ 严格加载当前 `config.ini [ui_defaults]`、当前测试方案、`network_card_ip.ini [power_supply] serial_port` 和新工具已勾选通道，COM 为空、方案缺失、通道或 PC IP 无效时在开始前显示缺项；④ 转发旧 `show_signal/show_signal_warning/show_signal_error` 与 logger 内容到新工具主执行日志，并记录每条实际下发的十六进制程控电源帧；⑤ 旧 Start All 初始化先发全通道断电帧，二次确认新增明确危险提示，之后只启动新工具当前勾选通道；⑥ 全部通道结束才返回结果，任一通道失败作为致命失败停止全流程；“停止”会通知旧 Telnet 业务，10秒内未退出则只终止本次无 GUI 子进程；⑦ 增加冻结程序多进程入口、旧业务运行依赖和打包 hidden import；旧 GUI 主文件与本机配置均未改写。
- 修改文件：`.claude/plans/legacy_power_test_subtask.md`、`README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/run_line_check_assistant.py`、`requirements.txt`、`THIRD_PARTY_NOTICES.md`、`build_line_check_assistant.ps1`、`line_check_assistant/pipeline_window.py`、`src/services/__init__.py`、`src/services/pipeline_orchestrator.py`、`src/services/legacy_power_test_service.py`、`tests/test_legacy_power_test_service.py`、`tests/test_pipeline_orchestrator.py`、`tests/test_pipeline_window.py`、`scripts/verify_baseline.py`、`line_check_assistant_README.md`。
- 验证方法：读取当前真实配置做无设备预检；执行旧 Start All service、全流程编排和窗口专项测试；执行 `python scripts/verify_baseline.py`；执行 `git diff --check`。未打开真实程控电源串口、未启动旧 GUI、未运行真实样机开关机循环。
- 验证结果：当前配置只读预检成功，解析为 `Telnet / COM102 / TEST_PROJECT / channel 9`；service 5 项、编排器 43 项、窗口 19 项专项测试通过；`python scripts/verify_baseline.py` 全绿（42 个当前主程序 `.py` 编译、编译清单完整、464 项单测、18 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面勾选第8项，确认危险提示后用真实程控电源和样机验收：旧 GUI 不出现、初始化全断电帧与后续通道帧可在主日志核对、只运行当前勾选通道、旧 Logs 持续转发、停止按钮可终止、全部循环结束后最终结果正确。真实样机结论须由项目负责人提供后再更新验收状态。

## 2026-08-08 - 全流程编号项统一使用“子任务”术语

- 类型：UI 文案 / 执行日志 / 术语统一 / 回归测试 / 文档
- 完成内容：① 全流程界面、二次确认框和主执行日志中，编号执行项统一称为“子任务”，不再显示“管道1 / 后续管道”等描述；② 120秒约束统一表述为“子任务1完成后等待120秒，再开始后续子任务”；③ 串口日志提示改为“全流程开始时提前启动”，总体流程异常和停止提示使用“全流程”，避免把总体编排与单个编号项混称；④ 底层 `pipeline_*` 文件名、类名和内部架构术语保持不变，避免仅因文案发生无意义重构；⑤ 同步更新当前状态、验收基线、操作员说明和文案回归测试。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`、`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：执行全流程编排和窗口专项测试；执行 `python scripts/verify_baseline.py`。
- 验证结果：全流程编排与窗口相关源码编译通过；`test_pipeline_window.py` 18 项通过；术语守门测试已加入强制基线；`python scripts/verify_baseline.py` 全绿（41 个当前主程序 `.py` 编译、编译清单完整、455 项单测、14 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续约定：项目负责人后续使用“子任务1～子任务7”表达全流程中的编号执行项；“全流程”表示整体执行过程。

## 2026-08-08 - 子任务1完成后统一等待120秒再执行后续子任务

- 类型：全流程执行约束 / 设备稳定等待 / 停止响应 / 回归门禁 / 文档
- 完成内容：① 只要勾选“1. 自动上/下电”且实际执行顺序中还有任意后续已勾选子任务，子任务1成功完成后固定等待120秒，再启动下一个子任务，不再限定后续必须是子任务2；② 只勾选子任务1、子任务1位于全部已勾选任务末尾或子任务1执行失败时不做无意义等待；③ 等待使用全流程停止事件，可由“停止”按钮立即中断并跳过全部后续任务；④ 主执行日志明确记录等待开始、目标后续子任务、等待完成或停止中断；⑤ 全流程二次确认框在满足条件时提前显示“子任务1完成后等待120秒”的约束；⑥ 新增任意后续子任务等待、仅子任务1不等待、等待可停止及确认框提示测试，并把120秒精确值纳入强制基线。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`、`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：编译编排器和全流程窗口；执行 `test_pipeline_orchestrator.py`、`test_pipeline_window.py`；执行 `python scripts/verify_baseline.py`。
- 验证结果：编排器和全流程窗口源码编译通过；`test_pipeline_orchestrator.py` 40 项、`test_pipeline_window.py` 17 项通过；`python scripts/verify_baseline.py` 全绿（41 个当前主程序 `.py` 编译、编译清单完整、454 项单测、13 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面勾选子任务1及任意后续子任务，确认子任务1结束后日志开始120秒等待、期间点击“停止”可立即结束；不点击停止时确认满120秒才出现下一个子任务的开始日志。

## 2026-08-08 - 修复全流程串口日志只显示窗口但未打开 COM

- 类型：BUG 修复 / 全流程编排 / 串口日志 / 回归门禁 / 文档
- 根因：全流程预启动复用了手工工具栏的 `_open_serial_log_module()`，该入口只创建/显示 VLAN/COM Tab；真正启用串口的逻辑仍封在“打开全部”按钮的匿名回调里，因此窗口虽已出现，各 Tab 仍显示“COM 未打开”，无法接收设备打印。
- 完成内容：① 将串口终端“打开全部”提取为可复用 `open_all()`，界面按钮和全流程共用同一动作；② 新增全流程专用 `_open_pipeline_serial_logs()`，在 Tk 主线程中严格执行“显示目标 Tab → 打开窗口当前全部串口”；③ 全部打开动作返回后才进入上下电等后续子任务；④ 主执行日志记录实际 VLAN/COM 目标和成功数量，任一串口失败则记录失败 VLAN，并按串口日志既有非致命规则继续后续；⑤ 手工点击主界面“串口日志”仍只显示窗口，不擅自打开串口；⑥ 新增终端全部打开、全流程显示/打开顺序、失败传播与 Tk 主线程调度回归测试，并把全流程自动“打开全部”纳入强制基线测试。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/src/ui/serial_terminal.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`、`Cheating_machine_execution_tool/tests/test_serial_terminal.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：编译串口终端、主程序和编排器源码；执行 `test_serial_terminal.py`、`test_app.py`、`test_pipeline_orchestrator.py`；执行 `python scripts/verify_baseline.py`。
- 验证结果：相关源码编译通过；`test_serial_terminal.py` 9 项、`test_app.py` 84 项、`test_pipeline_orchestrator.py` 37 项通过；`python scripts/verify_baseline.py` 全绿（41 个当前主程序 `.py` 编译、编译清单完整、450 项单测、12 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面勾选“串口日志”和至少一个后续子任务，确认窗口出现后各目标 Tab 由“COM 未打开”变为“COM 监控中”，并确认第一个上下电动作前的设备打印已写入 `D:\Serial_Log`。

## 2026-08-08 - 全流程串口日志改为全流程开始时预启动

- 类型：全流程编排 / 串口日志 / Tk 线程边界 / 回归测试 / 文档
- 完成内容：① 保留全流程界面原有 1→7 行布局和默认勾选规则；② 只要勾选“串口日志”，实际执行顺序就把它移到管道首位，先打开终端，再执行上下电、环境检查、升级、写参、ONU 和测试项；③ 串口窗口打开动作通过既有 UI 任务队列投回 Tk 主线程，入口返回后才继续其它管道；④ 串口日志仍为非致命任务，打开失败只记录失败并继续后续；⑤ 二次确认框改为显示真实执行顺序，串口日志位于首位并标注提前启动；⑥ 新增预启动顺序、未勾选时顺序不变、Tk 主线程调度和确认框回归测试。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`、`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：编译编排器和窗口源码；执行 `test_pipeline_orchestrator.py`、`test_pipeline_window.py`；执行 `python scripts/verify_baseline.py`。
- 验证结果：编排器和窗口源码编译通过；`test_pipeline_orchestrator.py` 37 项、`test_pipeline_window.py` 16 项通过；`python scripts/verify_baseline.py` 全绿（41 个当前主程序 `.py` 编译、编译清单完整、447 项单测、11 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）；`git diff --check` 通过，仅现有 LF/CRLF 换行提示。
- 后续待办：Windows 桌面勾选串口日志和上下电/升级等任务，确认二次确认框把串口日志显示在首位，并确认日志已捕获从第一个设备操作开始的串口输出。

## 2026-08-08 - 两份 INI 的指令重试间隔保持同步

- 类型：配置同步 / 兼容旧工具 / 回归测试 / 文档
- 完成内容：① 将 `test_project_config.ini [order] command_fail_retry_interval_time` 定为“测试项配置”的编辑主值；② 每次保存测试项配置时，同步将完全相同的值写入 `config.ini [other_config] command_fail_retry_interval_time`；③ 更新时保留 `config.ini` 其它段、配置项、注释和原换行风格；④ 当前两份实际配置已从 `10 / 60` 统一为 `10 / 10`；⑤ 主程序保存成功日志增加同步后重试间隔秒数；⑥ 新增直接更新保留注释和测试项保存双文件同值回归测试，并将双文件同步测试纳入 `verify_baseline.py` 强制基线；⑦ 修正旧工具当前配置回归测试，改为核对加载值与实际 INI 一致，不再将用户可编辑的 `startup_time` 硬编码为 240，保留当前用户配置 180。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/Auto_power_on_off_tool/config/config.ini`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/legacy_ui_defaults_store.py`、`Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/tests/test_legacy_ui_defaults.py`、`Cheating_machine_execution_tool/tests/test_legacy_ui_defaults_store.py`、`Cheating_machine_execution_tool/tests/test_test_item_config_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：编译 3 个相关源码；执行 `test_legacy_ui_defaults_store.py`、`test_test_item_config_store.py`、`test_app.py`；执行 `python scripts/verify_baseline.py`；核对两份实际 INI 值。
- 验证结果：3 个相关源码编译通过；`test_legacy_ui_defaults_store.py` 4 项、`test_test_item_config_store.py` 21 项、`test_app.py` 82 项通过；首次完整基线发现旧测试将用户已改为 180 的 `startup_time` 错误硬编码为 240，保留用户配置并修正断言后，`python scripts/verify_baseline.py` 全绿（41 个当前主程序 `.py` 编译、编译清单完整、444 项单测、11 个强制基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）；实际文件核对为 `10 / 10`；`git diff --check` 通过，仅现有 LF/CRLF 换行提示。
- 后续待办：Windows 桌面在“测试项”页把指令重试间隔改为任意值并保存，确认两份 INI 的同名字段值一致，且旧工具执行时使用该值。

## 2026-08-08 - 主界面新增 DUT 配置占位入口

- 类型：UI 功能入口 / 未来 UBUS 扩展边界 / 回归测试 / 文档
- 完成内容：① 在主界面“串口日志”右侧新增“DUT配置”按钮；② 点击后打开独立占位窗口，明确显示计划使用 UBUS、具体配置项和执行逻辑待后续完善；③ 重复点击复用已打开的窗口；④ 当前不实例化 UBUS 客户端、不连接 DUT、不下发命令，执行日志明确记录本次跳过；⑤ 新增工具栏位置、窗口复用和无 UBUS 下发边界回归测试。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：编译 `app.py`；执行 `test_app.py`；执行 `python scripts/verify_baseline.py`。
- 验证结果：`app.py` 编译通过；`test_app.py` 82 项通过；`python scripts/verify_baseline.py` 全绿（41 个当前主程序 `.py` 编译、编译清单完整、442 项单测、10 个关键基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）；`git diff --check` 通过，仅现有 LF/CRLF 换行提示。
- 后续待办：① Windows 桌面确认按钮位置、占位窗口显示和重复打开；② 项目负责人后续明确 DUT 配置项、UBUS 对象/方法、登录凭据、并行范围及成功判据后，再将业务编排放入 `src/services`、底层 UBUS 能力放入 `src/core`。

## 2026-08-07 - 修复测试项配置窗口需移动鼠标才显示

- 类型：BUG 修复 / Windows 窗口绘制 / 回归测试 / 文档
- 根因：测试项配置窗口包含五个 Tab 和多条动态命令，初版直接显示时 Windows 可能先呈现未完成绘制的客户区；第一版修复又在隐藏状态先执行 `update_idletasks()`、随后才显示，只计算了隐藏布局，没有处理显示后产生的 Windows 绘制消息，因此现场仍需鼠标事件触发重绘。
- 完成内容：① 创建窗口后先 `withdraw()`，在隐藏状态完成全部控件构建；② 当前按钮回调结束后通过 `after(0, ...)` 进入下一轮 Tk 事件循环，再按 `deiconify → lift → update_idletasks → update → focus_force` 显示窗口并处理完整绘制队列；③ 新增显示调用顺序和“先隐藏构建、下一轮事件显示”的回归测试。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：编译 `app.py`；执行 `test_app.py`；执行 `python scripts/verify_baseline.py`。
- 验证结果：`app.py` 编译通过；`test_app.py` 79 项通过；`python scripts/verify_baseline.py` 全绿（41 个当前主程序 `.py` 编译、编译清单完整、439 项单测、10 个关键基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- Windows 桌面验收：2026-08-07 项目负责人确认 BUG 已解决；点击「测试项配置」后窗口可正常绘制，不再只显示标题透明窗口，也不需移动鼠标触发刷新。
- 后续待办：本轮窗口绘制 BUG 无。

## 2026-08-07 - Telnet 与 WiFi 配置字段改为中文显示

- 类型：UI 文案 / 易用性 / 回归测试 / 文档
- 完成内容：① Telnet 页将 12 项原始配置键标签全部改为对应中文含义，并移除“设备默认已开启 Telnet”中的原始键名提示；② WiFi 页将 `product_solution` 改为“产品方案”，复选框改为“启用 WiFi 连接测试”且不再显示 `enable=1`；③ 仅修改界面标签，内存字段、INI 键名、值和保存格式完全不变；④ 新增中文标签存在、旧英文键标签不存在的界面回归测试。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：编译 `app.py`；执行 `test_app.py`；执行 `python scripts/verify_baseline.py`。
- 验证结果：`app.py` 编译通过；`test_app.py` 77 项通过；`python scripts/verify_baseline.py` 全绿（41 个当前主程序 `.py` 编译、编译清单完整、437 项单测、10 个关键基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面确认 Telnet 与 WiFi 页不再显示原始配置键名，中文标签与输入框对齐，保存并重新加载后配置值不变。

## 2026-08-07 - 测试项配置新增“开关机运行参数”Tab

- 类型：功能 / 配置编辑器 / UI / 测试 / 文档
- 完成内容：① 「测试项配置」新增第五个 Tab，名称按项目负责人要求固定为“开关机运行参数”；② 页面仅展示 `startup_time`、`interval_time`、`number_of_tests`、`wait_command_done` 四项，并按项目负责人要求删除左侧原始键名和右侧灰色说明列，改为左侧黑色中文名称 + 右侧输入框；③ `communication_method`、`baud_rate`、`selected_profile`、`telnet_enable` 不显示，保存时前三项保留原值，`telnet_enable` 由 Telnet 页反向计算并自动写入；④ “重新加载”同时重读测试项配置与旧工具参数，“保存”同时写入两份配置；⑤ 仅更新 `[ui_defaults]`，保留 `config.ini` 其它段、未知键和注释；⑥ 保存确认、主执行日志和成功提示明确记录旧工具参数数量及目标文件；⑦ 新增字段隐藏、中文标签布局与原值保留、字段校验、注释/其它段保留和第五 Tab 接线回归测试。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/legacy_ui_defaults_store.py`、`Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_legacy_ui_defaults_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：编译三个相关源码；执行 `test_legacy_ui_defaults_store.py`、`test_test_item_config_store.py`、`test_app.py`；执行 `python scripts/verify_baseline.py`。
- 验证结果：三个相关源码编译通过；`test_legacy_ui_defaults_store.py` 3 项、`test_test_item_config_store.py` 20 项、`test_app.py` 76 项通过；首次基线按预期拦截新增源码未登记编译清单，补入 `PY_COMPILE_FILES` 后 `python scripts/verify_baseline.py` 全绿（41 个当前主程序 `.py` 编译、编译清单完整、436 项单测、10 个关键基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面打开「测试项配置」，确认第五个 Tab 只显示 4 项黑色中文名称与输入框，无原始键名和右侧灰色说明；修改后保存/重开确认四项生效、隐藏三项原值不变，并确认 Telnet 页保存仍会更新反向镜像。

## 2026-08-07 - 旧工具 Telnet、COM 与通道选择复用新工具配置

- 类型：旧工具独立维护 / 配置统一 / 回归测试 / 文档
- 完成内容：① 旧工具 `Telnet Enable` 严格反向读取新工具 `test_project_config.ini [telnet] telnet_default_on`，即 `1 → 0`、`0 → 1`；② 新工具保存测试项配置时同步更新 `config.ini [ui_defaults] telnet_enable` 镜像行，并保留旧配置其它内容和注释；③ 旧工具 `serial_num` 严格读取新工具保存的程控电源 COM，删除重复配置及回退逻辑，新工具 COM 为空时旧工具也为空；④ 旧工具“电源控制”channel 1～16 逐项同步新工具选中通道，存在且 `enabled=1` 才勾选，其余全部取消；⑤ 启动日志增加 Telnet Enable、COM 配置来源和同步通道；⑥ 新增反向 Telnet、配置镜像、COM 唯一来源、空 COM、通道同步回归测试；⑦ 不改写本机 `network_card_ip.ini`。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py`、`Cheating_machine_execution_tool/Auto_power_on_off_tool/config/config.ini`、`Cheating_machine_execution_tool/Auto_power_on_off_tool/config/ui_defaults.py`、`Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`、`Cheating_machine_execution_tool/tests/test_legacy_ui_defaults.py`、`Cheating_machine_execution_tool/tests/test_test_item_config_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：编译旧工具主入口与配置加载器；执行 `python -m unittest discover -s tests -p "test_legacy_ui_defaults.py" -v`；执行 `python scripts/verify_baseline.py`。
- 验证结果：旧工具主入口、配置加载器和测试项配置存储编译通过；`test_legacy_ui_defaults.py` 8 项、`test_test_item_config_store.py` 20 项通过；`python scripts/verify_baseline.py` 全绿（40 个当前主程序 `.py` 编译、编译清单完整、432 项单测、10 个关键基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面分别保存 `telnet_default_on=1/0` 并启动旧工具，确认旧配置镜像和旧工具 Telnet Enable 分别为 `0/1`；同时确认不同 COM、通道组合以及全部清空场景均与新工具一致。

## 2026-08-07 - 旧工具顶部参数统一从 config.ini 加载

- 类型：旧工具独立维护 / 配置化 / BUG 修复 / 测试 / 文档
- 授权边界：项目负责人明确要求修改 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py`；当前 `LineCheckAssistant` 继续直连程控电源，不重新依赖旧工具源码、EXE 或 UI Automation。
- 完成内容：① `config.ini` 新增 `[ui_defaults]`，集中配置 ONU 通信方式、Telnet Enable、程控电源 COM、波特率、默认方案、Startup time、Interval time、Number of tests、Wait command done；② 新增 `config/ui_defaults.py` 负责读取、范围校验和界面加载；③ COM/波特率未出现在启动时下拉列表时自动加入并选中，默认方案按 `[config]` 键名不区分大小写匹配；④ 配置缺失或无效时保留 UI 回退值并输出失败日志，成功时输出实际加载结果；⑤ 修复 Telnet 路径把界面断电间隔错误覆盖为 `telnet_enable_fail_retry_interval` 的问题，两项改用独立变量。
- 当时配置的初始值：`telnet / Telnet Enable=1 / COM105 / 19200 / TEST_PROJECT / 240 / 20 / 500 / 20`；后续已按项目负责人要求删除 `serial_num` 重复配置，改为严格复用新工具 COM（见上一条记录）。
- 修改文件：`README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`Cheating_machine_execution_tool/Auto_power_on_off_tool/config/config.ini`、`Cheating_machine_execution_tool/Auto_power_on_off_tool/config/ui_defaults.py`、`Cheating_machine_execution_tool/Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py`、`Cheating_machine_execution_tool/Auto_power_on_off_tool/test_case/powe_on_off_telnet.py`、`Cheating_machine_execution_tool/tests/test_legacy_ui_defaults.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`。
- 验证方法：编译旧工具主入口、配置加载器和 Telnet 流程；执行 `python -m unittest discover -s tests -p "test_legacy_ui_defaults.py" -v`；执行 `python scripts\verify_baseline.py`。
- 验证结果：旧工具 3 个相关 Python 文件编译通过；`test_legacy_ui_defaults.py` 4 项通过；`python scripts\verify_baseline.py` 全绿（40 个当前主程序 `.py` 编译、编译清单完整、427 项单测、10 个关键基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面启动旧工具，核对九项默认值全部加载；修改 `[ui_defaults]` 后重启，确认界面随配置变化；实际连接 COM105 前确认该串口存在且对应程控电源。

## 2026-08-07 - 确认恢复默认残留 BUG 修复

- 类型：Windows 桌面验收 / 状态更新
- 验收依据：项目负责人确认“BUG 已确认修复”。
- 验收结果：在「测试项配置 → 测试项」使用「恢复默认」后，之前手动添加的测试项命令不再残留；默认命令与旧命令混排、编号重复问题已消除。
- 回归结果：`python scripts\verify_baseline.py` 全绿（40 个 `.py` 编译、编译清单完整、423 项单测、10 个关键基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 状态同步：`ACCEPTANCE_BASELINE.md §2.11` 将该独立交互更新为“已确认验收”；测试项保存后重新加载以及其它页签互不覆盖仍保留为后续确认边界。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。

## 2026-08-07 - 修复恢复默认后残留手动测试项

- 类型：BUG 修复 / 测试 / 文档
- 背景：现场点击「恢复默认」后，之前手动添加的命令仍隔行残留，且新加载的默认命令编号从 01 重新开始，出现重复编号。
- 根因：`load()` 直接遍历 `row_widgets`，而每次调用行的 `remove()` 又会从同一个列表删除当前元素，导致 Python 迭代游标跳过下一行；随后 `row_widgets.clear()` 只清除了引用，未销毁被跳过的 Tk 控件。
- 完成内容：① 新增 `_clear_test_item_rows()`，基于列表快照逐个调用删除逻辑，确保所有旧命令控件均被销毁；② 「恢复默认」与「重新加载」统一复用该安全清理；③ 新增 4 行混合数据回归测试，锁定每一行均被删除且列表最终为空；④ 保留现场已修改的正式 `test_project_config.ini`，不覆盖用户配置，默认模板仍为固定 9 条基线命令。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行 `python -m py_compile line_check_assistant\app.py`、`python -m unittest discover -s tests -p "test_app.py" -v`、`python scripts\verify_baseline.py`。
- 验证结果：`app.py` 编译通过；`test_app.py` 75 项通过，其中混合 4 行清理回归确认所有旧行均执行删除且列表为空；`python scripts\verify_baseline.py` 全绿（40 个 `.py` 编译、编译清单完整、423 项单测、10 个关键基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：旧命令清理已于 2026-08-07 完成 Windows 桌面确认；后续仅需在需要时补充「保存 → 重新加载」持久化及其它三个页签内容不变的现场确认。

## 2026-08-07 - 增加测试项恢复默认配置

- 类型：功能 / 界面 / 测试 / 文档
- 背景：操作员修改 `[order]` 测试项后缺少可回退的固定模板，需要能从「测试项」页一键恢复当前确认的默认测试命令。
- 完成内容：① 将当前 `test_project_config.ini` 完整复制为版本化 `test_project_config.default.ini`；② 「测试项」页底部新增「恢复默认」按钮；③ 点击后先二次确认，只恢复默认模板的 `[order]` 指令重试间隔和 9 条测试命令，不覆盖 Telnet、WiFi、项目信息；④ 恢复结果先进入界面并标记未保存，操作员点击窗口底部「保存」后才写入正式配置；⑤ 主执行日志记录等待确认、取消跳过、失败或恢复成功结果。
- 修改文件：`Cheating_machine_execution_tool/Auto_power_on_off_tool/config/test_project_config.default.ini`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行 `python -m py_compile line_check_assistant\app.py`、`python -m unittest discover -s tests -p "test_app.py" -v`、`python scripts\verify_baseline.py`。
- 验证结果：默认快照与当前 `test_project_config.ini` 逐行一致；`app.py` 编译通过；`test_app.py` 74 项通过；`python scripts\verify_baseline.py` 全绿（40 个 `.py` 编译、编译清单完整、422 项单测、10 个关键基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面修改或删除若干测试项，点击「恢复默认」并确认，核对恢复为 9 条默认命令；再点击「保存」并重新加载，确认正式配置已写回且其它三个页签内容未变化。

## 2026-08-07 - 加宽测试项命令组间距

- 类型：界面优化 / 测试 / 文档
- 背景：「测试项配置」窗口的不同测试项命令组之间仅有 6px 底部间隔，视觉分组过密。
- 完成内容：① 命令组底部间隔从 6px 调整为 14px；② 保持同一命令组内期望条件行的紧凑间距、滚动列表和增删逻辑不变；③ 增加布局回归断言并同步操作说明。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行 `python -m py_compile line_check_assistant\app.py`、`python -m unittest discover -s tests -p "test_app.py" -v`、`python scripts\verify_baseline.py`。
- 验证结果：`app.py` 编译通过；`test_app.py` 72 项通过；`python scripts\verify_baseline.py` 全绿（40 个 `.py` 编译、编译清单完整、420 项单测、10 个关键基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面打开「测试项配置 → 测试项」，确认相邻命令组之间留白更明显且段内布局正常。

## 2026-08-07 - 全流程管道选中态改为勾号

- 类型：界面优化 / 测试 / 文档
- 背景：「全流程执行」窗口左侧管道选择框当前以实心黑块表示选中，不符合操作员希望的标准打勾效果。
- 完成内容：① 7 个管道未选中时继续显示白底黑边空框；② 选中时在框内显示黑色“✓”，不再填充为实心黑块；③ 保持默认只勾选「环境线路检查」、点击方框或任务标题切换、状态刷新和执行逻辑不变。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行 `python -m py_compile line_check_assistant\pipeline_window.py`、`python -m unittest discover -s tests -p "test_pipeline_window.py" -v`、`python scripts\verify_baseline.py`。
- 验证结果：`pipeline_window.py` 编译通过；`test_pipeline_window.py` 15 项通过；`python scripts\verify_baseline.py` 全绿（40 个 `.py` 编译、编译清单完整、419 项单测、10 个关键基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面打开「全流程执行」，确认每个管道选中时显示“✓”、取消后恢复空框。

## 2026-08-07 - 加强已验收功能回归门禁

- 类型：回归约束 / 测试 / 开发流程
- 背景：原 `verify_baseline.py` 能检查编译、全量单测与关键协议字符串，但新增源码可能漏出编译清单，关键测试也可能被删除或改名后仍只剩“全量单测通过”的表象；本地 Git 提交默认不会自动执行门禁。
- 完成内容：① `PY_COMPILE_FILES` 补齐 40 个当前主程序 Python 文件，并新增源码编译清单完整性检查；② 新增 10 个已验收关键行为测试 ID（TFTP 双链路/源 IP 绑定、电源、写参可选命令、全流程顺序与失败停止），全量单测必须实际执行它们；③ 在输出中独立显示 `required_baseline_tests` 结果；④ 新增版本化 `.githooks/pre-commit` 与 `scripts/install_git_hooks.ps1`，首次安装后本地 `git commit` 自动执行基线门禁；⑤ 同步验收基线、项目状态和开发规则，修正状态页历史测试数。
- 修改文件：`AGENTS.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`.githooks/pre-commit`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/scripts/install_git_hooks.ps1`、`Cheating_machine_execution_tool/tests/test_verify_baseline.py`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_verify_baseline.py" -v`、`python scripts\verify_baseline.py`。
- 验证结果：`test_verify_baseline.py` 17 项通过；`python scripts\verify_baseline.py` 全绿（40 个 `.py` 编译、编译清单完整、419 项单测、10 个关键基线测试实际执行、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：远端代码托管启用后，为主分支配置同一基线命令的 CI 必过检查；本地 hook 可被 `git commit --no-verify` 绕过，不能替代远端保护。

## 2026-08-07 - 调整写参可选项勾选标识

- 类型：优化 / 测试 / 文档
- 背景：写样机参数窗口中「清空参数」「退出老化」使用 ttk Clam 主题的选中态，显示为叉号，容易让操作员误判为未选中或否定状态。
- 完成内容：① 两个可选项改用 Windows 原生 `Checkbutton`，选中时显示标准“✓”；② 保持默认不勾选、配置持久化、确认框内容和勾选后才下发对应命令的既有语义不变；③ 补充界面回归断言与操作员说明。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行 `python -m py_compile line_check_assistant\app.py`、`python -m unittest discover -s tests -p "test_app.py" -v`、`python scripts\verify_baseline.py`。
- 验证结果：`test_app.py` 71 项通过；`python scripts\verify_baseline.py` 全绿（29 个 `.py` 编译、413 项单测、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面打开「写样机参数」窗口，确认两个选项选中态为“✓”。

## 2026-07-24 - 串行等待全流程升级与写参完成

- 类型：BUG 修复 / 优化 / 测试 / 文档
- 背景：全流程子任务 3 只启动全包升级 worker 就被标记结束，子任务 4 随即并发启动，导致升级与写参争用同一台样机；此前关闭过写参配置窗口时，子任务 4 还会把已销毁的 `.toplevel...` 作为弹窗父窗口，报 `bad window path name`。
- 完成内容：① 主程序新增管道专用 UI 任务队列，确认框与窗口创建固定在 Tk 主线程；② 子任务 3、4 创建完成事件，worker 的成功/失败完成回调才解除管道等待；③ 管道写参启动时重新打开有效写参窗口；④ 升级/写参未启动、被取消或执行失败会返回管道并阻止后续致命子任务；⑤ 保留 `Tftp指令` / `Tftp Put` 两条独立链路。
- 修改文件：`.claude/plans/pipeline-async-subtask-sequencing.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_app.py" -v`、`python -m unittest discover -s tests -p "test_pipeline_orchestrator.py" -v`；执行 `python scripts/verify_baseline.py`。
- 验证结果：`test_app.py` 70 项通过；`test_pipeline_orchestrator.py` 35 项通过；`python scripts/verify_baseline.py` 全绿（29 个 `.py` 编译、412 项单测、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面选择子任务 3、4，确认日志必须在升级完成结果后才出现「开始子任务 4」，且不再出现 `bad window path name`。

## 2026-07-24 - 对接全流程全包升级入口

- 类型：BUG 修复 / 测试 / 文档
- 背景：全流程子任务 3 选择全包升级后，环境检查通过即报「主程序未实现 `_start_tftp_command_upgrade / _start_tftp_put_upgrade`」并中止。两个名称是管道残留的旧接口，主程序实际入口为 `_start_serial_tftp_copy_upgrade()`。
- 完成内容：① 管道全包升级改调主程序当前存在的统一入口；② 入口仍按当前配置独立分流 `Tftp指令` / `Tftp Put`，未合并两条传输链路；③ 主执行日志输出本次选择的传输方式；④ 新增两种传输方式的回归测试。
- 修改文件：`Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_pipeline_orchestrator.py" -v`；执行 `python scripts/verify_baseline.py`。
- 验证结果：`test_pipeline_orchestrator.py` 34 项通过；`python scripts/verify_baseline.py` 全绿（29 个 `.py` 编译、410 项单测、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面全流程选择子任务 3「全包升级 + Tftp指令」，确认环境检查后出现升级确认框并继续进入对应升级链路。

## 2026-07-24 - 保持写参参数表路径与全流程同步

- 类型：BUG 修复 / 测试 / 文档
- 背景：操作员从全流程子任务 4「写样机参数 → 去配置」选择参数表后，返回全流程仍提示「缺：参数表路径」；重开写参窗口时已选择的路径也丢失。原因是写参窗口每次新建临时路径变量，未更新全流程读取的实例级持久变量。
- 完成内容：① 写参窗口直接复用 `parameter_table_path_var`；② 选表成功后立即更新该变量并触发 `sample_upgrade_settings.ini` 保存；③ 重开写参窗口时自动恢复并加载已保存参数表；④ 已保存文件无法读取时保留路径、写主执行日志并要求操作员重新选择，不误清空配置。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_app.py" -v`、`python -m unittest discover -s tests -p "test_pipeline_window.py" -v`；执行 `python scripts/verify_baseline.py`。
- 验证结果：`test_app.py` 69 项通过；`test_pipeline_window.py` 15 项通过；`python scripts/verify_baseline.py` 全绿（29 个 `.py` 编译、409 项单测、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面选择参数表、关闭并重开写参窗口，确认路径和预检结果恢复；回到全流程点击「刷新状态」或返回后自动刷新，确认「缺：参数表路径」消失。

## 2026-07-24 - 增加全流程状态刷新按钮

- 类型：优化 / 测试 / 文档
- 背景：从去配置窗口返回全流程窗口时，部分 Windows 焦点切换不触发自动刷新，操作员需要额外点击窗口才能看到最新必填项状态。
- 完成内容：① 底部增加「刷新状态」按钮；② 点击只重算当前状态、不执行任何设备或电源操作；③ 保留原有回焦自动刷新。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_pipeline_window.py" -v`；执行 `python scripts/verify_baseline.py`。
- 验证结果：`test_pipeline_window.py` 15 项通过；`python scripts/verify_baseline.py` 全绿（29 个 `.py` 编译、407 项单测、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面从样机升级去配置返回后，点击「刷新状态」确认超级用户名缺项立即消失。

## 2026-07-24 - 刷新全流程升级凭据状态

- 类型：BUG 修复 / 测试 / 文档
- 背景：操作员在「样机升级 → 去配置」窗口已填写超级用户名，但全流程子任务 3 仍提示缺少超级用户名；原因是管道读取了启动时缓存，未读取当前 Tk 输入。
- 完成内容：① 管道上下文优先调用 `_current_sample_upgrade_settings()` 读取升级窗口当前值；② ONU 配置同步优先读取 `_current_onu_registration_config()`；③ 关闭去配置窗口回到全流程窗口时自动刷新状态；④ 增加回归测试，锁定实时输入覆盖旧缓存与回焦刷新。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_pipeline_window.py" -v`；执行 `python scripts/verify_baseline.py`。
- 验证结果：`test_pipeline_window.py` 14 项通过；`python scripts/verify_baseline.py` 全绿（29 个 `.py` 编译、406 项单测、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面在样机升级窗口填写超级用户名后，确认全流程子任务 3 立即不再提示缺少该字段。

## 2026-07-24 - 修正全流程上电指令

- 类型：BUG 修复 / 测试 / 文档
- 背景：现场日志显示全流程子任务「自动上/下电」选择上电时先下发关闭帧再下发开启帧，与主界面自动上电“只发开启帧”的已验收语义不一致。
- 完成内容：① 管道上电分支从 `power_on_selected_channels()` 改为 `turn_on_selected_channels()`；② 上电只下发开启帧，下电仍只下发关闭帧；③ 增加回归测试，锁定上电不得调用断电再上电接口。
- 修改文件：`Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_pipeline_orchestrator.py" -v`；执行 `python scripts/verify_baseline.py`。
- 验证结果：`test_pipeline_orchestrator.py` 33 项通过；`python scripts/verify_baseline.py` 全绿（29 个 `.py` 编译、404 项单测、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：现场再次选择「上电」执行全流程，确认主日志只出现「开启通道」帧、不出现「关闭通道」帧。

## 2026-07-24 - 调整全流程前两项顺序

- 类型：优化 / 测试 / 文档
- 背景：操作员确认全流程执行应先进行自动上/下电，再进行环境线路检查。
- 完成内容：① 子任务 1 改为自动上/下电、子任务 2 改为环境线路检查；② 实际调度、窗口编号、主执行日志编号和顺序守门测试同步调整；③ 环境线路检查仍是致命步骤，但发生在自动上/下电之后；默认仍只选环境线路检查。
- 修改文件：`Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`、`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`.claude/plans/power-before-env-pipeline-order.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_pipeline_orchestrator.py" -v`；执行 `python scripts/verify_baseline.py`。
- 验证结果：`test_pipeline_orchestrator.py` 32 项通过；`python scripts/verify_baseline.py` 全绿（29 个 `.py` 编译、403 项单测、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面确认前两行显示为「1. 自动上/下电」「2. 环境线路检查」；真实样机验证“上下电 → 环境检查”新顺序。

## 2026-07-24 - 修正电源配置弹窗边距

- 类型：BUG 修复 / 测试
- 背景：点击「自动上/下电 → 去配置」时，Tk 报 `bad pad value "-7"`，导致 COM 与操作类型选择弹窗无法打开。
- 完成内容：将 COM 留空提示的负 `pady` 改为非负边距，保留原有弹窗布局、配置保存和「不下发电源指令」语义。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_app.py" -v`；执行 `python scripts/verify_baseline.py`。
- 验证结果：`test_app.py` 67 项通过；`python scripts/verify_baseline.py` 全绿（29 个 `.py` 编译、403 项单测、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面点击「自动上/下电 → 去配置」，确认 COM 与操作类型选择框能正常打开。

## 2026-07-24 - 补全全流程电源配置入口

- 类型：BUG 修复 / 测试 / 文档
- 背景：全流程「自动上/下电」的「去配置」映射 `_open_power_control` 在主程序中不存在，点击后弹出「未找到配置入口」警告。
- 完成内容：① 新增 `_open_power_control`，复用 COM 与上电/下电选择弹窗；② 选择结果同步保存程控电源 COM 和管道 `up/down` 操作类型；③ 刷新全流程本行状态并记录「仅保存配置，未下发任何程控电源指令」，不创建执行线程。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_app.py" -v`；执行 `python scripts/verify_baseline.py`。
- 验证结果：`test_app.py` 66 项通过；`python scripts/verify_baseline.py` 全绿（29 个 `.py` 编译、402 项单测、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面依次点击「自动上/下电 → 去配置」，确认选择 COM / 操作类型后本行摘要刷新且未出现任何电源下发日志。

## 2026-07-24 - 改用实心选择框标识

- 类型：优化 / 测试 / 文档
- 背景：全流程窗口的系统 Checkbutton 选中态显示「×」，操作员要求保留小方框位置但改用更直观的实心黑色状态。
- 完成内容：① 子任务左侧改为 14px 自绘选择框；② 选中填满黑色、未选白底黑边；③ 点击小方框或任务标题均可切换，默认仅选环境线路检查不变。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_pipeline_window.py" -v`；执行 `python scripts/verify_baseline.py`。
- 验证结果：`test_pipeline_window.py` 12 项通过；`python scripts/verify_baseline.py` 全绿（29 个 `.py` 编译、401 项单测、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面打开「全流程执行」窗口，确认选中框为实心黑色。

## 2026-07-24 - 收紧全流程默认勾选

- 类型：优化 / 测试 / 文档
- 背景：操作员要求打开「全流程执行」窗口时只默认选择环境线路检查，避免其它具备设备操作的子任务被预选。
- 完成内容：① 默认仅勾选「1. 环境线路检查」；② 自动上/下电、样机升级、写样机参数、ONU 注册、串口日志、测试项执行均默认不勾选；③ 保持 1→7 固定执行顺序、必填项提示和二次确认不变。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：在主源码目录执行 `python -m unittest discover -s tests -p "test_pipeline_window.py" -v`；执行 `python scripts/verify_baseline.py`。
- 验证结果：`test_pipeline_window.py` 11 项通过；`python scripts/verify_baseline.py` 全绿（29 个 `.py` 编译、400 项单测、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 桌面打开「全流程执行」窗口，确认仅「环境线路检查」处于勾选状态。

## 2026-07-24 - 确认通道与电源其余场景验收

- 类型：真实样机验收 / 状态更新
- 背景：项目负责人补充确认通道 / 网卡 / Ping 与程控电源模块的其余现场场景均已通过，需清理两模块的残留待验收状态。
- 完成内容：① 通道 / 网卡配置、线路 Ping、`network_card_ip.ini` 端到端变更均确认通过；② 自动下电、同批次 COM 长连接复用、1–8 台并行均确认通过；③ 2.1、2.2 状态统一更新为“已确认验收”。
- 修改文件：`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：项目负责人提供的真实样机验收结果。
- 验证结果：真实样机验收通过。
- 后续待办：通道 / 网卡 / Ping 与程控电源模块无；串口终端高频场景及其它独立模块仍按各自验收基线跟踪。

## 2026-07-24 - 确认空 COM 手动重启流程验收

- 类型：真实样机验收 / 状态更新
- 背景：空 COM 展示所有网卡、配置保存，以及手动重启样机后点击确认再继续的流程已完成单元测试，需依据项目负责人现场结果更新验收状态。
- 完成内容：项目负责人确认真实样机验收通过：① COM 留空时展示 PC 中所有识别网卡且空值可保存；② 自动上/下电、全包升级和全流程执行会要求操作员确认样机已手动重启，确认后才继续；③ 全程未向任何程控电源 COM 口下发上下电指令。
- 修改文件：`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：Windows 主界面留空程控电源 COM，核对全网卡下拉候选和配置保存；分别进入自动上/下电、全包升级、全流程执行，手动重启样机后点击“是”确认继续并核对主执行日志。
- 验证结果：真实样机验收通过。
- 后续待办：自动下电、同批次 COM 长连接复用、4 / 8 台并行及通道/网卡其余现场场景仍按验收基线跟踪。

## 2026-07-23 - 支持空 COM 手动重启提示

- 类型：功能 / 测试 / 文档
- 背景：无需程控电源的现场仍被默认 COM 或必填校验限制，且无法在同一界面查看所有本机网卡。
- 完成内容：① 程控电源 COM 下拉新增空值并可持久保存；② 空 COM 时展示所有识别网卡，选择 COM 后仍按每组 8 个 VLAN 筛选；③ 自动上/下电、全包升级（串行/并行、`Tftp指令` / `Tftp Put`）和全流程管道在空 COM 时要求操作员先手动重启样机、点击“是”确认后才开始后续步骤，且不打开程控电源串口；④ 补充配置保存、界面、普通电源 service、升级协调器、Tftp Put 和管道手动重启提示的回归测试。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/config_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/services/power_on_service.py`、`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_channel_config.py`、`Cheating_machine_execution_tool/tests/test_power_supply.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行各专项 unittest；在主源码目录执行 `python scripts\verify_baseline.py`。
- 验证结果：`test_app.py` 65 项、`test_pipeline_window.py` 10 项及其它专项测试通过；基线检查全绿（29 个 `.py` 编译、399 项单测、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：Windows 主界面确认空 COM 可选、展示全部网卡；分别验证全流程和全包升级在空 COM 时主日志显示跳过后仍继续后续步骤。

## 2026-07-23 - 确认 COM 分组筛选真实样机验收

- 类型：真实样机验收 / 状态更新
- 背景：程控电源 COM 与 VLAN 下拉分组筛选已通过 390 项单元测试，需依据项目负责人提供的现场结果确认实际界面行为。
- 完成内容：项目负责人确认现场验收通过：`COM101` 只展示 `VLAN101`–`VLAN108`，`COM102` 只展示 `VLAN109`–`VLAN116`；不自动改写原有通道 VLAN 配置。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：Windows 主界面切换程控电源 `COM101` / `COM102`，打开「通道对应 VLAN」下拉框核对候选范围和已有配置。
- 验证结果：真实样机验收通过。
- 后续待办：网卡刷新、子网配置和线路 Ping 等通道/网卡模块的其余场景仍按验收基线继续跟踪。

## 2026-07-23 - 按程控电源分组筛选 VLAN 网卡

- 类型：优化 / 测试 / 文档
- 背景：主界面切换任意程控电源 COM 口时，「通道对应 VLAN」下拉框仍展示全部 VLAN 网卡，操作员需要手动从无关网卡中辨认本台电源对应范围。
- 完成内容：① 新增 COM 与 VLAN 的每组 8 个映射：`COM101` → `VLAN101`–`VLAN108`、`COM102` → `VLAN109`–`VLAN116`，后续 COM 口顺延；② 切换程控电源 COM 口后立即重建 VLAN 下拉候选，并在主执行日志记录筛选结果；③ 保留已有通道 VLAN 配置，不会因切换 COM 口而自动清空或改写；④ 增加 COM101 / COM102 以及操作员口头 `COM2` 输入的筛选回归测试。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`cd Cheating_machine_execution_tool; python -m unittest discover -s tests -p "test_app.py" -v`；`python -m py_compile line_check_assistant\app.py`；`python scripts\verify_baseline.py`。
- 验证结果：`test_app.py` 62 项通过；`py_compile` 通过；基线检查全绿（29 个 `.py` 编译、390 项单测、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：操作员在线下 Windows 主界面切换 `COM101` / `COM102`，确认 VLAN 下拉候选分别只显示 `VLAN101`–`VLAN108` / `VLAN109`–`VLAN116`；无需真实样机验收。

## 2026-07-23 - 整理项目管理文档

- 类型：文档 / 状态更新
- 背景：项目已具备验收基线、开发记录和回归门禁，但 `PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、操作 README 对测试数、子任务数和路径存在阶段性描述混杂，后续 AI 容易据此产生错误判断。
- 完成内容：① 新增根目录 `README.md` 作为源码入口、文档职责和历史目录边界导航；② 将 `PROJECT_STATUS.md` 收敛为当前状态、待办、关键入口和继续开发命令；③ 将 `ACCEPTANCE_BASELINE.md` 的测试总数改为引用状态页的最近一次记录，保留验收状态与不变量；④ 同步 `AGENTS.md`、工作流说明、操作 README、`.gitignore` 与第三方声明，并修复开发日志中的本地链接。
- 修改文件：`README.md`、`AGENTS.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/THIRD_PARTY_NOTICES.md`、`.claude/skills/line-check-dev/SKILL.md`、`.gitignore`、`DEVELOPMENT_LOG.md`。
- 验证方法：检查文档职责、主源码路径、7 子任务描述、测试基线引用和 Markdown 本地链接；运行 `git diff --check`。
- 验证结果：未修改业务代码、验收状态或历史记录；当前状态文档不再含旧测试总数或 6 子任务描述，Markdown 本地链接检查通过。
- 后续待办：下次业务代码改动前实跑 `python scripts\verify_baseline.py`，以实际结果更新 `PROJECT_STATUS.md` 的最近一次验证记录；凭据模板化、依赖锁定和 CI 仍按独立任务评估。

## 2026-07-23 - 调整测试项配置入口位置

- 类型：优化 / 文档
- 背景：用户要求将主界面「测试项配置」按钮移动到截图红框所示的「2 配置测试参数」卡片右上角。
- 完成内容：保持按钮文字、样式与 `_open_test_item_config` 打开逻辑不变；从常用工具栏移除，改放到「2 配置测试参数」标题右侧。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile line_check_assistant\app.py` 与 `python scripts\verify_baseline.py`；启动源码界面后核对按钮位置并点击确认仍能打开配置窗口。
- 验证结果：`py_compile` 通过；`python scripts\verify_baseline.py` 全绿（29 个 .py 编译、388 项单测、8 条 MUST_EXIST 与 1 条 MUST_NOT_EXIST 均通过）。
- 后续待办：用户在线下 Windows 桌面确认截图箭头所示位置符合预期。

## 2026-07-20 - 「全流程执行」管道编排器（主界面「检查并执行测试」按钮升级）

- 类型：功能 / 重构 / 测试 / 文档
- 背景：用户对 `app.py:431` 的「检查并执行测试」按钮不满意——当前只调 `_start_all_checks` 做已勾选通道的 ping 通过性检查，不消费 `test_project_config.ini` 的 `[order]` 段。**用户目标**：把「自动上/下电 / 样机升级 / 写样机参数 / ONU 注册 / 串口日志 / 测试项配置」6 个已有功能作为可勾选的子任务，由用户勾选后按 1→6 固定顺序串行执行，任一失败（串口日志除外）→ 整个管道停止；用户连接好样机 + 填好所有配置后，一键跑通全流程。
- 完成内容：
  1. **`src/core/fuzzy_match_runner.py`（新）** —— 移植老工具 [Auto_power_on_off_tool/common/fuzzy_match.py](Cheating_machine_execution_tool/Auto_power_on_off_tool/common/fuzzy_match.py) 的 per-segment `!A&&B` 语义；纯函数无 IO，`match_expected(result, expected) -> bool` 入口；`iter_segments(expected)` 暴露拆分；老工具 `tcapi get WanInfo_Entry` IPv6 特殊分支不移植（用 `re.escape` 保证「字面匹配」）。AGENTS 硬规则：不改老工具源码，独立模块移植。
  2. **`src/services/test_item_execution_service.py`（新）** —— 跑 `[order]` 段的 service：单台样机 → `prepare_network_for_sample` 切网卡 IP → `TelnetSession`（复用 `src/core/telnet_transport.py`）按 VLAN `bind_ip` 锁源 → `_login` 按 `telnet.input_user_flag` / `input_password_flag` / `login_success_flag` 三段登录 → 顺序执行 `[order]` 每条命令：send_line → `_read_until_stable`（连续 `READ_STABLE_SECONDS=1.0s` 无新数据 / 总 `READ_MAX_SECONDS=8.0s` 视完成）→ `match_expected` 判定 → 失败重试 `retry_times` 次（间隔 `command_fail_retry_interval_time` 秒）→ per-channel 结果文件 `Cheating_machine_execution_tool/test_results/device_{section}_command_results_{YYYYMMDD_HHMMSS}.log`。返回 `TestItemRunResult{channel_section, total, passed, failed, log_path}`；网络/登录失败抛 `RuntimeError`，由编排器统一 stop pipeline。
  3. **`src/services/pipeline_orchestrator.py`（新）** —— 全流程执行管道：`PipelineContext` 包装 app + 通道 + 3 个 store + serial_log_dir；`compute_all_subtask_statuses(ctx)` 6 子任务必填项评估；`PipelineOrchestrator.run(selected: set[str])` 按 `SUBTASK_CODES` 1→6 固定顺序执行勾选子任务；每个子任务调 `app._start_*` 方法（既有逻辑，不重写）或直接调 service（1 电源 / 6 测试项）；致命失败抛 `PipelineError` + 停止后续；`NON_FATAL_SUBTASKS = {"serial_terminal"}` 失败只记结果；`request_stop()` 在当前子任务结束后终止后续。
  4. **`line_check_assistant/pipeline_window.py`（新）** —— 「全流程执行」弹窗 UI（`Toplevel(780x560)` + 6 行 Checkbutton + 必填项状态 + 「去配置」按钮 + 「开始执行 / 停止 / 取消」）；每行右侧实时刷新「必填项当前状态」（绿色就绪 / 红色「缺: 字段1, 字段2」），「去配置」按钮调 `app._open_power_control` / `_open_upgrade_module` 等 6 个既有子窗口方法；「开始执行」走「必填项未就绪警告 + 全流程执行确认」二次确认后启动后台线程；主线程 UI 回调用 `window.after(0, ...)`；emit 投到主程序 `log_queue`。
  5. **`line_check_assistant/sample_upgrade_settings_store.py`（改）** —— `SampleUpgradeSettings` 新增 `power_operation: str = "up"`（"up"/"down"，非法值 save 时回退 "up"）+ `parameter_table_path: str = ""`；load/save 同步；老 ini 兼容回退默认；与既有 `parameter_initial_*` / `parameter_clear_*` / `parameter_exit_aging` 同级存到 `[sample_upgrade]` 段。
  6. **`line_check_assistant/app.py`（改）** —— `__init__` 新增 `self.pipeline_window = None`；新增 `self.power_operation_var = StringVar(value=settings.power_operation)` + `self.parameter_table_path_var = StringVar(value=settings.parameter_table_path)`，加入 `_bind_sample_upgrade_autosave` 的 trace_add 列表；`_current_sample_upgrade_settings` 透传这 2 个字段（`power_operation` 做 "up"/"down" 归一化，`parameter_table_path` 做 `.strip()`）；`_start_all_checks` 改为弹窗入口（`PipelineWindow(self)`），保留旧的 `_run_checks` / `_check_worker` 兜底用。
  7. **`src/services/__init__.py`（改）** —— 新增 `pipeline_orchestrator` / `test_item_execution_service` 模块的 re-export（`PipelineContext` / `PipelineError` / `PipelineOrchestrator` / `SubTaskResult` / `SubTaskStatus` / `compute_all_subtask_statuses` / `TestItemRunRequest` / `TestItemRunResult` / `build_log_path` / `run_test_item_execution` / `*_SECONDS` 等常量），`__all__` 同步。
  8. **`scripts/verify_baseline.py`（改）** —— `PY_COMPILE_FILES` 增 3 个路径：`src/core/fuzzy_match_runner.py` / `src/services/pipeline_orchestrator.py` / `src/services/test_item_execution_service.py` + `line_check_assistant/pipeline_window.py`。
  9. **测试** —— 新增 4 个测试文件共 61 项：`tests/test_fuzzy_match_runner.py`（18：单段 / 多段 / 否定 / 混合 / 空段 / re.escape / IPv6 边界 / 性能）+ `tests/test_test_item_execution_service.py`（14：单条匹配 / 失败重试 / 重试成功 / per-segment !A&&B / 无期望默认通过 / 多条顺序 / 网络准备失败 / 登录失败 / 结果文件创建 / session finally 关闭 / build_log_path / 常量）+ `tests/test_pipeline_orchestrator.py`（26：6 子任务状态评估 / run 顺序 / 致命失败抛 PipelineError / 串口失败不阻塞 / request_stop 阻止后续 / 6 个子任务 statuses 完整性 / 必填项 missing 标记）+ `tests/test_sample_upgrade_settings_store.py`（+3：power_operation / parameter_table_path 持久化 / power_operation 非法值回退 `up`）；同时 `tests/test_app.py` 的 2 项 `_current_sample_upgrade_settings` mock 补齐 2 个 StringVar。
- 修改文件：`Cheating_machine_execution_tool/src/core/fuzzy_match_runner.py`（新）、`Cheating_machine_execution_tool/src/services/test_item_execution_service.py`（新）、`Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`（新）、`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`（新）、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/services/__init__.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/tests/test_fuzzy_match_runner.py`（新）、`Cheating_machine_execution_tool/tests/test_test_item_execution_service.py`（新）、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`（新）、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：
  ```powershell
  cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
  python -m py_compile src\core\fuzzy_match_runner.py src\services\test_item_execution_service.py src\services\pipeline_orchestrator.py line_check_assistant\pipeline_window.py line_check_assistant\sample_upgrade_settings_store.py line_check_assistant\app.py
  python -m unittest discover -s tests -v
  python scripts\verify_baseline.py
  ```
- 验证结果：`py_compile` 通过；完整单测 `Ran 374 tests ... OK`（原 313 + 新增 18 fuzzy + 14 test_item + 26 pipeline + 3 settings）；`verify_baseline.py` `ALL CHECKS PASSED`，exit 0（29 个 .py 编译 + 374 项单测 + 8 条 MUST_EXIST 全部命中 + 1 条 MUST_NOT_EXIST 全程不出现）。
- 后续待办：
  - 用户线下 Windows 桌面打开「全流程执行」窗口核对：① 6 行 Checkbutton / 必填项状态表 / 「去配置」按钮 ② 二次确认弹框「必填项未就绪警告 + 全流程执行确认」 ③ 主执行日志按「=== 开始子任务 N === → ... → === 结束子任务 N ===」输出 ④ 任一「致命」失败弹错误框 + 停止后续
  - 用户在主程序配置好「全流程」所有必填项后，真实样机端到端跑通 6 子任务全流程：上下电 → 升级 → 写参 → ONU 注册 → 串口日志（持续）→ [order] 执行
  - 异常场景验证：2/3/4 异步子任务（升级 / 写参 / ONU 注册）失败如何传播到编排器（当前靠主程序 worker 异常冒泡 + 用户观察主执行日志；是否需要 polling 状态轮询机制待 v2 评估）
  - v2 候选：多通道并行、test_number 循环、WiFi 验证子任务、钉钉/邮件上报

## 2026-07-20 - 「全流程执行」第二轮：新增「1. 环境线路检查」子任务（6→7 项 / 编号顺延）

- 类型：功能追加 / 测试 / 文档
- 背景：用户线下看 6 子任务窗口截图后反馈:在最前面（1. 自动上/下电 之前）需要增加一项「环境线路检查」作为整个管道的预校验门——网络不通时上下电 / 升级 / 写参都无意义。三轮 AskUserQuestion 已确认:① 检查范围 = Ping + 必填项预校验（更严格）;② 失败处理 = 致命失败（与 2/3/4/7 同款）;③ 「去配置」按钮 = 调起现有网络配置页（主界面顶部 VLAN / IP 区）。
- 完成内容:
  1. **`src/services/pipeline_orchestrator.py`（改）** —— `SUBTASK_CODES` 在最前面插入 `env_check`,7 项顺序 `env_check → power_cycle → sample_upgrade → sample_parameter_write → onu_registration → serial_terminal → test_item_execution`;`SUBTASK_LABELS` 编号顺延 1→2 ... 6→7;`SUBTASK_CONFIG_TARGETS["env_check"] = "_open_network_config"`;新增 `_summarize_env_check()` —— 校验每通道 `vlan_name / adapter_alias / network_card_ip / device_manage_ip` 全部非空（复用 `_validate_channels()` 校验逻辑的字段子集）;新增 `_run_env_check()` —— 复用 `network_ops.run_line_check()` 逐通道 ping,任一失败抛 `RuntimeError` → 编排器捕获后抛 `PipelineError` 终止管道;`_SUMMARIZERS` 注册 `env_check`;`_run_subtask` 的 runner dict 头部加 `"env_check": self._run_env_check`。
  2. **`line_check_assistant/app.py`（改）** —— 在 `_open_sample_parameter_writer` 旁边新增 `_open_network_config()` 占位方法:隐藏全流程执行窗口（`withdraw`）+ 主界面 `deiconify/lift/focus_force` + `_log` 提示「请在主界面顶部「网络配置」卡片编辑 VLAN / 网卡 / PC 静态 IP / 样机管理 IP;完成后再次点击「检查并执行测试」重开全流程执行窗口」。无独立子窗口,不引入新 Tk 实例,符合 v1 范围。
  3. **`line_check_assistant/pipeline_window.py`（改）** —— `_build_row` 的 `default_checked` 集合加 `env_check`,1/2/6/7 默认勾选（3/4/5 默认不勾,需预先配置）。
  4. **`tests/test_pipeline_orchestrator.py`（改+新增 5 项）** —— 头部 docstring「6 个 sub-task」→「7 个 sub-task」;`PipelineRunOrderTests` docstring「1→6」→「1→7」;`test_run_all_six_subtasks_in_order` 改名为 `test_run_all_seven_subtasks_in_order`,断言 `len(results) == 7`;`test_run_only_selected_subtasks` 改用 `{"env_check", "power_cycle", "test_item_execution"}`;`test_fatal_subtask_failure_raises_pipeline_error` 新增 `method_mocks["env_check"].assert_called_once()` + 失败消息断言改 `"子任务 3. 样机升级 失败"`;`test_non_fatal_subtask_failure_continues` 注释改「7 项全选」;`test_request_stop_skips_subsequent_subtasks` 改用 `env_check` 触发 stop;`ConstantsTests.test_subtask_codes_in_order` 改 7 元组;新增 `test_subtask_labels_numbering_is_one_to_seven` —— 守门 `SUBTASK_LABELS` 编号 1→7;新增 4 项 `ComputeSubTaskStatusTests.test_env_check_status_*`（complete / no_enabled_channels / missing_vlan / missing_multiple_fields）。**26 → 31 项**。
  5. **`tests/test_pipeline_window.py`（改）** —— `_build_context` 路径测试断言改 `len(statuses) == 7` + 枚举加 `env_check`。
- 修改文件: `Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`、`ACCEPTANCE_BASELINE.md`（§2.12 全文 6→7 项 / 子任务编号 / 1 改 `_open_network_config` / 26 项 → 31 项 / 374 → 381 项）、`PROJECT_STATUS.md`（能力矩阵行 6 → 7 / 374 → 381 项）、`DEVELOPMENT_LOG.md`。
- 验证方法: `python -m py_compile src\services\pipeline_orchestrator.py line_check_assistant\pipeline_window.py line_check_assistant\app.py`;`python -m unittest discover -s tests -p "test_pipeline_orchestrator.py" -v`（应 31 项 OK）;`python -m unittest discover -s tests -p "test_pipeline_window.py" -v`（应 2 项 OK）;`python scripts\verify_baseline.py`（应 `ALL CHECKS PASSED`,381 项单测）。
- 验证结果: py_compile OK;`test_pipeline_orchestrator.py` 31 项 OK（26 + 4 env_check evaluate + 1 label-numbering）;`test_pipeline_window.py` 2 项 OK;`verify_baseline.py` `ALL CHECKS PASSED`(29 个 .py / **381** 项单测全绿,原 376 + 本轮新增 5 项)。
- 后续待办:
  - 用户线下 Windows 桌面重新打开「全流程执行」窗口核对 7 行(新 1. 环境线路检查 在最前);状态显示正确;`env_check` 默认勾选;「去配置」按钮隐藏窗口 + 主界面提示正常出现
  - 真实样机端到端跑通 7 子任务全流程:环境检查 → 上下电 → 升级 → 写参 → ONU 注册 → 串口日志（持续）→ [order] 执行
  - 异常场景验证:env_check 任一通道 ping 不通 → 整个管道停止（致命失败规则生效）;3/4/5 异步子任务失败传播机制评估
  - v2 候选:并行 ping 多通道;env_check 失败非致命化选项;网络配置做成独立子窗口

## 2026-07-20 - 「全流程执行」窗口尺寸 + 必填项状态计算修复（第二次：`_get_attr` 拿模块常量）

- 类型：BUG 修复 / 测试
- 背景：用户线下试运行「全流程执行」窗口(2026-07-20 提交后)报「6 行必填项状态全显示『无法计算状态』+ 错误 `'NoneType' object is not iterable`」。同一会话早先已修过一次(改 `resolve_config_dir()` 调用 → `app.TEST_ITEM_CONFIG_PATH`)，但**第一次修没修干净**——`TEST_ITEM_CONFIG_PATH` 是 `line_check_assistant/app.py:84` 的**模块级常量**,不是 `LineCheckAssistant` 实例属性,用 `_get_attr(app, "TEST_ITEM_CONFIG_PATH")` 仍拿到 `None`,后续 `configparser.read(None)` 抛 `TypeError: 'NoneType' object is not iterable`。
- 根因：
  1. `pipeline_window.py:38-39` 初始 / 最小尺寸过小(560 / 520),6 行 + 标题 + 按钮至少 640px。
  2. `_build_context` 上次改错位置——应该从 `line_check_assistant.app` **模块**直接取常量,而不是从 app 实例取(`getattr(app_instance, "TEST_ITEM_CONFIG_PATH", None)` 永远拿到 `None`)。
- 完成内容:
  1. **`line_check_assistant/pipeline_window.py`（再次修）** — `_build_context` 把 `_get_attr(app, "TEST_ITEM_CONFIG_PATH")` 改为 `import line_check_assistant.app as _app_module; _app_module.TEST_ITEM_CONFIG_PATH`,从模块直接取常量;`_get_attr` 调用位置全部加注释说明 `TEST_ITEM_CONFIG_PATH` 在模块上、不在实例上。
  2. **`tests/test_pipeline_window.py`(新)** — 2 项回归测试:① 静态源码断言 `_build_context` 不能再用 `_get_attr(app, "TEST_ITEM_CONFIG_PATH")`,且必须 `import line_check_assistant.app` + 访问 `TEST_ITEM_CONFIG_PATH`(防止以后误回滚);② 构造最小 `FakeApp`(无 tk、无实例属性),按 `_build_context` 的真实路径构造 `PipelineContext` 调 `compute_all_subtask_statuses`,断言 6 个子任务全部返回 `SubTaskStatus` 且不抛——直接复现并锁定 `'NoneType' object is not iterable` 这个 bug 不再回归。
- 修改文件: `Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`(新)、`DEVELOPMENT_LOG.md`。
- 验证方法: `python -m py_compile line_check_assistant/pipeline_window.py`;`python -m unittest discover -s tests -p "test_pipeline_window.py" -v`(应 2 项 OK);`python scripts\verify_baseline.py`(应 `ALL CHECKS PASSED`)。
- 验证结果: py_compile OK;`test_pipeline_window.py` 2 项 OK;`verify_baseline.py` `ALL CHECKS PASSED`(29 个 .py / **376** 项单测全绿,原 374 + 本轮新增 2)。
- 后续待办: 用户重新打开「全流程执行」窗口核对 6 行必填项状态显示正常,不再出现「无法计算状态 / 'NoneType' object is not iterable」;窗口高度能容纳所有 6 行 + 底部「开始执行 / 停止 / 取消」按钮。

## 2026-07-20 - Telnet Tab 顶部增加「Telnet 默认已开启」Checkbutton

- 类型：功能追加 / 测试 / 文档
- 背景：用户在线下「测试项配置 → Telnet」Tab 截图下方指出:在「Telnet 连接参数」标题与 `request_url` 之间留出空位,需要插入一个「Telnet 默认已开启」Checkbutton,默认勾选,由用户在 UI 中自行选择是否保留勾选状态(Q1=A 仍生效——仅编辑器,主程序不消费)。本轮沿用既有 `xxx_flag: int = 0` 风格:dataclass 字段名 `telnet_default_on: int = 1`,ini key `telnet_default_on`;`_dump_telnet` 强制 0/1 转换避免保存 `True`/`False`;`_load_telnet` 老 ini 缺该 key 时回退 1,与 dataclass 默认一致,保持向后兼容(不破坏已有 11 个 telnet 字段的回退行为)。
- 完成内容:
  1. **`line_check_assistant/test_item_config_store.py`** —— `TelnetSettings` 在 `only_power_off_on` 之后新增 `telnet_default_on: int = 1`(注释说明「默认 1 = 勾选,老 ini 缺 key 时回退 1」);`_load_telnet` 新增 `parser.get(section, "telnet_default_on", fallback="1")` + `_parse_int(..., 1)`,与其他 flag 同款 _parse_int 兜底;`_dump_telnet` 末尾新增 `"telnet_default_on": str(1 if bool(telnet.telnet_default_on) else 0)`,与 `connect_wifi.enable` 同款 0/1 强制转换。`enable` 字段 0/1 转换、`bool` 防 `True/False` 落盘等既有约定保持。
  2. **`line_check_assistant/app.py`** —— `_build_test_item_telnet_tab` 新增 `telnet_default_on_var = IntVar(value=telnet.telnet_default_on)` 并加入 `mark_dirty` trace_add 列表;在标题(原 row 0)与 `request_url` 之间新增 `Checkbutton(... text="Telnet 默认已开启(telnet_default_on = 1,默认勾选)", variable=telnet_default_on_var, onvalue=1, offvalue=0, ...)`,grid 到 row 1 / columnspan=3;原 `request_url` 行的 row 1→2、`user` 2→3、`password` 3→4、`port` 4→5、`timeout` 5→6、`input_user_flag` 6→7、`input_password_flag` 7→8、`login_success_flag` 8→9、`telnet_need_enter_password_flag` 9→10、`telnet_no_user_password_flag` 10→11、`only_power_off_on` 11→12,所有 row 全部统一下移 1 行;`capture` / `load` 同步处理 `telnet_default_on`(`.get()` / `.set(int(...))`)。`save` 二次确认弹窗「Telnet 字段:11 项」自动由 `len(captured.telnet.__dict__)` 计算得出 12,不需要手改。
  3. **`tests/test_test_item_config_store.py`** —— `test_load_defaults_when_config_is_missing` 末尾追加 `assertEqual(loaded.telnet.telnet_default_on, 1)`;`test_load_tolerates_unknown_keys` 末尾追加 `assertEqual(loaded.telnet.telnet_default_on, 1)` 验证老 ini 缺该 key 时回退 1;`test_save_and_load_round_trip` round-trip 数据加 `telnet_default_on=0`(显式非默认 1,验证非默认值也能往返),`self.assertEqual(loaded.telnet, saved.telnet)` 后追加 1 行 `assertEqual(loaded.telnet.telnet_default_on, 0)` 与落盘文本断言 `telnet_default_on = 0`;新增 `test_telnet_default_on_saves_as_zero_or_one`(参照 `test_connect_wifi_enable_serializes_as_zero_or_one` 模式,循环 4 种 raw_value(1/0/True/False) 验证落盘为 `1` / `0`)。312 → 313 项。
  4. **`line_check_assistant_README.md`** —— 「测试项配置窗口」段 Telnet Tab 描述:从「11 个字段」改为「12 个字段」;新增顶部「Telnet 默认已开启」Checkbutton 说明(默认 1 = 勾选,可由用户切换);其余字段顺序不变。
  5. **`PROJECT_STATUS.md`** —— 能力矩阵行:「测试项配置 ini 编辑器」描述增加「Telnet Tab 顶部『Telnet 默认已开启』Checkbutton 默认勾选」;单元测试行从 312 改 313。
- 修改文件: `Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_test_item_config_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法: `python -m py_compile line_check_assistant/app.py line_check_assistant/test_item_config_store.py`;`python -m unittest discover -s tests -v`(应 `Ran 313 tests ... OK`,原 312 + 本轮新增 1);`python scripts\verify_baseline.py`(应 `ALL CHECKS PASSED`)。
- 验证结果: `py_compile` 通过;完整单测 `Ran 313 tests ... OK`(原 312 + 新增 1 项 `test_telnet_default_on_saves_as_zero_or_one`);`verify_baseline.py` 全绿,exit 0。
- 后续待办: 用户线下 Windows 桌面打开「测试项配置 → Telnet」Tab,核对:① 标题下方出现「Telnet 默认已开启(telnet_default_on = 1,默认勾选)」Checkbutton,默认已勾选;② 取消勾选后「重新加载」会按磁盘值恢复;③ 显式关掉后保存,二次确认弹窗「Telnet 字段:12 项」行可见,落盘 ini 中 `telnet_default_on = 0`;④ 显式勾选后保存,落盘 ini 中 `telnet_default_on = 1`;⑤ 关闭再开,首次打开的 ini 若没有该 key,Checkbutton 默认仍是勾选状态(老 ini 向后兼容)。

## 2026-07-20 - 项目信息 Tab 增加「内部软件版本」字段

- 类型：功能追加 / 测试 / 文档
- 背景：上一轮在「测试项配置」窗口新增「项目信息」Tab 时,仅含 3 个字符串字段(项目名称 / 软件版本 / ONU 软件编译时间)。用户线下试用后反馈:现场场景下「软件版本」(对外版本号,例如 `V1.0.2-beta`)与「内部软件版本」(内部构建号,例如 `S13.58.01.001`)通常不同,操作员需要同时记录两个值用于和样机实际输出对照。本轮在「软件版本」下方插入新字段 `internal_software_version`,**仍 Q1=A**(仅编辑器,主程序不消费)。
- 完成内容:
  1. **`line_check_assistant/test_item_config_store.py`** —— `ProjectInfoSettings` 在 `software_version` 与 `onu_compile_time` 之间新增 `internal_software_version: str = ""`(默认空串);`_load_project_info` 新增 `parser.get(section, "internal_software_version", fallback="")`,老 ini 缺该 key 时回退空串;`_dump_project_info` 新增 `internal_software_version` key,落盘顺序固定在 `software_version` 之后。`enable` 0/1 转换 / `bool` 防 `True/False` 落盘等既有约定不动。
  2. **`line_check_assistant/app.py`** —— `_build_test_item_project_info_tab` 新增 `internal_software_version_var` 第三个 `StringVar`,加入 `mark_dirty` trace_add 列表;`text_field(3, "内部软件版本", internal_software_version_var)` 插入到 `软件版本`(row 2)与 `ONU 软件编译时间` 之间,原 ONU 行下移到 row 4,底部说明 Label 下移到 row 5;`capture` / `load` 同步处理新字段(`.strip()` 写入,`or ""` 防御性回退)。`save` 二次确认弹窗项目信息行追加「内部软件版本=…」。
  3. **`tests/test_test_item_config_store.py`** —— `test_load_defaults_when_config_is_missing` 末尾 3 行 assert 扩为 4 行(增加 `internal_software_version == ""`);`test_project_info_save_and_load_round_trip` round-trip 数据加 `internal_software_version="S13.58.01.001"`,落盘文本断言增加 `internal_software_version = S13.58.01.001`;`test_project_info_load_tolerates_missing_section` 末尾 3 行 assert 扩为 4 行。**不新增测试,只扩展既有 3 项**——`test_load_defaults_when_config_is_missing` / `test_project_info_save_and_load_round_trip` / `test_project_info_load_tolerates_missing_section` 3 项测试总数不变。
  4. **`line_check_assistant_README.md`** —— 「测试项配置窗口」段项目信息 Tab 描述从「3 个字符串字段(项目名称 / 软件版本 / ONU 软件编译时间)」改为「4 个字符串字段(项目名称 / 软件版本 / **内部软件版本** / ONU 软件编译时间)」。
- 修改文件: `Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_test_item_config_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`。
- 验证方法: `python -m py_compile line_check_assistant/app.py line_check_assistant/test_item_config_store.py`;`python -m unittest discover -s tests -v`(应仍 `Ran 312 tests ... OK`,原 312 + 本轮 0 新增);`python scripts\verify_baseline.py`(应 `ALL CHECKS PASSED`)。
- 验证结果: `py_compile` 通过;完整单测 `Ran 312 tests ... OK`(不增测试计数,仅扩展既有 3 项的断言 / round-trip 数据);`verify_baseline.py` 全绿,exit 0。
- 后续待办: 用户线下 Windows 桌面打开「测试项配置 → 项目信息」Tab,核对:① 第 3 行新增「内部软件版本」Label + 输入框;② 填入内部版本后点「保存」,二次确认弹窗项目信息行出现「内部软件版本=…」;③ 保存后点「重新加载」,内部软件版本值恢复;④ 关闭再开,磁盘 ini `[project_info]` 段含 `internal_software_version` 行,顺序在 `software_version` 之后、`onu_compile_time` 之前。

## 2026-07-20 - 测试项配置窗口新增「项目信息」Tab（Q1=A 第 4 段）

- 类型：功能 / 测试 / 文档
- 背景：用户在线下「测试项配置」窗口下提出：在三 Tab 之外**新增一个「项目信息」Tab**,配置可供参考的项目基础信息（项目名称 / 软件版本 / ONU 软件编译时间），用于操作员在主程序执行过程中肉眼对照样机实际值（如 `bbfdm` / `ifconfig` 输出中的版本号与编译时间）。本轮遵循既有 Q1=A 决策——**仅做编辑器,不被主程序消费**,不接任何自动比对/上报/写设备流程。新增 ini 段 `[project_info]`,字段全部按字符串存取(编译时间不强制 ISO 格式),与现有三 Tab 的实现模式完全对齐。
- 完成内容:
  1. **`line_check_assistant/test_item_config_store.py`** —— 新增 `PROJECT_INFO_SECTION = "project_info"` 模块级常量与 `ProjectInfoSettings` dataclass(3 字段默认空串: `project_name` / `software_version` / `onu_compile_time`);`TestProjectConfig` 新增 `project_info: ProjectInfoSettings` 字段(排在最末,与既有三段顺序保持向后兼容);`load()` 调新私有方法 `_load_project_info`;`save()` 在末位 `parser[PROJECT_INFO_SECTION] = self._dump_project_info(...)`;新增 `_load_project_info` / `_dump_project_info` 私有方法,沿用 `_load_connect_wifi` / `_dump_connect_wifi` 的风格——老 ini 缺 `[project_info]` 段时 3 字段全部回退空串,**不抛 `NoSectionError`**;`__all__` 末尾追加 `"PROJECT_INFO_SECTION"` / `"ProjectInfoSettings"`。`enable` 0/1 强制转换、`bool` 防 `"True"`/`"False"` 落盘等既有约定不动,本段无 `enable` 字段无需做 0/1 转换。
  2. **`tests/test_test_item_config_store.py`** —— import 加 `ProjectInfoSettings`;`test_load_defaults_when_config_is_missing` 末尾追加 3 行断言 `[project_info]` 段缺省时 3 字段默认空串;新增 `test_project_info_save_and_load_round_trip`(含中文 / 空格 / 常见符号的 round-trip + 落盘文本含 `[project_info]` 段 3 行);新增 `test_project_info_load_tolerates_missing_section`(手写不含 `[project_info]` 段的 ini,验证 `load` 不抛 `NoSectionError` 且 3 字段为空)。原 16 项 → 18 项。
  3. **`line_check_assistant/app.py`** —— import 加 `ProjectInfoSettings`;`_open_test_item_config` 顶部描述从「telnet / 测试项命令 / WiFi 连接」扩为「telnet / 测试项命令 / WiFi 连接 / 项目信息」;新增第 4 次 `_build_test_item_project_info_tab(notebook, config.project_info, mark_dirty)` 调用;`reload` 内追加 `project_info_vars["load"](reloaded.project_info)`;`save` 内 `TestProjectConfig(...)` 多传 `project_info=project_info_vars["capture"]()`,二次确认弹窗追加「项目信息：项目=…,软件版本=…,编译时间=…」(空值显示「(空)」)一行。新增私有方法 `_build_test_item_project_info_tab`:2 列 grid + 标题 + 3 行 Label+`ttk.Entry`(与 `_build_test_item_wifi_tab` 同风格),`capture` 对 3 字段 `get().strip()`,`load` 直接 `var.set(...)`;`trace_add("write", lambda *_a: mark_dirty())` 模式与既有三 Tab 完全一致,dirty 跟踪自动覆盖。窗口几何 960x940 高度足够,`minsize` 不动。
  4. **`line_check_assistant_README.md`** —— 「测试项配置窗口」段:「三 Tab 结构」改为「四 Tab 结构」;新增第 4 项「项目信息」描述(3 字段 + 仅编辑器 + 自由文本 + 肉眼对照样机值);保留前 3 Tab 描述不变。
  5. **`PROJECT_STATUS.md`** —— 能力矩阵行:把「测试项配置 ini 编辑器(3 Tab / Q1=A 不接执行)」改为「4 Tab: Telnet / 测试项 / WiFi / 项目信息」,状态加注「310 → 313 项」;单元测试行从 310 改 313;「已完成」段(原 line 52)把「三 Tab」改为「四 Tab」并新增项目信息 Tab 描述。
  6. **`ACCEPTANCE_BASELINE.md`** —— 本轮**不**新增独立 §2.x(原文件就没有为「测试项配置」单列条目,且本轮 Q1=A 不变,加 §2.x 会与既有叙述重复);等用户线下真实样机交互验证 4 Tab 行为后,再单独评估是否补 §2.x。
- 修改文件: `Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_test_item_config_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法: `python -m py_compile line_check_assistant/app.py line_check_assistant/test_item_config_store.py`;`python -m unittest discover -s tests -v`(应 `Ran 312 tests ... OK`,原 310 + 本轮新增 2);`python scripts\verify_baseline.py`(应 `ALL CHECKS PASSED`,exit 0)。
- 验证结果: 完整单测 `Ran 312 tests ... OK`(原 310 + 项目信息 2 项;`test_load_defaults_when_config_is_missing` 末尾追加 3 行 `[project_info]` 默认回退断言,不增加测试计数);`verify_baseline.py` 全绿,exit 0;`py_compile` 通过。
- 后续待办:
  - 用户线下 Windows 桌面打开「测试项配置」窗口,核对:① 第 4 个 Tab 显示「项目信息」;② 顶部描述包含「项目信息」;③ 首次打开 3 字段默认值都是空;④ 填值后点「保存」,二次确认弹窗项目信息一行显示填入的 3 个值;⑤ 保存后点「重新加载」,3 字段值恢复;⑥ 关闭再次打开,磁盘 ini 中存在 `[project_info]` 段且 3 字段写入正确(中文 / 空格 / 符号保留)。
  - 若用户希望对项目信息 Tab 加额外的「产品系列 / 硬件版本 / 备注 / 测试员」等字段,可在 `ProjectInfoSettings` dataclass 与 UI `_build_test_item_project_info_tab` 内叠加(`_dump_project_info` / `_load_project_info` 自动覆盖新 key),不在本轮范围。

## 2026-07-20 - 建立 verify_baseline.py 回归门禁 + AGENTS.md 加验收同步硬规则

- 类型：基础设施 / 文档 / 测试
- 背景：项目早期 QA 报告（2026-07-20）指出**核心质量缺口**：① 无 CI/CD，测试靠手动跑；② 无自动化机制拦截破坏已验收功能的改动；③ `ACCEPTANCE_BASELINE.md §1.3` 的 8 条 grep 不变量没自动跑；④ `AGENTS.md` 规则 5/11 漏列 `ACCEPTANCE_BASELINE.md`，人类开发者读 AGENTS.md 不会知道还要同步 baseline。本轮建立最低门禁：单一脚本 `scripts/verify_baseline.py` 封装 `§0` + `§1.3` + `§1.4` 全部检查，AGENTS.md 升级为「提交前必须跑 verify_baseline 全绿」硬规则。
- 完成内容：
  1. **`Cheating_machine_execution_tool/scripts/verify_baseline.py`（新）** —— 4 类检查：① `py_compile` 对 `PY_COMPILE_FILES`（25 个 .py，覆盖 `line_check_assistant/` + `src/` 全量） ② `unittest discover -s tests` + 解析 `Ran N tests` 行（防止静默 0 项） ③ `MUST_EXIST`（8 条 §1.3 不变量 + 扩展搜索目录到 `line_check_assistant/`，覆盖 `bbfdm.operate` / `MAX_PARALLEL_UPGRADES = 8` 的实际位置） ④ `MUST_NOT_EXIST`（`0.0.0.0` 仅在代码行检测，**过滤掉 `#` 注释 + 三引号文档字符串**，避免反向语义注释误报，如 `telnet_transport.py:10` 「不回退 0.0.0.0」）。退出码 0 全过 / 1 任一失败。模块结构单一来源（3 个常量 + 4 个 check 函数 + main），便于单元测试。
  2. **`tests/test_verify_baseline.py`（新，11 项）** —— ① `MUST_EXIST`/`MUST_NOT_EXIST` 结构合法性；② `PY_COMPILE_FILES` 全部位于 `line_check_assistant/` 或 `src/` 下；③ `check_must_exist` 命中/缺失/目录不存在 3 个分支；④ `check_must_not_exist` 命中/缺失/限制文件不存在/纯注释行/缩进注释行 5 个分支。`tempfile.TemporaryDirectory` 构造临时源码，毫秒级跑完。299 → 310。
  3. **`AGENTS.md`（修改）** —— 规则 5 扩展为「新增功能 / Bug 修复 / 真实样机验收 → 必须同步更新 `README.md` + `ACCEPTANCE_BASELINE.md §2.x / §3` + `PROJECT_STATUS.md`」；规则 11 末尾补「真实样机验收或破坏/补全验收状态时同步更新 baseline §2.x 与 §3」；新增规则 13「提交代码前必须运行 `python scripts/verify_baseline.py` 全部通过 —— 拦截破坏已验收功能的最低门禁」；新增规则 14「详细工作流参考 SKILL.md」；新增章节「## 验收不变量」列出 MUST_EXIST / MUST_NOT_EXIST 的可读副本（与脚本单一来源保持一致，注释明确「改这里必须同步改脚本」）。
  4. **`.claude/skills/line-check-dev/SKILL.md`（修改）** —— §5 验证命令改为引用 `verify_baseline.py`（封装 §0 + §1.3 + §1.4）；§11 第 5 步同步改为跑 `verify_baseline.py`。
  5. **故意破坏实验** —— 把 `MAX_PARALLEL_UPGRADES = 8` 改成 `4`，跑 `verify_baseline.py` → 立即 FAIL：① `must_exist: MAX_PARALLEL_UPGRADES = 8` 不变量命中失败；② 4 项单测（`test_serial_upgrade_service.py` 断言常量为 8）失败。`exit 1`。改回后全绿。**门禁有效**。
- 修改文件：`Cheating_machine_execution_tool/scripts/verify_baseline.py`（新）、`Cheating_machine_execution_tool/tests/test_verify_baseline.py`（新）、`AGENTS.md`、`.claude/skills/line-check-dev/SKILL.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile scripts\verify_baseline.py`；`python -m unittest discover -s tests -v`（应 `Ran 310 tests ... OK`，原 299 + 本轮新增 11）；`python scripts\verify_baseline.py`（应 `ALL CHECKS PASSED`，exit 0）；故意破坏 `MAX_PARALLEL_UPGRADES = 8` 验证拦截。
- 验证结果：`py_compile` 通过；完整单测 `Ran 310 tests ... OK`（原 299 + verify_baseline 11 项）；`verify_baseline.py` 实跑 4 类检查全绿；故意破坏实验证明门禁可拦截不变量破坏。
- 后续待办：
  - 用户每次提交前运行 `python scripts\verify_baseline.py` 全绿（强制规则）；任何 FAIL 必须先修复。
  - 下一步考虑 GitHub Actions 配置（需先建远端仓库），把 verify_baseline 接入 PR 检查。
  - 下一步可考虑让 `verify_baseline.py` 解析 `ACCEPTANCE_BASELINE.md §1.3` 自动同步 `MUST_EXIST` 列表（消除文档与脚本漂移）。
  - `THIRD_PARTY_NOTICES.md` 漏列 `requests` / `ACCEPTANCE_BASELINE.md §0` 数字 283→299 漂移仍未修（见 2026-07-20 QA 报告 P0-1 / P0-2）。

## 2026-07-20 - 测试项配置「期望」改为 per-segment 否定

- 类型：功能 / 重构 / 测试 / 文档
- 背景：上一轮把「测试项配置」窗口改造为 ini 编辑器时，「否定匹配」是命令级单 Checkbutton：所有期望段共享同一个 negate 标志。但实际场景常需要混合——例如 `ifconfig ra0` 应同时满足「MAC 全零应**不**出现」与「UP BROADCAST 应**出现**」，单标志位无法表达这种 A 否定 ∧ B 肯定的组合。同时重新审视老工具 `Auto_power_on_off_tool/common/fuzzy_match.py`：其 `&&` 循环里**每段独立**调 `Fuzzy_Match_01`，每段自带 `!` 前缀解析——per-segment 才是老工具的真实语义，先前的单标志是过度简化。
- 完成内容：
  1. **`line_check_assistant/test_item_config_store.py`** —— `ExpectedSegment` 新增 `negate: bool = False` 字段（per-segment）；`OrderItem` 移除冗余的命令级 `negate` 字段。`_split_expected` 重写：返回 `List[tuple[bool, str]]`，按段独立解析 `!` 前缀。`_join_expected` 重写：参数改为 `List[ExpectedSegment]`，每段独立加 `!` 前缀，`&&` 拼接。`_load_order` / `_dump_order` 同步更新。空段仍跳过拼接。docstring 注明「更贴近老工具真实语义」。
  2. **`tests/test_test_item_config_store.py`** —— 调整 3 项旧用例（`test_save_and_load_round_trip` / `test_negate_prefix_serializes_with_bang` / skip_empty_expected_segments_when_joining）的数据结构以反映新模型；新增 3 项：① `test_per_segment_negate_mixed_serialization` 验证 `!A&&B&&!C` 混合拼接；② `test_per_segment_negate_round_trip_mixed` 验证混合 negate 往返保留每段独立标志；③ `test_parse_per_segment_negate_helper` 覆盖 `_split_expected` 的 6 种输入（全肯定 / 全否定 / 混合 / 单段 / 空串）。13 → 16 项。
  3. **`line_check_assistant/app.py` `_build_test_item_order_tab`** —— 移除命令级「否定匹配」Checkbutton 与 `row_dict["negate_var"]` 字段；`_add_segment_row` 新增 `negate: bool = False` 形参，每段渲染独立「否定」Checkbutton（与 Entry、删除段按钮并排）；`_build_row_widgets` 初始化段时读 `seg.negate` 传入；`capture` 按段读 `seg["negate_var"]` 写回 `ExpectedSegment(text=..., negate=...)`。
  4. **`line_check_assistant_README.md`** —— 「期望」拼接规则描述更新：勾否定 → 该段前加 `!`；并以 `!00:00:00:00:00:00&&UP BROADCAST` 为例说明混合语义。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`、`tests/test_test_item_config_store.py`、`line_check_assistant/app.py`、`line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile line_check_assistant/app.py line_check_assistant/test_item_config_store.py`；`python -m unittest discover -s tests -v`；smoke test 用混合 negate 数据走一遍 `_build_test_item_order_tab` + `capture` 确认每段独立读出。
- 验证结果：`py_compile` 通过；完整单测 `Ran 299 tests ... OK`（原 296 + per-segment negate 3 项）。Smoke test 加载 `[ExpectedSegment('00:00:00:00:00:00', negate=True), ExpectedSegment('UP BROADCAST', negate=False)]` 后 capture 返回一致数据结构。
- 后续待办：用户线下重启主程序 → 打开「测试项配置」→ 切到「测试项」Tab → 在已加载的 9 条命令上独立勾选每段的「否定」（例如保留原 ini 的 ifconfig ra0: `00:00:00:00:00:00` 勾否定、`UP BROADCAST` 不勾）→ 保存 → 检查 ini 内容 `!00:00:00:00:00:00&&UP BROADCAST`；重新加载确认段级勾选状态恢复。

## 2026-07-20 - 测试项配置窗口改造为 ini 编辑器（不接执行）

- 类型：功能 / 重构 / 测试 / 文档
- 背景：用户希望把老工具 `Auto_power_on_off_tool/config/test_project_config.ini` 映射到主程序的「测试项配置」窗口。`PROJECT_STATUS.md` 中的 `测试项配置` 当前实现是「只读占位 + 固定启用 3 行」；用户明确选择 **Q1=A**（仅展示+编辑+保存 ini，不接主程序执行）+ Q2 表单化（命令/期望/重试次数三个独立控件）+ Q3 保留 `Auto_power_on_off_tool/config/` 路径不动 + Q4 密码明文显示。「期望」按 `!段A&&段B` 拆为「否定勾选 + 动态段列表」；「重试次数」为每条命令 Spinbox（1–99）。本轮同步澄清了「重试间隔」的真实语义：老工具 `wait_time_N` 是 sleep 秒数、不是 retry interval；与 `config.ini` `[other_config] command_fail_retry_interval_time = 60` 同名字段含义不同——`test_project_config.ini` 当前没有「重试间隔」位置，按用户决定在 `[order]` 段顶部独立写 `command_fail_retry_interval_time = 60`，仅作为 ini 内全局参考值，不被主程序或老工具读取。
- 完成内容：
  1. **`line_check_assistant/test_item_config_store.py`（新）** —— 参照 `sample_upgrade_settings_store.py` / `config_store.py` 模式新增 ini 读写服务：`TelnetSettings` / `OrderConfig` / `OrderItem` / `ExpectedSegment` / `ConnectWifiSettings` / `TestProjectConfig` 6 个 dataclass + `TestItemConfigStore`。`RawConfigParser` + `optionxform=str`，与既有 store 一致；`[order]` 顶部独立写 `command_fail_retry_interval_time`，命令 key 拼为 `命令 retry_times_N`（不写 `wait_time_N`，避免与老工具 sleep 语义冲突）；期望值拼接「`!段1&&段2&&...`」（勾选否定时加 `!` 前缀）/「`段1&&段2&&...`」（未勾选）；空段不写入拼接结果；`bool` 强制转 `0/1` 防止保存为 `True/False`；`retry_times_0` / `port=0` 等非法值回退默认；缺失段（如老 ini 没有 `[order]`）不抛 `NoSectionError`，全字段回退默认值。
  2. **`tests/test_test_item_config_store.py`（新，13 项）** —— 覆盖：缺 ini 全字段回退默认；save/load 往返（含 `!`、`&&`、空段、长命令、含 `%`/`*`/`#` 的密码）；`[order]` 顶部全局值在命令之前；期望段 `&&` 拼接；勾选否定加 `!`；空段跳过；命令 key 含管道空格时正确拆分 retry_times；缺 retry_times 默认 5；`retry_times_0` 回退默认；`enable` bool→`0/1`；`product_solution` 保存时统一小写；未识别 key 容错。
  3. **`line_check_assistant/app.py`** —— `tkinter` 导入加 `Canvas`；新增模块常量 `TEST_ITEM_CONFIG_PATH = CONFIG_DIR / "test_project_config.ini"`。`_open_test_item_config` 占位（3 行固定启用 + 不会改变流程注释）替换为「`Toplevel(960x640)` + `ttk.Notebook` 三 Tab + 底部『重新加载 / 保存 / 关闭』」：
     - **Tab 1: Telnet** —— 11 字段表单（request_url / port / user / password + 👁 明文切换 / timeout / input_user_flag / input_password_flag / login_success_flag / 三个 0-1 flag），password 按 Q4 明文保存。
     - **Tab 2: 测试项** —— 顶部全局 Spinbox「指令重试间隔（秒）」默认 60；中间 `Canvas` 滚动列表，每行 `序号 Label + 命令 Entry + 重试次数 Spinbox + 删除命令按钮 + 期望子表单（否定勾选 + 动态段列表 + + 增加段按钮 + 每段独立删除按钮）`；底部「+ 新增测试项」按钮。空行在保存时跳过。
     - **Tab 3: WiFi** —— enable Checkbutton（0/1）+ product_solution Combobox（openwrt/bcm/mtk readonly，保存时小写）。
     - 行为：打开时自动加载 ini；缺失 ini 弹一次「将以空白表单打开」提示；任意 widget 改动标记 dirty；「重新加载」「关闭」有 dirty 时弹「放弃修改？」；「保存」二次确认 + 写入磁盘 + 主执行日志 `[测试项配置] 已保存 N 条测试项命令到 test_project_config.ini` + 失败原因；ini 文件不存在时自动创建；保留 `_open_test_item_config` 签名 + `self.test_item_config_window` 单例引用；样式与 `Primary.TButton` / `Secondary.TButton` / `CardTitle.TLabel` 等保持一致。
  4. **`line_check_assistant_README.md` / `PROJECT_STATUS.md`** —— 同步 README「测试项配置窗口」说明（Q1=A、密码明文、保存覆盖、注释丢失、不接执行）+ 表格「测试项配置窗口」从「占位」升级为「ini 编辑器（Q1=A）」，移除「待完成」中相关描述。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`（新）、`tests/test_test_item_config_store.py`（新）、`line_check_assistant/app.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：
  ```powershell
  cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
  python -m py_compile line_check_assistant\app.py line_check_assistant\test_item_config_store.py
  python -m unittest discover -s tests -v
  python .\run_line_check_assistant.py   # 启动后点测试项配置→改几项→保存→检查 ini
  ```
- 验证结果：`py_compile` 通过；完整 `python -m unittest discover -s tests -v` **共 296 项 OK**（原 283 + 本轮新增 13）。`from line_check_assistant.app import LineCheckAssistant` 导入正常；`_open_test_item_config` docstring 含 Q1=A 说明。真实交互验证待用户线下 Windows 桌面跑通。
- 后续待办：
  - 用户线下点击「测试项配置」→ 改 Telnet / 测试项 / WiFi 各字段 → 保存 → 检查 `Auto_power_on_off_tool/config/test_project_config.ini` 内容（含 `!`、`&&`、`retry_times_N`、顶部 `command_fail_retry_interval_time`、WiFi enable 0/1）。
  - 验证 `[order]` 段动态段列表：「+ 增加段」/「删除段」、「否定」勾选加 `!`、空行保存时被跳过。
  - 验证「重新加载」「关闭」在 dirty 时弹「放弃修改？」二次确认。
  - 验证删除 ini 后重新打开：弹「将以空白表单打开」+ 保存后自动创建。
  - 验证注释丢失：原 `[connect_wifi]` 段上方 `;` 中文注释保存后被清空（已确认接受）。
  - **本轮明确不实现**：`wait_time_N` 序列化（与老工具 sleep 语义冲突，避免误导）；不接主程序执行（Q1=A）；不引入 `configobj` 依赖（标准 `configparser` 已确认可接受注释丢失）。

## 2026-07-19 - 写样机参数 telnet 6 台并行 + 生成批量参数表 真实样机验收通过

- 类型：真实样机验收 / 状态更新
- 背景：用户在 6 台独立 VLAN110–VLAN115 真实样机上对 `Cheating_machine_execution_tool/line_check_assistant/app.py` 主程序跑了 ① 批量写样机参数 telnet 6 台并行（默认并行 1，依次勾选/不勾选「清空参数」/「退出老化」跑通 9 步自然顺序） ② 生成批量样机参数表（同批 MAC 前 6 位 OUI 固定 + 2.4G / 5G SSID 后缀取本机 MAC 末 4 位 + label "SN/GPON SN 随机后缀长度" 优化）。两项功能均验收通过。
- 完成内容：本轮无新代码改动,仅同步状态。把 `ACCEPTANCE_BASELINE.md` §2.7（批量写样机参数）从"已确认验收（1 台 / 6 台）+ 已实现未验收（流水线下发命令由可选 Checkbutton 控制）"升级为"已确认验收（1 台 / 6 台,流水线下发命令由可选 Checkbutton 控制已含 6 台真实样机回归）"；§2.8（随机参数表生成）从"已实现未验收"升级为"已确认验收（6 台真实样机）",并把 2026-07-19 同 OUI 改动、SSID 末 4 位 MAC 强关联、label 优化三条子改动都标"已确认验收"。§0 测试基线从 273 → 283（与单测实际一致）。`PROJECT_STATUS.md` 表格对应行 + 单元测试行 + 已完成段 + 抬头日期同步刷新。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile line_check_assistant/app.py src/core/sample_parameter_table.py src/services/sample_parameter_service.py`；`python -m unittest discover -s tests -v`（应仍为 283 项全过,本轮仅改文档不涉及业务逻辑）。
- 验证结果：本次纯文档/状态刷新,无代码改动;`py_compile`/`unittest` 与上一轮一致（283 项全过）。
- 后续待办：现场若 2 / 8 台端点并行需要补验收,按 `ACCEPTANCE_BASELINE.md` §2.7 / §2.8 "已实现未验收"标记执行。

## 2026-07-19 - 生成批量样机参数表 label "随机后缀长度" 改名为 "SN/GPON SN 随机后缀长度"

- 类型：界面优化
- 背景:用户打开「生成批量样机参数表」窗口,看到 "随机后缀长度" 输入框排在 2.4G / 5G SSID 前缀下面,会误以为这条也控制 SSID 后缀长度。上一轮已经把 2.4G / 5G SSID 后缀改为 MAC 末 4 位固定派生,该字段实际只控制 SN / GPON SN 的随机后缀字符数,label 需要明确。
- 完成内容:
  1. **`line_check_assistant/app.py` `_open_parameter_generator`** —— `fields` 字典的 key 从 "随机后缀长度" 改为 "SN/GPON SN 随机后缀长度",相应位置不动(仍在 2.4G / 5G SSID 前缀下方,符合用户要求「只动这一行 label」);`generate_and_save` 内部 `fields["随机后缀长度"].get()` 同步改为新 key。
  2. **`src/core/sample_parameter_table.py` `generate_parameter_records`** —— `ValueError` 文案从 "SN / GPON SN 随机后缀长度必须在 1 到 32 之间。"(斜杠两侧有空格)改为 "SN/GPON SN 随机后缀长度必须在 1 到 32 之间。",与新 label 字面保持一致。
- 修改文件:`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/core/sample_parameter_table.py`、`DEVELOPMENT_LOG.md`。
- 验证方法:`python -m py_compile line_check_assistant/app.py src/core/sample_parameter_table.py`;`python -m unittest discover -s tests -v`。
- 验证结果:`py_compile` 通过;完整单测 `Ran 283 tests ... OK`(仅改 label 文本,业务逻辑与所有测试断言保持原状)。
- 后续待办:用户线下重新打开"生成批量样机参数表",确认 label 已是 "SN/GPON SN 随机后缀长度",且该字段填 8 仍能正确生成 SN/GPON SN 后缀长度 8 的随机字符(SSID 后缀仍按 MAC 末 4 位派生,不受该字段影响)。

## 2026-07-19 - 生成批量样机参数表 2.4G / 5G SSID 后缀与 MAC 末 4 位强关联

- 类型：功能 / 测试 / 文档
- 背景：用户要求自动生成参数表时,**同一行**的 2.4G SSID 与 5G SSID 必须共享同一个后缀,且该后缀 = 本机 MAC 末 4 位十六进制（大写）。原因:① 2.4G / 5G SSID 是一台样机的两个频段标识,共享后缀便于和样机本身强对应;② 与 MAC 末 4 位强绑定后,操作员看一眼 SSID 就能反查本机 MAC（例:MAC=CA:7A:85:18:B0:E8 → 后缀="B0E8"）。当前实现两条 SSID 各自跑独立的随机后缀,既不共享,也与 MAC 无关联。
- 完成内容：
  1. **`src/core/sample_parameter_table.py` `generate_parameter_records`** —— 重排循环:先生成 MAC,再以 `mac.replace(":", "")[-4:]` 取末 4 位十六进制作为 `ssid_suffix`,然后 `2.4G SSID = template.ssid_24_prefix + ssid_suffix` / `5G SSID = template.ssid_5_prefix + ssid_suffix`。从 `seen_values` 字典中移除 `"2.4G SSID"` / `"5G SSID"` 两个 key(不再用 `_unique_prefixed_value` 随机生成)。SSID 唯一性由 MAC 唯一性自然保证(MAC 唯一则末 4 位唯一)。`ssid_24_prefix` / `ssid_5_prefix` 仍必须非空(若用户留空,直接抛 ValueError,避免空字符串拼出裸后缀);`suffix_length` 仍控制 SN / GPON SN 随机后缀长度,SSID 不再受其影响。`ValueError` 文案相应从"SN、XPON SN 和 SSID 前缀均不能为空"改为"SN 和 GPON SN 前缀均不能为空" + 新增独立校验"2.4G SSID 和 5G SSID 前缀均不能为空",与新行为一致。
  2. **测试** —— `tests/test_sample_parameter_table.py` 新增 `test_generate_records_ssid_suffix_matches_mac_last_4_hex`:用 5 条记录遍历,逐条断言 ① MAC 末 4 位为 4 位大写十六进制;② 2.4G / 5G SSID 各自以 MAC 末 4 位结尾;③ 去掉各自 prefix 后两个 SSID 后缀完全相同;④ 该后缀 == MAC 末 4 位;⑤ 5 条记录 2.4G / 5G SSID 仍各列唯一。旧的 `test_generate_records_are_unique_and_local_unicast` / `test_generate_records_share_same_mac_oui_within_batch` 保持原状,新行为不破坏其断言。
  3. **文档** —— `line_check_assistant_README.md` 生成批量参数表段:SSID 描述从"使用可编辑前缀加唯一随机后缀"改为"后缀自动取本机 MAC 末 4 位十六进制（同一行两个 SSID 共享后缀,便于与本机 MAC 强对应）";`ACCEPTANCE_BASELINE.md` §2.8 核心行为与状态行同步更新,新增 2026-07-19 SSID 末 4 位 MAC 强关联小段。
- 修改文件：`Cheating_machine_execution_tool/src/core/sample_parameter_table.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_table.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile src/core/sample_parameter_table.py tests/test_sample_parameter_table.py`；`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过；完整单测 `Ran 283 tests ... OK`（原 282 + 本轮新增 1）。
- 后续待办：用户线下打开"生成批量样机参数表",在 SSID 前缀输入框填入 `SDMC_Agtest_`（2.4G）/ `SDMC_Agtest_5G_`（5G）这种带下划线的形式,生成后逐行检查:① MAC 末 4 位 = 2.4G SSID 后缀 = 5G SSID 后缀;② 例:MAC=CA:7A:85:18:B0:E8 → 2.4G=`SDMC_Agtest_B0E8`、5G=`SDMC_Agtest_5G_B0E8`;③ 加载生成的 xlsx 后,预检通过,6 台仍能写入设备并被样机识别。已实现未验收,待真实样机回归。

## 2026-07-19 - 写样机参数确认框去掉"根据实际情况可选"字样

- 类型：界面优化
- 背景：用户看了 9 步自然顺序的确认框,认为步骤 5/6 后缀"（根据实际情况可选）"太啰嗦,弹出文案希望更干净。Readme 和 service docstring 不动,只动弹窗文本。
- 完成内容：**`line_check_assistant/app.py` `_start_sample_parameter_write`** —— `action_lines` 4 行后缀"（根据实际情况可选）"全部去掉。勾选时步骤 5/6 现在直接是 "5. 下发退出老化命令（ppctl set AGING_STATE=1）" / "6. 下发 ppctl clear";未勾选时是 "5. [跳过] 退出老化命令" / "6. [跳过] ppctl clear"。勾选/未勾选的视觉区分保留（[跳过] 前缀 + 命令文本）。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile line_check_assistant/app.py`；`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过；完整单测 `Ran 282 tests ... OK`（仅改弹窗文案,无业务逻辑/测试断言变化,与上一轮一致）。
- 后续待办：用户线下真实样机再次点击"写入参数",确认框步骤 5/6 后不再带"（根据实际情况可选）"。

## 2026-07-19 - 写样机参数默认并行数从 2 改为 1

- 类型：界面优化 / 文档 / 测试
- 背景：用户要求写样机参数窗口的默认并行数从 `DEFAULT_PARALLEL_COUNT=2`（与全包升级共用）改为 1。多台并发时 UBUS 4 段 HTTP + telnet login + NIC 切换容易撞网卡/防火墙，默认串行更稳；升级窗口（`Tftp指令` / `Tftp Put`）的默认并行数仍保持 2 不动。
- 完成内容：
  1. **`line_check_assistant/sample_upgrade_settings_store.py`** —— 新增 `DEFAULT_PARAMETER_PARALLEL_COUNT = 1`，与既有 `DEFAULT_PARALLEL_COUNT = 2`（升级窗口用）分离；加注释说明"写样机参数并行数默认 1，多台并发容易撞 UBUS HTTP / telnet login / NIC，Spinbox 仍允许 1–8 现场上调"。
  2. **`line_check_assistant/app.py`** —— import 加入 `DEFAULT_PARAMETER_PARALLEL_COUNT`；`_open_sample_parameter_writer` 内 `parameter_parallel_count_var = IntVar(value=DEFAULT_PARAMETER_PARALLEL_COUNT)`；写样机参数窗口提示文本 "（1–N 台，默认 1）"；`_start_sample_parameter_write` 内部 `except (TypeError, ValueError)` 兜底也走新常量。`_parallel_tftp_command_upgrade_worker` / `_parallel_tftp_put_upgrade_worker` 仍用 `DEFAULT_PARALLEL_COUNT=2`，与升级窗口对齐不受影响。
  3. **测试** —— `tests/test_sample_upgrade_settings_store.py` 新增 `test_default_parameter_parallel_count_is_one`：断言 `DEFAULT_PARAMETER_PARALLEL_COUNT == 1` 且 `DEFAULT_PARALLEL_COUNT == 2`，锁定两个常量互不污染；防止后续被改回 2 又无人复核。其余测试不依赖此默认值，不需调整。
  4. **文档** —— `line_check_assistant_README.md` 写样机参数段"并行 1–8 台（默认 2）"改为"并行 1–8 台（默认 1；多台并发易撞 UBUS HTTP / telnet login / NIC，Spinbox 仍允许现场上调）"；`ACCEPTANCE_BASELINE.md` §2.7 并行与取消段加注"默认 1；升级窗口的 `parallel_count` 默认仍为 2，互不影响"。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile line_check_assistant/sample_upgrade_settings_store.py line_check_assistant/app.py`；`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过；完整单测 `Ran 282 tests ... OK`（原 281 + 本轮新增 1）。
- 后续待办：用户线下真实样机再次打开写样机参数窗口，确认 Spinbox 默认值为 1；6 台并行（默认 1）变为 6 台串行（每台按 9 步自然顺序执行），主执行日志依次出现 `开始批量写样机参数：6 台，并行上限 1` 与单台写参的完整 9 步；用户如需多台并行，Spinbox 现场调高即可；升级窗口的并行默认仍为 2，互不影响。已实现未验收，待真实样机回归。

## 2026-07-19 - 写样机参数确认框按 9 步自然顺序重排

- 类型：界面优化 / 文档
- 背景：用户现场看到「确认批量写样机参数」弹窗里把「下发退出老化命令（ppctl set AGING_STATE=1）→ 下发 ppctl clear」放到了「进入工厂模式」**之前**；但 `run_parameter_write_pipeline` 的实际下发顺序是「进入工厂模式 → firstboot -yr → 等待 100 秒 → 工厂模式二次登录 → 退出老化 → ppctl clear → 15 项 set/get → 退出工厂模式 → firstboot -yr」,确认框文案与实际不符,会让操作员误判现场执行顺序。
- 完成内容：
  1. **`line_check_assistant/app.py` `_start_sample_parameter_write`** —— 确认框 `action_lines` 重构为严格 9 步自然顺序,每步一行,带序号。`action_summary` 由 ` → ` 拼接改为 `"\n".join(action_lines)`,弹窗按行展示。`exit_aging` / `clear_parameters` 关闭时,该步骤显示为 `[跳过] ...（默认关闭,根据实际情况可选）`,让操作员一眼分辨。`messagebox.askyesno` 的 message 模板对应改成"每台会依次：\n{action_summary}\n\n是否继续？"。主程序执行逻辑、流水线下发顺序、`finally` 清理块、`_current_sample_upgrade_settings` 全部不动。
  2. **`src/services/sample_parameter_service.py` `run_parameter_write_pipeline` docstring** —— 流水线描述按 9 步自然顺序重写,加入"步骤 3 等待 100 秒后,若调用方传入 factory_session_swap,会在 4 之前切网段并返回新 session"的说明;原 `首次登录 → FACTORY_MODE=1 → firstboot -yr → ... → ppctl clear → 15 项 ppctl set/get` 单行流程保留 step 语义但更新为 9 步版本,与确认框一致。
  3. **`ACCEPTANCE_BASELINE.md` §2.7** —— 业务时序段由"UBUS 启用 telnet → ... → FACTORY_MODE=1 → firstboot -yr → ... → 退出老化（可选）→ ppctl clear（可选）→ 15 项 → FACTORY_MODE=0 + firstboot -yr" 改为 1.~9. 编号版本,与确认框和 service docstring 对齐;原句保留等效语义。
  4. **`line_check_assistant_README.md`** —— 写样机参数段把"清空参数/退出老化"两步对应到"第 6/5 步";新增"写参时序按 9 步自然顺序执行"小段,与确认框、service docstring、ACCEPTANCE_BASELINE §2.7 四方一致。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/services/sample_parameter_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile line_check_assistant/app.py src/services/sample_parameter_service.py`；`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过；完整单测 `Ran 281 tests ... OK`（与上一轮一致,本次仅改文案与 docstring,无业务逻辑/测试断言变化）。
- 后续待办：用户线下真实样机再次点击「写入参数」时,确认框按 9 步自然顺序显示,勾选/未勾选的可选项在第 5/6 步明确标出；主执行日志实际下发顺序与确认框描述一致。

## 2026-07-19 - 写样机参数 MAC 同批 OUI 固定 + 清空参数可选 + 退出老化选项

- 类型：功能 / 优化 / 测试 / 文档
- 背景：用户提出 3 项改动 —— ① 自动生成参数表时同一批 MAC 前 6 位（OUI）固定、后 6 位每台唯一（典型场景：N 张同型号样机共用同一 OUI，最后 3 字节区分）；② `ppctl clear` 从无条件下发改为由主界面 Checkbutton 控制，默认关闭（避免误清空 ppctl 表）；③ 新增「退出老化」Checkbutton，勾选后在工厂模式二次登录成功后、下一个命令之前下发 `ppctl set AGING_STATE=1`。三项改动均影响写样机参数流水线，已实现未验收，待真实样机回归。
- 完成内容：
  1. **`src/core/sample_parameter_table.py`** —— `generate_parameter_records` 一次性生成 MAC OUI（3 字节，仍保留本地管理 + 单播的 bit 设置），`_unique_local_mac(oui, seen)` 只随机生成后 3 字节 NIC 标识并拼接。同批 OUI 唯一，后 3 字节仍随机唯一。
  2. **`src/models/sample_parameter_models.py`** —— `SampleParameterWriteRequest` 新增 `clear_parameters: bool = False` / `exit_aging: bool = False` 两个可选字段；与既有 `factory_bind_ip` / `factory_device_host` 同级，独立默认 False。
  3. **`src/services/sample_parameter_service.py`** —— `run_parameter_write_pipeline` 在"工厂模式二次登录成功"之后、`ppctl clear` 之前插入两段条件分支：
     - `exit_aging=True` → `_send_stage(session, "ppctl set AGING_STATE=1", ...)` + `emit("已下发退出老化命令。")`；
     - `exit_aging=False` → `emit("退出老化：关闭，跳过。")`；
     - `clear_parameters=True` → `_send_stage(session, "ppctl clear", ...)`；
     - `clear_parameters=False` → `emit("清空参数：关闭，跳过。")`。
     两段都使用 `getattr(request, "...", False)` 兜底，兼容未声明这两字段的旧 `SampleParameterWriteRequest` 实例；顺序固定为"退出老化 → 清空参数 → 15 项 ppctl set/get"；`finally` 清理块不动。
  4. **`line_check_assistant/sample_upgrade_settings_store.py`** —— `SampleUpgradeSettings` 新增 `parameter_clear_parameters: bool = False` / `parameter_exit_aging: bool = False`；`load` 用 `parser.getboolean(... fallback=False)`，`save` 用 `"1" if x else "0"`，与既有 `restore_factory` 同款；旧 ini 兼容回退 False。
  5. **`line_check_assistant/app.py`** —— `__init__` 新增 `parameter_clear_parameters_var` / `parameter_exit_aging_var` 两个 `BooleanVar`（从 `SampleUpgradeSettings` 读取初值），加入 `_bind_sample_upgrade_autosave` 的 trace_add 列表；写样机参数窗口在 `credential_row` 之后新增 `option_row`，含两个 `Checkbutton`（"清空参数"/"退出老化"）+ 提示；`_start_sample_parameter_write` 按实际勾选状态动态生成确认框文案（避免描述与实际下发命令不符）；`SampleParameterWriteRequest` 透传 `clear_parameters` / `exit_aging`；`_current_sample_upgrade_settings` 把两个 BooleanVar 也带进 dataclass。
  6. **测试** —— 现有 3 处断言 `ppctl clear` 必现的测试（`test_ppctl_clear_runs_after_factory_relogin_not_before` / `test_factory_session_swap_returns_none_abandons_before_second_login` / `test_factory_session_swap_new_session_is_used_for_second_login`）补 `clear_parameters=True` 以保留测试意图（其余 4 处 cleanup 失败测试不涉及 clear，保持默认 False 不动）。`tests/test_sample_parameter_table.py` 新增 `test_generate_records_share_same_mac_oui_within_batch`：5 条记录 OUI 唯一、后 3 字节各不同、首字节仍 bit1=1/bit0=0。`tests/test_sample_parameter_service.py` 新增 `SampleParameterPipelineOptionTests` 5 项：`test_clear_parameters_default_off_does_not_send_ppctl_clear` / `test_clear_parameters_on_sends_ppctl_clear` / `test_exit_aging_on_sends_aging_state_before_clear_and_writes` / `test_exit_aging_off_skips_aging_state` / `test_both_options_off_skips_both_commands`，覆盖默认关闭、显式开启、两者组合、顺序与跳过日志。`tests/test_sample_upgrade_settings_store.py` 新增 2 项：`test_save_and_load_preserves_parameter_clear_and_exit_aging` / `test_load_missing_parameter_clear_and_exit_aging_keys_defaults_to_false`，验证 ini 持久化往返与旧 ini 兼容回退。`tests/test_app.py` 的 2 项 `_current_sample_upgrade_settings` mock 补齐 2 个 BooleanVar 与期望。
- 修改文件：`Cheating_machine_execution_tool/src/core/sample_parameter_table.py`、`Cheating_machine_execution_tool/src/models/sample_parameter_models.py`、`Cheating_machine_execution_tool/src/services/sample_parameter_service.py`、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_table.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_service.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/PROJECT_STATUS.md`、`Cheating_machine_execution_tool/ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：
  ```powershell
  cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
  python -m py_compile src\models\sample_parameter_models.py src\core\sample_parameter_table.py src\services\sample_parameter_service.py line_check_assistant\sample_upgrade_settings_store.py line_check_assistant\app.py
  python -m unittest discover -s tests -v
  ```
- 验证结果：`py_compile` 通过；完整单测 `Ran N tests ... OK`，其中 `N >= 273 + 1(同 OUI) + 5(新选项) + 2(持久化) = 281`。本轮先把现有断言 ppctl clear 必现的 3 项测试改为显式 `clear_parameters=True`，保持原意。
- 后续待办：用户线下真实样机回归 —— ① 重新生成参数表，确认 5 条记录的 MAC 前 6 位完全一致、后 6 位各不同；② 关闭「清空参数」复测写参流水线，主执行日志依次出现"清空参数：关闭，跳过"且不再出现 `TX ppctl clear`；③ 勾选「退出老化」复测，主执行日志依次出现 `TX ppctl set AGING_STATE=1 → 已下发退出老化命令 → ...`；④ 关闭「退出老化」复测，主执行日志出现"退出老化：关闭，跳过"且不再出现 AGING_STATE；⑤ 6 台并行（默认配置，两个选项都关闭）跑通且仍稳定；⑥ 用户确认后，把 `ACCEPTANCE_BASELINE.md` §2.7 / §2.8 状态从"已实现未验收（选项化 + MAC 同 OUI 改动）"升到"已确认验收"，并同步 `PROJECT_STATUS.md` 测试基线数字。

## 2026-07-19 - 写样机参数 telnet 路径 6 台真实样机并行验收通过

- 类型：真实样机验收 / 状态更新
- 背景：`ACCEPTANCE_BASELINE.md` §2.7 中 2 / 4 / 8 台独立 VLAN 并行写参的最后一项"已实现未验收"。2026-07-18 已常量化 7 个节奏常量并通过 15 项 Pacing 回归单测，把 8 台同 t=0 触发网络准备 + UBUS 4 段 HTTP + telnet login 把网卡/防火墙挤爆的随机失败风险压住；本次在 6 台真实样机上跑通，等价覆盖了"2 / 4 / 8"区间内的代表性场景。
- 完成内容：用户线下用 6 台样机（VLAN110 / VLAN111 / VLAN112 / VLAN113 / VLAN114 / VLAN115）端到端跑批量写样机参数 telnet 路径，依次验证：① 6 台并行预检（VLAN/MAC/COM 一一对应）通过；② 6 个 worker 通过 `PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS=0.6` 错峰启动，避免同 t=0 抢网卡 / 防火墙；③ 6 台全部完成 UBUS 启用 telnet（4 段日志 + 末尾 `sleep_fn(1.0)`）→ `TelnetSession`（按 VLAN `bind_ip` 锁源）→ 首次登录；④ 6 台全部进入工厂模式（`FACTORY_MODE=1` + `firstboot -yr`）并等 100 秒；⑤ 6 台全部工厂模式网段切换（192.168.1.{N} → 192.168.29.{N}，`factory_bind_ip`/`factory_device_host` 自动派生）并二次登录成功；⑥ 6 台全部 15 项 `ppctl set/get` 读回校验通过；⑦ 6 台全部 `finally` 清理（`FACTORY_MODE=0` + `firstboot -yr`）成功，主执行日志依次出现"已下发退出工厂模式与重启命令"。过程中未触发 `bind_ip == device_host` 配置冲突预检（vlan110/111 已修过 device_manage_ip）；也未出现上轮修复的"清理失败步骤名消失"问题（每台清理失败若发生，会精确显示是 FACTORY_MODE=0 还是 firstboot -yr 触发的）。
- 用户确认验收通过；批量写样机参数（含 telnet 路径、UBUS 启用 telnet、工厂模式自动网段切换、6 台并行调度、错峰启动、`set/get` 读回校验、退出工厂模式清理）从 `ACCEPTANCE_BASELINE.md` §2.7 的"已实现未验收（2 / 4 / 8 台并行）"升级为"已确认验收（6 台独立 VLAN 并行）"，覆盖到原计划"2 / 4 / 8 台"区间的代表性场景（6 台落在区间中段，比 2 台更严苛、比 8 台更稳健，能验证 4 段 UBUS HTTP 抢网卡、6 个 telnet session 并发登录、错峰启动对 NIC / 防火墙压力的缓解效果）。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`。
- 验证方法：6 台真实样机（VLAN110–VLAN115）端到端跑批量写参 telnet 路径，每台主执行日志依次出现
  ```
  VLANxxx 写参前置：准备网络 vlanxxx（192.168.1.xxx / 255.255.255.0）
  检查并启用网卡 → 已启用网卡 → 设置 vlanxxx 静态 IP → 已设置
  VLANxxx 写参前置：UBUS 启用 telnet 中 (192.168.1.xxx)
  VLANxxx UBUS: AccessCtrl 总开关开启
  VLANxxx UBUS: <already_present / added_iface / added_lan_fallback / reused>
  VLANxxx UBUS 启用 telnet <action>: <message>
  STATE Telnet 已连接
  VLANxxx 写参：使用 Telnet 会话（绑定源 IP 192.168.1.xxx）
  首次登录成功
  VLANxxx TX ppctl clear
  VLANxxx TX ppctl set FACTORY_MODE=1
  VLANxxx TX firstboot -yr
  VLANxxx 写参：已触发进入工厂模式重启，等待 100 秒。
  …（约 100 秒后）…
  VLANxxx 工厂模式网段切换：准备把 vlanxxx 设为 192.168.29.xxx
  VLANxxx 工厂模式重建 TelnetSession 成功（192.168.29.xxx → 192.168.29.1）
  VLANxxx 写参：工厂模式网络切换完成，继续工厂模式二次登录。
  工厂模式二次登录成功
  VLANxxx TX ppctl set <15 项参数>=…
  VLANxxx TX ppctl get <15 项参数>
  …
  VLANxxx 写参完成，15 项均已读回校验。
  VLANxxx TX ppctl set FACTORY_MODE=0
  VLANxxx TX firstboot -yr
  VLANxxx 写参：已下发退出工厂模式与重启命令。
  ```
  6 台样机错峰 0.6s 启动，主执行日志不出现"随机某台写参失败"或"频繁卡顿打断"；UBUS 启用 telnet / Telnet 登录 / 工厂模式网段切换 / `set/get` 读回校验 4 个阶段没有出现 sample_parameter_service.py:286 旧版 finally 块那种"清理失败"误报。
- 验证结果：通过。
- 后续待办：若现场后续要推 8 台满载并行或更换新型号，需先按现场经验微调 7 个节奏常量（优先上调 `PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS=15.0` 与 `PARAMETER_RETRY_BACKOFF_SECONDS=2.5`）再回归；本次 6 台验收不覆盖"2 台"与"8 台"端点，必要时各补一次端到端验收。

## 2026-07-19 - 写样机参数退出工厂模式清理失败：两步独立 try/except + 失败步骤名

- 类型：BUG 修复 / 测试
- 背景：用户线下 6 台真实样机跑批量写参，主执行日志在 VLAN112 上抓到一段有歧义的输出：
  ```
  13:27:52  VLAN112 TX ppctl set XPON_SN='XPOND8AIKI54'（XPON SN，第 2/3 次）
  13:27:53  VLAN112 TX ppctl get XPON_SN（读取 XPON SN）
  13:27:53  VLAN112 TX ppctl set FACTORY_MODE=0
  13:27:53  VLAN112 写参：退出工厂模式清理失败：Telnet 连接已关闭：192.168.29.1:23
  13:27:53  VLAN112 写参：请人工确认设备已退出工厂模式。
  ```
  清理阶段本应依次下发 `FACTORY_MODE=0` 和 `firstboot -yr`，但 `TX firstboot -yr` 这一行消失了，紧接着直接是"退出工厂模式清理失败"，操作员无法判断：① `firstboot -yr` 到底有没有尝试过；② 是 `FACTORY_MODE=0` 还是 `firstboot -yr` 触发"连接已关闭"；③ 设备是否处于 `FACTORY_MODE=0` 但未重启的"半退出"状态。
- 根因：`src/services/sample_parameter_service.py` 的 `finally` 块把 `FACTORY_MODE=0` 和 `firstboot -yr` 两次 `_send_stage` 包在同一个 `try/except` 里，第 2 步抛 `RuntimeError` 会被外层 except 直接捕获并只输出一行笼统的"清理失败"，既没有 step 名区分、也没有把第 1 步的成功上下文保留下来。
- 完成内容：
  1. **`src/services/sample_parameter_service.py`** — 把 `finally` 块改成两步独立 `try/except`：
     ```python
     cleanup_failures: list[str] = []
     try:
         _send_stage(session, "ppctl set FACTORY_MODE=0", False, emit, request.vlan)
     except Exception as exc:
         cleanup_failures.append(f"FACTORY_MODE=0 下发失败：{exc}")
     try:
         _send_stage(session, "firstboot -yr", False, emit, request.vlan)
     except Exception as exc:
         cleanup_failures.append(f"firstboot -yr 下发失败：{exc}")
     if cleanup_failures:
         emit(f"{request.vlan} 写参：退出工厂模式清理失败：{'；'.join(cleanup_failures)}")
         emit(f"{request.vlan} 写参：请人工确认设备已退出工厂模式。")
     else:
         emit(f"{request.vlan} 写参：已下发退出工厂模式与重启命令。")
     ```
     关键不变量：① 第 1 步失败不会阻止第 2 步尝试（best-effort）；② 两步的 TX 主程序执行日志都必然出现（`_send_stage` 内部 `emit` 在 `send_line` 之前）；③ 失败消息明确包含 step 名（`FACTORY_MODE=0 下发失败：…` / `firstboot -yr 下发失败：…`），并用「；」拼接多条失败；④ 成功路径日志、流程、调用方契约全部不变。
  2. **`tests/test_sample_parameter_service.py`** — 新增 `SampleParameterServiceCleanupFailureTests` 3 项：
     - `test_cleanup_emits_both_tx_lines_even_when_firstboot_fails`：用 `_FlakyFakeSession` + `fail_on_call_index={"firstboot -yr": 2}` 让 `firstboot -yr` 第 2 次（清理阶段）失败；断言 cleanup 的 `FACTORY_MODE=0` TX 在 cleanup 的 `firstboot -yr` TX 之前出现；断言 `firstboot -yr 下发失败` 与 `请人工确认设备已退出工厂模式` 都出现在主执行日志；断言成功收尾日志被抑制。
     - `test_cleanup_reports_factory_mode_failure_when_step_one_fails`：FACTORY_MODE=0 和 firstboot -yr 都失败；断言 cleanup 的 `FACTORY_MODE=0` TX 与 cleanup 的 `firstboot -yr` TX 都出现，顺序 FACTORY_MODE 在前；断言失败汇总消息同时含 `FACTORY_MODE=0 下发失败` 和 `firstboot -yr 下发失败` 且用「；」分隔。
     - `test_cleanup_success_log_unchanged_when_both_steps_succeed`：成功路径回归；断言"已下发退出工厂模式与重启命令"出现，"退出工厂模式清理失败"不出现。
     `_FlakyFakeSession` 新增 `fail_on_call_index` 形参（dict 形如 `{"firstboot -yr": 2}` 表示第 2 次匹配才抛），用于精确控制哪一次同名命令失败；不指定 target 时保持"立刻抛"向后兼容。
- 修改文件：`Cheating_machine_execution_tool/src/services/sample_parameter_service.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_service.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile src/services/sample_parameter_service.py tests/test_sample_parameter_service.py`；`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过；完整单测 `Ran 273 tests ... OK`（原 270 + 本轮新增 3）。
- 后续待办：用户线下真实样机再次跑批量写参时，主执行日志期望出现
  ```
  VLANxxx TX ppctl set FACTORY_MODE=0
  VLANxxx TX firstboot -yr
  VLANxxx 写参：退出工厂模式清理失败：firstboot -yr 下发失败：Telnet 连接已关闭：192.168.29.1:23
  VLANxxx 写参：请人工确认设备已退出工厂模式。
  ```
  两步 TX 都看得见 + 失败步骤名明确；按消息直接判断是 `FACTORY_MODE=0` 触发的连接关闭还是 `firstboot -yr` 触发的，再决定是否人工补 `firstboot -yr` / 重启样机 / 升级会话凭据。

## 2026-07-18 - 写样机参数配置冲突预检：bind_ip == device_host 弹错 + 错误消息 hint

- 类型：BUG 修复 / 测试
- 背景：用户线下用 6 台样机（VLAN110-115）跑批量写样机参数，主执行日志依次出现
  ```
  - VLAN111 写参启动失败：Telnet 连接失败 192.168.1.111:23 源 IP 192.168.1.111：timed out
  - VLAN110 写参启动失败：Telnet 连接失败 192.168.1.110:23 源 IP 192.168.1.110：timed out
  ```
  错误模式特征：`device_host == bind_ip == 192.168.1.{N}`，PC 想连 192.168.1.111:23 但源 IP 也是 192.168.1.111，等于连自己 → SYN 不被响应 → 15 秒后 timed out。根因：`Auto_power_on_off_tool/config/network_card_ip.ini` 中 VLAN110/VLAN111 这两段的 `device_manage_ip` 被误填为 PC 静态 IP（192.168.1.110/111），而其他通道正确填为 192.168.1.1。`vlan{N} -> 192.168.1.{N}` 这个约定只适用于 `network_card_ip`（PC 端 NIC IP），不适用于 `device_manage_ip`（设备自身的管理 IP，跟 VLAN 编号无关，典型 192.168.1.1）。
- 完成内容：
  1. **`line_check_assistant/app.py`** — `_start_sample_parameter_write` 在已有的「factory_bind_ip / factory_device_host 派生失败」校验之前新增「bind_ip == device_host 冲突」预检：命中即 `messagebox.showerror("样机 IP 配置冲突", ...)`，提示文案明确指出 "PC 无法把自己作为目标连接" 与修复位置（主界面表格或 `network_card_ip.ini` 的 `device_manage_ip` 字段，典型值 192.168.1.1）。
  2. **`src/core/telnet_transport.py`** — `TelnetSession._open_socket` 在 `socket.create_connection` 抛 `OSError` 时，若 `bind_ip == device_host`，错误消息追加 hint（"bind_ip 与 device_host 相同，PC 无法把自己作为目标连接；请检查 network_card_ip.ini 中该 VLAN 的 device_manage_ip 是否误填为 PC 静态 IP，样机管理 IP 应是设备自身 IP，典型 192.168.1.1"），即便上游预检漏掉，下游也能给操作员明确的修复指引。
  3. **`src/core/ubus_http_client.py`** — `UbusHttpClient._post` 在连接失败时附加同款 hint，保持 UBUS HTTP 与 Telnet 两条链路错误消息一致。
  4. **测试** — `tests/test_sample_parameter_app.py` 新增 `SampleParameterAppBindConflictPreflightTests` 2 项：① `test_start_shows_error_when_bind_ip_equals_device_host` 模拟用户误配，断言 `showerror` 弹"样机 IP 配置冲突"且 worker 不启动；② `test_start_proceeds_when_bind_ip_differs_from_device_host` 断言正常配置不弹冲突错误。`tests/test_telnet_transport.py` 新增 2 项：hint 与 no-hint 场景。`tests/test_ubus_http_client.py` 新增 2 项：hint 与 no-hint 场景（用 `OSError(110, "timed out")` 触发）。所有新增测试均使用 `Mock`/`patch` 不真连网络，跑得快（< 100 ms）。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/core/telnet_transport.py`、`Cheating_machine_execution_tool/src/core/ubus_http_client.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_app.py`、`Cheating_machine_execution_tool/tests/test_telnet_transport.py`、`Cheating_machine_execution_tool/tests/test_ubus_http_client.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile src\core\telnet_transport.py src\core\ubus_http_client.py line_check_assistant\app.py tests\test_*`；`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过；完整 `python -m unittest discover -s tests -v` 共 **270 项** 全过（原 264 + 本轮新增 6）。
- 后续待办：用户修改 `network_card_ip.ini` 把 VLAN110/VLAN111 的 `device_manage_ip` 改为 192.168.1.1（或其他真实设备管理 IP）后重新跑批量写参，主执行日志应不再出现"bind_ip == device_host"错误；其余 4 台（VLAN112/113/114/115）继续保持现状即可。后续若需扩展：在 `network_card_ip.ini` 启动时增加一次性配置体检，对所有通道的 `bind_ip`/`device_manage_ip`/`factory_bind_ip`/`factory_device_host` 做静态校验并写入主程序启动日志，便于现场发现同类配置错误。

## 2026-07-18 - 写样机参数多台并行稳定性 — 节奏常量 + 错峰启动

- 类型：性能优化 / 测试
- 背景：用户线下用 8 台真实样机跑批量写样机参数,反馈"随机某台或多台样机写参失败"。经代码定位与用户现场经验,根因为多台并行时单台节奏过紧(`ppctl set` 后只等 1.0s 就发 `get`、`get` 等 marker 只给 4.0s、15 项参数之间无间隔、3 次重试无退避、8 台 worker 同 t=0 启动把 UBUS HTTP / 网卡 / 防火墙挤爆)。
- 完成内容：
  1. **`src/services/sample_parameter_service.py`** —— 新增 7 个模块级节奏常量(默认值按现场经验统一调整):
     - `PARAMETER_SETTLE_AFTER_SET_SECONDS = 1.5`(原硬编码 1.0;set 后等样机落盘再发 get)
     - `PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS = 10.0`(原硬编码 4.0;get 后等 marker 的最长秒数)
     - `PARAMETER_RETRY_BACKOFF_SECONDS = 1.5`(原无;mismatch / marker=None 后下次重试前退避)
     - `PARAMETER_BETWEEN_PARAMS_SECONDS = 0.5`(原无;同一台样机 15 项参数之间留缓冲)
     - `PARAMETER_LOGIN_PROMPT_TIMEOUT_SECONDS = 10.0`(原硬编码 8.0;_login 等 prompt / username)
     - `PARAMETER_LOGIN_PASSWORD_TIMEOUT_SECONDS = 20.0`(原硬编码 15.0;_login 等密码回执)
     - `PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS = 0.6`(原无;并行 worker 错峰启动延迟)
     `_login` 3 处 `wait_for_any` 超时改用 `PARAMETER_LOGIN_PROMPT/PASSWORD_TIMEOUT_SECONDS`;`_write_and_verify` 的 set 后 settle / get 后 wait timeout / mismatch retry backoff / 成功失败末尾的 between-params sleep 全部按常量调用。`run_parallel_sample_parameter_writes` 新增 `startup_stagger_seconds` 形参,默认 = 常量;executor.submit 由 dict comprehension 改为 for-loop,按 `index > 0` 在 submit 前 `sleep_fn(stagger)`。
  2. **`src/services/__init__.py`** —— 新增 `PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS` 的 `__all__` 与显式 re-export,使 `from src.services import PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS` 可用。
  3. **`line_check_assistant/app.py`** —— `_sample_parameter_write_worker` 内 telnet 路径 executor 由 dict comprehension 改为 for-loop,`offset > 0` 时 `time.sleep(PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS)` 再 submit,避免 8 台同 t=0 触发网络准备 + UBUS 4 段 HTTP + telnet login 把网卡/防火墙挤爆。serial 路径走 `run_parallel_sample_parameter_writes` 默认 `startup_stagger_seconds` 自动生效,无需显式传。
  4. **测试** —— `tests/test_sample_parameter_pacing.py` 新增 15 项回归:① `LoginPacingTests` 3 项 — 用包装 fake 驱动 _login 走完整 3 次 wait_for_any,断言 timeout = 对应常量;另 2 项是常量值本身的下界保护;② `WriteAndVerifyPacingTests` 4 项 — 用 `_RecordingSession` + `_aggregate_chunks` 还原 `_wait_cancellable` 切块后的 sleep,断言成功 / mismatch-then-success / 全 timeout / 全 mismatch 4 种场景的 sleep 模式精确等于 `[SETTLE, ... , BACKOFF, ..., BETWEEN]`;③ `ParallelStaggerTests` 3 项 — 3 个 requests 走 `run_parallel_sample_parameter_writes(stagger=X)`,断言 sleep_fn 调用次数与时长;另含 zero-stagger 与默认常量场景;④ `PacingConstantRegressionTests` 5 项 — 保护 7 个常量不会被改回更紧的值。新增 `_aggregate_chunks(sleeps)` 把 `_wait_cancellable` 切出的 `(1.0, 0.5)` 合并回 1.5s,避免 SETTLE 与 BACKOFF 同值(都 1.5s)在聚合前无法区分。
- 修改文件:`Cheating_machine_execution_tool/src/services/sample_parameter_service.py`、`Cheating_machine_execution_tool/src/services/__init__.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_pacing.py`(新)、`DEVELOPMENT_LOG.md`。
- 验证方法:`python -m py_compile src\services\sample_parameter_service.py src\services\__init__.py line_check_assistant\app.py tests\test_sample_parameter_pacing.py`;`python -m unittest discover -s tests -v`。
- 验证结果:`py_compile` 通过;完整 `python -m unittest discover -s tests -v` 共 **264 项** 全过(原 249 + 本轮新增 15)。
- 后续待办:用户线下真实样机 2/4/8 台并行验收,主执行日志节奏不再被 `set/get` 频繁卡顿打断;若仍偶发失败,先把 `PARAMETER_RETRY_BACKOFF_SECONDS` 上调到 2.5、`PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS` 上调到 15.0 现场试一次;确认后把 `ACCEPTANCE_BASELINE.md §2.7` 待确认项的"2 / 4 / 8 台并行验收"升级为"已确认验收(全场景)"。

## 2026-07-17 - 写样机参数 UBUS 启用 telnet 失败允许重试 3 次

- 类型：功能 / 测试
- 背景：用户线下真实样机跑批量写样机参数时遇到 `写参前置：UBUS 启用 telnet 失败：UBUS HTTP 请求失败 192.168.1.1:80：timed out`,偶发但会直接放弃本台。失败原因通常是样机防火墙 reload 中 / telnetd 启动慢 / HTTP 握手慢,首次 UBUS 同步调用就判定失败过于严格;与 `serial_upgrade_service.TFTP_COMMAND_MAX_RETRIES=3` 和 `sample_parameter_service.PARAMETER_WRITE_RETRIES=3` 的同款约定一致,允许重试 3 次,每次间隔 2 秒给样机缓冲。
- 完成内容:
  1. **`line_check_assistant/app.py`** —— `_sample_parameter_write_worker` 顶部新增两个 worker 局部常量 `UBUS_ENABLE_TELNET_MAX_RETRIES=3` 与 `UBUS_ENABLE_TELNET_RETRY_DELAY_SECONDS=2.0`。`make_telnet_factory.factory` 内 UBUS 启用块由原来的单次 `try/except` 改为 `for _attempt in range(1, 3 + 2)` 重试循环,每次重试前 `time.sleep(2.0)` 并 emit 主程序执行日志 `VLANxxx UBUS 启用 telnet 第 N/3 次重试,等待 2 秒...`;失败时 emit `VLANxxx 写参前置：UBUS 启用 telnet 失败：{exc}`;最后一次失败抛 `RuntimeError` 给 worker 的 `except Exception` 捕获并标记 `telnet 写参启动失败`。`UbusHttpClient` 每次重试都新建(`finally` 保证关闭),避免上一个失败连接残留状态。
  2. **测试** —— `tests/test_sample_parameter_app.py` 新增 `SampleParameterAppUbusRetryTests` 3 项:① `test_ubus_retry_succeeds_on_third_attempt` 模拟 2 次失败后第 3 次成功,断言 `enable_telnet_via_ubus.call_count==3` / `time.sleep.call_count==2` / 主日志含 `第 1/3 次重试` 与 `第 2/3 次重试`;② `test_ubus_retry_gives_up_after_max_retries` 模拟 4 次全部抛 `RuntimeError("UBUS HTTP 请求失败...timed out")`,断言 4 次调用 + 3 次 sleep + 3 条重试日志 + 4 条失败日志 + 不建 `TelnetSession`;③ `test_ubus_first_try_success_no_retry_log` 首次成功,断言 1 次调用 + 0 次 sleep + 0 条重试日志。`time.sleep` 用 `@patch("time.sleep")` mock 掉,避免真睡 2*3=6 秒拖慢测试。
- 修改文件:`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法:`python -m py_compile line_check_assistant/app.py tests/test_sample_parameter_app.py`;`python -m unittest discover -s tests -v`。
- 验证结果:`py_compile` 通过;完整 `python -m unittest discover -s tests -v` 共 **249 项** 全过(原 246 + 新增 3)。
- 后续待办:用户真实样机验收 —— 主执行日志首次失败时依次出现 `VLANxxx 写参前置：UBUS 启用 telnet 中 → UBUS: 三段 → VLANxxx 写参前置：UBUS 启用 telnet 失败：UBUS HTTP 请求失败 ... timed out → VLANxxx UBUS 启用 telnet 第 1/3 次重试,等待 2 秒... → 再次启用 → 成功:`;若 4 次仍失败,主程序会弹 `telnet 写参启动失败：UBUS 启用 telnet 失败：...` 并标记该台失败,其它通道继续;按 UBUS 错误消息判断是防火墙 reload 慢、telnetd 没起还是 HTTP 服务异常,若是后者(比如 BBFDM 未就绪)需重启样机或排查 `UbusHttpClient` 内部连接握手逻辑。

## 2026-07-17 - 写样机参数 / 串口终端所有 [敏感内容已隐藏] 改为明文显示

- 类型：功能 / 测试
- 背景：用户线下真实样机验收时反馈,主程序执行日志、串口终端 RX/TX、文件日志中密码类字段(WiFi 密码、superuser 密码、user 密码、首次登录密码等)仍以 `[敏感内容已隐藏]` 占位符显示,与现场"操作员需在主界面核对实际下发的值"诉求不一致;沿用 2026-07-13 的"输入框明文显示"方针,要求下发与回显同样明文。
- 完成内容:
  1. **`src/core/telnet_transport.py`** —— `_display()` 不再按 `self._known_secrets` 替换为占位符,改为直接 `decode("utf-8", errors="replace")`;`_emit()` 不再分支 `sensitive`,统一走 `_display(data)`。`sensitive` 形参保留以兼容既有调用方,但实际不起作用。`known_secrets` 形参与 `self._known_secrets` 属性保留同样兼容,后续可按需删除。
  2. **`src/core/serial_transport.py`** —— `_display()` 与 `write()` 内联 emit 文本生成,均不再走占位符;`sensitive` 形参保留为 no-op。
  3. **`src/services/sample_parameter_service.py`** —— `_write_and_verify` 的 TX 日志从 `'{[敏感内容已隐藏]}' if sensitive else repr(value)` 改为统一 `repr(value)`,密码类 5 项字段(2.4G/5G WiFi Password、Superuser Password、User Password)主执行日志直接出原文。
  4. **测试** —— `tests/test_telnet_transport.py` 的 `test_peek_since_redacts_known_secrets` 重命名为 `test_peek_since_displays_plaintext_known_secrets`,断言反转(明文 secret 出现 / `[敏感内容已隐藏]` 不出现);`tests/test_sample_parameter_service.py` 的 `test_write_reads_back_all_values_and_hides_sensitive_values` 重命名为 `test_write_reads_back_all_values_and_displays_plaintext`,断言主执行日志含 `secret-super` / `secret-user` 且不含 `[敏感内容已隐藏]`。
- 修改文件:`Cheating_machine_execution_tool/src/core/telnet_transport.py`、`Cheating_machine_execution_tool/src/core/serial_transport.py`、`Cheating_machine_execution_tool/src/services/sample_parameter_service.py`、`Cheating_machine_execution_tool/tests/test_telnet_transport.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_service.py`、`DEVELOPMENT_LOG.md`。
- 验证方法:`python -m py_compile src/core/telnet_transport.py src/core/serial_transport.py src/services/sample_parameter_service.py tests/test_telnet_transport.py tests/test_sample_parameter_service.py`;`python -m unittest discover -s tests -v`。
- 验证结果:`py_compile` 通过;完整 `python -m unittest discover -s tests -v` 共 **246 项** 全过。
- 后续待办:用户重新跑批量写样机参数 telnet 路径,主执行日志期望直接看到 `TX ppctl set WIFI_KEY_24G1='xxx'`、`TX ppctl set SUPER_PASSWORD='xxx'` 等明文,串口终端 RX 同样明文;若现场反馈需对某类字段(例如 super 密码)在文件日志中重新脱敏,再单独加字段级控制(目前是统一明文)。

## 2026-07-17 - 写样机参数 telnet 路径 1 台真实样机验收通过

- 类型：真实样机验收 / 状态更新
- 背景：用户线下用 1 台样机（VLAN114，源 IP `192.168.1.114` / 设备 `192.168.1.1`）跑批量写样机参数 telnet 路径端到端，验证本轮三连改动——① 写参前置启用网卡 + 设置静态 IP + 等可绑；② `factory_bind_ip` / `factory_device_host` 未配置时按"第 3 段 → 29,主机位不变"自动派生（ini 中这两个字段故意留空以触发派生）；③ `ppctl clear` 紧跟工厂模式二次登录。
- 完成内容：用户确认 1 台真实样机验收通过；写样机参数（含 telnet 路径、UBUS 启用 telnet、工厂模式自动网段切换、`ppctl clear` 时序）从 `ACCEPTANCE_BASELINE.md` §2.7 与 `PROJECT_STATUS.md` 的「已实现未验收」升级为「已确认验收（1 台单台）」。`ACCEPTANCE_BASELINE.md` §0 最小可信回归基线从 199 项更新到 **246 项**（2026-07-17 实跑）。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`。
- 验证方法：真实样机 VLAN114 端到端验证网络准备 + UBUS 启用 telnet + 首次登录 + 工厂模式 + 15 项 ppctl set/get 读回校验 + 退出工厂模式完整流水线；主执行日志依次出现「`VLAN114 写参前置：准备网络 vlan114（192.168.1.114 / 255.255.255.0）` → `检查并启用网卡` → `已启用网卡` → `设置 vlan114 静态 IP` → `已设置` → `UBUS 启用 telnet 中` → UBUS 三段日志 → `UBUS 启用 telnet <action>` → `STATE Telnet 已连接` → `首次登录成功` → `TX ppctl clear` → `TX ppctl set FACTORY_MODE=1` → `TX firstboot -yr` → 等待 100 秒 → `VLAN114 工厂模式网段切换：准备把 vlan114 设为 192.168.29.114（自动派生自 network_card_ip）` → `工厂模式重建 TelnetSession 成功（192.168.29.114 → 192.168.29.1）` → 工厂模式二次登录 → 15 项 `TX ppctl set/get` 读回校验 → `写参完成，15 项均已读回校验` → `TX ppctl set FACTORY_MODE=0` → `TX firstboot -yr` → `已下发退出工厂模式与重启命令`」。
- 验证结果：通过。
- 后续待办：2 / 4 / 8 台独立 VLAN 真实样机并行验收（`ACCEPTANCE_BASELINE.md` §2.7 待确认项）；通过后再把 §2.7 状态升级到「已确认验收（全场景）」。

## 2026-07-15 - 写样机参数 factory_bind_ip / factory_device_host 未配置时自动派生

- 类型：功能 / 测试
- 背景：用户点击「写入参数」报弹窗 `通道 VLAN114 走 telnet 路径,但缺少 factory_bind_ip / factory_device_host 配置`。检查 `Auto_power_on_off_tool/config/network_card_ip.ini`,`[channel_2]` 的 `factory_bind_ip` 与 `factory_device_host` 都是空字符串,只有 `network_card_ip=192.168.1.114` 与 `device_manage_ip=192.168.1.1`。按本轮之前确认的"29 网段、主机位不变"约定,可由用户模式 IP 自动派生工厂模式 IP,无需用户在主界面表格里手动补两个字段。
- 完成内容：
  1. **`line_check_assistant/network_ops.py`** —— 新增模块常量 `FACTORY_MODE_OCTET_INDEX = 2` / `FACTORY_MODE_OCTET_VALUE = "29"` 与两个纯函数 `factory_bind_ip_for(network_card_ip)` / `factory_device_host_for(device_manage_ip)`,底层共用 `_swap_third_octet_to_factory_subnet(ip)`,走 `ipaddress.IPv4Address` 校验;无效或为空时返回空串,与既有 `static_ip_for_vlan` 派生失败语义一致。注释说明约定:样机进入工厂模式(ppctl set FACTORY_MODE=1 + firstboot -yr 重启)后管理 IP 切到第 3 段替换为 29 的网段,主机位不变。
  2. **`line_check_assistant/app.py`** —— 顶部新增 `factory_bind_ip_for` / `factory_device_host_for` 导入。`_factory_bind_ip_for_vlan` / `_factory_device_host_for_vlan` 在用户模式字段已填、工厂模式字段为空时改为按"第 3 段 → 29,主机位不变"自动派生;手动填的工厂模式字段优先级最高,不覆盖。`_start_sample_parameter_write` 的预校验错误文案改为"自动派生工厂模式配置失败:factory_bind_ip (需补齐 network_card_ip 或手动填写)"等,引导用户补用户模式字段或显式手动填工厂模式字段。
  3. **测试** —— `tests/test_network_ops.py` 新增 `FactoryModeIpDerivationTests` 8 项(典型场景、空串/None、无效 IP、非 192.168.1 子网、前导零拒绝);`tests/test_sample_parameter_app.py` 新增 `FactoryModeIpHelperTests` 6 项(派生行为、手动覆盖优先级、双字段缺失兜底、用户模式 IP 非法时 device_host 仍能派生)。复用现有 `_channel_for_vlan` 替换为 lambda 返回真实 `ChannelConfig`,避免 Mock() 自动 mock 属性吞掉断言。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile line_check_assistant/app.py line_check_assistant/network_ops.py tests/test_network_ops.py tests/test_sample_parameter_app.py`;`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过;完整 `python -m unittest discover -s tests -v` 共 **246 项** 全过(原 232 + 新增 14)。
- 后续待办：用户重新打开主界面,点击「写入参数」应不再弹工厂模式配置缺失报错;确认后主执行日志依次出现 `写参前置：准备网络 vlan114（192.168.1.114 / 255.255.255.0）→ 已启用 → 已设置 → UBUS 启用 telnet → ... → 工厂模式网段切换：准备把 vlan114 设为 192.168.29.114 → ...`。若主界面表格里想保留手工指定的工厂模式 IP(例如 192.168.29.114 之外的值),直接在 `network_card_ip.ini` 给 `factory_bind_ip` / `factory_device_host` 写非空即可,优先级高于派生。

## 2026-07-15 - 写样机参数开始前启用对应通道网卡 + 设置静态 IP

- 类型：功能 / 测试
- 背景：批量写样机参数默认走 Telnet 路径,`make_telnet_factory` 当前直接进入 UBUS 启用 telnet + TelnetSession 创建,没有显式启用对应 VLAN 网卡并把 `channel.network_card_ip` 写入该网卡。多张同网段网卡环境下若 adapter 未启用或 IP 未生效,UBUS / Telnet 用 `source_address=(bind_ip, 0)` 锁源时会立即抛 `WSAEADDRNOTAVAIL`(10049)。用户澄清:写参开始时样机处于用户模式,直接按 `network_card_ip` 设置即可(主界面已按 `vlan{N} → 192.168.1.{N}` 约定自动派生到该字段);100 秒工厂模式重启后切到 29 网段、主机位不变,继续走既有 `make_factory_session_swap`,不重复实现。
- 完成内容:
  1. **`line_check_assistant/app.py`** —— `_sample_parameter_write_worker.make_telnet_factory` 在「`r.bind_ip / r.device_host` 校验后、UBUS 启用 telnet 之前」插入 3 步:① 通过既有 `self._adapter_alias_for_vlan(r.vlan)` / `self._subnet_mask_for_vlan(r.vlan)` 取字段;② 调用 `prepare_network_for_sample(adapter_alias, r.bind_ip, subnet_mask, on_output=emit_to_main, sleep_fn=time.sleep)` 启用网卡 + 设置静态 IP(其内部 emit 会把 `检查并启用网卡 / 已启用 / 设置静态 IP / 已设置` 四条主程序执行日志自然输出);③ `wait_for_bindable_ip(r.bind_ip, timeout_seconds=15.0)` 等 Windows 把新 IP 注册为可绑地址。任一失败抛 `RuntimeError`,被 worker `except Exception` 捕获并标记该台 `telnet 写参启动失败:{exc}`,其它通道继续。`adapter_alias` 或 `bind_ip` 为空时跳过该步骤(向后兼容,避免对未配置通道硬错误)。
  2. **测试** —— `tests/test_sample_parameter_app.py` 新增 `SampleParameterAppNetworkPreflightTests` 4 项:① `test_factory_prepares_network_before_ubus` 断言 4 个外部依赖各被调用 1 次、`prepare_network_for_sample` 形参为 `(adapter_alias, bind_ip, subnet_mask, on_output=..., sleep_fn=...)`、`wait_for_bindable_ip` 形参为 `(bind_ip, timeout_seconds=15.0)`,且调用顺序为 prepare → wait → UBUS → TelnetSession;② `test_factory_raises_when_prepare_network_fails` 断言 `ok=False` 时抛 RuntimeError,UBUS/Telnet 不调用,主执行日志出现 `网络准备失败`;③ `test_factory_raises_when_bindable_ip_times_out` 断言 `wait_for_bindable_ip=False` 时抛 RuntimeError,主执行日志出现 `仍未成为可绑地址`;④ `test_factory_skips_network_step_when_adapter_alias_empty` 断言 `adapter_alias=""` 时跳过两步,继续 UBUS/Telnet。
- 修改文件:`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法:`python -m py_compile line_check_assistant/app.py tests/test_sample_parameter_app.py`;`python -m unittest discover -s tests -v`。
- 验证结果:`py_compile` 通过;完整 `python -m unittest discover -s tests -v` 共 **232 项** 全过(原 228 + 新增 4)。
- 后续待办:用户真实样机验收 —— 主执行日志期待出现
  ```
  VLANxxx 写参前置:准备网络 vlan101(192.168.1.101 / 255.255.255.0)。
  检查并启用网卡:vlan101
  已启用网卡 vlan101
  设置 vlan101 静态 IP:192.168.1.101(255.255.255.0)
  已设置 vlan101 为 192.168.1.101
  VLANxxx 写参前置:UBUS 启用 telnet 中 (192.168.1.1)。
  VLANxxx UBUS: ...
  VLANxxx UBUS 启用 telnet <action>: <message>
  STATE Telnet 已连接
  VLANxxx 写参:使用 Telnet 会话(绑定源 IP 192.168.1.101)
  ```
  确认 `network_card_ip` 与样机管理 IP 在同一 /24 子网;若 `prepare_network_for_sample` 失败日志明确显示对应 VLAN 与原因,按提示核对 `adapter_alias` / 管理员权限 / `network_card_ip.ini`;`wait_for_bindable_ip` 超时则核对 Windows 注册网卡 IP 的延迟(实测通常 < 3 秒,15 秒足够覆盖大部分现场)。

## 2026-07-15 - 写样机参数窗口「首次登录账号/密码」持久化到 sample_upgrade_settings.ini

- 类型：功能 / 测试
- 背景：用户反馈写样机参数窗口的"首次登录账号"和"密码"每次打开界面时,虽然默认值会取上次的内容,但实际只是从 Tk 内存变量 (`self.upgrade_username_var / self.upgrade_password_var`) 拷贝而来,并没有真的存盘。在升级窗口里改过的值能影响,样机参数窗口里键入的新内容关闭再打开会丢。用户指出项目里已有 `Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py` 把升级相关设置(`upgrade_mode`、`username`、`password`、`firmware_path` 等)持久化到 `Auto_power_on_off_tool/config/sample_upgrade_settings.ini`,建议把写样机参数窗口的首次登录账号/密码也落到这个文件。
- 完成内容:
  1. **`line_check_assistant/sample_upgrade_settings_store.py`** — `SampleUpgradeSettings` 加两个独立字段 `parameter_initial_username`、`parameter_initial_password`(独立 key,与升级超级凭据 `username/password` 不混淆);`SampleUpgradeSettingsStore.load/save` 同步读写,空 ini 兼容回退到空字符串。
  2. **`line_check_assistant/app.py`** — `__init__` 阶段(`_load_settings` 之后)新增实例级 StringVar `parameter_initial_username_var / parameter_initial_password_var`,值取自 `self.sample_upgrade_settings.parameter_initial_username/password`,与 `upgrade_username_var / upgrade_password_var` 同级,通过 `_bind_sample_upgrade_autosave` 的 `trace_add("write", ...)` 走 400ms 防抖自动写盘。`_current_sample_upgrade_settings()` 把这两个字段也带上写盘。原 `_open_parameter_writer_window` 不再新创建同名 StringVar,直接复用实例级,关闭再开窗能恢复到上次内容。
  3. **测试** — `tests/test_sample_upgrade_settings_store.py` 加 2 项:① `test_save_and_load_preserves_parameter_initial_credentials` —— 证明两个字段独立存读且与升级凭据分离;② `test_load_missing_parameter_initial_keys_defaults_to_empty` —— 旧 ini(还没写过这两个 key)回退到空字符串无报错。`tests/test_app.py` 的两处 `_current_sample_upgrade_settings` 用例补齐 `parameter_initial_username_var / _password_var` 的 mock。
- 修改文件:`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法:`python -m py_compile line_check_assistant/app.py line_check_assistant/sample_upgrade_settings_store.py`;`python -m unittest discover -s tests -v`。
- 验证结果:`py_compile` 通过;完整 `python -m unittest discover -s tests -v` 共 228 项全过(原 226 + 新增 2)。
- 后续待办:用户重新打开主界面,在"写样机参数"窗口的"首次登录账号"和"密码"输入新值,关闭主程序再重开,确认两个字段仍能恢复到本次输入(查看 `Auto_power_on_off_tool/config/sample_upgrade_settings.ini` 的 `parameter_initial_username = ...`、`parameter_initial_password = ...` 两行)。注意:`%` 走 `RawConfigParser` 仍不会触发 interpolation(配置类用 `RawConfigParser`),所以含百分号的密码不会被误解为变量引用。

## 2026-07-15 - 写样机参数 ppctl clear 移到工厂模式二次登录之后 + 工厂模式网段切换

- 类型：BUG 修复 / 功能 / 测试
- 背景：用户接着前几轮修复继续真机验证：
  - UBUS 启用 telnet 成功；
  - `ppctl clear → ppctl set FACTORY_MODE=1 → firstboot -yr` 成功；
  - 100 秒等待后,主程序仍在用旧 TelnetSession(指向 `192.168.1.1:23`)尝试工厂模式二次登录,样机已在 `192.168.29.1:23`,旧 socket 被关闭,`cleanup` 阶段报 `Telnet 连接已关闭:192.168.1.1:23`,样机因此卡在工厂模式。
  - 用户纠正一个时序错误:`ppctl clear` 应当出现在工厂模式二次登录之后、15 项 `ppctl set/get` 之前,而不是首次登录之后进入工厂模式之前（当前代码是先清再进入工厂,但工厂模式重启会把 ppctl 表复原,等于白清）。
- 完成内容：
  1. **`line_check_assistant/config_store.py`** — `ChannelConfig` 新增 `factory_device_host: str = ""`、`factory_bind_ip: str = ""` 两个字段;`ChannelConfigStore.load/save` 同步读写,缺失字段保持空字符串。
  2. **`src/models/sample_parameter_models.py`** — `SampleParameterWriteRequest` 新增 `factory_bind_ip / factory_device_host` 两个字段,默认空,串口路径不消费。
  3. **`src/services/sample_parameter_service.py`** — `run_parameter_write_pipeline` 与 `run_single_sample_parameter_write` 新增可选 `factory_session_swap: Callable[[ParameterSession], Optional[ParameterSession]] = None` 形参;流水线在 100s 等待后、第二次 `_login` 之前调用该回调:返回新 session 切换并继续二次登录,返回 None 视为放弃本台,抛异常也立刻放弃本台。`ppctl clear` 命令从"FACTORY_MODE=1 之前"挪到"二次登录成功之后",与用户期望一致(`_send_stage(session, "ppctl clear", ...)` 现在紧跟 `_login(FACTORY_USERNAME/FACTORY_PASSWORD)` 成功);`finally` 清理仍用当前 session(已切换过就走新 session)。
  4. **`line_check_assistant/app.py`** — 新增 5 个 helper:`_factory_bind_ip_for_vlan / _factory_device_host_for_vlan / _adapter_alias_for_vlan / _subnet_mask_for_vlan`;`_start_sample_parameter_write` 在确认弹窗前增加工厂模式必填校验(telnet 路径的通道必须配齐 `factory_bind_ip / factory_device_host`,缺一拒绝本次写入并给出说明);`SampleParameterWriteRequest` 在工厂里塞入新字段;`_sample_parameter_write_worker` 新增 `make_factory_session_swap(request)` 闭包:旧 session.close() → `prepare_network_for_sample(adapter_alias, factory_bind_ip, subnet_mask)` → `wait_for_bindable_ip(factory_bind_ip, 15s)` → `TelnetSession(factory_bind_ip, factory_device_host)`;任意一步失败返回 None 并 `emit_to_main` 明确写日志(切网段失败 / 重建 TelnetSession 失败 / 缺少字段);`executor.submit` 第 8 个位置参数 `make_factory_session_swap(req)` 接入。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/config_store.py`、`Cheating_machine_execution_tool/src/models/sample_parameter_models.py`、`Cheating_machine_execution_tool/src/services/sample_parameter_service.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_service.py`、`Cheating_machine_execution_tool/tests/test_channel_config.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile line_check_assistant/app.py src/services/sample_parameter_service.py src/models/sample_parameter_models.py line_check_assistant/config_store.py`;`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过;`tests/test_sample_parameter_service.py` 新增 4 项:① `test_ppctl_clear_runs_after_factory_relogin_not_before` —— 断言 `ppctl clear` 只在工厂模式二次登录之后、15 项 `ppctl set` 之前出现一次,且位于 `ppctl set FACTORY_MODE=0` 之前;② `test_factory_session_swap_returns_none_abandons_before_second_login` —— 断言 swap 返回 None 时立即放弃本台,旧 session 上没有 `ppctl clear`;③ `test_factory_session_swap_exception_reports_failure` —— 断言 swap 抛异常时 pipeline 以"工厂模式网络切换异常"消息失败;④ `test_factory_session_swap_new_session_is_used_for_second_login` —— 断言 swap 返回新 session 时,`ppctl clear` 与 15 项 set 走新 session,finally 清理 (`FACTORY_MODE=0` + `firstboot -yr`) 也走新 session,旧 session 被 close;`tests/test_channel_config.py` 新增 3 项:① `test_load_includes_factory_bind_ip_and_device_host`;② `test_load_defaults_factory_fields_to_empty_when_missing`;③ `test_save_round_trip_preserves_factory_fields`。完整 `python -m unittest discover -s tests -v` 共 226 项全过(原 219 + 新增 7)。
- 后续待办：用户真实样机验证 —— 主执行日志期待出现
  ```
  VLAN114 写参前置：UBUS 启用 telnet 中 (192.168.1.114)
  VLAN114 UBUS: 已发起 UBUS 启用 telnet 流程
  …
  VLAN114 TX ppctl set FACTORY_MODE=1
  VLAN114 TX firstboot -yr
  VLAN114 写参：已触发进入工厂模式重启,等待 100 秒。
  …（约 100 秒后）…
  VLAN114 工厂模式网段切换:准备把 vlan114 设为 192.168.29.114 ……
  …
  VLAN114 UBUS 启用 telnet added_iface/already_present: …
  VLAN114 工厂模式重建 TelnetSession 成功(192.168.29.114 → 192.168.29.1)。
  VLAN114 写参：工厂模式网络切换完成,继续工厂模式二次登录。
  VLAN114 TX ppctl clear
  VLAN114 TX ppctl set SERIAL_NUMBER=…
  …15 项 set/get…
  VLAN114 写参完成,15 项均已读回校验。
  VLAN114 TX ppctl set FACTORY_MODE=0
  VLAN114 TX firstboot -yr
  VLAN114 写参：已下发退出工厂模式与重启命令。
  ```
  提示：测试结果仍「待真实样机验收」,修完后还需 2/4/8 台并行验收才能在 `ACCEPTANCE_BASELINE.md` §2.7 与 `PROJECT_STATUS.md` 把"已实现未验收"升级到"已确认验收"。`ChannelConfig` 新增 `factory_bind_ip / factory_device_host` 后,主程序表格里这些列现在是空白(空字符串视为未配置);现场需要按 VLAN 补齐。若 `prepare_network_for_sample` 失败(log 出现"工厂模式网段切换失败"),按提示核对对应 VLAN 的 adapter_alias 是否存在、是否能启用并设静态 IP;若 NIC 切换后 15s 仍未可绑,核对 Windows 注册网卡 IP 的延迟或现场状态。

## 2026-07-15 - 写样机参数 telnet 路径 sleep_fn=None 导致 100 秒等待立即抛 'NoneType' object is not callable

- 类型：BUG 修复 / 测试
- 背景：用户接着上轮修复继续真机验证 VLAN114 写参,UBUS 启用 telnet 成功后，主执行日志依次出现
  ```
  00:34:29 VLAN114 TX ppctl clear
  00:34:29 VLAN114 TX ppctl set FACTORY_MODE=1
  00:34:29 VLAN114 TX firstboot -yr
  00:34:29 VLAN114 写参：已触发进入工厂模式重启,等待 100 秒。
  00:34:29 VLAN114 TX ppctl set FACTORY_MODE=0
  00:34:29 VLAN114 TX firstboot -yr
  00:34:29 VLAN114 写参：已下发退出工厂模式与重启命令。
  ```
  最后却弹窗 `VLAN114 写参异常：'NoneType' object is not callable`。症状是「等待 100 秒。」刚打印就立刻同秒覆写三条最终清理命令。根因:`line_check_assistant/app.py` 的 `_sample_parameter_write_worker` 提交 telnet 路径执行时把 `sleep_fn=None` 作为第 6 个位置参数传给 `run_single_sample_parameter_write`,而 `_wait_cancellable(FACTORY_REBOOT_WAIT_SECONDS, cancel, sleep_fn)` 内部循环第一轮直接调用 `sleep_fn(1.0)`,`None(1.0)` 立即抛 `TypeError`,被外层 `except Exception` 接住返回失败结果;`finally` 看到 `entered_factory=True` 立刻连续下发 `ppctl set FACTORY_MODE=0` + `firstboot -yr` + 「已下发退出工厂模式与重启命令。」 这就是同秒出现三条的原因。
- 完成内容：`_sample_parameter_write_worker` 内部按样式加 `import time`;telnet 路径 executor.submit 调用第 6 个位置参数从 `None` 改成 `time.sleep`,与串口路径(走默认 `time.sleep`)对齐。其余流程、cancel 语义、15 项 set/get 重试、`FACTORY_USERNAME / FACTORY_PASSWORD` 与 100 秒工厂模式等待都不变。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_regression_sleep_fn.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile line_check_assistant/app.py src/services/sample_parameter_service.py src/core/ubus_enable_telnet.py`;`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过;新增 `tests/test_regression_sleep_fn.py` 3 项固化契约:① `test_sleep_fn_none_raises_none_type_not_callable` —— 用 `assertRaisesRegex(TypeError, "NoneType")` 锁死"`sleep_fn=None` 必须立即抛错"的契约,防止以后 caller 误传 `None` 让工厂模式清理走 finally 同一毫秒；② `test_sleep_fn_callable_runs_through_and_returns_true` —— 真 sleep_fn 在 cancel 未触发时跑完返回 True;③ `test_sleep_fn_callable_returns_false_on_cancel` —— cancel 已 set 时返回 False 且不调用 sleep_fn;完整 `python -m unittest discover -s tests -v` 共 219 项全过(原 199 + 新增 20)。
- 后续待办：用户真实样机再跑 VLAN114 写参,主执行日志期待出现
  ```
  VLAN114 写参前置：UBUS 启用 telnet 中 (192.168.1.114)
  VLAN114 UBUS: 已发起 UBUS 启用 telnet 流程
  …
  VLAN114 TX ppctl set FACTORY_MODE=1
  VLAN114 TX firstboot -yr
  VLAN114 写参：已触发进入工厂模式重启,等待 100 秒。
  …等待约 100 秒后…
  VLAN114 写参：触发首次登录（root / ******）/ 工厂模式二次登录（root / ******）
  VLAN114 TX ppctl set <15 项参数>=…
  VLAN114 TX ppctl get <15 项参数>
  …
  VLAN114 写参完成,15 项均已读回校验。
  VLAN114 TX ppctl set FACTORY_MODE=0
  VLAN114 TX firstboot -yr
  VLAN114 写参：已下发退出工厂模式与重启命令。
  ```
  若 100 秒等待结束后出现 "工厂模式二次登录失败",需按现场样机的工厂模式用户名/密码核对 `src/services/sample_parameter_service.py:25` 的 `FACTORY_USERNAME = "root"` 与 `FACTORY_PASSWORD = "t*hEQ#BHu7z%3n"`;若等待期间 `cancel.is_set()` 提前返回,主程序会在「已触发进入工厂模式重启,等待 100 秒。」后立即进入 finally 清理(符合预期逻辑,但可能被肉眼误判为清理太快)。

## 2026-07-15 - 写样机参数 UBUS 启用 telnet 总开关 set 必须用对象路径而非参数路径

- 类型：BUG 修复 / 测试
- 背景：用户接着上一轮修复继续验证 VLAN115 写参,主执行日志抛出
  ```
  VLAN115 UBUS: 获取访问规则总开关失败:UBUS 设置访问控制总开关失败,响应 [0, {'results': [{'path': 'Device.Firewall.X_SDMC_Security.AccessCtrl.EnableEnable', 'fault': 9005, 'fault_msg': 'Invalid parameter name'}]}]
  ```
  关键线索是 BBFDM 响应里 path 字段被拼成了 `...AccessCtrl.EnableEnable` —— 多出一个 `Enable`。原版 `SdmcUbusLibEnableTelnet._set_SecurityAccessCtrl_enable` 用的是对象路径 `f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl."` (末尾带点),并传 `obj_path={"Enable":"1"}`,BBFDM 会把 `obj_path` 的键当作对象下的参数;我代码误用参数路径 `ACCESS_CTRL_ENABLE_PATH` (`...AccessCtrl.Enable`) + 同一个 `obj_path={"Enable":"1"}`,BBFDM 视为在已经到参数的路径上继续追加,把两段 `Enable` 直接串联,产生 fault 9005 `Invalid parameter name`。
- 完成内容:`src/core/ubus_enable_telnet.py` 新增模块常量 `ACCESS_CTRL_ENABLE_OBJECT_PATH = "...AccessCtrl."`,仅用在 SET 总开关那一处 (`bbfdm_set` 的 path)。GET 总开关仍保留 `ACCESS_CTRL_ENABLE_PATH = "...AccessCtrl.Enable"`,因为 GET 接收"参数路径"形式合法;同时 `_bbfdm_all_results_one` 检查 `data != "1"`,遇到 fault 9005 这种 `data='Invalid parameter name'` 的响应会判定失败并抛 `UbusError`,刚好与上一轮校验修复串起来。其余路径(规则 set、add iface、add lan 回退)沿用上轮的修改不动,继续走 `data == "1"` 校验。
- 修改文件:`Cheating_machine_execution_tool/src/core/ubus_enable_telnet.py`、`Cheating_machine_execution_tool/tests/test_ubus_enable_telnet.py`、`DEVELOPMENT_LOG.md`。
- 验证方法:`python -m py_compile src/core/ubus_enable_telnet.py line_check_assistant/app.py src/core/ubus_http_client.py`;`python -m unittest discover -s tests -v`。
- 验证结果:`py_compile` 通过;`tests/test_ubus_enable_telnet.py` 新增 2 项 —— ① `test_set_total_enable_uses_object_path_not_parameter_path`:直接抓取 `bbfdm_set` 路径调用,断言总开关 SET 路径严格等于 `ACCESS_CTRL_ENABLE_OBJECT_PATH` 且 obj_path 等于 `{"Enable":"1"}`,确保本回归不会再次出现;② `test_set_total_enable_fault_9005_with_parameter_path_raises`:模拟 BBFDM 返回 `{'path': '...EnableEnable', 'fault': 9005, 'fault_msg': 'Invalid parameter name'}`,断言 `enable_telnet_via_ubus` 抛 `UbusError` 含"总开关失败";`tests/test_ubus_enable_telnet.py` 共 17 项全过;完整 `python -m unittest discover -s tests -v` 共 216 项全过(原 199 + 17)。
- 后续待办:用户真实样机验证 —— 主执行日志期待出现
  ```
  VLAN115 写参前置:UBUS 启用 telnet 中 (192.168.1.115)
  VLAN115 UBUS: 已发起 UBUS 启用 telnet 流程
  VLAN115 UBUS: AccessCtrl 总开关开启                (若原先 Enable != "1")
  VLAN115 UBUS: <already_present / added_iface / added_lan_fallback / reused>
  VLAN115 UBUS 启用 telnet <action>: <message>
  STATE Telnet 已连接
  VLAN115 写参:使用 Telnet 会话(绑定源 IP 192.168.1.115)
  …
  ```
  若仍 timed out,主程序会抛出"总开关失败 / 开启 LAN-telnet 规则失败 / 添加 telnet 规则 (Device.IP.Interface.1 / lan) 失败" 的明确 UbusError;按消息判断是设备未就绪、BBFDM 拒绝还是 telnetd 没起;若是 telnetd 守护进程没起则需要新增 UCI / `system.exec` 等路线,与本次 BGF 修复独立。

## 2026-07-15 - 写样机参数 UBUS 启用 telnet 校验 BBFDM 响应 data + 防火墙 reload 缓冲

- 类型：BUG 修复 / 测试
- 背景：用户在 VLAN115 上跑批量写样机参数，前一次修复（TCP 连接挪到 UBUS 之后）后仍报 `Telnet 连接失败 192.168.1.1:23 ... timed out`。复查 `Cheating_machine_execution_tool/SdmcUbusLib/libs/Security_module_api/enable_telnet.py`：该库对外只暴露 `SdmcUbusLibEnableTelnet.Enable_telnet()` 和 `SdmcSecurityLib.Ubus_telnet_enable()`，两者本质都是 BBFDM `bbf.shell` 下 `Device.Firewall.X_SDMC_Security.AccessCtrl.{Enable,Rule}` 路径上的 GET/SET/ADD 操作，并不直接启停 `telnetd` 守护进程。对照原版后发现三处实际差异：① SdmcUbusLib `_set_SecurityAccessCtrl_enable` / `_add_SecurityAccessCtrlRule` 在 JSON-RPC `error_code=0` 之外还会校验 `results[*].data == "1"`，本地实现在这两处缺失该校验；② SdmcUbusLib `Enable_telnet` 内含 `time.sleep(2)` 缓冲；本地实现因为 `_sample_parameter_write_worker` 传 `sleep_after_seconds=0.0`，防火墙变更后几乎没有等待。这两条都让 BBFDM 即使"看似成功"也未必真把 telnet 端口放开。
- 完成内容：在 `src/core/ubus_enable_telnet.py` 新增模块级 helper `_bbfdm_all_results_one(response) -> bool`，对齐 SdmcUbusLib 同款 `data == "1"` 校验；`enable_telnet_via_ubus` 内部：总开关 `bbfdm_set`、已存在规则 `bbfdm_set Enable=1`、`bbfdm_add Device.IP.Interface.1`、`bbfdm_add lan` 回退四处全部要求 `results[*].data == "1"`，否则 `raise UbusError`（与 `except UbusError: lan 回退` 这一既有 fallback 兼容）；新增常量 `ENABLE_TELNET_FINAL_SLEEP_SECONDS = 1.0`，在三个成功分支末尾固定 `sleep_fn(1.0)`，与 `sleep_after_seconds` 叠加，确保即便调用方传 0.0 也给防火墙 reload 留 1 秒。本地并未新增启动 `telnetd` 守护进程的入口，与 SdmcUbusLib 保持完全一致；若该设备未启动 telnetd，单靠 UBUS 防火墙规则不会让 23 端口 listening，需后续单独处理。
- 修改文件：`Cheating_machine_execution_tool/src/core/ubus_enable_telnet.py`、`Cheating_machine_execution_tool/tests/test_ubus_enable_telnet.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile src/core/ubus_enable_telnet.py line_check_assistant/app.py src/core/ubus_http_client.py`；`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过；新增 `tests/test_ubus_enable_telnet.py` 包含 6 项 `_bbfdm_all_results_one` 行为断言（data='1' / data='0' / 缺 results / 负载非 dict / 顶层非 list）+ 9 项 `enable_telnet_via_ubus` 端到端断言（already_present 不调 set/add、reused、added_iface、set_total data=0 抛错、set 已有规则 data=0 抛错、add_iface data=0 走 lan 回退、add 抛 UbusError 时 lan 回退、set_total + add_iface 日志顺序、sleep_after_seconds=0 仍触发 ENABLE_TELNET_FINAL_SLEEP_SECONDS）；完整 `python -m unittest discover -s tests -v` 共 214 项全过（原 199 + 新增 15）。
- 后续待办：用户真实样机再次验证：①日志依次出现「写参前置：UBUS 启用 telnet 中 → UBUS 总开关/规则 enable 三段消息 → UBUS 启用 telnet <action>: <message> → STATE Telnet 已连接 → 首次登录成功 → ...」；②若仍 timed out，主程序将抛出明确 UbusError `总开关失败` / `开启 LAN-telnet 规则失败` / `添加 telnet 规则 (Device.IP.Interface.1 / lan) 失败`，按消息可判断是 BBFDM 拒绝、设备未就绪还是该设备本就没起 telnetd；若是后者再单独立项处理。

## 2026-07-15 - 写样机参数 TCP 连接挪到 UBUS 启用 telnet 之后

- 类型：BUG 修复
- 背景：用户实际跑批量写样机参数（VLAN115，源 IP `192.168.1.115`）失败，弹窗 `VLAN115 telnet 写参启动失败：Telnet 连接失败 192.168.1.1:23 源 IP 192.168.1.115: timed out`。`make_telnet_factory` 当前顺序为先 `TelnetSession(...)` 同步建 TCP 连接、后 `enable_telnet_via_ubus(...)` 打开样机防火墙访问控制规则；但 OpenWRT 样机默认禁用 LAN-telnet，访问规则不开就没有进程监听 23 端口，SYN 不会得到响应，15 秒后 `socket.timeout`。这与函数顶部注释「端到端 telnet 写参:UBUS 启用 telnet → TelnetSession(未登录)」相反。
- 完成内容：把 `make_telnet_factory` 内部语句顺序调整为「先 `enable_telnet_via_ubus`（含总开关 get/set、规则遍历、add 规则、add lan 回退四段，仍走 `sleep_after_seconds=0.0`）→ 后 `TelnetSession(...)` 同步连」。UBUS 失败时不再需要回头关闭未创建的 Telnet 连接，清理分支简化。其余传输流程、`known_secrets`、`log_path`、`UbusHttpClient.close()` 等不变；源 IP `source_address=(bind_ip, 0)` 锁源、`enable_telnet_via_ubus` 三段日志、`ACCEPTANCE_BASELINE.md` §2.7 注释等均保持原状。修复后关键阶段日志自然输出：`写参前置：UBUS 启用 telnet 中 → UBUS 三段消息 → UBUS 启用 telnet <action>: <message> → STATE Telnet 已连接 → 首次登录 → ppctl clear → …`。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile Cheating_machine_execution_tool\line_check_assistant\app.py`；`python -m unittest discover -s Cheating_machine_execution_tool\tests -v`。
- 验证结果：`python -m py_compile` 通过；完整 `python -m unittest discover -s Cheating_machine_execution_tool\tests -v` 共 199 项通过（与 `ACCEPTANCE_BASELINE.md` §0 基线一致，未新增/调整任何测试）。
- 后续待办：用户真实样机验收：先以 VLAN115 单台验证日志依次出现「写参前置：UBUS 启用 telnet 中 → UBUS 总开关/规则 enable 三段消息 → UBUS 启用 telnet added_iface/already_present: … → STATE Telnet 已连接 → 首次登录成功 → ppctl clear → 工厂模式 → 15 项 set/get 读回 → 退出工厂模式」；通过后扩展到 2/4/8 台独立 VLAN 并行，状态标签由「已实现未验收」升级为「已确认验收」再同步 `ACCEPTANCE_BASELINE.md` §2.7 与 `PROJECT_STATUS.md` 表格。

## 记录规则

- 每次完成代码、配置、文档或流程变更后，都在本文件顶部追加一条记录。
- 记录内容应尽量短，但要能说明改动目的、影响范围和验证结果。
- 如果改动会影响项目当前状态或后续入口，同步更新 `PROJECT_STATUS.md`。
- 如果新增或调整用户可见功能，同步更新对应 `README.md`。
- 不记录 `build`、`dist`、`logs`、`.venv` 目录中的生成内容。

## 记录模板

```markdown
## YYYY-MM-DD - 简短标题

- 类型：功能 / 优化 / 修改 / BUG 修复 / 文档 / 构建 / 测试
- 背景：
- 完成内容：
- 修改文件：
- 验证方法：
- 验证结果：
- 后续待办：
```

## 2026-07-15 - 串口终端命令输入框支持 Enter 发送

- 类型：优化 / 测试 / 文档
- 背景：操作员反馈“串口日志记录”窗口的命令输入框按 Enter 不发送，每次都要手动点「发送」按钮，与常见串口终端习惯不符。
- 完成内容：在每个 VLAN Tab 的命令输入框（`ttk.Entry`）上绑定 `<Return>` 事件，新增 `_on_command_return(vlan)` 内部方法直接复用现有 `send(vlan)` 入口并返回 `"break"` 阻断 Tk 默认 Enter 行为；输入框非空时发送文本并清空（等价「发送」按钮），空字符串时发送纯回车（等价「回车」按钮）。自动升级占用、危险命令 `reboot`/`reset`/`firstboot`/`tftp`/`upgrade` 二次确认等现有 `send()` 分支保持不变。
- 修改文件：`Cheating_machine_execution_tool/src/ui/serial_terminal.py`、`Cheating_machine_execution_tool/tests/test_serial_terminal.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile src/ui/serial_terminal.py`；`python -m unittest discover -s tests -p test_serial_terminal.py -v`；`python -m unittest discover -s tests -v`。
- 验证结果：`python -m py_compile` 通过；串口终端专项 8 项通过（原 6 项 + 新增 2 项）；完整 `python -m unittest discover -s tests -v` 共 184 项通过（原 182 项 + 新增 2 项）。
- 后续待办：用户真实桌面环境在 vlan137/vlan138 等终端确认按 Enter 等价于「发送」按钮、空输入时等价于「回车」按钮，并确认升级中锁定提示和危险命令二次确认仍生效。

## 2026-07-15 - 写样机参数传输层由串口切换为 Telnet（按 VLAN 网卡 IP 锁源）

- 类型：功能 / 安全优化 / 重构 / 测试 / 文档
- 背景：光猫/路由器测试环境普遍配备多张同网段 VLAN 网卡，串口写参会因 PC 自动选网卡导致命中错误样机。
- 完成内容：
  - 新增 `src/core/parameter_session.py` 的 `Protocol ParameterSession`，把 `run_single_sample_parameter_write` 抽出 `run_parameter_write_pipeline` helper，service 层不再 import `PySerialSession`；既有 4 项串口路径单测保持全绿。
  - 抽出 `src/core/bind_socket.py`：`ip_is_bindable_locally` / `wait_for_bindable_ip`；TFTP strict server 改转发到该模块以保持兼容（保留 `tftp_transport._ip_is_bindable_locally / wait_for_bindable_ip` 旧名以免破坏测试 patch）。
  - 新增 `src/core/telnet_transport.py`：`TelnetSession` 在 `socket.create_connection(..., source_address=(bind_ip, 0))` 上提供与 `PySerialSession` 同形接口（cursor / write / send_line / wait_for_any / wait_for_all / peek_since）；源 IP 不可绑时强报错、不回退 `0.0.0.0`。
  - 新增 `src/core/ubus_http_client.py`：自写 JSON-RPC 2.0 客户端，不依赖 `SdmcUbusLib`（其静态字段多线程会互相覆盖 session）；通过 `http.client.HTTPConnection(..., source_address=(bind_ip, 0))` 按 VLAN 网卡锁定出口；当前支持 `login / bbfdm.get / bbfdm.set / bbfdm.add / bbfdm.unauthenticated_operate`。
  - 新增 `src/core/ubus_enable_telnet.py`：复刻 `SdmcUbusLibEnableTelnet.Enable_telnet` 的访问控制规则协议，按 `get/set/add/SourceInterface=lan 回退` 三段处理；返回 `EnableTelnetResult(action, ok, message)`。
  - `SampleParameterWriteRequest` 增加 `bind_ip / device_host / ubus_port` 字段（默认空 / 80，向后兼容）。
  - `line_check_assistant/app.py` 的 `_start_sample_parameter_write` 把 `ChannelConfig.network_card_ip / device_manage_ip` 透传到 request；`_sample_parameter_write_worker` 中按 VLAN 一台样机走 UBUS 启用 telnet → `TelnetSession` → service 流程；其余串口路径保留作 transport 回退。
- 修改文件：`Cheating_machine_execution_tool/src/core/parameter_session.py`（新）、`src/core/bind_socket.py`（新）、`src/core/telnet_transport.py`（新）、`src/core/ubus_http_client.py`（新）、`src/core/ubus_enable_telnet.py`（新）、`tests/test_telnet_transport.py`（新）、`tests/test_ubus_http_client.py`（新）、`src/core/tftp_transport.py`（转发到 bind_socket）、`src/services/sample_parameter_service.py`（加 `ParameterSession` 依赖）、`src/models/sample_parameter_models.py`（新增字段）、`line_check_assistant/app.py`（组装 telnet 工厂、`_channel_for_vlan` 等 helper）、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile` 各新模块与 `app.py`；`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过；完整 `python -m unittest discover -s tests -v` 共 199 项通过（原 184 + telnet 6 + ubus 9）。
- 后续待办：用户先以 2 台独立 VLAN / COM 样机验收 UBUS 启用 telnet → Telnet 写参 → 工厂模式 → 15 项 set/get 读回校验；其次扩展至 4 / 8 台并行；真实样机成功后追加一条“真实样机验收通过”记录。

## 2026-07-15 - 串口日志记录-新增回车发送功能验收通过

- 类型：真实样机验收 / 状态更新
- 背景：2026-07-15 接入的命令输入框 Enter 发送最初仅有单元测试通过；用户已在线下样机完成端到端验证。
- 完成内容：用户确认“串口日志记录-新增回车发送功能”真实样机验收通过；该能力从 `ACCEPTANCE_BASELINE.md` 第 4 节的“已实现但未确认验收/待确认”收敛为“已确认验收”，同步把 `PROJECT_STATUS.md` 对应行（内置多 VLAN 串口终端）追加“含回车发送”说明。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`。
- 验证方法：以真实样机在“串口日志记录”窗口的命令输入框中：①输入文本后按 Enter，确认等价于「发送」按钮且输入框被清空；②输入框为空时按 Enter，确认等价于「回车」按钮；③自动升级占用对应 Tab 时按 Enter，确认弹出 “串口被占用” warning；④输入包含 `reboot` / `firstboot` 等关键字时按 Enter，确认继续弹出“确认危险命令”二次确认。
- 验证结果：通过。
- 后续待办：无。

## 2026-07-13 - 精简项目交接状态文档

- 类型：文档 / 交接
- 完成内容：按当前源码、测试与真实样机验收状态重写 `PROJECT_STATUS.md`，只保留项目进度、关键文件、已完成/待完成/限制、技术决策及运行测试入口。
- 修改文件：`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：核对当前源码入口、批量写参模块、运行命令与测试基线。
- 验证结果：状态文档当前测试基线为 182 项通过；未改动业务代码。
- 后续待办：按文档中的真实样机验收项继续验证。

## 2026-07-13 - 随机参数表生成窗口全部输入框改为明文显示

- 类型：界面优化
- 背景：操作员需要在生成批量参数表前核对 WiFi、超级用户和普通用户密码，原窗口中的密码类输入框以星号隐藏内容。
- 完成内容：生成批量样机参数表窗口的全部输入框统一明文显示；生成后的写参执行、串口终端和主执行日志仍继续脱敏敏感参数值。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 Python 编译检查；打开“生成批量样机参数表”，填写密码类字段后确认显示实际字符。
- 验证结果：待桌面界面确认。
- 后续待办：无。

## 2026-07-13 - 写样机参数首次登录密码改为明文显示

- 类型：界面优化
- 背景：操作员在“写样机参数”窗口需要核对首次登录密码，原输入框以星号隐藏内容，不便确认实际填写值。
- 完成内容：首次登录密码输入框改为明文显示；写参下发、串口终端和主执行日志中的敏感值脱敏逻辑不变。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 Python 编译检查；打开“写样机参数”，确认首次登录密码框显示实际字符。
- 验证结果：待桌面界面确认。
- 后续待办：无。

## 2026-07-13 - 接入批量写样机参数与随机参数表生成

- 类型：功能 / 安全优化 / 测试 / 文档
- 背景：主界面“写样机参数”仅为预留入口；同事的独立原型虽已具备单台写参流程，但未接入主程序的串口独占、并行调度、内置终端、主执行日志和参数表 VLAN 匹配。
- 完成内容：新增批量写参窗口，按参数表 `VLAN` 匹配已勾选通道并通过固定 `vlan{N} -> COM{N-100}` 映射并行执行（1–8 台、默认 2）；预检会阻止缺失/重复 VLAN、重复 COM、MAC 格式错误、必填值为空和引号/换行。写入前二次确认清晰展示 `ppctl clear`、工厂模式及两次 `firstboot -yr` 重启；每项 `ppctl set/get` 最多重试 3 次，单台失败不取消其它通道，取消时停止后续命令并尝试退出工厂模式。新增随机 `.xlsx` 参数表生成：按已勾选 VLAN 生成唯一的本地管理单播 MAC、SN、XPON SN、2.4G/5G SSID，其他参数由模板统一填写；导出后自动加载预检但不自动写设备。新表使用区分 2.4G/5G 密码和国家码的唯一表头，导入兼容旧表重复 `WiFi Password` / `Country code` 列。
- 修改文件：`line_check_assistant/app.py`、`src/models/sample_parameter_models.py`、`src/core/sample_parameter_table.py`、`src/services/sample_parameter_service.py`、相应 `__init__.py`、`requirements.txt`、`build_line_check_assistant.ps1`、`THIRD_PARTY_NOTICES.md`、新增专项测试、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行新增参数表/写参服务专项测试、源码编译检查与完整单元测试。
- 验证结果：专项 8 项通过；`python -m unittest discover -s tests -v` 完整回归 `Ran 182 tests ... OK`。
- 后续待办：先以 2 台独立 VLAN / COM 真实样机验证写参时序、读回校验、取消清理及密码脱敏，再扩展至 4 / 8 台并行。

## 2026-07-13 - 并行升级、ARP 重试与高频串口真实样机验收通过

- 类型：真实样机验收 / 项目状态
- 背景：`Tftp指令` 的 ARP 自动重试、两条升级链路的 2 / 4 / 8 台并行，以及高频串口日志下界面响应和程控电源 COM 批次长连接复用，均已完成代码与单元测试，尚需现场收口。
- 完成内容：用户确认上述三项真实样机验收均通过；`Tftp指令` 的 ARP 自动重试 3 次从“单元测试通过，待真实样机验收”更新为“已真实样机验收”，并移除相关现场待办。
- 修改文件：`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：真实样机验证 `Tftp指令` 的 ARP Retry count exceeded 自动重试；分别以 2 / 4 / 8 台独立 VLAN / COM 样机运行 `Tftp指令`、`Tftp Put` 并行升级；在高频串口日志下复测界面响应和程控电源 COM 长连接复用。
- 验证结果：均通过。
- 后续待办：保持现有已验收时序；仅在实验室功率闸容量紧张或出现新型号、异常现场日志时再评估扩展。

## 2026-07-13 - 样机升级配置行统一右边界

- 类型：界面优化 / 测试
- 背景：固件路径框扩展后，密码输入区及“目标样机”“执行状态”仍停在按钮左侧，右侧存在无意义空白，行间边界不一致。
- 完成内容：密码输入容器扩展到最右列，目标样机、执行状态和升级进度条同样跨到该列；固件选择按钮位置和业务逻辑不变。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 Python 编译检查；打开样机升级窗口，确认密码、目标样机、执行状态及进度条的右边缘与“选择固件...”按钮右边缘对齐。
- 验证结果：`python -m py_compile line_check_assistant\\app.py` 通过；`python -m unittest discover -s tests -p test_app.py -v` 共 60 项通过；界面真实显示待用户在 Windows 桌面环境确认。
- 后续待办：无。

## 2026-07-13 - 高频串口日志不再占满 Tk 主界面线程

- 类型：BUG 修复 / 性能优化 / 测试
- 背景：同时监控多个持续高频输出的 COM 口时，串口读取虽在后台线程，但终端在 Tk 主线程持续以 `after(0)` 渲染所有 VLAN 的 `Text` 控件并自动滚动；日志积压时窗口绘制与输入事件被挤占，Windows 可能显示“未响应”。
- 完成内容：终端渲染改为最小 33ms 节流；每轮只渲染当前可见 Tab，非活动 Tab 保留有限的最新缓冲，切换 Tab 时立即渲染；每个 Tab 的屏幕文本保留最近 5000 行，避免长期运行导致重绘成本和内存持续增加。屏幕缓冲最多 64KiB，超过时在终端提示已合并字符；原始串口日志仍由后台串口线程完整写入文件，不改串口协议、升级流程或端口映射。
- 修改文件：`Cheating_machine_execution_tool/src/ui/serial_terminal.py`、`Cheating_machine_execution_tool/tests/test_serial_terminal.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串口终端专项测试和完整单元测试；真实环境同时打开多路高频串口日志，确认主窗口、终端切换和按钮持续可操作。
- 验证结果：`python -m py_compile src\\ui\\serial_terminal.py` 通过；串口终端专项 6 项通过；`python -m unittest discover -s tests -v` 完整回归 `Ran 174 tests ... OK`。
- 后续待办：真实 3 路以上高频 WiFi 日志压测；如“打开全部”阶段仍卡顿，再把 COM 打开过程移到后台线程。

## 2026-07-13 - 样机升级固件路径框扩展至右侧可用宽度

- 类型：界面优化 / 测试
- 背景：样机升级窗口的“升级固件”路径框只占用输入区前两列，密码输入列到“选择固件...”按钮之间留有空白，长路径无法充分显示。
- 完成内容：路径框改为跨越前三个内容列，“选择固件...”按钮移到下一列并保持右对齐；窗口尺寸、固件选择和升级业务流程不变。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 Python 编译检查；打开样机升级窗口，选择长路径固件，确认路径框延伸至按钮左侧且按钮仍可点击。
- 验证结果：`python -m py_compile line_check_assistant\\app.py` 通过；`python -m unittest discover -s tests -p test_app.py -v` 共 60 项通过；界面真实显示待用户在 Windows 桌面环境确认。
- 后续待办：无。

## 2026-07-13 - 页面升级成功后执行 UBUS 恢复出厂

- 类型：功能 / 测试 / 文档
- 背景：样机升级窗口的“恢复出厂”原本只会保存为通用设置；页面升级链路未把该选项传入请求，也未调用公司 `SdmcUbusLib` 中的页面 UBUS 恢复出厂接口。
- 完成内容：`PageUpgradeRequest` 增加 `restore_factory`；页面升级确认框明确显示关闭，或“升级成功、设备重启并重新登录成功后将通过 UBUS 执行恢复出厂”。在 `X_SDMC_Upgrade()` 返回成功、设备重启并由当前独立 UBUS session 重新登录成功后，调用公司已定义的 `bbfdm.operate` + `Device.FactoryReset()` + `optional.proto=web`。恢复出厂关闭时明确记录跳过；开启时依次记录开始下发、`TX UBUS Device.FactoryReset()` 和命令已下发；调用异常会使该样机页面升级失败。为确保命令使用已验证的重新登录会话，重登检查不再提前 logout，而统一由流程 finally 收尾。新增项目规则：每个新增功能点必须向主程序执行日志输出关键阶段、实际命令下发、成功、跳过或失败提示。
- 修改文件：`AGENTS.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_page_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 `python -m py_compile line_check_assistant\\app.py line_check_assistant\\page_upgrade.py`；页面升级专项、主界面专项和完整单元测试。
- 验证结果：`python -m py_compile line_check_assistant\\app.py line_check_assistant\\page_upgrade.py` 通过；页面升级专项 9 项通过，主界面专项 60 项通过；`python -m unittest discover -s tests -v` 完整回归 `Ran 172 tests ... OK`。
- 后续待办：真实样机勾选页面升级“恢复出厂”，确认执行日志依次出现升级状态成功、重新登录成功、`TX UBUS Device.FactoryReset()` 和“UBUS 恢复出厂命令已下发”，并确认设备实际恢复出厂；关闭该选项时确认只出现“恢复出厂：关闭，跳过”。

## 2026-07-12 - Tftp指令 ARP 失败自动重试 3 次

- 类型：功能 / 优化 / 测试 / 文档
- 背景：现场样机偶发 `ARP Retry count exceeded; starting again` 后回到 `U-Boot>` 提示符；旧 `send_tftp_command_and_wait` 依赖 `wait_for_all(("done", "write"), TFTP_COMMAND_TIMEOUT_SECONDS=1800)`，本次失败会阻塞整整 30 分钟才向主程序报告超时，且无任何补救。
- 完成内容：模块顶部新增 `TFTP_COMMAND_MAX_RETRIES=3` / `TFTP_ARP_FAILURE_MARKER="arp retry count exceeded"` / `TFTP_RETRY_PROMPT_MARKER="u-boot>"` / `TFTP_COMMAND_POLL_SECONDS=1.0` / `TFTP_COMMAND_RETRY_DELAY_SECONDS=1.0`，并将单次超时从 1800 秒下调到 300 秒。`SerialUpgradeController` 新增 `_wait_for_tftp_completion_or_arp_failure` 按秒轮询：等待 `done + write` 完成标记，或识别 `ARP Retry count exceeded` + `u-boot>` 模式；不再阻塞到完整超时，避免已知快速失败场景浪费 5 分钟。`send_tftp_command_and_wait` 改为接收可选 `on_output` 回调，命中 ARP 失败模式时记录"自动重试 TFTP 命令：第 X/3 次发送..."和"检测到 ARP Retry count exceeded，剩余 N 次自动重试"并 sleep 1 秒后再次发送；最多 3 次尝试全部失败时返回 `TFTP 命令已重试 3 次仍未成功...`。`_run_tftp_command_with_power_supply` 调用处传入 `on_output=emit`，重试/成功提示直接进主程序执行日志。仅作用于 `Tftp指令`（样机主动拉固件）链路；`Tftp Put` 不走串口 tftp 命令，无 ARP 字样，不适用。`SerialUpgradeController.__init__` 新增 `monotonic_fn` 注入便于测试。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 `python -m py_compile` 关键模块；`python -m unittest discover -s tests -v` 全量；新增 6 项：首次成功不重试、ARP 失败后第 2 次成功、3 次全部 ARP 失败、无 ARP 标记不重试、ARP 标记但无 U-Boot> 不重试、`on_output=None` 也能跑通。
- 验证结果：`python -m py_compile src/services/serial_upgrade_service.py` 通过；`python -m unittest discover -s tests -v` 共 169 项通过（原 163 项 + 新增 6 项）。
- 后续待办：真实样机故意断 TFTPy Server 网络让 ARP 失败，确认主程序执行日志出现 "检测到 ARP Retry count exceeded, 剩余 X 次自动重试" 和 "自动重试 TFTP 命令：第 X/3 次发送..."；正常场景确认仍只发一条 tftp 即检测到 done + write 完成。

## 2026-07-12 - 并行 Tftp 指令高频日志不再阻塞 Tk 界面

- 类型：BUG 修复 / 测试 / 文档
- 背景：并行 `Tftp指令` 升级时，多路样机启动日志会高频进入串口终端；原终端每 80ms 逐条 Text 插入并滚动最多 200 次，主执行日志也会一次性清空队列，导致 Tk 主线程长期忙于渲染而显示“未响应”。
- 完成内容：串口终端按 VLAN 合并每轮事件，每 Tab 只插入/滚动一次，并设置 120 条或 10ms 的单轮预算；主执行日志改为每轮最多处理 120 条，积压时立即续跑。串口原始文件日志、升级并行调度、TFTPy 和程控电源时序不变。
- 修改文件：`Cheating_machine_execution_tool/src/ui/serial_terminal.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_serial_terminal.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串口终端、主界面和完整单元测试；真实两台并行 `Tftp指令` 样机验证 UI 响应。
- 验证结果：`python -m py_compile line_check_assistant/app.py src/ui/serial_terminal.py` 通过；串口终端专项 4 项、主界面专项 58 项通过；完整 `python -m unittest discover -s tests -v` 共 150 项通过。
- 后续待办：真实两台独立 VLAN 样机复测并行 `Tftp指令`，确认升级窗口和串口终端在高频启动日志下持续可响应。

## 2026-07-12 - 全包升级并行上限扩到 8 台 + 程控电源 COM 批次内复用

- 类型：功能 / 优化 / 测试 / 文档
- 背景：`Tftp指令` / `Tftp Put` 并行升级上限硬编码为 2 台，无法满足后续多 VLAN 真实样机需求；真实样机日志显示同一批次内程控电源 COM102 在每台样机上下电前后反复 open/close，扩到 8 台后浪费会放大 4 倍。
- 完成内容：`MAX_PARALLEL_UPGRADES = 8` 单一来源常量；`SampleUpgradeSettings` 新增 `parallel_count`（默认 2，存 ini，1–8 区间），Store 读写并加 `clamp_parallel_count` 防御非法值；UI 在执行方式 Combobox 右侧新增 `ttk.Spinbox`（1–8），串行时灰显；`_parallel_tftp_command_upgrade_worker` / `_parallel_tftp_put_upgrade_worker` 接收 `parallel_count` 并钳制后传入 `max_workers`，确认弹窗和状态文案跟随实际并行数。`UpgradePowerCycleCoordinator` 改为持有每条 COM 的长连接 `ProgrammablePowerSupply`，通过 `with UpgradePowerCycleCoordinator() as coordinator` 在两个并行 runner 收尾时统一 `close()`；serial 路径未动。`power_on_service.py` 未改接口，只新增一个供 coordinator 直接复用的入口（最终选择由 coordinator 直接调用 `supply.power_on_channels`）。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/Auto_power_on_off_tool/config/sample_upgrade_settings.ini`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 `python -m py_compile` 关键模块；`python -m unittest discover -s tests -v` 全量；新加 `coordinator` supply 复用与 `close()` 幂等两项断言。
- 验证结果：编译通过；`python -m unittest discover -s tests -v` 共 163 项通过；旧 coordinator 串行化测试改为对 `supply_factory` mock，新增 supply 只 open 一次 / close 幂等 2 项断言。
- 后续待办：真实 2 台、4 台、8 台独立 VLAN / COM 样机分别跑一次 `Tftp指令` 和 `Tftp Put` 并行升级，确认日志中"已打开 / 已关闭程控电源串口"各仅出现一次且 TFTPy 上传无错包；如实验室功率闸容量紧张，再评估在 coordinator 内加错峰 `power_cycle_offset_seconds` 开关（默认 0）。

## 2026-07-12 - Tftp Put 多台串行全包升级真实样机验收通过

- 类型：真实样机验收 / 状态更新
- 背景：Tftp Put 已完成前置下电上电、`UserName` 后 boot 登录、TFTPy 推送和串口终端自动收尾改造，需要确认多台按串行顺序执行时的完整链路。
- 完成内容：用户已完成全包升级 `Tftp Put` 多台串行真实样机验收，结果通过。
- 修改文件：`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：真实样机多台串行升级。
- 验证结果：通过。
- 后续待办：`Tftp指令` 两台并行仍待真实两台独立 VLAN 样机验收。

## 2026-07-12 - 全包升级结束后关闭自动打开的串口终端

- 类型：BUG 修复 / 测试 / 文档
- 背景：全包升级完成后，升级会话已写入 `STATE 串口已关闭` 并释放 COM 口，但本次自动打开的“串口日志记录”窗口仍残留。
- 完成内容：串口终端记录自动升级批次；串行全包升级和并行 `Tftp指令` 均在批次完成并释放会话后延迟 100ms 请求终端收尾。仅升级自动打开的终端会关闭，手动打开的终端保持打开。
- 修改文件：`Cheating_machine_execution_tool/src/ui/serial_terminal.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_serial_terminal.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串口终端、主界面升级流程相关测试、完整单元测试和源码编译检查。
- 验证结果：`python -m py_compile line_check_assistant/app.py src/ui/serial_terminal.py` 通过；串口终端专项 3 项、主界面专项 57 项通过；完整 `python -m unittest discover -s tests -v` 共 148 项通过。
- 后续待办：真实样机验证 `STATE 串口已关闭` 后本次自动打开的串口终端窗口关闭，手动打开的终端不受影响。

## 2026-07-12 - 恢复出厂命令同步到主程序执行日志

- 类型：优化 / 测试 / 文档
- 背景：串口日志可见 `TX firstboot -y;reboot`，但主程序执行日志未体现已实际下发恢复出厂命令，操作员无法在主界面确认危险操作是否执行。
- 完成内容：恢复出厂命令写入串口成功后，向主程序执行日志输出 `TX firstboot -y;reboot`；未启用恢复出厂时不输出该日志。两种全包升级传输方式均复用此日志回调，传输时序不变。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串行升级专项测试、完整单元测试和源码编译检查。
- 验证结果：`python -m py_compile src/services/serial_upgrade_service.py` 通过；串行升级专项 22 项通过；完整 `python -m unittest discover -s tests -v` 共 147 项通过。
- 后续待办：真实样机勾选恢复出厂时确认主程序执行日志出现该 TX 行；未勾选时确认不出现。

## 2026-07-12 - Tftp Put boot 登录不再漏掉同批 ECNT 提示

- 类型：BUG 修复 / 测试 / 文档
- 背景：真实串口日志显示 boot 密码提交后已出现 `ECNT>`，但 Tftp Put 专用登录逻辑在写密码并等待 1 秒后才记录 shell 等待游标，导致 `ECNT>` 落在游标之前而误报“boot 登录后未检测到 shell 提示符”。
- 完成内容：把 Tftp Put 专用 boot 登录的 shell 等待游标提前到 boot 密码写入前；`ecnt>` 已是现有 shell 提示识别项，修复后可匹配同批 `ECNT>` 并继续 TFTPy 传输。未改动 `Tftp指令` 路径。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串行升级专项测试、完整单元测试和源码编译检查。
- 验证结果：`python -m py_compile src/services/serial_upgrade_service.py` 通过；串行升级专项 21 项通过；完整 `python -m unittest discover -s tests -v` 共 146 项通过。
- 后续待办：使用真实 Tftp Put 样机确认 `ECNT>` 后立即进入 TFTPy 传输阶段。

## 2026-07-12 - Tftp Put boot 登录不再漏掉同批 Password 提示

- 类型：BUG 修复 / 测试 / 文档
- 背景：真实串口日志已显示 `UserName: telecomadmin` 后紧接 `Password:`，但 Tftp Put 专用登录逻辑在写用户名并等待 0.3 秒后才记录等待游标，导致同批到达的 `Password:` 落在游标之前而被漏检。
- 完成内容：把 Tftp Put 专用 boot 登录的密码等待游标提前到用户名写入前，确保用户名回显期间或同批数据中的完整 `Password:` 仍可匹配；未改动 `Tftp指令` 路径。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串行升级专项测试、完整单元测试和源码编译检查。
- 验证结果：`python -m py_compile src/services/serial_upgrade_service.py` 通过；串行升级专项 20 项通过；完整 `python -m unittest discover -s tests -v` 共 145 项通过。
- 后续待办：使用真实 Tftp Put 样机确认 `UserName` 后同批 `Password:` 可被识别并继续发送 boot 密码。

## 2026-07-12 - Tftp Put 检测 UserName 后按 boot 凭据登录并保留 TFTPy 上传

- 类型：BUG 修复 / 测试 / 文档
- 背景：`Tftp Put` 前置下电 + 上电完成后，现场要求以串口 `UserName:` 作为 boot 登录起点，沿用同事 `serial_upgrade.py` 的 boot 凭据交互，而不再先登录最终系统并发送 `reboot`。
- 完成内容：新增仅由 `Tftp Put` 调用的「循环回车等待 `UserName:` → `telecomadmin / nE7jA%5m` 登录 boot」状态机；登录成功后继续复用主程序 `prepare_tftp_network()` 和 TFTPy Client 上传，不调用 Windows `tftp.exe`。保留传输后的 boot 重启检测、最终系统登录及恢复出厂；`Tftp指令` 未调整。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串行升级专项测试、完整单元测试和源码编译检查。
- 验证结果：`python -m py_compile src/services/serial_upgrade_service.py` 通过；串行升级专项 19 项通过；完整 `python -m unittest discover -s tests -v` 共 144 项通过。
- 后续待办：使用真实 `Tftp Put` 样机确认日志顺序为“串口已开启”→等待 1 秒→检测到 `UserName`→boot 登录→TFTPy 上传。

## 2026-07-11 - Tftp Put 开始前先对样机执行下电 + 上电

- 类型：功能 / 程控电源 / 重构 / 测试 / 文档
- 背景：现场反馈 `Tftp Put` 升级时样机经常不是干净的上电状态，需要主程序在开始原有 reboot → boot → TFTP 流程前，先对程控电源对应通道做一次下电 + 上电，确保样机从已知上电状态启动；该需求与现有 `Tftp指令` 链路的「断电再上电」语义一致。
- 完成内容：把 `serial_upgrade_service.py` 中 `_run_tftp_command_with_power_supply` 内联的 `power_on_current_channel` 抽出为模块级 helper `_power_cycle_current_channel()`，复用 `power_on_selected_channels`（串行）或 `UpgradePowerCycleCoordinator`（并行）；`Tftp Put` 分支在打开串口后立即调用该 helper 对 `request.power_serial_port / request.power_channel` 执行下电 + 上电（`wait_seconds=0`，由后续 `login_final_system` 的 900 秒首轮等待兜底样机启动），失败立即返回；`Tftp指令` 链路行为保持不变，仅复用同一 helper。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile` 编译；运行 `test_serial_upgrade_service.py` 及完整单元测试。
- 验证结果：编译通过；`test_serial_upgrade_service.py` 新增 1 项（`test_full_package_upgrade_tftp_put_propagates_power_cycle_failure`），重命名 / 调整 2 项（原 `skips_programmable_power_supply` / `does_not_invoke_power_supply_module` 已不能描述新行为）；完整 `python -m unittest discover -s tests` 共 143 项全部通过。
- 后续待办：真实样机验证 `Tftp Put` 在开始 reboot 之前程控电源下电 + 上电日志与上电时序，并确认主流程未受影响。

## 2026-07-11 - 页面升级前先把网卡设为样机同网段

- 类型：优化 / 重构 / 测试 / 文档
- 背景：现场 `vlan137/138/139` 页面升级前 PC 网卡已启用但 IP 仍为旧配置，与样机管理 IP（如 `192.168.29.1`）不在同一网段，导致 HTTP/HTTPS 登录 UBUS 前路由不通。
- 完成内容：在 `network_ops.py` 抽出 `prepare_network_for_sample()`，封装「启用网卡 → 设置静态 IP → 缓冲 2 秒」的统一流程，原 `run_line_check` 复用同一 helper；`PageUpgradeRequest` 新增 `subnet_mask` 字段（默认 `255.255.255.0`），`run_single_page_upgrade` 在启用网卡之后改用 `prepare_network_for_sample()`，把 PC 静态 IP 切到样机管理 IP 所在网段；`app.py` 把 `ChannelConfig.subnet_mask` 透传给 `PageUpgradeRequest`。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_page_upgrade.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile` 编译主程序、网络与页面升级模块；运行 `test_network_ops.py`、`test_page_upgrade.py`、`test_app.py` 及完整单元测试。
- 验证结果：编译通过；`test_network_ops.py` 新增 6 项（启用网卡 + 静态 IP、启用失败、设 IP 失败、缺 alias、缺 bind_ip、display name 兼容）；`test_page_upgrade.py` 新增/调整 4 项；`test_app.py` 新增 1 项；完整 `python -m unittest discover -s tests` 共 142 项全部通过。
- 后续待办：使用真实 `vlan137/138/139` 复测页面升级，确认 PC 网卡 IP 已切到样机管理 IP 所在网段，且 HTTP/HTTPS 登录一次成功。

## 2026-07-11 - Boot 登录按新提示符逐步提交凭据

- 类型：BUG 修复 / 测试 / 文档
- 背景：现场日志显示 `UserName:` 与 `Password:` 分段到达时，用户名后仍可能使用旧串口缓存中的密码提示符，导致账号密码提交错位。
- 完成内容：Boot 登录仅在完整用户名提示符后发送用户名；用户名回车后重新取串口游标，只接受新到达的完整密码提示符才发送密码；登录结果也从密码回车后的新游标开始等待。
- 修改文件：`src/services/serial_upgrade_service.py`、`tests/test_serial_upgrade_service.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译串行升级服务，运行串行升级及完整单元测试。
- 验证结果：串行升级专项 12 项通过；完整 `python -m unittest discover -s tests -v` 共 124 项通过；新增回归测试确认密码提示符的等待游标晚于用户名回车，不会命中用户名输入前的旧缓存。
- 后续待办：使用真实 `Tftp指令` 样机复测分段 `UserName:` / `Password:` 回显。

## 2026-07-11 - 串口终端目录写入失败改为明确提示

- 类型：BUG 修复 / 测试 / 文档
- 背景：默认 `D:\Serial_Log` 或本机串口终端状态文件不可写时，原逻辑会吞掉异常，操作员无法判断日志或窗口设置未保存。
- 完成内容：默认日志目录创建失败和终端状态文件写入失败均弹出明确错误信息，并提示可通过“浏览…”选择可写日志目录。
- 修改文件：`src/ui/serial_terminal.py`、`tests/test_serial_terminal.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串口终端持久化测试和完整单元测试。
- 验证结果：`python -m py_compile` 通过；完整 `python -m unittest discover -s tests -v` 共 123 项通过；新增测试覆盖默认日志目录创建失败及终端状态文件保存失败时的错误弹窗。
- 后续待办：无。

## 2026-07-11 - 自动上/下电增加下电选择

- 类型：功能 / 测试 / 文档
- 背景：用户要求将“自动上电”扩展为“自动上/下电”，并在二级弹窗中用下拉框选择上电或下电，默认上电。
- 完成内容：工具栏入口改为“自动上/下电”；COM 选择弹窗新增默认“上电”的操作下拉框；下电仅向勾选通道按顺序发送关闭帧、相邻间隔 1 秒，不发送全断电帧。全包升级和 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 均未修改。
- 修改文件：`src/core/power_supply.py`、`src/services/power_on_service.py`、`src/services/__init__.py`、`line_check_assistant/app.py`、`tests/test_power_supply.py`、`tests/test_app.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译主程序和上下电服务；运行完整单元测试；核对旧工具源码哈希未变化。
- 验证结果：编译通过，完整 `python -m unittest discover -s tests -v` 共 111 项通过；单元测试验证下电仅发送所选通道关闭帧、相邻帧间隔 1 秒且不含全断电帧；`Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 哈希未变化。
- 后续待办：在真实程控电源上验收下电操作的关闭帧顺序和 1 秒间隔。

## 2026-07-11 - 取消自动上电后的启动等待

- 类型：优化 / 测试 / 文档
- 背景：用户要求最后一条自动上电开启帧发送后不再额外等待 10 秒。
- 完成内容：主程序自动上电的启动等待改为 0 秒；相邻开启帧的 1 秒间隔保持不变。全包升级及旧工具源码均未修改。
- 修改文件：`line_check_assistant/app.py`、`tests/test_app.py`、`tests/test_power_supply.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译主程序；运行完整单元测试；确认旧工具源码哈希未变化。
- 验证结果：编译通过，完整 `python -m unittest discover -s tests -v` 共 108 项通过；单元测试验证两条开启帧之间仅等待 1 秒、最后一条开启帧后无额外启动等待；`Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 哈希未变化。用户已在真实程控电源完成新自动上电流程验收，结果通过。
- 后续待办：无；全包升级的断电重启流程继续按独立路径验收。

## 2026-07-11 - 自动上电开启帧按通道间隔 1 秒

- 类型：BUG 修复 / 测试 / 文档
- 背景：现场日志显示通道 1-8 的开启帧在同一秒内连续发送；用户确认需要相邻开启指令间隔 1 秒。
- 完成内容：主程序“自动上电”的仅开启路径改为首个通道立即开启、后续每个通道开启前等待 1 秒；全部开启帧完成后再统一等待 10 秒。未改变断电策略、全包升级路径或 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py`。
- 修改文件：`src/core/power_supply.py`、`src/services/power_on_service.py`、`line_check_assistant/app.py`、`tests/test_power_supply.py`、`tests/test_app.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译主程序和上电服务；运行程控电源、主界面与串行升级单元测试；确认旧工具源码哈希未变化。
- 验证结果：待本次改动完成后填写。
- 后续待办：在真实程控电源上确认开启日志相邻时间约为 1 秒。

## 2026-07-11 - 自动上电改为一次性开启勾选通道

- 类型：优化 / 测试 / 文档
- 背景：用户要求主程序“自动上电”确认后一次性开启所有勾选通道，不再先完全断电或按通道逐个断电/上电；同时明确不得影响 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 业务逻辑。
- 完成内容：主程序新增仅开启通道的程控电源服务，连续发送勾选通道的开启帧且不插入关闭帧；自动上电统一等待 10 秒；全包升级原有断电重启路径及旧工具源码均未修改。
- 修改文件：`src/core/power_supply.py`、`src/services/power_on_service.py`、`src/services/__init__.py`、`line_check_assistant/app.py`、`tests/test_power_supply.py`、`tests/test_app.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译主程序和上电服务；运行程控电源、主界面及串行升级相关单元测试；比对旧工具源码未改动。
- 验证结果：`Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 与移动前 Git 版本哈希一致；编译通过，完整 `python -m unittest discover -s tests -v` 共 108 项通过；单元测试验证自动上电只写入全部勾选通道的开启帧，不含全断电或关闭帧，且全包升级仍走原有独立上电服务。
- 后续待办：使用真实程控电源确认多通道开启帧连续下发后，所有勾选通道可同时启动。

## 2026-07-11 - 统一主程序配置目录到旧工具源码目录

- 类型：重构 / 配置 / 文档 / 测试
- 背景：用户将 `Auto_power_on_off_tool` 移入 `Cheating_machine_execution_tool`，要求所有原先读写同级 `config` 的主程序逻辑统一改为读写 `Auto_power_on_off_tool/config`，并删除旧目录。
- 完成内容：新增统一配置目录解析；主界面通道、ONU 注册和样机升级状态均改写新目录；迁入现有通道配置和本机保存状态，保留旧工具已有的产品配置及原同级配置项；删除原同级 `config` 目录。
- 修改文件：`line_check_assistant/paths.py`、`line_check_assistant/app.py`、`tests/test_paths.py`、`.gitignore`、`Auto_power_on_off_tool/config`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译主程序与路径模块；运行路径和配置存储相关单元测试；确认旧目录不存在且主程序配置路径指向新目录。
- 验证结果：旧目录确认不存在；主程序导入后四个配置路径均指向新目录；迁入的通道配置可解析为 16 个通道、程控电源端口为 `COM105`；`python -m py_compile` 通过，完整 `python -m unittest discover -s tests -v` 共 106 项通过。
- 后续待办：真实设备流程继续以新目录中的 `network_card_ip.ini` 为唯一配置源。

## 2026-07-11 - 主程序内置程控电源直连，移除旧 GUI 上电依赖

- 类型：功能 / 重构 / 测试 / 文档
- 背景：自动上电和全包升级原先启动 `Auto_Power_On_Off_Tool.exe` 并通过 UI Automation 选择 COM、配置和 `Start ALL`，窗口控件状态会造成不稳定；用户提供旧工具源码，要求改为主程序直接控制程控电源。
- 完成内容：从旧源码提取 16 通道程控电源串口协议，新增无界面 `src/core/power_supply.py` 与上电服务；自动上电会二次确认“先关闭全部通道”，再按勾选的 `channel_x` 直接发送关闭/上电帧；全包升级从当前 `channel_x` 传递程控电源通道，写入上电帧后立即开始 boot 监听，重上电也走同一条直连路径；运行时主路径不再调用旧 EXE、PyQt 或 UI Automation。
- 修改文件：`Cheating_machine_execution_tool/src/core/power_supply.py`、`src/services/power_on_service.py`、`src/services/serial_upgrade_service.py`、`src/models/serial_models.py`、`src/core/__init__.py`、`src/services/__init__.py`、`line_check_assistant/app.py`、`tests/test_power_supply.py`、`tests/test_app.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译入口、主界面、直连核心和升级服务；导入主程序与上电服务；运行完整单元测试；检查运行时目录中不再存在旧 GUI 自动化调用。
- 验证结果：编译和导入通过；完整 `python -m unittest discover -s tests -v` 共 105 项通过；新增 5 项程控电源测试验证旧协议帧、全关后指定通道开关顺序、串口关闭、启动等待、非法通道不打开串口，以及全包升级首次上电和重上电均使用当前 `channel_x`。
- 后续待办：在真实程控电源上先验证 `COM` 口与 `19200 8N1` 参数、单通道断电/上电帧和通道映射；确认后再验收多通道自动上电及全包升级中的首次上电、重上电流程。

## 2026-07-11 - 修复主程序 VS Code 源码启动环境

- 类型：BUG 修复 / 配置 / 文档 / 测试
- 背景：用户在 VS Code 运行 `run_line_check_assistant.py` 时，专用 `.venv_serial_upgrade` 缺少主程序新增的 `tftpy`，启动期导入 `src.core.tftp_transport` 后报 `ModuleNotFoundError`；现有 F5 配置也只覆盖独立 `serial_upgrade.py`。
- 完成内容：为 VS Code 新增 `LineCheckAssistant` 调试入口，固定以 `Cheating_machine_execution_tool` 为工作目录；主程序依赖清单补充 `requests` 并在 `.venv_serial_upgrade` 安装 `tftpy==0.8.7`；README 补充首次安装依赖和 VS Code 运行步骤；项目状态同步主程序源码运行入口。
- 修改文件：`.vscode/launch.json`、`Cheating_machine_execution_tool/requirements.txt`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：使用 `.venv_serial_upgrade` 编译入口、主界面和 TFTP 模块；导入 `line_check_assistant.app`；执行 `pip check`；解析 `.vscode/launch.json`；运行 `test_tftp_transport.py`。
- 验证结果：编译通过；`LineCheckAssistant import OK`；`tftpy=0.8.7`；`No broken requirements found.`；`launch.json JSON OK`；`test_tftp_transport.py` 2 项通过。
- 后续待办：用户可在 VS Code 选择 `LineCheckAssistant` 后按 F5 完成界面与现场设备功能验证。

## 2026-07-10 - 主程序内置 pySerial 与 TFTPy 串行升级

- 类型：功能 / 重构 / 测试 / 文档
- 背景：全包升级原先依赖 SecureCRT、Tftpd64 和 Windows TFTP 客户端，串口状态机不可执行测试且多网卡源 IP 不可控。
- 完成内容：新增 `src/models`、`src/core`、`src/services`、`src/ui` 分层；pySerial 接管 VLAN→COM 的收发、状态 marker、终端显示与独占写锁；TFTPy Server 接管设备拉取并仅映射所选固件为 `tclinux_allinone`，TFTPy Client 接管 Put 并绑定当前通道源 IP；内置多通道终端替换占位窗口；保留两种 TFTP 语义、串行顺序、配置隔离、reset/登录/恢复出厂时序；移除旧 Python/VBS 自动化模块和旧实现测试。
- 修改文件：主界面、`src` 新模块、测试、依赖清单、第三方声明、构建脚本、README、PROJECT_STATUS。
- 验证方法：编译检查、完整单元测试、TFTPy 本机高端口上传/下载端到端测试。
- 验证结果：`python -m py_compile` 通过；完整 `python -m unittest discover -s tests -v` 100 项通过。
- 后续待办：在真实设备上分别验收两种传输、恢复出厂、多样机串行、端口占用、串口拔出、UDP 69 防火墙和多 `.1` 网卡源 IP。

## 2026-07-09 - 修复 Tftp Put 恢复出厂提交和 CRT 主窗口残留

- 类型：BUG 修复 / 优化 / 测试 / 文档
- 背景：用户验证 `Tftp Put` 模式在固件传输完成、重启并登录最终系统后，恢复出厂命令停留在 CRT 窗口中未真正下发；同时样机升级收尾只关闭了升级 Tab，SecureCRT 主窗口仍残留。
- 完成内容：恢复出厂逻辑改为发送 `firstboot -y;reboot` 后固定等待 1 秒再发送回车，不再等待命令回显；SecureCRT 升级脚本在关闭当前升级 Tab 后继续请求关闭 SecureCRT 主窗口，收尾日志同步说明 Tab 和主窗口都会由脚本请求关闭。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant/upgrade_cleanup.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/tests/test_tftpd_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、`test_securecrt_automation.py`、`test_tftpd_automation.py` 和完整单元测试。
- 验证结果：编译检查通过；`test_securecrt_automation.py` 16 项全部 OK；`test_tftpd_automation.py` 3 项全部 OK；完整 `python -m unittest discover -s tests -v` 123 项全部 OK。
- 后续待办：用真实 `Tftp Put + 恢复出厂` 样机升级复测，确认串口日志中命令 1 秒后下发并触发恢复出厂重启，且 SecureCRT 主窗口随升级结束关闭。

## 2026-07-08 - 恢复出厂命令发送后延迟关闭 SecureCRT Tab

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户验证勾选“恢复出厂”时，最终系统只成功登录，随后 SecureCRT 升级窗口很快关闭，`firstboot -y;reboot` 可能未完整下发。
- 完成内容：将恢复出厂发送逻辑从 `factoryResetCommand & vbCr` 后立即完成，改为先发送命令文本，等待命令回显或最多 5 秒，随后发送回车并记录 `RESTORE_FACTORY_SENT`，再额外等待 8 秒才写入 `DONE` 并关闭当前升级 Tab；回显未出现时记录 `RESTORE_FACTORY_ECHO_MISSED` 但继续发送回车，避免现场回显差异导致流程卡死。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/securecrt_automation.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、`test_securecrt_automation.py` 和完整单元测试。
- 验证结果：编译检查通过；`test_securecrt_automation.py` 16 项全部 OK；完整单元测试 123 项全部 OK。
- 后续待办：真实样机复测勾选“恢复出厂”时确认串口日志出现 `firstboot -y;reboot` 并触发重启。

## 2026-07-08 - SecureCRT 升级脚本完成后自关闭当前 Tab

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户验证多台样机串行 `Tftp Put` 升级可成功，但收尾日志显示未检测到本次新增 SecureCRT 窗口 PID，导致本轮升级打开的 CRT 窗口没有关闭。
- 完成内容：保留 Python 按本次新增 PID 兜底关闭的安全边界，避免误关用户手动 CRT；同时在 SecureCRT 升级脚本写入 `DONE` 后主动请求关闭当前脚本创建的升级 Tab，若关闭 API 不可用则写入 `SECURECRT_TAB_CLOSE_SKIPPED` 状态，避免因为窗口 PID 识别不到而无法关闭本轮升级 Tab；收尾日志改为说明脚本会自行请求关闭当前升级 Tab。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant/upgrade_cleanup.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/tests/test_tftpd_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、`test_securecrt_automation.py`、`test_tftpd_automation.py` 和完整单元测试。
- 验证结果：编译检查通过；`test_securecrt_automation.py` 16 项全部 OK；`test_tftpd_automation.py` 3 项全部 OK；完整单元测试 123 项全部 OK。
- 后续待办：用真实多台 `Tftp Put` 串行升级确认每台升级完成后当前 CRT Tab 能自动关闭。

## 2026-07-08 - 修复恢复出厂选项显示与确认状态

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户反馈 `Tftp Put` 单台升级成功后，未勾选“恢复出厂”却实际执行了恢复出厂。
- 完成内容：定位为样机升级窗口初始化时“恢复出厂”文字固定显示为未勾选，但底层布尔值会从 `config/sample_upgrade_settings.ini` 读取上次保存状态，可能出现界面显示未勾选而实际请求为开启；改为初始化文本直接按真实保存值生成，并在开始串行升级确认框中明确显示“恢复出厂：开启/关闭”。同时确认 SecureCRT 脚本仅在 manifest 字段为 `"1"` 时发送 `firstboot -y;reboot`。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、`test_app.py`、`test_securecrt_automation.py` 和完整单元测试。
- 验证结果：编译检查通过；`test_app.py` 55 项全部 OK；`test_securecrt_automation.py` 16 项全部 OK；完整单元测试 123 项全部 OK。
- 后续待办：用真实样机再次确认未勾选恢复出厂时不会发送 `firstboot -y;reboot`。

## 2026-07-08 - 收尾只关闭本次启动的 SecureCRT PID

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户反馈升级收尾日志中强制关闭了多个 SecureCRT 进程，其中部分是用户手动打开的其它 CRT 串口窗口。
- 完成内容：定位为 `upgrade_cleanup.py` 按进程名关闭所有 `SecureCRT`，清理范围过宽；改为启动 SecureCRT 前后对比新增窗口句柄并反查真实 PID，单台升级把新增 PID 回传给串行 worker，收尾只按这些精确 PID 关闭本次启动的 SecureCRT，同时继续按精确路径关闭项目目录下的 `tftpd64.exe`；未识别到新增 PID 时保留现有 CRT 会话。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/upgrade_cleanup.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_tftpd_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、SecureCRT PID 获取测试、单台升级 PID 回传测试、串行 worker 收尾传参测试、Tftpd/收尾脚本测试和完整单元测试。
- 验证结果：编译检查通过；完整单元测试 122 项全部 OK。
- 后续待办：真实升级后确认只关闭本次升级启动的 SecureCRT 窗口，不影响用户手动打开的其它 CRT 会话。

## 2026-07-08 - 提前 Tftp Put 进入 boot 敲回车时机

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户实测 `Tftp Put` 模式未成功进入 boot，原因是 SecureCRT 开始循环敲击回车的时间滞后，错过允许进入 boot 的窗口期。
- 完成内容：将 `boot_enter.signal` 从旧工具完整上电流程返回后前移到旧工具输出“已点击 Start ALL”时立即写出，让 SecureCRT 在 Start ALL 后马上每隔 1 秒敲击回车；保留旧软件关闭后的兜底信号，避免旧工具未输出该行时流程卡住。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、`test_sample_upgrade.py` 和完整单元测试，并补充 Start ALL 输出时立即写 boot signal 的回归测试。
- 验证结果：编译检查通过；`test_sample_upgrade.py` 11 项全部 OK；完整单元测试 121 项全部 OK。
- 后续待办：用真实样机复测 `Tftp Put` 进入 boot 时序。

## 2026-07-08 - 接入全包升级 Tftp Put 传输方式

- 类型：功能 / 测试 / 文档
- 背景：用户确认 `Tftp指令` 和 `Tftp Put` 是两种不同的固件传输方式，`Tftp Put` 目标设备 IP 固定为 `192.168.1.1`，需要在样机升级模块中都做适配。
- 完成内容：`全包升级 + Tftp Put` 进入现有多台串行升级流程；单台流程在 SecureCRT 完成 boot 登录后执行 Windows `tftp -i 192.168.1.1 put <升级固件路径>`，不启动 Tftpd64；Put 成功后继续复用现有 boot reset/重新上电、120 秒等待和最终登录确认；SecureCRT manifest 增加传输方式字段，脚本按 `Tftp指令` / `Tftp Put` 分支同步状态。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/securecrt_automation.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、样机升级入口测试、单台升级编排测试、SecureCRT 自动化测试和完整单元测试。
- 验证结果：编译检查通过；`test_app.py` 54 项通过；`test_sample_upgrade.py` 10 项通过；`test_securecrt_automation.py` 16 项通过；完整单元测试 120 项全部 OK。
- 后续待办：用真实样机验收 `全包升级 + Tftp Put`。

## 2026-07-08 - 样机升级 Tftp 文案调整

- 类型：修改 / 测试 / 文档
- 背景：用户要求将样机升级模块中的“Tftp拷贝命令”显示文案改为“Tftp指令”。
- 完成内容：样机升级固件传输方式下拉框、提示文案和确认文案统一显示为“Tftp指令”；保留旧配置值“Tftp拷贝命令”的自动兼容映射，避免已保存本机配置影响串行升级入口。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查和样机升级入口相关单元测试。
- 验证结果：编译检查通过；`test_app.py` 53 项全部 OK。
- 后续待办：无。

## 2026-07-07 - 页面升级前自动启用目标网卡

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户实测 `vlan137`、`vlan138` 页面升级失败，原因为 PC 对应 VLAN 网卡未启用，导致无法登录 UBUS。
- 完成内容：页面升级请求新增目标网卡字段；每台样机执行 UBUS 登录前先调用现有 `enable_adapter()` 启用对应网卡，启用失败则只标记该样机失败并保留日志，其它并行样机继续执行。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_page_upgrade.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行页面升级单元测试、样机升级入口测试、编译检查和完整测试集。
- 验证结果：编译检查通过；`test_page_upgrade.py` 5 项通过；`test_app.py` 52 项通过；完整单元测试 111 项全部 OK。
- 后续待办：用真实 `vlan137`、`vlan138` 复测未启用网卡场景。

## 2026-07-07 - 兼容 UBUS 触发升级 Access denied

- 类型：BUG 修复 / 测试
- 背景：用户实测页面升级时，`vlan139` 在触发 UBUS 升级阶段返回 `Access denied`；后续确认原因是浏览器仍登录样机 Web 管理界面，退出 Web 管理界面后升级成功。
- 完成内容：为 UBUS RPC 错误增加调用点上下文；触发升级命令从单一 `bbfdm.operate` 改为依次尝试 `bbfdm.operate`、`bbfdm.operate(proto=web)` 和 `bbfdm.unauthenticated_operate`，遇到 `Access denied` 时自动尝试下一种兼容方式，并在日志中输出切换过程。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`、`Cheating_machine_execution_tool/tests/test_page_upgrade.py`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行页面升级单元测试、样机升级入口测试、编译检查和完整测试集。
- 验证结果：编译检查通过；`test_page_upgrade.py` 4 项通过；`test_app.py` 52 项通过；完整单元测试 110 项全部 OK。
- 后续待办：页面升级操作前提醒退出样机 Web 管理界面；如后续仍出现 `Access denied`，再根据日志中的 UBUS 调用点排查账号权限或接口差异。

## 2026-07-07 - 接入 UBUS 页面批量升级

- 类型：功能 / 测试 / 文档
- 背景：用户提供同事的 `ubus_upgrade_gui.py` / `ubus_upgrade.py`，要求将已验证的 UBUS 批量页面升级能力合并到现有“样机升级”的“页面升级”功能中。
- 完成内容：新增页面升级业务模块，支持绑定本机 IP、HTTP/HTTPS 登录 UBUS、上传固件、触发升级、查询状态和等待重启上线；“页面升级”按钮改为按已勾选通道并行执行 UBUS 批量升级；保留“全包升级 + Tftp拷贝命令”现有串行流程。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_page_upgrade.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、页面升级单元测试、样机升级入口单元测试和完整测试集。
- 验证结果：编译检查通过；`test_page_upgrade.py` 2 项通过；`test_app.py` 52 项通过；完整单元测试 108 项全部 OK。
- 后续待办：使用真实样机验证页面升级的单台、多台并行和失败日志表现。

## 2026-07-07 - 配置 serial_upgrade.py 的 VS Code 运行环境

- 类型：配置 / 文档 / 测试
- 背景：用户希望直接在 VS Code 中运行 `Cheating_machine_execution_tool/test_boot_upgrade/serial_upgrade.py`。
- 完成内容：新增 VS Code 默认解释器与调试入口；新增 `test_boot_upgrade/requirements.txt`；将专用本地 Python 环境加入忽略列表；更新 `serial_upgrade` 使用指南和项目状态。
- 修改文件：`.vscode/settings.json`、`.vscode/launch.json`、`.gitignore`、`Cheating_machine_execution_tool/test_boot_upgrade/requirements.txt`、`Cheating_machine_execution_tool/test_boot_upgrade/使用指南.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：创建本地 Python 环境，安装 `pyserial`、`selenium`、`webdriver-manager`、`openpyxl`；运行编译检查和依赖导入检查。
- 验证结果：`python -m py_compile serial_upgrade.py` 通过；`serial`、`selenium`、`webdriver_manager`、`openpyxl` 导入通过。
- 后续待办：首次选择“页面升级”时，若 `webdriver-manager` 下载 Edge WebDriver 被网络或证书拦截，需要按现场网络环境处理。

## 2026-07-03 - 兼容旧工具 exe 新文件名

- 类型：优化 / 测试 / 文档
- 背景：用户将旧开关机工具从 `Auto_Power_On_Off_Tool(2).exe` 改名为 `Auto_Power_On_Off_Tool.exe`，要求程序只按 `Auto_Power_On_Off_Tool` 关键字识别。
- 完成内容：新增旧工具路径解析函数，查找根目录下文件名包含 `Auto_Power_On_Off_Tool` 且后缀为 `.exe` 的旧工具，优先使用 `Auto_Power_On_Off_Tool.exe`，兼容原 `(2)` 文件名；主程序自动上电和样机升级流程共用解析后的旧工具路径。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/paths.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_paths.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\paths.py`、`python -m unittest discover -s tests -p test_paths.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_paths.py` 3 项全部 OK；完整单元测试 103 项全部 OK。
- 后续待办：无。

## 2026-07-03 - ONU注册 清理离线 ONU 后重新注册

- 类型：BUG 修复 / 安全提示 / 测试 / 文档
- 背景：用户反馈原有 ONU 替换方式会替换到与新发现 ONU 不同 PON 口的旧 ONU，正确流程应删除不在线 ONU 后重新注册新 ONU。
- 完成内容：ONU 注册新增配置失败后不再执行 `registration-method sn 新SN` 复用旧 ONU 配置；改为查询 `show gpon onu state`，筛选已注册但不在线 ONU，优先删除和新 ONU 同 PON 口的不在线 ONU，再删除其它 PON 口不在线 ONU，删除后重新下发新 ONU 注册模板；注册确认提示同步说明该删除和重试行为。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_network_ops.py` 24 项全部 OK；完整单元测试 100 项全部 OK；新增回归覆盖新增配置失败后查询离线 ONU、优先删除同 PON 口离线 ONU、再删除其它 PON 口离线 ONU，并确认不再下发 `registration-method sn 新SN`。
- 后续待办：无。

## 2026-07-02 - 优化 ONU注册 长状态栏显示

- 类型：UI / 优化 / 测试 / 文档
- 背景：用户反馈 ONU注册 窗口中查询/注册状态栏显示不完整，长注册结果会在右侧被截断。
- 完成内容：将 ONU注册 查询/注册状态栏改为支持自动换行的多行状态框，增加垂直内边距并改为左上对齐；绑定状态框宽度变化，动态更新换行宽度，避免长 SN 或长注册结果被截断。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`，并执行 ONU注册 长状态文本布局探针。
- 验证结果：编译检查通过；`test_app.py` 49 项全部 OK；布局探针确认状态栏 `anchor=nw`、`pady=4`、`wraplength=640`。
- 后续待办：无。

## 2026-07-02 - ONU注册 注册后确认保存 OLT 配置

- 类型：功能 / 安全提示 / 测试 / 文档
- 背景：用户要求新 ONU 注册完成后弹出提示，询问是否保存 OLT 最新配置；用户确认保存时执行 `write` 写入启动配置。用户进一步验证确认这台 OLT 需要先退出全局模式，不能在 `ZXAN(config)#` 下执行 `write`。
- 完成内容：新增 OLT 配置保存底层能力，保存时独立登录 OLT，若检测到 `config` 或 `config-if` 提示符则循环执行 `exit` 直到回到执行模式，再执行 `write`；ONU 注册成功后弹窗询问是否保存，用户确认后异步执行保存并显示/记录保存结果，用户取消则只记录暂不保存。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_network_ops.py` 24 项全部 OK；`test_app.py` 49 项全部 OK；完整单元测试 100 项全部 OK；新增测试覆盖 `ZXAN(config)# exit -> ZXAN# write`、`ZXAN(config-if)# exit -> ZXAN(config)# exit -> ZXAN# write` 和注册成功后确认/取消保存两种 UI 分支。
- 后续待办：无。

## 2026-07-02 - 微调 ONU注册 密码小眼睛和开始注册按钮位置

- 类型：UI / 优化 / 测试
- 背景：用户反馈 ONU注册 窗口中密码小眼睛需要往右边移一点，“开始注册”按钮需要往左边移一点。
- 完成内容：将 ONU注册 密码输入框容器横跨右侧一列，让小眼睛按钮更靠右显示；收窄“取消全选”和“开始注册”之间的横向间距，使“开始注册”按钮整体更靠左。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`，并执行 ONU注册 布局探针确认密码容器跨列、按钮 padding 生效。
- 验证结果：编译检查通过；`test_app.py` 47 项全部 OK；布局探针显示密码容器 `columnspan=2`，小眼睛按钮右侧打包，开始注册按钮保持左对齐且横向 padding 已收窄。
- 后续待办：无。

## 2026-07-02 - ONU注册 新增配置失败后复用旧 ONU 配置

- 类型：功能 / 安全提示 / 测试 / 文档
- 背景：用户确认复用旧 ONU 配置的正确命令为进入已注册 ONU 接口后执行 `registration-method sn 新SN`，并要求“开始注册”优先使用新增 ONU 业务配置；如果新增配置过程中业务命令报错，则改用复用旧 ONU 配置的方式让新 ONU 上线。
- 完成内容：ONU 注册底层流程在新增配置命令失败时不再直接退出，而是切回执行模式查询 `show gpon onu state`，自动选择已注册但未在线的 ONU（例如 OMCC 非 enable 或 Phase 非 working），重新进入全局模式后执行 `interface gpon-onu_旧ONU接口` 与 `registration-method sn 新SN`；注册确认提示同步说明该 fallback 会替换旧 ONU 的认证 SN；结果状态会区分“新增配置成功”和“新增配置失败后复用旧 ONU 配置”。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_network_ops.py` 21 项全部 OK；`test_app.py` 47 项全部 OK；完整单元测试 95 项全部 OK；新增测试已模拟 `service Internet gemport 1 vlan 200` 返回错误后自动执行 `show gpon onu state`、选择离线旧 ONU 并下发 `registration-method sn 新SN`。
- 后续待办：如后续需要由用户手动指定要复用的旧 ONU 口，可在 ONU注册列表旁增加“旧 ONU 口选择”或“自动/手动复用”模式。

## 2026-07-02 - ONU注册 接入开始注册功能

- 类型：功能 / UI / 测试 / 文档
- 背景：用户要求在已查询出的未注册 ONU 列表基础上实现“开始注册”功能，用于将勾选的 ONU 注册上线。
- 完成内容：新增 ONU 注册底层 Telnet 下发能力，按已确认的 ZTE OLT / SD-41 模板生成 `interface gpon-olt`、`interface gpon-onu`、业务 VLAN、`pon-onu-mng` 等配置命令；ONU注册窗口新增“开始注册”按钮，仅对勾选 ONU 生效，执行前二次确认，执行中禁用相关按钮，完成后在状态栏显示结果并写入运行日志；注册不会自动保存 OLT 配置，完成后提示重新查询确认上线。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 “开始注册”按钮和勾选列表 Tk 探针。
- 验证结果：编译检查通过；`test_app.py` 47 项全部 OK；`test_network_ops.py` 19 项全部 OK；完整单元测试 93 项全部 OK；ONU注册 UI 探针通过。`test_network_ops.py` 首次在普通沙箱遇到 Windows ACL 读权限错误，已按规则提权重跑并通过。
- 后续待办：如需要将 OLT 配置保存为启动配置，可在后续增加独立确认后的保存按钮或注册完成后的保存选项。

## 2026-07-02 - ONU注册 未注册 ONU 列表增加选择框

- 类型：UI / 功能 / 测试 / 文档
- 背景：用户要求在查询到的未注册 ONU 列表中，每个 ONU 前面都加选择框，方便后续决定要注册哪些 ONU，并增加全选和取消全选按钮。
- 完成内容：查询结果状态栏改为显示查询摘要；未注册 ONU 明细改为复选框列表，每行包含接口、SN 和状态；新增“全选”和“取消全选”按钮，查询到结果后启用，无结果或查询失败时禁用并清空旧选择。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 复选框渲染探针。
- 验证结果：编译检查通过；`test_app.py` 43 项全部 OK；`test_network_ops.py` 15 项全部 OK；完整单元测试 85 项全部 OK；ONU注册 复选框渲染探针通过。
- 后续待办：注册流程接入时读取用户勾选的 ONU 列表并执行注册。

## 2026-07-02 - ONU注册 查询所有 PON 口未注册 ONU

- 类型：功能 / UI / 测试 / 文档
- 背景：用户要求点击 ONU注册 的“开始查询”时，把 OLT 所有 PON 口下未注册的 ONU 都显示出来。
- 完成内容：新增 `show gpon onu uncfg` 只读查询能力，登录 OLT 后查询所有 PON 口未注册 ONU 并解析接口、SN 和状态；“开始查询”按钮改为异步查询流程，查询中禁用按钮，完成后在查询状态栏显示全部结果并写入运行日志。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`，并用真实 OLT 执行只读查询函数。
- 验证结果：编译检查通过；`test_app.py` 42 项全部 OK；`test_network_ops.py` 15 项全部 OK；完整单元测试 84 项全部 OK；真实 OLT 只读查询返回 3 个未注册 ONU。
- 后续待办：后续接入注册配置时，基于查询出的接口和 SN 做选择/填充。

## 2026-07-02 - ONU注册 连通性测试后登录 OLT 并进入全局模式

- 类型：功能 / UI / 测试 / 文档
- 背景：用户要求点击 ONU注册 的连通性测试后，如果 Telnet 连通性通过，则直接使用界面填写的用户名和密码登录 OLT，并在登录成功后下发 `configure terminal` 进入全局模式；登录状态需要显示在状态栏。
- 完成内容：新增 OLT Telnet 登录和进入全局模式的底层能力；连通性测试按钮现在会先确认该操作，再测试 Telnet 23 端口，连通后登录 OLT 并下发 `configure terminal`；OLT IP 右侧仍只显示 Telnet 连通性结果，登录和全局模式结果显示在查询入口下方状态栏，并写入运行日志。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_app.py` 41 项全部 OK；`test_network_ops.py` 13 项全部 OK；完整单元测试 81 项全部 OK。
- 后续待办：用真实 OLT 确认具体登录提示符和全局模式提示符，如设备提示符与当前通用解析不同，再按实际提示符细化解析。

## 2026-07-02 - 调整 ONU注册 状态显示和窗口默认尺寸

- 类型：UI / 优化 / 文档 / 测试
- 背景：用户要求 ONU注册 模块中 OLT IP 右侧的连通性状态只显示 Telnet 状态，其它状态信息显示在“查询未注册的ONU”下方；同时默认宽减少 1cm、默认高减少 3cm。
- 完成内容：将 ONU注册 状态分为 Telnet 连通性状态和查询状态两块；Telnet 结果仍显示在 OLT IP 右侧，查询未注册 ONU 的占位/后续状态显示在查询入口下方；窗口默认尺寸从 `934x694` 调整为 `896x580`，最小尺寸从 `874x644` 调整为 `836x530`。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 窗口尺寸和状态分区探针。
- 验证结果：编译检查通过；`test_app.py` 41 项全部 OK；完整单元测试 79 项全部 OK；ONU注册 窗口尺寸和状态分区探针通过。
- 后续待办：无。

## 2026-07-02 - 加大 ONU注册 窗口尺寸

- 类型：UI / 优化 / 文档 / 测试
- 背景：用户要求将 ONU注册 模块界面的长宽都加大 3cm。
- 完成内容：将 ONU注册 窗口默认尺寸从 `820x580` 调整为 `934x694`，最小尺寸从 `760x530` 调整为 `874x644`，按 96 DPI 折算长宽各增加约 3cm；同步更新 README 和项目状态说明。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`，并执行 ONU注册 窗口尺寸探针。
- 验证结果：编译检查通过；`test_app.py` 40 项全部 OK；ONU注册 窗口尺寸探针通过。
- 后续待办：无。

## 2026-07-02 - 修复启动配置解析失败

- 类型：BUG 修复 / 配置 / 测试
- 背景：项目源码启动时报 `configparser.ParsingError`，原因是 `config/network_card_ip.ini` 中 `channel_14` 的 `adapter_alias` 行被截断为无效的 `adapter_al`。
- 完成内容：补全 `channel_14` 的 `adapter_alias`、`network_card_ip`、`device_manage_ip`、`subnet_mask` 配置项，恢复 INI 文件合法结构。
- 修改文件：`Cheating_machine_execution_tool/config/network_card_ip.ini`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\run_line_check_assistant.py .\line_check_assistant\app.py .\line_check_assistant\config_store.py`，并用 `ChannelConfigStore` 加载配置。
- 验证结果：配置解析恢复正常，源码入口不再因 `network_card_ip.ini` 解析错误而退出。
- 后续待办：如需要使用打包版启动，需要重新生成 `dist\LineCheckAssistant.exe`。

## 2026-07-02 - 新增 ONU注册 功能入口

- 类型：功能 / UI / 文档 / 测试
- 背景：用户要求在主界面“常用工具”中增加“ONU注册”功能入口，并保持软件界面风格一致。
- 完成内容：在常用工具栏新增 `ONU注册` 按钮；新增同风格独立占位窗口，展示 OLT 连接、ONU 标识、注册方式、注册状态等后续流程入口；窗口当前不登录设备、不修改配置、不执行注册操作。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py` 和 `python -m unittest discover -s tests -p test_app.py -v`。
- 验证结果：编译检查通过；`test_app.py` 28 项全部 OK。
- 后续待办：后续明确 ONU 注册协议、OLT 登录方式、SN/LOID 字段和注册校验规则后，再接入实际业务流程。

## 2026-07-02 - 完善 ONU注册 窗口表单和 Telnet 连通性测试

- 类型：功能 / UI / 测试 / 文档
- 背景：用户要求将 ONU注册 窗口中的占位项改为可输入表单：OLT IP 默认 `172.18.18.151`，支持 Telnet 连通性测试；ONU标识改为用户名和密码；注册方式改为查询未注册的ONU并提供开始查询按钮。
- 完成内容：新增 OLT IP、用户名、密码输入框；新增连通性测试按钮，调用底层 Telnet 23 端口连接检查；新增查询未注册 ONU 的开始查询入口占位；保持窗口配色、间距和按钮样式与现有界面一致。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_app.py` 31 项全部 OK；`test_network_ops.py` 11 项全部 OK；完整单元测试 63 项全部 OK。
- 后续待办：明确 OLT 登录提示符、查询未注册 ONU 的 Telnet 命令和解析规则后，再接入实际查询流程。

## 2026-07-02 - 保存 ONU注册 输入框上次关闭状态

- 类型：功能 / 配置 / 测试 / 文档
- 背景：用户要求 ONU注册 中所有输入框填写的信息都能保存上一次关闭时的信息，并明确默认 OLT IP 也要恢复上次关闭状态。
- 完成内容：新增 ONU 注册配置存储模块；OLT IP、用户名、密码会自动保存到本机 `config/onu_registration.ini`，关闭 ONU 窗口或直接关闭主程序时会立即保存；首次没有历史配置时才使用默认 OLT IP `172.18.18.151`；新增 `.gitignore` 规则避免本机凭据配置进入 Git。
- 修改文件：`.gitignore`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/onu_registration_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\onu_registration_store.py`、`python -m unittest discover -s tests -v`，并执行窗口关闭持久化探针。
- 验证结果：编译检查通过；完整单元测试 68 项全部 OK；窗口关闭持久化探针通过。
- 后续待办：后续接入真实 ONU 查询流程时，继续复用该本机配置作为默认连接信息。

## 2026-07-02 - 保存样机升级窗口上次关闭状态

- 类型：功能 / 配置 / 测试 / 文档
- 背景：用户补充说明其它功能模块也要保存上一次关闭时的状态，例如样机升级模块。
- 完成内容：新增样机升级设置存储模块；保存升级方式、固件传输方式、恢复出厂选项、超级用户名、密码和固件路径；关闭样机升级窗口或直接关闭主程序时立即保存；新增 `.gitignore` 规则避免本机样机升级输入状态进入 Git。
- 修改文件：`.gitignore`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\onu_registration_store.py .\line_check_assistant\sample_upgrade_settings_store.py`、`python -m unittest discover -s tests -v`，并执行样机升级关闭后重新打开的临时配置探针。
- 验证结果：编译检查通过；完整单元测试 72 项全部 OK；样机升级关闭后重新打开探针通过。
- 后续待办：后续如“写样机参数”“串口日志”等模块增加真实输入框，也按同一模式保存到本机配置文件并加入 Git 忽略。

## 2026-07-02 - 调整 ONU注册 连通性结果显示位置

- 类型：UI / 文档 / 测试
- 背景：用户要求将 OLT IP 的连通性测试结果显示到 OLT IP 输入框右侧、连通性测试按钮左侧的位置。
- 完成内容：移除 ONU注册 窗口底部状态行，将 Telnet 连通性测试结果改为显示在 OLT IP 输入框和连通性测试按钮之间的内联结果框。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 窗口初始化探针。
- 验证结果：编译检查通过；`test_app.py` 36 项全部 OK；完整单元测试 72 项全部 OK；ONU注册 窗口初始化探针通过。
- 后续待办：无。

## 2026-07-02 - ONU注册 密码框增加小眼睛切换

- 类型：UI / 测试 / 文档
- 背景：用户要求 ONU注册 模块的密码输入框增加小眼睛，可点击切换明文和密文显示。
- 完成内容：ONU注册 密码输入框改为带小眼睛按钮的组合控件；点击小眼睛可在 `*` 密文和明文显示之间切换，行为与样机升级密码框保持一致。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 密码小眼睛切换探针。
- 验证结果：编译检查通过；`test_app.py` 37 项全部 OK；完整单元测试 73 项全部 OK；ONU注册 密码小眼睛切换探针通过。
- 后续待办：无。

## 2026-07-02 - 修复样机升级配置后无法关闭窗口

- 类型：BUG 修复 / 配置 / 测试
- 背景：用户反馈样机升级模块填写升级配置后，点击关闭无法关闭，主界面也无法关闭，表现像卡死。
- 完成内容：定位为保存本机配置时 `ConfigParser` 默认插值会把密码或路径中的 `%` 当成特殊语法并抛异常，导致关闭回调未执行 `destroy()`；将 ONU注册 和 样机升级 的本机配置存储改为 `RawConfigParser`，支持保存 `%` 等普通字符；关闭 ONU注册、样机升级窗口和主窗口时，即使保存异常也会继续关闭窗口。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/onu_registration_store.py`、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_store.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\sample_upgrade_settings_store.py .\line_check_assistant\onu_registration_store.py`、`python -m unittest discover -s tests -v`，并执行包含 `%` 密码/路径的样机升级关闭回归探针。
- 验证结果：编译检查通过；完整单元测试 76 项全部 OK；包含 `%` 密码/路径的关闭回归探针通过。
- 后续待办：无。

## 2026-07-02 - ONU注册 Telnet 连通性结果增加状态颜色

- 类型：UI / 测试 / 文档
- 背景：用户要求 Telnet 连通性测试通过或失败时，用不同颜色区分结果。
- 完成内容：ONU注册 的内联连通性结果框增加颜色状态；测试中显示警告色，测试通过显示绿色，测试失败或未输入 OLT IP 显示红色。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 状态颜色探针。
- 验证结果：编译检查通过；`test_app.py` 40 项全部 OK；完整单元测试 78 项全部 OK；ONU注册 状态颜色探针通过。
- 后续待办：无。

## 2026-06-27 - 多台串行全包 Tftp 升级验收通过

- 类型：测试 / 项目状态
- 背景：用户反馈“全包 + Tftp 命令传输 + 多台串行升级”验收通过，今日开发到此结束。
- 完成内容：记录真实设备验收结论，并同步项目状态，将多台串行升级标记为已验收通过。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`
- 验证方法：用户在真实设备上验收“全包 + Tftp 命令传输 + 多台串行升级”流程。
- 验证结果：验收通过。
- 后续待办：后续再评估多台并发 TFTP 传输/并发升级，以及不同项目/型号和异常场景补强。

## 2026-06-27 - 升级收尾自动关闭 SecureCRT 和 Tftpd64

- 类型：优化 / 测试 / 文档
- 背景：用户要求在打印“已恢复 network_card_ip.ini 中用户选择的完整通道配置。”时，同步关闭升级过程中打开的串口工具，例如 SecureCRT 和 Tftpd64。
- 完成内容：新增升级收尾清理逻辑；多台串行升级恢复完整通道配置后，自动关闭 SecureCRT 进程和项目目录下的 `tftpd64.exe`；关闭过程输出到升级日志。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/upgrade_cleanup.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_tftpd_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\upgrade_cleanup.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_tftpd_automation.py -v` 和完整 `python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；完整 `python -m unittest discover -s tests -v` 57 项全部 OK。
- 后续待办：真实升级完成后确认 SecureCRT/Tftpd64 能被自动关闭，且不会影响需要保留的人工 SecureCRT 会话。

## 2026-06-27 - 上电等待时间改为每通道 10 秒

- 类型：修改 / 测试 / 文档
- 背景：用户要求把上电等待从 5 秒改为 10 秒。
- 完成内容：升级流程中每台样机调用旧开关机工具后的等待时间改为 10 秒；主界面“自动上电”按启用通道数每通道 10 秒计算等待时间；同步 README 和项目状态说明。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\sample_upgrade.py` 和 `python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；完整 `python -m unittest discover -s tests -v` 55 项全部 OK。
- 后续待办：使用真实设备确认 10 秒上电等待是否足够稳定。

## 2026-06-27 - 按当前通道临时改写 network_card_ip.ini 实现真实串行上电

- 类型：BUG 修复 / 功能 / 测试 / 文档
- 背景：用户指出旧开关机工具会按 `network_card_ip.ini` 从上往下逐台上电；如果配置里同时保留多台样机，旧工具 `Start ALL` 仍会操作多个通道，导致新软件内部串行不等于真实串行上电。
- 完成内容：多台串行升级开始时保存用户选择的完整通道快照；每台升级前写入 `network_card_ip.ini` 只保留当前通道；当前通道升级完成后再写入下一台；串行结束或失败后恢复完整通道配置。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py` 和 `python -m unittest discover -s tests -p test_app.py -v`。
- 验证结果：编译检查通过；完整 `python -m unittest discover -s tests -v` 55 项全部 OK。
- 后续待办：使用真实多台样机验证旧工具每次只给当前 `network_card_ip.ini` 中保留的通道上电。

## 2026-06-27 - 修复串行升级提示 VLAN 与实际上电顺序不一致

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户验收发现勾选 `vlan137`、`vlan138`、`vlan139` 后，界面提示正在升级 `vlan137`，但旧工具实际先启动的是 `VLAN139` 上电。
- 完成内容：多台串行升级不再按 VLAN 数字排序，而是按主界面通道顺序生成升级队列，让确认提示、状态栏和旧工具实际上电顺序保持一致。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py` 和 `python -m unittest discover -s tests -p test_app.py -v`。
- 验证结果：编译检查通过；`test_app.py` 26 项全部 OK；完整 `python -m unittest discover -s tests -v` 55 项全部 OK。
- 后续待办：继续用真实多台样机验证主界面通道顺序与旧工具上电顺序是否完全一致；如仍有偏差，需要进一步接入旧工具单通道选择/上电能力。

## 2026-06-27 - 实现多台样机串行 Tftp 拷贝升级

- 类型：功能 / 测试 / 文档
- 背景：用户要求开始实现多台串行升级，在单台样机已验证通过的基础上扩展到多个已勾选通道。
- 完成内容：全包升级 + Tftp 拷贝命令支持选择多个目标 VLAN，启动前确认，按主界面通道顺序逐台复用单台升级流程；某台失败时停止后续样机并提示失败信息。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\sample_upgrade.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_sample_upgrade.py -v`。
- 验证结果：编译检查通过；`test_app.py` 26 项通过；`test_sample_upgrade.py` 5 项通过；完整 `python -m unittest discover -s tests -v` 55 项全部 OK。
- 后续待办：使用真实多台样机验证串行升级流程；后续再评估并发 TFTP 传输/并发升级。

## 2026-06-27 - 单台样机 Tftp 拷贝升级和复位流程验证通过

- 类型：测试 / 项目状态
- 背景：用户反馈单台样机通过 Tftp 拷贝命令和复位功能已经验证通过。
- 完成内容：记录真实设备验证结论，并同步项目状态，明确单台样机“全包升级 + Tftp 拷贝命令 + reset/重新上电后登录确认”流程已通过验证。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`
- 验证方法：用户在真实单台样机上执行 Tftp 拷贝命令和复位流程。
- 验证结果：单台样机流程验证通过。
- 后续待办：继续完善多台样机、不同项目/型号和异常失败场景的流程验证。

## 2026-06-27 - 调整 boot reset 后登录等待时间

- 类型：修改 / 测试 / 文档
- 背景：用户要求检测到 SecureCRT 已发送 reset 后，以及未检测到 reset 重新上电后，主流程都固定等待 120 秒再登录样机系统。
- 完成内容：将 boot reset 分支和重新上电分支的登录前等待时间从 180 秒改为 120 秒，并更新界面日志文案、README 描述和单元测试期望。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\sample_upgrade.py` 和 `python -m unittest discover -s tests -p test_sample_upgrade.py -v`。
- 验证结果：`python -m py_compile .\line_check_assistant\sample_upgrade.py` 通过；`python -m unittest discover -s tests -p test_sample_upgrade.py -v` 通过，5 项测试 OK。
- 后续待办：无。

## 2026-06-27 - 新增开发记录机制

- 类型：文档 / 项目管理
- 背景：用户要求后续每次完成的功能、优化、修改、BUG 修复等都记录下来，方便继续开发和整体管理。
- 完成内容：新增统一开发记录文件，约定每次变更后的记录格式和同步规则。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`AGENTS.md`
- 验证方法：检查文档结构和链接入口。
- 验证结果：已建立可持续追加的开发记录入口。
- 后续待办：后续每次任务完成后，按模板在本文件顶部追加记录。
## 2026-07-11 - 修复 Boot 首轮提示符导致账号密码错位

- 类型：BUG 修复 / 串口时序 / 测试 / 文档
- 背景：真实升级日志显示，程控电源上电后的首轮 `UserName:` / `Password:` 过渡输出可能被当作有效登录提示，导致账号和密码在第一阶段提前写入，后续重试才成功。
- 完成内容：程控电源流程改为在电源动作返回并等待 1 秒后才放行 boot 登录线程；用户名提示符命中后增加仅接收串口的 1 秒稳定窗口，若用户名提交前已经收到 `Password:` / `Passvord:` 则丢弃整轮，不发送任何凭据；用户名回车后仍使用新游标等待本轮密码提示符。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：`python -m unittest discover -s tests -p test_serial_upgrade_service.py -v`、`python -m unittest discover -s tests -v`；真实设备需复测 `Tftp指令` 的首次上电进入 boot。
- 验证结果：串口升级专项 13 项通过；完整 `python -m unittest discover -s tests -v` 共 125 项通过。新增回归覆盖“首轮 UserName/Password 同时出现时不发送账号密码”；后续真实设备首次上电进入 boot 验证已通过。

## 2026-07-11 - Boot 首轮登录错位真实样机验证通过

- 类型：真实设备验收 / 项目状态
- 背景：修复上电初期 `UserName:` / `Password:` 过渡输出造成账号、密码错位后，需要确认实际样机首轮进入 boot 的登录行为。
- 完成内容：用户已确认该问题解决，首次 Boot 登录不再出现账号或密码错位。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`
- 验证方法：用户在真实样机使用 `Tftp指令` 的首次上电进入 boot 流程验证。
- 验证结果：通过。
## 2026-07-11 - 全包升级断电重启不再关闭全部程控电源通道

- 类型：流程优化 / 程控电源 / 测试 / 文档
- 背景：全包升级当前通道断电再上电时，日志仍先发送 `55 00 AD 00 00 AD` 全部断电帧；用户要求去除该操作。
- 完成内容：`power_on_selected_channels()` 保留当前升级通道的关闭帧、断电间隔和开启帧，移除“关闭全部程控电源通道”帧；主界面自动上/下电和 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 的业务逻辑未改动。
- 修改文件：`Cheating_machine_execution_tool/src/core/power_supply.py`、`Cheating_machine_execution_tool/src/services/power_on_service.py`、`Cheating_machine_execution_tool/tests/test_power_supply.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行程控电源专项测试和完整单元测试；真实样机观察全包升级首次/重新上电日志。
- 验证结果：程控电源专项 8 项通过；完整 `python -m unittest discover -s tests -v` 共 125 项通过。真实样机需确认日志不再出现 `关闭全部程控电源通道：55 00 AD 00 00 AD`。

## 2026-07-11 - 全包升级 Tftp指令 多台样机串行验收通过

- 类型：真实设备验收 / 项目状态
- 背景：主程序的 `全包升级 + Tftp指令` 采用程控电源按当前通道逐台执行，需要确认多台样机的串行升级完整流程。
- 完成内容：用户确认多台样机串行升级验收通过；`Tftp指令` 流程标记为真实样机已验收。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`
- 验证方法：用户在真实设备执行“样机升级 → 全包升级 → Tftp指令”的多台样机串行升级。
- 验证结果：通过。
## 2026-07-11 - 全包升级 Tftp指令 支持两台受控并行

- 类型：功能 / 并行编排 / 程控电源 / 测试 / 文档
- 背景：用户要求在已验收的多台样机串行 `Tftp指令` 流程基础上，提供最多两台样机并行升级；主程序已不再使用旧工具 GUI，因此升级过程不应逐台改写 `network_card_ip.ini`。
- 完成内容：样机升级窗口新增持久化的“串行 / 并行（最多 2 台）”选择，默认串行且仅对 `Tftp指令` 生效；并行模式完成即补位，单台失败不取消其它样机。新增共享电源协调器，仅串行化同一 COM 口的关闭/开启帧，将每台启动等待移到锁外；每台 TFTP 服务严格绑定各自 VLAN IP，不允许回退到 `0.0.0.0`。串行和并行全包升级均不再临时改写 `network_card_ip.ini`；`Tftp Put`、自动上/下电和 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 保持原逻辑。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`line_check_assistant/sample_upgrade_settings_store.py`、`src/core/tftp_transport.py`、`src/services/serial_upgrade_service.py`、`src/services/__init__.py`、相关单元测试、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行升级设置、TFTP、串行升级服务、主界面专项测试及完整单元测试；真实设备以两台独立 VLAN、相同 Boot IP 的样机验证。
- 验证结果：编译检查通过；完整 `python -m unittest discover -s tests -v` 共 130 项通过。新增严格双 IP 同端口 TFTP 监听、两台并行上限/失败继续、电源 COM 互斥与不改写升级配置的回归覆盖；真实两台并行升级待验收。
## 2026-07-11 - 并行 TFTP 严格绑定前等待 VLAN IP 就绪

- 类型：BUG 修复 / 网络时序 / 测试 / 文档
- 背景：两台并行 `Tftp指令` 日志显示，`netsh` 已成功设置 VLAN139/VLAN138 的静态 IP，但约 1 秒后严格 TFTP 预检仍报告 IP 不可绑定；这是 Windows 刚配置网卡地址时地址注册尚未完成造成的时序问题。
- 完成内容：设置静态 IP 后改为每 0.5 秒验证一次可绑定性，最长等待 15 秒；就绪后再启动严格绑定的 TFTP 服务。超时仅报告该 VLAN 的网卡 IP/重复 IP/驱动问题，仍不回退到 `0.0.0.0`，避免多 VLAN 同 Boot IP 的回包错路由。
- 修改文件：`Cheating_machine_execution_tool/src/core/tftp_transport.py`、`src/core/__init__.py`、`src/services/serial_upgrade_service.py`、相关单元测试、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 TFTP、串行升级服务专项测试和完整单元测试；真实设备重新执行两台并行 `Tftp指令`。
- 验证结果：专项 25 项通过；完整 `python -m unittest discover -s tests -v` 共 133 项通过。真实设备待复测。
## 2026-07-11 - 并行 TFTP 数据 socket 固定绑定 VLAN IP

- 类型：BUG 修复 / 多网卡路由 / 测试 / 文档
- 背景：两台样机的 UDP 69 服务都已成功监听，但只有一台开始传输。定位到 TFTPy 在收到 RRQ 后会创建未绑定本地 IP 的数据传输 socket；当多张 VLAN 网卡面对相同 Boot IP `192.168.1.1` 时，Windows 会把数据回包路由到其中一张网卡。
- 完成内容：在主程序 TFTP 包装层替换 TFTPy 的会话上下文工厂。每个监听线程创建传输数据 socket 时，强制绑定该服务的 VLAN IP 和随机本地端口；不修改虚拟环境中的第三方源码。这样监听帧和后续固件数据帧均从同一 VLAN IP 返回样机。
- 修改文件：`Cheating_machine_execution_tool/src/core/tftp_transport.py`、`tests/test_tftp_transport.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：模拟 RRQ，断言 TFTPy 新建的数据 socket 绑定监听 VLAN IP；运行完整单元测试；真实设备执行两台并行 `Tftp指令`。
- 验证结果：TFTP 专项 9 项通过；完整 `python -m unittest discover -s tests -v` 共 134 项通过。真实两台并行传输待复测。
## 2026-07-12 - 全包升级 Tftp Put 支持两台受控并行

- 类型：功能 / 并行编排 / 程控电源 / 测试 / 文档
- 背景：`Tftp Put` 已完成多台串行真实样机验收；需要在不触碰 `Tftp指令` 调度和传输逻辑的前提下，提供两台受控并行升级能力。
- 完成内容：新增仅接受 `Tftp Put` 请求的并行服务入口，固定最多两台、完成即补位、单台失败不中止其它样机并按输入顺序汇总。每个 worker 仍使用 TFTPy Client 将固件推送至隔离 VLAN 内的 `192.168.1.1`，共享程控电源 COM 的开关帧由现有协调器串行化。升级窗口现对 `Tftp Put` 显示“串行 / 并行（最多 2 台）”，新增独立 UI worker、状态汇总、VLAN 日志和自动串口终端收尾；`Tftp指令` 的 worker、严格服务端绑定和传输流程未改动。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/src/services/__init__.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行编译检查、串行升级服务专项测试、主界面专项测试和完整单元测试；真实两台独立 VLAN / COM 样机执行并行 `Tftp Put`。
- 验证结果：`python -m py_compile line_check_assistant/app.py src/services/serial_upgrade_service.py src/services/__init__.py` 通过；串行升级服务专项 24 项、主界面专项 60 项通过；完整 `python -m unittest discover -s tests -v` 共 154 项通过。
- 后续待办：真实两台独立 VLAN / COM 样机验收并行 `Tftp Put`，确认两路上传可同时推进且程控电源开关帧不交叠。

## 2026-07-12 - 全包升级 Tftp指令 / Tftp Put 两台并行真实样机验收通过

- 类型：真实样机验收 / 状态更新
- 背景：`Tftp指令` 两台并行和 `Tftp Put` 两台并行此前都是“代码完成，待真实两台验收”，需要把状态收口到已验收。
- 完成内容：用户已用两台不同 VLAN/COM 的真实样机验收 `Tftp指令` 并行和 `Tftp Put` 并行，结果通过。同步将 `PROJECT_STATUS.md` 中两项标记为“已真实两台验收”，移除“待两台真实验收”相关待办，删除“`Tftp Put` 并行仍是代码和单测验证”的限制项。
- 修改文件：`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：真实两台不同 VLAN/COM 样机分别执行 `Tftp指令` 并行和 `Tftp Put` 并行升级。
- 验证结果：通过。
- 后续待办：继续按现有约束观察新型号或异常现场日志，再扩展超时、掉线、登录失败与型号差异处理；不要预先改变已验收时序。

## 2026-07-12 - 串口乱码盲发密码补救登录真实样机验收通过

- 类型：真实样机验收 / 状态更新
- 背景：先前在 `_login_boot` 与 `login_tftp_put_boot_after_username` 增加的 salvage 分支（回显含 UTF-8 替换符 `�` → 盲发密码 → 等 shell 提示符）已通过单元测试（160 项），需要现场复现 UART 损坏场景验证命中率。
- 完成内容：用户已在真实样机上验证该 salvage 方案，结果通过。同步在 `PROJECT_STATUS.md` 的"已完成"中追加该能力的真实样机验收条目。
- 修改文件：`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：真实样机复现 UART 输出损坏场景,触发用户名回显和 `Password:` 提示符均为乱码,确认 salvage 命中并进入 shell。
- 验证结果：通过。
- 后续待办：继续按现有约束观察新型号或异常现场日志,再扩展其他场景;不要预先改变已验收时序。

## 2026-07-12 - 串口乱码时盲发密码补救登录

- 类型：BUG 修复 / 异常现场补强 / 测试 / 文档
- 背景：现场日志显示一台样机的 UART 输出损坏：`UserName:` 被切成 `U` + `serName:`、`RX C�H�`、`RX C!���ݽɑ�` 等乱码；`Password:` 提示符也是乱码。`_login_boot` 与 `login_tftp_put_boot_after_username` 都在等待完整 `Password:` 提示符，超时后只能重试或放弃，但 UART 输入正常时样机实际已接受账号。
- 完成内容：新增 `PySerialSession.peek_since(cursor)` 读取从游标开始的解码文本（不消费历史）；新增模块级常量 `GARBLED_REPLACEMENT_MARKER` 与辅助函数 `_looks_like_garbled_response()` 检测 UTF-8 替换符 `�`；新增 `SerialUpgradeController._try_login_after_garbled_username()`，在 `_login_boot`（Tftp指令）和 `login_tftp_put_boot_after_username`（Tftp Put）的 `Password:` 超时分支中：当回显含 `�` 时盲发一次密码，等待 shell 提示符（`#` / `>` / `ecnt>` / `u-boot>`）作为登录成功；salvage 失败不影响原重试或失败路径。完整 `UserName:` / `Password:` 提示符到达时仍走原路径，不改变已验收时序。
- 修改文件：`Cheating_machine_execution_tool/src/core/serial_transport.py`、`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_transport.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile src/core/serial_transport.py src/services/serial_upgrade_service.py`；运行 `tests/test_serial_upgrade_service.py`、`tests/test_serial_transport.py` 及完整单元测试。
- 验证结果：编译通过；新增 6 项用例覆盖 `peek_since` 基础行为、Tftp指令 salvage 成功 / 失败重试 / 干净超时无 salvage、Tftp Put salvage 成功 / 干净超时无 salvage；完整 `python -m unittest discover -s tests -v` 共 160 项通过。后续现场用已知会让响应乱码的串口线复测,确认命中并进入 shell,真实样机验收通过。
- 后续待办：继续按现有约束观察新型号或异常现场日志,再扩展其他场景;不要预先改变已验收时序。

## 2026-07-12 - 精简项目交接状态文档

- 类型：文档 / 交接
- 完成内容：重写 `PROJECT_STATUS.md`，仅保留项目目标与实现进度、关键文件、已完成与待验收项、技术限制，以及运行/测试/继续开发命令；同步当前全量测试基线为 154 项。
- 修改文件：`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证结果：已核对源码入口、升级服务、串口/TFTP 核心文件与当前测试基线；未改动业务代码。
## 2026-08-31 - 调整全包升级上电后 boot 回车时序

- 类型：优化 / 串口时序 / 测试 / 文档
- 背景：现场日志显示 `Tftp指令` 在上电帧下发后仍补足 10 秒启动等待，`Tftp Put` 也在电源动作返回后叠加了第二个 1 秒等待。项目负责人要求两条全包升级链路统一为上电帧后稳定 1 秒即开始串口循环回车进入 boot。
- 完成内容：① `Tftp指令` 不再传入 10 秒补足启动等待，电源层完成开启帧后的升级专用 1 秒稳定后立即放行 boot 登录线程；② `Tftp Put` 同样移除电源返回后的额外 1 秒，立即循环回车等待 `UserName:`；③ 两条链路新增“上电稳定 1 秒完成，开始串口循环回车进入 boot”主执行日志，保留断电 1 秒、上电 1 秒、账号/密码登录、传输和收尾语义；④ 补强两条链路的回归断言，并同步操作员说明、项目状态和验收边界。
- 修改文件：
  - `Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`
  - `Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`
  - `Cheating_machine_execution_tool/line_check_assistant_README.md`
  - `ACCEPTANCE_BASELINE.md`
  - `PROJECT_STATUS.md`
  - `DEVELOPMENT_LOG.md`
- 验证方法：在 `Cheating_machine_execution_tool` 执行 `python -m unittest discover -s tests -p test_serial_upgrade_service.py -v`、`python scripts/verify_baseline.py` 和 `git diff --check`。
- 验证结果：串口升级专项 `Ran 38 tests ... OK`；完整基线以本机权限执行，59 个源码文件编译、741 项单元测试、172 项强制基线测试和协议不变量均通过，输出 `ALL CHECKS PASSED`。未构建或运行 EXE，未连接真实样机。
- 后续待办：分别在 Windows 源码版和真实样机验证 `Tftp指令`、`Tftp Put` 的“上电帧后稳定 1 秒 → 首个回车 → UserName → boot 登录 → 传输”日志和稳定性；在项目负责人提供现场结果前，不升级本项验收状态。
