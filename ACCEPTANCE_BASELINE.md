# Acceptance Baseline

更新：2026-08-30（同步项目负责人确认的网卡复用、升级、写参、ONU、测试项与DUT真实验收）

> 与 `PROJECT_STATUS.md` 的关系：本文按"实现 → 单测 → 真实样机验收"三态罗列验收证据与不变量，作为独立验收基线。`PROJECT_STATUS.md` 保留面向项目的进度叙述；两者冲突时以本文为准。
>
> **状态标签**：
> - **已确认验收**：单元测试通过 + `DEVELOPMENT_LOG.md` 中有"真实样机验收通过"明确字样（且日志可索引到具体日期）。
> - **已实现未验收**：代码与单测通过，但尚无真实样机验收记录。
> - **待确认**：代码或测试入口存在，验收未完成或依据缺失。

## 0. 最小可信回归基线

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python scripts\verify_baseline.py
```

预期 `ALL CHECKS PASSED`，其中包括编译、源码编译清单完整性、全量单元测试、已验收关键行为测试实际执行，以及 §1.3 / §1.4 不变量检查。测试数量会随测试增加变化，不在本文件固化；最近一次已记录结果见 `PROJECT_STATUS.md`，历史增量见 `DEVELOPMENT_LOG.md`。

## 1. 全局不可破坏规则

### 1.1 入口、运行与打包

- 入口：`Cheating_machine_execution_tool/run_line_check_assistant.py` → `line_check_assistant.app.main()`
- 依赖以 `requirements.txt` 为准；除主程序原有 `pyserial / tftpy / requests / openpyxl / xlrd` 外，第7项旧业务无 GUI 运行还需 `requests-toolbelt / paramiko / ping3 / pywifi / configobj / psutil`（许可证清单见 `THIRD_PARTY_NOTICES.md`）
- 打包：`powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1` → 单文件`dist\LineCheckAssistant.exe`、完整目录`dist\LineCheckAssistant_portable\`和可搬运的`dist\LineCheckAssistant_portable.zip`
- 构建便携版时必须重新生成`Auto_power_on_off_tool/config`，不得复制当前电脑的账号密码、OLT/源IP/ONU ID、钉钉与远程信息、固件/参数表路径、项目身份、网卡、串口或无线网卡绑定；业务命令模板和C600业务映射可保留。ZIP必须包含EXE、脱敏配置、`PORTABLE_README.txt`、第三方声明和EXE SHA256
- PyInstaller 5.10.1的Tkinter运行时要求EXE解压根目录存在`tcl`和`tk`；构建门禁必须从实际EXE归档命中`tcl\init.tcl`与`tk\tk.tcl`，不得使用会触发`pyi_rth__tkinter`启动失败的`_tcl_data/_tk_data`旧目标名
- **构建后不在当前 PC 运行任一新生成的 `LineCheckAssistant.exe`**，仅确认打包成功、ZIP结构、脱敏结果和哈希并报告路径
- 主界面内容区不得重复显示“openWRT老化测试环境搭建助手”和“配置测试通道、完成自动上/下电并检查全部线路”，“执行日志”标题下不得显示“运行步骤、检查结果和异常信息”；管理员权限状态必须位于常用工具栏右侧、视觉上在“刷新串口”左侧，权限就绪/缺失仍分别使用成功/危险样式，刷新串口与刷新网卡顺序不得改变
- **已实现未验收（2026-08-31）**：左侧“选择测试通道”列表右键任一有效行时，必须先将该行设为当前通道，再显示“打开本次开关机运行日志”。该操作只在`Auto_power_on_off_tool/test_results/device_N/`匹配当前通道的`device_N_command_results_*.log`，按文件名时间戳选择最新项，并仅交给Windows关联程序打开；不得读取后改写、重命名或清理旧结果文件，也不得触发电源、设备或全流程操作。成功、未找到和打开失败都必须写入主执行日志。
- **已确认验收（2026-08-13）**：项目负责人确认各功能入口居中显示需求验收通过。主界面“检查并执行测试”“自动上/下电”“样机升级”“写样机参数”“ONU注册”“串口日志”“DUT配置”和“测试项配置”首次创建必须相对当前主界面实际屏幕坐标居中，主界面位于副屏时不得跳回主屏；DUT和测试项配置必须先居中再执行已验收的客户区尺寸刷新，刷新后位置不得漂移；串口日志无有效历史位置或历史位置为`+0+0`时居中，用户主动移动后的其它有效历史位置仍按原规则恢复
- **已确认验收（2026-08-29）**：主界面统一监听自身及全部子控件的鼠标按下并调用`lift()`，不使用`focus_force()`抢走刚点击控件的焦点。已打开的非模态二级窗口与主界面可相互点击升到前台，主界面升层不会关闭或重建二级窗口；再次点击功能入口仍可把原二级窗口升到前方。生成批量参数表、选择程控电源及确认/警告等模态窗口继续保留`transient + grab`或等价模态语义，不因窗口层级切换绕过必要输入或危险确认

### 1.2 测试与目录基线

- 全量：`python -m unittest discover -s tests -v`；提交前统一执行 `python scripts\verify_baseline.py`
- `scripts/verify_baseline.py` 中的 `REQUIRED_BASELINE_TEST_IDS` 是已验收关键行为的最小回归集合。重构若需删除或改名其中任一测试，必须先补等价或更强的测试、同步该清单与本文件的对应验收项，并在 `DEVELOPMENT_LOG.md` 说明。
- `src/` 或 `line_check_assistant/` 新增 Python 源文件时，必须同步加入 `PY_COMPILE_FILES`；基线脚本会拒绝遗漏编译清单的新增源码。
- 首次开发环境执行 `powershell -ExecutionPolicy Bypass -File scripts\install_git_hooks.ps1`，使版本化 `.githooks/pre-commit` 在每次 `git commit` 前自动运行基线门禁。该本地钩子可被 Git 的 `--no-verify` 绕过，远端合并仍应要求 CI 基线检查通过。
- 测试数量和文件数量属于运行结果，不在本节固化；新增测试后由实施者在 `PROJECT_STATUS.md` 记录最近一次完整验证结果，并在 `DEVELOPMENT_LOG.md` 保留本轮增量依据
- 不动 `build/`、`dist/`、`logs/`、`.venv/`

### 1.3 协议不变性自检（grep 必须命中）

- `bbfdm.operate`（页面升级 UBUS 调用形式）
- `0.0.0.0` **不应**出现在并行 TFTP 监听 / 数据 socket 路径
- `tclinux_allinone`（`Tftp指令` 文件名映射）
- `192.168.1.1`（`Tftp Put` 远端固定）
- `vlan{N} -> COM{N-100}` 映射（`vlan_to_serial_port`）
- `MAX_PARALLEL_UPGRADES = 8` 与 `clamp_parallel_count`
- `source_address=(bind_ip, 0)` 应出现在 `TelnetSession`、`UbusHttpClient` 构造路径
- `Device.Firewall.<X_SDMC_>Security.AccessCtrl` 应出现在 `ubus_enable_telnet`

### 1.4 流程隔离与禁止合并

- **`Tftp指令`（样机从本机 TFTPy Server 拉固件）与 `Tftp Put`（本机 TFTPy Client 推固件至 `192.168.1.1:69`）绝不可合并**为同一传输流程
- 不依赖 SecureCRT、Tftpd64、旧 `Auto_Power_On_Off_Tool.exe` 或 UI Automation
- TFTP socket 严禁回退 `0.0.0.0`；客户端必须绑当前通道 VLAN IP
- 升级 / 重启 / 恢复出厂 / 批量写参必须保留确认弹窗 + 主执行日志；新增功能必须输出"关键阶段 / 实际命令 / 成功 / 跳过 / 失败"
- 线路检查、页面升级、全包升级 TFTP 网卡、写参用户/工厂模式切网、测试项执行及 DUT 配置共用的网卡准备必须先查询启用状态和 IPv4/前缀：完全匹配才可跳过，部分不满足只修复对应项，状态读取失败必须回退完整启用和静态 IP 设置；原有 `wait_for_bindable_ip`、Ping、登录、传输和结果校验不得因复用而跳过
- 仅 Windows 10/11；写网卡静态 IP 与执行 EXE 均需管理员权限

### 1.5 主程序入口自检

可分别打开且行为正常：页面升级、全包升级（Tftp指令 / Tftp Put）、写样机参数（默认 telnet 路径）、生成批量样机参数表、ONU 注册、串口日志记录、DUT 配置。

---

## 2. 功能验收清单

### 2.1 通道 / 网卡 / Ping

- **状态**：已确认验收（通道 / 网卡配置、线路 Ping、程控电源COM与VLAN分组、通道对应COM口选择/保存及串口流程联动，2026-08-13；线路 Ping 网卡准备按需复用，2026-08-30）
- **核心行为**：按 VLAN 标识已勾选通道；支持网卡刷新 / 子网配置 / Ping 样机管理 IP；现场配置写 `Auto_power_on_off_tool/config/network_card_ip.ini`。每个通道同时保存独立`serial_port`；历史配置缺字段时仅在运行期回退`vlan{N} → COM{N-100}`，不得因兼容读取擅自改写文件
- **已确认验收行为（2026-07-23）**：切换程控电源 `COM101` 时 VLAN 下拉候选仅显示 `VLAN101`–`VLAN108`；切换 `COM102` 时仅显示 `VLAN109`–`VLAN116`；切换不会自动改写已保存通道配置。
- **已确认验收行为（2026-07-24）**：程控电源 COM 为空时，VLAN 下拉候选展示所有已识别网卡；空值可保存到 `network_card_ip.ini`，不会被读取逻辑回填为 `COM101`。
- **已确认验收（2026-08-13）**：主界面通道表“通道对应 COM口”只读下拉、分组候选和保存通过现场验收；`COM101`候选仅`COM1`–`COM8`，`COM102`仅`COM9`–`COM16`，后续每组8口顺延，程控电源为空时展示`COM1`–`COM48`。切换程控电源只改变候选，不清空或改写已保存通道VLAN/COM；选择后实时保存。
- **布局不变量（2026-08-30）**：主界面“选择测试通道”列表宽度必须能完整显示启用通道的 `channel_N  VLANxxx / COMxx` 文本；扩大列表宽度不得改变通道勾选、双击切换、当前行选择、配置保存或执行目标语义。
- **边界与异常**：写网卡静态 IP 需管理员权限；源 IP 不可绑时**强提示人工检查 ini**，不回退 `0.0.0.0`
- **禁止破坏**：配置写入位置唯一（不可再新建 `Cheating_machine_execution_tool/config/`）
- **已确认验收（2026-08-30）**：线路 Ping 在网卡已启用且静态 IP/前缀完全匹配时，不重复启用或设置静态 IP；网卡/IP 不满足时按需修复后可正常 Ping。
- **对应测试**：`tests/test_app.py`、`tests/test_channel_config.py`、`tests/test_paths.py`、`tests/test_network_ops.py`

### 2.2 程控电源（COM101-COM116 直连）

- **状态**：已确认验收（直连程控电源、自动上/下电、同批次 COM 长连接复用、1-8 台并行、空 COM 手动重启确认后继续流程，2026-07-24）
- **核心验收行为**：
  - 主程序直连程控电源；移除旧 `Auto_Power_On_Off_Tool.exe` / UI Automation
  - 自动上电：相邻开启帧间隔 1 秒、取消末尾 10 秒启动等待 — 现场已验收
  - 自动下电：仅发关闭帧、相邻 1 秒，**不发全断电帧** — 现场已验收
  - 同批次程控电源 COM 由 `UpgradePowerCycleCoordinator` 持有长连接（`open` 仅一次，`close()` 幂等）— 现场已验收
  - 并行 1-8 台、默认 2 台（`MAX_PARALLEL_UPGRADES=8`、`clamp_parallel_count`）— 现场已验收
  - 未选择程控电源 COM 时，自动上/下电、全包升级和全流程管道均要求操作员确认样机已手动重启后才开始后续步骤，不打开任何程控电源串口（2026-07-24 已确认验收）
- **禁止破坏**：
  - 串口参数 **19200 8N1**
  - **不发送全断电帧**
  - 当前主程序的直连程控电源、升级和写参路径不得依赖旧 GUI 或旧 EXE；仅全流程子任务7可通过独立无 GUI service 子进程复用旧工具的 `test_case/common/clients` 业务类，且不得 import / 实例化 `Auto_Power_On_Off_Tool.py` 的 GUI 主类，不得改变本节直连路径“不发送全断电帧”的已验收行为
  - 样机串口优先使用通道显式`serial_port`；仅历史配置缺少该字段时允许回退`vlan{N} -> COM{N-100}`，不得忽略用户选择
- **对应测试**：`tests/test_power_supply.py`、`tests/test_app.py`、`tests/test_serial_upgrade_service.py`

### 2.3 串口日志 / 多 VLAN 终端

- **状态**：已确认验收（命令输入框回车发送，2026-07-15；3路以上高频WiFi日志滚动下按钮持续可操作、日志文件名及逐行时间戳，2026-08-29）/ 已实现未验收（其余）
- **核心验收行为**：
  - 命令输入框 Enter 发送 — 非空等价「发送」+ 自动清空；空字符串等价「回车」；自动升级占用与危险命令（`reboot` / `reset` / `firstboot` / `tftp` / `upgrade`）二次确认仍生效
  - 多 Tab按通道显式COM打开；历史配置无`serial_port`时兼容`vlan{N} -> COM{N-100}`；按 VLAN 合并后只渲染当前 Tab，33ms 节流渲染
  - “打开全部”必须启用窗口当前全部 VLAN/COM Tab；全流程勾选串口日志时必须自动执行同一动作，不能只显示窗口并停留在“COM 未打开”
  - 屏内缓冲上限 48 KiB（工作缓冲）；全局缓冲超 64 KiB 触发合并展示
  - 默认日志目录不可写 / 终端状态文件不可写时显式提示
  - 串口终端原始日志文件名固定为 `<vlan名>_<COM口>_<YYYYMMDD>.log`，日期取打开监控时的本机日期，例如 `vlan112_COM12_20260808.log`；手动打开、“打开全部”和全流程预启动必须共用该规则
  - 串口终端落盘日志的每一行必须以 `YYYY-MM-DD_HH:MM:SS` 开头，方向字段紧随其后，例如 `2026-08-08_19:12:10 RX 打印内容`；RX 多行同包必须逐行加时间戳，半行跨读取块必须先拼接，关闭前末尾残留不得丢失。时间戳不得写入串口原始历史、界面事件文本或升级标记判断
- **禁止破坏**：自动升级占用的 Tab 手动发送（含 Enter）被锁定；危险命令二次确认；原始终端文件由后台串口线程完整写入磁盘
- **已确认验收（2026-08-13）**：通道显式选择COM后，串口日志按用户实际选择打开，Tab/串口映射符合现场预期；历史配置缺字段时的VLAN兼容回退继续保留。
- **已确认验收（2026-08-29）**：同时滚动3路以上高频WiFi日志时，终端按钮仍可操作；日志文件名和每个落盘行的时间戳符合既定规则。
- **对应测试**：`tests/test_serial_terminal.py`

### 2.4 全包升级 - `Tftp指令`（设备拉取固件）

- **状态**：已确认验收（既有 Tftp指令链路；两台受控并行、固定 `.1` 网段及 TFTP 网卡准备按需复用，2026-08-30）/ 已实现未验收（本次仅保留并行数的窗口交互；上电帧后稳定 1 秒即放行串口回车，2026-08-31；未恢复出厂时 3 秒结束并跳过最终登录，2026-09-01） / 已实现未验收（SDMC进入Boot分支及界面选择/持久化/确认摘要，2026-09-20）
- **核心验收行为**：
  - 两台受控并行真实样机（2026-07-12）
  - `ARP Retry count exceeded` 自动重试 3 次（2026-07-12 + 2026-07-13 合并记录）
  - 串口乱码盲发密码补救登录（`peek_since` salvage 路径） — 见 §3.2 待核对
  - 全包升级固定将 VLAN 网卡准备为 `192.168.1.<VLAN尾号>`，不读取主界面样机管理 IP 或已保存 PC 静态 IP；设备通过串口执行从该固定源 IP 拉取固件
  - 传输后观察 `Boot/Bood`，发送 `reset` 或后备重新上电完成后，未勾选恢复出厂时只等待 3 秒即结束当前通道并跳过最终系统登录；勾选恢复出厂时才保留 120 秒等待、最终登录和恢复出厂
- **边界与异常**：高并发时 `manual_writable` 仅在控制器释放后切回
- **禁止破坏**：
  - 监听 socket 与 RRQ 数据 socket 严格绑当前 VLAN IP，禁止回退 `0.0.0.0`
  - 固件名固定 `tclinux_allinone`
  - 不开外部 CRT / Tftpd 进程
- **已确认验收（2026-08-30）**：`Tftp指令` 已实测一次；网卡已满足时可复用并严格绑定对应 VLAN IP 完成设备拉取。
- **待确认**：上电帧后稳定 1 秒即开始循环回车进入 boot 的 Windows 源码版及真实样机；未勾选恢复出厂时 reset / 后备上电后的 3 秒收尾和跳过最终系统登录，以及勾选恢复出厂时原收尾链路；4 台、8 台独立 VLAN / COM 真实样机端到端（含程控电源长连接复用、日志仅有一次"已打开 / 已关闭程控电源串口"）；按现场需要补验收。
- **对应测试**：`tests/test_serial_upgrade_service.py`、`tests/test_tftp_transport.py`、`tests/test_serial_transport.py`

### 2.5 全包升级 - `Tftp Put`（主机推固件）

- **状态**：已确认验收（既有 Tftp Put 链路；两台受控并行、固定 `.1` 网段及 TFTP 网卡准备按需复用，2026-08-30）/ 已实现未验收（本次仅保留并行数的窗口交互；上电帧后稳定 1 秒即放行串口回车，2026-08-31；传输后未识别 Boot/Bood 时后备重新上下电，以及未恢复出厂时 3 秒结束并跳过最终登录，2026-09-01） / 已实现未验收（SDMC进入Boot分支及界面选择/持久化/确认摘要，2026-09-20）
- **核心验收行为**：
  - 两台受控并行真实样机（2026-07-12）
  - 开始前对程控电源下电 + 上电（与 `Tftp指令` 复用 `_power_cycle_current_channel`）；检测 `UserName:` 后按 boot 凭据登录；`Password:` 同批覆盖由 `cursor` 前移修复；上传失败 / 超时不影响后续 batch
  - 上传完成后观察 90 秒 Boot/Bood；检测到则发送 `reset`，未检测到且已配置程控电源时对当前通道执行一次后备下电 + 上电；未勾选恢复出厂时，完成 reset 或后备动作后等待 3 秒即结束当前通道并跳过最终系统登录；勾选恢复出厂时才等待 120 秒进入最终系统登录；后备上下电保留普通默认时序
  - 全包升级固定将 VLAN 网卡准备为 `192.168.1.<VLAN尾号>`，不读取主界面样机管理 IP 或已保存 PC 静态 IP；远端设备固定 `192.168.1.1:69`
- **禁止破坏**：
  - 客户端必须绑当前通道 VLAN IP
  - 远端固定 `192.168.1.1:69`
  - **不与 `Tftp指令` 合并**
- **已确认验收（2026-08-30）**：`Tftp Put` 已实测一次；网卡已满足时可复用。
- **待确认**：上电帧后稳定 1 秒即开始循环回车进入 boot 的 Windows 源码版及真实样机；传输后未识别 Boot/Bood 时的后备重新上下电；未勾选恢复出厂时 3 秒结束且跳过最终系统登录，以及勾选恢复出厂时保留 120 秒等待/最终系统登录；4 台、8 台并行真实样机；现场回显差异（如 `ECNT>` 大小写）下的最终登录时序；按现场需要补验收。
- **对应测试**：`tests/test_serial_upgrade_service.py`（含 `Tftp Put` salvage / 同批 `ECNT>` / `Password:` 测试）

### 2.6 全包升级 - 通用时序与收尾

- **状态**：已确认验收（升级结束关闭自动打开串口终端；两条升级链路的既有升级专用上下电，2026-08-30）/ 已实现未验收（TX 输出复用主执行日志；上电帧后稳定 1 秒即放行串口回车，2026-08-31；未恢复出厂时 3 秒结束并跳过最终系统登录，以及最终登录过滤密码回显中的 shell 字符，2026-09-01）
- **核心验收行为**：
  - 升级结束后关闭**自动打开**的串口终端；手动打开的不受影响
  - `Tftp指令` / `Tftp Put` 升级链路均复用主执行日志的 TX 输出
  - 两条全包升级链路均使用“断电后等待 1 秒 → 上电帧后等待 1 秒 → 立即放行串口循环回车”的升级专用时序，不改变普通电源流程的默认 1.5 秒/3 秒时序
  - 两条链路未勾选恢复出厂时，传输后 reset 或后备重新上电完成只等待 3 秒即结束当前通道，不执行最终系统登录；勾选恢复出厂时才保留 120 秒等待、最终登录和恢复出厂
  - 最终系统登录必须先识别实际失败回显，且仅独立 shell 提示符行可判定成功；密码回显内的 `#` / `>` 不得触发恢复出厂
