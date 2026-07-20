# 项目交接状态

更新：2026-07-20（主界面「检查并执行测试」按钮升级为「全流程执行」管道编排器：6 子任务 1→6 串行 / 必填项状态展示 / 失败停止；新增 fuzzy_match_runner / test_item_execution_service / pipeline_orchestrator / pipeline_window；verify_baseline.py 29 文件 / 374 项单测全过）

## 项目目标与当前实现进度

`LineCheckAssistant` 是 Windows Tkinter 桌面工具，用于配置测试通道、自动上/下电、线路 Ping、串口日志、样机升级、批量写样机参数和 OLT ONU 注册。

| 能力 | 当前状态 |
| --- | --- |
| 通道/网卡配置、线路 Ping、内置多 VLAN 串口终端 | 已完成 |
| 程控电源直连（COM101–COM116） | 已真实样机验收 |
| 页面升级（UBUS 批量 + 可选恢复出厂） | 升级已完成；恢复出厂待真实样机验收 |
| 全包升级 `Tftp指令`、`Tftp Put`（串行/并行 1–8 台） | 已真实样机验收 |
| `Tftp指令` ARP Retry count exceeded 自动重试 3 次 | 已真实样机验收 |
| 批量写样机参数（VLAN 表匹配、并行、set/get 校验） | 已 1 台（2026-07-17）/ 6 台独立 VLAN 并行（2026-07-19）真实样机验收，Telnet 路径；2 / 8 台端点并行待真实样机验收（如现场需要） |
| 写样机参数 UBUS 启用 telnet（按 VLAN 网卡 IP 锁源） | 已 1 台（2026-07-17）/ 6 台独立 VLAN 并行（2026-07-19）真实样机验收，UBUS 三段日志确认；2 / 8 台端点并行待真实样机验收（如现场需要） |
| 写样机参数 7 个节奏常量（set 后 settle / get 超时 / 重试退避 / 项间间隔 / 登录超时 / 错峰启动） | 单元测试通过（2026-07-18，15 项 Pacing 回归） |
| 写样机参数可选 `ppctl clear` / `AGING_STATE=1`（主界面 Checkbutton）+ 默认并行 1 + 确认框 9 步自然顺序 + 清理失败步骤名标识 | 已 6 台独立 VLAN 并行（2026-07-19）真实样机验收 |
| 自动生成参数表 MAC 同批 OUI 固定 + 2.4G / 5G SSID 后缀取 MAC 末 4 位 + label 优化 | 已 6 台独立 VLAN 并行（2026-07-19）真实样机验收 |
| 随机批量参数表生成（`.xlsx`） | 已 6 台独立 VLAN 并行（2026-07-19）真实样机验收 |
| ZTE OLT ONU 查询、注册、离线 ONU 清理重试 | 已完成 |
| 单元测试 | 313 项通过（2026-07-20，原 283 + 测试项配置 store 13 + per-segment 否定 3 + verify_baseline 11 + 项目信息 Tab 2 + Telnet 默认已开启 1 + 内部软件版本扩展 0） |
| 测试项配置 ini 编辑器（`test_project_config.ini` 加载/编辑/保存，4 个 Tab：Telnet / 测试项 / WiFi / 项目信息；Q1=A 不接执行；Telnet Tab 顶部「Telnet 默认已开启」Checkbutton 默认勾选） | 已完成（2026-07-20，283 → 296 项单测全过；新增项目信息 Tab + Telnet 默认已开启 后 310 → 313；待 Windows 桌面真实交互验证） |
| 「全流程执行」管道编排器（主界面「检查并执行测试」按钮升级：6 子任务 1→6 串行 / 必填项状态 / 失败停止 / 弹「全流程执行」窗口） | 已实现未验收（2026-07-20，313 → 374 项单测全过；pipeline_orchestrator 26 项 / test_item_execution 14 项 / fuzzy_match_runner 18 项 / sample_upgrade_settings 3 项；待 Windows 桌面真实交互验证 + 真实样机串行 6 子任务全流程跑通） |
| `scripts/verify_baseline.py` 回归门禁（py_compile + unittest + §1.3/§1.4 grep 不变量） | 已落地（2026-07-20，AGENTS.md 规则 13 强制提交前全绿；故意破坏实验证明可拦截不变量修改；本轮扩到 29 个 .py 文件 + 374 项单测） |

## 关键文件及其作用

