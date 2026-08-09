# DUT 2.4G / 5G WiFi 配置 Tab 实施计划

## 目标

- 在 DUT 配置窗口增加“2.4G WiFi配置”和“5G WiFi配置”两个独立 Tab。
- 支持批量查询、表单同步和配置：SSID、密码、信道、带宽、双频合一、启用、隐藏、认证模式、无线协议、发射功率、最大接入数、WMM、SSID 索引。
- 复用现有目标、网卡按需准备、锁源 UBUS、1–8 并行、停止、失败隔离和设备 Session 注销边界。

## 分层方案

1. `models`：增加 WiFi 配置/状态模型，并接入高级配置和查询结果联合类型。
2. `core`：新增 WiFi UBUS 协议切片；读取厂商 Mapping，解析实际 Radio/AP/SSID 实例，执行只读查询、多路径 set 和回读校验。
3. `services`：增加 WiFi 字段校验；将两个频段接入现有批量配置与状态查询编排。
4. `ui/app`：增加两个 Tab、字段联动、当前状态、查询/执行入口、确认提示和日志标签。
5. `tests/gate`：覆盖路径映射、查询、下发、双频合一、校验、表单映射、入口与强制基线。
6. `docs`：更新操作员说明、当前状态、验收边界和开发日志。

## 协议与交互约束

- 双频合一写入 `Device.WiFi.X_SDMC_DualBandEnable` 的当前 SSID 索引位置；开启时同一 SSID/启用/隐藏/认证/密码/AP 参数同步到 2.4G 和 5G，Radio 的信道、带宽、协议和功率仍只修改当前 Tab 对应频段。
- 开放网络不下发密码；非开放网络要求有效 WPA 密码。
- “隐藏 WiFi”与设备 `SSIDAdvertisementEnabled` 反向映射。
- 查询只有在全部目标成功且完整参数一致时才自动覆盖当前表单。
- 所有实际 `bbfdm.get/set` 路径和参数写入主执行日志；查询严禁执行 set。

## 验证

- 相关模块专项 unittest。
- `python scripts\verify_baseline.py`。
- `git diff --check`。
- Windows 桌面布局和真实 ONT 的 Mapping/字段兼容性保留为现场验收。
