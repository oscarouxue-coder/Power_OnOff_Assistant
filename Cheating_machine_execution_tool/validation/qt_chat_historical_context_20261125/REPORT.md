# P1/P2：Qt 聊天重开后的历史上下文用量显示（2026-11-25）

## 只读审计与独立缺口

复核当前普通聊天及连续诊断的实际代码、已有专项证据：

- [qt_ai_chat.py](../../src/services/qt_ai_chat.py) 的普通聊天 activity 按实际 reply_id 及 stream_state 投影，已保存完整/部分正文保留；原 Qt show_view 用单调 snapshot_generation 防旧回执覆盖当前窗口。
- [ai_conversation_service.py](../../src/services/ai_conversation_service.py) 已有 `_save_usage` 把原请求用量快照写入会话；[ai_context_usage.py](../../src/services/ai_context_usage.py) 已有接口返回、UTF-8 估算、仅输入估算、旧有效回复及失败/取消状态规则。无需改变任何模型请求、预算、存储或传输。
- 连续诊断补充 [先前证据](../qt_chat_channel_evidence_20261125/REPORT.md) 已有五态独立本地补充 ID/实际派发关联、同文重复、跨会话、迟到、重开及持久化：历史 268 项相关回归、三档原生各 21；普通正文/状态展示后续历史 189 项相关、三档各 22。拒绝把派发当成模型采纳。此次不重复开发它们。
- 普通回复无正文即取消时，原 Qt `aborted_reply_display` 是当前会话实例的临时显示；真正有部分正文的取消则原消息带 reply_id/status 持久化。未发现无正文取消的回复 ID 有对应持久记录，因此不能从用量记录推断它；这需另行决策持久契约，不在本次纯显示修复中。

明确缺口：原 Qt 仅从当前内存 `reply_display` 和 `route_display` 提供用量状态，原项目关闭重开后竟忽略已存在的有效持久会话 `context_usage`。不是重新发送/估算不足，而是可立即独立补齐的本地显示。

在改前正式 Qt 私有桌面用专属合成场景复现：实际创建项目及会话、持久保存纯合成原格式 API 计数（输入 12、输出 3、合计 15、当时上限 65536），关闭项目再重开、选择原会话后，存盘字段逐项相同、running=false，实际窗口仍只显示：

`本轮暂无可核对的模型请求与用量`

[改前真实 Qt 观察](baseline-observation.json) / [原生输出](native-baseline.txt)，1/1 观察用例通过，2.873s，5 个受管窗口，违规 0，真实 I/O 拒绝入口调用 0。该用例是记录旧行为，不能称旧显示满足要求。

开工 [文件哈希](workspace-before.json) 与上一轮 Fake 等待修正收尾快照 61 个已跟踪未暂存改动一致，目标文件哈希和现有并行修改稳定，未见新写入冲突。

## 窄修复

仅修改 Qt 显示层服务 `src/services/qt_ai_chat.py`：

- 活跃请求只展示原已核实的当前 reply_display/route_display；请求或会话不匹配、迟到时保留原暂无可核对的状态，不拿历史计数代替。当前和上次内存答复记录分别标注，原本地证据或身份显示保持。
- 不在历史分页重估或显示当前状态。会话无进行中的模型请求、无已绑定当前回复时，从 snapshot 已读取的精确会话 ID 的原持久 `context_usage` 只读投影历史；无需新的数据库写入或查询模型/配置。明确「非当前请求」。
- 校验来源、basis、state、非负整数及 input/output/total 一致性；接口返回数与 UTF-8 估算区别。只有历史输入估算时不伪造输出或完整回复；原记录时间或上限无可靠值则显示未知。失败或取消状态若仍有已保存回复计数，由于本结构没有稳定请求关联字段，标明计数与该次状态对应未核实，不推断属于最新失败/取消请求。
- 历史数据只展示原计数、保存时上限和时间；identity 只读取历史 capacity，不读取或显示 profile fingerprint，不访问当前模型配置或凭据、不读取当前容量、不把历史记录当账单或实时请求。

改后复用同一实际原生场景，[当前实际窗口观察](after-observation.json)：

```
已保存历史用量（非当前请求）
接口返回：输入 12，输出 3，合计 15 Token · 记录当时上限 65,536 Token
记录时间 2026-11-25T10:00:00+08:00；不代表当前配置或当前请求。
```

原存盘字段不变、running=false；[改后对照原生输出](native-after.txt)，1/1、5 个受管窗口、违规 0。没有实时调用或新持久契约。

## 最终定向验证

| 范围 | 实际通过 | 证据 |
|---|---|---|
| Qt 用量/回执投影 + 原上下文数学/保存/restart/取消 | 14/14，3.254s | [最终服务日志](service-tests-final.txt) |
| Windows 私有桌面 100% | 4/4，14.992s，25 个受管窗口，违规 0 | [日志](native-verified-1.txt) / [隔离](native-verified-1.json) |
| Windows 私有桌面 125% | 4/4，14.721s，25 个受管窗口，违规 0 | [日志](native-verified-1.25.txt) / [隔离](native-verified-1.25.json) |
| Windows 私有桌面 150% | 4/4，14.965s，25 个受管窗口，违规 0 | [日志](native-verified-1.5.txt) / [隔离](native-verified-1.5.json) |

新增两项服务用例对历史 API/估算/缺失/不一致、input-only、失败取消不冒充最后请求、历史时间/容量、会话隔离、当前 active stop 及旧 receipt、分页进行真实本地投影核对。

新增真实 Qt `test_qt_reopened_chat_displays_only_its_saved_context_usage_as_history`：3 个同项目独立会话分别保存 API、取消的仅输入估算、无历史用量；关闭项目后重开、选择每个会话准确显示，旧 snapshot 不覆盖另一个会话，原已存字段保持。其余三项原生复用原普通流式/窗口重开和持久显示、无正文取消且拒绝迟到、补充五态真实 Fake 派发/迟到快照和原持久记录。原流式用例增加当前/非当前请求显示的原 Qt 断言，既有业务断言保留。三档原生原测试 12 项最终通过，加服务 14 项合计 26；上述改前/改后对照各 1 项单独计。未把历史 268/189 数量称为本轮重跑。

所有上述测试均为 Synthetic/Fake 和非输入私有桌面，真实 HTTP/socket/串口/外部启动等保护调用均 0，原 HTTP 模型请求拒绝仍有效。四个 Python 文件原字节编译、限定差异格式检查通过；无新 GUI 业务动作、无框架/依赖/权限更改，过程 PNG 0。

## 改动范围和限制

生产仅 [qt_ai_chat.py](../../src/services/qt_ai_chat.py) 的本地展示；测试 [test_qt_ai_turn_display.py](../../tests/test_qt_ai_turn_display.py)、[qt_workbench_probe.py](../../tests/qt_workbench_probe.py)、[原生验收登记](../../scripts/verify_qt_migration.py)，操作员说明和 DEVELOPMENT_LOG。没有改 AI 请求、模型传输、自动执行/命令/设备/网络、挂测引擎、规则、测试等待或权限，也没修改已保存数据格式和任何原项目资料。

本轮 L0 定向显示和历史恢复通过，但实际用户阅读、L1 真实模型、L2 实际设备、L3 长期现场及完整基线未开展；不推断远端模型实际型号、不编造无正文取消后的持久回复编号。没有暂存/提交/推送、打包、删除或真实数据/凭据访问。结束差异见 [workspace-after.json](workspace-after.json)：HEAD 不变、暂存 0、追踪变更 63（开工 61），只有上述六个明确范围文件变化，范围外原有追踪文件全部哈希一致。
