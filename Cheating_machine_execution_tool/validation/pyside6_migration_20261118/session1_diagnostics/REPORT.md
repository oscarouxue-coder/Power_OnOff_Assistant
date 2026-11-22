# 会话 1 交接 · Qt 本机诊断与挂测证据

Qt 本机通道会话在选择通道、打开「查看留存证据…」和继续提问时均可取得本次挂测记录。两通道模拟回放中，修复前 Qt 在通道 3 取到 0 条，原服务取到 16 条。修复后双方各取到 16 条，逐条对齐。条数来自本次运行。[修复前](before-evidence.json) · [修复后](power-comparison.json)

最终完整基线运行 3,267 项测试，266 项指定用例全部命中，八类检查全部通过。Windows 私有桌面 100%、125%、150% 三档各通过 100 项。[完整基线](baseline-accepted.txt) · [机器可读结果](results.json)

## 共同起点与文件归属

只读参考目录为 `%LOCALAPPDATA%/LineCheckAssistant/qt-source/local-intent-26b1c43f`。发布记录中 697 个输入的集合 SHA256 为 `9e70315bcf225e66bee859cb028ca509c16daa958097acca9bec4c7791e6feb7`。本会话工作副本为 `C:/Users/Administrator/AppData/Local/LineCheckAssistant/qt-source/session1-diagnostics-20261121`。排除 Git 工作树指针、字节码和缓存后，复制的 2,786 个文件在修改前逐文件 SHA256 一致。[复制核对](copy-check.json)

会话 2 可在相同起点应用[源码和文档差异](session1.patch)，再复制本专项目录。前后 SHA256、新文件和验证材料见[文件清单](files.json)。共享的 `scripts/verify_baseline.py` 追加编译项和必跑测试 ID。`tests/qt_workbench_probe.py` 在既有用例中核对证据窗口。根文档按新增段落合并，主仓同期跨实例转发改动由会话 2 统合。

在主仓逐文件执行过只读的补丁适用检查。三份根文档的上下文已变化，需按段落合并。其余路径在本次检查时可应用，包括有同期改动的 Qt 会话、工作区测试和基线清单。主仓验证目录随交接已包含两个新回放脚本，合并时可从补丁排除已复制的专项目录，并按清单校验二者哈希。会话 2 合并时可复核这些路径。[主仓逐文件核对](shared-merge-check.json)

## 修复经过

原开关机流程对同一项目送达两次诊断开始通知，均带有本任务配置上下文。工作台 Job ID 与诊断批次 ID 实测不同。运行目录名由项目快照服务分配。[开始通知回放](before-binding.json)

原服务在创建会话时先刷新，此时路由尚未标记本机通道。随后 Qt 对设备会话的刷新直接返回。本轮由 `QtExecutionAdapter.observe_ai_event` 把项目事件交给沿用原缓存的 `QtPowerEvidence`。开始通知记录运行配置目录和当时的目标。读取时核对项目 `runs`、`run.json` 的项目及快照身份、初始目标、运行配置、当前草稿和会话目标。会话首次核对成功便保存快照标识。目标变化、快照缺失或来源冲突时保留原材料，并向操作员提示原因。

`QtAiChat._select_channel_route` 标记通道后，选择入口再刷新。追问沿用原会话刷新入口。当前设置也须在目标核对后才能写入。日志沿用原有 64 KiB 尾读、模型认证密钥过滤和批量去重。事件保留原时间，文件证据保留读取时间和行内故障时间说明。主执行日志记录核对条数或跳过原因。

## Phase 5 逐项核对

| 项目 | 原 Tk 入口及服务 | Qt 入口与实测 |
|---|---|---|
| 本机会话 | 对话工作区调用 `AiSessionRouter.send`，按目标复用会话 | `ai_chat_send` 明确选择通道 7 时跳过意图模型，自然语言经一次模拟识别选中同一目标。无效目标澄清、取消、迟到回执、恢复草稿及保留新输入均有回归。[明确切换](explicit.json) · [自然语言](natural.json) · [工作区专项](accepted-focused.txt) |
| 电脑排障 | 普通电脑路由与专用 `diagnosis_only` 会话各自保留偏好 | 普通问答切到电脑后保持普通模式。专用连续诊断创建独立会话，可补充问题及停止。[原服务与 Qt 对照](pc.json) · [原生用例](native-final/scale-1/tests.txt) |
| 当前挂测记录 | `AiConversationService.refresh_evidence` 从 `AiEvidenceContext.snapshot` 取证 | 本次 6 类 16 条逐项比对原文、来源、通道、批次及时间说明。事件产生时间一致。文件记录另核读取时间格式。重选去重，日志暂时不可读有反馈，恢复后可补读。另项目同号通道、同项目异通道、旧批次、同诊断号不同快照、报告和远程历史均有隔离反例。模型指定本地路径或其他串口均被拒绝。[明细统计](power-comparison.json) · [专项](accepted-focused.txt) |
| 历史报告与会话 | `create_session_from_report` 用报告目标，旧格式由本机确认关联 | 报告查看、接手、留存追问、批量删除复用原项目库和服务。旧格式在确认时复核目标。当前批次报告与远程记录也不会附加当前挂测设置。[报告和历史专项](accepted-focused.txt) |
| 审批 | 原会话的 `permissions.status` 及 `actions.pending/decide` 核对具体操作 | Qt 权限、审阅及决定入口沿用原服务。项目专项覆盖跨项目、指纹过期及拒绝。原生对话框用模拟待办核对批准与拒绝。只读通道没有主动采集待办。[专项](accepted-focused.txt) · [准入回放](phase5-scope-final.json) |
| 实时设备诊断和监控 | `AiMonitorWindow` 将策略和确认交给 `monitor.apply`。Tk 控制器装配串口独占、禁用端口、项目传输及目标/主机忙碌桥 | Qt 可询问操作员、检索材料和按资格被动读取已打开串口，模拟设备零写入。主动传输、串口独占与监控面板尚缺对应 Qt 适配。负责人需指定优先开放的采集类型、可控现场目标及资源冲突验收条件。[现有工具集](phase5-scope-final.json) · [串口回放](gateway.json) |
| 批量会话 | `AiBatchService.route/submit` 复核父授权、各通道及共享无线占用，子任务结果回到父记录 | Qt 可查看父记录和整组删除。模拟模型选择两个通道时，界面明确提示待接入，输入恢复，未创建批次。开放执行依赖各子任务的项目采集及资源保护适配。需确认逐台执行、停止和失败恢复的现场范围。[批量回执](phase5-scope-final.json) · [会话管理专项](accepted-focused.txt) |
| 网关及执行隔离 | 原网关处理项目控制。原开关机子进程持有资源 | 网关完成项目列表和切换，拒绝远程读串口及停止。取消本机目标识别后，原任务仍持有资源，通道 3、9 完成两轮断电、通电共 8 帧，终态 `completed`。物理串口打开与外部请求均为 0。[网关回执](gateway.json) · [逐帧回放](power-isolation.json) |

