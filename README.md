# Power OnOff Assistant

这是面向光猫 / 路由器测试工程师的 Windows 桌面工具仓库。当前主程序为 `LineCheckAssistant`，用于环境线路检查、程控电源、串口日志、样机升级、批量写参、ONU 注册和测试项执行。

## 从这里开始

- 主源码与运行目录：`Cheating_machine_execution_tool/`
- 源码入口：`Cheating_machine_execution_tool/run_line_check_assistant.py`
- 运行：进入主源码目录后执行 `python run_line_check_assistant.py`
- 回归门禁：进入主源码目录后执行 `python scripts/verify_baseline.py`

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


