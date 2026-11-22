# 会话 2 逐项验收与现场记录

以 [会话 2 计划](../SESSION_2_INTEGRATION_ACCEPTANCE.md) 的共同起点建立集成副本。表中“模拟”指使用临时项目、模拟设备或隔离的 Windows 原生窗口。操作员可从 [批次报告](REPORT.md) 进入同源验证记录。

| 阶段和判据 | 入口、业务依据和判读 | 证据 |
| --- | --- | --- |
| 0 · 审计和回退 | 共同起点与副本逐文件比对。Tk 源码入口为 `run_line_check_assistant.py`，Qt 源码从 `run_dutpilot_qt.py --workspace` 进入。切换前在原入口确认任务停止、资源释放，使用备份副本打开旧项目。 | [复制核对](copy-check.json) · [原恢复演练](../restore_result.json) |
| 1 · Windows 主窗口 | 三档显式缩放检查布局和线程守卫。现场另在实体显示器验证系统 DPI、图标、字号和操作便利性。 | [组合三档验证](native-release/results.json) · [布局范围](../PHASE1_2_REPORT.md) |
| 2 · 旧项目管理 | 从“项目 → 打开项目”分别进入两份迁移前副本，打开模块、关闭编辑器、待保存动作恢复可用后保存、关闭并重开。逐份比对草稿，旧运行记录保留两个成功及两个未知。 | [原生窗口复验](archived-window.txt) · [副本、版本与运行配置](old-projects.json) |
| 3 · 自动开关机 | 项目详情的开始、确认、停止经 `aging.start` 使用原 `legacy_power_test` Windows 子进程。逐通道核对断、通、断、通四帧、配置等待和最终结果。模拟写异常和短写须失败，停止 A 时 B 独立完成。原进程存活期间保留未知保护。 | [旧入口逐帧](combined-16-direct.json) · [Qt 逐帧](combined-16-qt.json) · [短写失败](combined-short-write.json) · [双项目停止](combined-parallel.json) · [存活保护](owner-exit.json) |
| 4 · 持续开机全业务老化 | 生产详情的开始测试映射到“自动开关机挂测”。演示页面中的持续开机卡片标为“待接入”。独立周期执行器待接入，持续探测、异常及恢复、多 DUT 和 7 天有效运行均待验。 | [负责人决定](../../../../.claude/plans/pyside6-migration.md) · [阶段总表](../MIGRATION_PROGRESS.md) |
| 5 · 串口日志 | 项目详情 → 串口日志，输出区右键读取快照或清屏。QtSerialTerminal 使用原 SerialSessionManager。核对默认映射、一次确认、取消保留输入、关闭失败可重试及落盘。 | [终端](../SERIAL_REPORT.md) · [收尾与失败](../serial_close_worker/REPORT.md) |
| 5 · DUT 配置 | 项目详情 → DUT 配置，经 QtDutConfiguration 及各功能适配器调用原项目批量服务。专项覆盖保存的登录字段、选中目标、过期确认拒绝、停止后资源及逐目标失败日志。 | [Telnet](../DUT_TELNET_REPORT.md) · [WAN](../WAN_REPORT.md) · [WiFi](../WIFI_REPORT.md) · [语音与 TR069](../VOICE_TR069_REPORT.md) |
| 5 · 样机升级 | 样机升级 → 配置、预检、确认。QtFirmwareUpgrade 将四种模式交原升级服务，核对固件、项目版本、勾选通道、取消和安全停止。模拟串口观察共享同一会话。 | [升级](../FIRMWARE_REPORT.md) · [手动重启确认](../FIRMWARE_MANUAL_REPORT.md) · [串口观察](../FIRMWARE_OBSERVATION_REPORT.md) |
| 5 · 写样机参数 | 项目详情 → 写样机参数，QtParameterWriter 复用原参数表、预检及写参服务。核对登录草稿、已选行、取消、工厂模式收尾及重开状态。 | [写参](../PARAMETER_WRITER_REPORT.md) · [模拟批次观察](../PARAMETER_OBSERVATION_REPORT.md) |
| 5 · ONU 注册 | 从发现结果选择目标并预览。注册、已注册项管理及保存分别复用原服务。型号/PON、每台 ID、修改后旧确认失效、部分失败与未知结果均有模拟覆盖。 | [注册](../ONU_REGISTRATION_REPORT.md) · [管理](../ONU_MANAGEMENT_REPORT.md) · [保存](../ONU_SAVE_REPORT.md) |
| 5 · 测试项与通道 | 详情 → 测试配置和通道配置，经 QtConfigurationService、QtChannelConfiguration 调原存储。覆盖六标签默认值、原字段字节、保存重开、草稿恢复、外部版本冲突及回滚。 | [六标签专项](../CONFIGURATION_REPORT.md) · [通道](../CHANNELS_REPORT.md) · [草稿恢复](../EDITOR_RECOVERY_QT_REPORT.md) |
| 5 · 全局设置及工具 | 从工具栏、设置、项目菜单和通道右键进入。核对原更新服务的下载取消、设备资源枚举与租约、远程项目范围、单次电源目标及全流程三项默认不选。平台和设备均使用模拟回执。 | [设置和更新](../APP_UPDATE_QT_REPORT.md) · [设备管理](../DEVICE_INVENTORY_QT_REPORT.md) · [单次电源](../SINGLE_POWER_QT_REPORT.md) · [全流程](../PIPELINE_QT_REPORT.md) · [实例](../instance_startup/REPORT.md) |
| 6 · 项目关闭和跨项目占用 | 工作区关闭等待读取线程释放 SQLite 连接。项目间禁止借用另一项目的终止权限；目标配置暂时不可读时保留错误反馈。 | [历史查询与关闭](../JOB_HISTORY_RESPONSIVENESS_QT_REPORT.md) · [双项目与独立停止](../parallel_power/REPORT.md) · [配置刷新](../local_serial_chat/REPORT.md) |
| 7 · 日志、过滤和轮转 | 从“归档日志”读取旧主日志与资源监测记录，24 个文件共 980 行；另有 72 行旧工作区日志。任务历史覆盖通道过滤、翻页和未知状态。刷新后文件为空时，两个翻页按钮都停用。 | [旧数据回放](old-projects.json) · [修正前](before-refresh.txt) · [修正后](after-refresh.txt) · [历史通道过滤](../CHANNEL_RETRY_HISTORY_QT_REPORT.md) |
| 8 · Windows 交付 | 锁定 Qt 环境完成标准构建。基线 3,267 项，指定 266 项全部命中。EXE/PYZ 对照 333 个项目模块，ZIP、哈希、声明和手册核对通过。干净 Windows 解压启动和打开旧项目待现场验收。 | [成品路径和 SHA256](REPORT.md) · [基线与打包](build.txt) · [验包](packaged-sources.json) · [交付目录](delivery.json) |
| 9 · 完整回归与现场 | 自动化、原生缩放、模拟设备、物理设备和长期运行分别记录。每台 DUT 500 次和 24/72 小时持续采样待负责人提供记录。 | [现场采样入口](../long_run_acceptance/README.md) |

