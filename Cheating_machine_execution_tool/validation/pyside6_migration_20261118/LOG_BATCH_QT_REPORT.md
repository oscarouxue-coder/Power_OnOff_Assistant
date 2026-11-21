# Qt 实时日志增量刷新和突发回归

2026-11-20，DUTPilot V1.3.0 第一阶段，原计划 Phase 6、7 和 9 的日志范围。

## 审计

工作区将日志批量交给 GUI，交接缓冲上限为 500 条和 128 Ki 字符。Qt 日志面板已经限制缓存，原刷新仍会每批扫描缓存中的全部条目、拼接匹配文本并调用 `setPlainText` 重建文档。150% 私有桌面上的回归用例在满载后追加一小批日志，现场复现一次整篇重建。多行记录的行数预算此前由 Qt 文档单独截断，可能与导出选中记录的边界不同。

## 实现

实时批次只处理新日志和因超出上限淘汰的头部记录。文档按行块裁剪前缀，再成批追加筛选命中的新行。切换项目、通道、任务、级别、搜索或清空时重新计算当前视图。继续处理多行消息，缓存按最多 5,000 个文本行块和约 1 Mi 字符计，达到上限时整条淘汰最早记录。关闭自动滚动时沿用原滚动位置策略。

导出在点击时冻结当前筛选中保留的记录。原工作区日志追加、原任务/通道标识、后台日志发出路径以及归档读取上限继续沿用。日志显示缓存淘汰不删除工作区文件中的原文。窗口操作和文档编辑继续在 GUI 主线程执行。

## 修改文件

- `src/ui/qt/log_panel.py`
- `tests/qt_workbench_probe.py`、`tests/test_qt_workspace_adapter.py`、`scripts/verify_qt_migration.py`
- `scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json` 和能力覆盖文档
- 操作员说明、迁移计划和进度、项目状态、开发记录与验收基线

## 复验命令

```powershell
python scripts/run_tests.py test_qt_workspace_adapter test_qt_archived_logs test_qt_log_history test_qt_log_export test_qt_execution_adapter test_workbench_status test_qt_migration_contract test_capability_coverage -v
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_log_batch_verified_final
```

## 已核对

- 四个后台生产者各写 1,500 条合成项目日志。验证工作区文件累计 6,000 条，每个生产者内顺序和序号正确。未消费时交接缓冲保留 500 条，累计淘汰数为 5,500，暂无新增写盘失败。活动条目继续携带原任务和通道字段。
- 150% 原生专项 2 项通过，检查满缓冲增量编辑、多行和 Unicode 记录、项目/任务/通道筛选，以及导出冻结。既有 GUI 行为清单的 674 条表达式经前后比对一致，刷新文件摘要后重新验证门禁。
- 首轮专项回归的能力清单仅因文件摘要变化失败。首次整套原生检查与专项回归重叠，后者命中模拟网卡资源锁，100% 的既有写参串口用例也超时。125% 的既有 AI 报告交接用例遇到权限错误，新增实时日志用例三档均通过。后续按专项再原生的顺序串行复验，隔离和资源保护沿用原规则。
- 最终串行的 94 项专项回归通过。编译 368 个文件、358 项源码登记、能力覆盖、GUI 守卫、原协议和既有实现保全检查通过。
- 最终标准原生复验退出 0。Windows 私有桌面在 100%、125%、150% 各通过 78 项，共 234 项。每档管理 1,751 个 Qt 窗口，隔离违规为零。新增用例在日志满载后追加 32 批各 20 条记录，保留行数、滚动位置和导出快照符合预期，未调用整篇重建。
- 核对 150% 满载实时日志截图，通道筛选、关闭自动滚动及底部日志可见。三档截图尺寸为 1480×900、1850×1061、1925×1061 像素，较高缩放受私有桌面可用区域约束。
- 自动验证通过后，将本轮 673 份截图、测试日志、结果清单和已由复验覆盖的失败证据移入 Windows 回收站，共约 34.1 MiB。

## 剩余差异

参考图的实时区按表格显示独立时间、级别和信息。当前工作台仍使用原可搜索文本区和统一工具条。短时突发测试覆盖文档更新、原始文件完整性和显示上限。磁盘长时写入、整机 CPU/内存、真实串口并发、真实设备和 24/72 小时长挂继续待验收。整机打包与完整基线留到后续验收。
