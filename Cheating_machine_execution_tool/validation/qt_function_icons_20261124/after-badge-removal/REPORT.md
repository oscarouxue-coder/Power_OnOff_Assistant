# 移除工具栏绿色 D 标记

本次产品源码改动为 `src/ui/qt/main_window.py` 删除三行。工具栏中的 `label('D')` 是局部静态 QLabel，只有创建、对自身设置内联样式和加入布局三处引用。删除前按完整样式字符串检查 `src/`，仅命中此处。现有侧栏按钮、DUTPilot 名称及「统一测试工作台」按原顺序相邻显示。

## 同场景截图

三批截图使用同一组离线合成快照。「原基线」是功能图标优化前的原图，「去标前」是功能图标优化后的上一批交付，「本次」为去掉绿色 D 的结果。普通与窄窗口各有三组尺寸匹配的总览。最后两列补充正式菜单装配和测试记录。

| Qt 缩放 | 普通总览 | 窄窗口总览 | 完整工作区菜单 | Windows 原生验证 |
| --- | --- | --- | --- | --- |
| 100% | [原基线](../before/overview-1.png) · [去标前](../after/overview-1.png) · [本次](overview-1.png) | [原基线](../before/narrow-1.png) · [去标前](../after/narrow-1.png) · [本次](narrow-1.png) | [普通](workspace-detail-1.png) · [窄窗展开](workspace-narrow-1.png) | [结果](checks-1.txt) · [隔离证据](isolation-1.json) |
| 125% | [原基线](../before/overview-1.25.png) · [去标前](../after/overview-1.25.png) · [本次](overview-1.25.png) | [原基线](../before/narrow-1.25.png) · [去标前](../after/narrow-1.25.png) · [本次](narrow-1.25.png) | [普通](workspace-detail-1.25.png) · [窄窗展开](workspace-narrow-1.25.png) | [结果](checks-1.25.txt) · [隔离证据](isolation-1.25.json) |
| 150% | [原基线](../before/overview-1.5.png) · [去标前](../after/overview-1.5.png) · [本次](overview-1.5.png) | [原基线](../before/narrow-1.5.png) · [去标前](../after/narrow-1.5.png) · [本次](narrow-1.5.png) | [普通](workspace-detail-1.5.png) · [窄窗展开](workspace-narrow-1.5.png) | [结果](checks-1.5.txt) · [隔离证据](isolation-1.5.json) |

## 验证范围

每档 3 项均通过。普通和 800 × 520 窄窗口中，侧栏按钮在两次键盘激活后回到初始状态；品牌名称与副标题可见，六项总览计数一致。正式菜单使用模拟工作区适配器，验证了设置菜单与项目菜单的原绑定、菜单项及窄窗口下的访问。

应用图标检查在非输入桌面的测试进程内调用正式 Qt 启动器的图标初始化，并复用守卫已创建的 QApplication。逐帧比对主窗口继承的 Qt 图像与 `DUTPilot-01.ico`。通过 Win32 读取主窗口实际提供的大小图标，与同一私有桌面上显式加载 01 的参考窗口逐像素比对，两者一致。首轮直接比较 Windows 原生图像与 Qt 内存图像时未通过；最终两侧使用同一 Windows 渲染路径。任务栏外观未在用户桌面目视复验。

从主源码目录执行：

```text
python -X utf8 validation\qt_function_icons_20261124\verify.py after-badge-removal
python -X utf8 -m py_compile src\ui\qt\main_window.py tests\qt_function_icons_probe.py validation\qt_function_icons_20261124\verify.py
python -X utf8 scripts\verify_capability_coverage.py --update
python -X utf8 scripts\verify_capability_coverage.py
git diff --check
```

专用测试位于 `tests/qt_function_icons_probe.py`，运行入口为本报告上一级的 `verify.py`。GUI 清单中 818 条动作表达式和出现次数相同，仅更新了主窗口文件指纹。隔离违规为零，测试退出时 Python 有一条对象回收提示，详见原始测试文本。

本批保留 12 张报告引用的 PNG，额外过程图 0 张，清理 0 张。原 before、after 证据和 01 图标文件已核对指纹。本轮未运行完整基线、打包或连接真实设备。
