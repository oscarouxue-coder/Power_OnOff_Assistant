# DUTPilot Qt迁移：2.4G / 5G WiFi增量

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

`feature/pyside6-migration`。WiFi两页源码、模拟回归、三档 Windows 原生验证和完整基线均通过。实际设备和长时间挂测仍待现场验收，正式设备测试入口继续使用Tk。

## 真实代码审计及实施边界

- 旧Tk两个WiFi页使用同一个双频开关，但各有独立SSID索引、SSID递增及Radio参数。5G初值不能套用2.4G模型默认值；认证为None时隐藏密码并保留输入。
- 原`dut_status_query_service`将SSID索引传入`dut_wifi_config.query_wifi_status`；原core实际查询两个频段，按厂商映射解析SSID/AP/Radio。只有全部目标成功且完整参数一致才回填，不把第一台作为共同配置。
- 原`build_dut_wifi_settings_sequence`负责UTF-8长度和数字尾缀递增；只有勾选递增且目标数大于1时使用原`shared_wifi_settle`路径：批量apply收敛、一次60秒等待、按原workers回读。普通批次和单目标递增保持原单台configure→60秒等待→verify。未改变等待、重试、并发上限、命令或判据。
- 原5项纯WiFi展示常量/函数原文共享到`src/models/dut_wifi_form.py`，旧Tk保留导入API；与前轮WAN累计16项移动定义、旧Tk剩余29项定义AST完全一致，含整个DutConfigWindow类。没有搬迁旧GUI生命周期或设备业务。
- 第一轮在打开原生窗口前被输入桌面权限拦截。负责人恢复可交互桌面后只读探针返回成功，后续使用同一套私有桌面守卫和 Windows QPA 取得实际运行证据。

## 已实现和验收状态

| 项目 | 当前结果 |
| --- | --- |
| 两频段完整表单 | SSID索引1–8、名称/密码/认证、启用/隐藏/WMM、双频、递增、主/peer信道/带宽/协议、公共功率/接入数已接入 |
| 原默认值与显隐 | 与原Tk默认赋值自动对照；密码默认隐藏，可切换显示；None认证保留已填密码 |
| 真实查询能力 | 直接调用原查询；支持列表由本机收到的实际结果/原兜底规则派生，客户端不能伪造supported字段 |
| 一致回填和失效 | 全部一致才回填；目标/凭据/索引改变后旧结果不覆盖新输入；确认再次核对项目配置、NIC和查询版本 |
| 任务与停止 | 原Job/资源/批量/单台/core路径；确认取消零下发，切页/关闭显示不取消任务；等待中停止不把未校验结果计成功 |
| 私有字段 | GUI专用完整回填保留实际密码；确认/持久任务/结果/Qt日志去除登录和WiFi密钥，实际下发值不变 |
| 布局实现 | 三档原生验证宽二列、窄一列、标签及控件不重叠、无横向滚动、底部操作可见、结果可纵向滚动访问 |
| 线程/定时器 | 延用后台Job与原主线程事件轮询，没有新UI定时器/日志订阅，后台不操作控件 |
| 现场验收 | 真实设备、Windows 系统缩放与实体多屏、长期挂测待负责人验证 |

## 修改文件

相对主源码目录：

| 文件 | 用途 |
| --- | --- |
| `src/models/dut_wifi_form.py`（新） | 原WiFi展示映射/候选及原两频段默认参数，无GUI依赖 |
| `src/ui/dut_config_window.py` | 5项纯定义共享导入，旧类AST保持 |
| `src/services/qt_dut_wifi.py`（新） | 本机参数投影、真实能力缓存/复核、原序列校验和安全记录 |
| `src/services/qt_dut_configuration.py` | 四种WiFi查询/配置动作、原Job调用、私有回填与密钥过滤 |
| `src/ui/qt/dut_wifi_panel.py`（新） | 两频段完整表单、共享双频、真实选项、显隐/密码、弹性排列 |
| `src/ui/qt/dut_configuration_dialog.py` | 启用WiFi标签、原目标/凭据共用、结果与失效绑定 |
| `src/ui/qt/workspace_controller.py` | 已接入功能入口说明 |
| `tests/qt_wifi_fakes.py`（新） | 原batch/single/core配字典UBUS和假时间，不另造业务引擎 |
| `tests/test_qt_dut_wifi.py`（新） | 16项原逻辑/参数/能力/停止/隐私回归 |
| `tests/qt_workbench_probe.py` | 两项强制 WiFi 原生用例、稳定布局截图、原通道用例等待界面解锁 |
| `scripts/verify_baseline.py` | 新源码编译登记及4项必执行回归 |
| `scripts/verify_qt_migration.py` | 原生必执行清单增加两项，不降低隔离要求 |
| `scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json` | 动作审查及真实接入范围 |
| `validation/pyside6_migration_20261118/verify_wifi{,_delivery}.py`（新） | 累计AST等价/业务保全及顺序验证记录 |
| `line_check_assistant_README.md` | 已实现操作与待验收范围 |

