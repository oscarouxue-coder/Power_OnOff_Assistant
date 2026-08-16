# DUT WiFi SSID递增

## 目标

- 2.4G与5G WiFi页分别增加“SSID递增”勾选项，默认关闭。
- 开启后以当前SSID的数字尾缀为起点，按DUT窗口已勾选目标的固定表格顺序逐台加1并保持数字宽度。
- 配置确认框和主执行日志逐台展示最终SSID；查询只读取设备现状，不参与递增。

## 规则

- 未开启时保持所有已选目标使用同一SSID的现有行为。
- 开启时SSID必须以数字结尾；否则在下发前拒绝并提示，不自动追加数字。
- 第一台使用输入值，后续目标递增；批次请求生成后映射冻结，单台重试复用同一SSID。
- 每个生成结果按UTF-8校验不超过32字节；任一结果超限时整批拒绝。
- 2.4G与5G选项互相独立；双频合一仍由每台请求的最终SSID同步到两个频段。

## 分层

- `src/services/dut_advanced_config_service.py`：生成、校验逐台SSID与逐台WiFi settings。
- `src/ui/dut_config_window.py`：两个WiFi页的独立勾选输入和提示文案。
- `line_check_assistant/app.py`：按DUT窗口选择顺序组装请求、预检提示、确认预览及日志。
- `tests/`：尾缀规则、前导零、UTF-8长度、非法输入、独立选项、逐台请求和日志/确认接线。

## 验证

- 运行DUT高级配置service与主程序专项测试。
- 运行`python scripts\verify_baseline.py`和`git diff --check`。
- 同步操作员README、项目状态、验收基线和开发记录；自动化测试不替代Windows桌面及真实DUT验收。
