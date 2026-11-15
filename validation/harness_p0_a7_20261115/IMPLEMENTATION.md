# A1/A2/A7 实施与交付说明

本轮按A1、A2、A7三个批次实施，未修改老化测试业务PASS/FAIL、SSH执行器、A3凭据策略或A8权限语义。完整压力结果及曲线见[REPORT.html](REPORT.html)，原始数据见两个channels目录；版本边界见[VALIDATION_SCOPE.md](VALIDATION_SCOPE.md)。这是源码交付，没有构建或运行EXE、提交Git、调用真实模型或连接真实DUT。

## 修改与回退

22个Python文件的准确分组见[changes/manifest.json](changes/manifest.json)。补丁仅包含本轮拥有的源码片段：依次A1、A2、A7；回退顺序A7、A2、A1。共享文件必须逐段处理，不能恢复整文件。独立临时树逐批应用、专项测试以及逆向后正向往返均已验证，见[changes/reverse_checks.json](changes/reverse_checks.json)。补丁不包含个人配置、测试数据或同期其它改动，不要在已修改工作区重复应用。

| 批次 | 核心差异 | 主要文件（均位于Cheating_machine_execution_tool） |
| --- | --- | --- |
| A1 | 本机通用命令/写入在准备及发送前检查整机、目标、共享占用；三档权限均生效；GUI线程提供整机占用快照，串口租约检查关闭和其它控制者 | `src/services/ai_action_service.py`、`src/services/ai_serial_client.py`、`src/ui/ai_assistant_controller.py`、`src/ui/ai_serial_bridge.py`、`src/core/serial_transport.py`、`line_check_assistant/app.py`、三个相关测试文件 |
| A2 | Shell发送前复核；Boot、重新登录、EOF及未知结果使旧连接失效；禁止已尝试命令自动跨协议重放；cleanup不绕过保护；区分dispatched=false与结果未知 | `src/core/ai_debug_transport.py`、`src/services/ai_debug_service.py`、`src/services/ai_action_service.py`、`src/services/ai_conversation_service.py`、三个相关测试文件 |
| A7 | 弱引用数据观察器、60秒后台采样、主日志告警、关闭末次快照；不复制完整history、不读COM/socket、不改接收/写盘/缓冲方法 | 新增`src/core/transport_observation.py`和`src/services/transport_history_monitor.py`；接入serial/telnet transport、serial_terminal、app；登记编译清单；新增监测测试、压力工具与报告工具 |

同步文档：根目录`PLAN.md`、`.claude/plans/ai-harness-p0-a7.md`、`AI_HARNESS_COMPATIBILITY.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`及操作员`line_check_assistant_README.md`。A3/A8影响和兼容选择只整理在兼容文档中，等待确认。

## 测试证据与限制

复跑时从主源码目录执行，使用新的输出目录，避免把旧文本文件追加当作新测试；两个命令各实际运行一小时。这里的`python`应指向报告所用独立CPython3.9.10验证环境：

```powershell
python -B tests/transport_history_stress.py --channels 8 --seconds 3600 --interval 60 --output ../validation/new_run/channels8
python -B tests/transport_history_stress.py --channels 16 --seconds 3600 --interval 60 --output ../validation/new_run/channels16
python -B scripts/report_transport_history.py --output ../validation/new_run
```

- [旧版复现](reproductions.json)：隔离加载本轮起点5c21027，4个缺陷场景均按预期暴露失败；模拟连接及临时文件，不操作真实主机命令或设备。
- A1新增15项、A2新增13项、A7新增11项通过；同期其它任务改动合并后再次执行这39项仍全部通过，见[new_tests_current.txt](new_tests_current.txt)。包含下发前转忙、目标子集、纯只读/历史/报告/被动读取保留、登录否决、Boot/EOF/超时/发送异常、未知结果不重放、非阻塞采样、关闭不做文件IO及末次日志排空。
- 完成实现时[30组777项相关回归](related_tests_final.txt)通过，110.683秒，130个离屏窗口；后续主日志退出排空补充由[60项收尾专项](shutdown_checks.txt)通过。它们是当时版本的真实记录，不是完整基线。
- 同期其它会话改变界面后，[当前工作区再跑30组](related_tests_merged.txt)：785项、109.270秒，2个失败子用例、0错误、0跳过。失败仅为同一钉钉窗口测试在Vista/Clam主题期待旧按钮顺序；实际“诊断报告、自动监控”，断言仍是相反顺序。未越界回退同期产品改动或修改其测试，当前相关组合不能标为全通过。
- [静态检查](static_checks.json)：本轮22文件编译、源码编译登记覆盖与协议不变量；13个接收/显示/解码/写盘方法与起点AST一致；8个业务/权限/脱敏核心文件未改。静态检查不等于全量自动化或现场验收。
- [异常与完整性探针](logging_probes.json)揭示的是未修复风险，不能算作原始日志可靠性验收通过。早期失败记录保留在此目录，最终结论必须按所对应版本读取。

