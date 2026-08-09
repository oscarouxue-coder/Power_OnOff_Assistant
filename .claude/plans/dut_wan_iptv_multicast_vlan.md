# DUT WAN IPTV 组播 VLAN 实施计划

## 目标

- WAN 业务类型选择 `IPTV` 时显示可选的“组播 VLAN ID”。
- 填写时校验范围为 1–4094，并以 `MulticastVLANID` 写入 `Device.X_SDMC_CreateWAN()` 输入。
- 非 IPTV 隐藏并忽略该字段，避免切换业务类型后把旧值误下发。
- 查询现有 IPTV WAN 时解析并回填设备返回的组播 VLAN。

## 边界

- 沿用旧协议实现：组播 VLAN 是 IPTV 可选参数，留空时不单独配置。
- 新增和修改均适用，删除流程仍只使用现有连接索引。
- router 与 bridge 的 IPTV 均可携带该字段；其它 WAN 规则、MTU、地址组合和端口绑定保持不变。
- 不导入旧 `SdmcUbusLib` 的共享 Session，只参考字段命名。

## 实施步骤

1. 扩展 WAN 设置模型与现有连接快照模型。
2. 在 service 中增加 IPTV 可选组播 VLAN 校验，在 core 中增加 payload 和查询解析。
3. 在 WAN 表单中按业务类型联动显示、收集和回填该字段。
4. 增加 core、service、UI 回归，并纳入强制基线测试。
5. 同步 README、项目状态、验收基线和开发记录，运行 `python scripts\verify_baseline.py`。

## 验收重点

- IPTV：字段可见；空值可执行；`222` 下发为整数 222；0、4095、非数字被拦截。
- INTERNET/TR069/VOICE 等：字段隐藏，即使模型残留旧值也不写入 payload。
- 查询 IPTV WAN：设备返回 `X_SDMC_Multicast_VLANID` 后表单显示相同值。
- 切换为非 IPTV 后，不影响既有 WAN 配置和删除行为。
