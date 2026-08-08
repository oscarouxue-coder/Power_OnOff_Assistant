# 测试项配置 WiFi 参数完整映射

## 目标

- 将旧“WIFI 连接参数”窗口的全部有效功能映射到新工具“测试项配置 → WiFi”Tab。
- 所有字段持久化到当前测试方案 `test_project_config.ini [connect_wifi]`，并由全流程子任务7的无 GUI 旧业务真实读取。

## 字段映射

| 新工具字段 | 配置键 | 旧业务属性 |
| --- | --- | --- |
| 连接 WiFi（主控） | `enable` | `connect_wifi_enable_status` |
| 测试 2.4G WiFi | `test_2g_enable` | `choose_test_2g_flag` |
| 测试 5G WiFi | `test_5g_enable` | `choose_test_5g_flag` |
| ONU 方案类型 | `product_solution` | `Onu_solution_type` |
| 认证方式 | `auth_mode` | `connect_wifi_auth_mode` |
| 加密算法 | `cipher` | `connect_wifi_ciper` |
| 指定无线网卡 | `choose_wireless_card` | `choose_wireless_card_flag` |
| 无线网卡 | `wireless_card_name` | `choose_wireless_card_name` |

## 分层

- `line_check_assistant/test_item_config_store.py`：扩展配置模型及向后兼容读写。
- `src/core/wifi_interfaces.py`：提供无线网卡名称枚举能力。
- `line_check_assistant/app.py`：构建中文 WiFi Tab、刷新网卡、捕获和重载字段。
- `src/services/legacy_power_test_service.py`：将配置映射到无 GUI 旧业务请求和 `HeadlessOnuConfig`。

## 兼容边界

- 老配置缺新键时：2.4G/5G 默认启用，认证默认 `WPA2-PSK`，加密默认 `AES`，默认不指定网卡。
- 主控关闭时不执行 WiFi 连接测试；子选项保留，供下次重新启用。
- 勾选指定网卡但名称为空或运行电脑不存在该网卡时，启动前明确失败，不静默回退其它网卡。

## 验证

- 配置 store、无线网卡枚举、旧业务适配和主界面专项单测。
- `python scripts/verify_baseline.py`
- `git diff --check`

## 完成状态

- 已完成 8 项配置、WiFi Tab、无线网卡刷新和无 GUI 旧业务映射。
- 完整基线通过：43 个源码文件编译、492 项单元测试、35 个强制基线测试。
