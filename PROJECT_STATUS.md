# 项目开发状态

更新时间：2026-07-11

## 当前结论

- 全包升级已完成源码侧迁移：主程序使用 pySerial 内置串口状态机与 TFTPy，`Tftp指令` 为设备从本机 Server 拉取，`Tftp Put` 为本机 Client 向固定 `192.168.1.1` 推送；两种模式仍独立。真实设备验收待执行。
- “页面升级”已接入 UBUS 批量升级流程，支持按主界面勾选通道自动启用对应网卡、并行上传固件、触发升级并等待设备重启上线；用户已确认退出样机 Web 管理界面后，原 `Access denied` 样机可升级成功。
- 最新程序：`开关机执行工具\dist\LineCheckAssistant.exe`
- 自动化测试：迁移后 100 项单元测试通过；新增串口分片 marker、独占写锁、状态机时序和 TFTPy 本机端到端传输覆盖。
- 打包后不要在当前 PC 运行 EXE，只需确认打包成功并报告输出路径。
- VS Code 已同时配置 `LineCheckAssistant`（主程序）和独立 `serial_upgrade.py` 的运行入口；两者共用 `.venv_serial_upgrade`，主程序依赖由 `Cheating_machine_execution_tool\requirements.txt` 统一安装。

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
- 全包升级按主界面通道顺序逐台执行；每台前仍临时改写 `config/network_card_ip.ini`，让旧开关机工具只给当前样机上电并等待 10 秒。pySerial 直接处理 boot 进入、登录、串口 marker 和最终登录；TFTPy Server/Client 均显式绑定当前通道 IP，资源由本程序回收。
- 勾选“恢复出厂”时，内置状态机会在最终系统登录成功后发送 `firstboot -y;reboot`，等待 1 秒后回车，并等待 8 秒再完成。
- 旧开关机工具 exe 支持按文件名关键字识别，只要文件名包含 `Auto_Power_On_Off_Tool` 且后缀为 `.exe` 即可，优先使用 `Auto_Power_On_Off_Tool.exe`，兼容原 `Auto_Power_On_Off_Tool(2).exe`。
- 串口映射规则为 `vlan101 -> COM1`、`vlan102 -> COM2`，以此类推。
- `Cheating_machine_execution_tool\test_boot_upgrade\serial_upgrade.py` 可在 VS Code 中直接运行；工作目录固定为 `test_boot_upgrade`，用于正确加载同目录下的 `TFTPD322_NEW\tftpd32.exe`。

## 内置串口当前配置

- 终端页签使用 VLAN 名称，例如 `vlan101`、`vlan102`。
- 串口参数：115200、8N1、无 CTS/DSR/XON 流控。
- 每个 COM 仅一个读取线程；终端窗口订阅同一会话，升级期间手动发送锁定。
- F 盘存在时，日志目录为 `F:\Aouxue\开关机环境搭建工具\开关机执行工具\样机串口日志`。
- F 盘不存在时，自动创建并使用 `D:\样机串口日志`。
- 日志文件按 VLAN、升级时间或 COM 保存，并在每条记录前写入本机时间戳。

## 待继续完善

- UBUS 页面升级已支持并行；多台样机并发 TFTP 传输/并发全包升级暂未实现。
- 不同项目、样机型号对应的具体升级步骤、命令和校验规则待后续完善。
- 异常场景仍需继续补强：TFTP 失败、登录失败、串口断开、样机长时间不回显等。

## 明日继续入口

- 开发记录：`DEVELOPMENT_LOG.md`
- 主程序：`Cheating_machine_execution_tool\run_line_check_assistant.py`
- 串口/TFTP 核心：`Cheating_machine_execution_tool\src\core`
- 串行升级服务：`Cheating_machine_execution_tool\src\services\serial_upgrade_service.py`
- 完整测试：在 `开关机执行工具` 目录运行 `python -m unittest discover -s tests -v`
- 打包：在 `开关机执行工具` 目录运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1`
- 独立串口升级工具：在 VS Code 中选择 `serial_upgrade` 调试配置，或打开 `Cheating_machine_execution_tool\test_boot_upgrade\serial_upgrade.py` 后直接运行。
