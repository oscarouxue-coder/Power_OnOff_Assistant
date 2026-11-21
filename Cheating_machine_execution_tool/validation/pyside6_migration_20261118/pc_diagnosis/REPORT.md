# Phase 5 · Qt 本机电脑连续诊断

2026-11-21。范围为本机操作员在当前项目里发起的电脑连续诊断。使用 Qt 源码工作台的「AI 诊断 → 新建普通问答右侧菜单 → 新建本机电脑连续诊断」。原有普通问答仍可直接点击。

## Windows 交付

本阶段代码已通过标准命令 `build_line_check_assistant.ps1 -Gui Qt` 构建。完整解压后，目标机由 `DUTPilot_portable\DUTPilot.exe` 启动。ZIP 为 55,372,345 字节，SHA256 为 `15d7bd73d70333ef83c8176ea67f7f286dc98ae049ec6c2076fce5f50e8861ef`。[Windows 候选包](../../../dist/qt-20261121-103221-39df2f12/DUTPilot_portable.zip) · [SHA256 文件](../../../dist/qt-20261121-103221-39df2f12/DUTPilot_portable.zip.sha256.txt)

完整源码基线执行 3,233 项，其中全部 239 项指定测试命中。标准构建和静态验包退出码为 0。另逐一比对实际 EXE 中 325 个项目模块的代码对象、Qt 入口、包内操作手册及 ZIP 哈希，通过配对、诊断、原事件缓存和挂测等关键模块的存在性检查。迁移前记录中的 97 个受保护文件哈希仍一致。按项目规则未在本机运行新 EXE，独立目标机启动待验收。[基线与构建输出](build.txt) · [标准验包记录](../../../dist/qt-20261121-103221-39df2f12/PACKAGING_REPORT.json) · [成品源码比对](packaged-sources.json)

## 业务行为

- 会话由原 `AiConversationService.create_session` 创建，原记录中保存 `scope=pc`、空设备目标及 `diagnosis_only=true`。进入窗口和重开窗口仅显示留存记录。操作员发送问题后，原服务按模型工具资格、当前批次和会话来源决定可用工具。
- 查询电脑环境沿用 `PcConversationExecutor`，读取 Windows 系统信息、权限以及地址、路由、无线状态。模型工具调用、证据存储、运行中补充、停止事件和项目关闭时的收尾均使用原连续诊断服务。
- Qt 任务适配器持有每个项目各自的 `AiEvidenceContext`。原编排器在启动时提供其诊断批次号，旧业务子进程通过原旁路提供按通道和尝试编号关联的事件。窗口稍后打开时使用该项目已有的上下文。已创建的诊断服务通过原有队列接收事件，批次变化会唤醒原停止流程，撤销旧会话的实时查询资格。
- 本次 Qt 入口直接选择本机电脑。原 Tk 还支持用自然语言消歧、跨范围续接，以及常规电脑、设备、批量和远程会话。上述完整路由和实时串口联动仍待迁移。

## 验证记录

1. 执行原连续诊断、会话路由及 Qt 普通问答兼容测试，共 56 项通过，离屏守卫无违规。[服务测试原文](services.txt)
2. Windows 原生窗口通过项目菜单创建会话，固定模型及网络读取返回模拟数据。原执行器按顺序请求地址、路由、无线状态。测试确认 DUT 工具未获派发，证据写入当前会话，窗口关闭和重开后零额外读取。再次发送时可补充问题并停止，原模型工作线程收到停止事件。[补充与停止专项](focused-final.txt)
3. 在初次 100% 对照中发现新建会话按钮高度与原设计有差异，恢复与同栏原按钮一致的宽高，套用共享主色。专项检查按钮几何和原默认动作。随后验证已存在的项目批次、旧会话资格和下一会话的批次身份。[按钮几何专项](button-layout.txt) · [批次绑定专项](batch-binding.txt)
4. 模拟模型在第三轮会话中等待停止，项目收到下一批次启动事件。原服务发出停止信号，记录“新批次已开始”，执行器结束，操作员可在新会话沿用新批次号。此项另核对累计网络查询次数。[批次切换使在途请求停止](batch-stop.txt)
5. 通过 Qt 操作提交全部 16 个通道，保留原父进程，用模拟子进程返回逆序结果。逐字段核对原服务从保存配置生成的请求，验证第 16 通道失败、过期消息隔离、资源释放和该通道诊断事件的原批次归属。[16 通道专项](sixteen-channels.txt)

模拟测试未向实际模型发请求，未连接 DUT、串口或外部平台。真实模型结果、实际主机环境、目标电脑及长时间运行仍待现场。

最终源码在 100%、125%、150% 三个 Windows 私有桌面各运行全部 91 项原生用例，共 273 次通过，每档 1,834 个受管窗口、零隔离违规。此前用于发现布局差异的批次单列。三档均为 Qt 显式缩放。[最终测试记录](final-native/results.json) · [开发期测试记录](native/results.json)

保留首次及最终窗口图以核对按钮几何和状态文本。[初次 100%](native/scale-1/pc-diagnosis.png) · [最终 100%](final-native/scale-1/pc-diagnosis.png) · [最终 125%](final-native/scale-1.25/pc-diagnosis.png) · [最终 150%](final-native/scale-1.5/pc-diagnosis.png)

本阶段共生成 769 张窗口截图，765 张过程截图已移入回收站。上述 4 张报告引用截图、各档测试原文和 JSON 结果均保留。

## 涉及文件

- `src/services/ai_conversation_service.py` 增加创建时记录连续诊断的可选参数，原调用方默认行为保持。
- `src/services/qt_ai_chat.py`、`src/models/qt_ai_chat.py` 和 `src/ui/qt/ai_chat_dialog.py` 接入项目会话、原只读诊断、运行中补充与状态展示。`src/ui/qt/theme.py` 为同一主按钮的菜单式外观提供共享样式。
- `src/services/qt_execution_adapter.py`、`qt_workspace_adapter.py` 和 `capability_device_services.py` 连接原项目执行器的诊断事件旁路。原设备命令、开关机时序、停止和结果判定继续由既有编排器执行。
- `tests/qt_workbench_probe.py` 验证真实 Qt 控件与模拟模型的完整往返，`tests/test_qt_execution_adapter.py` 核对原 16 通道子进程边界和旁路事件使用同一批次。`scripts/verify_qt_migration.py` 登记必跑原生用例。
- `scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`、根目录 `CAPABILITY_COVERAGE.md` 更新能力说明和 GUI 快照。操作方式、状态、验收范围和变更分别记入操作员手册、迁移进度、项目状态、验收基线和开发记录。
