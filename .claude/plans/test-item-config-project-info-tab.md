# 测试项配置 — 新增「项目信息」Tab

## 背景

用户在 `line_check_assistant_README.md`「测试项配置窗口」截图下追加诉求：在三 Tab 之外**新增一个「项目信息」Tab**,配置项为可供参考的项目基础信息:

1. **项目名称** (project_name)
2. **软件版本** (software_version)
3. **ONU 软件编译时间** (onu_compile_time)

用户已确认（2026-07-20 当前会话 AskUserQuestion）：

- 字段集合 = 基础 3 项
- ini 段名 = `[project_info]`
- 全部按字符串存取（不强制 ISO 格式）
- **仍走 Q1=A 决策**：仅编辑器，不参与任何自动比对或主程序执行；这 3 项用于操作员在主程序执行中肉眼对照样机实际值（例如与 `ifconfig` / `bbfdm` 输出对比版本号与编译时间），不接主程序消费。

窗口已经有 3 个 Tab（Telnet / 测试项 / WiFi），新 Tab 与之并列；现有 dirty / 重新加载 / 保存 / 关闭 / 二次确认 / `[test_item_config_store.py]` 读写的整套约定不变。

## 改动总览

| 改动 | 落点 | 行为变化 |
| --- | --- | --- |
| 数据模型 | `line_check_assistant/test_item_config_store.py` | 新增 `PROJECT_INFO_SECTION` / `ProjectInfoSettings` 3 字段；`TestProjectConfig` 新增 `project_info: ProjectInfoSettings` |
| 持久化 | `test_item_config_store.py` `_load_project_info` / `_dump_project_info` | 兼容老 ini（缺段 → 3 字段默认空串）；保存时统一写 `[project_info]` 段 |
| UI | `line_check_assistant/app.py` `_build_test_item_project_info_tab` | 2 列网格：标题 / 3 个 Label+Entry / 底部说明；返回 `{capture, load}` 与现有 Tab 同形 |
| 主窗口接线 | `app.py` `_open_test_item_config` | 新增 `project_info_vars = self._build_test_item_project_info_tab(...)`；reload/save 链路同步接入；顶部描述从 3 段扩为 4 段 |
| 测试 | `tests/test_test_item_config_store.py` | 默认回退 / 往返 / 段缺省容错 3 项 |
| 文档 | `line_check_assistant_README.md` / `PROJECT_STATUS.md` / `DEVELOPMENT_LOG.md` | README 增加第 4 个 Tab 描述；STATUS 矩阵「测试项配置 ini 编辑器」更新为「4 个 Tab，Q1=A 不接执行」；DEVELOPMENT_LOG 追加完整条目 |

## 实现方案

### 改动 1 — `test_item_config_store.py` 模型扩展

`test_item_config_store.py` 顶部新增段名常量：

```python
PROJECT_INFO_SECTION = "project_info"
```

在 `ConnectWifiSettings` 之后新增 dataclass（3 字段都默认空串，与老 ini 没有 `[project_info]` 段时回退默认值一致）：

```python
@dataclass
class ProjectInfoSettings:
    """``[project_info]`` 段。Q1=A:仅做 ini 编辑器,不被主程序消费。

    字段含义:
        project_name: 项目名称
        software_version: 软件版本
        onu_compile_time: ONU 软件编译时间(自由文本,不强制格式)
    """

    project_name: str = ""
    software_version: str = ""
    onu_compile_time: str = ""
```

`TestProjectConfig` 新增字段:

```python
@dataclass
class TestProjectConfig:
    telnet: TelnetSettings = field(default_factory=TelnetSettings)
    order: OrderConfig = field(default_factory=OrderConfig)
    connect_wifi: ConnectWifiSettings = field(default_factory=ConnectWifiSettings)
    project_info: ProjectInfoSettings = field(default_factory=ProjectInfoSettings)
```

`load()` 改一行（`TestProjectConfig(...)` 添字段）：

```python
return TestProjectConfig(
    telnet=self._load_telnet(parser),
    order=self._load_order(parser),
    connect_wifi=self._load_connect_wifi(parser),
    project_info=self._load_project_info(parser),
)
```

`save()` 添一行写入:

```python
parser[PROJECT_INFO_SECTION] = self._dump_project_info(config.project_info)
```