## 现场交接

| 项目 | 负责人回填 | 判据及证据 |
| --- | --- | --- |
| 干净 Windows 目标机 | 机器标识、Windows 版本、DPI、包名与 ZIP SHA256、操作员及起止时间 | 校验完整 ZIP，解压启动，打开旧项目副本、保存重开；附启动截图及错误/日志路径。 |
| DUT、OLT、网卡、电源和串口 | 项目、运行 ID、固件与配置版本，逐台列出 DUT ↔ 通道、VLAN/网卡、COM、电源口 | 逐一核对目标及确认页。以真实设备响应、帧和结果文件确认成功、失败或停止。 |
| 单通道、多通道及 16 通道 | 设备数量、每台目标与实际轮次、开始和结束时间、异常时间段 | 每台 500 次逐通道核对。记录中断、停止请求、实际退出、租约释放与复核人。 |
| 24/72 小时稳定性 | 操作员、起止时间、采样与主日志/串口日志/结果目录 | 保存 CPU、内存、线程、事件积压、GUI 响应和采样缺口，逐项记录预期与实际。 |
| 持续开机业务监测 | 独立执行器接入后的检测项、周期、故障及恢复条件、多 DUT 映射 | 核对业务回执、7 天有效运行及缺失区间；本批状态为待接入。 |
| 实体平台 | 项目范围、账号角色、确认人、平台回执时间和日志路径 | 核对实际授权项目选择、拒绝和撤销，记录异常、复核人及现场结论。 |
