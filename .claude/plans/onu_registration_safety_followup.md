# ONU 注册现场安全与验证完善

## 目标

1. C300 离线清理只能处理同一 PON、由操作员明确选择的一台 ONU，禁止批量和跨 PON 删除。
2. C600 以真实命令完成精确 ONU ID 和全 OLT SN 查重，并正确接受“未找到”返回。
3. 两种 OLT 下发后可停止轮询上线，区分“配置已存在”和“ONU 已上线”。
4. C600 对注册身份、T-CONT/GEM、业务、状态和 MVLAN 600 做实际解析，不再只执行查询。
5. C300/C600 分别保存连接资料；C600 固定 MVLAN 600 时必须存在 VLAN 600 业务映射。

## 实施边界

- UI 只负责显示候选、收集明确选择和调用 service；设备查询、重检、删除限制和轮询均在 core/service。
- C300 删除前必须再次读取状态，候选必须仍在目标 PON 且仍为离线；只生成一条目标 `no onu <ID>`。
- C600 的 `%Error ... ONU data is null` 与 `%Error ... No related information to show`仅在对应只读预检命令中视为空结果，其他错误照常停止。
- 上线轮询可取消，达到超时时明确返回“配置已下发但未上线”，不得触发额外删除。
- 不修改或运行独立 C600 GUI，不打包，不在真实 OLT 下发配置。

## 验证

- driver/parser、service 编排、UI 单候选和分型号持久化专项测试。
- `python scripts/verify_baseline.py`。
- `git diff --check`。
