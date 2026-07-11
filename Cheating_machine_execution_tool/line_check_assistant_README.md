# 开关机测试环境搭建助手

## 当前实现

这是现有文件名包含 `Auto_Power_On_Off_Tool` 的旧开关机工具 exe 的前置辅助工具，用于：

- 读取和实时维护 `config/network_card_ip.ini` 的通道配置。
- 主界面顶部提供“样机升级”入口，支持“页面升级”和“全包升级”两类流程。
- 样机升级窗口支持自定义项目/型号、输入超级用户凭据、选择升级固件、同步主界面目标 VLAN，并显示实时状态和进度。
- 样机升级窗口会保存上一次关闭时的升级方式、固件传输方式、恢复出厂选项、超级用户名、密码和固件路径；恢复出厂显示会按真实保存值刷新，开始升级确认框会明确显示“恢复出厂：开启/关闭”；状态保存到本机 `config/sample_upgrade_settings.ini`，该文件不提交 Git。
- 选择“页面升级”后，点击“开始升级”会按主界面已勾选通道并行执行 UBUS 页面升级；每台样机会先启用通道对应网卡，再使用通道的 PC 静态 IP 作为请求绑定 IP、样机管理 IP 作为目标 IP，自动尝试 HTTP/HTTPS 登录 `/ubus/`，上传固件到 `/cgi-bin/cgi-upload`，调用 `Device.DeviceInfo.X_SDMC_Upgrade()`，查询升级状态并等待设备重启上线。
- 选择“全包升级 + Tftp指令”后，软件按已勾选 VLAN 串行升级：内置 pySerial 打开 VLAN 对应 COM 口，旧开关机工具点击 `Start ALL` 后立即每秒回车进入 boot；TFTPy Server 明确绑定当前通道 IP 的 UDP 69，只将所选固件映射为设备固定请求名 `tclinux_allinone`，设备仍执行 `tftp <通道IP>:tclinux_allinone`。
- 选择“全包升级 + Tftp Put”后，TFTPy Client 从当前通道 IP 上传到固定设备 `192.168.1.1:69`，并绑定该源 IP，避免多张 `.1` 网卡造成错误选路或启动变慢；远端文件名使用所选固件 basename。
- 两种全包升级均按主界面通道顺序串行、首错即停。每台前仍临时改写 `config/network_card_ip.ini`，结束后恢复完整选择；所有串口和 TFTPy Server 都由本程序在 `finally` 中关闭，不查找或关闭外部 CRT/Tftpd 进程。
- `Tftp指令` 仍以串口的 `done` 与 `write` 同时出现作为设备处理完成判据；`Tftp Put` 则以 TFTPy 上传成功作为传输完成判据。随后保留 90 秒 boot 观察、`Boot/Bood` 后延迟 1 秒发送一次 `reset`、120 秒等待或重新上电、最终系统五次登录重试，以及恢复出厂“命令→1 秒→回车→8 秒”时序。
- 主界面“串口日志记录”已改为内置多通道终端：按 VLAN/COM 分页实时显示、开始/停止、清屏、手动命令发送和日志保存。自动升级占用某通道时仍显示输出，但手动发送被锁定；`reboot`、`reset`、`firstboot`、`tftp`、`upgrade` 类手动命令需要二次确认。
- `web打开网关` 保持原有真实语义：仅打开内置串口监控，不下发升级命令。
- 主界面顶部提供“ONU注册”入口，窗口默认尺寸为 `896x580`，支持输入 OLT IP（首次默认 `172.18.18.151`，后续恢复上一次关闭时保存的值）、用户名和密码，密码框支持小眼睛切换明文/密文显示；点击 Telnet 连通性测试并确认后，会先检查 OLT Telnet 23 端口，连通后使用用户填写的用户名和密码登录 OLT，并下发 `configure terminal` 进入全局模式；OLT IP 右侧只显示 Telnet 连通性结果，登录和全局模式状态显示在查询入口下方，查询/注册状态栏支持长结果自动换行；点击“开始查询”会登录 OLT 并执行 `show gpon onu uncfg`，以复选框列表显示所有 PON 口下未注册 ONU 的接口、SN 和状态，并支持全选/取消全选；勾选 ONU 后点击“开始注册”会二次确认并优先按已确认的 SD-41 模板下发注册配置、业务 VLAN 和 `pon-onu-mng` 服务配置，如新增业务配置命令报错，会自动查询并删除已注册但未在线的 ONU，优先删除和新 ONU 同 PON 口的不在线 ONU，再删除其它 PON 口不在线 ONU，删除后重新下发新 ONU 注册配置；注册完成后会询问是否保存 OLT 最新配置，用户确认后先退出到 `ZXAN#` 执行模式再执行 `write` 写入启动配置；ONU 注册输入框会保存到本机 `config/onu_registration.ini`，该文件不提交 Git；后续扩展结果导出流程。
- 为每个通道选择实际接入的 Windows 网卡名称。
- 网卡列表优先读取 `Get-NetAdapter -IncludeHidden`，可显示禁用、断开和隐藏网卡；界面显示状态，例如 `[Connected]`、`[Disconnected]`。
- 保存每个通道的 PC 静态 IP、样机管理 IP、子网掩码、启用状态。
- 自动启动旧软件，选择 `Fully_powered_on`，点击 `Start ALL`，按启用通道数每通道等待 10 秒后关闭旧软件；多台串行升级时每次只保留当前通道，因此每台上电等待 10 秒。
- 自动上电过程会实时输出日志，便于判断卡在打开窗口、选择下拉框还是点击按钮。
- 自动上电前会读取设备管理器 `端口(COM 和 LPT)` 中名称以 `Prolific` 开头的端口，让用户选择程控电源 COM 口，并同步到旧工具的 `Serial Num` 下拉框。
- 启动旧软件前会把 `config/config.ini` 中的 `Fully_powered_on` 移到 `[config]` 第一项，让旧软件启动后默认选择上电配置。
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
4. 勾选或取消勾选通道，确认 `config/network_card_ip.ini` 立即更新，并且只保留已勾选通道的 `[channel_x]` 配置节。
5. 人工接好线路后，点击“自动启动旧软件上电”，先选择程控电源 COM 口，再让新软件完成旧工具上电流程。
   - 旧软件启动前会自动准备 `Fully_powered_on` 默认配置。
   - 新软件会在旧工具中选择对应 `Serial Num`。
   - 新软件会尝试自动选择 `Fully_powered_on`，点击 `Start ALL`。
   - 新软件会按启用通道数每通道等待 10 秒，等程控电源完成上电动作，再关闭旧软件。
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

打包后程序会自动从 EXE 所在目录、上级目录中查找 `config` 文件夹和文件名包含 `Auto_Power_On_Off_Tool` 的旧工具 exe，优先使用 `Auto_Power_On_Off_Tool.exe`，因此可以放在 `开关机执行工具\dist` 目录运行。
