# DUTPilot Qt迁移：六标签配置编辑交付

> 本报告所列的部分截图和测试输出已在对应验证通过后清理，测试结论与复跑方法见正文。

后续检查点：通道配置与矩阵/列表已由下一轮交付，见[通道阶段报告](CHANNELS_REPORT.md)。下文为六标签阶段当时的文件、结果及待办记录。

2026-11-18，分支`feature/pyside6-migration`。本轮继续负责人所给迁移计划，完成Phase 5的测试配置编辑/保存垂直模块，**不是整个Phase 5或整套GUI迁移完成**。原Tk与版本V1.2.10保留；未提交、推送、打包或运行EXE。

## 审计与本轮边界

实际旧界面在`line_check_assistant/app.py::_open_test_item_config`及其六个Tab构建函数，消息推送界面在`src/ui/message_push_tab.py`。旧界面直接调用三个存储服务，保存后调用原工作区提交项目版本；运行参数中部分键本就隐藏，不能因迁移遗漏或重置。旧命令期望分段按AND组合、每段独立否定；全局重试间隔只写`config.ini [other_config]`。Telnet默认开关与旧`telnet_enable`反向同步，废弃密码探测值固定0。WiFi高级选项通过原`validate_wifi_options`检查。没有把这些业务含义写进Qt控件或重写原store。

本轮新增：

- 六标签QDialog：Telnet、测试项、WiFi、项目信息、开关机运行参数、消息推送。
- 标签/输入对齐、统一主题、短数字框140逻辑像素上限、普通输入460上限、底部固定操作、逐页纵向滚动；密码/推送凭据默认隐藏并支持显隐。空值、未知枚举、隐藏运行键和关闭/禁用选项的原值保留，不擅自补默认值。
- 命令/期望分段增删、逐段否定、原默认模板草稿、WiFi只读枚举；网卡刷新保留原非空选择，仅空选择补首项，不扫描、连接或断开WiFi。默认命令恢复不写盘、不改变当前全局重试间隔。
- 保存、关闭、重载、dirty确认、保存期间防止提前关闭；跨项目切页后已打开编辑器仍绑定原project_id。编辑租约阻止同项目启动和其它保存/重命名/复制/关闭，任务执行/收尾时拒绝打开或保存。
- GUI专用`configuration.editor.*`注册到原CapabilityService，只接受`gui`来源，不能由`local`模型或远程来源读写私有字段；不将密码/Token等值写入日志、异常或任务载荷。原104项业务覆盖状态保持，动作快照现469项。
- 保存先复核项目/文件版本，在独立暂存目录按原`TestItemConfigStore.save → LegacyUiDefaultsStore.save → MessagePushConfigService.save`序列化，再更新草稿并调用原ProjectStore提交修订。失败恢复原草稿，恢复失败保留原主机协调器的未知保护。项目UUID/格式不变，不另建项目数据库或任务存储。

尚未开放的原执行按钮保持明确禁用及提示：草稿预备测试、设备版本查询、消息试发。它们必须以后按原草稿/确认/资源语义接入，不能用执行“已保存配置”的入口冒充。其它通道配置/串口/DUT/升级/写参/ONU/AI/平台及历史日志功能也未由本轮代替。持续开机老化继续待接入。

## 文件清单

相对主源码目录：

| 文件 | 用途 |
| --- | --- |
| `src/models/qt_configuration.py` | 本机私有编辑快照，repr不含配置值 |
| `src/services/qt_configuration_service.py` | 原store事务、版本/租约校验及GUI专用能力 |
| `src/ui/qt/configuration_dialog.py` | 六标签表单、动态命令/分段及保存/重载/关闭交互 |
| `src/services/qt_execution_adapter.py` | 注册编辑控制、编辑与任务准入互斥 |
| `src/services/qt_workspace_adapter.py` | 后台配置命令、输入快照、错误隐私及项目操作保护 |
| `src/models/workbench_presentation.py` | 配置可编辑/编辑中展示字段 |
| `src/ui/qt/project_detail.py` | 接通“编辑配置” |
| `src/ui/qt/workspace_controller.py` | 项目绑定、异步结果和窗口/租约生命周期 |
| `src/ui/qt/theme.py` | 配置页/Tab主题 |
| `tests/test_qt_configuration_service.py` | 14项新增服务回归 |
| `tests/qt_workbench_probe.py` | 六标签保存重开、取消重载、跨项目绑定、保存期间响应与截图 |
| `scripts/verify_qt_migration.py` | 全部20项原生用例及三档门禁 |
| `scripts/verify_baseline.py` | 新源文件编译及4项关键回归ID登记 |
| `scripts/verify_capability_coverage.py`、`scripts/capability_gui_actions.json` | 控制边界审查与动作快照 |
| 本验证目录`verify_configuration.py`、`verify_phase3.py` | 共用只读源码检查，配置阶段写独立证据文件，不覆盖前轮结果 |

另同步根`README.md`、`PROJECT_STATUS.md`、`ACCEPTANCE_BASELINE.md`、`DEVELOPMENT_LOG.md`、`CAPABILITY_COVERAGE.md`、`.claude/plans/pyside6-migration.md`及操作员`line_check_assistant_README.md`、前阶段报告导航。原Tk构建函数、三个store、设备引擎和本机配置未修改。

