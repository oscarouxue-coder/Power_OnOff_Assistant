"""Marshal original pipeline serial prestart onto the workspace owner thread."""
from concurrent.futures import Future, TimeoutError
from queue import Empty, Queue
import time

from src.models.upgrade_stop import UpgradeStopped


class PipelineSerialPrestart:
    def __init__(self):
        self.requests = Queue()
        self.last_run = ''

    def request(self, context, channels, directory):
        response = Future()
        self.requests.put((response, context, tuple(channels), directory))
        deadline = time.monotonic() + 30
        while True:
            if context.stop.is_set() and response.cancel():
                raise UpgradeStopped('串口预启动在领取前已停止')
            if time.monotonic() >= deadline and response.cancel():
                raise RuntimeError('串口预启动领取超时')
            try:
                return response.result(timeout=.05)
            except TimeoutError:
                if response.done():
                    return response.result()

    def drain(self, terminal):
        while True:
            try:
                response, context, channels, directory = self.requests.get_nowait()
            except Empty:
                return
            if not response.set_running_or_notify_cancel():
                continue
            try:
                context.stop.checkpoint()
                failures = terminal.open_pipeline(channels, directory)
                self.last_run = context.job_id
                if failures:
                    raise RuntimeError('部分串口未能打开：' + '、'.join(failures))
            except Exception as error:
                response.set_exception(error)
            else:
                response.set_result(None)
