# C600 业务分层与可选 write

## 目标

- C600 上网业务默认使用 `WT-10G`。
- 按业务 VLAN 固定拆分四组上行资源：上网、语音、组播、TR069。
- 保持 NP7287XGS 已验证的 `real-speed=auto`，不自动下发该型号拒绝的命令。
- 增加 C600 `write` 本次授权选项：默认关闭、不持久化，仅在注册上线和完整只读验证成功后执行。
- 使用一台当前未注册 ONU 做真实注册、write、精确删除和第二次 write 清理验证。

## 兼容与安全边界

- 继续使用可编辑的 `ServiceID,VLAN` 输入；按 VLAN 派生业务层：
  - 上网：170/171/172/173/151/150 以及未定义的普通 VLAN → 用户设置的主 T-CONT/GEM，默认 `1/1 + WT-10G`
  - 语音：335 → `T-CONT 2 / DBA_FONE / GEM 2`
  - 组播：600 → `T-CONT 3 / DBA_IPTV / GEM 3`，保留 `mvlan 600`
  - TR069：50 → `T-CONT 4 / DBA_TR069 / GEM 4`
- 只为实际出现的业务创建对应 T-CONT/GEM；拒绝主 T-CONT/GEM 与固定业务 ID 冲突。
- VPort/service-port VLAN 映射保持原语法和编号。
- C600 write 选项不写入 INI，每次新开 ONU 注册窗口恢复关闭；确认框明确显示本次选择。
- 真实验证只处理预检确认的目标 ONU；不执行自动回滚、不处理其他未注册 ONU。
- write 验证后必须删除同一测试 ONU、回读确认 ID/SN 释放，再执行第二次 write 保存清理状态。

## 修改范围

- `src/core/zte_c600_onu.py`：业务分层命令、校验和回读验证；允许独立 write。
- `line_check_assistant/onu_registration_store.py`：上网 DBA 默认值改为 `WT-10G`。
- `line_check_assistant/app.py`：业务层提示、C600 write 本次选项、确认及成功后保存流程。
- `tests/test_onu_registration_service.py`、`tests/test_onu_registration_store.py`、`tests/test_app.py`：回归覆盖。
- `line_check_assistant_README.md`、`ACCEPTANCE_BASELINE.md`、`PROJECT_STATUS.md`、`DEVELOPMENT_LOG.md`：行为、状态和验证证据。

## 验证

1. ONU 注册专项测试、store 和 UI 专项测试。
2. `python scripts/verify_baseline.py`。
3. 真实 C600：未注册发现与精确 ID/SN 预检 → 分层下发 → working → 四组回读 → write → 精确删除 → ID/SN/未注册回读 → write。
4. 不构建、不运行 `dist\LineCheckAssistant.exe`。