- **禁止破坏**：保留确认弹窗 + 主执行日志；密码回显内的 `#` / `>` 不得被最终登录当作 shell 成功提示；`finally` 中关闭会话与电源长连接
- **待确认**：真实样机分别以 `Tftp指令`、`Tftp Put` 确认断电 1 秒、上电帧后稳定 1 秒即开始循环回车并稳定进入 boot；未勾选恢复出厂时 reset / 后备上电后的 3 秒收尾和跳过最终系统登录，以及勾选恢复出厂时原收尾时序、错误密码回显含 `#` / `>` 时不误下发恢复出厂仍正确。
- **对应测试**：`tests/test_serial_upgrade_service.py`（两条链路的 1 秒/1 秒入 boot 时序、并行电源协调与主日志提示）、`tests/test_power_supply.py`（升级专用时序覆盖与普通默认时序隔离）、`tests/test_app.py`（自动打开 / 手动打开终端的差异化断言）

### 2.6.1 全包升级 - `web打开网关`

- **2026-09-20修复边界（已实现未验收）**：从vlan148串口记录确认`## Checking hash(es)`被SDMC误当成`#`，现改为独立提示行且裸提示稳定观察；Web打开前同出口只读GET最长90秒确认升级表单，GET无HTTP头HTML兼容转发，代理和CDP超时分阶段记录。实际VLAN148/192.168.1.148/ifIndex71只读访问确认标题Software update及1个文件框；此证据只覆盖该次页面读取，不代表负责人完成升级验收。提交后的30秒及原收尾不变，失败/延迟启动与多通道完整升级待复验。

- **状态**：已实现未验收（2026-09-20；源码/自动化及本机无头浏览器模拟页通过，不代表Windows可见界面、真实网关或物理多NIC验收）。
- **核心不变量**：沿用两种Boot方式、首轮电源1秒/1秒、并行1–8及单台失败隔离；浏览器仅访问主界面管理IP，每通道独立临时配置/代理，TCP同时绑定该VLAN的PC源IP和Windows接口，不能回退默认网卡或系统代理；两种TFTP的固定地址及传输实现不变。
- **提交与收尾**：仅定位唯一文件框及Update software按钮，校验所选文件后点击一次；不判断网页变化，固定等待30秒再进入既有90秒Boot/Bood观察及reset/后备上下电。恢复出厂仍必须经过最终系统登录；提交失败不得进入后处理，不自动重试点击。固定等待不构成固件上传、写入或版本验收证明。
- **资源与日志**：当前通道结束关闭本次浏览器/代理/临时配置，保留普通浏览器；准备网卡不改写配置INI；主日志记录出口、文件、提交动作、30秒等待和各后续结果。
- **待确认**：Windows源码版可见窗口、Edge/Chrome目标机启动与清理，真实样机两种Boot方式、30秒后Boot观察、reset/后备上下电、恢复出厂开关、2/4/8通道同IP物理出网隔离及全流程端到端。
- **对应测试**：`tests/test_web_gateway_upgrade.py`；本机浏览器集成测试须显式设置 `LINECHECK_WEB_BROWSER_TEST=1`，仅访问loopback模拟网页，上传临时测试数据。

### 2.7 批量写样机参数（默认走 telnet 路径）

- **状态**：已确认验收（1 台单台 telnet 路径，2026-07-17；6 台独立 VLAN 并行 telnet 路径，2026-07-19；流水线下发命令由可选 Checkbutton 控制：`ppctl clear` 与 `AGING_STATE=1` 默认关闭、勾选才下发、关闭时主日志输出"关闭，跳过"，2026-07-19 6 台真实样机验收通过；默认并行数 1 / 确认框 9 步自然顺序 / 清理失败步骤名标识同步验收通过；用户模式与工厂模式网卡准备按需复用，2026-08-30）/ 已实现未验收（2 / 8 台端点并行；2026-07-19 用 6 台覆盖了原计划 2 / 4 / 8 区间中段代表性场景）
- **业务时序**：UBUS 启用 telnet → `TelnetSession`（未登录） → 首次登录 → 1. 进入工厂模式（`ppctl set FACTORY_MODE=1`）→ 2. `firstboot -yr` → 3. 等待 100 秒 → 4. 工厂模式二次登录 → 5.（可选 `ppctl set AGING_STATE=1`）→ 6.（可选 `ppctl clear`）→ 7. 15 项 `ppctl set/get` 读回校验 → 8. 退出工厂模式（`ppctl set FACTORY_MODE=0`）→ 9. `firstboot -yr`（`finally` 中执行第 8/9 步）

  写参前置采用「查询并按需准备对应通道网卡 + `wait_for_bindable_ip` 等 15 秒」：已启用且 `channel.network_card_ip`/前缀完全匹配时跳过重复设置，部分不满足只修复对应项，状态读取失败回退完整启用和静态 IP 设置；任何一步失败抛 `RuntimeError` → worker 标记 `telnet 写参启动失败`，单台放弃不影响其它通道。该步骤位于 `make_telnet_factory` 内 UBUS 启用 telnet 之前；100 秒工厂模式网段切换继续由 `make_factory_session_swap` 处理并使用相同预检规则，PC 端从 `192.168.1.x` 切到 `192.168.29.x`、主机位保持不变。`factory_bind_ip` / `factory_device_host` 未配置时按 `factory_bind_ip_for(network_card_ip)` / `factory_device_host_for(device_manage_ip)` 自动派生（第 3 段 → 29，主机位不变）；手动填值优先级最高。
