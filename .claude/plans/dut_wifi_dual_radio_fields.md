# DUT WiFi双频合一独立射频参数

## 目标

- 2.4G或5G WiFi页勾选“启用双频合一”后，在同一页显示当前频段和另一频段两套独立射频参数。
- 2.4G与5G的信道、信道带宽、协议类型分别使用各自DUT能力和独立输入；发射功率作为公共参数，同时写入两个Radio。
- 未勾选双频合一时保持原行为：只显示并修改当前Tab对应Radio。

## 分层

- `src/models/dut_config_models.py`：为WiFi设置增加另一频段Radio状态、输入和能力快照。
- `src/core/dut_wifi_config.py`：双频查询解析两个Mapping/Radio；双频配置分别写入两个Radio并回读校验，公共功率写入两边。
- `src/services/dut_advanced_config_service.py`：分别校验两套信道、带宽、协议能力，并校验公共功率同时受两个Radio支持。
- `src/ui/dut_config_window.py`：双频开启时显示另一频段射频组，按两个Radio能力更新独立下拉；关闭时隐藏另一组。
- `line_check_assistant/app.py`：确认框和警告文案逐频段展示最终射频参数。

## 兼容与安全

- SSID、密码、认证、启用/隐藏、最大接入数和WMM继续作为双频公共参数。
- 只有开启双频合一才要求另一频段Radio参数完整；旧的单频请求、查询和60秒稳定等待时序保持不变。
- 双频查询和配置都必须走各自`X_SDMC_Mapping_2G/5G`解析路径，不假定两个频段实例一致。
- 任一频段能力校验失败时整台DUT在下发前拒绝；回读必须分别核对两个Radio。

## 验证

- 补模型/UI映射、两个Mapping查询、双Radio下发与回读、两套能力预检和界面显隐回归。
- 运行WiFi core、DUT service、DUT状态查询和主程序专项测试。
- 运行`python scripts\verify_baseline.py`与`git diff --check`。
- 同步操作员README、验收基线、项目状态和开发记录；自动化测试不替代Windows桌面及真实双频DUT验收。
