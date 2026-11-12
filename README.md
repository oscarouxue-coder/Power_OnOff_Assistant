# Power OnOff Assistant

这是面向光猫 / 路由器测试工程师的 Windows 桌面工具仓库。当前主程序为 `LineCheckAssistant`，用于环境线路检查、程控电源、串口日志、样机升级、批量写参、ONU 注册和测试项执行。

## 从这里开始

- 主源码与运行目录：`Cheating_machine_execution_tool/`
- 源码入口：`Cheating_machine_execution_tool/run_line_check_assistant.py`
- 运行：进入主源码目录后执行 `python run_line_check_assistant.py`
- 日常修改默认只运行相关检查：按影响范围执行必要的局部编译、相关专项测试及差异检查；纯文档只检查内容一致性、链接和差异格式，不运行代码测试。
- 完整基线：仅在用户明确要求、提交代码前、标准打包（包括 `-CheckOnly`）或已验收功能结构调整时，进入主源码目录执行 `python scripts/verify_baseline.py`。局部行为或显示修改不因涉及已验收功能自动触发完整基线，原复验要求仍保留；详细规则见 [AGENTS.md](AGENTS.md) 和 [开发工作流 §5](.claude/skills/line-check-dev/SKILL.md#5-验证范围与完整基线触发条件)。

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

项目统一采用已由负责人确认异机正常运行的精简方式：独立CPython **3.9.10 x64**、固定`requirements-build.txt`依赖和PyInstaller **5.10.1**，排除NumPy/OpenBLAS、lxml、PyQt5，禁用外部UPX。17.23MiB是当前版本结果，后续体积可随功能变化。

1. 同步完整工程，包括`requirements-build.txt`、`scripts/`、`tests/fixtures/`、`line_check_assistant/packaging_specs/`和图标/资源；不要复制原电脑的虚拟环境、`build/`或`dist/`。通过Git换电脑时，这些源码改动需先提交/同步；本轮不会自动提交。
2. 安装[Python 3.9.10 Windows 64-bit](https://www.python.org/downloads/release/python-3910/)，保留Tcl/Tk和pip，建议安装`py`启动器。无需把默认Python切换成3.9；脚本优先使用`py -3.9`，再查找PATH中的Python，版本和位数必须准确匹配。
3. 在仓库根目录打开PowerShell，执行：

```powershell
cd .\Cheating_machine_execution_tool
$buildId = Get-Date -Format yyyyMMdd_HHmmss
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1 -OutputDirectory "dist\slim_$buildId" -WorkDirectory "build\slim_$buildId"
```

脚本首次自动在`%LOCALAPPDATA%\LineCheckAssistant\build-env-py39`创建独立环境并联网安装锁定依赖；以后复用并检查该环境。每次先检查版本、隔离状态和依赖，再运行完整基线；任一步失败即停止构建，不跳过门禁或回退全局环境。使用脚本相对位置解析工程路径，支持移动目录、换盘符、中文及空格路径。每次输出独立目录，保留旧包及正在运行的旧程序。

如果Python不在PATH且没有`py`启动器，在构建命令末尾加`-BasePython "实际安装目录\python.exe"`。若希望使用另一个独立环境，加`-PythonExecutable "新环境目录\Scripts\python.exe"`，脚本仍会自动准备并严格检查它。环境被装入额外库时会拒绝构建；可指定新的环境目录重新准备，不改全局Python。

只检查环境和完整基线、不生成EXE：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1 -CheckOnly
```

构建输出包括`LineCheckAssistant.exe`、完整便携ZIP、SHA256、版本/构建说明、第三方声明和`PACKAGING_REPORT.json`。构建后校验实际EXE/PYZ关键模块、原生依赖、Tcl/Tk四份布局、排除项、ZIP CRC和哈希。不要在打包电脑启动新EXE；交付到目标电脑按该版本变更范围复验。**统一入口是PowerShell脚本，不直接调用全局`pyinstaller`或单独执行spec来代替完整流程。**

## GitHub 发布附件

从2026-11-05确认后的下一次构建/发布开始，GitHub Release只上传同一次构建输出的两个文件：

- `LineCheckAssistant_portable.zip`
- `LineCheckAssistant_portable.zip.sha256.txt`

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
- 打包后不得在当前 PC 运行 `dist/LineCheckAssistant.exe`；只确认打包成功并报告输出路径。
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


