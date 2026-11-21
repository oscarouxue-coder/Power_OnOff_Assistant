# 旧配置导入、草稿及多项目隔离复验

2026-11-21 在锁定的 Qt 构建 Python 环境执行 7 个源码服务用例，全部通过，退出码 0。GUI 隔离预检通过，运行时界面窗口数为 0、违规数为 0。测试使用临时目录内的脱敏旧式 INI、项目副本和测试草稿，经过 Qt 工作区后台命令、原 ProjectStore、原配置存储及 Windows 当前用户的 DPAPI。

| 场景 | 本轮实际检查 |
|---|---|
| 旧式配置导入 | 从临时 `Auto_power_on_off_tool/config` 导入。源 INI 字节未变，导入备份字节及清单 SHA256 一致，记录完成；项目无活动任务，关闭再打开的项目 ID 一致 |
| 保存与重开 | Qt 工作区保存项目后配置版本更新、项目 ID 稳定，改名、复制及按清单重开保留各自身份。六页正式保存写入原配置存储，关闭选项的已有值保留 |
| 旧及新页面草稿 | Qt 识别旧 Tk 草稿文件存在，保留原文件字节。在另一份 Qt 草稿中记录未填完的文本后，重建工作区、重开项目能还原输入，正式配置仍为原字节；显式保存后清除对应 Qt 草稿。版本过期的 Qt 草稿提示并保留，确认重载后清除 |
| 项目隔离 | 用原 ProjectStore 创建四个使用同名配置文件的独立项目，各自保存并创建运行快照；随后修改各自草稿，每个快照仍包含原项目值。新项目从脱敏默认值开始 |

在主源码目录复跑：

```powershell
$qtPython = Join-Path $env:LOCALAPPDATA 'LineCheckAssistant/qt-build-py39/Scripts/python.exe'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$cases = @(
    'test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_legacy_import_creates_original_backup_and_leaves_source_intact'
    'test_qt_workspace_adapter.QtWorkspaceAdapterTests.test_original_project_lifecycle_preserves_values_and_identity'
    'test_qt_configuration_service.QtConfigurationTests.test_encrypted_recovery_survives_workspace_restart_and_explicit_save_clears_it'
    'test_qt_configuration_service.QtConfigurationTests.test_stale_recovery_is_preserved_until_explicit_reload'
    'test_qt_configuration_service.QtConfigurationTests.test_six_domains_save_through_original_stores_and_commit_project_revision'
    'test_project_management.ProjectManagementTests.test_four_projects_same_filename_save_and_snapshot_are_isolated'
    'test_project_management.ProjectManagementTests.test_new_project_uses_sanitized_defaults_not_local_bindings'
)
& $qtPython -X utf8 scripts/run_tests.py @cases -v
```

本批全部执行用例通过。旧 Tk 草稿的字段按原 Tk 控件位置恢复，本批验证的是 Qt 对文件的识别和字节保全。目标机真实旧项目、跨 Windows 用户的加密草稿处理及已打包程序上的交互仍待现场。现场使用副本核对保存前后的配置和版本，并留存原项目。
