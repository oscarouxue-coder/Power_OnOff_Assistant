# DUTPilot

这是面向光猫 / 路由器测试工程师的 Windows 桌面工具仓库。当前主程序为 `DUTPilot`，用于环境线路检查、程控电源、串口日志、样机升级、批量写参、ONU 注册和测试项执行。

## 产品名称与旧版升级

2026-11-17起，产品名称统一为 **DUTPilot**，窗口标题显示名称和版本号。后续标准构建交付`DUTPilot.exe`及`DUTPilot_portable.zip`，发布附件仍仅为完整ZIP和对应`.sha256.txt`。本次仅改源码和构建规则，V1.2.10版本号及现有线上发布保持。

旧版更新客户端无法识别新附件名，首次升级须从现有GitHub Releases页面手动下载完整ZIP；新版客户端兼容新旧附件名。换版前退出程序并备份旧目录、配置及独立项目，完整解压新包，按[操作员说明](Cheating_machine_execution_tool/line_check_assistant_README.md)恢复或导入配置、打开原项目。构建脚本、`LineCheckAssistant` 本机数据目录和构建环境路径继续沿用。

## 从这里开始

- 用 VS Code 打开本仓库根目录，按 **Ctrl+F5** 启动当前 PySide6 源码工作台。如果运行面板此前选过其他配置，先选择 **DUTPilot V1.3.0 · PySide6 工作台**。该配置使用独立的 `qt-dev-py39` 环境并传入 `--workspace`。[启动配置](.vscode/launch.json)

- Qt 后续开发遵循[统一 GUI 设计规范](GUI_DESIGN_GUIDELINES.md)。V1.3.0 迁移交接条件、两份指导书的业务口径和 V1.3.x 增量清单见[升级执行记录](docs/GUI_UPGRADE_EXECUTION_PLAN.md)。

- Qt 运行概览已接入失败轮次续跑，右键选择符合原条件的通道，从未完成轮次继续。[续跑阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/RESUME_QT_REPORT.md)

- Qt「测试项配置 → 消息推送」已接入本机确认后的钉钉/飞书试发，使用当前推送草稿及已保存项目名。[消息试发阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PUSH_TRIAL_QT_REPORT.md)

- Qt「测试项配置 → 项目信息」已接入单通道样机版本查询，使用当前 Telnet 草稿，在手填版本基准下方显示只读回读结果。[版本查询阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/VERSION_QUERY_QT_REPORT.md)

- Qt「测试项配置 → 测试项」已接入单次预备测试，使用当前草稿和已选通道，确认后经原服务执行并支持安全停止。[预备测试阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PRETEST_QT_REPORT.md)

- Qt 项目详情的「全流程…」已接入串口日志预启动、环境线路检查与开关机测试。三项默认均不勾选，确认后执行原任务，可从项目详情请求安全停止。[全流程阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PIPELINE_QT_REPORT.md)

- Qt ONU 已接入 C300/C600 配置、查询、目标与业务设置、只读命令预览、注册、当前 PON 批量删除、注册后独立保存 OLT 启动配置，以及 C300 单台注册的可选离线清理重试。[ONU 查询报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/ONU_QUERY_REPORT.md) [ONU 注册报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/ONU_REGISTRATION_REPORT.md) [ONU 管理报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/ONU_MANAGEMENT_REPORT.md) [OLT 保存报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/ONU_SAVE_REPORT.md) [C300 清理报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/ONU_CLEANUP_REPORT.md)
- Qt 写样机参数已接入参数表生成、导入、预检、确认、批量执行与停止。走串口时自动打开只读日志。[写参阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PARAMETER_WRITER_REPORT.md) [串口观察报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PARAMETER_OBSERVATION_REPORT.md)
- Qt 样机升级已接入原页面升级和三种全包升级。无程控电源时，本机操作员确认已手动重启后继续。全包升级期间可查看自动打开的只读串口日志。[样机升级阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/FIRMWARE_REPORT.md) [升级日志阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/FIRMWARE_OBSERVATION_REPORT.md) [手动重启报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/FIRMWARE_MANUAL_REPORT.md)

