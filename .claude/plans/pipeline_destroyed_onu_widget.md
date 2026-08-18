# 修复全流程读取已销毁 ONU 控件

## 目标

1. ONU 注册窗口关闭后，全流程刷新状态不得读取已销毁的 C600 业务映射 Text。
2. 关闭窗口前保存的最新 ONU 配置必须同步回主程序内存缓存，供全流程读取。
3. 增加真实跨模块调用回归并纳入强制基线，覆盖“打开并关闭 ONU 窗口后刷新全流程”的生命周期。

## 实施边界

- 仅修复本机 Tk 配置读取和回归测试，不改变 C300/C600 命令、注册流程或真实 OLT 状态。
- 存活的 ONU 窗口继续优先读取当前 Text 输入；窗口已关闭时读取最近保存的内存配置。
- 不打包、不执行真实设备命令。

## 验证

- `python -m unittest discover -s tests -p test_app.py`
- `python -m unittest discover -s tests -p test_pipeline_window.py`
- `python scripts/verify_baseline.py`
- `git diff --check`
