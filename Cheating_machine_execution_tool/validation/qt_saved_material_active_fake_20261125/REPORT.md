# P0C：在途 Fake 挂测与历史报告并发隔离

2026-11-25，原工作区 `feature/pyside6-migration`、HEAD `69887ae5f4dafdf109cb80e7a21cbeafa6f574fb`。本轮补齐 P0C 原[复核缺口](../qt_saved_material_batch_20261125/REPORT.md)：在同一项目中真正存在运行中的原业务任务实例（下层为已有完全 Fake 的 `ControlledPipeline`）时，验证本地历史报告错误及取消。

## 真实 Qt 合成用例

`tests/qt_workbench_probe.py::QtProjectWorkspaceTests.test_qt_saved_material_error_and_cancel_leave_active_fake_power_job_unchanged`

- 复用 `_configured_execution()`、`configure_project()` 和 `ControlledPipeline`。所有项目、配置、历史任务及结果文件均为临时合成夹具；真实串口、HTTP、Python socket 连接/发送/监听及地址解析入口均设置拒绝断言，既有真实模型传输拒绝继续生效。未改动原测试引擎、设备命令、权限或生产逻辑。
- 通过正式 Qt 启动入口确认并启动原业务任务。Fake 上报运行状态、68/100 轮进度和 `fixture stage`，等待测试释放。记录实际业务任务 ID、任务库状态/结果/事件以及资源所有者。
- 在该任务仍在运行时，从正式任务历史入口选择另一个已保存批次，多选两通道文件，模拟其中一份读取失败：报告保留有效通道的引用并标明另一通道无可读资料。原活跃任务的状态、结果、事件及资源所有者不变，原 `stop_event` 未设置。
- 重查时在第二个通道的原本地读取服务等待，独立取消报告，保留第一通道的实际报告并标记第二通道取消；活跃 Fake 挂测不受影响。关闭两个历史窗口并等待读取队列收尾后，再核对原任务状态、结果、输出和资源不变。
- 释放原 Fake 挂测的正常完成信号后，任务正常成功并保存原结果项，原输出前缀完整保留、出现 `fixture result`，资源释放。原历史文件及快照字节不变。三档中所有真实串口/网络拒绝入口均零调用。

## 实测结果

| 缩放 | 专项结果 | 隔离记录 |
| --- | --- | --- |
| 100% | 1/1 通过，6 个受管窗口，违规 0 | [终态输出](native-final-1.txt) · [隔离](native-final-1.json) |
| 125% | 1/1 通过，6 个受管窗口，违规 0 | [终态输出](native-final-1.25.txt) · [隔离](native-final-1.25.json) |
| 150% | 1/1 通过，6 个受管窗口，违规 0 | [终态输出](native-final-1.5.txt) · [隔离](native-final-1.5.json) |

三份最终日志中的 `ACTIVE_FAKE_HISTORY_EVIDENCE` 来自测试实测并一致：`running`、68/100、结果为空；原 7 条任务事件在报告错误/取消/关窗后原封不变；结束 `succeeded`、`ok=true`、原单项结果 `true`、最终 10 条事件且原前缀保持、`fixture result` 存在、`stop_observed=false`、资源释放、原历史字节不变、真实串口/受保护网络调用各 0。该输出不能解释为真实设备通过。

初版三档均通过记录也保留（`native-1*.txt/json`）；最终版另加 socket 拒绝范围及实际 JSON 证据，成功复跑。只生成文本/JSON，过程 PNG 生成及清理均为 0。

## 完整离线门禁的前置判断

[前置核对与实际退出码](baseline-preflight.txt) 已记录局部编译、能力覆盖、GUI 隔离预检及差异检查成功。正常完整门禁会发现并执行全量测试，现存测试含真实本机回环 TCP/UDP、WebSocket、实际浏览器等用例；窗口隔离不能证明全部真实 I/O 均封闭。另在本轮期间原工作区出现其他并行挂测相关未暂存改动，原样保留。按负责人“不能保证全部满足 Fake/隔离无真实操作则停止”的明确条件，完整门禁没有调用，故没有完整门禁退出码，不宣称本轮完整基线通过，也没有修改、跳过或绕过它。最近原提交完整基线 3,444 项通过为历史记录。

## 变更与验收边界

仅新增上述定向测试及 `scripts/verify_qt_migration.py` 原生必跑登记、准确记录。保留所有 P0A/P0B 及并行工作。L0 现补齐“原 Fake 挂测在历史报告读取错误/取消期间运行并正常完成”的组合；L1 真实模型、L2 实际设备、L3 长期现场均未开展。未暂存、提交、推送、打包或删除文件。
