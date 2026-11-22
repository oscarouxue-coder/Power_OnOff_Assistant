# Qt 实时设备诊断与多通道排障

本阶段在当前项目 Qt 源码入口接通了实时状态查询、串口独占、异常监控和多通道排障。操作入口为「Ai助手 → 新建普通问答 ▾ → 实时诊断与监控…」。已有 Windows 候选包对应此前的集成源码。

## 软件路径与边界

| 操作 | 实现与检查 |
| --- | --- |
| 选择通道、模型与采集范围 | 本机界面展示 VLAN、COM、源地址、管理地址、模型及资料接收地址。确认令牌一次使用，应用前重读目标、模型和批次。受控能力 `diagnostics.qt.configure` 接受 GUI 来源。 |
| 单设备实时查询 | 原会话权限服务处理首次登录。预定义设备状态查询复用原有锁源 Telnet、串口回退及项目资源租约。串口由项目的 SerialSessionManager 取得独占并释放。电源口冲突、目标变化、关闭和占用在执行前复核。 |
| 挂测异常监控 | Qt 接到原执行器事件和已打开终端的接收事件。沿用 AiMonitorService 的通道、异常阈值、特性、冷却、关键词、错误码和审批策略。面板显示排队、运行、收尾和待批准数量，审批绑定监控操作 ID 和指纹。 |
| 多通道排障 | 本机聊天路由交给 AiBatchService。父会话记录任务和进度，各子会话保留实际观察。逐台执行、停止、继续剩余及重查失败沿用原调度。Ping 使用已确认通道的配置与出口。 |
| 诊断工具 | 当前通道可读取预定义 DUT 状态、PC 环境、网络状态和已有串口输出，可作限定出口的连通性检测。模型可以查找本会话已有证据和询问操作员。设备登录和具体操作的审批沿用原服务。 |

## 自动化证据

[96 项专项回归](focused-final.txt)覆盖 Qt 工作区命令、原批量调度、监控审批和诊断传输。新增集成用例从临时项目创建和模型选择进入，使用模拟模型、驱动、Telnet 会话及 ICMP 回执。

- 模拟通道 7 的系统查询经过原诊断传输，记录的发送命令与目标源 IP 均经过检查。模拟串口取得和释放时核对控制所有者。
- 从 Qt 父会话对通道 7、9 顺序执行 Ping，并验证由模拟模型分解的逐台系统查询。两个子任务各留有预定义 DUT 状态查询回执。停止第一台时第二台保留停止状态，继续剩余会执行两台；第二台无回复时只重查第 9 通道。
- 注入挂测失败事件后，自动监控为第 9 通道生成登录待办。过期指纹被拒绝，匹配批准后完成查询并保存报告。匹配的串口输出进入通道上下文，VLAN 与 COM 不匹配的事件被排除。
- 配置变化使旧确认失效；模拟非 GUI 调用无法授予权限。关闭后复查批量资格及串口入口，并检查终端订阅释放。全程禁止外部模型请求与物理串口操作。

## 完整基线

项目独立 Qt 开发环境执行 `python scripts/verify_baseline.py`，八类门禁全部通过，编译 387 个文件，覆盖 377 个源码文件。全量运行 3,280 项，270 项指定用例实际执行。[最终基线收据](baseline-final.txt)

首次在全局解释器运行时，虚拟环境占用识别用例失败；当时工作区接线仍在更新，Qt 新用例记录到一个属性错误。使用独立 Qt 环境与定稿业务源码单独复跑这两项通过，全量复验通过。随后对同一业务源码补充了模拟模型分解并逐台取证的断言，见上述专项结果。[首次失败记录](baseline.txt) · [两项复验](baseline-recheck.txt)

## Windows 原生复验

定稿源码在 100%、125%、150% 三档各通过 102 项，合计 306 次。每档 1,886 个受管窗口，窗口隔离违规为零。新增界面用例触发「Ai助手」下拉菜单，核对设置请求、勾选通道和提交参数，并在未选择普通会话时审阅和拒绝指定监控操作。[三档结果](native-verified/results.json)

保留本功能的三个设置面板截图供核对：[100%](native-verified/scale-1/qt-channel-diagnostics.png)、[125%](native-verified/scale-1.25/qt-channel-diagnostics.png)、[150%](native-verified/scale-1.5/qt-channel-diagnostics.png)。

本阶段三个原生验证批次共产生 1,283 张 PNG。核对 Git 状态和报告引用后，已将 1,280 张过程截图移入回收站，保留上列三张。

## 改动文件

以下为本轮修改，源码路径相对于主源码目录。

- 服务与数据模型：`src/services/qt_device_diagnostics.py`、`src/services/qt_ai_chat.py`、`src/services/qt_serial_terminal.py`、`src/models/qt_ai_chat.py`。
- 共享业务接线：`src/services/ai_diagnostic_service.py`、`src/services/ai_monitor_service.py`、`src/services/ai_conversation_service.py`、`src/services/ai_session_router.py`、`src/services/ai_batch_service.py`、`src/services/capability_catalog.py`。
- Qt 窗口和控制器：`src/ui/qt/ai_monitor_dialog.py`、`src/ui/qt/ai_chat_dialog.py`、`src/ui/qt/ai_chat_controller.py`。
- 验证及覆盖：`tests/test_qt_workspace_adapter.py`、`tests/qt_workbench_probe.py`、`scripts/verify_baseline.py`、`scripts/verify_qt_migration.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`、仓库根 `CAPABILITY_COVERAGE.md`。
- 操作和交接：`line_check_assistant_README.md`、[迁移进度](../MIGRATION_PROGRESS.md)、本报告及收据、仓库根 `ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。

若需要恢复旧的 Qt 行为，可移除本阶段 Qt 设置入口与诊断接线，并还原本阶段为共享服务增加的注入点。运行中的诊断先在本项目停止，等待串口释放和任务收尾。现场结论按项目原验收记录维护。
