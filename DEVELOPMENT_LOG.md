# 开发记录

本文件用于按时间记录每次开发完成的功能、优化、修改、BUG 修复、验证方式和后续待办，方便下一次继续开发，也方便做整体项目概览和管理。

## 2026-07-20 - 「全流程执行」管道编排器（主界面「检查并执行测试」按钮升级）

- 类型：功能 / 重构 / 测试 / 文档
- 背景：用户对 `app.py:431` 的「检查并执行测试」按钮不满意——当前只调 `_start_all_checks` 做已勾选通道的 ping 通过性检查，不消费 `test_project_config.ini` 的 `[order]` 段。**用户目标**：把「自动上/下电 / 样机升级 / 写样机参数 / ONU 注册 / 串口日志 / 测试项配置」6 个已有功能作为可勾选的子任务，由用户勾选后按 1→6 固定顺序串行执行，任一失败（串口日志除外）→ 整个管道停止；用户连接好样机 + 填好所有配置后，一键跑通全流程。
- 完成内容：
  1. **`src/core/fuzzy_match_runner.py`（新）** —— 移植老工具 [Auto_power_on_off_tool/common/fuzzy_match.py](../../Cheating_machine_execution_tool/Auto_power_on_off_tool/common/fuzzy_match.py) 的 per-segment `!A&&B` 语义；纯函数无 IO，`match_expected(result, expected) -> bool` 入口；`iter_segments(expected)` 暴露拆分；老工具 `tcapi get WanInfo_Entry` IPv6 特殊分支不移植（用 `re.escape` 保证「字面匹配」）。AGENTS 硬规则：不改老工具源码，独立模块移植。
  2. **`src/services/test_item_execution_service.py`（新）** —— 跑 `[order]` 段的 service：单台样机 → `prepare_network_for_sample` 切网卡 IP → `TelnetSession`（复用 `src/core/telnet_transport.py`）按 VLAN `bind_ip` 锁源 → `_login` 按 `telnet.input_user_flag` / `input_password_flag` / `login_success_flag` 三段登录 → 顺序执行 `[order]` 每条命令：send_line → `_read_until_stable`（连续 `READ_STABLE_SECONDS=1.0s` 无新数据 / 总 `READ_MAX_SECONDS=8.0s` 视完成）→ `match_expected` 判定 → 失败重试 `retry_times` 次（间隔 `command_fail_retry_interval_time` 秒）→ per-channel 结果文件 `Cheating_machine_execution_tool/test_results/device_{section}_command_results_{YYYYMMDD_HHMMSS}.log`。返回 `TestItemRunResult{channel_section, total, passed, failed, log_path}`；网络/登录失败抛 `RuntimeError`，由编排器统一 stop pipeline。
  3. **`src/services/pipeline_orchestrator.py`（新）** —— 全流程执行管道：`PipelineContext` 包装 app + 通道 + 3 个 store + serial_log_dir；`compute_all_subtask_statuses(ctx)` 6 子任务必填项评估；`PipelineOrchestrator.run(selected: set[str])` 按 `SUBTASK_CODES` 1→6 固定顺序执行勾选子任务；每个子任务调 `app._start_*` 方法（既有逻辑，不重写）或直接调 service（1 电源 / 6 测试项）；致命失败抛 `PipelineError` + 停止后续；`NON_FATAL_SUBTASKS = {"serial_terminal"}` 失败只记结果；`request_stop()` 在当前子任务结束后终止后续。
  4. **`line_check_assistant/pipeline_window.py`（新）** —— 「全流程执行」弹窗 UI（`Toplevel(780x560)` + 6 行 Checkbutton + 必填项状态 + 「去配置」按钮 + 「开始执行 / 停止 / 取消」）；每行右侧实时刷新「必填项当前状态」（绿色就绪 / 红色「缺: 字段1, 字段2」），「去配置」按钮调 `app._open_power_control` / `_open_upgrade_module` 等 6 个既有子窗口方法；「开始执行」走「必填项未就绪警告 + 全流程执行确认」二次确认后启动后台线程；主线程 UI 回调用 `window.after(0, ...)`；emit 投到主程序 `log_queue`。
  5. **`line_check_assistant/sample_upgrade_settings_store.py`（改）** —— `SampleUpgradeSettings` 新增 `power_operation: str = "up"`（"up"/"down"，非法值 save 时回退 "up"）+ `parameter_table_path: str = ""`；load/save 同步；老 ini 兼容回退默认；与既有 `parameter_initial_*` / `parameter_clear_*` / `parameter_exit_aging` 同级存到 `[sample_upgrade]` 段。
  6. **`line_check_assistant/app.py`（改）** —— `__init__` 新增 `self.pipeline_window = None`；新增 `self.power_operation_var = StringVar(value=settings.power_operation)` + `self.parameter_table_path_var = StringVar(value=settings.parameter_table_path)`，加入 `_bind_sample_upgrade_autosave` 的 trace_add 列表；`_current_sample_upgrade_settings` 透传这 2 个字段（`power_operation` 做 "up"/"down" 归一化，`parameter_table_path` 做 `.strip()`）；`_start_all_checks` 改为弹窗入口（`PipelineWindow(self)`），保留旧的 `_run_checks` / `_check_worker` 兜底用。
  7. **`src/services/__init__.py`（改）** —— 新增 `pipeline_orchestrator` / `test_item_execution_service` 模块的 re-export（`PipelineContext` / `PipelineError` / `PipelineOrchestrator` / `SubTaskResult` / `SubTaskStatus` / `compute_all_subtask_statuses` / `TestItemRunRequest` / `TestItemRunResult` / `build_log_path` / `run_test_item_execution` / `*_SECONDS` 等常量），`__all__` 同步。
  8. **`scripts/verify_baseline.py`（改）** —— `PY_COMPILE_FILES` 增 3 个路径：`src/core/fuzzy_match_runner.py` / `src/services/pipeline_orchestrator.py` / `src/services/test_item_execution_service.py` + `line_check_assistant/pipeline_window.py`。
  9. **测试** —— 新增 4 个测试文件共 61 项：`tests/test_fuzzy_match_runner.py`（18：单段 / 多段 / 否定 / 混合 / 空段 / re.escape / IPv6 边界 / 性能）+ `tests/test_test_item_execution_service.py`（14：单条匹配 / 失败重试 / 重试成功 / per-segment !A&&B / 无期望默认通过 / 多条顺序 / 网络准备失败 / 登录失败 / 结果文件创建 / session finally 关闭 / build_log_path / 常量）+ `tests/test_pipeline_orchestrator.py`（26：6 子任务状态评估 / run 顺序 / 致命失败抛 PipelineError / 串口失败不阻塞 / request_stop 阻止后续 / 6 个子任务 statuses 完整性 / 必填项 missing 标记）+ `tests/test_sample_upgrade_settings_store.py`（+3：power_operation / parameter_table_path 持久化 / power_operation 非法值回退 `up`）；同时 `tests/test_app.py` 的 2 项 `_current_sample_upgrade_settings` mock 补齐 2 个 StringVar。
- 修改文件：`Cheating_machine_execution_tool/src/core/fuzzy_match_runner.py`（新）、`Cheating_machine_execution_tool/src/services/test_item_execution_service.py`（新）、`Cheating_machine_execution_tool/src/services/pipeline_orchestrator.py`（新）、`Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`（新）、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/services/__init__.py`、`Cheating_machine_execution_tool/scripts/verify_baseline.py`、`Cheating_machine_execution_tool/tests/test_fuzzy_match_runner.py`（新）、`Cheating_machine_execution_tool/tests/test_test_item_execution_service.py`（新）、`Cheating_machine_execution_tool/tests/test_pipeline_orchestrator.py`（新）、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：
  ```powershell
  cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
  python -m py_compile src\core\fuzzy_match_runner.py src\services\test_item_execution_service.py src\services\pipeline_orchestrator.py line_check_assistant\pipeline_window.py line_check_assistant\sample_upgrade_settings_store.py line_check_assistant\app.py
  python -m unittest discover -s tests -v
  python scripts\verify_baseline.py
  ```
- 验证结果：`py_compile` 通过；完整单测 `Ran 374 tests ... OK`（原 313 + 新增 18 fuzzy + 14 test_item + 26 pipeline + 3 settings）；`verify_baseline.py` `ALL CHECKS PASSED`，exit 0（29 个 .py 编译 + 374 项单测 + 8 条 MUST_EXIST 全部命中 + 1 条 MUST_NOT_EXIST 全程不出现）。
- 后续待办：
  - 用户线下 Windows 桌面打开「全流程执行」窗口核对：① 6 行 Checkbutton / 必填项状态表 / 「去配置」按钮 ② 二次确认弹框「必填项未就绪警告 + 全流程执行确认」 ③ 主执行日志按「=== 开始子任务 N === → ... → === 结束子任务 N ===」输出 ④ 任一「致命」失败弹错误框 + 停止后续
  - 用户在主程序配置好「全流程」所有必填项后，真实样机端到端跑通 6 子任务全流程：上下电 → 升级 → 写参 → ONU 注册 → 串口日志（持续）→ [order] 执行
  - 异常场景验证：2/3/4 异步子任务（升级 / 写参 / ONU 注册）失败如何传播到编排器（当前靠主程序 worker 异常冒泡 + 用户观察主执行日志；是否需要 polling 状态轮询机制待 v2 评估）
  - v2 候选：多通道并行、test_number 循环、WiFi 验证子任务、钉钉/邮件上报

## 2026-07-20 - 「全流程执行」窗口尺寸 + 必填项状态计算修复（第二次：`_get_attr` 拿模块常量）

- 类型：BUG 修复 / 测试
- 背景：用户线下试运行「全流程执行」窗口(2026-07-20 提交后)报「6 行必填项状态全显示『无法计算状态』+ 错误 `'NoneType' object is not iterable`」。同一会话早先已修过一次(改 `resolve_config_dir()` 调用 → `app.TEST_ITEM_CONFIG_PATH`)，但**第一次修没修干净**——`TEST_ITEM_CONFIG_PATH` 是 `line_check_assistant/app.py:84` 的**模块级常量**,不是 `LineCheckAssistant` 实例属性,用 `_get_attr(app, "TEST_ITEM_CONFIG_PATH")` 仍拿到 `None`,后续 `configparser.read(None)` 抛 `TypeError: 'NoneType' object is not iterable`。
- 根因：
  1. `pipeline_window.py:38-39` 初始 / 最小尺寸过小(560 / 520),6 行 + 标题 + 按钮至少 640px。
  2. `_build_context` 上次改错位置——应该从 `line_check_assistant.app` **模块**直接取常量,而不是从 app 实例取(`getattr(app_instance, "TEST_ITEM_CONFIG_PATH", None)` 永远拿到 `None`)。
- 完成内容:
  1. **`line_check_assistant/pipeline_window.py`（再次修）** — `_build_context` 把 `_get_attr(app, "TEST_ITEM_CONFIG_PATH")` 改为 `import line_check_assistant.app as _app_module; _app_module.TEST_ITEM_CONFIG_PATH`,从模块直接取常量;`_get_attr` 调用位置全部加注释说明 `TEST_ITEM_CONFIG_PATH` 在模块上、不在实例上。
  2. **`tests/test_pipeline_window.py`(新)** — 2 项回归测试:① 静态源码断言 `_build_context` 不能再用 `_get_attr(app, "TEST_ITEM_CONFIG_PATH")`,且必须 `import line_check_assistant.app` + 访问 `TEST_ITEM_CONFIG_PATH`(防止以后误回滚);② 构造最小 `FakeApp`(无 tk、无实例属性),按 `_build_context` 的真实路径构造 `PipelineContext` 调 `compute_all_subtask_statuses`,断言 6 个子任务全部返回 `SubTaskStatus` 且不抛——直接复现并锁定 `'NoneType' object is not iterable` 这个 bug 不再回归。
- 修改文件: `Cheating_machine_execution_tool/line_check_assistant/pipeline_window.py`、`Cheating_machine_execution_tool/tests/test_pipeline_window.py`(新)、`DEVELOPMENT_LOG.md`。
- 验证方法: `python -m py_compile line_check_assistant/pipeline_window.py`;`python -m unittest discover -s tests -p "test_pipeline_window.py" -v`(应 2 项 OK);`python scripts\verify_baseline.py`(应 `ALL CHECKS PASSED`)。
- 验证结果: py_compile OK;`test_pipeline_window.py` 2 项 OK;`verify_baseline.py` `ALL CHECKS PASSED`(29 个 .py / **376** 项单测全绿,原 374 + 本轮新增 2)。
- 后续待办: 用户重新打开「全流程执行」窗口核对 6 行必填项状态显示正常,不再出现「无法计算状态 / 'NoneType' object is not iterable」;窗口高度能容纳所有 6 行 + 底部「开始执行 / 停止 / 取消」按钮。

## 2026-07-20 - Telnet Tab 顶部增加「Telnet 默认已开启」Checkbutton

- 类型：功能追加 / 测试 / 文档
- 背景：用户在线下「测试项配置 → Telnet」Tab 截图下方指出:在「Telnet 连接参数」标题与 `request_url` 之间留出空位,需要插入一个「Telnet 默认已开启」Checkbutton,默认勾选,由用户在 UI 中自行选择是否保留勾选状态(Q1=A 仍生效——仅编辑器,主程序不消费)。本轮沿用既有 `xxx_flag: int = 0` 风格:dataclass 字段名 `telnet_default_on: int = 1`,ini key `telnet_default_on`;`_dump_telnet` 强制 0/1 转换避免保存 `True`/`False`;`_load_telnet` 老 ini 缺该 key 时回退 1,与 dataclass 默认一致,保持向后兼容(不破坏已有 11 个 telnet 字段的回退行为)。
- 完成内容:
  1. **`line_check_assistant/test_item_config_store.py`** —— `TelnetSettings` 在 `only_power_off_on` 之后新增 `telnet_default_on: int = 1`(注释说明「默认 1 = 勾选,老 ini 缺 key 时回退 1」);`_load_telnet` 新增 `parser.get(section, "telnet_default_on", fallback="1")` + `_parse_int(..., 1)`,与其他 flag 同款 _parse_int 兜底;`_dump_telnet` 末尾新增 `"telnet_default_on": str(1 if bool(telnet.telnet_default_on) else 0)`,与 `connect_wifi.enable` 同款 0/1 强制转换。`enable` 字段 0/1 转换、`bool` 防 `True/False` 落盘等既有约定保持。
  2. **`line_check_assistant/app.py`** —— `_build_test_item_telnet_tab` 新增 `telnet_default_on_var = IntVar(value=telnet.telnet_default_on)` 并加入 `mark_dirty` trace_add 列表;在标题(原 row 0)与 `request_url` 之间新增 `Checkbutton(... text="Telnet 默认已开启(telnet_default_on = 1,默认勾选)", variable=telnet_default_on_var, onvalue=1, offvalue=0, ...)`,grid 到 row 1 / columnspan=3;原 `request_url` 行的 row 1→2、`user` 2→3、`password` 3→4、`port` 4→5、`timeout` 5→6、`input_user_flag` 6→7、`input_password_flag` 7→8、`login_success_flag` 8→9、`telnet_need_enter_password_flag` 9→10、`telnet_no_user_password_flag` 10→11、`only_power_off_on` 11→12,所有 row 全部统一下移 1 行;`capture` / `load` 同步处理 `telnet_default_on`(`.get()` / `.set(int(...))`)。`save` 二次确认弹窗「Telnet 字段:11 项」自动由 `len(captured.telnet.__dict__)` 计算得出 12,不需要手改。
  3. **`tests/test_test_item_config_store.py`** —— `test_load_defaults_when_config_is_missing` 末尾追加 `assertEqual(loaded.telnet.telnet_default_on, 1)`;`test_load_tolerates_unknown_keys` 末尾追加 `assertEqual(loaded.telnet.telnet_default_on, 1)` 验证老 ini 缺该 key 时回退 1;`test_save_and_load_round_trip` round-trip 数据加 `telnet_default_on=0`(显式非默认 1,验证非默认值也能往返),`self.assertEqual(loaded.telnet, saved.telnet)` 后追加 1 行 `assertEqual(loaded.telnet.telnet_default_on, 0)` 与落盘文本断言 `telnet_default_on = 0`;新增 `test_telnet_default_on_saves_as_zero_or_one`(参照 `test_connect_wifi_enable_serializes_as_zero_or_one` 模式,循环 4 种 raw_value(1/0/True/False) 验证落盘为 `1` / `0`)。312 → 313 项。
  4. **`line_check_assistant_README.md`** —— 「测试项配置窗口」段 Telnet Tab 描述:从「11 个字段」改为「12 个字段」;新增顶部「Telnet 默认已开启」Checkbutton 说明(默认 1 = 勾选,可由用户切换);其余字段顺序不变。
  5. **`PROJECT_STATUS.md`** —— 能力矩阵行:「测试项配置 ini 编辑器」描述增加「Telnet Tab 顶部『Telnet 默认已开启』Checkbutton 默认勾选」;单元测试行从 312 改 313。
- 修改文件: `Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_test_item_config_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法: `python -m py_compile line_check_assistant/app.py line_check_assistant/test_item_config_store.py`;`python -m unittest discover -s tests -v`(应 `Ran 313 tests ... OK`,原 312 + 本轮新增 1);`python scripts\verify_baseline.py`(应 `ALL CHECKS PASSED`)。
- 验证结果: `py_compile` 通过;完整单测 `Ran 313 tests ... OK`(原 312 + 新增 1 项 `test_telnet_default_on_saves_as_zero_or_one`);`verify_baseline.py` 全绿,exit 0。
- 后续待办: 用户线下 Windows 桌面打开「测试项配置 → Telnet」Tab,核对:① 标题下方出现「Telnet 默认已开启(telnet_default_on = 1,默认勾选)」Checkbutton,默认已勾选;② 取消勾选后「重新加载」会按磁盘值恢复;③ 显式关掉后保存,二次确认弹窗「Telnet 字段:12 项」行可见,落盘 ini 中 `telnet_default_on = 0`;④ 显式勾选后保存,落盘 ini 中 `telnet_default_on = 1`;⑤ 关闭再开,首次打开的 ini 若没有该 key,Checkbutton 默认仍是勾选状态(老 ini 向后兼容)。

## 2026-07-20 - 项目信息 Tab 增加「内部软件版本」字段

- 类型：功能追加 / 测试 / 文档
- 背景：上一轮在「测试项配置」窗口新增「项目信息」Tab 时,仅含 3 个字符串字段(项目名称 / 软件版本 / ONU 软件编译时间)。用户线下试用后反馈:现场场景下「软件版本」(对外版本号,例如 `V1.0.2-beta`)与「内部软件版本」(内部构建号,例如 `S13.58.01.001`)通常不同,操作员需要同时记录两个值用于和样机实际输出对照。本轮在「软件版本」下方插入新字段 `internal_software_version`,**仍 Q1=A**(仅编辑器,主程序不消费)。
- 完成内容:
  1. **`line_check_assistant/test_item_config_store.py`** —— `ProjectInfoSettings` 在 `software_version` 与 `onu_compile_time` 之间新增 `internal_software_version: str = ""`(默认空串);`_load_project_info` 新增 `parser.get(section, "internal_software_version", fallback="")`,老 ini 缺该 key 时回退空串;`_dump_project_info` 新增 `internal_software_version` key,落盘顺序固定在 `software_version` 之后。`enable` 0/1 转换 / `bool` 防 `True/False` 落盘等既有约定不动。
  2. **`line_check_assistant/app.py`** —— `_build_test_item_project_info_tab` 新增 `internal_software_version_var` 第三个 `StringVar`,加入 `mark_dirty` trace_add 列表;`text_field(3, "内部软件版本", internal_software_version_var)` 插入到 `软件版本`(row 2)与 `ONU 软件编译时间` 之间,原 ONU 行下移到 row 4,底部说明 Label 下移到 row 5;`capture` / `load` 同步处理新字段(`.strip()` 写入,`or ""` 防御性回退)。`save` 二次确认弹窗项目信息行追加「内部软件版本=…」。
  3. **`tests/test_test_item_config_store.py`** —— `test_load_defaults_when_config_is_missing` 末尾 3 行 assert 扩为 4 行(增加 `internal_software_version == ""`);`test_project_info_save_and_load_round_trip` round-trip 数据加 `internal_software_version="S13.58.01.001"`,落盘文本断言增加 `internal_software_version = S13.58.01.001`;`test_project_info_load_tolerates_missing_section` 末尾 3 行 assert 扩为 4 行。**不新增测试,只扩展既有 3 项**——`test_load_defaults_when_config_is_missing` / `test_project_info_save_and_load_round_trip` / `test_project_info_load_tolerates_missing_section` 3 项测试总数不变。
  4. **`line_check_assistant_README.md`** —— 「测试项配置窗口」段项目信息 Tab 描述从「3 个字符串字段(项目名称 / 软件版本 / ONU 软件编译时间)」改为「4 个字符串字段(项目名称 / 软件版本 / **内部软件版本** / ONU 软件编译时间)」。
- 修改文件: `Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_test_item_config_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`。
- 验证方法: `python -m py_compile line_check_assistant/app.py line_check_assistant/test_item_config_store.py`;`python -m unittest discover -s tests -v`(应仍 `Ran 312 tests ... OK`,原 312 + 本轮 0 新增);`python scripts\verify_baseline.py`(应 `ALL CHECKS PASSED`)。
- 验证结果: `py_compile` 通过;完整单测 `Ran 312 tests ... OK`(不增测试计数,仅扩展既有 3 项的断言 / round-trip 数据);`verify_baseline.py` 全绿,exit 0。
- 后续待办: 用户线下 Windows 桌面打开「测试项配置 → 项目信息」Tab,核对:① 第 3 行新增「内部软件版本」Label + 输入框;② 填入内部版本后点「保存」,二次确认弹窗项目信息行出现「内部软件版本=…」;③ 保存后点「重新加载」,内部软件版本值恢复;④ 关闭再开,磁盘 ini `[project_info]` 段含 `internal_software_version` 行,顺序在 `software_version` 之后、`onu_compile_time` 之前。

## 2026-07-20 - 测试项配置窗口新增「项目信息」Tab（Q1=A 第 4 段）

- 类型：功能 / 测试 / 文档
- 背景：用户在线下「测试项配置」窗口下提出：在三 Tab 之外**新增一个「项目信息」Tab**,配置可供参考的项目基础信息（项目名称 / 软件版本 / ONU 软件编译时间），用于操作员在主程序执行过程中肉眼对照样机实际值（如 `bbfdm` / `ifconfig` 输出中的版本号与编译时间）。本轮遵循既有 Q1=A 决策——**仅做编辑器,不被主程序消费**,不接任何自动比对/上报/写设备流程。新增 ini 段 `[project_info]`,字段全部按字符串存取(编译时间不强制 ISO 格式),与现有三 Tab 的实现模式完全对齐。
- 完成内容:
  1. **`line_check_assistant/test_item_config_store.py`** —— 新增 `PROJECT_INFO_SECTION = "project_info"` 模块级常量与 `ProjectInfoSettings` dataclass(3 字段默认空串: `project_name` / `software_version` / `onu_compile_time`);`TestProjectConfig` 新增 `project_info: ProjectInfoSettings` 字段(排在最末,与既有三段顺序保持向后兼容);`load()` 调新私有方法 `_load_project_info`;`save()` 在末位 `parser[PROJECT_INFO_SECTION] = self._dump_project_info(...)`;新增 `_load_project_info` / `_dump_project_info` 私有方法,沿用 `_load_connect_wifi` / `_dump_connect_wifi` 的风格——老 ini 缺 `[project_info]` 段时 3 字段全部回退空串,**不抛 `NoSectionError`**;`__all__` 末尾追加 `"PROJECT_INFO_SECTION"` / `"ProjectInfoSettings"`。`enable` 0/1 强制转换、`bool` 防 `"True"`/`"False"` 落盘等既有约定不动,本段无 `enable` 字段无需做 0/1 转换。
  2. **`tests/test_test_item_config_store.py`** —— import 加 `ProjectInfoSettings`;`test_load_defaults_when_config_is_missing` 末尾追加 3 行断言 `[project_info]` 段缺省时 3 字段默认空串;新增 `test_project_info_save_and_load_round_trip`(含中文 / 空格 / 常见符号的 round-trip + 落盘文本含 `[project_info]` 段 3 行);新增 `test_project_info_load_tolerates_missing_section`(手写不含 `[project_info]` 段的 ini,验证 `load` 不抛 `NoSectionError` 且 3 字段为空)。原 16 项 → 18 项。
  3. **`line_check_assistant/app.py`** —— import 加 `ProjectInfoSettings`;`_open_test_item_config` 顶部描述从「telnet / 测试项命令 / WiFi 连接」扩为「telnet / 测试项命令 / WiFi 连接 / 项目信息」;新增第 4 次 `_build_test_item_project_info_tab(notebook, config.project_info, mark_dirty)` 调用;`reload` 内追加 `project_info_vars["load"](reloaded.project_info)`;`save` 内 `TestProjectConfig(...)` 多传 `project_info=project_info_vars["capture"]()`,二次确认弹窗追加「项目信息：项目=…,软件版本=…,编译时间=…」(空值显示「(空)」)一行。新增私有方法 `_build_test_item_project_info_tab`:2 列 grid + 标题 + 3 行 Label+`ttk.Entry`(与 `_build_test_item_wifi_tab` 同风格),`capture` 对 3 字段 `get().strip()`,`load` 直接 `var.set(...)`;`trace_add("write", lambda *_a: mark_dirty())` 模式与既有三 Tab 完全一致,dirty 跟踪自动覆盖。窗口几何 960x940 高度足够,`minsize` 不动。
  4. **`line_check_assistant_README.md`** —— 「测试项配置窗口」段:「三 Tab 结构」改为「四 Tab 结构」;新增第 4 项「项目信息」描述(3 字段 + 仅编辑器 + 自由文本 + 肉眼对照样机值);保留前 3 Tab 描述不变。
  5. **`PROJECT_STATUS.md`** —— 能力矩阵行:把「测试项配置 ini 编辑器(3 Tab / Q1=A 不接执行)」改为「4 Tab: Telnet / 测试项 / WiFi / 项目信息」,状态加注「310 → 313 项」;单元测试行从 310 改 313;「已完成」段(原 line 52)把「三 Tab」改为「四 Tab」并新增项目信息 Tab 描述。
  6. **`ACCEPTANCE_BASELINE.md`** —— 本轮**不**新增独立 §2.x(原文件就没有为「测试项配置」单列条目,且本轮 Q1=A 不变,加 §2.x 会与既有叙述重复);等用户线下真实样机交互验证 4 Tab 行为后,再单独评估是否补 §2.x。
