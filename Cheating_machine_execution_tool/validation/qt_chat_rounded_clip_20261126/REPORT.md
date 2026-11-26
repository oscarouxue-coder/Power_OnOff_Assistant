# Qt 圆角气泡滚动裁切——独立内存补证（2026-11-26）

不重复 [原 8 项](../qt_chat_rounded_bubbles_20261126/REPORT.md)。选此前未直接验的滚动坐标与局部裁切。现有 `AiChatTranscript.paintEvent` 先按事件脏矩形设置 clip，再按水平和垂直滚动值平移，使用文档坐标可见区判断后调用实际 `_draw_rounded_bubble`；原文本仍由 QTextEdit 绘制。

[独立探针](clip_probe.py) 使用真实内存 QImage/QPainter，完全合成区域：画布 120×90，脏矩形 70×60，滚动偏移 (18,90)，两个部分可见的不同角色圆角及一个完全不可见的圆角。按现有 paintEvent 的实际裁切/平移顺序和绘制函数执行，核对两处角色色、气泡间留白、不可见区域跳过，并逐像素核对裁切外 **6,600 个像素全部不变**。未构造 QWidget 或真实文档布局；不能据此认定实际滚动/选择文本事件及叠加像素已经验收。

使用原 `scripts/run_tests.py` 单进程入口仅运行 `clip_probe.RoundedClipProbe`。禁止外部子进程、socket 建连/发送目标和外部打开。实际输出：

```text
GUI_TEST_COVERAGE_OK
test_scrolled_dirty_rectangle_does_not_paint_outside_visible_region (clip_probe.RoundedClipProbe) ... ok
Ran 1 test in 0.962s
OK
GUI_RUNTIME_REPORT: {'passed': True, 'managed_windows': 0, 'violations': [], 'isolation': 'offscreen', 'desktop': None}
prohibited_io_calls 0
```

退出 0。未复现新的裁切缺陷，因此不改生产代码或既有测试。原 Qt 私有桌面需要子进程，本轮禁用，不绕过守卫、不生成截图、不启动模型、设备、网络、真实数据、CLI 或挂测，不改权限/规则，不进行 Git 写或完整门禁。真实 Qt 窗口的滚动、选择和实际视觉仍待独立验收。