- **并行与取消**：并行 1-8 台（默认 1；2026-07-19 用户要求默认串行更稳，多台并发易撞 UBUS HTTP / telnet login / NIC；Spinbox 仍允许 1–8 现场上调，关闭写参窗口或主程序后保存本次有效值并在下次打开时恢复；升级窗口的 `parallel_count` 默认仍为 2，互不影响）；取消时停止后续命令并尝试退出工厂模式
- **节奏常量（2026-07-18 P2 缓解）**：默认 `src/services/sample_parameter_service.py` 顶部 7 个常量，按现场经验统一调整；`_login` prompt/password_prompt 用 `PARAMETER_LOGIN_PROMPT_TIMEOUT_SECONDS=10.0`、password_result 用 `PARAMETER_LOGIN_PASSWORD_TIMEOUT_SECONDS=20.0`；`_write_and_verify` set 后 sleep `PARAMETER_SETTLE_AFTER_SET_SECONDS=1.5`、get 等 marker 用 `PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS=10.0`、mismatch/marker=None 后退避 `PARAMETER_RETRY_BACKOFF_SECONDS=1.5`、成功/失败末尾 BETWEEN_PARAMS=`0.5`；并行 worker 错峰 `PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS=0.6`。若 8 台并行仍偶发失败，优先上调 `PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS=15.0` 与 `PARAMETER_RETRY_BACKOFF_SECONDS=2.5`。
- **前置 UBUS 协议**：经自写 `UbusHttpClient` 按 `SdmcUbusLibEnableTelnet.Enable_telnet` 协议开 LAN-telnet 规则 — ① 总开关 `Device.Firewall.<X_SDMC_>Security.AccessCtrl.Enable` 若非 `"1"` 则 `set Enable=1`（用对象路径 `...AccessCtrl.`，非参数路径，避免 fault 9005 `EnableEnable`）；② 查 `AccessCtrl.Rule.{}.` 既有 telnet 规则（`SourceInterface ∈ {lan, both, Device.IP.Interface.1}`）— 已启用返回 `already_present`，否则 `set Enable=1` 返回 `reused`；③ 若无合适规则则 `add {SourceInterface: Device.IP.Interface.1, IPVersion:4, SourceIP:0.0.0.0, Application:telnet}` 返回 `added_iface`；失败回退 `add SourceInterface=lan` 返回 `added_lan_fallback`。每步校验 `results[*].data == "1"`，末尾固定 `sleep_fn(ENABLE_TELNET_FINAL_SLEEP_SECONDS=1.0)` 给防火墙 reload 留缓冲。
- **核心验收行为（2026-07-19 6 台独立 VLAN110–VLAN115 真实样机并行验收通过，含可选项化 + 默认并行 1）**：
  - 6 个 worker 通过 `PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS=0.6` 错峰启动，避免同 t=0 把 NIC / 防火墙挤爆；UBUS 启用 telnet 4 段日志按样机独立给出，没有交错串行。
  - 6 台全部完成 `TelnetSession`（按 VLAN `bind_ip` 锁源）→ 首次登录 → （按主界面 Checkbutton 状态）`AGING_STATE=1` / `ppctl clear` → `FACTORY_MODE=1` + `firstboot -yr` → 等 100 秒 → 工厂模式网段切换（192.168.1.{N} → 192.168.29.{N}，`factory_bind_ip`/`factory_device_host` 自动派生）→ 工厂模式二次登录 → 15 项 `ppctl set/get` 读回校验通过 → `FACTORY_MODE=0` + `firstboot -yr`（`finally` 清理成功，主执行日志出现"已下发退出工厂模式与重启命令"）。
  - 「清空参数」勾选时 6 台 `TX ppctl clear` 全部出现在主执行日志；关闭时 6 台主日志均出现"清空参数：关闭，跳过"且设备 ppctl 表保持未清空。「退出老化」勾选时 6 台 `TX ppctl set AGING_STATE=1` 全部出现在主执行日志；关闭时 6 台主日志均出现"退出老化：关闭，跳过"。
  - 默认并行 1 时 6 台变为串行（每台完整 9 步自然顺序），主执行日志依次出现 `开始批量写样机参数：6 台，并行上限 1` 与每台写参的完整 9 步；Spinbox 现场调到 2 / 4 仍能正常并行。
  - 6 台未触发 `bind_ip == device_host` 配置冲突预检（vlan110/111 已修过 device_manage_ip）；也未触发"清理失败步骤名消失"问题（每台清理失败若发生，会精确显示是 FACTORY_MODE=0 还是 firstboot -yr 触发的）。
  - 覆盖了原计划 2 / 4 / 8 台区间的中段代表性场景（4 段 UBUS HTTP 抢网卡、6 个 telnet session 并发登录、错峰启动对 NIC / 防火墙压力的缓解效果都得到验证）；2 台 / 8 台端点如现场需要再补验收。
- **核心验收行为（2026-07-17 单台 VLAN114 真实样机验收通过）**：
  - 主执行日志依次输出「写参前置：准备网络 vlan114（192.168.1.114 / 255.255.255.0） → 检查并启用网卡 → 已启用网卡 → 设置静态 IP → 已设置 → UBUS 启用 telnet 中 → UBUS 三段消息（AccessCtrl 总开关开启 / 规则 enable / 最终 action） → UBUS 启用 telnet added_iface/already_present: ... → STATE Telnet 已连接 → 首次登录成功 → TX ppctl clear → TX ppctl set FACTORY_MODE=1 → TX firstboot -yr → 等待 100 秒 → 工厂模式网段切换：准备把 vlan114 设为 192.168.29.114（自动派生自 network_card_ip）→ 工厂模式重建 TelnetSession 成功（192.168.29.114 → 192.168.29.1） → 工厂模式二次登录 → 15 项 TX ppctl set/get 读回校验 → 写参完成，15 项均已读回校验 → TX ppctl set FACTORY_MODE=0 → TX firstboot -yr → 已下发退出工厂模式与重启命令」
  - `factory_bind_ip` / `factory_device_host` 在 `network_card_ip.ini` 故意留空，由派生逻辑兜底；现场若需特殊工厂模式网段（与 192.168.29.x 不同），手动填入 ini 即可覆盖派生
- **边界与异常**：
  - 参数值不允许双引号 / 回车 / 换行
  - 按项目负责人 2026-08-08 最新约定，密码类字段允许在界面、终端和日志中明文显示，不设置脱敏验收要求
  - 源 IP 不可绑时强提示人工检查 `network_card_ip.ini`，不回退 `0.0.0.0`
  - 派生失败（`network_card_ip` / `device_manage_ip` 缺失或格式无效）时 `_start_sample_parameter_write` 弹错误并要求补齐
  - **`ppctl clear` 与 `ppctl set AGING_STATE=1` 选项化（2026-07-19）**：两个命令不再默认下发；`SampleParameterWriteRequest` 新增 `clear_parameters` / `exit_aging` 两个 `bool` 字段（默认 `False`），由主界面 Checkbutton「清空参数」/「退出老化」控制。勾选后，工厂模式二次登录成功时分别下发对应命令；未勾选时主执行日志输出 `清空参数：关闭，跳过` / `退出老化：关闭，跳过`，不实际下发命令。顺序固定为「退出老化 → 清空参数 → 15 项 ppctl set/get」。两个字段状态持久化到 `sample_upgrade_settings.ini`（`parameter_clear_parameters` / `parameter_exit_aging`），旧 ini 兼容回退 False。需在 6 / 8 台真实样机上回归确认现场是否符合"勾选才下发"的语义。
  - **配置冲突（2026-07-18）**：`bind_ip == device_host`（PC 静态 IP 与样机管理 IP 相同）→ PC 把自己作为目标连接，必然 timed out。`_start_sample_parameter_write` 预检命中即弹「样机 IP 配置冲突」并阻止 worker 启动；同时 `TelnetSession._open_socket` / `UbusHttpClient._post` 在 `bind_ip == device_host` 时，错误消息附加 hint 提示操作员去 `network_card_ip.ini` 修 `device_manage_ip`（典型值 192.168.1.1）。
  - **退出工厂模式清理失败（2026-07-19）**：`finally` 清理块把 `ppctl set FACTORY_MODE=0` 与 `firstboot -yr` 拆为两个独立 `try/except`，第 1 步失败也会尝试第 2 步（best-effort）。两步的 TX 主程序执行日志都必然出现（`_send_stage` 内部 `emit` 在 `send_line` 之前），失败消息明确包含 step 名（`FACTORY_MODE=0 下发失败：…` / `firstboot -yr 下发失败：…`），多条失败用「；」拼接，便于操作员分辨是哪一步触发的"Telnet 连接已关闭"。
- **禁止破坏**：
  - `TelnetSession`、`UbusHttpClient` 必须按 VLAN `bind_ip` 锁源（`source_address=(bind_ip, 0)`）
  - 串口路径保留作 transport 配置回退入口；其他功能（页面升级 / 全包升级 / 串口终端）不受影响
  - UBUS HTTP 客户端不复用 `SdmcUbusLib`（其会话静态、不允许多并发）— 如要替换须保证同等并发与源 IP 锁源语义
  - 工厂模式网段约定 29（第 3 段替换）必须保持稳定；变更前需通知所有现场并同步升级 `network_ops.py` 常量
- **已确认验收（2026-08-30）**：用户模式与工厂模式的网卡预检均可在完全匹配时复用，且仍完成可绑定确认。
- **待确认**：Windows 源码版修改写参并行数后关闭并重开窗口，确认恢复上次有效值且不改变升级并行数；2 / 8 台端点独立 VLAN 真实样机并行验收（VLAN/MAC 对应、`set/get` 读回校验、取消清理、退出工厂模式后的重启、明文凭据核对、UBUS 启用 telnet 与 telnet 登录衔接时序；2026-07-19 已用 6 台覆盖了 2 / 4 / 8 区间中段代表性场景）；按现场需要补验收。
- **对应测试**：`tests/test_sample_parameter_service.py`、`tests/test_telnet_transport.py`、`tests/test_ubus_http_client.py`、`tests/test_ubus_enable_telnet.py`、`tests/test_sample_parameter_table.py`、`tests/test_sample_parameter_app.py`、`tests/test_channel_config.py`、`tests/test_regression_sleep_fn.py`、`tests/test_network_ops.py`

### 2.8 随机参数表生成（`.xlsx`）

- **状态**：已确认验收（2026-07-19 6 台独立 VLAN110–VLAN115：同批MAC OUI、SSID后缀与MAC关联；2026-08-13 生成窗口透明首帧修复、MAC前6位自定义、普通SN纯数字且总长不超过16位、XPON SN固定12位且后8位为十六进制）
- **核心行为**：按已勾选 VLAN 生成 `.xlsx` 表，导出后自动加载并预检（**不自动下设备**）；MAC前6位由操作员输入并校验为6个十六进制字符及单播地址，后6位为每台唯一的随机十六进制值，输出统一大写冒号格式；普通SN的前缀与随机后缀均只允许数字，二者总长不得超过16位，默认配置生成16位；自动生成XPON SN固定12位，由严格4位操作员前缀加8位唯一大写十六进制后缀组成，并为兼容既有表头写入`GPON SN`列；2.4G / 5G SSID 后缀取本机 MAC 末 4 位十六进制（同一行两个 SSID 共享后缀）；密码类字段明文显示（操作员核对需要）
- **兼容性约束**：导入兼容旧表共用 `WiFi Password` / `Country code` 列
- **2026-07-19 同 OUI 改动（已确认验收）**：自动生成时一次性随机生成 3 字节 OUI（保留本地管理 bit1=1 + 单播 bit0=0 的位设置），每条记录只随机生成后 3 字节 NIC 标识并拼接；同批 N 条记录的 MAC 前 6 位完全一致。6 台真实样机验收：6 条记录的 MAC 前 6 位字符串完全相同，后 3 字节每台唯一；样机端能正确识别。
- **2026-07-19 SSID 末 4 位 MAC 强关联（已确认验收）**：2.4G / 5G SSID 后缀不再随机生成，改为 `mac.replace(":", "")[-4:]` 取本机 MAC 末 4 位十六进制（大写），便于操作员把同一行 SSID 与本机 MAC 一眼对应。例：`MAC=CA:7A:85:18:B0:E8` → 2.4G SSID = `ssid_24_prefix` + `B0E8`；5G SSID = `ssid_5_prefix` + `B0E8`（共享同一后缀）。6 台真实样机验收：6 条记录的 2.4G / 5G SSID 后缀全部等于各自 MAC 末 4 位，且同一行两个 SSID 互相一致；样机端能正确识别。
- **2026-07-19 label 优化（已确认验收）**：生成窗口输入框 label 从 "随机后缀长度" 改为 "SN/GPON SN 随机后缀长度"，与 SN/GPON SN 两个字段字面对齐，避免操作员误以为该字段也控制 2.4G / 5G SSID 长度。
- **2026-08-13 XPON SN格式优化（已确认验收）**：XPON SN前缀输入改为固定4位（默认`XPON`），后8位只从`0123456789ABCDEF`生成，同批保持唯一；最终XPON SN必须恰好12位。原后缀长度输入改名为“SN随机后缀长度”，只控制普通SN。生成或保存失败、成功文件路径和记录数均写入主执行日志。
- **2026-08-13 普通SN格式优化（已确认验收）**：SN前缀改为纯数字输入语义（默认`12345678`），随机后缀只从`0123456789`生成；前缀长度与后缀长度合计最多16位，超过上限、前缀为空或含非数字字符均明确拒绝；默认前缀8位加后缀8位生成16位SN。
- **2026-08-13 MAC前缀自定义（已确认验收）**：生成窗口增加“MAC 前6位（十六进制）”，默认`020000`，兼容无分隔符、冒号和短横线输入；去掉分隔符后必须恰好6位且只含`0-9/A-F`，首字节组播位必须为0。程序为每条记录随机生成唯一后3字节，输出统一大写冒号格式。该规则替代2026-07-19的随机OUI生成方式，但继续保持同批前缀一致、后缀唯一和SSID取MAC末4位规则。
- **2026-08-13 生成窗口透明首帧修复（已确认验收）**：生成批量样机参数表窗口保持标准`Toplevel`自然映射，控件全部创建后按已知`680×750`尺寸相对“写样机参数”父窗口居中，再复用DUT配置/测试项配置的20/120/360ms一像素尺寸脉冲触发客户区整树重绘；不使用`withdraw/update/after(0)`阻塞式首帧处理。第一次成功刷新写入主执行日志。项目负责人Windows现场确认无需移动鼠标即可正常完整显示。
- **现场结论（2026-08-13）**：项目负责人确认批量样机参数表生成规则整组实际验收通过，覆盖普通SN、XPON SN、MAC前缀/随机后缀、非法输入提示及SSID与MAC末4位关联。
- **对应测试**：`tests/test_sample_parameter_table.py`

### 2.9 页面升级 - UBUS 批量

- **状态**：已确认验收（网卡按需复用、恢复出厂命令/重启/日志，2026-08-30）
- **核心行为**：
  - 查询目标 VLAN 网卡启用状态和 IPv4/前缀，完全匹配时直接复用，否则按需启用或切换 PC 到样机管理 IP 网段（`prepare_network_for_sample(reuse_if_ready=True)`）
  - HTTP/HTTPS `ubus` 登录、上传固件、调用 `Device.DeviceInfo.X_SDMC_Upgrade()`
  - 升级后 UBUS `Device.FactoryReset()`（`proto=web`）；关闭时输出"恢复出厂：关闭，跳过"
- **禁止破坏**：
  - `Access denied` 兼容三种 RPC：`bbfdm.operate` / `bbfdm.operate(proto=web)` / `bbfdm.unauthenticated_operate`
  - `PageUpgradeRequest.restore_factory` 已落地；只可在**升级成功 + 重启 + 重新登录成功**之后调用
  - 不提前 `logout` 复用已验证会话
- **已确认验收（2026-08-30）**：页面升级验证网卡按需复用；勾选“恢复出厂”时，实际`Device.FactoryReset()`命令、重启及主执行日志均符合预期。
- **对应测试**：`tests/test_page_upgrade.py`（含 `restore_factory`、`exit` 回退策略）、`tests/test_app.py`、`tests/test_network_ops.py`

### 2.10 ZTE OLT ONU 注册

