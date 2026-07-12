# 开关机测试环境搭建助手

## 当前实现

这是用于配置测试通道、自动上/下电、检查线路和升级样机的桌面工具。

本文后续出现的 `config/...` 均指 `Auto_power_on_off_tool/config/...`；主程序不再使用 `Cheating_machine_execution_tool/config`。

- 读取和实时维护 `Auto_power_on_off_tool/config/network_card_ip.ini` 的通道配置。
- 主界面顶部提供“样机升级”入口，支持“页面升级”和“全包升级”两类流程。
- 样机升级窗口支持自定义项目/型号、输入超级用户凭据、选择升级固件、同步主界面目标 VLAN，并显示实时状态和进度。
- 样机升级窗口会保存上一次关闭时的升级方式、固件传输方式、`Tftp指令` 的执行方式（串行/并行）、恢复出厂选项、超级用户名、密码和固件路径；恢复出厂显示会按真实保存值刷新，开始升级确认框会明确显示“恢复出厂：开启/关闭”；状态保存到本机 `Auto_power_on_off_tool/config/sample_upgrade_settings.ini`，该文件不提交 Git。
- 选择“页面升级”后，点击“开始升级”会按主界面已勾选通道并行执行 UBUS 页面升级；每台样机会先启用通道对应网卡，再使用通道的 PC 静态 IP 作为请求绑定 IP、样机管理 IP 作为目标 IP，自动尝试 HTTP/HTTPS 登录 `/ubus/`，上传固件到 `/cgi-bin/cgi-upload`，调用 `Device.DeviceInfo.X_SDMC_Upgrade()`，查询升级状态并等待设备重启上线。
- 选择“全包升级 + Tftp指令”后，可选择默认“串行”或“并行（最多 2 台）”。并行模式完成即补位，单台失败不会停止其它样机；程控电源 COM 帧仍按通道串行发送，后续 Boot、TFTP、重启等待和最终登录可并行。每台 TFTPy Server 及其后续数据传输 socket 都严格绑定当前 VLAN 的 PC IP；设置网卡 IP 后会最多等待 15 秒，直到 Windows 确认该 IP 可绑定，仍不可绑定才报网卡/重复 IP/驱动错误，不回退到 `0.0.0.0`。所选固件映射为设备固定请求名 `tclinux_allinone`，设备仍执行 `tftp <通道IP>:tclinux_allinone`。
- 选择“全包升级 + Tftp Put”后，程序先对当前通道下电再上电；串口就绪后等待 1 秒并循环发送回车，检测到 `UserName:` 后按 boot 账号 `telecomadmin / nE7jA%5m` 登录。随后仍由 TFTPy Client 从当前通道 IP 上传到固定设备 `192.168.1.1:69`，并绑定该源 IP，避免多张 `.1` 网卡造成错误选路或启动变慢；远端文件名使用所选固件 basename。
- `Tftp Put` 保持原有串行、首错即停；`Tftp指令` 的并行模式最多同时运行两台。全包升级全程不临时改写 `Auto_power_on_off_tool/config/network_card_ip.ini`；所有串口和 TFTPy Server 都由本程序在 `finally` 中关闭，不查找或关闭外部 CRT/Tftpd 进程。
- `Tftp指令` 仍以串口的 `done` 与 `write` 同时出现作为设备处理完成判据；`Tftp Put` 则以 TFTPy 上传成功作为传输完成判据。随后保留 90 秒 boot 观察、`Boot/Bood` 后延迟 1 秒发送一次 `reset`、120 秒等待或重新上电、最终系统五次登录重试，以及恢复出厂“命令→1 秒→回车→8 秒”时序；仅当实际发送恢复出厂命令后，主程序执行日志才显示 `TX firstboot -y;reboot`。
- Boot 登录会在上电完成后先等待 1 秒再发送首个回车；仅当完整 `UserName:` / `User Name:` 在 1 秒稳定窗口内未夹带旧 `Password:` / `Passvord:` 时才提交用户名。用户名回车后重新从串口新数据中等待完整密码提示符，避免首轮上电过渡日志或旧缓存导致账号、密码错位。`Tftp Put` 的 UserName 后直连 boot 登录会在写用户名前记录密码游标、在写密码前记录 shell 游标，确保同批回显里的 `Password:` 或 `ECNT>` 不会漏检。
- 主界面“串口日志记录”已改为内置多通道终端：按 VLAN/COM 分页实时显示、开始/停止、清屏、手动命令发送和日志保存。自动升级占用某通道时仍显示输出，但手动发送被锁定；高频串口输出会按 VLAN 分批合并渲染，界面可短暂滞后但原始日志仍完整写入磁盘；全包升级自动打开的终端会在本批串口释放并写入关闭状态后自动关闭，手动打开的终端不会被自动关闭；`reboot`、`reset`、`firstboot`、`tftp`、`upgrade` 类手动命令需要二次确认；默认日志目录或本机终端状态文件不可写时会弹出明确错误提示。
- `web打开网关` 保持原有真实语义：仅打开内置串口监控，不下发升级命令。
- 主界面顶部提供“ONU注册”入口，窗口默认尺寸为 `896x580`，支持输入 OLT IP（首次默认 `172.18.18.151`，后续恢复上一次关闭时保存的值）、用户名和密码，密码框支持小眼睛切换明文/密文显示；点击 Telnet 连通性测试并确认后，会先检查 OLT Telnet 23 端口，连通后使用用户填写的用户名和密码登录 OLT，并下发 `configure terminal` 进入全局模式；OLT IP 右侧只显示 Telnet 连通性结果，登录和全局模式状态显示在查询入口下方，查询/注册状态栏支持长结果自动换行；点击“开始查询”会登录 OLT 并执行 `show gpon onu uncfg`，以复选框列表显示所有 PON 口下未注册 ONU 的接口、SN 和状态，并支持全选/取消全选；勾选 ONU 后点击“开始注册”会二次确认并优先按已确认的 SD-41 模板下发注册配置、业务 VLAN 和 `pon-onu-mng` 服务配置，如新增业务配置命令报错，会自动查询并删除已注册但未在线的 ONU，优先删除和新 ONU 同 PON 口的不在线 ONU，再删除其它 PON 口不在线 ONU，删除后重新下发新 ONU 注册配置；注册完成后会询问是否保存 OLT 最新配置，用户确认后先退出到 `ZXAN#` 执行模式再执行 `write` 写入启动配置；ONU 注册输入框会保存到本机 `config/onu_registration.ini`，该文件不提交 Git；后续扩展结果导出流程。
- 为每个通道选择实际接入的 Windows 网卡名称。
- 网卡列表优先读取 `Get-NetAdapter -IncludeHidden`，可显示禁用、断开和隐藏网卡；界面显示状态，例如 `[Connected]`、`[Disconnected]`。
- 保存每个通道的 PC 静态 IP、样机管理 IP、子网掩码、启用状态。
- 自动上电和全包升级均由主程序直接控制程控电源，不启动 `Auto_Power_On_Off_Tool.exe` 或其 GUI。
- 程控电源使用所选 COM 口的 `19200 8N1` 串口参数；“自动上/下电”二级弹窗提供“上电/下电”下拉框，默认“上电”。
- 自动上电会按勾选顺序发送 `channel_1` 到 `channel_16` 的开启帧，相邻帧间隔 1 秒；自动下电仅向勾选通道发送关闭帧，相邻帧同样间隔 1 秒；两种操作均不发送全断电帧。
- 自动上/下电均在最后一条指令发送后立即结束，不额外预留启动等待；全包升级每次仅关闭再开启当前升级通道，不发送“关闭全部程控电源通道”帧，保留其独立断电重启逻辑。
- 按通道切换指定网卡静态 IP，并 ping 样机管理 IP 判断线路是否正常。

