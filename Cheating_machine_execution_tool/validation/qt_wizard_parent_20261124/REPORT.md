# Qt 新建项目的保存位置离线复验

2026-11-24，在 Windows 原生 Qt 向导验证「保存到」及最终路径。已有父目录可以包含其他项目。自动开关机使用 `项目名_开关机挂测`，持续型全业务老化使用 `项目名_全业务老化`。名称、类型及父目录变更会即时更新可复制的完整预览，确认页再显示一次目标路径。

点击「创建项目」后，工作区按同一规则重新验证路径，沿用现有项目档案与初始版本保存流程。Windows 把已经准备好的目录移动到最终位置，移动操作遇到任何同名目标都会失败。已存在的空目录、非空目录及在提交末段抢先创建的目录都保留原样。选择不存在的父目录时，提示重新选择已有位置。

旧草稿保留原有项目配置，清空原路径输入并提示重新选择父目录。取消和保存草稿均不创建项目。旧项目打开、导入及原 `create_typed` 直接入口继续接受原有目录规则。

## 截图与验证

两张截图取自 Windows 非输入私有桌面上的真实 Qt 新建向导，数据均为离线模拟。Qt 缩放 100%，截图各为 810 × 560 像素。[开关机路径预览](preview-power_cycle-1.png) · [全业务老化路径预览](preview-service_aging-1.png)

| 检查 | 结果 |
| --- | --- |
| Windows Qt 100% | [12 项通过](tests-1.txt) |
| Windows Qt 125% | [12 项通过](tests-1.25.txt) |
| Windows Qt 150% | [12 项通过](tests-1.5.txt) |
| 原工作区服务接口离线回归 | [3 项通过](tests-service.txt) |

使用锁定 Qt 环境、`run_gui_child(framework='qt', native_render=True)` 与 `scripts/run_tests.py`。测试窗口隔离违规及现场连接尝试均为零。覆盖两类项目、中文与空格父目录、原有兄弟目录、预览随名称和类型更新、确认前无产物、空和非空冲突、Windows 保留名、越界和超长名称、末段并发抢占、取消、旧草稿、原有打开与导入入口。[结果与隔离证据](results.json)

10 个改动的 Python 文件局部编译通过，GUI 能力清单复核及差异格式检查通过。本轮未运行完整基线或打包，现场设备与原故障待核对。

## 修改文件

- `src/models/project.py` 提供路径预览和创建共用的命名校验。
- `src/services/project_store.py` 为新向导增加独立的父目录创建入口，保护已存在目标。
- `src/services/project_wizard_draft.py` 接收旧草稿与显式父目录草稿。
- `src/services/qt_project_wizard_service.py`、`src/services/qt_workspace_adapter.py` 接入独立创建请求和原回执流程。
- `src/ui/qt/project_wizard.py`、`src/ui/qt/project_wizard_controller.py` 增加保存位置、实时预览及旧草稿提示。
- `tests/qt_project_wizard_probe.py`、`tests/qt_workbench_probe.py`、`scripts/verify_qt_migration.py` 更新 Qt 专项及迁移验证用例清单。
- `scripts/capability_gui_actions.json`、根目录 `CAPABILITY_COVERAGE.md` 同步界面绑定。
- `line_check_assistant_README.md`、根目录 `DEVELOPMENT_LOG.md` 记录操作方式与验证结果。