- **状态**：已确认验收（C600四VPort OLT配置、MAC学习、write与清理，2026-08-24；C300默认SD-41六业务模板单台注册/回读，2026-08-25；Windows四步窗口布局、原生勾号及C300/C600文案和切换，2026-08-29；C300/C600专项、ONU终端业务与Windows专项，2026-08-30；C300/C600 ONU类型模板、DBA模板查询结果去除标签显示，2026-09-03；本次C600两台手填3/4与确认执行ID一致的修复，2026-09-06）/ 已实现未验收（C300/C600多台勾选、批量ID分配、整批预检、逐台下发回读和全流程等待结果的其余场景，2026-09-05；ID修复的其它型号与异常组合，2026-09-06）
- **已确认验收（2026-09-06）**：项目负责人确认本次C600批量ONU目标ID修复通过：两台分别填写3、4，确认执行保持3、4；仅记录本次问题范围，其余批量组合保持待确认。
- **本轮实现（2026-08-25）**：C300 查询页增加机框/槽位/PON，仍执行全局未注册查询并在客户端按目标 PON 过滤；配置页支持 ONU ID、类型模板、T-CONT/DBA和六项 ServiceID/VLAN 参数，Service ID 派生同号 GEM/VPort。默认参数保持旧六业务模板，C300 自定义参数路径仅完成代码与单元测试，未进行真实写入验收。
- **核心行为**：
  - 主界面单一入口不变；窗口当前默认和最小尺寸均为`1000x900`，通过“1. 查询 ONU / 2. 配置业务 / 3. 确认执行 / 4. 已注册管理”四步分页支持C300与C600，不导入或启动原独立GUI
  - OLT型号、OLT IP、源IP、用户名、密码、登录测试和连接状态必须固定显示在分页上方；C600机框/槽位/PON必须位于第一步查询页，不得要求操作员先切到配置页再返回查询
  - C300与C600发现结果使用Windows原生`Checkbutton`多选，并保留“全选/清除”；本批仅包含操作员明确勾选的 SN，不能按查询返回顺序猜测目标。预览必须逐台显示SN、PON和最终ONU ID。单台时保留手填ONU ID；逐台配置时按目标ONU保留各自手填ID，切换目标不得被共用输入框最后值覆盖。手填ID优先于发现建议ID，同PON手填重复ID必须拒绝，不能自动改号；未单独填写的目标优先使用发现建议ID，其余自配置起始ID递增且避开本批手填/已分配ID，实际OLT占用仍由下发前预检确认。重新查询须清空本次目标ID输入。C300原始未注册输出只有位置、SN和状态，列表须额外以`注册类型:SD-41（配置模板）`、`PON类型:GPON（根据接口推断）`显示已知配置与接口推断，不得伪装成OLT实际探测的型号或最大速率；C600未注册查询结果中的`型号`必须保持设备发现语义；配置字段必须标为`ONU 类型模板`，默认从发现型号带入但允许按OLT兼容模板修改；已注册/清理候选中的`onu type`必须显示为`类型模板`。第二步按OLT型号显示C300固定模板/危险删除开关或C600完整业务参数；第三步同时显示执行摘要、完整命令预览和唯一的“开始注册”主按钮
  - 未选择ONU时不得进入配置或生成预览；OLT型号、连接、ONU选择或业务参数变化后旧预览必须失效并禁用注册，重新生成预览后才能执行；查询/执行状态、停止和关闭必须在三个步骤下持续可见
  - 顶层标题、说明、连接区、Notebook、危险提示、状态栏和底部按钮必须使用固定行布局，只允许Notebook行伸缩；命令预览不得使用Tk Text默认大请求高度，普通`1000x900`窗口下危险提示、状态栏和“关闭/停止”必须完整显示，不得要求最大化
  - 统一service编排“登录 → 未注册查询 → 全批下发前预检 → 按预览顺序逐台配置 → 每台最长60秒可停止上线轮询 → 每台只读验证 → 结果”。预检阶段任一ID/SN/PON冲突时不得下发任何配置；配置阶段一台失败或停止时不得启动后续目标，不自动回滚已成功目标。C300与C600命令生成、接口格式和解析器由两个独立driver负责，不允许跨型号替换字符串；配置记录存在但未进入working不得误报成功
  - C300：全局`show gpon onu uncfg`查询，使用`gpon-olt_` / `gpon-onu_`、SD-41固定业务模板、`pon-onu-mng`和`mvlan 600`；下发前再次执行实机确认有效的全局`show gpon onu uncfg`并按每个目标ONU接口与SN精确确认仍未注册、以`show gpon onu baseinfo ... <ONU ID>`确认ID空闲、以`show gpon onu by sn <SN>`执行整台OLT的SN查重，不得使用实机返回`Invalid parameter`的`show gpon onu uncfg gpon-olt_<PON>`格式
  - C300下发后必须按真实C300格式核对：`baseinfo/state/detail-info`中的接口、类型模板、SN、ready/working/config success/SN Bind；`tcont/gemport/vport`中的1G模板、六个GEM active及1:1映射；`service-port/remote-onu service/remote-onu mvlan`中的六组固定业务、OK/YES及`mvlan 600`。空ID返回`ONU data is null`、空SN返回`No related information to show`时视为可继续，不得误判CLI失败
  - C600：按PON执行`show pon onu uncfg gpon_olt-... sn model speed-mode`，使用`gpon_olt-` / `gpon_onu-` / `vport-`及可编辑ServiceID/VLAN映射；发现结果的Speed Mode不得直接转换成必下发的`real-speed`，选中ONU后默认使用`auto`并省略该命令。上网170/171/172/173/151/150及未定义普通数据VLAN使用可编辑主资源（默认T-CONT 1/GEM 1/VPort 1/`WT-10G`），语音335固定T-CONT 2/GEM 2/VPort 2/`DBA_FONE`，组播600固定T-CONT 3/GEM 3/VPort 3/`DBA_IPTV`，TR069 50固定T-CONT 4/GEM 4/VPort 4/`DBA_TR069`；gemport模式下GEM与VPort必须1:1，只创建实际出现的业务资源，并拒绝上网ID与固定资源冲突。映射必须包含VLAN 600并下发ONU侧`mvlan 600`及OLT侧`igmp fast-leave enable`、`igmp version v2`、`igmp mvlan 600 receive-port`。下发前精确拒绝ID/SN冲突；下发后必须解析collection、换行service-port、detail-info及MVLAN四组输出，逐项核对四层T-CONT/GEM/VPort、9组业务实际VPort与OK/YES、IGMP receive-port、working/config success和`Multicast VLAN: 600`
  - 两种型号遇到第一条CLI错误即停止并尝试退出配置模式；主日志必须记录型号、关键阶段、实际`TX OLT`命令、返回、成功、停止或失败
  - Telnet必须使用操作员填写的源IP调用`source_address=(bind_ip, 0)`锁定Windows出口；源IP为空/格式错误/不可绑定必须失败，不得回退系统默认网卡。C300与C600分别保存OLT IP、源IP、用户名和密码，型号切换不得串用另一型号连接资料；已知默认路径为C300 `172.18.18.151`经`172.18.18.40`、C600 `172.18.18.152`经`172.33.5.35`
  - C300离线ONU删除重试是默认关闭且不持久化的独立危险选项；启用后必须先只读查询目标PON候选并由操作员明确选择一台，配置失败后再次确认其仍为同PON离线候选且接口/SN与查询时一致，才允许只生成一条目标`no onu <ID>`，禁止批量或跨PON删除；C600任何场景都不得自动删除或回滚ONU
  - C300危险删除、C600 SN双重绑定和C600 write必须使用Windows原生`Checkbutton`，选中显示标准“✔”、未选为空框，不得使用Clam主题下显示叉号的`ttk.Checkbutton`；控件替换不得改变默认值、持久化、确认或执行语义。此规则同样适用于以后新增或修改的布尔选择控件
  - 独立的“已注册管理”分页允许操作员主动查询目标 PON 口下已注册 ONU，列出全部已注册 ONU（含在线 working）供单选删除；C300 用全局`show gpon onu state`后按目标 PON 过滤（`show gpon onu state <pon>` 按 PON 不带 ID 的格式 OLT 已确认不支持）、C600 用`show running-config-interface <pon>`查已注册列表再逐台`show gpon onu state <pon> <id>`取状态标签，删除前必须二次确认并重新核对接口与 SN，只删除明确选择的这一台，删除后回读 baseinfo 确认其回到未注册状态，且不执行 write。该入口对 C300 与 C600 均可用，允许删除任意状态（含在线 working，删除在线 ONU 会立即中断业务）；C600 仍不自动删除、不自动 write，仅此显式选择路径允许删除
  - 注册默认不保存OLT配置；C300成功后单独询问`write`。C600提供“完整验证成功后执行write”本次选项，默认关闭、不持久化，摘要和最终确认必须明确显示；只有working与完整回读成功后才用独立新会话执行，最长等待120秒并记录真实返回
- **真实设备命令核查（2026-08-18，不等同注册写入验收）**：已从`172.18.18.40`登录C300 `172.18.18.151`，使用一台已注册在线ONU确认上述ID/SN空记录、注册身份、运行状态、T-CONT/GEM/VPort、service-port、远端业务和MVLAN输出格式；已从`172.33.5.35`登录C600 `172.18.18.152`，确认已注册样本当前无MVLAN数据、`show gpon remote-onu mvlan gpon_onu-...`查询格式以及`pon-onu-mng`上下文的`mvlan <1-4094>`帮助。核查过程未实际下发MVLAN、未删除ONU、未执行`write`
- **真实C600 service执行验证（2026-08-18，Windows三步UI仍待复验）**：使用一台未注册NP7287XGS首次执行时，ONU注册成功但`real-speed xgspon`返回`%Error 230240: Not support this function.`；该ONU在未配置此命令时会自动进入XGS-PON。修复为发现后默认`auto`后，从未注册状态完整执行精确ID/SN预检、9组业务、SN双重绑定、MVLAN 600、7次状态轮询（OffLine → syncMib → working）和collection/service-port/detail-info/MVLAN四组验证，service返回成功且未执行`write`。随后按项目负责人授权删除唯一测试ONU，确认目标ID返回`ONU data is null`、全OLT SN查询返回`No related information to show`，并在第5次发现查询重新出现于未注册列表；另一台未注册ONU未处理
- **真实C600四层业务/write验证（2026-08-24）**：项目负责人授权使用未注册NP7287XGS `SDMC176D42AA`和ONU ID 1执行写入及清理。精确ID/SN预检通过后，下发`WT-10G`、`DBA_FONE`、`DBA_IPTV`、`DBA_TR069`四个T-CONT及1:1 GEM，9组业务按上网/语音/组播/TR069分层；第5次轮询进入working，collection逐项返回四组T-CONT/GEM和9组service，全部service-port为OK/YES，detail-info为XGS-PON/working/config success，MVLAN为600。首次write持续输出进度点并超过旧30秒客户端等待，暴露超时不足；改为独立exec会话直接执行、最长120秒后，清理状态write约41秒返回`............[OK].`。测试ONU随后按接口/ID/SN复核后精确删除，baseinfo为`ONU data is null`、全OLT SN为`No related information to show`，清理后write成功且目标第一次查询即重新未注册；另一台未注册ONU及所有既有ONU未处理
- **真实C600 VPort/GEM修复验证（2026-08-24）**：项目负责人发现同一ONU只有Internet VLAN 171获取地址，授权再次精确删除并注册`SDMC176D42AA`。只读诊断确认ONU为working/config success、四组T-CONT/GEM存在且相关VLAN均在上联放通，但9条service-port全部位于VPort 1；实机`show gpon onu vport`明确为VPort 1/2/3/4与GEM 1/2/3/4的1:1映射，旧验证只检查service-port OK/YES而未检查VPort编号。修正后删除前再次核对接口/ID/SN，删除后第2次查询重新发现目标；重注册全部命令被OLT接受，第4次轮询进入XGS-PON working，collection确认VPort 1承载上网、VPort 2承载335、VPort 3承载600及IGMP receive-port、VPort 4承载50，9条service-port均OK/YES。`show mac vlan`进一步确认ONU四个WAN MAC分别在VLAN 171的VPort 1、VLAN 335的VPort 2、VLAN 600的VPort 3和VLAN 50的VPort 4动态学习成功。重注册未执行write，ONU保留在线；该证据确认OLT二层路径，不替代ONU页面语音/TR069 DHCP地址和IPTV实际节目验收
- **真实C300只读命令核查（2026-08-24，不等同注册写入验收）**：从配置的显式源IP登录C300后确认全局`show gpon onu uncfg`原始表头只有`OnuIndex / Sn / State`，不提供C600式`model / speed-mode`字段；命令帮助也没有型号或速率选项。进一步确认`show gpon onu uncfg gpon-olt_1/2/1`返回`%Error 20202: Invalid input ... Invalid parameter`，因此下发前未注册复核改用全局查询后按目标接口与SN精确匹配。本轮只执行只读查询，未进入配置模式、未注册或删除ONU、未执行`write`
- **真实C300默认模板注册验证（2026-08-25）**：经项目负责人确认，使用`gpon-onu_1/2/1:3 / GPONA62D6F48`注册`SD-41`。预检确认目标仍未注册、ONU ID 3 空闲、SN 未占用；下发默认T-CONT 1/`1G`、六个GEM/VPort及200/46/335/600/171/172六项业务后，第8次轮询进入working。`baseinfo/state/detail-info`回读为ready/working/config success/SN Bind；六个GEM均active、六个VPort均为1:1、六条service-port均OK/YES，远端六项业务和`mvlan 600`全部一致。未执行`write`，ONU保留在线；此结论不覆盖Windows界面、语音/TR069地址、IPTV节目、参数化组合或write。
- **项目负责人验收确认（2026-08-26）**：项目负责人明确确认「中兴C300注册流程验收OK」。据此，C300默认SD-41单台注册流程（按PON发现/选择、ID/SN预检、默认六业务下发、上线轮询、完整只读回读、默认不write）状态为已确认验收；此前及后续「待确认」中涉及C300的条目仅限参数化组合、write、删除命令、Windows界面及终端业务效果。
- **项目负责人验收确认（2026-08-29）**：ONU注册窗口在普通`1000x900`尺寸下四步布局完整、底部按钮不裁切；相关布尔选项显示Windows原生标准勾号；C300/C600文案与型号切换符合预期。
- **项目负责人验收确认（2026-08-30）**：C300 参数化注册、ONU ID/SN 冲突拦截、显式单台删除、`no onu`命令格式与`write`均已现场验收；C600 停止、`Access denied`、按 PON 查询和冲突预检专项复验通过；Windows 端 C300 离线候选查询/单选/清空，以及 C600 四层预览、`write`默认关闭和关闭重开复位通过。ONU终端业务已确认：语音 VLAN 335 与 TR069 VLAN 50 获得预期 DHCP 地址，IPTV VLAN 600 的现场取址/桥接方式及节目效果符合预期。
- **项目负责人验收确认（2026-09-03）**：C300/C600 的 ONU 类型模板和 DBA 模板查询下拉项均已确认显示为“模板名（值）”；“PON类型：”“速率：”标签不再显示。此结论仅覆盖该显示调整，不覆盖同轮新增的整台 OLT 未注册 ONU 查询。
- **禁止破坏**：C300/C600命令体系与连接资料隔离；源IP锁定；整批预检必须先于首条配置命令；一台失败停止后续；上线轮询可停止；危险删除默认关闭且不持久化、只允许明确选择的一台且批量禁用；C600不自动删除或回滚，批量不自动write，write必须默认关闭且只在本次明确选择、完整验证成功后执行；窗口当前默认和最小尺寸`1000x900`；普通窗口底部区域不被裁切；本机凭据和`onu_registration.ini`不入Git
- **待确认**：C300/C600多台勾选下的ID分配、整批冲突预检、跨PON批次、逐台上线/回读、失败或停止后的后续阻止，以及全流程“预选→确认→等待最终结果→下一项”需要分别在Windows源码版和真实OLT上确认；既有单台现场验收不自动覆盖这些新增场景。
- **对应测试**：`tests/test_onu_batch_registration_service.py`（批量ID分配与重复SN拒绝）、`tests/test_onu_registration_service.py`（双driver语法、发现型号/类型模板显示语义、批量预检先于下发、C300边界、C600四层T-CONT/GEM/VPort、GEM/VPort冲突、错误VPort及缺失IGMP拒绝、精确ID/SN预检、VLAN/MVLAN 600、上线与四组解析、显式write、已注册查询/删除）、`tests/test_app.py`（统一UI、ONU类型模板字段及说明、多选、四VPort提示、分型号连接、ONU原生勾选框及全源码禁止`ttk.Checkbutton`、C600 write默认不执行与选中后启动独立保存、已注册管理危险确认）、`tests/test_pipeline_orchestrator.py`（ONU全流程完成等待桥接）、`tests/test_onu_registration_store.py`、`tests/test_network_ops.py`（历史C300兼容边界）

