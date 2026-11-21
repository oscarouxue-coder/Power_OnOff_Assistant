# Phase 5｜批量写样机参数迁移前审计

表格生成、加载、预检、本机确认及独立写参已接入。下表保留接入前的对照。原串口会话的 Qt 自动只读窗口已接入，旧全流程联动仍待迁移。[写参报告](PARAMETER_WRITER_REPORT.md) [串口观察报告](PARAMETER_OBSERVATION_REPORT.md)

| 入口 | 原实现与需保全的行为 |
| --- | --- |
| 项目设置 | `line_check_assistant/app.py::_open_sample_parameter_writer` 与原 `SampleUpgradeSettingsStore`。保留同一个项目 `sample_upgrade_settings.ini` 中的首次登录凭据、并行数（1–8，默认 1）、退出老化、清空参数及上次已载入表格路径。保存写参部分时应保留升级和其他设置。 |
| 读取和预检 | 原 `load_parameter_records` 与 `preflight_parameter_targets` 处理 CSV、XLS、XLSX（底层加载器也识别 XLSM），并依据实际已选通道的 VLAN/COM 生成目标。Qt 应呈现原错误和警告，保存前校验项目版本。 |
| 本机确认 | Tk 从原预检输出取 VLAN、COM 和 MAC，还校验首次登录凭据、PC 与样机 IP 冲突及工厂网段。确认显示两项可选动作与原九步流程。本机确认应绑定实际表格内容、目标、配置和选项，默认取消。 |
| 批量执行及停止 | 原 `run_sample_parameter_batch` 已同时供 Tk 和能力层调用。保留 Telnet/UBUS、源 IP、串口回退、并行、等待重启、15 项读回和工厂模式清理，复用资源租约与协作取消。未经负责人验收，现场结论保持待确认。 |
| 表格生成 | Tk 通过 `generate_parameter_records` 和 `save_parameter_records_xlsx` 使用旧模板并由操作员选路径。能力接口 `parameters.generate` 只可在受控工作区生成新文件。迁移本机另存入口时保留原核心生成和用户路径授权，远程能力边界保持现状。 |
| 日志与完成 | Tk 将串口路径的 `on_session_ready` 接入日志终端并在完成时收尾。当前能力适配器写入 Job 事件，未转发会话回调。Qt 可复用本轮观察机制，但须按写参批次隔离回调和结果。 |

接入前 Qt 只初始化 `devices`、`channels` 两组能力。本轮增加本机界面控制，复用 `parameters` 共享预检和原写参任务。

## 自动串口窗口的接入边界

- 原 `run_sample_parameter_batch` 仅向串口目标传递 `on_session_ready`。Telnet 目标使用原文本日志，工厂模式二次登录继续使用原会话切换。
- 串口回退在获得控制权后通知观察者，在原 runner 的清理阶段释放。可复用升级的有界只读订阅机制，按项目及写参批次隔离，观察失败不得中断原写参。验证应覆盖已有手动终端、并行目标、停止收尾、迟到回调和异步退订。
