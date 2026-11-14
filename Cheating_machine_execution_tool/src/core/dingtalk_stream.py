"""钉钉Stream小型协议适配；只负责传输，不执行AI或设备操作。

协议：https://open-dingtalk.github.io/developerpedia/docs/learn/stream/protocol/
"""
import ctypes
import hashlib
import json
import logging
import os
import threading
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener

from src.core.dingtalk_robot import _NoRedirect
from src.models.dingtalk_remote import BOT_TOPIC


def post_json(url, payload):
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=10) as response:
            raw = response.read(1024 * 1024 + 1)
            if response.status != 200 or len(raw) > 1024 * 1024:
                raise ValueError()
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except Exception:
        raise RuntimeError("钉钉HTTPS请求失败或响应无效，结果待核实（凭据省略）") from None


def valid_session_url(url):
    try:
        parts = urlsplit(url)
        return (parts.scheme == "https" and parts.hostname == "oapi.dingtalk.com"
                and parts.port in (None, 443) and parts.path == "/robot/sendBySession"
                and not parts.username and not parts.password and not parts.fragment and bool(parts.query))
    except ValueError:
        return False


def send_session_text(url, text):
    if not valid_session_url(url):
        raise ValueError("会话回复地址无效")
    result = post_json(url, {"msgtype": "text", "text": {"content": text}})
    if type(result.get("errcode")) is not int or result["errcode"] != 0:
        raise RuntimeError("钉钉未接受回复，请检查群消息和应用配置")


class InstanceLease:
    """同机防止重复项目或凭据建立多个Stream连接；进程退出由Windows释放。"""
    def __init__(self, *identities):
        self.identities, self.handles = identities, []

    def acquire(self):
        if os.name != "nt":
            raise RuntimeError("钉钉项目接入需要Windows")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        try:
            for identity in sorted(set(self.identities)):
                name = "Local\\LineCheckDingTalk_" + hashlib.sha256(identity.encode()).hexdigest()
                ctypes.set_last_error(0)
                handle = kernel.CreateMutexW(None, False, name)
                if not handle:
                    raise RuntimeError("无法建立钉钉实例保护")
                self.handles.append(handle)
                if ctypes.get_last_error() == 183:
                    raise RuntimeError("当前项目目录或应用凭据已由另一进程接入，请勿重复启动")
        except Exception:
            self.close()
            raise

    def close(self):
        if self.handles:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle.restype = ctypes.c_int
            for handle in self.handles:
                kernel.CloseHandle(handle)
            self.handles.clear()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class DingTalkStream:
    def __init__(self, client_id, client_secret, receive, status, *, opener=post_json, connector=None):
        self.client_id, self.client_secret = client_id, client_secret
        self.receive, self.status = receive, status
        self.opener, self.connector = opener, connector
        self.stop = threading.Event()
        self.thread = None
        self.socket = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        # 在调用线程报告缺依赖，避免后台无限重试。
        if self.connector is None:
            try:
                from websockets.sync.client import connect
            except ImportError:
                raise RuntimeError("缺少websockets依赖，请按项目requirements安装后重启") from None
            self.connector = connect
        self.thread = threading.Thread(target=self._run, name="dingtalk-stream", daemon=True)
        self.thread.start()

    def frame(self, frame):
        headers = frame.get("headers", {})
        identifier = headers.get("messageId", "")
        topic, kind = headers.get("topic"), frame.get("type")
        data = frame.get("data", "{}")
        data = json.loads(data) if isinstance(data, str) else data
        code, response = 200, {"response": None}
        if kind == "SYSTEM":
            response = data  # ping原样返回opaque；disconnect确认后重连。
        elif kind == "CALLBACK" and topic == BOT_TOPIC:
            try:
                self.receive(data)
            except (ValueError, TypeError, KeyError):
                pass  # 非支持消息/不可信身份，不执行且不要求平台重复推送。
            except Exception:
                code = 500  # 未持久化则允许平台重投。
                self.status("收件失败，等待平台重投")
        else:
            code = 404
        return {"code": code, "message": "OK" if code == 200 else "unavailable",
                "headers": {"messageId": identifier, "contentType": "application/json"},
                "data": json.dumps(response)}, kind == "SYSTEM" and topic == "disconnect"

    def _run(self):
        delay = 1
        logger = logging.getLogger("linecheck.dingtalk.websocket")
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
        try:
            while not self.stop.is_set():
                try:
                    self.status("正在连接")
                    connection = self.opener("https://api.dingtalk.com/v1.0/gateway/connections/open", {
                        "clientId": self.client_id, "clientSecret": self.client_secret,
                        "subscriptions": [{"type": "CALLBACK", "topic": BOT_TOPIC}],
                        "ua": "LineCheckAssistant/Python3.9"})
                    endpoint, ticket = connection.get("endpoint", ""), connection.get("ticket", "")
                    parts = urlsplit(endpoint)
                    if (parts.scheme != "wss" or not parts.hostname or not parts.hostname.endswith(".dingtalk.com")
                            or parts.port not in (None, 443) or parts.username or parts.password
                            or parts.query or parts.fragment or not isinstance(ticket, str) or not ticket):
                        raise ValueError("连接凭据无效")
                    if self.stop.is_set():
                        break
                    with self.connector(endpoint + "?" + urlencode({"ticket": ticket}),
                                        open_timeout=10, close_timeout=3, max_size=1024 * 1024,
                                        ping_interval=20, ping_timeout=20, proxy=None, logger=logger) as sock:
                        self.socket = sock
                        self.status("已连接")
                        delay = 1
                        while not self.stop.is_set():
                            try:
                                raw = sock.recv(timeout=1)
                            except TimeoutError:
                                continue
                            reply, disconnect = self.frame(json.loads(raw))
                            sock.send(json.dumps(reply))
                            if disconnect:
                                break
                except Exception:
                    if not self.stop.is_set():
                        self.status("连接中断或鉴权失败，等待重连（凭据省略）")
                finally:
                    self.socket = None
                if self.stop.wait(delay):
                    break
                delay = min(60, delay * 2)
        finally:
            self.status("已停止")

    def begin_close(self):
        # 接收最多1秒/HTTPS最多10秒后返回，Tk主线程不执行socket.close等待。
        self.stop.set()

    @property
    def idle(self):
        return self.thread is None or not self.thread.is_alive()