### 2.11 输入持久化与启动 / 打包

- **推送项目名称修正（2026-10-12，已实现未验收）**：正式完成/异常通知的标题与正文，以及手动测试消息均使用 `test_project_config.ini [project_info] project_name`；每次发送读取磁盘已保存值，页面未保存项目名不生效，不回退到 `config.ini [config] test_project` 或固定名称。项目名缺失、空白、配置读取失败时明确提示并跳过发送。试发地址、密钥和 @所有人仍使用页面快照，无需保存推送配置、不受自动推送开关限制；其它发送时机保持。专项与完整基线仅证明源码行为，真实收信及 Windows 源码版仍待负责人确认。

- **消息推送扩展（2026-10-11，已实现未验收）**：第六页固定命名“消息推送”，四项仅写入 `config.ini [dingtalk_config]`；开关使用原生 Checkbutton，Webhook 和密钥直接显示但不得写入执行日志或确认摘要。接入统一保存、重新加载及未保存提醒；更新保留其它段、未知字段、注释和换行，不覆盖重试间隔或运行参数。保存不触发网络请求或消息发送；仅显式点击“发送测试消息”使用页面快照试发，不要求保存、不受自动推送开关限制，遵循当前 @所有人设置；后台单次请求、不自动重试、界面显示成功或失败。既有五页的验收结论不自动覆盖本次扩展。

- **状态**：已确认验收（测试项「恢复默认」清除全部手动命令并加载固定模板，2026-08-07；修复后便携ZIP在另一台Windows电脑可正常启动使用，2026-08-18；测试项加载提速体感及第五Tab四项参数保存重开，2026-08-29；Telnet反向镜像、WiFi八项和子任务7真实连接，2026-08-30）/ 已实现未验收（未列明的输入持久化交互）
- **核心行为**：
  - 升级方式 / 固件路径 / 恢复出厂 / 超级凭据 / 并行数 → `Auto_power_on_off_tool/config/sample_upgrade_settings.ini`
  - OLT型号 / C300与C600各自的OLT IP、源IP、用户名、密码 / C600参数 → `Auto_power_on_off_tool/config/onu_registration.ini`；C300危险删除授权每次打开均恢复关闭，不写成可复用授权
  - 测试项默认模板 → `Auto_power_on_off_tool/config/test_project_config.default.ini`；「测试项」页点击「恢复默认」只恢复 `[order]` 测试命令，确认后先加载到界面、再由操作员点击「保存」写入 `test_project_config.ini`，不得覆盖当前指令重试间隔、Telnet / WiFi / 项目信息
  - 2026-08-07 Windows 桌面确认：先手动增加测试命令，再点击「恢复默认」，手动命令全部消失，界面不再出现旧命令与默认命令混排或重复编号
  - 旧工具顶部其它启动参数由 `Auto_power_on_off_tool/config/config.ini [ui_defaults]` 加载；其中 `serial_num` 必须始终严格等于新工具保存在 `network_card_ip.ini [power_supply] serial_port` 的“程控电源 COM”，新工具 COM 为空或尚未保存时旧工具也必须为空，严禁回退或自动选择其它 COM；成功日志必须显示实际 COM 及来源，配置缺失或校验失败时保留旧界面的回退值并记录错误日志
  - 旧工具 `Telnet Enable` 必须与新工具 `test_project_config.ini [telnet] telnet_default_on` 反向：`1 → 0`、`0 → 1`；旧工具启动时直接以新配置计算，新工具保存时同步更新 `config.ini [ui_defaults] telnet_enable` 镜像值且不得破坏该文件其它内容
  - `config.ini [other_config] command_fail_retry_interval_time` 是指令重试间隔的唯一持久化位置；测试项页面从该处加载并只写回该处。`test_project_config.ini` 与默认模板的 `[order]` 只保存测试命令，不得出现同名键；加载历史测试项目文件时必须忽略残留同名键，不得把它识别为命令，也不得覆盖 `config.ini` 当前值。更新时不得破坏 `config.ini` 其它段、配置项或注释
    - 强制基线测试：`test_test_item_config_store.TestItemConfigStoreTests.test_save_writes_retry_interval_only_to_legacy_other_config`
  - 「测试项配置」第五个 Tab 固定命名“开关机运行参数”，只展示 `startup_time`、`interval_time`、`number_of_tests`、`wait_command_done` 对应的四项中文名称；左侧必须使用黑色中文名称，不得显示原始键名或右侧灰色说明列；`communication_method`、`baud_rate`、`selected_profile`、`telnet_enable` 均不得显示，保存时前三项必须保持原值，`telnet_enable` 必须由 Telnet 页反向计算并自动写入
  - 「测试项配置」Telnet 与 WiFi 页所有字段标签必须显示中文含义，不得直接显示 `request_url`、`input_user_flag`、`product_solution` 等 INI 原始键名
  - 「项目信息」页保留现有四个可手动编辑输入框，并提供“查询当前样机版本”按钮：仅使用当前通道的 PC 静态 IP / 样机管理 IP 与 Telnet 页当前连接参数锁源登录；只下发 `cat /etc/config/deviceinfo`、`cat /proc/version`，成功后在独立只读文本框显示软件版本、内部软件版本、ONU 软件编译时间，不支持手动修改、不覆写输入框、不自动保存、不下发配置/重启/升级命令；文本框支持鼠标选择，右键“复制全部”可复制当前字段
  - WiFi 页必须完整映射旧 WiFi 参数窗口并保存到当前测试方案 `[connect_wifi]`：`enable`（主控）、`test_2g_enable`、`test_5g_enable`、`product_solution`、`auth_mode`、`cipher`、`choose_wireless_card`、`wireless_card_name`；老配置缺新增键时必须兼容回退为“2.4G/5G 开启、WPA2-PSK、AES、不指定网卡”。“刷新无线网卡”只枚举当前 pywifi 接口，不执行连接
  - 全流程子任务7必须把上述 8 项映射到无 GUI `OnuCongfig`，不得继续把频段、认证、加密或网卡选择写死；主控关闭时明确记录跳过日志。指定网卡开启但名称为空时启动前失败，运行电脑不存在所选网卡时子进程明确失败，不得静默回退其它网卡
  - 点击「测试项配置」后，首次创建必须使用与样机升级、写参和ONU注册一致的标准`Toplevel`自然映射，禁止执行`withdraw()`隐藏构建、`after(0)`强制恢复或嵌套`update()`；复用已有窗口只执行标准`deiconify → lift → focus_force`，不得依赖移动鼠标或其它额外输入才完成客户区绘制
  - **已确认验收（2026-08-12 / 2026-08-29）**：映射后120ms/360ms执行可恢复的1像素宽度脉冲，可触发Windows`WM_SIZE/WM_PAINT`整树刷新；项目负责人确认“测试项配置”打开后客户区直接完整显示、无需移动鼠标。2026-08-29确认20ms快速刷新与固定尺寸无阻塞居中的加载提速体感符合预期；刷新前后窗口尺寸与位置保持不变
  - 旧工具“电源控制”channel 1～16 的复选框必须严格等于新工具选中配置：`network_card_ip.ini` 中存在且 `enabled=1` 的 `channel_N` 才勾选，其余（不存在或 `enabled=0`）全部取消勾选；同步只读配置，不得改写新工具通道
  - 串口终端窗口位置 + 日志目录 → `~/.aouxue_serial_terminal.json`
  - VS Code `.vscode/launch.json` 中 `LineCheckAssistant` 入口以 `Cheating_machine_execution_tool` 为工作目录；`.venv_serial_upgrade` 配套 `tftpy==0.8.7`
  - 打包脚本非交互式；`.spec` 落 `line_check_assistant/packaging_specs`；同时生成完整免安装目录与ZIP，脱敏脚本不得覆盖当前运行配置目录，重建输出配置时不得遗留旧文件；生成ZIP前必须检查实际EXE内`tcl\init.tcl`和`tk\tk.tcl`
- **禁止破坏**：
  - 本机配置文件不入 Git
  - 免安装发布包不得包含构建电脑的凭据、通知/远程控制资料、本机路径、设备/源IP、ONU ID或硬件绑定；不得只交付无法找到配套配置的孤立EXE
  - INI 转义（含 `%`）不得再触发 `ConfigParser` 内插崩溃
  - 开发使用 `.venv_serial_upgrade`，不污染全局或 `.venv`
- **对应测试**：`tests/test_sample_upgrade_settings_store.py`、`tests/test_onu_registration_store.py`、`tests/test_legacy_ui_defaults.py`、`tests/test_legacy_ui_defaults_store.py`、`tests/test_test_item_config_store.py`、`tests/test_wifi_interfaces.py`、`tests/test_legacy_power_test_service.py`、`tests/test_app.py`、`tests/test_portable_release.py`
- **已确认验收（2026-08-30）**：分别保存`telnet_default_on=1/0`后，旧配置镜像及旧工具复选框均保持反向关系（`telnet_enable=0/1`）；WiFi八项的加载/保存、刷新无线网卡与子任务7真实连接均通过。
- **待确认**：修复后便携ZIP已在另一台Windows电脑确认可正常启动使用；该结论不自动覆盖脱敏后首次填写的网卡/串口、业务凭据、配置保存、串口枚举或各真实设备业务入口。当前电脑按约定不启动新EXE。已确认第五个Tab只显示四项运行参数，修改后保存并重开仍生效；隐藏字段未纳入本轮验收。

### 2.12 「全流程执行」子任务编排器（主界面「检查并执行测试」按钮升级）

