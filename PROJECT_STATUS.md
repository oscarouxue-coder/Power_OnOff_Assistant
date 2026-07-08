# 项目开发状态

更新时间：2026-07-08

## 当前结论

- “全包升级 + Tftp指令 + 多台串行升级”流程已由用户在真实设备上验收通过；“全包升级 + Tftp Put”已接入同一套串行流程，目标设备 IP 固定为 `192.168.1.1`，待真实设备验收。
- “页面升级”已接入 UBUS 批量升级流程，支持按主界面勾选通道自动启用对应网卡、并行上传固件、触发升级并等待设备重启上线；用户已确认退出样机 Web 管理界面后，原 `Access denied` 样机可升级成功。
- 最新程序：`开关机执行工具\dist\LineCheckAssistant.exe`
- 自动化测试：123 项全部通过。
- 打包后不要在当前 PC 运行 EXE，只需确认打包成功并报告输出路径。
- 独立 `serial_upgrade.py` 已配置 VS Code 运行入口，可直接用 `.vscode` 配置和专用本地 Python 环境启动。

## 已完成功能

- 软件名称为“开关机测试环境搭建助手”。
- 主界面通道勾选状态实时写入 `config\network_card_ip.ini`，配置文件只保留已勾选通道。
- 已移除“新增通道”和“保存通道配置”按钮。
- 主界面提供“样机升级”、“ONU注册”和“串口日志记录”功能入口。
- ONU注册窗口默认尺寸调整为 `896x580`；已支持输入 OLT IP（首次默认 `172.18.18.151`，后续恢复上一次关闭时保存的值）、用户名和密码，密码框支持小眼睛切换明文/密文显示，并提供 Telnet 连通性测试按钮；确认后会先测试 OLT Telnet 23 端口，连通后使用用户填写的用户名和密码登录 OLT，并下发 `configure terminal` 进入全局模式；OLT IP 右侧只显示 Telnet 连通性结果，登录和全局模式状态显示在查询入口下方，查询/注册状态栏支持长结果自动换行；“开始查询”会登录 OLT 并执行 `show gpon onu uncfg`，以复选框列表显示所有 PON 口下未注册 ONU 的接口、SN 和状态，并支持全选/取消全选；“开始注册”会对勾选 ONU 二次确认后优先按 SD-41 模板下发注册配置、业务 VLAN 和 `pon-onu-mng` 服务配置，若新增业务配置报错则自动查询并删除已注册但未在线 ONU，优先删除和新 ONU 同 PON 口的不在线 ONU，再删除其它 PON 口不在线 ONU，删除后重新注册新 ONU，避免跨 PON 口替换旧 ONU 配置；注册成功后会弹窗询问是否保存 OLT 最新配置，确认后先退出到 `ZXAN#` 执行模式再执行 `write` 写入启动配置；输入框内容保存到本机 `config/onu_registration.ini`，该文件不提交 Git。
- 样机升级界面支持项目、样机型号、超级用户名、密码显示切换、固件选择、目标 VLAN 和执行状态展示。
- 样机升级界面会恢复上一次关闭时的升级方式、固件传输方式、恢复出厂选项、超级用户名、密码和固件路径；本机状态保存到 `config/sample_upgrade_settings.ini`，该文件不提交 Git。
- “恢复出厂”显示会按真实保存值初始化；开始串行升级确认框会明确显示恢复出厂开启/关闭，避免界面显示和实际执行状态不一致。
- 选择“页面升级”并点击“开始升级”时，会按主界面已勾选通道生成 UBUS 批量升级任务：先启用通道对应网卡，再将通道 PC 静态 IP 用作请求绑定 IP、样机管理 IP 用作目标 IP，使用样机升级窗口账号密码登录 `/ubus/`，上传固件到 `/cgi-bin/cgi-upload`，触发 `Device.DeviceInfo.X_SDMC_Upgrade()` 并等待重启上线。
- 页面升级前应退出样机 Web 管理界面；实测浏览器仍登录 Web 管理界面时，UBUS 触发升级可能返回 `Access denied`。
- “全包升级 + Tftp指令”流程已支持并验收通过多台样机串行升级：按主界面通道顺序逐台执行；每台开始前临时改写 `config/network_card_ip.ini` 只保留当前通道，让旧开关机工具只给当前样机上电并等待 10 秒；随后自动进入 boot、配置 TFTP 网卡、启动 Tftpd64、下发 Tftp指令、传输完成后处理 boot reset 或重新上电、等待 120 秒后登录最终系统；串行结束或失败退出后恢复完整通道配置，自动关闭项目目录下的 Tftpd64；SecureCRT 脚本在完成后会自行请求关闭当前升级 Tab，Python 收尾只按本次登记到的新增 SecureCRT PID 做兜底关闭。
- “全包升级 + Tftp Put”流程已接入同一套多台串行升级外层流程：旧工具点击 `Start ALL` 后立即允许 SecureCRT 每隔 1 秒敲击回车；每台进入 boot 后不启动 Tftpd64，改为执行 Windows `tftp -i 192.168.1.1 put <升级固件路径>`，成功后继续复用 boot reset/重新上电、120 秒等待和最终系统登录确认。
- 勾选“恢复出厂”时，SecureCRT 会在最终系统登录成功后发送 `firstboot -y;reboot`，等待命令回显或最多 5 秒后回车，并额外等待 8 秒再写完成状态和关闭升级 Tab。
- 旧开关机工具 exe 支持按文件名关键字识别，只要文件名包含 `Auto_Power_On_Off_Tool` 且后缀为 `.exe` 即可，优先使用 `Auto_Power_On_Off_Tool.exe`，兼容原 `Auto_Power_On_Off_Tool(2).exe`。
- 串口映射规则为 `vlan101 -> COM1`、`vlan102 -> COM2`，以此类推。
- `Cheating_machine_execution_tool\test_boot_upgrade\serial_upgrade.py` 可在 VS Code 中直接运行；工作目录固定为 `test_boot_upgrade`，用于正确加载同目录下的 `TFTPD322_NEW\tftpd32.exe`。