另新增[语音/TR069只读审计](NEXT_VOICE_TR069_AUDIT.md)，同步根`README.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`、`CAPABILITY_COVERAGE.md`、`.claude/plans/pyside6-migration.md`及本目录进度/审计导航。保留此前工作区其它改动；未暂存/提交。

## 实际验证和失败记录

在主源码目录、标准仓库外CPython3.9.10、父子进程UTF-8下：

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
python validation/pyside6_migration_20261118/verify_wifi_delivery.py
```

- 58项相关回归通过：16项新增WiFi、14项WAN、17项DUT Telnet、11项开关机适配。Fake仅替代物理网络/UBUS/时间，实际使用原批量、单台、解析、下发和回读。覆盖单/批等待分支、双频公共功率、原厂商映射/索引、能力防伪、不一致不回填、取消/过期/查询变化、停止未校验、回读不符为未知、密码转义及不泄露。
- 源码及AST门禁通过：303份编译、293份源码登记、能力/GUI覆盖及协议不变量；162份原core/services、38份旧业务Python、7份本机配置及原app.py字节不变；累计16项提取定义/剩余29项定义AST一致。原生用例仅语法编译通过，不能据此记为已执行。
- 初次原生记录三档均在GUI创建前报`Cannot verify current input desktop`。系统探针报OpenInputDesktop/WinError 5。初次完整基线运行3087项，2项原生隔离检查失败，其它门禁通过。初次顺序结果保留各步退出码。
- 恢复桌面后的首轮原生记录中两项新WiFi用例各档通过，100%与150%档的原通道用例在编辑器释放后、界面快照尚未解锁时发起测试。调整用例等待启动按钮真正可用，再从按钮发起操作。
- 修正后全套原生共33×3=99项通过，每档511个受管窗口、违规0。密码开关移到对应输入旁，嵌套编辑控件取消重复输入框样式，切换设备配置页回到表单顶部。原生截图复查发现缩放时的第二轮布局需等待，因此增加稳定高度和行间不重叠断言，用于最终截图复采。
- 恢复后的完整基线通过，3087项测试、236项指定用例、303份编译、293份源码登记。505个GUI动作已审查登记，覆盖、协议不变量和原业务保全通过。截图复采只改显式原生用例，生产源码与完整基线时一致。
- 稳定布局截图复采的两项 WiFi 测试在100%、125%、150%共6项通过。等待外层滚动区和内层表单双重重排完成后再截图，并检查行间不重叠、内嵌文字控件落在下拉框内。

中间失败保留：首轮47项中两项测试误将原功率字符串当整数，并错误假定真实查询不含peer；按原core纠正断言，no-peer仅注入部分模型刻画共享helper兜底。另一次组合误写不存在的`test_qt_execution`导致导入失败；改用真实`test_qt_execution_adapter`，最终58项通过。未修改原业务以迎合测试。

## 改造前后截图及参考图差异

此前WiFi标签禁用，见改造前DUT窗口。下列改后图为 Windows 私有桌面上实际运行的源码界面，采用模拟 DUT。

| 场景 | 实际截图 |
| --- | --- |
| 2.4G 宽窗双列 | 1000×740 |
| 5G 宽窗双列 | 1000×740 |
| 2.4G 窄窗与结果区 | 560×460，125% · 滚动到底 |
| 5G 窄窗与结果区 | 560×460，150% · 滚动到底 |

参考图未展示独立 WiFi 参数弹窗。本轮沿用工作台配色、按钮层级及紧凑输入，窄窗需要纵向滚动。对照总览和详情，当前主窗口已有青色导航、状态卡片、通道矩阵、配置侧栏和日志区。参考图中的告警总表、系统健康与老化探针趋势仍待真实数据接入。原窗口几何恢复及与后续写参窗口共享输入的联动待补。

## 下一步及回退边界

三档原生全套已覆盖WiFi和前序模块，包括WAN最后的确认端口文案版本。WiFi阶段自动化门禁通过，现场验收另行记录。

后续继续DUT语音/TR069，然后升级、写参、ONU、AI/平台、完整日志/历史、多项目兼容、可靠性及Qt构建部署，见[完整迁移进度](MIGRATION_PROGRESS.md)。持续开机全业务老化按负责人确认保持待接入，不在UI迁移内发明检测引擎。

原Tk功能及同名导入API保留；本次没有修改设备服务/配置值。需要回退本增量时，仅回退上述WiFi控制面、共享导入和相应登记，不覆盖其它增量。真实WiFi配置、源IP/网卡、设备差异、1/8台异常/停止和长期稳定性只能依据负责人现场结果。未连接真实设备/串口、修改真实网卡或发送外部消息。