- **状态**：已确认验收（Windows桌面交互：首次7项全不勾选、状态刷新、确认框、主界面状态徽标和进度条，2026-08-29）/ 已实现未验收（本次无人值守授权的Windows交互、真实样机7子任务端到端及异常路径）
- **核心行为**：
  - 主界面「检查并执行测试」按钮按下后弹出「全流程执行」窗口（替代旧实现的「直接跑 ping 检查」）
  - **7 个子任务（界面保留 1→7 行布局；勾选串口日志时在全流程开始预启动，其余任务保持 1→7 相对顺序）**：
    1. **自动上/下电**（默认不勾）—— 调 `power_on_service.power_on_selected_channels` / `turn_off_selected_channels` 同步执行；必填项：程控电源 COM + 上/下电（`sample_upgrade_settings.ini` 新增 `power_operation`）+ ≥1 已勾选通道
    2. **环境线路检查**（默认不勾）—— 复用 `network_ops.run_line_check()` 对每个已勾选通道做「查询 VLAN 网卡状态 → 完全匹配则复用/否则按需启用或设 PC 静态 IP → ping 样机管理 IP」；**致命失败**（任一通道 ping 不通 → 整个全流程停止）；必填项：≥1 已勾选通道 + 每通道 `vlan_name / adapter_alias / network_card_ip / device_manage_ip` 全部非空
    3. **样机升级**（默认不勾）—— 调主程序既有 `_start_page_upgrade` / `_start_serial_tftp_copy_upgrade`（异步起线程 + 弹确认框）；后者按当前设置继续分流 `Tftp指令` 与 `Tftp Put` 两条独立链路；必填项：升级方式 / 固件 / 超级用户凭据 / Tftp 指令或 Put。仅在本次勾选“无人值守”且已完成总确认时跳过本项确认框，并将升级完成结果写入主执行日志而不显示中间完成提示框；失败仍终止全流程
    4. **写样机参数**（默认不勾）—— 调主程序既有 `_start_sample_parameter_write`（异步起线程 + 弹确认框）；必填项：参数表路径（`sample_upgrade_settings.ini` 新增 `parameter_table_path`）+ 写参首次登录账号 / 密码。仅在本次勾选“无人值守”且已完成总确认时跳过本项确认框
    5. **ONU 注册**（默认不勾）—— 调主程序既有 `_on_onu_query_clicked` + `_on_onu_register_clicked`（异步起线程 + 弹确认框）；必填项：OLT IP / 用户名 / 密码
    6. **串口日志（管道期间持续记录）**（默认不勾）—— 界面仍保留第 6 行；勾选时在其它子任务前预启动，通过 Tk 主线程调全流程专用 `_open_pipeline_serial_logs`，先显示 `SerialTerminalWindow`，再执行窗口同一套 `open_all()` 动作打开当前全部 VLAN/COM；全部打开动作返回后才进入后续上下电、环境检查、升级、写参和开关机测试；**非致命**（任一串口打开失败需记录失败结果，但不阻塞后续）
    7. **执行开关机测试**（默认不勾）—— 通过 `legacy_power_test_service` 在独立无 GUI 子进程直接复用旧工具 `PowerOnOffTelnet` / `PowerOnOffSsh`、程控电源和 Start All 通道业务；严格读取当前 `config.ini [ui_defaults]`、当前方案、`network_card_ip.ini [power_supply] serial_port` 和新工具已勾选通道。启动旧业务前，必须以当前方案 `[project_info]` 中手动保存的软件版本、内部软件版本、ONU 软件编译时间为基准，逐台对全部已勾选通道锁源 Telnet 只读查询 `software_version`、`inner_sw_version`、`/proc/version` 编译时间并严格比对；三项基准值任一为空、任一通道查询失败或任一字段不一致，必须记录通道和差异并作为致命失败返回，**不得下发全通道断电帧或启动旧 Start All**。仅全部通道三项一致后才继续。初始化会先下发旧 Start All 的全通道断电帧 `55 00 AD 00 00 AD`，因此二次确认必须显示危险操作提示；之后仅启动新工具当前勾选通道。旧业务 `show_signal/show_signal_warning/show_signal_error` 操作员日志继续转发；logger 的 WARNING / ERROR 全部保留，INFO 只保留登录、连接、Ping、WiFi、重试、测试完成等关键结果；2 秒内同级同文日志只显示一次，同级同文旧日志连续出现时无论间隔多久也只显示第一条，出现其它可见旧日志或执行阶段日志后才允许再次显示；`<IP>登录成功` 在单次开关机测试运行期间必须按 IP 去重，即使多个 IP 交替输出，同一 IP 也只显示第一次，不同 IP 各保留一条，下一次重新启动测试后重新计数；旧英文 `The network card with IP <源IP> has been pinged` 必须按当前通信方式从当前方案 `request_url` 提取实际 Ping 目标，并在新工具显示为 `[旧工具Logs][INFO] Ping 成功：源网卡 <源IP> → 目标样机 <目标IP>`，不得写死目标地址或重复透传英文原文；实际电源帧必须以十六进制记录，最终结论不得过滤；`[旧工具Logs][INFO] *******通道 【N】 开始第M次测试*******` 正文必须在新工具执行日志中显示为绿色；旧工具真实结果路径 `test_results/device_N/device_N_command_results_*.log` 中形如 `2026-08-08 15:37:41.904434: 通道9下挂的设备在第1次测试时正常` 的完整行必须实时桥接为新工具 `[旧工具Logs][INFO]`，且不得改变旧结果文件字节内容。全部通道结束才判定子任务完成，任一通道失败为致命失败
  - “测试项配置（[order] 执行）”不得出现在全流程子任务列表、状态计算、确认顺序或执行分发中；主界面的“测试项配置”编辑器继续保留，可显式启动独立的单次预备测试，不接全流程调度。
  - 全流程窗口首次打开时 7 个子任务必须全部不勾选，不得自动选择环境线路检查或其它子任务；每行任务标题左侧为勾选框：选中时白底黑边小方框内显示“✓”、未选时保持空框，点击小方框或任务标题可切换；右侧实时显示「必填项当前状态」（绿色就绪 / 红色「缺: 字段1, 字段2」），「去配置」按钮跳到主程序对应子窗口或方法（「环境线路检查」去配置调 `_open_network_config()`：隐藏全流程窗口 + 把主界面拉到前台 + 主执行日志提示操作员去顶部「网络配置」卡片编辑）
  - 底部「刷新状态」只重算当前必填项状态，不下发设备或电源操作；用于去配置后主动核对状态
  - 管道构造上下文时优先读取仍然存活的升级 / ONU 窗口当前输入，不依赖本机 ini 的延迟保存；ONU窗口关闭前必须把最新配置同步回主程序内存缓存，关闭后不得因Python属性仍存在而读取已经销毁的C600业务映射`Text`，全流程7行状态不得统一显示`invalid command name ...!text`；写样机参数的参数表路径也直接复用同一实例级持久变量，选表后立即同步管道状态，重开写参窗口自动恢复并加载已选表；从配置窗口返回时自动刷新状态，避免已填写的字段被误判为缺失
  - 「自动上/下电」去配置调 `_open_power_control()`：弹出 COM 与上电/下电选择框，确认后保存配置、刷新本行状态并输出主执行日志；**不下发任何程控电源指令**
  - 管道子任务 1 选择「上电」时只调用 `turn_on_selected_channels()`、只发开启帧；选择「下电」时调用 `turn_off_selected_channels()`、只发关闭帧
  - **子任务间隔等待约束**：串口日志只在全流程开始预启动、环境线路检查完成后均不等待120秒；其余任一已选子任务结束后，只要实际顺序中还有下一项，就必须固定等待120秒，再开始下一子任务。最后一项后不等待；等待期间点击主界面“停止测试”必须立即中断并跳过全部后续子任务
  - 「开始执行」默认走「必填项未就绪警告 + 全流程执行确认」二次确认后启动后台线程；“本次无人值守”默认关闭、不写入本机配置，启用后缺任一已勾选任务必填项即拒绝启动，全包升级未选程控电源 COM 也拒绝启动；样机升级和批量写参的完成结果只记录到主执行日志，不以中间提示框阻塞后续子任务
  - 无人值守总确认必须列明当前已选样机升级的方式/传输/固件/并行数/恢复出厂，以及写参的参数表/并行数/清空参数/退出老化；授权仅传给子任务3/4，不包含 ONU 注册、停止、预检、失败处理或自动重试
  - 二次确认框在实际顺序多于一项时必须明确显示“串口日志预启动和环境线路检查完成后不等待；其余每个已选子任务结束后等待120秒，再开始下一个已选子任务”
  - 任一「致命」子任务（含「环境线路检查」）抛异常 → 整个全流程停止，弹错误框；串口日志失败只记结果不阻塞
  - 主界面“环境检查与开关机测试”卡片必须以 11 号粗体、带内边距的状态徽标实时显示“未运行 / 正在执行 / 正在停止 / 已完成 / 已停止 / 执行失败”；“正在执行”必须使用深绿色底白字高对比样式，其它状态分别使用灰、警告、成功或危险颜色语义；“停止测试”按钮仅在“正在执行”时启用
  - 同一卡片的确定型进度条必须在全流程启动时重置；进入子任务7后以本次从 `config.ini [ui_defaults] number_of_tests` 读取的值为总轮次，并显示“当前/总轮次”。旧结果文件每出现一个已选通道的第 N 轮正常结论，就更新该通道已完成轮次；`only_power_off_on` 路径不写正常结论时，进入第 N 轮必须确认前 N-1 轮已完成，最终成功再补齐总轮次。多通道总体进度取所有已选通道的最小已完成轮次，不得因单个快通道提前达到满格。总进度下方的可折叠“通道概览”必须显示每个已选通道的独立轮次和等待/运行/重试/失败/完成状态，点击小卡显示详情，“关注”行只列落后、重试或失败通道；左侧通道列表保持配置、勾选和结果日志入口，不以运行态着色。停止/失败保留最后进度和通道详情，全部成功显示满格；所有 Tk 控件更新必须回到主线程
  - “停止测试”按钮必须从全流程弹窗移动到主界面，不得在弹窗重复显示；点击后仍调用当前 `PipelineOrchestrator.request_stop()`，状态立即变为“正在停止”，普通子任务在安全退出后停止后续，旧 Start All 子任务直接接收同一停止事件
  - **已实现未验收（2026-08-31）**：通道概览必须在每次开关机测试启动前，只清空本次所选通道的内存重试/失败历史；运行中须在旧工具原始日志精简、去重之前，按通道记录重试、重试后成功和最终失败事件及所属轮次。主界面的当前摘要必须保持单行；点击小卡必须打开可滚动的非模态独立窗口查看该通道本次完整历史，窗口打开期间随新事件刷新。历史不得串入其它通道、写入配置或改动旧结果文件。Windows 源码版和真实样机异常路径待项目负责人确认。
  - 二次确认后必须先成功启动后台线程，再调用 `withdraw()` 隐藏全流程配置窗口；运行期间主入口不得重新显示该窗口，完成/部分失败/异常提示必须以主界面为父窗口，流程结束后才允许再次显示配置窗口
  - 后台全流程完成/失败回调必须通过主程序 `pipeline_ui_task_queue` 回到 Tk 主线程，不得从后台线程调用隐藏 `Toplevel.after()`；主入口和停止按钮必须核对线程真实存活状态，线程已结束时自动清理残留运行态，不得连续出现“当前全流程仍在执行”和“当前没有正在执行的全流程”矛盾提示
- **核心验收行为（2026-07-20 单测全过，真实样机待验收）**：
  - 实现轮已执行 `scripts/verify_baseline.py` 并通过；当前完整测试结果以 `PROJECT_STATUS.md` 的最近一次记录为准，历史增量依据保留在 `DEVELOPMENT_LOG.md`
  - 编排器 7 子任务调度顺序与失败传播：已勾选串口日志必须最先预启动并执行“显示窗口 + 打开全部”，预启动后不等待；环境线路检查成功后直接进入下一任务；其余相邻已选子任务之间必须调用可停止的120秒等待；致命失败抛 `PipelineError`、任一串口打开失败则串口日志任务记失败但不阻塞、用户点主界面“停止测试”时 `request_stop` 在当前子任务或等待结束后终止后续
- **边界与异常**：
  - 必填项未就绪时弹「必填项未就绪」警告询问是否继续（不强阻，便于操作员知情决策）
  - 关闭窗口时若管道运行中弹「全流程执行正在进行」二次确认
  - 异步子任务（3/4）由主程序既有 worker 完成；管道在 Tk 主线程提交确认框和 worker 启动后，必须等待当前完成回调才执行下一子任务。写参启动时重新打开有效窗口，不得引用已关闭的 `Toplevel`；失败结果会停止后续致命子任务
- **禁止破坏**：
  - `TelnetSession` 协议（按 VLAN `bind_ip` 锁源）必须复用，不重写 telnet 客户端
  - 子任务 1/6/7 调既有 service，不绕过主程序中间层
  - 子任务 3/4 默认仍调主程序既有 `_start_*` 方法并由操作员点「是」；只有本次原生“无人值守”勾选和总确认完整摘要均已完成时，才允许向 3/4 传递一次性 `skip_confirmation=True`；子任务3还必须抑制中间完成提示框并写入主执行日志，成功后才开始下一项。子任务5 ONU注册始终由操作员确认
  - 子任务 2 调既有 `network_ops.run_line_check()`，不绕过主程序的网络准备流程
  - `0.0.0.0` 不出现在 telnet / tftp 路径（与 §1.4 一致）
  - 子任务7不得启动旧 GUI / EXE，不得 import 或实例化 `Auto_Power_On_Off_Tool.py` 的 `UiCase`；只允许无 GUI service 子进程复用旧 `test_case/common/clients` 业务类。子任务7之外的主程序路径继续与旧业务隔离
- **已确认验收（2026-08-29）**：首次打开窗口7个子任务均为空框；状态刷新、确认框、主界面状态徽标及开关机测试进度条交互符合预期。
- **待确认**：
  - Windows源码版：勾选“本次无人值守”后核对默认关闭、总确认摘要、仅升级/写参不再弹二次确认、样机升级完成不弹中间提示框而自动继续、缺项/无程控电源全包升级启动前拦截，以及关闭/重新打开后不保留授权
  - 真实样机端到端跑通 7 子任务全流程：串口日志预启动 → 上下电 → 环境检查 → 升级 → 写参 → ONU 注册 → 无 GUI Start All 开关机测试；重点确认全断电危险提示、当前勾选通道映射、旧 Logs 转发、停止行为和最终成功/失败判据
  - 异常场景：3/4/5 异步子任务失败传播（当前靠主程序 worker 异常冒泡 + 用户观察主执行日志；是否需要 polling + 状态轮询机制待定）
- **对应测试**：
  - `tests/test_pipeline_orchestrator.py`（7 子任务状态评估 / run 顺序 / `[order]` 项不存在 / 致命失败抛 PipelineError / 串口失败不阻塞 / request_stop 阻止后续 / 无 GUI Start All service 委派 / 编号 1→7 顺序守门）
  - `tests/test_legacy_power_test_service.py`（配置加载 / 空 COM 拦截 / 旧 Logs 桥接 / 实际电源帧格式 / 不导入旧 GUI 主类）
  - `tests/test_sample_upgrade_settings_store.py`（+3 项：power_operation / parameter_table_path 持久化 / power_operation 非法值回退 `up`）
  - `tests/test_app.py`（当前ONU配置读取必须跳过已销毁的C600业务映射Text，并在保存成功后更新内存缓存；`_current_sample_upgrade_settings`透传新增字段）
  - `tests/test_pipeline_window.py`（窗口默认无勾选、确认提示、上下文不加载测试项目配置、已销毁ONU Text跨模块回归及7项状态完整性）

### 2.13 DUT 配置 - UBUS 批量配置