- 修改文件: `Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_test_item_config_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法: `python -m py_compile line_check_assistant/app.py line_check_assistant/test_item_config_store.py`;`python -m unittest discover -s tests -v`(应 `Ran 312 tests ... OK`,原 310 + 本轮新增 2);`python scripts\verify_baseline.py`(应 `ALL CHECKS PASSED`,exit 0)。
- 验证结果: 完整单测 `Ran 312 tests ... OK`(原 310 + 项目信息 2 项;`test_load_defaults_when_config_is_missing` 末尾追加 3 行 `[project_info]` 默认回退断言,不增加测试计数);`verify_baseline.py` 全绿,exit 0;`py_compile` 通过。
- 后续待办:
  - 用户线下 Windows 桌面打开「测试项配置」窗口,核对:① 第 4 个 Tab 显示「项目信息」;② 顶部描述包含「项目信息」;③ 首次打开 3 字段默认值都是空;④ 填值后点「保存」,二次确认弹窗项目信息一行显示填入的 3 个值;⑤ 保存后点「重新加载」,3 字段值恢复;⑥ 关闭再次打开,磁盘 ini 中存在 `[project_info]` 段且 3 字段写入正确(中文 / 空格 / 符号保留)。
  - 若用户希望对项目信息 Tab 加额外的「产品系列 / 硬件版本 / 备注 / 测试员」等字段,可在 `ProjectInfoSettings` dataclass 与 UI `_build_test_item_project_info_tab` 内叠加(`_dump_project_info` / `_load_project_info` 自动覆盖新 key),不在本轮范围。

## 2026-07-20 - 建立 verify_baseline.py 回归门禁 + AGENTS.md 加验收同步硬规则

- 类型：基础设施 / 文档 / 测试
- 背景：项目早期 QA 报告（2026-07-20）指出**核心质量缺口**：① 无 CI/CD，测试靠手动跑；② 无自动化机制拦截破坏已验收功能的改动；③ `ACCEPTANCE_BASELINE.md §1.3` 的 8 条 grep 不变量没自动跑；④ `AGENTS.md` 规则 5/11 漏列 `ACCEPTANCE_BASELINE.md`，人类开发者读 AGENTS.md 不会知道还要同步 baseline。本轮建立最低门禁：单一脚本 `scripts/verify_baseline.py` 封装 `§0` + `§1.3` + `§1.4` 全部检查，AGENTS.md 升级为「提交前必须跑 verify_baseline 全绿」硬规则。
- 完成内容：
  1. **`Cheating_machine_execution_tool/scripts/verify_baseline.py`（新）** —— 4 类检查：① `py_compile` 对 `PY_COMPILE_FILES`（25 个 .py，覆盖 `line_check_assistant/` + `src/` 全量） ② `unittest discover -s tests` + 解析 `Ran N tests` 行（防止静默 0 项） ③ `MUST_EXIST`（8 条 §1.3 不变量 + 扩展搜索目录到 `line_check_assistant/`，覆盖 `bbfdm.operate` / `MAX_PARALLEL_UPGRADES = 8` 的实际位置） ④ `MUST_NOT_EXIST`（`0.0.0.0` 仅在代码行检测，**过滤掉 `#` 注释 + 三引号文档字符串**，避免反向语义注释误报，如 `telnet_transport.py:10` 「不回退 0.0.0.0」）。退出码 0 全过 / 1 任一失败。模块结构单一来源（3 个常量 + 4 个 check 函数 + main），便于单元测试。
  2. **`tests/test_verify_baseline.py`（新，11 项）** —— ① `MUST_EXIST`/`MUST_NOT_EXIST` 结构合法性；② `PY_COMPILE_FILES` 全部位于 `line_check_assistant/` 或 `src/` 下；③ `check_must_exist` 命中/缺失/目录不存在 3 个分支；④ `check_must_not_exist` 命中/缺失/限制文件不存在/纯注释行/缩进注释行 5 个分支。`tempfile.TemporaryDirectory` 构造临时源码，毫秒级跑完。299 → 310。
  3. **`AGENTS.md`（修改）** —— 规则 5 扩展为「新增功能 / Bug 修复 / 真实样机验收 → 必须同步更新 `README.md` + `ACCEPTANCE_BASELINE.md §2.x / §3` + `PROJECT_STATUS.md`」；规则 11 末尾补「真实样机验收或破坏/补全验收状态时同步更新 baseline §2.x 与 §3」；新增规则 13「提交代码前必须运行 `python scripts/verify_baseline.py` 全部通过 —— 拦截破坏已验收功能的最低门禁」；新增规则 14「详细工作流参考 SKILL.md」；新增章节「## 验收不变量」列出 MUST_EXIST / MUST_NOT_EXIST 的可读副本（与脚本单一来源保持一致，注释明确「改这里必须同步改脚本」）。
  4. **`.claude/skills/line-check-dev/SKILL.md`（修改）** —— §5 验证命令改为引用 `verify_baseline.py`（封装 §0 + §1.3 + §1.4）；§11 第 5 步同步改为跑 `verify_baseline.py`。
  5. **故意破坏实验** —— 把 `MAX_PARALLEL_UPGRADES = 8` 改成 `4`，跑 `verify_baseline.py` → 立即 FAIL：① `must_exist: MAX_PARALLEL_UPGRADES = 8` 不变量命中失败；② 4 项单测（`test_serial_upgrade_service.py` 断言常量为 8）失败。`exit 1`。改回后全绿。**门禁有效**。
- 修改文件：`Cheating_machine_execution_tool/scripts/verify_baseline.py`（新）、`Cheating_machine_execution_tool/tests/test_verify_baseline.py`（新）、`AGENTS.md`、`.claude/skills/line-check-dev/SKILL.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile scripts\verify_baseline.py`；`python -m unittest discover -s tests -v`（应 `Ran 310 tests ... OK`，原 299 + 本轮新增 11）；`python scripts\verify_baseline.py`（应 `ALL CHECKS PASSED`，exit 0）；故意破坏 `MAX_PARALLEL_UPGRADES = 8` 验证拦截。
- 验证结果：`py_compile` 通过；完整单测 `Ran 310 tests ... OK`（原 299 + verify_baseline 11 项）；`verify_baseline.py` 实跑 4 类检查全绿；故意破坏实验证明门禁可拦截不变量破坏。
- 后续待办：
  - 用户每次提交前运行 `python scripts\verify_baseline.py` 全绿（强制规则）；任何 FAIL 必须先修复。
  - 下一步考虑 GitHub Actions 配置（需先建远端仓库），把 verify_baseline 接入 PR 检查。
  - 下一步可考虑让 `verify_baseline.py` 解析 `ACCEPTANCE_BASELINE.md §1.3` 自动同步 `MUST_EXIST` 列表（消除文档与脚本漂移）。
  - `THIRD_PARTY_NOTICES.md` 漏列 `requests` / `ACCEPTANCE_BASELINE.md §0` 数字 283→299 漂移仍未修（见 2026-07-20 QA 报告 P0-1 / P0-2）。

## 2026-07-20 - 测试项配置「期望」改为 per-segment 否定

- 类型：功能 / 重构 / 测试 / 文档
- 背景：上一轮把「测试项配置」窗口改造为 ini 编辑器时，「否定匹配」是命令级单 Checkbutton：所有期望段共享同一个 negate 标志。但实际场景常需要混合——例如 `ifconfig ra0` 应同时满足「MAC 全零应**不**出现」与「UP BROADCAST 应**出现**」，单标志位无法表达这种 A 否定 ∧ B 肯定的组合。同时重新审视老工具 `Auto_power_on_off_tool/common/fuzzy_match.py`：其 `&&` 循环里**每段独立**调 `Fuzzy_Match_01`，每段自带 `!` 前缀解析——per-segment 才是老工具的真实语义，先前的单标志是过度简化。
- 完成内容：
  1. **`line_check_assistant/test_item_config_store.py`** —— `ExpectedSegment` 新增 `negate: bool = False` 字段（per-segment）；`OrderItem` 移除冗余的命令级 `negate` 字段。`_split_expected` 重写：返回 `List[tuple[bool, str]]`，按段独立解析 `!` 前缀。`_join_expected` 重写：参数改为 `List[ExpectedSegment]`，每段独立加 `!` 前缀，`&&` 拼接。`_load_order` / `_dump_order` 同步更新。空段仍跳过拼接。docstring 注明「更贴近老工具真实语义」。
  2. **`tests/test_test_item_config_store.py`** —— 调整 3 项旧用例（`test_save_and_load_round_trip` / `test_negate_prefix_serializes_with_bang` / skip_empty_expected_segments_when_joining）的数据结构以反映新模型；新增 3 项：① `test_per_segment_negate_mixed_serialization` 验证 `!A&&B&&!C` 混合拼接；② `test_per_segment_negate_round_trip_mixed` 验证混合 negate 往返保留每段独立标志；③ `test_parse_per_segment_negate_helper` 覆盖 `_split_expected` 的 6 种输入（全肯定 / 全否定 / 混合 / 单段 / 空串）。13 → 16 项。
  3. **`line_check_assistant/app.py` `_build_test_item_order_tab`** —— 移除命令级「否定匹配」Checkbutton 与 `row_dict["negate_var"]` 字段；`_add_segment_row` 新增 `negate: bool = False` 形参，每段渲染独立「否定」Checkbutton（与 Entry、删除段按钮并排）；`_build_row_widgets` 初始化段时读 `seg.negate` 传入；`capture` 按段读 `seg["negate_var"]` 写回 `ExpectedSegment(text=..., negate=...)`。
  4. **`line_check_assistant_README.md`** —— 「期望」拼接规则描述更新：勾否定 → 该段前加 `!`；并以 `!00:00:00:00:00:00&&UP BROADCAST` 为例说明混合语义。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`、`tests/test_test_item_config_store.py`、`line_check_assistant/app.py`、`line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile line_check_assistant/app.py line_check_assistant/test_item_config_store.py`；`python -m unittest discover -s tests -v`；smoke test 用混合 negate 数据走一遍 `_build_test_item_order_tab` + `capture` 确认每段独立读出。
- 验证结果：`py_compile` 通过；完整单测 `Ran 299 tests ... OK`（原 296 + per-segment negate 3 项）。Smoke test 加载 `[ExpectedSegment('00:00:00:00:00:00', negate=True), ExpectedSegment('UP BROADCAST', negate=False)]` 后 capture 返回一致数据结构。
- 后续待办：用户线下重启主程序 → 打开「测试项配置」→ 切到「测试项」Tab → 在已加载的 9 条命令上独立勾选每段的「否定」（例如保留原 ini 的 ifconfig ra0: `00:00:00:00:00:00` 勾否定、`UP BROADCAST` 不勾）→ 保存 → 检查 ini 内容 `!00:00:00:00:00:00&&UP BROADCAST`；重新加载确认段级勾选状态恢复。

## 2026-07-20 - 测试项配置窗口改造为 ini 编辑器（不接执行）

- 类型：功能 / 重构 / 测试 / 文档
- 背景：用户希望把老工具 `Auto_power_on_off_tool/config/test_project_config.ini` 映射到主程序的「测试项配置」窗口。`PROJECT_STATUS.md` 中的 `测试项配置` 当前实现是「只读占位 + 固定启用 3 行」；用户明确选择 **Q1=A**（仅展示+编辑+保存 ini，不接主程序执行）+ Q2 表单化（命令/期望/重试次数三个独立控件）+ Q3 保留 `Auto_power_on_off_tool/config/` 路径不动 + Q4 密码明文显示。「期望」按 `!段A&&段B` 拆为「否定勾选 + 动态段列表」；「重试次数」为每条命令 Spinbox（1–99）。本轮同步澄清了「重试间隔」的真实语义：老工具 `wait_time_N` 是 sleep 秒数、不是 retry interval；与 `config.ini` `[other_config] command_fail_retry_interval_time = 60` 同名字段含义不同——`test_project_config.ini` 当前没有「重试间隔」位置，按用户决定在 `[order]` 段顶部独立写 `command_fail_retry_interval_time = 60`，仅作为 ini 内全局参考值，不被主程序或老工具读取。
- 完成内容：
  1. **`line_check_assistant/test_item_config_store.py`（新）** —— 参照 `sample_upgrade_settings_store.py` / `config_store.py` 模式新增 ini 读写服务：`TelnetSettings` / `OrderConfig` / `OrderItem` / `ExpectedSegment` / `ConnectWifiSettings` / `TestProjectConfig` 6 个 dataclass + `TestItemConfigStore`。`RawConfigParser` + `optionxform=str`，与既有 store 一致；`[order]` 顶部独立写 `command_fail_retry_interval_time`，命令 key 拼为 `命令 retry_times_N`（不写 `wait_time_N`，避免与老工具 sleep 语义冲突）；期望值拼接「`!段1&&段2&&...`」（勾选否定时加 `!` 前缀）/「`段1&&段2&&...`」（未勾选）；空段不写入拼接结果；`bool` 强制转 `0/1` 防止保存为 `True/False`；`retry_times_0` / `port=0` 等非法值回退默认；缺失段（如老 ini 没有 `[order]`）不抛 `NoSectionError`，全字段回退默认值。
  2. **`tests/test_test_item_config_store.py`（新，13 项）** —— 覆盖：缺 ini 全字段回退默认；save/load 往返（含 `!`、`&&`、空段、长命令、含 `%`/`*`/`#` 的密码）；`[order]` 顶部全局值在命令之前；期望段 `&&` 拼接；勾选否定加 `!`；空段跳过；命令 key 含管道空格时正确拆分 retry_times；缺 retry_times 默认 5；`retry_times_0` 回退默认；`enable` bool→`0/1`；`product_solution` 保存时统一小写；未识别 key 容错。
  3. **`line_check_assistant/app.py`** —— `tkinter` 导入加 `Canvas`；新增模块常量 `TEST_ITEM_CONFIG_PATH = CONFIG_DIR / "test_project_config.ini"`。`_open_test_item_config` 占位（3 行固定启用 + 不会改变流程注释）替换为「`Toplevel(960x640)` + `ttk.Notebook` 三 Tab + 底部『重新加载 / 保存 / 关闭』」：
     - **Tab 1: Telnet** —— 11 字段表单（request_url / port / user / password + 👁 明文切换 / timeout / input_user_flag / input_password_flag / login_success_flag / 三个 0-1 flag），password 按 Q4 明文保存。
     - **Tab 2: 测试项** —— 顶部全局 Spinbox「指令重试间隔（秒）」默认 60；中间 `Canvas` 滚动列表，每行 `序号 Label + 命令 Entry + 重试次数 Spinbox + 删除命令按钮 + 期望子表单（否定勾选 + 动态段列表 + + 增加段按钮 + 每段独立删除按钮）`；底部「+ 新增测试项」按钮。空行在保存时跳过。
     - **Tab 3: WiFi** —— enable Checkbutton（0/1）+ product_solution Combobox（openwrt/bcm/mtk readonly，保存时小写）。
     - 行为：打开时自动加载 ini；缺失 ini 弹一次「将以空白表单打开」提示；任意 widget 改动标记 dirty；「重新加载」「关闭」有 dirty 时弹「放弃修改？」；「保存」二次确认 + 写入磁盘 + 主执行日志 `[测试项配置] 已保存 N 条测试项命令到 test_project_config.ini` + 失败原因；ini 文件不存在时自动创建；保留 `_open_test_item_config` 签名 + `self.test_item_config_window` 单例引用；样式与 `Primary.TButton` / `Secondary.TButton` / `CardTitle.TLabel` 等保持一致。
  4. **`line_check_assistant_README.md` / `PROJECT_STATUS.md`** —— 同步 README「测试项配置窗口」说明（Q1=A、密码明文、保存覆盖、注释丢失、不接执行）+ 表格「测试项配置窗口」从「占位」升级为「ini 编辑器（Q1=A）」，移除「待完成」中相关描述。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/test_item_config_store.py`（新）、`tests/test_test_item_config_store.py`（新）、`line_check_assistant/app.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：
  ```powershell
  cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
  python -m py_compile line_check_assistant\app.py line_check_assistant\test_item_config_store.py
  python -m unittest discover -s tests -v
  python .\run_line_check_assistant.py   # 启动后点测试项配置→改几项→保存→检查 ini
  ```
- 验证结果：`py_compile` 通过；完整 `python -m unittest discover -s tests -v` **共 296 项 OK**（原 283 + 本轮新增 13）。`from line_check_assistant.app import LineCheckAssistant` 导入正常；`_open_test_item_config` docstring 含 Q1=A 说明。真实交互验证待用户线下 Windows 桌面跑通。
- 后续待办：
  - 用户线下点击「测试项配置」→ 改 Telnet / 测试项 / WiFi 各字段 → 保存 → 检查 `Auto_power_on_off_tool/config/test_project_config.ini` 内容（含 `!`、`&&`、`retry_times_N`、顶部 `command_fail_retry_interval_time`、WiFi enable 0/1）。
  - 验证 `[order]` 段动态段列表：「+ 增加段」/「删除段」、「否定」勾选加 `!`、空行保存时被跳过。
  - 验证「重新加载」「关闭」在 dirty 时弹「放弃修改？」二次确认。
  - 验证删除 ini 后重新打开：弹「将以空白表单打开」+ 保存后自动创建。
  - 验证注释丢失：原 `[connect_wifi]` 段上方 `;` 中文注释保存后被清空（已确认接受）。
  - **本轮明确不实现**：`wait_time_N` 序列化（与老工具 sleep 语义冲突，避免误导）；不接主程序执行（Q1=A）；不引入 `configobj` 依赖（标准 `configparser` 已确认可接受注释丢失）。

## 2026-07-19 - 写样机参数 telnet 6 台并行 + 生成批量参数表 真实样机验收通过

- 类型：真实样机验收 / 状态更新
- 背景：用户在 6 台独立 VLAN110–VLAN115 真实样机上对 `Cheating_machine_execution_tool/line_check_assistant/app.py` 主程序跑了 ① 批量写样机参数 telnet 6 台并行（默认并行 1，依次勾选/不勾选「清空参数」/「退出老化」跑通 9 步自然顺序） ② 生成批量样机参数表（同批 MAC 前 6 位 OUI 固定 + 2.4G / 5G SSID 后缀取本机 MAC 末 4 位 + label "SN/GPON SN 随机后缀长度" 优化）。两项功能均验收通过。
- 完成内容：本轮无新代码改动,仅同步状态。把 `ACCEPTANCE_BASELINE.md` §2.7（批量写样机参数）从"已确认验收（1 台 / 6 台）+ 已实现未验收（流水线下发命令由可选 Checkbutton 控制）"升级为"已确认验收（1 台 / 6 台,流水线下发命令由可选 Checkbutton 控制已含 6 台真实样机回归）"；§2.8（随机参数表生成）从"已实现未验收"升级为"已确认验收（6 台真实样机）",并把 2026-07-19 同 OUI 改动、SSID 末 4 位 MAC 强关联、label 优化三条子改动都标"已确认验收"。§0 测试基线从 273 → 283（与单测实际一致）。`PROJECT_STATUS.md` 表格对应行 + 单元测试行 + 已完成段 + 抬头日期同步刷新。
- 修改文件：`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile line_check_assistant/app.py src/core/sample_parameter_table.py src/services/sample_parameter_service.py`；`python -m unittest discover -s tests -v`（应仍为 283 项全过,本轮仅改文档不涉及业务逻辑）。
- 验证结果：本次纯文档/状态刷新,无代码改动;`py_compile`/`unittest` 与上一轮一致（283 项全过）。
- 后续待办：现场若 2 / 8 台端点并行需要补验收,按 `ACCEPTANCE_BASELINE.md` §2.7 / §2.8 "已实现未验收"标记执行。

## 2026-07-19 - 生成批量样机参数表 label "随机后缀长度" 改名为 "SN/GPON SN 随机后缀长度"

- 类型：界面优化
- 背景:用户打开「生成批量样机参数表」窗口,看到 "随机后缀长度" 输入框排在 2.4G / 5G SSID 前缀下面,会误以为这条也控制 SSID 后缀长度。上一轮已经把 2.4G / 5G SSID 后缀改为 MAC 末 4 位固定派生,该字段实际只控制 SN / GPON SN 的随机后缀字符数,label 需要明确。
- 完成内容:
  1. **`line_check_assistant/app.py` `_open_parameter_generator`** —— `fields` 字典的 key 从 "随机后缀长度" 改为 "SN/GPON SN 随机后缀长度",相应位置不动(仍在 2.4G / 5G SSID 前缀下方,符合用户要求「只动这一行 label」);`generate_and_save` 内部 `fields["随机后缀长度"].get()` 同步改为新 key。
  2. **`src/core/sample_parameter_table.py` `generate_parameter_records`** —— `ValueError` 文案从 "SN / GPON SN 随机后缀长度必须在 1 到 32 之间。"(斜杠两侧有空格)改为 "SN/GPON SN 随机后缀长度必须在 1 到 32 之间。",与新 label 字面保持一致。
- 修改文件:`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/core/sample_parameter_table.py`、`DEVELOPMENT_LOG.md`。
- 验证方法:`python -m py_compile line_check_assistant/app.py src/core/sample_parameter_table.py`;`python -m unittest discover -s tests -v`。
- 验证结果:`py_compile` 通过;完整单测 `Ran 283 tests ... OK`(仅改 label 文本,业务逻辑与所有测试断言保持原状)。
- 后续待办:用户线下重新打开"生成批量样机参数表",确认 label 已是 "SN/GPON SN 随机后缀长度",且该字段填 8 仍能正确生成 SN/GPON SN 后缀长度 8 的随机字符(SSID 后缀仍按 MAC 末 4 位派生,不受该字段影响)。

## 2026-07-19 - 生成批量样机参数表 2.4G / 5G SSID 后缀与 MAC 末 4 位强关联

- 类型：功能 / 测试 / 文档
- 背景：用户要求自动生成参数表时,**同一行**的 2.4G SSID 与 5G SSID 必须共享同一个后缀,且该后缀 = 本机 MAC 末 4 位十六进制（大写）。原因:① 2.4G / 5G SSID 是一台样机的两个频段标识,共享后缀便于和样机本身强对应;② 与 MAC 末 4 位强绑定后,操作员看一眼 SSID 就能反查本机 MAC（例:MAC=CA:7A:85:18:B0:E8 → 后缀="B0E8"）。当前实现两条 SSID 各自跑独立的随机后缀,既不共享,也与 MAC 无关联。
- 完成内容：
  1. **`src/core/sample_parameter_table.py` `generate_parameter_records`** —— 重排循环:先生成 MAC,再以 `mac.replace(":", "")[-4:]` 取末 4 位十六进制作为 `ssid_suffix`,然后 `2.4G SSID = template.ssid_24_prefix + ssid_suffix` / `5G SSID = template.ssid_5_prefix + ssid_suffix`。从 `seen_values` 字典中移除 `"2.4G SSID"` / `"5G SSID"` 两个 key(不再用 `_unique_prefixed_value` 随机生成)。SSID 唯一性由 MAC 唯一性自然保证(MAC 唯一则末 4 位唯一)。`ssid_24_prefix` / `ssid_5_prefix` 仍必须非空(若用户留空,直接抛 ValueError,避免空字符串拼出裸后缀);`suffix_length` 仍控制 SN / GPON SN 随机后缀长度,SSID 不再受其影响。`ValueError` 文案相应从"SN、XPON SN 和 SSID 前缀均不能为空"改为"SN 和 GPON SN 前缀均不能为空" + 新增独立校验"2.4G SSID 和 5G SSID 前缀均不能为空",与新行为一致。
  2. **测试** —— `tests/test_sample_parameter_table.py` 新增 `test_generate_records_ssid_suffix_matches_mac_last_4_hex`:用 5 条记录遍历,逐条断言 ① MAC 末 4 位为 4 位大写十六进制;② 2.4G / 5G SSID 各自以 MAC 末 4 位结尾;③ 去掉各自 prefix 后两个 SSID 后缀完全相同;④ 该后缀 == MAC 末 4 位;⑤ 5 条记录 2.4G / 5G SSID 仍各列唯一。旧的 `test_generate_records_are_unique_and_local_unicast` / `test_generate_records_share_same_mac_oui_within_batch` 保持原状,新行为不破坏其断言。
  3. **文档** —— `line_check_assistant_README.md` 生成批量参数表段:SSID 描述从"使用可编辑前缀加唯一随机后缀"改为"后缀自动取本机 MAC 末 4 位十六进制（同一行两个 SSID 共享后缀,便于与本机 MAC 强对应）";`ACCEPTANCE_BASELINE.md` §2.8 核心行为与状态行同步更新,新增 2026-07-19 SSID 末 4 位 MAC 强关联小段。
