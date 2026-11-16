# 公司 MiniMax 网关接入实施与验证（2026-11-16）

本轮为源码局部行为改动，未结构性搬迁既有功能，未提交、推送、打包或运行EXE，未操作DUT。方案见[实施计划](../../.claude/plans/company-minimax-gateway.md)。

## 实现

- `src/services/ai_store.py`：仅精确HTTP源地址`10.10.120.244:4000`例外，其余继续HTTPS；保存格式、DPAPI地址绑定及指纹未改变。
- `src/core/ai_client.py`：统一Chat Completions/模型列表路径组装；显式`/v1`或完整端点不重复拼接。默认不带`/v1`，无自动路径/模型回退或网络重发。增加可选`emit`，分类连接/代理/TLS/超时错误，HTTP状态错误仍独立处理，输出最终地址且过滤密钥。
- 新增`src/core/ai_gateway_network.py`：Requests有效代理脱敏快照；固定PowerShell脚本，目标只经stdin JSON传入；DNS单目标1秒、TCP单目标总计2秒，诊断总计8秒，停止清理进程并保留已完成JSON阶段。使用无源地址绑定的TCP socket、Get-NetIPAddress和Find-NetRoute，只读不改配置。原HTTP未知出口、后续探测实际源IP/对应接口和路由推断明确分开。
- `src/services/ai_diagnostic_service.py`：默认客户端带主日志回调，自定义三参数factory兼容；对话、审查、监控、Capability模型测试使用既有共享factory。
- `src/ui/ai_diagnostics_window.py`：现有刷新模型及测试入口传入同一主日志回调；无新增按钮、权限或业务分支。原模型查询/测试Capability仍调用共享客户端；配置写入的partial边界保持。审查后更新`src/ui`该文件的11份GUI动作摘要，矩阵86项及63/15/5/3状态计数不变，`CAPABILITY_COVERAGE.md`重新生成后无内容差异。
- 新增`tests/test_ai_gateway.py`，编译清单登记新core模块；同步操作员说明、项目状态、验收§2.16/§3及开发日志。

除上述源码外，修改/新增文件：

- `Cheating_machine_execution_tool/scripts/verify_baseline.py`
- `Cheating_machine_execution_tool/scripts/capability_gui_actions.json`
- `Cheating_machine_execution_tool/line_check_assistant_README.md`
- `.claude/plans/company-minimax-gateway.md`
- `PROJECT_STATUS.md`
- `ACCEPTANCE_BASELINE.md`
- `DEVELOPMENT_LOG.md`
- 本记录

## 自动化验证

在主源码目录使用仓库外锁定构建环境的CPython3.9.10 x64、Requests2.31.0。未安装/调整依赖或工具链。

```powershell
$taskPython = "$env:LOCALAPPDATA\LineCheckAssistant\build-env-py39\Scripts\python.exe"
& $taskPython -c "import sys,unittest; sys.path.insert(0,'tests'); names=['test_ai_gateway','test_ai_core','test_ai_conversation','test_ai_context_budget','test_ai_context_usage','test_ai_integration','test_ai_diagnostic_task','test_capability_ai_data','test_capability_coverage']; suite=unittest.defaultTestLoader.loadTestsFromNames(names); result=unittest.TextTestRunner(verbosity=1).run(suite); sys.exit(not result.wasSuccessful())"
& $taskPython -c "import py_compile; paths=['src/core/ai_gateway_network.py','src/core/ai_client.py','src/services/ai_store.py','src/services/ai_diagnostic_service.py','src/ui/ai_diagnostics_window.py','scripts/verify_baseline.py','tests/test_ai_gateway.py']; [py_compile.compile(p,doraise=True) for p in paths]; print('PY_COMPILE_OK '+str(len(paths)))"
& $taskPython scripts/verify_capability_coverage.py
git diff --check
```

- 最终组合：`Ran 196 tests in 27.030s`、`OK`，exit0；含新增22项网关测试。此前195项通过后，复核补充“NO_PROXY匹配但显式Session代理仍生效”的回归，避免误报已经绕过代理；最终组合重跑通过。
- 局部编译7文件通过；覆盖审查后已执行`verify_capability_coverage.py --update`，复核`CAPABILITY_COVERAGE_OK`；差异格式通过。
- 覆盖精确地址/路径矩阵、两个手填模型ID原样发送、Bearer与密钥隔离、保存重开、工具资格失效、工具续接、Chat Completions流式及原Responses、代理/NO_PROXY与不修改Session、错误码/脱敏、不重发、停止、8秒终止及部分证据保留。固定脚本参数注入边界也有回归。
- Windows真实本机回环：TCP连接成功，读取127.0.0.1、Loopback Pseudo-Interface 1/1及当前路由。关闭端口如实记录拒绝或超时；不访问真实设备。
- 首轮新增18项中1项失败：关闭端口在Windows上实际超时，测试原先只允许明确拒绝；修正为接受真实的拒绝或超时，并仅在拒绝时断言错误码。该修正未改变探测结果或扩大成功判定。随后新增专项18项通过，补充模型ID/流式/固定脚本及显式代理回归后纳入最终196项。
- 首轮现有相关150项中149通过、1项覆盖快照失败（日志回调引起GUI AST摘要改变）；审查并更新快照后，最终组合全部通过。源码编译清单及6份文档UTF-8/新增本地链接核对通过。
- 本轮未运行完整基线；保留PROJECT_STATUS中最近一次完整2589项记录，不把它当成本轮结果。提交/标准打包门禁未改变。

## 真实公司网关证据

本轮在当前执行环境实际执行，未读取/打印任何真实API Key：

1. 默认AI配置库仅用SQLite只读模式查询该网关配置元数据，未找到匹配配置/绑定凭据；不挪用其他厂商的地址绑定密钥。
2. 对`10.10.120.244:4000`的当前无绑定TCP探测成功；源IP`198.18.0.1`，源地址对应接口`Meta/5`；Find-NetRoute当前选择亦为该接口/源IP。它不是原HTTP请求socket证据，也不能证明办公网IP`10.10.112.18`错误。
3. 向`http://10.10.120.244:4000/chat/completions`发送一次无认证、无项目材料的最小POST（model=`3rd-MiniMax-M3`，messages仅`Reply OK.`，stream=false），禁止重定向、超时3/5秒，返回`HTTP 401`。只记录状态，无服务正文或认证头。

这仅证明当前环境能得到该路径的HTTP响应；401不证明模型存在、密钥有效或工具兼容。默认配置无公司密钥，尚未完成两个模型的真实文本/流式/工具续接验证，亦未进行完整Windows GUI人工验收或DUT验收。负责人可按操作员说明在本机模型配置页填写公司密钥后复验；不在聊天、代码或报告中填写密钥。
