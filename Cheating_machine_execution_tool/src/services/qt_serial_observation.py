"""Bounded read-only subscription to serial sessions owned by an existing job."""
from contextlib import contextmanager
from functools import partial
import queue
import threading

from src.services.qt_serial_terminal import DisplayDelivery
from src.utils.bounded_mailbox import BoundedMailbox


SERIAL_LOG_REQUEST = {
    'batch': dict(type='string', minLength=32, maxLength=32),
    'active': dict(type='string', maxLength=200),
}


class ObservationDelivery(DisplayDelivery):
    def __call__(self, event):
        if not event.sensitive:
            super().__call__(event)


class JobSerialObservation:
    def __init__(self, title, log):
        self._title = title
        self._log = log
        self._lock = threading.Lock()
        self._batch = ''
        self._targets = set()
        self._sessions = {}
        self._events = None

    @contextmanager
    def track(self, batch, requests):
        events = BoundedMailbox(256)
        sessions = {}
        with self._lock:
            self._batch = batch
            self._targets = {request.vlan.casefold() for request in requests}
            self._sessions = sessions
            self._events = events
        try:
            yield partial(self._ready, batch)
        finally:
            with self._lock:
                if self._batch == batch:
                    self._batch = ''
                    self._targets.clear()
                    self._sessions = {}
                    self._events = None
            for item in sessions.values():
                delivery = item['delivery']
                delivery.invalidate()
                try:
                    item['session'].unsubscribe(delivery)
                except Exception:
                    self._note('串口显示退订失败，已屏蔽迟到事件')
            events.clear()

    @property
    def log_id(self):
        with self._lock:
            return self._batch if self._sessions else ''

    def _note(self, message):
        try:
            self._log(f'[{self._title}] {message}')
        except Exception:
            pass  # Display errors cannot interrupt the device runner.

    def _ready(self, batch, vlan, session, log_path):
        try:
            vlan = vlan.casefold()
            with self._lock:
                if batch != self._batch or vlan not in self._targets or vlan in self._sessions:
                    return
                port = session.settings.port
                path = str(getattr(session, 'log_path', log_path) or '')
                delivery = ObservationDelivery(vlan, self._events)
                session.subscribe(delivery)
                self._sessions[vlan] = dict(session=session, delivery=delivery, port=port,
                                            path=path, text='', dropped=0)
            self._note('已订阅原任务串口：' + vlan)
        except Exception:
            self._note('串口显示订阅失败，原任务与文件日志继续')

    def logs(self, batch, active):
        with self._lock:
            if batch != self._batch or not self._sessions:
                return dict(batch=batch, closed=True, tabs=[], dropped=0)
            for _ in range(80):
                try:
                    vlan, event, delivery = self._events.get_nowait()
                except queue.Empty:
                    break
                item = self._sessions.get(vlan)
                if item is None or item['delivery'] is not delivery:
                    continue
                combined = item['text'] + event.text
                item['dropped'] += max(0, len(combined) - 65536)
                item['text'] = combined[-65536:]
            tabs = []
            for vlan, item in self._sessions.items():
                tabs.append(dict(vlan=vlan, port=item['port'], path=item['path'],
                                 text=item['text'] if vlan == active else '',
                                 dropped=item['dropped'] + item['delivery'].trimmed))
                if vlan == active:
                    item['text'] = ''
            return dict(batch=batch, closed=False, tabs=tabs, dropped=self._events.dropped)
