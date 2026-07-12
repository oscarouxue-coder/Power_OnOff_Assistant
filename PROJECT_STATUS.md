# 项目状态

更新时间:2026-07-11(精简版,供新模型接手)

---

## 1. 项目目标与当前实现进度

桌面工具 **"开关机测试环境搭建助手"** (`LineCheckAssistant`),面向嵌入式光网络样机的测试环境搭建与运维,统一替代过去 SecureCRT + Tftpd64 + Auto_Power_On_Off_Tool.exe 的多工具方案。

**核心功能**:多通道程控电源上/下电、线路检查、样机批量升级(页面升级 UBUS 并行 / 全包升级 Tftp指令 与 Tftp Put)、OLT 侧 ONU 注册(ZTE)、多 VLAN 串口终端。

| 模块 | 状态 |
|---|---|
| 主程序框架 / UI / 持久化(Tkinter) | ✅ 完成 |
| 程控电源直连(自动上/下电,COM101–COM116) | ✅ 真实样机验收 |
| 页面升级(UBUS 并行) + 前置网卡同网段 | ✅ 完成 |
| 全包升级 + Tftp指令(串行/两台并行) | ✅ 真实样机验收(串行);并行代码完成待真实验收 |
| 全包升级 + Tftp Put + 前置下电+上电 | ✅ 真实样机验收（多台串行） |
| ONU 注册完整流程(ZTE OLT) | ✅ 完成 |
| 多 VLAN 串口终端 | ✅ 完成 |
| 单元测试 **148 项** | ✅ 全部通过 |
| 多台并发升级(>2 台) | ❌ 未开始 |
| 异常场景加固(超时/串口掉线/登录失败) | ❌ 未开始 |
| 差异化升级模板(不同项目/型号) | ❌ 未开始 |
| vlan→COM 映射可配置化(vlan139 等) | ❌ 未开始 |

---

## 2. 关键文件及其作用

```
f:\Aouxue\Power_OnOff_Assistant\
├── AGENTS.md                         # 目录/开发规则(必读)
├── PROJECT_STATUS.md                 # 本文件
├── DEVELOPMENT_LOG.md                # 每次改动顶部追加
├── Cheating_machine_execution_tool/
│   ├── run_line_check_assistant.py   # 主入口(只 import app.main)
│   ├── requirements.txt              # pyserial==3.5, tftpy==0.8.7, requests>=2.31,<3
│   ├── build_line_check_assistant.ps1 # 打包脚本
│   ├── line_check_assistant/
│   │   ├── app.py                    # 主界面 + 所有窗口编排 + 持久化(~2055 行)
│   │   ├── paths.py                  # 统一配置目录(Auto_power_on_off_tool/config)
│   │   ├── network_ops.py            # OLT Telnet / 网卡静态 IP / prepare_network_for_sample / vlan→COM39 等
│   │   ├── page_upgrade.py           # 页面升级(UBUS 并行 + 前置同网段)
│   │   ├── *_store.py                # ONU注册/样机升级/通道配置 持久化
│   │   └── config_store.py           # 通道配置
│   ├── src/                          # 内置核心逻辑
│   │   ├── config.py                 # DEFAULT_LOG_DIR = Path(r"D:\Serial_Log")
│   │   ├── core/
│   │   │   ├── power_supply.py       # 程控电源 16 通道协议帧【禁止修改】
│   │   │   ├── serial_transport.py   # 串口状态机 + vlan→COM 映射 + PySerialSession
│   │   │   └── tftp_transport.py     # TFTPy Server/Client + INADDR_ANY 回退 + 数据 socket VLAN IP 绑定
│   │   ├── models/serial_models.py   # SerialSettings / SerialEvent / FullPackageUpgradeRequest
│   │   ├── services/
│   │   │   ├── power_on_service.py   # 上/下电(turn_*_channels / power_on_selected_channels)
│   │   │   └── serial_upgrade_service.py # 全包升级核心(run_single_full_package_upgrade)
│   │   └── ui/serial_terminal.py     # 多 VLAN 串口终端窗口
│   ├── Auto_power_on_off_tool/       # 【不修改,仅参考】
│   │   ├── config/                   # 运行时配置(INI,只保留已勾选通道)
│   │   │   ├── network_card_ip.ini
│   │   │   ├── onu_registration.ini  # Git 忽略(本机凭据)
│   │   │   └── sample_upgrade_settings.ini # Git 忽略
│   │   └── Auto_Power_On_Off_Tool.py
│   └── tests/                        # 单元测试 143 项
└── .vscode/launch.json               # `LineCheckAssistant` 调试入口
```

