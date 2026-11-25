# Qt 普通问答的本地掉线证据

2026-11-25，已接入正式 Qt 源码的普通问答。发送「CH03 为什么反复掉线？」可在聊天正文查看当前持续老化项目和批次内的已有观测。显式 CH 决定目标，查询前同时核对详情页、日志范围、运行快照和 DUT 的唯一通道映射。读取事务再次核对项目当前老化任务。切项目或切批次会使正在查询的结果作废，切回原项目也会丢弃旧回执。

## 查询结果与边界

- 查询沿用原只读历史入口。有界读取该 DUT 的最近 48 条观测，最多在聊天正文引用 6 条仍有效的记录，显示 UTC 时间、来源、记录编号和观察结果。过期和未来记录不参与结论。仅有 Ping 时，设备是否掉线及原因均未知。原证据按钮仍可查看其历史范围。
- 当前绑定缺失、通道无匹配、映射重复、批次已更新或数据库不可读时，正文提示原因或证据缺口。查询范围固定在本次绑定。回复按纯文本显示。
- 本地证据问答只在当前聊天窗口展示。后续成功发送或切换会话会替换该显示。原会话库、普通回复历史与老化历史导出沿用原入口。主执行日志记录查询阶段、目标、完成和失败，观测片段只进入本条本地回复。
- 原生用例使用合成项目和 Fake。新增取证用例对网络、模型、取凭据及设备与任务入口设调用断言，查询前后临时项目文件哈希一致。现场采集记录的质量决定能观察到什么，掉线根因仍需相应证据。

## 连续诊断补充消息

Qt 保留「已接收」。`AiConversationService.send` 将补充正文入队，保存的聊天消息只有补充标记。`DiagnosticTask.take_inputs` 取出正文，`AiConversationService._task_checkpoint` 追加到本轮内存并保存检查点。该检查点也会在取消或异常的 `finally` 中执行。后续真正调用模型前还会组装、裁剪请求，但现有记录缺少补充消息 ID 与 session、诊断任务及实际下一次 request/reply ID 的关联。单凭检查点事件无法证明这条消息进入下一次请求。共享执行与权限沿用原实现。

## 验证

| 范围 | 结果 | 证据 |
| --- | --- | --- |
| 只读证据、显示回执、诊断任务、老化及项目准备 | 67 项通过 | [专项日志](service-tests.txt) |
| Qt Windows 100% | 17 项通过，75 个受管窗口，零违规 | [日志](native-1.txt) · [隔离](native-1.json) |
| Qt Windows 125% | 17 项通过，75 个受管窗口，零违规 | [日志](native-1.25.txt) · [隔离](native-1.25.json) |
| Qt Windows 150% | 17 项通过，75 个受管窗口，零违规 | [日志](native-1.5.txt) · [隔离](native-1.5.json) |
| 局部源码与 GUI 能力覆盖 | 13 个 Python 文件编译通过，GUI 动作覆盖和差异检查通过 | [静态检查](static-checks.txt) |

从主源码目录使用项目锁定的 Qt CPython 3.9.10 和 PySide6 6.8.3。

```text
python scripts/run_tests.py test_qt_channel_evidence test_qt_ai_turn_display test_ai_diagnostic_task test_service_aging test_service_aging_feed test_project_preparation -v
python scripts/verify_capability_coverage.py
```

原生专项使用 `scripts.gui_test_process.run_gui_child(framework='qt', native_render=True)`，以 Windows Qt 插件分别设置 `QT_SCALE_FACTOR` 为 `1`、`1.25`、`1.5`，通过 `scripts/run_tests.py` 的 `-v` 执行以下用例。

- `qt_channel_evidence_probe` 全部 13 项，覆盖 Qt 发送按钮和 Ctrl+Enter、显式 CH 与相反的选中 DUT、缺失和重复映射、证据稀缺及过期、同名项目来回切换、批次变化、迟到回执、原证据按钮、普通聊天与连续诊断分流。
- `qt_workbench_probe` 三项，覆盖普通会话原历史、输入快捷键和正文、Fake 本机连续诊断和停止。
- `qt_project_wizard_probe` 一项，覆盖指定老化批次分页和导出。

