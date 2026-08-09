# DUT配置窗口宽高记忆计划

## 目标

- 关闭DUT配置窗口时保存当前宽度和高度。
- 下次打开时自动恢复上次关闭的窗口尺寸。
- 与六个Tab的当前状态高度共用本机状态文件且互不覆盖。
- 损坏、过小或超过当前屏幕的尺寸安全回退或收敛。

## 实现

1. 在`~/.aouxue_dut_config.json`增加`window_size.width/height`。
2. 创建窗口时先读取并按当前屏幕范围收敛，再调用`geometry()`。
3. 保持现有最小尺寸1530×880；关闭前读取窗口实际宽高并原子保存。
4. 状态高度和窗口尺寸写入均先合并现有JSON，避免任一功能覆盖另一功能。
5. 增加尺寸往返、跨屏幕收敛、非法值回退和状态高度兼容回归。

## 验证

- `python -m unittest discover -s tests -p "test_app.py" -v`
- `python scripts\verify_baseline.py`
- `git diff --check`
- Windows桌面调整DUT窗口宽高，关闭重开确认恢复。