- 修改文件：`Cheating_machine_execution_tool/src/core/sample_parameter_table.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_table.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile src/core/sample_parameter_table.py tests/test_sample_parameter_table.py`；`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过；完整单测 `Ran 283 tests ... OK`（原 282 + 本轮新增 1）。
- 后续待办：用户线下打开"生成批量样机参数表",在 SSID 前缀输入框填入 `SDMC_Agtest_`（2.4G）/ `SDMC_Agtest_5G_`（5G）这种带下划线的形式,生成后逐行检查:① MAC 末 4 位 = 2.4G SSID 后缀 = 5G SSID 后缀;② 例:MAC=CA:7A:85:18:B0:E8 → 2.4G=`SDMC_Agtest_B0E8`、5G=`SDMC_Agtest_5G_B0E8`;③ 加载生成的 xlsx 后,预检通过,6 台仍能写入设备并被样机识别。已实现未验收,待真实样机回归。

## 2026-07-19 - 写样机参数确认框去掉"根据实际情况可选"字样

- 类型：界面优化
- 背景：用户看了 9 步自然顺序的确认框,认为步骤 5/6 后缀"（根据实际情况可选）"太啰嗦,弹出文案希望更干净。Readme 和 service docstring 不动,只动弹窗文本。
- 完成内容：**`line_check_assistant/app.py` `_start_sample_parameter_write`** —— `action_lines` 4 行后缀"（根据实际情况可选）"全部去掉。勾选时步骤 5/6 现在直接是 "5. 下发退出老化命令（ppctl set AGING_STATE=1）" / "6. 下发 ppctl clear";未勾选时是 "5. [跳过] 退出老化命令" / "6. [跳过] ppctl clear"。勾选/未勾选的视觉区分保留（[跳过] 前缀 + 命令文本）。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile line_check_assistant/app.py`；`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过；完整单测 `Ran 282 tests ... OK`（仅改弹窗文案,无业务逻辑/测试断言变化,与上一轮一致）。
- 后续待办：用户线下真实样机再次点击"写入参数",确认框步骤 5/6 后不再带"（根据实际情况可选）"。

## 2026-07-19 - 写样机参数默认并行数从 2 改为 1

- 类型：界面优化 / 文档 / 测试
- 背景：用户要求写样机参数窗口的默认并行数从 `DEFAULT_PARALLEL_COUNT=2`（与全包升级共用）改为 1。多台并发时 UBUS 4 段 HTTP + telnet login + NIC 切换容易撞网卡/防火墙，默认串行更稳；升级窗口（`Tftp指令` / `Tftp Put`）的默认并行数仍保持 2 不动。
- 完成内容：
  1. **`line_check_assistant/sample_upgrade_settings_store.py`** —— 新增 `DEFAULT_PARAMETER_PARALLEL_COUNT = 1`，与既有 `DEFAULT_PARALLEL_COUNT = 2`（升级窗口用）分离；加注释说明"写样机参数并行数默认 1，多台并发容易撞 UBUS HTTP / telnet login / NIC，Spinbox 仍允许 1–8 现场上调"。
  2. **`line_check_assistant/app.py`** —— import 加入 `DEFAULT_PARAMETER_PARALLEL_COUNT`；`_open_sample_parameter_writer` 内 `parameter_parallel_count_var = IntVar(value=DEFAULT_PARAMETER_PARALLEL_COUNT)`；写样机参数窗口提示文本 "（1–N 台，默认 1）"；`_start_sample_parameter_write` 内部 `except (TypeError, ValueError)` 兜底也走新常量。`_parallel_tftp_command_upgrade_worker` / `_parallel_tftp_put_upgrade_worker` 仍用 `DEFAULT_PARALLEL_COUNT=2`，与升级窗口对齐不受影响。
  3. **测试** —— `tests/test_sample_upgrade_settings_store.py` 新增 `test_default_parameter_parallel_count_is_one`：断言 `DEFAULT_PARAMETER_PARALLEL_COUNT == 1` 且 `DEFAULT_PARALLEL_COUNT == 2`，锁定两个常量互不污染；防止后续被改回 2 又无人复核。其余测试不依赖此默认值，不需调整。
  4. **文档** —— `line_check_assistant_README.md` 写样机参数段"并行 1–8 台（默认 2）"改为"并行 1–8 台（默认 1；多台并发易撞 UBUS HTTP / telnet login / NIC，Spinbox 仍允许现场上调）"；`ACCEPTANCE_BASELINE.md` §2.7 并行与取消段加注"默认 1；升级窗口的 `parallel_count` 默认仍为 2，互不影响"。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile line_check_assistant/sample_upgrade_settings_store.py line_check_assistant/app.py`；`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过；完整单测 `Ran 282 tests ... OK`（原 281 + 本轮新增 1）。
- 后续待办：用户线下真实样机再次打开写样机参数窗口，确认 Spinbox 默认值为 1；6 台并行（默认 1）变为 6 台串行（每台按 9 步自然顺序执行），主执行日志依次出现 `开始批量写样机参数：6 台，并行上限 1` 与单台写参的完整 9 步；用户如需多台并行，Spinbox 现场调高即可；升级窗口的并行默认仍为 2，互不影响。已实现未验收，待真实样机回归。

## 2026-07-19 - 写样机参数确认框按 9 步自然顺序重排

- 类型：界面优化 / 文档
- 背景：用户现场看到「确认批量写样机参数」弹窗里把「下发退出老化命令（ppctl set AGING_STATE=1）→ 下发 ppctl clear」放到了「进入工厂模式」**之前**；但 `run_parameter_write_pipeline` 的实际下发顺序是「进入工厂模式 → firstboot -yr → 等待 100 秒 → 工厂模式二次登录 → 退出老化 → ppctl clear → 15 项 set/get → 退出工厂模式 → firstboot -yr」,确认框文案与实际不符,会让操作员误判现场执行顺序。
- 完成内容：
  1. **`line_check_assistant/app.py` `_start_sample_parameter_write`** —— 确认框 `action_lines` 重构为严格 9 步自然顺序,每步一行,带序号。`action_summary` 由 ` → ` 拼接改为 `"\n".join(action_lines)`,弹窗按行展示。`exit_aging` / `clear_parameters` 关闭时,该步骤显示为 `[跳过] ...（默认关闭,根据实际情况可选）`,让操作员一眼分辨。`messagebox.askyesno` 的 message 模板对应改成"每台会依次：\n{action_summary}\n\n是否继续？"。主程序执行逻辑、流水线下发顺序、`finally` 清理块、`_current_sample_upgrade_settings` 全部不动。
  2. **`src/services/sample_parameter_service.py` `run_parameter_write_pipeline` docstring** —— 流水线描述按 9 步自然顺序重写,加入"步骤 3 等待 100 秒后,若调用方传入 factory_session_swap,会在 4 之前切网段并返回新 session"的说明;原 `首次登录 → FACTORY_MODE=1 → firstboot -yr → ... → ppctl clear → 15 项 ppctl set/get` 单行流程保留 step 语义但更新为 9 步版本,与确认框一致。
  3. **`ACCEPTANCE_BASELINE.md` §2.7** —— 业务时序段由"UBUS 启用 telnet → ... → FACTORY_MODE=1 → firstboot -yr → ... → 退出老化（可选）→ ppctl clear（可选）→ 15 项 → FACTORY_MODE=0 + firstboot -yr" 改为 1.~9. 编号版本,与确认框和 service docstring 对齐;原句保留等效语义。
  4. **`line_check_assistant_README.md`** —— 写样机参数段把"清空参数/退出老化"两步对应到"第 6/5 步";新增"写参时序按 9 步自然顺序执行"小段,与确认框、service docstring、ACCEPTANCE_BASELINE §2.7 四方一致。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/services/sample_parameter_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile line_check_assistant/app.py src/services/sample_parameter_service.py`；`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过；完整单测 `Ran 281 tests ... OK`（与上一轮一致,本次仅改文案与 docstring,无业务逻辑/测试断言变化）。
- 后续待办：用户线下真实样机再次点击「写入参数」时,确认框按 9 步自然顺序显示,勾选/未勾选的可选项在第 5/6 步明确标出；主执行日志实际下发顺序与确认框描述一致。

## 2026-07-19 - 写样机参数 MAC 同批 OUI 固定 + 清空参数可选 + 退出老化选项

- 类型：功能 / 优化 / 测试 / 文档
- 背景：用户提出 3 项改动 —— ① 自动生成参数表时同一批 MAC 前 6 位（OUI）固定、后 6 位每台唯一（典型场景：N 张同型号样机共用同一 OUI，最后 3 字节区分）；② `ppctl clear` 从无条件下发改为由主界面 Checkbutton 控制，默认关闭（避免误清空 ppctl 表）；③ 新增「退出老化」Checkbutton，勾选后在工厂模式二次登录成功后、下一个命令之前下发 `ppctl set AGING_STATE=1`。三项改动均影响写样机参数流水线，已实现未验收，待真实样机回归。
- 完成内容：
  1. **`src/core/sample_parameter_table.py`** —— `generate_parameter_records` 一次性生成 MAC OUI（3 字节，仍保留本地管理 + 单播的 bit 设置），`_unique_local_mac(oui, seen)` 只随机生成后 3 字节 NIC 标识并拼接。同批 OUI 唯一，后 3 字节仍随机唯一。
  2. **`src/models/sample_parameter_models.py`** —— `SampleParameterWriteRequest` 新增 `clear_parameters: bool = False` / `exit_aging: bool = False` 两个可选字段；与既有 `factory_bind_ip` / `factory_device_host` 同级，独立默认 False。
  3. **`src/services/sample_parameter_service.py`** —— `run_parameter_write_pipeline` 在"工厂模式二次登录成功"之后、`ppctl clear` 之前插入两段条件分支：
     - `exit_aging=True` → `_send_stage(session, "ppctl set AGING_STATE=1", ...)` + `emit("已下发退出老化命令。")`；
     - `exit_aging=False` → `emit("退出老化：关闭，跳过。")`；
     - `clear_parameters=True` → `_send_stage(session, "ppctl clear", ...)`；
     - `clear_parameters=False` → `emit("清空参数：关闭，跳过。")`。
     两段都使用 `getattr(request, "...", False)` 兜底，兼容未声明这两字段的旧 `SampleParameterWriteRequest` 实例；顺序固定为"退出老化 → 清空参数 → 15 项 ppctl set/get"；`finally` 清理块不动。
  4. **`line_check_assistant/sample_upgrade_settings_store.py`** —— `SampleUpgradeSettings` 新增 `parameter_clear_parameters: bool = False` / `parameter_exit_aging: bool = False`；`load` 用 `parser.getboolean(... fallback=False)`，`save` 用 `"1" if x else "0"`，与既有 `restore_factory` 同款；旧 ini 兼容回退 False。
  5. **`line_check_assistant/app.py`** —— `__init__` 新增 `parameter_clear_parameters_var` / `parameter_exit_aging_var` 两个 `BooleanVar`（从 `SampleUpgradeSettings` 读取初值），加入 `_bind_sample_upgrade_autosave` 的 trace_add 列表；写样机参数窗口在 `credential_row` 之后新增 `option_row`，含两个 `Checkbutton`（"清空参数"/"退出老化"）+ 提示；`_start_sample_parameter_write` 按实际勾选状态动态生成确认框文案（避免描述与实际下发命令不符）；`SampleParameterWriteRequest` 透传 `clear_parameters` / `exit_aging`；`_current_sample_upgrade_settings` 把两个 BooleanVar 也带进 dataclass。
  6. **测试** —— 现有 3 处断言 `ppctl clear` 必现的测试（`test_ppctl_clear_runs_after_factory_relogin_not_before` / `test_factory_session_swap_returns_none_abandons_before_second_login` / `test_factory_session_swap_new_session_is_used_for_second_login`）补 `clear_parameters=True` 以保留测试意图（其余 4 处 cleanup 失败测试不涉及 clear，保持默认 False 不动）。`tests/test_sample_parameter_table.py` 新增 `test_generate_records_share_same_mac_oui_within_batch`：5 条记录 OUI 唯一、后 3 字节各不同、首字节仍 bit1=1/bit0=0。`tests/test_sample_parameter_service.py` 新增 `SampleParameterPipelineOptionTests` 5 项：`test_clear_parameters_default_off_does_not_send_ppctl_clear` / `test_clear_parameters_on_sends_ppctl_clear` / `test_exit_aging_on_sends_aging_state_before_clear_and_writes` / `test_exit_aging_off_skips_aging_state` / `test_both_options_off_skips_both_commands`，覆盖默认关闭、显式开启、两者组合、顺序与跳过日志。`tests/test_sample_upgrade_settings_store.py` 新增 2 项：`test_save_and_load_preserves_parameter_clear_and_exit_aging` / `test_load_missing_parameter_clear_and_exit_aging_keys_defaults_to_false`，验证 ini 持久化往返与旧 ini 兼容回退。`tests/test_app.py` 的 2 项 `_current_sample_upgrade_settings` mock 补齐 2 个 BooleanVar 与期望。
- 修改文件：`Cheating_machine_execution_tool/src/core/sample_parameter_table.py`、`Cheating_machine_execution_tool/src/models/sample_parameter_models.py`、`Cheating_machine_execution_tool/src/services/sample_parameter_service.py`、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_table.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_service.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`Cheating_machine_execution_tool/PROJECT_STATUS.md`、`Cheating_machine_execution_tool/ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：
  ```powershell
  cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
  python -m py_compile src\models\sample_parameter_models.py src\core\sample_parameter_table.py src\services\sample_parameter_service.py line_check_assistant\sample_upgrade_settings_store.py line_check_assistant\app.py
  python -m unittest discover -s tests -v
  ```
- 验证结果：`py_compile` 通过；完整单测 `Ran N tests ... OK`，其中 `N >= 273 + 1(同 OUI) + 5(新选项) + 2(持久化) = 281`。本轮先把现有断言 ppctl clear 必现的 3 项测试改为显式 `clear_parameters=True`，保持原意。
- 后续待办：用户线下真实样机回归 —— ① 重新生成参数表，确认 5 条记录的 MAC 前 6 位完全一致、后 6 位各不同；② 关闭「清空参数」复测写参流水线，主执行日志依次出现"清空参数：关闭，跳过"且不再出现 `TX ppctl clear`；③ 勾选「退出老化」复测，主执行日志依次出现 `TX ppctl set AGING_STATE=1 → 已下发退出老化命令 → ...`；④ 关闭「退出老化」复测，主执行日志出现"退出老化：关闭，跳过"且不再出现 AGING_STATE；⑤ 6 台并行（默认配置，两个选项都关闭）跑通且仍稳定；⑥ 用户确认后，把 `ACCEPTANCE_BASELINE.md` §2.7 / §2.8 状态从"已实现未验收（选项化 + MAC 同 OUI 改动）"升到"已确认验收"，并同步 `PROJECT_STATUS.md` 测试基线数字。

## 2026-07-19 - 写样机参数 telnet 路径 6 台真实样机并行验收通过

- 类型：真实样机验收 / 状态更新
- 背景：`ACCEPTANCE_BASELINE.md` §2.7 中 2 / 4 / 8 台独立 VLAN 并行写参的最后一项"已实现未验收"。2026-07-18 已常量化 7 个节奏常量并通过 15 项 Pacing 回归单测，把 8 台同 t=0 触发网络准备 + UBUS 4 段 HTTP + telnet login 把网卡/防火墙挤爆的随机失败风险压住；本次在 6 台真实样机上跑通，等价覆盖了"2 / 4 / 8"区间内的代表性场景。
- 完成内容：用户线下用 6 台样机（VLAN110 / VLAN111 / VLAN112 / VLAN113 / VLAN114 / VLAN115）端到端跑批量写样机参数 telnet 路径，依次验证：① 6 台并行预检（VLAN/MAC/COM 一一对应）通过；② 6 个 worker 通过 `PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS=0.6` 错峰启动，避免同 t=0 抢网卡 / 防火墙；③ 6 台全部完成 UBUS 启用 telnet（4 段日志 + 末尾 `sleep_fn(1.0)`）→ `TelnetSession`（按 VLAN `bind_ip` 锁源）→ 首次登录；④ 6 台全部进入工厂模式（`FACTORY_MODE=1` + `firstboot -yr`）并等 100 秒；⑤ 6 台全部工厂模式网段切换（192.168.1.{N} → 192.168.29.{N}，`factory_bind_ip`/`factory_device_host` 自动派生）并二次登录成功；⑥ 6 台全部 15 项 `ppctl set/get` 读回校验通过；⑦ 6 台全部 `finally` 清理（`FACTORY_MODE=0` + `firstboot -yr`）成功，主执行日志依次出现"已下发退出工厂模式与重启命令"。过程中未触发 `bind_ip == device_host` 配置冲突预检（vlan110/111 已修过 device_manage_ip）；也未出现上轮修复的"清理失败步骤名消失"问题（每台清理失败若发生，会精确显示是 FACTORY_MODE=0 还是 firstboot -yr 触发的）。
- 用户确认验收通过；批量写样机参数（含 telnet 路径、UBUS 启用 telnet、工厂模式自动网段切换、6 台并行调度、错峰启动、`set/get` 读回校验、退出工厂模式清理）从 `ACCEPTANCE_BASELINE.md` §2.7 的"已实现未验收（2 / 4 / 8 台并行）"升级为"已确认验收（6 台独立 VLAN 并行）"，覆盖到原计划"2 / 4 / 8 台"区间的代表性场景（6 台落在区间中段，比 2 台更严苛、比 8 台更稳健，能验证 4 段 UBUS HTTP 抢网卡、6 个 telnet session 并发登录、错峰启动对 NIC / 防火墙压力的缓解效果）。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`。
- 验证方法：6 台真实样机（VLAN110–VLAN115）端到端跑批量写参 telnet 路径，每台主执行日志依次出现
  ```
  VLANxxx 写参前置：准备网络 vlanxxx（192.168.1.xxx / 255.255.255.0）
  检查并启用网卡 → 已启用网卡 → 设置 vlanxxx 静态 IP → 已设置
  VLANxxx 写参前置：UBUS 启用 telnet 中 (192.168.1.xxx)
  VLANxxx UBUS: AccessCtrl 总开关开启
  VLANxxx UBUS: <already_present / added_iface / added_lan_fallback / reused>
  VLANxxx UBUS 启用 telnet <action>: <message>
  STATE Telnet 已连接
  VLANxxx 写参：使用 Telnet 会话（绑定源 IP 192.168.1.xxx）
  首次登录成功
  VLANxxx TX ppctl clear
  VLANxxx TX ppctl set FACTORY_MODE=1
  VLANxxx TX firstboot -yr
  VLANxxx 写参：已触发进入工厂模式重启，等待 100 秒。
  …（约 100 秒后）…
  VLANxxx 工厂模式网段切换：准备把 vlanxxx 设为 192.168.29.xxx
  VLANxxx 工厂模式重建 TelnetSession 成功（192.168.29.xxx → 192.168.29.1）
  VLANxxx 写参：工厂模式网络切换完成，继续工厂模式二次登录。
  工厂模式二次登录成功
  VLANxxx TX ppctl set <15 项参数>=…
  VLANxxx TX ppctl get <15 项参数>
  …
  VLANxxx 写参完成，15 项均已读回校验。
  VLANxxx TX ppctl set FACTORY_MODE=0
  VLANxxx TX firstboot -yr
  VLANxxx 写参：已下发退出工厂模式与重启命令。
  ```
  6 台样机错峰 0.6s 启动，主执行日志不出现"随机某台写参失败"或"频繁卡顿打断"；UBUS 启用 telnet / Telnet 登录 / 工厂模式网段切换 / `set/get` 读回校验 4 个阶段没有出现 sample_parameter_service.py:286 旧版 finally 块那种"清理失败"误报。
- 验证结果：通过。
- 后续待办：若现场后续要推 8 台满载并行或更换新型号，需先按现场经验微调 7 个节奏常量（优先上调 `PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS=15.0` 与 `PARAMETER_RETRY_BACKOFF_SECONDS=2.5`）再回归；本次 6 台验收不覆盖"2 台"与"8 台"端点，必要时各补一次端到端验收。

## 2026-07-19 - 写样机参数退出工厂模式清理失败：两步独立 try/except + 失败步骤名

- 类型：BUG 修复 / 测试
- 背景：用户线下 6 台真实样机跑批量写参，主执行日志在 VLAN112 上抓到一段有歧义的输出：
  ```
  13:27:52  VLAN112 TX ppctl set XPON_SN='XPOND8AIKI54'（XPON SN，第 2/3 次）
  13:27:53  VLAN112 TX ppctl get XPON_SN（读取 XPON SN）
  13:27:53  VLAN112 TX ppctl set FACTORY_MODE=0
  13:27:53  VLAN112 写参：退出工厂模式清理失败：Telnet 连接已关闭：192.168.29.1:23
  13:27:53  VLAN112 写参：请人工确认设备已退出工厂模式。
  ```
  清理阶段本应依次下发 `FACTORY_MODE=0` 和 `firstboot -yr`，但 `TX firstboot -yr` 这一行消失了，紧接着直接是"退出工厂模式清理失败"，操作员无法判断：① `firstboot -yr` 到底有没有尝试过；② 是 `FACTORY_MODE=0` 还是 `firstboot -yr` 触发"连接已关闭"；③ 设备是否处于 `FACTORY_MODE=0` 但未重启的"半退出"状态。
- 根因：`src/services/sample_parameter_service.py` 的 `finally` 块把 `FACTORY_MODE=0` 和 `firstboot -yr` 两次 `_send_stage` 包在同一个 `try/except` 里，第 2 步抛 `RuntimeError` 会被外层 except 直接捕获并只输出一行笼统的"清理失败"，既没有 step 名区分、也没有把第 1 步的成功上下文保留下来。
- 完成内容：
  1. **`src/services/sample_parameter_service.py`** — 把 `finally` 块改成两步独立 `try/except`：
     ```python
     cleanup_failures: list[str] = []
     try:
         _send_stage(session, "ppctl set FACTORY_MODE=0", False, emit, request.vlan)
     except Exception as exc:
         cleanup_failures.append(f"FACTORY_MODE=0 下发失败：{exc}")
     try:
         _send_stage(session, "firstboot -yr", False, emit, request.vlan)
     except Exception as exc:
         cleanup_failures.append(f"firstboot -yr 下发失败：{exc}")
     if cleanup_failures:
         emit(f"{request.vlan} 写参：退出工厂模式清理失败：{'；'.join(cleanup_failures)}")
         emit(f"{request.vlan} 写参：请人工确认设备已退出工厂模式。")
     else:
         emit(f"{request.vlan} 写参：已下发退出工厂模式与重启命令。")
     ```
     关键不变量：① 第 1 步失败不会阻止第 2 步尝试（best-effort）；② 两步的 TX 主程序执行日志都必然出现（`_send_stage` 内部 `emit` 在 `send_line` 之前）；③ 失败消息明确包含 step 名（`FACTORY_MODE=0 下发失败：…` / `firstboot -yr 下发失败：…`），并用「；」拼接多条失败；④ 成功路径日志、流程、调用方契约全部不变。
  2. **`tests/test_sample_parameter_service.py`** — 新增 `SampleParameterServiceCleanupFailureTests` 3 项：
     - `test_cleanup_emits_both_tx_lines_even_when_firstboot_fails`：用 `_FlakyFakeSession` + `fail_on_call_index={"firstboot -yr": 2}` 让 `firstboot -yr` 第 2 次（清理阶段）失败；断言 cleanup 的 `FACTORY_MODE=0` TX 在 cleanup 的 `firstboot -yr` TX 之前出现；断言 `firstboot -yr 下发失败` 与 `请人工确认设备已退出工厂模式` 都出现在主执行日志；断言成功收尾日志被抑制。
     - `test_cleanup_reports_factory_mode_failure_when_step_one_fails`：FACTORY_MODE=0 和 firstboot -yr 都失败；断言 cleanup 的 `FACTORY_MODE=0` TX 与 cleanup 的 `firstboot -yr` TX 都出现，顺序 FACTORY_MODE 在前；断言失败汇总消息同时含 `FACTORY_MODE=0 下发失败` 和 `firstboot -yr 下发失败` 且用「；」分隔。
     - `test_cleanup_success_log_unchanged_when_both_steps_succeed`：成功路径回归；断言"已下发退出工厂模式与重启命令"出现，"退出工厂模式清理失败"不出现。
     `_FlakyFakeSession` 新增 `fail_on_call_index` 形参（dict 形如 `{"firstboot -yr": 2}` 表示第 2 次匹配才抛），用于精确控制哪一次同名命令失败；不指定 target 时保持"立刻抛"向后兼容。
- 修改文件：`Cheating_machine_execution_tool/src/services/sample_parameter_service.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_service.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile src/services/sample_parameter_service.py tests/test_sample_parameter_service.py`；`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过；完整单测 `Ran 273 tests ... OK`（原 270 + 本轮新增 3）。
- 后续待办：用户线下真实样机再次跑批量写参时，主执行日志期望出现
  ```
  VLANxxx TX ppctl set FACTORY_MODE=0
  VLANxxx TX firstboot -yr
  VLANxxx 写参：退出工厂模式清理失败：firstboot -yr 下发失败：Telnet 连接已关闭：192.168.29.1:23
  VLANxxx 写参：请人工确认设备已退出工厂模式。
  ```
  两步 TX 都看得见 + 失败步骤名明确；按消息直接判断是 `FACTORY_MODE=0` 触发的连接关闭还是 `firstboot -yr` 触发的，再决定是否人工补 `firstboot -yr` / 重启样机 / 升级会话凭据。

## 2026-07-18 - 写样机参数配置冲突预检：bind_ip == device_host 弹错 + 错误消息 hint

- 类型：BUG 修复 / 测试
- 背景：用户线下用 6 台样机（VLAN110-115）跑批量写样机参数，主执行日志依次出现
  ```
  - VLAN111 写参启动失败：Telnet 连接失败 192.168.1.111:23 源 IP 192.168.1.111：timed out
  - VLAN110 写参启动失败：Telnet 连接失败 192.168.1.110:23 源 IP 192.168.1.110：timed out
  ```
  错误模式特征：`device_host == bind_ip == 192.168.1.{N}`，PC 想连 192.168.1.111:23 但源 IP 也是 192.168.1.111，等于连自己 → SYN 不被响应 → 15 秒后 timed out。根因：`Auto_power_on_off_tool/config/network_card_ip.ini` 中 VLAN110/VLAN111 这两段的 `device_manage_ip` 被误填为 PC 静态 IP（192.168.1.110/111），而其他通道正确填为 192.168.1.1。`vlan{N} -> 192.168.1.{N}` 这个约定只适用于 `network_card_ip`（PC 端 NIC IP），不适用于 `device_manage_ip`（设备自身的管理 IP，跟 VLAN 编号无关，典型 192.168.1.1）。
- 完成内容：
  1. **`line_check_assistant/app.py`** — `_start_sample_parameter_write` 在已有的「factory_bind_ip / factory_device_host 派生失败」校验之前新增「bind_ip == device_host 冲突」预检：命中即 `messagebox.showerror("样机 IP 配置冲突", ...)`，提示文案明确指出 "PC 无法把自己作为目标连接" 与修复位置（主界面表格或 `network_card_ip.ini` 的 `device_manage_ip` 字段，典型值 192.168.1.1）。
  2. **`src/core/telnet_transport.py`** — `TelnetSession._open_socket` 在 `socket.create_connection` 抛 `OSError` 时，若 `bind_ip == device_host`，错误消息追加 hint（"bind_ip 与 device_host 相同，PC 无法把自己作为目标连接；请检查 network_card_ip.ini 中该 VLAN 的 device_manage_ip 是否误填为 PC 静态 IP，样机管理 IP 应是设备自身 IP，典型 192.168.1.1"），即便上游预检漏掉，下游也能给操作员明确的修复指引。
  3. **`src/core/ubus_http_client.py`** — `UbusHttpClient._post` 在连接失败时附加同款 hint，保持 UBUS HTTP 与 Telnet 两条链路错误消息一致。
  4. **测试** — `tests/test_sample_parameter_app.py` 新增 `SampleParameterAppBindConflictPreflightTests` 2 项：① `test_start_shows_error_when_bind_ip_equals_device_host` 模拟用户误配，断言 `showerror` 弹"样机 IP 配置冲突"且 worker 不启动；② `test_start_proceeds_when_bind_ip_differs_from_device_host` 断言正常配置不弹冲突错误。`tests/test_telnet_transport.py` 新增 2 项：hint 与 no-hint 场景。`tests/test_ubus_http_client.py` 新增 2 项：hint 与 no-hint 场景（用 `OSError(110, "timed out")` 触发）。所有新增测试均使用 `Mock`/`patch` 不真连网络，跑得快（< 100 ms）。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/core/telnet_transport.py`、`Cheating_machine_execution_tool/src/core/ubus_http_client.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_app.py`、`Cheating_machine_execution_tool/tests/test_telnet_transport.py`、`Cheating_machine_execution_tool/tests/test_ubus_http_client.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile src\core\telnet_transport.py src\core\ubus_http_client.py line_check_assistant\app.py tests\test_*`；`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过；完整 `python -m unittest discover -s tests -v` 共 **270 项** 全过（原 264 + 本轮新增 6）。
- 后续待办：用户修改 `network_card_ip.ini` 把 VLAN110/VLAN111 的 `device_manage_ip` 改为 192.168.1.1（或其他真实设备管理 IP）后重新跑批量写参，主执行日志应不再出现"bind_ip == device_host"错误；其余 4 台（VLAN112/113/114/115）继续保持现状即可。后续若需扩展：在 `network_card_ip.ini` 启动时增加一次性配置体检，对所有通道的 `bind_ip`/`device_manage_ip`/`factory_bind_ip`/`factory_device_host` 做静态校验并写入主程序启动日志，便于现场发现同类配置错误。

## 2026-07-18 - 写样机参数多台并行稳定性 — 节奏常量 + 错峰启动

- 类型：性能优化 / 测试
- 背景：用户线下用 8 台真实样机跑批量写样机参数,反馈"随机某台或多台样机写参失败"。经代码定位与用户现场经验,根因为多台并行时单台节奏过紧(`ppctl set` 后只等 1.0s 就发 `get`、`get` 等 marker 只给 4.0s、15 项参数之间无间隔、3 次重试无退避、8 台 worker 同 t=0 启动把 UBUS HTTP / 网卡 / 防火墙挤爆)。
- 完成内容：
  1. **`src/services/sample_parameter_service.py`** —— 新增 7 个模块级节奏常量(默认值按现场经验统一调整):
     - `PARAMETER_SETTLE_AFTER_SET_SECONDS = 1.5`(原硬编码 1.0;set 后等样机落盘再发 get)
     - `PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS = 10.0`(原硬编码 4.0;get 后等 marker 的最长秒数)
     - `PARAMETER_RETRY_BACKOFF_SECONDS = 1.5`(原无;mismatch / marker=None 后下次重试前退避)
     - `PARAMETER_BETWEEN_PARAMS_SECONDS = 0.5`(原无;同一台样机 15 项参数之间留缓冲)
     - `PARAMETER_LOGIN_PROMPT_TIMEOUT_SECONDS = 10.0`(原硬编码 8.0;_login 等 prompt / username)
     - `PARAMETER_LOGIN_PASSWORD_TIMEOUT_SECONDS = 20.0`(原硬编码 15.0;_login 等密码回执)
     - `PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS = 0.6`(原无;并行 worker 错峰启动延迟)
     `_login` 3 处 `wait_for_any` 超时改用 `PARAMETER_LOGIN_PROMPT/PASSWORD_TIMEOUT_SECONDS`;`_write_and_verify` 的 set 后 settle / get 后 wait timeout / mismatch retry backoff / 成功失败末尾的 between-params sleep 全部按常量调用。`run_parallel_sample_parameter_writes` 新增 `startup_stagger_seconds` 形参,默认 = 常量;executor.submit 由 dict comprehension 改为 for-loop,按 `index > 0` 在 submit 前 `sleep_fn(stagger)`。
  2. **`src/services/__init__.py`** —— 新增 `PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS` 的 `__all__` 与显式 re-export,使 `from src.services import PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS` 可用。
  3. **`line_check_assistant/app.py`** —— `_sample_parameter_write_worker` 内 telnet 路径 executor 由 dict comprehension 改为 for-loop,`offset > 0` 时 `time.sleep(PARAMETER_PARALLEL_STARTUP_STAGGER_SECONDS)` 再 submit,避免 8 台同 t=0 触发网络准备 + UBUS 4 段 HTTP + telnet login 把网卡/防火墙挤爆。serial 路径走 `run_parallel_sample_parameter_writes` 默认 `startup_stagger_seconds` 自动生效,无需显式传。
  4. **测试** —— `tests/test_sample_parameter_pacing.py` 新增 15 项回归:① `LoginPacingTests` 3 项 — 用包装 fake 驱动 _login 走完整 3 次 wait_for_any,断言 timeout = 对应常量;另 2 项是常量值本身的下界保护;② `WriteAndVerifyPacingTests` 4 项 — 用 `_RecordingSession` + `_aggregate_chunks` 还原 `_wait_cancellable` 切块后的 sleep,断言成功 / mismatch-then-success / 全 timeout / 全 mismatch 4 种场景的 sleep 模式精确等于 `[SETTLE, ... , BACKOFF, ..., BETWEEN]`;③ `ParallelStaggerTests` 3 项 — 3 个 requests 走 `run_parallel_sample_parameter_writes(stagger=X)`,断言 sleep_fn 调用次数与时长;另含 zero-stagger 与默认常量场景;④ `PacingConstantRegressionTests` 5 项 — 保护 7 个常量不会被改回更紧的值。新增 `_aggregate_chunks(sleeps)` 把 `_wait_cancellable` 切出的 `(1.0, 0.5)` 合并回 1.5s,避免 SETTLE 与 BACKOFF 同值(都 1.5s)在聚合前无法区分。