---

## 3. 已完成、待完成和当前问题

### ✅ 已完成(要点)
- 程控电源直连(0 等待 / 1 秒间隔 / 无全断电帧);全包升级断电重启仅向当前通道发送开关帧
- 页面升级 UBUS 并行(真实样机验收);**升级前 `prepare_network_for_sample()` 启用网卡 + 设置 PC 静态 IP 到样机管理 IP 所在网段**
- 全包升级 `Tftp指令` 多台样机串行 + 两台并行(串行已真实样机验收,并行代码完成待真实两台验收);共享电源协调器仅串行化同一 COM 口的关闭/开启帧
- **`Tftp Put` 升级前对当前通道执行下电 + 上电**(走 `_power_cycle_current_channel()`);等待 `UserName` 后登录 boot，再由 TFTPy 推送固件；**多台串行真实样机验收通过**
- TFTP 服务 INADDR_ANY 回退(避免 `[WinError 10049]`);数据 socket 强制绑定 VLAN IP;严格绑定前等 IP 就绪(0.5 秒 × 15 秒)
- boot 登录:程控电源动作完成 1 秒后才探测;`UserName` 稳定窗口 1 秒(剔除夹带旧密码);密码提示符新游标握手；`Tftp Put` 前置上电后也先等待 1 秒、循环回车确认 `UserName`，写 boot 用户名前先记录密码游标、写 boot 密码前先记录 shell 游标，以覆盖同批 `Password:` / `ECNT>`，随后按同事 `serial_upgrade.py` 的 boot 凭据时序登录，再继续主程序 TFTPy 上传
- 多 VLAN 串口终端 + 几何持久化 + 日志目录切换(默认 `D:\Serial_Log`);目录不可写时弹窗；全包升级自动打开的终端在本批串口释放后自动关闭，手动终端不受影响
- ONU 注册(查询 / 注册 / 离线清理后重注册 / `write` 保存提示)
- 单元测试 **143 项全过**

### ❌ 待完成
- 多台并发 TFTP / 并发升级(>2 台)
- 异常场景加固(TFTP 失败 / 登录失败 / 串口断开 / 长时间不回显)
- 不同项目 / 样机型号的差异化升级模板
- vlan→COM 映射的预检或可配置化(当前 `vlan_to_serial_port` 写死 `vlan{N} → COM{N-100}`,仅 vlan101–vlan116;vlan139 等落到不存在 COM 端口,只能靠 TFTP INADDR_ANY 回退 + 串口报错暴露)

### ⚠ 已知风险 / 当前问题
- 仅 Windows;`os.startfile` / `Get-NetAdapter` 等用了 Win API
- `Tftp指令` 两台并行代码已写,**待真实两台独立 VLAN 样机验收**

---

## 4. 重要技术决策与限制