- **状态**：已确认验收（2026-08-13 DUT配置窗口布局、连续查询与session注销、DUT网卡按需复用、WAN配置；2026-08-14单台2.4G WiFi连续两次配置、60秒稳定等待及回读、仅2.4G WiFi五类下拉按DUT实际能力动态加载；2026-08-29独立目标选择、“全选/清除”、SSID递增和双频区域显隐）/ 已实现未验收（按选择过滤配置/查询的真实设备路径、SSID多台递增批次统一等待后逐台回读、双频两套Radio实际下发/回读及公共发射功率、5G WiFi动态能力、语音DTMF/SIP/编码动态能力、TR069实际字段约束、WiFi能力字段缺失兜底与目标变化清理、2.4G其它参数组合、5G/语音/TR069实际配置、Telnet状态准确性、1/8台并行及异常隔离）
- **核心行为**：
  - 主界面“串口日志”右侧固定显示“DUT配置”按钮；窗口采用 Notebook，包含“Telnet配置”“WAN配置”“2.4G WiFi配置”“5G WiFi配置”“语音配置”“TR069配置”六个独立 Tab；协议在 core、批量流程在 service，UI 只收集输入和显示结果
  - 六个 Tab 的字段名称必须在各自标签单元格内统一左对齐；公共 `_field()` 创建的 WAN、WiFi、语音、TR069 标签及单独创建的“现有连接名/索引”不得恢复为右对齐，Telnet 页标签继续从左侧排列
  - 主界面已勾选通道只作为DUT候选范围；六个Tab目标表必须共享同一套独立“选择”列及“全选/清除”，首次加载默认选中全部候选，在任一Tab逐台切换后其它Tab立即同步。刷新相同候选必须保留手动取消状态，新加入候选默认选中，已移除候选自动删除；运行期间不得修改选择。所有配置、Telnet/WAN/WiFi/语音/TR069查询、启动前校验、确认目标和批次统计只能处理DUT窗口当前已选目标，未选目标的配置错误不得阻塞本批；未选任何目标时必须明确提示在DUT目标表勾选。选择变化必须使旧状态、WAN下拉及DUT动态能力失效；表格同时显示通道、VLAN、网卡、PC 静态 IP、样机管理 IP 和逐台状态。账号密码与写样机参数 `parameter_initial_*` 共享并明文显示、明文记录
  - 启动前拒绝无目标、缺 VLAN/网卡/IP/凭据、IP 格式错误、源 IP 与样机 IP 相同以及重复 VLAN；确认框明确提示会修改本机网卡与 DUT AccessCtrl 规则
  - 单台固定时序：`prepare_network_for_sample(reuse_if_ready=True)` 先只读查询目标网卡启用状态及 IPv4/前缀；已启用且目标地址/前缀完全匹配时跳过重复启用和静态 IP 设置，部分不匹配时只修复对应项，状态读取失败时回退原完整准备流程 → `wait_for_bindable_ip` 最多 15 秒（复用时也不得跳过）→ 每台独立 `UbusHttpClient(bind_ip, device_host, 80)` → `enable_telnet_via_ubus` → 严格 `source_address=(bind_ip, 0)` 探测 TCP 23 端口；只有 UBUS 与端口探测均成功才标记成功
  - UBUS 首次失败后最多重试 3 次、间隔 2 秒；端口最多探测 3 次、单次 5 秒、间隔 1 秒；UBUS client 每次尝试均关闭。Access denied 最终失败提示操作员退出样机 Web 管理页面后重试
  - 支持 1–8 并行、默认 1；单台失败不阻断其它 DUT。点击停止后不再提交尚未开始的 DUT，已进入系统/HTTP 调用的任务在安全点结束；运行期间输入、刷新、开始和关闭均受控
  - 主执行日志必须包含准备网络、明文 `session.login`、实际 `bbfdm get/set/add` 路径与参数、源/目标 TCP 23 验证以及逐台成功/失败/跳过和批次汇总
  - WAN：同一参数批量应用到已勾选 DUT；支持新增、修改和按明确连接名/数字索引删除，不提供“删除全部”；支持 router/bridge、IPoE/PPPoE、IPv4、IPv6、`IPv4AndIPv6` 双栈，IPv4 支持 DHCP/静态，IPv6 支持 SLAAC/DHCPv6/静态。新增/修改/删除统一调用登录态 `bbfdm.operate command=Device.X_SDMC_CreateWAN()`，并校验 `Result=OK`；修改/删除必须预检索引，删除确认框明确不可自动恢复
  - WAN 表单必须按真实创建规则联动：新增隐藏索引，修改显示索引，删除只显示索引；bridge隐藏路由/IP参数且业务类型仅允许IPTV/INTERNET/OTHER，未选择端口时默认LAN1；端口绑定必须使用LAN1–LAN8原生多选框并按1、2、4、8、16、32、64、128生成 `PortBind` 位掩码，查询回填必须把位掩码反向勾选到对应LAN口，修改时不得清除设备已有的非LAN绑定，新增时不得继承不可见旧位；业务类型为IPTV时，router/bridge均显示可选“组播 VLAN ID”，填写时校验1–4094并以 `MulticastVLANID` 下发，非IPTV必须隐藏并忽略残留值；IPoE隐藏PPPoE凭据并自动回填MTU 1500，PPPoE显示凭据并自动回填MTU 1492；IPv4/IPv6/双栈仅显示对应地址方式，动态方式隐藏静态地址字段。IPoE双栈只允许Dynamic+SLAAC、Dynamic+DHCPv6、Static+Static；PPPoE不得使用静态IPv4/IPv6，双栈只允许Dynamic+SLAAC或Dynamic+DHCPv6；UI收敛之外，service预检必须再次拒绝非法组合
  - 修改/删除的“现有连接名/索引”必须是只读下拉框，并提供“查询现有 WAN”按钮；查询按每台目标执行网络准备、等待源IP可绑、独立锁源UBUS登录和一次只读多路径 `bbfdm.get`，覆盖 IP Interface、Ethernet/VLAN、PPP、Bridge、DHCP、DNS、NAT，过滤LAN/透传等非可操作接口并按数字索引排序。单台显示本机连接并把业务类型、VLAN、组播VLAN、模式、端口绑定、接入方式、IP协议、地址方式、MTU、NAT及设备可返回的静态地址/DNS/PPPoE字段同步到当前表单；多台只显示所有查询成功目标名称完全一致的共同WAN，且只有完整参数在所有目标上一致时才自动回填，不能仅凭数字索引合并不同连接或拿任意一台参数覆盖整批；任一目标失败/停止不得生成下拉项。目标集合变化或WAN配置执行后必须使旧列表失效，查询完整信息和共同项汇总必须写入主执行日志
  - 每次成功登录产生的设备端 UBUS session 必须在查询/配置/异常重试结束时调用 `bbfdm.unauthenticated_operate Device.X_SDMC_Login.logout()` 释放；关闭本机HTTP连接不能代替设备注销。WAN查询主日志必须记录注销TX和结果，连续点击两次“查询现有 WAN”不得因上一轮残留session触发 `Access denied`
  - Telnet：“查询当前Telnet”必须只读获取AccessCtrl总开关和LAN Telnet规则，并严格绑定当前VLAN源IP探测TCP 23；当前状态区逐台显示总开关、规则存在/启用、SourceInterface和端口可连接状态。查询路径严禁执行set/add或隐式复用开启Telnet流程
  - WAN：“查询现有 WAN”的同一批逐台结果必须同时展示在WAN当前状态区，至少包含连接名、路由/桥接模式、业务类型和VLAN；不得仅为状态展示重复发起第二轮WAN查询。目标变化或WAN配置执行后必须清除旧状态
  - WiFi：2.4G与5G必须使用独立Tab，至少包含SSID索引、WiFi名称/密码、信道、信道带宽、启用/隐藏、认证/加密模式、协议类型、发射功率、最大接入数、WMM和双频合一。开放模式必须隐藏并忽略密码；加密模式必须校验WPA密码。2.4G与5G的信道、带宽和协议候选值必须分频段限制，不能把一个频段的Radio规则套到另一个频段
  - 2.4G与5G页必须各自提供默认关闭且互相独立的“SSID递增”。关闭时维持同一SSID批量下发；开启时输入SSID必须以数字结尾，按DUT窗口已选择目标的固定表格顺序生成逐台不可变请求，第一台保持输入值、后续加1并保留数字尾缀宽度。无数字尾缀不得自动补数，任一生成值按UTF-8超过32字节不得截断且必须整批拒绝。确认框与主执行日志必须逐台展示通道/VLAN到最终SSID的映射；并行补位或单台重试不得重新编号。双频合一继续使用当前DUT最终生成的SSID同步两个频段；查询只读设备现状，不得参与递增或改变开关
  - 多台目标开启SSID递增时，必须先完成所有目标的WiFi参数下发，仅在原目标顺序中最后一台成功下发的样机日志下执行一次可停止的60秒统一稳定等待，再为每台成功下发目标重新准备网络、登录并逐台回读校验；不得让前面每台各自重复等待60秒，也不得省略其回读。下发失败目标不进入回读且不阻断其它目标；统一等待期间停止时，已下发但尚未回读的目标必须标记停止而非成功。单台设置或未开启SSID递增时继续保持每台下发后等待60秒再回读的既有时序
  - WiFi查询必须只读获取`Device.WiFi.X_SDMC_Mapping_2G/5G`，结合Radio、AccessPoint、SSID节点的`X_SDMC_Instance`把界面SSID索引解析为两个频段各自的真实对象路径，再读取SSID/AP/Security/Radio及`X_SDMC_DualBandEnable`；严禁查询路径执行set。无论设备当前是否已开启双频合一，查询当前2.4G或5G时都必须预读另一频段Radio状态和能力，供操作员随后勾选双频合一。配置必须使用各自解析后的真实路径并回读校验
  - 开启双频合一时，当前页必须同时显示当前频段和另一频段两个独立射频参数区域；2.4G与5G的信道、信道带宽和协议类型分别配置，不能共用一个值。SSID名称、启用/隐藏、认证密码、最大接入数和WMM继续同步到两个频段；发射功率作为公共参数分别写入两个Radio。关闭双频合一时隐藏另一频段区域且只修改当前Tab Radio。双频回读必须分别核对两套Radio参数和公共功率，任一频段不一致均不得宣告成功
  - WiFi查询成功后，认证/加密模式必须按AP Security的`ModesSupported`加载；2.4G和5G的信道必须分别按各自`X_SDMC_ChannelsSupported`加载，带宽和协议必须分别按各自`X_SDMC_ModeBWMap`加载，发射功率优先按两个Radio的`TransmitPowerSupported`或兼容厂商字段加载；开启双频合一时公共功率候选取两个Radio均支持的值。设备返回能力时不得继续展示该设备不支持的固定候选，当前实际值即使未列入能力字段也必须保留以便显示。设备缺少对应能力字段时才允许使用分频段兼容兜底。目标DUT变化后必须清除上一目标的动态能力候选并要求重新查询；多台参数或能力不一致时不得拿任意一台覆盖整批表单
  - 语音：按 `Device.Services.VoiceService.1` 路径设置 DTMF、SIP 模式、代理/出站代理/注册服务器、账号、5 项编码和 DigitMap，最后回读 SIP 路径；查询后必须从VoIPProfile的DTMF支持字段、SIP的`X_SDMC_SIPModeSupported`兼容字段及标准`Device.Services.VoiceService.1.Capabilities.Codecs.`能力表加载DTMF、SIP模式和编码下拉，当前实际值必须保留，缺少能力字段时才使用兼容候选；UI与service使用同一能力列表，所选值原样写入设备，未知或当前DUT不支持的值必须在下发前拒绝；账号启用时必须预检显示名、认证账号和密码；“查询当前语音”必须按当前线路索引只读获取并展示上述完整状态
  - TR069：设置并回读 `Device.ManagementServer.` 的 ACS URL/账号/密码、周期 Inform、连接请求和证书参数；查询后必须按ManagementServer返回中实际存在的字段启用对应配置控件，缺失字段保持禁用且不得出现在`bbfdm.set`载荷；可选触发 `X_SDMC_ManualInformStage=1_wait_inform`并轮询最终`X_SDMC_InformResult`，设备未返回手动Inform能力时不得允许选择，停止事件可中断Inform等待；“查询当前TR069”必须只读获取并展示ManagementServer当前状态，“配置后手动 Inform”是动作选项，不得由查询自动勾选
  - 六个Tab均必须有“当前状态”区域。Telnet/语音/TR069/WiFi查询及WAN现有连接查询均复用网卡状态预检、源IP可绑等待、锁源client、1–8并行、停止和失败隔离；语音/TR069/WiFi仅在全部目标成功且参数一致时回填表单，不一致/失败不得拿任意一台覆盖整批。目标集合变化或执行对应配置后必须使旧状态失效，主日志必须记录实际get路径、完整状态、成功/失败及注销结果
  - 六个Tab的“当前状态”区域必须统一提供可拖动高度调节条，每个Tab独立限制在2–16行并保存到本机`~/.aouxue_dut_config.json`；底部“已加载 N 台目标 DUT”提示和“刷新/查询/停止/执行/关闭”按钮栏必须组成统一受保护区域，以Tab底部优先保留完整请求高度，再由状态区和目标表格使用剩余空间，不能依赖事后坐标测量。固定最大行数之外，还必须按当前Tab及底部区域的实际位置动态收敛，拖动、首次/再次显示、历史高度恢复和Tab切换均不得使提示或按钮被压缩、裁切、遮挡。拖动结束与窗口关闭均保存，下次打开自动恢复各Tab上次有效高度；恢复值在当前布局下会遮挡底部区域时必须自动降低并保存校正值。状态文件缺失、损坏、字段未知或高度越界时必须安全忽略/收敛，不得阻止DUT窗口打开、关闭、查询或配置
  - DUT配置窗口关闭时必须把实际宽度和高度保存到同一`~/.aouxue_dut_config.json`，下次打开在创建内容前恢复；窗口尺寸与当前状态高度的任一保存均不得覆盖另一字段。尺寸不得低于1530×880；在不低于该最小尺寸的前提下，跨屏幕后超过当前屏幕的历史值必须按当前屏幕收敛；状态文件缺失、损坏、字段未知或尺寸非法时回退默认1530×880，不得阻止窗口打开或关闭
  - DUT配置首次创建必须使用标准`Toplevel`自然映射，禁止执行`withdraw()`隐藏构建、`after(0)`强制恢复或嵌套`update()`；状态高度校正只在Tk空闲阶段执行，复用已有窗口只做标准恢复、置顶和聚焦，不得出现透明客户区或依赖移动鼠标触发完整显示。DUT和测试项配置已知最终窗口尺寸时，居中不得为了读取客户区尺寸而同步刷新整棵控件树；20ms快速尺寸刷新不得替代或删除120ms/360ms两次已验收兜底
  - **已确认验收（2026-08-12）**：映射后120ms/360ms的可恢复1像素尺寸刷新生效；项目负责人确认“DUT配置”打开后六个Tab客户区直接完整显示、无需移动鼠标，窗口尺寸位置无异常。2026-08-13增加的20ms快速刷新和已知尺寸无阻塞居中只属于加载提速，原两次验收刷新继续保留
  - **已确认验收（2026-08-13，窗口布局）**：项目负责人确认六个Tab字段左对齐、原生勾选框外观、当前状态区高度拖动及逐页保存恢复、底部提示/按钮保护、窗口宽高保存恢复和20ms快速刷新均符合现场预期。
  - **已确认验收（2026-08-13，连续查询与网卡复用）**：项目负责人确认同一DUT连续两次Telnet/WAN/WiFi/语音/TR069查询均成功，每轮设备session正确注销，不再因残留会话出现第二次`Access denied`；网卡已满足、仅地址不符、禁用及状态读取失败四类按需准备路径均符合预期，并继续执行源IP可绑定确认。
  - **已确认验收（2026-08-13，WAN配置）**：项目负责人确认现有WAN只读查询下拉和完整表单回填、新增/修改/明确连接删除、IPoE/PPPoE字段及MTU联动、IPv4/IPv6/双栈动态与静态组合、路由/桥接、NAT、LAN1–LAN8端口绑定、IPTV组播VLAN、多台共同WAN及状态展示均通过现场验收。
  - **已确认验收（2026-08-14，2.4G WiFi连续配置）**：项目负责人确认同一真实DUT连续两次修改2.4G WiFi配置均成功；每次下发后等待60秒再回读，第二轮不再在`Device.WiFi.Radio.`读取时报`timed out`。本结论只覆盖单台连续两次配置时序，不代表5G、2.4G其它参数组合、开放网络、隐藏SSID、双频合一或多台并行已经验收。
  - **已确认验收（2026-08-14，仅2.4G WiFi动态能力下拉）**：项目负责人确认2.4G页的认证/加密模式、信道、信道带宽、WiFi协议类型和发射功率五类下拉会按真实DUT实际支持能力动态加载，工具不再展示该DUT不支持的固定候选；其中认证/加密模式与DUT管理页面一致，仅显示`None`、`WPA2-Personal`和`WPA3-Personal-Transition`。本结论不包含5G，也不扩大为设备缺少能力字段时的兜底、目标变化后的旧能力清理或WiFi实际配置组合验收。
