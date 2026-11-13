"""Main-thread handlers, deliberately separate from the worker channel."""
import threading
from types import SimpleNamespace
from src.services.pipeline_runtime import PipelineChannel, PipelineDispatcher, PipelineUiError


class PipelineUiController:
    def __init__(self, app, dispatch_timeout=30.0):
        self.app = app
        self.channel = PipelineChannel(dispatch_timeout=dispatch_timeout)
        self.dispatcher = PipelineDispatcher(self.channel)
        self.windows = {}
        self.runs = {}
        self.threads = {}
        self.subtasks = {}
        handlers = {
            'serial_logs': '_open_pipeline_serial_logs',
            'diagnostic': '_observe_ai_power_event',
            'reset_channels': '_reset_power_test_channel_states',
            'progress': '_set_power_test_progress',
            'channel_state': '_set_power_test_channel_state',
            'channel_history': '_record_power_test_channel_history',
            'channel_progress': '_set_power_test_channel_progress',
        }
        for code, method in handlers.items():
            self.dispatcher.handlers[code] = self._handler(method)
        self.dispatcher.handlers.update(resume_session=self._register_resume,
                                        finished=self._finished, start_subtask=self._start_subtask)

    def _handler(self, method):
        def handle(request):
            # Admission is needed for starting monitors as well as device jobs.
            if request.code == 'serial_logs' and not request.admit():
                raise PipelineUiError('串口监控启动已取消')
            return getattr(self.app, method)(*request.args)
        return handle

    def register(self, window, run, thread):
        self.windows[run.generation] = window
        self.runs[run.generation] = run
        self.threads[run.generation] = thread

    def _register_resume(self, request):
        if not request.admit():
            raise PipelineUiError('测试会话注册已取消')
        self.app.power_test_resume_session = request.args[0]

    def _start_subtask(self, request):
        code, skip = request.args
        completion = {'event': threading.Event(), 'ok': False, 'detail': ''}
        self.subtasks[code] = completion
        request.run.subtasks[code] = completion
        try:
            self.app._begin_pipeline_subtask(code)
            method = getattr(self.app, '_start_pipeline_' + code + '_on_ui')
            started = method() if code == 'onu_registration' else method(skip)
        except Exception as exc:
            self.complete_subtask(code, False, type(exc).__name__ + ': ' + str(exc))
            raise
        if not started:
            self.complete_subtask(code, False, '操作员取消、请求已失效或配置未通过')
        return completion

    def complete_subtask(self, code, ok, detail):
        completion = self.subtasks.pop(code, None)
        if completion is not None:
            # The new data client waits on completion, not the legacy app wait.
            # Remove ownership markers so later manual jobs are not misclassified.
            self.app.__dict__.get('_pipeline_subtask_events', {}).pop(code, None)
            self.app.__dict__.get('_pipeline_subtask_results', {}).pop(code, None)
            completion.update(ok=ok, detail=str(detail))
            completion['event'].set()

    def _finished(self, request):
        generation = request.run.generation
        if generation not in self.runs:
            return
        window = self.windows.get(generation)
        results, error = request.args
        if window is not None and not window._closed:
            if error:
                window._on_pipeline_failed(PipelineUiError(error))
            else:
                window._on_pipeline_complete(results)
        else:
            state = 'stopped' if request.run.stop.is_set() else ('failed' if error else 'completed')
            self.app._set_power_test_status(state)
            self.app._log('[全流程] 后台收尾完成' + (': ' + error if error else ''))
        self.windows.pop(generation, None)
        self.runs.pop(generation, None)

    def poll(self):
        self.dispatcher.poll()
        for generation, thread in tuple(self.threads.items()):
            if not thread.is_alive():
                run = self.runs.get(generation)
                if run is not None and run.finished.is_set():
                    if all(item['event'].is_set() for item in run.subtasks.values()):
                        self.threads.pop(generation, None)
                        self._finished(SimpleNamespace(run=run, args=run.outcome))

    def begin_close(self):
        for run in self.runs.values():
            run.cancel()
        self.channel.close()
        for code in tuple(self.subtasks):
            self.complete_subtask(code, False, '主界面正在关闭')

    def idle(self):
        return not self.runs and not any(thread.is_alive() for thread in self.threads.values())

    def dispose(self):
        for window in tuple(self.windows.values()):
            window._dispose()
        self.windows.clear()
        self.runs.clear()
        self.threads.clear()
        self.dispatcher.dispose()
        self.channel.requests.clear()
        self.app = None