- **平台**:Windows 10/11;Python 3.9+;`.venv_serial_upgrade`
- **依赖**:`pyserial==3.5`、`tftpy==0.8.7`(**不要升级**,已验证 Windows 兼容)、`requests>=2.31,<3`
- **不依赖**:SecureCRT、Tftpd64、Auto_Power_On_Off_Tool.exe、PyQt、UI Automation
- **管理员权限**:切网卡静态 IP 必须
- **程控电源**:COM101–COM116,`19200 8N1`,协议字节**禁止修改**(`src/core/power_supply.py`)
- **样机串口**:COM1–COM16,`115200 8N1`,`vlan{N} → COM{N-100}`(仅 vlan101–vlan116)
- **TFTPy**:UDP 69,需 Windows 防火墙放行
- **目录规则**:`src/ui` 只放界面;`src/core` 放底层能力;`src/services` 放流程编排;`src/models` 放数据结构
- **配置**:`RawConfigParser` 写入(避免 `%` 被插值);配置文件只保留已勾选通道;**本机凭据类配置 Git 忽略**;恢复出厂启用且命令实际写入串口后，主程序执行日志显示 `TX firstboot -y;reboot`
- **日志目录**:统一 `D:\Serial_Log`,`src/config.py::DEFAULT_LOG_DIR` 集中管理
- **Git**:默认不自动 commit,等用户说"提交"再执行
- **禁止修改**:`Auto_power_on_off_tool/` 下任何文件;`src/core/power_supply.py` 协议字节
- **扩展点**:新增全局默认往 `src/config.py` 追加常量
- **网络准备**:页面升级和全包升级都用 `network_ops.prepare_network_for_sample()` 统一封装「启用网卡 → 设静态 IP → 缓冲」;全包 TFTP 还要走 `serial_upgrade_service.prepare_tftp_network()` 加 15 秒严格 bindable 预检
- **电源周期**:全包升级统一通过 `_power_cycle_current_channel()` 复用 `power_on_selected_channels`(串行)或 `UpgradePowerCycleCoordinator`(并行)

---

## 5. 运行、测试和继续开发的方法

### 5.1 直接运行源码
```bash
cd Cheating_machine_execution_tool
python run_line_check_assistant.py
```
VS Code 已有 `LineCheckAssistant` 调试入口(工作目录已固定)。

### 5.2 完整单元测试
```bash
cd Cheating_machine_execution_tool/tests
python -m unittest discover -s .        # 期望 143 项 OK
```

### 5.3 打包
```bash
cd Cheating_machine_execution_tool
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1
```
**打包后不要在当前 PC 运行 EXE**,只需确认成功并报路径(`dist\LineCheckAssistant.exe`)。

### 5.4 改动入口
- 全包升级核心:`src/services/serial_upgrade_service.py`(`run_single_full_package_upgrade` / `_run_tftp_command_with_power_supply` / `_power_cycle_current_channel` / `SerialUpgradeController._login_boot` / `wait_for_boot_login`)
- 页面升级:`line_check_assistant/page_upgrade.py`(`run_single_page_upgrade` / `PageUpgradeRequest` 已含 `subnet_mask`)
- 网络准备共用 helper:`line_check_assistant/network_ops.py::prepare_network_for_sample`(升级 / 线路检查复用)
- 串口底层:`src/core/serial_transport.py`(包括 `vlan_to_serial_port` 和 `write()` 错误信息)
- TFTP 底层:`src/core/tftp_transport.py`(INADDR_ANY 回退 + 数据 socket VLAN IP 绑定 + 严格绑定前 IP 就绪等待)
- 串口终端:`src/ui/serial_terminal.py`
- 全局配置:`src/config.py`
- 改动日志:`DEVELOPMENT_LOG.md`(每次顶部追加,模板见文件头)

### 5.5 改动前先确认
1. 是否要修改 `src/core/power_supply.py`? — 通常**不要**
2. 是否动 `vlan_to_serial_port`? — 当前写死支持 vlan101–vlan116;支持 vlan139 等需拓展
3. 是否引入新依赖? — 优先复用 `pyserial`/`tftpy`/`requests`,**不升级版本**
4. 是否动 git? — 默认不 commit,等用户指示
5. 全包升级链路异常先在 `SerialUpgradeController` 方法里捕获 → `controller.cancel()`,不要让裸异常穿透到 `boot_worker` daemon 线程

### 5.6 接手第一步
1. 读本文件 → `DEVELOPMENT_LOG.md`(只看当天条目)→ `AGENTS.md`
2. 跑 `cd Cheating_machine_execution_tool/tests && python -m unittest discover -s .` → 期望 143 OK
3. 跑 `cd Cheating_machine_execution_tool && python -m py_compile run_line_check_assistant.py`(只编译,不启动 GUI)
4. 不要自动 commit,等用户指示
