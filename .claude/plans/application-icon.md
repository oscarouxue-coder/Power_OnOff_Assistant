# 统一程序窗口与任务栏图标

负责人已确认：源码修复、打包资源配置和相关验证；本轮不打包、不提交、不发布。实施中追加“图标增加一下清晰度”，保留原网络拓扑与心跳标记。

## 实施边界

- 独立`src/ui/application_icon.py`负责源码/冻结资源路径、稳定任务栏标识、根窗口与Tk默认图标；`app.py`只接初始化和主日志。应用标识在创建Tk前设置，图标在创建后立即设置，结果在日志就绪后各记录一次。失败继续启动。
- 不逐个重写窗口、不修改全局Tk、事件、定时任务、焦点、模态关系、关闭或设备流程。系统语义图标和外部程序遵循原规则。
- 保留同一资源名称；EXE资源与归档运行时数据同源，归档漏图标或内容不一致阻止包校验。
- 原ICO四帧均为PNG，独立Windows专项发现Tk设置成功但实际HICON不等于文件图案。现导出16/20/24/32/40/48/64/96/128原生32位DIB及256 PNG，独立进程的实际大小HICON与Windows读取文件的ARGB和掩码逐字节一致。无需运行时图像转换或新依赖。
- 图像使用内置imagegen编辑，保存到项目原PNG；`scripts/create_application_icon.ps1`用Windows System.Drawing从同一PNG生成ICO，支持任意工作目录和显式输出路径。本轮未新增应用依赖，未修改锁定环境。

## 验证记录（2026-11-13）

使用标准独立CPython 3.9.10 x64环境，在主源码目录执行：

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$iconPython = Join-Path $env:LOCALAPPDATA 'LineCheckAssistant\build-env-py39\Scripts\python.exe'
& $iconPython -X utf8 -m unittest discover -s tests -p 'test_application_icon*.py' -v
& $iconPython -X utf8 -m unittest discover -s tests -p test_portable_release.py -v
& $iconPython -X utf8 -m unittest discover -s tests -p test_app.py -v
```

- 图标专项18项、现有打包专项10项、主程序相关专项221项，合计249项通过。专项包含模拟冻结/中文空格/不同工作目录、损坏/缺失资源、Tk/API失败、非Windows跳过、实际主入口初始化先后顺序、打包缺失/内容不同及导出再现一致性。
- 独立限时Windows Tk进程在屏幕外验证4个窗口8个大小图标、已有/嵌套/重开继承、无新增事件/定时任务及任务栏标识回读；不操作设备或现有进程。已有测试隔离工具只用于测试，不进入程序。
- 8个Python/spec文件局部py_compile通过；直接调用`check_py_compile_inventory`通过，153个源码已覆盖；没有运行完整基线或构建入口`-CheckOnly`。
- 图标文件原生尺寸预览已检查；computer-use初始化后`sky.list_windows()`返回native pipe连接不可用，因此完整程序标题栏、Alt+Tab和实际任务栏目视仍待负责人确认，未将独立测试替代目视验收。后续新包须在目标电脑验证，不在打包电脑运行。
- 首轮测试曾暴露Windows短/长临时路径与测试模块导入差异，已修正测试；原全PNG ICO的实际图案不一致由DIB资源解决，最终专项全通过。

## 图像编辑提示词（内置 imagegen）

输入为项目原`assets/icons/line_check_assistant_network_topology_v1.png`；输出覆盖同名项目PNG并生成同名ICO，不依赖Codex生成目录。最终提示词：

> Use case: precise-object-edit. Edit target: the attached existing LineCheckAssistant software icon. Primary request: improve sharpness and small-size legibility while faithfully preserving its design. Keep exactly the central dark navy hexagon with the white heartbeat/pulse symbol, the three cyan network arms, and three blue circular nodes at top, lower-left and lower-right with white rings. Keep the same orientation, balanced geometry, navy/cyan/blue/white palette and transparent background. Produce a single crisp square high-resolution application icon, flat vector-like precision, smooth clean sharply defined edges, uniform bold shapes and high contrast readable at Windows title-bar 16px and taskbar 32px. Simplify only faint texture/soft gradients, remove fuzzy/jagged edge halos, sharpen pulse corners and circles. Do not add text, letters, extra objects, shadows, blur, glow, border, background, platform mockup or multiple variants. Fill the canvas with the mark with only about 4% clear padding; do not clip any node. Actual alpha transparency. This is an enhancement of the existing mark, not a new logo.
