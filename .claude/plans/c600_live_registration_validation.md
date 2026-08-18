# C600真实ONU注册与业务配置验证

## 目标

1. 使用当前C600业务service完成一台未注册ONU的真实注册、业务配置和回读验证。
2. 根据实机首错修复自动速率命令策略，保留操作员手工指定能力。
3. 修复后从未注册状态完整复验，最后删除测试ONU并确认ONU ID/SN释放。

## 现场边界

- 目标OLT：当前本机C600配置，显式绑定已配置源IP。
- 仅处理一台明确选定的未注册ONU和ONU ID 11；不触碰第二台未注册ONU。
- 不执行`write`；删除仅针对本次测试ONU，由项目负责人明确授权。
- 每条CLI首错停止，删除后以baseinfo、SN查询和未注册列表三项确认恢复。

## 验证

- 真实流程：发现、ID/SN预检、配置、working轮询、collection/service-port/detail-info/MVLAN验证。
- 修复后重复完整service流程并清理测试ONU。
- 相关专项测试、`python scripts/verify_baseline.py`、`git diff --check`。