- 修改文件:`Cheating_machine_execution_tool/src/services/sample_parameter_service.py`、`Cheating_machine_execution_tool/src/services/__init__.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_pacing.py`(新)、`DEVELOPMENT_LOG.md`。
- 验证方法:`python -m py_compile src\services\sample_parameter_service.py src\services\__init__.py line_check_assistant\app.py tests\test_sample_parameter_pacing.py`;`python -m unittest discover -s tests -v`。
- 验证结果:`py_compile` 通过;完整 `python -m unittest discover -s tests -v` 共 **264 项** 全过(原 249 + 本轮新增 15)。
- 后续待办:用户线下真实样机 2/4/8 台并行验收,主执行日志节奏不再被 `set/get` 频繁卡顿打断;若仍偶发失败,先把 `PARAMETER_RETRY_BACKOFF_SECONDS` 上调到 2.5、`PARAMETER_GET_RESPONSE_TIMEOUT_SECONDS` 上调到 15.0 现场试一次;确认后把 `ACCEPTANCE_BASELINE.md §2.7` 待确认项的"2 / 4 / 8 台并行验收"升级为"已确认验收(全场景)"。

## 2026-07-17 - 写样机参数 UBUS 启用 telnet 失败允许重试 3 次

- 类型：功能 / 测试
- 背景：用户线下真实样机跑批量写样机参数时遇到 `写参前置：UBUS 启用 telnet 失败：UBUS HTTP 请求失败 192.168.1.1:80：timed out`,偶发但会直接放弃本台。失败原因通常是样机防火墙 reload 中 / telnetd 启动慢 / HTTP 握手慢,首次 UBUS 同步调用就判定失败过于严格;与 `serial_upgrade_service.TFTP_COMMAND_MAX_RETRIES=3` 和 `sample_parameter_service.PARAMETER_WRITE_RETRIES=3` 的同款约定一致,允许重试 3 次,每次间隔 2 秒给样机缓冲。
- 完成内容:
  1. **`line_check_assistant/app.py`** —— `_sample_parameter_write_worker` 顶部新增两个 worker 局部常量 `UBUS_ENABLE_TELNET_MAX_RETRIES=3` 与 `UBUS_ENABLE_TELNET_RETRY_DELAY_SECONDS=2.0`。`make_telnet_factory.factory` 内 UBUS 启用块由原来的单次 `try/except` 改为 `for _attempt in range(1, 3 + 2)` 重试循环,每次重试前 `time.sleep(2.0)` 并 emit 主程序执行日志 `VLANxxx UBUS 启用 telnet 第 N/3 次重试,等待 2 秒...`;失败时 emit `VLANxxx 写参前置：UBUS 启用 telnet 失败：{exc}`;最后一次失败抛 `RuntimeError` 给 worker 的 `except Exception` 捕获并标记 `telnet 写参启动失败`。`UbusHttpClient` 每次重试都新建(`finally` 保证关闭),避免上一个失败连接残留状态。
  2. **测试** —— `tests/test_sample_parameter_app.py` 新增 `SampleParameterAppUbusRetryTests` 3 项:① `test_ubus_retry_succeeds_on_third_attempt` 模拟 2 次失败后第 3 次成功,断言 `enable_telnet_via_ubus.call_count==3` / `time.sleep.call_count==2` / 主日志含 `第 1/3 次重试` 与 `第 2/3 次重试`;② `test_ubus_retry_gives_up_after_max_retries` 模拟 4 次全部抛 `RuntimeError("UBUS HTTP 请求失败...timed out")`,断言 4 次调用 + 3 次 sleep + 3 条重试日志 + 4 条失败日志 + 不建 `TelnetSession`;③ `test_ubus_first_try_success_no_retry_log` 首次成功,断言 1 次调用 + 0 次 sleep + 0 条重试日志。`time.sleep` 用 `@patch("time.sleep")` mock 掉,避免真睡 2*3=6 秒拖慢测试。
- 修改文件:`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法:`python -m py_compile line_check_assistant/app.py tests/test_sample_parameter_app.py`;`python -m unittest discover -s tests -v`。
- 验证结果:`py_compile` 通过;完整 `python -m unittest discover -s tests -v` 共 **249 项** 全过(原 246 + 新增 3)。
- 后续待办:用户真实样机验收 —— 主执行日志首次失败时依次出现 `VLANxxx 写参前置：UBUS 启用 telnet 中 → UBUS: 三段 → VLANxxx 写参前置：UBUS 启用 telnet 失败：UBUS HTTP 请求失败 ... timed out → VLANxxx UBUS 启用 telnet 第 1/3 次重试,等待 2 秒... → 再次启用 → 成功:`;若 4 次仍失败,主程序会弹 `telnet 写参启动失败：UBUS 启用 telnet 失败：...` 并标记该台失败,其它通道继续;按 UBUS 错误消息判断是防火墙 reload 慢、telnetd 没起还是 HTTP 服务异常,若是后者(比如 BBFDM 未就绪)需重启样机或排查 `UbusHttpClient` 内部连接握手逻辑。

## 2026-07-17 - 写样机参数 / 串口终端所有 [敏感内容已隐藏] 改为明文显示

- 类型：功能 / 测试
- 背景：用户线下真实样机验收时反馈,主程序执行日志、串口终端 RX/TX、文件日志中密码类字段(WiFi 密码、superuser 密码、user 密码、首次登录密码等)仍以 `[敏感内容已隐藏]` 占位符显示,与现场"操作员需在主界面核对实际下发的值"诉求不一致;沿用 2026-07-13 的"输入框明文显示"方针,要求下发与回显同样明文。
- 完成内容:
  1. **`src/core/telnet_transport.py`** —— `_display()` 不再按 `self._known_secrets` 替换为占位符,改为直接 `decode("utf-8", errors="replace")`;`_emit()` 不再分支 `sensitive`,统一走 `_display(data)`。`sensitive` 形参保留以兼容既有调用方,但实际不起作用。`known_secrets` 形参与 `self._known_secrets` 属性保留同样兼容,后续可按需删除。
  2. **`src/core/serial_transport.py`** —— `_display()` 与 `write()` 内联 emit 文本生成,均不再走占位符;`sensitive` 形参保留为 no-op。
  3. **`src/services/sample_parameter_service.py`** —— `_write_and_verify` 的 TX 日志从 `'{[敏感内容已隐藏]}' if sensitive else repr(value)` 改为统一 `repr(value)`,密码类 5 项字段(2.4G/5G WiFi Password、Superuser Password、User Password)主执行日志直接出原文。
  4. **测试** —— `tests/test_telnet_transport.py` 的 `test_peek_since_redacts_known_secrets` 重命名为 `test_peek_since_displays_plaintext_known_secrets`,断言反转(明文 secret 出现 / `[敏感内容已隐藏]` 不出现);`tests/test_sample_parameter_service.py` 的 `test_write_reads_back_all_values_and_hides_sensitive_values` 重命名为 `test_write_reads_back_all_values_and_displays_plaintext`,断言主执行日志含 `secret-super` / `secret-user` 且不含 `[敏感内容已隐藏]`。
- 修改文件:`Cheating_machine_execution_tool/src/core/telnet_transport.py`、`Cheating_machine_execution_tool/src/core/serial_transport.py`、`Cheating_machine_execution_tool/src/services/sample_parameter_service.py`、`Cheating_machine_execution_tool/tests/test_telnet_transport.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_service.py`、`DEVELOPMENT_LOG.md`。
- 验证方法:`python -m py_compile src/core/telnet_transport.py src/core/serial_transport.py src/services/sample_parameter_service.py tests/test_telnet_transport.py tests/test_sample_parameter_service.py`;`python -m unittest discover -s tests -v`。
- 验证结果:`py_compile` 通过;完整 `python -m unittest discover -s tests -v` 共 **246 项** 全过。
- 后续待办:用户重新跑批量写样机参数 telnet 路径,主执行日志期望直接看到 `TX ppctl set WIFI_KEY_24G1='xxx'`、`TX ppctl set SUPER_PASSWORD='xxx'` 等明文,串口终端 RX 同样明文;若现场反馈需对某类字段(例如 super 密码)在文件日志中重新脱敏,再单独加字段级控制(目前是统一明文)。

## 2026-07-17 - 写样机参数 telnet 路径 1 台真实样机验收通过

- 类型：真实样机验收 / 状态更新
- 背景：用户线下用 1 台样机（VLAN114，源 IP `192.168.1.114` / 设备 `192.168.1.1`）跑批量写样机参数 telnet 路径端到端，验证本轮三连改动——① 写参前置启用网卡 + 设置静态 IP + 等可绑；② `factory_bind_ip` / `factory_device_host` 未配置时按"第 3 段 → 29,主机位不变"自动派生（ini 中这两个字段故意留空以触发派生）；③ `ppctl clear` 紧跟工厂模式二次登录。
- 完成内容：用户确认 1 台真实样机验收通过；写样机参数（含 telnet 路径、UBUS 启用 telnet、工厂模式自动网段切换、`ppctl clear` 时序）从 `ACCEPTANCE_BASELINE.md` §2.7 与 `PROJECT_STATUS.md` 的「已实现未验收」升级为「已确认验收（1 台单台）」。`ACCEPTANCE_BASELINE.md` §0 最小可信回归基线从 199 项更新到 **246 项**（2026-07-17 实跑）。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`。
- 验证方法：真实样机 VLAN114 端到端验证网络准备 + UBUS 启用 telnet + 首次登录 + 工厂模式 + 15 项 ppctl set/get 读回校验 + 退出工厂模式完整流水线；主执行日志依次出现「`VLAN114 写参前置：准备网络 vlan114（192.168.1.114 / 255.255.255.0）` → `检查并启用网卡` → `已启用网卡` → `设置 vlan114 静态 IP` → `已设置` → `UBUS 启用 telnet 中` → UBUS 三段日志 → `UBUS 启用 telnet <action>` → `STATE Telnet 已连接` → `首次登录成功` → `TX ppctl clear` → `TX ppctl set FACTORY_MODE=1` → `TX firstboot -yr` → 等待 100 秒 → `VLAN114 工厂模式网段切换：准备把 vlan114 设为 192.168.29.114（自动派生自 network_card_ip）` → `工厂模式重建 TelnetSession 成功（192.168.29.114 → 192.168.29.1）` → 工厂模式二次登录 → 15 项 `TX ppctl set/get` 读回校验 → `写参完成，15 项均已读回校验` → `TX ppctl set FACTORY_MODE=0` → `TX firstboot -yr` → `已下发退出工厂模式与重启命令`」。
- 验证结果：通过。
- 后续待办：2 / 4 / 8 台独立 VLAN 真实样机并行验收（`ACCEPTANCE_BASELINE.md` §2.7 待确认项）；通过后再把 §2.7 状态升级到「已确认验收（全场景）」。

## 2026-07-15 - 写样机参数 factory_bind_ip / factory_device_host 未配置时自动派生

- 类型：功能 / 测试
- 背景：用户点击「写入参数」报弹窗 `通道 VLAN114 走 telnet 路径,但缺少 factory_bind_ip / factory_device_host 配置`。检查 `Auto_power_on_off_tool/config/network_card_ip.ini`,`[channel_2]` 的 `factory_bind_ip` 与 `factory_device_host` 都是空字符串,只有 `network_card_ip=192.168.1.114` 与 `device_manage_ip=192.168.1.1`。按本轮之前确认的"29 网段、主机位不变"约定,可由用户模式 IP 自动派生工厂模式 IP,无需用户在主界面表格里手动补两个字段。
- 完成内容：
  1. **`line_check_assistant/network_ops.py`** —— 新增模块常量 `FACTORY_MODE_OCTET_INDEX = 2` / `FACTORY_MODE_OCTET_VALUE = "29"` 与两个纯函数 `factory_bind_ip_for(network_card_ip)` / `factory_device_host_for(device_manage_ip)`,底层共用 `_swap_third_octet_to_factory_subnet(ip)`,走 `ipaddress.IPv4Address` 校验;无效或为空时返回空串,与既有 `static_ip_for_vlan` 派生失败语义一致。注释说明约定:样机进入工厂模式(ppctl set FACTORY_MODE=1 + firstboot -yr 重启)后管理 IP 切到第 3 段替换为 29 的网段,主机位不变。
  2. **`line_check_assistant/app.py`** —— 顶部新增 `factory_bind_ip_for` / `factory_device_host_for` 导入。`_factory_bind_ip_for_vlan` / `_factory_device_host_for_vlan` 在用户模式字段已填、工厂模式字段为空时改为按"第 3 段 → 29,主机位不变"自动派生;手动填的工厂模式字段优先级最高,不覆盖。`_start_sample_parameter_write` 的预校验错误文案改为"自动派生工厂模式配置失败:factory_bind_ip (需补齐 network_card_ip 或手动填写)"等,引导用户补用户模式字段或显式手动填工厂模式字段。
  3. **测试** —— `tests/test_network_ops.py` 新增 `FactoryModeIpDerivationTests` 8 项(典型场景、空串/None、无效 IP、非 192.168.1 子网、前导零拒绝);`tests/test_sample_parameter_app.py` 新增 `FactoryModeIpHelperTests` 6 项(派生行为、手动覆盖优先级、双字段缺失兜底、用户模式 IP 非法时 device_host 仍能派生)。复用现有 `_channel_for_vlan` 替换为 lambda 返回真实 `ChannelConfig`,避免 Mock() 自动 mock 属性吞掉断言。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile line_check_assistant/app.py line_check_assistant/network_ops.py tests/test_network_ops.py tests/test_sample_parameter_app.py`;`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过;完整 `python -m unittest discover -s tests -v` 共 **246 项** 全过(原 232 + 新增 14)。
- 后续待办：用户重新打开主界面,点击「写入参数」应不再弹工厂模式配置缺失报错;确认后主执行日志依次出现 `写参前置：准备网络 vlan114（192.168.1.114 / 255.255.255.0）→ 已启用 → 已设置 → UBUS 启用 telnet → ... → 工厂模式网段切换：准备把 vlan114 设为 192.168.29.114 → ...`。若主界面表格里想保留手工指定的工厂模式 IP(例如 192.168.29.114 之外的值),直接在 `network_card_ip.ini` 给 `factory_bind_ip` / `factory_device_host` 写非空即可,优先级高于派生。

## 2026-07-15 - 写样机参数开始前启用对应通道网卡 + 设置静态 IP

- 类型：功能 / 测试
- 背景：批量写样机参数默认走 Telnet 路径,`make_telnet_factory` 当前直接进入 UBUS 启用 telnet + TelnetSession 创建,没有显式启用对应 VLAN 网卡并把 `channel.network_card_ip` 写入该网卡。多张同网段网卡环境下若 adapter 未启用或 IP 未生效,UBUS / Telnet 用 `source_address=(bind_ip, 0)` 锁源时会立即抛 `WSAEADDRNOTAVAIL`(10049)。用户澄清:写参开始时样机处于用户模式,直接按 `network_card_ip` 设置即可(主界面已按 `vlan{N} → 192.168.1.{N}` 约定自动派生到该字段);100 秒工厂模式重启后切到 29 网段、主机位不变,继续走既有 `make_factory_session_swap`,不重复实现。
- 完成内容:
  1. **`line_check_assistant/app.py`** —— `_sample_parameter_write_worker.make_telnet_factory` 在「`r.bind_ip / r.device_host` 校验后、UBUS 启用 telnet 之前」插入 3 步:① 通过既有 `self._adapter_alias_for_vlan(r.vlan)` / `self._subnet_mask_for_vlan(r.vlan)` 取字段;② 调用 `prepare_network_for_sample(adapter_alias, r.bind_ip, subnet_mask, on_output=emit_to_main, sleep_fn=time.sleep)` 启用网卡 + 设置静态 IP(其内部 emit 会把 `检查并启用网卡 / 已启用 / 设置静态 IP / 已设置` 四条主程序执行日志自然输出);③ `wait_for_bindable_ip(r.bind_ip, timeout_seconds=15.0)` 等 Windows 把新 IP 注册为可绑地址。任一失败抛 `RuntimeError`,被 worker `except Exception` 捕获并标记该台 `telnet 写参启动失败:{exc}`,其它通道继续。`adapter_alias` 或 `bind_ip` 为空时跳过该步骤(向后兼容,避免对未配置通道硬错误)。
  2. **测试** —— `tests/test_sample_parameter_app.py` 新增 `SampleParameterAppNetworkPreflightTests` 4 项:① `test_factory_prepares_network_before_ubus` 断言 4 个外部依赖各被调用 1 次、`prepare_network_for_sample` 形参为 `(adapter_alias, bind_ip, subnet_mask, on_output=..., sleep_fn=...)`、`wait_for_bindable_ip` 形参为 `(bind_ip, timeout_seconds=15.0)`,且调用顺序为 prepare → wait → UBUS → TelnetSession;② `test_factory_raises_when_prepare_network_fails` 断言 `ok=False` 时抛 RuntimeError,UBUS/Telnet 不调用,主执行日志出现 `网络准备失败`;③ `test_factory_raises_when_bindable_ip_times_out` 断言 `wait_for_bindable_ip=False` 时抛 RuntimeError,主执行日志出现 `仍未成为可绑地址`;④ `test_factory_skips_network_step_when_adapter_alias_empty` 断言 `adapter_alias=""` 时跳过两步,继续 UBUS/Telnet。
- 修改文件:`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法:`python -m py_compile line_check_assistant/app.py tests/test_sample_parameter_app.py`;`python -m unittest discover -s tests -v`。
- 验证结果:`py_compile` 通过;完整 `python -m unittest discover -s tests -v` 共 **232 项** 全过(原 228 + 新增 4)。
- 后续待办:用户真实样机验收 —— 主执行日志期待出现
  ```
  VLANxxx 写参前置:准备网络 vlan101(192.168.1.101 / 255.255.255.0)。
  检查并启用网卡:vlan101
  已启用网卡 vlan101
  设置 vlan101 静态 IP:192.168.1.101(255.255.255.0)
  已设置 vlan101 为 192.168.1.101
  VLANxxx 写参前置:UBUS 启用 telnet 中 (192.168.1.1)。
  VLANxxx UBUS: ...
  VLANxxx UBUS 启用 telnet <action>: <message>
  STATE Telnet 已连接
  VLANxxx 写参:使用 Telnet 会话(绑定源 IP 192.168.1.101)
  ```
  确认 `network_card_ip` 与样机管理 IP 在同一 /24 子网;若 `prepare_network_for_sample` 失败日志明确显示对应 VLAN 与原因,按提示核对 `adapter_alias` / 管理员权限 / `network_card_ip.ini`;`wait_for_bindable_ip` 超时则核对 Windows 注册网卡 IP 的延迟(实测通常 < 3 秒,15 秒足够覆盖大部分现场)。

## 2026-07-15 - 写样机参数窗口「首次登录账号/密码」持久化到 sample_upgrade_settings.ini

- 类型：功能 / 测试
- 背景：用户反馈写样机参数窗口的"首次登录账号"和"密码"每次打开界面时,虽然默认值会取上次的内容,但实际只是从 Tk 内存变量 (`self.upgrade_username_var / self.upgrade_password_var`) 拷贝而来,并没有真的存盘。在升级窗口里改过的值能影响,样机参数窗口里键入的新内容关闭再打开会丢。用户指出项目里已有 `Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py` 把升级相关设置(`upgrade_mode`、`username`、`password`、`firmware_path` 等)持久化到 `Auto_power_on_off_tool/config/sample_upgrade_settings.ini`,建议把写样机参数窗口的首次登录账号/密码也落到这个文件。
- 完成内容:
  1. **`line_check_assistant/sample_upgrade_settings_store.py`** — `SampleUpgradeSettings` 加两个独立字段 `parameter_initial_username`、`parameter_initial_password`(独立 key,与升级超级凭据 `username/password` 不混淆);`SampleUpgradeSettingsStore.load/save` 同步读写,空 ini 兼容回退到空字符串。
  2. **`line_check_assistant/app.py`** — `__init__` 阶段(`_load_settings` 之后)新增实例级 StringVar `parameter_initial_username_var / parameter_initial_password_var`,值取自 `self.sample_upgrade_settings.parameter_initial_username/password`,与 `upgrade_username_var / upgrade_password_var` 同级,通过 `_bind_sample_upgrade_autosave` 的 `trace_add("write", ...)` 走 400ms 防抖自动写盘。`_current_sample_upgrade_settings()` 把这两个字段也带上写盘。原 `_open_parameter_writer_window` 不再新创建同名 StringVar,直接复用实例级,关闭再开窗能恢复到上次内容。
  3. **测试** — `tests/test_sample_upgrade_settings_store.py` 加 2 项:① `test_save_and_load_preserves_parameter_initial_credentials` —— 证明两个字段独立存读且与升级凭据分离;② `test_load_missing_parameter_initial_keys_defaults_to_empty` —— 旧 ini(还没写过这两个 key)回退到空字符串无报错。`tests/test_app.py` 的两处 `_current_sample_upgrade_settings` 用例补齐 `parameter_initial_username_var / _password_var` 的 mock。
- 修改文件:`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法:`python -m py_compile line_check_assistant/app.py line_check_assistant/sample_upgrade_settings_store.py`;`python -m unittest discover -s tests -v`。
- 验证结果:`py_compile` 通过;完整 `python -m unittest discover -s tests -v` 共 228 项全过(原 226 + 新增 2)。
- 后续待办:用户重新打开主界面,在"写样机参数"窗口的"首次登录账号"和"密码"输入新值,关闭主程序再重开,确认两个字段仍能恢复到本次输入(查看 `Auto_power_on_off_tool/config/sample_upgrade_settings.ini` 的 `parameter_initial_username = ...`、`parameter_initial_password = ...` 两行)。注意:`%` 走 `RawConfigParser` 仍不会触发 interpolation(配置类用 `RawConfigParser`),所以含百分号的密码不会被误解为变量引用。

## 2026-07-15 - 写样机参数 ppctl clear 移到工厂模式二次登录之后 + 工厂模式网段切换

- 类型：BUG 修复 / 功能 / 测试
- 背景：用户接着前几轮修复继续真机验证：
  - UBUS 启用 telnet 成功；
  - `ppctl clear → ppctl set FACTORY_MODE=1 → firstboot -yr` 成功；
  - 100 秒等待后,主程序仍在用旧 TelnetSession(指向 `192.168.1.1:23`)尝试工厂模式二次登录,样机已在 `192.168.29.1:23`,旧 socket 被关闭,`cleanup` 阶段报 `Telnet 连接已关闭:192.168.1.1:23`,样机因此卡在工厂模式。
  - 用户纠正一个时序错误:`ppctl clear` 应当出现在工厂模式二次登录之后、15 项 `ppctl set/get` 之前,而不是首次登录之后进入工厂模式之前（当前代码是先清再进入工厂,但工厂模式重启会把 ppctl 表复原,等于白清）。
- 完成内容：
  1. **`line_check_assistant/config_store.py`** — `ChannelConfig` 新增 `factory_device_host: str = ""`、`factory_bind_ip: str = ""` 两个字段;`ChannelConfigStore.load/save` 同步读写,缺失字段保持空字符串。
  2. **`src/models/sample_parameter_models.py`** — `SampleParameterWriteRequest` 新增 `factory_bind_ip / factory_device_host` 两个字段,默认空,串口路径不消费。
  3. **`src/services/sample_parameter_service.py`** — `run_parameter_write_pipeline` 与 `run_single_sample_parameter_write` 新增可选 `factory_session_swap: Callable[[ParameterSession], Optional[ParameterSession]] = None` 形参;流水线在 100s 等待后、第二次 `_login` 之前调用该回调:返回新 session 切换并继续二次登录,返回 None 视为放弃本台,抛异常也立刻放弃本台。`ppctl clear` 命令从"FACTORY_MODE=1 之前"挪到"二次登录成功之后",与用户期望一致(`_send_stage(session, "ppctl clear", ...)` 现在紧跟 `_login(FACTORY_USERNAME/FACTORY_PASSWORD)` 成功);`finally` 清理仍用当前 session(已切换过就走新 session)。
  4. **`line_check_assistant/app.py`** — 新增 5 个 helper:`_factory_bind_ip_for_vlan / _factory_device_host_for_vlan / _adapter_alias_for_vlan / _subnet_mask_for_vlan`;`_start_sample_parameter_write` 在确认弹窗前增加工厂模式必填校验(telnet 路径的通道必须配齐 `factory_bind_ip / factory_device_host`,缺一拒绝本次写入并给出说明);`SampleParameterWriteRequest` 在工厂里塞入新字段;`_sample_parameter_write_worker` 新增 `make_factory_session_swap(request)` 闭包:旧 session.close() → `prepare_network_for_sample(adapter_alias, factory_bind_ip, subnet_mask)` → `wait_for_bindable_ip(factory_bind_ip, 15s)` → `TelnetSession(factory_bind_ip, factory_device_host)`;任意一步失败返回 None 并 `emit_to_main` 明确写日志(切网段失败 / 重建 TelnetSession 失败 / 缺少字段);`executor.submit` 第 8 个位置参数 `make_factory_session_swap(req)` 接入。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/config_store.py`、`Cheating_machine_execution_tool/src/models/sample_parameter_models.py`、`Cheating_machine_execution_tool/src/services/sample_parameter_service.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_sample_parameter_service.py`、`Cheating_machine_execution_tool/tests/test_channel_config.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile line_check_assistant/app.py src/services/sample_parameter_service.py src/models/sample_parameter_models.py line_check_assistant/config_store.py`;`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过;`tests/test_sample_parameter_service.py` 新增 4 项:① `test_ppctl_clear_runs_after_factory_relogin_not_before` —— 断言 `ppctl clear` 只在工厂模式二次登录之后、15 项 `ppctl set` 之前出现一次,且位于 `ppctl set FACTORY_MODE=0` 之前;② `test_factory_session_swap_returns_none_abandons_before_second_login` —— 断言 swap 返回 None 时立即放弃本台,旧 session 上没有 `ppctl clear`;③ `test_factory_session_swap_exception_reports_failure` —— 断言 swap 抛异常时 pipeline 以"工厂模式网络切换异常"消息失败;④ `test_factory_session_swap_new_session_is_used_for_second_login` —— 断言 swap 返回新 session 时,`ppctl clear` 与 15 项 set 走新 session,finally 清理 (`FACTORY_MODE=0` + `firstboot -yr`) 也走新 session,旧 session 被 close;`tests/test_channel_config.py` 新增 3 项:① `test_load_includes_factory_bind_ip_and_device_host`;② `test_load_defaults_factory_fields_to_empty_when_missing`;③ `test_save_round_trip_preserves_factory_fields`。完整 `python -m unittest discover -s tests -v` 共 226 项全过(原 219 + 新增 7)。
- 后续待办：用户真实样机验证 —— 主执行日志期待出现
  ```
  VLAN114 写参前置：UBUS 启用 telnet 中 (192.168.1.114)
  VLAN114 UBUS: 已发起 UBUS 启用 telnet 流程
  …
  VLAN114 TX ppctl set FACTORY_MODE=1
  VLAN114 TX firstboot -yr
  VLAN114 写参：已触发进入工厂模式重启,等待 100 秒。
  …（约 100 秒后）…
  VLAN114 工厂模式网段切换:准备把 vlan114 设为 192.168.29.114 ……
  …
  VLAN114 UBUS 启用 telnet added_iface/already_present: …
  VLAN114 工厂模式重建 TelnetSession 成功(192.168.29.114 → 192.168.29.1)。
  VLAN114 写参：工厂模式网络切换完成,继续工厂模式二次登录。
  VLAN114 TX ppctl clear
  VLAN114 TX ppctl set SERIAL_NUMBER=…
  …15 项 set/get…
  VLAN114 写参完成,15 项均已读回校验。
  VLAN114 TX ppctl set FACTORY_MODE=0
  VLAN114 TX firstboot -yr
  VLAN114 写参：已下发退出工厂模式与重启命令。
  ```
  提示：测试结果仍「待真实样机验收」,修完后还需 2/4/8 台并行验收才能在 `ACCEPTANCE_BASELINE.md` §2.7 与 `PROJECT_STATUS.md` 把"已实现未验收"升级到"已确认验收"。`ChannelConfig` 新增 `factory_bind_ip / factory_device_host` 后,主程序表格里这些列现在是空白(空字符串视为未配置);现场需要按 VLAN 补齐。若 `prepare_network_for_sample` 失败(log 出现"工厂模式网段切换失败"),按提示核对对应 VLAN 的 adapter_alias 是否存在、是否能启用并设静态 IP;若 NIC 切换后 15s 仍未可绑,核对 Windows 注册网卡 IP 的延迟或现场状态。