本轮未执行完整基线。真实模型、物理 DUT 与现场运行未纳入本次验收。Git 状态仅供只读核对，现有暂存改动保留。无打包。过程 PNG 生成及清理均为 0，保留本报告、文本日志和隔离记录。

## 补充离线验收

2026-11-25，复核了实际请求派发边界。连续诊断继续显示「已接收」。掉线证据正文增加一条随证据现状变化的人工核对提示。只有 Ping 等观测时，可核对同一通道和时段有无明确离线记录。已经看到离线时，可按引用的时间对照该通道的现场记录。证据缺失或已过期时，等本批次有新的有效观测后可再查询。提示只显示在现有本地回复中。

### 补充消息与派发

| 位置 | 现有信息与边界 |
| --- | --- |
| 入队和持久化 | 队列保存正文，聊天库另存一个带补充标记的用户消息。SQLite 行号没有随队列项或协议消息传递，相同正文可以对应两条不同的记录。 [补充入队](../../src/services/ai_conversation_service.py#L421) · [消息写入](../../src/services/ai_store.py#L329) |
| 检查点和最终组装 | 检查点将正文加入本轮输入。诊断输入压缩和上下文预算之后才形成当次请求，终态清理也会调用检查点。容量估算还会调用一次请求体构建函数。 [检查点](../../src/services/ai_conversation_service.py#L632) · [预算](../../src/services/ai_context_budget.py#L67) · [收尾](../../src/services/ai_conversation_service.py#L990) |
| Qt 观察钩子 | 用量钩子可辨识会话、当前停止令牌和回复编号。调用模型客户端之前就会触发一次，返回后再次触发。它没有补充消息的归属或传输回执。 [调用顺序](../../src/services/ai_conversation_service.py#L824) · [Qt 用量显示](../../src/services/qt_ai_chat.py#L101) |
| 模型客户端 | Chat Completions 使用 `messages`，Responses 使用 `input`。两路最终在 `DiagnosticModelClient._request` 检查取消和出口条件后调用传输。现有 TX 日志在调用传输前产生，无消息级派发回执。 [协议封装](../../src/core/ai_client.py#L172) · [实际调用](../../src/core/ai_client.py#L51) |

现有挂点无法可靠显示「已带入下一步请求」。最低新增契约是为每条已接收补充生成唯一 ID，将它作为本地元数据随会话、诊断轮次及消息位置保留到裁剪后的最终输入。传输层须按实际请求尝试回报已确认派发的补充 ID，身份至少包含会话、诊断轮次和请求尝试 ID。模型正文、请求体、认证头和补充正文均无需进入回执。重复回执按 ID 幂等处理，未知派发、取消前未派发及其他会话或轮次的迟到回执只保留原有接收状态。该状态只表达输入随请求派发，推理过程中如何使用仍未知。此契约需要跨队列、组装及传输传递身份，本轮仅完成审查。

### 本轮证据

- Fake 传输审查三项通过。相同正文对应两个接收行，在下一次有效 Fake 请求中出现两次，另一会话只含自己的补充。取消发生在第二次回复编号生成后，实际 Fake POST 仍为一次。响应失败收尾保留补充记录，实际 Fake POST 仍为一次。日志仅记录合成计数和结果。 [派发审查](followup-transport-audit.txt)
- 44 项本地专项通过，覆盖证据读取、补充回执显示和连续诊断。 [专项日志](followup/service-tests.txt)
- Windows 私有桌面 100%、125%、150% 各通过 17 项，每档 75 个受管窗口、零违规。使用实际 Qt 发送按钮及 Ctrl+Enter 核对仅 Ping、有明确离线、稀缺及过期时的正文，并复验范围变化、迟到结果、原证据按钮、普通聊天、Fake 连续诊断及历史导出。 [100% 日志](followup/native-1.txt) · [125% 日志](followup/native-1.25.txt) · [150% 日志](followup/native-1.5.txt) · [100% 隔离](followup/native-1.json) · [125% 隔离](followup/native-1.25.json) · [150% 隔离](followup/native-1.5.json)
- 两个改动的 Python 文件通过编译，能力覆盖和 GUI 隔离入口检查通过。过程 PNG 生成及清理均为 0。完整基线、真实模型及设备、外部服务、Git 操作和打包均未执行。 [静态检查](followup/static-checks.txt)

### 11 月 26 日验收步骤

1. 从 VS Code 启动正式 Qt 源码入口 `run_dutpilot_qt.py`。打开已有留存记录的持续老化项目详情，进入「Ai助手 → 普通问答」。使用原有记录或 Fake 完成检查。
2. 若 CH03 和 CH04 均有冻结映射，先选中 CH04，再发送「CH03 为什么反复掉线？」。核对答复标题、批次、UTC 时间、来源和记录号均对应 CH03。仅有 Ping 时，正文应说明掉线和原因未知，并给出核对明确离线记录的提示。有明确离线时，应提示按离线时间对照现场记录。现场记录已过期时，可核对过期提示，新鲜数据分支可用合成用例重放。
3. 切到另一个项目后，在原聊天窗口重发同一句问题，应提示上下文不一致。切回后重新发送，应只得到当前项目和批次的回执。快速切回及迟到回执以原生合成用例为准。再用原工具栏菜单查看所选 DUT 的证据，并从原历史入口核对指定批次的查看和导出。
4. 在 Fake 本机连续诊断运行中发送补充，核对显示「已接收」。停止本轮后复查终态和接收原文。重复补充、跨会话和派发前取消以本轮 Fake 派发审查及原生日志为准。真实模型和真实设备不作为该项验收的前置条件。

这轮已验证上述合成分支、原生窗口、权限及范围边界。明早尚待操作员在自己的 Qt 源码工作台核对显示与阅读路径。未新增可供验收的「已带入下一步请求」状态。

## P0 本地查询任务结果和阶段回执

2026-11-25，将正式 Qt 普通问答的现有本地只读掉线查询收敛成带编号的查询结果。此次范围仍为当前持续老化项目、任务、运行快照及明确 CH，沿用原有能力验证、历史数据库只读事务和已有 48 条候选记录限制。

- 工作区受理后显示本地请求编号和「已受理」，正文仅提示正在核对。
- 接受与本次请求编号、项目、会话上下文及完整冻结目标一致的结构化回执后，才显示「已完成」。回执正文包含项目、老化任务、批次、配置版本、DUT 和 CH；在取证阶段显示 UTC 核对时间、候选数量、过期数量、时间无效数量、符合时效数量、实际引用数量和其余未展开数量。计数范围为本次查询返回的最多 48 条候选，而非完整历史库。
- 分析结果区分证据不足、发现明确离线观测，以及有离线、在线后再次离线的观测。重复掉线结论需要引用范围内明确离线事件及相邻在线心跳的记录顺序和时间支持。最多引用 6 条观测，未引用的候选只参与时效计数。根因始终未知，现场核对建议仍按现有证据展示。
- 目标不一致、工作区拒绝受理、读取失败及回执目标不匹配分别给出未开始、未受理或未完成的结果。使用聊天内既有「停止本轮」可取消本次本地读取；结果作废，迟到回执不能覆盖重查结果。切项目、切批次及关闭窗口继续作废在途查询。停止本地查询绑定本次读取的取消信号，无业务任务停止请求。
- 请求编号来自工作区现有请求序列，属于本次程序运行的显示凭据。回执和正文只在当前聊天窗口展示，主执行日志记录编号、阶段和计数，原历史库及聊天模型上下文没有新增写入。

### 连续诊断补充 P0 核查

本轮再次核对最新检出的 `AiConversationService.send`、`DiagnosticTask.supplement/take_inputs`、`_task_checkpoint`、`ConversationBudget.fit`、`QtLocalConversation.observe_reply_usage` 和 `DiagnosticModelClient._request`，现有链路仍缺少贯穿接收、组装和传输的补充 ID。SQLite 消息行、纯文本队列项和请求正文之间没有稳定关联。检查点可以发生在收尾阶段，用量观察钩子先于真正派发，真实传输当前没有补充级的确认回执。

因此保留「已接收」，本轮不写连续诊断共享执行代码。若后续授权此契约，应由接收位置生成唯一补充 ID，绑定精确会话和诊断轮次，以本地元数据映射至实际请求尝试中的最终输入位置；由真实传输确认后发出关联本次尝试与实际带入补充 ID 的回执。重试和新轮次使用独立尝试编号，过期、未知和取消前未实际发出的请求保留接收状态；迟到与重复回执按相同身份幂等核对。回执保持本地，不包含数据正文、认证信息或额外外发字段。该方案需要贯穿共享队列、裁剪与传输边界，因此超出本轮纯观察授权。

上一轮 [Fake 派发审查](followup-transport-audit.txt) 已复现同文重复、跨会话、派发前取消和失败终态。本轮又运行原有补充、停止、流式和 Qt 原生连续诊断回归，仅核对现有行为。

### P0 验证与修改范围

| 检查 | 结果 | 可核对记录 |
| --- | --- | --- |
| 本地服务、连续诊断、老化历史、项目准备相关回归 | 70 项通过，其中新增 3 项回执/分析测试 | [专项日志](p0/service-tests.txt) |
| Windows 原生 Qt 100% | 20 项通过，87 个受管窗口，隔离违规 0 | [日志](p0/native-1.txt) · [隔离](p0/native-1.json) |
| Windows 原生 Qt 125% | 20 项通过，87 个受管窗口，隔离违规 0 | [日志](p0/native-1.25.txt) · [隔离](p0/native-1.25.json) |
| Windows 原生 Qt 150% | 20 项通过，87 个受管窗口，隔离违规 0 | [日志](p0/native-1.5.txt) · [隔离](p0/native-1.5.json) |
| 局部编译、能力与 GUI 隔离覆盖、差异检查 | 通过 | [静态检查](p0/static-checks.txt) |

验证沿用前文六个服务测试模块和四个原生专项入口。新增原生用例包括挂起读取时停止、重试与乱序回执，读取完成尚未显示时取消，回执同编号但目标不匹配，以及数据库读取失败时不显示已完成阶段。其他原生用例核对原证据按钮、项目和批次隔离、普通聊天及连续诊断、历史分页与导出。测试对实际模型、设备、凭据和联网入口设置调用断言；合成项目查询前后文件哈希一致。

修改文件（相对主源码目录）

- `src/services/qt_channel_evidence.py`、`src/services/qt_workspace_adapter.py` 只读查询结果封装与现有历史分发。
- `src/ui/qt/ai_chat_controller.py`、`src/ui/qt/ai_chat_dialog.py` 请求状态与原停止按钮的本地取消分流。
- `src/services/capability_catalog.py`、`scripts/capability_gui_actions.json` 能力覆盖记录。
- `tests/test_qt_channel_evidence.py`、`tests/qt_channel_evidence_probe.py`、`scripts/verify_qt_migration.py` 回归与原生用例清单。
- `line_check_assistant_README.md` 以及仓库根的 `CAPABILITY_COVERAGE.md`、`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`，本报告与本轮日志。

待验收项为操作员在自己的 Qt 源码工作台查看请求阶段、引用结果及本地取消状态。连续诊断派发回执契约待另行授权。本轮不涉及实体设备、真实模型、外部服务、凭据读取、挂测或测试引擎修改、Git 写入和打包。未执行完整基线，保留已有记录。过程 PNG 生成及清理均为 0。

## 连续诊断补充实际派发回执（P0 后续）

2026-11-25，负责人明确授权增加共享的补充状态元数据。本次在保留前述本地掉线查询 P0 的基础上，接入正式 Qt 连续诊断。

### 回执契约

- 受理补充时为本轮生成独立消息 ID，原用户消息与仅含 ID、状态的 `chat_supplement_receipts` 记录在同一 SQLite 事务保存。重复正文也有不同 ID；会话和诊断轮次分别绑定。
- 队列仍保存原有文本及顺序，另有本地身份映射。检查点按原顺序追加标准用户协议消息。完整补充条目的对象身份用于核对上下文裁剪后的实际位置；旧历史、同文其他消息、诊断记忆片段均不能替代该身份。
- 每次原有模型调用仍使用既有本地回复 ID 作为独立请求尝试编号。实际传输前复核该位置与最终协议输入相符，只有同一次既有 `session.request` 返回有效 HTTP 响应状态后才确认。确认时核对项目会话、当前任务实例、停止令牌及回复编号；本地回执一次性落库。确认仅证明该完整独立补充条目随该请求尝试派发，远端是否成功处理或模型如何使用仍未知。
- 受理后显示「已接收」，确认派发后显示「已带入下一次请求」以及补充编号、请求编号。终态保留已确认回执。已取消且明确未派发显示「已取消，未派发」；终态明确未派发显示「未派发」；已进入可能的传输但缺少响应证明、观察挂点未经过或上次中断均显示「派发未核实」。这些状态都属于接受该补充的诊断轮次，后来的历史或同文请求不会改写旧回执。
- 旧版本仅有补充标记而无回执的消息继续显示「已接收」。重开窗口、切回原会话及分页从本地回执表读取。Qt 会话快照带单调递增生成编号，旧快照不能覆盖已经显示的接收或派发回执，也不能切回旧会话。会话删除时清理对应元数据。
- 模型协议正文、工具列表、正常发送顺序、权限、诊断及挂测判据、模型调用次数沿用原行为。新增 ID 和状态表不进入模型输入、诊断记忆、原聊天消息 JSON 或能力历史接口。传输观察点不启动额外请求。日志只将已有检查点用语改为准确的留存状态。

### 验证结果

本轮最终版本的 14 个相关模块共 268 项通过。

| 模块 | 通过 |
| --- | ---: |
| test_ai_diagnostic_task | 37 |
| test_qt_ai_turn_display | 4 |
| test_ai_core | 21 |
| test_ai_conversation | 53 |
| test_ai_session_deletion | 18 |
| test_ai_context_budget | 23 |
| test_ai_context_usage | 13 |
| test_ai_session_router | 26 |
| test_ai_workspace | 22 |
| test_capability_ai_data | 14 |
| test_qt_channel_evidence | 14 |
| test_service_aging | 8 |
| test_service_aging_feed | 7 |
| test_project_preparation | 8 |

[完整服务测试日志](supplement-receipts/service-tests.txt)

新增八项诊断服务用例覆盖同文不同 ID 和独立会话、派发前取消、确认派发后取消、预算拒绝、真实压缩后同文误匹配、Chat Completions 与 Responses 原始请求体等价及实际传输前篡改位置、无响应的未核实终态、数据库重载和会话删除。已有停止和 Qt 状态显示用例增强断言。全部使用临时合成数据库与 Fake transport。

| Windows Qt 原生 | 结果 | 证据 |
| --- | --- | --- |
| 100% | 21 项通过，92 个受管窗口，隔离违规 0 | [日志](supplement-receipts/native-1.txt) · [隔离](supplement-receipts/native-1.json) |
| 125% | 21 项通过，92 个受管窗口，隔离违规 0 | [日志](supplement-receipts/native-1.25.txt) · [隔离](supplement-receipts/native-1.25.json) |
| 150% | 21 项通过，92 个受管窗口，隔离违规 0 | [日志](supplement-receipts/native-1.5.txt) · [隔离](supplement-receipts/native-1.5.json) |

新增 `test_qt_supplement_receipts_survive_late_snapshots_and_only_confirm_next_transport` 在实际 Qt 普通发送和连续诊断入口上，用真实请求构建、Fake session.request 及受保护的传输方法完成以下核对。

- A 已组装并进入 Fake 传输时，连续提交两条相同补充，保持两个「已接收」。迟到的 A 快照以及重新应用的接收快照均无法使当前状态回退。
- 下一次 Fake 请求的原协议正文含两条补充。收到响应前保持接收状态，收到响应后准确显示两个独立补充的请求编号；随后的停止不清除已确认状态。
- 第三次诊断在补充随下一请求派发前取消，旧接收快照无法将终态回退，也未多发诊断请求。实际 Fake 诊断调用为 3 次，目标识别调用为原流程 5 次，真实网络调用为 0。
- 切换、切回会话及关闭重开窗口，回执归属与历史不变。保留前一轮 P0 只读查询和原普通聊天、证据按钮、历史导出及原连续诊断用例。

初轮服务测试 129 项中的一条新断言误将原已有回复 ID 作为新增字段，已按原协议事实修正。首轮原生新增用例未等待目标识别结束即点击下一次发送，已补足原入口就绪条件。最终完整重跑均通过。[初轮服务日志](supplement-receipts/initial-tests.txt) · [初轮原生记录](supplement-receipts/initial-native-failure.txt)

### 修改路径

- `src/services/ai_diagnostic_task.py`、`src/services/ai_conversation_service.py`，队列身份、请求绑定及终态回执。
- `src/core/ai_client.py`，仅对既有请求的最终输入和传输响应进行观察。
- `src/services/ai_store.py`，本地回执表、合并写入、状态更新、重启与删除处理。
- `src/services/qt_ai_chat.py`、`src/models/qt_ai_chat.py`、`src/ui/qt/ai_chat_dialog.py`，状态投影及迟到快照拒绝。
- `src/ui/main_log_filter.py`，留存提示的兼容过滤。
- `tests/test_ai_diagnostic_task.py`、`tests/test_qt_ai_turn_display.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`，专项测试与原生验证登记。
- `scripts/capability_gui_actions.json`、`line_check_assistant_README.md`、仓库根 `DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`，覆盖和操作交接记录。

局部编译、覆盖、差异与证据链接检查通过。[静态检查](supplement-receipts/static-checks.txt)

本轮未运行完整基线、真实模型、实际设备、外部网络或真实凭据，未执行 Git 写入或打包。新状态只在本机自动化与 Windows 非输入私有桌面验收，实际使用环境的可见操作仍待负责人检查。过程 PNG 生成及清理均为 0，保留原 P0 验收证据及本轮文本隔离记录。

## Qt 普通问答的状态事件呈现

2026-11-25，核对了正式 Qt P0 本地查询和模型流式回复的现有界面。发现本地查询正文已更新时，上方最新会话状态可能仍指向上次模型回复；普通模型回复已有本地回复编号，但界面快照没有保留。此次仅新增 Qt 展示数据和状态投影，复用既有「最新会话状态」栏。

### 实际展示内容

- 本地证据查询用原工作区请求编号、会话和真实读取回执显示已受理、已完成、未完成、未受理、未开始或已取消。证据不足仍属于查询已完成，结论在状态及原正文中显示。没有中间回执时只显示受理后等待回执。
- 普通问答的模型回复使用现有 draft/reply ID 与保留的终态正文记录。进入回复生成、收到流式正文、停止申请、完成及取消/失败均按实际来源渲染。模型请求编号尚未分配时明确显示会话请求和等待状态。编号为既有本地回复尝试 ID，未据此推断真实远端派发或模型采纳。
- 模型回复活动状态与正文流分别呈现。会话最近错误仍可在状态栏悬停提示查看。P0 本地结果优先呈现自己的状态及完整正文，旧模型状态不能覆盖；重新发送普通问题或切会话时沿用原窗口清理规则。
- 同一会话的迟到或重复快照按此前的快照生成序号隔离；本地查询结果沿用原请求编号及冻结目标核对。模型取消但没有正文的回复编号来自 Qt 对既有 abort 回调的本地观察，随当前 Qt 会话服务保留，重启后缺少持久正文或原日志编号时仍沿用已有会话状态。已有正文的历史回复可从原持久回复记录核对。
- 本轮范围为普通问答的本地查询和模型回复状态。连续诊断的既有诊断进展与五态补充回执继续使用原真实来源，避免用一般回复状态覆盖具体诊断阶段。没有新增百分比、假定工具进度、持久事件库、第三方协议或依赖。

实际价值是消除本地查询与旧模型状态的冲突，以及落实从模型流式正文到终态的实际请求关联。此为 Qt 展示归一化，现有业务执行、模型传输、权限、测试引擎及任务结果语义保持。

### 验证

| 范围 | 通过情况 | 记录 |
| --- | --- | --- |
| 8 个相关服务模块 | 189 项通过 | [服务日志](presentation/service-tests.txt) |
| Windows Qt 100% | 22 项通过，96 个受管窗口，违规 0 | [日志](presentation/native-1.txt) · [隔离](presentation/native-1.json) |
| Windows Qt 125% | 22 项通过，96 个受管窗口，违规 0 | [日志](presentation/native-1.25.txt) · [隔离](presentation/native-1.25.json) |
| Windows Qt 150% | 22 项通过，96 个受管窗口，违规 0 | [日志](presentation/native-1.5.txt) · [隔离](presentation/native-1.5.json) |
| 局部编译及覆盖 | 8 个 Python 文件、能力与 GUI 隔离覆盖、差异检查通过 | [静态检查](presentation/static-checks.txt) |

服务专项使用 `scripts/run_tests.py` 运行 test_qt_ai_turn_display（5 项）、test_ai_diagnostic_task（37 项）、test_qt_channel_evidence（14 项）、test_ai_conversation（53 项）、test_ai_session_router（26 项）、test_ai_context_usage（13 项）、test_ai_context_budget（23 项）、test_ai_session_deletion（18 项）。最后仅补齐 Qt 悬停错误信息和跨会话断言，最终三档原生覆盖该显示版本。

原生实际发送及窗口入口使用合成项目、原 Fake 和受核验 Windows 非输入私有桌面。覆盖 P0 本地证据受理、完成且证据不足、失败、取消、旧模型快照以及切回正常模型回复时状态更新；原模型流式正文和终态使用同一请求 ID，重开窗口仍可核对已保存回复，旧流式快照不覆盖终态；新增 `test_qt_ordinary_reply_event_cancelled_without_body_keeps_request_identity` 核对无正文取消、会话错误、跨会话与迟到快照。原连续诊断补充五态测试、普通聊天、历史导出和原证据按钮随同回归。

### 修改文件

- `src/models/qt_ai_chat.py`、`src/services/qt_ai_chat.py`，Qt 只读状态数据和原回复生命周期投影。
- `src/ui/qt/ai_chat_controller.py`、`src/ui/qt/ai_chat_dialog.py`，原状态栏及本地查询事件归一化。
- `tests/test_qt_ai_turn_display.py`、`tests/qt_channel_evidence_probe.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py`，专项测试与原生登记。
- `scripts/capability_gui_actions.json`、`line_check_assistant_README.md`、仓库根的 `DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`，覆盖和操作记录。

原生验证未访问真实模型、真实设备或网络，使用合成配置。完整基线、真实运行环境的可见操作和显示仍未验收。未执行 Git 写入或打包。过程 PNG 生成及清理均为 0。

## 变更文件

- `ACCEPTANCE_BASELINE.md`
- `CAPABILITY_COVERAGE.md`
- `Cheating_machine_execution_tool/line_check_assistant_README.md`
- `Cheating_machine_execution_tool/scripts/capability_gui_actions.json`
- `Cheating_machine_execution_tool/scripts/verify_qt_migration.py`
- `Cheating_machine_execution_tool/src/models/qt_ai_chat.py`
- `Cheating_machine_execution_tool/src/services/capability_catalog.py`
- `Cheating_machine_execution_tool/src/services/qt_ai_chat.py`
- `Cheating_machine_execution_tool/src/services/qt_channel_evidence.py`
- `Cheating_machine_execution_tool/src/services/qt_workspace_adapter.py`
- `Cheating_machine_execution_tool/src/services/service_aging_history.py`
- `Cheating_machine_execution_tool/src/ui/qt/ai_chat_controller.py`
- `Cheating_machine_execution_tool/src/ui/qt/ai_chat_dialog.py`
- `Cheating_machine_execution_tool/src/ui/qt/ai_chat_transcript.py`
- `Cheating_machine_execution_tool/src/ui/qt/main_window.py`
- `Cheating_machine_execution_tool/tests/qt_channel_evidence_probe.py`
- `Cheating_machine_execution_tool/tests/test_qt_channel_evidence.py`
- `Cheating_machine_execution_tool/validation/qt_chat_channel_evidence_20261125/REPORT.md`
- `DEVELOPMENT_LOG.md`
- `PROJECT_STATUS.md`
