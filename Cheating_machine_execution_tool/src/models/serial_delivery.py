"""Reader-owned subscription endpoint. Deliberately has no window reference."""
import queue
import threading


class SerialDelivery:
    def __init__(self, vlan, mailbox, observer=None):
        self.vlan = vlan
        self.mailbox = mailbox
        self.observer = observer  # data-only diagnostic receiver, never a UI method
        self.invalid = threading.Event()

    def invalidate(self):
        self.invalid.set()

    def __call__(self, event):
        if self.invalid.is_set():
            return
        if self.observer is not None:
            try:
                self.observer(self.vlan, event)
            except Exception:
                pass  # passive diagnostics cannot interrupt display or disk logging
        if not self.invalid.is_set():
            try:
                self.mailbox.put_nowait((self.vlan, event, self))
            except queue.Full:
                pass
