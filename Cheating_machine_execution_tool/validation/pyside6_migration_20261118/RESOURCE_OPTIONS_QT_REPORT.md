# Phase 3｜Qt 通道的串口和网卡候选

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

后续已接入[主工具栏刷新](HOST_INVENTORY_QT_REPORT.md)。本报告保留上一轮通道窗口及完整基线的验证记录。

## 审计与改动

原 Tk 根据程控电源 COM 选择网卡与样机串口分组。Qt 之前把本机枚举结果直接填入每行，不能按电源分组，且单项枚举失败时会丢掉之前的候选清单。原分组函数已移入独立模块，原入口继续导入原名字。审计脚本从 Phase 0 备份核对提取内容，并比较移除这次提取差异后的原 Tk 入口。

- 程控电源候选默认留空或选 COM101–106。COM1–6 仍能作为对应分组的兼容输入。已知分组匹配实际识别到的 VLAN 和对应八个样机 COM。电源为空时显示所有识别网卡；未知电源编号保留全部 VLAN。这两种情况下的标准样机候选均为 COM1–48。
- 勾选「显示所有网卡和串口」后使用本机识别结果，网卡按原规则去重，串口按原枚举规则编号排序。显示模式仅在本次窗口内有效。打开窗口、开启全量和点击「刷新串口/网卡」均通过原 Qt 项目后台队列读取。刷新期间表单可编辑；失败的来源保留上一次成功清单，成功返回空列表时清空候选。迟到结果只更新发出请求的窗口。
- 当前字段、勾选状态和未保存内容在刷新、切换或改变电源候选时保留。实际字段修改继续走原通道配置预览和保存，配置、版本、设备指令及任务时序不受候选刷新影响。
- 缩放截图发现通道行反复重排会短暂压缩输入框。行布局现在只在宽窄模式切换时重排，原生探针检查窄窗字段完整、底部按钮可见及横向滚动条范围为零。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 共享规则与 Tk 入口 | `src/models/channel_resource_options.py`、`line_check_assistant/app.py` |
| Qt 界面与服务 | `src/ui/qt/channel_configuration_dialog.py`、`src/ui/qt/workspace_controller.py`、`src/services/qt_channel_configuration.py` |
| 测试与门禁 | `tests/test_qt_channel_configuration.py`、`tests/qt_workbench_probe.py`、`scripts/verify_baseline.py`、`scripts/verify_qt_migration.py`、`scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json`、本目录 `verify_phase3.py` |
| 状态和操作说明 | `line_check_assistant_README.md`、根目录 `PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`ACCEPTANCE_BASELINE.md`、`CAPABILITY_COVERAGE.md`、`.claude/plans/pyside6-migration.md`、本目录阶段索引与报告 |

## 运行截图与参考图差异

| 同尺寸 620×500，150% 缩放 | 运行截图 |
| --- | --- |
| 改前 | 旧通道表单 |
| 初次复验 | 窄窗切换时的字段裁切 |
| 改后 | 分组 · 全量 |

截图使用 Windows 私有桌面和临时项目。参考稿侧重详情页的配置摘要，本阶段的编辑控件集中在独立窗口。缩小窗口后通道行自动换行并纵向滚动，顶部公共输入和底部操作保持可见。网卡候选延续 Qt 的按名称显示及带超时的身份查询，Tk 的网卡状态后缀和旧枚举回退路径仍在原入口。

## 验证与剩余工作

- `python scripts/run_tests.py test_resource_options test_app test_qt_channel_configuration test_channel_config test_adapter_rename -v` 通过 300 项。包含原 Tk 分组、枚举表现与网卡改名回归，以及 Qt 成功空列表、部分失败留存、配置或版本未动等断言。
- 源码、编译、能力覆盖和协议检查通过，编译 328 份文件，其中文件清单覆盖 318 份源码。
- 当前 Windows 主机通过 Qt 通道后台入口只读枚举出了 70 个网卡和 55 个串口。使用临时项目验证了配置文件和项目版本保持原值，打开串口、执行改名和启动任务的次数均为零。本机只读证据
- 初次 150% Windows 原生专项通过 4 项。最终执行 `python scripts/verify_qt_migration.py --output validation/pyside6_migration_20261118/qt_resource_options_final`，100%、125%、150% 各通过 53 项，共 159 项，隔离违规为 0。最终原生结果
- 首次全量验证在窄窗布局修改后读到了旧的 GUI 源码快照，能力覆盖预检及同一项覆盖用例失败。审查了布局动作后重新同步快照，`test_capability_coverage` 的 3 项均通过。首轮完整基线记录
- 按原入口重新执行 `python scripts/verify_baseline.py`，最终全部门禁通过。套件运行 3,165 项，239 项指定用例实际执行，编译、协议、能力与 GUI 隔离检查均通过。最终完整基线

物理网卡改名及主工具栏的跨窗口刷新还在迁移范围内。目标电脑配置、Windows 系统 DPI 和多屏交互待现场复验。本轮保持 Tk 默认入口，未执行设备命令或构建 EXE。

### 下一项审计记录

Tk 在选中没有数字尾号的网卡时先恢复当前通道选择，再由 `offer_adapter_rename` 确认目标和新名称。`AdapterRenameService` 在执行前读取 GUID、核对重名，命令后回读同一身份。成功后只同步名称和派生 PC IP，有效的历史 COM 映射保留，已打开的其它项目也会刷新引用。系统已改名而配置保存失败时，旧路径提示人工核对，保留已更新的内存值。

现有 `network.rename` 能力从已配置通道读取原别名，无法直接覆盖 Tk 的「为当前槽位选择一个尚未绑定的网卡」场景。Qt 也尚缺相应的配置同步回调。接入前需验证同名不同 GUID 拒绝、不同项目的草稿不互相覆盖、租约收尾后才允许操作，以及系统已改名但配置写入失败时的未知保护。现有候选刷新依旧是只读入口。

主工具栏当前有禁用的「刷新串口」「刷新网卡」动作。Tk 的组合刷新还会调用 `ProjectWorkspace.refresh_inventory()`；它用独立线程读网卡身份，结果再交给工作区资源登记。Qt 当前从执行预检登记身份。由于 `WorkspaceResources.register_adapter` 在网卡已有租约时会补上身份键，后续应分别验证候选显示、身份登记和活动租约行为。
