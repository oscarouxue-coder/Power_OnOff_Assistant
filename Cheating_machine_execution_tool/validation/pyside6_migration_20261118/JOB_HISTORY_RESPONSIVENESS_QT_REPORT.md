# Qt 任务历史慢查询与工作区响应

2026-11-21，V1.3.0 迁移 Phase 6 和 Phase 7。

## 审计结论

原「任务历史 → 业务任务」在工作区命令线程上同步查询项目 SQLite 库。慢查询期间，窗口的 Qt 事件循环仍可响应，但同一队列中的保存、停止请求和退出收尾须等待查询结束。SQLite 的连接超时仅限制等待数据库锁的时间；分页上限限制返回条数，无法作为读取耗时上限。

## 改动

任务列表和所选任务的事件页现在由独立的单线程执行器按提交顺序读取。工作区的原请求容量限制继续生效，各请求绑定打开时的项目上下文和请求编号。工作区线程分派其他命令，并通过已有轮询收取查询结果。数据库位置、只读访问、任务 ID、翻页顺序及当前页筛选方式沿用原有实现。[原任务历史入口与分页](LOG_HISTORY_QT_REPORT.md)

关闭项目时取消该项目尚在排队或读取的请求，等读连接释放后再关闭项目。其他项目已进入队列的历史请求可以继续。退出工作区时取消全部历史读取，工作线程结束前回收历史执行器。每个已接收请求均返回一次结果或取消反馈。SQLite 在连接前、开库后和返回小页前响应取消；长事件扫描通过 SQLite 进度回调中断。文件性质的归档和旧工作台运行记录继续使用原归档读取路径。

## 修改文件

| 文件 | 改动 |
| --- | --- |
| `src/services/qt_workspace_adapter.py` | 分派历史读取、返回项目绑定结果、取消和回收执行器 |
| `src/services/qt_log_history.py` | 只读任务列表和事件页在查询前后及长扫描中响应取消 |
| `tests/test_qt_log_history.py` | 检查缺库、小页、真实 SQLite 中断、连接释放和取消后重读 |
| `tests/test_qt_workspace_adapter.py` | 验证慢查询期间项目保存、两项目排队、退出取消以及项目关闭后重开 |
| `tests/qt_workbench_probe.py` | 在已有必跑历史用例中，延迟一项读取并核对另一项目窗口、查询归属及迟到结果 |

## 复验方法

关闭项目会取消该项目正在执行和排队的历史查询。连接释放、项目真正关闭后，所有已受理的关闭请求才收到成功结果。收尾期间重开会提示稍后再试。另一项目已排队的历史读取继续执行。

从主源码目录运行。工作区测试使用临时项目库；在其中一个查询受阻时，检查另一项目的保存返回，再放行读取并核对项目 A、B 的结果顺序。退出与单项目关闭用例核对实际关闭读连接及排队结果。原生场景通过原任务历史菜单和现有窗口进行。

~~~powershell
python scripts/run_tests.py test_qt_log_history test_qt_workspace_adapter test_qt_execution_adapter test_qt_migration_contract -v
python scripts/verify_baseline.py
$qtPython = "$env:LOCALAPPDATA\LineCheckAssistant\qt-build-py39\Scripts\python.exe"
& $qtPython -X utf8 scripts/verify_qt_migration.py --python $qtPython --output validation/pyside6_migration_20261118/qt_job_history_responsive
~~~

## 验收状态

固定 Python 下单独执行 `scripts/run_tests.py test_qt_log_history -v`，8 项通过。新增用例实测已取消的请求跳过查库，开库后取消会释放连接，小页能在返回前取消，长事件扫描由 SQLite 报告中断，之后仍可正常读取。组合专项、完整基线、三档 Windows 原生结果待回填。

本轮涉及任务历史的读取和关闭。目标电脑的大型真实项目库、长时间连续浏览时的响应以及真实挂测期间停止操作的现场表现仍待验收。