## 2026-07-15 - 写样机参数 telnet 路径 sleep_fn=None 导致 100 秒等待立即抛 'NoneType' object is not callable

- 类型：BUG 修复 / 测试
- 背景：用户接着上轮修复继续真机验证 VLAN114 写参,UBUS 启用 telnet 成功后，主执行日志依次出现
  ```
  00:34:29 VLAN114 TX ppctl clear
  00:34:29 VLAN114 TX ppctl set FACTORY_MODE=1
  00:34:29 VLAN114 TX firstboot -yr
  00:34:29 VLAN114 写参：已触发进入工厂模式重启,等待 100 秒。
  00:34:29 VLAN114 TX ppctl set FACTORY_MODE=0
  00:34:29 VLAN114 TX firstboot -yr
  00:34:29 VLAN114 写参：已下发退出工厂模式与重启命令。
  ```
  最后却弹窗 `VLAN114 写参异常：'NoneType' object is not callable`。症状是「等待 100 秒。」刚打印就立刻同秒覆写三条最终清理命令。根因:`line_check_assistant/app.py` 的 `_sample_parameter_write_worker` 提交 telnet 路径执行时把 `sleep_fn=None` 作为第 6 个位置参数传给 `run_single_sample_parameter_write`,而 `_wait_cancellable(FACTORY_REBOOT_WAIT_SECONDS, cancel, sleep_fn)` 内部循环第一轮直接调用 `sleep_fn(1.0)`,`None(1.0)` 立即抛 `TypeError`,被外层 `except Exception` 接住返回失败结果;`finally` 看到 `entered_factory=True` 立刻连续下发 `ppctl set FACTORY_MODE=0` + `firstboot -yr` + 「已下发退出工厂模式与重启命令。」 这就是同秒出现三条的原因。
- 完成内容：`_sample_parameter_write_worker` 内部按样式加 `import time`;telnet 路径 executor.submit 调用第 6 个位置参数从 `None` 改成 `time.sleep`,与串口路径(走默认 `time.sleep`)对齐。其余流程、cancel 语义、15 项 set/get 重试、`FACTORY_USERNAME / FACTORY_PASSWORD` 与 100 秒工厂模式等待都不变。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_regression_sleep_fn.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile line_check_assistant/app.py src/services/sample_parameter_service.py src/core/ubus_enable_telnet.py`;`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过;新增 `tests/test_regression_sleep_fn.py` 3 项固化契约:① `test_sleep_fn_none_raises_none_type_not_callable` —— 用 `assertRaisesRegex(TypeError, "NoneType")` 锁死"`sleep_fn=None` 必须立即抛错"的契约,防止以后 caller 误传 `None` 让工厂模式清理走 finally 同一毫秒；② `test_sleep_fn_callable_runs_through_and_returns_true` —— 真 sleep_fn 在 cancel 未触发时跑完返回 True;③ `test_sleep_fn_callable_returns_false_on_cancel` —— cancel 已 set 时返回 False 且不调用 sleep_fn;完整 `python -m unittest discover -s tests -v` 共 219 项全过(原 199 + 新增 20)。
- 后续待办：用户真实样机再跑 VLAN114 写参,主执行日志期待出现
  ```
  VLAN114 写参前置：UBUS 启用 telnet 中 (192.168.1.114)
  VLAN114 UBUS: 已发起 UBUS 启用 telnet 流程
  …
  VLAN114 TX ppctl set FACTORY_MODE=1
  VLAN114 TX firstboot -yr
  VLAN114 写参：已触发进入工厂模式重启,等待 100 秒。
  …等待约 100 秒后…
  VLAN114 写参：触发首次登录（root / ******）/ 工厂模式二次登录（root / ******）
  VLAN114 TX ppctl set <15 项参数>=…
  VLAN114 TX ppctl get <15 项参数>
  …
  VLAN114 写参完成,15 项均已读回校验。
  VLAN114 TX ppctl set FACTORY_MODE=0
  VLAN114 TX firstboot -yr
  VLAN114 写参：已下发退出工厂模式与重启命令。
  ```
  若 100 秒等待结束后出现 "工厂模式二次登录失败",需按现场样机的工厂模式用户名/密码核对 `src/services/sample_parameter_service.py:25` 的 `FACTORY_USERNAME = "root"` 与 `FACTORY_PASSWORD = "t*hEQ#BHu7z%3n"`;若等待期间 `cancel.is_set()` 提前返回,主程序会在「已触发进入工厂模式重启,等待 100 秒。」后立即进入 finally 清理(符合预期逻辑,但可能被肉眼误判为清理太快)。

## 2026-07-15 - 写样机参数 UBUS 启用 telnet 总开关 set 必须用对象路径而非参数路径

- 类型：BUG 修复 / 测试
- 背景：用户接着上一轮修复继续验证 VLAN115 写参,主执行日志抛出
  ```
  VLAN115 UBUS: 获取访问规则总开关失败:UBUS 设置访问控制总开关失败,响应 [0, {'results': [{'path': 'Device.Firewall.X_SDMC_Security.AccessCtrl.EnableEnable', 'fault': 9005, 'fault_msg': 'Invalid parameter name'}]}]
  ```
  关键线索是 BBFDM 响应里 path 字段被拼成了 `...AccessCtrl.EnableEnable` —— 多出一个 `Enable`。原版 `SdmcUbusLibEnableTelnet._set_SecurityAccessCtrl_enable` 用的是对象路径 `f"Device.Firewall.{VENDOR_PREFIX}Security.AccessCtrl."` (末尾带点),并传 `obj_path={"Enable":"1"}`,BBFDM 会把 `obj_path` 的键当作对象下的参数;我代码误用参数路径 `ACCESS_CTRL_ENABLE_PATH` (`...AccessCtrl.Enable`) + 同一个 `obj_path={"Enable":"1"}`,BBFDM 视为在已经到参数的路径上继续追加,把两段 `Enable` 直接串联,产生 fault 9005 `Invalid parameter name`。
- 完成内容:`src/core/ubus_enable_telnet.py` 新增模块常量 `ACCESS_CTRL_ENABLE_OBJECT_PATH = "...AccessCtrl."`,仅用在 SET 总开关那一处 (`bbfdm_set` 的 path)。GET 总开关仍保留 `ACCESS_CTRL_ENABLE_PATH = "...AccessCtrl.Enable"`,因为 GET 接收"参数路径"形式合法;同时 `_bbfdm_all_results_one` 检查 `data != "1"`,遇到 fault 9005 这种 `data='Invalid parameter name'` 的响应会判定失败并抛 `UbusError`,刚好与上一轮校验修复串起来。其余路径(规则 set、add iface、add lan 回退)沿用上轮的修改不动,继续走 `data == "1"` 校验。
- 修改文件:`Cheating_machine_execution_tool/src/core/ubus_enable_telnet.py`、`Cheating_machine_execution_tool/tests/test_ubus_enable_telnet.py`、`DEVELOPMENT_LOG.md`。
- 验证方法:`python -m py_compile src/core/ubus_enable_telnet.py line_check_assistant/app.py src/core/ubus_http_client.py`;`python -m unittest discover -s tests -v`。
- 验证结果:`py_compile` 通过;`tests/test_ubus_enable_telnet.py` 新增 2 项 —— ① `test_set_total_enable_uses_object_path_not_parameter_path`:直接抓取 `bbfdm_set` 路径调用,断言总开关 SET 路径严格等于 `ACCESS_CTRL_ENABLE_OBJECT_PATH` 且 obj_path 等于 `{"Enable":"1"}`,确保本回归不会再次出现;② `test_set_total_enable_fault_9005_with_parameter_path_raises`:模拟 BBFDM 返回 `{'path': '...EnableEnable', 'fault': 9005, 'fault_msg': 'Invalid parameter name'}`,断言 `enable_telnet_via_ubus` 抛 `UbusError` 含"总开关失败";`tests/test_ubus_enable_telnet.py` 共 17 项全过;完整 `python -m unittest discover -s tests -v` 共 216 项全过(原 199 + 17)。
- 后续待办:用户真实样机验证 —— 主执行日志期待出现
  ```
  VLAN115 写参前置:UBUS 启用 telnet 中 (192.168.1.115)
  VLAN115 UBUS: 已发起 UBUS 启用 telnet 流程
  VLAN115 UBUS: AccessCtrl 总开关开启                (若原先 Enable != "1")
  VLAN115 UBUS: <already_present / added_iface / added_lan_fallback / reused>
  VLAN115 UBUS 启用 telnet <action>: <message>
  STATE Telnet 已连接
  VLAN115 写参:使用 Telnet 会话(绑定源 IP 192.168.1.115)
  …
  ```
  若仍 timed out,主程序会抛出"总开关失败 / 开启 LAN-telnet 规则失败 / 添加 telnet 规则 (Device.IP.Interface.1 / lan) 失败" 的明确 UbusError;按消息判断是设备未就绪、BBFDM 拒绝还是 telnetd 没起;若是 telnetd 守护进程没起则需要新增 UCI / `system.exec` 等路线,与本次 BGF 修复独立。

## 2026-07-15 - 写样机参数 UBUS 启用 telnet 校验 BBFDM 响应 data + 防火墙 reload 缓冲

- 类型：BUG 修复 / 测试
- 背景：用户在 VLAN115 上跑批量写样机参数，前一次修复（TCP 连接挪到 UBUS 之后）后仍报 `Telnet 连接失败 192.168.1.1:23 ... timed out`。复查 `Cheating_machine_execution_tool/SdmcUbusLib/libs/Security_module_api/enable_telnet.py`：该库对外只暴露 `SdmcUbusLibEnableTelnet.Enable_telnet()` 和 `SdmcSecurityLib.Ubus_telnet_enable()`，两者本质都是 BBFDM `bbf.shell` 下 `Device.Firewall.X_SDMC_Security.AccessCtrl.{Enable,Rule}` 路径上的 GET/SET/ADD 操作，并不直接启停 `telnetd` 守护进程。对照原版后发现三处实际差异：① SdmcUbusLib `_set_SecurityAccessCtrl_enable` / `_add_SecurityAccessCtrlRule` 在 JSON-RPC `error_code=0` 之外还会校验 `results[*].data == "1"`，本地实现在这两处缺失该校验；② SdmcUbusLib `Enable_telnet` 内含 `time.sleep(2)` 缓冲；本地实现因为 `_sample_parameter_write_worker` 传 `sleep_after_seconds=0.0`，防火墙变更后几乎没有等待。这两条都让 BBFDM 即使"看似成功"也未必真把 telnet 端口放开。
- 完成内容：在 `src/core/ubus_enable_telnet.py` 新增模块级 helper `_bbfdm_all_results_one(response) -> bool`，对齐 SdmcUbusLib 同款 `data == "1"` 校验；`enable_telnet_via_ubus` 内部：总开关 `bbfdm_set`、已存在规则 `bbfdm_set Enable=1`、`bbfdm_add Device.IP.Interface.1`、`bbfdm_add lan` 回退四处全部要求 `results[*].data == "1"`，否则 `raise UbusError`（与 `except UbusError: lan 回退` 这一既有 fallback 兼容）；新增常量 `ENABLE_TELNET_FINAL_SLEEP_SECONDS = 1.0`，在三个成功分支末尾固定 `sleep_fn(1.0)`，与 `sleep_after_seconds` 叠加，确保即便调用方传 0.0 也给防火墙 reload 留 1 秒。本地并未新增启动 `telnetd` 守护进程的入口，与 SdmcUbusLib 保持完全一致；若该设备未启动 telnetd，单靠 UBUS 防火墙规则不会让 23 端口 listening，需后续单独处理。
- 修改文件：`Cheating_machine_execution_tool/src/core/ubus_enable_telnet.py`、`Cheating_machine_execution_tool/tests/test_ubus_enable_telnet.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile src/core/ubus_enable_telnet.py line_check_assistant/app.py src/core/ubus_http_client.py`；`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过；新增 `tests/test_ubus_enable_telnet.py` 包含 6 项 `_bbfdm_all_results_one` 行为断言（data='1' / data='0' / 缺 results / 负载非 dict / 顶层非 list）+ 9 项 `enable_telnet_via_ubus` 端到端断言（already_present 不调 set/add、reused、added_iface、set_total data=0 抛错、set 已有规则 data=0 抛错、add_iface data=0 走 lan 回退、add 抛 UbusError 时 lan 回退、set_total + add_iface 日志顺序、sleep_after_seconds=0 仍触发 ENABLE_TELNET_FINAL_SLEEP_SECONDS）；完整 `python -m unittest discover -s tests -v` 共 214 项全过（原 199 + 新增 15）。
- 后续待办：用户真实样机再次验证：①日志依次出现「写参前置：UBUS 启用 telnet 中 → UBUS 总开关/规则 enable 三段消息 → UBUS 启用 telnet <action>: <message> → STATE Telnet 已连接 → 首次登录成功 → ...」；②若仍 timed out，主程序将抛出明确 UbusError `总开关失败` / `开启 LAN-telnet 规则失败` / `添加 telnet 规则 (Device.IP.Interface.1 / lan) 失败`，按消息可判断是 BBFDM 拒绝、设备未就绪还是该设备本就没起 telnetd；若是后者再单独立项处理。

## 2026-07-15 - 写样机参数 TCP 连接挪到 UBUS 启用 telnet 之后

- 类型：BUG 修复
- 背景：用户实际跑批量写样机参数（VLAN115，源 IP `192.168.1.115`）失败，弹窗 `VLAN115 telnet 写参启动失败：Telnet 连接失败 192.168.1.1:23 源 IP 192.168.1.115: timed out`。`make_telnet_factory` 当前顺序为先 `TelnetSession(...)` 同步建 TCP 连接、后 `enable_telnet_via_ubus(...)` 打开样机防火墙访问控制规则；但 OpenWRT 样机默认禁用 LAN-telnet，访问规则不开就没有进程监听 23 端口，SYN 不会得到响应，15 秒后 `socket.timeout`。这与函数顶部注释「端到端 telnet 写参:UBUS 启用 telnet → TelnetSession(未登录)」相反。
- 完成内容：把 `make_telnet_factory` 内部语句顺序调整为「先 `enable_telnet_via_ubus`（含总开关 get/set、规则遍历、add 规则、add lan 回退四段，仍走 `sleep_after_seconds=0.0`）→ 后 `TelnetSession(...)` 同步连」。UBUS 失败时不再需要回头关闭未创建的 Telnet 连接，清理分支简化。其余传输流程、`known_secrets`、`log_path`、`UbusHttpClient.close()` 等不变；源 IP `source_address=(bind_ip, 0)` 锁源、`enable_telnet_via_ubus` 三段日志、`ACCEPTANCE_BASELINE.md` §2.7 注释等均保持原状。修复后关键阶段日志自然输出：`写参前置：UBUS 启用 telnet 中 → UBUS 三段消息 → UBUS 启用 telnet <action>: <message> → STATE Telnet 已连接 → 首次登录 → ppctl clear → …`。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile Cheating_machine_execution_tool\line_check_assistant\app.py`；`python -m unittest discover -s Cheating_machine_execution_tool\tests -v`。
- 验证结果：`python -m py_compile` 通过；完整 `python -m unittest discover -s Cheating_machine_execution_tool\tests -v` 共 199 项通过（与 `ACCEPTANCE_BASELINE.md` §0 基线一致，未新增/调整任何测试）。
- 后续待办：用户真实样机验收：先以 VLAN115 单台验证日志依次出现「写参前置：UBUS 启用 telnet 中 → UBUS 总开关/规则 enable 三段消息 → UBUS 启用 telnet added_iface/already_present: … → STATE Telnet 已连接 → 首次登录成功 → ppctl clear → 工厂模式 → 15 项 set/get 读回 → 退出工厂模式」；通过后扩展到 2/4/8 台独立 VLAN 并行，状态标签由「已实现未验收」升级为「已确认验收」再同步 `ACCEPTANCE_BASELINE.md` §2.7 与 `PROJECT_STATUS.md` 表格。

## 记录规则

- 每次完成代码、配置、文档或流程变更后，都在本文件顶部追加一条记录。
- 记录内容应尽量短，但要能说明改动目的、影响范围和验证结果。
- 如果改动会影响项目当前状态或后续入口，同步更新 `PROJECT_STATUS.md`。
- 如果新增或调整用户可见功能，同步更新对应 `README.md`。
- 不记录 `build`、`dist`、`logs`、`.venv` 目录中的生成内容。

## 记录模板

```markdown
## YYYY-MM-DD - 简短标题

- 类型：功能 / 优化 / 修改 / BUG 修复 / 文档 / 构建 / 测试
- 背景：
- 完成内容：
- 修改文件：
- 验证方法：
- 验证结果：
- 后续待办：
```

## 2026-07-15 - 串口终端命令输入框支持 Enter 发送

- 类型：优化 / 测试 / 文档
- 背景：操作员反馈“串口日志记录”窗口的命令输入框按 Enter 不发送，每次都要手动点「发送」按钮，与常见串口终端习惯不符。
- 完成内容：在每个 VLAN Tab 的命令输入框（`ttk.Entry`）上绑定 `<Return>` 事件，新增 `_on_command_return(vlan)` 内部方法直接复用现有 `send(vlan)` 入口并返回 `"break"` 阻断 Tk 默认 Enter 行为；输入框非空时发送文本并清空（等价「发送」按钮），空字符串时发送纯回车（等价「回车」按钮）。自动升级占用、危险命令 `reboot`/`reset`/`firstboot`/`tftp`/`upgrade` 二次确认等现有 `send()` 分支保持不变。
- 修改文件：`Cheating_machine_execution_tool/src/ui/serial_terminal.py`、`Cheating_machine_execution_tool/tests/test_serial_terminal.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile src/ui/serial_terminal.py`；`python -m unittest discover -s tests -p test_serial_terminal.py -v`；`python -m unittest discover -s tests -v`。
- 验证结果：`python -m py_compile` 通过；串口终端专项 8 项通过（原 6 项 + 新增 2 项）；完整 `python -m unittest discover -s tests -v` 共 184 项通过（原 182 项 + 新增 2 项）。
- 后续待办：用户真实桌面环境在 vlan137/vlan138 等终端确认按 Enter 等价于「发送」按钮、空输入时等价于「回车」按钮，并确认升级中锁定提示和危险命令二次确认仍生效。

## 2026-07-15 - 写样机参数传输层由串口切换为 Telnet（按 VLAN 网卡 IP 锁源）

- 类型：功能 / 安全优化 / 重构 / 测试 / 文档
- 背景：光猫/路由器测试环境普遍配备多张同网段 VLAN 网卡，串口写参会因 PC 自动选网卡导致命中错误样机。
- 完成内容：
  - 新增 `src/core/parameter_session.py` 的 `Protocol ParameterSession`，把 `run_single_sample_parameter_write` 抽出 `run_parameter_write_pipeline` helper，service 层不再 import `PySerialSession`；既有 4 项串口路径单测保持全绿。
  - 抽出 `src/core/bind_socket.py`：`ip_is_bindable_locally` / `wait_for_bindable_ip`；TFTP strict server 改转发到该模块以保持兼容（保留 `tftp_transport._ip_is_bindable_locally / wait_for_bindable_ip` 旧名以免破坏测试 patch）。
  - 新增 `src/core/telnet_transport.py`：`TelnetSession` 在 `socket.create_connection(..., source_address=(bind_ip, 0))` 上提供与 `PySerialSession` 同形接口（cursor / write / send_line / wait_for_any / wait_for_all / peek_since）；源 IP 不可绑时强报错、不回退 `0.0.0.0`。
  - 新增 `src/core/ubus_http_client.py`：自写 JSON-RPC 2.0 客户端，不依赖 `SdmcUbusLib`（其静态字段多线程会互相覆盖 session）；通过 `http.client.HTTPConnection(..., source_address=(bind_ip, 0))` 按 VLAN 网卡锁定出口；当前支持 `login / bbfdm.get / bbfdm.set / bbfdm.add / bbfdm.unauthenticated_operate`。
  - 新增 `src/core/ubus_enable_telnet.py`：复刻 `SdmcUbusLibEnableTelnet.Enable_telnet` 的访问控制规则协议，按 `get/set/add/SourceInterface=lan 回退` 三段处理；返回 `EnableTelnetResult(action, ok, message)`。
  - `SampleParameterWriteRequest` 增加 `bind_ip / device_host / ubus_port` 字段（默认空 / 80，向后兼容）。
  - `line_check_assistant/app.py` 的 `_start_sample_parameter_write` 把 `ChannelConfig.network_card_ip / device_manage_ip` 透传到 request；`_sample_parameter_write_worker` 中按 VLAN 一台样机走 UBUS 启用 telnet → `TelnetSession` → service 流程；其余串口路径保留作 transport 回退。
- 修改文件：`Cheating_machine_execution_tool/src/core/parameter_session.py`（新）、`src/core/bind_socket.py`（新）、`src/core/telnet_transport.py`（新）、`src/core/ubus_http_client.py`（新）、`src/core/ubus_enable_telnet.py`（新）、`tests/test_telnet_transport.py`（新）、`tests/test_ubus_http_client.py`（新）、`src/core/tftp_transport.py`（转发到 bind_socket）、`src/services/sample_parameter_service.py`（加 `ParameterSession` 依赖）、`src/models/sample_parameter_models.py`（新增字段）、`line_check_assistant/app.py`（组装 telnet 工厂、`_channel_for_vlan` 等 helper）、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile` 各新模块与 `app.py`；`python -m unittest discover -s tests -v`。
- 验证结果：`py_compile` 通过；完整 `python -m unittest discover -s tests -v` 共 199 项通过（原 184 + telnet 6 + ubus 9）。
- 后续待办：用户先以 2 台独立 VLAN / COM 样机验收 UBUS 启用 telnet → Telnet 写参 → 工厂模式 → 15 项 set/get 读回校验；其次扩展至 4 / 8 台并行；真实样机成功后追加一条“真实样机验收通过”记录。

## 2026-07-15 - 串口日志记录-新增回车发送功能验收通过

- 类型：真实样机验收 / 状态更新
- 背景：2026-07-15 接入的命令输入框 Enter 发送最初仅有单元测试通过；用户已在线下样机完成端到端验证。
- 完成内容：用户确认“串口日志记录-新增回车发送功能”真实样机验收通过；该能力从 `ACCEPTANCE_BASELINE.md` 第 4 节的“已实现但未确认验收/待确认”收敛为“已确认验收”，同步把 `PROJECT_STATUS.md` 对应行（内置多 VLAN 串口终端）追加“含回车发送”说明。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`。
- 验证方法：以真实样机在“串口日志记录”窗口的命令输入框中：①输入文本后按 Enter，确认等价于「发送」按钮且输入框被清空；②输入框为空时按 Enter，确认等价于「回车」按钮；③自动升级占用对应 Tab 时按 Enter，确认弹出 “串口被占用” warning；④输入包含 `reboot` / `firstboot` 等关键字时按 Enter，确认继续弹出“确认危险命令”二次确认。
- 验证结果：通过。
- 后续待办：无。

## 2026-07-13 - 精简项目交接状态文档

- 类型：文档 / 交接
- 完成内容：按当前源码、测试与真实样机验收状态重写 `PROJECT_STATUS.md`，只保留项目进度、关键文件、已完成/待完成/限制、技术决策及运行测试入口。
- 修改文件：`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：核对当前源码入口、批量写参模块、运行命令与测试基线。
- 验证结果：状态文档当前测试基线为 182 项通过；未改动业务代码。
- 后续待办：按文档中的真实样机验收项继续验证。

## 2026-07-13 - 随机参数表生成窗口全部输入框改为明文显示

- 类型：界面优化
- 背景：操作员需要在生成批量参数表前核对 WiFi、超级用户和普通用户密码，原窗口中的密码类输入框以星号隐藏内容。
- 完成内容：生成批量样机参数表窗口的全部输入框统一明文显示；生成后的写参执行、串口终端和主执行日志仍继续脱敏敏感参数值。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 Python 编译检查；打开“生成批量样机参数表”，填写密码类字段后确认显示实际字符。
- 验证结果：待桌面界面确认。
- 后续待办：无。

## 2026-07-13 - 写样机参数首次登录密码改为明文显示

- 类型：界面优化
- 背景：操作员在“写样机参数”窗口需要核对首次登录密码，原输入框以星号隐藏内容，不便确认实际填写值。
- 完成内容：首次登录密码输入框改为明文显示；写参下发、串口终端和主执行日志中的敏感值脱敏逻辑不变。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 Python 编译检查；打开“写样机参数”，确认首次登录密码框显示实际字符。
- 验证结果：待桌面界面确认。
- 后续待办：无。

## 2026-07-13 - 接入批量写样机参数与随机参数表生成

- 类型：功能 / 安全优化 / 测试 / 文档
- 背景：主界面“写样机参数”仅为预留入口；同事的独立原型虽已具备单台写参流程，但未接入主程序的串口独占、并行调度、内置终端、主执行日志和参数表 VLAN 匹配。
- 完成内容：新增批量写参窗口，按参数表 `VLAN` 匹配已勾选通道并通过固定 `vlan{N} -> COM{N-100}` 映射并行执行（1–8 台、默认 2）；预检会阻止缺失/重复 VLAN、重复 COM、MAC 格式错误、必填值为空和引号/换行。写入前二次确认清晰展示 `ppctl clear`、工厂模式及两次 `firstboot -yr` 重启；每项 `ppctl set/get` 最多重试 3 次，单台失败不取消其它通道，取消时停止后续命令并尝试退出工厂模式。新增随机 `.xlsx` 参数表生成：按已勾选 VLAN 生成唯一的本地管理单播 MAC、SN、XPON SN、2.4G/5G SSID，其他参数由模板统一填写；导出后自动加载预检但不自动写设备。新表使用区分 2.4G/5G 密码和国家码的唯一表头，导入兼容旧表重复 `WiFi Password` / `Country code` 列。
- 修改文件：`line_check_assistant/app.py`、`src/models/sample_parameter_models.py`、`src/core/sample_parameter_table.py`、`src/services/sample_parameter_service.py`、相应 `__init__.py`、`requirements.txt`、`build_line_check_assistant.ps1`、`THIRD_PARTY_NOTICES.md`、新增专项测试、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行新增参数表/写参服务专项测试、源码编译检查与完整单元测试。
- 验证结果：专项 8 项通过；`python -m unittest discover -s tests -v` 完整回归 `Ran 182 tests ... OK`。
- 后续待办：先以 2 台独立 VLAN / COM 真实样机验证写参时序、读回校验、取消清理及密码脱敏，再扩展至 4 / 8 台并行。

## 2026-07-13 - 并行升级、ARP 重试与高频串口真实样机验收通过

- 类型：真实样机验收 / 项目状态
- 背景：`Tftp指令` 的 ARP 自动重试、两条升级链路的 2 / 4 / 8 台并行，以及高频串口日志下界面响应和程控电源 COM 批次长连接复用，均已完成代码与单元测试，尚需现场收口。
- 完成内容：用户确认上述三项真实样机验收均通过；`Tftp指令` 的 ARP 自动重试 3 次从“单元测试通过，待真实样机验收”更新为“已真实样机验收”，并移除相关现场待办。
- 修改文件：`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：真实样机验证 `Tftp指令` 的 ARP Retry count exceeded 自动重试；分别以 2 / 4 / 8 台独立 VLAN / COM 样机运行 `Tftp指令`、`Tftp Put` 并行升级；在高频串口日志下复测界面响应和程控电源 COM 长连接复用。
- 验证结果：均通过。
- 后续待办：保持现有已验收时序；仅在实验室功率闸容量紧张或出现新型号、异常现场日志时再评估扩展。

## 2026-07-13 - 样机升级配置行统一右边界

- 类型：界面优化 / 测试
- 背景：固件路径框扩展后，密码输入区及“目标样机”“执行状态”仍停在按钮左侧，右侧存在无意义空白，行间边界不一致。
- 完成内容：密码输入容器扩展到最右列，目标样机、执行状态和升级进度条同样跨到该列；固件选择按钮位置和业务逻辑不变。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 Python 编译检查；打开样机升级窗口，确认密码、目标样机、执行状态及进度条的右边缘与“选择固件...”按钮右边缘对齐。
- 验证结果：`python -m py_compile line_check_assistant\\app.py` 通过；`python -m unittest discover -s tests -p test_app.py -v` 共 60 项通过；界面真实显示待用户在 Windows 桌面环境确认。
- 后续待办：无。

