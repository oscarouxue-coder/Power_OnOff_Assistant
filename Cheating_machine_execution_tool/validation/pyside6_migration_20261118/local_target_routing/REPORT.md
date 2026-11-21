# 本机会话目标切换对照

修正前，在临时项目配置通道 7，用模拟答复客户端发送同一句「切换到通道7」。Qt 当前的发送入口沿用所选普通问答，产生一次模拟答复；旧 Tk 所调用的目标路由在刷新配置后选中通道 7 的设备会话，本次只切换目标，业务提交次数为 0。验证中的模型外部调用、外部连接和串口打开均为 0。[复现脚本](check_selection.py) · [结果](selection.json)

[旧 Tk 发送路径](../../../src/ui/ai_chat_panel.py)使用[原目标路由](../../../src/services/ai_session_router.py)，可以只切换会话。[Qt 会话服务](../../../src/services/qt_ai_chat.py)修正前直接向选定的可写会话发送。Qt 控制器在服务成功受理后清空输入，服务报错时保留输入。此次对照定位了 Phase 5 的单通道切换差异。已交付的网关「切换项目」命令选择的是项目，与这里的本机设备会话是两个入口。[各阶段结论](../MIGRATION_PROGRESS.md)

## 修正后的行为与回归

Qt 的发送入口与 Tk 共用原路由的单通道识别、有效目标澄清、批次及模型身份核对和会话复用。Qt 只对明确的单通道表达启用这一分支。普通问答中的日志引用仍留在当前会话。报告、批量任务和连续诊断记录不会被复用作新的通道材料会话。仅切换时不会排队、启动模型或打开设备。选择已经切换的通道后可以导入材料和继续询问。此阶段的通道会话使用留存材料。自然语言模型路由及设备实时工具仍待迁移。

在临时项目中通过工作台的实际发送入口验证了目标切换、重复选择、无效通道澄清及带回原问题、配置变化后重新绑定、历史报告隔离和跨项目拒绝。具备工具能力的模拟模型只能询问用户或检索留存证据。首次跨项目测试没有先打开第二项目的 AI 窗口。修正测试入口后又核对了原留存会话的两种合法工具，最终 30 项专项通过。专项包括原 Tk 路由及 Qt 保存槽位重开的回环网关用例。[专项结果](focused-final.txt) · [能力覆盖](coverage.txt)

涉及[共享路由](../../../src/services/ai_session_router.py)、[Qt 会话服务](../../../src/services/qt_ai_chat.py)、[项目目标配置读取](../../../src/services/qt_ai_report_handoff.py)、[工作区回归](../../../tests/test_qt_workspace_adapter.py)、[原生窗口验证](../../../tests/qt_workbench_probe.py)、[原生清单](../../../scripts/verify_qt_migration.py)与[基线清单](../../../scripts/verify_baseline.py)。

两个独立工作区项目各启用 16 个模拟通道，原子进程分别完成两轮，每个项目 64 帧，共 128 帧。另一次从 Qt 停止项目 A，项目 B 按原计划完成。[双项目逐帧记录](parallel-power.json) · [单项目停止对照](parallel-stop.json)

首次同时运行原生窗口与标准构建基线，150% 的 3 项原生用例和完整基线中的 5 项失败，多进程争用相同的模拟串口或网卡。首次构建被门禁拦下。100% 另行全跑 98 项通过。原失败的 5 项基线和 3 项 150% 原生用例分开执行后全部通过。完整候选验证与后续串口联动串行执行。[首轮基线](build.txt) · [首轮三档](native/results.json) · [基线失败用例复验](baseline-failed-fixtures-retest.txt) · [150% 失败用例复验](native-failed-fixtures-retest.txt) · [100% 追加全跑](native-current-100/result.json)

本阶段沿用既有会话布局。Windows 100% 源码窗口显示通道 7、当前模型与已切换的状态，输入区已清空，停止按钮保持禁用。[100% 窗口](native-current-100/ai-local-channel-switch.png) Tk 入口继续沿用原路由。后续的[串口阶段](../local_serial_chat/REPORT.md)在本机通道会话上增加了被动读取。

组合源码已完成串行的三档 Windows 原生回归和标准构建基线。[最终测试与交付](../local_serial_chat/REPORT.md)

本次可用 `check_selection.py --case current` 复验明确通道，用 `--case natural` 复验通用表述差异。[明确通道同源复验](../local_serial_chat/selection-current.json) · [自然语言目标差异](../local_serial_chat/selection-natural.json)

阶段报告完成后，已将 549 张过程 PNG 移入回收站，报告引用的 1 张 Windows 原生截图保留。
