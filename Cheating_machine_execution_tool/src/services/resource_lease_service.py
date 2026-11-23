"""Atomic in-process admission; physical COM ownership stays in SerialSessionManager."""
import threading
from contextlib import contextmanager
from src.models.capabilities import CapabilityError
from src.core.host_resource_lock import HostResourceLock, HostResourceBusy, physical_key


class ResourceLeaseService:
    def __init__(self, admissible=lambda owner, keys: True, released=lambda owner: None, fence=None,
                 coordinator=None, project_id="", project_name=""):
        self._lock = threading.RLock()
        self._owners = {}
        self.admissible = admissible
        self.released = released
        self.fence = fence
        self._host_locks = {}
        self.coordinator, self.project_id, self.project_name = coordinator, project_id, project_name

    @property
    def busy(self):
        with self._lock:
            return bool(self._owners)

    def acquire(self, owner, keys):
        keys = tuple(sorted(set(keys)))
        # Never wait for a GUI admission while holding the resource lock.
        if not self.admissible(owner, keys):
            raise CapabilityError("resource_busy", "当前业务状态不允许取得资源")
        error = None
        with self._lock:
            conflict = any(self._owners.get(key, owner) != owner for key in keys)
            if not conflict:
                guard = None
                try:
                    if self.coordinator is not None:
                        self.coordinator.acquire(owner, self.project_id, self.project_name, keys)
                    physical = [physical_key(k) for k in keys if k.startswith(("serial:", "adapter:", "power:", "olt:", "pon:", "dut:", "adb:"))]
                    if owner in self._host_locks:
                        physical = list(set(physical) | set(self._host_locks[owner].keys))
                    guard = HostResourceLock(physical).acquire()
                    if self.fence:
                        self.fence.acquire(owner, physical)
                    previous = self._host_locks.pop(owner, None)
                    self._host_locks[owner] = guard
                    if previous:
                        previous.close()
                    for key in keys:
                        self._owners[key] = owner
                except Exception as exc:
                    if self.coordinator is not None:
                        self.coordinator.release(owner)
                    if guard:
                        guard.close()
                    error = exc
        if conflict or error is not None:
            # released may wait for Tk. It must never run under the lease mutex.
            self.released(owner)
            if error is not None:
                if isinstance(error, HostResourceBusy):
                    raise CapabilityError("resource_busy", str(error)) from None
                raise error
            raise CapabilityError("resource_busy", "设备或共享资源已由其它业务任务占用")

    def release(self, owner, uncertain=False):
        with self._lock:
            if self.coordinator is not None:
                self.coordinator.release(owner, uncertain)
            if self.fence:
                self.fence.release(owner, uncertain)
            self._owners = {key: value for key, value in self._owners.items() if value != owner}
            guard = self._host_locks.pop(owner, None)
            if guard:
                guard.close()
        self.released(owner)

    @contextmanager
    def lease(self, owner, keys):
        self.acquire(owner, keys)
        try:
            yield
        finally:
            self.release(owner)
