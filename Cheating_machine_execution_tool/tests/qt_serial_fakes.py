"""Queue-backed serial driver; original reader/logging/ownership stay active."""
import queue
from unittest.mock import patch
from src.core.serial_transport import PySerialSession


class QueueSerial:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.input = queue.Queue()
        self.writes = []
        self.closed = False

    @property
    def in_waiting(self):
        return 0

    def read(self, size):
        try:
            return self.input.get(timeout=.02)
        except queue.Empty:
            return b''

    def write(self, value):
        self.writes.append(value)
        return len(value)

    def flush(self):
        pass

    def cancel_read(self):
        self.input.put(b'')

    def close(self):
        self.closed = True
        self.input.put(b'')


class SerialHarness:
    def __init__(self):
        self.drivers = {}
        self.sessions = {}
        self.patch = patch('src.core.serial_transport.PySerialSession', side_effect=self.factory)

    def factory(self, settings, log_path=None):
        driver = self.drivers.setdefault(settings.port, QueueSerial())
        session = PySerialSession(settings, log_path, lambda **kwargs: driver)
        self.sessions[settings.port] = session
        return session

    def start(self):
        self.patch.start()
        return self

    def stop(self):
        self.patch.stop()
