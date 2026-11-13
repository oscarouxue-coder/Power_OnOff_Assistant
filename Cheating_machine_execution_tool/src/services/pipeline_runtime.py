"""Data-only worker/UI bridge. Only PipelineDispatcher owns GUI handlers.

Never send a GUI callable or an exception traceback through this channel.
The dispatch deadline covers pending requests, not a human confirmation dialog.
"""
import itertools
import queue
import threading
import time
from dataclasses import dataclass, field
from src.utils.bounded_mailbox import BoundedMailbox


# Per-thread registry: a worker cannot reach another thread's GUI handlers.
_dispatchers = threading.local()


class PipelineUiError(RuntimeError):
    def __init__(self, message, error_type=''):
        super().__init__(message)
        self.error_type = error_type


@dataclass
class PipelineRun:
    generation: int
    stop: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    detached: bool = False
    subtasks: dict = field(default_factory=dict)
    outcome: object = None

    def cancel(self):
        self.stop.set()


class UiRequest:
    def __init__(self, channel, run, code, args, cleanup=False):
        self.channel, self.run, self.code, self.args = channel, run, code, args
        self.cleanup = cleanup
        self.deadline = time.monotonic() + channel.dispatch_timeout
        self.done = threading.Event()
        self._lock = threading.Lock()
        self.state = 'pending'
        self.admitted = False
        self.result = None
        self.error = ''
        self.error_type = ''

    def _invalid(self):
        return self.channel.closed.is_set() or (not self.cleanup and self.run.stop.is_set())

    def start(self):
        with self._lock:
            if self.state != 'pending':
                return False
            if self._invalid() or time.monotonic() >= self.deadline:
                self._cancel_locked('界面动作已取消或排队超时')
                return False
            self.state = 'running'
            return True

    def admit(self):
        with self._lock:
            if self.state != 'running' or self._invalid():
                return False
            self.state = 'admitted'
            self.admitted = True
            return True

    def _cancel_locked(self, reason):
        if self.state in ('completed', 'failed', 'cancelled', 'expired'):
            return
        self.error = reason + ('；实际操作已准入，按原停止边界收尾，结果待确认' if self.admitted else '')
        self.state = 'expired' if '超时' in reason else 'cancelled'
        self.done.set()

    def cancel(self, reason):
        with self._lock:
            self._cancel_locked(reason)

    def complete(self, result=None, error='', error_type=''):
        with self._lock:
            if self.state in ('cancelled', 'expired'):
                return False
            if self._invalid():
                self._cancel_locked('界面动作已取消')
                return False
            self.result, self.error = result, error
            self.error_type = error_type
            self.state = 'failed' if error else 'completed'
            self.done.set()
            return True


class PipelineChannel:
    def __init__(self, dispatch_timeout=30.0):
        if dispatch_timeout <= 0:
            raise ValueError('dispatch_timeout must be positive')
        self.dispatch_timeout = float(dispatch_timeout)
        self.requests = BoundedMailbox(256)
        self.closed = threading.Event()
        self._generations = itertools.count(1)

    def new_run(self):
        if self.closed.is_set():
            raise PipelineUiError('主界面正在关闭')
        return PipelineRun(next(self._generations))

    def post(self, run, code, args=(), cleanup=False):
        request = UiRequest(self, run, code, args, cleanup)
        if request._invalid():
            request.cancel('界面动作已取消')
            return request
        try:
            self.requests.put_nowait(request)
        except queue.Full:
            request.complete(error='界面动作队列繁忙，未提交动作')
        return request

    def invoke(self, run, code, args=(), cleanup=False):
        local = getattr(_dispatchers, 'entries', {}).get(id(self))
        if local is not None:
            request = UiRequest(self, run, code, args, cleanup)
            local.execute(request)
        else:
            request = self.post(run, code, args, cleanup)
        while not request.done.wait(.02):
            if request._invalid():
                request.cancel('界面动作已取消')
            elif request.state == 'pending' and time.monotonic() >= request.deadline:
                request.cancel('界面动作排队超时')
        if request.error:
            if not cleanup and not request.error_type:
                run.cancel()
            raise PipelineUiError(request.error, request.error_type)
        return request.result

    def close(self):
        self.closed.set()