## SecureCRT 当前配置

- 会话名称使用 VLAN 名称，例如 `vlan101`、`vlan102`。
- 串口参数：115200、8N1、无 CTS/DSR/XON 流控。
- 连接前基于 `Default_Serial` 写入会话配置，因此首次连接即可记录时间戳。
- `Start log upon connect`：勾选。
- `Start new log at midnight`：勾选。
- 日志模式：Append to file。
- 内置 `Timestamp each line`：关闭。
- `On each line`：`[%Y-%M-%D %h:%m:%s] `。
- F 盘存在时，日志目录为 `F:\Aouxue\开关机环境搭建工具\开关机执行工具\样机串口日志`。
- F 盘不存在时，自动创建并使用 `D:\样机串口日志`。
- 日志文件模板：`%H-%M%D.log`。
- SecureCRT 自动化使用 VBScript，不依赖 SecureCRT Python 脚本引擎。

## 待继续完善

- UBUS 页面升级已支持并行；多台样机并发 TFTP 传输/并发全包升级暂未实现。
- 不同项目、样机型号对应的具体升级步骤、命令和校验规则待后续完善。
- 异常场景仍需继续补强：TFTP 失败、登录失败、串口断开、样机长时间不回显等。

## 明日继续入口

- 开发记录：`DEVELOPMENT_LOG.md`
- 主程序：`开关机执行工具\line_check_assistant\app.py`
- SecureCRT 自动化：`开关机执行工具\line_check_assistant\securecrt_automation.py`
- SecureCRT 测试：`开关机执行工具\tests\test_securecrt_automation.py`
- 完整测试：在 `开关机执行工具` 目录运行 `python -m unittest discover -s tests -v`
- 打包：在 `开关机执行工具` 目录运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1`
- 独立串口升级工具：在 VS Code 中选择 `serial_upgrade` 调试配置，或打开 `Cheating_machine_execution_tool\test_boot_upgrade\serial_upgrade.py` 后直接运行。
