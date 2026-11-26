# 程控电源跨项目通道共享验证报告（2026-11-25）

## 已实现行为

- Qt 工作区按保存的 COM 和启用通道登记，通道归属独立于运行任务。停止或完成任务后仍保留登记，保存解绑或项目安全关闭后释放。历史重复配置可打开，但未登记通道不能执行。
- 同一 COM 可供不同项目分别执行所属通道。正式 Telnet/SSH 挂测、续跑、单次上下电、全流程及受控升级复用逐帧串口发送保护。每条指令完整发送后关闭串口，原断电、启动、升级等待和判据保留。
- 本机同进程请求按 COM 排队，跨进程采用主机级互斥；等待超时为 30 秒。挂测和单次上下电的未下发等待请求可取消。已登记的电源口不能作为普通串口整口取得。
- Qt 环境配置实时反映其他项目占用通道，置灰且全选跳过；已保存冲突可解除勾选，保存及执行前复核。资源监控显示登记与实时发送状态。重启或刷新资源可核实并恢复异常退出后残留的登记。

## 自动验证

- 专项回归：236 项通过；随后补充的 90、197、136、159、61、124 项相关检查分别通过。最终源码及 Fake 资源隔离完成后，302 项相关测试全部通过，窗口隔离预检及运行时守卫通过。覆盖同一 COM 不同通道双项目运行、重复保存拒绝、历史冲突打开、跨实例资源冲突、改名显示、关闭释放、逐帧关闭、等待期间其他项目写入、等待停止、初始断电、旧子进程保护及升级原时序。测试批次有交集，不累加为唯一测试数。
- 第二次完整基线 `python scripts/verify_baseline.py` 退出 0，427 个编译文件、417 个源文件覆盖、3471 项单元测试、287 项必跑测试及协议、GUI/能力覆盖全部门禁通过。首次完整基线受并行工作区启动入口与能力清单变更影响失败，相关失败项复测通过。残留登记恢复补充后第三次基线与原生测试并行，模拟 COM102 的主机全局互斥发生竞争，3473 项中 3 项断言及 7 项错误；随后将相关 Fake 测试接入项目既有的按进程隔离资源命名空间。第四次基线执行 3473 项，6 项断言失败、14 项错误，主要为其他进程持有 VLAN116 引起的能力/远程升级测试准入失败、并行清单变化及既有 Tk 焦点和心跳测试失败。本机保护数据库只读核对 `adapter:vlan116`、`power-channel:com102:1` 均为 active，保留实际资源及生产锁。最终 302 项相关回归、能力覆盖、局部编译和差异复查通过；最新完整基线未通过，待实际占用解除、工作区稳定后复验，保留最近一次完整通过记录。
- Qt 最终专项 `python scripts/verify_qt_migration.py --output validation/power_channel_sharing_20261125/final` 退出 0，100%、125%、150% 各 160 项通过，每档 743 个受管窗口，隔离违规 0，必跑缺失 0。[最终结果](final/results.json) · [100% 日志](final/scale-1/tests.txt) · [125% 日志](final/scale-1.25/tests.txt) · [150% 日志](final/scale-1.5/tests.txt)
- 首轮 Qt 专项在 100% 和 125% 档仍使用旧单次打开串口次数断言，150% 档实际 160 项通过但运行中并行更新了必跑清单。对应断言更新后，三档两项电源相关原生复测均通过，随后上述完整专项通过。[针对性复测](retest/results.json) · [初次结果](results.json)
- 能力覆盖更新及检查、GUI 预检、修改模块编译与差异检查均通过。未构建 EXE，未连接真实程控电源或 DUT。

## 验收范围

真实串口的跨项目共享、实际电源输出、长时间挂测，以及新版使用周期下的真实样机升级待项目负责人现场复验。现场建议使用两个已确认接线的独立 DUT 通道，核对等待阶段 COM 口可释放、另一项目仍能正常控制其通道，且原测试轮次结果准确。

过程 PNG 为开发验证生成，无报告引用。最终三档原生全套复验通过后，核对本批次目录解析结果和 Git 跟踪清单，将 877 张过程 PNG 全部移入回收站，剩余 0 张；完整测试文本、JSON 凭据及本报告保留。未操作其他验证目录或现场证据。

## 本轮涉及文件

以下路径以主源码目录为准。工作区原有及并行任务的其他改动保留。

- 底层串口及锁：`src/core/power_supply.py`、`src/core/host_resource_lock.py`。
- 资源、项目与配置：`src/services/workspace_resources.py`、`src/services/workspace_service.py`、`src/services/project_store.py`、`src/services/resource_lease_service.py`、`src/services/qt_channel_configuration.py`、`src/services/qt_project_wizard_service.py`。
- 执行业务：`src/services/capability_device_services.py`、`src/services/capability_service.py`、`src/services/pipeline_orchestrator.py`、`src/services/legacy_power_test_service.py`、`src/services/power_on_service.py`、`src/services/qt_single_power.py`、`src/services/physical_resource_guards.py`、`src/services/serial_upgrade_service.py`、`src/services/qt_execution_adapter.py`、`src/services/qt_workspace_adapter.py`。
- Qt 界面：`src/ui/qt/channel_configuration_dialog.py`、`src/ui/qt/workspace_controller.py`、`src/ui/qt/device_inventory_dialog.py`。
- 自动回归：`tests/test_power_supply.py`、`tests/test_legacy_power_initialization.py`、`tests/test_project_management.py`、`tests/qt_execution_fakes.py`、`tests/test_qt_execution_adapter.py`、`tests/test_serial_upgrade_service.py`、`tests/test_qt_channel_configuration.py`、`tests/test_qt_workspace_adapter.py`、`tests/test_qt_dut_configuration.py`、`tests/qt_workbench_probe.py`。
- 文档及能力覆盖：`line_check_assistant_README.md`、`scripts/capability_gui_actions.json`、根目录 `ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`、`CAPABILITY_COVERAGE.md`。
