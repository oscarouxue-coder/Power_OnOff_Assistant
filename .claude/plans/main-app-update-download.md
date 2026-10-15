# 主界面检查更新与程序内下载

## 目标

- 主界面手动检查 `oscarouxue-coder/Power_OnOff_Assistant` 最新正式 Release。
- 发现更高版本后显示说明并下载完整便携 ZIP，完成 SHA256 校验后由操作员手动换版。
- 联网、下载和校验不阻塞 Tk 主线程；关闭窗口或程序时安全取消并隔离迟到回调。

## 分层

- `src/models/app_update.py`：版本、Release 附件和检查结果数据结构。
- `src/core/github_release_client.py`：GitHub Release HTTPS 查询、小文件读取和流式下载。
- `src/services/app_update_service.py`：版本比较、附件校验、临时文件、SHA256 和最终落盘。
- `src/ui/app_update_dialog.py`：检查结果、下载确认、进度、取消及打开目录。
- `line_check_assistant/app.py`：主界面按钮、窗口装配和应用关闭通知。
- 工具栏右侧控件在窄窗口整体换行，保持管理员状态/刷新串口/刷新网卡/检查更新顺序。
- 关闭程序先保留既有设备取消请求，再异步等待全部更新线程取消并清理临时文件。

## 发布约定

- Release 标签使用 `vX.Y.Z`，包内 `VERSION_INFO.txt` 使用同一版本号。
- Release 必须同时包含 `LineCheckAssistant_portable.zip` 和 `LineCheckAssistant_portable.zip.sha256.txt`。
- 构建脚本在生成 ZIP 后输出对应 SHA256 文件。

## 验证

- 专项单测覆盖版本判断、GitHub 错误映射、附件缺失、下载成功、取消、哈希不符和写入失败。
- 静态/模拟 UI 回归覆盖主入口、重复点击、关闭取消与迟到事件隔离。
- 运行 `python scripts/verify_baseline.py`；不运行打包后的 EXE。
- 实际验证发现 Python 3.12 的 verbose 测试名包含完整方法名；兼容新旧格式，保持173项关键ID名单，并为混合格式及错误名称增加回归。
