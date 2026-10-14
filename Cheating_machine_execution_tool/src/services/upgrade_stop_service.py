"""Per-batch stop ownership and per-thread protected operations."""
import threading
import time
import queue
from contextlib import contextmanager

from src.models.upgrade_stop import UpgradeStopped, UpgradeStoppedResult


class UpgradeRun:
    """One immutable ownership token for a batch and its UI messages."""
    def __init__(self, pipeline_owned=False):
        self.control = UpgradeStopControl()
        self.pipeline_owned = pipeline_owned
        self.thread = None
        self.ui_queue = queue.Queue()
        self.finished = False


def stopped_result(label, detail="", *, skipped=False):
    action = "停止后跳过（未开始）" if skipped else "已停止"
    return UpgradeStoppedResult(f"{label} {action}。{detail}", skipped=skipped)


def result_state(result):
    if isinstance(result, UpgradeStoppedResult):
        return "跳过" if result.skipped else "已停止"
    return "成功" if result.ok else "失败"


def summarize_results(results):
    counts = {key: 0 for key in ("成功", "失败", "已停止", "跳过")}
    for item in results:
        counts[result_state(item.result)] += 1
    return "，".join(f"{key} {value} 台" for key, value in counts.items())


class UpgradeStopControl:
    def __init__(self):
        self.event = threading.Event()
        self._local = threading.local()

    def request_stop(self):
        self.event.set()

    def is_set(self):
        return self.event.is_set()

    def checkpoint(self, detail="停止后不再下发后续命令。"):
        if self.is_set() and not getattr(self._local, "protected", 0):
            raise UpgradeStopped(detail)

    @contextmanager
    def protect(self):
        """Finish an admitted transfer/power operation; never shared across workers."""
        self._local.protected = getattr(self._local, "protected", 0) + 1
        try:
            yield
        finally:
            self._local.protected -= 1

    def sleep(self, seconds, sleep_fn=time.sleep):
        self.checkpoint()
        if getattr(self._local, "protected", 0) or sleep_fn is not time.sleep:
            sleep_fn(seconds)
        else:
            self.event.wait(seconds)
        self.checkpoint()

    def wait_event(self, event, timeout):
        deadline = time.monotonic() + timeout
        while True:
            self.checkpoint()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return event.is_set()
            if event.wait(min(0.1, remaining)):
                self.checkpoint()
                return True


class StopAwareSerialSession:
    """Guard serial sends and split passive waits without changing history cursors."""
    def __init__(self, session, control, local_cancel=None):
        self._session = session
        self._control = control
        self._local_cancel = local_cancel

    def __getattr__(self, name):
        return getattr(self._session, name)

    def _check(self):
        self._control.checkpoint()
        if self._local_cancel is not None and self._local_cancel.is_set():
            raise RuntimeError("串口升级控制器已结束。")

    def write(self, *args, **kwargs):
        self._check()
        return self._session.write(*args, **kwargs)

    def send_line(self, *args, **kwargs):
        self._check()
        return self._session.send_line(*args, **kwargs)

    def wait_for_any(self, markers, timeout, cursor):
        deadline = time.monotonic() + timeout
        while True:
            self._check()
            remaining = max(0, deadline - time.monotonic())
            result = self._session.wait_for_any(markers, min(0.2, remaining), cursor)
            self._check()
            if result is not None or time.monotonic() >= deadline:
                return result