额外回放向已受理批次注入来源不明的模拟事件，原会话没有取得该标记。收到相同诊断号但配置来源冲突的开始通知后，既有材料保持原样。已登记的模型密钥在事件原文入库前被过滤。[来源与脱敏回放](phase5-scope-final.json)

## 复验命令

在副本的 `Cheating_machine_execution_tool` 执行。共同起点的两个旧对照脚本断言修复前的行为。修复后运行本目录的 `check_power_parity.py`。

```powershell
$py = Join-Path $env:LOCALAPPDATA 'LineCheckAssistant/qt-build-py39/Scripts/python.exe'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = (Get-Location).Path + ';' + (Join-Path (Get-Location) 'tests')
$stage = 'validation/pyside6_migration_20261118'
& $py "$stage/session1_diagnostics/check_power_parity.py"
& $py "$stage/session1_diagnostics/check_phase5_scope.py"
& $py "$stage/local_chat_intent/check_intent_during_power.py"
& $py "$stage/local_chat_intent/check_gateway_chat.py" --expect-bridge --gateway
& $py "$stage/local_chat_intent/check_selection.py" --case natural
& $py "$stage/local_chat_intent/check_selection.py" --case current
& $py "$stage/local_chat_intent/check_pc_preference.py"
& $py scripts/run_tests.py test_ai_session_router test_qt_workspace_adapter test_qt_execution_adapter -v
& $py scripts/verify_capability_coverage.py
& $py scripts/verify_baseline.py
& $py scripts/verify_qt_migration.py --output "$stage/session1_diagnostics/recheck"
```

## 验证记录

修改前两个专项共 80 项通过。首次新增用例的模型夹具漏配上下文容量，传输守卫拦住了容量探测。增加文件路径反例时，普通问答模型先返回工具未开放。给夹具登记已验证工具资格后，原服务明确拒绝额外路径参数。最终 128 项专项通过。[首次失败](focused.txt) · [工具资格反例](final-focused.txt) · [最终专项](accepted-focused.txt) · [能力覆盖](capability.txt)

自然语言对照首次遇到上一轮识别仍在收尾的拒绝回执。夹具原先只等待选中会话空闲，现同时等待后台识别完成，再执行原路由对照。[首次回执](natural-first.txt) · [复验](natural.json)

最终源码在受守卫的 Windows 私有桌面完成 100%、125%、150% 三档，各通过全部 100 个指定用例，违规数为 0。证据窗口显示七号通道及原时间说明，异通道标记没有进入窗口。[原生结果](native-final/results.json) · [100% 截图](native-final/scale-1/ai-current-power-evidence.png) · [125% 截图](native-final/scale-1.25/ai-current-power-evidence.png) · [150% 截图](native-final/scale-1.5/ai-current-power-evidence.png)

两批原生用例共生成 852 张 PNG。核对阶段目录及报告引用后，849 张过程截图已移入回收站，保留上述 3 张交付截图。

首次完整基线在模拟网关升级的 4 秒等待内未收到执行器进入信号。单独复验从网关到假执行器和断线后的原 Job 回执均通过，耗时 2.812 秒。[首次基线](baseline.txt) · [单项复验](gateway-baseline-recheck.txt)

第二次完整基线出现 Fake 版本查询未准入。两进程重复用例复现了宿主互斥拒绝同一个模拟网卡 adapter:vlan21。版本查询和模拟固件网关测试现沿用仓库已有的进程级台架标识。资源键、真实系统互斥、身份授权及业务断言沿用原值。已接入前一版交接的会话 2 可仅对 tests/test_ai_version_query.py 和 tests/test_remote_gateway_agent.py 应用新增差异。两个独立进程同时运行版本、网关以及原有宿主锁争用和释放用例，各通过 38 项。[第二次基线](baseline-final.txt) · [复现回执](version-concurrent-a.txt) · [独立进程 A](independent-bench-a.txt) · [独立进程 B](independent-bench-b.txt)

真实模型、现场 DUT 与串口、长期挂测、系统 DPI 和目标机待现场验收。会话 2 负责组合源码、验包与整体交付。