新增私有方法（与 `_load_connect_wifi` / `_dump_connect_wifi` 同风格；缺段容错通过 `parser.has_section` + `parser.get` 的 fallback 实现，**不抛 `NoSectionError`**）：

```python
def _load_project_info(self, parser):
    section = PROJECT_INFO_SECTION
    return ProjectInfoSettings(
        project_name=parser.get(section, "project_name", fallback=""),
        software_version=parser.get(section, "software_version", fallback=""),
        onu_compile_time=parser.get(section, "onu_compile_time", fallback=""),
    )

def _dump_project_info(self, info: ProjectInfoSettings) -> dict:
    return {
        "project_name": info.project_name or "",
        "software_version": info.software_version or "",
        "onu_compile_time": info.onu_compile_time or "",
    }
```

`__all__` 末尾追加 `"PROJECT_INFO_SECTION"` 与 `"ProjectInfoSettings"`。

**关键不变量**：

- 不动既有 `TelnetSettings` / `OrderConfig` / `ConnectWifiSettings` 字段；`TestProjectConfig` 字段顺序保持 `telnet / order / connect_wifi / project_info`，新字段排在最末，对旧 round-trip 兼容。
- 不在 `parser.write` 前手工写任何空段；老 ini 缺 `[project_info]` 时 `save` 会**新建**一个空段（3 字段空串），与 `connect_wifi` 段的行为一致（即使 enable=0 也写段），保持 configparser 行为单一来源。
- `enable` 字段在 `ProjectInfoSettings` 不存在（仅 3 字符串字段），不需要 0/1 强制转换。

### 改动 2 — `line_check_assistant/app.py` UI 与接线

`app.py` 顶部 import 加入 `ProjectInfoSettings`：

```python
from .test_item_config_store import (
    DEFAULT_COMMAND_FAIL_RETRY_INTERVAL,
    ConnectWifiSettings,
    ExpectedSegment,
    OrderConfig,
    OrderItem,
    ProjectInfoSettings,
    TelnetSettings,
    TestItemConfigStore,
    TestProjectConfig,
)
```

`_open_test_item_config` 内修改 3 处：

1. 顶部描述文案（line ~2366）从「telnet / 测试项命令 / WiFi 连接」扩为「telnet / 测试项命令 / WiFi 连接 / 项目信息」；
2. `notebook` 三个 Tab 构造下面增加一行：
   ```python
   project_info_vars = self._build_test_item_project_info_tab(notebook, config.project_info, mark_dirty)
   ```
3. `reload` 内追加 `project_info_vars["load"](reloaded.project_info)`；
4. `save` 内 `TestProjectConfig(...)` 多传 `project_info=project_info_vars["capture"]()`；二次确认弹窗文案「- 项目信息：项目={name}，软件版本={version}，编译时间={compile}」（全空时显示「全字段为空」）。

新增方法（与 `_build_test_item_wifi_tab` 风格一致：2 列 grid、标题 + 3 行 Label+Entry、底部说明、`capture`/`load` 回调对）：

```python
def _build_test_item_project_info_tab(
    self,
    notebook: ttk.Notebook,
    info: ProjectInfoSettings,
    mark_dirty,
) -> dict:
    """构建 [project_info] 段 Tab。返回 ``{"capture": Callable, "load": Callable}``。"""
    frame = ttk.Frame(notebook, style="App.TFrame", padding=(16, 14))
    notebook.add(frame, text="项目信息")

    project_name_var = StringVar(value=info.project_name or "")
    software_version_var = StringVar(value=info.software_version or "")
    onu_compile_time_var = StringVar(value=info.onu_compile_time or "")

    for var in (project_name_var, software_version_var, onu_compile_time_var):
        var.trace_add("write", lambda *_a: mark_dirty())

    Label(
        frame,
        text="项目信息",
        font=(FONT_FAMILY, 12, "bold"),
        foreground=COLOR_TEXT,
        background=COLOR_BG,
    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

    def text_field(row, label, var, width=40):
        Label(frame, text=label, width=20, anchor="w", background=COLOR_BG).grid(
            row=row, column=0, sticky="w", padx=(0, 12), pady=6
        )
        ttk.Entry(frame, textvariable=var, width=width).grid(
            row=row, column=1, sticky="we", pady=6
        )

    text_field(1, "项目名称", project_name_var)
    text_field(2, "软件版本", software_version_var)
    text_field(3, "ONU 软件编译时间", onu_compile_time_var)

    Label(
        frame,
        text=(
            "本段仅做编辑器,不被主程序消费(Q1=A)。"
            "编译时间为自由文本,不强制 ISO 格式；"
            "操作员可在执行测试时肉眼对照样机输出的版本/编译时间。"
        ),
        foreground=COLOR_MUTED,
        background=COLOR_BG,
        wraplength=560,
        justify="left",
    ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

    frame.columnconfigure(1, weight=1)

    def capture() -> ProjectInfoSettings:
        return ProjectInfoSettings(
            project_name=project_name_var.get().strip(),
            software_version=software_version_var.get().strip(),
            onu_compile_time=onu_compile_time_var.get().strip(),
        )

    def load(new_info: ProjectInfoSettings) -> None:
        project_name_var.set(new_info.project_name or "")
        software_version_var.set(new_info.software_version or "")
        onu_compile_time_var.set(new_info.onu_compile_time or "")

    return {"capture": capture, "load": load}
```