- `Cheating_machine_execution_tool/run_line_check_assistant.py`：源码启动入口。
- `Cheating_machine_execution_tool/line_check_assistant/app.py`：Tk 主界面、各功能窗口、后台 worker 与主执行日志。
- `Cheating_machine_execution_tool/src/core/serial_transport.py`：串口独占会话、单读线程、固定 `vlan{N} -> COM{N-100}` 映射。
- `Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`：全包升级、boot 登录、ARP 重试、并行调度、程控电源协调。
- `Cheating_machine_execution_tool/src/core/tftp_transport.py`：TFTPy Server/Client；并行设备拉取时严格绑定 VLAN IP。
- `Cheating_machine_execution_tool/src/services/sample_parameter_service.py`：批量写参预检、工厂模式流程、`set/get` 校验、取消清理与并行调度。
- `Cheating_machine_execution_tool/src/core/sample_parameter_table.py`：Excel/CSV/XLS 参数表读取、规范 `.xlsx` 导出、随机参数生成。
- `Cheating_machine_execution_tool/src/models/sample_parameter_models.py`：15 项标准写参字段、记录、请求和结果模型。
- `Cheating_machine_execution_tool/src/ui/serial_terminal.py`：多 VLAN 终端与高频日志节流渲染。
- `Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`：UBUS 页面升级与升级后恢复出厂。
- `Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`：测试项配置 ini（`test_project_config.ini`）的加载 / 编辑 / 保存服务（Q1=A：仅编辑器，不接主程序执行）。
- `Cheating_machine_execution_tool/scripts/verify_baseline.py`：项目级回归门禁脚本（py_compile + unittest + `ACCEPTANCE_BASELINE §1.3/§1.4` grep），AGENTS.md 规则 13 强制提交前全绿。
- `Cheating_machine_execution_tool/tests/`：单元测试；`line_check_assistant_README.md`：操作说明。

## 已完成、待完成和当前问题

**已完成**：

- 主程序全包升级使用内置 pySerial、TFTPy 和程控电源，不依赖 SecureCRT、Tftpd64 或旧工具 GUI。
- `Tftp指令` 是样机从本机 TFTPy Server 拉取固件；`Tftp Put` 是本机 TFTPy Client 向样机 `192.168.1.1:69` 推送固件，两条链路均已真实验收。
- 并行升级最大 8 台、默认 2 台；同 COM 程控电源批次内复用长连接，串口终端仅重绘当前 Tab，避免高频日志卡死 UI。
- 串口日志记录终端已支持命令输入框回车发送：非空等价「发送」按钮、空字符串等价「回车」按钮，自动升级占用与危险命令二次确认仍生效（2026-07-15 真实样机验收通过）。
- 批量写参可按参数表 `VLAN` 匹配已勾选通道，预检重复/缺失 VLAN、重复 COM、MAC 和危险字符；写入前二次确认，标准流程为（2026-07-19 9 步自然顺序）1. 进入工厂模式（`ppctl set FACTORY_MODE=1`）→ 2. `firstboot -yr` → 3. 等待 100 秒 → 4. 工厂模式二次登录 → 5.（可选 `ppctl set AGING_STATE=1`）→ 6.（可选 `ppctl clear`）→ 7. 15 项 `ppctl set/get` 读回校验 → 8. 退出工厂模式（`ppctl set FACTORY_MODE=0`）→ 9. `firstboot -yr`（8/9 步在 `finally` 中执行）。默认并行 1（Spinbox 仍允许 1–8 现场上调），6 台真实样机验收通过。随机生成表只导出/加载预检，不自动下发；同批 MAC 前 6 位 OUI 固定 + 2.4G / 5G SSID 后缀取本机 MAC 末 4 位，6 台真实样机验收通过。
- 「测试项配置」窗口改造为 `test_project_config.ini` 编辑器（Q1=A：仅展示 + 编辑 + 保存，不接主程序执行）。四 Tab（Telnet / 测试项 / WiFi / **项目信息**）覆盖 ini 四段；项目信息 Tab 包含项目名称 / 软件版本 / ONU 软件编译时间 3 个字符串字段，**仅编辑器不被主程序消费**，用于操作员肉眼对照样机实际值。测试项 Tab 支持「否定勾选 + 动态段列表」表达 `!段A&&段B`，每条命令独立重试次数（1–99），顶部全局「指令重试间隔（秒）」默认 60 写到 `[order]` 段顶部；表单 dirty 时「重新加载」「关闭」弹「放弃修改？」二次确认；保存覆盖原 ini（标准 `configparser` 不保留注释，`[connect_wifi]` 段上方 `;` 中文注释会丢失）；283 → 296 项单测全过（store 13 项），新增项目信息 Tab 后 310 → 312 项全过。
- **「全流程执行」管道编排器（2026-07-20）**：主界面「检查并执行测试」按钮升级为弹「全流程执行」窗口，6 个子任务（自动上/下电 / 样机升级 / 写样机参数 / ONU 注册 / 串口日志 / 测试项配置）可勾选，按 1→6 固定顺序串行执行，任一「致命」失败（串口日志除外）→ 整个管道停止，弹错误框。窗口展示每行「必填项当前状态」（绿色就绪 / 红色「缺: 字段1, 字段2」），「去配置」按钮跳到主程序对应子窗口，「开始执行」走「必填项未就绪警告 + 全流程执行确认」二次确认后启动后台线程。子任务 1/5/6 同步执行（电源 / 串口 / 测试项），子任务 2/3/4 调主程序既有 `_start_*` 方法（异步起线程 + 弹确认框由操作员点「是」），不重写任何业务逻辑。新增模块：`src/core/fuzzy_match_runner.py`（移植老工具 `fuzzy_match.py` per-segment `!A&&B` 语义，AGENTS 硬规则不改老工具源码）、`src/services/test_item_execution_service.py`（[order] telnet 下发 + fuzzy 匹配 + per-command retry + per-channel 结果文件，源 IP 锁源复用 `TelnetSession`）、`src/services/pipeline_orchestrator.py`（6 子任务调度 + 状态评估 + 失败传播）、`line_check_assistant/pipeline_window.py`（弹窗 UI）；新增持久化字段 `sample_upgrade_settings.ini` 的 `power_operation` / `parameter_table_path`；`scripts/verify_baseline.py` 增 3 个 py_compile 路径；374 项单测全过（313 + 18 fuzzy + 14 test_item + 26 pipeline + 3 settings）；本轮「已实现未验收」待 Windows 桌面真实交互 + 真实样机 6 子任务全流程跑通。

