# Phase 9 同一通道跨批次迟到事件回归

## 审计

原计划要求在模拟设备环境中验证任务事件乱序。现有单批次测试覆盖两个通道的轮次和状态。此次补充的场景是项目已经显示第二批任务时，第一批任务的回调才送达。

原 Job 服务按任务 ID 写入 SQLite 事件，读取时按该 ID 和事件游标查询，并按事件 ID 升序返回。Qt 执行适配器在轮询时分别更新各批次的缓存，当前项目详情从最近一次准入的任务取值。本次仅新增回归用例。[原 Job 服务](../../src/services/capability_jobs.py) · [Qt 执行适配器](../../src/services/qt_execution_adapter.py)

## 回归范围

用例在同一临时项目中先后启动两批自动开关机任务，使用原任务服务和数据库，物理引擎由测试替身执行。第二批的通道 7 已显示第 12 轮后，第一批的投影再发送第 99 轮、通道失败和历史事件。用例检查第二批的任务 ID、运行状态、进度、通道状态、关注数、历史游标和资源租约，并核对两批日志的归属及第一批数据库的历史事件和终态。[回归用例](../../tests/test_qt_execution_adapter.py)

## 复跑与状态

从主源码目录 `Cheating_machine_execution_tool` 执行。

~~~powershell
python scripts/run_tests.py test_qt_execution_adapter.QtExecutionAdapterTests.test_late_previous_batch_events_preserve_current_run_channel_and_history -v
~~~

本轮专项回归共 95 项通过，测试输出逐项确认本用例已执行并通过。真实设备和持续高负载下的事件交付仍待现场确认。
