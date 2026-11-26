# 工作区关闭生命周期修复 preflight（2026-11-25）

**终态：并行修改冲突，停止生产写入。** 本轮尚未修改生产源码或现有测试，也未开始修复后的测试。没有暂存、提交、推送、打包、删除或读取现场配置。上轮定位和数据保持不变。

## 已核对的关闭顺序

- QtWorkspaceAdapter 正常退出先确认项目选择和后台任务安全收尾，等待执行、平台、查询、AI 会话等完成，再关闭 WorkspaceService，保存会话并写入最后一条工作区日志。
- worker 的 finally 仍等待管理和历史线程池收尾并处理已完成的回执；普通退出才同步等待日志写入器关闭。更新任务仍需在业务关闭后记录最后一条日志时，现有 GUI 经 finish_log_close 等待写入器真实结束；此分支不能提前解除 adapter/service/logger 关联。
- WorkspaceEventWriter 现有 begin_close 会停止受理并通知写线程，close join 写线程；写线程正常退出须排空 pending 和 overflow，且写入结果由原 report 回调反馈。单凭收到关闭请求不能判断写盘完成。
- 独立 WorkspaceService 的关闭次序先关闭模型 store、平台池、gateway runtime、资源库。资源恢复回调、平台池捕获 service 的闭包和 adapter 的 emit/日志回指仍是上轮最可能的引用环，具体内核句柄种类不明。未改变任何授权或恢复行为。

## 写入前冲突检测

[before.json](before.json) 和 [after-conflict.json](after-conflict.json) 为原工作区只读 Git/文件 SHA-256 快照。开始和结束 HEAD 69887ae5f4dafdf109cb80e7a21cbeafa6f574fb，分支 feature/pyside6-migration，暂存 0，追踪改动 51 项。计划涉及的以下两个源文件在本轮只读核对之间发生字节变化：

- src/services/qt_workspace_adapter.py
- src/services/workspace_service.py

当前差异额外出现资源回收调用，分别位于 adapter 的资源相关路径和 service 的 enable_automatic_resource_recovery；相同时间段还有 workspace_resources.py、test_project_management.py 的变化。它们属于正在并行工作的资源生命周期范围，与当前修复依赖的关闭前置条件存在关联。虽未观察到同一关闭代码行上的文本冲突，但无法在当前持续变化的依赖上保证既有行为；按授权的冲突停止要求，不尝试覆盖、回退或只交付半个修复。

## 待恢复时的验收范围

待另一工作完成上述共享文件后，以新的哈希和关闭顺序重新审查：保留业务关闭成功及原后台收尾判定，仅在成功的正常关闭与延迟日志写入都完成后释放已失效的引用，特别保护更新取消末尾日志、重复关闭与关闭被拒绝的分支；独立 WorkspaceService 的结束态也须证明只在合法关闭后解除内部循环引用，不改变平台准入或恢复行为。不以生产强制 GC 处理。无需新依赖或架构改造。

再用此前 [专项定位](../qt_workspace_handle_audit_20261125/REPORT.md) 探针及固定报告窗口、Fake 挂测隔离、真实 Qt 私有桌面关闭日志等待和三档缩放回归验证。未得到修复后输出之前，不将上一轮 130 次合成对照记作此次修复通过。L1/L2/L3 未开展。
