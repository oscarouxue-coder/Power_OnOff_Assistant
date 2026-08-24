# C600 VPort/GEM 对齐修复

## 目标

- 修复C600四层业务已经拆分到GEM 1/2/3/4，但全部service-port仍配置到VPort 1的问题。
- 依据实机`show gpon onu vport`确认的1:1关系，让上网/语音/组播/TR069分别进入对应VPort。
- 为VLAN 600补齐实机现网已确认的IGMP接收端口配置。
- 保持C300命令、C600可选write、显式源IP和删除安全边界不变。

## 实施

1. C600 driver按VLAN同时派生GEM与VPort，校验上网GEM/VPort一致且不与固定2/3/4冲突。
2. 生成多个`interface vport-...:<ID>`上下文，只在对应VPort下创建service-port。
3. VLAN 600所在VPort增加`igmp fast-leave enable`、`igmp version v2`及`igmp mvlan 600 / receive-port`。
4. 完整验证同时核对service-port运行状态和实际VPort编号，并核对IGMP配置。
5. 更新UI说明、操作员说明、验收状态、开发记录和强制基线测试。

## 验证边界

- 项目负责人已授权精确删除并重新注册`SDMC176D42AA`；删除前必须再次核对接口、ONU ID和SN，只处理这一台。
- 自动化通过后执行真实注册、working轮询、四VPort/service-port/IGMP完整回读；默认不执行`write`，成功后保留ONU在线供WAN侧检查。
- OLT侧完整回读通过不自动扩大为语音/TR069 DHCP服务器及IPTV节目业务验收，仍需结合ONU WAN状态确认。
- 不构建、不运行`dist\LineCheckAssistant.exe`，不自动提交Git。
