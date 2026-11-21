# 下一DUT增量：WiFi代码审计入口

后续进度：以下为实施前审计；WiFi源码/模拟接入已经按该边界完成，最新结果和未通过的原生门禁见[WiFi报告](WIFI_REPORT.md)。不以本审计替代实现或验收证据。

2026-11-18，WAN源代码和模拟验证后、最后原生因桌面不可读待复验时进行。此文件是下一步审计，不代表WiFi已经迁移；本轮未改WiFi原业务/默认值、未调用真实设备。

- 原Tk`dut_config_window.py`内`wifi_status_form_values`及能力候选辅助逻辑映射公共参数/两套Radio；`wifi_settings`收集活动频段、SSID索引、隐藏/启用/WMM、认证/密码、发射功率及peer_radio。`wifi_dual_band_var`是两个页共享的一个布尔量，不能新建两套互不一致状态。
- 两页字段初值、密码在None认证下显隐、双频区域、SSID递增和查询索引联动仍需逐段核对；不能用`DutWifiSettings`的2.4G默认值覆盖原5G表单值。实际能力来自查询快照及原候选/兜底函数，不假定所有DUT支持相同信道/带宽/认证。
- `dut_status_query_service.run_dut_status_query_batch`已支持wifi_2g/wifi_5g，查询参数有SSID索引；`common_dut_status_settings`只有所有目标成功且完整settings一致才给回填。查询与配置校验分离，空配置表单不能阻止只读查询。
- `dut_advanced_config_service.build_dut_wifi_settings_sequence`保留SSID数字尾缀宽度和UTF-8长度校验；原app只有勾选SSID递增且目标数大于1时传`shared_wifi_settle=True`，不能把所有并发WiFi批次默认改成统一等待。
- 原批量统一等待路径是全部apply成功/失败收敛后，对已下发目标统一stop-aware等待`WIFI_APPLY_SETTLE_SECONDS`，再回读；停止后未回读必须保持未校验/停止结果，不把下发成功当作最终成功。普通`dut_wifi_config.configure_wifi`仍是原单台apply→60秒稳定→verify流程，GUI不能改变等待、重试或判据。
  - 实际回读调用仍是同一个`run_phase`及其原workers，文案“逐台”不等于新增串行调度；Qt不得擅自改为单线程验证或改变校验节拍。
- 继续复用原core的路径解析/双频映射/回读断言和原批量service；Qt只做字段、真实查询能力、确认/任务/结果和私有密码回填。测试以原batch/single/core配Fake边界验证，不另写一套模拟业务引擎。
- 如共享纯WiFi展示函数，沿WAN方法原文提取、旧导入代理、AST等价、原Tk回归和完整基线，保持DutConfigWindow类/设备服务不搬迁。涉及改动原设备流程或真实硬件时先等负责人确认。

原生环境先读取输入桌面状态；目前已确认OpenInputDesktop失败/WinError 5，不能推断确切锁屏原因，不能绕过守卫、SwitchDesktop或退回用户桌面。恢复后先补WAN端口文案的最新原生证据，再验证新增WiFi界面。源码/模拟工作可以继续，但整个Phase 5及完整迁移均未完成。
