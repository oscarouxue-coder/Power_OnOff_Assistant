# WiFi连接与无线Ping（2026-11-04，负责人已授权实施）

- 正式Telnet流程新增分频段/合一接入两种模式；旧配置默认分频段、自动认证、无线Ping关闭。保留高级手动认证、原生勾选框、现有FIFO/停止/续跑和有线Ping。
- 独立core通过现有锁源Telnet只读Mapping、SSID/AP/Radio实例和BSSID，Windows Native WLAN使用目标BSSID及未持久化临时profile；实际身份/频率/认证须核验且连续稳定2秒。4次连接、每次20秒（含扫描/核验）、间隔10秒。
- 无线Ping支持IPv4和域名，指定接口DNS（5秒）、等待无线IPv4（30秒）、源IPv4+IP_UNICAST_IF双绑定。4包、每包2秒、间隔1秒、至少1个有效回复通过；连接/频段变化覆盖已有回复，不重连重跑Ping。不开启不查询DNS/发包。
- 新模块放core/services/models/ui，旧业务仅改入口适配，不搬迁或重写已验收结构；临时连接退出时断开，不清理用户profile、不修改样机无线参数/IP/DNS/路由。新数据结构包含options、目标snapshot和Ping结果，旧凭据摘要保持兼容。
- 分轮落地：独立模块及特征测试→正式连接入口→UI及Ping接入→专项/完整基线→同步开发记录、状态、验收基线及操作说明。保留工作区已有修改；不提交、不打包、不发布、不启动EXE。
- 自动化使用模拟WLAN、Telnet、socket和DNS；Windows真实双频/多通道/无线有线并存抓包仍待负责人复验，不将自动化结论扩大为现场验收。
