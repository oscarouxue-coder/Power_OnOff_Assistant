# 项目开发状态

更新时间:2026-07-11(精简版,供新模型接手)

---

## 1. 项目目标

桌面工具 **"开关机测试环境搭建助手"** (`LineCheckAssistant`),面向嵌入式光网络样机的测试环境搭建与运维,统一替代过去 SecureCRT + Tftpd64 + Auto_Power_On_Off_Tool.exe 的多工具方案。

核心功能:
- 多通道样机的批量上/下电(程控电源,COM101–COM116)
- 线路检查与配置管理
- 样机批量升级:
  - **页面升级**(UBUS 并行)
  - **全包升级**(`Tftp指令` 拉取 / `Tftp Put` 推送,串行)
- **OLT 侧 ONU 注册**(Telnet + ZTE OLT 命令)
- 实时串口日志(多 VLAN Tab)

---

## 2. 当前实现进度(~90%)

| 模块 | 状态 | 备注 |
|---|---|---|
| 主程序框架 / UI / 持久化 | ✅ 完成 | Tkinter,`app.py` ~2055 行 |
| 程控电源直连(自动上/下电) | ✅ 完成,真实样机验收通过 | 上电无额外等待,相邻帧 1s |
| 页面升级(UBUS 并行) | ✅ 完成,真实样机验收通过 | UBUS 触发可能因浏览器仍登录 Web 报 `Access denied` |
| 全包升级 + **Tftp指令**(拉取) | ✅ 代码完成 | **程控电源上电驱动**,电源完成后 1s 缓冲,boot 登录必须经过 UserName/Password 提示符 |
| 全包升级 + **Tftp Put**(推送) | ✅ 代码完成 | 用户手动上电,reboot + 每秒回车中断,login 完成后发 tftp |
| ONU 注册完整流程(ZTE OLT) | ✅ 完成 | 含离线清理后重注册、`write` 保存提示 |
| 多 VLAN 串口终端 | ✅ 完成 | 几何持久化、最小尺寸、日志目录切换 |
| 单元测试 | ✅ **121 项全过** | `python -m unittest discover -s tests` |
| **TFTP 服务 INADDR_ANY 回退** | ✅ 完成 | 配置 IP 不在本机时回退 `0.0.0.0`,避免 `[WinError 10049]` |
| **boot 登录串口异常安全化** | ✅ 完成 | 串口未打开/已关闭时转 CommandResult 失败,daemon 线程不再裸抛异常 |
| 多台并发升级 | ❌ 未开始 | 当前为串行 |
| 异常场景加固(超时/串口掉线) | ❌ 未开始 |
| 差异化升级模板 | ❌ 未开始 |

---

## 3. 关键文件

