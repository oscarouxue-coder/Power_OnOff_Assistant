"""Read-only, data-only transport observations. Never reads a COM/socket or copies RX."""
import sys
import shutil
import threading
import time
import uuid
import weakref
from collections import deque
from pathlib import Path


class HistoryRegistry:
    def __init__(self):
        self.lock = threading.Lock()
        self.sessions = {}
        self.finished = deque(maxlen=512)
        self.finished_dropped = 0

    def register(self, session, protocol, endpoint):
        with self.lock:
            self.sessions[id(session)] = (weakref.ref(session), {
                "session_id": uuid.uuid4().hex, "protocol": protocol,
                "endpoint": endpoint, "opened_monotonic": time.monotonic()})

    def label(self, session, **labels):
        with self.lock:
            item = self.sessions.get(id(session))
            if item:
                item[1].update({k: v for k, v in labels.items() if k in ("channel", "vlan")})

    @staticmethod
    def inspect(session, metadata, file_metrics=True):
        result = dict(metadata)
        condition = session._condition
        if not condition.acquire(False):
            return dict(result, sample_status="busy")
        try:
            resident = len(session._history)
            spilled = getattr(session, '_history_offset', 0)
            result.update(history_bytes=resident, history_spilled_bytes=spilled,
                          history_object_bytes=sys.getsizeof(session._history),
                          history_limit_bytes=getattr(session, 'HISTORY_LIMIT', None),
                          history_high_water_bytes=max(resident, getattr(session, '_history_peak', 0)),
                          received_bytes=resident + spilled + getattr(session, '_unretained_bytes', 0),
                          received_source='serial_rx_cursor' if hasattr(session, '_history_offset') else 'append_only_history_length')
        finally:
            condition.release()
        result.update(pending_rx_chars=(len(getattr(session, "_rx_log_line_buffer", "")) +
                                        getattr(session, '_rx_line_spilled', 0) + int(getattr(session, '_rx_line_cr', False))),
                      pending_rx_spilled_chars=getattr(session, '_rx_line_spilled', 0),
                      pending_rx_object_bytes=sys.getsizeof(getattr(session, "_rx_log_line_buffer", "")),
                      reader_alive=bool(session._reader and session._reader.is_alive()),
                      closed=bool(session._closed), receive_error=type(session.error).__name__ if session.error else None,
                      last_flush_confirmed=None, write_error=None, write_status="unverified",
                      sample_status="ok")
        path = getattr(session, "log_path", None)
        result["log_path"] = str(path) if path else None
        result["log_file_bytes"] = None
        result["log_disk_free_bytes"] = None
        handle = getattr(session, "_log_handle", None)
        if not path:
            result["write_status"] = "not_configured"
        else:
            result["write_status"] = "closed_unverified" if result["closed"] else "open_unverified" if handle else "not_open"
            if file_metrics:
                HistoryRegistry.file_metrics(result)
        if not result["closed"] and session._reader is not None and not result["reader_alive"]:
            result["write_status"] = "reader_stopped_unexpectedly"
        if getattr(session, '_rx_log_error', ''):
            result["write_error"] = session._rx_log_error
        return result

    @staticmethod
    def file_metrics(result):
        path = result.get("log_path")
        if not path:
            return
        try:
            result["log_disk_free_bytes"] = shutil.disk_usage(Path(path).parent).free
        except OSError:
            pass
        try:
            result["log_file_bytes"] = Path(path).stat().st_size
        except OSError as exc:
            result.update(write_status="stat_error", write_error=type(exc).__name__ + ":" + str(exc.errno))

    def retire(self, session):
        with self.lock:
            item = self.sessions.pop(id(session), None)
        if item:
            value = self.inspect(session, item[1], file_metrics=False)
            value["final"] = True
            with self.lock:
                if len(self.finished) == self.finished.maxlen:
                    self.finished_dropped += 1
                self.finished.append(value)

    def collect(self):
        if not self.lock.acquire(False):
            return {"registry_busy": True, "sessions": [], "final_samples_dropped": self.finished_dropped}
        try:
            items = tuple(self.sessions.items())
            finished = list(self.finished)
            self.finished.clear()
        finally:
            self.lock.release()
        dead = []
        for row in finished:
            self.file_metrics(row)  # Filesystem IO belongs to the sampler, never transport close.
        for key, (reference, metadata) in items:
            session = reference()
            if session is None:
                dead.append(key)
            else:
                finished.append(self.inspect(session, metadata))
            session = None  # Do not retain sessions until the next sampling tick.
        if dead:
            with self.lock:
                for key in dead:
                    item = self.sessions.get(key)
                    if item and item[0]() is None:
                        self.sessions.pop(key, None)
        return {"registry_busy": False, "sessions": finished, "final_samples_dropped": self.finished_dropped}


HISTORY_REGISTRY = HistoryRegistry()


def register_session(session, protocol, endpoint):
    try:
        HISTORY_REGISTRY.register(session, protocol, endpoint)
    except Exception:
        pass  # Observability cannot change transport initialization.


def label_session(session, **labels):
    try:
        HISTORY_REGISTRY.label(session, **labels)
    except Exception:
        pass  # Labels must not affect a successful monitor open.


def retire_session(session):
    try:
        HISTORY_REGISTRY.retire(session)
    except Exception:
        pass  # Preserve the original close outcome and log behavior.
