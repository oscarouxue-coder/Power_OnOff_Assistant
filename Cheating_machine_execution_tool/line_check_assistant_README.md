# 开关机测试环境搭建助手

## 当前实现

这是现有文件名包含 `Auto_Power_On_Off_Tool` 的旧开关机工具 exe 的前置辅助工具，用于：

- 读取和实时维护 `config/network_card_ip.ini` 的通道配置。
- 主界面顶部提供“样机升级”入口，支持“页面升级”和“全包升级”两类流程。
- 样机升级窗口支持自定义项目/型号、输入超级用户凭据、选择升级固件、同步主界面目标 VLAN，并显示实时状态和进度。
- 样机升级窗口会保存上一次关闭时的升级方式、固件传输方式、恢复出厂选项、超级用户名、密码和固件路径；恢复出厂显示会按真实保存值刷新，开始升级确认框会明确显示“恢复出厂：开启/关闭”；状态保存到本机 `config/sample_upgrade_settings.ini`，该文件不提交 Git。
- 选择“页面升级”后，点击“开始升级”会按主界面已勾选通道并行执行 UBUS 页面升级；每台样机会先启用通道对应网卡，再使用通道的 PC 静态 IP 作为请求绑定 IP、样机管理 IP 作为目标 IP，自动尝试 HTTP/HTTPS 登录 `/ubus/`，上传固件到 `/cgi-bin/cgi-upload`，调用 `Device.DeviceInfo.X_SDMC_Upgrade()`，查询升级状态并等待设备重启上线。
- 选择“全包升级 + Tftp指令”后，点击“开始升级”会按已勾选目标 VLAN 串行升级；每台样机会依次打开 SecureCRT 串口日志，自动上电并进入 boot，先把 Windows 对应 VLAN 网卡设置为通道 IP，再启动项目目录下的 `tftpd64.exe`；Tftpd64 软件内仅设置固件所在目录并保持 `Tftp Server` 页签，然后由 SecureCRT 下发 `tftp <通道对应VLAN的IP>:tclinux_allinone`。
- 选择“全包升级 + Tftp Put”后，点击“开始升级”会复用同一套串行升级流程；SecureCRT 进入 boot 后，软件会通过 Windows TFTP 客户端执行 `tftp -i 192.168.1.1 put <升级固件路径>`，不启动 Tftpd64。
- 多台样机串行升级会按主界面通道顺序执行，启动前弹出确认提示；每台开始前会临时改写 `config/network_card_ip.ini`，只保留当前上电通道，避免旧开关机工具 `Start ALL` 给其他通道上电；旧工具点击 `Start ALL` 后会立即允许 SecureCRT 每隔 1 秒敲击回车，避免错过 boot 进入窗口；全部完成或失败退出后会恢复用户选择的完整通道配置，并自动关闭项目目录下的 Tftpd64；SecureCRT 升级脚本写入 `DONE` 后会自行请求关闭当前升级 Tab，Python 收尾只按本次登记到的新增窗口 PID 做兜底关闭，未识别到新增 PID 时不会扩大范围关闭用户其它 CRT 会话。
- Tftp 传输完成后会先等待 1.5 分钟并持续监控 SecureCRT 串口；如果期间看到 `Boot`/`Bood` 字符，SecureCRT 会发送 `reset`，随后跳过自动重新上电，等待 120 秒后继续在当前串口窗口等待 `login` 并登录。
- Tftp 传输完成后，如果未检测到 boot reset，会自动重新上电并等待 120 秒后确认登录；重新上电和等待最终 `login` 期间 SecureCRT 保持实时串口监控，只有在需要捕获关键字或自动输入账号密码时才切回脚本同步等待模式。
- 最终系统登录阶段看到 `login` 后，会输入样机升级页面中的“超级用户名”和“密码”；如果登录失败，会间隔 2 秒继续重试，总共尝试 5 次后才判定失败；勾选“恢复出厂”时，会在最终系统登录成功后发送 `firstboot -y;reboot`，等待命令回显或最多 5 秒后回车，并额外等待 8 秒再写入完成状态和关闭 SecureCRT 升级 Tab。
- 启动 SecureCRT 后会等待可见窗口并尝试恢复、置前；未检测到窗口时明确报错，不再误报“串口日志已启动”。
- SecureCRT 自动化使用 Windows 自带的 VBScript 引擎，不要求目标 PC 额外安装 Python；标题仅为“SecureCRT”的错误对话框不会被误判为主窗口。
- SecureCRT 日志关闭内置紧凑时间戳，使用 `[%Y-%M-%D %h:%m:%s]` 行前缀输出本机时区的完整年月日时分秒；脚本会在连接前基于 `Default_Serial` 建立临时会话并预先配置日志，`Start log upon connect` 默认开启，因此首次连接即可写入时间戳。
- SecureCRT 会话名称直接使用主界面已勾选通道对应的 VLAN，例如 `vlan101`、`vlan102`。
- 主界面顶部提供“串口日志记录”入口，当前打开独立的日志配置占位窗口，后续扩展串口采集流程。
- 主界面顶部提供“ONU注册”入口，窗口默认尺寸为 `896x580`，支持输入 OLT IP（首次默认 `172.18.18.151`，后续恢复上一次关闭时保存的值）、用户名和密码，密码框支持小眼睛切换明文/密文显示；点击 Telnet 连通性测试并确认后，会先检查 OLT Telnet 23 端口，连通后使用用户填写的用户名和密码登录 OLT，并下发 `configure terminal` 进入全局模式；OLT IP 右侧只显示 Telnet 连通性结果，登录和全局模式状态显示在查询入口下方，查询/注册状态栏支持长结果自动换行；点击“开始查询”会登录 OLT 并执行 `show gpon onu uncfg`，以复选框列表显示所有 PON 口下未注册 ONU 的接口、SN 和状态，并支持全选/取消全选；勾选 ONU 后点击“开始注册”会二次确认并优先按已确认的 SD-41 模板下发注册配置、业务 VLAN 和 `pon-onu-mng` 服务配置，如新增业务配置命令报错，会自动查询并删除已注册但未在线的 ONU，优先删除和新 ONU 同 PON 口的不在线 ONU，再删除其它 PON 口不在线 ONU，删除后重新下发新 ONU 注册配置；注册完成后会询问是否保存 OLT 最新配置，用户确认后先退出到 `ZXAN#` 执行模式再执行 `write` 写入启动配置；ONU 注册输入框会保存到本机 `config/onu_registration.ini`，该文件不提交 Git；后续扩展结果导出流程。
- 为每个通道选择实际接入的 Windows 网卡名称。
- 网卡列表优先读取 `Get-NetAdapter -IncludeHidden`，可显示禁用、断开和隐藏网卡；界面显示状态，例如 `[Connected]`、`[Disconnected]`。
- 保存每个通道的 PC 静态 IP、样机管理 IP、子网掩码、启用状态。
- 自动启动旧软件，选择 `Fully_powered_on`，点击 `Start ALL`，按启用通道数每通道等待 10 秒后关闭旧软件；多台串行升级时每次只保留当前通道，因此每台上电等待 10 秒。
- 自动上电过程会实时输出日志，便于判断卡在打开窗口、选择下拉框还是点击按钮。
- 自动上电前会读取设备管理器 `端口(COM 和 LPT)` 中名称以 `Prolific` 开头的端口，让用户选择程控电源 COM 口，并同步到旧工具的 `Serial Num` 下拉框。
- 启动旧软件前会把 `config/config.ini` 中的 `Fully_powered_on` 移到 `[config]` 第一项，让旧软件启动后默认选择上电配置。
- 按通道切换指定网卡静态 IP，并 ping 样机管理 IP 判断线路是否正常。

当前版本使用 Python 标准库 `tkinter` 实现桌面界面，不需要安装 PySide6；页面升级功能依赖 `requests`。

## 运行方式

在 `开关机执行工具` 目录执行：

```powershell
python .\run_line_check_assistant.py
```

修改网卡静态 IP 需要管理员权限。正式检查线路时，请用管理员权限打开 PowerShell 或打包后的 EXE。

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