class PipelineDispatcher:
    """GUI-only registry. It is never reachable from PipelineChannel/clients."""
    def __init__(self, channel):
        self.channel = channel
        self.handlers = {}
        self.current = None
        self.owner_thread = threading.get_ident()
        if not hasattr(_dispatchers, 'entries'):
            _dispatchers.entries = {}
        _dispatchers.entries[id(channel)] = self

    def dispose(self):
        if threading.get_ident() != self.owner_thread:
            raise RuntimeError('UI dispatcher must be disposed by its owner')
        self.handlers.clear()
        _dispatchers.entries.pop(id(self.channel), None)

    def poll(self, limit=8):
        if threading.get_ident() != self.owner_thread:
            raise RuntimeError('UI dispatcher must run on its owner thread')
        for _ in range(limit):
            try:
                request = self.channel.requests.get_nowait()
            except queue.Empty:
                break
            self.execute(request)

    def execute(self, request):
        if threading.get_ident() != self.owner_thread:
            raise RuntimeError('UI dispatcher must run on its owner thread')
        if not request.start():
            return
        previous, self.current = self.current, request
        try:
            handler = self.handlers.get(request.code)
            if handler is None:
                raise ValueError('未知界面动作: ' + request.code)
            result = handler(request)
        except Exception as exc:
            request.complete(error=type(exc).__name__ + ': ' + str(exc), error_type=type(exc).__name__)
        else:
            if not request.complete(result) and hasattr(result, 'discard'):
                result.discard()
        finally:
            self.current = previous


class PipelineClient:
    """Compatibility-facing app interface, containing only data and channel."""
    def __init__(self, channel, run, power_serial_port='', onu_targets=(), onu_preview_ready=False):
        self.channel, self.run = channel, run
        self.power_serial_port = power_serial_port
        self.onu_targets = tuple(onu_targets)
        self.onu_preview_ready = onu_preview_ready

    def _invoke_pipeline_ui_action(self, action):
        # Orchestrator compatibility closures here contain this data-only client.
        # Execute locally; the client method below posts a coded request to Tk.
        return action()

    def _selected_unregistered_onus(self):
        return self.onu_targets

    def _open_pipeline_serial_logs(self):
        return self.channel.invoke(self.run, 'serial_logs')

    def _observe_ai_power_event(self, message):
        return self.channel.invoke(self.run, 'diagnostic', (dict(message),))

    def _reset_power_test_channel_states(self, numbers):
        return self.channel.invoke(self.run, 'reset_channels', (list(numbers),))

    def _set_power_test_progress(self, *args):
        return self.channel.invoke(self.run, 'progress', args)

    def _set_power_test_channel_state(self, *args):
        return self.channel.invoke(self.run, 'channel_state', args)

    def _record_power_test_channel_history(self, *args):
        return self.channel.invoke(self.run, 'channel_history', args)

    def _set_power_test_channel_progress(self, *args):
        return self.channel.invoke(self.run, 'channel_progress', args)

    @property
    def power_test_resume_session(self):
        return None

    @power_test_resume_session.setter
    def power_test_resume_session(self, session):
        self.channel.invoke(self.run, 'resume_session', (session,))

    def _subtask(self, code, skip_confirmation=False):
        completion = self.channel.invoke(self.run, 'start_subtask', (code, skip_confirmation))
        while not completion['event'].wait(.05):
            if self.channel.closed.is_set() or self.run.stop.is_set():
                raise PipelineUiError('全流程子任务已请求停止；已提交操作等待安全收尾，结果待确认')
        if not completion['ok']:
            raise PipelineUiError(completion['detail'])

    def _run_pipeline_sample_upgrade(self, skip_confirmation=False):
        return self._subtask('sample_upgrade', skip_confirmation)

    def _run_pipeline_sample_parameter_write(self, skip_confirmation=False):
        return self._subtask('sample_parameter_write', skip_confirmation)

    def _run_pipeline_onu_registration(self):
        return self._subtask('onu_registration')


class PipelineLogSink:
    def __init__(self, output_queue, labels):
        self.output_queue = output_queue
        self.labels = tuple(labels)

    def __call__(self, line):
        for old, new in self.labels:
            line = line.replace(old, new)
        self.output_queue.put(line)


def run_pipeline(context, selected, channel, run, emit):
    """Thread entry point: no bound window target, UI closure, or UI traceback."""
    from src.services.pipeline_orchestrator import PipelineOrchestrator
    try:
        orchestrator = PipelineOrchestrator(context, emit)
        run.diagnostic_run_id = orchestrator.diagnostic_run_id
        results = orchestrator.run(selected)
        run.outcome = (results, '')
    except Exception as exc:
        run.outcome = ([], type(exc).__name__ + ': ' + str(exc))
    finally:
        run.finished.set()
