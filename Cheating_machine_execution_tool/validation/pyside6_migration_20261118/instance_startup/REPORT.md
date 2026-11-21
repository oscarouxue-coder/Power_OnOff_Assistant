# 多实例启动配置与开关机停止回执

## 多实例启动配置

旧 Tk 通过 `RemoteInstanceManagement.slot` 读取实例，按本地已注册能力和平台来源筛选可用业务，确认后用 `save_instance` 写入下次启动模式及加密的待生效范围。本阶段将同一流程接入 Qt「多实例接入状态 → 网关操作 → 下次启动配置…」。

1. 打开项目后，窗口使用该项目实际能力注册表。读取已配对槽位时回填实例 ID、成员范围、地址、VPN、通道与业务能力。保存统一接入前显示将授权的范围及将移除的能力。
2. 后台再次核对启动设置、槽位绑定和现有范围。保存后仍由原运行时在下次初始化时读取待生效配置。正在运行的实例保留其现有范围。直接接入可在原槽位被占用时保存；损坏的旧启动文件在明确保存前保留原样。
3. 故障注入发现，原服务先写入授权范围，随后写启动模式失败时，新范围会留在磁盘。现于槽位锁内完成两次写入；第二次写入报错时，恢复之前的加密范围文件，或移除本次新建的范围。在已有待生效范围与首次创建两种情况下均已验证。[修复前复现](initial-save-failure.txt)
4. 本机设置与当前运行状态分开显示。Qt 读到指定槽位但没有实例客户端时，显示「统一接入（尚未启动）」。Qt 开机后建立实例连接、转发项目消息仍待接入。验证未连接真实平台或 DUT。

22 项原多实例管理和 Qt 工作区专项通过，包括持久设置、失效复核、权限选择、损坏配置恢复、占用槽位及项目关闭等待。Windows 窗口专项覆盖取消、确认、回填及重新打开。项目适配器与原运行时使用临时目录和模拟连接验证了待生效文件的提升，未启动网络客户端。[服务测试](services.txt) · [窗口专项](focused.txt)

## 开关机任务停止

两个项目分别使用独立的模拟电源 COM、通道 COM、网卡标识和项目运行目录。通过两个项目执行适配器提交后，原任务库、资源协调器、编排器、配置快照、取消信号和释放路径均参与执行。本例在旧业务运行函数边界返回模拟回执。

首次运行重现，原业务已返回“用户已停止执行开关机测试”，但能力任务仍记成失败。原因是原编排器用同一异常向调用端传递负测试结论与已确认的停止。现由能力任务层核对停止请求及原业务的明确停止回执，记录任务已停止，保留原文和原有负判定。遇到真实业务失败或超时强制终止子进程时仍保留失败。原电源指令、时序、版本预检、子进程生命周期及通道判定代码保持。[修复前回执](initial-stop-result.txt) · [两项目隔离与失败竞争专项](dual-project.txt)

停止项目 A 时，A 的租约在原执行器退出后释放；B 保有自己的租约并正常结束。这里验证了项目执行服务，工作台现有的设备任务并行限制仍保留。真实多项目设备并发、断电时序和长期稳定性待现场验收。持续开机全业务老化仍待独立执行源。

## 涉及文件

- `src/ui/qt/instance_startup_dialog.py`、`instance_status_dialog.py` 提供入口、复核、本机确认及当前状态显示，沿用原工作台表单、列表和菜单。原 Tk 的槽位、成员、通道、能力均在新窗口可见。
- `src/services/qt_instance_startup.py`、`qt_workspace_adapter.py`、`qt_execution_adapter.py` 绑定实际注册表、后台操作和项目生命周期。`remote_instance_management.py` 保留 Tk 调用接口并补全写失败恢复。`capability_device_services.py` 处理原停止回执。
- `tests/test_remote_instance_management.py`、`test_qt_workspace_adapter.py`、`test_qt_execution_adapter.py`、`qt_workbench_probe.py`、`scripts/verify_qt_migration.py`、`verify_baseline.py` 增加回归和必跑清单。
- 能力覆盖生成器、GUI 动作快照、能力覆盖说明、操作员手册、项目状态、验收基线、开发记录和逐阶段进度同步更新。Tk 启动入口与回退备份保留。

## 原生窗口与构建检查

窗口专项通过 Qt 工作台真实的开始与停止入口运行原开关机编排器及子进程管理代码。测试仅用模拟进程代替实际设备子进程。收到停止信号但尚未返回业务回执时，原租约仍被占用。返回明确停止回执后，窗口显示“已停止”，任务记录留存原有负判定。该测试不测量电源时序。[窗口专项复验](final-focused.txt)

