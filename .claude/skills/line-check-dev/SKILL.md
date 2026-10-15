---
name: line-check-dev
description: LineCheckAssistant 开发工作流。开工前先读 AGENTS.md + PROJECT_STATUS.md + DEVELOPMENT_LOG.md（最近 3 条）+ ACCEPTANCE_BASELINE.md 相关章节；按 ui/core/services/models 分层；改完代码必跑 `python -m unittest discover -s tests`，按规范追加 DEVELOPMENT_LOG.md 条目；默认不自动 commit；构建后不运行 dist\LineCheckAssistant.exe。覆盖任何代码改动、BUG 修复、重构、文档同步、真实样机验收记录。
---

# LineCheckAssistant 开发工作流

> 适用场景：开关机测试环境搭建助手（Windows Tkinter 桌面工具）的任何代码改动、Bug 修复、文档同步、真实样机验收记录。
> 工作目录：`F:\Aouxue\Power_OnOff_Assistant\`；主源码：`Cheating_machine_execution_tool\`。
> 所有 `src/`、`line_check_assistant/`、`tests/`、`scripts/` 相对路径均以主源码目录为准；先 `cd Cheating_machine_execution_tool` 再运行命令。

---

## 1. 开工前必读

按顺序读这 5 份文档，建立对当前状态的不变量认识：

| 文件 | 必读章节 | 用途 |
| --- | --- | --- |
| `AGENTS.md` | 全文件 | 项目硬规则、目录分层、文档纪律 |
| `PROJECT_STATUS.md` | 表格 + 「已完成/待完成/限制」 | 当前能力清单与未验收项 |
| `ACCEPTANCE_BASELINE.md` | §0 基线 + §1 全局不变量 + 改动章节 | 验收标签、grep 自检项、禁止破坏点 |
| `DEVELOPMENT_LOG.md` | 顶部最近 3 条 | 已完成改动的时间顺序记录与最近同类改动的写法 |
| 改动相关章节的单元测试 | `tests/test_<相关>.py` | 看现有断言、约定 mock 风格 |

**关键 grep 自检项（验收基线 §1.3）**：

```bash
# 以下命令在主源码目录执行；全部必须命中
grep -r "bbfdm.operate" src/
grep -r "tclinux_allinone" src/
grep -r "192.168.1.1" src/
grep -r "vlan_to_serial_port" src/ line_check_assistant/
grep -r "MAX_PARALLEL_UPGRADES = 8" src/
grep -r "clamp_parallel_count" src/ line_check_assistant/
grep -r "source_address=(bind_ip, 0)" src/ line_check_assistant/
grep -r "Device.Firewall.<X_SDMC_>Security.AccessCtrl" src/

