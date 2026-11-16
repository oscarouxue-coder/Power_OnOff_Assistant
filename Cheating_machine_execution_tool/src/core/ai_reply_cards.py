"""官方卡片HTTPS适配；无模型/设备操作，禁止重定向和未知结果自动重发。"""
import json
import time
import uuid

import requests


class CardRejected(RuntimeError):
    """平台明确拒绝，可降级普通回复。"""


class CardUnavailable(CardRejected):
    """尚未投递，配置或创建实体不可用。"""


class CardStopped(RuntimeError):
    pass


class FeishuReplyCard:
    def __init__(self, api, guard, emit):
        self.api, self.guard, self.emit = api, guard, emit

    def request(self, method, path, payload):
        if not self.guard():
            raise CardStopped()
        self.emit("下发流式卡片：" + method + " " + path + "（凭据省略）")
        return self.api._authorized(method, path, payload)

    def create(self, message, title, text, identifier):
        card = {"schema": "2.0", "config": {"streaming_mode": True, "update_multi": True},
                "header": {"title": {"tag": "plain_text", "content": title}},
                "body": {"elements": [{"tag": "markdown", "element_id": "reply", "content": text or "正在生成…"}]}}
        try:
            result = self.request("POST", "/open-apis/cardkit/v1/cards",
                                  {"type": "card_json", "data": json.dumps(card, ensure_ascii=False)})
            card_id = result["data"]["card_id"]
            if not isinstance(card_id, str) or not card_id:
                raise ValueError()
        except CardStopped:
            raise
        except Exception:
            # 实体尚未投放到聊天，不会造成重复消息。
            raise CardUnavailable("飞书卡片实体不可用，请核对cardkit:card:write权限") from None
        payload = {"receive_id": message.group, "msg_type": "interactive", "uuid": identifier[:32],
                   "content": json.dumps({"type": "card", "data": {"card_id": card_id}})}
        result = self.request("POST", "/open-apis/im/v1/messages?receive_id_type=chat_id", payload)
        message_id = result.get("data", {}).get("message_id")
        if not isinstance(message_id, str) or not message_id:
            raise RuntimeError("飞书卡片投递结果未知")
        return {"card_id": card_id, "message_id": message_id, "sequence": 0}

    def update(self, handle, text, final, failed=False):
        path = "/open-apis/cardkit/v1/cards/" + handle["card_id"]
        handle["sequence"] += 1
        self.request("PUT", path + "/elements/reply/content",
                     {"content": text or "（无正文）", "sequence": handle["sequence"], "uuid": uuid.uuid4().hex})
        if final:
            handle["final_text_accepted"] = True
            self.close(handle, text, failed)

    def close(self, handle, text, failed=False):
        handle["sequence"] += 1
        self.request("PATCH", "/open-apis/cardkit/v1/cards/" + handle["card_id"] + "/settings",
                     {"settings": json.dumps({"streaming_mode": False}),
                      "sequence": handle["sequence"], "uuid": uuid.uuid4().hex})


class DingTalkReplyCard:
    def __init__(self, config, guard, emit, token_cache, requester=requests.request, clock=time.monotonic):
        self.config, self.guard, self.emit = config, guard, emit
        self.cache, self.requester, self.clock = token_cache, requester, clock

    def request(self, method, path, payload, token=""):
        if not self.guard():
            raise CardStopped()
        self.emit("下发流式卡片：" + method + " " + path + "（凭据省略）")
        response = None
        try:
            response = self.requester(method, "https://api.dingtalk.com" + path, json=payload,
                headers={"x-acs-dingtalk-access-token": token} if token else {},
                timeout=10, allow_redirects=False)
            status = response.status_code
            if status in (400, 401, 403, 404, 429):
                raise CardRejected("钉钉卡片接口明确拒绝（HTTP " + str(status) + "）")
            if not 200 <= status < 300:
                raise RuntimeError()
            result = response.json()
            if not isinstance(result, dict):
                raise RuntimeError()
            if result.get("success") is False or result.get("errcode", 0) != 0 or result.get("code") not in (None, 0, "0", "OK", "Success"):
                raise CardRejected("钉钉卡片接口明确拒绝，请核对模板、权限及额度")
            return result
        except (CardRejected, CardStopped):
            raise
        except Exception:
            raise RuntimeError("钉钉卡片请求结果未知（凭据省略）") from None
        finally:
            if response is not None:
                response.close()

    def token(self):
        identity = (self.config["client_id"], self.config["client_secret"])
        if self.cache.get("identity") == identity and self.clock() < self.cache.get("expires", 0):
            return self.cache["token"]
        try:
            result = self.request("POST", "/v1.0/oauth2/accessToken",
                                  {"appKey": identity[0], "appSecret": identity[1]})
            token, expires = result["accessToken"], result["expireIn"]
            if not isinstance(token, str) or not token or type(expires) is not int or expires <= 60:
                raise ValueError()
        except CardStopped:
            raise
        except Exception:
            raise CardUnavailable("钉钉卡片令牌不可用") from None
        self.cache.update(identity=identity, token=token, expires=self.clock() + expires - 60)
        return token

    def create(self, message, title, text, identifier):
        template = self.config.get("ai_card_template_id", "")
        if not template:
            raise CardUnavailable("钉钉未配置AI卡片模板，使用完整回复")
        return_value = {"outTrackId": identifier, "title": title}
        self.request("POST", "/v1.0/card/instances/createAndDeliver",
            {"cardTemplateId": template, "outTrackId": identifier, "callbackType": "STREAM",
             "cardData": {"cardParamMap": {"flowStatus": "2", "msgContent": text or "正在生成…", "title": title}},
             "openSpaceId": "dtv1.card//IM_GROUP." + message.group,
             "imGroupOpenSpaceModel": {"supportForward": False},
             "imGroupOpenDeliverModel": {"robotCode": self.config["robot_code"]}}, self.token())
        return return_value

    def update(self, handle, text, final, failed=False):
        self.request("PUT", "/v1.0/card/streaming",
            {"outTrackId": handle["outTrackId"], "guid": uuid.uuid4().hex, "key": "msgContent",
             "content": text or "（无正文）", "isFull": True, "isFinalize": final, "isError": failed}, self.token())
        if final:
            handle["final_text_accepted"] = True
            self.close(handle, text, failed)

    def close(self, handle, text, failed=False):
        self.request("PUT", "/v1.0/card/instances", {"outTrackId": handle["outTrackId"],
            "cardData": {"cardParamMap": {"flowStatus": "5" if failed else "3", "msgContent": text}},
            "cardUpdateOptions": {"updateCardDataByKey": True}}, self.token())