## 改造前后截图与视觉核对

前：Phase 3详情，“编辑配置”未接入。本轮未重新捕获旧Tk配置窗口，不能把此前主窗口截图冒充旧配置弹窗。

后：真正Windows Qt窗口、原项目服务创建的临时验证项目，表单内容为测试值；由受管非输入私有桌面捕获，不切换用户桌面，不操作真实设备。

| 场景 | 实际截图 |
| --- | --- |
| Telnet、密码隐藏、是/否下拉与短数值框 | Telnet |
| 动态命令、重试、逐段否定 | 测试项 |
| WiFi模式/高级选项/网卡枚举 | WiFi |
| 项目信息 | 项目 |
| 原运行参数 | 运行参数 |
| 推送保存与凭据隐藏 | 消息推送 |
| 620×460逻辑尺寸、纵向滚动、底部操作 | 100%小窗口、150%小窗口 |
| 整体工作台仍保留 | 1366总览、1920总览 |

已核对：六标签无横向滚动，短数字不占满窗口，表单标签/输入对齐、隐藏密码、固定底部按钮、缩小时可纵向访问内容，100/125/150%指定Qt缩放均执行。大窗口保留统一表单区域，字段少的标签页不填假监控数据。未进行真实系统DPI切换/实体多屏/负责人正常桌面键鼠验收。

与负责人目标图仍有差异：整个主窗口告警中心/系统健康、全业务探针/趋势、通道配置/列表、完整日志/历史及其它业务页仍待后续。配置页执行按钮目前未全部接入，不能称为完整软件可替代Tk。

## 实际验证

| 范围 | 结果与证据 |
| --- | --- |
| 新服务用例 | 14项均在本轮相关组合实际执行：原保存序列字节等价、Telnet反向镜像、全局重试0、隐私/GUI来源、禁用值、过期/冲突、编辑/任务互斥、暂存/提交失败恢复、恢复失败未知保护、默认草稿/缺模板、WiFi只读枚举等 |
| 相关组合 | 156项首轮：155项通过，1项为本轮最后UI调整后的能力动作快照待更新；没有业务断言失败。审查469动作及GUI专用来源后更新快照，覆盖模块3项复验通过。不把分批结果描述为156项首次全绿 |
| 原生Qt | 20项×3档=60项全部通过，每档23受管顶层、违规0，全部指定ID执行，Windows QPA，核验私有桌面；含关闭/重开、保存期间响应、项目绑定、密码显隐、六页/小窗口截图 |
| 源码门禁 | 291编译、281源码登记、能力/GUI覆盖及全部协议项通过 |
| 原业务保全 | 与Phase 0备份对比的162份core/services、38份旧工具Python、7份非Python配置及原Tk app.py字节一致；检查范围由脚本明确列出，不替代设备验收 |
| 完整基线 | 本轮新增独立Qt模块及未验收Qt适配，未搬迁已验收Tk/业务，不触发/未运行完整基线；最近2981项是前轮结果 |
| 差异检查 | `git diff --check`通过；未构建、发布、运行EXE、操作设备或发送消息 |

相关回归使用标准隔离CPython3.9.10 x64（原环境无需安装Qt），统一`scripts/run_tests.py`，原Tk专项20个受管窗口、违规0。原生专项使用原独立Qt开发环境，不更换构建依赖。

可重复命令（主源码目录）：

```powershell
# 用项目验证过的Python运行相关专项；不是完整基线
python scripts/run_tests.py test_qt_configuration_service test_qt_execution_adapter test_qt_workspace_adapter test_qt_migration_contract test_test_item_config_store test_legacy_ui_defaults_store test_legacy_ui_defaults test_message_push_config test_capability_devices test_capability_settings test_capability_coverage test_verify_baseline -v
python scripts/verify_qt_migration.py --output validation/pyside6_migration_20261118/qt_configuration_acceptance
python validation/pyside6_migration_20261118/verify_configuration.py
```

保留失败记录：`qt_configuration_first`在关闭/重开测试等待编辑租约释放超时，并在失败清理路径发生Qt原生访问异常、缺少子进程证据，门禁正确判失败。复现确认新QDialog关闭处理仅accept事件、漏调基类，导致finished未发出；修正基类关闭后，单项及三档全量均通过。另`qt_configuration_final`中的新显隐测试最初点击了被布局撑大的复选框空白中点，未切换；限制复选框尺寸并在实际指示器位置执行原生鼠标点击后20×3通过。守卫未放宽、未新增跳过，不能把最早崩溃附近的某个Qt C++对象断言为已证明的独立根因。

## 待验收与下一边界

负责人正常Windows桌面核对六标签旧项目加载、保存/取消/重载、默认草稿、WiFi只读枚举、版本冲突/失败恢复、编辑任务互斥及跨项目绑定；系统DPI和多屏仍待人工确认。Qt原预备测试、版本查询、试发、通道配置、其它模块、日志/历史及打包继续逐项接入。真实DUT/平台/模型及24/72小时挂测结论不因本轮源码测试而升级。正常挂测继续原Tk入口。
