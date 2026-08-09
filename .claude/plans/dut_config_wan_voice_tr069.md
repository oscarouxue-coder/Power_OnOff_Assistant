# DUT 配置扩展 WAN、语音与 TR069

## 目标

- 在现有 `DUT配置` Notebook 中新增“WAN配置”“语音配置”“TR069配置”三个可执行 Tab。
- 三个 Tab 继续使用主界面已勾选通道、共享 UBUS 登录凭据，并复用网络准备、VLAN 源 IP 绑定、1–8 台并行、停止和单台失败隔离边界。
- WAN 首版覆盖新增、修改、删除现有 WAN，以及 IPv4、IPv6、IPv4+IPv6 双栈三种协议模式；IPv4 支持 DHCP/静态，IPv6 支持 SLAAC/DHCPv6/静态组合。

## 实现

1. 在 `src/models` 增加三个功能的请求、参数和结果模型；公共 DUT 连接信息保持唯一来源。
2. 在 `src/core` 基于现有 `UbusHttpClient` 实现 WAN operate、VoIP set、TR069 set/get/manual inform 的最小协议切片；`SdmcUbusLib` 仅作为协议参考，不直接依赖其共享静态 Session。
3. 在 `src/services` 为 WAN、语音、TR069 分别新增批量编排；单台统一执行“准备网卡 → 等源 IP 可绑定 → 独立 UBUS 登录 → 下发实际配置 → 回读或结果验证 → 关闭 client”。
4. 扩展 `DutConfigWindow`：每个 Tab 有独立参数区、目标状态表和开始按钮；共享刷新、并行数、停止控制，同一时间只允许一个 DUT 批次运行。
5. 主程序负责收集已勾选通道、危险操作确认、启动 worker、主线程回收逐台状态及输出批次汇总。
6. WAN 删除必须要求明确连接名或索引并二次确认；不自动批量删除全部 WAN。修改必须要求现有 WAN 索引。
7. 主执行日志记录关键阶段、源/目标、实际 UBUS method/path/input、成功、跳过、失败与汇总。

## 验证

- core 协议 payload、字段校验、单台流程、批量并行/停止/失败隔离和 UI 控制器专项测试。
- `python scripts/verify_baseline.py`
- `git diff --check`
- Windows 桌面布局和真实 DUT 协议兼容性另行验收，不由单元测试自动升级状态。
