# Phase 5 增量：Windows Qt 实例配对

2026-11-21。源码和本次 Windows 候选包均从「多实例接入状态 → 网关操作 → 实例配对…」进入。[此前候选及十阶段审计](../current_candidate_review/REPORT.md)

## Windows 候选包

使用标准脚本 `build_line_check_assistant.ps1 -Gui Qt` 构建，退出码为 0。完整 ZIP 为 55,371,503 字节，SHA256 为 `c4b1e3ec868d1f6f3f6e20b43a1c31e0f419cc31d642cf87961c2fb71c7c392f`。在目标 Windows 电脑完整解压后，从 `DUTPilot_portable\DUTPilot.exe` 启动。[便携 ZIP](../../../dist/qt-20261121-094840-01ea3a1e/DUTPilot_portable.zip) · [SHA256](../../../dist/qt-20261121-094840-01ea3a1e/DUTPilot_portable.zip.sha256.txt)

锁定环境为 CPython 3.9.10 x64。完整基线编译了 379 个文件，清单覆盖 369 份源码，3,232 项回归及其中全部 239 项指定用例通过。EXE 静态识别为 Windows x64 GUI 1.3.0，便携目录和 ZIP 的 247 个文件逐一匹配。独立目标机启动仍待现场。[构建与基线输出](candidate-build.txt) · [标准验包记录](../../../dist/qt-20261121-094840-01ea3a1e/PACKAGING_REPORT.json)

另读取 EXE 内的启动脚本和 PYZ。按构建输入路径找到 325 个项目模块，包括配对窗口、Qt 适配器及旧开关机业务模块，逐个和当前源码编译结果比对通过。手册、ZIP CRC 和外部校验文件也已核验。相同比对程序对前一候选包报告旧适配器存在差异。本机全程未运行成品 EXE。[输入及比对结果](packaged-sources.json) · [成品比对脚本](check_candidate.py)

## 自动开关机 16 通道模拟回归

成品构建后，在 `tests/test_qt_execution_adapter.py` 增加 16 通道回归。使用临时项目及模拟网卡，沿用 Qt 确认、原能力、任务、编排器和旧业务父进程，只替换创建真实硬件子进程的上下文。逐字段对照原服务从已保存配置生成的请求，核对任务实际读取独立运行快照。模拟子进程按逆序报告 15 个正常通道和第 16 通道失败，再投递上一批次第 16 通道的成功事件。

Qt 保留失败批次的任务 ID 和终态，第 1 至 15 通道各显示模拟完成 100 轮，第 16 通道保留失败及 0 个已完成轮次，任务结束后资源租约释放。该例和同模块全部 43 项通过。此用例在上述构建基线之后独立运行，真实继电器、电源帧、设备时序和逐台 500 轮仍需现场核对。[完整执行适配器测试输出](sixteen-channels.txt)

## 新旧流程核对

| 原流程约束 | Qt 实现与验证 |
|---|---|
| 只有网关已保存允许的成员范围才能签发 | 窗口调用原管理服务签发。测试在无授权范围时检查拒绝，在配置范围后签发成功。 |
| 配对码五分钟有效，仅能成功兑换一次 | 服务使用原网关存储。界面到期后清空显示并禁止复制。用已兑换的码在第二槽位配对，原网关存储拒绝。 |
| 在指定槽位向指定网关配对 | 默认读取原启动配置中的槽位。确认框显示槽位、实例 ID、名称和网关。提交时复读槽位身份及配对状态，变更后拒绝。 |
| 配对与实际接入分别由操作员决定 | 兑换后的实例初始禁用，通道和业务能力为空。测试核对槽位持久状态、原启动设置以及状态与执行日志中的凭据保护。 |

## 验证

在主源码目录通过 `scripts/run_tests.py` 运行新增适配器专项、网关异步隔离专项与原实例管理测试模块，20 项通过。使用临时配置、原管理及账本服务、模拟传输或本机回环。未连接现场网关、远端平台或设备。[服务验证原文](services.txt)

Windows 私有桌面的新增原生用例单独运行 1 项通过，覆盖槽位选择、配对确认取消、确认提交、配对码到期及窗口关闭重开后的迟到回执。阶段原生全套由 `scripts/verify_qt_migration.py` 依次在 100%、125%、150% 下运行。

配对窗口使用模拟实例。保留三档窗口截图供人工比对。[100%](native/scale-1/instance-pairing.png) · [125%](native/scale-1.25/instance-pairing.png) · [150%](native/scale-1.5/instance-pairing.png)

全套原生回归在三档各执行 90 项，合计 270 次全部通过。每档均命中全部指定用例，Windows 私有桌面各记录 1,829 个受管 Qt 窗口，隔离违规为零。[三档测试及隔离结果](native/results.json)

三档共生成 381 张截图。核对报告引用、目录和 Git 跟踪状态后，378 张过程截图已移入回收站，保留上述三张配对窗口截图及全部测试文本与 JSON。

配对开发时编译九个 Python 文件通过，能力清单通过，GUI 窗口覆盖检查核对了 83 个构造位置。随后标准构建执行了上文的完整源码基线。

本次重新计算了迁移前已登记的 97 份受保护源码的 SHA256，全部与原记录匹配，涵盖自动开关机执行器、底层通信和资源管理。另核对前次便携包，SHA256 与候选报告一致。[受保护文件与 SHA256 清单](../current_candidate_review/source-check.json)

## 修改范围

构建及开关机复验均从主源码目录运行。独立 Qt 打包环境提供读取 PYZ 所需的同版本解释器及 PyInstaller。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1 -Gui Qt
python scripts/run_tests.py test_qt_execution_adapter -v
& "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe" -I -X utf8 validation/pyside6_migration_20261118/instance_pairing/check_candidate.py dist/qt-20261121-094840-01ea3a1e
```

- `src/services/qt_workspace_adapter.py` 通过原有网关工作线程串行调用原签发、槽位读取和配对服务。
- `src/ui/qt/instance_pairing_dialog.py`、`instance_status_dialog.py` 和 `workspace_controller.py` 提供本机人工操作、确认和回执路由。
- `tests/test_qt_workspace_adapter.py` 和 `tests/qt_workbench_probe.py` 覆盖原服务约束、窗口状态与异常回执。
- `scripts/verify_baseline.py`、`verify_qt_migration.py`、`verify_capability_coverage.py`、`scripts/capability_gui_actions.json` 和根目录 `CAPABILITY_COVERAGE.md` 登记编译、原生测试与人工控制面。
- 操作方式已写入 `line_check_assistant_README.md`。项目状态、验收基线、开发记录与[总进度](../MIGRATION_PROGRESS.md)同步保存此阶段结论。

## 剩余验收

跨机配对、现场身份核验、独立 Windows 目标机和平台实际接入仍待验收。全计划还缺持续开机全业务老化的原独立执行器、部分实时诊断和串口联动，以及设备和长期稳定性记录。原开关机编排器、检测条件及结果判定均未在此次配对工作中修改。

对照附件第七章，Phase 4 要求 DUT 持续开机，并由原业务层提供检测周期、结果、异常恢复及停止收尾。源码中 `aging.start` 注册的任务是 `legacy_power_test`。另有演示项目“全业务老化”，状态标记为“待接入”。现有材料无法验证持续业务检测。[原能力注册](../../../src/services/capability_device_services.py) · [演示数据](../../../src/ui/qt/demo_data.py) · [负责人记录](../../../../.claude/plans/pyside6-migration.md)