当前版本使用 Python 标准库 `tkinter` 实现桌面界面，不需要安装 PySide6；依赖见 `requirements.txt`（`pyserial==3.5`、`tftpy==0.8.7`、`requests>=2.31,<3`）。

## 运行方式

首次运行前，在 `Cheating_machine_execution_tool` 目录安装依赖：

```powershell
python -m pip install -r .\requirements.txt
```

随后启动主程序：

```powershell
python .\run_line_check_assistant.py
```

修改网卡静态 IP 需要管理员权限。正式检查线路时，请用管理员权限打开 PowerShell 或打包后的 EXE。

### VS Code 运行

1. 用 VS Code 打开 `F:\Aouxue\Power_OnOff_Assistant` 工作区，并选择解释器 `.venv_serial_upgrade\Scripts\python.exe`。
2. 打开 `Cheating_machine_execution_tool\run_line_check_assistant.py`。
3. 在“运行和调试”中选择 `LineCheckAssistant` 后按 `F5`，或使用右上角“运行 Python 文件”。

`LineCheckAssistant` 会以 `Cheating_machine_execution_tool` 为工作目录启动，确保可正确导入主程序模块并读取项目配置。

## 验收步骤

1. 启动软件后，确认界面能列出 `network_card_ip.ini` 中已有的 `channel_1`、`channel_2` 等通道。
2. 点击“刷新网卡”，确认下拉框里能看到当前 PC 的网卡名称，例如 `a虚拟网卡2口`。
3. 选择一个通道，填写：
   - 样机接入网卡
   - PC 静态 IP
   - 样机管理 IP
   - 子网掩码
   - 是否启用