- **已确认验收（2026-08-29，Windows桌面交互）**：DUT窗口独立目标选择、全选/清除、SSID递增以及双频合一时另一频段射频区域的显隐均符合预期；未扩大为真实设备下发、统一稳定等待或双频回读结论。
- **已确认验收（2026-08-30，独立目标隔离）**：主界面同时选择`vlan112`/`vlan113`、DUT窗口仅选择`vlan112`后，分别完成查询和配置；现场确认整个DUT流程未访问`vlan113`。
  - WAN/WiFi/语音/TR069 复用主界面通道和 Telnet 页 UBUS 凭据/并行数；同一时间只允许一个 DUT 配置批次。每台均执行“准备网络 → 等源 IP 可绑 → 每台独立 UBUS 登录 → 功能配置 → 回读/结果校验 → 关闭 client”，登录失败最多重试3次，功能下发不自动重试，避免 WAN 重复创建
  - 五个新增 Tab 的主执行日志必须包含功能阶段、明文登录、实际 UBUS method/path/input、成功/跳过/失败和批次汇总；表格只显示简短逐台结果
  - WAN的LAN1–LAN8端口绑定和“启用 NAT”、两个WiFi页的“启用WiFi/隐藏WiFi/启用双频合一/启用WMM/SSID递增”、语音“启用 SIP 账号”、TR069“启用周期 Inform / 启用 HTTP 连接请求 / 启用证书 / 配置后手动 Inform”必须使用 Windows 原生 `Checkbutton`：选中显示标准“✓”，未选为空框，不得继续使用 Clam 主题下显示叉号的 `ttk.Checkbutton`；各 BooleanVar 默认值和配置语义保持不变
- **禁止破坏**：不得复制第二份 AccessCtrl 协议；Telnet 必须继续复用 `enable_telnet_via_ubus`；每台功能必须使用独立 UBUS client 并绑定对应 VLAN 源 IP，结束时必须释放设备端session；网卡状态、目标 IPv4 或前缀任一不满足时不得错误复用，状态读取失败不得绕过原准备流程，任何复用路径不得跳过 `wait_for_bindable_ip`；不得直接导入使用共享静态 Session 的 `SdmcUbusLib`；WAN 删除不得自动扩大为删除全部或模糊匹配其它连接；不得重新向IPoE展示PPPoE凭据、向PPPoE提供静态地址或允许不受协议封装支持的双栈混合静态组合；不得把查询失败、仅部分DUT存在或同索引不同名称的WAN放入批量修改/删除下拉列表；WiFi不得绕过Mapping直接假定Radio/AP/SSID实例相同，双频合一不得拿当前Tab的信道、带宽或协议覆盖另一频段，必须使用另一频段独立输入和能力校验
- **待确认**：真实DUT以`Aouxue_001`对多台已选目标执行，核对确认框、主日志、实际下发与回读依次为001/002/003，且仅最后一台出现一次“等待 WiFi 参数生效并稳定：60 秒”、等待后每台均完成回读；再复验统一等待期间停止、单台下发/回读失败隔离、非法尾缀和32字节超限均不误报成功或产生错误写操作。真实DUT分别从2.4G页和5G页执行双频配置，核对两套信道/带宽/协议按各自候选下发、公共功率写入两个Radio并完成双频回读，取消双频时不修改另一Radio。Telnet查询准确显示AccessCtrl/规则/TCP23且不修改设备；WiFi设备缺少能力字段时正确兜底、目标变化后旧能力不残留；5G五类下拉与真实DUT能力一致，2.4G其它参数组合及5G真实Mapping、各字段查询回填/下发/回读、开放网络和隐藏SSID；语音DTMF/SIP/编码动态候选与真实DUT一致及实际下发/回读；TR069缺失字段正确禁用且不下发、查询参数准确性与一致参数回填；多台状态或能力不一致不覆盖表单、TR069查询不勾选手动Inform；真实样机覆盖主动触发Access denied、1/8台并行、停止和单台失败隔离。
- **对应测试**：`tests/test_network_ops.py`、`tests/test_dut_config_service.py`、`tests/test_dut_advanced_config_service.py`、`tests/test_dut_wan_query_service.py`、`tests/test_dut_status_query_service.py`、`tests/test_dut_ubus_config.py`、`tests/test_dut_wifi_config.py`、`tests/test_ubus_http_client.py`、`tests/test_telnet_transport.py`、`tests/test_ubus_enable_telnet.py`、`tests/test_app.py`

---

### 2.14 测试项单次预备测试

- **状态**：已确认验收（2026-09-10，项目负责人确认本次一键执行、每条一次不重试、主日志打印/保存及成功绿色/失败红色功能通过）/ 已实现未验收（多通道隔离、停止、无期望及断连等未单独反馈的专项）。
- **验收依据**：项目负责人在本次功能交付后明确反馈“验收通过”；未提供设备型号、台数或逐项异常场景记录，不扩展为EXE发布或其它设备流程的验收结论。
- 使用当前测试项和 Telnet 页快照及主界面勾选通道，整批校验、确认目标后逐通道逐命令执行；每条只执行一次，正式测试重试配置和执行路径不变，不自动保存配置。
- 成功与失败结果显式使用主日志绿色/红色；回显、命令、结果、停止和汇总自动保存到当前主日志。无期望不计为匹配成功；停止时已下发未校验和未执行分别统计。
- 不匹配或回显超时继续下一条；登录失败、网络失败或连接中断终止当前设备并继续下个已确认目标；停止阻止后续下发，关闭窗口先停止并等待日志队列排空。
- 自动化入口：`tests/test_test_item_pretest.py`；不以模拟会话/日志测试替代 Windows 界面、真实网卡或 Telnet 现场验收。

## 3. 待确认 / 疑似过时内容

- **消息推送页签（2026-10-11，已实现未验收）**：§2.11 新增第六页“消息推送”，四项配置加载、统一保存、重载和未保存提醒已加入回归测试；Windows可见界面布局、完整窗口保存重开待负责人确认。新增手动试发使用模拟HTTP验证，真实钉钉收信、签名及 @所有人效果待负责人确认，既有五页验收结论保持。
- **推送项目名称（2026-10-12，已实现未验收）**：需负责人确认正式完成/异常通知与手动试发均显示磁盘保存的 `project_name`，保存新名称后下次发送生效，空名称阻止发送；Windows 源码版及真实钉钉收信待确认。

- **2026-09-20 Web启动超时修复**：SDMC不误认启动`##`、等网口/HTTP服务就绪、无头HTML兼容，需现场重跑实际升级确认。已有VLAN148只读页面证据不能替代选固件/提交/等待/恢复出厂端到端结论。

- **2026-09-20 Web网关升级（§2.6.1，已实现未验收）**：窗口与真实多NIC出网、两种Boot方式、单次提交后固定30秒接90秒观察、恢复出厂、失败隔离及全流程待负责人现场确认；原TFTP验收结论不自动覆盖新Web路径。

- **2026-09-20 SDMC Boot分支（§2.4/§2.5，已实现未验收）**：两种TFTP方式均需现场确认上电稳定1秒后循环发送 `sdmc\r`、间隔1秒、成功提示后立即停止且不发送Boot凭据、600秒超时与失败隔离；旧账号方式回归、配置关闭重开、单独/无人值守确认一致性及恢复出厂最终登录均待Windows源码版和真实样机验收。后续传输与收尾不变量不变，既有验收结论不自动覆盖新分支。


- **§2.14 单次预备测试（2026-09-10，部分已确认验收）**：本次一键执行、每条仅一次、成功/失败颜色及主日志打印/保存已由项目负责人确认通过；未保存编辑快照、多通道目标隔离、无期望提示、停止与断连处理、正式测试重试复验仍待专项现场结果，EXE发布未验收。

> 列入此节的内容暂不进入第 2 节"功能验收清单"，直到对应依据补齐。

1. **§2.6 全包升级通用时序 中"恢复出厂命令实际下发 → 主程序执行日志输出 `TX firstboot -y;reboot`（2026-07-12）"** — 原文件标为"已确认验收"，但 `DEVELOPMENT_LOG.md` 在 2026-07-12 这天未找到对应的真实样机验收条目（当日三条记录为：Tftp指令 ARP 重试、Tftp Put 多台串行验收通过、全包升级关闭自动终端）。**已从 §2.6 中移除并降级为「待确认」**，待用户核对原始证据后再决定升回。

2. **§2.4 §Tftp指令 中"串口乱码盲发密码补救登录（`peek_since` salvage 路径）"** — 同样在已读到的 `DEVELOPMENT_LOG.md`（至 2026-07-12）中未找到对应的真实样机验收条目。**暂保留"已确认验收"标签**，需用户二次核对日期后确认或降级。

3. **历史测试数量**：旧版本在本文件多个章节写入 283、381 等阶段性数字，容易与后续测试数冲突。自 2026-07-23 起，本文件不再固化总数；最新完整验证结果只记录在 `PROJECT_STATUS.md`，每次增量保留在 `DEVELOPMENT_LOG.md`。

4. **文档职责**：`PROJECT_STATUS.md` 是当前交接状态，`ACCEPTANCE_BASELINE.md` 是验收与不变量依据。两者冲突时以本文的功能状态和不变量为准；操作步骤以 `Cheating_machine_execution_tool/line_check_assistant_README.md` 为准。

5. **§2.12 开关机测试逐通道状态（2026-08-31，已实现未验收）**：每个已选通道的独立完成轮次及等待/运行/重试/失败/完成状态必须显示在主界面测试卡的可折叠“通道概览”，左侧通道列表不再以运行态着色。指令尚有下一次验证时，对应小卡显示“重试”并输出黄色重试信息；重试后成功立即更新为正常运行或最终完成；重试用尽时显示“失败”并输出完整指令与验证次数。“关注”行只点名落后、重试或失败通道，点击小卡可查看当前阶段或异常详情。全部通道完成后，结束提示必须逐通道列出“验证失败”或“所有测试项验证成功”，不得只显示“全流程异常终止/失败通道编号”。其余通道继续执行、全断电确认、停止和致命失败边界保持原约束；Windows源码版与真实样机异常路径待项目负责人确认。

6. **§2.4 / §2.5 / §2.6 全包升级首轮 boot 时序（2026-08-31，已实现未验收）**：`Tftp指令` 与 `Tftp Put` 均改为上电帧下发后只稳定等待 1 秒，随后立即放行串口循环回车；不得保留 `Tftp指令` 的 10 秒补足启动等待，也不得在任一链路叠加第二个 1 秒等待。需分别在 Windows 源码版和真实样机确认首个回车、`UserName:`、boot 登录及后续传输稳定；此前不同等待行为的现场结论不自动覆盖本项。

7. **§2.4 / §2.5 / §2.6 全包升级未恢复出厂收尾（2026-09-01，已实现未验收）**：`Tftp指令` 与 `Tftp Put` 在传输后观察到 `Boot/Bood` 时，必须延迟 1 秒发送 `reset`；未观察到时，必须对当前通道执行后备下电再上电。未勾选恢复出厂时，两种动作后只等待 3 秒，记录跳过最终系统登录并结束当前通道；勾选恢复出厂时仍须保持 120 秒等待、最终系统登录和恢复出厂链路。需分别在 Windows 源码版及真实样机确认两种后处理分支。

8. **§2.6 最终系统登录成功判据（2026-09-01，已实现未验收）**：最终登录等待中不得把错误密码回显里的 `#` 或 `>` 当作 shell 提示符；只有独立 shell 提示符行才能成功，出现 `Login incorrect` / `incorrect` 必须判定登录失败，绝不可继续下发恢复出厂。需以含 `#` / `>` 的错误密码在 Windows 源码版及真实样机确认。

9. **§2.10 批量 ONU 逐台 ID（2026-09-06，指定C600场景已确认验收，其余场景待确认）**：项目负责人在修复交付后明确反馈“验收通过”，确认本次C600两台目标填写3、4后，确认执行仍保持3、4，不再变为4、5。该问题从待确认清单中关闭；C300、跨PON、重复/非法ID、重新查询清理等组合及全流程端到端继续单独验收。本次未提供逐条TX或OLT回读明细，不追加这些明细的独立验收结论，也不扩展EXE发布、删除或write范围。
