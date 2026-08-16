# DUT 5G WiFi、语音与 TR069 动态能力

## 目标

- 将本次已确认验收范围收窄为 2.4G WiFi 五类下拉。
- 保证 5G WiFi 使用独立 Radio/AP 能力加载，不复用 2.4G 候选。
- 语音查询后按 DUT 返回能力加载 DTMF、SIP 模式和编码候选，并在配置前再次校验。
- TR069 查询后按 ManagementServer 实际存在字段控制可配置项，下发时不写设备不支持的可选字段。

## 分层改动

- `src/models`：保存语音能力候选和 TR069 支持字段。
- `src/core`：解析 UBUS 能力字段、构建按能力裁剪的配置载荷。
- `src/services`：配置前拒绝不在 DUT 能力列表中的语音选项。
- `src/ui`：查询成功后更新语音下拉；按 TR069 支持字段启用/禁用控件；目标变化后清理旧能力。
- `tests`：覆盖 5G 独立能力、语音动态能力、TR069 字段裁剪和目标变化。

## 验证

- 运行相关 unittest。
- 运行 `python scripts\verify_baseline.py`。
- 真实 DUT 验收仍分别记录，不用自动化测试替代。