```
f:\Aouxue\Power_OnOff_Assistant\
├── PROJECT_HANDOFF.md                      # 完整历史交接上下文(冗长)
├── PROJECT_STATUS.md                       # 本文件
├── DEVELOPMENT_LOG.md                      # 每次改动的追加日志
├── AGENTS.md                               # 目录/开发规则
├── Cheating_machine_execution_tool/
│   ├── run_line_check_assistant.py         # 主入口(只 import app.main)
│   ├── requirements.txt                    # pyserial==3.5, tftpy==0.8.7, requests>=2.31,<3
│   ├── line_check_assistant/
│   │   ├── app.py                          # 主界面 + 所有窗口编排 + 持久化
│   │   ├── paths.py                        # 统一配置目录(Auto_power_on_off_tool/config)
│   │   ├── network_ops.py                  # OLT Telnet / 网卡静态 IP / vlan139→COM39 等映射
│   │   ├── page_upgrade.py                 # 页面升级(UBUS 并行)
│   │   ├── securecrt_automation.py         # 旧兼容层(不再主动调用)
│   │   ├── upgrade_cleanup.py              # 同上
│   │   ├── *_store.py                      # ONU注册 / 样机升级 / 通道配置 持久化
│   │   └── ...
│   ├── src/                                # 内置核心逻辑
│   │   ├── config.py                       # DEFAULT_LOG_DIR = Path(r"D:\Serial_Log")
│   │   ├── core/
│   │   │   ├── power_supply.py             # 程控电源 16 通道协议帧,【禁止修改】
│   │   │   ├── serial_transport.py         # 串口状态机 + vlan→COM 映射 + PySerialSession
│   │   │   └── tftp_transport.py           # TFTPy Server/Client + INADDR_ANY 回退
│   │   ├── models/serial_models.py         # SerialSettings / SerialEvent / FullPackageUpgradeRequest
│   │   ├── services/
│   │   │   ├── power_on_service.py         # power_on_selected_channels / turn_*_channels
│   │   │   └── serial_upgrade_service.py   # 全包升级 + 串行编排(见 §4)
│   │   └── ui/serial_terminal.py           # 多 VLAN 串口终端窗口
│   ├── Auto_power_on_off_tool/             # 【不修改,仅参考】
│   │   ├── config/                         # 运行时配置(INI,只保留已勾选通道)
│   │   │   ├── network_card_ip.ini
│   │   │   ├── onu_registration.ini        # Git 忽略(本机凭据)
│   │   │   └── sample_upgrade_settings.ini # Git 忽略
│   │   └── Auto_Power_On_Off_Tool.py
│   └── tests/                              # 单元测试 121 项
├── ~/.aouxue_serial_terminal.json          # 串口终端几何 + 日志目录(Git 忽略)
└── .vscode/launch.json                     # `LineCheckAssistant` 与 `serial_upgrade` 两个调试入口
```

---

## 4. 全包升级两条链路(关键)

入口:`run_single_full_package_upgrade(request, session_manager, ...)` in `src/services/serial_upgrade_service.py`。按 `request.transfer_method` 分支。

### 4.1 Tftp指令(样机拉取) — 使用程控电源

实现位置:同文件私有函数 `_run_tftp_command_with_power_supply(...)`。

```
acquire_control(port) → session
  ↓
spawn boot_worker 线程,等 power_started Event
  ↓
power_on_selected_channels(power_serial_port, [power_channel])
  on_channel_powered → power_started.set()
  ↓
sleep_fn(1.0)                       ← 电源动作完成后 1 秒缓冲
  ↓
power_started.set()                  ← 兜底(若 on_channel_powered 因通道号未触发则由它兜底)
  ↓
worker.join → wait_for_boot_login() 轮询:
   每隔 1s 写 \r,等提示符
   *仅* 在看到 username/user name/passvord/password 才走 _login_boot
   看到残余 # / > 不直接 return(避免把 tftp 发到未登录的 UserName 提示符上)
  ↓
_login_boot(每条指令间 sleep 1.0s):
  user → 1.0s → \r → passvord → 1.0s → pass → 1.0s → \r → #/>
  ↓
prepare_tftp_network(server_interface, tftp_server_ip)
  ↓
TftpServerHandle.start():
  *预检* bind_ip 是否本机可绑,不可绑则回退到 INADDR_ANY(""),再不可绑也尝试回退
  ↓
TFTPy Server 监听 :69,文件名映射为 tclinux_allinone
  ↓
controller.send_tftp_command_and_wait("tftp <ip>:tclinux_allinone")
  ↓
server.stop()
  ↓
controller.monitor_post_tftp(90s)
  ├─ 命中 "boot" / "bood" → send "reset" → sleep 120s
  └─ 未命中 → power_on_selected_channels 再上电 + sleep 120s
  ↓
controller.login_final_system(final_username, final_password)
  ↓
controller.restore_factory_if_enabled(restore_factory)
```

异常安全:整段循环包在 try/except(`RuntimeError` 与 `Exception`)中,**串口层异常转 CommandResult 失败并 `controller.cancel()`**;`boot_worker` 兜底 try/except,防止 daemon 线程因未捕获异常死亡。

### 4.2 Tftp Put(本机推送) — 不操作程控电源

