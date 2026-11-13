"""Background serial diagnostic client: manager, data models and channel only."""
import threading
from src.models.serial_models import SerialSettings
from src.services.pipeline_runtime import PipelineChannel, PipelineUiError
from src.utils.bounded_mailbox import BoundedMailbox


class SerialLease:
    def __init__(self, client, target, session, owner, cancelled, token):
        self.client, self.target, self.session = client, target, session
        self.owner, self.cancelled, self.token = owner, cancelled, token

    def discard(self):
        self.client.release(self.target, self.owner, self.token)


class AiSerialClient:
    def __init__(self, manager):
        self.manager = manager
        self.channel = PipelineChannel(dispatch_timeout=20)
        self.channel.requests = BoundedMailbox(32)
        self.controls = {}
        self.lock = threading.RLock()

    def call(self, code, target, stop=None):
        run = self.channel.new_run()
        if stop is not None:
            run.stop = stop
        try:
            return self.channel.invoke(run, code, (target,))
        except PipelineUiError as exc:
            error_class = {'PermissionError': PermissionError, 'OSError': OSError,
                           'ValueError': ValueError, 'RuntimeError': RuntimeError}.get(exc.error_type)
            if error_class is not None:
                raise error_class(str(exc)) from None
            raise InterruptedError(str(exc)) from None

    def busy(self, target):
        return self.call('busy', target)

    def shared_busy(self, target):
        return self.call('shared_busy', target)

    def target_current(self, target):
        return self.call('target_current', target)

    def acquire(self, target, stop):
        lease = self.call('acquire', target, stop)
        return lease.session, lease.discard, lease.cancelled

    def release(self, target, owner, token):
        self.manager.release(owner, target.port, wait=threading.current_thread() is not threading.main_thread())
        with self.lock:
            current = self.controls.get(target.port.upper())
            if current is not None and current[0] == owner:
                self.controls.pop(target.port.upper(), None)
        if not self.channel.closed.is_set():
            try:
                run = self.channel.new_run()
            except PipelineUiError:
                return
            self.channel.post(run, 'restore', (target, token), cleanup=True)

    def cancel_port(self, port):
        with self.lock:
            item = self.controls.get(port.upper())
        if item:
            item[1].set()
            return True
        return False

    def read(self, target):
        session = self.manager.existing_session(SerialSettings(target.port)) if target.port else None
        if session is None:
            return '目标串口未打开，无实时串口输出；未为被动读取自动打开COM'
        return session.peek_since(max(0, session.cursor() - 65536))

    def serial_status(self, target):
        return self.call('status', target)

    def close(self):
        self.channel.close()
        with self.lock:
            controls = tuple(self.controls.values())
        for _, cancel in controls:
            cancel.set()