## 2026-07-13 - 高频串口日志不再占满 Tk 主界面线程

- 类型：BUG 修复 / 性能优化 / 测试
- 背景：同时监控多个持续高频输出的 COM 口时，串口读取虽在后台线程，但终端在 Tk 主线程持续以 `after(0)` 渲染所有 VLAN 的 `Text` 控件并自动滚动；日志积压时窗口绘制与输入事件被挤占，Windows 可能显示“未响应”。
- 完成内容：终端渲染改为最小 33ms 节流；每轮只渲染当前可见 Tab，非活动 Tab 保留有限的最新缓冲，切换 Tab 时立即渲染；每个 Tab 的屏幕文本保留最近 5000 行，避免长期运行导致重绘成本和内存持续增加。屏幕缓冲最多 64KiB，超过时在终端提示已合并字符；原始串口日志仍由后台串口线程完整写入文件，不改串口协议、升级流程或端口映射。
- 修改文件：`Cheating_machine_execution_tool/src/ui/serial_terminal.py`、`Cheating_machine_execution_tool/tests/test_serial_terminal.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串口终端专项测试和完整单元测试；真实环境同时打开多路高频串口日志，确认主窗口、终端切换和按钮持续可操作。
- 验证结果：`python -m py_compile src\\ui\\serial_terminal.py` 通过；串口终端专项 6 项通过；`python -m unittest discover -s tests -v` 完整回归 `Ran 174 tests ... OK`。
- 后续待办：真实 3 路以上高频 WiFi 日志压测；如“打开全部”阶段仍卡顿，再把 COM 打开过程移到后台线程。

## 2026-07-13 - 样机升级固件路径框扩展至右侧可用宽度

- 类型：界面优化 / 测试
- 背景：样机升级窗口的“升级固件”路径框只占用输入区前两列，密码输入列到“选择固件...”按钮之间留有空白，长路径无法充分显示。
- 完成内容：路径框改为跨越前三个内容列，“选择固件...”按钮移到下一列并保持右对齐；窗口尺寸、固件选择和升级业务流程不变。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 Python 编译检查；打开样机升级窗口，选择长路径固件，确认路径框延伸至按钮左侧且按钮仍可点击。
- 验证结果：`python -m py_compile line_check_assistant\\app.py` 通过；`python -m unittest discover -s tests -p test_app.py -v` 共 60 项通过；界面真实显示待用户在 Windows 桌面环境确认。
- 后续待办：无。

## 2026-07-13 - 页面升级成功后执行 UBUS 恢复出厂

- 类型：功能 / 测试 / 文档
- 背景：样机升级窗口的“恢复出厂”原本只会保存为通用设置；页面升级链路未把该选项传入请求，也未调用公司 `SdmcUbusLib` 中的页面 UBUS 恢复出厂接口。
- 完成内容：`PageUpgradeRequest` 增加 `restore_factory`；页面升级确认框明确显示关闭，或“升级成功、设备重启并重新登录成功后将通过 UBUS 执行恢复出厂”。在 `X_SDMC_Upgrade()` 返回成功、设备重启并由当前独立 UBUS session 重新登录成功后，调用公司已定义的 `bbfdm.operate` + `Device.FactoryReset()` + `optional.proto=web`。恢复出厂关闭时明确记录跳过；开启时依次记录开始下发、`TX UBUS Device.FactoryReset()` 和命令已下发；调用异常会使该样机页面升级失败。为确保命令使用已验证的重新登录会话，重登检查不再提前 logout，而统一由流程 finally 收尾。新增项目规则：每个新增功能点必须向主程序执行日志输出关键阶段、实际命令下发、成功、跳过或失败提示。
- 修改文件：`AGENTS.md`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_page_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 `python -m py_compile line_check_assistant\\app.py line_check_assistant\\page_upgrade.py`；页面升级专项、主界面专项和完整单元测试。
- 验证结果：`python -m py_compile line_check_assistant\\app.py line_check_assistant\\page_upgrade.py` 通过；页面升级专项 9 项通过，主界面专项 60 项通过；`python -m unittest discover -s tests -v` 完整回归 `Ran 172 tests ... OK`。
- 后续待办：真实样机勾选页面升级“恢复出厂”，确认执行日志依次出现升级状态成功、重新登录成功、`TX UBUS Device.FactoryReset()` 和“UBUS 恢复出厂命令已下发”，并确认设备实际恢复出厂；关闭该选项时确认只出现“恢复出厂：关闭，跳过”。

## 2026-07-12 - Tftp指令 ARP 失败自动重试 3 次

- 类型：功能 / 优化 / 测试 / 文档
- 背景：现场样机偶发 `ARP Retry count exceeded; starting again` 后回到 `U-Boot>` 提示符；旧 `send_tftp_command_and_wait` 依赖 `wait_for_all(("done", "write"), TFTP_COMMAND_TIMEOUT_SECONDS=1800)`，本次失败会阻塞整整 30 分钟才向主程序报告超时，且无任何补救。
- 完成内容：模块顶部新增 `TFTP_COMMAND_MAX_RETRIES=3` / `TFTP_ARP_FAILURE_MARKER="arp retry count exceeded"` / `TFTP_RETRY_PROMPT_MARKER="u-boot>"` / `TFTP_COMMAND_POLL_SECONDS=1.0` / `TFTP_COMMAND_RETRY_DELAY_SECONDS=1.0`，并将单次超时从 1800 秒下调到 300 秒。`SerialUpgradeController` 新增 `_wait_for_tftp_completion_or_arp_failure` 按秒轮询：等待 `done + write` 完成标记，或识别 `ARP Retry count exceeded` + `u-boot>` 模式；不再阻塞到完整超时，避免已知快速失败场景浪费 5 分钟。`send_tftp_command_and_wait` 改为接收可选 `on_output` 回调，命中 ARP 失败模式时记录"自动重试 TFTP 命令：第 X/3 次发送..."和"检测到 ARP Retry count exceeded，剩余 N 次自动重试"并 sleep 1 秒后再次发送；最多 3 次尝试全部失败时返回 `TFTP 命令已重试 3 次仍未成功...`。`_run_tftp_command_with_power_supply` 调用处传入 `on_output=emit`，重试/成功提示直接进主程序执行日志。仅作用于 `Tftp指令`（样机主动拉固件）链路；`Tftp Put` 不走串口 tftp 命令，无 ARP 字样，不适用。`SerialUpgradeController.__init__` 新增 `monotonic_fn` 注入便于测试。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 `python -m py_compile` 关键模块；`python -m unittest discover -s tests -v` 全量；新增 6 项：首次成功不重试、ARP 失败后第 2 次成功、3 次全部 ARP 失败、无 ARP 标记不重试、ARP 标记但无 U-Boot> 不重试、`on_output=None` 也能跑通。
- 验证结果：`python -m py_compile src/services/serial_upgrade_service.py` 通过；`python -m unittest discover -s tests -v` 共 169 项通过（原 163 项 + 新增 6 项）。
- 后续待办：真实样机故意断 TFTPy Server 网络让 ARP 失败，确认主程序执行日志出现 "检测到 ARP Retry count exceeded, 剩余 X 次自动重试" 和 "自动重试 TFTP 命令：第 X/3 次发送..."；正常场景确认仍只发一条 tftp 即检测到 done + write 完成。

## 2026-07-12 - 并行 Tftp 指令高频日志不再阻塞 Tk 界面

- 类型：BUG 修复 / 测试 / 文档
- 背景：并行 `Tftp指令` 升级时，多路样机启动日志会高频进入串口终端；原终端每 80ms 逐条 Text 插入并滚动最多 200 次，主执行日志也会一次性清空队列，导致 Tk 主线程长期忙于渲染而显示“未响应”。
- 完成内容：串口终端按 VLAN 合并每轮事件，每 Tab 只插入/滚动一次，并设置 120 条或 10ms 的单轮预算；主执行日志改为每轮最多处理 120 条，积压时立即续跑。串口原始文件日志、升级并行调度、TFTPy 和程控电源时序不变。
- 修改文件：`Cheating_machine_execution_tool/src/ui/serial_terminal.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_serial_terminal.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串口终端、主界面和完整单元测试；真实两台并行 `Tftp指令` 样机验证 UI 响应。
- 验证结果：`python -m py_compile line_check_assistant/app.py src/ui/serial_terminal.py` 通过；串口终端专项 4 项、主界面专项 58 项通过；完整 `python -m unittest discover -s tests -v` 共 150 项通过。
- 后续待办：真实两台独立 VLAN 样机复测并行 `Tftp指令`，确认升级窗口和串口终端在高频启动日志下持续可响应。

## 2026-07-12 - 全包升级并行上限扩到 8 台 + 程控电源 COM 批次内复用

- 类型：功能 / 优化 / 测试 / 文档
- 背景：`Tftp指令` / `Tftp Put` 并行升级上限硬编码为 2 台，无法满足后续多 VLAN 真实样机需求；真实样机日志显示同一批次内程控电源 COM102 在每台样机上下电前后反复 open/close，扩到 8 台后浪费会放大 4 倍。
- 完成内容：`MAX_PARALLEL_UPGRADES = 8` 单一来源常量；`SampleUpgradeSettings` 新增 `parallel_count`（默认 2，存 ini，1–8 区间），Store 读写并加 `clamp_parallel_count` 防御非法值；UI 在执行方式 Combobox 右侧新增 `ttk.Spinbox`（1–8），串行时灰显；`_parallel_tftp_command_upgrade_worker` / `_parallel_tftp_put_upgrade_worker` 接收 `parallel_count` 并钳制后传入 `max_workers`，确认弹窗和状态文案跟随实际并行数。`UpgradePowerCycleCoordinator` 改为持有每条 COM 的长连接 `ProgrammablePowerSupply`，通过 `with UpgradePowerCycleCoordinator() as coordinator` 在两个并行 runner 收尾时统一 `close()`；serial 路径未动。`power_on_service.py` 未改接口，只新增一个供 coordinator 直接复用的入口（最终选择由 coordinator 直接调用 `supply.power_on_channels`）。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/Auto_power_on_off_tool/config/sample_upgrade_settings.ini`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行 `python -m py_compile` 关键模块；`python -m unittest discover -s tests -v` 全量；新加 `coordinator` supply 复用与 `close()` 幂等两项断言。
- 验证结果：编译通过；`python -m unittest discover -s tests -v` 共 163 项通过；旧 coordinator 串行化测试改为对 `supply_factory` mock，新增 supply 只 open 一次 / close 幂等 2 项断言。
- 后续待办：真实 2 台、4 台、8 台独立 VLAN / COM 样机分别跑一次 `Tftp指令` 和 `Tftp Put` 并行升级，确认日志中"已打开 / 已关闭程控电源串口"各仅出现一次且 TFTPy 上传无错包；如实验室功率闸容量紧张，再评估在 coordinator 内加错峰 `power_cycle_offset_seconds` 开关（默认 0）。

## 2026-07-12 - Tftp Put 多台串行全包升级真实样机验收通过

- 类型：真实样机验收 / 状态更新
- 背景：Tftp Put 已完成前置下电上电、`UserName` 后 boot 登录、TFTPy 推送和串口终端自动收尾改造，需要确认多台按串行顺序执行时的完整链路。
- 完成内容：用户已完成全包升级 `Tftp Put` 多台串行真实样机验收，结果通过。
- 修改文件：`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：真实样机多台串行升级。
- 验证结果：通过。
- 后续待办：`Tftp指令` 两台并行仍待真实两台独立 VLAN 样机验收。

## 2026-07-12 - 全包升级结束后关闭自动打开的串口终端

- 类型：BUG 修复 / 测试 / 文档
- 背景：全包升级完成后，升级会话已写入 `STATE 串口已关闭` 并释放 COM 口，但本次自动打开的“串口日志记录”窗口仍残留。
- 完成内容：串口终端记录自动升级批次；串行全包升级和并行 `Tftp指令` 均在批次完成并释放会话后延迟 100ms 请求终端收尾。仅升级自动打开的终端会关闭，手动打开的终端保持打开。
- 修改文件：`Cheating_machine_execution_tool/src/ui/serial_terminal.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_serial_terminal.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串口终端、主界面升级流程相关测试、完整单元测试和源码编译检查。
- 验证结果：`python -m py_compile line_check_assistant/app.py src/ui/serial_terminal.py` 通过；串口终端专项 3 项、主界面专项 57 项通过；完整 `python -m unittest discover -s tests -v` 共 148 项通过。
- 后续待办：真实样机验证 `STATE 串口已关闭` 后本次自动打开的串口终端窗口关闭，手动打开的终端不受影响。

## 2026-07-12 - 恢复出厂命令同步到主程序执行日志

- 类型：优化 / 测试 / 文档
- 背景：串口日志可见 `TX firstboot -y;reboot`，但主程序执行日志未体现已实际下发恢复出厂命令，操作员无法在主界面确认危险操作是否执行。
- 完成内容：恢复出厂命令写入串口成功后，向主程序执行日志输出 `TX firstboot -y;reboot`；未启用恢复出厂时不输出该日志。两种全包升级传输方式均复用此日志回调，传输时序不变。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串行升级专项测试、完整单元测试和源码编译检查。
- 验证结果：`python -m py_compile src/services/serial_upgrade_service.py` 通过；串行升级专项 22 项通过；完整 `python -m unittest discover -s tests -v` 共 147 项通过。
- 后续待办：真实样机勾选恢复出厂时确认主程序执行日志出现该 TX 行；未勾选时确认不出现。

## 2026-07-12 - Tftp Put boot 登录不再漏掉同批 ECNT 提示

- 类型：BUG 修复 / 测试 / 文档
- 背景：真实串口日志显示 boot 密码提交后已出现 `ECNT>`，但 Tftp Put 专用登录逻辑在写密码并等待 1 秒后才记录 shell 等待游标，导致 `ECNT>` 落在游标之前而误报“boot 登录后未检测到 shell 提示符”。
- 完成内容：把 Tftp Put 专用 boot 登录的 shell 等待游标提前到 boot 密码写入前；`ecnt>` 已是现有 shell 提示识别项，修复后可匹配同批 `ECNT>` 并继续 TFTPy 传输。未改动 `Tftp指令` 路径。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串行升级专项测试、完整单元测试和源码编译检查。
- 验证结果：`python -m py_compile src/services/serial_upgrade_service.py` 通过；串行升级专项 21 项通过；完整 `python -m unittest discover -s tests -v` 共 146 项通过。
- 后续待办：使用真实 Tftp Put 样机确认 `ECNT>` 后立即进入 TFTPy 传输阶段。

## 2026-07-12 - Tftp Put boot 登录不再漏掉同批 Password 提示

- 类型：BUG 修复 / 测试 / 文档
- 背景：真实串口日志已显示 `UserName: telecomadmin` 后紧接 `Password:`，但 Tftp Put 专用登录逻辑在写用户名并等待 0.3 秒后才记录等待游标，导致同批到达的 `Password:` 落在游标之前而被漏检。
- 完成内容：把 Tftp Put 专用 boot 登录的密码等待游标提前到用户名写入前，确保用户名回显期间或同批数据中的完整 `Password:` 仍可匹配；未改动 `Tftp指令` 路径。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串行升级专项测试、完整单元测试和源码编译检查。
- 验证结果：`python -m py_compile src/services/serial_upgrade_service.py` 通过；串行升级专项 20 项通过；完整 `python -m unittest discover -s tests -v` 共 145 项通过。
- 后续待办：使用真实 Tftp Put 样机确认 `UserName` 后同批 `Password:` 可被识别并继续发送 boot 密码。

## 2026-07-12 - Tftp Put 检测 UserName 后按 boot 凭据登录并保留 TFTPy 上传

- 类型：BUG 修复 / 测试 / 文档
- 背景：`Tftp Put` 前置下电 + 上电完成后，现场要求以串口 `UserName:` 作为 boot 登录起点，沿用同事 `serial_upgrade.py` 的 boot 凭据交互，而不再先登录最终系统并发送 `reboot`。
- 完成内容：新增仅由 `Tftp Put` 调用的「循环回车等待 `UserName:` → `telecomadmin / nE7jA%5m` 登录 boot」状态机；登录成功后继续复用主程序 `prepare_tftp_network()` 和 TFTPy Client 上传，不调用 Windows `tftp.exe`。保留传输后的 boot 重启检测、最终系统登录及恢复出厂；`Tftp指令` 未调整。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串行升级专项测试、完整单元测试和源码编译检查。
- 验证结果：`python -m py_compile src/services/serial_upgrade_service.py` 通过；串行升级专项 19 项通过；完整 `python -m unittest discover -s tests -v` 共 144 项通过。
- 后续待办：使用真实 `Tftp Put` 样机确认日志顺序为“串口已开启”→等待 1 秒→检测到 `UserName`→boot 登录→TFTPy 上传。

## 2026-07-11 - Tftp Put 开始前先对样机执行下电 + 上电

- 类型：功能 / 程控电源 / 重构 / 测试 / 文档
- 背景：现场反馈 `Tftp Put` 升级时样机经常不是干净的上电状态，需要主程序在开始原有 reboot → boot → TFTP 流程前，先对程控电源对应通道做一次下电 + 上电，确保样机从已知上电状态启动；该需求与现有 `Tftp指令` 链路的「断电再上电」语义一致。
- 完成内容：把 `serial_upgrade_service.py` 中 `_run_tftp_command_with_power_supply` 内联的 `power_on_current_channel` 抽出为模块级 helper `_power_cycle_current_channel()`，复用 `power_on_selected_channels`（串行）或 `UpgradePowerCycleCoordinator`（并行）；`Tftp Put` 分支在打开串口后立即调用该 helper 对 `request.power_serial_port / request.power_channel` 执行下电 + 上电（`wait_seconds=0`，由后续 `login_final_system` 的 900 秒首轮等待兜底样机启动），失败立即返回；`Tftp指令` 链路行为保持不变，仅复用同一 helper。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile` 编译；运行 `test_serial_upgrade_service.py` 及完整单元测试。
- 验证结果：编译通过；`test_serial_upgrade_service.py` 新增 1 项（`test_full_package_upgrade_tftp_put_propagates_power_cycle_failure`），重命名 / 调整 2 项（原 `skips_programmable_power_supply` / `does_not_invoke_power_supply_module` 已不能描述新行为）；完整 `python -m unittest discover -s tests` 共 143 项全部通过。
- 后续待办：真实样机验证 `Tftp Put` 在开始 reboot 之前程控电源下电 + 上电日志与上电时序，并确认主流程未受影响。

## 2026-07-11 - 页面升级前先把网卡设为样机同网段

- 类型：优化 / 重构 / 测试 / 文档
- 背景：现场 `vlan137/138/139` 页面升级前 PC 网卡已启用但 IP 仍为旧配置，与样机管理 IP（如 `192.168.29.1`）不在同一网段，导致 HTTP/HTTPS 登录 UBUS 前路由不通。
- 完成内容：在 `network_ops.py` 抽出 `prepare_network_for_sample()`，封装「启用网卡 → 设置静态 IP → 缓冲 2 秒」的统一流程，原 `run_line_check` 复用同一 helper；`PageUpgradeRequest` 新增 `subnet_mask` 字段（默认 `255.255.255.0`），`run_single_page_upgrade` 在启用网卡之后改用 `prepare_network_for_sample()`，把 PC 静态 IP 切到样机管理 IP 所在网段；`app.py` 把 `ChannelConfig.subnet_mask` 透传给 `PageUpgradeRequest`。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_page_upgrade.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile` 编译主程序、网络与页面升级模块；运行 `test_network_ops.py`、`test_page_upgrade.py`、`test_app.py` 及完整单元测试。
- 验证结果：编译通过；`test_network_ops.py` 新增 6 项（启用网卡 + 静态 IP、启用失败、设 IP 失败、缺 alias、缺 bind_ip、display name 兼容）；`test_page_upgrade.py` 新增/调整 4 项；`test_app.py` 新增 1 项；完整 `python -m unittest discover -s tests` 共 142 项全部通过。
- 后续待办：使用真实 `vlan137/138/139` 复测页面升级，确认 PC 网卡 IP 已切到样机管理 IP 所在网段，且 HTTP/HTTPS 登录一次成功。

## 2026-07-11 - Boot 登录按新提示符逐步提交凭据

- 类型：BUG 修复 / 测试 / 文档
- 背景：现场日志显示 `UserName:` 与 `Password:` 分段到达时，用户名后仍可能使用旧串口缓存中的密码提示符，导致账号密码提交错位。
- 完成内容：Boot 登录仅在完整用户名提示符后发送用户名；用户名回车后重新取串口游标，只接受新到达的完整密码提示符才发送密码；登录结果也从密码回车后的新游标开始等待。
- 修改文件：`src/services/serial_upgrade_service.py`、`tests/test_serial_upgrade_service.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译串行升级服务，运行串行升级及完整单元测试。
- 验证结果：串行升级专项 12 项通过；完整 `python -m unittest discover -s tests -v` 共 124 项通过；新增回归测试确认密码提示符的等待游标晚于用户名回车，不会命中用户名输入前的旧缓存。
- 后续待办：使用真实 `Tftp指令` 样机复测分段 `UserName:` / `Password:` 回显。

## 2026-07-11 - 串口终端目录写入失败改为明确提示

- 类型：BUG 修复 / 测试 / 文档
- 背景：默认 `D:\Serial_Log` 或本机串口终端状态文件不可写时，原逻辑会吞掉异常，操作员无法判断日志或窗口设置未保存。
- 完成内容：默认日志目录创建失败和终端状态文件写入失败均弹出明确错误信息，并提示可通过“浏览…”选择可写日志目录。
- 修改文件：`src/ui/serial_terminal.py`、`tests/test_serial_terminal.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行串口终端持久化测试和完整单元测试。
- 验证结果：`python -m py_compile` 通过；完整 `python -m unittest discover -s tests -v` 共 123 项通过；新增测试覆盖默认日志目录创建失败及终端状态文件保存失败时的错误弹窗。
- 后续待办：无。

## 2026-07-11 - 自动上/下电增加下电选择

- 类型：功能 / 测试 / 文档
- 背景：用户要求将“自动上电”扩展为“自动上/下电”，并在二级弹窗中用下拉框选择上电或下电，默认上电。
- 完成内容：工具栏入口改为“自动上/下电”；COM 选择弹窗新增默认“上电”的操作下拉框；下电仅向勾选通道按顺序发送关闭帧、相邻间隔 1 秒，不发送全断电帧。全包升级和 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 均未修改。
- 修改文件：`src/core/power_supply.py`、`src/services/power_on_service.py`、`src/services/__init__.py`、`line_check_assistant/app.py`、`tests/test_power_supply.py`、`tests/test_app.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译主程序和上下电服务；运行完整单元测试；核对旧工具源码哈希未变化。
- 验证结果：编译通过，完整 `python -m unittest discover -s tests -v` 共 111 项通过；单元测试验证下电仅发送所选通道关闭帧、相邻帧间隔 1 秒且不含全断电帧；`Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 哈希未变化。
- 后续待办：在真实程控电源上验收下电操作的关闭帧顺序和 1 秒间隔。

## 2026-07-11 - 取消自动上电后的启动等待

- 类型：优化 / 测试 / 文档
- 背景：用户要求最后一条自动上电开启帧发送后不再额外等待 10 秒。
- 完成内容：主程序自动上电的启动等待改为 0 秒；相邻开启帧的 1 秒间隔保持不变。全包升级及旧工具源码均未修改。
- 修改文件：`line_check_assistant/app.py`、`tests/test_app.py`、`tests/test_power_supply.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译主程序；运行完整单元测试；确认旧工具源码哈希未变化。
- 验证结果：编译通过，完整 `python -m unittest discover -s tests -v` 共 108 项通过；单元测试验证两条开启帧之间仅等待 1 秒、最后一条开启帧后无额外启动等待；`Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 哈希未变化。用户已在真实程控电源完成新自动上电流程验收，结果通过。
- 后续待办：无；全包升级的断电重启流程继续按独立路径验收。

## 2026-07-11 - 自动上电开启帧按通道间隔 1 秒

- 类型：BUG 修复 / 测试 / 文档
- 背景：现场日志显示通道 1-8 的开启帧在同一秒内连续发送；用户确认需要相邻开启指令间隔 1 秒。
- 完成内容：主程序“自动上电”的仅开启路径改为首个通道立即开启、后续每个通道开启前等待 1 秒；全部开启帧完成后再统一等待 10 秒。未改变断电策略、全包升级路径或 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py`。
- 修改文件：`src/core/power_supply.py`、`src/services/power_on_service.py`、`line_check_assistant/app.py`、`tests/test_power_supply.py`、`tests/test_app.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译主程序和上电服务；运行程控电源、主界面与串行升级单元测试；确认旧工具源码哈希未变化。
- 验证结果：待本次改动完成后填写。
- 后续待办：在真实程控电源上确认开启日志相邻时间约为 1 秒。

## 2026-07-11 - 自动上电改为一次性开启勾选通道

- 类型：优化 / 测试 / 文档
- 背景：用户要求主程序“自动上电”确认后一次性开启所有勾选通道，不再先完全断电或按通道逐个断电/上电；同时明确不得影响 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 业务逻辑。
- 完成内容：主程序新增仅开启通道的程控电源服务，连续发送勾选通道的开启帧且不插入关闭帧；自动上电统一等待 10 秒；全包升级原有断电重启路径及旧工具源码均未修改。
- 修改文件：`src/core/power_supply.py`、`src/services/power_on_service.py`、`src/services/__init__.py`、`line_check_assistant/app.py`、`tests/test_power_supply.py`、`tests/test_app.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译主程序和上电服务；运行程控电源、主界面及串行升级相关单元测试；比对旧工具源码未改动。
- 验证结果：`Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 与移动前 Git 版本哈希一致；编译通过，完整 `python -m unittest discover -s tests -v` 共 108 项通过；单元测试验证自动上电只写入全部勾选通道的开启帧，不含全断电或关闭帧，且全包升级仍走原有独立上电服务。
- 后续待办：使用真实程控电源确认多通道开启帧连续下发后，所有勾选通道可同时启动。

## 2026-07-11 - 统一主程序配置目录到旧工具源码目录

- 类型：重构 / 配置 / 文档 / 测试
- 背景：用户将 `Auto_power_on_off_tool` 移入 `Cheating_machine_execution_tool`，要求所有原先读写同级 `config` 的主程序逻辑统一改为读写 `Auto_power_on_off_tool/config`，并删除旧目录。
- 完成内容：新增统一配置目录解析；主界面通道、ONU 注册和样机升级状态均改写新目录；迁入现有通道配置和本机保存状态，保留旧工具已有的产品配置及原同级配置项；删除原同级 `config` 目录。
- 修改文件：`line_check_assistant/paths.py`、`line_check_assistant/app.py`、`tests/test_paths.py`、`.gitignore`、`Auto_power_on_off_tool/config`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译主程序与路径模块；运行路径和配置存储相关单元测试；确认旧目录不存在且主程序配置路径指向新目录。
- 验证结果：旧目录确认不存在；主程序导入后四个配置路径均指向新目录；迁入的通道配置可解析为 16 个通道、程控电源端口为 `COM105`；`python -m py_compile` 通过，完整 `python -m unittest discover -s tests -v` 共 106 项通过。
- 后续待办：真实设备流程继续以新目录中的 `network_card_ip.ini` 为唯一配置源。

## 2026-07-11 - 主程序内置程控电源直连，移除旧 GUI 上电依赖

- 类型：功能 / 重构 / 测试 / 文档
- 背景：自动上电和全包升级原先启动 `Auto_Power_On_Off_Tool.exe` 并通过 UI Automation 选择 COM、配置和 `Start ALL`，窗口控件状态会造成不稳定；用户提供旧工具源码，要求改为主程序直接控制程控电源。
- 完成内容：从旧源码提取 16 通道程控电源串口协议，新增无界面 `src/core/power_supply.py` 与上电服务；自动上电会二次确认“先关闭全部通道”，再按勾选的 `channel_x` 直接发送关闭/上电帧；全包升级从当前 `channel_x` 传递程控电源通道，写入上电帧后立即开始 boot 监听，重上电也走同一条直连路径；运行时主路径不再调用旧 EXE、PyQt 或 UI Automation。
- 修改文件：`Cheating_machine_execution_tool/src/core/power_supply.py`、`src/services/power_on_service.py`、`src/services/serial_upgrade_service.py`、`src/models/serial_models.py`、`src/core/__init__.py`、`src/services/__init__.py`、`line_check_assistant/app.py`、`tests/test_power_supply.py`、`tests/test_app.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：编译入口、主界面、直连核心和升级服务；导入主程序与上电服务；运行完整单元测试；检查运行时目录中不再存在旧 GUI 自动化调用。
- 验证结果：编译和导入通过；完整 `python -m unittest discover -s tests -v` 共 105 项通过；新增 5 项程控电源测试验证旧协议帧、全关后指定通道开关顺序、串口关闭、启动等待、非法通道不打开串口，以及全包升级首次上电和重上电均使用当前 `channel_x`。
- 后续待办：在真实程控电源上先验证 `COM` 口与 `19200 8N1` 参数、单通道断电/上电帧和通道映射；确认后再验收多通道自动上电及全包升级中的首次上电、重上电流程。