```
开串口 → login_final_system(超级用户名/密码)
  ↓
controller.session.send_line("reboot"); sleep 3s
  ↓
interrupt_boot_with_enter(enter_interval=1.0, timeout=BOOT_LOGIN_TIMEOUT)
  ↓
controller._login_boot()(同样 1.0s 节拍、异常安全)
  ↓
prepare_tftp_network(...)
  ↓
upload_firmware(firmware_path, "192.168.1.1", ...)  # TFTPy Client 推送到设备
  ↓
monitor_post_tftp()         # 命中/未命中均不再操作程控电源
  ↓
sleep 120s → login_final_system → restore_factory
```

**Tftp Put 分支依赖用户先手动给样机上电**(忘记上电会等到 `login_final_system` 超时 ~900s)。

---

## 5. 已完成 / 未完成 / 当前问题

### ✅ 已完成(本次会话要点)
- 程控电源直连、自动上/下电(0 等待 / 1s 间隔 / 无全断电帧)
- 页面升级 UBUS 并行(已真实样机验收)
- 全包升级两条链路(Tftp指令 用电源 / Tftp Put 手动)
- **TFTP 服务 INADDR_ANY 回退**:`network_card_ip` 配置与本机网卡不一致时(典型 vlan139→COM39 不存在的情况,vlan→COM 仅覆盖 101–116)改为 bind `0.0.0.0`,日志中显示实际监听 IP
- **boot 登录时间收紧**:用户名/密码与回车间各 1.0s
- **boot 登录 orphan 提示符剔除**:不再因瞬态 `# / >` 误判 boot 就绪,避免 `tftp ...` 被打到未登录的 UserName 提示符
- **boot 登录串口异常安全化**:`wait_for_boot_login` / `_login_boot` / `boot_worker` 三层都包了 try/except,串口层 `RuntimeError` 转 `CommandResult(ok=False)`;`write()` 错误信息明确区分"未打开(可能端口不存在/驱动异常)"与"已关闭"
- 电源 ON 后 1 秒再触发 worker 发送第一帧 `\r`(现场需求)
- 多 VLAN 串口终端 + 几何持久化 + 日志目录切换 + 全局日志 `D:\Serial_Log`
- ONU 注册(查询 / 注册 / 离线清理后重注册 / `write` 保存)
- 单元测试 **121 项全过**,覆盖串口状态机、独占写锁、TFTPy 端到端、程控电源协议帧、上/下电顺序、升级编排、boot 登录异常路径

### ❌ 未完成
- 多台并发 TFTP / 并发升级(目前只串行,经真实样机验证)
- 异常场景加固(TFTP 失败 / 登录失败 / 串口断开 / 长时间不回显)
- 不同项目 / 样机型号的差异化升级模板
- vlan→COM 映射的预检或可配置化(`vlan_to_serial_port` 当前写死 `vlan{N} → COM{N-100}`,仅支持 vlan101–vlan116,vlan139 等会落到不存在的 COM 端口,只能靠 TFTP 服务 INADDR_ANY 回退 + 串口异常报错暴露)

### ⚠ 当前问题 / 已知风险
- 仅 Windows;`os.startfile`,`Get-NetAdapter` 等用了 Win API
- `~/.aouxue_serial_terminal.json` D 盘不可写时**当前是静默失败**,应改为弹错误框(优化项)
- Tftp指令 链路在本次代码收紧后**尚未在真实样机上重新验收**:`wait_for_boot_login` 早退路径移除、电源后 1s 缓冲、orphan 提示符硬剔除均需要在 vlan101–vlan116 实物样机回归一次

---

## 6. 重要技术决策与限制