## history与日志路径调查

`_history`是会话内追加字节历史，现有绝对游标读取、命令回显/标记匹配和诊断证据依赖它。不能直接裁去前缀而不适配游标和历史分析。接收线程把同一读取块追加到history，并独立发送到文本日志写入路径；落盘不需要回读history。

串口文本路径逐块解码，在`_rx_log_line_buffer`积累半行，按完整行添加时间戳和RX方向后追加写文件；正常关闭补写尾行。实时显示截短不等于磁盘日志被截短。当前路径没有按容量自动轮转、删除或截断历史文件，但写失败、读线程退出、程序/系统异常退出、磁盘耗尽及待写半行仍可能形成缺口。Telnet文本写入错误存在被忽略路径。完整内存history不能证明磁盘文本完整；磁盘字节大小也不能代替接收字节量。

运行时接收量明确标记为从当前append-only history长度推导，不伪称独立驱动计数。压力工具另有驱动真实read计数和输入摘要作对照。`last_flush_confirmed=null`表示没有确认，不表示成功；被原实现吞掉的写异常无法靠只读采样恢复精确错误。监测记录包含文件大小、日志所在卷剩余空间、采集线程、可见错误及潜在停写状态。

## 日志完整性与异常验证

- 两次一小时合成ASCII负载分别核对输入、驱动read、内存原始字节及文本序号/规范化内容摘要。文本大小包含时间戳，不应与输入大小直接相等。
- UTF-8跨块探针出现替代字符；当前文本格式改变CRLF并添加时间戳，**不支持原始字节保真归档**。测试用`input/*.rx.bin`只是输入对照，不是程序新增归档能力。
- 1MiB无换行片段在显式尾行flush前全留内存，落盘为零；当前半行缓冲同样可能增长。不能从正常按行负载的一小时结果推断任意输出都不会积压。
- 注入串口写盘OSError导致读线程停止，session.error未记入该写错；监测可发现采集线程停止，无法补回日志或取得精确写错误。Telnet探针确认写错被原实现吞掉。没有伪造磁盘已满实机验证，也未改变这些原路径。

## 剩余风险及下一批

1. 优先设计完整RX二进制追加归档、兼容文本视图、时间索引与AI磁盘区间检索。即使分卷也全部保留，记录序列/时间覆盖，不能用轮转删除历史。明确flush/关闭策略、磁盘空间预警和写失败/采集中断告警，不允许静默丢弃。
2. 归档可靠性验证后再设计有界内存：保持绝对游标、活动命令等待窗口、回显匹配、实时打印和老化流程；旧区间从磁盘补读。覆盖多字节跨块、无换行、异常退出、写满/断盘、重连及多日负载后，才讨论替换history。
3. A1保守拦截所有通用本机命令，可能连Get-Date等无害操作也拒绝；本轮不放宽，推荐继续使用专用只读工具。纯文件读取、历史材料分析和报告正文未被占用检查阻断。
4. A2无法消除发送检查后远端瞬间重启的物理竞争；未知提示保守停止。真实Router/ONU提示符、Boot/重连、SSH/Telnet/串口、挂测并行以及可见Windows退出仍待负责人现场复验；未知结果始终不自动重发。
5. 60秒RSS是采样工作集而非连续峰值；8路早期观测版本与16路最终观测版本边界见范围文档。72/168小时仅按本次负载做趋势外推，未实际运行，不构成长期稳定性验收。
