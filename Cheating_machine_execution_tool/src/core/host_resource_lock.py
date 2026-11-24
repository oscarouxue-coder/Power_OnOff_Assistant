"""Process lifetime locks for physical resources; no device I/O or thread ownership."""
import ctypes
import hashlib
import os
from pathlib import Path
import re
import tempfile
import threading
from functools import wraps


class HostResourceBusy(RuntimeError):
    pass


def physical_key(key):
    kind, separator, value = str(key).partition(":")
    if not separator or not value.strip():
        raise ValueError("资源标识不能为空")
    kind, value = kind.casefold(), value.strip().casefold()
    if kind in ("serial", "power"):
        value = value.removeprefix("\\\\.\\")
        if re.fullmatch(r"com\d+", value):
            value = "com" + str(int(value[3:]))
        kind = "serial"
    return kind + ":" + value


class HostResourceLock:
    """Global Windows objects survive threads, release on process exit, and nest locally.

    Same-process nesting permits a reserved business job to use existing serial/power
    engines. Their existing owner checks still arbitrate threads within the process.
    """
    _guard = threading.RLock()
    _held = {}
    _failed_cleanup = set()

    def __init__(self, keys, namespace="physical-v1", *, reentrant=True):
        self.keys = tuple(sorted({physical_key(k) for k in keys}))
        self.namespace, self.acquired = namespace, []
        self.reentrant = reentrant

    def acquire(self):
        with self._guard:
            if self.acquired:
                return self
            try:
                for key in self.keys:
                    identity = (os.getpid(), self.namespace, key)
                    if identity in self._held:
                        if identity in self._failed_cleanup:
                            raise HostResourceBusy("原资源关闭失败，等待原进程退出：" + key)
                        if not self.reentrant:
                            raise HostResourceBusy("资源已被本进程持有：" + key)
                        handle, count = self._held[identity]
                        self._held[identity] = (handle, count + 1)
                    else:
                        handle = self._open(key)
                        self._held[identity] = (handle, 1)
                    self.acquired.append(identity)
            except BaseException:
                self.close()
                raise
        return self

    def _open(self, key):
        digest = hashlib.sha256((self.namespace + "|" + key).encode()).hexdigest()
        if os.name == "nt":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
            kernel.CreateMutexW.restype = ctypes.c_void_p
            ctypes.set_last_error(0)
            handle = kernel.CreateMutexW(None, False, "Global\\LineCheckPhysical_" + digest)
            error = ctypes.get_last_error()
            if handle and error != 183:
                return handle
            if handle:
                self._close(handle)
            raise HostResourceBusy("物理资源已被其它进程占用或无法取得系统保护：" + key)
        import fcntl
        directory = Path(tempfile.gettempdir()) / "linecheck-physical-locks"
        directory.mkdir(exist_ok=True)
        stream = (directory / digest).open("a+b")
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise HostResourceBusy("物理资源已被其它进程占用：" + key) from None
        return stream

    @staticmethod
    def _close(handle):
        if os.name == "nt":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle.restype = ctypes.c_int
            kernel.CloseHandle(handle)
        else:
            handle.close()

    def close(self):
        with self._guard:
            for identity in reversed(self.acquired):
                handle, count = self._held[identity]
                if count == 1:
                    self._close(handle)
                    del self._held[identity]
                    self._failed_cleanup.discard(identity)
                else:
                    self._held[identity] = (handle, count - 1)
            self.acquired.clear()

    def mark_cleanup_failed(self):
        with self._guard:
            self._failed_cleanup.update(self.acquired)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.close()


def guard_adapter(result_type):
    """Adapter operations return their established failure type on cross-process conflict."""
    def decorate(function):
        @wraps(function)
        def run(adapter_alias, *args, **kwargs):
            alias = adapter_alias.strip().split(" [", 1)[0]
            try:
                with HostResourceLock(["adapter:" + alias] if alias else []):
                    return function(adapter_alias, *args, **kwargs)
            except HostResourceBusy as exc:
                output = kwargs.get("on_output")
                if output:
                    output(str(exc))
                return result_type(False, str(exc))
        return run
    return decorate