- **平台**:Windows 10/11;Python 3.9+(`.venv_serial_upgrade`)
- **依赖**:`pyserial==3.5`、`tftpy==0.8.7`(0.8.7 是验证过的 Windows 兼容版,**不要升级**)、`requests>=2.31,<3`
- **不依赖**:SecureCRT、Tftpd64、`Auto_Power_On_Off_Tool.exe`、PyQt、UI Automation
- **管理员权限**:切网卡静态 IP 必须
- **程控电源**:COM101–COM116,`19200 8N1`,协议字节**禁止修改**(在 `src/core/power_supply.py`)
- **样机串口**:COM1–COM16,`115200 8N1`,`vlan101 → COM1` ... `vlan116 → COM16`(`vlan_to_serial_port`)
- **TFTPy**:UDP 69,需 Windows 防火墙放行
- **目录规则**:`src/ui` 只放界面;`src/core` 放底层能力(ping/ssh/telnet/串口/升级);`src/services` 放业务流程编排;`src/models` 放数据结构
- **配置**:`RawConfigParser` 写入,避免 `%` 等被当插值;配置文件只保留**已勾选通道**;**所有本机凭据类配置都 Git 忽略**
- **日志目录**:统一 `D:\Serial_Log`,通过 `src/config.py::DEFAULT_LOG_DIR` 集中管理
- **MEMORY 规则**:默认不自动 git commit,等用户说"提交"再执行
- **不修改**:`Auto_power_on_off_tool/` 下任何文件;`src/core/power_supply.py` 协议字节
- **扩展点**:新增全局默认往 `src/config.py` 追加常量

---

## 7. 运行 / 测试 / 继续开发

### 7.1 直接运行源码
```
cd Cheating_machine_execution_tool
python run_line_check_assistant.py
```
VS Code 已有 `LineCheckAssistant` 调试入口(工作目录已固定)。

### 7.2 完整单元测试
```
cd Cheating_machine_execution_tool/tests
python -m unittest discover -s .        # 期望 121 项 OK
```

### 7.3 打包
```
cd Cheating_machine_execution_tool
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1
```
打包后**不要在当前 PC 运行 EXE**,只需确认成功并报路径(`开关机执行工具\dist\LineCheckAssistant.exe`)。

### 7.4 继续开发的入口
- 全包升级核心:`src/services/serial_upgrade_service.py`(`run_single_full_package_upgrade` / `_run_tftp_command_with_power_supply` / `SerialUpgradeController._login_boot` / `wait_for_boot_login` / `boot_worker`)
- 串口底层:`src/core/serial_transport.py`(包括 `vlan_to_serial_port` 和 `write()` 错误信息)
- TFTP 底层:`src/core/tftp_transport.py`(包括 INADDR_ANY 回退)
- 串口终端:`src/ui/serial_terminal.py`
- 全局配置:`src/config.py`
- 实时日志入口:`DEVELOPMENT_LOG.md`(每次改动顶部追加,模板见文件头)
- 完整历史上下文:`PROJECT_HANDOFF.md`(可选,作为深度背景)

### 7.5 改动前先确认的事
1. 是否要修改 `src/core/power_supply.py`? — 通常**不要**,除非协议本身要改
2. 是否动 `src/core/serial_transport.py::vlan_to_serial_port`? — 当前写死支持 vlan101–vlan116,如果支持 vlan139 等需要拓展
3. 是否引入新依赖? — 优先复用现有(`pyserial` / `tftpy` / `requests`),不升级版本
4. 是否动 git? — 默认不 commit,等用户指示
5. 全包升级链路上的异常要先在 `SerialUpgradeController` 的方法里捕获,再 `controller.cancel()`,不要让裸异常穿透到 `boot_worker` daemon 线程

---

## 8. 接手第一步(摘要)

1. 读本文件 → `DEVELOPMENT_LOG.md`(只看当天条目即可)→ `AGENTS.md`
2. 看 `PROJECT_HANDOFF.md` 了解完整对话上下文(可选)
3. 跑 `cd Cheating_machine_execution_tool/tests && python -m unittest discover -s .` → 期望 121 OK
4. 跑 `cd Cheating_machine_execution_tool && python -m py_compile run_line_check_assistant.py`(只编译,不启动 GUI)
5. 不要自动 commit,等用户指示
