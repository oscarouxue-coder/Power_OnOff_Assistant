"""Bounded FIFO for expendable UI data, never waits for its mutex.

No Condition.notify allocation while holding a lock. A busy consumer yields its
tick; a busy/full producer drops the new display record. Disk logging is separate.
"""
import queue
import threading
from collections import deque


class BoundedMailbox:
    def __init__(self, maxsize=2000):
        if maxsize <= 0:
            raise ValueError('maxsize must be positive')
        self.maxsize = maxsize
        self._items = deque()
        self._lock = threading.Lock()
        self.dropped = 0
        self.high_water = 0

    def put_nowait(self, item):
        if not self._lock.acquire(False):
            self.dropped += 1
            raise queue.Full
        accepted = False
        try:
            if len(self._items) < self.maxsize:
                self._items.append(item)
                self.high_water = max(self.high_water, len(self._items))
                accepted = True
        finally:
            self._lock.release()
        if not accepted:
            self.dropped += 1
            raise queue.Full

    put = put_nowait

    def get_nowait(self):
        if not self._lock.acquire(False):
            raise queue.Empty
        item = None
        found = False
        try:
            if self._items:
                item = self._items.popleft()
                found = True
        finally:
            self._lock.release()
        if not found:
            raise queue.Empty
        return item

    def qsize(self):
        # Advisory snapshots, as with queue.Queue; CPython deque len is atomic.
        return len(self._items)

    def empty(self):
        return not self._items

    def full(self):
        return len(self._items) >= self.maxsize

    def clear(self):
        # Caller is the GUI owner. Keep removed references alive until unlock.
        if not self._lock.acquire(False):
            return False
        try:
            removed, self._items = self._items, deque()
        finally:
            self._lock.release()
        removed.clear()
        return True
