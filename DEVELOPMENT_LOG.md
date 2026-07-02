# 开发记录

本文件用于按时间记录每次开发完成的功能、优化、修改、BUG 修复、验证方式和后续待办，方便下一次继续开发，也方便做整体项目概览和管理。

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