# 严禁出现
grep -rn "0.0.0.0" src/core/tftp_transport.py src/core/telnet_transport.py
```

---

## 2. 分层与文件位置（硬规则）

```
src/ui/        只放界面代码（无业务编排）
src/core/      单个底层能力（ping、ssh、telnet、串口、TFTP、升级、写参 transport）
src/services/  多步骤流程编排
src/models/    数据结构与字段定义
src/utils/     工具函数（少量）
config/        配置文件（注：项目已统一到 Auto_power_on_off_tool/config/）
assets/        图标和图片
logs/          运行日志，不提交 Git
tests/         unittest（与 src/ 平级，从 src.X 与 line_check_assistant.X 导入）
scripts/       运行和打包脚本
line_check_assistant/  Tk 主程序、配置 store、UI 窗口、网络/页面升级模块
```

**禁止**：
- 业务逻辑写在 UI 文件里（`line_check_assistant/app.py` 的 UI 部分只能显示/输入/调 service）
- 改动 `Auto_Power_On_Off_Tool.py` 源码（旧工具，不再演进）
- 改动 `build/`、`dist/`、`logs/`、`.venv/`

### 2.1 渐进式模块化与已验收功能保护（硬规则）

1. **现有已验收功能默认保持原结构。** 文件较大本身不是主动拆分理由；不得为了减行、统一风格或顺手清理，跨模块搬迁、重写已通过 Windows / 真实样机验收的实现。
2. **新增功能从正确的独立模块开始。** 新窗口优先放 `src/ui/`，业务流程放 `src/services/`，底层协议放 `src/core/`，请求/结果模型放 `src/models/`；`line_check_assistant/app.py` 只保留入口装配、输入收集、service 调用和 Tk 主线程回调。
3. **旧代码只做需求触发的小步整理。** 当前需求必须修改既有大块代码时，只整理该需求直接涉及的一个功能或一个边界；保留既有入口、方法名或必要兼容代理，确保可以单独回退。
4. **结构调整与行为修改默认分开。** 不在同一轮同时大范围搬迁代码并改变默认值、INI / JSON 持久化、确认弹窗、执行日志、线程 / 队列、停止事件、设备命令或业务时序。确需合并时，先向用户确认并在计划中写明不可变行为、验证和回退方式。
5. **先保护再移动。** 结构调整前补齐当前行为的特征测试；调整后运行专项测试和完整基线。涉及已验收 UI 时继续做 Windows 源码版复验；涉及真实设备路径时只能由项目负责人提供现场结果，不得把自动化测试升级为真实样机验收。
6. **禁止用 Mixin 或共享全局状态掩盖耦合。** 新模块应拥有明确输入、输出、生命周期和停止边界，不得只是把同一批 `self.xxx` 状态分散到多个文件。

---

## 3. 改动分类与对应文档更新矩阵

| 改动类型 | DEVELOPMENT_LOG.md | PROJECT_STATUS.md | ACCEPTANCE_BASELINE.md | README / 子 README | tests/ |
| --- | --- | --- | --- | --- | --- |
| 新功能 | ✅ | ✅ 若改表格行 | ✅ 若改 §2.x 状态/不变量 | ✅ `line_check_assistant_README.md` 用户可见功能 | ✅ |
| Bug 修复 | ✅ | 一般不改 | ✅ 若改状态/边界 | 一般不改 | ✅ 至少 1 项回归 |
| 重构（无行为变化） | ✅ | 一般不改 | 一般不改 | 一般不改 | ✅ 全绿 |
| 真实样机验收 | ✅「真实样机验收 / 状态更新」段 | ✅ 升级状态标签 | ✅ §2.x 状态从「已实现未验收」→「已确认验收」 | 一般不改 | 一般不需新测 |
| 文档/注释/构建 | ✅ | 按需 | 按需 | 按需 | 不需 |

`ACCEPTANCE_BASELINE.md` 与 `PROJECT_STATUS.md` **冲突时以 baseline 为准**（baseline 抬头明示）。

---

## 4. DEVELOPMENT_LOG.md 追加模板（必须严格遵守）

每次改动完，在 `DEVELOPMENT_LOG.md` **顶部**追加一条（最新在最上）：

```markdown
## YYYY-MM-DD - 简短标题（动词开头，≤ 30 字）

- 类型：功能 / 优化 / 修改 / BUG 修复 / 文档 / 构建 / 测试 / 真实样机验收 / 状态更新
- 背景：（1-3 句）触发原因、用户诉求、报错信息（贴关键日志片段）
- 完成内容：（分点）① ... ② ... ③ ...
- 修改文件：（列表，每个一行相对路径）
- 验证方法：（具体可执行的命令）
- 验证结果：（py_compile 通过 / Ran N tests ... OK / 真实样机通过）
- 后续待办：（若全部完成可写"无"）
```

类型必须是以上枚举之一。标题用动词开头，不写"修复了 xxx"这种描述性语言。

---

## 5. 验证命令（必须跑）

按 `ACCEPTANCE_BASELINE.md` §0 + §1.3 + §1.4，统一封装在 `scripts/verify_baseline.py`：

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python scripts\verify_baseline.py
```

- 预期：`ALL CHECKS PASSED`，exit 0
- 任何一条 `FAIL` 都必须先修复再提交（`AGENTS.md` 规则 13）
- 验证包含 4 类检查：① 全量 py_compile ② 全量 unittest（解析 `Ran N tests`）③ §1.3 必须命中不变量 grep ④ §1.3 / §1.4 必须不出现模式 grep
- 单条检查的常量定义在 `scripts/verify_baseline.py` 的 `PY_COMPILE_FILES` / `MUST_EXIST` / `MUST_NOT_EXIST`；`AGENTS.md` 中同名章节是可读副本

新增单测后必须确认 `Ran N tests ... OK` 中 N 正确递增（之前的基线 + 本轮新增 = 当前）。

---

## 6. 真实样机验收记录

按 `ACCEPTANCE_BASELINE.md` §0「状态标签」定义升级流程：

1. 用户线下确认通过 → `DEVELOPMENT_LOG.md` 顶部追加「**真实样机验收 / 状态更新**」条目
2. `PROJECT_STATUS.md` 对应行从「代码与单元测试通过...待真实样机验收」→「已 N 台真实样机验收（YYYY-MM-DD）」
3. `ACCEPTANCE_BASELINE.md` 对应 §2.x 状态标签：
   - 全场景通过：`- **状态**：已确认验收`
   - 部分通过（如仅 1 台）：`- **状态**：已确认验收（N 台单台，YYYY-MM-DD）/ 已实现未验收（2/4/8 台并行）`
4. 在「核心验收行为」列出主执行日志期望序列（用户核对实际跑出的日志）
5. 更新测试基线到 `python -m unittest discover -s tests` 实跑数

