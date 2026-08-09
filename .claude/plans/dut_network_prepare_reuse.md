# DUT 网卡准备按需复用

## 目标

DUT 配置和 WAN 查询执行前先只读检查目标网卡的启用状态、IPv4 地址和前缀长度。配置已完全满足要求时直接复用；仅修复不满足项；查询失败时回退既有完整准备流程。

## 边界

- 公共 `prepare_network_for_sample` 通过可选参数启用预检，默认行为不变。
- 仅 DUT Telnet、WAN/语音/TR069 配置和 WAN 查询传入复用开关。
- 线路检查、页面升级、全包升级、写参及测试项执行继续保持原准备语义。
- 无论是否复用，DUT service 都继续执行 `wait_for_bindable_ip`，不跳过源 IP 可绑定确认。

## 验证

- 已满足：不调用启用和静态 IP 设置，也不执行等待稳定延时。
- 已启用但地址不匹配：只设置静态 IP。
- 状态查询失败：启用、设置 IP 和两次稳定等待完整回退。
- DUT 三条 service 路径均明确传入复用开关。
- 执行全量 `python scripts\verify_baseline.py` 和 `git diff --check`。
