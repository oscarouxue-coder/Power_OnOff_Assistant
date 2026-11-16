"""Explicit dependency failure and repair result; no UI or installation side effects."""
from dataclasses import dataclass
from functools import wraps
import threading


class MissingFeishuSdkError(RuntimeError):
    def __init__(self):
        super().__init__("缺少飞书SDK，请安装项目固定依赖后重启")


@dataclass(frozen=True)
class RepairResult:
    ok: bool
    message: str


class MaintenanceGate:
    """Atomic admission, without retaining mutexes across UI/network waits."""
    def __init__(self):
        self.lock = threading.Lock()
        self.active = False
        self.operations = 0

    def begin(self, busy=None):
        with self.lock:
            if self.active or self.operations or (busy is not None and busy()):
                raise RuntimeError("请结束当前任务后重试，未安装、未重启")
            self.active = True

    def end(self):
        with self.lock:
            self.active = False

    def enter(self):
        with self.lock:
            if self.active:
                raise RuntimeError("飞书依赖正在安装或等待重启，本次任务未启动")
            self.operations += 1

    def leave(self):
        with self.lock:
            self.operations -= 1


def maintenance_operation(function):
    @wraps(function)
    def guarded(self, *args, **kwargs):
        gate = getattr(self, "maintenance", None)
        if gate is not None:
            gate.enter()
        try:
            return function(self, *args, **kwargs)
        finally:
            if gate is not None:
                gate.leave()
    return guarded