首次原生回归在 100% 缩放的模拟 WiFi 查询用例发生超时，隔离守卫记录了未接管的警告弹窗。125% 和 150% 各通过当时的 93 项。后续将该用例中的警告接入测试断言，使错误正文直接进入失败记录。WiFi 查询、实例设置、开关机停止三项随后通过。[首次运行](native/results.json) · [三项复验](final-focused.txt)

静态扫描前一候选包时，发现 PDF 图像插件和虚拟键盘插件分别依赖当前锁定 Qt Essentials 环境未提供的 Qt6Pdf、Qt6VirtualKeyboard。Qt 构建配置新增条件筛选，仅在对应实现缺失时移除该插件。标准验包脚本逐个检查 PySide6 与 shiboken6 的 DLL/PYD 直接及延迟导入的 Qt6 库。对前一包做内存中反例检查时，移去两个插件后其余 39 个文件通过，再模拟移去 Qt6Widgets 后验包明确报告两个引用方。全程未启动成品 EXE。[反例记录](previous-qt-imports.txt)

涉及构建文件为 `line_check_assistant/packaging_specs/DUTPilotQt.spec` 和 `scripts/verify_slim_package.py`。构建入口、锁定依赖和 Tk 构建配置沿用原设置。

首次构建的完整基线执行 3,240 项，Telnet 回环构造用例失败，构建脚本在冻结 EXE 前退出。原模拟服务接入后立即发送七字节的 `login: `，后台读取线程可在初始游标断言前已经读完。现以事件让 `tests/test_telnet_transport.py` 的模拟服务在初始游标断言后才发出提示，并复核完整提示到达时游标为 7。测试服务器使用系统直接分配的回环端口。生产 Telnet 实现沿用原代码。[首次构建失败记录](first-build-telnet.txt) · [Telnet 专项复验](telnet-loopback.txt)

## Windows 源码窗口对照

最终 Windows 原生专项退出码为 0。100%、125%、150% 三档各通过 94 项，合计 282 次。每档隔离守卫记录 1,848 个受管理窗口，必跑用例未缺失，违规清单为空。隔离运行覆盖源码窗口，实体显示器的系统 DPI 切换和异机 EXE 启动待验。[三档机器结果](final-native/results.json) · [运行输出](final-native-console.txt)

实例设置沿用工作台的表单和标准勾选控件，重新打开后能看到第 16 通道仍被勾选。挂测截图可核对项目名称、任务终态、配置快照和原业务日志。窗口使用模拟项目，截图中的循环数、端口和日志只属于该用例。本阶段没有单独的实例启动窗口目标设计图。

| Qt 缩放 | 实例启动设置 | 开关机任务停止 |
| --- | --- | --- |
| 100% | [实例与允许范围](final-native/scale-1/instance-startup.png) | [停止回执与工作台](final-native/scale-1/power-stopped-receipt.png) |
| 125% | [实例与允许范围](final-native/scale-1.25/instance-startup.png) | [停止回执与工作台](final-native/scale-1.25/power-stopped-receipt.png) |
| 150% | [实例与允许范围](final-native/scale-1.5/instance-startup.png) | [停止回执与工作台](final-native/scale-1.5/power-stopped-receipt.png) |

三档复验通过并记录后，仅在本批初测、复验目录内清理了开发脚本生成的 PNG。777 张中，771 张过程图已移入回收站，表中的 6 张交付图和各次测试日志、机器结果均保留。

## 标准 Windows 候选包

3,240 项完整基线通过，242 项指定用例全部执行。三档 Windows 原生共 282 次通过。成品入口和 330 个项目模块与源码一致，97 个原业务文件与迁移前的哈希一致。目录与 ZIP 的 245 份文件已比对，验包逐一核对 39 个 PySide6/shiboken6 原生文件导入的 Qt6 DLL。ZIP 共 55,350,641 字节，SHA256 为 `11835ed0b42a46d327b220eb237129e7ec65f9280369ba1e645774c61b7f05f5`。

[Windows 便携 ZIP](../../../dist/qt-20261121-120503-1bc9ddf8/DUTPilot_portable.zip) · [SHA256](../../../dist/qt-20261121-120503-1bc9ddf8/DUTPilot_portable.zip.sha256.txt) · [构建与全量回归](build.txt) · [成品源码比对](packaged-sources.json) · [验包明细](../../../dist/qt-20261121-120503-1bc9ddf8/PACKAGING_REPORT.json)

本机仅静态核对新 EXE。目标机独立启动、实体多屏、真实 DUT 及长期挂测待现场验证。
