# Power OnOff Assistant

这是面向光猫 / 路由器测试工程师的 Windows 桌面工具仓库。当前主程序为 `LineCheckAssistant`，用于环境线路检查、程控电源、串口日志、样机升级、批量写参、ONU 注册和测试项执行。

## 从这里开始

- 主源码与运行目录：`Cheating_machine_execution_tool/`
- 源码入口：`Cheating_machine_execution_tool/run_line_check_assistant.py`
- 运行：进入主源码目录后执行 `python run_line_check_assistant.py`
- 回归门禁：进入主源码目录后执行 `python scripts/verify_baseline.py`

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
- `Cheating_machine_execution_tool/Auto_power_on_off_tool/`：旧工具源码与当前程序仍使用的本机配置目录；默认不扩展旧工具业务代码，仅在项目负责人明确提出旧工具维护需求时独立修改，且不得让当前主程序重新依赖旧工具。
- `Cheating_machine_execution_tool/test_boot_upgrade/`、`Page_upgrade/`、`SdmcUbusLib/`：历史实现或协议参考；修改前必须先确认当前主程序是否依赖。

## 本机文件与发布边界

- `network_card_ip.ini`、ONU 注册、升级输入等属于本机运行状态，不提交 Git。
- `build/`、`dist/`、日志和测试结果是生成物，不提交 Git。
- 打包后不得在当前 PC 运行 `dist/LineCheckAssistant.exe`；只确认打包成功并报告输出路径。
- 发现 webhook、密码或其他凭据时，不要复制到文档、日志或提交内容；配置模板化与凭据轮换应作为单独任务处理。
