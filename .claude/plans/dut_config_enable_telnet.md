# DUT 配置批量开启 Telnet

## 目标

- 将现有 DUT 配置占位入口升级为可执行的 UBUS 批量开启 Telnet 功能。
- DUT 窗口采用 Notebook，首个 Tab 为“Telnet配置”；后续其它 DUT 能力新增独立 Tab。
- 目标使用主界面已勾选通道，凭据与“写样机参数”的首次登录账号、密码共享且明文显示。

## 实现

1. 新增 DUT 请求/结果模型及独立 service，UI 不复制 UBUS 协议。
2. 单台时序：准备 VLAN 网卡与静态 IP → 等源 IP 可绑定 → UBUS 开启 AccessCtrl Telnet 规则 → 严格绑定源 IP 验证 TCP 23 端口。
3. 支持 1–8 并行、默认 1；首次失败后最多重试 3 次，端口最多验证 3 次；单台失败不阻断其它 DUT。
4. 停止后不再提交后续 DUT，已进入调用的任务在安全点退出；主线程队列更新逐台状态。
5. 主执行日志记录真实 UBUS get/set/add、明文凭据、TCP 源/目标以及成功、失败、停止与汇总。

## 验证

- DUT service、Telnet 源绑定探测、UBUS 实际命令日志和主界面控制器专项测试。
- `python scripts/verify_baseline.py`
- `git diff --check`
- Windows 桌面与真实样机验收另行确认，不由单元测试自动升级状态。
