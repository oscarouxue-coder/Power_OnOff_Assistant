# 下一增量：样机升级界面和执行边界

保留样机升级接入前审计。自动串口与逐台状态的已实现范围见[升级日志阶段报告](FIRMWARE_OBSERVATION_REPORT.md)。Qt 已实现的执行和保存范围见[样机升级阶段报告](FIRMWARE_REPORT.md)。Tk 原入口继续供现场使用，以下兼容差异用于下一增量核验。

| 边界 | 现有实现 | 迁移需保持 |
| --- | --- | --- |
| 模式及参数 | `line_check_assistant/app.py::_open_upgrade_module`、原 `SampleUpgradeSettingsStore` | 页面升级与全包升级。全包保留 Tftp 指令、Tftp Put、Web 网关、Boot 方式、并行 1–8、恢复出厂、实际固件与目标通道。升级和写参初始凭据属于同一文件的独立字段。 |
| 原目标和地址 | `_selected_page_upgrade_channels`、`_selected_tftp_copy_upgrade_channels`、`build_upgrade_requests` | 保留各模式的网卡、源 IP、样机 IP、COM 与电源通道选择。TFTP 固定样机目标及锁源约束、Web 同网段预检、原端口冲突检查都沿用。 |
| 预检和文件绑定 | `FirmwareUpgradeValidation` 与 `CapabilityService._upgrade` | 复用文件哈希、目标绑定、配置版本、资源检查及固件适配确认。预览不写网卡、不控硬件。最终下发使用同一已验证的固件内容。 |
| 执行与停止 | `dispatch_upgrade` 分发四套原业务引擎 | 保留原 Boot、上传和重传、`done + write`、重启/上线、恢复出厂及停止安全点。界面进度只能根据原事件更新，UI 不推导刷写结论。 |
| 自动串口监控 | Tk `_attach_serial_upgrade` 与 `begin_upgrade_logs` | 全包升级开始时的原串口日志联动、共享会话和升级控制优先保留。Qt 串口界面已有相同会话管理器，但 `firmware.upgrade` 入口目前没有把这些回调透传给 Qt。 |

原有兼容差异及接入记录：

- 旧 Tk 在未配置程控电源时允许操作员明确确认已手动重启后继续。标准能力入口继续返回 `manual_restart_required`。Qt 已接入独立本机确认，绑定项目版本、固件、实际网卡、设备和串口，确认后保留空电源口进入原引擎。[手动重启报告](FIRMWARE_MANUAL_REPORT.md)
- 审计发现原 Qt 运行快照误读 `network_card_ip.ini`，现已改为当前项目同目录的 `sample_upgrade_settings.ini`。已验证 DUT 本机初值读取，未改写两份项目文件。升级配置继续使用修正后的同一存储路径。见[后续报告](QT_FOLLOWUP_REPORT.md)。

测试从临时项目、Fake 固件、Fake 网卡/串口/电源/浏览器开始，经原确认、Job、资源保护和原引擎接口执行。阶段门禁还需逐模式晚到事件、停止、固件和版本变化拒绝、日志归属、实际截图和完整基线。真实设备、刷写、网卡和电源操作留给负责人现场验收。

自动串口联动的接入点已核对：全包引擎会把实际 `session` 和文件路径传给 `on_session_ready`，旧窗口通过 `subscribe` 观察同一个会话。Qt 可在本机升级分发层接该回调，将有界文本事件及原日志路径送给串口界面，界面沿当前线程规则刷新。测试须验证观察订阅不调用 `acquire_control` 或打开第二个 COM；原 Job 停止后释放会话，自动打开的窗口随任务收尾，已有的用户监控在结束后保留。不同批次、切换项目或晚到回调不得复用旧订阅。手动重启分支不得把允许缺失程控电源作为远程能力参数或代入虚拟 COM。

下一阶段核对原三项全流程。当前 `pipeline.start` 已保留原编排入口，Qt 现有直接执行只接入独立环境检查与自动开关机。旧窗口默认三项均不选，串口日志在其余项目之前预启动且失败不阻塞，环境线路检查失败停止后续。已经移出旧全流程页面的升级、写参、ONU 等入口继续独立使用。