**关键不变量**：

- 复用 `ttk.Frame` / `ttk.Entry` / `StringVar` / `trace_add("write", ...)` 模式；不引入新依赖、不创建下拉/复选框。
- 字段 strip 写入（用户键入 `  V1.0  ` → 保存为 `V1.0`），与 Telnet/WiFi Tab 风格一致（`telnet.request_url` 等已经走 `or ""` 不 trim，本 Tab 出于「编译时间可能带尾随空格无意义」的考虑采用 trim；若用户希望保留原行为可改回不 strip，但本轮按 trim 实现）。
- 不修改现有三 Tab 的任何代码，仅追加。
- 顶部 dialog 几何 (960x940) 高度够放下第 4 个简单 Tab，不需要 resize。

### 改动 3 — `tests/test_test_item_config_store.py` 测试

新增 3 项；现有用例零修改（默认值断言处扩展一行）：

```python
def test_load_defaults_when_config_is_missing(self):
    ...
    # [project_info] 段缺省时 3 字段全部回退空串
    self.assertEqual(loaded.project_info.project_name, "")
    self.assertEqual(loaded.project_info.software_version, "")
    self.assertEqual(loaded.project_info.onu_compile_time, "")

def test_project_info_save_and_load_round_trip(self):
    """3 字段含中文 / 空格 / 常见符号时往返保留。"""
    with tempfile.TemporaryDirectory() as temp_dir:
        store = TestItemConfigStore(Path(temp_dir) / "test_project_config.ini")
        saved = TestProjectConfig(
            project_info=ProjectInfoSettings(
                project_name="SDMC ONT 自动化",
                software_version="V1.0.2-beta",
                onu_compile_time="2026-07-19 18:30",
            )
        )

        store.save(saved)
        loaded = store.load()

        self.assertEqual(loaded.project_info, saved.project_info)

def test_project_info_load_tolerates_missing_section(self):
    """老 ini 没有 [project_info] 段时,3 字段全部回退空串,不抛 NoSectionError。"""
    from configparser import RawConfigParser

    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = Path(temp_dir) / "test_project_config.ini"
        parser = RawConfigParser()
        parser.optionxform = str
        # 故意不写 [project_info]
        parser["telnet"] = {"request_url": "http://10.0.0.1"}
        with config_path.open("w", encoding="utf-8") as file:
            parser.write(file)

        loaded = TestItemConfigStore(config_path).load()
        self.assertEqual(loaded.project_info.project_name, "")
        self.assertEqual(loaded.project_info.software_version, "")
        self.assertEqual(loaded.project_info.onu_compile_time, "")
```

顶部 import 同步加入 `ProjectInfoSettings`。

### 改动 4 — 文档同步

1. **`line_check_assistant_README.md`「测试项配置窗口」段**：
   - 把"三 Tab"改写为"四 Tab"；保留原有 3 Tab 描述；
   - 新增第 4 段描述项目信息 Tab：3 字段 + 「Q1=A 不被主程序消费」+ 「编译时间自由文本不强制 ISO」+ 「用于操作员肉眼对照样机实际值」。
2. **`PROJECT_STATUS.md` 能力矩阵 line 24**：
   - 把「测试项配置 ini 编辑器（`test_project_config.ini` 加载/编辑/保存，Q1=A 不接执行）」改为「测试项配置 ini 编辑器（4 个 Tab：Telnet / 测试项 / WiFi / 项目信息；Q1=A 不接执行）」；
   - 单元测试行把「310 项」改为新数（310 + 3 = 313，先跑测试再回填）；
   - 「已完成」段（line 52 附近）追加「2026-07-20：增加第 4 个项目信息 Tab，含项目名称 / 软件版本 / ONU 软件编译时间 3 字段」。
