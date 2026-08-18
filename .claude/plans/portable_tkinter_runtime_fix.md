# 免安装版Tkinter运行时修复

## 现场问题

目标电脑启动便携版时，PyInstaller运行时hook在程序主入口之前报错：`Tcl data directory ...\_MEI...\tcl not found`。

## 根因

- PyInstaller 5.10.1的`pyi_rth__tkinter`固定读取`sys._MEIPASS/tcl`和`sys._MEIPASS/tk`。
- 项目自定义`hook-_tkinter.py`却把正确资源收集到`_tcl_data/_tk_data`。
- 首版发布检查只覆盖PE头、ZIP、哈希和配置脱敏，没有检查EXE内部资源目录。

## 修复

1. 自定义hook按本机`_tkinter`版本定位源目录，目标固定为`tcl`和`tk`。
2. 源Tcl/Tk目录不存在时让构建直接失败。
3. PyInstaller结束后读取实际EXE归档，必须命中`tcl\init.tcl`和`tk\tk.tcl`才继续生成便携包。
4. 单元回归保护hook目标名、关键源文件和构建门禁，加入强制基线。

## 验证边界

- 当前电脑只读检查EXE归档、ZIP、哈希和脱敏配置，不启动新EXE。
- 目标电脑必须删除旧解压目录、重新完整解压新ZIP并启动复验；用户反馈前不宣称桌面启动验收通过。
