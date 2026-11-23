"""Forward existing Qt power-test notification events without affecting verdicts."""
from threading import RLock

from src.services.feishu_notifications import FeishuNotificationService


class QtFeishuNotifications:
    def __init__(self, execution):
        self.execution = execution
        self.lock = RLock()
        self.service = None
        self.closing = False
        self.auto_blocked = False

    def observe(self, message):
        if message.get('type') != 'test_notification':
            return
        with self.lock:
            if self.closing or self.auto_blocked:
                return
            e = self.execution
            try:
                if self.service is None:
                    store = e.workspace.platform_config('feishu')
                    if not store.load()['push_enabled']:
                        return
                    config = e.context.saved_root / 'Auto_power_on_off_tool/config/test_project_config.ini'
                    self.service = FeishuNotificationService(store, config, e._log)
                self.service.enqueue(message)
            except Exception:
                e._log('[飞书通知] 无法交付测试结果事件，原测试继续', 'WARN')

    def set_auto_blocked(self, blocked):
        with self.lock:
            self.auto_blocked = blocked
            if self.service is not None:
                self.service.set_auto_blocked(blocked)

    @property
    def busy(self):
        with self.lock:
            return self.service is not None and bool(self.service.queue.unfinished_tasks
                or (self.closing and not self.service.idle))

    def begin_close(self):
        with self.lock:
            self.closing = True
            if self.service is not None:
                self.service.begin_close()

    def finish(self):
        self.begin_close()
        if self.service is not None:
            self.service.thread.join()