3. **`DEVELOPMENT_LOG.md`** 顶部追加一条 `2026-07-20 - 测试项配置窗口新增「项目信息」Tab（Q1=A 第 4 段）`，按既有模板写：类型 / 背景 / 完成内容 / 修改文件 / 验证方法 / 验证结果（先跑测试再回填）/ 后续待办（用户线下真实桌面打开窗口核对 4 Tab + 字段持久化）。
4. **`ACCEPTANCE_BASELINE.md`**：当前文件没有为「测试项配置」单列 §2.x，按 `AGENTS.md` 规则 5 精神，本轮不强行新增独立 §2.12（避免与既有"三 Tab 已完成"叙述重复）；在 DEVELOPMENT_LOG 与 PROJECT_STATUS 已对齐的前提下保持 baseline 不变。如果用户后续要补一段，单独再开一轮。

## 关键不变量

- 主程序入口、运行/打包方式不变（仍 `python .\run_line_check_assistant.py` / `build_line_check_assistant.ps1`）。
- 既有三 Tab 的字段、`capture`/`load` 协议、dirty 跟踪、二次确认弹窗、保存后丢失 `;` 注释等行为完全不动。
- `Tftp指令` 与 `Tftp Put` 仍隔离；TFTP 绑 VLAN IP 不回退 `0.0.0.0`。
- `MAX_PARALLEL_UPGRADES = 8` / 7 个写参节奏常量 / `source_address=(bind_ip, 0)` 锁源 / `bbfdm.operate` / `tclinux_allinone` / `192.168.1.1` / `vlan_to_serial_port` / `Device.Firewall.<X_SDMC_>Security.AccessCtrl` 全部不动 → `verify_baseline.py` 必过。
- `ProjectInfoSettings` 字段全部为 `str`，不引入 `int` 校验；空串视为合法（与老 ini 缺段回退一致）。

## 不做的事

- **不**为项目信息增加任何自动比对/上报/写设备行为（Q1=A 仍生效）。
- **不**在 `[project_info]` 段加 `enable` 之类 0/1 字段（用户未要求）。
- **不**改 `enable` / `product_solution` / `command_fail_retry_interval_time` / `retry_times` / `ExpectedSegment` 既有逻辑。
- **不**改既有 ini 段顺序（`configparser.RawConfigParser` 按 `parser[...]` 写入顺序落盘，新段追加到末尾，与既有 `[telnet] / [order] / [connect_wifi]` 不冲突）。
- **不**改 `_open_test_item_config` 窗口尺寸 960x940（高度够）；不改 `minsize`。
- **不**改 `TestItemConfigStore` 类名 / 公开 API；仅扩字段。
- **不**做自动 commit（按项目记忆 `git-commit-on-request.md`）。

## 验证方法

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m py_compile line_check_assistant/app.py line_check_assistant/test_item_config_store.py
python -m unittest discover -s tests -v
python scripts\verify_baseline.py
```

期望：
- `py_compile` 通过；
- 完整 `python -m unittest discover -s tests -v` → `Ran 313 tests ... OK`（原 310 + 本轮新增 3 项）；
- `verify_baseline.py` → `ALL CHECKS PASSED`，exit 0；
- 故意破坏实验不需要：本轮不涉及 `MUST_EXIST` / `MUST_NOT_EXIST` 列表里的不变量，verify_baseline 行为应当与改动前一致。

## 后续待办（落到 `DEVELOPMENT_LOG.md`）

- 用户线下 Windows 桌面打开「测试项配置」窗口，核对：① 第 4 个 Tab 显示「项目信息」；② 顶部描述文案包含「项目信息」；③ 3 个字段默认值都是空（首次打开）；④ 填值后保存，再重新加载（点「重新加载」）后字段值恢复；⑤ 关闭后再次打开窗口，磁盘 ini 中存在 `[project_info]` 段，3 字段写入正确。
- 如果用户希望对项目信息 Tab 加额外的「产品系列 / 硬件版本 / 备注」等字段，可单独开一轮在 dataclass 与 UI 上叠加（不在本轮范围）。
