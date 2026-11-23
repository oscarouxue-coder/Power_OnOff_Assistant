# DUTPilot Tk 源码退役核对

Qt 是主程序唯一的源码入口和标准构建界面。本轮基于当前 `run_dutpilot_qt.py` 启动约定。独立串口升级和 ZTE ONU 工具继续使用各自的 Tk 界面。

## 主程序入口核对

| 原业务入口 | Qt 当前实现及删前核对 |
| --- | --- |
| 项目新建、打开、切换、保存、历史导入、关闭 | Qt 工作台已调用原 `WorkspaceService` 和 `ProjectStore`。继续保留旧项目备份、配置草稿及已保存版本的断言。 |
| 环境检查、预备测试、开关机、失败轮次续跑、全流程 | Qt 走原执行器。保留源 IP、只执行选中目标、安全停止、资源释放、批次快照及失败回执的指定测试。 |
| 串口、固件升级、写参、DUT、ONU | Qt 有对应业务窗和原服务入口。核对旧窗口专项中的选中目标、确认、协议、部分失败和未知结果。独立工具另有运行入口。 |
| AI 聊天、历史、报告、案例、监控和人工审批 | Qt 有本机界面与服务。受控扩展已接入本机导入、审阅、停用及恢复。任务历史支持本机确认后请求当前项目活跃任务安全停止。 |
| 钉钉、飞书应用配置、群身份绑定、飞书试发和 SDK 缺包修复 | 本轮补齐 Qt 源码入口。应用配置沿用原加密存储，群绑定复核项目与群 ID，绑定结束回收临时连接。试发确认使用已保存项目名和群 ID。SDK 修复完成后等待工作区退出再启动。 |
| 钉钉和飞书直连排障启停、飞书挂测通知开关 | Qt 复用原平台池、会话服务及通知队列。模拟验证覆盖本机项目授权、平台身份、撤权和停止后续通知。实际群、单聊和自动通知仍待分别现场复验。 |

## 清理边界

- 当前 `src` 和 `line_check_assistant` 中仍有 49 个文件直接导入 `tkinter`。`tests/test_*.py` 中有 66 个文件命中 Tk 工具、旧 `app` 或 `tkinter`。这些统计用于定位，逐文件仍需核对共享代码和测试断言。
- 用显式导入语句收窄到 63 个测试模块，其中包含 88 个当前必跑用例。`test_app` 有 58 项，`test_pipeline_window` 有 7 项。其余主要分布于窗口隔离、打包历史、项目收尾和串口等测试。这个统计包含仍应保留的独立工具与隔离设施用例。
- `line_check_assistant/app.py`、`pipeline_window.py` 仍由完整基线编译，`test_app`、`test_pipeline_window` 和部分 Qt 迁移契约仍直接引用旧窗口。每个必要断言应先落到共享服务或 Qt 原生测试。纯 Tk 控件布局和渲染断言随对应窗口退出。
- Qt 继续使用原配置存储、主日志过滤和执行器。删除应按调用关系处理，Qt 正在使用的共享模块需保留。Qt 私有桌面验证现在拒绝导入 `tkinter` 和 `_tkinter`，旧回归继续经原 Tk 隔离守卫执行。
- WiFi 默认值和 WAN 规则已有无需 Tk 的测试，Qt 启动契约和消息试发也已移除旧窗口导入。旧导出别名继续由 Tk 历史测试核对。其余待移除断言仍须逐项登记 Qt 或共享服务替代用例。完成对应现场复验与源码放行后再删除旧窗口。

## 优先核对的断言

