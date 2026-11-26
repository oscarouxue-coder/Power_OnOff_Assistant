# Qt 通道会话目标拒绝提示——只读定位及展示补充（2026-11-26）

## 已证实与未证实

- [具体原提示](../../src/services/ai_session_router.py#L257) 在既有本地识别结果要求延续会话、而原会话条件或设备目标快照不能核对一致时抛出。是现有拒绝，不应通过改显示绕过。仅凭截图不能区分实际不一致的字段，也不能判定该次识别输出是否明确指向普通问答、通道或其他范围。
- [本地身份判定](../../src/models/qt_ai_chat.py#L14) 仅支持既有特定型号问法；「你是谁?」不在该短语范围，且截图处为通道会话而非普通问答。此前询问版本本身不能证明本次根因。
- [Qt 错误保存与清除](../../src/services/qt_ai_chat.py#L500) 原错误按会话 ID 存放在临时 `_route_errors`；新有效发送在既有时机清除，迟到/切会话的收尾按原范围判断。最新页将失败输入和对应错误一同投影；切走再回来可见该未重试失败，属原设计，不能仅凭截图认定错误过期。没有访问截图对应真实会话或结果，也未调用模型、路由、设备。

## 窄展示修改

仅在已有拒绝文案精确匹配时，[Qt snapshot](../../src/services/qt_ai_chat.py) 将现有 `ChatSessionView.target` 显示标签加入提示，如「目标识别失败（当前所选会话：通道1）：原拒绝原因」，另注明「本条未通过目标核对，未自动切换会话」。此标签原本就在项目会话列表中，不新增身份或活目标核验。其他错误、失败输入/重试、旧提示清除、历史分页、选择、模型调用、目标识别/核验、权限、执行、设备或网络均不变。

## 纯展示实证

[独立探针](target_error_probe.py) 在临时 SQLite 内创建同名通道1/通道2和原合成历史问答，仅直接注入已发生的错误，调用原 Qt `snapshot` 投影。确认提示保留原原因且附真实所选标签；「你是谁?」不属于现有本地型号快捷问法；失败输入可重试且没有写入聊天历史。切到另一个会话不串提示，返回原会话仍保留真实原拒绝；旧页不显示该临时错误；其他错误不变化；模拟既有清除发生后才消失。没有运行 `_send`、识别、路由、模型或任何执行。

原 `scripts/run_tests.py` 单进程入口仅运行 `target_error_probe.TargetErrorDisplayProbe`，外部子进程、socket 建连/发送及外部打开受禁止断言。实际输出：

```text
source_compile 2 ok
GUI_TEST_COVERAGE_OK
test_existing_rejection_displays_exact_selected_label_without_clearing_or_rerouting (target_error_probe.TargetErrorDisplayProbe) ... ok
Ran 1 test in 1.262s
OK
GUI_RUNTIME_REPORT: {'passed': True, 'managed_windows': 0, 'violations': [], 'isolation': 'offscreen', 'desktop': None}
prohibited_io_calls 0
```

退出 0。不是 Qt 原生红字布局、真实模型或截图问题复现；用户实际当次是否由旧失败或新识别产生仍未知。原守卫/子进程限制保持，无完整门禁、模型、设备、网络、凭据或真实数据、Git 写或打包。