**不要**在没有真实样机记录的情况下擅自升级状态标签。

---

## 7. Git 提交规则（硬规则）

- **默认不自动 commit**：改完代码不要 `git add` 或 `git commit`，等用户说"提交"再执行
- 提交时 Co-Authored-By 必须保留：`Co-Authored-By: Claude <noreply@anthropic.com>`
- 仅当用户明确说"提交"才执行；用户说"先不提交"则保留工作区改动
- 不动 `build/`、`dist/`、`logs/`、`.venv/`（即使有改动）

---

## 8. 构建规则（硬规则）

- GitHub每次发布只保留本次新版Release：先上传并核对新版全部附件、设为Latest并确认公开可下载，然后删除全部旧Release及附件。不删除Git标签或源码历史。
- 对外发布说明仅包含用户可见更新、下载与使用说明；不加入构建/测试数量、源码基准或工作区提交状态，以及打包电脑未运行/现场验收声明。验证和验收边界仍按本工作流写内部开发日志、状态及验收基线。

```powershell
# 打包
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_line_check_assistant.ps1

# 打包后不要在当前 PC 运行 EXE —— 只确认打包成功并报告路径
# dist\LineCheckAssistant.exe 仅在交付现场运行
```

---

## 9. 何时进入 plan mode

按工具内置触发条件 + 项目特定场景：

**必须 EnterPlanMode**：
- 新功能（添加新窗口、新流程、新协议）
- 多文件改动（≥ 3 个 py 文件）
- 修改 `src/core/`、`src/services/`、`src/services/sample_parameter_service.py` 等核心模块
- 改动不变量相关字段（`source_address`、`bind_ip`、`MAX_PARALLEL_UPGRADES` 等）
- 跨模块搬迁既有代码、拆分已验收窗口或重构线程 / 队列 / 停止边界；开始前还必须取得用户明确确认

**可以跳过**：
- 单行 typo / 注释调整
- 单元测试本身的修正
- 文档/DEVELOPMENT_LOG 同步

plan 文档存放：`.claude/plans/<slug>.md`（参考已有 `telnet-ubus-pre-enable.md`、`parallel-upgrade-to-8.md` 的格式）。

---

## 10. 常见坑（来自 DEVELOPMENT_LOG 真实记录）

| 坑 | 现象 | 规避 |
| --- | --- | --- |
| 串口升级 `sleep_fn=None` | `'NoneType' object is not callable` | telnet 路径走 `time.sleep`，不要传 `None` |
| UBUS set 用参数路径 | fault 9005 `EnableEnable` | 总开关 SET 用对象路径 `...AccessCtrl.`（末尾带点），不是参数路径 |
| 写参时先建 TCP 后 UBUS | telnet 端口未监听 timed out | 先 `enable_telnet_via_ubus` 再 `TelnetSession(...)` |
| 工厂模式 `ppctl clear` 位置 | 工厂模式重启复原 ppctl 表，"清空"白做 | 移到「二次登录成功后、15 项 set 之前」 |
| TelnetSession 不锁源 IP | 多网卡下随机选样机 | 严格 `socket.create_connection(..., source_address=(bind_ip, 0))`，不可绑直接抛错不回退 `0.0.0.0` |
| `network_card_ip.ini` 缺 `factory_bind_ip` | 弹窗报错"缺少工厂模式配置" | 用 `factory_bind_ip_for(network_card_ip)` 按"29 网段、主机位不变"派生（`network_ops.py`） |

---

## 11. 完成一次改动的标准动作清单

执行下列清单前，先应用 §2.1：判断是否触及已验收功能；若是，默认保持现有结构，只在当前需求直接边界内小步修改并列出不可变行为。新增功能必须先确定独立 `ui / services / core / models` 落点；跨模块搬迁既有代码时，即使文件数量未达到 3 个，也必须先写计划并取得用户确认。

1. 读 5 份文档，定位改动的 §2.x 章节与已有断言
2. **若改动 ≥ 3 文件或核心模块**：写 `.claude/plans/<slug>.md`，用 `EnterPlanMode` 让用户确认
3. 写代码（遵守分层、保留 `sensitive` / `known_secrets` 形参兼容）
4. 加单测（参照 `tests/test_*.py` 同类断言风格；优先 mock 外部 IO）
5. 跑 `python scripts\verify_baseline.py`，确认 `ALL CHECKS PASSED`（封装了 py_compile + unittest + §1.3/§1.4 grep；任一 FAIL 必须先修复再提交）
6. 在 `DEVELOPMENT_LOG.md` 顶部追加模板条目
7. **按 §3 矩阵同步其它文档**（PROJECT_STATUS / ACCEPTANCE_BASELINE / README）
8. 把改动文件、验证结果、后续待办告诉用户
9. **不执行 git commit**，等用户说"提交"
