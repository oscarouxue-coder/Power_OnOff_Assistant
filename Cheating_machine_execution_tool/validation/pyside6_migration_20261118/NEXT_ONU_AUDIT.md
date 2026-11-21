# Phase 5｜ONU 入口迁移前审计

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

原 Tk 窗口在 `line_check_assistant/app.py::_open_onu_registration_module` 内装配四步入口。项目的 `onu_registration.ini` 使用 `OnuRegistrationStore`，保留 C300/C600 各自的连接、模板和业务设置，以及历史字段回读。Qt 实施记录见下方各阶段报告。

| 功能 | 原实现及接入边界 |
| --- | --- |
| OLT 连接与范围 | `OnuCapabilities.connection` 按型号读取原配置并校验源地址和 PON。保留连接测试、模板查询和未注册发现。查询可选整 OLT，注册、删除、配置预览和离线清理必须限定单 PON。 |
| 授权与资源 | `CapabilityScopes` 对 OLT 型号、目标地址、源地址、PON、动作和连接指纹生效。Qt 本机确认应使用明确范围，并保留读、写、整机配置保存的授权边界。切换型号、项目、连接或 PON 后清空依赖旧范围的结果和确认。任务及取消继续经原 Jobs 与资源租约。 |
| 查询到预览 | Tk 查询后可选择多台并为各台指定 ONU ID，再用 `build_batch_requests` 与 `OnuCommandEditService` 构造和校验计划。已验收的确认页仅显示可复制的只读命令文本，修改业务参数须返回上一步。现有 `onu.preview` 会重新查询并构建默认计划，本机预览须绑定操作员实际选择的发现结果。 |
| 执行与保存 | 原 UI 将不可变 `OnuCommandPlan` 交给 `OnuRegistrationService.register` 并按实际参数验证。C300 完成后另问是否保存。C600 仅在确认过保存选项且实际验证成功时启动独立保存。注册、删除和整个 OLT 的保存需要分别绑定实际授权。 |
| 已注册管理 | `query_registered_candidates` 和 `OnuBatchDeleteService` 保留当前 PON、目标读取及逐台验证。C300 离线清理只在单台注册、显式候选且复核仍离线时成立，批量注册与 C600 无这条重试路径。 |

双型号配置和查询已接入。[查询阶段报告](ONU_QUERY_REPORT.md) 多选、逐台 ID、业务参数、只读命令计划和注册已接入。[注册阶段报告](ONU_REGISTRATION_REPORT.md) 当前 PON 的已注册 ONU 批量删除已接入，确认使用本次查询中的接口和 SN，逐台复核与回读仍在原服务。[管理阶段报告](ONU_MANAGEMENT_REPORT.md) 注册验证完成后可按原方式独立保存 OLT 启动配置。[保存阶段报告](ONU_SAVE_REPORT.md)

已接入 C300 单台注册的原离线清理重试。[清理阶段报告](ONU_CLEANUP_REPORT.md)

- 保留原临时开关默认关闭且不落盘。关闭或改变型号、目标、配置后作废候选和预览。
- 复用 `OnuRegistrationService.query_c300_cleanup_candidates`。它根据不可变的单台注册请求定位 PON，以只读状态和 baseinfo 返回同 PON 候选及 SN。选择项必须来自本次查询并明确冻结接口、ONU ID 和 SN，预览和最终确认都应显示被授权的清理目标。
- 向原 `register` 服务传入此次已确认的候选。旧引擎只在 C300 单台配置遇到 CLI 错误后，重新读取实际状态和身份，接口、SN、离线状态均符合才删除并重试一次原注册命令。候选失效、上线、SN 不符、中止或通信失败时保留原错误路径。注册最终验证成功后继续使用本阶段独立保存确认。

已核对后续原生私有桌面记录，C300/C600 目标发现、预览注册、删除、保存以及 C300 离线清理重试的 5 项模拟用例在三档缩放全部通过。实机连接、注册、删除和保存配置的验收仍需负责人确认。三档结果 · 批量注册确认 · 删除结果 · C300 清理确认
