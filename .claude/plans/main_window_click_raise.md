# 主界面点击升到二级窗口前方

## 目标

- 打开DUT配置、样机升级、写样机参数、ONU注册、测试项配置、全流程执行或串口日志后，点击主界面任意可见位置即可把主界面升到这些非模态窗口前方。
- 二级窗口保持打开、状态不重建；再次点击对应功能按钮仍可把该二级窗口升到前方。

## 边界

- 移除持久非模态功能窗口对主界面的`transient`所有者关系，避免Windows强制子窗口始终压住主界面。
- 主窗口统一监听鼠标按下并执行`lift()`，不调用`focus_force()`，避免抢走操作员刚点击的输入控件焦点。
- 参数生成、程控电源选择、确认/警告等必须先完成的模态窗口继续保留`transient + grab`，不允许绕过确认。
- 不改变二级窗口首次居中、客户区刷新、窗口尺寸记忆、运行/停止或关闭语义。

## 修改与验证

- 修改`line_check_assistant/app.py`、`src/ui/dut_config_window.py`和`line_check_assistant/pipeline_window.py`的窗口层级接线。
- 在`tests/test_app.py`增加主界面点击升层、非模态窗口无transient及模态窗口保持grab的回归，并纳入强制基线。
- 同步操作员README、项目状态、验收基线和开发记录；运行`python scripts\verify_baseline.py`与`git diff --check`。
