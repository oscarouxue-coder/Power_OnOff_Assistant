"""固定飞书官方域名的应用API；超时有界，凭据和原始响应不进入异常。"""
import json
import re
import threading
import time
import uuid

import requests


def post_payload(chat_id, post, identifier):
    """与实际发送共用序列化，禁止富文本正文意外触发飞书@标签。"""
    content = re.sub(r"<at\b", "[at", json.dumps(post, ensure_ascii=False), flags=re.I)
    return dict(receive_id=chat_id, msg_type="post", content=content, uuid=identifier)


class FeishuApi:
    def __init__(self, app_id, app_secret, *, requester=requests.request, clock=time.monotonic):
        self.app_id, self.app_secret = app_id, app_secret
        self.requester, self.clock = requester, clock
        self.lock = threading.RLock()
        self._token, self._expires = "", 0

    def _request(self, method, path, payload=None, *, token=""):
        try:
            response = self.requester(method, "https://open.feishu.cn" + path,
                                      json=payload, headers={"Authorization": "Bearer " + token} if token else {},
                                      timeout=10, allow_redirects=False)
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError
            result = response.json()
            if not isinstance(result, dict) or type(result.get("code")) is not int:
                raise ValueError
        except Exception:
            raise RuntimeError("飞书HTTPS请求失败或响应无效，结果待核实（凭据省略）") from None
        if result["code"] != 0:
            raise RuntimeError("飞书接口未接受请求，错误码：" + str(result["code"]))
        return result

    def token(self):
        with self.lock:
            if self._token and self.clock() < self._expires:
                return self._token
            result = self._request("POST", "/open-apis/auth/v3/tenant_access_token/internal",
                                   {"app_id": self.app_id, "app_secret": self.app_secret})
            token, expire = result.get("tenant_access_token"), result.get("expire")
            if not isinstance(token, str) or not token or type(expire) is not int or expire <= 60:
                raise RuntimeError("飞书应用令牌响应无效（凭据省略）")
            self._token, self._expires = token, self.clock() + expire - 60
            return token

    def bot_id(self):
        result = self._authorized("GET", "/open-apis/bot/v3/info")
        bot = result.get("bot", {}).get("open_id")
        if not isinstance(bot, str) or not bot:
            raise RuntimeError("飞书机器人身份不可用，请检查应用机器人能力及发布状态")
        return bot

    def endpoint(self):
        result = self._request("POST", "/callback/ws/endpoint", {"AppID": self.app_id, "AppSecret": self.app_secret})
        return result.get("data", {})

    def _authorized(self, method, path, payload=None):
        try:
            return self._request(method, path, payload, token=self.token())
        except RuntimeError:
            # 当前请求不重发；后续独立请求刷新令牌，避免失效令牌长期卡住接入。
            with self.lock:
                self._token, self._expires = "", 0
            raise

    def send_text(self, chat_id, text, identifier=None):
        # 禁止AI输出意外形成@全员或@他人的飞书标签。
        text = text.replace("<at ", "[at ")
        import json
        payload = dict(receive_id=chat_id, msg_type="text", content=json.dumps({"text": text}, ensure_ascii=False),
                       uuid=identifier or uuid.uuid4().hex)
        return self._authorized("POST", "/open-apis/im/v1/messages?receive_id_type=chat_id", payload)

    def send_post(self, chat_id, post, identifier=None):
        payload = post_payload(chat_id, post, identifier or uuid.uuid4().hex)
        # requests的json参数采用ASCII转义；检查真实请求大小而非仅检查正文。
        if len(json.dumps(payload, ensure_ascii=True).encode("utf-8")) > 30000:
            raise ValueError("飞书富文本回复过长，正文保留本地")
        return self._authorized("POST", "/open-apis/im/v1/messages?receive_id_type=chat_id", payload)
