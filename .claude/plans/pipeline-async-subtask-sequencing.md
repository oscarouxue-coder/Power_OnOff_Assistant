# 全流程异步子任务顺序化

## 目标

使全流程子任务 3「样机升级」和子任务 4「写样机参数」不再只要启动后台线程就结束；必须等待当前任务完成后，才开始下一子任务。

## 范围

- 主程序增加线程安全的管道 UI 调度队列，以及子任务完成事件。
- 样机升级、写样机参数由管道启动时在 Tk 主线程显示确认弹窗；完成回调再通知管道继续。
- 写参由管道启动时重新打开写参窗口，避免使用已关闭的 `Toplevel` 作为弹窗父窗口。
- 保持 `Tftp指令` 与 `Tftp Put` 的独立升级分流不变。

## 验证

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m unittest discover -s tests -p "test_pipeline_orchestrator.py" -v
python -m unittest discover -s tests -p "test_app.py" -v
python scripts\verify_baseline.py
```