4. 勾选或取消勾选通道，确认 `Auto_power_on_off_tool/config/network_card_ip.ini` 立即更新，并且只保留已勾选通道的 `[channel_x]` 配置节。
5. 人工接好线路后，点击“自动上/下电”，选择程控电源 COM 口和操作类型（默认“上电”），并确认影响通道。
   - 选择“上电”时，软件会按勾选顺序发送开启帧，相邻帧间隔 1 秒，且不会先关闭任何通道。
   - 选择“下电”时，软件只会向勾选通道发送关闭帧，相邻帧间隔 1 秒，不会发送全部断电帧。
   - 确认后主程序直接发送程控电源串口帧，不会启动旧 EXE 或点击外部 GUI；最后一条帧后不额外等待。
6. 回到新软件，点击“检查当前通道”或“已上电，开始检查全部启用通道”。
7. 观察日志：
   - 通过：显示 `[通过] channel_x ping xxx 成功`。
   - 失败：显示通道、网卡、PC IP、样机 IP，并提示检查上电、网线、接错口、IP 配置。
8. 打开“样机升级”，选择“页面升级”，确认已勾选通道都有 PC 静态 IP 和样机管理 IP，选择固件后点击“开始升级”。
   - 软件会二次确认将通过 UBUS 上传固件并触发升级。
   - 软件会先启用目标通道对应网卡；如果启用失败，会在日志和失败弹窗中提示。
   - 日志会显示每台样机的 HTTP/HTTPS 登录、上传、升级状态和重启上线结果。

## 打包建议

安装 PyInstaller 后，可在 `开关机执行工具` 目录执行：

```powershell
.\build_line_check_assistant.ps1
```

生成的 EXE 位于 `dist\LineCheckAssistant.exe`。
生成的 `.spec` 文件统一保存到 `line_check_assistant\packaging_specs`。

每次重新打包出最新版 EXE 后，不在当前 PC 直接运行 `dist\LineCheckAssistant.exe`；只确认打包成功，并向用户报告输出路径。

打包后程序会从 EXE 所在目录、上级目录中查找 `Auto_power_on_off_tool/config` 文件夹；程控电源协议已内置，不再依赖 `Auto_Power_On_Off_Tool.exe`。
