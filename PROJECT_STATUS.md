# 项目开发状态

更新时间：2026-06-27

## 当前结论

- “全包升级 + Tftp 拷贝命令 + 多台串行升级”流程已由用户在真实设备上验收通过。
- 最新程序：`开关机执行工具\dist\LineCheckAssistant.exe`
- 自动化测试：57 项全部通过。
- 打包后不要在当前 PC 运行 EXE，只需确认打包成功并报告输出路径。

## 已完成功能

- 软件名称为“开关机测试环境搭建助手”。
- 主界面通道勾选状态实时写入 `config\network_card_ip.ini`，配置文件只保留已勾选通道。
- 已移除“新增通道”和“保存通道配置”按钮。
- 主界面提供“样机升级”和“串口日志记录”功能入口。
- 样机升级界面支持项目、样机型号、超级用户名、密码显示切换、固件选择、目标 VLAN 和执行状态展示。
- 点击“开始升级”会按已勾选 VLAN 启动 SecureCRT 串口会话。
- “全包升级 + Tftp 拷贝命令”流程已支持并验收通过多台样机串行升级：按主界面通道顺序逐台执行；每台开始前临时改写 `config/network_card_ip.ini` 只保留当前通道，让旧开关机工具只给当前样机上电并等待 10 秒；随后自动进入 boot、配置 TFTP 网卡、启动 Tftpd64、下发 Tftp 拷贝命令、传输完成后处理 boot reset 或重新上电、等待 120 秒后登录最终系统；串行结束或失败退出后恢复完整通道配置并关闭 SecureCRT/Tftpd64。
- 串口映射规则为 `vlan101 -> COM1`、`vlan102 -> COM2`，以此类推。

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

- 多台样机并发 TFTP 传输/并发升级暂未实现。
- 不同项目、样机型号对应的具体升级步骤、命令和校验规则待后续完善。
- 异常场景仍需继续补强：TFTP 失败、登录失败、串口断开、样机长时间不回显等。

## 明日继续入口

- 开发记录：`DEVELOPMENT_LOG.md`
- 主程序：`开关机执行工具\line_check_assistant\app.py`
- SecureCRT 自动化：`开关机执行工具\line_check_assistant\securecrt_automation.py`
- SecureCRT 测试：`开关机执行工具\tests\test_securecrt_automation.py`
- 完整测试：在 `开关机执行工具` 目录运行 `python -m unittest discover -s tests -v`
- 打包：在 `开关机执行工具` 目录运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1`
