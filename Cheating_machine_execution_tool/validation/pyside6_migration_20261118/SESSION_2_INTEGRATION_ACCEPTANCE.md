# 会话 2 执行计划书｜非 AI 页面、核心挂测与 Windows 总交付

**领取任务后直接执行。** 收到会话 1 成果前，先完成非 AI 页面审计与修复、原挂测回放及现场验收准备。收到交接后，由你负责合并两路成果、在同一份组合源码上验证，并交付 Windows 候选包。会话 1 独立负责 AI 会话与挂测证据适配。

## 开工依据

主仓库为 `F:\Aouxue\Power_OnOff_Assistant`，主源码目录为 `Cheating_machine_execution_tool`。在各自副本使用项目锁定解释器执行测试；用 `scripts/run_tests.py` 作为 unittest 入口。

原计划附件在 `C:\Users\Administrator\.codex\attachments\1583c7fe-9e8d-4ca7-9f25-9a96d4a3ea06\已粘贴的文本.txt`。先读仓库根 `AGENTS.md`、[迁移范围与负责人决定](../../../.claude/plans/pyside6-migration.md)、[十阶段进度](MIGRATION_PROGRESS.md) 和[最近的源码验证记录](local_chat_intent/REPORT.md)。下文源码相对路径和命令均以 `Cheating_machine_execution_tool` 为工作目录。

两个会话从同一份包含自然语言路由修正的独立源码开始。本机参考目录为 `%LOCALAPPDATA%\LineCheckAssistant\qt-source\local-intent-26b1c43f\Cheating_machine_execution_tool`，[697 个构建输入的集合 SHA256](local_chat_intent/source-inventory-release.json) 为 `9e70315bcf225e66bee859cb028ca509c16daa958097acca9bec4c7791e6feb7`。参考目录只读。各自在不同目录建立工作副本，保留仓库根文档、已修改以及未跟踪的必需源码、测试、资源和构建清单，核对复制前后一致。仅检出 Git HEAD 会漏掉尚未提交的迁移代码。主工作区另有同期跨实例业务转发改动，按文件差异保留，候选包沿用已经确认的网关范围。

## 1. 接管验证状态，同时推进页面核对

- 编写本计划时，主仓最近已验包的版本为 `qt-20261121-194426-f1cfb93a`，完整基线运行 3,265 项，264 项指定用例全部命中，三档原生界面各通过 100 项。自然语言路由源码另有 80 项专项通过；截至 20:37，新一轮全套原生验证日志已写入 100% 缩放通过。开工时检查参考目录内 `validation/pyside6_migration_20261118/local_chat_intent/` 的 `native-release/results.json`、`build.txt`、`packaged-sources.json`，并核对实际进程、ZIP 和哈希。已有同源作业正在运行时接续读取其结果。未产生完整回执的阶段保留待验证。
- 按原计划逐项检查串口日志、DUT 配置、样机升级、写样机参数、ONU 注册、测试配置、全局设置与其他工具。使用迁移前真实项目的**副本**。从启动后的窗口、菜单和右键入口追到共享 service，核对默认值、保存重开、目标绑定、确认取消、异常反馈和日志。控件能打开仅能证明入口存在。对已有合格证据直接引用，把开发时间用于实际可复现的差异。
- 你负责非 AI 专属页面与适配层。每批修复一个行为，先留复现记录，再通过同一入口做模拟回归。涉及双方共用文件时，在自己的副本保留独立差异，合并时核对双方调用路径。会话 1 的会话路由及证据实现由其独立交付。

## 2. 核对原业务及现场边界

| 验收项 | 执行方式与判据 |
|---|---|
| 自动开关机 | 复用[逐帧回放](power_command_receipts/REPORT.md)、[双项目并行与独立停止](parallel_power/REPORT.md)、[工作区崩溃后的原进程保护](power_owner_exit/REPORT.md)。核对旧入口与 Qt 的通道、断电/通电帧序、原延时、失败判定、停止回执和锁释放。16 个模拟通道两轮每入口应有 64 帧；异常写入应按原判定失败。Qt 崩溃后原任务可继续，原进程退出前不能人工解除保护。 |
| 全业务老化 | 负责人已确认原工程缺少持续开机的独立周期检测执行器，Phase 4 保留待接入。检查生产界面的真实状态和文档表达；把持续检测、异常恢复、多 DUT 和 7 天运行列入待验清单。现有 `aging.start` 使用开关机执行流程。 |
| 项目、日志与资源 | 用两份原项目副本对比保存、重开、历史结果及未知状态。复验翻页、通道过滤、项目关闭等待、配置暂时不可读和跨项目资源冲突。真实硬件、真实平台发送、24/72 小时长挂和每台 DUT 500 次循环由负责人安排，当前只做非硬件验证。 |
| 现场交接 | 沿用[现场取证入口](long_run_acceptance/README.md)，列明设备及通道映射、固件与配置版本、操作者、开始结束时间、预期结果、异常和日志位置。干净 Windows 目标机解压启动和打开旧项目单列。现场结论须有负责人记录。 |

## 3. 唯一集成与打包顺序

1. 在自己的集成副本接收会话 1 的报告、源码清单、新文件、差异和测试命令，核对共同起点。对共享适配器、测试 ID、编译清单、机器覆盖清单和公共文档逐项合并。核对主工作区同期改动并予以保留，本次网关候选只开放项目控制命令。运行双方的失败样本、修复后专项、旧项目回放和模拟电源联动；出现差异，按原基线修复后重跑。
2. 固定组合源码指纹和工具链版本。GUI 业务绑定发生变化时运行 `python scripts/verify_capability_coverage.py --update`，逐项审查覆盖变化。使用项目锁定的 Qt 环境运行 `python scripts/verify_qt_migration.py --output <本次独立验证目录>`，核对 100%、125%、150% 三档的全部指定用例、真实窗口隔离证据和守卫结果。运行全量原生套件时与会话 1 错开占用同一模拟台架的测试。
3. 在主源码目录运行 `powershell -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1 -Gui Qt`。标准脚本必须实际执行并通过 `scripts/verify_baseline.py` 的全部门禁；新源码或新必跑 ID 必须进入清单。检查 EXE/PYZ、便携目录、ZIP、SHA256 及第三方声明，并复用 `validation/pyside6_migration_20261118/instance_pairing/check_candidate.py`（沿用 `--reviewed-changes validation/pyside6_migration_20261118/serial_close_worker/reviewed-sources.json` 中已核准的修正） 比对成品与本轮源码。仅在同一份输入上全部通过后发布本地交付路径。构建机禁止运行打包后的 EXE。
4. 同步 `MIGRATION_PROGRESS.md`、根目录 `PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md` 以及操作员手册。报告写明原计划各阶段判据、实际修改、原业务复用、测试命令及统计、截图、已知差异、Tk 回退入口和未验项。阶段报告完成后按项目规则清理过程 PNG 并记录数量。

**交付物**为 `validation/pyside6_migration_20261118/session2_integration/REPORT.md`、逐项验收表与证据索引、最终 EXE 路径、便携 ZIP 和同批 SHA256。最终交付到本机。公开发布和真实现场操作另按负责人指令执行。