## 2026-07-11 - 修复主程序 VS Code 源码启动环境

- 类型：BUG 修复 / 配置 / 文档 / 测试
- 背景：用户在 VS Code 运行 `run_line_check_assistant.py` 时，专用 `.venv_serial_upgrade` 缺少主程序新增的 `tftpy`，启动期导入 `src.core.tftp_transport` 后报 `ModuleNotFoundError`；现有 F5 配置也只覆盖独立 `serial_upgrade.py`。
- 完成内容：为 VS Code 新增 `LineCheckAssistant` 调试入口，固定以 `Cheating_machine_execution_tool` 为工作目录；主程序依赖清单补充 `requests` 并在 `.venv_serial_upgrade` 安装 `tftpy==0.8.7`；README 补充首次安装依赖和 VS Code 运行步骤；项目状态同步主程序源码运行入口。
- 修改文件：`.vscode/launch.json`、`Cheating_machine_execution_tool/requirements.txt`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：使用 `.venv_serial_upgrade` 编译入口、主界面和 TFTP 模块；导入 `line_check_assistant.app`；执行 `pip check`；解析 `.vscode/launch.json`；运行 `test_tftp_transport.py`。
- 验证结果：编译通过；`LineCheckAssistant import OK`；`tftpy=0.8.7`；`No broken requirements found.`；`launch.json JSON OK`；`test_tftp_transport.py` 2 项通过。
- 后续待办：用户可在 VS Code 选择 `LineCheckAssistant` 后按 F5 完成界面与现场设备功能验证。

## 2026-07-10 - 主程序内置 pySerial 与 TFTPy 串行升级

- 类型：功能 / 重构 / 测试 / 文档
- 背景：全包升级原先依赖 SecureCRT、Tftpd64 和 Windows TFTP 客户端，串口状态机不可执行测试且多网卡源 IP 不可控。
- 完成内容：新增 `src/models`、`src/core`、`src/services`、`src/ui` 分层；pySerial 接管 VLAN→COM 的收发、状态 marker、终端显示与独占写锁；TFTPy Server 接管设备拉取并仅映射所选固件为 `tclinux_allinone`，TFTPy Client 接管 Put 并绑定当前通道源 IP；内置多通道终端替换占位窗口；保留两种 TFTP 语义、串行顺序、配置隔离、reset/登录/恢复出厂时序；移除旧 Python/VBS 自动化模块和旧实现测试。
- 修改文件：主界面、`src` 新模块、测试、依赖清单、第三方声明、构建脚本、README、PROJECT_STATUS。
- 验证方法：编译检查、完整单元测试、TFTPy 本机高端口上传/下载端到端测试。
- 验证结果：`python -m py_compile` 通过；完整 `python -m unittest discover -s tests -v` 100 项通过。
- 后续待办：在真实设备上分别验收两种传输、恢复出厂、多样机串行、端口占用、串口拔出、UDP 69 防火墙和多 `.1` 网卡源 IP。

## 2026-07-09 - 修复 Tftp Put 恢复出厂提交和 CRT 主窗口残留

- 类型：BUG 修复 / 优化 / 测试 / 文档
- 背景：用户验证 `Tftp Put` 模式在固件传输完成、重启并登录最终系统后，恢复出厂命令停留在 CRT 窗口中未真正下发；同时样机升级收尾只关闭了升级 Tab，SecureCRT 主窗口仍残留。
- 完成内容：恢复出厂逻辑改为发送 `firstboot -y;reboot` 后固定等待 1 秒再发送回车，不再等待命令回显；SecureCRT 升级脚本在关闭当前升级 Tab 后继续请求关闭 SecureCRT 主窗口，收尾日志同步说明 Tab 和主窗口都会由脚本请求关闭。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant/upgrade_cleanup.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/tests/test_tftpd_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、`test_securecrt_automation.py`、`test_tftpd_automation.py` 和完整单元测试。
- 验证结果：编译检查通过；`test_securecrt_automation.py` 16 项全部 OK；`test_tftpd_automation.py` 3 项全部 OK；完整 `python -m unittest discover -s tests -v` 123 项全部 OK。
- 后续待办：用真实 `Tftp Put + 恢复出厂` 样机升级复测，确认串口日志中命令 1 秒后下发并触发恢复出厂重启，且 SecureCRT 主窗口随升级结束关闭。

## 2026-07-08 - 恢复出厂命令发送后延迟关闭 SecureCRT Tab

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户验证勾选“恢复出厂”时，最终系统只成功登录，随后 SecureCRT 升级窗口很快关闭，`firstboot -y;reboot` 可能未完整下发。
- 完成内容：将恢复出厂发送逻辑从 `factoryResetCommand & vbCr` 后立即完成，改为先发送命令文本，等待命令回显或最多 5 秒，随后发送回车并记录 `RESTORE_FACTORY_SENT`，再额外等待 8 秒才写入 `DONE` 并关闭当前升级 Tab；回显未出现时记录 `RESTORE_FACTORY_ECHO_MISSED` 但继续发送回车，避免现场回显差异导致流程卡死。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/securecrt_automation.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、`test_securecrt_automation.py` 和完整单元测试。
- 验证结果：编译检查通过；`test_securecrt_automation.py` 16 项全部 OK；完整单元测试 123 项全部 OK。
- 后续待办：真实样机复测勾选“恢复出厂”时确认串口日志出现 `firstboot -y;reboot` 并触发重启。

## 2026-07-08 - SecureCRT 升级脚本完成后自关闭当前 Tab

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户验证多台样机串行 `Tftp Put` 升级可成功，但收尾日志显示未检测到本次新增 SecureCRT 窗口 PID，导致本轮升级打开的 CRT 窗口没有关闭。
- 完成内容：保留 Python 按本次新增 PID 兜底关闭的安全边界，避免误关用户手动 CRT；同时在 SecureCRT 升级脚本写入 `DONE` 后主动请求关闭当前脚本创建的升级 Tab，若关闭 API 不可用则写入 `SECURECRT_TAB_CLOSE_SKIPPED` 状态，避免因为窗口 PID 识别不到而无法关闭本轮升级 Tab；收尾日志改为说明脚本会自行请求关闭当前升级 Tab。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant/upgrade_cleanup.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/tests/test_tftpd_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、`test_securecrt_automation.py`、`test_tftpd_automation.py` 和完整单元测试。
- 验证结果：编译检查通过；`test_securecrt_automation.py` 16 项全部 OK；`test_tftpd_automation.py` 3 项全部 OK；完整单元测试 123 项全部 OK。
- 后续待办：用真实多台 `Tftp Put` 串行升级确认每台升级完成后当前 CRT Tab 能自动关闭。

## 2026-07-08 - 修复恢复出厂选项显示与确认状态

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户反馈 `Tftp Put` 单台升级成功后，未勾选“恢复出厂”却实际执行了恢复出厂。
- 完成内容：定位为样机升级窗口初始化时“恢复出厂”文字固定显示为未勾选，但底层布尔值会从 `config/sample_upgrade_settings.ini` 读取上次保存状态，可能出现界面显示未勾选而实际请求为开启；改为初始化文本直接按真实保存值生成，并在开始串行升级确认框中明确显示“恢复出厂：开启/关闭”。同时确认 SecureCRT 脚本仅在 manifest 字段为 `"1"` 时发送 `firstboot -y;reboot`。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、`test_app.py`、`test_securecrt_automation.py` 和完整单元测试。
- 验证结果：编译检查通过；`test_app.py` 55 项全部 OK；`test_securecrt_automation.py` 16 项全部 OK；完整单元测试 123 项全部 OK。
- 后续待办：用真实样机再次确认未勾选恢复出厂时不会发送 `firstboot -y;reboot`。

## 2026-07-08 - 收尾只关闭本次启动的 SecureCRT PID

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户反馈升级收尾日志中强制关闭了多个 SecureCRT 进程，其中部分是用户手动打开的其它 CRT 串口窗口。
- 完成内容：定位为 `upgrade_cleanup.py` 按进程名关闭所有 `SecureCRT`，清理范围过宽；改为启动 SecureCRT 前后对比新增窗口句柄并反查真实 PID，单台升级把新增 PID 回传给串行 worker，收尾只按这些精确 PID 关闭本次启动的 SecureCRT，同时继续按精确路径关闭项目目录下的 `tftpd64.exe`；未识别到新增 PID 时保留现有 CRT 会话。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/upgrade_cleanup.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_tftpd_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、SecureCRT PID 获取测试、单台升级 PID 回传测试、串行 worker 收尾传参测试、Tftpd/收尾脚本测试和完整单元测试。
- 验证结果：编译检查通过；完整单元测试 122 项全部 OK。
- 后续待办：真实升级后确认只关闭本次升级启动的 SecureCRT 窗口，不影响用户手动打开的其它 CRT 会话。

## 2026-07-08 - 提前 Tftp Put 进入 boot 敲回车时机

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户实测 `Tftp Put` 模式未成功进入 boot，原因是 SecureCRT 开始循环敲击回车的时间滞后，错过允许进入 boot 的窗口期。
- 完成内容：将 `boot_enter.signal` 从旧工具完整上电流程返回后前移到旧工具输出“已点击 Start ALL”时立即写出，让 SecureCRT 在 Start ALL 后马上每隔 1 秒敲击回车；保留旧软件关闭后的兜底信号，避免旧工具未输出该行时流程卡住。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、`test_sample_upgrade.py` 和完整单元测试，并补充 Start ALL 输出时立即写 boot signal 的回归测试。
- 验证结果：编译检查通过；`test_sample_upgrade.py` 11 项全部 OK；完整单元测试 121 项全部 OK。
- 后续待办：用真实样机复测 `Tftp Put` 进入 boot 时序。

## 2026-07-08 - 接入全包升级 Tftp Put 传输方式

- 类型：功能 / 测试 / 文档
- 背景：用户确认 `Tftp指令` 和 `Tftp Put` 是两种不同的固件传输方式，`Tftp Put` 目标设备 IP 固定为 `192.168.1.1`，需要在样机升级模块中都做适配。
- 完成内容：`全包升级 + Tftp Put` 进入现有多台串行升级流程；单台流程在 SecureCRT 完成 boot 登录后执行 Windows `tftp -i 192.168.1.1 put <升级固件路径>`，不启动 Tftpd64；Put 成功后继续复用现有 boot reset/重新上电、120 秒等待和最终登录确认；SecureCRT manifest 增加传输方式字段，脚本按 `Tftp指令` / `Tftp Put` 分支同步状态。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/securecrt_automation.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade.py`、`Cheating_machine_execution_tool/tests/test_securecrt_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、样机升级入口测试、单台升级编排测试、SecureCRT 自动化测试和完整单元测试。
- 验证结果：编译检查通过；`test_app.py` 54 项通过；`test_sample_upgrade.py` 10 项通过；`test_securecrt_automation.py` 16 项通过；完整单元测试 120 项全部 OK。
- 后续待办：用真实样机验收 `全包升级 + Tftp Put`。

## 2026-07-08 - 样机升级 Tftp 文案调整

- 类型：修改 / 测试 / 文档
- 背景：用户要求将样机升级模块中的“Tftp拷贝命令”显示文案改为“Tftp指令”。
- 完成内容：样机升级固件传输方式下拉框、提示文案和确认文案统一显示为“Tftp指令”；保留旧配置值“Tftp拷贝命令”的自动兼容映射，避免已保存本机配置影响串行升级入口。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查和样机升级入口相关单元测试。
- 验证结果：编译检查通过；`test_app.py` 53 项全部 OK。
- 后续待办：无。

## 2026-07-07 - 页面升级前自动启用目标网卡

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户实测 `vlan137`、`vlan138` 页面升级失败，原因为 PC 对应 VLAN 网卡未启用，导致无法登录 UBUS。
- 完成内容：页面升级请求新增目标网卡字段；每台样机执行 UBUS 登录前先调用现有 `enable_adapter()` 启用对应网卡，启用失败则只标记该样机失败并保留日志，其它并行样机继续执行。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_page_upgrade.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行页面升级单元测试、样机升级入口测试、编译检查和完整测试集。
- 验证结果：编译检查通过；`test_page_upgrade.py` 5 项通过；`test_app.py` 52 项通过；完整单元测试 111 项全部 OK。
- 后续待办：用真实 `vlan137`、`vlan138` 复测未启用网卡场景。

## 2026-07-07 - 兼容 UBUS 触发升级 Access denied

- 类型：BUG 修复 / 测试
- 背景：用户实测页面升级时，`vlan139` 在触发 UBUS 升级阶段返回 `Access denied`；后续确认原因是浏览器仍登录样机 Web 管理界面，退出 Web 管理界面后升级成功。
- 完成内容：为 UBUS RPC 错误增加调用点上下文；触发升级命令从单一 `bbfdm.operate` 改为依次尝试 `bbfdm.operate`、`bbfdm.operate(proto=web)` 和 `bbfdm.unauthenticated_operate`，遇到 `Access denied` 时自动尝试下一种兼容方式，并在日志中输出切换过程。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`、`Cheating_machine_execution_tool/tests/test_page_upgrade.py`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行页面升级单元测试、样机升级入口测试、编译检查和完整测试集。
- 验证结果：编译检查通过；`test_page_upgrade.py` 4 项通过；`test_app.py` 52 项通过；完整单元测试 110 项全部 OK。
- 后续待办：页面升级操作前提醒退出样机 Web 管理界面；如后续仍出现 `Access denied`，再根据日志中的 UBUS 调用点排查账号权限或接口差异。

## 2026-07-07 - 接入 UBUS 页面批量升级

- 类型：功能 / 测试 / 文档
- 背景：用户提供同事的 `ubus_upgrade_gui.py` / `ubus_upgrade.py`，要求将已验证的 UBUS 批量页面升级能力合并到现有“样机升级”的“页面升级”功能中。
- 完成内容：新增页面升级业务模块，支持绑定本机 IP、HTTP/HTTPS 登录 UBUS、上传固件、触发升级、查询状态和等待重启上线；“页面升级”按钮改为按已勾选通道并行执行 UBUS 批量升级；保留“全包升级 + Tftp拷贝命令”现有串行流程。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/page_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_page_upgrade.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行编译检查、页面升级单元测试、样机升级入口单元测试和完整测试集。
- 验证结果：编译检查通过；`test_page_upgrade.py` 2 项通过；`test_app.py` 52 项通过；完整单元测试 108 项全部 OK。
- 后续待办：使用真实样机验证页面升级的单台、多台并行和失败日志表现。

## 2026-07-07 - 配置 serial_upgrade.py 的 VS Code 运行环境

- 类型：配置 / 文档 / 测试
- 背景：用户希望直接在 VS Code 中运行 `Cheating_machine_execution_tool/test_boot_upgrade/serial_upgrade.py`。
- 完成内容：新增 VS Code 默认解释器与调试入口；新增 `test_boot_upgrade/requirements.txt`；将专用本地 Python 环境加入忽略列表；更新 `serial_upgrade` 使用指南和项目状态。
- 修改文件：`.vscode/settings.json`、`.vscode/launch.json`、`.gitignore`、`Cheating_machine_execution_tool/test_boot_upgrade/requirements.txt`、`Cheating_machine_execution_tool/test_boot_upgrade/使用指南.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：创建本地 Python 环境，安装 `pyserial`、`selenium`、`webdriver-manager`、`openpyxl`；运行编译检查和依赖导入检查。
- 验证结果：`python -m py_compile serial_upgrade.py` 通过；`serial`、`selenium`、`webdriver_manager`、`openpyxl` 导入通过。
- 后续待办：首次选择“页面升级”时，若 `webdriver-manager` 下载 Edge WebDriver 被网络或证书拦截，需要按现场网络环境处理。

## 2026-07-03 - 兼容旧工具 exe 新文件名

- 类型：优化 / 测试 / 文档
- 背景：用户将旧开关机工具从 `Auto_Power_On_Off_Tool(2).exe` 改名为 `Auto_Power_On_Off_Tool.exe`，要求程序只按 `Auto_Power_On_Off_Tool` 关键字识别。
- 完成内容：新增旧工具路径解析函数，查找根目录下文件名包含 `Auto_Power_On_Off_Tool` 且后缀为 `.exe` 的旧工具，优先使用 `Auto_Power_On_Off_Tool.exe`，兼容原 `(2)` 文件名；主程序自动上电和样机升级流程共用解析后的旧工具路径。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/paths.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_paths.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\paths.py`、`python -m unittest discover -s tests -p test_paths.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_paths.py` 3 项全部 OK；完整单元测试 103 项全部 OK。
- 后续待办：无。

## 2026-07-03 - ONU注册 清理离线 ONU 后重新注册

- 类型：BUG 修复 / 安全提示 / 测试 / 文档
- 背景：用户反馈原有 ONU 替换方式会替换到与新发现 ONU 不同 PON 口的旧 ONU，正确流程应删除不在线 ONU 后重新注册新 ONU。
- 完成内容：ONU 注册新增配置失败后不再执行 `registration-method sn 新SN` 复用旧 ONU 配置；改为查询 `show gpon onu state`，筛选已注册但不在线 ONU，优先删除和新 ONU 同 PON 口的不在线 ONU，再删除其它 PON 口不在线 ONU，删除后重新下发新 ONU 注册模板；注册确认提示同步说明该删除和重试行为。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_network_ops.py` 24 项全部 OK；完整单元测试 100 项全部 OK；新增回归覆盖新增配置失败后查询离线 ONU、优先删除同 PON 口离线 ONU、再删除其它 PON 口离线 ONU，并确认不再下发 `registration-method sn 新SN`。
- 后续待办：无。

## 2026-07-02 - 优化 ONU注册 长状态栏显示

- 类型：UI / 优化 / 测试 / 文档
- 背景：用户反馈 ONU注册 窗口中查询/注册状态栏显示不完整，长注册结果会在右侧被截断。
- 完成内容：将 ONU注册 查询/注册状态栏改为支持自动换行的多行状态框，增加垂直内边距并改为左上对齐；绑定状态框宽度变化，动态更新换行宽度，避免长 SN 或长注册结果被截断。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`，并执行 ONU注册 长状态文本布局探针。
- 验证结果：编译检查通过；`test_app.py` 49 项全部 OK；布局探针确认状态栏 `anchor=nw`、`pady=4`、`wraplength=640`。
- 后续待办：无。

## 2026-07-02 - ONU注册 注册后确认保存 OLT 配置

- 类型：功能 / 安全提示 / 测试 / 文档
- 背景：用户要求新 ONU 注册完成后弹出提示，询问是否保存 OLT 最新配置；用户确认保存时执行 `write` 写入启动配置。用户进一步验证确认这台 OLT 需要先退出全局模式，不能在 `ZXAN(config)#` 下执行 `write`。
- 完成内容：新增 OLT 配置保存底层能力，保存时独立登录 OLT，若检测到 `config` 或 `config-if` 提示符则循环执行 `exit` 直到回到执行模式，再执行 `write`；ONU 注册成功后弹窗询问是否保存，用户确认后异步执行保存并显示/记录保存结果，用户取消则只记录暂不保存。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_network_ops.py` 24 项全部 OK；`test_app.py` 49 项全部 OK；完整单元测试 100 项全部 OK；新增测试覆盖 `ZXAN(config)# exit -> ZXAN# write`、`ZXAN(config-if)# exit -> ZXAN(config)# exit -> ZXAN# write` 和注册成功后确认/取消保存两种 UI 分支。
- 后续待办：无。

## 2026-07-02 - 微调 ONU注册 密码小眼睛和开始注册按钮位置

- 类型：UI / 优化 / 测试
- 背景：用户反馈 ONU注册 窗口中密码小眼睛需要往右边移一点，“开始注册”按钮需要往左边移一点。
- 完成内容：将 ONU注册 密码输入框容器横跨右侧一列，让小眼睛按钮更靠右显示；收窄“取消全选”和“开始注册”之间的横向间距，使“开始注册”按钮整体更靠左。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`，并执行 ONU注册 布局探针确认密码容器跨列、按钮 padding 生效。
- 验证结果：编译检查通过；`test_app.py` 47 项全部 OK；布局探针显示密码容器 `columnspan=2`，小眼睛按钮右侧打包，开始注册按钮保持左对齐且横向 padding 已收窄。
- 后续待办：无。

## 2026-07-02 - ONU注册 新增配置失败后复用旧 ONU 配置

- 类型：功能 / 安全提示 / 测试 / 文档
- 背景：用户确认复用旧 ONU 配置的正确命令为进入已注册 ONU 接口后执行 `registration-method sn 新SN`，并要求“开始注册”优先使用新增 ONU 业务配置；如果新增配置过程中业务命令报错，则改用复用旧 ONU 配置的方式让新 ONU 上线。
- 完成内容：ONU 注册底层流程在新增配置命令失败时不再直接退出，而是切回执行模式查询 `show gpon onu state`，自动选择已注册但未在线的 ONU（例如 OMCC 非 enable 或 Phase 非 working），重新进入全局模式后执行 `interface gpon-onu_旧ONU接口` 与 `registration-method sn 新SN`；注册确认提示同步说明该 fallback 会替换旧 ONU 的认证 SN；结果状态会区分“新增配置成功”和“新增配置失败后复用旧 ONU 配置”。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_network_ops.py` 21 项全部 OK；`test_app.py` 47 项全部 OK；完整单元测试 95 项全部 OK；新增测试已模拟 `service Internet gemport 1 vlan 200` 返回错误后自动执行 `show gpon onu state`、选择离线旧 ONU 并下发 `registration-method sn 新SN`。
- 后续待办：如后续需要由用户手动指定要复用的旧 ONU 口，可在 ONU注册列表旁增加“旧 ONU 口选择”或“自动/手动复用”模式。

## 2026-07-02 - ONU注册 接入开始注册功能

- 类型：功能 / UI / 测试 / 文档
- 背景：用户要求在已查询出的未注册 ONU 列表基础上实现“开始注册”功能，用于将勾选的 ONU 注册上线。
- 完成内容：新增 ONU 注册底层 Telnet 下发能力，按已确认的 ZTE OLT / SD-41 模板生成 `interface gpon-olt`、`interface gpon-onu`、业务 VLAN、`pon-onu-mng` 等配置命令；ONU注册窗口新增“开始注册”按钮，仅对勾选 ONU 生效，执行前二次确认，执行中禁用相关按钮，完成后在状态栏显示结果并写入运行日志；注册不会自动保存 OLT 配置，完成后提示重新查询确认上线。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 “开始注册”按钮和勾选列表 Tk 探针。
- 验证结果：编译检查通过；`test_app.py` 47 项全部 OK；`test_network_ops.py` 19 项全部 OK；完整单元测试 93 项全部 OK；ONU注册 UI 探针通过。`test_network_ops.py` 首次在普通沙箱遇到 Windows ACL 读权限错误，已按规则提权重跑并通过。
- 后续待办：如需要将 OLT 配置保存为启动配置，可在后续增加独立确认后的保存按钮或注册完成后的保存选项。

## 2026-07-02 - ONU注册 未注册 ONU 列表增加选择框

- 类型：UI / 功能 / 测试 / 文档
- 背景：用户要求在查询到的未注册 ONU 列表中，每个 ONU 前面都加选择框，方便后续决定要注册哪些 ONU，并增加全选和取消全选按钮。
- 完成内容：查询结果状态栏改为显示查询摘要；未注册 ONU 明细改为复选框列表，每行包含接口、SN 和状态；新增“全选”和“取消全选”按钮，查询到结果后启用，无结果或查询失败时禁用并清空旧选择。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 复选框渲染探针。
- 验证结果：编译检查通过；`test_app.py` 43 项全部 OK；`test_network_ops.py` 15 项全部 OK；完整单元测试 85 项全部 OK；ONU注册 复选框渲染探针通过。
- 后续待办：注册流程接入时读取用户勾选的 ONU 列表并执行注册。

## 2026-07-02 - ONU注册 查询所有 PON 口未注册 ONU

- 类型：功能 / UI / 测试 / 文档
- 背景：用户要求点击 ONU注册 的“开始查询”时，把 OLT 所有 PON 口下未注册的 ONU 都显示出来。
- 完成内容：新增 `show gpon onu uncfg` 只读查询能力，登录 OLT 后查询所有 PON 口未注册 ONU 并解析接口、SN 和状态；“开始查询”按钮改为异步查询流程，查询中禁用按钮，完成后在查询状态栏显示全部结果并写入运行日志。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`，并用真实 OLT 执行只读查询函数。
- 验证结果：编译检查通过；`test_app.py` 42 项全部 OK；`test_network_ops.py` 15 项全部 OK；完整单元测试 84 项全部 OK；真实 OLT 只读查询返回 3 个未注册 ONU。
- 后续待办：后续接入注册配置时，基于查询出的接口和 SN 做选择/填充。

## 2026-07-02 - ONU注册 连通性测试后登录 OLT 并进入全局模式

- 类型：功能 / UI / 测试 / 文档
- 背景：用户要求点击 ONU注册 的连通性测试后，如果 Telnet 连通性通过，则直接使用界面填写的用户名和密码登录 OLT，并在登录成功后下发 `configure terminal` 进入全局模式；登录状态需要显示在状态栏。
- 完成内容：新增 OLT Telnet 登录和进入全局模式的底层能力；连通性测试按钮现在会先确认该操作，再测试 Telnet 23 端口，连通后登录 OLT 并下发 `configure terminal`；OLT IP 右侧仍只显示 Telnet 连通性结果，登录和全局模式结果显示在查询入口下方状态栏，并写入运行日志。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_app.py` 41 项全部 OK；`test_network_ops.py` 13 项全部 OK；完整单元测试 81 项全部 OK。
- 后续待办：用真实 OLT 确认具体登录提示符和全局模式提示符，如设备提示符与当前通用解析不同，再按实际提示符细化解析。

## 2026-07-02 - 调整 ONU注册 状态显示和窗口默认尺寸

- 类型：UI / 优化 / 文档 / 测试
- 背景：用户要求 ONU注册 模块中 OLT IP 右侧的连通性状态只显示 Telnet 状态，其它状态信息显示在“查询未注册的ONU”下方；同时默认宽减少 1cm、默认高减少 3cm。
- 完成内容：将 ONU注册 状态分为 Telnet 连通性状态和查询状态两块；Telnet 结果仍显示在 OLT IP 右侧，查询未注册 ONU 的占位/后续状态显示在查询入口下方；窗口默认尺寸从 `934x694` 调整为 `896x580`，最小尺寸从 `874x644` 调整为 `836x530`。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 窗口尺寸和状态分区探针。
- 验证结果：编译检查通过；`test_app.py` 41 项全部 OK；完整单元测试 79 项全部 OK；ONU注册 窗口尺寸和状态分区探针通过。
- 后续待办：无。

## 2026-07-02 - 加大 ONU注册 窗口尺寸

- 类型：UI / 优化 / 文档 / 测试
- 背景：用户要求将 ONU注册 模块界面的长宽都加大 3cm。
- 完成内容：将 ONU注册 窗口默认尺寸从 `820x580` 调整为 `934x694`，最小尺寸从 `760x530` 调整为 `874x644`，按 96 DPI 折算长宽各增加约 3cm；同步更新 README 和项目状态说明。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`，并执行 ONU注册 窗口尺寸探针。
- 验证结果：编译检查通过；`test_app.py` 40 项全部 OK；ONU注册 窗口尺寸探针通过。
- 后续待办：无。

## 2026-07-02 - 修复启动配置解析失败

- 类型：BUG 修复 / 配置 / 测试
- 背景：项目源码启动时报 `configparser.ParsingError`，原因是 `config/network_card_ip.ini` 中 `channel_14` 的 `adapter_alias` 行被截断为无效的 `adapter_al`。
- 完成内容：补全 `channel_14` 的 `adapter_alias`、`network_card_ip`、`device_manage_ip`、`subnet_mask` 配置项，恢复 INI 文件合法结构。
- 修改文件：`Cheating_machine_execution_tool/config/network_card_ip.ini`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\run_line_check_assistant.py .\line_check_assistant\app.py .\line_check_assistant\config_store.py`，并用 `ChannelConfigStore` 加载配置。
- 验证结果：配置解析恢复正常，源码入口不再因 `network_card_ip.ini` 解析错误而退出。
- 后续待办：如需要使用打包版启动，需要重新生成 `dist\LineCheckAssistant.exe`。

