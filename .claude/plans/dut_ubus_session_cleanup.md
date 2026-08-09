# DUT UBUS 会话释放与连续查询修复

## 问题

同一 DUT 第一次查询现有 WAN 成功，第二次重新登录成功后 `bbfdm.get Device.IP.Interface.` 返回 `Access denied`。轻量 `UbusHttpClient.close()` 只关闭本机 HTTP 连接，没有调用设备支持的 `Device.X_SDMC_Login.logout()`，导致设备端会话残留。

## 实现

- `UbusHttpClient` 记录最近一次成功登录的 session ID。
- 新增显式 `logout()`，按项目协议参考调用 `bbfdm.unauthenticated_operate Device.X_SDMC_Login.logout()`。
- `close()` 对仍有效的 session 执行 best-effort 注销，再关闭本机连接，覆盖 DUT 配置和写参等共用调用。
- WAN 查询每次尝试结束前显式注销并记录 TX、成功或失败；注销失败不覆盖原查询结果，但仍关闭连接。

## 验证

- core 测试确认注销命令、SessionId 和重复关闭行为。
- service 测试模拟设备仅允许一个活动会话，连续执行两次 WAN 查询必须都成功。
- 运行 `python scripts\verify_baseline.py` 与 `git diff --check`。
