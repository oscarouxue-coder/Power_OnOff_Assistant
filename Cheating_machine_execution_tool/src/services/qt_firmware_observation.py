"""Phase and serial displays attached to the original upgrade callbacks."""
import threading

from src.services.firmware_upgrade_service import upgrade_result
from src.services.qt_serial_observation import JobSerialObservation


class FirmwareObservation:
    """Receives driver events but never acquires, closes, or writes a COM port."""

    def __init__(self, engine, log):
        self.engine = engine
        self.log = log
        self._lock = threading.RLock()
        self._armed = ''
        self._batch = ''
        self._running = False
        self._rows = {}
        self.serial = JobSerialObservation('Qt升级', log)

    def arm(self, batch):
        with self._lock:
            self._armed = batch
            self._batch = batch
            self._running = False
            self._rows.clear()

    def disarm(self):
        with self._lock:
            self._armed = ''

    def progress(self, batch):
        with self._lock:
            return [row.copy() for row in self._rows.values()] if batch == self._batch else []

    def _start_item(self, batch, request):
        with self._lock:
            vlan = request.vlan.casefold()
            if self._batch == batch and self._running and vlan in self._rows:
                row = self._rows[vlan]
                if row['state'] == 'queued':
                    row.update(state='running', message='原引擎已开始')

    def _note(self, message):
        try:
            self.log(message)
        except Exception:
            pass  # Losing a display message must not interrupt the original engine.

    def _complete_item(self, batch, item):
        try:
            row = upgrade_result((item,))['items'][0]
            with self._lock:
                vlan = row['vlan'].casefold()
                if self._batch == batch and self._running and vlan in self._rows:
                    self._rows[vlan] = row
        except Exception:
            self._note('[Qt升级] 逐台展示未更新，原升级流程继续')

    def dispatch(self, requests, manager, **kwargs):
        with self._lock:
            batch, self._armed = self._armed, ''
            if batch:
                self._running = True
                self._rows = {request.vlan.casefold(): dict(vlan=request.vlan, state='queued', message='等待原引擎')
                              for request in requests}
        if not batch:
            return self.engine(requests, manager, **kwargs)
        try:
            with self.serial.track(batch, requests) as ready:
                return self.engine(requests, manager, **kwargs, on_session_ready=ready,
                    on_item_started=lambda request: self._start_item(batch, request),
                    on_item_complete=lambda item: self._complete_item(batch, item))
        finally:
            with self._lock:
                if self._batch == batch:
                    self._running = False
