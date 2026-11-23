# DUTPilot V1.3.x 现场验收记录

将本材料、待验的 `DUTPilot_portable.zip` 和同一次构建的 `DUTPilot_portable.zip.sha256.txt` 带到目标 Windows 机。便携包完整解压到新目录。另存本表，每个项目和运行批次分别保存，证据路径可相对本批记录目录填写。

| 批次信息 | 现场填写 |
|---|---|
| 验收人、复核人及报告时间 | |
| 目标机、Windows 版本、系统时区、实际缩放、多屏布局 | |
| 候选版本、ZIP SHA256、解压目录 | |
| 项目 ID、开关机运行 ID 或全业务老化 Job ID | |
| 上次项目版本、导入或重开方式 | |
| DUT 标识、网卡、串口、电源通道和其他资源映射 | |
| 配置快照、批次开始和结束时间 | |

## 采集工作台进程数据

在目标机通过任务管理器确认当前 `DUTPilot.exe` 的 PID。以操作员身份在本材料目录打开 Windows PowerShell，准备实际批次的项目和运行 ID。采样只读取所选进程信息，不启动设备任务。挂测本身使用工作台的正式入口和确认流程。

```powershell
$workbench = Get-Process -Id ([int](Read-Host '当前 DUTPilot.exe PID'))
$processStart = $workbench.StartTime.ToUniversalTime().ToString('o')
$zip = (Get-Item -LiteralPath (Read-Host '候选 DUTPilot_portable.zip 完整路径')).FullName
$project = Read-Host '项目 ID'
$run = Read-Host '开关机运行 ID 或全业务老化 Job ID'
$trace = Join-Path (Get-Location).Path ('qt-process-' + (Get-Date -Format yyyyMMdd-HHmmss) + '.jsonl')
powershell -NoProfile -ExecutionPolicy Bypass -File .\watch_process.ps1 -TargetProcessId $workbench.Id -ExpectedStartUtc $processStart -CandidateZip $zip -ProjectId $project -RunId $run -OutputPath $trace -DurationSeconds 259200 -IntervalSeconds 60
```

24 小时专项将 `-DurationSeconds` 设为 `86400`。一次连续 72 小时观察可在第 24 小时取中段记录。采集首行记录两份哈希、PID、进程启动时间和操作者填写的项目及运行 ID。用工作台批次回执复核填写的 ID。需要提前结束观察时，在另一个 PowerShell 窗口用实际日志路径创建 `<日志路径>.stop` 文件，停止采样后保留日志和终止原因。目标进程重启时新建采样文件并登记缺口。

## 回填验收结果

| 验收项 | 实际证据 | 结论 |
|---|---|---|
| 目标机启动、已有项目重开、原历史读取、系统缩放及多屏切换 | 保存环境、实际操作和截图 | |
| 自动开关机每台 DUT 500 个已完成轮次 | 逐台批次原始结果、上下电与检查回执、失败或续跑、停止及资源释放 | |
| 语音连续通话 48 小时 | 通话起止、连续性及中断记录 | |
| LAN 长 Ping 48 小时且丢包率低于 1% | 源网卡、目标、起止、发送量及丢包率 | |
| 常温全业务老化 7 天 | 逐 DUT 业务观测、原始采集、正常与异常、断流和恢复、每日检查与期末按键检查 | |
| 24／72 小时无人值守 | 同批进程 JSONL、界面响应、任务进度、日志落盘、内存／CPU／线程、异常和收尾回执 | |

逐项填写通过、失败或待确认。异常需记录发生时间、处理和补测证据。仅有采样 JSONL 时可核对进程资源与采样时长；业务连续性按实际业务记录判定。
