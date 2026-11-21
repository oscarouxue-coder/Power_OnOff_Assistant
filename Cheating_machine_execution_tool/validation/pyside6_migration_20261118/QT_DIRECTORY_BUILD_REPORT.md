# Phase 8｜Windows Qt 目录包

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

## 审计与改动

原标准构建是 Tk 单文件配置。Qt 源码启动要求指定模式，工作区模板路径来自源码目录。目录包新增双击进入实际工作台的路径，并把可写便携目录和 PyInstaller 资源目录分别解析。便携目录里的脱敏 INI 作为新项目模板，原工作区标识、数据目录和单实例转发继续使用现有服务。

标准入口 `build_line_check_assistant.ps1 -Gui Qt` 创建独立 CPython 3.9.10 x64 目录环境，使用原 `requirements-build.txt` 及带 SHA256 的 `requirements-qt.txt`。Qt 目录包采用 PyInstaller 5.10.1，排除项及 UPX 设置沿用标准构建。Qt 默认创建独立的构建和输出子目录。原 Tk 构建仍可使用原命令。

Qt 应用以 V1.3.0 迁移验证版标识。验包检查 EXE 的 GUI 子系统、x64、版本资源、图标、Qt 入口与启动钩子、打包后的业务模块、Windows 平台插件、Qt DLL、许可文本、脱敏模板、确认案例快照及 ZIP 内容和校验值。

Qt 许可资料保存在包内 `qt_licenses`。GPL 和 LGPL 文本取自 [Qt Base 6.8.3 源码标签](https://github.com/qt/qtbase/tree/v6.8.3/LICENSES)，两组 wheel 自带的许可记录一并保留。公开分发前仍需按实际 DLL 和插件确认完整的第三方资料和分发条件。[Qt for Python 许可说明](https://doc.qt.io/qtforpython-6.8/licenses.html)

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 标准构建和检查 | `build_line_check_assistant.ps1`、`scripts/prepare_build_environment.ps1`、`check_build_environment.py`、`verify_baseline.py`、`verify_slim_package.py` |
| Qt 启动 | `run_dutpilot_qt.py`、`src/ui/qt/application.py` |
| 构建定义与资源 | `line_check_assistant/packaging_specs/DUTPilotQt.spec`、`packaging_assets/QT_VERSION_INFO.txt`、`QT_PE_VERSION.txt`、`qt_licenses/` |
| 检查与交接 | `tests/test_qt_migration_contract.py`、`tests/qt_workbench_probe.py`、`scripts/capability_gui_actions.json`、根目录状态、开发日志、基线和 README、操作员说明、第三方声明、本报告和迁移进度表 |

## 验证

- 在锁定的 Qt 构建环境中运行 `python scripts/run_tests.py test_ai_case_store.CasePackageTests test_portable_release test_qt_migration_contract -v`，16 项通过。覆盖原 Tk 构建约束、确认案例归档、Qt 双击参数路径、脱敏配置和标准环境检查。
- 首次由构建脚本以 Python 隔离模式调用基线时找不到同目录检查模块。明确从基线脚本目录加载后，第二次门禁执行了 3,185 项，其中 Tk 旧案例核查的错误提示用例失败。已恢复原提示并通过定向回归。首次构建日志 · 第二次构建日志
- 第三次标准构建完成锁定环境检查和全部基线。3,185 项测试执行，命中全部 239 项要求用例，编译 338 份文件，登记 328 份源码。随后 PyInstaller 冻结目录、写入六份脱敏模板。初次 `Compress-Archive` 在打开 `base_library.zip` 时被文件占用拦下。标准脚本的 Qt 配置改用 Python ZIP 实现，本次从同一目录补齐归档。最终静态验包退出 0。第三次构建日志 · 归档续验
- 对三个 Qt Python 扩展、三个 Qt 核心 DLL 和 `qwindows.dll` 的 x64 类型及静态导入表单独检查。本机 Windows 系统和包内 DLL 可解释全部常规依赖。API-set 别名按 Windows 系统组件记录。PyInstaller 日志还记录了两个非工作台所需的可选 Qt 插件所缺的 PDF 和虚拟键盘附加组件。PE 依赖检查
- 项目规定只静态检查新 EXE。原生窗口截图使用 Qt 源码及 Windows 私有桌面验证。
- 从实际 Qt 构建环境执行 `scripts/verify_qt_migration.py`，100%、125%、150% 各通过 60 项，隔离违规为零。总览沿用迁移期间的真实项目状态和卡片布局。验证用临时工作区中的两个项目显示为空闲。改造前总览 · 本轮 150% 源码窗口 · 三档证据

## 产物

| 文件 | 结果 |
| --- | --- |
| [DUTPilot_portable.zip](../../dist/qt-20261120-093334-06af70ca/DUTPilot_portable.zip) | 55,087,114 字节。ZIP CRC 通过，247 个文件与便携目录逐项一致 |
| [ZIP SHA256](../../dist/qt-20261120-093334-06af70ca/DUTPilot_portable.zip.sha256.txt) | `e55758a0e62a3739b13ae1e1d8498ed6e5523544b99b161addee3e886f59a384` |
| [目录内 DUTPilot.exe](../../dist/qt-20261120-093334-06af70ca/DUTPilot_portable/DUTPilot.exe) | 16,996,276 字节。x64 GUI，产品版本 1.3.0，图标资源通过 |
| [PACKAGING_REPORT.json](../../dist/qt-20261120-093334-06af70ca/PACKAGING_REPORT.json) | Qt 插件、Python 模块、归档及依赖版本证据 |

Qt GUI 迁移仍继续推进。验证包面向异机验证，现场及长期挂测的验收范围继续见迁移进度表。
