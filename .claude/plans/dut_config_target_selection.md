# DUT配置窗口独立目标选择

## 目标

- DUT配置六个Tab的目标表增加共享“选择”列及“全选/清除”按钮。
- 主界面已勾选通道仍是候选范围；DUT窗口首次加载时默认全选，操作员可缩小本次配置或查询范围。
- Telnet、WAN、2.4G/5G WiFi、语音和TR069的配置与只读查询都只处理DUT窗口内已选择目标。

## 交互边界

- 同一批主界面目标刷新时保留DUT窗口内的手动取消状态；主界面新增目标默认选中，已移除目标自动删除。
- 六个Tab共享同一目标选择，在任一Tab切换后其它Tab立即同步。
- 未选择任何目标时拒绝启动并明确提示在DUT目标表勾选；未选择目标的配置错误不阻止已选择目标执行。
- 批次运行期间禁用选择、全选和清除，停止与已有安全点语义不变。

## 分层

- `src/ui/dut_config_window.py`：目标选择状态、表格勾选交互和同步显示。
- `line_check_assistant/app.py`：按窗口选择过滤请求、重新校验、确认、查询与日志编排。
- `tests/test_app.py`：选择继承/保留、跨Tab同步、请求过滤和入口接线回归。

## 验证

- 运行 `python -m unittest discover -s tests -p test_app.py -v`。
- 运行 `python scripts\verify_baseline.py`。
- 同步操作员README、项目状态、验收基线和开发记录；自动化测试不替代Windows桌面及真实DUT验收。
