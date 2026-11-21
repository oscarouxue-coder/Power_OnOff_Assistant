# 下一DUT增量：语音 / TR069审计

2026-11-18，只读审计。WiFi当前源码/模拟完成、原生和完整门禁状态见[WiFi报告](WIFI_REPORT.md)；本文不代表语音/TR069已经实现。

## 可直接复用的真实入口

- `src/models/dut_config_models.py`：`DutVoiceSettings`、`DutTr069Settings`及原请求/查询结果。
- `src/services/dut_status_query_service.py`：`voice`查询携带当前`line_index`，验证1–8；`tr069`无线路索引；共同回填仍用`common_dut_status_settings`严格比较所有目标。
- `src/services/dut_advanced_config_service.py`：原完整字段校验及原批量/单台网络准备、锁源登录注销、停止和失败隔离。
- `src/core/dut_ubus_config.py`：实际`query_voice_status/configure_voice`、`query_tr069_status/configure_tr069`都在此文件，不另建一套设备实现。
- `src/ui/dut_config_window.py`：原语音/TR069默认值、回填、候选与能力禁用规则。纯模型默认不等于原Tk表单默认；尤其TR069表单有原初值，应逐项对照而不在本报告复制凭据。

## 语音必须保持

- 线路索引、账号启用、显示名、认证账号/密码、代理/出站代理/注册服务器及三个端口、DTMF、注册有效期、SIP模式、DigitMap、五个按顺序编码。
- 原服务只在账号启用时要求名称和认证凭据；代理/注册服务器、端口及有效期仍按原校验。五个编码不能改成无序集合，也不能增加“去重”改变现有语义。
- `voice_choice_options`使用查询支持列表，缺失时走原兜底，同时保留当前值；支持列表由本机实际查询派生，不接受前端自报能力。只读查询不依赖未填完的配置表单。
- 私有状态回填认证密码，持久Job参数、结果、确认及Qt日志不得包含该密码；不能只过滤登录密码。

## TR069必须保持

- ACS URL/账号/密码、周期Inform开关和间隔、HTTP连接请求开关及凭据、证书开关、配置后手动Inform。
- `tr069_status_form_values`刻意不回填`manual_inform`，这是执行动作而不是设备持久状态；查询完成不能自动勾选或抹掉用户动作选择。
- 查询的`supported_fields`非空时，禁用不支持的字段；不支持手动Inform时原GUI会取消该动作。空能力列表仍沿原兼容兜底，不能直接判为全部不支持。字段禁用要保留现有值，payload仍由原core筛选。
- `configure_tr069`先按原支持字段下发并回读；勾选手动Inform才触发原阶段字段，沿原60秒超时/1秒轮询/停止检查，只有原`10_success`判成功。不能把参数写入成功当作手动Inform成功，不重试重放未知动作。
- ACS与连接请求两套密码都必须纳入私有回填及日志/任务脱敏；不修改原设备实际参数值或协议。

## 进入实现前的门禁

WiFi与已有模块强制原生、稳定布局截图和完整基线已通过。接下来按小步边界实现语音/TR069控制面。继续使用原DUT窗口目标/凭据/并发、一次确认、项目配置/NIC/查询绑定及原Job/资源，不新增定时器或业务并行。Fake替代物理边界，调用原服务/core，覆盖各密码、部分能力、动作选项、回读失败和停止。需要共享原纯展示规则时保留旧导入和AST证据，按已验收UI迁移运行完整基线。真实DUT、网卡和ACS连接不在此次只读审计范围内。
