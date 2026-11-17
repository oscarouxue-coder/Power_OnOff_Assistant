"""测试通知代理与独立飞书发送队列；不改变旧钉钉返回值和业务判据。"""
from collections import deque
from pathlib import Path
import queue
import threading
import uuid

from src.core.feishu_client import FeishuApi
from src.services.feishu_output import sanitize
from src.services.message_push_config_service import load_push_project_name


class TestNotificationProxy:
    def __init__(self, original, emit):
        self.original, self.emit = original, emit
        self.local = threading.local()

    def set_channel(self, channel):
        self.local.channel = channel

    def __getattr__(self, name):
        return getattr(self.original, name)

    def webhook_send_message(self, device_type, message, normal_flag=0):
        try:
            # 先交付旁路事件；原钉钉网络失败/阻塞不影响飞书分发。
            self.emit(dict(type="test_notification", id=uuid.uuid4().hex, normal=bool(normal_flag),
                           channel=getattr(self.local, "channel", None)))
        except Exception:
            self.original.log("[飞书通知] 测试结果事件交付失败，原测试及钉钉流程继续")
        return self.original.webhook_send_message(device_type, message, normal_flag)


class FeishuNotificationService:
    def __init__(self, config_store, project_path, emit, *, api_factory=FeishuApi, autostart=True):
        self.config_store, self.project_path, self.emit = config_store, Path(project_path), emit
        self.api_factory = api_factory
        self.queue = queue.Queue(maxsize=128)
        self.lock = threading.RLock()
        self.seen, self.order = set(), deque()
        self.stop = threading.Event()
        self.auto_blocked = threading.Event()
        self.active = False
        self.last_result = "尚未试发"
        self.thread = threading.Thread(target=self._loop, name="feishu-notification", daemon=True)
        if autostart:
            self.thread.start()

    @property
    def busy(self):
        return self.active or not self.queue.empty()

    def enqueue(self, event, *, test=False):
        if self.stop.is_set():
            return False
        try:
            config = self.config_store.load()
            if not test and (self.auto_blocked.is_set() or not config["push_enabled"]):
                self.emit("[飞书通知] 自动推送关闭，跳过发送")
                return False
            if not config["app_id"] or not config["app_secret"] or not config["group"] or not config["corp"]:
                raise ValueError("请先保存飞书凭据并绑定通知群")
            identifier = str(event.get("id") or uuid.uuid4().hex)
            with self.lock:
                if identifier in self.seen:
                    return False
                # 不携带旧通知正文：旧正文可能包含设备命令或远程访问凭据。
                job = dict(id=identifier, channel=event.get("channel"), normal=bool(event.get("normal")),
                           test=test, revision=config["push_revision"], app=config["app_id"], group=config["group"])
                self.queue.put_nowait(job)
                self.seen.add(identifier)
                self.order.append(identifier)
                if len(self.order) > 4096:
                    self.seen.discard(self.order.popleft())
                if test:
                    self.last_result = "正在发送飞书测试消息…"
            self.emit("[飞书通知] 已接收" + ("手动试发" if test else "测试结果") + "，等待独立发送")
            return True
        except Exception:
            self.last_result = "通知未入队，请检查飞书配置、绑定群和队列状态"
            self.emit("[飞书通知] " + self.last_result)
            return False

    def _send(self, job):
        config = self.config_store.load()
        if (self.stop.is_set() or job["revision"] != config["push_revision"]
                or job["app"] != config["app_id"] or job["group"] != config["group"]
                or (not job["test"] and (self.auto_blocked.is_set() or not config["push_enabled"]))):
            self.emit("[飞书通知] 配置已变更或通知关闭，跳过旧队列消息")
            if job["test"]:
                self.last_result = "配置已变更，已取消本次试发"
            return
        project = load_push_project_name(self.project_path)
        header = "项目：" + project
        if type(job["channel"]) is int and 1 <= job["channel"] <= 16:
            header += " | 通道" + str(job["channel"])
        body = header + "\n" + ("DUTPilot 飞书测试消息。" if job["test"] else
                                 ("挂测开关机完成。" if job["normal"] else "挂测开关机出现异常，请查看本地主执行日志。"))
        body = sanitize(body, self.project_path, (config["app_secret"],))
        self.emit("[飞书通知] 下发" + ("测试消息" if job["test"] else "测试结果") +
                  "：POST /open-apis/im/v1/messages（凭据省略）")
        self.api_factory(config["app_id"], config["app_secret"]).send_text(config["group"], body, job["id"])
        if job["test"]:
            self.last_result = "飞书已接受测试消息，请在绑定群核对收到"
        self.emit("[飞书通知] 发送成功（飞书已接受），请在绑定群核对")

    def _loop(self):
        while not self.stop.is_set():
            try:
                job = self.queue.get(timeout=.2)
            except queue.Empty:
                continue
            self.active = True
            try:
                self._send(job)
            except Exception:
                if job["test"]:
                    self.last_result = "飞书试发失败或结果未知，请先在群中核对"
                self.emit("[飞书通知] 发送失败或结果未知；未重试测试操作，原挂测及钉钉流程继续")
            finally:
                self.active = False
                self.queue.task_done()
            self.stop.wait(.35)

    def set_auto_blocked(self, blocked):
        if blocked:
            self.auto_blocked.set()
        else:
            self.auto_blocked.clear()

    def begin_close(self):
        if self.stop.is_set():
            return
        self.stop.set()
        discarded = 0
        while True:
            try:
                self.queue.get_nowait()
                self.queue.task_done()
                discarded += 1
            except queue.Empty:
                break
        self.emit(f"[飞书通知] 程序退出，取消{discarded}条排队通知并等待正在进行的网络请求")

    @property
    def idle(self):
        return not self.thread.is_alive()