- Qt 已接入 DUT 的 Telnet、WAN、2.4G/5G WiFi、语音和 TR069 六页。DUT 阶段完整基线 3,093 项通过，三档 Windows 原生 105 项通过。旧项目导入和后续显示修正见对应检查记录。[DUT 阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/VOICE_TR069_REPORT.md) · [后续报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/QT_FOLLOWUP_REPORT.md)

- Qt WiFi阶段：2.4G/5G 已接入原受控服务并完成三档稳定布局截图。测试与操作边界见[WiFi阶段报告](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/WIFI_REPORT.md)。

- 完整迁移目标逐项进度及缺少的验收证据见[迁移进度表](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/MIGRATION_PROGRESS.md)，不会把已完成增量算作整份计划完成。

- PySide6迁移：独立工作台、真实项目基础管理、原开关机控制链、六标签配置编辑、通道选择/绑定/矩阵与列表及基本串口终端已接入，整体迁移/设备复验及其它业务页面仍待完成。最新[串口终端与截图](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/SERIAL_REPORT.md)、[通道配置](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/CHANNELS_REPORT.md)、[配置编辑](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/CONFIGURATION_REPORT.md)、[开关机接入](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PHASE3_REPORT.md)、[工作台原型](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PHASE1_2_REPORT.md)、[初始审计](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/PHASE0_AUDIT.md)及[代码计划](.claude/plans/pyside6-migration.md)分别记录分阶段交付和未完成范围。

- 多项目主程序验收：在主源码目录执行 `python run_dutpilot_qt.py`，通过项目菜单新建或打开验收项目。操作及现场记录见[验收清单](Cheating_machine_execution_tool/validation/multi_project_completion_20261117/ACCEPTANCE_CHECKLIST.md)。自动化结果不代替可见Windows或真实设备验收。

- 单实例多项目入口：启动源码后使用可收起项目侧栏或“项目”菜单，新建/打开/保存独立项目；旧目录通过“导入旧配置目录”迁入，操作见主源码操作员说明。本轮源码改造的验证和待验收边界见`PROJECT_STATUS.md`及`ACCEPTANCE_BASELINE.md §2.18`。