**待完成**：

- 真实样机验收页面升级“恢复出厂”。
- 真实 2 / 8 台端点独立 VLAN/COM 并行验收批量写参（2026-07-17 已 1 台验收通过；2026-07-18 已将 7 个节奏常量常量化 + 错峰启动 0.6s；2026-07-19 已 6 台独立 VLAN 并行验收通过，覆盖原计划 2 / 4 / 8 区间的中段代表性场景；若现场后续推 8 台满载或换新型号，按现场经验微调节奏常量并补端到端验收）。

**当前问题/限制**：

- 仅支持 Windows；设置网卡 IP 需要管理员权限。
- 串口映射固定为 `vlan{N} -> COM{N-100}`，未配置化；批量写参参数值不允许双引号、回车或换行。
- 新增的写参密码输入框和随机参数表生成窗口均按操作员要求明文显示；下发记录、串口终端和文件日志仍脱敏。
- 现场若出现新型号、登录异常或网络异常，应先保留日志并扩展对应分支，不预先改变已验收时序。

## 重要技术决策与限制

- 严格保持 `Tftp指令` 与 `Tftp Put` 分离，禁止合并为同一传输流程。
- 并行 `Tftp指令` 的监听 socket 和 RRQ 数据 socket 都必须绑定当前 VLAN IP，不能回退 `0.0.0.0`；`Tftp Put` 不启动本地 TFTP Server。
- 升级、重启、恢复出厂、批量写参均必须保留确认提示和主执行日志；新增功能必须记录关键阶段、实际命令、成功、跳过或失败。
- 页面升级恢复出厂只能发生在升级成功、设备重启且独立 UBUS session 重新登录成功之后。
- 保持分层：`src/ui` 只放界面，`src/core` 放底层能力，`src/services` 放流程编排，`src/models` 放数据结构。
- 不修改 `build/`、`dist/`、`logs/`、`.venv/`；开始新工作前先保留现有工作区改动，默认不自动提交 Git。

## 运行、测试和继续开发的方法

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m pip install -r .\requirements.txt
python .\run_line_check_assistant.py
python -m py_compile line_check_assistant\app.py src\services\serial_upgrade_service.py src\services\sample_parameter_service.py
python -m unittest discover -s tests -v
```

- 当前全量测试预期：`Ran 310 tests ... OK`（2026-07-20 实跑；原 299 + verify_baseline 11 项 = MUST_EXIST/MUST_NOT_EXIST 结构 / PY_COMPILE_FILES 路径校验 / check_must_exist 命中缺失目录不存在 / check_must_not_exist 命中缺失注释行缩进注释）。推荐提交前跑 `python scripts\verify_baseline.py` 作为更严的门禁（封装 py_compile + unittest + §1.3/§1.4 grep）。
- VS Code 使用 `.vscode/launch.json` 的 `LineCheckAssistant`，工作目录为 `Cheating_machine_execution_tool`。
- 打包：`powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1`；构建后不要在当前 PC 运行 `dist\LineCheckAssistant.exe`，仅确认构建成功并报告路径。
- 每次代码、测试或文档改动后追加 `DEVELOPMENT_LOG.md`；影响本文件结论时同步更新本文件。
