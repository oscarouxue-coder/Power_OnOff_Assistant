# DUT WAN 现有连接查询下拉

## 目标

- WAN 操作为“修改”或“删除”时，将“现有连接名/索引”改为只读下拉框。
- 通过当前已勾选 DUT 的 VLAN 源 IP 登录 UBUS，读取 `Device.IP.Interface.` 中的 WAN 连接名。
- 多台批量操作只展示所有查询成功目标中名称完全一致的共同 WAN，避免同一索引在不同 DUT 上指向不同业务时误修改或误删除。

## 分层

- `src/core/dut_ubus_config.py`：发送和解析 WAN 连接名查询协议。
- `src/services/dut_wan_query_service.py`：网络准备、源 IP 可绑定检查、UBUS 登录重试、批量查询和共同连接汇总。
- `src/models/dut_config_models.py`：单台查询结果模型。
- `src/ui/dut_config_window.py`：只读下拉、查询按钮、查询结果提示。
- `line_check_assistant/app.py`：主线程回收和后台查询入口，不复制协议或业务流程。

## 安全边界

- 查询是只读 UBUS get，不调用 `Device.X_SDMC_CreateWAN()`。
- 任一目标查询失败时不生成批量修改/删除下拉列表。
- 不展示仅部分 DUT 存在的连接，也不按数字索引模糊合并不同名称。
- 主执行日志记录网络准备、明文登录、实际 get 路径、每台连接列表及共同连接汇总。

## 验证

- core 查询响应解析、过滤和排序。
- service 单台成功/失败关闭 client、批量停止、共同连接交集。
- UI 只读下拉、查询按钮、主线程完成回收。
- `python scripts\verify_baseline.py` 与 `git diff --check`。