- 主源码与运行目录：`Cheating_machine_execution_tool/`
- Qt 源码入口：`Cheating_machine_execution_tool/run_dutpilot_qt.py`
- 进入主源码目录执行 `python run_dutpilot_qt.py`。如需打开指定项目，执行 `python run_dutpilot_qt.py "项目目录/project.linecheck.json"`。旧脚本 `run_line_check_assistant.py` 已移除，快捷方式、批处理和计划任务改用 `run_dutpilot_qt.py`，原启动参数可沿用。
- 日常修改默认只运行相关检查：按影响范围执行必要的局部编译、相关专项测试及差异检查；纯文档只检查内容一致性、链接和差异格式，不运行代码测试。
- 完整基线：仅在用户明确要求、提交代码前、标准打包（包括 `-CheckOnly`）或已验收功能结构调整时，进入主源码目录执行 `python scripts/verify_baseline.py`。局部行为或显示修改不因涉及已验收功能自动触发完整基线，原复验要求仍保留；详细规则见 [AGENTS.md](AGENTS.md) 和 [开发工作流 §5](.claude/skills/line-check-dev/SKILL.md#5-验证范围与完整基线触发条件)。

## 开发测试与窗口隔离

源码环境：在主源码目录执行`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_qt_environment.ps1 -WithBusinessDependencies`，使用输出的独立Python运行`run_dutpilot_qt.py --demo`查看明确演示数据，或`run_dutpilot_qt.py --workspace [原项目路径]`操作真实项目。真实项目的开关机/环境检查须明确确认，配置编辑与任务互斥，其它未迁移按钮禁用。原项目格式、配置值和运行记录沿用，实际设备验收尚未完成。源码运行说明见[操作员说明](Cheating_machine_execution_tool/line_check_assistant_README.md)。

Qt 迁移专项从主源码目录运行 `python scripts/verify_qt_migration.py --output validation/本次Qt验证目录`，可用 `--python` 指定安装了锁定依赖的解释器。100%、125%、150% 三档原生用例要求完整的私有桌面证据。Qt 私有桌面测试拒绝导入 Tk，旧回归继续使用 Tk 隔离守卫。实际 Windows 系统缩放及实体多屏按现场范围核对。[Tk 退役核对](docs/TK_RETIREMENT_AUDIT.md)

含设备任务的模拟专项仍使用原主机资源锁；Qt原生专项与相关服务回归请依次执行，避免两套测试同时占用相同模拟COM/VLAN。资源冲突必须按失败处理，不绕过保护。

自动化测试统一从主源码目录使用带离屏预检的入口；先检查整个测试目录，再导入并执行指定测试。新增真实 GUI 测试遗漏保护、无法确认的窗口入口或运行时违规都会返回非零，不能靠捕获异常、登记名称或跳过测试变成通过。

```powershell
cd .\Cheating_machine_execution_tool
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
python scripts/run_tests.py discover -s tests -v
python scripts/run_tests.py test_ai_workspace -v
python scripts/run_tests.py test_gui_test_coverage.GuiCoverageTests.test_missing_fixture_and_import_only_fail -v
python scripts/verify_gui_test_coverage.py
```

VS Code 使用“终端 → 运行任务”中的 **DUTPilot: 测试（离屏预检）** 或 **DUTPilot: 指定测试（离屏预检）**；后者输入模块、类或方法 ID，使用当前选择的 Python 解释器。测试资源管理器直接调用旧 unittest 命令不属于强制预检入口。已有测试保留自身离屏保护，旧命令不提供运行前门禁保证。

真实 Tk 测试在首次创建窗口前调用 `install_offscreen_windows(self)`，或将创建过程放在 `with OffscreenTkWindows():` 内。共享 GUI 辅助函数可用 `@requires_offscreen` 声明并检查调用方作用域；测试子进程使用 `run_gui_child(..., timeout=...)` 返回独立隔离证据。工具均来自 `tests/tk_test_windows.py`，禁止由产品代码导入。纯 Mock、`Tcl()` 和 `Tk(useTk=False)` 不需创建窗口作用域；真实原生确认/文件对话框须由测试明确模拟回答。

窗口默认保持真实映射并移出全部显示器范围。Windows 原生像素专项使用 `run_gui_child(..., native_render=True)` 创建一次性私有桌面，子进程在导入 GUI 前绑定，并由系统 API 核验其不是输入桌面；不切换用户桌面。创建/绑定/身份核验失败即失败，不回退到用户桌面或跳过像素断言。此适配用于保留原有 GetDC/GetPixel 渲染检查。

完整基线增加第八类 `gui_test_coverage` 门禁，覆盖失败时不启动测试；原有触发条件和七类检查保持。专项测试通过不代表完整基线、Windows 人工目视或真实设备验收通过。

## 跨电脑配置 Git 提交检查

提交检查统一使用 **CPython 3.9.10 x64**，安装目录可以不同，不必修改系统默认 Python。首次在仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Cheating_machine_execution_tool\scripts\install_git_hooks.ps1
```

钩子依次寻找：本仓库 `linecheck.pythonExecutable` 配置 → 已激活虚拟环境 → 仓库根目录的 `.venv` → 主源码目录的 `.venv` → `%LOCALAPPDATA%\LineCheckAssistant\build-env-py39` → `py -3.9` → PATH 中的 `python`、`python3`。已有虚拟环境无需先激活；自动搜索会跳过 Windows Store 占位入口、无法执行或版本/位数不符的候选。

非标准位置或其它名称的已有环境，可单独指定（换成该电脑的实际路径）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Cheating_machine_execution_tool\scripts\install_git_hooks.ps1 -PythonExecutable "C:\my-project-env\Scripts\python.exe"
```

脚本先验证解释器，再将绝对路径写入本仓库 `.git/config`，不会把本机路径提交到源码，也不会影响其它仓库。不带参数重新安装钩子会保留已有配置；指定路径失效或版本不符时会阻止提交并提示修正，不会悄悄换用其它环境。恢复自动识别：

```powershell
git config --local --unset linecheck.pythonExecutable
```

提交时显示实际 Python 路径、版本与位数，进入主源码目录执行原有完整基线；检查失败保留原始输出和退出码，阻止提交。钩子进程内使用 UTF-8，并将已有 TMPDIR/TEMP/TMP 的 Windows 短路径规范化为完整路径，避免临时工作目录文本比较不一致，不修改系统设置。也可以在仓库根目录直接验证入口，不创建提交：

```powershell
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\Cheating_machine_execution_tool\scripts\run_git_pre_commit.ps1
```

出现 `Python was not found` 通常是系统命中了 Microsoft Store 占位入口。新入口会明确指出缺少可用的 CPython 3.9.10 x64，并给出指定路径的方法；不会自动安装 Python 或下载依赖。新电脑仍需先安装对应 Python 和项目依赖；需要标准锁定环境时按下节的 `-CheckOnly` 流程准备。若解释器已找到但缺依赖，应修复所选环境后重试，不能跳过提交检查。修改 PATH 后需重启编辑器，使其读取新环境；使用本仓库显式路径配置则不依赖 Python 的 PATH 设置。此优化只影响提交检查，打包标准及入口保持下节规定。

## 在另一台 Windows 电脑打包

标准构建使用独立 CPython 3.9.10 x64、PyInstaller 5.10.1 及锁定的业务和 PySide6 依赖。Qt 目录包包含 Windows 平台插件和运行库。

1. 同步完整工程，包括 `requirements-build.txt`、`requirements-qt.txt`、`scripts/`、`tests/fixtures/`、`line_check_assistant/packaging_specs/`和图标/资源；不要复制原电脑的虚拟环境、`build/`或`dist/`。通过Git换电脑时，这些源码改动需先提交/同步；本轮不会自动提交。
2. 安装[Python 3.9.10 Windows 64-bit](https://www.python.org/downloads/release/python-3910/)，保留Tcl/Tk和pip，建议安装`py`启动器。无需把默认Python切换成3.9；脚本优先使用`py -3.9`，再查找PATH中的Python，版本和位数必须准确匹配。
3. 在仓库根目录打开PowerShell，执行：

```powershell
cd .\Cheating_machine_execution_tool
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1
```

脚本首次自动在`%LOCALAPPDATA%\LineCheckAssistant\qt-build-py39`创建独立环境并联网安装锁定依赖；以后复用并检查该环境。每次先检查版本、隔离状态和依赖，再运行完整基线；任一步失败即停止构建，不跳过门禁或回退全局环境。使用脚本相对位置解析工程路径，支持移动目录、换盘符、中文及空格路径。每次输出独立目录，保留旧包及正在运行的旧程序。

如果Python不在PATH且没有`py`启动器，在构建命令末尾加`-BasePython "实际安装目录\python.exe"`。若希望使用另一个独立环境，加`-PythonExecutable "新环境目录\Scripts\python.exe"`，脚本仍会自动准备并严格检查它。环境被装入额外库时会拒绝构建；可指定新的环境目录重新准备，不改全局Python。

只检查环境和完整基线、不生成EXE：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1 -CheckOnly
```

标准脚本默认构建 Qt，显式参数 `-Gui Qt` 仍可使用。`-Gui Tk` 会提示旧构建已退役并退出。每次在 `dist/qt-<构建批次>/` 下生成完整便携目录、ZIP、SHA256 和构建报告。脚本核验 EXE/PYZ、Qt 插件与动态库、ZIP 内容和哈希。交付时将 ZIP 完整解压，在目标电脑上运行 `DUTPilot_portable/DUTPilot.exe`。[Qt 构建与验证](Cheating_machine_execution_tool/validation/pyside6_migration_20261118/QT_DIRECTORY_BUILD_REPORT.md)

当前标准规格为 `DUTPilotQt.spec`。复现 `LineCheckAssistant*.spec` 的历史构建时，请使用对应的历史源码提交。

## GitHub 发布附件

标准构建同时生成全部人工确认案例及修订快照 `CONFIRMED_CASES.json`，包含停用记录，同一份快照随EXE和便携ZIP交付。来源为当前Windows用户的共用案例库及迁入的旧AI/项目库；导出失败阻止构建，空库可生成空快照。包校验核对EXE/ZIP内快照与构建快照一致并记录案例数、修订数及SHA256。目标电脑的AI服务启动后只补充新案例，保留本地修订、停用和删除结果；共用库位置与备份方法见操作员说明。不复制整个AI数据库，GitHub附件仍仅为以下两份。

从2026-11-05确认后的下一次构建/发布开始，GitHub Release只上传同一次构建输出的两个文件：

- `DUTPilot_portable.zip`
- `DUTPilot_portable.zip.sha256.txt`

构建脚本完成后会单独列出这两个待上传路径。本地仍保留完整EXE、便携目录、校验文件和构建报告；版本说明、第三方声明及EXE校验文件随ZIP提供，不再作为独立附件上传。公开发布说明统一指引下载完整ZIP及ZIP校验文件，不再提供单独EXE下载说明。

发布顺序：创建草稿并上传两个附件 → 核对大小/SHA256 → 发布并设为Latest → 匿名完整下载校验两个附件并验证源码更新客户端 → 删除旧Release及附件；Git标签与源码历史保留。更新客户端已支持两附件发布，无需修改接口；构建脚本仍只负责本地构建，不自动上传。V1.2.6及其六份附件、历史发布记录保持原样。

## 文档职责

| 文件 | 只负责什么 | 何时更新 |
| --- | --- | --- |
| `AGENTS.md` | 人与 AI 的硬规则、目录边界、文档更新纪律 | 工作流或硬规则变化时 |
| `PROJECT_STATUS.md` | 当前能力、待办、限制、继续开发入口 | 当前状态或后续入口变化时 |
| `ACCEPTANCE_BASELINE.md` | 不变量、验收状态、真实样机待确认项 | 功能边界或验收结论变化时 |
| `DEVELOPMENT_LOG.md` | 已完成改动的时间顺序记录 | 每次完成代码、测试、文档或构建调整后 |
| `Cheating_machine_execution_tool/line_check_assistant_README.md` | 操作员使用方式与界面可见行为 | 操作步骤、配置项或界面行为变化时 |
| `Cheating_machine_execution_tool/THIRD_PARTY_NOTICES.md` | 当前发布涉及的第三方声明边界 | 依赖、随包组件或发布方式变化时 |

发生功能改动时，实施者先按 `AGENTS.md` 判断需要同步哪些文档；不以 `DEVELOPMENT_LOG.md` 代替当前状态，也不以 `PROJECT_STATUS.md` 代替验收证据。

## 目录边界

- `Cheating_machine_execution_tool/src/`：当前主程序的 core / services / models / ui。
- `Cheating_machine_execution_tool/line_check_assistant/`：Tk 主窗口、配置 store、窗口和页面升级集成。
- `Cheating_machine_execution_tool/tests/`：当前主程序单元测试。
- `Cheating_machine_execution_tool/Auto_power_on_off_tool/`：旧工具源码与当前程序仍使用的本机配置目录；默认不扩展旧工具业务代码。全流程子任务7按项目负责人明确要求，通过新 service 的独立无 GUI 子进程复用旧 `test_case/common/clients` 业务类，但不启动或实例化旧 GUI；其它当前主程序路径继续与旧业务隔离。
- `Cheating_machine_execution_tool/test_boot_upgrade/`、`Page_upgrade/`、`SdmcUbusLib/`：历史实现或协议参考；修改前必须先确认当前主程序是否依赖。

## 本机文件与发布边界

- 按负责人要求，`Cheating_machine_execution_tool/Auto_power_on_off_tool/config/` 下所有配置与源码文件均纳入 Git 跟踪，包括本机配置；后续新增配置可正常加入跟踪，自动生成的 Python 缓存仍按通用规则忽略。
- `build/`、`dist/`、日志和测试结果是生成物，不提交 Git。
- 打包后不得在当前 PC 运行 `dist/DUTPilot.exe`；只确认打包成功并报告输出路径。
- 上述配置按负责人要求原样纳入跟踪；其中的 webhook、密码或其他凭据不要额外复制到文档、日志或提交说明；配置模板化与凭据轮换应作为单独任务处理。

中兴C300： 
GPON ONU类型模板:
SD-41 (4GE,1POTS)
OSCAR_GPON (5GE,2POTS)

DBA带宽模板：
1G：  1G、1000m
100M：100M
50M： 50M



中兴C600：
XGSPON ONU类型模板:
NP7287XGS (4GE,1POTS)
OSCAR_XGS (5GE,2POTS)

GPON ONU类型模板:
TZW-99 

DBA带宽模板：
1G： HGU-1G
10G：WT-10G


