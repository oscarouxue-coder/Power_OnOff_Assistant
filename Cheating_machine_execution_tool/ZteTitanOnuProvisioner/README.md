# 中兴 TITAN ONU 自动注册与业务配置工具

这是一个 Windows Python/Tkinter 源码工具，按 `172.18.18.152` 实机确认过的 TITAN/C600 风格命令生成并下发 ONU 注册与业务配置。

## 已实现

- Telnet 可指定源 IP，默认使用 `172.33.5.35`。
- 查询指定 PON 口未注册 ONU，并解析型号、SN、速率。
- 双击未注册 ONU 后自动填入 PON、型号、SN、速率。
- 生成完整命令预览。
- 下发前重新检查：
  - ONU ID 是否已占用；
  - SN 是否已在本 PON 口注册；
  - SN 是否仍存在于未注册 ONU 列表。
- 逐条执行注册、T-CONT、GEM Port、ONU service、VPort service-port 配置。
- 第一条 CLI 错误立即停止，不继续盲目下发。
- 完成后自动执行只读配置、service-port 和 detail-info 验证。
- 支持停止操作，密码只保存在当前界面内存中，不写文件和日志。

## 实机确认过的命令格式

```text
show pon onu uncfg gpon_olt-1/1/5 sn model speed-mode
show running-config-interface gpon_olt-1/1/5
show running-config-interface gpon_onu-1/1/5:55
show running-config-interface vport-1/1/5.55:1
show collection pon-onu gpon_onu-1/1/5:55 config
```

生成的配置结构：

```text
configure terminal
interface gpon_olt-1/1/5
onu <ONU_ID> type <型号> sn <SN>
exit
interface gpon_onu-1/1/5:<ONU_ID>
real-speed xgspon
tcont 1 profile <模板>
sn-bind enable both
gemport 1 tcont 1
exit
pon-onu-mng gpon_onu-1/1/5:<ONU_ID>
service <业务ID> gemport 1 vlan <VLAN>
exit
interface vport-1/1/5.<ONU_ID>:1
service-port <业务ID> user-vlan <VLAN> vlan <VLAN>
exit
end
```

## 运行

要求 Windows Python 3.9-3.12；只使用标准库，无需 `pip install`。

在本目录执行：

```powershell
python run.py
```

也可以双击 `启动工具.bat`。

## 操作流程

1. 填写 OLT 密码。
2. 设置机框、槽位、PON 口，点击“查询当前 PON 口”。
3. 选择未注册 ONU，双击或点击“填入选中 ONU”。
4. 手工填写一个未占用的 ONU ID。
5. 核对 T-CONT 模板和业务 VLAN；默认值来自 `gpon_onu-1/1/5:55` 的现有配置。
6. 点击“生成命令预览”逐条核对。
7. 勾选允许实际下发，再点击“执行注册与配置”。
8. 在执行日志中检查三组只读验证输出。

## 安全边界

- 工具不会执行 `write`。确认运行配置正确后，如现场要求持久化，请由操作员单独决定是否保存。
- 工具不会自动删除、覆盖或回滚 ONU。中途失败时会停止并退出配置模式，保留日志供人工判断。
- 当前已经在实机上完成只读命令、接口格式、未注册 ONU 表格和目标 ONU 配置结构验证。
- 尚未使用一台新的真实 ONU 执行写入验收；第一次现场使用应在维护窗口内，先用测试 PON/ONU ID 和少量 VLAN 验证。
- Telnet 是明文协议；如果 OLT 后续启用 SSH，应将传输层升级为 SSH。

## 测试

```powershell
python -m unittest discover -s tests -v
```