## 2026-07-02 - 新增 ONU注册 功能入口

- 类型：功能 / UI / 文档 / 测试
- 背景：用户要求在主界面“常用工具”中增加“ONU注册”功能入口，并保持软件界面风格一致。
- 完成内容：在常用工具栏新增 `ONU注册` 按钮；新增同风格独立占位窗口，展示 OLT 连接、ONU 标识、注册方式、注册状态等后续流程入口；窗口当前不登录设备、不修改配置、不执行注册操作。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py` 和 `python -m unittest discover -s tests -p test_app.py -v`。
- 验证结果：编译检查通过；`test_app.py` 28 项全部 OK。
- 后续待办：后续明确 ONU 注册协议、OLT 登录方式、SN/LOID 字段和注册校验规则后，再接入实际业务流程。

## 2026-07-02 - 完善 ONU注册 窗口表单和 Telnet 连通性测试

- 类型：功能 / UI / 测试 / 文档
- 背景：用户要求将 ONU注册 窗口中的占位项改为可输入表单：OLT IP 默认 `172.18.18.151`，支持 Telnet 连通性测试；ONU标识改为用户名和密码；注册方式改为查询未注册的ONU并提供开始查询按钮。
- 完成内容：新增 OLT IP、用户名、密码输入框；新增连通性测试按钮，调用底层 Telnet 23 端口连接检查；新增查询未注册 ONU 的开始查询入口占位；保持窗口配色、间距和按钮样式与现有界面一致。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/network_ops.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_network_ops.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\network_ops.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_network_ops.py -v`、`python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；`test_app.py` 31 项全部 OK；`test_network_ops.py` 11 项全部 OK；完整单元测试 63 项全部 OK。
- 后续待办：明确 OLT 登录提示符、查询未注册 ONU 的 Telnet 命令和解析规则后，再接入实际查询流程。

## 2026-07-02 - 保存 ONU注册 输入框上次关闭状态

- 类型：功能 / 配置 / 测试 / 文档
- 背景：用户要求 ONU注册 中所有输入框填写的信息都能保存上一次关闭时的信息，并明确默认 OLT IP 也要恢复上次关闭状态。
- 完成内容：新增 ONU 注册配置存储模块；OLT IP、用户名、密码会自动保存到本机 `config/onu_registration.ini`，关闭 ONU 窗口或直接关闭主程序时会立即保存；首次没有历史配置时才使用默认 OLT IP `172.18.18.151`；新增 `.gitignore` 规则避免本机凭据配置进入 Git。
- 修改文件：`.gitignore`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/onu_registration_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\onu_registration_store.py`、`python -m unittest discover -s tests -v`，并执行窗口关闭持久化探针。
- 验证结果：编译检查通过；完整单元测试 68 项全部 OK；窗口关闭持久化探针通过。
- 后续待办：后续接入真实 ONU 查询流程时，继续复用该本机配置作为默认连接信息。

## 2026-07-02 - 保存样机升级窗口上次关闭状态

- 类型：功能 / 配置 / 测试 / 文档
- 背景：用户补充说明其它功能模块也要保存上一次关闭时的状态，例如样机升级模块。
- 完成内容：新增样机升级设置存储模块；保存升级方式、固件传输方式、恢复出厂选项、超级用户名、密码和固件路径；关闭样机升级窗口或直接关闭主程序时立即保存；新增 `.gitignore` 规则避免本机样机升级输入状态进入 Git。
- 修改文件：`.gitignore`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\onu_registration_store.py .\line_check_assistant\sample_upgrade_settings_store.py`、`python -m unittest discover -s tests -v`，并执行样机升级关闭后重新打开的临时配置探针。
- 验证结果：编译检查通过；完整单元测试 72 项全部 OK；样机升级关闭后重新打开探针通过。
- 后续待办：后续如“写样机参数”“串口日志”等模块增加真实输入框，也按同一模式保存到本机配置文件并加入 Git 忽略。

## 2026-07-02 - 调整 ONU注册 连通性结果显示位置

- 类型：UI / 文档 / 测试
- 背景：用户要求将 OLT IP 的连通性测试结果显示到 OLT IP 输入框右侧、连通性测试按钮左侧的位置。
- 完成内容：移除 ONU注册 窗口底部状态行，将 Telnet 连通性测试结果改为显示在 OLT IP 输入框和连通性测试按钮之间的内联结果框。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 窗口初始化探针。
- 验证结果：编译检查通过；`test_app.py` 36 项全部 OK；完整单元测试 72 项全部 OK；ONU注册 窗口初始化探针通过。
- 后续待办：无。

## 2026-07-02 - ONU注册 密码框增加小眼睛切换

- 类型：UI / 测试 / 文档
- 背景：用户要求 ONU注册 模块的密码输入框增加小眼睛，可点击切换明文和密文显示。
- 完成内容：ONU注册 密码输入框改为带小眼睛按钮的组合控件；点击小眼睛可在 `*` 密文和明文显示之间切换，行为与样机升级密码框保持一致。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 密码小眼睛切换探针。
- 验证结果：编译检查通过；`test_app.py` 37 项全部 OK；完整单元测试 73 项全部 OK；ONU注册 密码小眼睛切换探针通过。
- 后续待办：无。

## 2026-07-02 - 修复样机升级配置后无法关闭窗口

- 类型：BUG 修复 / 配置 / 测试
- 背景：用户反馈样机升级模块填写升级配置后，点击关闭无法关闭，主界面也无法关闭，表现像卡死。
- 完成内容：定位为保存本机配置时 `ConfigParser` 默认插值会把密码或路径中的 `%` 当成特殊语法并抛异常，导致关闭回调未执行 `destroy()`；将 ONU注册 和 样机升级 的本机配置存储改为 `RawConfigParser`，支持保存 `%` 等普通字符；关闭 ONU注册、样机升级窗口和主窗口时，即使保存异常也会继续关闭窗口。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/line_check_assistant/onu_registration_store.py`、`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade_settings_store.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_onu_registration_store.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade_settings_store.py`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\sample_upgrade_settings_store.py .\line_check_assistant\onu_registration_store.py`、`python -m unittest discover -s tests -v`，并执行包含 `%` 密码/路径的样机升级关闭回归探针。
- 验证结果：编译检查通过；完整单元测试 76 项全部 OK；包含 `%` 密码/路径的关闭回归探针通过。
- 后续待办：无。

## 2026-07-02 - ONU注册 Telnet 连通性结果增加状态颜色

- 类型：UI / 测试 / 文档
- 背景：用户要求 Telnet 连通性测试通过或失败时，用不同颜色区分结果。
- 完成内容：ONU注册 的内联连通性结果框增加颜色状态；测试中显示警告色，测试通过显示绿色，测试失败或未输入 OLT IP 显示红色。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -v`，并执行 ONU注册 状态颜色探针。
- 验证结果：编译检查通过；`test_app.py` 40 项全部 OK；完整单元测试 78 项全部 OK；ONU注册 状态颜色探针通过。
- 后续待办：无。

## 2026-06-27 - 多台串行全包 Tftp 升级验收通过

- 类型：测试 / 项目状态
- 背景：用户反馈“全包 + Tftp 命令传输 + 多台串行升级”验收通过，今日开发到此结束。
- 完成内容：记录真实设备验收结论，并同步项目状态，将多台串行升级标记为已验收通过。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`
- 验证方法：用户在真实设备上验收“全包 + Tftp 命令传输 + 多台串行升级”流程。
- 验证结果：验收通过。
- 后续待办：后续再评估多台并发 TFTP 传输/并发升级，以及不同项目/型号和异常场景补强。

## 2026-06-27 - 升级收尾自动关闭 SecureCRT 和 Tftpd64

- 类型：优化 / 测试 / 文档
- 背景：用户要求在打印“已恢复 network_card_ip.ini 中用户选择的完整通道配置。”时，同步关闭升级过程中打开的串口工具，例如 SecureCRT 和 Tftpd64。
- 完成内容：新增升级收尾清理逻辑；多台串行升级恢复完整通道配置后，自动关闭 SecureCRT 进程和项目目录下的 `tftpd64.exe`；关闭过程输出到升级日志。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/upgrade_cleanup.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_tftpd_automation.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\upgrade_cleanup.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_tftpd_automation.py -v` 和完整 `python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；完整 `python -m unittest discover -s tests -v` 57 项全部 OK。
- 后续待办：真实升级完成后确认 SecureCRT/Tftpd64 能被自动关闭，且不会影响需要保留的人工 SecureCRT 会话。

## 2026-06-27 - 上电等待时间改为每通道 10 秒

- 类型：修改 / 测试 / 文档
- 背景：用户要求把上电等待从 5 秒改为 10 秒。
- 完成内容：升级流程中每台样机调用旧开关机工具后的等待时间改为 10 秒；主界面“自动上电”按启用通道数每通道 10 秒计算等待时间；同步 README 和项目状态说明。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\sample_upgrade.py` 和 `python -m unittest discover -s tests -v`。
- 验证结果：编译检查通过；完整 `python -m unittest discover -s tests -v` 55 项全部 OK。
- 后续待办：使用真实设备确认 10 秒上电等待是否足够稳定。

## 2026-06-27 - 按当前通道临时改写 network_card_ip.ini 实现真实串行上电

- 类型：BUG 修复 / 功能 / 测试 / 文档
- 背景：用户指出旧开关机工具会按 `network_card_ip.ini` 从上往下逐台上电；如果配置里同时保留多台样机，旧工具 `Start ALL` 仍会操作多个通道，导致新软件内部串行不等于真实串行上电。
- 完成内容：多台串行升级开始时保存用户选择的完整通道快照；每台升级前写入 `network_card_ip.ini` 只保留当前通道；当前通道升级完成后再写入下一台；串行结束或失败后恢复完整通道配置。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py` 和 `python -m unittest discover -s tests -p test_app.py -v`。
- 验证结果：编译检查通过；完整 `python -m unittest discover -s tests -v` 55 项全部 OK。
- 后续待办：使用真实多台样机验证旧工具每次只给当前 `network_card_ip.ini` 中保留的通道上电。

## 2026-06-27 - 修复串行升级提示 VLAN 与实际上电顺序不一致

- 类型：BUG 修复 / 测试 / 文档
- 背景：用户验收发现勾选 `vlan137`、`vlan138`、`vlan139` 后，界面提示正在升级 `vlan137`，但旧工具实际先启动的是 `VLAN139` 上电。
- 完成内容：多台串行升级不再按 VLAN 数字排序，而是按主界面通道顺序生成升级队列，让确认提示、状态栏和旧工具实际上电顺序保持一致。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py` 和 `python -m unittest discover -s tests -p test_app.py -v`。
- 验证结果：编译检查通过；`test_app.py` 26 项全部 OK；完整 `python -m unittest discover -s tests -v` 55 项全部 OK。
- 后续待办：继续用真实多台样机验证主界面通道顺序与旧工具上电顺序是否完全一致；如仍有偏差，需要进一步接入旧工具单通道选择/上电能力。

## 2026-06-27 - 实现多台样机串行 Tftp 拷贝升级

- 类型：功能 / 测试 / 文档
- 背景：用户要求开始实现多台串行升级，在单台样机已验证通过的基础上扩展到多个已勾选通道。
- 完成内容：全包升级 + Tftp 拷贝命令支持选择多个目标 VLAN，启动前确认，按主界面通道顺序逐台复用单台升级流程；某台失败时停止后续样机并提示失败信息。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\app.py .\line_check_assistant\sample_upgrade.py`、`python -m unittest discover -s tests -p test_app.py -v`、`python -m unittest discover -s tests -p test_sample_upgrade.py -v`。
- 验证结果：编译检查通过；`test_app.py` 26 项通过；`test_sample_upgrade.py` 5 项通过；完整 `python -m unittest discover -s tests -v` 55 项全部 OK。
- 后续待办：使用真实多台样机验证串行升级流程；后续再评估并发 TFTP 传输/并发升级。

## 2026-06-27 - 单台样机 Tftp 拷贝升级和复位流程验证通过

- 类型：测试 / 项目状态
- 背景：用户反馈单台样机通过 Tftp 拷贝命令和复位功能已经验证通过。
- 完成内容：记录真实设备验证结论，并同步项目状态，明确单台样机“全包升级 + Tftp 拷贝命令 + reset/重新上电后登录确认”流程已通过验证。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`
- 验证方法：用户在真实单台样机上执行 Tftp 拷贝命令和复位流程。
- 验证结果：单台样机流程验证通过。
- 后续待办：继续完善多台样机、不同项目/型号和异常失败场景的流程验证。

## 2026-06-27 - 调整 boot reset 后登录等待时间

- 类型：修改 / 测试 / 文档
- 背景：用户要求检测到 SecureCRT 已发送 reset 后，以及未检测到 reset 重新上电后，主流程都固定等待 120 秒再登录样机系统。
- 完成内容：将 boot reset 分支和重新上电分支的登录前等待时间从 180 秒改为 120 秒，并更新界面日志文案、README 描述和单元测试期望。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/sample_upgrade.py`、`Cheating_machine_execution_tool/tests/test_sample_upgrade.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 `python -m py_compile .\line_check_assistant\sample_upgrade.py` 和 `python -m unittest discover -s tests -p test_sample_upgrade.py -v`。
- 验证结果：`python -m py_compile .\line_check_assistant\sample_upgrade.py` 通过；`python -m unittest discover -s tests -p test_sample_upgrade.py -v` 通过，5 项测试 OK。
- 后续待办：无。

## 2026-06-27 - 新增开发记录机制

- 类型：文档 / 项目管理
- 背景：用户要求后续每次完成的功能、优化、修改、BUG 修复等都记录下来，方便继续开发和整体管理。
- 完成内容：新增统一开发记录文件，约定每次变更后的记录格式和同步规则。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`、`AGENTS.md`
- 验证方法：检查文档结构和链接入口。
- 验证结果：已建立可持续追加的开发记录入口。
- 后续待办：后续每次任务完成后，按模板在本文件顶部追加记录。
## 2026-07-11 - 修复 Boot 首轮提示符导致账号密码错位

- 类型：BUG 修复 / 串口时序 / 测试 / 文档
- 背景：真实升级日志显示，程控电源上电后的首轮 `UserName:` / `Password:` 过渡输出可能被当作有效登录提示，导致账号和密码在第一阶段提前写入，后续重试才成功。
- 完成内容：程控电源流程改为在电源动作返回并等待 1 秒后才放行 boot 登录线程；用户名提示符命中后增加仅接收串口的 1 秒稳定窗口，若用户名提交前已经收到 `Password:` / `Passvord:` 则丢弃整轮，不发送任何凭据；用户名回车后仍使用新游标等待本轮密码提示符。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：`python -m unittest discover -s tests -p test_serial_upgrade_service.py -v`、`python -m unittest discover -s tests -v`；真实设备需复测 `Tftp指令` 的首次上电进入 boot。
- 验证结果：串口升级专项 13 项通过；完整 `python -m unittest discover -s tests -v` 共 125 项通过。新增回归覆盖“首轮 UserName/Password 同时出现时不发送账号密码”；后续真实设备首次上电进入 boot 验证已通过。

## 2026-07-11 - Boot 首轮登录错位真实样机验证通过

- 类型：真实设备验收 / 项目状态
- 背景：修复上电初期 `UserName:` / `Password:` 过渡输出造成账号、密码错位后，需要确认实际样机首轮进入 boot 的登录行为。
- 完成内容：用户已确认该问题解决，首次 Boot 登录不再出现账号或密码错位。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`
- 验证方法：用户在真实样机使用 `Tftp指令` 的首次上电进入 boot 流程验证。
- 验证结果：通过。
## 2026-07-11 - 全包升级断电重启不再关闭全部程控电源通道

- 类型：流程优化 / 程控电源 / 测试 / 文档
- 背景：全包升级当前通道断电再上电时，日志仍先发送 `55 00 AD 00 00 AD` 全部断电帧；用户要求去除该操作。
- 完成内容：`power_on_selected_channels()` 保留当前升级通道的关闭帧、断电间隔和开启帧，移除“关闭全部程控电源通道”帧；主界面自动上/下电和 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 的业务逻辑未改动。
- 修改文件：`Cheating_machine_execution_tool/src/core/power_supply.py`、`Cheating_machine_execution_tool/src/services/power_on_service.py`、`Cheating_machine_execution_tool/tests/test_power_supply.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行程控电源专项测试和完整单元测试；真实样机观察全包升级首次/重新上电日志。
- 验证结果：程控电源专项 8 项通过；完整 `python -m unittest discover -s tests -v` 共 125 项通过。真实样机需确认日志不再出现 `关闭全部程控电源通道：55 00 AD 00 00 AD`。

## 2026-07-11 - 全包升级 Tftp指令 多台样机串行验收通过

- 类型：真实设备验收 / 项目状态
- 背景：主程序的 `全包升级 + Tftp指令` 采用程控电源按当前通道逐台执行，需要确认多台样机的串行升级完整流程。
- 完成内容：用户确认多台样机串行升级验收通过；`Tftp指令` 流程标记为真实样机已验收。
- 修改文件：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`
- 验证方法：用户在真实设备执行“样机升级 → 全包升级 → Tftp指令”的多台样机串行升级。
- 验证结果：通过。
## 2026-07-11 - 全包升级 Tftp指令 支持两台受控并行

- 类型：功能 / 并行编排 / 程控电源 / 测试 / 文档
- 背景：用户要求在已验收的多台样机串行 `Tftp指令` 流程基础上，提供最多两台样机并行升级；主程序已不再使用旧工具 GUI，因此升级过程不应逐台改写 `network_card_ip.ini`。
- 完成内容：样机升级窗口新增持久化的“串行 / 并行（最多 2 台）”选择，默认串行且仅对 `Tftp指令` 生效；并行模式完成即补位，单台失败不取消其它样机。新增共享电源协调器，仅串行化同一 COM 口的关闭/开启帧，将每台启动等待移到锁外；每台 TFTP 服务严格绑定各自 VLAN IP，不允许回退到 `0.0.0.0`。串行和并行全包升级均不再临时改写 `network_card_ip.ini`；`Tftp Put`、自动上/下电和 `Auto_power_on_off_tool/Auto_Power_On_Off_Tool.py` 保持原逻辑。
- 修改文件：`Cheating_machine_execution_tool/line_check_assistant/app.py`、`line_check_assistant/sample_upgrade_settings_store.py`、`src/core/tftp_transport.py`、`src/services/serial_upgrade_service.py`、`src/services/__init__.py`、相关单元测试、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行升级设置、TFTP、串行升级服务、主界面专项测试及完整单元测试；真实设备以两台独立 VLAN、相同 Boot IP 的样机验证。
- 验证结果：编译检查通过；完整 `python -m unittest discover -s tests -v` 共 130 项通过。新增严格双 IP 同端口 TFTP 监听、两台并行上限/失败继续、电源 COM 互斥与不改写升级配置的回归覆盖；真实两台并行升级待验收。
## 2026-07-11 - 并行 TFTP 严格绑定前等待 VLAN IP 就绪

- 类型：BUG 修复 / 网络时序 / 测试 / 文档
- 背景：两台并行 `Tftp指令` 日志显示，`netsh` 已成功设置 VLAN139/VLAN138 的静态 IP，但约 1 秒后严格 TFTP 预检仍报告 IP 不可绑定；这是 Windows 刚配置网卡地址时地址注册尚未完成造成的时序问题。
- 完成内容：设置静态 IP 后改为每 0.5 秒验证一次可绑定性，最长等待 15 秒；就绪后再启动严格绑定的 TFTP 服务。超时仅报告该 VLAN 的网卡 IP/重复 IP/驱动问题，仍不回退到 `0.0.0.0`，避免多 VLAN 同 Boot IP 的回包错路由。
- 修改文件：`Cheating_machine_execution_tool/src/core/tftp_transport.py`、`src/core/__init__.py`、`src/services/serial_upgrade_service.py`、相关单元测试、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：运行 TFTP、串行升级服务专项测试和完整单元测试；真实设备重新执行两台并行 `Tftp指令`。
- 验证结果：专项 25 项通过；完整 `python -m unittest discover -s tests -v` 共 133 项通过。真实设备待复测。
## 2026-07-11 - 并行 TFTP 数据 socket 固定绑定 VLAN IP

- 类型：BUG 修复 / 多网卡路由 / 测试 / 文档
- 背景：两台样机的 UDP 69 服务都已成功监听，但只有一台开始传输。定位到 TFTPy 在收到 RRQ 后会创建未绑定本地 IP 的数据传输 socket；当多张 VLAN 网卡面对相同 Boot IP `192.168.1.1` 时，Windows 会把数据回包路由到其中一张网卡。
- 完成内容：在主程序 TFTP 包装层替换 TFTPy 的会话上下文工厂。每个监听线程创建传输数据 socket 时，强制绑定该服务的 VLAN IP 和随机本地端口；不修改虚拟环境中的第三方源码。这样监听帧和后续固件数据帧均从同一 VLAN IP 返回样机。
- 修改文件：`Cheating_machine_execution_tool/src/core/tftp_transport.py`、`tests/test_tftp_transport.py`、`line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`
- 验证方法：模拟 RRQ，断言 TFTPy 新建的数据 socket 绑定监听 VLAN IP；运行完整单元测试；真实设备执行两台并行 `Tftp指令`。
- 验证结果：TFTP 专项 9 项通过；完整 `python -m unittest discover -s tests -v` 共 134 项通过。真实两台并行传输待复测。
## 2026-07-12 - 全包升级 Tftp Put 支持两台受控并行

- 类型：功能 / 并行编排 / 程控电源 / 测试 / 文档
- 背景：`Tftp Put` 已完成多台串行真实样机验收；需要在不触碰 `Tftp指令` 调度和传输逻辑的前提下，提供两台受控并行升级能力。
- 完成内容：新增仅接受 `Tftp Put` 请求的并行服务入口，固定最多两台、完成即补位、单台失败不中止其它样机并按输入顺序汇总。每个 worker 仍使用 TFTPy Client 将固件推送至隔离 VLAN 内的 `192.168.1.1`，共享程控电源 COM 的开关帧由现有协调器串行化。升级窗口现对 `Tftp Put` 显示“串行 / 并行（最多 2 台）”，新增独立 UI worker、状态汇总、VLAN 日志和自动串口终端收尾；`Tftp指令` 的 worker、严格服务端绑定和传输流程未改动。
- 修改文件：`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/src/services/__init__.py`、`Cheating_machine_execution_tool/line_check_assistant/app.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_app.py`、`Cheating_machine_execution_tool/line_check_assistant_README.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：运行编译检查、串行升级服务专项测试、主界面专项测试和完整单元测试；真实两台独立 VLAN / COM 样机执行并行 `Tftp Put`。
- 验证结果：`python -m py_compile line_check_assistant/app.py src/services/serial_upgrade_service.py src/services/__init__.py` 通过；串行升级服务专项 24 项、主界面专项 60 项通过；完整 `python -m unittest discover -s tests -v` 共 154 项通过。
- 后续待办：真实两台独立 VLAN / COM 样机验收并行 `Tftp Put`，确认两路上传可同时推进且程控电源开关帧不交叠。

## 2026-07-12 - 全包升级 Tftp指令 / Tftp Put 两台并行真实样机验收通过

- 类型：真实样机验收 / 状态更新
- 背景：`Tftp指令` 两台并行和 `Tftp Put` 两台并行此前都是“代码完成，待真实两台验收”，需要把状态收口到已验收。
- 完成内容：用户已用两台不同 VLAN/COM 的真实样机验收 `Tftp指令` 并行和 `Tftp Put` 并行，结果通过。同步将 `PROJECT_STATUS.md` 中两项标记为“已真实两台验收”，移除“待两台真实验收”相关待办，删除“`Tftp Put` 并行仍是代码和单测验证”的限制项。
- 修改文件：`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：真实两台不同 VLAN/COM 样机分别执行 `Tftp指令` 并行和 `Tftp Put` 并行升级。
- 验证结果：通过。
- 后续待办：继续按现有约束观察新型号或异常现场日志，再扩展超时、掉线、登录失败与型号差异处理；不要预先改变已验收时序。

## 2026-07-12 - 串口乱码盲发密码补救登录真实样机验收通过

- 类型：真实样机验收 / 状态更新
- 背景：先前在 `_login_boot` 与 `login_tftp_put_boot_after_username` 增加的 salvage 分支（回显含 UTF-8 替换符 `�` → 盲发密码 → 等 shell 提示符）已通过单元测试（160 项），需要现场复现 UART 损坏场景验证命中率。
- 完成内容：用户已在真实样机上验证该 salvage 方案，结果通过。同步在 `PROJECT_STATUS.md` 的"已完成"中追加该能力的真实样机验收条目。
- 修改文件：`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证方法：真实样机复现 UART 输出损坏场景,触发用户名回显和 `Password:` 提示符均为乱码,确认 salvage 命中并进入 shell。
- 验证结果：通过。
- 后续待办：继续按现有约束观察新型号或异常现场日志,再扩展其他场景;不要预先改变已验收时序。

## 2026-07-12 - 串口乱码时盲发密码补救登录

- 类型：BUG 修复 / 异常现场补强 / 测试 / 文档
- 背景：现场日志显示一台样机的 UART 输出损坏：`UserName:` 被切成 `U` + `serName:`、`RX C�H�`、`RX C!���ݽɑ�` 等乱码；`Password:` 提示符也是乱码。`_login_boot` 与 `login_tftp_put_boot_after_username` 都在等待完整 `Password:` 提示符，超时后只能重试或放弃，但 UART 输入正常时样机实际已接受账号。
- 完成内容：新增 `PySerialSession.peek_since(cursor)` 读取从游标开始的解码文本（不消费历史）；新增模块级常量 `GARBLED_REPLACEMENT_MARKER` 与辅助函数 `_looks_like_garbled_response()` 检测 UTF-8 替换符 `�`；新增 `SerialUpgradeController._try_login_after_garbled_username()`，在 `_login_boot`（Tftp指令）和 `login_tftp_put_boot_after_username`（Tftp Put）的 `Password:` 超时分支中：当回显含 `�` 时盲发一次密码，等待 shell 提示符（`#` / `>` / `ecnt>` / `u-boot>`）作为登录成功；salvage 失败不影响原重试或失败路径。完整 `UserName:` / `Password:` 提示符到达时仍走原路径，不改变已验收时序。
- 修改文件：`Cheating_machine_execution_tool/src/core/serial_transport.py`、`Cheating_machine_execution_tool/src/services/serial_upgrade_service.py`、`Cheating_machine_execution_tool/tests/test_serial_transport.py`、`Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py`、`DEVELOPMENT_LOG.md`。
- 验证方法：`python -m py_compile src/core/serial_transport.py src/services/serial_upgrade_service.py`；运行 `tests/test_serial_upgrade_service.py`、`tests/test_serial_transport.py` 及完整单元测试。
- 验证结果：编译通过；新增 6 项用例覆盖 `peek_since` 基础行为、Tftp指令 salvage 成功 / 失败重试 / 干净超时无 salvage、Tftp Put salvage 成功 / 干净超时无 salvage；完整 `python -m unittest discover -s tests -v` 共 160 项通过。后续现场用已知会让响应乱码的串口线复测,确认命中并进入 shell,真实样机验收通过。
- 后续待办：继续按现有约束观察新型号或异常现场日志,再扩展其他场景;不要预先改变已验收时序。

## 2026-07-12 - 精简项目交接状态文档

- 类型：文档 / 交接
- 完成内容：重写 `PROJECT_STATUS.md`，仅保留项目目标与实现进度、关键文件、已完成与待验收项、技术限制，以及运行/测试/继续开发命令；同步当前全量测试基线为 154 项。
- 修改文件：`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`。
- 验证结果：已核对源码入口、升级服务、串口/TFTP 核心文件与当前测试基线；未改动业务代码。