| 旧断言集中位置 | 已有 Qt / 共享测试入口 | 删前须逐项核对 |
| --- | --- | --- |
| `test_app` | `test_qt_dut_configuration`、`test_qt_dut_wifi`、`test_qt_dut_wan`、`test_qt_onu_query`、`test_qt_workspace_adapter` | 保留默认值、逐通道输入、业务参数、保存和真实停止的检查。旧控件身份与外观断言随窗口退出。 |
| `test_pipeline_window`、`test_project_completion` | `test_qt_execution_adapter`、`test_qt_workspace_adapter`、`qt_workbench_probe` | 核对默认未选、已选操作准入、运行快照、未确认草稿、任务关闭及未核实资源保护。 |
| `test_serial_terminal`、`test_ui_lifecycle_runtime` | `test_qt_serial_terminal`、`qt_workbench_probe` | 核对串口所有权、收到数据、停止时序、项目关闭及迟到回执。 |
| 历史打包和 Tk GUI 隔离 | `test_portable_release`、`test_gui_test_coverage`、Qt 私有桌面守卫 | 按旧主程序和仍保留工具区分依赖。Qt 发行包使用现行规范，独立 Tk 工具保留原隔离断言。 |

## 全流程窗口的 7 项指定回归

| 旧用例 | Qt 对应断言及缺口 |
| --- | --- |
| `test_pipeline_defaults_to_no_selected_subtasks` | `test_qt_pipeline_choices_prestart_original_serial_terminal_before_environment` 检查三项及顺序、首次打开无选择、开始禁用。`test_pipeline_requires_explicit_choices_and_rejects_changed_serial_destination` 从服务层复核空选择和变更的串口目标。 |
| `test_main_stop_request_uses_existing_orchestrator_stop_event` | `test_stop_waits_for_engine_and_keeps_resources` 和 `test_qt_start_switch_stop_and_exit_wait_for_original_job` 已检查原执行器收到停止、等待实际退出期间继续持有资源。 |
| `test_pipeline_start_hides_configuration_window_after_thread_starts` | `test_qt_pipeline_choices_prestart_original_serial_terminal_before_environment` 检查确认后后台复核拒绝时保留窗口、无串口和任务；成功受理后窗口收起，任务结束后可重新打开、再次操作。 |
| `test_pipeline_thread_dispatches_completion_through_main_ui_queue` | 同一 Qt 原生用例用真实事件循环接收原流程完成回执，并更新反馈。`test_qt_start_switch_stop_and_exit_wait_for_original_job` 另外覆盖停止期间主事件循环继续响应。 |
| `test_pipeline_confirmation_does_not_call_numbered_items_pipelines` | 同一 Qt 原生用例校验串口与环境检查顺序、确认文案使用「子任务」、拒绝后无动作。 |
| `test_start_all_checks_recovers_stale_running_status` | Qt 用项目任务记录与实际执行状态更新按钮。全流程原生用例检查真实结束后可重新开始。结束状态不明时，`test_qt_unknown_task_review_requires_local_confirmation_and_preserves_verdict` 和 `test_qt_reviews_one_persisted_interrupted_job_in_bound_history` 检查保留资源保护及本机核实。 |
| `test_build_context_uses_saved_onu_config_after_services_text_is_destroyed` | Qt 全流程限定为环境检查、串口日志和开关机。ONU 改为独立入口。`test_qt_onu_profiles_discovery_and_stop_from_project_details` 检查 C300/C600 独立保存，关闭重开后加载已保存的 C600 PON 和服务模板。 |

旧用例仍在指定清单内。上表登记了对应的现有断言与差异，方便补足再撤下旧主程序覆盖。

## 本阶段验证

- `python scripts/verify_baseline.py` 通过 3,379 项测试，实际运行 285 项指定回归。完整基线仍包含历史 Tk 覆盖。
- `python scripts/verify_qt_migration.py` 集成阶段在 100%、125%、150% 各通过 122 项原生回归。随后补入任务停止及全流程启动回执，在同三档各通过 15 项相关原生回归，两次运行均无隔离违规。最后一次局部改动沿用集成阶段的完整基线结果。
- 钉钉与飞书真实群、单聊及挂测通知，以及目标机 SDK 安装后的重启，仍按验收基线 §3 记录。本阶段使用模拟平台和设备。[验收基线](../ACCEPTANCE_BASELINE.md)
