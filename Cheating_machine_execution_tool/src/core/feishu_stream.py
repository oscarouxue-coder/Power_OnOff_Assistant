"""锁定SDK的线程适配层；控制事件循环、超时、重连和退出，不接触Tk。"""
import asyncio
import importlib
import importlib.util
import json
import threading
from urllib.parse import urlsplit

from src.core.feishu_client import FeishuApi
from src.core.dingtalk_stream import InstanceLease
from src.models.dependency_repair import MissingFeishuSdkError


class FeishuInstanceLease(InstanceLease):
    """保留既有项目互斥命名，飞书应用另加命名空间。"""
    def acquire(self):
        try:
            super().acquire()
        except RuntimeError as exc:
            raise RuntimeError(str(exc).replace("钉钉", "飞书")) from None


class FeishuStream:
    def __init__(self, app_id, app_secret, receive, status, *, api=None, sdk_loader=None):
        self.app_id, self.app_secret = app_id, app_secret
        self.receive, self.status = receive, status
        self.api = api or FeishuApi(app_id, app_secret)
        self.custom_sdk = sdk_loader is not None
        self.sdk_loader = sdk_loader or (lambda: importlib.import_module("lark_oapi.ws.client"))
        self.stop = threading.Event()
        self.thread = None
        self.loop = None
        self.client = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        if self.stop.is_set():
            raise ValueError("飞书连接正在退出")
        if not self.custom_sdk and importlib.util.find_spec("lark_oapi") is None:
            raise MissingFeishuSdkError()
        self.thread = threading.Thread(target=self._run, name="feishu-stream", daemon=True)
        self.thread.start()

    def _endpoint(self, client, sdk):
        data = self.api.endpoint()
        try:
            parts = urlsplit(data["URL"])
            if (parts.scheme != "wss" or not parts.hostname or not parts.hostname.endswith(".feishu.cn")
                    or parts.port not in (None, 443) or parts.username or parts.password or parts.fragment):
                raise ValueError
            if data.get("ClientConfig") is not None:
                client._configure(sdk.JSON.unmarshal(json.dumps(data["ClientConfig"]), sdk.ClientConfig))
            return data["URL"]
        except Exception:
            raise RuntimeError("飞书长连接地址或配置无效（凭据省略）") from None

    def _run(self):
        # SDK 1.7.5自身使用模块级loop；项目内仅此适配层使用SDK长连接。
        # 首次导入、循环创建及所有SDK任务均限制在同一后台线程。
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.set_exception_handler(lambda _loop, _context: None)
        try:
            sdk = self.sdk_loader()
            import lark_oapi as lark
            from lark_oapi.core.const import VERSION
            if VERSION != "1.7.5":
                raise RuntimeError("飞书SDK版本不匹配，请安装requirements固定依赖")
            sdk.loop = self.loop
            # SDK日志包含带票据的连接URL及消息正文，不转发到控制台/主日志。
            sdk.logger.disabled = True

            def callback(event):
                if not self.stop.is_set():
                    try:
                        self.receive(json.loads(lark.JSON.marshal(event)), self.bot_id)
                    except ValueError:
                        return  # 不支持/不属于本应用的事件确认后忽略。
                    # 持久化失败抛给SDK返回失败响应，允许飞书重投。

            handler = lark.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(callback).build()
            outer = self

            class BoundedClient(sdk.Client):
                def _get_conn_url(self):
                    return outer._endpoint(self, sdk)

            self.loop.run_until_complete(self._serve(BoundedClient, handler, lark))
        except Exception:
            self.status("飞书连接未启动，请检查固定依赖、应用凭据及发布状态（凭据省略）")
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.close()
            self.status("飞书连接已停止")

    async def _serve(self, client_type, handler, lark):
        while not self.stop.is_set():
            self.client = None
            try:
                self.status("正在连接飞书（HTTPS注册 / WSS）")
                self.bot_id = self.api.bot_id()
                if self.stop.is_set():
                    break
                self.client = client_type(self.app_id, self.app_secret, event_handler=handler,
                                          auto_reconnect=False, log_level=lark.LogLevel.ERROR)
                await self.client._connect()
                self.loop.create_task(self.client._ping_loop())
                self.status("飞书长连接已连接")
                while not self.stop.is_set() and self.client._conn is not None:
                    await asyncio.sleep(.1)
                if not self.stop.is_set():
                    self.status("飞书连接已断开，稍后重连（凭据省略）")
            except Exception:
                self.status("飞书连接失败或断开，稍后重连（凭据省略）")
            finally:
                if self.client is not None:
                    try:
                        await asyncio.wait_for(self.client._disconnect(), 3)
                    except Exception:
                        pass
                current = asyncio.current_task()
                pending = [task for task in asyncio.all_tasks() if task is not current]
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
            for _ in range(20):
                if self.stop.is_set():
                    break
                await asyncio.sleep(.1)

    def begin_close(self):
        self.stop.set()

    @property
    def idle(self):
        return self.thread is None or not self.thread.is_alive()
