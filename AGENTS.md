# Project Notes

- After rebuilding the latest `dist\LineCheckAssistant.exe`, do not run it on the current PC. Only verify that packaging completed successfully and report the output path to the user.

## 项目背景

这是一个 Windows 桌面应用，用于辅助光猫/路由器测试工程师完成测试环境搭建、设备连通性检查、样机升级、串口日志查看、Ping 检测等工作。

主要用户是网络通信产品软件测试工程师，要求界面简单、操作稳定、日志清晰。

## 技术选型原则

本项目暂不固定具体技术栈。

1. 目标平台：Windows 10/11
2. 交付形式：普通用户可双击运行的桌面应用
3. 主要功能：设备连通性检测、Ping、SSH、Telnet、串口、样机升级、日志查看、测试结果导出
4. 用户特点：非专业开发人员也要能使用
5. 开发要求：易维护、易打包、易调试、适合后续接入 AI Agent
6. 优先考虑：稳定性、开发效率、打包便利性、生态成熟度

在没有得到用户确认前，不要直接创建大规模代码。

## 目录规则

- `src/ui`：只放界面代码
- `src/core`：放 ping、ssh、telnet、串口、升级等底层能力
- `src/services`：放完整业务流程编排
- `src/models`：放数据结构
- `src/utils`：放工具函数
- `config`：放配置文件
- `assets`：放图标和图片
- `logs`：运行日志，不提交 Git
- `tests`：测试代码
- `scripts`：运行和打包脚本

## 开发规则

1. 不要把业务逻辑直接写在 UI 文件里。
2. UI 只负责显示、输入和调用 service。
3. 单个底层能力放到 core。
4. 多步骤流程放到 services。
5. 新增功能时，必须同步更新 `README.md`。
6. 修改代码后，必须说明改了哪些文件。
7. 修改代码后，必须给出验证方法。
8. 不要改动 `build`、`dist`、`logs`、`.venv` 目录。
9. 不要随意删除已有功能。
10. 涉及设备登录、升级、重启等危险操作时，必须加确认提示和日志记录。
