# Qt 工作台资源保护、ADB 声明与型号模板

2026-11-22。本批已完成源码与隔离专项验证，**尚未生成包含本批改动的新 EXE 或便携 ZIP**。操作入口见[操作员手册](../../line_check_assistant_README.md)。

## 操作与数据来源

| 功能 | 操作员能核对的内容 |
| --- | --- |
| 资源保护 | 「设备管理」的「资源保护」页列出保护状态、资源类型、原标识、项目名称与 ID，以及 Job 或持有者。活动持有者来自本工作区的实际租约，待核实保护来自持久化记录。同一资源的不同持有者分别列出，同名项目保留各自的 ID。旧记录缺少归属时显示「未记录」。采样时遇到数据库忙会保留上一份快照和采样时间。 |
| PON 与所属 OLT | 新旧资源键均可识别所属 OLT，包括 C300、C600 和 IPv6 主机。资源保护使用实际 OLT 主机身份，以便拦截对同一设备的冲突占用。 |
| 可选 ADB 标识 | 向导为每台 DUT 单独保存、回显大小写敏感的标识。内部使用 `adb:` 加原文 UTF-8 的小写十六进制编码，明细可还原原标识。开关机挂测按冻结的选中通道申请，续跑只申请原失败 DUT 的资源，全业务老化从冻结 DUT 清单申请。保留原项目间互斥、跨进程物理锁和未知结果保护。未声明的旧档案继续沿用原配置与摘要。更换某一 DUT 已声明的标识后，重新核对该 DUT 的环境准备证据。 |
| 型号模板 | 在已保存项目的向导内，由本机操作员从「项目操作」选择「保存为型号模板…」。工作区的 `project_model_presets.json` 按型号和测试类型保存模板，型号比较忽略大小写，同键更新后版本递增。仅保存型号、类型、选做准备步骤和该类型的方案。新建向导在「型号模板」中显示版本，点击「应用模板」后可继续编辑或保存草稿。模板版本已被更新、文件损坏或源项目有未保存变更时，向导提示核对。 |

型号模板适用于复用计划。软件版本、项目要求、DUT 身份、串口、网卡、ADB 及其它资源映射均取自本次新建向导的输入。现场准备依据、设备连接状态和任务租约须由对应项目实际取得。侧栏「测试模板」列出已打开项目的保存版，实际套用入口位于新建向导第一页。

## 修改文件

以下路径均相对主源码目录。

| 范围 | 文件 |
| --- | --- |
| 资源查询、归属与展示 | `src/services/workspace_resources.py`、`src/models/qt_device_inventory.py`、`src/services/qt_workspace_adapter.py`、`src/ui/qt/device_inventory_dialog.py` |
| ADB 档案、准备与租约 | `src/models/project_profile.py`、`src/services/project_preparation.py`、`src/services/resource_lease_service.py`、`src/services/capability_jobs.py`、上述工作区服务及共用向导 |
| 型号模板存储与向导 | `src/services/project_model_presets.py`、`src/services/qt_project_wizard_service.py`、上述工作区适配器、`src/ui/qt/project_wizard.py`、`src/ui/qt/project_wizard_controller.py`、`src/ui/qt/project_templates_page.py` |
| 服务及进程测试 | `tests/test_workspace_resource_details.py`、`tests/test_adb_resource_lease.py`、`tests/fixtures/adb_resource_probe.py`、`tests/test_typed_power_admission.py`、`tests/test_service_aging.py`、`tests/test_project_preparation.py`、`tests/test_qt_workspace_adapter.py` |
| 原生交互与验证清单 | `tests/qt_workbench_probe.py`、`tests/qt_project_wizard_probe.py`、`scripts/verify_baseline.py`、`scripts/verify_qt_migration.py` |

## 专项结果

合并后在主源码目录运行 `scripts/run_tests.py`，与资源、向导、准备、持续老化和开关机历史相关的 [44 项服务回归](services.txt)通过（4.712 秒）。开关机总览和详情复用 `src/models/workbench_presentation.py` 的逐 DUT 完成率，`src/ui/qt/test_type_panel.py` 显示详情。在最新任务就是该结束批次时，工作区从原始台账恢复时长与进度。`tests/test_power_run_overview.py` 验证缺回执、不同任务和缺起始时间三种情况。型号模板的本机确认已登记到 `src/services/capability_catalog.py`，机器清单和能力矩阵检查通过。

各行对应各自的源码与验证范围。界面专项均由 `scripts/run_tests.py` 在独立、非输入的 Windows 原生桌面执行，缩放依次为 100%、125%、150%。

| 验证对象与来源 | 实际结果 | 覆盖内容 |
| --- | --- | --- |
| 资源服务独立源码 | 16/16，2.931 秒 | `test_workspace_resource_details`、`test_project_management.WorkspaceResourcesTests` 及工作区适配器原健康与设备清单测试。核对活动所有者、未结案归属、PON 父资源和读取失败时的快照。 |
| ADB 声明与保护独立源码 | 92/92，11.604 秒 | `test_adb_resource_lease`、`test_typed_power_admission`、`test_service_aging`、`test_project_profile_store`、`test_project_preparation`、`test_capabilities` 和 `test_project_management`。第二个 Windows 进程争用同一标识受到拦截，大小写不同的标识可独立取得。持有者进程强制退出后重开，原标识保留保护，现场核实流程解除后可再次取得。 |
| ADB 原生向导独立源码 | 每档 1/1，每档 7 个受管窗口，0 违规 | 在 DUT 表填写区分大小写的标识，保存并恢复向导草稿，核对创建预览及既有准备流程。 |
| 资源明细原生界面与服务联调源码 | 每档 3/3，每档 15 个受管窗口，0 违规 | 资源明细、原设备页及侧栏导航。核对已持有与待核实显示、同名项目、ADB 原标识和现有设备清单。 |
| 型号模板服务专项 | 专用用例 1/1。同一轮另外覆盖 5 项开关机历史，总回执 6/6，2.588 秒 | `test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_model_template_only_shares_versioned_defaults_with_independent_new_projects`，核对保存版本、独立项目和可复用的方案字段。 |
| 型号模板原生界面与服务联调源码 | 每档 3/3，每档 21 个受管窗口，0 违规 | 型号模板提取、版本与草稿应用，现场采集来源及旧档默认值，以及既有向导恢复、建项与准备用例。 |

## 现场核对

在目标实验室按实际接线核对设备标识、网卡、串口及 OLT/PON 归属。用两个独立项目验证同资源冲突、异资源并行和安全停止，现场复核异常退出后实际设备状态，再处理待核实的原记录。ADB 专项使用模拟标识和真实 Windows 进程锁，真实桥接、ADB 设备在线性和物理输出仍需现场证据。

选择一个实际型号验证开关机和全业务老化两种模板。应用后逐台复核资源映射、目标与采集来源，并按原项目要求完成准备和现场运行。整合源码的完整基线、三档全量原生结果及后续打包由对应交付记录登记。
